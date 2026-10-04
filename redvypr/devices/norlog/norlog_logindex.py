"""
Index and catalog of the norlog SD card log files.

The firmware (src/log_index.h) writes next to every data file
/log/data_*.cbor an index data_*.idx with entry points (offset, RTC time,
uptime, packet number) every 4 KB or 60 s, and one record per data file into
/log/catalog.dat. With them a time span can be loaded without the whole file:

    idx = parse_index(index_bytes)
    start, end = byte_range(idx['records'], t0, t1, file_size)
    # read bytes start..end of the data file (e.g. with the file service)
    packets = decode_range(data_bytes, start=0)        # data_bytes = the range

The CBOR packets are self-delimiting, so decoding starts at any entry point.
build_index() creates the index of a data file without one (older firmware,
lost index); verify_index() checks an index against its data file.

Command line:

    python -m redvypr.devices.norlog.norlog_logindex catalog catalog.dat
    python -m redvypr.devices.norlog.norlog_logindex index data_00012_....idx
    python -m redvypr.devices.norlog.norlog_logindex verify data_00012_....cbor [data_00012_....idx]
    python -m redvypr.devices.norlog.norlog_logindex range data.cbor data.idx 2026-10-04T12:00 2026-10-04T12:10
"""

import bisect
import datetime
import struct

from . import norlog_cbor
from .cbor_mini import CBORDecodeError, _Decoder

INDEX_MAGIC = b"NLIX"
CATALOG_MAGIC = b"NLCT"

# struct log_index_header / log_index_record / log_catalog_header / log_catalog_record
INDEX_HEADER = struct.Struct("<4sHHQIIII")       # 32 bytes
INDEX_RECORD = struct.Struct("<IIII")            # 16 bytes
CATALOG_HEADER = struct.Struct("<4sHHQ")         # 16 bytes
CATALOG_RECORD = struct.Struct("<IIIIIIII48s")   # 80 bytes

CATALOG_FLAG_CLOSED = 0x01

INTERVAL_BYTES = 4096
INTERVAL_S = 60

# First bytes of a packet: tag 500xx (0xd9 0xc3 0x51..) -> resync after damaged data
_TAG_PREFIXES = tuple(bytes([0xD9]) + struct.pack(">H", t) for t in norlog_cbor.PACKET_TAGS)

# Errors damaged data can cause while decoding (e.g. a tag as map key: TypeError,
# a huge epoch time: OverflowError, deep nesting: RecursionError)
_DECODE_ERRORS = (CBORDecodeError, TypeError, ValueError, KeyError, IndexError, OverflowError,
                  OSError, RecursionError)


class LogIndexError(ValueError):
    pass


def _ts(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat() if t else None


def _to_unix(t):
    """unix time from a number, datetime (naive = UTC) or ISO string."""
    if t is None or isinstance(t, (int, float)):
        return t
    if isinstance(t, str):
        t = datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return t.timestamp()


# ---------------------------------------------------------------------------
# Index and catalog files
# ---------------------------------------------------------------------------

def parse_index(data: bytes):
    """
    Parse a .idx file. Returns {'version', 'hwid', 'boot', 'file_index',
    'interval_bytes', 'interval_s', 'records': [{'offset', 'rtc_time', 'uptime_s',
    'packet_num'}, ...]}. A truncated last record (power loss) is ignored.
    """
    if len(data) < INDEX_HEADER.size:
        raise LogIndexError("index too short")
    magic, version, rec_size, hwid, boot, file_index, ib, isec = INDEX_HEADER.unpack_from(data)
    if magic != INDEX_MAGIC:
        raise LogIndexError(f"no norlog index (magic {magic!r})")
    if rec_size != INDEX_RECORD.size:
        raise LogIndexError(f"unknown record size {rec_size}")
    records = []
    for pos in range(INDEX_HEADER.size, len(data) - rec_size + 1, rec_size):
        offset, rtc, up, pnum = INDEX_RECORD.unpack_from(data, pos)
        records.append({"offset": offset, "rtc_time": rtc, "uptime_s": up, "packet_num": pnum})
    return {"version": version, "hwid": f"{hwid:016X}", "boot": boot, "file_index": file_index,
            "interval_bytes": ib, "interval_s": isec, "records": records}


def parse_catalog(data: bytes):
    """
    Parse /log/catalog.dat. Returns {'version', 'hwid', 'files': [{'file_index',
    'boot', 'first_rtc', 'last_rtc', 'packets', 'size', 'closed', 'name'}, ...]}.
    A file still open (or open at a power loss) has closed=False; its packets and
    size are those of the last index entry point.
    """
    if len(data) < CATALOG_HEADER.size:
        raise LogIndexError("catalog too short")
    magic, version, rec_size, hwid = CATALOG_HEADER.unpack_from(data)
    if magic != CATALOG_MAGIC:
        raise LogIndexError(f"no norlog catalog (magic {magic!r})")
    if rec_size != CATALOG_RECORD.size:
        raise LogIndexError(f"unknown record size {rec_size}")
    files = []
    for pos in range(CATALOG_HEADER.size, len(data) - rec_size + 1, rec_size):
        fi, boot, t0, t1, packets, size, flags, _res, name = CATALOG_RECORD.unpack_from(data, pos)
        files.append({"file_index": fi, "boot": boot, "first_rtc": t0, "last_rtc": t1,
                      "packets": packets, "size": size, "closed": bool(flags & CATALOG_FLAG_CLOSED),
                      "name": name.split(b"\0", 1)[0].decode(errors="replace")})
    return {"version": version, "hwid": f"{hwid:016X}", "files": files}


def files_in_span(catalog, t0=None, t1=None):
    """Files of a catalog (parse_catalog()) with data in [t0, t1] (unix time, datetime or ISO)."""
    t0, t1 = _to_unix(t0), _to_unix(t1)
    result = []
    for f in catalog["files"]:
        if f["first_rtc"] == 0:          # no RTC time: cannot be placed in time
            continue
        if t1 is not None and f["first_rtc"] > t1:
            continue
        if t0 is not None and f["last_rtc"] < t0:
            continue
        result.append(f)
    return result


def byte_range(records, t0=None, t1=None, file_size=None, key="rtc_time", margin=None):
    """
    Byte range [start, end) of a data file containing all packets with
    t0 <= key <= t1, from its index records. key: 'rtc_time', 'uptime_s' or
    'packet_num'. The range starts at the last entry point before t0 (the RTC
    time has a resolution of 1 s: packets of second t0 can lie before an entry
    point of second t0) and ends at the first entry point after t1 (or file_size /
    None = end of file): at most one index interval too much on each side. Entries
    without time (rtc_time 0) are ignored for key 'rtc_time'.

    The packets of different threads reach the file slightly out of order (by
    about a second or a few packet numbers), so the range is widened by margin
    (default 2 for times, 16 for packet_num); decode_range() selects exactly. The
    key must be ascending apart from that (an RTC set while logging breaks this).
    """
    if key == "rtc_time":
        t0, t1 = _to_unix(t0), _to_unix(t1)
        recs = [r for r in records if r["rtc_time"]]
    else:
        recs = list(records)
    if not recs:
        return 0, file_size
    if margin is None:
        margin = 16 if key == "packet_num" else 2
    keys = [r[key] for r in recs]
    start = 0
    if t0 is not None:
        i = bisect.bisect_left(keys, t0 - margin) - 1
        start = recs[i]["offset"] if i >= 0 else 0
    end = file_size
    if t1 is not None:
        j = bisect.bisect_right(keys, t1 + margin)
        if j < len(recs):
            end = recs[j]["offset"]
    return start, end


# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------

def iter_packets(data: bytes, start=0, resync=True):
    """
    Decode the CBOR packets of (a part of) a data file from offset start.
    Yields (offset, packet) with packet as norlog_cbor.decode_packet() (None for
    an unknown item). With resync, damaged data (e.g. a packet cut by a power
    loss) is skipped up to the next packet tag; otherwise CBORDecodeError is raised
    (also for other errors the damaged data causes).
    A truncated packet at the end of data is not returned.
    """
    dec = _Decoder(data)
    dec.pos = start
    n = len(data)
    while dec.pos < n:
        pos = dec.pos
        try:
            pkt = norlog_cbor.decode_packet(dec.item())
        except _DECODE_ERRORS as exc:
            if pos + 1 >= n:
                return
            if not resync:
                if isinstance(exc, CBORDecodeError):
                    raise
                raise CBORDecodeError(f"damaged data at offset {pos}: {exc!r}") from exc
            nxt = min((p for p in (data.find(pre, pos + 1) for pre in _TAG_PREFIXES) if p >= 0),
                      default=-1)
            if nxt < 0:
                return
            dec.pos = nxt
            continue
        yield pos, pkt


def decode_range(data: bytes, start=0, t0=None, t1=None):
    """Packets of data from offset start, optionally only those with t0 <= rtc_time <= t1."""
    t0, t1 = _to_unix(t0), _to_unix(t1)
    packets = []
    for _off, pkt in iter_packets(data, start):
        if pkt is None:
            continue
        t = _header(pkt)[2]
        if (t0 is not None or t1 is not None) and not t:
            continue
        if (t0 is not None and t < t0) or (t1 is not None and t > t1):
            continue
        packets.append(pkt)
    return packets


def _header(pkt):
    """(packet_num, uptime_ms, rtc unix seconds) of a decoded packet."""
    rtc = pkt.get("rtc_time")
    if isinstance(rtc, str):
        rtc = datetime.datetime.fromisoformat(rtc).timestamp()
    return pkt.get("packet_num", 0), pkt.get("uptime_ms", 0), int(rtc) if rtc else 0


def build_index(data: bytes, interval_bytes=INTERVAL_BYTES, interval_s=INTERVAL_S):
    """Index records of a data file, chosen like the firmware does (first packet, then intervals)."""
    records = []
    last = None
    for off, pkt in iter_packets(data):
        if pkt is None:
            continue
        pnum, up_ms, rtc = _header(pkt)
        up_s = up_ms // 1000
        if last is None or off - last[0] >= interval_bytes or up_s - last[1] >= interval_s:
            records.append({"offset": off, "rtc_time": rtc, "uptime_s": up_s,
                            "packet_num": pnum & 0xFFFFFFFF})
            last = (off, up_s)
    return records


def write_index(records, hwid=0, boot=0, file_index=0, interval_bytes=INTERVAL_BYTES,
                interval_s=INTERVAL_S) -> bytes:
    """A .idx file (same format as the firmware) from index records."""
    if isinstance(hwid, str):
        hwid = int(hwid, 16)
    out = bytearray(INDEX_HEADER.pack(INDEX_MAGIC, 1, INDEX_RECORD.size, hwid, boot, file_index,
                                      interval_bytes, interval_s))
    for r in records:
        out += INDEX_RECORD.pack(r["offset"], r["rtc_time"], r["uptime_s"], r["packet_num"])
    return bytes(out)


def verify_index(data: bytes, index: bytes):
    """
    Check an index against its data file. Returns a list of problems (empty = ok).
    The entry points must be exactly those the firmware rule gives (build_index()
    with the intervals of the index header). An index that ends early (file still
    open or power loss) is reported as such.
    """
    idx = parse_index(index)
    actual = idx["records"]
    expected = build_index(data, idx["interval_bytes"], idx["interval_s"])
    problems = []
    for i, (a, e) in enumerate(zip(actual, expected)):
        if a != e:
            problems.append(f"entry {i}: index {a} != expected {e}")
    if len(actual) > len(expected):
        problems.append(f"{len(actual) - len(expected)} entry point(s) beyond the data")
    elif len(actual) < len(expected):
        problems.append(f"index ends early: {len(actual)} of {len(expected)} entry points "
                        f"(file not closed, power loss?)")
    return problems


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _main(argv=None):
    import argparse
    import pathlib

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalog", help="show catalog.dat").add_argument("file")
    sub.add_parser("index", help="show a .idx file").add_argument("file")
    v = sub.add_parser("verify", help="check a .idx file against its data file")
    v.add_argument("data")
    v.add_argument("index", nargs="?")
    b = sub.add_parser("build", help="create the .idx file of a data file")
    b.add_argument("data")
    r = sub.add_parser("range", help="byte range and packets of a time span")
    r.add_argument("data")
    r.add_argument("index")
    r.add_argument("t0")
    r.add_argument("t1")
    a = ap.parse_args(argv)

    def idx_path(p):
        return pathlib.Path(str(p)[:-5] + ".idx") if str(p).endswith(".cbor") else pathlib.Path(p + ".idx")

    if a.cmd == "catalog":
        cat = parse_catalog(pathlib.Path(a.file).read_bytes())
        print(f"hwid {cat['hwid']}, {len(cat['files'])} file(s)")
        for f in cat["files"]:
            print(f"{f['file_index']:5d} boot {f['boot']:4d}  {_ts(f['first_rtc'])} .. {_ts(f['last_rtc'])}"
                  f"  {f['packets']:8d} packets {f['size']:9d} B  {'closed' if f['closed'] else 'open  '}"
                  f"  {f['name']}")
    elif a.cmd == "index":
        idx = parse_index(pathlib.Path(a.file).read_bytes())
        recs = idx.pop("records")
        print(idx, f"{len(recs)} entries")
        for rec in recs:
            print(f"{rec['offset']:9d}  {_ts(rec['rtc_time'])}  uptime {rec['uptime_s']:7d} s"
                  f"  packet {rec['packet_num']}")
    elif a.cmd == "verify":
        data = pathlib.Path(a.data).read_bytes()
        index = pathlib.Path(a.index or idx_path(a.data)).read_bytes()
        problems = verify_index(data, index)
        n = len(parse_index(index)["records"])
        print(f"{len(data)} bytes, {sum(1 for _ in iter_packets(data))} packets, {n} entry points: "
              + ("OK" if not problems else f"{len(problems)} problem(s)"))
        for p in problems:
            print("  " + p)
        return 1 if problems else 0
    elif a.cmd == "build":
        data = pathlib.Path(a.data).read_bytes()
        out = idx_path(a.data)
        if out.exists():
            raise SystemExit(f"{out} exists")
        out.write_bytes(write_index(build_index(data)))
        print(f"{out} written")
    elif a.cmd == "range":
        data = pathlib.Path(a.data).read_bytes()
        idx = parse_index(pathlib.Path(a.index).read_bytes())
        start, end = byte_range(idx["records"], a.t0, a.t1, len(data))
        pk = decode_range(data[start:end], 0, a.t0, a.t1)
        print(f"bytes {start}..{end} ({end - start} of {len(data)}), {len(pk)} packets in the span")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
