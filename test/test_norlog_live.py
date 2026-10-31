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


def test_live_window_counts_lost_packets():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from redvypr.devices.norlog.norlog_gateway import LiveDataWindow
    w = LiveDataWindow()
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
