"""
Minimal CBOR (RFC 8949) encoder/decoder without external dependencies.

Covers what norlog and the MCUmgr/SMP protocol need: unsigned/negative
integers, byte/text strings, arrays, maps (definite and indefinite length,
as produced by zcbor), tags, false/true/null and float16/32/64.
"""

import math
import struct

__all__ = ["CBORTag", "CBORDecodeError", "dumps", "loads", "loads_all"]


class CBORDecodeError(ValueError):
    pass


class CBORTag:
    """A tagged CBOR item (tag number + value)."""

    __slots__ = ("tag", "value")

    def __init__(self, tag, value):
        self.tag = tag
        self.value = value

    def __eq__(self, other):
        return isinstance(other, CBORTag) and (self.tag, self.value) == (other.tag, other.value)

    def __repr__(self):
        return f"CBORTag({self.tag}, {self.value!r})"


# --------------------------------------------------------------------------
# Encoder
# --------------------------------------------------------------------------

def _head(major, value):
    if value < 24:
        return bytes([(major << 5) | value])
    if value < 0x100:
        return bytes([(major << 5) | 24, value])
    if value < 0x10000:
        return bytes([(major << 5) | 25]) + struct.pack(">H", value)
    if value < 0x100000000:
        return bytes([(major << 5) | 26]) + struct.pack(">I", value)
    return bytes([(major << 5) | 27]) + struct.pack(">Q", value)


def _encode(obj, out):
    if obj is False:
        out += b"\xf4"
    elif obj is True:
        out += b"\xf5"
    elif obj is None:
        out += b"\xf6"
    elif isinstance(obj, int):
        if obj >= 0:
            out += _head(0, obj)
        else:
            out += _head(1, -1 - obj)
    elif isinstance(obj, float):
        out += b"\xfb" + struct.pack(">d", obj)
    elif isinstance(obj, (bytes, bytearray, memoryview)):
        b = bytes(obj)
        out += _head(2, len(b)) + b
    elif isinstance(obj, str):
        b = obj.encode("utf-8")
        out += _head(3, len(b)) + b
    elif isinstance(obj, (list, tuple)):
        out += _head(4, len(obj))
        for item in obj:
            _encode(item, out)
    elif isinstance(obj, dict):
        out += _head(5, len(obj))
        for k, v in obj.items():
            _encode(k, out)
            _encode(v, out)
    elif isinstance(obj, CBORTag):
        out += _head(6, obj.tag)
        _encode(obj.value, out)
    else:
        raise TypeError(f"cannot CBOR-encode {type(obj).__name__}")


def dumps(obj) -> bytes:
    out = bytearray()
    _encode(obj, out)
    return bytes(out)


# --------------------------------------------------------------------------
# Decoder
# --------------------------------------------------------------------------

_BREAK = object()


def _half_to_float(h):
    exp = (h >> 10) & 0x1F
    mant = h & 0x3FF
    if exp == 0:
        val = math.ldexp(mant, -24)
    elif exp == 31:
        val = math.inf if mant == 0 else math.nan
    else:
        val = math.ldexp(mant + 1024, exp - 25)
    return -val if h & 0x8000 else val


class _Decoder:
    def __init__(self, data):
        self.data = memoryview(bytes(data))
        self.pos = 0

    def _take(self, n):
        if self.pos + n > len(self.data):
            raise CBORDecodeError("unexpected end of data")
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def _arg(self, info):
        if info < 24:
            return info
        if info == 24:
            return self._take(1)[0]
        if info == 25:
            return struct.unpack(">H", self._take(2))[0]
        if info == 26:
            return struct.unpack(">I", self._take(4))[0]
        if info == 27:
            return struct.unpack(">Q", self._take(8))[0]
        if info == 31:
            return None     # indefinite length
        raise CBORDecodeError(f"invalid additional info {info}")

    def item(self, allow_break=False):
        ib = self._take(1)[0]
        major, info = ib >> 5, ib & 0x1F

        if ib == 0xFF:
            if allow_break:
                return _BREAK
            raise CBORDecodeError("unexpected break")

        if major == 7:
            if info == 20:
                return False
            if info == 21:
                return True
            if info in (22, 23):
                return None
            if info == 25:
                return _half_to_float(struct.unpack(">H", self._take(2))[0])
            if info == 26:
                return struct.unpack(">f", self._take(4))[0]
            if info == 27:
                return struct.unpack(">d", self._take(8))[0]
            if info < 24:
                return info     # unassigned simple value
            if info == 24:
                return self._take(1)[0]
            raise CBORDecodeError(f"invalid simple value {info}")

        arg = self._arg(info)

        if major == 0:
            return arg
        if major == 1:
            return -1 - arg
        if major in (2, 3):
            if arg is None:     # indefinite: concatenation of chunks
                parts = []
                while True:
                    chunk = self.item(allow_break=True)
                    if chunk is _BREAK:
                        break
                    parts.append(chunk)
                return b"".join(parts) if major == 2 else "".join(parts)
            raw = bytes(self._take(arg))
            return raw if major == 2 else raw.decode("utf-8")
        if major == 4:
            result = []
            if arg is None:
                while True:
                    v = self.item(allow_break=True)
                    if v is _BREAK:
                        break
                    result.append(v)
            else:
                for _ in range(arg):
                    result.append(self.item())
            return result
        if major == 5:
            result = {}
            count = 0
            while arg is None or count < arg:
                k = self.item(allow_break=arg is None)
                if k is _BREAK:
                    break
                if isinstance(k, (list, dict)):
                    k = repr(k)     # unhashable key -> use its text form
                result[k] = self.item()
                count += 1
            return result
        if major == 6:
            return CBORTag(arg, self.item())

        raise CBORDecodeError(f"unknown major type {major}")


def loads(data):
    """Decode exactly one CBOR item (trailing data is ignored)."""
    return _Decoder(data).item()


def loads_all(data):
    """Decode a concatenated stream of CBOR items (e.g. a norlog *.cbor file)."""
    dec = _Decoder(data)
    items = []
    while dec.pos < len(dec.data):
        items.append(dec.item())
    return items
