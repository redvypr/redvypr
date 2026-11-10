"""Sensor manager working with the items (step 3 of the sensor manager merge, design_items.rst)."""

import datetime
import math

import numpy as np
import pytest
import yaml
from PyQt6 import QtWidgets

import redvypr
from redvypr import items
from redvypr.devices.norlog import norlog_items  # noqa: F401
from redvypr.devices.sensors.calibration import item_calibration as ic
from redvypr.devices.sensors.calibration import sensor_and_calibration_definitions as sd
from redvypr.devices.sensors.calibration import sensor_calibration_manager as scm
from redvypr.devices.sensors.calibration.calibration_models import CalibrationNTC

UTC = datetime.timezone.utc
T0 = '2026-11-01T00:00:00+00:00'


@pytest.fixture
def manager():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    r = redvypr.Redvypr(hostname='mgritems')
    dev = r.add_device(devicemodulename=r.get_devicemodulename_from_str('sensor_calibration_manager'))
    yield r, dev
    assert app is not None


def hf_cal(sn='HF-0815', value=12.3):
    return sd.HeatflowClassicCalibration(calibration_date='2026-03-01T10:00:00', date_produced='2025-12-01T00:00:00',
                                         manufacturer_sn=sn, series='classic', calibration_HF_SI=value,
                                         calibration_data=[])


def test_heatflow_raw2data_and_units():
    cal = hf_cal(value=12.3)
    assert cal.unit == 'W m-2' and cal.unit_input == 'mV'
    assert np.isclose(cal.raw2data(0.5), 6.15)
    assert ic.unit_factor('V', 'mV') == 1000.0 and ic.unit_factor('mV', 'V') == 1e-3
    assert ic.unit_factor('', 'mV') == 1.0 and ic.unit_factor('V', 'Ohm') is None


def test_heatflow_conversion_with_items():
    # hf0 raw in V (profile raw_unit), calibration in W m-2 per mV: x1000, x12.3
    found = items.FoundItems(sensor=sd.HeatflowClassicSensor(sn='HF-0815'),
                             setup=items.SetupItem(id='p', channels={'hf0': {'cal': 'poly', 'raw_unit': 'V'}}))
    res = ic.apply_calibration({}, "hf0 @ i:'adc_brd' and di:'AA'", 0.0005, found=found,
                               calibrations=[hf_cal()], at_time=datetime.datetime(2026, 6, 1, tzinfo=UTC))
    assert res.ok, res.problems
    assert np.isclose(res.value, 0.5 * 12.3) and res.unit == 'W m-2' and 'V -> mV x1000' in res.scale_source


def test_manager_tab_import_and_apply(manager, tmp_path):
    r, dev = manager
    w = scm.RedvyprDeviceWidget(device=dev, redvypr=r)
    assert w.tabs.tabText(0).endswith('Sensors (items)')
    assert 'New Sensor List' not in [a.text() for a in w.add_menu.actions()]
    sensors = w.sensors_widget
    # import a sensor file: items in the metadata (key sensortype is read as item type)
    f = tmp_path / 'sensors.yaml'
    with open(f, 'w', encoding='utf-8') as fh:
        yaml.safe_dump_all([{'sensortype': 'heatflow_classic', 'sn': 'HF-1', 'name': 'hf one'},
                            {'itemtype': 'tar_sensor', 'sn': 'T-1'}], fh)
    got = sensors.import_sensors(str(f))
    assert [s.ref for s in got] == ['heatflow_classic/HF-1', 'tar_sensor/T-1']
    assert r.get_item('heatflow_classic/HF-1').name == 'hf one'
    assert sensors.table.rowCount() == 2
    # a calibration list applied to the system: calibrations in the metadata, missing sensor created
    dev.calibration_lists['Calibrations'] = [hf_cal('HF-2'),
                                             CalibrationNTC(sn='N-1', sensor_model='ntc_sensor',
                                                            date=datetime.datetime(2026, 1, 1, tzinfo=UTC),
                                                            coeff=[1 / 3950.0, 1 / 298.15 - math.log(1e4) / 3950.0])]
    report = dev.set_metadata_from_calibration_list('Calibrations')
    assert [(ref, new) for _c, ref, new in report] == [('heatflow_classic/HF-2', True), ('ntc_sensor/N-1', True)]
    back = dev.create_calibration_list_from_metadata('from_md')
    assert sorted(c.sn for c in back) == ['HF-2', 'N-1']
    sensors.refresh()
    rows = {sensors.table.item(i, 0).text(): sensors.table.item(i, 4).text() for i in range(sensors.table.rowCount())}
    assert rows['heatflow_classic/HF-2'] == '1' and rows['heatflow_classic/HF-1'] == '0'
    # the items window opens from the tab
    win = sensors.open_items_window()
    assert win.isVisible()
    win.close()
    # the fixed tab cannot be deleted
    w.delete_list(0)
    assert w.tabs.tabText(0).endswith('Sensors (items)')
    w.close()
