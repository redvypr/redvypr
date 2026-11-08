"""
Sensors of the sensor and calibration manager as items (step 6 of design_items.rst).
"""
import datetime

from redvypr import items
from redvypr import metadata as md
from redvypr.devices.sensors.calibration import sensor_and_calibration_definitions as sd

T0 = '2026-11-01T00:00:00+00:00'


def heatflow(sn='HF-1', **kw):
    return sd.HeatflowClassicSensor(name='hf', sn=sn, series='classic',
                                    date_produced=datetime.datetime(2025, 1, 1), **kw)


def into_storage(metadict, storage=None):
    storage = {} if storage is None else storage
    for addr, values in metadict.items():
        md.add_metadata_to_entries(md.create_metadata_dict(addr, values, valid_from=T0), storage)
    return storage


def test_sensor_is_item():
    s = heatflow()
    assert s.itemtype == 'HeatflowClassicSensor' and s.id == 'HF-1' and s.ref == 'HeatflowClassicSensor/HF-1'
    assert s.create_redvypr_address().to_address_string() == items.item_address('HeatflowClassicSensor', 'HF-1')
    assert items.get_item_type('HeatflowClassicSensor') is sd.HeatflowClassicSensor
    assert sd.SensorFactory.create({'sensortype': 'TarSensor', 'sn': 'T7',
                                    'date_produced': '2025-01-01T00:00:00'}).id == 'T7'
    # id given instead of sn
    assert sd.BaseSensor(id='B1').sn == 'B1'
    # without serial number: the address of older versions
    assert "i:'sensor'" in sd.BaseSensor().create_redvypr_address().to_address_string()


def test_one_key_per_field_and_back():
    s = heatflow(description='lab sensor')
    metadict = sd.sensor_metadict(s)
    (addr, values), = metadict.items()
    assert addr == s.address and values['description'] == 'lab sensor' and 'sensor' not in values
    storage = into_storage(metadict)
    back = items.get_item(storage, s.ref)
    assert isinstance(back, sd.HeatflowClassicSensor) and back.date_produced == s.date_produced
    assert back.series == 'classic' and back.sn == 'HF-1'
    assert [x.ref for x in sd.sensors_from_metadata(storage)] == ['HeatflowClassicSensor/HF-1']


def test_legacy_format_is_read():
    old = heatflow(sn='OLD-1')
    storage = into_storage({old.create_legacy_address().to_address_string(): {'sensor': old.model_dump(mode='json')}})
    found = sd.sensors_from_metadata(storage)
    assert [(x.sensortype, x.sn) for x in found] == [('HeatflowClassicSensor', 'OLD-1')]
    # stored as item as well: not twice
    into_storage(sd.sensor_metadict(old), storage)
    assert [(x.sensortype, x.sn) for x in sd.sensors_from_metadata(storage)] == [('HeatflowClassicSensor', 'OLD-1')]
    # a sensor without serial number is written in the old format
    nosn = sd.BaseSensor(name='x')
    (addr, values), = sd.sensor_metadict(nosn).items()
    assert "i:'sensor'" in addr and values['sensor']['name'] == 'x'


def test_sensor_in_tree():
    # a heat flux sensor of the manager on a breakout, found for a channel
    storage = {}
    items.add_item(storage, items.Item(itemtype='norlog_v02', id='N-1', deviceid='AA'), valid_from=T0)
    items.add_item(storage, items.Item(itemtype='breakout_board_v01', id='B-1', parent='norlog_v02/N-1'), valid_from=T0)
    items.add_item(storage, heatflow(parent='breakout_board_v01/B-1', slot='hf0'), valid_from=T0)
    found = items.get_items(storage, "hf0 @ i:'adc_brd' and di:'AA'")
    assert isinstance(found['sensor'], sd.HeatflowClassicSensor) and found['sensor'].sn == 'HF-1'
