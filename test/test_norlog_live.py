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
    assert ot_cli.types_from_mask(0x7FE) == list(ot_cli.PACKET_TYPES)


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
    from redvypr.devices.norlog.norlog_gateway import LiveDataTab

    class Owner(QtCore.QObject):
        def open_live_subscriptions(self):
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


def test_save_sqlite_channel(tmp_path):
    """Save data: published packets into the redvypr SQLite format, host = redvypr instance, type filter."""
    import sqlite3
    from redvypr.devices.norlog import norlog_save, norlog_cbor
    from redvypr.redvypr_datadict import create_redvypr_dict
    host = {"host": "pc", "tstart": 0, "addr": "127.0.0.1", "uuid": "pc-uuid"}
    path = tmp_path / "live.sqlite"
    saver = norlog_save.DataSaver(host)
    assert saver.configure(True, [{"filepath": str(path), "packet_types": ["board_temp"]}])
    assert not saver.configure(True, [{"filepath": str(path), "packet_types": ["board_temp"]}])
    for i in range(3):
        pkt = norlog_cbor.Packet(packet_type="board_temp", mac="AB", board_temp_c=20.0 + i, t=1.7e9 + i)
        data = create_redvypr_dict(device="norlog_7", deviceid="AB", packetid="board_temp", tu=pkt["t"],
                                   hostinfo=host)
        data.update(pkt)
        saver.write(data, pkt, "7")
        saver.write(data, norlog_cbor.Packet(packet_type="gnss", mac="AB", t=1.7e9 + i), "7")   # not wanted
    status = saver.status()["channels"][0]
    assert status["packets"] == 3 and status["error"] is None
    saver.close()
    con = sqlite3.connect(str(path))
    try:
        uuids = {r[0] for r in con.execute("SELECT uuid FROM redvypr_metadata")}
        n = con.execute("SELECT COUNT(*) FROM norlog").fetchone()[0]
    finally:
        con.close()
    assert uuids == {"pc-uuid"} and n > 0
