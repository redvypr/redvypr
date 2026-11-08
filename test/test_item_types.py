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
    for table in (it.DATA_TYPES, it.TYPE_SOURCES, it._FOUND_IN, it._FILE_CACHE):
        table.clear()


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


def test_lookup_of_unknown_types_in_the_library_directory(tmp_path):
    # only the items are loaded; the definitions are found in the same directory (and subdirectories)
    import os
    import time
    import redvypr
    sub = tmp_path / 'types' / 'calypso'
    sub.mkdir(parents=True)
    with open(sub / 'CMI1018.yaml', 'w', encoding='utf-8') as f:
        yaml.safe_dump({'item_types': {'calypso_CMI1018': CALYPSO,
                                       'unused_type': {'description': 'not needed'}}}, f)
    s = {}
    items.add_item(s, items.Item(itemtype='calypso_CMI1018', id='0011', heading_offset=4.0), valid_from=T0)
    items.add_item(s, items.Item(itemtype='gadget_without_definition', id='G1'), valid_from=T0)
    inv = str(tmp_path / 'inventory.yaml')
    ms.save_item_library(inv, s)
    assert 'calypso_CMI1018' not in items.ITEM_TYPES
    lib = ms.load_item_library(inv)
    assert items.get_item_type('calypso_CMI1018').ORIGIN == 'data'
    assert 'unused_type' not in items.ITEM_TYPES              # only what is needed
    assert 'gadget_without_definition' not in items.ITEM_TYPES
    w = items.get_item(lib, 'calypso_CMI1018/0011', at_time=T1)
    assert w.heading_offset.unit == 'deg' and w.mpn == 'CMI1018'
    assert all(it.parse_itemtype_address(a) is None for a in lib)

    # a redvypr instance: item_type_paths elsewhere, resolved again after a change of the file
    items.ITEM_TYPES.pop('calypso_CMI1018')
    other = tmp_path / 'elsewhere'
    other.mkdir()
    os.replace(sub / 'CMI1018.yaml', other / 'CMI1018.yaml')
    r = redvypr.Redvypr(hostname='typelookup')
    r.item_type_paths = [str(other)]
    r.load_item_library(inv)
    assert items.get_item_type('calypso_CMI1018').ORIGIN == 'data'
    assert r.get_config().item_type_paths == [str(other)]
    # changed definition: read again on the next resolution
    items.ITEM_TYPES.pop('calypso_CMI1018')
    time.sleep(0.01)
    changed = dict(CALYPSO, description='changed')
    with open(other / 'CMI1018.yaml', 'w', encoding='utf-8') as f:
        yaml.safe_dump({'item_types': {'calypso_CMI1018': changed}}, f)
    os.utime(other / 'CMI1018.yaml', (time.time() + 5, time.time() + 5))
    assert 'calypso_CMI1018' in r.resolve_item_types()
    assert items.get_item_type('calypso_CMI1018').DEFINITION.description == 'changed'
