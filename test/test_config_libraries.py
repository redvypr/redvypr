"""The configuration stores the location of item libraries, not their contents."""

import yaml

import redvypr
from redvypr import items
from redvypr import metadata_sources as ms
from redvypr.redvypr import RedvyprConfig

T0 = '2026-11-01T00:00:00+00:00'


def make_library(tmp_path):
    lib = str(tmp_path / 'lib')
    s = {}
    for i in range(3):
        items.add_item(s, items.Item(itemtype='gadget', id=f'G{i}', name=f'name {i}'), valid_from=T0)
    ms.save_metadata_library(lib, s)
    return lib


def config_of(path):
    return RedvyprConfig(**yaml.safe_load(open(path, encoding='utf-8')))


def test_save_config_keeps_the_location_not_the_contents(tmp_path):
    lib = make_library(tmp_path)
    r = redvypr.Redvypr(hostname='cfglib1')
    r.set_metadata_from_dict({"temp @ d:'ctd_01'": {'unit': 'degC'}})
    r.load_metadata_library(lib)
    r.add_item(items.Item(itemtype='gadget', id='G9', name='not saved in the library yet'), valid_from=T0)
    r.add_item(items.Item(itemtype='gadget', id='G1', name='changed, not saved'),
               valid_from='2026-11-07T00:00:00+00:00')
    cfg = str(tmp_path / 'cfg.yaml')
    r.save_config(fname=cfg)
    data = yaml.safe_load(open(cfg, encoding='utf-8'))
    assert data['metadata_libraries'] == [lib]
    md = data['metadata']
    assert "temp @ d:'ctd_01'" in md                                    # generic metadata stays
    # G0, G2 and the unchanged fields of G1 are only in the library; what is not in it stays
    assert items.item_address('gadget', 'G0') not in md and items.item_address('gadget', 'G2') not in md
    assert [e['key'] for e in md[items.item_address('gadget', 'G9')]] == ['name', 'type_revision']
    assert {e['value'] for e in md[items.item_address('gadget', 'G1')] if e['key'] == 'name'} == \
        {'changed, not saved'}
    # applying it: the library is loaded from its files, the unsaved changes come from the config
    r2 = redvypr.Redvypr(hostname='cfglib2', config=config_of(cfg))
    assert r2.metadata_libraries == [lib]
    got = {i.ref: i.name for i in r2.list_items()}
    assert got == {'gadget/G0': 'name 0', 'gadget/G1': 'changed, not saved', 'gadget/G2': 'name 2',
                   'gadget/G9': 'not saved in the library yet'}
    assert r2.get_metadata(address="temp @ d:'ctd_01'") == {"temp @ d:'ctd_01'": {'unit': 'degC'}}


def test_start_follows_the_library_not_an_old_copy(tmp_path):
    lib = make_library(tmp_path)
    r = redvypr.Redvypr(hostname='cfglib3')
    r.load_metadata_library(lib)
    cfg = str(tmp_path / 'cfg.yaml')
    r.save_config(fname=cfg)
    # the library changes afterwards (e.g. a git pull): G1 renamed, G2 deleted, G3 new
    s = ms.read_library_storage(lib)
    items.add_item(s, items.Item(itemtype='gadget', id='G1', name='renamed'), valid_from='2026-11-05T00:00:00+00:00')
    del s[items.item_address('gadget', 'G2')]
    items.add_item(s, items.Item(itemtype='gadget', id='G3', name='new'), valid_from=T0)
    ms.save_metadata_library(lib, s)
    r2 = redvypr.Redvypr(hostname='cfglib4', config=config_of(cfg))
    assert {i.ref: i.name for i in r2.list_items()} == {'gadget/G0': 'name 0', 'gadget/G1': 'renamed',
                                                         'gadget/G3': 'new'}


def test_old_configuration_with_copies_does_not_bring_back_deleted_entries(tmp_path):
    lib = make_library(tmp_path)
    r = redvypr.Redvypr(hostname='cfglib5')
    r.load_metadata_library(lib)
    old = str(tmp_path / 'old_cfg.yaml')
    # an older configuration: the whole metadata of the instance, with the library entries
    yaml.safe_dump({'hostname': 'cfglib5', 'metadata_libraries': [lib], 'metadata': r._copy_metadata()},
                   open(old, 'w', encoding='utf-8'))
    s = ms.read_library_storage(lib)
    del s[items.item_address('gadget', 'G2')]
    ms.save_metadata_library(lib, s)
    r2 = redvypr.Redvypr(hostname='cfglib6', config=config_of(old))
    assert sorted(i.ref for i in r2.list_items()) == ['gadget/G0', 'gadget/G1']


def test_strip_library_entries():
    s = {}
    items.add_item(s, items.Item(itemtype='gadget', id='A', name='a'), valid_from=T0)
    items.add_item(s, items.Item(itemtype='gadget', id='B', name='b'), valid_from=T0)
    tagged = ms.tag_storage({k: v for k, v in s.items() if "di:'A'" in k}, 'library:one', force=True)
    tagged.update(ms.tag_storage({k: v for k, v in s.items() if "di:'B'" in k}, 'library:other', force=True))
    out = ms.strip_library_entries(tagged, ['D:/x/one'])
    assert list(out) == [items.item_address('gadget', 'B')]                 # only 'one' is loaded
    assert ms.strip_library_entries(tagged, ['/p/one', '/q/other']) == {}
    assert ms.strip_library_entries(s, ['/p/one']) == s                       # no source: kept


def test_config_key_is_metadata_libraries_and_the_old_name_is_read(tmp_path):
    lib = make_library(tmp_path)
    r = redvypr.Redvypr(hostname='cfglib7')
    r.load_metadata_library(lib)
    cfg = str(tmp_path / 'cfg.yaml')
    r.save_config(fname=cfg)
    data = yaml.safe_load(open(cfg, encoding='utf-8'))
    assert data['metadata_libraries'] == [lib] and 'item_libraries' not in data
    # a configuration of an older version names them item_libraries
    data['item_libraries'] = data.pop('metadata_libraries')
    old = str(tmp_path / 'old.yaml')
    yaml.safe_dump(data, open(old, 'w', encoding='utf-8'))
    r2 = redvypr.Redvypr(hostname='cfglib8', config=config_of(old))
    assert r2.metadata_libraries == [lib] and len(r2.list_items()) == 3
    assert r2.get_config().metadata_libraries == [lib]
