"""
Live data over Thread ('norlog pub' / 'norlog sink', firmware >= 0.4.32): texts of the
commands, status of a device and the live data window (lost packets).
"""
import os

import pytest

from redvypr.devices.norlog import ot_cli


def test_types_from_mask():
    assert ot_cli.types_from_mask(0) == []
    assert ot_cli.types_from_mask(0x160) == ["ntc", "board_temp", "wind"]
    assert ot_cli.types_from_mask(0xFFE) == list(ot_cli.PACKET_TYPES)
    assert ot_cli.types_from_mask(1 << 11) == ["time"]


def test_pub_text():
    assert ot_cli.pub_text([]) == "off"
    assert ot_cli.pub_text(["ntc", "wind"]) == "ntc,wind"
    assert ot_cli.pub_text(["ntc"], ["sinks", "fd11::1"]) == "ntc sinks fd11::1"
    with pytest.raises(ValueError):
        ot_cli.pub_text(["temperature"])


def test_sink_text():
    assert ot_cli.sink_text(False) == "off"
    assert ot_cli.sink_text(True) == "on"
    assert ot_cli.sink_text(True, list(ot_cli.PACKET_TYPES)) == "on"
    assert ot_cli.sink_text(True, ["gnss", "ntc"]) == "on gnss,ntc"


class FakeCli:
    def __init__(self, lines):
        self.lines = lines
        self.sent = []

    def shell_query(self, cmd, prefix, timeout=4.0):
        self.sent.append(cmd)
        return self.lines.pop(0)


def test_pub_set_gateway_shell():
    status = '{"pub":{"types":"ntc","mask":32,"sinks":true,"to":[],"sent":0,"dropped":0},' \
             '"sink":{"on":false,"types":"-","mask":0,"received":0,"rx_dropped":0,"known":[]}}'
    cli = FakeCli([status, "err unbekannte Typen"])
    assert ot_cli.pub_set(cli, "ntc")["pub"]["mask"] == 32
    assert cli.sent == ["norlog pub ntc"]
    with pytest.raises(ot_cli.OtError):
        ot_cli.pub_set(cli, "xyz")


def test_live_pub_text_from_status():
    from redvypr.devices.norlog.norlog_gateway import _live_pub_text
    assert _live_pub_text({}) == ""
    assert _live_pub_text({"pub": {"mask": 0}}) == "off"
    assert _live_pub_text({"pub": {"mask": 0x120, "sinks": True, "to": ["fd11::7"]}}) == "ntc,wind sinks fd11::7"


def test_live_tab_counts_lost_packets():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from PyQt6 import QtCore
    from redvypr.devices.norlog.norlog_gateway import LiveDataTab, DeviceCustomConfig

    class Owner(QtCore.QObject):
        cfg = DeviceCustomConfig()

        def open_live_subscriptions(self):
            pass

        def send_config(self):
            pass
    w = LiveDataTab(Owner())
    head = {"_redvypr": {"device": "norlog_7"}, "mac": "AB", "boot": 3, "source": "0x7000", "t": 1.7e9}
    for num in (1, 2, 5):                       # 3 and 4 lost
        w.add_packet({**head, "packet_type": "ntc", "packet_num_type": num, "ntc_temp": 21.5})
    # adcseq packets carry the sensor name as type, one counter for all sensors
    w.add_packet({**head, "packet_type": "adc_brd", "sensor": "adc_brd", "packet_num_type": 1})
    w.add_packet({**head, "packet_type": "hfm", "sensor": "hfm", "packet_num_type": 2})
    w.add_packet({**head, "boot": 4, "packet_type": "ntc", "packet_num_type": 1})    # restart: no gap
    assert w.gaps[("AB", "ntc")]["lost"] == 2
    assert w.gaps[("AB", "adcseq")]["lost"] == 0
    assert w.table.rowCount() == 3
    assert "6 packets" in w.summary.text() and "2 lost" in w.summary.text()
    cols = LiveDataTab.COLUMNS
    assert w.table.item(1, cols.index("CBOR type")).text() == "adcseq (50009)"
    # one row per value: redvypr address of the value, numeric values can be plotted
    w.add_packet({"_redvypr": {"device": "norlog_7", "packetid": "battery"}, "mac": "AB", "packet_type": "battery",
                  "packet_num_type": 1, "batt_mv": 4200, "batt_charging": False})
    w.split.setChecked(True)
    row = w.rows[("AB", "battery", "batt_mv")]
    assert w.table.item(row, cols.index("Redvypr address")).text() == "batt_mv @ d:'norlog_7' and i:'battery'"
    w.table.selectRow(row)
    assert [a for a, _n, _u in w.selected_lines()] == ["batt_mv @ d:'norlog_7' and i:'battery'"]
    w.table.selectRow(w.rows[("AB", "battery", "batt_charging")])
    assert w.selected_lines() == []
    w.close()
    assert app is not None


def test_device_list_assigns_live_data_to_gateway_and_members():
    from redvypr.devices.norlog import device_list
    status = {"extaddr": "aaaa", "rloc16": "0x4000", "state": "leader",
              "children": [{"Extended MAC": "bbbb", "RLOC16": "0x4001"}]}
    infos = {"gateway": {"hwid": "GW"}, "0x4001": {"hwid": "N1"}}
    now = 1000.0
    sources = {"0x4000": {"last_seen": now, "packets": 5, "mac": "GW"},       # gateway itself (sink)
               "0x6c00": {"last_seen": now, "packets": 2, "mac": "N1"},       # member, RLOC16 changed
               "0x8000": {"last_seen": now, "packets": 1, "mac": "XX"}}       # unknown: data only
    devices = device_list.build_device_list(status, data_sources=sources, infos=infos, now=now)
    assert devices[0]["role"] == device_list.ROLE_GATEWAY and devices[0]["packets"] == 5
    member = next(d for d in devices if d.get("rloc16") == "0x4001")
    assert member["packets"] == 2
    links = [d.get("link") for d in devices]
    assert links.count("data only") == 1


def test_live_parse_and_text():
    from redvypr.devices.norlog.norlog_gateway import _live_parse, _live_text
    assert _live_parse("off") == (frozenset(), ())
    assert _live_parse("all")[0] == frozenset(ot_cli.PACKET_TYPES)
    assert _live_parse("ntc,wind") == (frozenset({"ntc", "wind"}), ("sinks",))
    assert _live_parse("ntc sinks fd11::7") == (frozenset({"ntc"}), ("sinks", "fd11::7"))
    assert _live_text(frozenset(ot_cli.PACKET_TYPES), ("sinks",)) == "all"
    assert _live_text({"wind", "ntc"}, ("sinks",)) == "ntc,wind"
    assert _live_text({"ntc"}, ("fd11::7",)) == "ntc fd11::7"
    assert _live_text(set(), ()) == "off"
    # what the device reports compares equal to the wish
    status = {"pub": {"mask": 0x120, "sinks": True, "to": []}}
    from redvypr.devices.norlog.norlog_gateway import _live_pub_text
    assert _live_parse(_live_pub_text(status)) == _live_parse("ntc,wind")


def test_packet_time_offset_and_old_rtc_time():
    from redvypr.devices.norlog import norlog_cbor
    from redvypr.devices.norlog.cbor_mini import CBORTag, dumps
    # firmware >= 0.4.35: uptime_ms + offset_ms, ms resolution
    pkt = norlog_cbor.decode_bytes(dumps(CBORTag(50005, {0: 1, 1: 1234, 100: 1_700_000_000_000})))
    assert norlog_cbor.packet_time(pkt) == (1_700_000_001.234, "node")
    # older firmware: rtc_time in seconds
    pkt = norlog_cbor.decode_bytes(dumps(CBORTag(50005, {0: 1, 1: 1234, 2: CBORTag(1, 1_700_000_000)})))
    assert norlog_cbor.packet_time(pkt) == (1_700_000_000.0, "rtc")
    assert norlog_cbor.packet_time({"uptime_ms": 5}) == (None, None)


def test_time_packet_decoded():
    from redvypr.devices.norlog import norlog_cbor
    from redvypr.devices.norlog.cbor_mini import CBORTag, dumps
    pkt = norlog_cbor.decode_bytes(dumps(CBORTag(50011, {
        0: 7, 1: 60000, 4: 0xAB, 8: 2, 100: 1_700_000_000_000, 101: 0, 105: -1500, 106: 1_700_000_000_120,
        107: 300, 108: True})))
    assert pkt["packet_type"] == "time" and pkt["time_event_name"] == "observation"
    assert pkt["rtc_diff_us"] == -1500 and pkt["gps_offset_ms"] - pkt["offset_ms"] == 120
    assert norlog_cbor.units_of(pkt)["rtc_diff_us"] == "us"
    assert pkt["gps_pps"] is True


def test_logindex_header_from_offset():
    from redvypr.devices.norlog import norlog_logindex as L
    assert L._header({"packet_num": 3, "uptime_ms": 2500, "offset_ms": 1_700_000_000_000}) == \
        (3, 2500, 1_700_000_002)
    assert L._header({"packet_num": 3, "uptime_ms": 2500}) == (3, 2500, 0)


def test_live_and_sd_card_packets_stored_once(tmp_path):
    """
    The same packet received live and converted from the SD card: one row in redvypr_raw
    (uid_keys boot + packet_num of the source), even with a different time (live: time of reception).
    """
    import sqlite3
    import time
    from redvypr.devices.db.db_engine_sqlite import DbSqlite
    from redvypr.devices.norlog import norlog_cbor, norlog_convert
    from redvypr.devices.norlog.cbor_mini import CBORTag, dumps
    from redvypr.redvypr_datadict import create_redvypr_dict
    off = (int(time.time()) - 100) * 1000
    raw = [dumps(CBORTag(50005, {0: n, 1: 1000 * n, 100: off, 4: 0x9AB64B5C71AE5C1C, 7: n, 8: 3,
                                 52: 20.0 + n})) for n in (1, 2, 3)]
    (tmp_path / "data_00001_x.cbor").write_bytes(b"".join(raw))
    db_path = tmp_path / "both.sqlite"
    db = DbSqlite(norlog_convert.db_config(db_path))
    host = {"host": "redvypr", "tstart": 0, "addr": "127.0.0.1", "uuid": "pc"}
    for b in raw[:2]:                           # live, like the gateway ('#NLD')
        pkt = norlog_cbor.decode_bytes(b)
        t = time.time()                         # e.g. old gateway: time of reception
        data = create_redvypr_dict(device="norlog_7", deviceid=pkt["mac"], sensorid="7",
                                   packetid=pkt["packet_type"], tu=t, hostinfo=host)
        data.update(pkt)
        data.update({"source": "0x7000", "t": t, "t_source": "received"})
        db.insert_packet(data)
    db.close()
    res = norlog_convert.convert([tmp_path / "data_00001_x.cbor"], db_path, sn="7")
    assert res["packets_new"] == 1 and res["packets_duplicate"] == 2
    con = sqlite3.connect(str(db_path))
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = con.execute("SELECT COUNT(*) FROM redvypr_raw").fetchone()[0]
    finally:
        con.close()
    assert rows == 3 and "norlog" not in tables          # no flat table without flat=True
    res = norlog_convert.convert([tmp_path / "data_00001_x.cbor"], db_path, sn="7", flat=True)
    assert res["packets_new"] == 0 and res["entries"] > 0
