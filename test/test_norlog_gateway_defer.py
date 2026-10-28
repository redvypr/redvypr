"""
Commands that arrive while the norlog gateway thread is busy (flash, download, file list)
wait and run afterwards instead of being dropped (redvypr.devices.norlog.norlog_gateway._Gateway).
"""
import queue

from redvypr.devices.norlog import norlog_gateway as ng


def make_gateway(monkeypatch):
    monkeypatch.setattr(ng, "check_for_command",
                        lambda data, **kw: (data["cmd"], {"command_data": {"data": data.get("args")}}))
    gw = ng._Gateway({"device": None, "thread_uuid": "t"}, None, queue.Queue(), queue.Queue())
    gw.executed = []
    gw.execute = lambda command, args: gw.executed.append((command, args))
    return gw


def test_commands_wait_during_a_download(monkeypatch):
    gw = make_gateway(monkeypatch)
    gw.datainqueue.put({"cmd": "data_list", "args": {"target": "0x1000"}})
    gw.datainqueue.put({"cmd": "data_list", "args": {"target": "0x1000"}})     # double click
    gw.datainqueue.put({"cmd": "sync_cancel", "args": {}})
    assert gw.check_commands(during_flash=True) is True
    assert gw.executed == [] and gw.deferred == [("data_list", {"target": "0x1000"})]
    gw.check_commands()
    assert gw.executed == [("data_list", {"target": "0x1000"})] and gw.deferred == []
