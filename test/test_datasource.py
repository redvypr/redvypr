"""
Reading a database of the SQLite writer as data source (redvypr.datasource).
"""
import numpy as np
import pytest

import redvypr.metadata
from redvypr.datasource import DataSourceConfig, DatasourceRegistry, DataSourceError, open_datasource
from redvypr.devices.db.db_config_util import DbWriteConfig, DbTableConfig
from redvypr.devices.db.db_engine_sqlite import DbSqlite, SqliteConfig
from redvypr.redvypr_datadict import create_redvypr_dict

T0 = 1_700_000_000.0
N = 5000


@pytest.fixture(scope="module")
def dbfile(tmp_path_factory):
    path = tmp_path_factory.mktemp("ds") / "data.sqlite"
    tables = {"flat": DbTableConfig(tablename="flat", tabletype="data_flat", addresses=["@"])}
    db = DbSqlite(SqliteConfig(filepath=str(path), storage="file", append_to_file=True, batch_size=1000,
                               dt_newfile=0, dt_newfile_unit="none", max_file_size_mb=None,
                               write_config=DbWriteConfig(tables=tables)))
    host = {"host": "h", "tstart": 0, "addr": None, "uuid": "h-uuid"}
    for i in range(N):
        for dev, hwid, off in (("cam", "0123", 0.0), ("gps", "ABCD", 100.0)):
            d = create_redvypr_dict(device=dev, deviceid=hwid, packetid="p", tu=T0 + i, hostinfo=host)
            d["t"] = T0 + i
            d["temp"] = off + np.sin(i / 100.0)
            d["text"] = f"v{i}"
            db.insert_packet(d)
    meta = redvypr.metadata.create_metadata_dict("temp @ di:'0123'", {"unit": "degC"},
                                                 valid_from=T0 - 10)
    for address, entries in meta.items():
        db.add_metadata(address, "h-uuid", entries)
    db.close()
    return path


def test_datastreams(dbfile):
    src = open_datasource(DataSourceConfig(name="test", filepath=str(dbfile)))
    streams = {s.address.split(" @")[0] + "/" + s.raddress.deviceid: s for s in src.datastreams()}
    s = streams["temp/0123"]
    assert s.numeric and s.num == N and s.t_first == T0 and s.t_last == T0 + N - 1
    assert not streams["text/0123"].numeric


def test_get_data_raw_decimated_range(dbfile):
    src = open_datasource(DataSourceConfig(name="test", filepath=str(dbfile)))
    raw = src.get_data("temp @ di:'0123'")
    assert len(raw["t"]) == N and not raw["decimated"]
    dec = src.get_data("temp @ di:'0123'", max_points=200)
    assert dec["decimated"] and len(dec["t"]) <= 200 and dec["num"] == N
    assert dec["data"].min() == pytest.approx(raw["data"].min())
    assert dec["data"].max() == pytest.approx(raw["data"].max())
    part = src.get_data("temp @ di:'0123'", t_start=T0 + 100, t_end=T0 + 199, max_points=200)
    assert not part["decimated"] and len(part["t"]) == 100 and part["t"][0] == T0 + 100
    both = src.get_data("temp", max_points=None)
    assert len(both["t"]) == 2 * N and np.all(np.diff(both["t"]) >= 0) and len(both["streams"]) == 2


def test_metadata(dbfile):
    src = open_datasource(DataSourceConfig(name="test", filepath=str(dbfile)))
    assert src.get_metadata("temp @ di:'0123'").get("unit") == "degC"
    assert "unit" not in src.get_metadata("temp @ di:'ABCD'")


def test_registry(dbfile):
    changed = []
    reg = DatasourceRegistry(on_change=lambda: changed.append(1))
    reg.add_datasource({"name": "a", "filepath": str(dbfile)})
    reader = reg.get_datasource_reader("a")
    assert reg.get_datasource_reader("a") is reader
    reg.add_datasource({"name": "a", "filepath": str(dbfile), "description": "changed"})
    assert reg.get_datasource_reader("a") is not reader      # config changed: new reader
    reg.remove_datasource("a")
    assert changed == [1, 1, 1] and reg.datasources == []
    with pytest.raises(DataSourceError):
        reg.get_datasource_reader("a")
    with pytest.raises(DataSourceError):
        open_datasource(DataSourceConfig(name="x", filepath=str(dbfile) + ".missing"))
