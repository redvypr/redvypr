"""
Local archive of the norlog SD card log files.

The data files (/log/data_*.cbor), their indexes (.idx) and the catalog
(/log/catalog.dat) are copied 1:1 into <archive>/<hwid>/. A sync only
appends what is new: the files on the card are append-only, so the local
size is the position from which the next sync continues (also after an
interrupted sync). Before appending, the end of the local copy is compared
with the card (CRC); a card that was formatted or swapped meanwhile keeps the
old local file as <name>.replaced-<time> and the file is loaded again.

The original files are the archive: lossless, 14x smaller than redvypr
packets as JSON, with index and catalog. new_packets() decodes what was not
decoded yet (state in <archive>/<hwid>/sync.json) and gives each packet a
time: the RTC or GPS time of the packet, or, for packets written before the
clock was set, uptime + offset of its boot (learned from the packets of the
same boot that have a time). Packets of a boot without any time are kept
until the time of that boot is known.

    remote = RemoteFiles(cli, address)              # address None = gateway
    result = sync(remote, "norlog_archive")
    for pkt in new_packets(result["dir"]):
        ...                                         # e.g. publish into redvypr
"""

import datetime
import json
import logging
import os
import pathlib
import statistics
import zlib

from . import norlog_logindex as L
from . import ot_cli

logger = logging.getLogger('redvypr.device.norlog_archive')

LOG_DIR = "/log"
CATALOG = "catalog.dat"
STATE = "sync.json"
TAIL_CHECK = 4096           # bytes at the end of a local copy compared with the card
CRC_CHECK_MAX = 256 * 1024  # verify a downloaded range in pieces of this size


class ArchiveError(Exception):
    pass


class RemoteFiles:
    """Files of a norlog through the gateway (address None = the gateway itself)."""

    def __init__(self, cli, address=None):
        self.cli, self.address = cli, address

    def list(self, path):
        return ot_cli.fs_list(self.cli, self.address, path)

    def read(self, path, off, length):
        return ot_cli.fs_read_block(self.cli, self.address, path, off, length)

    def crc(self, path, off, length):
        return ot_cli.fs_crc(self.cli, self.address, path, off, length)[0]

    def read_all(self, path):
        return ot_cli.fs_download(self.cli, self.address, path)


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def load_state(dev_dir):
    p = pathlib.Path(dev_dir) / STATE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"files": {}, "boot_offsets": {}}


def save_state(dev_dir, state):
    p = pathlib.Path(dev_dir) / STATE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def _write_atomic(path, data):
    tmp = pathlib.Path(str(path) + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _local_crc(path, off, length):
    with open(path, "rb") as f:
        f.seek(off)
        return zlib.crc32(f.read(length))


def sync(remote, archive_root, hwid=None, progress=None, cancel=None):
    """
    Copy what is new on the card into <archive_root>/<hwid>/.
    hwid: only needed for cards without catalog (firmware < 0.4.3).
    progress(done_bytes, total_bytes, name); cancel() -> True stops after the current block.
    Returns {'hwid', 'dir', 'files': [{'name', 'old', 'new', 'status'}], 'bytes', 'cancelled'}.
    """
    entries = remote.list(LOG_DIR)
    sizes = {e["n"]: e.get("s", 0) for e in entries if not e.get("d")}

    catalog = None
    if CATALOG in sizes:
        catalog_bytes = remote.read_all(f"{LOG_DIR}/{CATALOG}")
        try:
            catalog = L.parse_catalog(catalog_bytes)
            hwid = catalog["hwid"]
        except L.LogIndexError as exc:
            logger.warning(f"catalog not readable: {exc}")
    if not hwid:
        raise ArchiveError("hardware ID unknown (no catalog on the card, read the device info first)")
    dev_dir = pathlib.Path(archive_root) / hwid
    dev_dir.mkdir(parents=True, exist_ok=True)
    if catalog is not None:
        _write_atomic(dev_dir / CATALOG, catalog_bytes)

    names = sorted(n for n in sizes if n.startswith("data_") and (n.endswith(".cbor") or n.endswith(".idx")))
    result = {"hwid": hwid, "dir": str(dev_dir), "files": [], "bytes": 0, "cancelled": False}

    # Plan: local size, checked against the card
    plan = []
    for name in names:
        local = dev_dir / name
        have = local.stat().st_size if local.exists() else 0
        status = "unchanged"
        if have > sizes[name] or (have and not _tail_matches(remote, local, name, have)):
            old = local.with_name(f"{name}.replaced-{datetime.datetime.now():%Y%m%d-%H%M%S}")
            os.replace(local, old)
            logger.warning(f"{name}: local copy does not match the card (formatted/swapped?), kept as {old.name}")
            have, status = 0, "replaced"
        plan.append((name, have, sizes[name], status))
    total = sum(max(0, r - h) for _n, h, r, _s in plan)

    done = 0
    for name, have, rsize, status in plan:
        entry = {"name": name, "old": have, "new": have, "status": status}
        result["files"].append(entry)
        if have >= rsize:
            continue
        if cancel and cancel():
            result["cancelled"] = True
            break
        got = _append_range(remote, dev_dir / name, name, have, rsize,
                            lambda n: progress and progress(done + n, total, name), cancel)
        done += got - have
        entry["new"] = got
        entry["status"] = "new" if have == 0 and status != "replaced" else (
            "replaced" if status == "replaced" else "appended")
        if got < rsize:
            result["cancelled"] = True
            break
    result["bytes"] = done

    state = load_state(dev_dir)
    state["hwid"] = hwid
    state["last_sync"] = _now_iso()
    for f in result["files"]:
        if f["status"] == "replaced":        # decode the new file from its beginning
            state.get("files", {}).pop(f["name"], None)
    save_state(dev_dir, state)
    return result


def _tail_matches(remote, local, name, have):
    n = min(have, TAIL_CHECK)
    try:
        return remote.crc(f"{LOG_DIR}/{name}", have - n, n) == _local_crc(local, have - n, n)
    except ot_cli.OtError:
        return False


def _append_range(remote, local, name, start, end, progress, cancel):
    """Append bytes [start, end) of the card file to local, verified by CRC; returns the new size."""
    path = f"{LOG_DIR}/{name}"
    off = start
    with open(local, "ab") as f:
        while off < end:
            chunk = remote.read(path, off, end - off)
            if not chunk:
                break
            f.write(chunk)
            off += len(chunk)
            progress(off - start)
            if cancel and cancel() and off < end:
                break
    # Verify the new range (in pieces: one CRC request covers at most CRC_CHECK_MAX)
    pos = start
    while pos < off:
        n = min(CRC_CHECK_MAX, off - pos)
        if remote.crc(path, pos, n) != _local_crc(local, pos, n):
            with open(local, "r+b") as f:
                f.truncate(start)
            raise ArchiveError(f"{name}: downloaded range {start}..{off} does not match the card (CRC)")
        pos += n
    return off


# ---------------------------------------------------------------------------
# Decoding the archive
# ---------------------------------------------------------------------------

def _packet_times(pkt):
    """(packet time or None, source) from the RTC or GPS time of a decoded packet."""
    for key, src in (("rtc_time", "rtc"), ("gps_time", "gps")):
        t = pkt.get(key)
        if isinstance(t, str):
            try:
                t = datetime.datetime.fromisoformat(t).timestamp()
            except ValueError:
                t = None
        if t:
            return float(t), src
    return None, None


def new_packets(dev_dir, max_packets=None):
    """
    Decode the packets of the archive that were not decoded yet and give each a
    time ('t', unix s) and 't_source' ('rtc', 'gps' or 'uptime'). Yields the
    packets (dicts as norlog_cbor.decode_packet()) file by file; the state is
    saved after every file, so a consumer may stop at any file boundary.
    Packets of a boot without any time stay in the archive until the time of
    that boot is known (e.g. after "Set clock").
    """
    dev_dir = pathlib.Path(dev_dir)
    state = load_state(dev_dir)
    files_state = state.setdefault("files", {})
    offsets = {int(k): v for k, v in state.setdefault("boot_offsets", {}).items()}
    names = sorted(p.name for p in dev_dir.glob("data_*.cbor"))

    # 1. Decode the new ranges, learn the time offset of every boot
    decoded = []
    for name in names:
        data = (dev_dir / name).read_bytes()
        start = files_state.get(name, {}).get("decoded_until", 0)
        if start >= len(data):
            continue
        spans = list(L.iter_packet_spans(data, start))
        if not spans:
            continue
        samples = {}
        for _pos, _end, pkt in spans:
            if pkt is None:
                continue
            t, _src = _packet_times(pkt)
            if t is not None and pkt.get("uptime_ms") is not None:
                samples.setdefault(pkt.get("boot", 0), []).append(t - pkt["uptime_ms"] / 1000.0)
        for boot, vals in samples.items():
            if boot not in offsets:
                offsets[boot] = statistics.median(vals)
        decoded.append((name, spans))
    state["boot_offsets"] = {str(k): v for k, v in offsets.items()}

    # 2. Give every packet a time; a file with packets of an unknown boot time waits
    count = 0
    for name, spans in decoded:
        out = []
        waiting = False
        for _pos, _end, pkt in spans:
            if pkt is None:
                continue
            t, src = _packet_times(pkt)
            if t is None:
                off = offsets.get(pkt.get("boot", 0))
                if off is None or pkt.get("uptime_ms") is None:
                    waiting = True
                    break
                t, src = off + pkt["uptime_ms"] / 1000.0, "uptime"
            pkt["t"], pkt["t_source"] = t, src
            out.append(pkt)
        if waiting:
            files_state.setdefault(name, {})["waiting_for_time"] = True
            continue
        for pkt in out:
            yield pkt
        count += len(out)
        files_state[name] = {"decoded_until": spans[-1][1]}
        save_state(dev_dir, state)
        if max_packets is not None and count >= max_packets:
            break
    save_state(dev_dir, state)


def waiting_files(dev_dir):
    """Data files whose packets wait for the time of their boot."""
    state = load_state(dev_dir)
    return sorted(n for n, s in state.get("files", {}).items() if s.get("waiting_for_time"))
