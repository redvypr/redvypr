"""
Links to a norlog (SerialLink: shell at the port, ThreadLink: CoAP through the gateway) and their
use by the gateway thread.
"""
import json
import queue
import zlib

import pytest

from redvypr.devices.norlog import device_list
from redvypr.devices.norlog import links
from redvypr.devices.norlog import norlog_gateway as ng
from redvypr.devices.norlog import ot_cli
from redvypr.devices.norlog import ports


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


class Cfg:
    comport = ""
    ports = []
    baud = 115200
    coap_timeout_s = 5
    extinfo_interval_s = 60.0
    live_apply = False
    live_sink = True
    publish_raw_data = False
    ports_show_all = True
    console_show_commands = False
    prefer_leader = False


def make_gateway(port_answers, status):
    """Gateway thread with one open (fake) port COM5 that is the gateway of network 'net'."""
    gw = ng._Gateway({"device": None, "thread_uuid": "t"}, None, queue.Queue(), queue.Queue())
    gw.config = Cfg()
    port = ports.Port("COM5", 115200, on_line=gw.on_port_line)
    port.ser = object()             # "open"
    port.cli = FakeCli(port_answers)
    port.status = status
    gw.ports["COM5"] = port
    gw.gateways = {"net": "COM5"}
    return gw, port


STATUS = {"state": "leader", "extpanid": "net", "rloc16": "0x1000",
          "ipaddr": ["fd11:2233:4455:6677:0:ff:fe00:1000"],
          "children": [{"Extended MAC": "aabbccddeeff0011", "RLOC16": "0x1001"}]}


def test_gateway_reads_info_over_links(monkeypatch):
    gw, port = make_gateway({"norlog info json": json.dumps({"hwid": "GW", "firmware": "0.4.50",
                                                             "device": "nRF52840"})}, dict(STATUS))
    asked = []

    def coap_get(cli, addr, uri, timeout=10.0):
        asked.append((addr, uri))
        if uri == "info":
            return json.dumps({"hwid": "M1", "uptime_s": 5,
                               "thread": {"role": "child", "mleid": "fd11:2233:4455:6677:1:2:3:4"}}).encode()
        return json.dumps({"hwid": "M1", "firmware": "0.4.50", "sn": "007"}).encode()
    monkeypatch.setattr(ot_cli, "coap_get", coap_get)
    monkeypatch.setattr(ot_cli, "props_read", lambda cli, address=None: {})

    # before the info: temporary keys
    assert [d["key"] for d in gw.build_devices()] == ["port:COM5", "rloc:0x1001@COM5"]

    gw.query_info("all", report=False)
    # the info gives the hardware ID: the key of the device from now on
    assert port.hwid == "GW" and gw.infos["GW"]["hwid"] == "GW"
    assert gw.infos["M1"]["sn"] == "007" and gw.infos["M1"]["uptime_s"] == 5
    assert gw.member_hwid == {("COM5", "0x1001"): "M1"}
    assert "port:COM5" not in gw.infos and "rloc:0x1001@COM5" not in gw.infos
    assert asked == [("fd11:2233:4455:6677:0:ff:fe00:1001", "info"),
                     ("fd11:2233:4455:6677:0:ff:fe00:1001", "extinfo")]
    devices = gw.build_devices()
    assert [(d["key"], d["parent"]) for d in devices] == [("GW", ""), ("M1", "GW")]
    assert devices[0]["role"] == device_list.ROLE_GATEWAY and devices[1]["sn"] == "007"
    assert gw.link("gateway").is_local and gw.link("GW").is_local and gw.link("COM5").is_local
    # member: over its Mesh-Local EID (stays the same when the RLOC16 changes)
    member = gw.link("M1")
    assert member.address == "fd11:2233:4455:6677:1:2:3:4" and member.gateway.port == "COM5"
    assert gw.link("rloc:0x1001@COM5").address == "fd11:2233:4455:6677:0:ff:fe00:1001"
    with pytest.raises(ValueError):
        gw.link("UNKNOWN")


def test_duplicate_packets_published_once():
    gw, _port = make_gateway({}, dict(STATUS))
    pkt = {"mac": "M1", "boot": 3, "packet_num": 17}
    assert not gw.is_duplicate(dict(pkt))
    assert gw.is_duplicate(dict(pkt))
    assert not gw.is_duplicate({**pkt, "packet_num": 18})
    assert not gw.is_duplicate({**pkt, "boot": 4})
    assert gw.duplicates == 1


def test_choose_gateways():
    def port(name, state, role="auto", net="net", opened=1):
        return {"name": name, "role": role, "opened": opened, "status": {"state": state, "extpanid": net}}
    choose = device_list.choose_gateways
    # leader before router before child, then the port opened first
    assert choose([port("A", "child"), port("B", "leader", opened=2)]) == {"net": "B"}
    assert choose([port("A", "router", opened=2), port("B", "router", opened=1)]) == {"net": "B"}
    # role gateway first; role node and ports without network never
    assert choose([port("A", "child", role="gateway"), port("B", "leader")]) == {"net": "A"}
    assert choose([port("A", "leader", role="node"), port("B", "detached")]) == {}
    # tie: the previous gateway stays (no flapping)
    assert choose([port("A", "router", opened=1), port("B", "router", opened=2)], {"net": "B"}) == {"net": "B"}
    # two networks: one gateway each
    assert choose([port("A", "leader"), port("B", "leader", net="other")]) == {"net": "A", "other": "B"}


def test_ports_match_by_usb_serial_number_then_name():
    PC = ng.PortConfig
    found = [{"name": "COM3", "description": "USB", "usb_sn": "X1", "vid": 0x1915, "pid": 1},
             {"name": "COM9", "description": "nRF", "usb_sn": "Y2", "vid": 0x1915, "pid": 1},
             {"name": "COM1", "description": "Communications Port", "usb_sn": "", "vid": None, "pid": None},
             {"name": "COM4", "description": "other", "usb_sn": "", "vid": 0x0403, "pid": 1}]
    configs = [PC(port="COM5", usb_sn="Y2", role="gateway"),     # renamed COM5 -> COM9
               PC(port="COM1"),                                   # by name (no USB serial number)
               PC(port="COM7", usb_sn="Z3")]                      # not plugged in
    rows, by_name = ports.match(configs, found)
    assert [r["name"] for r in rows] == ["COM9", "COM1", "COM7", "COM3", "COM4"]
    assert by_name["COM9"].role == "gateway" and rows[2]["found"] is None
    assert rows[3]["config"] is None        # COM3: found, not configured (norlog-like first)
    # a configured name with another USB serial number at it: another device, no match
    rows, _by_name = ports.match([PC(port="COM3", usb_sn="OTHER")], found)
    assert rows[0]["found"] is None


def test_configured_ports_takes_over_comport():
    cfg = ng.DeviceCustomConfig(comport="COM5")
    assert [(p.port, p.role) for p in ng.configured_ports(cfg)] == [("COM5", "gateway")]
    cfg = ng.DeviceCustomConfig(comport="COM5", ports=[{"port": "COM7"}])
    assert [p.port for p in ng.configured_ports(cfg)] == ["COM7"]


def test_build_devices_ports_tree_and_merge():
    status_gw = {"state": "leader", "extpanid": "net", "rloc16": "0x1000", "extaddr": "1111",
                 "children": [{"Extended MAC": "2222", "RLOC16": "0x1001"},
                              {"Extended MAC": "3333", "RLOC16": "0x1002"}]}
    status_node = {"state": "child", "extpanid": "net", "rloc16": "0x1001", "extaddr": "2222"}
    rows = [{"name": "COM5", "state": device_list.PORT_OPEN, "key": "GW", "active": True, "status": status_gw,
             "member_keys": {"0x1002": "M2"}},
            {"name": "COM7", "state": device_list.PORT_OPEN, "key": "N1", "active": False, "status": status_node},
            {"name": "COM9", "state": device_list.PORT_CLOSED},
            {"name": "COM11", "state": device_list.PORT_GONE, "key": "OLD"}]
    devices = device_list.build_devices(rows, infos={"M2": {"hwid": "M2", "sn": "002"}})
    assert [(d["key"], d["parent"], d["role"]) for d in devices] == [
        ("GW", "", device_list.ROLE_GATEWAY), ("M2", "GW", device_list.ROLE_MEMBER),
        ("N1", "", device_list.ROLE_NODE), ("port:COM9", "", device_list.ROLE_NODE),
        ("OLD", "", device_list.ROLE_NODE)]
    # N1 is at COM7 and a child of the gateway: one entry at its port, with the Thread link values
    assert devices[2]["thread_link"]["via"] == "COM5" and devices[2]["thread_link"]["rloc16"] == "0x1001"
    assert devices[1]["sn"] == "002" and devices[3]["port_state"] == device_list.PORT_CLOSED
    assert devices[4]["hwid"] == "OLD" and devices[4]["port_state"] == device_list.PORT_GONE


def test_update_ports_opens_and_closes(monkeypatch):
    found = [{"name": "COM5", "description": "nRF", "usb_sn": "S5", "vid": 0x1915, "pid": 1},
             {"name": "COM7", "description": "nRF", "usb_sn": "S7", "vid": 0x1915, "pid": 1}]
    monkeypatch.setattr(ports, "scan", lambda: list(found))
    opened = []

    def fake_open(self):
        if self.name == "COM7":
            raise OSError("access denied")
        self.ser = object()
        self.cli = FakeCli({"norlog info json": json.dumps({"hwid": "GW", "firmware": "0.4.50"})})
        opened.append(self.name)
    monkeypatch.setattr(ports.Port, "open", fake_open)
    monkeypatch.setattr(ot_cli, "read_status", lambda cli: {"state": "leader", "extpanid": "net"})
    monkeypatch.setattr(ot_cli, "props_read", lambda cli, address=None: {"sn": "005"})
    monkeypatch.setattr(ot_cli, "sink_set", lambda cli, text: {"sink": {"on": True}})
    monkeypatch.setattr(ot_cli, "pub_set", lambda cli, text, address=None, timeout=10.0: {"pub": text})
    gw = ng._Gateway({"device": None, "thread_uuid": "t"}, None, queue.Queue(), queue.Queue())
    gw.config = ng.DeviceCustomConfig(ports=[{"port": "COM5", "usb_sn": "S5"}, {"port": "COM7"}])
    assert gw.update_ports(force_scan=True)
    assert opened == ["COM5"] and list(gw.ports) == ["COM5"]
    assert gw.ports["COM5"].hwid == "GW" and gw.props_cache["GW"] == {"sn": "005"}
    gw.read_status()
    assert gw.gateways == {"net": "COM5"} and gw.ports["COM5"].sink is True
    devices = gw.build_devices()
    assert [(d["key"], d["port_state"]) for d in devices] == [("GW", device_list.PORT_OPEN),
                                                               ("port:COM7", device_list.PORT_ERROR)]
    assert devices[0]["sn"] == "005" and "access denied" in devices[1]["port_error"]
    # unplugged: closed
    found.pop(0)
    assert gw.update_ports(force_scan=True)
    assert gw.ports == {}
    # disconnected in the configuration: not opened again
    found.insert(0, {"name": "COM5", "description": "nRF", "usb_sn": "S5", "vid": 0x1915, "pid": 1})
    gw.config.ports[0].connect = False
    gw.update_ports(force_scan=True)
    assert gw.ports == {}
