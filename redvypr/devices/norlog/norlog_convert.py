"""
Convert norlog log files (*.cbor, e.g. from the archive) into an SQLite database
in the redvypr format: the packets as they are (raw data) in the table
redvypr_raw (type redvypr_datapacket, one row per packet), written by the redvypr
SQLite engine (DbSqlite) like the SQLite writer of "Save data" of the gateway.
Optionally (flat=True, --flat) also a data_flat table "norlog" (one column per
datastream) as convenience for plots.

The packets get the header of their norlog (device norlog_<sn>, deviceid =
hardware ID, sensorid = sn, packetid = packet type) and their measurement
time: the RTC or GPS time of the packet, or for packets written before the
clock was set, uptime + offset of their boot (learned from the packets of the
same device and boot that have a time). Packets without any time are not
written. Every packet is written once (skip_duplicates, uid_keys boot + packet_num): converting a
file again or overlapping files add nothing, converting into an existing database
adds the new data.

The units of the values ("unit" of "board_temp_c @ di:<hwid>") and the hardware ID
and serial number of every norlog ("@di:<hwid>") are stored as metadata in the
database (table redvypr_metadata), the plot finds them without a running norlog.

    python -m redvypr.devices.norlog.norlog_convert -o data.sqlite --sn 002 norlog_archive/9AB64B5C71AE5C1C
    python -m redvypr.devices.norlog.norlog_convert -o data.sqlite data_00167_*.cbor
"""

import logging
import pathlib
import sqlite3
import statistics
import time

from . import norlog_logindex as L
from .norlog_archive import to_redvypr_packet
from .norlog_cbor import packet_time, units_of

logger = logging.getLogger('redvypr.device.norlog_convert')

# A norlog packet is identified by its device (deviceid = hardware ID), boot and packet_num:
# the same packet received live and converted from the SD card is stored once
UID_KEYS = ["boot", "packet_num"]

CONVERT_HOST = {"host": "norlog_convert", "tstart": 0, "addr": None, "uuid": "norlog_convert"}


class ConvertError(Exception):
    pass


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
            t, _src = packet_time(pkt)
            if t is not None and pkt.get("uptime_ms") is not None:
                samples.setdefault((pkt.get("mac"), pkt.get("boot")), []).append(t - pkt["uptime_ms"] / 1000.0)
    return {k: statistics.median(v) for k, v in samples.items()}


def _stored_metadata(db_path):
    """Metadata written by earlier conversions into db_path, storage format {address: [entries]}."""
    import redvypr.metadata
    from redvypr.serialize import deserialize_json
    if not pathlib.Path(db_path).is_file():
        return {}
    storage = {}
    try:
        con = sqlite3.connect(str(db_path))
        try:
            rows = con.execute("SELECT redvypr_address, metadata FROM redvypr_metadata WHERE uuid = ?",
                               (CONVERT_HOST["uuid"],)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    for address, content in rows:
        try:
            for a, entries in redvypr.metadata.normalize_metadata({address: deserialize_json(content)}).items():
                storage.setdefault(a, []).extend(entries)
        except Exception:
            logger.debug(f"could not read the metadata of {address}", exc_info=True)
    return storage


def _add_metadata(data, pkt, sn, sent):
    """Metadata of a norlog (hardware ID, serial number) and units of its values, once each."""
    import redvypr.metadata
    hwid = pkt.get("mac")
    if not hwid:
        return
    if hwid not in sent:
        meta = {"hwid": hwid, **({"sn": sn} if sn else {})}
        redvypr.metadata.add_metadata2datapacket(data, address=f"@di:'{hwid}'", metadict=meta, hostinfo=CONVERT_HOST)
        sent.add(hwid)
    for key, unit in units_of(pkt).items():
        if (hwid, key, unit) not in sent:
            redvypr.metadata.add_metadata2datapacket(data, address=f"{key}@di:'{hwid}'", metadict={"unit": unit},
                                                     hostinfo=CONVERT_HOST)
            sent.add((hwid, key, unit))


RAW_TABLE = "redvypr_raw"


def db_config(db_path, table="norlog", flat=False):
    """
    SqliteConfig of the conversion: one file, continued, the packets in RAW_TABLE (and with flat a
    data_flat table with all datastreams), each packet/value once.
    """
    from redvypr.devices.db.db_engine_sqlite import SqliteConfig
    from redvypr.devices.db.db_config_util import DbWriteConfig, DbTableConfig
    tables = {RAW_TABLE: DbTableConfig(tablename=RAW_TABLE, tabletype="redvypr_datapacket", addresses=["@"],
                                       skip_duplicates=True, uid_keys=UID_KEYS)}
    if flat:
        tables[table] = DbTableConfig(tablename=table, tabletype="data_flat", addresses=["@"], skip_duplicates=True)
    return SqliteConfig(filepath=str(db_path), storage="file", append_to_file=True, batch_size=2000,
                        dt_newfile=0, dt_newfile_unit="none", max_file_size_mb=None,
                        write_config=DbWriteConfig(tables=tables, name="norlog_convert",
                                                   description="norlog log files converted by norlog_convert"))


def convert(inputs, db_path, sn=None, table="norlog", progress=None, cancel=None, flat=False, boot_offsets=None):
    """
    Convert *.cbor files (files and/or folders) into db_path (created or extended).
    sn: serial number of the norlog for the header (device norlog_<sn>, sensorid).
    flat: also the data_flat table <table> (one column per datastream).
    progress(done_files, total_files, name); cancel() -> True stops after the current file.
    boot_offsets: {(hardware ID, boot): time - uptime} instead of learning them from the files
    (e.g. learned from earlier files of the same boot).
    Returns {'files', 'packets', 'written', 'without_time', 'packets_new', 'packets_duplicate',
    'entries', 'entries_duplicate', 'metadata', 'seconds', 'cancelled'}.
    """
    import redvypr.metadata
    from redvypr.devices.db.db_engine_sqlite import DbSqlite
    files = find_files(inputs)
    if not files:
        raise ConvertError("no data_*.cbor files")
    t_start = time.monotonic()
    offsets = _boot_offsets(files) if boot_offsets is None else boot_offsets
    metadata = {"metadata": _stored_metadata(db_path)}
    meta_sent = set()
    db = DbSqlite(db_config(db_path, table, flat))
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
                t, src = packet_time(pkt)
                if t is None:
                    off_boot = offsets.get((pkt.get("mac"), pkt.get("boot")))
                    if off_boot is None or pkt.get("uptime_ms") is None:
                        res["without_time"] += 1
                        continue
                    t, src = off_boot + pkt["uptime_ms"] / 1000.0, "uptime"
                pkt["t"], pkt["t_source"] = t, src
                data = to_redvypr_packet(pkt, sn, hostinfo=CONVERT_HOST)
                _add_metadata(data, pkt, sn, meta_sent)
                if "_metadata" in data:
                    redvypr.metadata.do_metadata(data, metadata)
                    del data["_metadata"]
                db.insert_packet(data)
                res["written"] += 1
            res["files"] += 1
    finally:
        for address, entries in metadata["metadata"].items():
            db.add_metadata(address, CONVERT_HOST["uuid"], entries)
        res["metadata"] = len(metadata["metadata"])
        db.close()
    st = db.file_statistics_total
    res["packets_new"] = st.get("packets_raw_written", 0)
    res["packets_duplicate"] = st.get("packets_duplicate_skipped", 0)
    res["entries"] = st.get("entries_flat_written", 0)
    res["entries_duplicate"] = st.get("entries_duplicate_skipped", 0)
    if progress:
        progress(len(files), len(files), "")
    res["seconds"] = time.monotonic() - t_start
    return res


def summary(res, db_path):
    text = (f"{res['files']} file(s), {res['packets']} packets into {db_path}: {res['packets_new']} new packets, "
            f"{res['packets_duplicate']} already in the database")
    if res["entries"] or res["entries_duplicate"]:
        text += f"; flat table: {res['entries']} new values, {res['entries_duplicate']} already there"
    text += f" ({res['seconds']:.1f} s)"
    if res["without_time"]:
        text += (f"; {res['without_time']} packets without time not written (the clock of their boot was never "
                 f"set)")
    if res["cancelled"]:
        text = "cancelled after " + text
    return text


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Convert norlog log files (*.cbor) into an SQLite database in the "
                                             "redvypr format (packets in the table redvypr_raw).")
    ap.add_argument("inputs", nargs="+", help="data_*.cbor files and/or folders (searched recursively)")
    ap.add_argument("-o", "--output", required=True, help="SQLite file (created or extended)")
    ap.add_argument("--sn", default=None, help="serial number of the norlog (device norlog_<sn>, sensorid)")
    ap.add_argument("--flat", action="store_true", help="also a data_flat table (one column per datastream)")
    ap.add_argument("--table", default="norlog", help="name of the data_flat table (default: norlog)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    try:
        res = convert(a.inputs, a.output, sn=a.sn, table=a.table, flat=a.flat,
                      progress=lambda i, n, name: name and print(f"[{i + 1}/{n}] {name}", flush=True))
    except ConvertError as exc:
        raise SystemExit(str(exc))
    print(summary(res, a.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
