"""git for the item libraries (redvypr.item_git): status and commit with the git program and dulwich."""

import os

import pytest
from dulwich import porcelain
from dulwich.repo import Repo

from redvypr import item_git as ig
from redvypr import items
from redvypr import metadata_sources as ms

T0 = '2026-11-01T00:00:00+00:00'
BACKENDS = ['dulwich'] + (['cli'] if ig.git_program_available() else [])


def make_repo(tmp_path):
    root = tmp_path / 'inventory'
    root.mkdir()
    porcelain.init(str(root))
    cfg = Repo(str(root)).get_config()
    cfg.set((b'user',), b'name', b'Test User')
    cfg.set((b'user',), b'email', b'test@example.org')
    cfg.write_to_path()
    (root / 'README.md').write_text('readme\n')
    s = {}
    items.add_item(s, items.Item(itemtype='gadget', id='G1', name='one'), valid_from=T0)
    ms.save_item_library(str(root / 'inventory.yaml'), s)
    s2 = {}
    items.add_item(s2, items.Item(itemtype='gadget', id='G2'), valid_from=T0)
    ms.save_item_library(str(root / 'lib'), s2)
    porcelain.add(str(root), paths=[str(root / 'README.md'), str(root / 'inventory.yaml'),
                                    str(root / 'lib' / 'redvypr_library.yaml'),
                                    str(root / 'lib' / 'items' / 'gadget' / 'G2.yaml')])
    porcelain.commit(str(root), message=b'start')
    return root


@pytest.mark.parametrize('backend', BACKENDS)
def test_status_and_commit_of_library_files(tmp_path, backend):
    root = make_repo(tmp_path)
    b = ig.backend_for(root / 'lib', prefer=backend)
    assert b is not None and b.root == str(root) and b.branch() in ('master', 'main')
    start = b.head()
    assert b.status() == []
    # changes: a modified file, a new file in the directory library, a deleted one, an unrelated file
    s = ms.read_library_storage(str(root / 'inventory.yaml'))
    items.add_item(s, items.Item(itemtype='gadget', id='G1', name='renamed'), valid_from='2026-11-05T00:00:00+00:00')
    ms.save_item_library(str(root / 'inventory.yaml'), s)
    s2 = ms.read_library_storage(str(root / 'lib'))
    items.add_item(s2, items.Item(itemtype='gadget', id='G3'), valid_from=T0)
    del s2[items.item_address('gadget', 'G2')]
    ms.save_item_library(str(root / 'lib'), s2)
    (root / 'notes.txt').write_text('not a library\n')
    paths = [root / 'inventory.yaml', root / 'lib']
    got = {(c.path, c.state) for c in b.status(paths)}
    assert got == {('inventory.yaml', 'modified'), ('lib/items/gadget/G3.yaml', 'untracked'),
                   ('lib/items/gadget/G2.yaml', 'deleted')}
    assert ('notes.txt', 'untracked') in {(c.path, c.state) for c in b.status()}
    sha = b.commit(paths, 'field changes')
    assert sha and sha != start
    assert b.status(paths) == []
    assert [(c.path, c.state) for c in b.status()] == [('notes.txt', 'untracked')]     # not committed
    log = [e.commit for e in Repo(str(root)).get_walker()]
    assert log[0].message.strip() == b'field changes' and log[0].author.startswith(b'Test User')
    assert b.commit(paths, 'nothing') is None


@pytest.mark.parametrize('backend', BACKENDS)
def test_commit_refused_with_other_staged_changes(tmp_path, backend):
    root = make_repo(tmp_path)
    b = ig.backend_for(root, prefer=backend)
    (root / 'README.md').write_text('changed\n')
    porcelain.add(str(root), paths=[str(root / 'README.md')])
    (root / 'inventory.yaml').write_text((root / 'inventory.yaml').read_text() + '\n')
    with pytest.raises(ig.GitError, match='README.md'):
        b.commit([root / 'inventory.yaml'], 'x')
    with pytest.raises(ig.GitError, match='message'):
        b.commit([root / 'inventory.yaml'], ' ')


def test_no_repository(tmp_path):
    assert ig.find_repo(tmp_path) is None or not str(ig.find_repo(tmp_path)).startswith(str(tmp_path))
    plain = tmp_path / 'plain'
    plain.mkdir()
    if ig.find_repo(plain) is None:
        assert ig.backend_for(plain) is None
    assert ig.group_by_repo([plain / 'x.yaml']) == {} or ig.find_repo(plain) is not None


@pytest.mark.parametrize('backend', BACKENDS)
def test_redvypr_commits_the_item_files(tmp_path, backend):
    import redvypr
    root = make_repo(tmp_path)
    r = redvypr.Redvypr(hostname='gitcommit')
    r.load_item_library(str(root / 'inventory.yaml'))
    r.load_item_library(str(root / 'lib'))
    assert all(st == [] for _b, st in r.item_git_status(prefer=backend).values())
    r.add_item(items.Item(itemtype='gadget', id='G9', name='new in the field'), valid_from=T0)
    (root / 'notes.txt').write_text('unrelated\n')
    res = r.item_git_commit('new gadget G9', prefer=backend)
    assert list(res) == [str(root)] and res[str(root)]
    backend_obj = ig.backend_for(root, prefer=backend)
    assert [c.path for c in backend_obj.status()] == ['notes.txt']
    assert str(root / 'inventory.yaml') in r.item_git_paths()


# --- pull and push ---------------------------------------------------------------------------

def two_computers(tmp_path):
    """A server repository and two clones (home and field) with a library file each."""
    server = str(tmp_path / 'server.git')
    porcelain.init(server, bare=True)
    home = make_repo(tmp_path)
    cfg = Repo(str(home)).get_config()
    cfg.set((b'remote', b'origin'), b'url', server.encode())
    cfg.set((b'remote', b'origin'), b'fetch', b'+refs/heads/*:refs/remotes/origin/*')
    cfg.write_to_path()
    branch = porcelain.active_branch(Repo(str(home)))
    porcelain.push(str(home), 'origin', b'refs/heads/' + branch + b':refs/heads/' + branch,
                   outstream=__import__('io').BytesIO(), errstream=__import__('io').BytesIO())
    field = tmp_path / 'field'
    porcelain.clone(server, str(field), errstream=__import__('io').BytesIO())
    cfg = Repo(str(field)).get_config()
    cfg.set((b'user',), b'name', b'Field User')
    cfg.set((b'user',), b'email', b'field@example.org')
    cfg.write_to_path()
    return home, field


def change_item(repo_root, item_id, name, when='2026-11-05T00:00:00+00:00'):
    s = ms.read_library_storage(str(repo_root / 'lib'))
    items.add_item(s, items.Item(itemtype='gadget', id=item_id, name=name), valid_from=when)
    ms.save_item_library(str(repo_root / 'lib'), s)


@pytest.mark.parametrize('backend', BACKENDS)
def test_push_and_pull(tmp_path, backend):
    home, field = two_computers(tmp_path)
    bh, bf = ig.backend_for(home, prefer=backend), ig.backend_for(field, prefer=backend)
    assert bh.pull().action == 'up to date' and bh.push().action == 'nothing to push'
    # field: new item, commit, push; home: fast-forward
    change_item(field, 'F1', 'from the field')
    bf.commit([field / 'lib'], 'field: F1')
    res = bf.push()
    assert res.action == 'pushed' and res.ahead == 1
    res = bh.pull()
    assert res.action == 'fast-forward' and res.behind == 1 and res.changed
    assert (home / 'lib' / 'items' / 'gadget' / 'F1.yaml').exists()
    # both sides new commits in different files: push refused, pull merges, then push
    change_item(home, 'H2', 'at home')
    bh.commit([home / 'lib'], 'home: H2')
    bh.push()
    change_item(field, 'F2', 'field again')
    bf.commit([field / 'lib'], 'field: F2')
    with pytest.raises(ig.GitError, match='pull first'):
        bf.push()
    res = bf.pull()
    assert res.action == 'merged' and res.ahead == 1 and res.behind == 1
    assert (field / 'lib' / 'items' / 'gadget' / 'H2.yaml').exists()
    assert bf.push().action == 'pushed'
    assert bh.pull().changed and (home / 'lib' / 'items' / 'gadget' / 'F2.yaml').exists()


@pytest.mark.parametrize('backend', BACKENDS)
def test_pull_needs_clean_tree_and_stops_at_conflicts(tmp_path, backend):
    home, field = two_computers(tmp_path)
    bh, bf = ig.backend_for(home, prefer=backend), ig.backend_for(field, prefer=backend)
    change_item(field, 'G2', 'field name')
    with pytest.raises(ig.GitError, match='commit first'):
        bf.pull()
    bf.commit([field / 'lib'], 'field: G2 renamed')
    change_item(home, 'G2', 'home name')
    bh.commit([home / 'lib'], 'home: G2 renamed')
    bh.push()
    before = bf.head()
    with pytest.raises(ig.GitError, match='(?i)nothing changed'):
        bf.pull()
    assert bf.head() == before and bf.status() == []          # as before the pull
    text = (field / 'lib' / 'items' / 'gadget' / 'G2.yaml').read_text()
    assert 'field name' in text and '<<<<' not in text


def test_credentials_are_asked_and_stored(monkeypatch):
    stored = {}

    class FakeCred:
        def __init__(self, u, p):
            self.username, self.password = u, p

    import keyring
    monkeypatch.setattr(keyring, 'get_credential',
                        lambda service, user: FakeCred(*stored[service]) if service in stored else None)
    monkeypatch.setattr(keyring, 'set_password', lambda service, user, pw: stored.__setitem__(service, (user, pw)))
    url = 'https://gitlab.example.org/group/inventory.git'
    assert ig.get_credentials(url) is None
    ig.store_credentials(url, 'peter', 'tok')
    assert ig.get_credentials(url) == ('peter', 'tok') and 'redvypr-git:gitlab.example.org' in stored


@pytest.mark.parametrize('backend', BACKENDS)
def test_redvypr_pull_reloads_and_push(tmp_path, backend):
    import redvypr
    home, field = two_computers(tmp_path)
    r_field = redvypr.Redvypr(hostname='field')
    r_field.load_item_library(str(field / 'lib'))
    r_home = redvypr.Redvypr(hostname='home')
    r_home.load_item_library(str(home / 'lib'))
    # in the field: rename G2, delete nothing; commit and push from redvypr
    r_field.add_item(items.Item(itemtype='gadget', id='G2', name='renamed in the field'),
                     valid_from='2026-11-06T00:00:00+00:00')
    assert all(r_field.item_git_commit('field: G2 renamed', prefer=backend).values())
    res = r_field.item_git_push(prefer=backend)
    assert [x.action for x in res.values()] == ['pushed']
    # at home: pull brings it in, the library is loaded again
    assert r_home.get_item('gadget/G2').name is None
    res = r_home.item_git_pull(prefer=backend)
    assert [x.action for x in res.values()] == ['fast-forward']
    assert r_home.get_item('gadget/G2').name == 'renamed in the field'
    # an item deleted elsewhere disappears after the pull (reload removes the old entries)
    s = ms.read_library_storage(str(field / 'lib'))
    del s[items.item_address('gadget', 'G2')]
    ms.save_item_library(str(field / 'lib'), s)
    ig.backend_for(field, prefer=backend).commit([field / 'lib'], 'G2 removed')
    ig.backend_for(field, prefer=backend).push()
    r_home.item_git_pull(prefer=backend)
    assert r_home.get_item('gadget/G2') is None
    # a new item (new file) does not stop a pull; a changed existing item not committed does
    r_home.add_item(items.Item(itemtype='gadget', id='H9'), valid_from=T0)
    assert not isinstance(list(r_home.item_git_pull(prefer=backend).values())[0], ig.GitError)
    r_home.load_item_library(str(home / 'inventory.yaml'))
    r_home.add_item(items.Item(itemtype='gadget', id='G1', name='changed, not committed'),
                    valid_from='2026-11-07T00:00:00+00:00')
    res = r_home.item_git_pull(prefer=backend)
    assert isinstance(list(res.values())[0], ig.GitError) and 'commit first' in str(list(res.values())[0])


@pytest.mark.parametrize('backend', BACKENDS)
def test_merge_of_one_file_changed_at_two_places(tmp_path, backend):
    # a single file library: home changes G1 (first item), the field adds an item at the end
    home, field = two_computers(tmp_path)
    bh, bf = ig.backend_for(home, prefer=backend), ig.backend_for(field, prefer=backend)
    s = ms.read_library_storage(str(home / 'inventory.yaml'))
    items.add_item(s, items.Item(itemtype='gadget', id='G1', name='home'), valid_from='2026-11-05T00:00:00+00:00')
    ms.save_item_library(str(home / 'inventory.yaml'), s)
    bh.commit([home / 'inventory.yaml'], 'home: G1')
    bh.push()
    s = ms.read_library_storage(str(field / 'inventory.yaml'))
    items.add_item(s, items.Item(itemtype='gadget', id='Z9', name='field'), valid_from=T0)
    ms.save_item_library(str(field / 'inventory.yaml'), s)
    bf.commit([field / 'inventory.yaml'], 'field: Z9')
    res = bf.pull()
    assert res.action == 'merged'
    merged = ms.read_library_storage(str(field / 'inventory.yaml'))
    assert items.get_item(merged, 'gadget/G1', at_time='2026-11-10T00:00:00+00:00').name == 'home'
    assert items.get_item(merged, 'gadget/Z9', at_time='2026-11-10T00:00:00+00:00') is not None
    assert '<<<<' not in (field / 'inventory.yaml').read_text()
