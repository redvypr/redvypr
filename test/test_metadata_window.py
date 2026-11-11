"""The Metadata window: tabs Generic, Items, Item types, Calibrations (redvypr.widgets.redvypr_metadata_window)."""

import datetime
import math

import pytest
from PyQt6 import QtWidgets

import redvypr
from redvypr import items
from redvypr import metadata as md
from redvypr import metadata_sources as ms
from redvypr.devices.sensors.calibration import item_calibration as ic
from redvypr.devices.sensors.calibration import sensor_and_calibration_definitions as sd
from redvypr.devices.sensors.calibration.calibration_models import CalibrationNTC
from redvypr.widgets import redvypr_metadata_window as mw

UTC = datetime.timezone.utc
T0 = '2026-11-01T00:00:00+00:00'


def ntc(sn, date, model='ntc_sensor'):
    return CalibrationNTC(sn=sn, sensor_model=model, date=date,
                          coeff=[1 / 3950.0, 1 / 298.15 - math.log(1e4) / 3950.0])


@pytest.fixture
def window(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    s = {}
    items.add_item(s, items.Item(itemtype='ntc_sensor', id='N1'), valid_from=T0)
    items.add_item(s, sd.HfSensor(sn='HF1'), valid_from=T0)
    for cal in (ntc('N1', datetime.datetime(2025, 1, 1, tzinfo=UTC)),
                ntc('N1', datetime.datetime(2026, 6, 1, tzinfo=UTC)),
                ntc('N9', datetime.datetime(2026, 6, 1, tzinfo=UTC))):        # N9: no item
        (addr, value), = ic.calibration_metadict(cal).items()
        md.add_metadata_to_entries(md.create_metadata_dict(addr, value, valid_from=T0), s)
    lib = str(tmp_path / 'inventory.yaml')
    ms.save_metadata_library(lib, s)
    r = redvypr.Redvypr(hostname='mdwin')
    r.load_metadata_library(lib)
    r.set_metadata_from_dict({"temp @ d:'ctd_01'": {'unit': 'degC'}})
    w = mw.RedvyprMetadataWindow(redvypr_instance=r)
    yield r, w
    w.close()
    assert app is not None


def test_tabs_and_shared_bar(window):
    r, w = window
    assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == list(mw.TABS)
    # the items tab is embedded: no own library, git and time controls
    for b in (w.items.btn_load, w.items.btn_save_lib, w.items.btn_git, w.items.use_now):
        assert b.isHidden()
    assert 'inventory.yaml' in w.status.text()
    # generic: other metadata only, the special ones on request
    rows = w.generic.base_model._raw_data
    assert any(row.get('key') == 'unit' for row in rows)
    assert not any(row.get('key') == 'calibration' for row in rows)
    assert not any(items.parse_item_address(str(row.get('source_address'))) for row in rows)
    w.generic.show_library_entries.setChecked(True)
    assert any(row.get('key') == 'calibration' for row in w.generic.base_model._raw_data)
    # shared time reaches the tabs
    w.set_time(datetime.datetime(2025, 6, 1, tzinfo=UTC))
    assert not w.items.use_now.isChecked() and w.items.time().year == 2025
    w.set_time(None)
    assert w.items.use_now.isChecked()


def test_calibrations_tab(window):
    r, w = window
    c = w.calibrations
    assert c.table.rowCount() == 3
    rows = {(c.table.item(i, 1).text(), c.table.item(i, 4).text()[:10]):
            (c.table.item(i, 0).text(), c.table.item(i, 5).text()) for i in range(3)}
    assert rows[('N1', '2025-01-01')] == ('ntc_sensor/N1', '')
    assert rows[('N1', '2026-06-01')] == ('ntc_sensor/N1', 'yes')
    assert rows[('N9', '2026-06-01')] == ('—', 'yes')
    assert 'without sensor item' in c.status.text()
    # state time before the second calibration: the first one is valid
    w.set_time(datetime.datetime(2026, 1, 1, tzinfo=UTC))
    valid = {(c.table.item(i, 1).text(), c.table.item(i, 4).text()[:10]) for i in range(3)
             if c.table.item(i, 5).text() == 'yes'}
    assert ('N1', '2025-01-01') in valid and ('N9', '2026-06-01') not in valid
    w.set_time(None)
    # filters
    c.filter.setText('N9')
    assert c.apply_filter() == 1
    c.filter.setText('')
    c.only_unassigned.setChecked(True)
    assert c.apply_filter() == 1
    c.only_unassigned.setChecked(False)
    # create the missing sensor item for N9
    row = next(i for i in range(3) if c.table.item(i, 1).text() == 'N9')
    c.table.selectRow(row)
    assert c.create_sensor_item() == 'ntc_sensor/N9'
    assert r.get_item('ntc_sensor/N9') is not None
    assert 'without sensor item' not in c.status.text()
    # double click / "Show sensor": the Items tab shows it
    row = next(i for i in range(3) if c.table.item(i, 1).text() == 'N1')
    c.table.selectRow(row)
    c.show_sensor()
    assert w.tabs.tabText(w.tabs.currentIndex()) == 'Items' and w.items.current_ref == 'ntc_sensor/N1'
    # remove
    row = next(i for i in range(3) if c.table.item(i, 1).text() == 'N9')
    c.table.selectRow(row)
    assert c.remove_selected(confirm=lambda t: True)
    assert c.table.rowCount() == 2


def test_item_selection_reaches_the_types_tab(window):
    r, w = window
    w.show_item('hf_sensor/HF1')
    w._item_selected()
    assert w.types._item is not None and w.types._item.ref == 'hf_sensor/HF1'


def test_main_window_button(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from redvypr.redvypr_main_widget import redvyprMainWidget
    m = redvyprMainWidget(width=800, height=600, hostname='mdmain')
    assert m.redvypr_widget.edit_metadata_button.text() == 'Metadata'
    win = m.redvypr_widget.open_metadata_window('Calibrations')
    assert win.tabs.tabText(win.tabs.currentIndex()) == 'Calibrations'
    assert m.redvypr_widget.open_items_widget() is win and win.tabs.tabText(win.tabs.currentIndex()) == 'Items'
    actions = [a.text() for menu in m.menuBar().actions() if menu.menu() for a in menu.menu().actions()]
    assert '&Metadata ...' in actions and '&Query metadata ...' in actions
    win.close()
    m.hide()          # not close(): the main window ends the program (sys.exit)
    assert app is not None


def test_cross_links_between_items_and_types(window):
    r, w = window
    # item -> type: the link in the title of the item
    w.show_item('hf_sensor/HF1')
    assert 'href="type:hf_sensor"' in w.items.title.text()
    w.items._title_link('type:hf_sensor')
    assert w.tabs.tabText(w.tabs.currentIndex()) == 'Item types'
    assert w.types.current == 'hf_sensor' and w.types.list.currentItem().text(0) == 'hf_sensor'
    # type -> items: "Show items" filters the tab Items to the type
    assert w.types.btn_items.isEnabled()
    w.types.btn_items.click()
    assert w.tabs.tabText(w.tabs.currentIndex()) == 'Items'
    assert w.items.type_filter.currentData() == 'hf_sensor'
    refs = [w.items.tree.topLevelItem(i).text(0) for i in range(w.items.tree.topLevelItemCount())]
    assert refs == ['hf_sensor/HF1']
    # a type without definition (generic Item): message in the type editor
    r.add_item(items.Item(itemtype='undefined_type_q7', id='G'), valid_from=T0)
    assert not w.show_type('undefined_type_q7')
    assert 'not defined' in w.types.status.text()


def test_type_link_in_the_items_window_alone(window):
    r, _w = window
    from redvypr.widgets.redvypr_items_widget import RedvyprItemsWidget
    iw = RedvyprItemsWidget(redvypr_instance=r)
    iw.current_ref = 'ntc_sensor/N1'
    iw.set_item(r.get_item('ntc_sensor/N1'))
    iw._title_link('type:ntc_sensor')
    assert iw.types_widget is not None and iw.types_widget.current == 'ntc_sensor'
    iw.types_widget.close()
    iw.close()
