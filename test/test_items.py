"""
Items in the metadata (redvypr.items, design: doc/source/design_items.rst).
"""
import typing

import pytest

from redvypr import items
from redvypr.redvypr_address import RedvyprAddress

T0 = '2026-11-01T00:00:00+00:00'
T1 = '2026-11-10T00:00:00+00:00'
T2 = '2026-12-01T00:00:00+00:00'


@items.register_item_type
class BreakoutTest(items.Item):
    ITEMTYPE: typing.ClassVar[str] = 'breakout_test'
    REVISION: typing.ClassVar[int] = 2
    R1: typing.Optional[items.Quantity] = None

    @classmethod
    def migrate(cls, fields, from_revision):
        # revision 1 stored the reference resistor as 'r_ref' (a number in Ohm)
        if from_revision < 2 and 'r_ref' in fields:
            fields = dict(fields)
            fields['R1'] = {'value': fields.pop('r_ref'), 'unit': 'Ohm'}
        return fields


def tree(storage):
    """norlog N-012 (deviceid 0xA1B2) <- breakout BO-003 <- NTC 0042 in slot ntc0, HF-17 in slot hf0."""
    items.add_item(storage, items.Item(itemtype='norlog_v02', id='N-012', deviceid='0xA1B2'), valid_from=T0)
    items.add_item(storage, BreakoutTest(id='BO-003', parent='norlog_v02/N-012',
                                         R1=items.Quantity(value=10002.7, unit='Ohm')), valid_from=T0)
    items.add_item(storage, items.Item(itemtype='ntc_sensor', id='0042', parent='breakout_test/BO-003',
                                       slot='ntc0', mpn='NTC-2k'), valid_from=T0)
    items.add_item(storage, items.Item(itemtype='hf_sensor', id='HF-17', parent='breakout_test/BO-003',
                                       slot='hf0'), valid_from=T0)


def test_refs_and_addresses():
    assert items.make_ref('ntc_sensor', '0042') == 'ntc_sensor/0042'
    assert items.parse_ref('cable/A/7') == ('cable', 'A/7')
    addr = items.item_address('breakout_v01', 'BO-003')
    assert items.parse_item_address(addr) == ('breakout_v01', 'BO-003')
    assert RedvyprAddress(addr).packetid == 'item'
    assert items.parse_item_address("temp @ d:'x' and si:'y'") is None
    for bad in ("x'y", '', None):
        with pytest.raises(items.ItemError):
            items.item_address('t', bad)
    with pytest.raises(items.ItemError):
        items.parse_ref('noslash')


def test_one_key_per_field_and_history():
    storage = {}
    item = BreakoutTest(id='BO-003', mpn='BRK', R1=items.Quantity(value=10000, unit='Ohm'))
    assert items.add_item(storage, item, valid_from=T0)
    assert not items.add_item(storage, item, valid_from=T0)            # same again: nothing new
    keys = {e['key'] for e in storage[item.address]}
    assert keys == {'mpn', 'R1', 'type_revision'}
    # R1 measured again: only R1 gets a new entry
    item2 = item.model_copy(update={'R1': items.Quantity(value=10002.7, unit='Ohm', method='4-wire')})
    assert items.add_item(storage, item2, valid_from=T1)
    old = items.get_item(storage, 'breakout_test/BO-003', at_time='2026-11-05T00:00:00Z')
    new = items.get_item(storage, 'breakout_test/BO-003', at_time=T2)
    assert isinstance(new, BreakoutTest) and old.R1.value == 10000 and new.R1.value == 10002.7
    assert new.R1.method == '4-wire' and new.mpn == 'BRK' and new.type_revision == 2
    hist = [e for e in items.get_item_history(storage, 'breakout_test/BO-003') if e['key'] == 'R1']
    assert len(hist) == 2 and hist[0]['constraints']['valid_until'] == T1
    # before it existed
    assert items.get_item(storage, 'breakout_test', 'BO-003', at_time='2026-10-01T00:00:00Z') is None


def test_unknown_type_and_extra_fields():
    storage = {}
    items.add_item(storage, items.Item(itemtype='gadget', id='1', colour='red'), valid_from=T0)
    item = items.get_item(storage, 'gadget/1')
    assert type(item) is items.Item and item.colour == 'red' and item.type_revision == 1


def test_revision_migration_and_newer_revision():
    storage = {}
    addr = items.item_address('breakout_test', 'OLD')
    # an item written with revision 1 of the type
    from redvypr import metadata as md
    md.add_metadata_to_entries(md.create_metadata_dict(addr, {'r_ref': 9999.0, 'type_revision': 1},
                                                       valid_from=T0), storage)
    item = items.get_item(storage, 'breakout_test/OLD')
    assert item.R1.value == 9999.0 and item.R1.unit == 'Ohm'
    # saved again: written with revision 2, the old key ends, history kept
    items.add_item(storage, item, valid_from=T1)
    saved = items.get_item(storage, 'breakout_test/OLD', at_time=T2)
    assert saved.type_revision == 2 and saved.R1.value == 9999.0 and not hasattr(saved, 'r_ref')
    assert items.get_item(storage, 'breakout_test/OLD', at_time='2026-11-05T00:00:00Z').R1.value == 9999.0
    # newer revision than the code knows: read with a warning, not written back
    md.add_metadata_to_entries(md.create_metadata_dict(items.item_address('breakout_test', 'NEW'),
                                                       {'type_revision': 5, 'future': 1}, valid_from=T0), storage)
    new = items.get_item(storage, 'breakout_test/NEW')
    assert new.future == 1
    with pytest.raises(items.ItemError, match='newer'):
        items.add_item(storage, new)


def test_list_children_uuid():
    storage = {}
    tree(storage)
    items.add_item(storage, items.Item(itemtype='cable', id='C1', uuid='u-1'), valid_from=T1)
    assert [i.ref for i in items.list_items(storage, at_time=T2)] == [
        'breakout_test/BO-003', 'cable/C1', 'hf_sensor/HF-17', 'norlog_v02/N-012', 'ntc_sensor/0042']
    assert [i.ref for i in items.list_items(storage, at_time='2026-11-05T00:00:00Z', itemtype='cable')] == []
    assert sorted(c.ref for c in items.children(storage, 'breakout_test/BO-003')) == [
        'hf_sensor/HF-17', 'ntc_sensor/0042']
    assert items.find_by_uuid(storage, 'u-1', at_time=T2).ref == 'cable/C1'


def test_cleared_field_ends():
    storage = {}
    items.add_item(storage, items.Item(itemtype='gadget', id='1', comment='old', mpn='M'), valid_from=T0)
    items.add_item(storage, items.Item(itemtype='gadget', id='1', mpn='M'), valid_from=T1)
    assert items.get_item(storage, 'gadget/1', at_time=T2).comment is None
    assert items.get_item(storage, 'gadget/1', at_time='2026-11-05T00:00:00Z').comment == 'old'
    # writing single fields does not end the others
    items.add_item(storage, items.Item(itemtype='gadget', id='1'), valid_from=T2, fields={'batch': 'B7'})
    later = items.get_item(storage, 'gadget/1', at_time='2026-12-02T00:00:00Z')
    assert later.mpn == 'M' and later.batch == 'B7'


def test_get_items_tree_and_move():
    storage = {}
    tree(storage)
    found = items.get_items(storage, "ntc0 @ i:'adc_brd' and di:'0xA1B2'")
    assert {k: v.ref for k, v in found.items()} == {
        'device': 'norlog_v02/N-012', 'board': 'breakout_test/BO-003', 'sensor': 'ntc_sensor/0042'}
    # datakey with suffix
    assert items.get_items(storage, "ntc0_raw @ i:'adc_brd' and di:'0xA1B2'")['sensor'].ref == 'ntc_sensor/0042'
    assert items.get_items(storage, "hf0 @ i:'adc_brd' and di:'0xA1B2'")['sensor'].ref == 'hf_sensor/HF-17'
    # unknown channel, other device
    assert set(items.get_items(storage, "temp @ i:'adc_brd' and di:'0xA1B2'")) == {'device'}
    assert items.get_items(storage, "ntc0 @ i:'adc_brd' and di:'0xFFFF'") == {}
    # the NTC moves to slot ntc1 on 1 Dec: before the old, after the new assignment
    ntc = items.get_item(storage, 'ntc_sensor/0042')
    items.add_item(storage, ntc.model_copy(update={'slot': 'ntc1'}), valid_from=T2, fields={'slot': 'ntc1'})
    assert items.get_items(storage, "ntc0 @ i:'adc_brd' and di:'0xA1B2'", at_time=T1)['sensor'].id == '0042'
    assert 'sensor' not in items.get_items(storage, "ntc0 @ i:'adc_brd' and di:'0xA1B2'", at_time=T2)
    assert items.get_items(storage, "ntc1 @ i:'adc_brd' and di:'0xA1B2'", at_time=T2)['sensor'].id == '0042'


def test_get_items_explicit_and_loops():
    storage = {}
    tree(storage)
    from redvypr import metadata as md
    md.add_metadata_to_entries(md.create_metadata_dict(
        "temp @ d:'ctd_01'", {'items': {'sensor': 'ntc_sensor/0042', 'x': 'nope/1'}}, valid_from=T0), storage)
    found = items.get_items(storage, "temp @ d:'ctd_01'")
    assert {k: v.ref for k, v in found.items()} == {'sensor': 'ntc_sensor/0042'}
    # parent loop does not hang
    items.add_item(storage, items.Item(itemtype='a', id='1', parent='b/1', deviceid='LOOP'), valid_from=T0)
    items.add_item(storage, items.Item(itemtype='b', id='1', parent='a/1', slot='x'), valid_from=T0)
    assert items.get_items(storage, "x @ di:'LOOP'")['sensor'].ref == 'b/1'


def test_redvypr_instance():
    import redvypr
    r = redvypr.Redvypr(hostname='itemtest')
    assert r.add_item(items.Item(itemtype='gadget', id='9', mpn='M', comment='c'), valid_from=T0)
    assert not r.add_item(items.Item(itemtype='gadget', id='9', mpn='M', comment='c'), valid_from=T0)
    # address stays as given (no UUID of the host), cleared field ends
    assert items.item_address('gadget', '9') in r._copy_metadata()
    assert r.add_item(items.Item(itemtype='gadget', id='9', mpn='M'), valid_from=T1)
    assert r.get_item('gadget/9', at_time=T2).comment is None
    assert r.get_item('gadget/9', at_time='2026-11-05T00:00:00Z').comment == 'c'
    assert [i.ref for i in r.list_items(itemtype='gadget', at_time=T2)] == ['gadget/9']
    assert len(r.get_item_history('gadget/9')) == 3


def test_resolve_param():
    storage = {}
    tree(storage)
    value, item = items.resolve_param(storage, "ntc0 @ i:'adc_brd' and di:'0xA1B2'", 'board', 'R1')
    assert value == 10002.7 and item.ref == 'breakout_test/BO-003'
    assert items.resolve_param(storage, "ntc0 @ i:'adc_brd' and di:'0xA1B2'", 'board', 'mpn')[0] is None
    assert items.resolve_param(storage, "ntc0 @ di:'0xFFFF'", 'board', 'R1') == (None, None)
    assert items.param_value({'value': 3, 'unit': 'Ohm'}) == 3.0 and items.param_value(True) is None


def test_setup_profile_translates_terminals():
    storage = {}
    tree(storage)
    # the NTC names the terminal of the breakout instead of the channel
    ntc = items.get_item(storage, 'ntc_sensor/0042')
    items.add_item(storage, ntc.model_copy(update={'slot': 'J2.3-4'}), valid_from=T0)
    items.add_item(storage, items.SetupItem(id='hf_ntc_v01', board_type='breakout_test',
                                            channels={'ntc0': {'slot': 'J2.3-4', 'cal': 'ntc'}}), valid_from=T0)
    addr = "ntc0 @ i:'adc_brd' and di:'0xA1B2'"
    found = items.get_items(storage, addr)
    assert 'sensor' not in found and 'setup' not in found        # the device names no profile yet
    # the device reports its profile (metadata of the gateway, address with the UUID of the host)
    from redvypr import metadata as md
    md.add_metadata_to_entries(md.create_metadata_dict("@di:'0xA1B2' and u:'host-uuid'",
                                                       {'setup': {'adc_brd': 'hf_ntc_v01'}}, valid_from=T1), storage)
    found = items.get_items(storage, "ntc0 @ i:'adc_brd' and di:'0xA1B2' and u:'host-uuid'", at_time=T2)
    assert found['sensor'].ref == 'ntc_sensor/0042' and found['setup'].ref == 'setup/hf_ntc_v01'
    assert found['board'].ref == 'breakout_test/BO-003'
    # a query without the UUID (e.g. built by a device widget) finds it too
    assert items.get_items(storage, addr, at_time=T2)['sensor'].ref == 'ntc_sensor/0042'
    # before the device named the profile: no translation
    assert 'sensor' not in items.get_items(storage, "ntc0 @ i:'adc_brd' and di:'0xA1B2' and u:'host-uuid'",
                                           at_time='2026-11-05T00:00:00Z')
    # a profile of another sensor (packetid) does not apply
    assert 'sensor' not in items.get_items(storage, "ntc0 @ i:'adc_hfm' and di:'0xA1B2' and u:'host-uuid'",
                                           at_time=T2)
    setup = items.get_item(storage, 'setup/hf_ntc_v01')
    assert setup.channel_of_slot('J2.3-4') == 'ntc0' and setup.slot_of_channel('ntc1') is None
    assert items.setup_name({'setup': 'x'}) == 'x' and items.setup_name({'setup': {'a': 'y'}}, 'a') == 'y'
