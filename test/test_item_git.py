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
