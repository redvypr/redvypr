"""Directory libraries: one file per item, item type and calibration (redvypr.metadata_sources)."""

import datetime
import math
import os
import time

import redvypr
from redvypr import items
from redvypr import item_types as it
from redvypr import metadata as md
from redvypr import metadata_sources as ms
from redvypr.devices.sensors.calibration import item_calibration as ic
from redvypr.devices.sensors.calibration import sensor_and_calibration_definitions as sd
from redvypr.devices.sensors.calibration.calibration_models import CalibrationNTC

T0 = '2026-11-01T00:00:00+00:00'
T1 = '2026-11-10T00:00:00+00:00'
UTC = datetime.timezone.utc


def ntc(sn, date):
    return CalibrationNTC(sn=sn, sensor_model='ntc_sensor', date=date,
                          coeff=[1 / 3950.0, 1 / 298.15 - math.log(1e4) / 3950.0])


def storage_with_everything():
    s = {}
    items.add_item(s, sd.HfSensor(sn='0614', name='F-002-4_0614'), valid_from=T0)
    items.add_item(s, items.Item(itemtype='ntc_sensor', id='0614-ntc', parent='hf_sensor/0614'),
                   valid_from=T0)
    it.add_definition(s, it.TypeDefinition(name='gadget_x', description='a gadget'), valid_from=T0)
    for cal in (ntc('0614-ntc', datetime.datetime(2021, 9, 14, 20, 21, tzinfo=UTC)),
                ntc('0614-ntc', datetime.datetime(2022, 1, 1, tzinfo=UTC))):
        md.add_metadata_to_entries(md.create_metadata_dict(*next(iter(ic.calibration_metadict(cal).items())),
                                                           valid_from=T0), s)
    return s


def test_one_file_per_address_and_back(tmp_path):
    d = str(tmp_path / 'hf_classic')
    s = storage_with_everything()
    assert ms.save_item_library(d, s) == 5
    rel = sorted(os.path.relpath(f, d).replace(os.sep, '/') for f in ms.directory_library_files(d))
    assert rel[:2] == ['calibrations/ntc_sensor/0614-ntc/20210914T202100_' + rel[0].split('_')[-1],
                       'calibrations/ntc_sensor/0614-ntc/20220101T000000_' + rel[1].split('_')[-1]]
    assert rel[2:] == ['item_types/gadget_x.yaml', 'items/hf_sensor/0614.yaml',
                       'items/ntc_sensor/0614-ntc.yaml']
    assert os.path.exists(os.path.join(d, ms.LIBRARY_MARKER))
    back = ms.read_library_storage(d)
    assert sorted(back) == sorted(ms.library_entries(s))
    lib = ms.load_item_library(d)
    assert all(e['constraints']['source'] == 'library:hf_classic' for es in lib.values() for e in es)
    assert items.get_item(lib, 'hf_sensor/0614', at_time=T1).name == 'F-002-4_0614'
    assert len(ic.calibrations_of_item(lib, items.get_item(lib, 'ntc_sensor/0614-ntc', at_time=T1))) == 2
    # every file alone is a library as well
    one = os.path.join(d, 'items', 'hf_sensor', '0614.yaml')
    assert list(ms.read_library_storage(one)) == [items.item_address('hf_sensor', '0614')]


def test_only_changed_files_are_written_and_gone_ones_removed(tmp_path):
    d = str(tmp_path / 'lib')
    s = storage_with_everything()
    ms.save_item_library(d, s)
    f_hf = os.path.join(d, 'items', 'hf_sensor', '0614.yaml')
    f_ntc = os.path.join(d, 'items', 'ntc_sensor', '0614-ntc.yaml')
    old = {f: os.path.getmtime(f) for f in (f_hf, f_ntc)}
    time.sleep(0.05)
    items.add_item(s, sd.HfSensor(sn='0614', name='renamed'), valid_from=T1)
    ms.save_item_library(d, s)
    assert os.path.getmtime(f_hf) != old[f_hf] and os.path.getmtime(f_ntc) == old[f_ntc]
    # an address gone: its file and empty directories are removed, other files stay
    readme = os.path.join(d, 'README.txt')
    open(readme, 'w').write('not a library file')
    del s[items.item_address('ntc_sensor', '0614-ntc')]
    ms.save_item_library(d, s)
    assert not os.path.exists(f_ntc) and not os.path.isdir(os.path.dirname(f_ntc))
    assert os.path.exists(readme) and os.path.exists(f_hf)


def test_redvypr_with_directory_library(tmp_path):
    repo = tmp_path / 'inventory'
    repo.mkdir()
    d = str(repo / 'hf_classic')
    ms.save_item_library(d, storage_with_everything())
    r = redvypr.Redvypr(hostname='dirlib')
    r.load_item_library(d)
    assert r.get_item('hf_sensor/0614') is not None
    # a new sensor: goes into the directory library (first library of its kind), one new file
    r.add_item(sd.HfSensor(sn='0615'), valid_from=T1)
    saved = r.save_item_libraries()
    assert saved[d] == 6
    assert os.path.exists(os.path.join(d, 'items', 'hf_sensor', '0615.yaml'))
    assert r.get_config().item_libraries == [d]
    # types next to the directory and in its item_types directory are search paths
    paths = ms.type_search_paths(d)
    assert os.path.join(d, 'item_types') in paths
    (repo / 'item_types.yaml').write_text('item_types: {}\n')
    assert str(repo / 'item_types.yaml') in ms.type_search_paths(d)
    # no calibrations.yaml next to a directory library: new calibrations go into the directory
    assert r.library_default_files() == {}
