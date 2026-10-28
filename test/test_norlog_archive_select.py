"""
File list, selection and order of the norlog archive download
(redvypr.devices.norlog.norlog_archive.plan/sync with a simulated SD card).
"""
import zlib

from redvypr.devices.norlog import norlog_archive

A = "data_00001_2026-10-01_120000_00000001"
B = "data_00002_2026-10-02_120000_00000001"
C = "data_00003_2026-10-03_120000_00000001"


class FakeRemote:
    def __init__(self, files):
        self.files = dict(files)        # name -> bytes (no catalog: hwid given)
        self.reads = []
        self.crcs = []

    def list(self, path):
        return [{"n": n, "s": len(b)} for n, b in self.files.items()]

    def read(self, path, off, length):
        name = path.rsplit("/", 1)[1]
        self.reads.append(name)
        return self.files[name][off:off + min(length, 100)]

    def crc(self, path, off, length):
        self.crcs.append((path.rsplit("/", 1)[1], off, length))
        return zlib.crc32(self.files[path.rsplit("/", 1)[1]][off:off + length])

    def read_all(self, path):
        raise AssertionError("no catalog in this test")


def card():
    return FakeRemote({f"{A}.cbor": b"a" * 250, f"{A}.idx": b"i" * 20, f"{B}.cbor": b"b" * 150,
                       f"{B}.idx": b"j" * 10, f"{C}.cbor": b"c" * 50, f"{C}.idx": b"k" * 5})


def test_plan_does_not_download(tmp_path):
    remote = card()
    p = norlog_archive.plan(remote, tmp_path, hwid="HW1")
    assert [f["name"] for f in p["files"]][:2] == [f"{A}.cbor", f"{A}.idx"]
    assert all(f["state"] == "new" and f["local"] == 0 for f in p["files"])
    assert remote.reads == []


def test_selection_and_newest_first(tmp_path):
    remote = card()
    res = norlog_archive.sync(remote, tmp_path, hwid="HW1", stems={A, C}, newest_first=True)
    assert [f["name"] for f in res["files"]] == [f"{C}.cbor", f"{C}.idx", f"{A}.cbor", f"{A}.idx"]
    assert remote.reads[0] == f"{C}.cbor" and f"{B}.cbor" not in remote.reads
    assert res["bytes"] == 250 + 20 + 50 + 5
    assert (tmp_path / "HW1" / f"{A}.cbor").read_bytes() == b"a" * 250

    # B is still new, A and C up to date; C grows on the card
    remote.files[f"{C}.cbor"] += b"c" * 30
    states = {f["name"]: f["state"] for f in norlog_archive.plan(remote, tmp_path, hwid="HW1")["files"]}
    assert states[f"{A}.cbor"] == "unchanged" and states[f"{B}.cbor"] == "new"
    assert states[f"{C}.cbor"] == "grown"


def test_all_chronological_by_default(tmp_path):
    remote = card()
    res = norlog_archive.sync(remote, tmp_path, hwid="HW1")
    assert [f["name"] for f in res["files"]][::2] == [f"{A}.cbor", f"{B}.cbor", f"{C}.cbor"]


def test_list_compares_sizes_only(tmp_path):
    remote = card()
    norlog_archive.sync(remote, tmp_path, hwid="HW1")
    remote.crcs.clear()
    remote.files[f"{C}.cbor"] += b"c" * 10              # only C grew: one tail CRC
    p = norlog_archive.plan(remote, tmp_path, hwid="HW1")
    assert [c[0] for c in remote.crcs] == [f"{C}.cbor"]
    assert sum(f["state"] == "unchanged" for f in p["files"]) == 5


def test_verify_and_reload(tmp_path):
    remote = card()
    norlog_archive.sync(remote, tmp_path, hwid="HW1", stems={A})
    remote.files[f"{A}.cbor"] = b"x" * 250              # same size, other content
    state = lambda p: next(f for f in p["files"] if f["name"] == f"{A}.cbor")["state"]
    assert state(norlog_archive.plan(remote, tmp_path, hwid="HW1")) == "unchanged"
    seen = []
    p = norlog_archive.plan(remote, tmp_path, hwid="HW1", verify=True, progress=lambda i, n, f: seen.append(i))
    assert state(p) == "mismatch" and seen[-1] == len(p["files"])
    res = norlog_archive.sync(remote, tmp_path, hwid="HW1", stems={A}, reload={f"{A}.cbor"})
    assert res["files"][0]["status"] == "replaced"
    assert (tmp_path / "HW1" / f"{A}.cbor").read_bytes() == b"x" * 250
    assert list((tmp_path / "HW1").glob(f"{A}.cbor.replaced-*"))


def test_fs_list_reports_pages_and_total():
    from redvypr.devices.norlog import ot_cli
    pages = {0: {"entries": [{"n": "a", "s": 1}], "next": 1, "total": 2}, 1: {"entries": [{"n": "b", "s": 2}], "next": 0}}
    seen = []
    ot_cli_fs_local = ot_cli.fs_local
    try:
        ot_cli.fs_local = lambda cli, op, path, start: pages[start]
        entries = ot_cli.fs_list(None, None, "/log", progress=lambda e, total: seen.append((len(e), total)))
    finally:
        ot_cli.fs_local = ot_cli_fs_local
    assert [e["n"] for e in entries] == ["a", "b"] and seen == [(1, 2), (2, 2)]


def _catalog(records, hwid=0x9AB64B5C71AE5C1C):
    from redvypr.devices.norlog import norlog_logindex as L
    data = L.CATALOG_HEADER.pack(L.CATALOG_MAGIC, 2, L.CATALOG_RECORD.size, hwid)
    for i, (name, boot, packets) in enumerate(records):
        data += L.CATALOG_RECORD.pack(i + 1, boot, 0, 0, packets, 0, 1, 0, 0, 0, 0, 0, name.encode())
    return data


class CatalogRemote(FakeRemote):
    def read(self, path, off, length):
        name = path.rsplit("/", 1)[1]
        self.reads.append((name, off))
        return self.files[name][off:off + min(length, 100)]


def test_catalog_is_loaded_incrementally(tmp_path):
    remote = CatalogRemote(card().files)
    remote.files["catalog.dat"] = _catalog([(f"{A}.cbor", 7, 10), (f"{B}.cbor", 8, 5)])
    p = norlog_archive.plan(remote, tmp_path)
    assert p["hwid"] == "9AB64B5C71AE5C1C"
    assert {f["name"]: f["boot"] for f in p["files"]}[f"{B}.idx"] == 8
    first = [o for n, o in remote.reads if n == "catalog.dat"]
    assert first[0] == 0 and len(first) > 2

    # B is closed (its record changes), C is new: only from the last known record on
    remote.reads.clear()
    remote.files["catalog.dat"] = _catalog([(f"{A}.cbor", 7, 10), (f"{B}.cbor", 8, 9), (f"{C}.cbor", 9, 1)])
    p = norlog_archive.plan(remote, tmp_path)
    offsets = [o for n, o in remote.reads if n == "catalog.dat"]
    assert offsets[0] == 0 and min(offsets[1:]) == 16 + 96         # header, then record B on
    assert (tmp_path / p["hwid"] / "catalog.dat").read_bytes() == remote.files["catalog.dat"]
    assert {f["name"]: f["boot"] for f in p["files"]}[f"{C}.cbor"] == 9


class FlakyRemote(FakeRemote):
    """Garbles the first read of chosen offsets (like a log line inside an answer of the gateway)."""

    def __init__(self, files, bad):
        super().__init__(files)
        self.bad = set(bad)

    def read(self, path, off, length):
        data = super().read(path, off, length)
        if off in self.bad:
            self.bad.discard(off)
            return bytes(b ^ 0xFF for b in data)
        return data


def test_garbled_block_is_read_again(tmp_path, monkeypatch):
    monkeypatch.setattr(norlog_archive, "REPAIR_PIECE", 64)
    remote = FlakyRemote(card().files, bad={100})
    res = norlog_archive.sync(remote, tmp_path, hwid="HW1", stems={A})
    assert res["files"][0]["status"] == "new" and "errors" not in res
    assert (tmp_path / "HW1" / f"{A}.cbor").read_bytes() == b"a" * 250


class BrokenRemote(FakeRemote):
    """One file reads wrong every time."""

    def read(self, path, off, length):
        data = super().read(path, off, length)
        return bytes(b ^ 0xFF for b in data) if path.endswith(f"{B}.cbor") else data


def test_failed_file_does_not_stop_the_others(tmp_path):
    remote = BrokenRemote(card().files)
    res = norlog_archive.sync(remote, tmp_path, hwid="HW1")
    status = {f["name"]: f["status"] for f in res["files"]}
    assert status[f"{B}.cbor"] == "failed" and status[f"{C}.cbor"] == "new" and len(res["errors"]) == 1
    assert (tmp_path / "HW1" / f"{B}.cbor").stat().st_size == 0


def test_gateway_block_with_log_text_is_read_again(monkeypatch):
    import base64
    from redvypr.devices.norlog import ot_cli
    good = base64.b64encode(b"x" * 48).decode()
    answers = [good[:20] + "[NMEA] 4800 Baud" + good[20:], good]       # log text inside, then clean
    monkeypatch.setattr(ot_cli, "fs_local", lambda cli, *a, **k: answers.pop(0))
    assert ot_cli.fs_read_block(None, None, "/log/x", 0, 48) == b"x" * 48 and not answers


def test_gateway_block_crc(monkeypatch):
    import base64
    import zlib
    from redvypr.devices.norlog import ot_cli
    data = bytes(range(48))
    b64 = base64.b64encode(data).decode()
    wrong = base64.b64encode(bytes(range(1, 49))).decode()       # clean base64, but other bytes
    answers = [f"{wrong} {zlib.crc32(data):08x}", f"{b64} {zlib.crc32(data):08x}", "- 00000000", b64]
    monkeypatch.setattr(ot_cli, "fs_local", lambda cli, *a, **k: answers.pop(0))
    assert ot_cli.fs_read_block(None, None, "/log/x", 0, 48) == data      # CRC wrong: read again
    assert ot_cli.fs_read_block(None, None, "/log/x", 48, 48) == b""      # end of the file
    assert ot_cli.fs_read_block(None, None, "/log/x", 0, 48) == data      # firmware < 0.4.23
