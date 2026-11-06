"""
'norlog coap local' answers (firmware >= 0.4.48): binary payload as base64 with CRC-32.
"""
import base64
import zlib

import pytest

from redvypr.devices.norlog import ot_cli


def b64_line(data, crc=None):
    crc = zlib.crc32(data) if crc is None else crc
    return f"ok local 2.05 b64 {base64.b64encode(data).decode()} {crc:08x}"


def test_b64_payload():
    data = bytes(range(256)) * 2
    ok, code, payload, truncated = ot_cli.parse_coap_line(b64_line(data))
    assert ok and code == "2.05" and payload == data and not truncated


def test_b64_truncated_flag():
    line = b64_line(b"\x00\x01").replace(" b64 ", " b64+ ")
    assert ot_cli.parse_coap_line(line)[3] is True


def test_b64_wrong_crc_is_garbled():
    data = b"\x00\x01\x02"
    with pytest.raises(ValueError):
        ot_cli.parse_coap_line(b64_line(data, crc=zlib.crc32(data) ^ 1))


def test_b64_without_crc_is_garbled():
    with pytest.raises(ValueError):
        ot_cli.parse_coap_line("ok local 2.05 b64 AAEC")


def test_txt_and_hex_unchanged():
    assert ot_cli.parse_coap_line('ok local 2.05 txt {"a": 1}')[2] == b'{"a": 1}'
    assert ot_cli.parse_coap_line("ok fd00::1 2.05 hex 0001ff")[2] == b"\x00\x01\xff"


def test_local_errors():
    ok, code, payload, _ = ot_cli.parse_coap_line("err local no_thread")
    assert not ok and code == "no_thread" and payload == b""
