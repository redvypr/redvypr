"""
Items window (redvypr.widgets.redvypr_items_widget), offscreen.
"""
import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

import redvypr
from redvypr import items
from redvypr.widgets import redvypr_items_widget as iw

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 11, 1, tzinfo=UTC)
T1 = datetime.datetime(2026, 11, 5, tzinfo=UTC)


@pytest.fixture
def widget():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    r = redvypr.Redvypr(hostname='itemswidget')
    r.add_item(items.Item(itemtype='norlog_v02', id='N-012', deviceid='0xA1B2'), valid_from=T0)
    r.add_item(items.Item(itemtype='breakout_board_v01', id='BO-003', parent='norlog_v02/N-012'), valid_from=T0)
    r.add_item(items.Item(itemtype='ntc_sensor', id='0042', parent='breakout_board_v01/BO-003', slot='ntc0'),
               valid_from=T0)
    w = iw.RedvyprItemsWidget(redvypr_instance=r)
    yield w
    w.close()
    assert app is not None


def tree_refs(w):
    out = []

    def walk(node, depth):
        if node.data(0, iw.ROLE_SLOT) is not None:      # free slot rows are no items
            return
        out.append((depth, node.text(0)))
        for i in range(node.childCount()):
            walk(node.child(i), depth + 1)
    for i in range(w.tree.topLevelItemCount()):
        walk(w.tree.topLevelItem(i), 0)
    return out


def select(w, ref):
    found = w.tree.findItems(ref, iw.QtCore.Qt.MatchFlag.MatchExactly | iw.QtCore.Qt.MatchFlag.MatchRecursive)
    w.tree.setCurrentItem(found[0])


def test_value_conversion():
    assert iw.value_to_text(None) == '' and iw.value_to_text({'value': 1}) == '{"value": 1}'
    assert iw.text_to_value('', str) is None and iw.text_to_value('3', int) == 3
    assert iw.text_to_value('{value: 2.5, unit: Ohm}', None) == {'value': 2.5, 'unit': 'Ohm'}
    assert iw._base_type(items.Item.model_fields['name'].annotation) is str
    assert iw._base_type(items.Item.model_fields['order'].annotation) is None


def test_tree_form_and_save(widget):
    w = widget
    assert tree_refs(w) == [(0, 'norlog_v02/N-012'), (1, 'breakout_board_v01/BO-003'), (2, 'ntc_sensor/0042')]
    select(w, 'breakout_board_v01/BO-003')
    assert w.current_ref == 'breakout_board_v01/BO-003' and 'parent' in w.form_fields
    w.form_fields['mpn'][0].setText('BRK-1')
    w.new_key.setText('R1')
    w.add_field()
    w.form_fields['R1'][0].setText('{"value": 10002.7, "unit": "Ohm"}')
    w.save_item()
    item = w.redvypr.get_item('breakout_board_v01/BO-003')
    assert item.mpn == 'BRK-1' and items.param_value(item.R1) == 10002.7   # dict or Quantity (breakout_board_v01 type)
    assert 'saved' in w.status.text()
    keys = {w.history.item(r, 0).text() for r in range(w.history.rowCount())}
    assert {'mpn', 'R1', 'parent'} <= keys
    # wrong value
    w.form_fields['R1'][0].setText('{broken')
    w.save_item()
    assert 'not saved' in w.status.text()


def test_new_copy_move_and_state_at(widget):
    w = widget
    assert w.create_item('ntc_sensor', '0043', valid_from=T0, with_uuid=True)
    assert w.redvypr.get_item('ntc_sensor/0043').uuid
    assert not w.create_item('ntc_sensor', '0043', valid_from=T0)          # exists
    assert 'exists' in w.status.text()
    src = w.redvypr.get_item('ntc_sensor/0042')
    assert w.create_item('ntc_sensor', '0044', valid_from=T0, source=src)
    assert w.redvypr.get_item('ntc_sensor/0044').slot == 'ntc0'
    # move 0042 to slot ntc1 from T1 on; the state at T0 shows the old slot
    assert w.move(w.redvypr.get_item('ntc_sensor/0042'), 'breakout_board_v01/BO-003', 'ntc1', T1)
    assert w.redvypr.get_item('ntc_sensor/0042').slot == 'ntc1'
    w.use_now.setChecked(False)
    w.at_time.setDateTime(iw._qdt(T0 + datetime.timedelta(days=1)))
    w.refresh()
    select(w, 'ntc_sensor/0042')
    assert w.form_fields['slot'][0].text() == 'ntc0'
    # detach: no parent any more
    w.use_now.setChecked(True)
    assert w.move(w.redvypr.get_item('ntc_sensor/0044'), None, None, T1)
    assert w.redvypr.get_item('ntc_sensor/0044').parent is None
    assert (0, 'ntc_sensor/0044') in tree_refs(w)


def test_type_filter_and_library(widget, tmp_path):
    w = widget
    i = w.type_filter.findData('ntc_sensor')
    w.type_filter.setCurrentIndex(i)
    assert tree_refs(w) == [(0, 'ntc_sensor/0042')]
    path = str(tmp_path / 'lib.yaml')
    w.save_library(path)
    assert '3 items saved' in w.status.text()
    r2 = redvypr.Redvypr(hostname='itemswidget2')
    w2 = iw.RedvyprItemsWidget(redvypr_instance=r2)
    w2.load_library(path)
    assert '3 items loaded' in w2.status.text()
    assert [ref for _d, ref in tree_refs(w2)] == ['norlog_v02/N-012', 'breakout_board_v01/BO-003', 'ntc_sensor/0042']
    w2.close()


def test_save_libraries_button(widget, tmp_path):
    w = widget
    path = str(tmp_path / 'inventory_norlog.yaml')
    w.save_library(path)
    assert w.redvypr.metadata_libraries == [path]
    w.save_libraries()
    assert 'inventory_norlog.yaml (3)' in w.status.text()


def test_delete_item(widget, tmp_path):
    w = widget
    path = str(tmp_path / 'inventory_norlog.yaml')
    w.save_library(path)
    asked = []
    # breakout has a child: the question names it; answered no: nothing happens
    assert not w.delete_item('breakout_board_v01/BO-003', confirm=lambda t: asked.append(t) or False)
    assert 'ntc_sensor/0042' in asked[0]
    assert w.redvypr.get_item('breakout_board_v01/BO-003') is not None
    # a wrong item deleted, also from the library at the next save
    w.redvypr.add_item(items.Item(itemtype='norlog_v02', id='WRONG'), valid_from=T0)
    w.refresh()
    assert w.delete_item('norlog_v02/WRONG', confirm=lambda t: True)
    assert w.redvypr.get_item('norlog_v02/WRONG') is None
    assert 'norlog_v02/WRONG' not in [ref for _d, ref in tree_refs(w)]
    w.save_libraries()
    from redvypr import metadata_sources as ms
    assert items.item_address('norlog_v02', 'WRONG') not in ms.load_metadata_library(path)
    assert len(ms.load_metadata_library(path)) == 3


def test_sn_column_and_move_dialog_labels(widget):
    w = widget
    w.redvypr.add_item(items.Item(itemtype='norlog_v02', id='6BD51FFD60A7F08E', sn='003',
                                  deviceid='6BD51FFD60A7F08E'), valid_from=T0)
    w.refresh()
    assert w.tree.headerItem().text(1) == 'SN'
    rows = {}

    def walk(node):
        rows[node.text(0)] = node.text(1)
        for i in range(node.childCount()):
            walk(node.child(i))
    for i in range(w.tree.topLevelItemCount()):
        walk(w.tree.topLevelItem(i))
    assert rows['norlog_v02/6BD51FFD60A7F08E'] == '003'
    bo = w.redvypr.get_item('breakout_board_v01/BO-003')
    dlg = iw.MoveItemDialog(w, bo, w.redvypr.list_items())
    labels = [dlg.parent_ref.itemText(i) for i in range(dlg.parent_ref.count())]
    assert 'norlog_v02/6BD51FFD60A7F08E (sn 003)' in labels
    dlg.parent_ref.setCurrentIndex(labels.index('norlog_v02/6BD51FFD60A7F08E (sn 003)'))
    assert dlg.values()[0] == 'norlog_v02/6BD51FFD60A7F08E'
    dlg.parent_ref.setEditText('norlog_v02/N-012')        # typed reference
    assert dlg.values()[0] == 'norlog_v02/N-012'
    dlg.parent_ref.setCurrentIndex(0)
    assert dlg.values()[0] is None


def test_flat_list(widget):
    w = widget
    assert [d for d, _r in tree_refs(w)] == [0, 1, 2]           # tree
    w.flat.setChecked(True)
    assert tree_refs(w) == [(0, 'breakout_board_v01/BO-003'), (0, 'norlog_v02/N-012'), (0, 'ntc_sensor/0042')]
    w.flat.setChecked(False)
    assert [d for d, _r in tree_refs(w)] == [0, 1, 2]


def test_form_of_a_data_type(widget):
    from redvypr import item_types as it
    w = widget
    s_before = dict(items.ITEM_TYPES)
    try:
        defn = it.TypeDefinition(name='calypso_CMI1018', description='wind meter',
                                 fields={'heading_offset': {'kind': 'quantity', 'unit': 'deg',
                                                            'description': 'Mounting offset'}})
        storage = {}
        it.add_definition(storage, defn, valid_from=T0)
        w.redvypr.set_metadata_from_dict(storage)
        w.refresh()                                   # registers the type of the metadata
        cls = items.get_item_type('calypso_CMI1018')
        assert cls.ORIGIN == 'data'
        w.redvypr.add_item(cls(id='0011', heading_offset=7.0), valid_from=T0)
        w.refresh()
        w.set_item(w.redvypr.get_item('calypso_CMI1018/0011'))
        assert 'type defined as data' in w.title.text()
        edit, _base = w.form_fields['heading_offset']
        assert 'deg' in edit.placeholderText() and 'Mounting offset' in edit.toolTip()
    finally:
        items.ITEM_TYPES.clear()
        items.ITEM_TYPES.update(s_before)


def slot_rows(w):
    """{(owner, slot): row} of the free slot rows of the tree."""
    out = {}

    def walk(node):
        key = node.data(0, iw.ROLE_SLOT)
        if key is not None:
            out[tuple(key)] = node
        for i in range(node.childCount()):
            walk(node.child(i))
    for i in range(w.tree.topLevelItemCount()):
        walk(w.tree.topLevelItem(i))
    return out


def test_free_slots_assign_and_free(widget):
    w = widget
    owner = 'breakout_board_v01/BO-003'
    # ntc 0042 sits in ntc0 (below the board): the other slots are free rows below the board
    rows = slot_rows(w)
    assert sorted(slot for _o, slot in rows) == ['hf0', 'hf1', 'ntc1']
    assert all(o == owner for o, _s in rows) and rows[(owner, 'hf0')].text(4) == 'free'
    assert not w.btn_assign.isEnabled()
    w.tree.setCurrentItem(rows[(owner, 'ntc1')])
    assert w.btn_assign.isEnabled() and w.current_slot == (owner, 'ntc1') and w.current_ref is None
    # a sensor with a built_into link, a sensor in the store, one mounted elsewhere
    w.redvypr.add_item(items.Item(itemtype='ntc_sensor', id='0044', built_into='hf_sensor/1158'), valid_from=T0)
    w.redvypr.add_item(items.Item(itemtype='hf_sensor', id='1158'), valid_from=T0)
    w.refresh()
    # the dialog lists the unmounted items of the accepted types only
    all_items = w.redvypr.list_items()
    spec = items.get_item_type('breakout_board_v01').SLOTS['ntc1']
    dlg = iw.AssignSensorDialog(None, owner, 'ntc1', spec, all_items)
    refs = [dlg.list.item(i).data(iw.QtCore.Qt.ItemDataRole.UserRole) for i in range(dlg.list.count())]
    assert refs == ['ntc_sensor/0044']                    # not the mounted 0042, not the hf sensor
    assert 'belongs to hf_sensor/1158' in dlg.list.item(0).text()
    dlg.show_mounted.setChecked(True)
    refs = [dlg.list.item(i).data(iw.QtCore.Qt.ItemDataRole.UserRole) for i in range(dlg.list.count())]
    assert refs == ['ntc_sensor/0042', 'ntc_sensor/0044']
    dlg.search.setText('0042')
    assert dlg.list.count() == 1 and 'sits on breakout_board_v01/BO-003 / ntc0' in dlg.list.item(0).text()
    dlg.search.setText('')
    dlg.list.setCurrentRow(1)
    assert dlg.values()[0] == 'ntc_sensor/0044' and 'ntc_sensor/0044: parent - -> ' + owner in dlg.change.text()
    # assign: parent = the board, slot = the slot (the rows were rebuilt by the refresh)
    w.tree.setCurrentItem(slot_rows(w)[(owner, 'ntc1')])
    assert w.current_slot == (owner, 'ntc1')
    assert w.assign_sensor(item_ref='ntc_sensor/0044') is True
    ntc = w.redvypr.get_item('ntc_sensor/0044')
    assert (ntc.parent, ntc.slot, ntc.built_into) == (owner, 'ntc1', 'hf_sensor/1158')    # origin stays
    assert sorted(slot for _o, slot in slot_rows(w)) == ['hf0', 'hf1']
    # free the slot again: parent and slot are cleared, the origin stays
    w.free_slot('ntc_sensor/0044')
    ntc = w.redvypr.get_item('ntc_sensor/0044')
    assert (ntc.parent, ntc.slot, ntc.built_into) == (None, None, 'hf_sensor/1158')
    assert sorted(slot for _o, slot in slot_rows(w)) == ['hf0', 'hf1', 'ntc1']
    # nothing selected / unknown owner
    w.current_slot = None
    assert w.assign_sensor() is False and 'free slot' in w.status.text()
    assert w.assign_sensor('norlog_v02/nothing', 'x') is False


def test_free_button_follows_the_selection(widget):
    w = widget
    select(w, 'ntc_sensor/0042')
    assert w.btn_free.isEnabled()
    select(w, 'norlog_v02/N-012')
    assert not w.btn_free.isEnabled()
