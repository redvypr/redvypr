"""
Loader update without SWD, redvypr.devices.norlog.ot_cli.fw_loader_* (with a simulated
norlog shell, firmware 0.4.42): 'norlog fw loader' / 'norlog fw json' on the gateway,
POST fw?op=loader and GET fw on a member.
"""
import json

import pytest

from redvypr.devices.norlog import ot_cli

ADDR = "fd00::ff:fe00:1400"


def status(loader="1.0.2+0", state="none", rc=1):
    return {"running": "0.4.42+0", "auto": True, "update": None, "loader": loader,
            "loader_file": {"version": "1.0.3+0", "size": 58000}, "loader_state": state, "loader_rc": rc}


class FakeCli:
    def __init__(self, results=("busy", "ok"), local="ok"):
        self.results = list(results)    # loader_state of the following GET fw
        self.local = local
        self.sent = []

    def shell_query(self, cmd, prefix, timeout=4.0):
        self.sent.append(cmd)
        assert prefix in (ot_cli.FW_PREFIX, ot_cli.COAP_PREFIX)
        if cmd == "norlog fw json":
            return json.dumps(status())
        if cmd == "norlog fw loader":
            if self.local == "ok":
                return "ok " + json.dumps(status("1.0.3+0", "ok", 0))
            return "err -2 no /fw/loader.bin"
        if cmd.startswith("norlog coap"):
            parts = cmd.split(" ")
            method, addr, uri = parts[2], parts[3], parts[4]
            assert addr == ADDR
            if method == "post":
                assert uri == "fw?op=loader"
                return f"ok {addr} 2.04 txt {{\"ok\":true}}"
            assert method == "get" and uri == "fw"
            state = self.results.pop(0)
            st = status("1.0.3+0" if state == "ok" else "1.0.2+0", state, 0 if state == "ok" else -5)
            return f"ok {addr} 2.05 txt {json.dumps(st)}"
        raise AssertionError(cmd)


def test_local_loader_install():
    cli = FakeCli()
    assert ot_cli.fw_status_local(cli)["loader"] == "1.0.2+0"
    st = ot_cli.fw_loader_local(cli)
    assert st["loader"] == "1.0.3+0" and st["loader_state"] == "ok"


def test_local_loader_error():
    with pytest.raises(ot_cli.OtError, match="no /fw/loader.bin"):
        ot_cli.fw_loader_local(FakeCli(local="err"))


def test_remote_loader_install_waits_for_result():
    cli = FakeCli(results=["busy", "busy", "ok"])
    st = ot_cli.fw_loader_remote(cli, ADDR, poll=0)
    assert st["loader"] == "1.0.3+0"
    assert sum(c.startswith("norlog coap get") for c in cli.sent) == 3


def test_remote_loader_install_error():
    with pytest.raises(ot_cli.OtError, match="failed"):
        ot_cli.fw_loader_remote(FakeCli(results=["busy", "error"]), ADDR, poll=0)
