"""
Links to a norlog (SerialLink: shell at the port, ThreadLink: CoAP through the gateway) and their
use by the gateway thread.
"""
import json
import queue
import zlib

import pytest

from redvypr.devices.norlog import links
from redvypr.devices.norlog import norlog_gateway as ng
from redvypr.devices.norlog import ot_cli


class FakeCli:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.queries = []

    def shell_query(self, cmd, prefix, timeout=10.0):
        self.queries.append(cmd)
        return self.answers[cmd]


def test_serial_and_thread_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(ot_cli, "fs_local", lambda cli, *a, **k: calls.append(("local", a)) or {})
    monkeypatch.setattr(ot_cli, "fs_remote", lambda cli, addr, op, path, **k: calls.append(("remote", addr, op, path)) or {})
    monkeypatch.setattr(ot_cli, "sd_op_local", lambda cli, op, name, progress=None: {"where": "local", "op": op})
    monkeypatch.setattr(ot_cli, "sd_op_remote", lambda cli, addr, op, name, progress=None: {"where": addr, "op": op})
    gw = links.SerialLink(FakeCli(), "COM5")
    member = links.ThreadLink(gw, "fd00::1")
    assert gw.is_local and gw.kind == links.KIND_SERIAL and gw.port == "COM5"
    assert not member.is_local and member.kind == links.KIND_THREAD and member.port == "COM5"
    assert member.cli is gw.cli and member.gateway is gw
    gw.fs_op("mkdir", "/fw")
    member.fs_op("rm", "/a.txt")
    assert calls == [("local", ("mkdir", "/fw")), ("remote", "fd00::1", "rm", "/a.txt")]
    assert gw.sd_op("delete") == {"where": "local", "op": "delete"}
    assert member.sd_op("format") == {"where": "fd00::1", "op": "format"}
    with pytest.raises(ValueError):
        links.ThreadLink(gw, "")


def test_serial_info_and_thread_info(monkeypatch):
    cli = FakeCli({"norlog info json": json.dumps({"hwid": "GW", "firmware": "0.4.50"})})
    gw = links.SerialLink(cli, "COM5")
    assert gw.info() == {"hwid": "GW", "firmware": "0.4.50"}
    monkeypatch.setattr(ot_cli, "coap_get", lambda cli, addr, uri, timeout=10.0:
                        json.dumps({"uri": uri, "addr": addr}).encode())
    member = links.ThreadLink(gw, "fd00::2")
    assert member.info() == {"uri": "info", "addr": "fd00::2"}
    assert member.extinfo() == {"uri": "extinfo", "addr": "fd00::2"}


@pytest.mark.parametrize("cached", [False, True])
def test_push_through_gateway_sd(monkeypatch, cached):
    data = b"x" * 1000
    steps = []
    monkeypatch.setattr(ot_cli, "fs_local", lambda cli, *a, **k: steps.append(("fs", a[0], a[1])) or {})
    monkeypatch.setattr(ot_cli, "fs_crc", lambda cli, addr, path:
                        (zlib.crc32(data), len(data)) if cached else (0, 0))

    def upload(cli, d, path, progress=None, resume=True):
        steps.append(("upload", path))
        progress and progress(len(d), len(d))
        return 0
    monkeypatch.setattr(ot_cli, "fs_upload_local", upload)

    def push(cli, addr, local, remote, progress=None, resume=False):
        steps.append(("push", addr, local, remote, resume))
        progress and progress(len(data), len(data))
        return {"resumed": 0}
    monkeypatch.setattr(ot_cli, "fs_push", push)

    phases = []
    member = links.ThreadLink(links.SerialLink(FakeCli(), "COM5"), "fd00::1")
    member.push(data, "/fw/update.bin", lambda phase, d, t: phases.append(phase), tmp="/fw/push.bin", keep=True)
    expect = [("fs", "mkdir", "/fw")] + ([] if cached else [("upload", "/fw/push.bin")]) + \
             [("push", "fd00::1", "/fw/push.bin", "/fw/update.bin", True)]
    assert steps == expect
    assert phases == (["cached", "thread"] if cached else ["gateway", "thread"])

    steps.clear()
    member.push(data, "/x.bin")         # tmp removed afterwards
    assert steps[-1] == ("fs", "rm", "/fw/xfer.tmp")


def test_gateway_reads_info_over_links(monkeypatch):
    gw = ng._Gateway({"device": None, "thread_uuid": "t"}, None, queue.Queue(), queue.Queue())

    class Cfg:
        comport = "COM5"
        coap_timeout_s = 5
        extinfo_interval_s = 60.0
        live_apply = False
        publish_raw_data = False
    gw.config = Cfg()
    gw.cli = FakeCli({"norlog info json": json.dumps({"hwid": "GW", "firmware": "0.4.50", "device": "nRF52840"})})
    gw.last_status = {"rloc16": "0x1000", "ipaddr": ["fd11:2233:4455:6677:0:ff:fe00:1000"],
                      "children": [{"Extended MAC": "aabbccddeeff0011", "RLOC16": "0x1001"}]}
    asked = []

    def coap_get(cli, addr, uri, timeout=10.0):
        asked.append((addr, uri))
        if uri == "info":
            return json.dumps({"hwid": "M1", "uptime_s": 5}).encode()
        return json.dumps({"hwid": "M1", "firmware": "0.4.50", "sn": "007"}).encode()
    monkeypatch.setattr(ot_cli, "coap_get", coap_get)
    monkeypatch.setattr(ot_cli, "props_read", lambda cli, address=None: {})

    gw.query_info("all", report=False)
    assert gw.infos["gateway"]["hwid"] == "GW"
    assert gw.infos["0x1001"]["sn"] == "007" and gw.infos["0x1001"]["uptime_s"] == 5
    assert asked == [("fd11:2233:4455:6677:0:ff:fe00:1001", "info"),
                     ("fd11:2233:4455:6677:0:ff:fe00:1001", "extinfo")]
    assert gw.link("gateway").is_local
    assert gw.link("0x1001").address == "fd11:2233:4455:6677:0:ff:fe00:1001"
