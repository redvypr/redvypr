"""Type editor of the Items window (redvypr.widgets.redvypr_item_types_widget)."""

import os

import pytest
import yaml
from PyQt6 import QtWidgets

import redvypr
from redvypr import items
from redvypr import item_types as it
from redvypr import metadata_sources as ms
from redvypr.devices.norlog import norlog_items
from redvypr.widgets import redvypr_items_widget as iw
from redvypr.widgets import redvypr_item_types_widget as tw

T0 = '2026-11-01T00:00:00+00:00'


@pytest.fixture
def setup(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    before = dict(items.ITEM_TYPES)
    for table in (it.DATA_TYPES, it.TYPE_SOURCES, it._FOUND_IN, it._FILE_CACHE):
        table.clear()
    inv = str(tmp_path / 'inventory_norlog.yaml')
    s = {}
    items.add_item(s, items.Item(itemtype='calypso_CMI1018', id='0011', manufacturer='Calypso Instruments',
                                 heading_offset={'value': 3.0, 'unit': 'deg'}, firmware='2.1'), valid_from=T0)
    items.add_item(s, norlog_items.NorlogV02(id='HW1', deviceid='HW1', sn='001'), valid_from=T0)
    ms.save_metadata_library(inv, s)
    r = redvypr.Redvypr(hostname='typeeditor')
    r.load_metadata_library(inv)
    w = tw.RedvyprItemTypesWidget(redvypr_instance=r)
    yield r, w, tmp_path
    w.close()
    items.ITEM_TYPES.clear()
    items.ITEM_TYPES.update(before)
    for table in (it.DATA_TYPES, it.TYPE_SOURCES, it._FOUND_IN, it._FILE_CACHE):
        table.clear()
    assert app is not None


def names(w):
    return [w.list.topLevelItem(i).text(0) for i in range(w.list.topLevelItemCount())]


def test_new_type_saved_in_file_next_to_library(setup):
    r, w, tmp = setup
    assert 'norlog_v02' in names(w)
    w.new_type()
    w.name.setText('gill_windsonic')
    w.description.setPlainText('Gill WindSonic ultrasonic wind sensor')
    row = w.add_field_row('heading_offset')
    w.fields.cellWidget(row, 1).setCurrentText('quantity')
    w.fields.item(row, 2).setText('deg')
    w.fields.item(row, 3).setText('Mounting offset to north')
    row = w.add_field_row('interface')
    w.fields.item(row, 5).setText('[RS232, RS422]')
    w._add_pair(w.defaults, 'manufacturer', 'Gill Instruments')
    path = str(tmp / 'item_types.yaml')
    assert w.file.currentText() == path                     # default: next to the library
    assert w.save(), w.status.text()
    assert 'gill_windsonic' in names(w)
    cls = items.get_item_type('gill_windsonic')
    assert cls.ORIGIN == 'data' and cls.model_fields['heading_offset'].description == 'Mounting offset to north'
    g = cls(id='G1', heading_offset=5)
    assert g.heading_offset.unit == 'deg' and g.manufacturer == 'Gill Instruments'
    with pytest.raises(ValueError):
        cls(id='G2', interface='USB')
    data = yaml.safe_load(open(path, encoding='utf-8'))
    assert "@d:'gill_windsonic' and i:'itemtype'" in data['item_types']
    assert it.TYPE_SOURCES['gill_windsonic'] == os.path.abspath(path)
    # the same name again as new type: refused
    w.new_type()
    w.name.setText('gill_windsonic')
    assert not w.save()
    assert 'exists already' in w.status.text()


def test_type_from_item_and_edit_again(setup):
    r, w, tmp = setup
    item = r.get_item('calypso_CMI1018/0011')
    assert type(item) is items.Item                          # no definition yet
    w.set_item(item)
    w.type_from_item(item)
    assert w.name.text() == 'calypso_CMI1018' and w.name.isReadOnly()
    rows = {w._cell(w.fields, i, 0): (w._cell(w.fields, i, 1), w._cell(w.fields, i, 2))
            for i in range(w.fields.rowCount())}
    assert rows['heading_offset'] == ('quantity', 'deg') and rows['firmware'] == ('str', '')
    assert w._cell(w.defaults, 0, 0) == 'manufacturer'
    assert w.save(), w.status.text()
    got = r.get_item('calypso_CMI1018/0011')
    assert type(got).ORIGIN == 'data' and got.heading_offset.unit == 'deg'
    # edit: description, new revision with a renamed field; history stays in the file
    w.set_type('calypso_CMI1018')
    w.description.setPlainText('Calypso wind meter')
    w.revision.setValue(2)
    w._add_pair(w.renamed, 'firmware', 'fw_version')
    for i in range(w.fields.rowCount()):
        if w._cell(w.fields, i, 0) == 'firmware':
            w.fields.item(i, 0).setText('fw_version')
    assert w.save(), w.status.text()
    path = it.TYPE_SOURCES['calypso_CMI1018']
    entries = ms.read_library_storage(path)[it.itemtype_address('calypso_CMI1018')]
    assert len([e for e in entries if e['key'] == 'fields']) == 2           # history
    old = items.item_from_fields('calypso_CMI1018', 'X', {'firmware': '1.0', 'type_revision': 1})
    assert old.fw_version == '1.0'


def test_extend_python_type_and_errors(setup):
    r, w, tmp = setup
    w.set_type('norlog_v02')
    assert 'Python' in w.title.text() and not w.base.isEnabled()
    assert 'deviceid' in w.inherited.text()
    w.add_field_row('firmware')
    assert w.save(str(tmp / 'item_types.yaml')), w.status.text()
    cls = items.get_item_type('norlog_v02')
    assert issubclass(cls, norlog_items.NorlogV02) and 'firmware' in cls.model_fields
    assert 'norlog_v02' in [w.list.topLevelItem(i).text(0) for i in range(w.list.topLevelItemCount())
                            if w.list.topLevelItem(i).text(1) == 'Python + data']
    # invalid field name, invalid file
    w.add_field_row('bad name')
    assert not w.save()
    assert 'field name' in w.status.text()
    w.fields.removeRow(w.fields.rowCount() - 1)
    assert not w.save(str(tmp / 'types.txt'))


def test_types_button_in_items_window(setup):
    r, _w, _tmp = setup
    items_window = iw.RedvyprItemsWidget(redvypr_instance=r)
    t = items_window.open_types()
    assert isinstance(t, tw.RedvyprItemTypesWidget)
    assert items_window.open_types() is t
    t.close()
    items_window.close()
