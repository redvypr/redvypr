"""Items window: calibrations and attachments of an item (step 2 of the sensor manager merge)."""

import datetime
import math
import os

import pytest
import yaml
from PyQt6 import QtWidgets

import redvypr
from redvypr import items
from redvypr import item_attachments as ia
from redvypr import metadata_sources as ms
from redvypr.devices.norlog import norlog_items  # noqa: F401
from redvypr.devices.sensors.calibration import item_calibration as ic
from redvypr.devices.sensors.calibration import sensor_and_calibration_definitions as sd
from redvypr.devices.sensors.calibration.calibration_models import CalibrationNTC
from redvypr.widgets import redvypr_items_widget as iw

UTC = datetime.timezone.utc
T0 = '2026-11-01T00:00:00+00:00'


def ntc_cal(sn, date, beta=3950.0, sensor_model='NA'):
    return CalibrationNTC(sn=sn, date=date, sensor_model=sensor_model,
                          coeff=[1 / beta, 1 / 298.15 - math.log(10000.0) / beta])


def write_calibrations(path, cals):
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump_all([c.model_dump(mode='json') for c in cals], f)


@pytest.fixture
def window(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    inv = str(tmp_path / 'inventory_norlog.yaml')
    s = {}
    items.add_item(s, items.Item(itemtype='ntc_sensor', id='0042'), valid_from=T0)
    items.add_item(s, sd.HeatflowClassicSensor(sn='0042', name='hf'), valid_from=T0)
    ms.save_item_library(inv, s)
    r = redvypr.Redvypr(hostname='calatt')
    r.load_item_library(inv)
    w = iw.RedvyprItemsWidget(redvypr_instance=r)
    yield r, w, tmp_path, inv
    w.close()
    assert app is not None


def select(w, ref):
    w.current_ref = ref
    w.set_item(w.redvypr.get_item(ref))


def test_import_calibrations_by_serial_number_and_type(window):
    r, w, tmp, inv = window
    f = str(tmp / 'cal.yaml')
    old = ntc_cal('0042', datetime.datetime(2026, 1, 1, tzinfo=UTC), beta=3000.0)
    new = ntc_cal('0042', datetime.datetime(2026, 10, 1, tzinfo=UTC))
    other = ntc_cal('0099', datetime.datetime(2026, 10, 1, tzinfo=UTC))      # no item yet: created (ntc)
    write_calibrations(f, [old, new, other])
    select(w, 'ntc_sensor/0042')
    report = w.import_calibration(f)
    assert [ref for _c, ref, _n in report] == ['ntc_sensor/0042', 'ntc_sensor/0042', 'ntc_sensor/0099']
    assert [n for _c, _r, n in report] == [False, False, True]
    assert r.get_item('ntc_sensor/0099') is not None
    assert w.calibrations.rowCount() == 2
    assert [w.calibrations.item(i, 1).text() for i in range(2)] == ['', 'yes']      # the newer one is valid
    # the heat flux sensor with the same serial number does not get the NTC calibrations
    select(w, 'heatflow_classic/0042')
    assert w.calibrations.rowCount() == 0
    # saved: new calibrations go into calibrations.yaml next to the inventory
    saved = r.save_item_libraries()
    cal_file = os.path.join(os.path.dirname(inv), 'calibrations.yaml')
    assert saved[cal_file] == 3 and 'calibrations:' not in open(inv, encoding='utf-8').read()
    lib = ms.load_item_library(cal_file)
    assert sorted(c.sn for c in ic.calibrations_from_metadata(lib)) == ['0042', '0042', '0099']
    # remove one
    select(w, 'ntc_sensor/0042')
    uuid0 = w.calibrations.item(0, 0).data(0x0100)
    assert w.remove_calibration(uuid0, confirm=lambda t: True)
    assert w.calibrations.rowCount() == 1


def test_calibration_without_serial_number_takes_the_selected_item(window):
    r, w, tmp, _inv = window
    cal = ntc_cal('NA', datetime.datetime(2026, 5, 1, tzinfo=UTC))
    report = ic.import_calibrations(r, [cal], item=r.get_item('ntc_sensor/0042'))
    assert report[0][1] == 'ntc_sensor/0042' and cal.sn == '0042' and cal.sensor_model == 'ntc_sensor'


def test_attachments(window):
    r, w, tmp, inv = window
    photo = tmp / 'photo.jpg'
    photo.write_bytes(b'\xff\xd8 not really a jpeg')
    select(w, 'heatflow_classic/0042')
    att = w.add_attachment(str(photo), description='mounted')
    assert att is not None and w.attachments.rowCount() == 1
    base = r.item_attachments_folder()
    assert base == os.path.join(os.path.dirname(inv), 'attachments')
    path = os.path.join(base, 'heatflow_classic', '0042', att.attachment_uuid, 'photo.jpg')
    assert os.path.exists(path)
    got = ia.attachments_of(r.get_item('heatflow_classic/0042'))
    assert [(a.file_name, a.description) for a in got] == [('photo.jpg', 'mounted')]
    # the form does not show the list, saving the form keeps it
    assert 'attachments' not in w.form_fields
    w.form_fields['name'][0].setText('hf renamed')
    w.save_item()
    assert len(ia.attachments_of(r.get_item('heatflow_classic/0042'))) == 1
    assert r.get_item('heatflow_classic/0042').name == 'hf renamed'
    # saved into the library and back
    r.save_item_libraries()
    lib = ms.load_item_library(inv)
    assert ia.attachments_of(items.get_item(lib, 'heatflow_classic/0042'))[0].sha256 == att.sha256
    # remove: entry and file
    assert w.remove_attachment(att.attachment_uuid, confirm=lambda t: True)
    assert not os.path.exists(path) and w.attachments.rowCount() == 0


def test_heatflow_calibration_creates_its_sensor(window):
    r, _w, _tmp, _inv = window
    cal = sd.HeatflowClassicCalibration(calibration_date='2026-03-01T10:00:00', date_produced='2025-12-01T00:00:00',
                                        manufacturer_sn='HF-0815', series='classic 50x50', calibration_HF_SI=12.3,
                                        calibration_data=[])
    assert cal.sensor_model == 'heatflow_classic' and cal.calibration_uuid.startswith('CALHFC_')
    (_c, ref, created), = ic.import_calibrations(r, [cal])
    assert ref == 'heatflow_classic/HF-0815' and created
    hf = r.get_item(ref)
    assert isinstance(hf, sd.HeatflowClassicSensor) and hf.series == 'classic 50x50'
    assert [ic.calibration_summary(c) for c in ic.calibrations_of_item(r._copy_metadata(), hf)] == \
        ['calibration_HF_SI = 12.3']
