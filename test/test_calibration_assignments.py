"""
Calibration assignments (redvypr.devices.sensors.calibration.calibration_assignments).
"""
import datetime

import pytest

from redvypr.redvypr_address import RedvyprAddress
from redvypr.redvypr_datadict import create_redvypr_dict
from redvypr.devices.sensors.calibration import calibration_assignments as ca
from redvypr.devices.sensors.calibration.sensor_and_calibration_definitions import HfCalibration

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime.datetime(2026, 1, 10, tzinfo=UTC)
T2 = datetime.datetime(2026, 1, 20, tzinfo=UTC)
FILTER = "hf0 @ i:'adc' and di:'ABC'"


def hf_cal(date, coeff, sn='1158'):
    return HfCalibration(calibration_date=date, date_produced=date, manufacturer_sn=sn, calibration_HF_SI=coeff)


def packet(t, value=2.0, deviceid='ABC'):
    p = create_redvypr_dict(device='norlog', packetid='adc')
    p['_redvypr']['deviceid'] = deviceid
    p['_redvypr']['t'] = t.timestamp()
    p['hf0'] = value
    return p


def test_assignment_needs_a_calibration_and_roundtrips():
    with pytest.raises(ValueError):
        ca.CalibrationAssignment(filter=FILTER)
    a = ca.CalibrationAssignment(filter=FILTER, sn='1158', type='hf_sensor', result='hf0_W', raw_unit='V')
    assert ca.CalibrationAssignment.model_validate(a.model_dump()) == a
    assert a.value() == {'sn': '1158', 'type': 'hf_sensor', 'result': 'hf0_W', 'raw_unit': 'V'}
    assert 'hf0' in a.address


def test_apply_picks_the_calibration_valid_at_the_time_of_the_data():
    cals = [hf_cal(T0, 10.0), hf_cal(T2, 20.0)]
    a = ca.CalibrationAssignment(filter=FILTER, sn='1158', result='hf0_W')
    out, applied = ca.apply_assignments([a], packet(T1), cals)
    assert out['hf0'] == 2.0 and out['hf0_W'] == pytest.approx(20.0) and len(applied) == 1   # 2 mV x 10
    out, _ = ca.apply_assignments([a], packet(T2 + datetime.timedelta(days=1)), cals)
    assert out['hf0_W'] == pytest.approx(40.0)                                              # newer calibration
    # by uuid: exactly that one, whatever the time
    b = ca.CalibrationAssignment(filter=FILTER, uuid=cals[0].calibration_uuid)
    out, _ = ca.apply_assignments([b], packet(T2 + datetime.timedelta(days=1)), cals)
    assert out['hf0'] == pytest.approx(20.0)                                                # replaced, 2 x 10


def test_unit_conversion_and_non_matching_filters():
    cals = [hf_cal(T0, 10.0)]
    a = ca.CalibrationAssignment(filter=FILTER, sn='1158', raw_unit='V', result='hf0_W')
    out, _ = ca.apply_assignments([a], packet(T1, value=0.002), cals)      # 0.002 V = 2 mV
    assert out['hf0_W'] == pytest.approx(20.0)
    bad = ca.CalibrationAssignment(filter=FILTER, sn='1158', raw_unit='K')
    out, applied = ca.apply_assignments([bad], packet(T1), cals)
    assert applied == [] and out['hf0'] == 2.0
    # other device, other datakey, no calibration of that sn: untouched, the packet itself
    p = packet(T1, deviceid='XYZ')
    assert ca.apply_assignments([a], p, cals) == (p, [])
    other = ca.CalibrationAssignment(filter=FILTER, sn='9999')
    p = packet(T1)
    assert ca.apply_assignments([other], p, cals) == (p, [])
    # the input packet is not changed
    p = packet(T1)
    ca.apply_assignments([ca.CalibrationAssignment(filter=FILTER, sn='1158')], p, cals)
    assert p['hf0'] == 2.0


def test_store_and_rebuild_the_configuration_at_a_date():
    storage = {}
    a = ca.CalibrationAssignment(filter=FILTER, sn='1158', type='hf_sensor', result='hf0_W')
    n = ca.CalibrationAssignment(filter="ntc0 @ i:'adc' and di:'ABC'", sn='1158-ntc', type='ntc_sensor')
    assert len(ca.store_assignments(storage, [a], valid_from=T0)) == 1
    assert ca.store_assignments(storage, [a], valid_from=T1) == []             # unchanged: no new entry
    assert len(ca.store_assignments(storage, [a, n], valid_from=T1)) == 1
    a2 = a.model_copy(update={'sn': '1042'})
    assert len(ca.store_assignments(storage, [a2], valid_from=T2)) == 2        # a changed, n ended
    entries = storage[a.address]
    assert all(e['key'] == ca.KEY and e['constraints'].get('persistent') for e in entries)
    day = datetime.timedelta(days=1)
    assert ca.assignments_from_storage(storage, T0 - day) == []
    assert ca.assignments_from_storage(storage, T0 + day) == [a]
    assert ca.assignments_from_storage(storage, T1 + day) == sorted([a, n], key=lambda x: x.address)
    assert ca.assignments_from_storage(storage, T2 + day) == [a2]
    assert ca.assignments_from_storage(storage) == [a2]
    # the address of the entry is the filter without the run filters: found by persistent matching
    assert RedvyprAddress(a.address).datakey == 'hf0'


# --- configuration of the generic_sensor device, redvypr instance ---------------------------------

def test_redvypr_saves_and_rebuilds_the_assignments():
    import redvypr
    r = redvypr.Redvypr(hostname='assign')
    a = ca.CalibrationAssignment(filter=FILTER, sn='1158', type='hf_sensor', result='hf0_W')
    b = ca.CalibrationAssignment(filter="ntc0 @ i:'adc' and di:'ABC'", sn='1158-ntc')
    assert len(r.save_calibration_assignments([a], valid_from=T0, owner='gs1')) == 1
    assert len(r.save_calibration_assignments([b], valid_from=T0, owner='gs2')) == 1
    assert r.save_calibration_assignments([a], valid_from=T1, owner='gs1') == []
    day = datetime.timedelta(days=1)
    assert r.get_calibration_assignments(T0 + day, owner='gs1') == [a]
    assert r.get_calibration_assignments(T0 + day, owner='gs2') == [b]
    assert len(r.get_calibration_assignments(T0 + day)) == 2
    # gs1 drops its assignment: only its entry ends
    assert len(r.save_calibration_assignments([], valid_from=T2, owner='gs1')) == 1
    assert r.get_calibration_assignments(T2 + day, owner='gs1') == []
    assert r.get_calibration_assignments(T1 + day, owner='gs1') == [a]            # rebuilt for that date
    assert r.get_calibration_assignments(T2 + day, owner='gs2') == [b]


def test_generic_sensor_config_and_start():
    import queue
    import yaml
    from redvypr.devices.sensors.generic_sensor import generic_sensor as gs
    cal = hf_cal(T0, 10.0)
    cfg = gs.DeviceCustomConfig(calibration_assignments=[
        ca.CalibrationAssignment(filter=FILTER, sn='1158', result='hf0_W')], library_metadata={'x': []})
    dumped = cfg.model_dump()
    assert 'library_metadata' not in dumped                           # runtime only, not saved
    assert dumped['calibration_assignments'][0]['sn'] == '1158'
    assert gs.DeviceCustomConfig.model_validate(yaml.safe_load(yaml.safe_dump(dumped, sort_keys=False))
                                                ).calibration_assignments == cfg.calibration_assignments
    # the thread: the calibration comes from the library metadata given at the start
    from redvypr.devices.sensors.calibration import item_calibration
    storage = item_calibration.calibration_metadict(cal)
    config = dict(dumped, library_metadata={a: [{'key': 'calibration', 'value': e['calibration'], 'constraints': {}}]
                                            for a, e in storage.items()})
    dataq, inq, statq = queue.Queue(), queue.Queue(), queue.Queue()
    inq.put(packet(T1, value=3.0))
    inq.put(packet(T1, value=3.0, deviceid='OTHER'))                  # does not match
    inq.put({'_redvypr_command': {'command': 'stop', 'thread_uuid': 'T'}})
    gs.start({'thread_uuid': 'T'}, config=config, dataqueue=dataq, datainqueue=inq, statusqueue=statq)
    out = []
    while not dataq.empty():
        out.append(dataq.get())
    assert len(out) == 1 and out[0]['hf0'] == 3.0 and out[0]['hf0_W'] == pytest.approx(30.0)


def test_device_takes_the_calibrations_of_the_assignments_from_the_metadata():
    import types
    from redvypr.devices.sensors.generic_sensor import generic_sensor as gs
    from redvypr.devices.sensors.calibration import item_calibration
    mine, other = hf_cal(T0, 10.0), hf_cal(T0, 5.0, sn='0042')
    storage = {}
    for c in (mine, other):
        for a, e in item_calibration.calibration_metadict(c).items():
            storage[a] = [{'key': 'calibration', 'value': e['calibration'], 'constraints': {}}]
    cfg = gs.DeviceCustomConfig(calibration_assignments=[ca.CalibrationAssignment(filter=FILTER, sn='1158')])
    stub = types.SimpleNamespace(custom_config=cfg, redvypr=types.SimpleNamespace(_copy_metadata=lambda: storage))
    found = item_calibration.calibrations_from_metadata(gs.Device.assignment_metadata(stub))
    assert [c.sn for c in found] == ['1158']
