"""
GUI of the calibration assignments (calibration_assignments_widget, Items window), offscreen.
"""
import datetime
import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

import redvypr
from redvypr import items
from redvypr.devices.sensors.calibration import calibration_assignments as ca
from redvypr.devices.sensors.calibration import calibration_assignments_widget as w
from redvypr.devices.sensors.generic_sensor import generic_sensor as gs
from redvypr.widgets import redvypr_items_widget as iw

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime.datetime(2026, 1, 10, tzinfo=UTC)
FILTER = "hf0 @ i:'adc' and di:'ABC'"


class Signal:
    def __init__(self):
        self.n = 0

    def emit(self):
        self.n += 1


def stub_device(r, name='gs1'):
    """A device with the interface of the generic_sensor for the widgets (nothing is started)."""
    dev = types.SimpleNamespace(name=name, redvypr=r, custom_config=gs.DeviceCustomConfig(),
                                config_changed_signal=Signal(), subscribed=0)
    dev.update_subscriptions = lambda: setattr(dev, 'subscribed', dev.subscribed + 1)
    dev.assignments_to_metadata = lambda valid_from=None: gs.Device.assignments_to_metadata(dev, valid_from)
    dev.assignments_from_metadata = lambda at_time=None: gs.Device.assignments_from_metadata(dev, at_time)
    return dev


def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_assignments_widget():
    qapp = app()
    r = redvypr.Redvypr(hostname='assignw')
    dev = stub_device(r)
    wd = w.CalibrationAssignmentsWidget(dev)
    a = ca.CalibrationAssignment(filter=FILTER, sn='1158', type='hf_sensor', result='hf0_W', raw_unit='V')
    wd.add(assignment=a)
    assert wd.table.rowCount() == 1 and dev.subscribed == 1 and dev.config_changed_signal.n == 1
    assert wd.table.item(0, 1).text() == 'sn 1158' and wd.table.item(0, 3).text() == 'hf0_W'
    wd.add(assignment=a.model_copy(update={'sn': '1042'}))             # same filter: replaced
    assert wd.table.rowCount() == 1 and dev.custom_config.calibration_assignments[0].sn == '1042'
    wd.table.selectRow(0)
    wd.edit(assignment=a)
    assert dev.custom_config.calibration_assignments[0].sn == '1158'
    # configuration -> metadata -> configuration at a date
    assert len(wd.save_to_metadata(valid_from=T0, ask=False)) == 1
    wd.add(assignment=ca.CalibrationAssignment(filter="ntc0 @ i:'adc' and di:'ABC'", uuid='CALNTC_1'))
    wd.save_to_metadata(valid_from=T1, ask=False)
    day = datetime.timedelta(days=1)
    assert len(wd.load_from_metadata(T0 + day, ask=False)) == 1 and wd.table.rowCount() == 1
    assert len(wd.load_from_metadata(T1 + day, ask=False)) == 2 and wd.table.rowCount() == 2
    wd.table.selectRow(0)
    assert wd.remove() and wd.table.rowCount() == 1
    wd.table.setCurrentCell(-1, -1)
    assert wd.remove() is False


def test_assignment_dialog_values_and_problems():
    qapp = app()
    d = w.AssignmentDialog(preset={'sn': '1158', 'type': 'hf_sensor'})
    assert 'filter' in d.problem()
    d.filter.setText(FILTER)
    assert d.problem() is None
    d.result.setText('hf0_W')
    a = d.assignment()
    assert a.sn == '1158' and a.type == 'hf_sensor' and a.result == 'hf0_W' and a.uuid is None
    d.sn.setText('')
    assert 'sn' in d.problem()
    d.uuid.setText('CALHFC_1')
    assert d.assignment().uuid == 'CALHFC_1'
    again = w.AssignmentDialog(assignment=a)
    assert again.filter.text() == a.address and again.assignment() == a


def test_items_window_applies_a_calibration_to_a_stream():
    qapp = app()
    r = redvypr.Redvypr(hostname='assignitems')
    r.add_item(items.Item(itemtype='hf_sensor', id='1158'), valid_from=T0)
    wd = iw.RedvyprItemsWidget(redvypr_instance=r)
    assert wd.apply_calibration_to_stream() is None                    # nothing selected
    wd.current_ref = 'hf_sensor/1158'
    assert wd.assignment_devices() == []
    assert wd.apply_calibration_to_stream() is None                    # no device
    dev = stub_device(r)
    r.devices.append({'device': dev})
    assert wd.assignment_devices() == [dev]
    a = ca.CalibrationAssignment(filter=FILTER, sn='1158', type='hf_sensor')
    assert wd.apply_calibration_to_stream(device=dev, assignment=a) == a
    assert dev.custom_config.calibration_assignments == [a] and dev.subscribed == 1
    wd.close()
    assert qapp is not None
