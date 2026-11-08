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
    r.add_item(items.Item(itemtype='breakout_v01', id='BO-003', parent='norlog_v02/N-012'), valid_from=T0)
    r.add_item(items.Item(itemtype='ntc_sensor', id='0042', parent='breakout_v01/BO-003', slot='ntc0'),
               valid_from=T0)
    w = iw.RedvyprItemsWidget(redvypr_instance=r)
    yield w
    w.close()
    assert app is not None


def tree_refs(w):
    out = []

    def walk(node, depth):
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
    assert tree_refs(w) == [(0, 'norlog_v02/N-012'), (1, 'breakout_v01/BO-003'), (2, 'ntc_sensor/0042')]
    select(w, 'breakout_v01/BO-003')
    assert w.current_ref == 'breakout_v01/BO-003' and 'parent' in w.form_fields
    w.form_fields['mpn'][0].setText('BRK-1')
    w.new_key.setText('R1')
    w.add_field()
    w.form_fields['R1'][0].setText('{"value": 10002.7, "unit": "Ohm"}')
    w.save_item()
    item = w.redvypr.get_item('breakout_v01/BO-003')
    assert item.mpn == 'BRK-1' and items.param_value(item.R1) == 10002.7   # dict or Quantity (breakout_v01 type)
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
    assert w.move(w.redvypr.get_item('ntc_sensor/0042'), 'breakout_v01/BO-003', 'ntc1', T1)
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
    assert [ref for _d, ref in tree_refs(w2)] == ['norlog_v02/N-012', 'breakout_v01/BO-003', 'ntc_sensor/0042']
    w2.close()
