"""
ADC measurement sequence over the gateway shell and CoAP, redvypr.devices.norlog.ot_cli.adc_*
(with a simulated norlog shell).
"""
import json

import pytest

from redvypr.devices.norlog import ot_cli

STATE = {"sensor": "adc_brd", "present": True, "on": False, "cfg_id": 1, "n": 1, "interval_ms": 10000,
         "dur_ms": 192, "runs": 1, "cfg": "on=0,sps=20,filter=sinc3,interval=10000;temp,TEMP,-"}


class FakeCli:
    """Answers like the firmware 0.4.15 shell; 'norlog coap' requests go to the same state."""

    def __init__(self):
        self.state = dict(STATE)
        self.sent = []
        self.read_pending = False

    def _measure(self):
        self.state["runs"] += 1
        self.state["last"] = {"age_ms": 0, "cfg_id": self.state["cfg_id"], "err": 0, "ovr": 0,
                              "raw": [434559], "val": [26.26]}

    def write_line(self, cmd):
        self.sent.append(cmd)
        if cmd.startswith("norlog adc read"):
            self.read_pending = True

    def shell_query(self, cmd, prefix, timeout=4.0):
        self.sent.append(cmd)
        if self.read_pending:      # the shell runs the queued 'read' first
            self.read_pending = False
            self._measure()
        if cmd.startswith("norlog adc json"):
            return json.dumps(self.state)
        if cmd.startswith("norlog adc set"):
            text = cmd.split(" ", 4)[4]
            if ",9,9" in text:
                return "err a: p und n gleich"
            self.state.update(cfg=text, cfg_id=self.state["cfg_id"] + 1)
            return f"ok {self.state['cfg_id']}"
        if cmd.startswith("norlog coap"):
            parts = cmd.split(" ")
            method, addr, uri = parts[2], parts[3], parts[4]
            if method == "get":
                return f"ok {addr} 2.05 txt {json.dumps(self.state)}"
            if "op=read" in uri:
                self._measure()
                return f"ok {addr} 2.04 txt {{\"ok\":true}}"
            return f"err {addr} 4.00 txt {{\"ok\":false,\"err\":\"a: p und n gleich\"}}"
        raise AssertionError(cmd)


def test_get_and_set_on_the_gateway():
    cli = FakeCli()
    assert ot_cli.adc_get(cli, "adc_brd")["cfg_id"] == 1
    ot_cli.adc_set(cli, "adc_brd", "on=1;u0,0,COM,off")
    assert cli.sent[-1] == "norlog adc set adc_brd on=1;u0,0,COM,off"
    assert ot_cli.adc_get(cli)["cfg_id"] == 2
    with pytest.raises(ot_cli.OtError, match="p und n gleich"):
        ot_cli.adc_set(cli, "adc_brd", "on=1;a,9,9")
    with pytest.raises(ValueError):
        ot_cli.adc_set(cli, "adc_brd", "on=1; a,0,COM")


def test_measure_on_the_gateway():
    cli = FakeCli()
    st = ot_cli.adc_measure(cli, "adc_brd")
    assert st["runs"] == 2 and st["last"]["val"] == [26.26]
    assert "norlog adc read adc_brd" in cli.sent


def test_member_over_coap(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    cli = FakeCli()
    addr = "fd00::ff:fe00:1000"
    assert ot_cli.adc_get(cli, "adc_brd", addr)["runs"] == 1
    st = ot_cli.adc_measure(cli, "adc_brd", addr)
    assert st["runs"] == 2
    assert any("adc?s=adc_brd&op=read" in c for c in cli.sent)
    with pytest.raises(ot_cli.OtError, match="ADC sequence adc_brd: a: p und n gleich"):
        ot_cli.adc_set(cli, "adc_brd", "on=1;a,9,9", addr)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main(["-v", __file__]))
