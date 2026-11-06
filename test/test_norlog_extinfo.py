"""
Compact CoAP 'info' plus 'extinfo' (firmware >= 0.4.50): merged into one info dict,
the extinfo is read again only after extinfo_interval_s.
"""
import json
import queue
import time

from redvypr.devices.norlog import device_list
from redvypr.devices.norlog import norlog_gateway as ng

BASE = {"hwid": "AA", "uptime_s": 42, "time": "2026-11-06T17:51:19.196Z",
        "battery": {"mv": 4213, "soc": 85, "charging": False},
        "gnss": {"fix": 1, "used": 12},
        "thread": {"role": "child", "rloc16": "0x8003", "mleid": "fd00::1"}}
EXT = {"device": "nRF52840", "firmware": "0.4.50", "hwid": "AA", "sn": "003",
       "battery": {"current_ma": 0, "model": "akyga", "gauge": True, "mv": 1},
       "board_temp_c": 26.3,
       "gnss": {"view": 47, "lat": 54.0, "lon": 12.2},
       "thread": {"commissioned": True, "network": "NorlogMesh", "channel": 18}}


def test_compact_detection():
    assert device_list.is_compact_info(BASE)
    assert not device_list.is_compact_info({**BASE, "firmware": "0.4.49"})
    assert not device_list.is_compact_info({})


def test_merge_one_level_base_wins():
    m = device_list.merge_info(EXT, BASE)
    assert m["firmware"] == "0.4.50" and m["sn"] == "003" and m["board_temp_c"] == 26.3
    assert m["battery"] == {"current_ma": 0, "model": "akyga", "gauge": True, "mv": 4213, "soc": 85,
                            "charging": False}
    assert m["gnss"]["fix"] == 1 and m["gnss"]["lat"] == 54.0
    assert m["thread"]["role"] == "child" and m["thread"]["network"] == "NorlogMesh"
    assert device_list.merge_info(None, BASE) == BASE


class Cfg:
    extinfo_interval_s = 60.0
    coap_timeout_s = 5


def make_gateway(monkeypatch, answers):
    gw = ng._Gateway({"device": None, "thread_uuid": "t"}, None, queue.Queue(), queue.Queue())
    gw.config = Cfg()
    gw.cli = None
    gw.requests = []

    def coap_get(cli, addr, uri, timeout=10.0):
        gw.requests.append(uri)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return json.dumps(answer).encode()
    monkeypatch.setattr(ng.ot_cli, "coap_get", coap_get)
    return gw


def test_extinfo_read_once_then_cached(monkeypatch):
    gw = make_gateway(monkeypatch, [EXT])
    info, fresh = gw.with_extinfo("fd00::1", BASE)
    assert fresh and info["sn"] == "003" and gw.requests == ["extinfo"]
    info, fresh = gw.with_extinfo("fd00::1", BASE)
    assert not fresh and info["sn"] == "003" and gw.requests == ["extinfo"]


def test_extinfo_again_after_interval_or_force(monkeypatch):
    gw = make_gateway(monkeypatch, [EXT, {**EXT, "sn": "004"}, {**EXT, "sn": "005"}])
    gw.with_extinfo("fd00::1", BASE)
    ext, t = gw.ext_infos["AA"]
    gw.ext_infos["AA"] = (ext, time.time() - 61)
    assert gw.with_extinfo("fd00::1", BASE)[0]["sn"] == "004"
    assert gw.with_extinfo("fd00::1", BASE, force=True)[0]["sn"] == "005"


def test_extinfo_error_keeps_cache(monkeypatch):
    gw = make_gateway(monkeypatch, [EXT, TimeoutError("no answer")])
    gw.with_extinfo("fd00::1", BASE)
    info, fresh = gw.with_extinfo("fd00::1", BASE, force=True)
    assert not fresh and info["sn"] == "003"


def test_extinfo_of_another_device_is_ignored(monkeypatch):
    gw = make_gateway(monkeypatch, [{**EXT, "hwid": "BB"}])
    info, fresh = gw.with_extinfo("fd00::1", BASE)
    assert not fresh and info == BASE
