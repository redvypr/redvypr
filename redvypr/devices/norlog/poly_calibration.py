"""
Calibration of a channel of the norlog ADC measurement sequence, stored and
applied on the device (src/calibration.h) under "<sensor>.<channel>" (e.g.
"adc_brd.hf0"). x is the value of the step (V, U_in/U_ref or degC).

- kind 'poly' (firmware >= 0.4.16):  y = c0 + c1*x + ... + c5*x^5
- kind 'ntc'  (firmware >= 0.4.17):  R = x * scale [Ohm],
                                     T = 1 / (c0 + c1*ln(R) + ... + c5*ln(R)^5) - toff
  This is redvypr's CalibrationNTC (Hoge / Steinhart-Hart type); with a ratiometric
  measurement x = R/R_ref, so scale = R_ref.

Text for the device:  [ntc:<scale>,<toff>,]c0,c1[,...];unit[;id[;date]]
The coefficients are ascending here; redvypr's calibration models store them
descending (numpy.polyval order), from_redvypr()/to_redvypr() convert.
"""

import dataclasses
import math
import re
import time

ORDER_MAX = 5
UNIT_MAX = 11
ID_MAX = 23
NAME_MAX = 23
KINDS = ("poly", "ntc")


class CalibrationError(ValueError):
    pass


def cal_name(sensor, channel):
    return f"{sensor}.{channel}"


@dataclasses.dataclass
class PolyCalibration:
    coeffs: list                    # c0, c1, ... (ascending powers of x or ln(R))
    unit: str
    id: str = ""
    date: int = 0                   # unix time [s]
    name: str = ""                  # "<sensor>.<channel>"
    kind: str = "poly"              # 'poly' or 'ntc'
    scale: float = 1.0              # ntc: R = x * scale [Ohm]
    toff: float = 273.15            # ntc: T = 1/(...) - toff

    def __post_init__(self):
        self.coeffs = [float(c) for c in self.coeffs]

    def check(self):
        if self.kind not in KINDS:
            raise CalibrationError(f"kind: {' or '.join(KINDS)}")
        if not 2 <= len(self.coeffs) <= ORDER_MAX + 1:
            raise CalibrationError(f"2 to {ORDER_MAX + 1} coefficients (c0, c1 ...)")
        if not all(math.isfinite(c) for c in self.coeffs):
            raise CalibrationError("coefficients must be finite")
        if self.kind == "ntc" and not (math.isfinite(self.scale) and self.scale > 0 and math.isfinite(self.toff)):
            raise CalibrationError("ntc: scale (R_ref in Ohm) > 0 and a finite toff")
        if not 1 <= len(self.unit) <= UNIT_MAX or re.search(r'[\s,;"]', self.unit):
            raise CalibrationError(f"unit: 1-{UNIT_MAX} characters without spaces , ; \"")
        if len(self.id) > ID_MAX or re.search(r'[;"]', self.id) or re.search(r"\s", self.id):
            raise CalibrationError(f"id: at most {ID_MAX} characters without spaces ; \"")

    def to_text(self):
        """Text for 'norlog cal set <name> <text>' / CoAP 'cal?n=<name>'."""
        self.check()
        coeffs = ",".join(f"{c:.12g}" for c in self.coeffs)
        if self.kind == "ntc":
            coeffs = f"ntc:{self.scale:.12g},{self.toff:.12g}," + coeffs
        text = f"{coeffs};{self.unit}"
        if self.id or self.date:
            text += f";{self.id}"
        if self.date:
            text += f";{int(self.date)}"
        return text

    @classmethod
    def from_device(cls, d):
        """From the JSON of 'norlog cal get <name>' / CoAP 'cal?n=<name>'; None for None."""
        if not d:
            return None
        return cls(coeffs=d.get("c", []), unit=d.get("unit", ""), id=d.get("id", ""), date=int(d.get("date", 0)),
                   name=d.get("name", ""), kind=d.get("kind", "poly"), scale=float(d.get("scale", 1.0)),
                   toff=float(d.get("toff", 273.15)))

    def apply(self, x):
        t = x
        if self.kind == "ntc":
            r = x * self.scale
            if not r > 0:
                return float("nan")
            t = math.log(r)
        y = 0.0
        for c in reversed(self.coeffs):
            y = y * t + c
        if self.kind == "ntc":
            return 1.0 / y - self.toff if y != 0 else float("nan")
        return y

    def summary(self, var="x"):
        if self.kind == "ntc":
            var = f"ln({var}·{self.scale:.6g})" if self.scale != 1 else f"ln({var})"
        terms = []
        for i, c in enumerate(self.coeffs):
            if c == 0 and i > 0:
                continue
            term = f"{c:.6g}"
            if i == 1:
                term += f"·{var}"
            elif i > 1:
                term += f"·{var}^{i}"
            terms.append(term)
        poly = " + ".join(terms).replace("+ -", "- ")
        if self.kind == "ntc":
            return f"{self.unit} = 1 / ({poly}) - {self.toff:g}"
        return f"{self.unit} = {poly}"


def linear_from_sensitivity(sensitivity, unit, id="", offset=0.0):
    """
    Linear calibration of a sensor with a given sensitivity (x per unit of y), e.g. a
    heat flux sensor with 62.5e-6 V per W/m2: y = (x - offset) / sensitivity.
    """
    if sensitivity == 0:
        raise CalibrationError("sensitivity must not be 0")
    return PolyCalibration(coeffs=[-offset / sensitivity + 0.0, 1.0 / sensitivity], unit=unit, id=id,
                           date=int(time.time()))


def _points(points, order):
    import numpy as np
    order = int(order)
    if not 1 <= order <= ORDER_MAX:
        raise CalibrationError(f"order 1..{ORDER_MAX}")
    pts = np.array([(float(x), float(y)) for x, y in points], dtype=float)
    if len(pts) < order + 1:
        raise CalibrationError(f"order {order} needs at least {order + 1} points")
    if len(np.unique(pts[:, 0])) < order + 1:
        raise CalibrationError(f"order {order} needs at least {order + 1} different x values")
    return pts, order


def _rms(cal, pts):
    import numpy as np
    resid = pts[:, 1] - np.array([cal.apply(x) for x in pts[:, 0]])
    return float(np.sqrt(np.mean(resid ** 2)))


def fit(points, order, unit, id=""):
    """
    Least squares fit of y(x) to reference points [(x, y), ...] (x: value of the step,
    y: reference). Returns (PolyCalibration, rms residual).
    """
    import numpy as np
    pts, order = _points(points, order)
    coeffs = np.polynomial.polynomial.polyfit(pts[:, 0], pts[:, 1], order)
    cal = PolyCalibration(coeffs=list(coeffs), unit=unit, id=id, date=int(time.time()))
    return cal, _rms(cal, pts)


def fit_ntc(points, order=3, scale=1.0, toff=273.15, unit="degC", id=""):
    """
    NTC fit like redvypr's CalibrationNTC.calc_coeffs(): 1/(T + toff) as polynomial of ln(x * scale).
    points [(x, T), ...]: x = value of the step (R/R_ref with scale = R_ref, or R in Ohm with scale = 1),
    T = reference temperature. Returns (PolyCalibration, rms residual in the unit of T).
    """
    import numpy as np
    pts, order = _points(points, order)
    if scale <= 0 or (pts[:, 0] <= 0).any():
        raise CalibrationError("ntc: x and scale must be > 0")
    coeffs = np.polynomial.polynomial.polyfit(np.log(pts[:, 0] * scale), 1.0 / (pts[:, 1] + toff), order)
    cal = PolyCalibration(coeffs=list(coeffs), unit=unit, id=id, date=int(time.time()), kind="ntc",
                          scale=float(scale), toff=float(toff))
    return cal, _rms(cal, pts)


# --- redvypr calibration models (devices/sensors/calibration/calibration_models.py) ---

def from_redvypr(cal, scale=None, unit=None, id=None):
    """
    norlog calibration from a redvypr calibration model:
    - CalibrationNTC: kind 'ntc'; its input is R in Ohm, so scale = R_ref (x = R/R_ref) or 1 if the
      channel already delivers Ohm
    - CalibrationPoly: polynomial (coefficients reversed)
    - CalibrationLinearFactor: y = coeff * x
    - CalibrationHeatFlow: y = coeff * x[mV] (coeff in W m-2 mV-1), x of the norlog in V
    scale: only for 'ntc' (default 1). unit/id: default from the model (unit, calibration_id or sn).
    """
    ctype = getattr(cal, "calibration_type", "")
    ident = id if id is not None else (getattr(cal, "calibration_id", "") or getattr(cal, "sn", "") or "")
    ident = re.sub(r'[\s;"]', "_", str(ident if ident != "NA" else ""))[:ID_MAX]
    model_unit = getattr(cal, "unit", "") or ""
    date = getattr(cal, "date", None)
    date = int(date.timestamp()) if date is not None and date.year > 1970 else int(time.time())
    if ctype == "ntc":
        coeffs = list(reversed([float(c) for c in cal.coeff]))
        return PolyCalibration(coeffs=coeffs, unit=unit or (model_unit if model_unit != "NA" else "degC"),
                               id=ident, date=date, kind="ntc", scale=float(scale or 1.0), toff=float(cal.Toff))
    if ctype == "polynom":
        coeffs = list(reversed([float(c) for c in cal.coeff]))
        if len(coeffs) == 1:
            coeffs.append(0.0)
    elif ctype == "linearfactor":
        coeffs = [0.0, float(cal.coeff)]
    elif ctype == "heatflow":
        coeffs = [0.0, float(cal.coeff) * 1000.0]      # W m-2 mV-1 -> W m-2 V-1
        model_unit = "W/m2" if model_unit in ("", "NA", "W m-2 mV-1") else model_unit
    else:
        raise CalibrationError(f"calibration type '{ctype}' can not be used on the norlog")
    if model_unit in ("", "NA"):
        model_unit = "?"
    return PolyCalibration(coeffs=coeffs, unit=unit or re.sub(r"[\s,;]", "", model_unit)[:UNIT_MAX] or "?",
                           id=ident, date=date)


def to_redvypr(cal, channel="", sn="NA"):
    """
    redvypr calibration model of a norlog calibration: CalibrationPoly or, for 'ntc',
    CalibrationNTC (input R in Ohm = x * scale, unit_input 'Ohm').
    """
    import datetime
    from redvypr.devices.sensors.calibration import calibration_models as cm
    date = datetime.datetime.fromtimestamp(cal.date or time.time(), tz=datetime.timezone.utc)
    coeff = list(reversed(cal.coeffs))
    common = dict(channel=channel or "@", sn=sn, unit=cal.unit, calibration_id=cal.id, date=date,
                  comment=f"norlog {cal.name}".strip())
    if cal.kind == "ntc":
        return cm.CalibrationNTC(coeff=coeff, Toff=cal.toff, poly_degree=len(coeff) - 1, unit_input="Ohm",
                                 **common)
    return cm.CalibrationPoly(coeff=coeff, poly_degree=len(coeff) - 1, **common)
