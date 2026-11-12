"""
Slot suggestions of the item types (Item.SLOTS, redvypr.items.slot_options, MoveItemDialog), offscreen.
"""
import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

import redvypr
from redvypr import items
from redvypr import item_types as it
from redvypr.devices.norlog import norlog_items  # noqa: registers breakout_board_v01
from redvypr.widgets import redvypr_items_widget as iw

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 11, 1, tzinfo=UTC)


def make_items():
    board = items.get_item_type('breakout_board_v01')(id='BO-001')
    hf = items.Item(itemtype='hf_sensor', id='1158', parent=board.ref, slot='hf0')
    ntc = items.Item(itemtype='ntc_sensor', id='1158-ntc', parent=hf.ref)
    return board, hf, ntc


def test_slot_options_from_the_board():
    board, hf, ntc = make_items()
    all_items = [board, hf, ntc]
    # the sensor on the board: heat flux slots only, hf0 is taken by the sensor itself (excluded)
    opts = items.slot_options(all_items, board.ref, 'hf_sensor', exclude_ref=hf.ref)
    assert [o['slot'] for o in opts] == ['hf0', 'hf1']
    assert all(o['occupied_by'] is None for o in opts)
    assert opts[0]['label'].startswith('heat flux 0')
    # the NTC (parent: the sensor): the slots of the board, ntc only; the sensor has none of its own
    opts = items.slot_options(all_items, hf.ref, 'ntc_sensor', exclude_ref=ntc.ref)
    assert [o['slot'] for o in opts] == ['ntc0', 'ntc1']
    assert {o['owner'] for o in opts} == {board.ref}


def test_slot_options_occupied_and_empty():
    board, hf, ntc = make_items()
    ntc2 = items.Item(itemtype='ntc_sensor', id='0042', parent=board.ref, slot='ntc0')
    all_items = [board, hf, ntc, ntc2]
    opts = {o['slot']: o for o in items.slot_options(all_items, hf.ref, 'ntc_sensor', exclude_ref=ntc.ref)}
    assert opts['ntc0']['occupied_by'] == ntc2.ref and opts['ntc1']['occupied_by'] is None
    # a sensor in a slot of its own sitting below another item (hf_sensor/1158 in hf0) is found as occupant
    opts = {o['slot']: o for o in items.slot_options(all_items, board.ref, 'hf_sensor')}
    assert opts['hf0']['occupied_by'] == hf.ref
    # no parent, unknown parent, parent without slots: no suggestions
    assert items.slot_options(all_items, None, 'ntc_sensor') == []
    assert items.slot_options(all_items, 'norlog_v02/x', 'ntc_sensor') == []
    assert items.slot_options([hf], hf.ref, 'ntc_sensor') == []


def test_slots_from_a_type_definition():
    defn = it.TypeDefinition(name='my_board', slots={'a': {'accepts': ['ntc_sensor'], 'label': 'A'}, 'b': {}})
    it.register_definitions({'my_board': defn})
    try:
        assert items.get_item_type('my_board').SLOTS['a']['label'] == 'A'
        board = items.get_item_type('my_board')(id='1')
        ntc = items.Item(itemtype='ntc_sensor', id='n1')
        hf = items.Item(itemtype='hf_sensor', id='h1')
        assert [o['slot'] for o in items.slot_options([board, ntc], board.ref, 'ntc_sensor')] == ['a', 'b']
        assert [o['slot'] for o in items.slot_options([board, hf], board.ref, 'hf_sensor')] == ['b']
        # a definition of the Python type adds to its slots
        extra = it.TypeDefinition(name='breakout_board_v01', slots={'x': {'label': 'extra'}})
        it.register_definitions({'breakout_board_v01': extra})
        slots = items.get_item_type('breakout_board_v01').SLOTS
        assert set(slots) == {'hf0', 'ntc0', 'hf1', 'ntc1', 'x'}
        # storage round trip keeps the slots
        storage = it.add_definition({}, defn)
        assert it.definitions_from_storage(storage)['my_board'].slots['a']['label'] == 'A'
        assert it.short_form_to_storage({'my_board': {'slots': {'a': {'label': 'A'}}}})
    finally:
        items.ITEM_TYPES.pop('my_board', None)
        it.DATA_TYPES.pop('my_board', None)
        # back to the Python class
        items.ITEM_TYPES['breakout_board_v01'] = norlog_items.BreakoutBoardV01
        it.DATA_TYPES.pop('breakout_board_v01', None)


def test_move_dialog_suggests_slots():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    board, hf, ntc = make_items()
    r = redvypr.Redvypr(hostname='slots')
    for i in (board, hf, ntc):
        r.add_item(i, valid_from=T0)
    all_items = r.list_items()
    ntc = r.get_item(ntc.ref)
    dlg = iw.MoveItemDialog(None, ntc, all_items, all_items=all_items)      # parent: the sensor
    entries = [dlg.slot.itemData(i) for i in range(dlg.slot.count())]
    assert entries == ['', 'ntc0', 'ntc1']
    dlg.slot.setCurrentIndex(entries.index('ntc1'))
    assert dlg.values()[:2] == (hf.ref, 'ntc1')
    # the board as parent: the slot offers are those of the board for this type (none for ntc: both ntc)
    labels = [dlg.parent_ref.itemData(i) for i in range(dlg.parent_ref.count())]
    dlg.parent_ref.setCurrentIndex(labels.index(board.ref))
    assert [dlg.slot.itemData(i) for i in range(dlg.slot.count())] == ['', 'ntc0', 'ntc1']
    # a typed slot stays possible; without parent no suggestions
    dlg.slot.setEditText('J2.3-4')
    assert dlg.values()[1] == 'J2.3-4'
    dlg.parent_ref.setCurrentIndex(0)
    assert dlg.slot.count() == 1 and dlg.slot.currentText() == 'J2.3-4'
    # occupied slot: hint
    ntc2 = items.Item(itemtype='ntc_sensor', id='0042', parent=board.ref, slot='ntc0')
    dlg2 = iw.MoveItemDialog(None, ntc, all_items + [ntc2], all_items=all_items + [ntc2])
    dlg2.slot.setEditText('ntc0')
    assert ntc2.ref in dlg2.slot_hint.text()
    assert app is not None
