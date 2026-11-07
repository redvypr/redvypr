"""
Setup profiles of the norlog ADC sequence (firmware >= 0.4.51): field setup= in the
configuration text, profiles in adc_setups, ADC tab and the column 'Setup' of the device list.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from redvypr.devices.norlog import adc_sequence as aseq
from redvypr.devices.norlog import adc_setups
from redvypr.devices.norlog import device_list
from redvypr.devices.norlog import norlog_gateway as ng
from redvypr.devices.norlog import poly_calibration
from redvypr.devices.norlog import ports

PROFILE = ("on=1,sps=10,filter=sinc3,interval=10000,setup=hf_ntc_v01;hf0,0,1,128,INT,0,-,-,10,1;"
           "hf1,2,3,128,INT,0,-,-,10,3;ntc0,4,6,1,REF1,100,4,-,20;ntc1,5,6,1,REF1,100,5,-,20")


def test_setup_field_in_text():
    seq = aseq.parse(PROFILE)
    assert seq.setup == "hf_ntc_v01" and seq.to_text() == PROFILE
    # missing: kept from base (like the firmware); "-" clears it
    assert aseq.parse("interval=5000;a,0,COM", base=seq).setup == "hf_ntc_v01"
    assert aseq.parse("setup=-;a,0,COM", base=seq).setup == ""
    assert "setup" not in aseq.parse("on=0;a,0,COM").to_text()


@pytest.mark.parametrize("text, msg", [("setup=a-b;x,0,COM", "only a-z"),
                                       ("setup=" + "x" * 24 + ";x,0,COM", "1-23")])
def test_setup_errors(text, msg):
    with pytest.raises(aseq.SequenceError, match=msg):
        aseq.parse(text)


def test_profile_hf_ntc_v01():
    setup = adc_setups.get("hf_ntc_v01")
    assert setup.sequence().to_text() == PROFILE and setup.sensor == "adc_brd"
    assert len(PROFILE) <= aseq.TEXT_MAX
    assert [s.name for s in adc_setups.for_sensor("adc_brd")] == ["hf_ntc_v01"]
    seq = setup.sequence()
    assert adc_setups.differences(seq, setup) == []
    # on/off and interval are free, steps and data rate belong to the profile
    seq.on, seq.interval_ms = False, 60000
    assert adc_setups.differences(seq, setup) == []
    seq.sps = "20"
    seq.steps[0].gain = "64"
    seq.steps.pop()
    assert adc_setups.differences(seq, setup) == ["data rate 20 instead of 10", "hf0 changed", "ntc1 missing"]


def test_status_and_calibrations():
    seq = aseq.parse(PROFILE)
    poly = poly_calibration.PolyCalibration(coeffs=[0, 16000], unit="W/m2")
    ntc = poly_calibration.PolyCalibration(coeffs=[1e-3, 2e-4], unit="degC", kind="ntc", scale=10000.0)
    cals = {"hf0": poly, "hf1": poly, "ntc0": ntc, "ntc1": poly}
    text, ok = adc_setups.status_text(seq, seq.setup, cals)
    assert not ok and text == "hf_ntc_v01; ntc1: calibration poly instead of ntc"
    cals["ntc1"] = ntc
    assert adc_setups.status_text(seq, seq.setup, cals) == ("hf_ntc_v01", True)
    assert adc_setups.status_text(seq, seq.setup) == ("hf_ntc_v01", True)     # calibrations not read
    assert adc_setups.status_text(seq, "") == ("", True)
    assert adc_setups.status_text(seq, "other") == ("other (unknown profile)", False)


def test_device_setups_text():
    assert adc_setups.device_setups_text(None) == ("", "")
    text, tip = adc_setups.device_setups_text({"adc_brd": "hf_ntc_v01"})
    assert text == "hf_ntc_v01" and "heat flux" in tip
    text, _tip = adc_setups.device_setups_text({"adc_hfm": "x", "adc_brd": "hf_ntc_v01"})
    assert text == "adc_brd: hf_ntc_v01, adc_hfm: x"


# --- GUI -------------------------------------------------------------------------------

class FakeDevice(ng.QtCore.QObject):
    thread_started = ng.QtCore.pyqtSignal(dict)
    thread_stopped = ng.QtCore.pyqtSignal(dict)
    new_data = ng.QtCore.pyqtSignal(list)
    mp = "thread"
    subscribes = False
    statusqueue = None
    redvypr = None

    def __init__(self, cfg):
        super().__init__()
        self.custom_config = cfg
        self.running = True
        self.commands = []

    def get_thread_status(self):
        return {"thread_running": self.running}

    def thread_command(self, command, data=None):
        self.commands.append((command, data))


@pytest.fixture
def widget(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(ports, "scan", lambda: [{"name": "COM5", "description": "nRF52840", "usb_sn": "S5",
                                                  "vid": 0x1915, "pid": 1}])
    w = ng.RedvyprDeviceWidget(device=FakeDevice(ng.DeviceCustomConfig(comport="COM5")))
    yield w
    w.close()
    assert app is not None


def show_device(w, setup=None):
    rows = [{"name": "COM5", "state": device_list.PORT_OPEN, "key": "GW", "active": True, "role": "gateway",
             "status": {"state": "leader", "extpanid": "net", "rloc16": "0x1000", "extaddr": "1111"}}]
    info = {"hwid": "GW", "firmware": "0.4.51"}
    if setup:
        info["setup"] = setup
    devices = device_list.build_devices(rows, infos={"GW": info})
    w.show_devices(devices)
    return devices


def test_device_list_column(widget):
    show_device(widget, {"adc_brd": "hf_ntc_v01"})
    col = widget.DEVICE_COLUMNS.index("Setup")
    item = widget.devices_table.topLevelItem(0)
    assert item.text(col) == "hf_ntc_v01" and "heat flux" in item.toolTip(col)


def adc_answer(dlg, cfg, setup_key=True, cals=None):
    adc = {"sensor": "adc_brd", "present": True, "on": True, "cfg_id": 3, "cfg": cfg}
    if setup_key:
        adc["setup"] = aseq.parse(cfg).setup
    data = {"ok": True, "sensor": "adc_brd", "op": "get", "adc": adc}
    if cals is not None:
        data["cals"] = cals
    dlg.on_adc_message(data)


def test_adc_tab_profile(widget):
    w = widget
    show_device(w)
    w.open_settings("GW")
    dlg = w.settings_dialogs["GW"]
    # device with the profile, no calibrations yet
    adc_answer(dlg, PROFILE, cals={})
    assert dlg.adc_setup.currentData() == "hf_ntc_v01"
    assert dlg.adc_setup_state.text().startswith("device: hf_ntc_v01; hf0 without calibration")
    # without profile: choose and load it, then write
    adc_answer(dlg, "on=0,sps=20,filter=sinc3,interval=10000;temp,TEMP,-", cals={})
    assert dlg.adc_setup.currentData() == "" and dlg.adc_setup_state.text() == "device: no setup profile"
    dlg.adc_setup.setCurrentIndex(dlg.adc_setup.findData("hf_ntc_v01"))
    dlg.adc_load_setup()
    assert dlg.adc_text.text() == PROFILE and "not yet written" in dlg.adc_status.text()
    dlg.adc_write()
    assert w.device.commands[-1] == ("adc_set", {"target": "GW", "sensor": "adc_brd", "text": PROFILE,
                                                 "channel": ""})
    # changed step: the device reports the profile as changed
    adc_answer(dlg, PROFILE.replace("hf0,0,1,128", "hf0,0,1,64"), cals={})
    assert "hf_ntc_v01 (changed: hf0 changed)" in dlg.adc_setup_state.text()
    # an unknown profile name of the device stays selectable
    adc_answer(dlg, "on=0,setup=lab_x;a,0,COM")
    assert dlg.adc_setup.currentText() == "lab_x (unknown)"
    dlg.close()


def test_adc_tab_choosing_loads_profile(widget):
    w = widget
    show_device(w)
    w.open_settings("GW")
    dlg = w.settings_dialogs["GW"]
    adc_answer(dlg, "on=0,sps=20,filter=sinc3,interval=10000", cals={})
    # the user chooses the profile: it is loaded at once (not only the name)
    i = dlg.adc_setup.findData("hf_ntc_v01")
    dlg.adc_setup.setCurrentIndex(i)
    dlg.adc_setup.activated.emit(i)
    assert dlg.adc_text.text() == PROFILE
    # only the name without steps is not written
    dlg.adc_table.setRowCount(0)
    dlg.adc_on.setChecked(False)
    n = len(w.device.commands)
    dlg.adc_write()
    assert len(w.device.commands) == n and "Load profile" in dlg.adc_status.text()
    dlg.close()


def test_adc_tab_old_firmware(widget):
    w = widget
    show_device(w)
    w.open_settings("GW")
    dlg = w.settings_dialogs["GW"]
    adc_answer(dlg, "on=0,sps=20,filter=sinc3,interval=10000;temp,TEMP,-", setup_key=False)
    assert "0.4.51" in dlg.adc_setup_state.text()
    n = len(w.device.commands)
    dlg.adc_setup.setCurrentIndex(dlg.adc_setup.findData("hf_ntc_v01"))
    dlg.adc_load_setup()
    dlg.adc_write()
    assert len(w.device.commands) == n and "0.4.51" in dlg.adc_status.text()
    dlg.close()


def test_calibration_dialog_preset(widget):
    preset = adc_setups.get("hf_ntc_v01").channels["ntc0"]
    dlg = ng.AdcCalibrationDialog(widget, "adc_brd.ntc0", "1", None, 0.5, preset=preset)
    assert dlg.current_kind() == "ntc" and dlg.scale.text() == "10000" and dlg.unit.text() == "degC"
    dlg.close()
