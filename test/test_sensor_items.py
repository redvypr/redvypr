"""
Sensors of the sensor and calibration manager as items (step 6 of design_items.rst).
"""
import datetime

import pytest

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
    assert s.itemtype == 'heatflow_classic' and s.id == 'HF-1' and s.ref == 'heatflow_classic/HF-1'
    assert s.create_redvypr_address().to_address_string() == items.item_address('heatflow_classic', 'HF-1')
    assert items.get_item_type('heatflow_classic') is sd.HeatflowClassicSensor
    assert not hasattr(s, 'sensortype')
    # the factory takes the item type; a key 'sensortype' of a sensor file is read as item type
    t = sd.SensorFactory.create({'itemtype': 'tar_sensor', 'sn': 'T7'})
    assert isinstance(t, sd.TarSensor) and t.id == 'T7' and t.date_produced is None
    assert isinstance(sd.SensorFactory.create({'sensortype': 'heatflow_classic', 'sn': 'H2'}),
                      sd.HeatflowClassicSensor)
    # id given instead of sn
    assert sd.BaseSensor(id='B1').sn == 'B1'
    # without serial number: no address
    with pytest.raises(ValueError):
        sd.BaseSensor().create_redvypr_address()


def test_one_key_per_field_and_back():
    s = heatflow(description='lab sensor')
    metadict = sd.sensor_metadict(s)
    (addr, values), = metadict.items()
    assert addr == s.address and values['description'] == 'lab sensor' and 'sensor' not in values
    storage = into_storage(metadict)
    back = items.get_item(storage, s.ref)
    assert isinstance(back, sd.HeatflowClassicSensor) and back.date_produced == s.date_produced
    assert back.series == 'classic' and back.sn == 'HF-1'
    assert [x.ref for x in sd.sensors_from_metadata(storage)] == ['heatflow_classic/HF-1']


def test_sensor_in_tree():
    # a heat flux sensor of the manager on a breakout, found for a channel
    storage = {}
    items.add_item(storage, items.Item(itemtype='norlog_v02', id='N-1', deviceid='AA'), valid_from=T0)
    items.add_item(storage, items.Item(itemtype='breakout_board_v01', id='B-1', parent='norlog_v02/N-1'), valid_from=T0)
    items.add_item(storage, heatflow(parent='breakout_board_v01/B-1', slot='hf0'), valid_from=T0)
    found = items.get_items(storage, "hf0 @ i:'adc_brd' and di:'AA'")
    assert isinstance(found['sensor'], sd.HeatflowClassicSensor) and found['sensor'].sn == 'HF-1'
