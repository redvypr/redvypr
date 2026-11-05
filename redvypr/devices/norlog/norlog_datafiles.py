"""
Data files of the norlog archive (<archive>/<hwid>/data_*.cbor, see norlog_archive) for the
"Datafiles" tab of the gateway: overview, conversion into one SQLite database per device and
reading selected packets.

Per device folder:

    <archive>/<hwid>/
        data_*.cbor, *.idx, catalog.dat, sync.json     copies of the SD card (norlog_archive)
        summary.json                                    overview per file (summarize())
        convert.json                                    what was converted (convert_device())
        <hwid>.sqlite                                   all packets (redvypr_raw) and a data_flat
                                                        table "norlog" for the plots

The files on the card are append-only: a file whose size did not change is not read again.
summary.json and the SQLite database can be deleted, they are made again from the CBOR files.

    info = summarize(dev_dir)               # {'files': {name: {...}}, 'types': {...}}
    rows = summary_rows(info, names=None)   # one row per packet type and value
    res = convert_device(dev_dir, sn='002')
    for pkt in iter_packets(dev_dir, names=None, types={'mag'}):
        ...
"""

import json
import logging
import os
import pathlib
import re
import statistics

from . import norlog_cbor
from . import norlog_convert
from . import norlog_logindex as L
from .norlog_cbor import packet_time

logger = logging.getLogger('redvypr.device.norlog_datafiles')

SUMMARY = "summary.json"
CONVERT_STATE = "convert.json"
SUMMARY_VERSION = 1
HWID_RE = re.compile(r"^[0-9A-Fa-f]{16}$")
FLAT_TABLE = "norlog"

# Header fields of the packets, not values
SKIP = {'packet_type', 'mac', 'packet_num', 'packet_num_type', 'uptime_ms', 'boot', 'source', 't',
        'rtc_time', 'rtc_time_iso', 'gps_time_iso', 'raw_data', 'offset_ms', 't_source'}


def device_dirs(archive_root):
    """Folders of the devices in the archive (named after the hardware ID), sorted."""
    root = pathlib.Path(archive_root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and HWID_RE.match(p.name))


def data_files(dev_dir):
    """data_*.cbor of a device folder: [(name, size)] sorted by name (= chronological)."""
    return [(p.name, p.stat().st_size) for p in sorted(pathlib.Path(dev_dir).glob("data_*.cbor"))]


def db_path(dev_dir):
    dev_dir = pathlib.Path(dev_dir)
    return dev_dir / f"{dev_dir.name}.sqlite"


def datasource_name(hwid):
    """Name of the redvypr data source of the database of a device."""
    return f"norlog_{hwid}"


def _load_json(path, default):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    path = pathlib.Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _scan_file(path):
    """Overview of one data file: per packet type count, time range, values; counters per boot."""
    types = {}
    counters = {}       # "base|boot" -> [min, max, count] of packet_num_type
    packets = without_time = 0
    for _off, pkt in L.iter_packets(pathlib.Path(path).read_bytes()):
        if not pkt:
            continue
        packets += 1
        ptype = pkt.get("packet_type", "?")
        base = norlog_cbor.base_type(pkt)
        e = types.setdefault(ptype, {"base": base, "count": 0, "t_min": None, "t_max": None, "keys": {},
                                     "boots": []})
        e["count"] += 1
        t, _src = packet_time(pkt)
        if t is None:
            without_time += 1
        else:
            e["t_min"] = t if e["t_min"] is None else min(e["t_min"], t)
            e["t_max"] = t if e["t_max"] is None else max(e["t_max"], t)
        boot = pkt.get("boot")
        if boot is not None and boot not in e["boots"]:
            e["boots"].append(boot)
        units = norlog_cbor.units_of(pkt)
        for k, v in pkt.items():
            if k in SKIP or k.startswith("_"):
                continue
            if k not in e["keys"]:
                e["keys"][k] = {"numeric": _is_number(v), "unit": units.get(k, "")}
            elif not _is_number(v):
                e["keys"][k]["numeric"] = False
        num = pkt.get("packet_num_type")
        if isinstance(num, int):
            c = counters.setdefault(f"{base}|{boot}", [num, num, 0])
            c[0], c[1], c[2] = min(c[0], num), max(c[1], num), c[2] + 1
    return {"packets": packets, "without_time": without_time, "types": types, "counters": counters}


def summarize(dev_dir, progress=None, cancel=None):
    """
    Overview of the data files of a device folder, stored in summary.json: only files that are new
    or changed in size are read. progress(done, total, name); cancel() -> True stops (what was read
    so far is kept). Returns {'version', 'files': {name: {'size', 'packets', 'without_time', 'types',
    'counters'}}}.
    """
    dev_dir = pathlib.Path(dev_dir)
    info = _load_json(dev_dir / SUMMARY, {})
    if info.get("version") != SUMMARY_VERSION:
        info = {"version": SUMMARY_VERSION, "files": {}}
    files = data_files(dev_dir)
    names = {n for n, _s in files}
    for name in list(info["files"]):
        if name not in names:
            del info["files"][name]
    todo = [(n, s) for n, s in files if info["files"].get(n, {}).get("size") != s]
    for i, (name, size) in enumerate(todo):
        if cancel and cancel():
            break
        if progress:
            progress(i, len(todo), name)
        try:
            entry = _scan_file(dev_dir / name)
        except OSError as exc:
            logger.warning(f"{dev_dir / name}: {exc}")
            continue
        entry["size"] = size
        info["files"][name] = entry
        _save_json(dev_dir / SUMMARY, info)
    if todo and progress:
        progress(len(todo), len(todo), "")
    if not todo and not (dev_dir / SUMMARY).exists() and files:
        _save_json(dev_dir / SUMMARY, info)
    return info


def summary_rows(info, names=None):
    """
    Rows of the overview (all files or only names): one per packet type and value
    {'type', 'base', 'key', 'numeric', 'unit', 'count', 't_min', 't_max', 'lost', 'boots'};
    lost = gaps in packet_num_type per boot of the base type (over the selected files).
    """
    files = {n: f for n, f in info.get("files", {}).items() if names is None or n in names}
    types = {}
    counters = {}
    for f in files.values():
        for ptype, e in f.get("types", {}).items():
            t = types.setdefault(ptype, {"base": e["base"], "count": 0, "t_min": None, "t_max": None, "keys": {},
                                         "boots": set()})
            t["count"] += e["count"]
            for k, fn in (("t_min", min), ("t_max", max)):
                if e[k] is not None:
                    t[k] = e[k] if t[k] is None else fn(t[k], e[k])
            t["boots"].update(e.get("boots", []))
            for k, kv in e["keys"].items():
                if k not in t["keys"]:
                    t["keys"][k] = dict(kv)
                elif not kv["numeric"]:
                    t["keys"][k]["numeric"] = False
        for key, (lo, hi, n) in f.get("counters", {}).items():
            c = counters.setdefault(key, [lo, hi, 0])
            c[0], c[1], c[2] = min(c[0], lo), max(c[1], hi), c[2] + n
    lost_base = {}
    for key, (lo, hi, n) in counters.items():
        base = key.split("|", 1)[0]
        lost_base[base] = lost_base.get(base, 0) + max(0, hi - lo + 1 - n)
    rows = []
    for ptype in sorted(types):
        t = types[ptype]
        for k in sorted(t["keys"]) or [""]:
            kv = t["keys"].get(k, {})
            rows.append({"type": ptype, "base": t["base"], "key": k, "numeric": kv.get("numeric", False),
                         "unit": kv.get("unit", ""), "count": t["count"], "t_min": t["t_min"], "t_max": t["t_max"],
                         "lost": lost_base.get(t["base"], 0), "boots": len(t["boots"])})
    return rows


def file_info(info, name):
    """(packets, t_min, t_max) of one file of the overview, (None, None, None) if not read yet."""
    f = info.get("files", {}).get(name)
    if not f:
        return None, None, None
    tmin = [e["t_min"] for e in f["types"].values() if e["t_min"] is not None]
    tmax = [e["t_max"] for e in f["types"].values() if e["t_max"] is not None]
    return f["packets"], min(tmin) if tmin else None, max(tmax) if tmax else None


def _boot_offsets(dev_dir, names, known):
    """Time offset (time - uptime) per boot from the packets with a time, merged with known."""
    samples = {}
    for name in names:
        for _off, pkt in L.iter_packets((pathlib.Path(dev_dir) / name).read_bytes()):
            if not pkt:
                continue
            t, _src = packet_time(pkt)
            if t is not None and pkt.get("uptime_ms") is not None:
                samples.setdefault(str(pkt.get("boot")), []).append(t - pkt["uptime_ms"] / 1000.0)
    offsets = dict(known)
    for boot, vals in samples.items():
        offsets.setdefault(boot, statistics.median(vals))
    return offsets


def convert_device(dev_dir, sn=None, progress=None, cancel=None, rebuild=False):
    """
    Convert the new or grown data files of a device folder into <hwid>.sqlite (packets in
    redvypr_raw, values in the data_flat table "norlog"); every packet is written once. rebuild:
    delete the database and convert everything again. Returns the result of norlog_convert.convert()
    plus 'db', or {'files': 0, 'db'} if there was nothing to do.
    """
    dev_dir = pathlib.Path(dev_dir)
    db = db_path(dev_dir)
    state = _load_json(dev_dir / CONVERT_STATE, {})
    if rebuild:
        state = {}
        for p in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
            if p.exists():
                p.unlink()
    elif not db.exists():
        state = {}      # database deleted: convert everything again
    # (an existing database without convert.json, e.g. from "Convert to SQLite", is continued:
    # every packet is written once)
    done = state.setdefault("files", {})
    files = data_files(dev_dir)
    todo = [n for n, s in files if done.get(n) != s]
    if not todo:
        return {"files": 0, "db": str(db)}
    offsets = _boot_offsets(dev_dir, todo, state.get("boot_offsets", {}))
    res = norlog_convert.convert([dev_dir / n for n in todo], db, sn=sn, table=FLAT_TABLE, flat=True,
                                 progress=progress, cancel=cancel,
                                 boot_offsets={(dev_dir.name, int(b)): v for b, v in offsets.items()
                                               if b not in ("None", "")})
    sizes = dict(files)
    for n in todo[:res["files"]]:
        done[n] = sizes[n]
    state["boot_offsets"] = offsets
    _save_json(dev_dir / CONVERT_STATE, state)
    res["db"] = str(db)
    return res


def iter_packets(dev_dir, names=None, types=None, offsets=None):
    """
    Packets of the data files (all or names) of a device folder with their time ('t', 't_source'),
    only the packet types in types (None = all). Packets without any time are skipped.
    """
    dev_dir = pathlib.Path(dev_dir)
    names = [n for n, _s in data_files(dev_dir) if names is None or n in names]
    if offsets is None:
        offsets = _boot_offsets(dev_dir, names, _load_json(dev_dir / CONVERT_STATE, {}).get("boot_offsets", {}))
    for name in names:
        for _off, pkt in L.iter_packets((dev_dir / name).read_bytes()):
            if not pkt or (types is not None and pkt.get("packet_type") not in types):
                continue
            t, src = packet_time(pkt)
            if t is None:
                off = offsets.get(str(pkt.get("boot")))
                if off is None or pkt.get("uptime_ms") is None:
                    continue
                t, src = off + pkt["uptime_ms"] / 1000.0, "uptime"
            pkt["t"], pkt["t_source"] = t, src
            yield pkt
