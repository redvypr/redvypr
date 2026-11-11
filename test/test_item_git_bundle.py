"""git bundles for computers without network (redvypr.item_git)."""

import os

import pytest

import redvypr
from redvypr import item_git as ig
from redvypr import items
from redvypr import metadata_sources as ms

from test_item_git import BACKENDS, T0, change_item, make_repo, two_computers  # noqa: E402

PAIRS = [(a, b) for a in BACKENDS for b in BACKENDS]


@pytest.mark.parametrize('make_with,read_with', PAIRS)
def test_field_cycle_with_bundles(tmp_path, make_with, read_with):
    """home -> bundle -> new field repository -> changes -> bundle -> home, without any network."""
    home, _field = two_computers(tmp_path)
    r_home = redvypr.Redvypr(hostname='bundle_home')
    r_home.load_metadata_library(str(home / 'lib'))
    r_home.load_metadata_library(str(home / 'inventory.yaml'))
    out = r_home.item_git_export_bundle(str(home), str(tmp_path / 'to_field.bundle'), prefer=make_with)
    info = ig.read_bundle_info(out)
    assert info['server'].endswith('server.git') and info['commit'] == ig.backend_for(home).head()
    # field computer: new repository from the bundle, libraries loaded, origin = the server
    r_field = redvypr.Redvypr(hostname='bundle_field')
    libs = r_field.item_git_clone_bundle(out, str(tmp_path / 'field2'), prefer=read_with)
    assert sorted(os.path.basename(p) for p in libs) == ['inventory.yaml', 'lib']
    assert r_field.get_item('gadget/G2') is not None
    bf = ig.backend_for(tmp_path / 'field2', prefer=read_with)
    assert bf.remote_url() == info['server']
    # changes in the field, committed there; back as a bundle
    r_field.add_item(items.Item(itemtype='gadget', id='F5', name='made in the field'), valid_from=T0)
    assert all(r_field.item_git_commit('field: F5', prefer=read_with).values())
    back = r_field.item_git_export_bundle(str(tmp_path / 'field2'), str(tmp_path / 'from_field.bundle'),
                                          prefer=read_with)
    # meanwhile at home another change: the import merges
    change_item(home, 'H1', 'at home')
    ig.backend_for(home, prefer=make_with).commit([home / 'lib'], 'home: H1')
    r_home.reload_metadata_library(str(home / 'lib'))
    res = r_home.item_git_import_bundle(str(home), back, prefer=make_with)
    assert res.action == 'merged' and res.behind == 1
    assert r_home.get_item('gadget/F5').name == 'made in the field'
    assert r_home.get_item('gadget/H1') is not None
    # importing the same bundle again: nothing new
    assert r_home.item_git_import_bundle(str(home), back, prefer=make_with).action == 'up to date'


@pytest.mark.parametrize('backend', BACKENDS)
def test_bundle_import_conflict_and_checks(tmp_path, backend):
    home, field = two_computers(tmp_path)
    bh, bf = ig.backend_for(home, prefer=backend), ig.backend_for(field, prefer=backend)
    change_item(field, 'G2', 'field name')
    bf.commit([field / 'lib'], 'field: G2')
    bundle = bf.create_bundle(str(tmp_path / 'f.bundle'))
    change_item(home, 'G2', 'home name')
    with pytest.raises(ig.GitError, match='commit first'):
        bh.import_bundle(bundle)
    bh.commit([home / 'lib'], 'home: G2')
    before = bh.head()
    with pytest.raises(ig.GitError, match='(?i)nothing changed'):
        bh.import_bundle(bundle)
    assert bh.head() == before and bh.status() == []
    # a bundle into a folder that is not empty: refused
    (tmp_path / 'full').mkdir()
    (tmp_path / 'full' / 'x').write_text('x')
    with pytest.raises(ig.GitError, match='not empty'):
        ig.clone_bundle(bundle, str(tmp_path / 'full'), prefer=backend)
    # remote given explicitly wins over the information file
    b2 = ig.clone_bundle(bundle, str(tmp_path / 'c2'), remote_url='https://example.org/inv.git', prefer=backend)
    assert b2.remote_url() == 'https://example.org/inv.git'


def test_find_libraries(tmp_path):
    root = make_repo(tmp_path)
    (root / 'notes.yaml').write_text('a: 1\n')
    assert [os.path.basename(p) for p in ms.find_libraries(root)] == ['inventory.yaml', 'lib']
