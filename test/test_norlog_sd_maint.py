"""
SD card of a norlog: archive/delete the log files, format (firmware 0.4.44), with a simulated
norlog shell: 'norlog sd archive|delete|format|json' on the gateway, POST/GET sd on a member.
Firmware 0.4.44/45 answers the shell command at the end, 0.4.46 at once (state busy, then
'norlog sd json' with the growing number of deleted files).
"""
import json

import pytest

from redvypr.devices.norlog import ot_cli

ADDR = "fd00::ff:fe00:1400"


def state(op="", st="idle", rc=0, path="", deleted=0):
    return {"mounted": True, "logging": True, "file": "/log/data_00012_x.cbor", "op": op, "state": st,
            "rc": rc, "path": path, "deleted": deleted}


class FakeCli:
    def __init__(self, results=("busy", "ok"), local_rc=0, local_async=None):
        self.results = list(results)    # state of the following GET sd
        self.local_rc = local_rc
        self.local_async = None if local_async is None else list(local_async)  # 0.4.46: (state, deleted)
        self.sent = []
        self.op = ""

    def shell_query(self, cmd, prefix, timeout=4.0):
        self.sent.append(cmd)
        if cmd.startswith("norlog sd "):
            assert prefix == ot_cli.SD_PREFIX
            parts = cmd.split(" ")
            if parts[2] == "json":
                if self.local_async is not None:
                    st, n = self.local_async.pop(0)
                    return json.dumps(state(self.op, st, deleted=n))
                return json.dumps(state())
            op = parts[2]
            self.op = op
            if self.local_async is not None:
                return "ok " + json.dumps(state(op, "busy"))
            if self.local_rc:
                return f"err {self.local_rc} " + json.dumps(state(op, "error", self.local_rc))
            return "ok " + json.dumps(state(op, "ok", path="/archive/test_2026-11-05_181500" if op == "archive"
                                            else "", deleted=7 if op == "delete" else 0))
        assert prefix == ot_cli.COAP_PREFIX
        parts = cmd.split(" ")
        method, addr, uri = parts[2], parts[3], parts[4]
        assert addr == ADDR
        if method == "post":
            self.op = uri.split("op=")[1].split("&")[0]
            self.post_uri = uri
            return f"ok {addr} 2.04 txt {{\"ok\":true}}"
        assert method == "get" and uri == "sd"
        st = self.results.pop(0)
        return f"ok {addr} 2.05 txt " + json.dumps(state(self.op, st, -5 if st == "error" else 0,
                                                          "/archive/x_1" if st == "ok" else ""))


def test_local_archive_delete_format():
    cli = FakeCli()
    st = ot_cli.sd_op_local(cli, "archive", "test")
    assert cli.sent[-1] == "norlog sd archive test" and st["path"] == "/archive/test_2026-11-05_181500"
    assert ot_cli.sd_op_local(cli, "delete")["deleted"] == 7
    assert cli.sent[-1] == "norlog sd delete confirm"
    ot_cli.sd_op_local(cli, "format")
    assert cli.sent[-1] == "norlog sd format confirm"
    assert ot_cli.sd_status_local(cli)["state"] == "idle"


def test_local_error_and_invalid_name():
    with pytest.raises(ot_cli.OtError, match=r"failed \(-16\)"):
        ot_cli.sd_op_local(FakeCli(local_rc=-16), "delete")
    with pytest.raises(ValueError):
        ot_cli.sd_op_local(FakeCli(), "archive", "bad name/..")
    with pytest.raises(ValueError):
        ot_cli.sd_op_local(FakeCli(), "erase")


def test_remote_archive_waits_for_result():
    cli = FakeCli(results=["busy", "busy", "ok"])
    st = ot_cli.sd_op_remote(cli, ADDR, "archive", "run1", poll=0)
    assert cli.post_uri == "sd?op=archive&name=run1" and st["path"] == "/archive/x_1"
    assert sum(c.startswith("norlog coap get") for c in cli.sent) == 3


def test_remote_format_needs_confirm_and_reports_errors():
    cli = FakeCli(results=["error"])
    with pytest.raises(ot_cli.OtError, match="failed"):
        ot_cli.sd_op_remote(cli, ADDR, "format", poll=0)
    assert cli.post_uri == "sd?op=format&confirm=1"


def test_local_async_polls_with_progress():
    cli = FakeCli(local_async=[("busy", 40), ("busy", 40), ("busy", 300), ("ok", 412)])
    seen = []
    st = ot_cli.sd_op_local(cli, "delete", poll=0, progress=lambda s: seen.append(s["deleted"]))
    assert st["deleted"] == 412 and cli.sent[0] == "norlog sd delete confirm"
    assert seen == [0, 40, 300]         # only when something moved


def test_local_async_gives_up_without_progress():
    cli = FakeCli(local_async=[("busy", 5)] * 1000)
    with pytest.raises(TimeoutError, match="no progress"):
        ot_cli.sd_op_local(cli, "delete", stall=0.05, poll=0.001)


def test_remote_progress():
    cli = FakeCli(results=["busy", "busy", "ok"])
    seen = []
    ot_cli.sd_op_remote(cli, ADDR, "format", poll=0, progress=seen.append)
    assert [s["state"] for s in seen] == ["busy", "busy"]
