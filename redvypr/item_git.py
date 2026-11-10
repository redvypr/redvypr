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
"""

import dataclasses
import logging
import os
import shutil
import subprocess
import typing

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

    # --- common ---
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
        res = subprocess.run(['git', '-C', self.root, *args], capture_output=True, text=True,
                             encoding='utf-8', errors='replace')
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
