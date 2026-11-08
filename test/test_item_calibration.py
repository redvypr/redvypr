"""
Conversion into units with items and calibrations (redvypr.devices.sensors.calibration.item_calibration).
"""
import datetime
import math

import numpy as np

from redvypr import items
from redvypr import metadata as md
from redvypr.devices.norlog import adc_setups, norlog_items
from redvypr.devices.sensors.calibration import item_calibration as ic
from redvypr.devices.sensors.calibration.calibration_models import CalibrationNTC, CalibrationLinearFactor

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 11, 1, tzinfo=UTC)
T1 = datetime.datetime(2026, 11, 10, tzinfo=UTC)
T2 = datetime.datetime(2026, 12, 1, tzinfo=UTC)
ADDR = "ntc0 @ i:'adc_brd' and di:'AA'"


def ntc_cal(sn='0042', beta=3950.0, date=datetime.datetime(2026, 10, 1, tzinfo=UTC), r0=10000.0):
    # beta model as Steinhart-Hart polynomial in ln R (descending): 1/T = 1/T0 + ln(R/R0)/B
    return CalibrationNTC(sn=sn, date=date, coeff=[1 / beta, 1 / 298.15 - math.log(r0) / beta])


def setup_storage(r1=10002.7):
    s = {}
    items.add_item(s, norlog_items.NorlogV02(id='N-1', deviceid='AA'), valid_from=T0)
    bo = norlog_items.BreakoutV01(id='BO-3', parent='norlog_v02/N-1')
    if r1 is not None:
        bo.R1 = items.Quantity(value=r1, unit='Ohm')
    items.add_item(s, bo, valid_from=T0)
    items.add_item(s, norlog_items.NtcSensor(id='0042', parent='breakout_v01/BO-3', slot='ntc0'), valid_from=T0)
    md.add_metadata_to_entries(md.create_metadata_dict("@di:'AA' and u:'x'", {'setup': {'adc_brd': 'hf_ntc_v01'}},
                                                       valid_from=T0), s)
    return s


def test_builtin_profile_item():
    assert adc_setups.get('hf_ntc_v01') is not None      # module registers its built-in profiles
    assert items.get_item({}, 'setup/hf_ntc_v01').channels['ntc0']['scale_ref'] == ['board', 'R1']
    assert items.list_items({}) == []
    found = items.get_items(setup_storage(), ADDR, at_time=T1)
    assert found['setup'].id == 'hf_ntc_v01' and found['sensor'].ref == 'ntc_sensor/0042'


def test_two_stages():
    s = setup_storage()
    x = 10000.0 / 10002.7                   # R = 10 kOhm: 25 degC
    res = ic.apply_calibration(s, ADDR, x, at_time=T1, calibrations=[ntc_cal()])
    assert res.ok and abs(res.value - 25.0) < 1e-9 and res.unit == 'degC'
    assert res.scale == 10002.7 and res.scale_source == 'R1 of breakout_v01/BO-3'
    # array
    res = ic.apply_calibration(s, ADDR, [x, x], at_time=T1, calibrations=[ntc_cal()])
    assert np.allclose(res.value, 25.0)
    # without R1: nominal R_ref of the profile, reported
    res = ic.apply_calibration(setup_storage(r1=None), ADDR, 1.0, at_time=T1, calibrations=[ntc_cal()])
    assert abs(res.value - 25.0) < 1e-9 and res.scale_source == 'nominal 10000' and not res.ok
    assert 'no R1 of the board' in res.problems[0]
    # no calibration / no sensor
    res = ic.apply_calibration(s, ADDR, x, at_time=T1, calibrations=[ntc_cal(sn='other')])
    assert res.value is None and 'no calibration of ntc_sensor/0042' in res.problems[-1]
    assert ic.apply_calibration(s, "ntc1 @ i:'adc_brd' and di:'AA'", x, at_time=T1,
                                calibrations=[]).problems == ['no sensor item for the channel']


def test_select_calibration_by_date_and_channel():
    old = ntc_cal(beta=3000.0, date=datetime.datetime(2025, 1, 1, tzinfo=UTC))
    new = ntc_cal(beta=3950.0, date=datetime.datetime(2026, 11, 5, tzinfo=UTC))
    assert ic.select_calibration([old, new], '0042', 'ntc0', T1) is new
    assert ic.select_calibration([old, new], '0042', 'ntc0', T0) is old
    assert ic.select_calibration([old, new], '0042', 'ntc0', datetime.datetime(2024, 1, 1, tzinfo=UTC)) is None
    a = CalibrationLinearFactor(sn='S', channel='a', coeff=1.0)
    b = CalibrationLinearFactor(sn='S', channel='b', coeff=2.0)
    assert ic.select_calibration([a, b], 'S', 'b_raw', T1) is b
    assert ic.select_calibration([a, b], 'S', 'c', T1) is None


def test_series_split_at_changes():
    s = setup_storage()
    cal = ntc_cal()
    # the NTC moves to slot ntc1 at T2: ntc0 has no sensor afterwards
    ntc = items.get_item(s, 'ntc_sensor/0042', at_time=T1)
    items.add_item(s, ntc, valid_from=T2, fields={'slot': 'ntc1'})
    t = np.array([T1.timestamp(), T1.timestamp() + 60, T2.timestamp() + 60])
    x = np.full(3, 10000.0 / 10002.7)
    values, unit, parts = ic.calibrate_series(s, ADDR, t, x, calibrations=[cal])
    assert unit == 'degC' and np.allclose(values[:2], 25.0) and np.isnan(values[2])
    assert any(p[2].problems == ['no sensor item for the channel'] for p in parts)


def test_calibrations_from_metadata_and_reader():
    s = setup_storage()
    cal = ntc_cal()
    addr = cal.create_redvypr_address().to_address_string()
    md.add_metadata_to_entries(md.create_metadata_dict(addr, {'calibration': cal.model_dump(mode='json')},
                                                       valid_from=T0), s)
    found = ic.calibrations_from_metadata(s)
    assert len(found) == 1 and found[0].sn == '0042'

    class Reader:
        def get_data(self, address, t_start=None, t_end=None, max_points=None):
            return {'t': np.array([T1.timestamp()]), 'data': np.array([10000.0 / 10002.7]), 'decimated': False,
                    'num': 1, 'streams': []}

        def combined_metadata(self):
            return s, []
    d = ic.get_data_calibrated(Reader(), ADDR)
    assert d['unit'] == 'degC' and abs(d['data'][0] - 25.0) < 1e-9 and d['raw'][0] < 1
