"""
git for the item libraries (design note doc/source/design_items.rst, section
"Storage and exchange"): status and commit of the files of the libraries,
later pull, push and bundles.

Two backends with the same interface:

* :class:`CliBackend`: the git program, if it is installed (uses its
  configuration and credentials);
* :class:`DulwichBackend`: dulwich, pure Python, always available (a
  dependency of redvypr), so ``pip install redvypr`` works without git.

:func:`backend_for` chooses (environment variable ``REDVYPR_GIT``: ``cli``
or ``dulwich`` forces one). Both work on normal git repositories, so the
terminal can be used alongside.

Only the files of the libraries are staged and committed (``paths``); a
commit is refused if other changes are staged already (they would go into
the commit).

Pull and push (:meth:`GitBackend.pull`, :meth:`GitBackend.push`) work with
the remote of the current branch (default ``origin``). A pull needs a clean
working tree (commit first); it fast-forwards, or merges if both sides have
new commits; a conflict stops it with the files named and leaves the
repository as before. A push is refused if the remote has new commits (pull
first). Credentials: the git program uses its own; with dulwich an HTTPS
remote takes a user name and a personal access token, kept in the system
key store (keyring, service ``redvypr-git:<host>``) and asked for with a
callback when missing or rejected.

Bundles for computers without network (:meth:`GitBackend.create_bundle`,
:meth:`GitBackend.import_bundle`, :func:`clone_bundle`): a bundle is one file
with the commits of the branch; next to it ``<bundle>.txt`` names the server,
branch and commit, so a computer made from the bundle can later push to the
server. Importing a bundle works like a pull (fast-forward, merge, a conflict
stops it without changes). Bundles of the git program and of dulwich are the
same format.
"""

import datetime

import dataclasses
import io
import logging
import os
import shutil
import subprocess
import typing
import urllib.parse

logger = logging.getLogger('redvypr.item_git')


class GitError(Exception):
    pass


@dataclasses.dataclass
class FileChange:
    """A changed file of a repository; path relative to the repository root, with '/'."""
    path: str
    state: str          # 'modified', 'added', 'deleted', 'untracked'
    staged: bool = False


def find_repo(path) -> typing.Optional[str]:
    """Root of the git repository containing path (file or directory), None if none."""
    p = os.path.abspath(str(path))
    if not os.path.isdir(p):
        p = os.path.dirname(p)
    while True:
        if os.path.exists(os.path.join(p, '.git')):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def _rel(root: str, path) -> str:
    return os.path.relpath(os.path.abspath(str(path)), root).replace(os.sep, '/')


def _under(rel_path: str, prefixes) -> bool:
    """True if a relative path is one of prefixes or below one of them ('.' : the whole repository)."""
    for p in prefixes:
        if p in ('.', '') or rel_path == p or rel_path.startswith(p.rstrip('/') + '/'):
            return True
    return False


@dataclasses.dataclass
class SyncResult:
    """Result of a pull or push."""
    action: str                 # 'up to date', 'fast-forward', 'merged', 'pushed', 'nothing to push'
    before: typing.Optional[str] = None
    after: typing.Optional[str] = None
    ahead: int = 0              # local commits not on the remote (before)
    behind: int = 0             # remote commits not here (before)

    @property
    def changed(self) -> bool:
        return self.action in ('fast-forward', 'merged')


# --- credentials (dulwich, HTTPS) ---------------------------------------------------------------

KEYRING_PREFIX = 'redvypr-git:'


def _host(url: str) -> str:
    return urllib.parse.urlparse(url).hostname or url


def get_credentials(url: str) -> typing.Optional[typing.Tuple[str, str]]:
    """(user, token) stored for the host of a remote URL, None if none."""
    try:
        import keyring
        cred = keyring.get_credential(KEYRING_PREFIX + _host(url), None)
    except Exception:
        logger.debug('no credentials from keyring', exc_info=True)
        return None
    return (cred.username, cred.password) if cred is not None else None


def store_credentials(url: str, user: str, token: str):
    import keyring
    keyring.set_password(KEYRING_PREFIX + _host(url), user, token)


def delete_credentials(url: str):
    import keyring
    cred = get_credentials(url)
    if cred is not None:
        try:
            keyring.delete_password(KEYRING_PREFIX + _host(url), cred[0])
        except Exception:
            logger.debug('could not delete the credentials', exc_info=True)


class GitBackend:
    """Status and commit of the files below some paths of one repository."""
    name = 'base'

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    # --- to implement ---
    def _all_changes(self) -> typing.List[FileChange]:
        raise NotImplementedError

    def _stage(self, changes: typing.List[FileChange]):
        raise NotImplementedError

    def _commit_index(self, message: str) -> str:
        raise NotImplementedError

    def branch(self) -> str:
        raise NotImplementedError

    def head(self) -> typing.Optional[str]:
        raise NotImplementedError

    def remote_name(self) -> str:
        raise NotImplementedError

    def remote_url(self) -> typing.Optional[str]:
        raise NotImplementedError

    def _fetch(self, ask_credentials=None):
        raise NotImplementedError

    def _ahead_behind(self, target=None) -> typing.Tuple[int, int]:
        """(ahead, behind) of HEAD against target (default: the remote branch)."""
        raise NotImplementedError

    def _merge_remote(self, fast_forward: bool, target=None) -> str:
        raise NotImplementedError

    def _create_bundle(self, path: str):
        raise NotImplementedError

    def _fetch_bundle(self, path: str, src: str, target: str):
        """Objects of a bundle into the repository, its branch src as ref target (refs/remotes/bundle/...)."""
        raise NotImplementedError

    def bundle_heads(self, path: str) -> typing.Dict[str, str]:
        """{ref: commit} of the branches in a bundle."""
        from dulwich import bundle as dbundle
        with open(path, 'rb') as f:
            b = dbundle.read_bundle(f)
            try:
                return {k.decode(): v.decode() for k, v in b.references.items()}
            finally:
                b.close()

    def _push(self, ask_credentials=None):
        raise NotImplementedError

    # --- common ---
    def _require_clean(self):
        dirty = [c.path for c in self._all_changes() if c.state != 'untracked']
        if dirty:
            raise GitError('uncommitted changes, commit first: ' + ', '.join(dirty[:5]) +
                           (' ...' if len(dirty) > 5 else ''))

    def ahead_behind(self, fetch: bool = True, ask_credentials=None) -> typing.Tuple[int, int]:
        """(local commits not on the remote, remote commits not here), after a fetch."""
        if fetch:
            self._fetch(ask_credentials)
        return self._ahead_behind()

    def pull(self, ask_credentials=None) -> SyncResult:
        """
        Fetches and brings in the new commits of the remote (fast-forward, or a merge if both
        sides have new commits). Needs a clean working tree; a conflict stops it, the
        repository stays as before.
        """
        self._require_clean()
        self._fetch(ask_credentials)
        ahead, behind = self._ahead_behind()
        before = self.head()
        if behind == 0:
            return SyncResult('up to date', before, before, ahead, behind)
        action = self._merge_remote(fast_forward=(ahead == 0))
        return SyncResult(action, before, self.head(), ahead, behind)

    def create_bundle(self, path: str, libraries=None) -> str:
        """
        Writes the current branch with all its commits into a bundle file, and next to it
        <path>.txt with server, branch, commit and date, and the libraries (paths relative to
        the repository, in the order they were loaded: new items go into the first library of
        their kind, so the other computer loads them in the same order). Returns the path.
        """
        path = os.path.abspath(path)
        if self.head() is None:
            raise GitError('the repository has no commits')
        self._create_bundle(path)
        info = {'server': self.remote_url() or '', 'branch': self.branch(), 'commit': self.head(),
                'created': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
                'repository': os.path.basename(self.root)}
        if libraries:
            info['libraries'] = ', '.join(_rel(self.root, p) for p in libraries)
        with open(path + '.txt', 'w', encoding='utf-8', newline='\n') as f:
            f.write('# redvypr item libraries: git bundle (see redvypr.item_git)\n')
            for k, v in info.items():
                f.write(f'{k}: {v}\n')
        return path

    def import_bundle(self, path: str) -> SyncResult:
        """
        Brings in the commits of a bundle like a pull: fast-forward, or a merge if both sides
        have new commits; needs a clean working tree; a conflict stops it without changes.
        """
        self._require_clean()
        heads = self.bundle_heads(path)
        want = f'refs/heads/{self.branch()}'
        src = want if want in heads else next((h for h in heads if h.startswith('refs/heads/')), None)
        if src is None:
            raise GitError(f'{os.path.basename(path)} has no branch')
        target = f'refs/remotes/bundle/{src.split("/", 2)[2]}'
        self._fetch_bundle(os.path.abspath(path), src, target)
        ahead, behind = self._ahead_behind(target)
        before = self.head()
        if behind == 0:
            return SyncResult('up to date', before, before, ahead, behind)
        action = self._merge_remote(fast_forward=(ahead == 0), target=target)
        return SyncResult(action, before, self.head(), ahead, behind)

    def push(self, ask_credentials=None) -> SyncResult:
        """Pushes the local commits; refused if the remote has new commits (pull first)."""
        self._fetch(ask_credentials)
        ahead, behind = self._ahead_behind()
        head = self.head()
        if behind:
            raise GitError(f'the remote has {behind} new commit(s): pull first')
        if ahead == 0:
            return SyncResult('nothing to push', head, head, ahead, behind)
        self._push(ask_credentials)
        return SyncResult('pushed', head, head, ahead, behind)

    def status(self, paths=None) -> typing.List[FileChange]:
        """The changes below paths (files or directories; default: the whole repository)."""
        prefixes = ['.'] if not paths else [_rel(self.root, p) for p in paths]
        return sorted((c for c in self._all_changes() if _under(c.path, prefixes)), key=lambda c: c.path)

    def commit(self, paths, message: str) -> typing.Optional[str]:
        """
        Stages the changes below paths and commits them with message; returns the commit id
        (None if there is nothing to commit). Refused if changes outside paths are staged.
        """
        if not message or not message.strip():
            raise GitError('a commit needs a message')
        prefixes = [_rel(self.root, p) for p in paths]
        everything = self._all_changes()
        foreign = [c.path for c in everything if c.staged and not _under(c.path, prefixes)]
        if foreign:
            raise GitError('other changes are staged already (they would be committed as well): '
                           + ', '.join(foreign[:5]) + (' ...' if len(foreign) > 5 else ''))
        mine = [c for c in everything if _under(c.path, prefixes)]
        if not mine:
            return None
        self._stage(mine)
        return self._commit_index(message.strip())


class CliBackend(GitBackend):
    """The git program."""
    name = 'git'

    def _git(self, *args, check=True) -> str:
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0')     # no hanging prompt in the terminal
        res = subprocess.run(['git', '-C', self.root, *args], capture_output=True, text=True,
                             encoding='utf-8', errors='replace', env=env)
        if check and res.returncode != 0:
            raise GitError(f'git {" ".join(args[:2])}: {res.stderr.strip() or res.stdout.strip()}')
        return res.stdout

    def _all_changes(self):
        out = self._git('status', '--porcelain=v1', '-z', '--untracked-files=all')
        changes = []
        parts = out.split('\0')
        i = 0
        while i < len(parts):
            entry = parts[i]
            i += 1
            if len(entry) < 4:
                continue
            x, y, path = entry[0], entry[1], entry[3:]
            if x in 'RC':
                i += 1          # the original path of a rename follows
            if x == '?' and y == '?':
                changes.append(FileChange(path, 'untracked'))
                continue
            code = x if x != ' ' else y
            state = {'M': 'modified', 'A': 'added', 'D': 'deleted', 'R': 'added', 'C': 'added',
                     'T': 'modified'}.get(code, 'modified')
            changes.append(FileChange(path, state, staged=x not in (' ', '?')))
        return changes

    def _stage(self, changes):
        paths = [c.path for c in changes]
        for k in range(0, len(paths), 200):
            self._git('add', '-A', '--', *paths[k:k + 200])

    def _commit_index(self, message):
        self._git('commit', '-q', '-m', message)
        return self.head()

    def branch(self):
        return self._git('rev-parse', '--abbrev-ref', 'HEAD', check=False).strip()

    def head(self):
        out = self._git('rev-parse', 'HEAD', check=False).strip()
        return out or None

    def remote_name(self):
        name = self._git('config', f'branch.{self.branch()}.remote', check=False).strip()
        return name or 'origin'

    def remote_url(self):
        return self._git('config', f'remote.{self.remote_name()}.url', check=False).strip() or None

    def _upstream(self):
        return f'{self.remote_name()}/{self.branch()}'

    def _fetch(self, ask_credentials=None):
        if not self.remote_url():
            raise GitError(f'no remote {self.remote_name()} configured')
        self._git('fetch', '--quiet', self.remote_name())

    def _ahead_behind(self, target=None):
        target = target or self._upstream()
        out = self._git('rev-list', '--left-right', '--count', f'HEAD...{target}', check=False).split()
        return (int(out[0]), int(out[1])) if len(out) == 2 else (0, 0)

    def _merge_remote(self, fast_forward, target=None):
        target = target or self._upstream()
        if fast_forward:
            self._git('merge', '--ff-only', '--quiet', target)
            return 'fast-forward'
        env_res = subprocess.run(['git', '-C', self.root, 'merge', '--no-edit', '--quiet', target],
                                 capture_output=True, text=True, encoding='utf-8', errors='replace',
                                 env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))
        if env_res.returncode != 0:
            conflicts = self._git('diff', '--name-only', '--diff-filter=U', check=False).split()
            self._git('merge', '--abort', check=False)
            raise GitError('merge conflict, nothing changed; resolve with git: ' +
                           (', '.join(conflicts) or env_res.stderr.strip() or env_res.stdout.strip()))
        return 'merged'

    def _push(self, ask_credentials=None):
        b = self.branch()
        self._git('push', '--quiet', self.remote_name(), f'HEAD:refs/heads/{b}')

    def _create_bundle(self, path):
        self._git('bundle', 'create', '--quiet', path, f'refs/heads/{self.branch()}')

    def _fetch_bundle(self, path, src, target):
        self._git('fetch', '--quiet', path, f'+{src}:{target}')


class DulwichBackend(GitBackend):
    """dulwich (pure Python)."""
    name = 'dulwich'

    def __init__(self, root):
        super().__init__(root)
        from dulwich.repo import Repo
        self.repo = Repo(self.root)

    @staticmethod
    def _p(p) -> str:
        p = p.decode('utf-8') if isinstance(p, bytes) else str(p)
        return p.replace('\\', '/')

    def _all_changes(self):
        from dulwich import porcelain
        st = porcelain.status(self.repo, untracked_files='all')
        changes = []
        for kind, state in (('add', 'added'), ('delete', 'deleted'), ('modify', 'modified')):
            for p in st.staged.get(kind, []):
                changes.append(FileChange(self._p(p), state, staged=True))
        staged = {c.path for c in changes}
        for p in st.unstaged:
            path = self._p(p)
            if path in staged:
                continue
            state = 'modified' if os.path.exists(os.path.join(self.root, path)) else 'deleted'
            changes.append(FileChange(path, state))
        for p in st.untracked:
            path = self._p(p)
            if path not in staged:
                changes.append(FileChange(path, 'untracked'))
        return changes

    def _stage(self, changes):
        from dulwich import porcelain
        present = [os.path.join(self.root, c.path) for c in changes if c.state != 'deleted']
        gone = [os.path.join(self.root, c.path) for c in changes if c.state == 'deleted' and not c.staged]
        if present:
            porcelain.add(self.repo, paths=present)
        if gone:
            porcelain.remove(self.repo, paths=gone, cached=True)

    def _commit_index(self, message):
        from dulwich import porcelain
        sha = porcelain.commit(self.repo, message=message.encode('utf-8'))
        return sha.decode('ascii') if isinstance(sha, bytes) else str(sha)

    def branch(self):
        from dulwich import porcelain
        try:
            name = porcelain.active_branch(self.repo)
            return name.decode('utf-8') if isinstance(name, bytes) else str(name)
        except Exception:
            return ''

    def head(self):
        try:
            h = self.repo.head()
            return h.decode('ascii') if isinstance(h, bytes) else str(h)
        except KeyError:
            return None

    def _config(self, section, key):
        try:
            v = self.repo.get_config().get(section, key)
            return v.decode('utf-8') if isinstance(v, bytes) else v
        except KeyError:
            return None

    def remote_name(self):
        return self._config((b'branch', self.branch().encode()), b'remote') or 'origin'

    def remote_url(self):
        return self._config((b'remote', self.remote_name().encode()), b'url')

    def _remote_ref(self) -> bytes:
        return f'refs/remotes/{self.remote_name()}/{self.branch()}'.encode()

    def _with_credentials(self, func, ask_credentials):
        """Calls func(**kw) with the credentials of an HTTPS remote; asks once if they are missing or rejected."""
        from dulwich.client import HTTPUnauthorized
        url = self.remote_url()
        if not url:
            raise GitError(f'no remote {self.remote_name()} configured')
        https = url.startswith(('http://', 'https://'))
        cred = get_credentials(url) if https else None
        for attempt in (0, 1):
            kw = {'username': cred[0], 'password': cred[1]} if cred else {}
            try:
                result = func(**kw)
                if https and cred and attempt == 1:
                    store_credentials(url, *cred)
                return result
            except HTTPUnauthorized:
                if attempt == 1 or ask_credentials is None:
                    raise GitError(f'{_host(url)}: authentication failed (user name and access token needed)')
                cred = ask_credentials(_host(url))
                if not cred:
                    raise GitError('authentication cancelled')

    def _fetch(self, ask_credentials=None):
        from dulwich import porcelain
        quiet = io.BytesIO()
        self._with_credentials(lambda **kw: porcelain.fetch(self.repo, self.remote_name(), outstream=io.StringIO(),
                                                            errstream=quiet, quiet=True, **kw), ask_credentials)

    def _count(self, include, exclude) -> int:
        if include is None:
            return 0
        return sum(1 for _ in self.repo.get_walker(include=[include], exclude=[exclude] if exclude else []))

    def _ahead_behind(self, target=None):
        local = self.repo.head()
        ref = target.encode() if isinstance(target, str) else (target or self._remote_ref())
        try:
            remote = self.repo.refs[ref]
        except KeyError:
            return self._count(local, None), 0
        return self._count(local, remote), self._count(remote, local)

    def _merge_remote(self, fast_forward, target=None):
        from dulwich import porcelain
        before = self.repo.head()
        ref = target.encode() if isinstance(target, str) else (target or self._remote_ref())
        try:
            merge_commit, conflicts = porcelain.merge(self.repo, ref)
        except ImportError as e:
            porcelain.reset(self.repo, 'hard', before)
            raise GitError('both sides changed the same file(s); merging needs the package merge3 or git. '
                           f'Nothing changed. ({e})')
        except Exception as e:
            porcelain.reset(self.repo, 'hard', before)
            raise GitError(f'merge failed, nothing changed: {e}')
        if conflicts:
            porcelain.reset(self.repo, 'hard', before)
            names = [c.decode('utf-8') if isinstance(c, bytes) else str(c) for c in conflicts]
            raise GitError('merge conflict, nothing changed; resolve with git: ' + ', '.join(names))
        return 'fast-forward' if fast_forward else 'merged'

    def _push(self, ask_credentials=None):
        from dulwich import porcelain
        from dulwich.errors import HangupException
        ref = f'refs/heads/{self.branch()}'.encode()
        try:
            self._with_credentials(lambda **kw: porcelain.push(
                self.repo, self.remote_name(), ref + b':' + ref, outstream=io.BytesIO(),
                errstream=io.BytesIO(), **kw), ask_credentials)
        except porcelain.DivergedBranches:
            raise GitError('the remote has new commits: pull first')
        except HangupException as e:
            raise GitError(f'push failed: {e}')

    def _create_bundle(self, path):
        from dulwich import bundle as dbundle
        b = dbundle.create_bundle_from_repo(self.repo, refs=[f'refs/heads/{self.branch()}'.encode()])
        with open(path, 'wb') as f:
            dbundle.write_bundle(f, b)

    def _fetch_bundle(self, path, src, target):
        from dulwich import bundle as dbundle
        with open(path, 'rb') as f:
            b = dbundle.read_bundle(f)
            try:
                for sha in b.prerequisites or []:
                    sha = sha[0] if isinstance(sha, tuple) else sha
                    if sha not in self.repo.object_store:
                        raise GitError(f'{os.path.basename(path)} needs commit {sha.decode()[:7]}, not here')
                b.store_objects(self.repo.object_store)
                self.repo.refs[target.encode()] = b.references[src.encode()]
            finally:
                b.close()


def read_bundle_info(path: str) -> dict:
    """The information file <bundle>.txt next to a bundle (server, branch, commit, ...), {} if none."""
    info = {}
    try:
        with open(path + '.txt', 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line and not line.startswith('#'):
                    k, v = line.split(':', 1)
                    info[k.strip()] = v.strip()
    except OSError:
        pass
    return info


def clone_bundle(path: str, target: str, remote_url: typing.Optional[str] = None,
                 prefer: typing.Optional[str] = None) -> GitBackend:
    """
    A new repository in target from a bundle (e.g. on a field computer without network). Its
    remote origin is remote_url, else the server named in <bundle>.txt (for a later pull and
    push), else none. Returns the backend of the new repository.
    """
    path, target = os.path.abspath(path), os.path.abspath(target)
    if os.path.exists(target) and os.listdir(target):
        raise GitError(f'{target} exists and is not empty')
    url = remote_url or read_bundle_info(path).get('server') or None
    choice = (prefer or os.environ.get('REDVYPR_GIT') or '').lower()
    if choice != 'dulwich' and (choice == 'cli' or git_program_available()):
        res = subprocess.run(['git', 'clone', '--quiet', path, target], capture_output=True, text=True,
                             encoding='utf-8', errors='replace')
        if res.returncode != 0:
            raise GitError(f'clone failed: {res.stderr.strip()}')
        b = CliBackend(target)
        if url:
            b._git('remote', 'set-url', 'origin', url)
        else:
            b._git('remote', 'remove', 'origin', check=False)
        return b
    # not porcelain.clone(): it fails on bundles of the git program (offset deltas); the objects
    # are stored directly, the branch is checked out
    from dulwich import porcelain
    from dulwich import bundle as dbundle
    os.makedirs(target, exist_ok=True)
    repo = porcelain.init(target)
    with open(path, 'rb') as f:
        bundle = dbundle.read_bundle(f)
        try:
            if bundle.prerequisites:
                raise GitError(f'{os.path.basename(path)} is incremental, a new repository needs a full bundle')
            bundle.store_objects(repo.object_store)
            heads = {k: v for k, v in bundle.references.items() if k.startswith(b'refs/heads/')}
        finally:
            bundle.close()
    if not heads:
        raise GitError(f'{os.path.basename(path)} has no branch')
    ref = b'refs/heads/' + read_bundle_info(path).get('branch', '').encode()
    if ref not in heads:
        ref = sorted(heads)[0]
    repo.refs[ref] = heads[ref]
    repo.refs.set_symbolic_ref(b'HEAD', ref)
    porcelain.reset(repo, 'hard', heads[ref])
    b = DulwichBackend(target)
    cfg = b.repo.get_config()
    if url:
        cfg.set((b'remote', b'origin'), b'url', url.encode())
        cfg.set((b'remote', b'origin'), b'fetch', b'+refs/heads/*:refs/remotes/origin/*')
    else:
        try:
            del cfg[(b'remote', b'origin')]
        except KeyError:
            pass
    cfg.write_to_path()
    return b


def git_program_available() -> bool:
    return shutil.which('git') is not None


def backend_for(path, prefer: typing.Optional[str] = None) -> typing.Optional[GitBackend]:
    """
    The git backend of the repository containing path (None if it is in none): the git program
    if installed, else dulwich; prefer or the environment variable REDVYPR_GIT ('cli' or
    'dulwich') forces one.
    """
    root = find_repo(path)
    if root is None:
        return None
    choice = (prefer or os.environ.get('REDVYPR_GIT') or '').lower()
    if choice != 'dulwich' and (choice == 'cli' or git_program_available()):
        return CliBackend(root)
    return DulwichBackend(root)


def group_by_repo(paths, prefer=None) -> typing.Dict[str, typing.Tuple[GitBackend, list]]:
    """{repository root: (backend, [paths in it])} of paths (paths outside repositories are left out)."""
    out = {}
    for p in paths:
        root = find_repo(p)
        if root is None:
            continue
        if root not in out:
            out[root] = (backend_for(root, prefer=prefer), [])
        out[root][1].append(p)
    return out
