"""Item types defined as data (redvypr.item_types)."""

import pytest
import yaml

from redvypr import items
from redvypr import item_types as it
from redvypr import metadata_sources as ms
from redvypr.devices.norlog import norlog_items

T0 = '2026-11-01T00:00:00+00:00'
T1 = '2026-11-10T00:00:00+00:00'
T2 = '2026-12-01T00:00:00+00:00'

CALYPSO = {
    'description': 'Calypso Instruments ultrasonic wind meter CMI1018',
    'defaults': {'manufacturer': 'Calypso Instruments', 'mpn': 'CMI1018'},
    'fields': {
        'heading_offset': {'kind': 'quantity', 'unit': 'deg', 'description': 'Mounting offset to north'},
        'interface': {'kind': 'str', 'choices': ['NMEA0183', 'RS485']},
        'firmware': {'kind': 'str'},
    },
}


@pytest.fixture(autouse=True)
def clean_registry():
    before = dict(items.ITEM_TYPES)
    yield
    items.ITEM_TYPES.clear()
    items.ITEM_TYPES.update(before)
    it.DATA_TYPES.clear()


def test_short_form_library_and_model(tmp_path):
    path = str(tmp_path / 'item_types.yaml')
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump({'item_types': {'calypso_CMI1018': CALYPSO}}, f)
    lib = ms.load_item_library(path)
    assert list(lib) == [it.itemtype_address('calypso_CMI1018')]
    cls = items.get_item_type('calypso_CMI1018')
    assert cls.ORIGIN == 'data' and it.type_origin('calypso_CMI1018') == 'data'
    assert cls.model_fields['heading_offset'].description == 'Mounting offset to north'
    w = cls(id='0011', heading_offset=12.5)
    assert w.itemtype == 'calypso_CMI1018'
    assert w.heading_offset.value == 12.5 and w.heading_offset.unit == 'deg'
    assert w.manufacturer == 'Calypso Instruments' and w.mpn == 'CMI1018'
    with pytest.raises(ValueError):
        cls(id='x', heading_offset={'value': 1, 'unit': 'rad'})
    with pytest.raises(ValueError):
        cls(id='x', interface='BLE')
    # saved again: storage format in the section item_types, loaded the same
    out = str(tmp_path / 'again.yaml')
    ms.save_item_library(out, lib)
    text = open(out, encoding='utf-8').read()
    assert 'item_types:' in text and 'items:' not in text
    items.ITEM_TYPES.pop('calypso_CMI1018')
    ms.load_item_library(out)
    assert items.get_item_type('calypso_CMI1018').ORIGIN == 'data'


def test_items_of_a_data_type_in_storage():
    s = {}
    it.add_definition(s, it.TypeDefinition(name='calypso_CMI1018', **CALYPSO), valid_from=T0)
    assert it.register_from_storage(s) == ['calypso_CMI1018']
    cls = items.get_item_type('calypso_CMI1018')
    items.add_item(s, cls(id='0011', heading_offset=3.0, parent='norlog_v02/A'), valid_from=T0)
    got = items.get_item(s, 'calypso_CMI1018/0011', at_time=T1)
    assert type(got) is cls and got.heading_offset.unit == 'deg'
    # library kinds: the definition and the item
    kinds = {k for k, _e in ms.library_entries(s).values()}
    assert kinds == {'item', 'itemtype'}


def test_definition_extends_python_type():
    defn = it.TypeDefinition(name='breakout_board_v01', description='Breakout board',
                             fields={'pcb_batch': {'kind': 'str', 'description': 'PCB batch'}})
    assert it.register_definitions({'breakout_board_v01': defn}) == ['breakout_board_v01']
    cls = items.get_item_type('breakout_board_v01')
    assert issubclass(cls, norlog_items.BreakoutBoardV01)
    assert 'R1' in cls.model_fields and 'pcb_batch' in cls.model_fields
    b = cls(id='BO-001', R1={'value': 9995.5, 'unit': 'Ohm'}, pcb_batch='A')
    assert items.param_value(b.R1) == 9995.5
    # registered again (e.g. library loaded twice): still based on the Python type
    it.register_definitions({'breakout_board_v01': defn})
    assert issubclass(items.get_item_type('breakout_board_v01'), norlog_items.BreakoutBoardV01)


def test_base_and_renamed_migration():
    base = it.TypeDefinition(name='anemometer', fields={'height': {'kind': 'quantity', 'unit': 'm'}})
    sub = it.TypeDefinition(name='calypso_x', base='anemometer', revision=2, renamed={'fw': 'firmware'},
                            fields={'firmware': {'kind': 'str'}})
    assert sorted(it.register_definitions({'calypso_x': sub, 'anemometer': base})) == ['anemometer', 'calypso_x']
    cls = items.get_item_type('calypso_x')
    assert issubclass(cls, items.get_item_type('anemometer'))
    old = items.item_from_fields('calypso_x', 'C1', {'fw': '1.2', 'height': 10, 'type_revision': 1})
    assert old.firmware == '1.2' and old.height.unit == 'm'


def test_definition_history_now_wins():
    s = {}
    it.add_definition(s, it.TypeDefinition(name='gadget', description='old'), valid_from=T0)
    it.add_definition(s, it.TypeDefinition(name='gadget', description='new',
                                           fields={'size': {'kind': 'float'}}), valid_from=T1)
    assert it.definitions_from_storage(s, at_time='2026-11-05T00:00:00+00:00')['gadget'].description == 'old'
    d = it.definitions_from_storage(s, at_time=T2)['gadget']
    assert d.description == 'new' and 'size' in d.fields


def test_invalid_kind_is_rejected():
    with pytest.raises(ValueError):
        it.TypeDefinition(name='x', fields={'a': {'kind': 'complex'}})
