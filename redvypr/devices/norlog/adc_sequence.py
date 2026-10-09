"""
Measurement sequence of a norlog ADC (firmware >= 0.4.15, src/adc_seq.h).

The configuration is one line of text, the same for the shell, CoAP and the
configuration packets:

    on=1,sps=20,filter=sinc3,interval=10000;<step>;<step>;...
    <step> = name,p,n[,gain[,ref[,idac_ua[,i1[,i2[,delay_ms]]]]]]

parse() and AdcSequence.to_text() follow the firmware (same checks, same
canonical text), so a sequence can be checked before it is sent.
"""

import dataclasses
import re

MAX_STEPS = 16
NAME_MAX = 11
TEXT_MAX = 440

SENSORS = ["adc_brd", "adc_hfm"]
SENSOR_INFO = {
    "adc_brd": "ADS124S08 on the board (U6), inputs at J15/J17",
    "adc_hfm": "ADS124S08 of the hfmeter module (J1)",
}

SPS = ["2.5", "5", "10", "16.6", "20", "45", "90", "175", "330", "600", "1000", "2000"]
FILTERS = ["sinc3", "ll"]
GAINS = ["off", "1", "2", "4", "8", "16", "32", "64", "128"]
REFS = ["INT", "REF1", "REF0"]
IDAC_UA = [0, 10, 50, 100, 250, 500, 750, 1000, 1500, 2000]
INPUTS = [str(i) for i in range(12)] + ["COM"]
INTERNAL = ["TEMP", "AVDD", "DVDD", "OFS"]
P_INPUTS = INPUTS + INTERNAL
IDAC_PINS = ["-"] + INPUTS


class SequenceError(ValueError):
    pass


@dataclasses.dataclass
class AdcStep:
    name: str
    p: str = "0"
    n: str = "COM"
    gain: str = "1"         # "off" (PGA bypassed) or 1..128
    ref: str = "INT"
    idac_ua: int = 0
    i1: str = "-"
    i2: str = "-"
    delay_ms: int = 0

    @property
    def internal(self):
        return self.p in INTERNAL

    def unit(self):
        if self.p == "TEMP":
            return "degC"
        if self.internal or self.ref == "INT":
            return "V"
        return "1"      # U_in / U_ref

    def to_text(self):
        if self.internal:
            return f"{self.name},{self.p},-"
        fields = [self.name, self.p, self.n]
        last = 0
        if self.gain != "1":
            last = 1
        if self.ref != "INT":
            last = 2
        if self.idac_ua:
            last = 5
        if self.delay_ms:
            last = 6
        # up to the last field that differs from its default; idac_ua, i1 and i2 belong together
        extra = [self.gain, self.ref, str(self.idac_ua), self.i1, self.i2, str(self.delay_ms)]
        return ",".join(fields + extra[:last])


@dataclasses.dataclass
class AdcSequence:
    on: bool = False
    sps: str = "20"
    filter: str = "sinc3"
    interval_ms: int = 10000
    steps: list = dataclasses.field(default_factory=list)

    def to_text(self):
        head = f"on={int(self.on)},sps={self.sps},filter={self.filter},interval={self.interval_ms}"
        return ";".join([head] + [s.to_text() for s in self.steps])

    def conv_ms(self):
        periods = 1.0 if self.filter == "ll" else 3.0
        return int(periods * 1000.0 / float(self.sps) * 1.25) + 3

    def duration_ms(self):
        """Duration of one run as estimated by the firmware."""
        return sum(s.delay_ms + self.conv_ms() + 2 for s in self.steps)

    def validate(self):
        """Raise SequenceError like the firmware would; returns the canonical text."""
        return parse(self.to_text()).to_text()


def _pin(text, internal_ok=False, none_ok=False):
    t = text.strip()
    u = t.upper()
    if u in ("COM", "AINCOM"):
        return "COM"
    if none_ok and t in ("-", ""):
        return "-"
    if internal_ok and u in INTERNAL:
        return u
    if u.startswith("AIN"):
        t = t[3:]
    if not t.isdigit() or not 0 <= int(t) <= 11:
        raise ValueError(text)
    return str(int(t))


def _parse_step(seg, idx):
    f = seg.split(",", 8)
    if len(f) < 2:
        raise SequenceError(f"step {idx + 1}: name,p,n[,gain,ref,idac_ua,i1,i2,delay_ms]")
    name = f[0]
    if not 1 <= len(name) <= NAME_MAX:
        raise SequenceError(f"step {idx + 1}: name 1-{NAME_MAX} characters")
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise SequenceError(f"step {idx + 1}: name only a-z A-Z 0-9 _")
    st = AdcStep(name=name)
    try:
        st.p = _pin(f[1], internal_ok=True)
    except ValueError:
        raise SequenceError(f"{name}: p = 0..11, COM, TEMP, AVDD, DVDD or OFS") from None
    if st.internal:
        st.n = "-"
        return st
    try:
        if len(f) < 3:
            raise ValueError
        st.n = _pin(f[2])
    except ValueError:
        raise SequenceError(f"{name}: n = 0..11 or COM") from None
    if st.p == st.n:
        raise SequenceError(f"{name}: p and n are the same")
    if len(f) > 3 and f[3]:
        g = f[3]
        if g in ("off", "0"):
            st.gain = "off"
        elif g.isdigit() and int(g) in (1, 2, 4, 8, 16, 32, 64, 128):
            st.gain = str(int(g))
        else:
            raise SequenceError(f"{name}: gain = off, 1, 2, 4, ... 128")
    if len(f) > 4 and f[4]:
        r = f[4].upper()
        if r not in REFS:
            raise SequenceError(f"{name}: ref = INT, REF0 or REF1")
        st.ref = r
    if len(f) > 5 and f[5]:
        try:
            ua = int(f[5])
        except ValueError:
            ua = -1
        if ua not in IDAC_UA:
            raise SequenceError(f"{name}: idac_ua = " + " ".join(str(v) for v in IDAC_UA))
        st.idac_ua = ua
    try:
        if len(f) > 6:
            st.i1 = _pin(f[6], none_ok=True)
    except ValueError:
        raise SequenceError(f"{name}: i1 = 0..11, COM or -") from None
    try:
        if len(f) > 7:
            st.i2 = _pin(f[7], none_ok=True)
    except ValueError:
        raise SequenceError(f"{name}: i2 = 0..11, COM or -") from None
    if st.idac_ua and st.i1 == "-" and st.i2 == "-":
        raise SequenceError(f"{name}: IDAC current without output (i1/i2)")
    if not st.idac_ua:
        st.i1 = st.i2 = "-"
    if len(f) > 8 and f[8]:
        try:
            d = int(f[8])
        except ValueError:
            d = -1
        if not 0 <= d <= 2000:
            raise SequenceError(f"{name}: delay_ms = 0..2000")
        st.delay_ms = d
    return st


def parse(text, base=None):
    """
    Parse a configuration text. Global values that are missing are taken from base
    (like the firmware keeps its current values), otherwise the defaults.
    """
    seq = dataclasses.replace(base, steps=[]) if base is not None else AdcSequence()
    segs = [s for s in (text or "").strip().split(";") if s]
    if not segs:
        raise SequenceError("empty")
    for kv in segs[0].split(","):
        if not kv:
            continue
        if "=" not in kv:
            raise SequenceError(f"'{kv}': expected name=value")
        k, v = kv.split("=", 1)
        if k == "on":
            if v not in ("0", "1"):
                raise SequenceError("on: 0 or 1")
            seq.on = v == "1"
        elif k == "sps":
            try:
                val = float(v)
            except ValueError:
                val = -1
            match = [s for s in SPS if abs(val - float(s)) <= 0.05 * float(s)]
            if not match:
                raise SequenceError("sps: " + " ".join(SPS))
            seq.sps = match[-1]
        elif k == "filter":
            if v not in FILTERS:
                raise SequenceError("filter: sinc3 or ll")
            seq.filter = v
        elif k == "interval":
            try:
                ms = int(v)
            except ValueError:
                ms = -1
            if not 100 <= ms <= 86400000:
                raise SequenceError("interval: 100..86400000 ms")
            seq.interval_ms = ms
        else:
            raise SequenceError(f"unknown: {k}")
    for i, seg in enumerate(segs[1:]):
        if i >= MAX_STEPS:
            raise SequenceError(f"at most {MAX_STEPS} steps")
        st = _parse_step(seg, i)
        if any(s.name == st.name for s in seq.steps):
            raise SequenceError(f"name twice: {st.name}")
        seq.steps.append(st)
    if len(seq.to_text()) > TEXT_MAX:
        raise SequenceError(f"configuration too long (at most {TEXT_MAX} characters), use shorter names")
    return seq
