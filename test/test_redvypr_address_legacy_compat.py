"""
Compares the RedvyprAddress implementation with the previous (AST based) one in
redvypr_address_legacy: address strings, filters, datakey values, matches,
attributes and dicts must be the same. Intended differences are tested separately:

- address strings with lists, existence checks and regular expressions are written
  in the address syntax (re-parseable), parentheses of 'or' inside 'and' are kept,
  redundant parentheses around comparisons are not written
- an error in one condition of a filter (e.g. comparing a list with a number) only
  affects that condition, not the whole filter
"""
import random

import pytest

from redvypr.redvypr_address import RedvyprAddress as New
from redvypr.redvypr_address_legacy import RedvyprAddress as Old
from redvypr.redvypr_datadict import create_redvypr_dict

from test_redvypr_address import pkt1, pkt2, pkt3, pkt4, pkt5, pkt_empty

ADDRESSES = [
    "temp @ d:dev1 and h:host1", "@d:'norlog' and di:'HW1' and i:'info'", "x", "@", "", "!", "! @ i:test",
    "data[0]", "data[::-1] @ i:test", "data[-1] @ i:test", "data3 @ i:test", "u['test@i:test'] @ i:test",
    "'test@i:test' @ i:test", "'test@i:test' @ i:'test@i:test'", "payload['x'] @ i:42", "payload['y'] @ i:42",
    "_redvypr['packetid'] @ i:1", "v['a'][2][3][0]", "['f'][1] @ i:x", "@i:42", "@i:'42'", "@ i:4.5",
    "@u:176473386979093-142", "@a:192.168.178.137", "@ul:176473386979093-142", "@al:192.168.178.137",
    "z[::-1] @ ul:176473386979093-142", "x @ a:192.168.178.137", "x @ (u:176473386979093-142 and p:somedevice)",
    "x @ h:someredvypr", "x @ hl:someredvypr", "@ data2 == 10", "@d:cam and data2 != 3", "@ 1 < x < 5",
    "@d:a or d:b", "data[0] @ td==dt(2000-01-01)", "data[0]@td_utc>=dt('1999-12-05T10:48:04.762994+00:00')",
    "payload['x'] > 1.5 @ i:x", "@di:HW1 and si:SN1", "board_temp_c @ di:'9AB6' and i:board_temp",
]


def _packets():
    rnd = random.Random(3)
    pkts = [pkt1, pkt2, pkt3, pkt4, pkt5, pkt_empty]
    for i in range(20):
        d = create_redvypr_dict(device=rnd.choice(["cam", "gps", "norlog_002"]), packetid=rnd.choice(["test", 42, "info"]),
                                deviceid=rnd.choice([None, "HW1"]), sensorid=rnd.choice([None, "SN1"]), tu=1.0,
                                hostinfo={"host": "someredvypr", "uuid": "176473386979093-142", "addr": "192.168.178.137",
                                          "tstart": 0})
        d.update({"x": i, "data": [i, 2, 3], "data2": rnd.choice([5, 10]), "board_temp_c": 20.0 + i})
        pkts.append(d)
    return pkts


PACKETS = _packets()
FORMATS = [None, "k,i", "d,i", "k,d,i", "i,p,d,h,u,a,di,s,si", "k,i,h,d,p,di,si,s", "u,a,h,d,i", "k"]


def _safe(f):
    try:
        return ("ok", f())
    except Exception as e:
        return ("exc", type(e).__name__)


@pytest.mark.parametrize("addr", ADDRESSES)
def test_same_as_legacy(addr):
    old, new = Old(addr), New(addr)
    for fmt in FORMATS:
        assert new.to_address_string(fmt) == old.to_address_string(fmt), fmt
    for attr in ("datakey", "device", "packetid", "publisher", "uuid", "host", "addr", "deviceid", "sensorid"):
        assert getattr(new, attr) == getattr(old, attr), attr
    for include in (True, False):
        assert new.to_redvypr_dict(include) == old.to_redvypr_dict(include)
    assert _safe(new.get_datakeyentries) == _safe(old.get_datakeyentries)
    for i, pkt in enumerate(PACKETS):
        assert _safe(lambda: new.matches_packetfilter(pkt)) == _safe(lambda: old.matches_packetfilter(pkt)), i
        assert _safe(lambda: new(pkt, strict=False)) == _safe(lambda: old(pkt, strict=False)), i
        assert _safe(lambda: new(pkt)) == _safe(lambda: old(pkt)), i
        assert _safe(lambda: new.matches(pkt)) == _safe(lambda: old.matches(pkt)), i


def test_address_from_packet_same_as_legacy():
    for pkt in PACKETS:
        for fmt in FORMATS:
            assert New(pkt).to_address_string(fmt) == Old(pkt).to_address_string(fmt)


def test_matches_between_addresses_same_as_legacy():
    objs = [(Old(a), New(a)) for a in ADDRESSES]
    for o1, n1 in objs:
        for o2, n2 in objs:
            assert _safe(lambda: n1.matches(n2)) == _safe(lambda: o1.matches(o2)), (o1, o2)


@pytest.mark.parametrize("addr, expected", [
    ("x@i:[a,b,3]", "x @ i:['a', 'b', 3]"),
    ("data @ d?:", "data @ d?:"),
    ("@(lon?:) or (lat?:)", "@lon?: or lat?:"),
    ("@not d?:", "@not d?:"),
    (r"temp @ i:~/^ch\d+$/i", r"temp @ i:~/^ch\d+$/i"),
    ("@d:a and (d:b or d:c)", "@d:'a' and (d:'b' or d:'c')"),
    ("@(d:a or d:b) and i:x", "@(d:'a' or d:'b') and i:'x'"),
    # the legacy version added redundant parentheses: "... and (manufacturer_sn == 'SN1')"
    ("@i:calibration and calibration_type=='abc' and manufacturer_sn=='SN1'",
     "@i:'calibration' and calibration_type == 'abc' and manufacturer_sn == 'SN1'"),
])
def test_intended_string_changes(addr, expected):
    a = New(addr)
    assert a.to_address_string() == expected
    # re-parseable to the same address
    assert New(a.to_address_string()).to_address_string() == expected


def test_error_in_one_condition_only():
    # data is a list: "data >= 2" fails, the packetid condition still counts
    a = New("@ data >= 2 and i:test")
    assert a.matches_packetfilter({"_redvypr": {"packetid": "test"}, "data": [1, 2]})
    assert not a.matches_packetfilter({"_redvypr": {"packetid": "other"}, "data": [1, 2]})
    # content filter of the packet
    b = New("@ data > 2")
    assert b.matches_packetfilter({"_redvypr": {}, "data": 3}) and not b.matches_packetfilter({"_redvypr": {}, "data": 2})
