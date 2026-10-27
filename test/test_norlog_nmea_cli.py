"""
NMEA sensor at UART1 over the gateway shell and CoAP, redvypr.devices.norlog.ot_cli.nmea_*
(with a simulated norlog shell, firmware 0.4.21).
"""
import base64
import json

import pytest

from redvypr.devices.norlog import ot_cli

STATE = {"on": False, "baud": 4800, "auto": True, "raw": False, "ok": 0, "err": 0, "lines": 0, "age_ms": -1,
         "last": ""}


def apply(state, text):
    """Like serial_nmea_set_text() of the firmware; returns an error text or None."""
    for kv in text.split(","):
        k, v = kv.split("=", 1)
        if k in ("on", "raw"):
            state[k] = v == "1"
        elif k == "baud":
            state["auto"] = v == "auto"
            if v != "auto":
                state["baud"] = int(v)
        else:
            return f"unbekannt: {k} (on, baud, raw)"
    return None


class FakeCli:
    def __init__(self, old=False):
        self.state = dict(STATE)
        self.sent = []
        self.old = old          # firmware < 0.4.21: no 'set', CoAP wind GET only

    def shell_query(self, cmd, prefix, timeout=4.0):
        self.sent.append(cmd)
        if cmd == "norlog nmea json":
            return json.dumps(self.state)
        if cmd.startswith("norlog nmea set "):
            if self.old:
                raise TimeoutError
            err = apply(self.state, cmd.split(" ", 3)[3])
            return f"err {err}" if err else "ok"
        if cmd.startswith("norlog coap"):
            parts = cmd.split(" ")
            method, addr, uri = parts[2], parts[3], parts[4]
            assert uri == "wind"
            if method == "get":
                return f"ok {addr} 2.05 txt {json.dumps(self.state)}"
            if self.old:
                return f"err {addr} 4.05"
            text = base64.b64decode(parts[5][4:]).decode()
            err = apply(self.state, text)
            if err:
                return f"err {addr} 4.00 txt {json.dumps({'ok': False, 'err': err})}"
            return f"ok {addr} 2.04 txt {{\"ok\":true}}"
        raise AssertionError(cmd)


def test_settings_text():
    assert ot_cli.nmea_settings_text(True, "auto", False) == "on=1,baud=auto,raw=0"
    assert ot_cli.nmea_settings_text(baud=38400) == "baud=38400"
    assert ot_cli.nmea_settings_text(on=False, baud=0) == "on=0,baud=auto"
    with pytest.raises(ValueError):
        ot_cli.nmea_settings_text(baud=300)
    with pytest.raises(ValueError):
        ot_cli.nmea_settings_text()


def test_gateway_shell():
    cli = FakeCli()
    assert ot_cli.nmea_get(cli)["on"] is False
    ot_cli.nmea_set(cli, on=True, baud=9600, raw=True)
    assert cli.sent[-1] == "norlog nmea set on=1,baud=9600,raw=1"
    st = ot_cli.nmea_get(cli)
    assert st["on"] and st["raw"] and st["baud"] == 9600 and not st["auto"]


def test_member_over_coap():
    cli = FakeCli()
    addr = "fd00::ff:fe00:1000"
    ot_cli.nmea_set(cli, on=True, baud="auto", address=addr)
    st = ot_cli.nmea_get(cli, address=addr)
    assert st["on"] and st["auto"] and not st["raw"]


def test_old_firmware():
    cli = FakeCli(old=True)
    with pytest.raises(ot_cli.OtError, match="0.4.21"):
        ot_cli.nmea_set(cli, on=True)
    with pytest.raises(ot_cli.OtError, match="0.4.21"):
        ot_cli.nmea_set(cli, on=True, address="fd00::1")
