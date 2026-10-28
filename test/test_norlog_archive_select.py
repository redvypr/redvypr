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

    def list(self, path):
        return [{"n": n, "s": len(b)} for n, b in self.files.items()]

    def read(self, path, off, length):
        name = path.rsplit("/", 1)[1]
        self.reads.append(name)
        return self.files[name][off:off + min(length, 100)]

    def crc(self, path, off, length):
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


def test_mismatch_is_loaded_again(tmp_path):
    remote = card()
    norlog_archive.sync(remote, tmp_path, hwid="HW1", stems={A})
    remote.files[f"{A}.cbor"] = b"x" * 250          # card swapped
    p = norlog_archive.plan(remote, tmp_path, hwid="HW1")
    assert next(f for f in p["files"] if f["name"] == f"{A}.cbor")["state"] == "mismatch"
    res = norlog_archive.sync(remote, tmp_path, hwid="HW1", stems={A})
    assert res["files"][0]["status"] == "replaced"
    assert (tmp_path / "HW1" / f"{A}.cbor").read_bytes() == b"x" * 250
    assert list((tmp_path / "HW1").glob(f"{A}.cbor.replaced-*"))
