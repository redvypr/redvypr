"""
Setup profiles of the norlog ADC sequence (firmware >= 0.4.51).

A profile describes a known hardware setup at an ADC of the norlog (e.g. a breakout board with
sensors): the sequence that measures it and the kind of calibration of each channel. The
device stores the name of the profile with its sequence (setup=<name>) and reports it in
extinfo ("setup": {"adc_brd": "hf_ntc_v01"}), so redvypr recognises the setup by itself.
Design: firmware repository, doc/design_aufbau_profile.md.
"""

import dataclasses

from . import adc_sequence


@dataclasses.dataclass(frozen=True)
class ChannelCal:
    """Calibration a channel of a profile needs: kind 'poly' (unit) or 'ntc' (scale = R_ref)."""
    kind: str = "poly"
    unit: str = ""
    scale: float = 1.0
    hint: str = ""


@dataclasses.dataclass(frozen=True)
class Setup:
    name: str
    title: str
    description: str
    sensor: str
    text: str                                   # sequence without setup=, the name is added
    channels: dict = dataclasses.field(default_factory=dict)    # channel -> ChannelCal

    def sequence(self):
        """The sequence of the profile (with setup=<name>)."""
        seq = adc_sequence.parse(self.text)
        seq.setup = self.name
        return seq


SETUPS = {}


def _add(setup):
    setup.sequence()        # the text must be valid
    SETUPS[setup.name] = setup


_add(Setup(
    name="hf_ntc_v01",
    title="Breakout v01: 2 heat flux sensors + 2 NTC",
    description=("norlog_v02_breakout_v01 at J17 of the main board v02 (JP1 closed). Terminal block J2: "
                 "1/2 HF0+/-, 3/4 NTC0+/-, 5/6 HF1+/-, 7/8 NTC1+/-. Thermopiles differential with gain 128 "
                 "and VBIAS at the negative input (sensor must be floating), NTCs ratiometric with 100 uA "
                 "against R_ref = 10 kOhm (REF1 = AIN6/AIN7)."),
    sensor="adc_brd",
    text=("on=1,sps=10,filter=sinc3,interval=10000;hf0,0,1,128,INT,0,-,-,10,1;hf1,2,3,128,INT,0,-,-,10,3;"
          "ntc0,4,6,1,REF1,100,4,-,20;ntc1,5,6,1,REF1,100,5,-,20"),
    channels={
        "hf0": ChannelCal("poly", "W/m2", hint="linear: c1 = 1 / sensitivity [W/m2 per V]"),
        "hf1": ChannelCal("poly", "W/m2", hint="linear: c1 = 1 / sensitivity [W/m2 per V]"),
        "ntc0": ChannelCal("ntc", "degC", scale=10000.0, hint="NTC, scale = R_ref = 10000"),
        "ntc1": ChannelCal("ntc", "degC", scale=10000.0, hint="NTC, scale = R_ref = 10000"),
    },
))


def get(name):
    return SETUPS.get(name or "")


def for_sensor(sensor):
    return [s for s in SETUPS.values() if s.sensor == sensor]


def differences(seq, setup):
    """
    What differs between a sequence and its profile: list of short texts, empty if it matches.
    on/off and the interval are free; the steps, data rate and filter belong to the profile.
    """
    ref = setup.sequence()
    diff = []
    if seq.sps != ref.sps:
        diff.append(f"data rate {seq.sps} instead of {ref.sps}")
    if seq.filter != ref.filter:
        diff.append(f"filter {seq.filter} instead of {ref.filter}")
    steps = {s.name: s for s in seq.steps}
    for st in ref.steps:
        if st.name not in steps:
            diff.append(f"{st.name} missing")
        elif steps[st.name].to_text() != st.to_text():
            diff.append(f"{st.name} changed")
    diff += [f"{name} added" for name in steps if name not in {s.name for s in ref.steps}]
    return diff


def missing_calibrations(setup, cals):
    """Channels of the profile without a matching calibration on the device (cals: {channel: PolyCalibration})."""
    missing = []
    for channel, need in setup.channels.items():
        cal = (cals or {}).get(channel)
        if cal is None:
            missing.append(f"{channel} without calibration")
        elif cal.kind != need.kind:
            missing.append(f"{channel}: calibration {cal.kind} instead of {need.kind}")
    return missing


def status_text(seq, setup_name, cals=None):
    """
    (text, ok) for the setup of a sequence read from the device: 'hf_ntc_v01', 'hf_ntc_v01 (changed: ...)',
    'xyz (unknown profile)' or '' without setup. cals=None: calibrations not checked.
    """
    if not setup_name:
        return "", True
    setup = get(setup_name)
    if setup is None:
        return f"{setup_name} (unknown profile)", False
    problems = differences(seq, setup)
    text = setup_name + (f" (changed: {', '.join(problems)})" if problems else "")
    if cals is not None:
        missing = missing_calibrations(setup, cals)
        if missing:
            text += "; " + ", ".join(missing)
            problems = problems + missing
    return text, not problems


def device_setups_text(setups):
    """Text of extinfo 'setup' ({sensor: name}) for the device list: 'hf_ntc_v01' or 'adc_brd: a, adc_hfm: b'."""
    setups = {k: v for k, v in (setups or {}).items() if v} if isinstance(setups, dict) else {}
    if not setups:
        return "", ""
    if len(setups) == 1:
        text = next(iter(setups.values()))
    else:
        text = ", ".join(f"{k}: {v}" for k, v in sorted(setups.items()))
    tip = "\n".join(f"{k}: {v} - {get(v).title if get(v) else 'unknown profile'}" for k, v in sorted(setups.items()))
    return text, tip
