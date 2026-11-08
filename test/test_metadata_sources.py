"""
Metadata from several sources (redvypr.metadata_sources, design note design_items.rst).
"""
import sqlite3

import pytest

from redvypr import items
from redvypr import metadata as md
from redvypr import metadata_sources as ms

T0 = '2026-11-01T00:00:00+00:00'
T1 = '2026-11-10T00:00:00+00:00'
T2 = '2026-12-01T00:00:00+00:00'
BO = items.item_address('breakout_v01', 'BO-003')


def storage_with(address, values, valid_from=T0, valid_until=None):
    s = {}
    md.add_metadata_to_entries(md.create_metadata_dict(address, values, valid_from=valid_from,
                                                       valid_until=valid_until), s)
    return s


def value_at(storage, address, key, t):
    return md.get_metadata({'metadata': storage}, address=address, mode='merge', at_time=t).get(key)


def test_source_is_not_context():
    s = {}
    e = md.create_metadata_dict(BO, {'mpn': 'X'}, valid_from=T0)
    e[BO][0]['constraints']['source'] = 'db:nov'
    md.add_metadata_to_entries(e, s)
    assert len(s[BO]) == 1 and s[BO][0]['constraints']['source'] == 'db:nov'
    e = md.create_metadata_dict(BO, {'mpn': 'X'}, valid_from=T1)
    e[BO][0]['constraints']['source'] = 'library:a.yaml'
    md.add_metadata_to_entries(e, s)
    assert len(s[BO]) == 1 and s[BO][0]['constraints']['source'] == ['db:nov', 'library:a.yaml']


def test_equal_entries_join_sources():
    lib = ms.tag_storage(storage_with(BO, {'mpn': 'X'}), 'library:items.yaml')
    db = ms.tag_storage(storage_with(BO, {'mpn': 'X'}, valid_from=T1), 'db:nov', force=True)
    merged, conflicts = ms.merge_storages([('lib', lib), ('db', db)])
    assert conflicts == [] and len(merged[BO]) == 1
    assert merged[BO][0]['constraints']['source'] == ['library:items.yaml', 'db:nov']
    assert merged[BO][0]['constraints']['valid_from'] == T0


def test_library_correction_reaches_old_data():
    # The database of November knows R1 = 10000 (nominal). In December R1 is measured
    # and entered in the library valid from the production of the board.
    db = ms.tag_storage(storage_with(BO, {'R1': 10000.0}), 'db:nov', force=True)
    lib = ms.tag_storage(storage_with(BO, {'R1': 10002.7}), 'library:items.yaml')
    merged, conflicts = ms.merge_storages([('nov', db), ('lib', lib)])
    assert value_at(merged, BO, 'R1', T1) == 10002.7
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c['winner'] == ('library:items.yaml', 10002.7) and c['loser'][1] == 10000.0
    assert c['valid_from'] == T0 and c['valid_until'] is None


def test_partial_overlap_and_other_addresses():
    # library value only from T1 on: before T1 the database value stays
    db = ms.tag_storage(storage_with(BO, {'R1': 1.0}), 'db:nov', force=True)
    lib = ms.tag_storage(storage_with(BO, {'R1': 2.0}, valid_from=T1), 'library:x')
    merged, conflicts = ms.merge_storages([('nov', db), ('lib', lib)])
    assert value_at(merged, BO, 'R1', '2026-11-05T00:00:00Z') == 1.0
    assert value_at(merged, BO, 'R1', T2) == 2.0
    assert [(c['valid_from'], c['valid_until']) for c in conflicts] == [(T1, None)]
    # data address: the instance (device reported) wins over the database
    addr = "temp @ d:'ctd_01'"
    db = ms.tag_storage(storage_with(addr, {'unit': 'degC'}), 'db:nov', force=True)
    inst = storage_with(addr, {'unit': 'K'})
    merged, conflicts = ms.merge_storages([('nov', db), ('instance', inst)])
    assert value_at(merged, addr, 'unit', T1) == 'K' and len(conflicts) == 1


def test_same_kind_later_value_wins_without_conflict():
    old = ms.tag_storage(storage_with(BO, {'R1': 1.0}), 'db:a', force=True)
    new = {}
    md.add_metadata_to_entries(md.create_metadata_dict(BO, {'R1': 1.0}, valid_from=T0), new)
    md.add_metadata_to_entries(md.create_metadata_dict(BO, {'R1': 2.0}, valid_from=T1), new)
    new = ms.tag_storage(new, 'db:b', force=True)
    merged, conflicts = ms.merge_storages([('a', old), ('b', new)])
    assert conflicts == []
    assert value_at(merged, BO, 'R1', '2026-11-05T00:00:00Z') == 1.0 and value_at(merged, BO, 'R1', T2) == 2.0


def test_library_file_roundtrip(tmp_path):
    s = {}
    items.add_item(s, items.Item(itemtype='breakout_v01', id='BO-003', mpn='X', comment='c'), valid_from=T0)
    items.add_item(s, items.Item(itemtype='breakout_v01', id='BO-003', mpn='X'), valid_from=T1)
    s.update(storage_with("temp @ d:'ctd_01'", {'unit': 'degC'}))     # not an item: not in the file
    path = str(tmp_path / 'items.yaml')
    assert ms.save_item_library(path, s) == 1
    text = open(path, encoding='utf-8').read()
    assert 'hostinfo' not in text and 'ctd_01' not in text
    lib = ms.load_item_library(path)
    assert list(lib) == [BO]
    assert all(e['constraints']['source'] == 'library:items.yaml' for e in lib[BO])
    assert items.get_item(lib, 'breakout_v01/BO-003', at_time=T2).comment is None
    assert items.get_item(lib, 'breakout_v01/BO-003', at_time='2026-11-05T00:00:00Z').comment == 'c'


def test_dbreader_uses_further_sources(tmp_path):
    from redvypr.datasource import DataSourceConfig, SqliteReader
    from redvypr.serialize import serialize_json
    path = str(tmp_path / 'nov.sqlite')
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE redvypr_metadata (redvypr_address TEXT, uuid TEXT, metadata TEXT)')
    db_storage = storage_with(BO, {'R1': 10000.0})
    con.execute('INSERT INTO redvypr_metadata VALUES (?, ?, ?)', (BO, 'u', serialize_json(db_storage[BO])))
    con.commit()
    con.close()
    reader = SqliteReader(DataSourceConfig(name='nov', filepath=path))
    assert reader.get_metadata(BO, at_time=T1)['R1'] == 10000.0
    lib = ms.tag_storage(storage_with(BO, {'R1': 10002.7}), 'library:items.yaml')
    reader.metadata_sources = lambda: [('lib', lib)]
    reader.refresh()
    assert reader.get_metadata(BO, at_time=T1)['R1'] == 10002.7
    assert len(reader.metadata_conflicts()) == 1
    reader.close()


def test_redvypr_item_library(tmp_path):
    import redvypr
    path = str(tmp_path / 'lib.yaml')
    s = {}
    items.add_item(s, items.Item(itemtype='gadget', id='1', mpn='M'), valid_from=T0)
    ms.save_item_library(path, s)
    r = redvypr.Redvypr(hostname='libtest')
    assert r.load_item_library(path) == 1
    assert r.load_item_library(path) == 1           # again: nothing new
    assert len(r.get_item_history('gadget/1')) == 2   # mpn, type_revision
    r.add_item(items.Item(itemtype='gadget', id='1', mpn='M', batch='B'), valid_from=T1)
    assert r.save_item_library() == 1
    lib = ms.load_item_library(path)
    assert items.get_item(lib, 'gadget/1', at_time=T2).batch == 'B'
    assert r.get_config().item_libraries == [path]
    with pytest.raises(ValueError):
        redvypr.Redvypr(hostname='libtest2').save_item_library()
