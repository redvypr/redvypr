"""
GUI of the norlog gateway with several serial ports: device list as tree (ports at the top,
members below their gateway), port actions, port choice of console and Thread tab.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

from redvypr.devices.norlog import device_list
from redvypr.devices.norlog import norlog_gateway as ng
from redvypr.devices.norlog import ports

FOUND = [{"name": "COM5", "description": "nRF52840 shell", "usb_sn": "S5", "vid": 0x1915, "pid": 1},
         {"name": "COM7", "description": "nRF52840 shell", "usb_sn": "S7", "vid": 0x1915, "pid": 1},
         {"name": "COM1", "description": "Communications Port", "usb_sn": "", "vid": None, "pid": None}]


class FakeDevice(QtCore.QObject):
    thread_started = QtCore.pyqtSignal(dict)
    thread_stopped = QtCore.pyqtSignal(dict)
    new_data = QtCore.pyqtSignal(list)
    mp = "thread"
    subscribes = False
    statusqueue = None
    redvypr = None

    def __init__(self, cfg):
        super().__init__()
        self.custom_config = cfg
        self.running = False
        self.commands = []

    def get_thread_status(self):
        return {"thread_running": self.running}

    def thread_command(self, command, data=None):
        self.commands.append((command, data))


@pytest.fixture
def widget(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(ports, "scan", lambda: [dict(f) for f in FOUND])
    dev = FakeDevice(ng.DeviceCustomConfig(comport="COM5"))
    w = ng.RedvyprDeviceWidget(device=dev)
    yield w
    w.close()
    assert app is not None


def tree_rows(w):
    rows = []

    def walk(item, depth):
        rows.append((depth, item.text(0)))
        for i in range(item.childCount()):
            walk(item.child(i), depth + 1)
    for i in range(w.devices_table.topLevelItemCount()):
        walk(w.devices_table.topLevelItem(i), 0)
    return rows


def test_offline_ports_and_migration(widget):
    w = widget
    # the older comport became the first port, role gateway
    assert [(p.port, p.role) for p in w.cfg.ports] == [("COM5", "gateway")] and w.cfg.comport == ""
    assert tree_rows(w) == [(0, "COM5"), (0, "COM7"), (0, "COM1")]
    assert w.current_devices[0]["port_state"] == device_list.PORT_CLOSED
    # not all ports: COM1 (no norlog) hidden
    w.show_all_ports.setChecked(False)
    assert tree_rows(w) == [(0, "COM5"), (0, "COM7")]
    # connect COM7 with role node: stored with its USB serial number
    w.port_connect("COM7", True)
    w.port_set_role("COM7", "node")
    pc = w.port_config("COM7")
    assert (pc.port, pc.usb_sn, pc.role, pc.connect) == ("COM7", "S7", "node", True)
    # found again under another name by its USB serial number
    FOUND[1]["name"] = "COM9"
    try:
        w.scan_ports()
        assert w.port_config("COM9") is pc and pc.port == "COM9"
    finally:
        FOUND[1]["name"] = "COM7"
    w.port_forget("COM9")
    assert [p.port for p in w.cfg.ports] == ["COM5"]


def test_running_tree_dialog_and_port_choice(widget):
    w = widget
    w.device.running = True
    status = {"state": "leader", "extpanid": "net", "rloc16": "0x1000", "extaddr": "1111",
              "children": [{"Extended MAC": "2222", "RLOC16": "0x1001"}]}
    rows = [{"name": "COM5", "state": device_list.PORT_OPEN, "key": "port:COM5", "active": True,
             "status": status, "role": "gateway"},
            {"name": "COM7", "state": device_list.PORT_ERROR, "error": "access denied"}]
    devices = device_list.build_devices(rows)
    w.on_new_data([{"_redvypr": {"packetid": "thread_status"}, "devices": devices,
                    "gateways": {"net": "COM5"}, "port_status": {"COM5": status}}])
    assert tree_rows(w) == [(0, "COM5"), (1, "thread"), (0, "COM7")]
    member = w.devices_table.topLevelItem(0).child(0)
    assert "via COM5" in member.toolTip(0) and "Extended MAC 2222" in member.toolTip(0)
    assert w.console_port.currentData() == "COM5" and w.thread_port.currentData() == "COM5"
    assert w.status_tree.topLevelItem(0).text(1) == "leader"
    # settings dialog of the serial device: its key changes to the hardware ID
    w.open_settings("port:COM5")
    rows[0]["key"] = "GW"
    devices = device_list.build_devices(rows, infos={"GW": {"hwid": "GW", "firmware": "0.4.50"}})
    w.show_devices(devices)
    assert list(w.settings_dialogs) == ["GW"] and w.settings_dialogs["GW"].key == "GW"
    dlg = w.settings_dialogs["GW"]
    dlg.send_shell("norlog usb mode auto")
    assert w.device.commands[-1] == ("send", {"text": "norlog usb mode auto", "port": "COM5"})
    dlg.close()
    # selection and "Read info (selected)": only reachable devices
    w.devices_table.topLevelItem(0).setSelected(True)
    w.devices_table.topLevelItem(1).setSelected(True)
    w.read_info_selected()
    assert w.device.commands[-1] == ("read_device_info", {"targets": ["GW"]})
    # console to the chosen port
    w.console_input.setText("ot state")
    w.send_console()
    assert w.device.commands[-1] == ("send", {"text": "ot state", "port": "COM5"})
