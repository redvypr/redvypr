"""Tab Datafiles of the norlog gateway: overview, conversion per device, selected packets (norlog_datafiles)."""
import os

from redvypr.devices.norlog import norlog_datafiles as D
from redvypr.devices.norlog.cbor_mini import CBORTag, dumps

HWID = "00AABBCCDDEEFF01"
MAC = int(HWID, 16)
T0 = 1_790_000_000_000        # offset_ms: uptime + offset = time [ms]


def battery(num, up, boot=1, offset=True):
    d = {0: num, 1: up, 4: MAC, 7: num, 8: boot, 10: 4000 + num, 11: 90, 12: False}
    if offset:
        d[100] = T0
    return dumps(CBORTag(50001, d))


def board_temp(num, up, boot=1):
    return dumps(CBORTag(50006, {0: 100 + num, 1: up, 4: MAC, 7: num, 8: boot, 60: 20.5, 61: 21.0, 100: T0}))


def make_archive(tmp_path):
    dev = tmp_path / HWID
    dev.mkdir()
    # battery 1, 2, 4: one lost; the last one without offset gets its time from its boot
    (dev / "data_00001_a.cbor").write_bytes(battery(1, 1000) + board_temp(1, 1500) + battery(2, 2000))
    (dev / "data_00002_b.cbor").write_bytes(battery(4, 4000, offset=False) + board_temp(2, 4500))
    return dev


def test_summary_rows_and_cache(tmp_path):
    dev = make_archive(tmp_path)
    assert D.device_dirs(tmp_path) == [dev]
    info = D.summarize(dev)
    assert set(info["files"]) == {"data_00001_a.cbor", "data_00002_b.cbor"}
    rows = {(r["type"], r["key"]): r for r in D.summary_rows(info)}
    r = rows[("battery", "batt_mv")]
    assert r["count"] == 3 and r["lost"] == 1 and r["numeric"] and r["unit"] == "mV" and r["boots"] == 1
    assert rows[("battery", "batt_charging")]["numeric"] is False
    assert rows[("board_temp", "board_temp_c")]["t_min"] == (T0 + 1500) / 1000
    # only the selected file
    rows1 = {(r["type"], r["key"]): r for r in D.summary_rows(info, ["data_00001_a.cbor"])}
    assert rows1[("battery", "batt_mv")]["count"] == 2 and rows1[("battery", "batt_mv")]["lost"] == 0
    # unchanged files are not read again, a grown file is
    os.utime(dev / "data_00001_a.cbor")
    with open(dev / "data_00002_b.cbor", "ab") as f:
        f.write(battery(5, 5000))
    info = D.summarize(dev)
    rows = {(r["type"], r["key"]): r for r in D.summary_rows(info)}
    assert rows[("battery", "batt_mv")]["count"] == 4
    assert D.file_info(info, "data_00002_b.cbor")[0] == 3


def test_convert_device_incremental_and_datasource(tmp_path):
    from redvypr.datasource import DataSourceConfig, open_datasource
    dev = make_archive(tmp_path)
    res = D.convert_device(dev, sn="007")
    assert res["files"] == 2 and res["packets_new"] == 5 and res["without_time"] == 0
    assert D.convert_device(dev, sn="007")["files"] == 0          # nothing new
    with open(dev / "data_00002_b.cbor", "ab") as f:
        f.write(battery(5, 5000))
    res = D.convert_device(dev, sn="007")
    assert res["files"] == 1 and res["packets_new"] == 1
    src = open_datasource(DataSourceConfig(name="t", filepath=str(D.db_path(dev))))
    try:
        d = src.get_data(f"batt_mv @ di:'{HWID}' and i:'battery'")
        assert list(d["data"]) == [4001, 4002, 4004, 4005]
        # the packet without offset got the time of its boot
        assert d["t"][2] == (T0 + 4000) / 1000
    finally:
        src.close()


def test_iter_packets_selected_types_and_files(tmp_path):
    dev = make_archive(tmp_path)
    pkts = list(D.iter_packets(dev, types={"battery"}))
    assert [p["batt_mv"] for p in pkts] == [4001, 4002, 4004]
    assert all(p["t"] is not None for p in pkts)
    pkts = list(D.iter_packets(dev, names=["data_00002_b.cbor"]))
    assert [p["packet_type"] for p in pkts] == ["battery", "board_temp"]
