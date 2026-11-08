"""
Setup profiles of the norlog ADC sequence (firmware >= 0.4.51).

A profile describes a known hardware setup at an ADC of the norlog (e.g. a breakout board with
sensors): the sequence that measures it and the kind of calibration of each channel. The
device stores the name of the profile with its sequence (setup=<name>) and reports it in
extinfo ("setup": {"adc_brd": "hf_ntc_v01"}), so redvypr recognises the setup by itself.
Design: firmware repository, doc/design_aufbau_profile.md.

Profiles are also items of type 'setup' of the redvypr metadata (redvypr.items.SetupItem,
design note doc/source/design_items.rst): update_from_items() takes them over, they win over the
built-in profiles of the same name. New profiles can so be made without a change of the code.
"""

import dataclasses
import logging

from . import adc_sequence

logger = logging.getLogger('redvypr.device.norlog.adc_setups')


@dataclasses.dataclass(frozen=True)
class ChannelCal:
    """Calibration a channel of a profile needs: kind 'poly' (unit) or 'ntc' (scale = R_ref)."""
    kind: str = "poly"
    unit: str = ""
    scale: float = 1.0
    hint: str = ""
    # ntc: R_ref from an item of the channel (redvypr.items), (role, field), e.g. ('board', 'R1')
    scale_ref: tuple = ()
    # slot of the item measured by the channel, e.g. a terminal 'J2.3-4' (redvypr.items)
    slot: str = ""

    def to_dict(self):
        d = {'cal': self.kind}
        if self.unit:
            d['unit'] = self.unit
        if self.kind == 'ntc' or self.scale != 1.0:
            d['scale'] = self.scale
        if self.scale_ref:
            d['scale_ref'] = list(self.scale_ref)
        if self.slot:
            d['slot'] = self.slot
        if self.hint:
            d['hint'] = self.hint
        return d

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        ref = d.get('scale_ref') or ()
        return cls(kind=str(d.get('cal', d.get('kind', 'poly'))), unit=str(d.get('unit', '')),
                   scale=float(d.get('scale', 1.0)), hint=str(d.get('hint', '')),
                   scale_ref=tuple(ref) if len(ref) == 2 else (), slot=str(d.get('slot', '')))


@dataclasses.dataclass(frozen=True)
class Setup:
    name: str
    title: str
    description: str
    sensor: str
    text: str                                   # sequence without setup=, the name is added
    channels: dict = dataclasses.field(default_factory=dict)    # channel -> ChannelCal
    board_type: str = ""                        # item type of the board (redvypr.items)
    builtin: bool = True                        # False: from an item of the metadata

    def sequence(self):
        """The sequence of the profile (with setup=<name>)."""
        seq = adc_sequence.parse(self.text)
        seq.setup = self.name
        return seq


SETUPS = {}              # built-in profiles
ITEM_SETUPS = {}        # profiles from items of type 'setup' (update_from_items())


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
    board_type="breakout_board_v01",
    text=("on=1,sps=5,filter=sinc3,interval=10000;hf0,0,1,128,INT,0,-,-,10,1;hf1,2,3,128,INT,0,-,-,10,3;"
          "ntc0,4,6,1,REF1,100,4,-,20;ntc1,5,6,1,REF1,100,5,-,20"),
    channels={
        "hf0": ChannelCal("poly", "W/m2", hint="linear: c1 = 1 / sensitivity [W/m2 per V]", slot="J2.1-2"),
        "hf1": ChannelCal("poly", "W/m2", hint="linear: c1 = 1 / sensitivity [W/m2 per V]", slot="J2.5-6"),
        "ntc0": ChannelCal("ntc", "degC", scale=10000.0, scale_ref=("board", "R1"), slot="J2.3-4",
                           hint="NTC, scale = R_ref = R1 of the board (nominal 10000)"),
        "ntc1": ChannelCal("ntc", "degC", scale=10000.0, scale_ref=("board", "R1"), slot="J2.7-8",
                           hint="NTC, scale = R_ref = R1 of the board (nominal 10000)"),
    },
))


def get(name):
    """A profile by name: from the items, else built-in."""
    name = name or ""
    return ITEM_SETUPS.get(name) or SETUPS.get(name)


def all_setups():
    merged = dict(SETUPS)
    merged.update(ITEM_SETUPS)
    return merged


def for_sensor(sensor):
    return [s for s in all_setups().values() if s.sensor == sensor]


# --- profiles as items (redvypr.items.SetupItem) ---------------------------------------------

def from_item(item):
    """Setup of an item of type 'setup' (fields sensor and sequence needed), None if it is no ADC profile."""
    sensor = getattr(item, 'sensor', None)
    text = getattr(item, 'sequence', None)
    if not sensor or not text:
        return None
    seq = adc_sequence.parse(text)          # raises SequenceError for an invalid text
    seq.setup = ''
    channels = {ch: ChannelCal.from_dict(d) for ch, d in (item.channels or {}).items() if isinstance(d, dict)}
    return Setup(name=item.id, title=item.title or '', description=item.description or '', sensor=str(sensor),
                 text=seq.to_text(), channels=channels, board_type=item.board_type or '', builtin=False)


def to_item(setup):
    """Item of type 'setup' of a profile (to store it in the metadata / an item library)."""
    import redvypr.items
    seq = adc_sequence.parse(setup.text)
    seq.setup = ''
    return redvypr.items.SetupItem(id=setup.name, title=setup.title or None,
                                   description=setup.description or None,
                                   board_type=setup.board_type or None,
                                   channels={ch: c.to_dict() for ch, c in setup.channels.items()},
                                   sensor=setup.sensor, sequence=seq.to_text())


def update_from_items(items):
    """Take the profiles of the items of type 'setup' (replaces the previous ones). Returns their names."""
    found = {}
    for item in items or []:
        try:
            setup = from_item(item)
        except Exception as exc:
            logger.warning(f'setup item {getattr(item, "id", "?")}: {exc}')
            continue
        if setup is not None:
            found[setup.name] = setup
    ITEM_SETUPS.clear()
    ITEM_SETUPS.update(found)
    return sorted(found)


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


def _register_builtin_items():
    """The built-in profiles as built-in items 'setup/<name>' (redvypr.items): found by the items of a channel."""
    import redvypr.items
    for setup in SETUPS.values():
        redvypr.items.register_builtin_item(to_item(setup))


_register_builtin_items()
