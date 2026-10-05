"""
Convert norlog log files (*.cbor, e.g. from the archive) into an SQLite database
in the redvypr format: a data_flat table (one column per datastream, e.g.
"board_temp_c @ d:'norlog_002' and di:'9AB6...' and i:'board_temp' and
h:'norlog_convert'") written by the redvypr SQLite engine (DbSqlite). The file
can be read with the redvypr database tools (DbSqlite.get_data(), replay,
plots) like a file of the SQLite writer.

The packets get the header of their norlog (device norlog_<sn>, deviceid =
hardware ID, sensorid = sn, packetid = packet type) and their measurement
time: the RTC or GPS time of the packet, or for packets written before the
clock was set, uptime + offset of their boot (learned from the packets of the
same device and boot that have a time). Packets without any time are not
written (data_flat needs a time). Every value is written once (skip_duplicates):
converting a file again or overlapping files add nothing, converting into an
existing database adds the new data.

    python -m redvypr.devices.norlog.norlog_convert -o data.sqlite --sn 002 norlog_archive/9AB64B5C71AE5C1C
    python -m redvypr.devices.norlog.norlog_convert -o data.sqlite data_00167_*.cbor
"""

import datetime
import logging
import pathlib
import statistics
import time

from . import norlog_logindex as L
from .norlog_archive import to_redvypr_packet

logger = logging.getLogger('redvypr.device.norlog_convert')

CONVERT_HOST = {"host": "norlog_convert", "tstart": 0, "addr": None, "uuid": "norlog_convert"}


class ConvertError(Exception):
    pass


def _packet_time(pkt):
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


def find_files(inputs):
    """*.cbor files of the given files and folders (folders recursively), sorted, without duplicates."""
    files = []
    for item in inputs:
        p = pathlib.Path(item)
        if p.is_dir():
            files.extend(sorted(p.rglob("data_*.cbor")))
        elif p.is_file():
            files.append(p)
        else:
            matches = sorted(pathlib.Path().glob(str(item)))       # pattern not expanded by the shell
            if not matches:
                raise ConvertError(f"not found: {item}")
            files.extend(matches)
    seen, result = set(), []
    for f in files:
        key = f.resolve()
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result


def _boot_offsets(files):
    """Time offset (time - uptime) of every (hardware ID, boot) from the packets with a time."""
    samples = {}
    for f in files:
        for _off, pkt in L.iter_packets(pathlib.Path(f).read_bytes()):
            if not pkt:
                continue
            t, _src = _packet_time(pkt)
            if t is not None and pkt.get("uptime_ms") is not None:
                samples.setdefault((pkt.get("mac"), pkt.get("boot")), []).append(t - pkt["uptime_ms"] / 1000.0)
    return {k: statistics.median(v) for k, v in samples.items()}


def db_config(db_path, table="norlog"):
    """SqliteConfig of the conversion: one file, continued, data_flat with all datastreams, each value once."""
    from redvypr.devices.db.db_engine_sqlite import SqliteConfig
    from redvypr.devices.db.db_config_util import DbWriteConfig, DbTableConfig
    tables = {table: DbTableConfig(tablename=table, tabletype="data_flat", addresses=["@"], skip_duplicates=True)}
    return SqliteConfig(filepath=str(db_path), storage="file", append_to_file=True, batch_size=2000,
                        dt_newfile=0, dt_newfile_unit="none", max_file_size_mb=None,
                        write_config=DbWriteConfig(tables=tables, name="norlog_convert",
                                                   description="norlog log files converted by norlog_convert"))


def convert(inputs, db_path, sn=None, table="norlog", progress=None, cancel=None):
    """
    Convert *.cbor files (files and/or folders) into db_path (created or extended).
    sn: serial number of the norlog for the header (device norlog_<sn>, sensorid).
    progress(done_files, total_files, name); cancel() -> True stops after the current file.
    Returns {'files', 'packets', 'written', 'without_time', 'entries', 'entries_duplicate',
    'seconds', 'cancelled'}.
    """
    from redvypr.devices.db.db_engine_sqlite import DbSqlite
    files = find_files(inputs)
    if not files:
        raise ConvertError("no data_*.cbor files")
    t_start = time.monotonic()
    offsets = _boot_offsets(files)
    db = DbSqlite(db_config(db_path, table))
    res = {"files": 0, "packets": 0, "written": 0, "without_time": 0, "cancelled": False}
    try:
        for i, f in enumerate(files):
            if cancel and cancel():
                res["cancelled"] = True
                break
            if progress:
                progress(i, len(files), f.name)
            for _off, pkt in L.iter_packets(f.read_bytes()):
                if not pkt:
                    continue
                res["packets"] += 1
                t, src = _packet_time(pkt)
                if t is None:
                    off_boot = offsets.get((pkt.get("mac"), pkt.get("boot")))
                    if off_boot is None or pkt.get("uptime_ms") is None:
                        res["without_time"] += 1
                        continue
                    t, src = off_boot + pkt["uptime_ms"] / 1000.0, "uptime"
                pkt["t"], pkt["t_source"] = t, src
                db.insert_packet(to_redvypr_packet(pkt, sn, hostinfo=CONVERT_HOST))
                res["written"] += 1
            res["files"] += 1
    finally:
        db.close()
    st = db.file_statistics_total
    res["entries"] = st.get("entries_flat_written", 0)
    res["entries_duplicate"] = st.get("entries_duplicate_skipped", 0)
    if progress:
        progress(len(files), len(files), "")
    res["seconds"] = time.monotonic() - t_start
    return res


def summary(res, db_path):
    text = (f"{res['files']} file(s), {res['packets']} packets into {db_path}: {res['entries']} new values, "
            f"{res['entries_duplicate']} already in the database ({res['seconds']:.1f} s)")
    if res["without_time"]:
        text += (f"; {res['without_time']} packets without time not written (the clock of their boot was never "
                 f"set)")
    if res["cancelled"]:
        text = "cancelled after " + text
    return text


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Convert norlog log files (*.cbor) into an SQLite database in the "
                                             "redvypr data_flat format.")
    ap.add_argument("inputs", nargs="+", help="data_*.cbor files and/or folders (searched recursively)")
    ap.add_argument("-o", "--output", required=True, help="SQLite file (created or extended)")
    ap.add_argument("--sn", default=None, help="serial number of the norlog (device norlog_<sn>, sensorid)")
    ap.add_argument("--table", default="norlog", help="name of the data_flat table (default: norlog)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    try:
        res = convert(a.inputs, a.output, sn=a.sn, table=a.table,
                      progress=lambda i, n, name: name and print(f"[{i + 1}/{n}] {name}", flush=True))
    except ConvertError as exc:
        raise SystemExit(str(exc))
    print(summary(res, a.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
