"""Git window of the item libraries (redvypr.widgets.redvypr_item_git_widget)."""

import pytest
from PyQt6 import QtWidgets

import redvypr
from redvypr import item_git as ig
from redvypr import items
from redvypr.widgets import redvypr_item_git_widget as gw
from redvypr.widgets import redvypr_items_widget as iw

from test_item_git import BACKENDS, two_computers  # noqa: E402


@pytest.fixture
def app():
    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield a


@pytest.mark.parametrize('backend', BACKENDS)
def test_git_window_commit_push_pull(app, tmp_path, backend):
    home, field = two_computers(tmp_path)
    r_field = redvypr.Redvypr(hostname='gitwin_field')
    r_field.load_item_library(str(field / 'lib'))
    r_home = redvypr.Redvypr(hostname='gitwin_home')
    r_home.load_item_library(str(home / 'lib'))
    wf = gw.RedvyprItemGitWidget(r_field, prefer=backend)
    assert wf.repos.rowCount() == 1 and wf.repos.item(0, 3).text() == '0'
    r_field.add_item(items.Item(itemtype='gadget', id='F7', name='field'), valid_from='2026-11-02T00:00:00+00:00')
    r_field.save_item_libraries()
    wf.refresh()
    assert wf.repos.item(0, 3).text() == '1' and wf.files.item(0, 1).text() == 'lib/items/gadget/F7.yaml'
    assert wf.commit('') is None and 'message' in wf.status.text()
    assert wf.commit('field: F7') and 'committed' in wf.status.text()
    wf.refresh(fetch=True)
    assert wf.repos.item(0, 4).text() == '1'                 # one commit to push
    wf.push()
    assert 'pushed' in wf.status.text()
    # home: the Items window opens the git window; a pull changes the libraries and the tree
    items_window = iw.RedvyprItemsWidget(redvypr_instance=r_home)
    wh = items_window.open_git(prefer=backend)
    assert items_window.open_git() is wh
    seen = []
    wh.libraries_changed.connect(lambda: seen.append(True))
    wh.pull()
    assert 'fast-forward' in wh.status.text() and seen
    assert r_home.get_item('gadget/F7').name == 'field'
    assert 'gadget/F7' in [ref for _d, ref in _tree(items_window)]
    for w in (wf, wh, items_window):
        w.close()


def _tree(w):
    out = []

    def walk(node, depth):
        out.append((depth, node.text(0)))
        for i in range(node.childCount()):
            walk(node.child(i), depth + 1)
    for i in range(w.tree.topLevelItemCount()):
        walk(w.tree.topLevelItem(i), 0)
    return out


def test_git_window_without_repository(app, tmp_path):
    r = redvypr.Redvypr(hostname='gitwin_none')
    lib = tmp_path / 'plain' / 'inventory.yaml'
    lib.parent.mkdir()
    from redvypr import metadata_sources as ms
    ms.save_item_library(str(lib), {})
    if ig.find_repo(lib) is not None:
        pytest.skip('temporary folder inside a git repository')
    r.load_item_library(str(lib))
    w = gw.RedvyprItemGitWidget(r)
    assert w.repos.rowCount() == 0 and 'not in a git repository' in w.status.text()
    w.close()


def test_credentials_asked_once_and_stored(monkeypatch, tmp_path):
    # dulwich backend: an HTTPS remote rejecting without credentials, accepting the asked ones
    from dulwich import porcelain
    from dulwich.client import HTTPUnauthorized
    root = tmp_path / 'r'
    root.mkdir()
    porcelain.init(str(root))
    b = ig.DulwichBackend(str(root))
    monkeypatch.setattr(b, 'remote_url', lambda: 'https://git.example.org/x/inv.git')
    stored = {}
    monkeypatch.setattr(ig, 'get_credentials', lambda url: stored.get('cred'))
    monkeypatch.setattr(ig, 'store_credentials', lambda url, u, t: stored.__setitem__('cred', (u, t)))
    calls = []

    def remote_op(**kw):
        calls.append(kw)
        if kw.get('password') != 'good':
            raise HTTPUnauthorized('www-authenticate', 'https://git.example.org/x/inv.git')
        return 'ok'

    asked = []
    assert b._with_credentials(remote_op, lambda host: asked.append(host) or ('peter', 'good')) == 'ok'
    assert asked == ['git.example.org'] and stored['cred'] == ('peter', 'good')
    assert calls[0] == {} and calls[1] == {'username': 'peter', 'password': 'good'}
    # next time from the key store, no question
    asked.clear()
    assert b._with_credentials(remote_op, lambda host: asked.append(host)) == 'ok' and asked == []
    # rejected and cancelled
    stored['cred'] = ('peter', 'bad')
    with pytest.raises(ig.GitError, match='cancelled'):
        b._with_credentials(remote_op, lambda host: None)
