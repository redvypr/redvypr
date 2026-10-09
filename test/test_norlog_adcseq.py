"""
ADC sequence packets of the norlog (firmware >= 0.4.15), redvypr.devices.norlog.norlog_cbor.
"""
import struct

from redvypr.devices.norlog import norlog_cbor


def _uint(major, v):
    if v < 24:
        return bytes([(major << 5) | v])
    if v < 0x100:
        return bytes([(major << 5) | 24, v])
    if v < 0x10000:
        return bytes([(major << 5) | 25]) + struct.pack(">H", v)
    if v < 0x100000000:
        return bytes([(major << 5) | 26]) + struct.pack(">I", v)
    return bytes([(major << 5) | 27]) + struct.pack(">Q", v)


def _int(v):
    return _uint(0, v) if v >= 0 else _uint(1, -1 - v)


def _tstr(s):
    b = s.encode()
    return _uint(3, len(b)) + b


def _f32(v):
    return b"\xfa" + struct.pack(">f", v)


def _list(items):
    # zcbor without ZCBOR_CANONICAL: indefinite length
    return b"\x9f" + b"".join(items) + b"\xff"


def _packet(tag, fields):
    body = b"".join(_int(k) + v for k, v in fields)
    return b"\xd9" + struct.pack(">H", tag) + b"\xbf" + body + b"\xff"


def _adcseq(names, raw, values, units, sensor="adc_brd", extra=()):
    return _packet(50009, [
        (0, _int(17)), (1, _int(123456)), (4, _int(0x1122334455667788)),
        (9, _tstr(sensor)), (90, _int(3)),
        (91, _list([_tstr(n) for n in names])),
        (92, _list([_int(r) for r in raw])),
        (93, _list([_f32(v) for v in values])),
        (94, _list([_tstr(u) for u in units])),
        *extra,
    ])


def test_adcseq_flattened_by_step_name():
    pkt = norlog_cbor.decode_bytes(_adcseq(["ain0", "pt100", "temp"], [3355443, -12, 1000],
                                           [1.0, -0.25, 25.5], ["V", "1", "degC"]))
    assert pkt["packet_type"] == "adc_brd"
    assert pkt["sensor"] == "adc_brd"
    assert pkt["cfg_id"] == 3
    assert pkt["ain0"] == 1.0 and pkt["ain0_raw"] == 3355443
    assert pkt["pt100"] == -0.25 and pkt["pt100_raw"] == -12
    assert pkt["temp"] == 25.5
    assert not any(k.startswith("seq_") for k in pkt)
    units = norlog_cbor.units_of(pkt)
    assert units["ain0"] == "V" and units["pt100"] == "1" and units["temp"] == "degC"
    assert units["uptime_ms"] == "ms"


def test_adcseq_reserved_names_and_masks():
    pkt = norlog_cbor.decode_bytes(_adcseq(["boot", "x"], [1, 2], [0.5, float("nan")], ["V", "V"],
                                           sensor="adc_hfm", extra=[(95, _int(2)), (96, _int(1))]))
    assert pkt["packet_type"] == "adc_hfm"
    assert pkt["ch_boot"] == 0.5 and "boot" not in pkt
    assert pkt["x"] != pkt["x"]     # NaN: step failed
    assert pkt["seq_err"] == 2 and pkt["seq_ovr"] == 1


def test_adcseq_cfg_packet():
    text = "on=1,sps=20,filter=sinc3,interval=5000;ain0,0,COM,off;temp,TEMP,-"
    pkt = norlog_cbor.decode_bytes(_packet(50010, [(0, _int(1)), (4, _int(1)), (9, _tstr("adc_brd")),
                                                   (90, _int(3)), (97, _tstr(text))]))
    assert pkt["packet_type"] == "adc_brd_cfg"
    assert pkt["cfg"] == text and pkt["cfg_id"] == 3


def test_other_packets_unchanged():
    pkt = norlog_cbor.decode_bytes(_packet(50008, [(0, _int(1)), (80, b"\xfb" + struct.pack(">d", 90.0))]))
    assert pkt["packet_type"] == "wind" and pkt["wind_dir"] == 90.0
    assert norlog_cbor.units_of(pkt)["wind_dir"] == "deg"
