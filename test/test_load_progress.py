"""Progress while loading item libraries (callback, cancel, dialog, windows)."""

import pytest
from PyQt6 import QtWidgets

import redvypr
from redvypr import items
from redvypr import metadata_sources as ms
from redvypr.widgets import load_progress as lp
from redvypr.widgets import redvypr_items_widget as iw
from redvypr.widgets import redvypr_metadata_window as mw

T0 = '2026-11-01T00:00:00+00:00'


@pytest.fixture
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def directory_library(tmp_path):
    s = {}
    for i in range(12):
        items.add_item(s, items.Item(itemtype='gadget', id=f'G{i:02d}', name=f'gadget {i}'), valid_from=T0)
    d = str(tmp_path / 'lib')
    ms.save_metadata_library(d, s)
    return d


def test_callback_per_file_and_totals(directory_library):
    calls = []
    st = ms.read_library_storage(directory_library, progress=lambda text, done, total: calls.append((text, done, total)))
    assert len(st) == 12
    assert calls[0] == ('Reading lib', 0, 12) and calls[-1] == ('Reading lib', 12, 12) and len(calls) == 13
    # loading into redvypr: reading, then adding
    calls.clear()
    r = redvypr.Redvypr(hostname='progress1')
    assert r.load_metadata_library(directory_library, progress=lambda *a: calls.append(a)) == 12
    assert calls[-1][0] == 'Adding to the metadata'
    assert r.get_item('gadget/G05') is not None


def test_cancel_changes_nothing(directory_library):
    r = redvypr.Redvypr(hostname='progress2')

    def cancel_at_five(text, done, total):
        if done >= 5:
            raise ms.LoadCancelled()
    with pytest.raises(ms.LoadCancelled):
        r.load_metadata_library(directory_library, progress=cancel_at_five)
    assert r.list_items() == [] and r.metadata_libraries == []
    # reload: reads first, so a cancel keeps the old entries
    r.load_metadata_library(directory_library)
    assert len(r.list_items()) == 12
    with pytest.raises(ms.LoadCancelled):
        r.reload_metadata_library(directory_library, progress=cancel_at_five)
    assert len(r.list_items()) == 12 and r.metadata_libraries == [directory_library]
    # reload without cancel replaces the entries (an item deleted in the files is gone)
    s = ms.read_library_storage(directory_library)
    del s[items.item_address('gadget', 'G03')]
    ms.save_metadata_library(directory_library, s)
    seen = []
    r.reload_metadata_library(directory_library, progress=lambda text, *_: seen.append(text))
    assert r.get_item('gadget/G03') is None and len(r.list_items()) == 11
    assert 'Replacing the old entries' in seen


def test_dialog_is_shown_after_the_delay_and_cancels(app):
    fast = lp.LoadProgress(None, 'Loading', delay=60)
    fast('Reading x', 1, 10)
    assert not fast.shown
    fast.close()
    slow = lp.LoadProgress(None, 'Loading', delay=0)
    slow('Reading x', 3, 10)
    assert slow.shown and slow.dialog.isVisible()
    assert 'Reading x' in slow.dialog.labelText() and '3 / 10' in slow.dialog.labelText()
    assert slow.dialog.maximum() == 10 and slow.dialog.value() == 3
    slow('Adding', 0, 0)
    assert slow.dialog.maximum() == 0
    slow.dialog.cancel()
    with pytest.raises(ms.LoadCancelled):
        slow('Reading x', 4, 10)
    slow.close()


def test_items_and_metadata_window_load_with_progress(app, directory_library, tmp_path):
    r = redvypr.Redvypr(hostname='progress3')
    w = iw.RedvyprItemsWidget(redvypr_instance=r)
    assert w.load_library(directory_library) == 12
    assert ' items loaded from ' in w.status.text() and w.status.text().endswith(' s')
    assert len(r.list_items()) == 12
    w.close()
    r2 = redvypr.Redvypr(hostname='progress4')
    m = mw.RedvyprMetadataWindow(redvypr_instance=r2)
    assert m.load_library(directory_library) == 12
    assert 'lib/' in m.status.text() and 'items loaded' in m.items.status.text()
    assert m.items.tree.topLevelItemCount() == 12
    # an unreadable path: error, no crash
    assert m.load_library(str(tmp_path / 'missing.sqlite')) is None
    assert 'not loaded' in m.items.status.text()
    m.close()
