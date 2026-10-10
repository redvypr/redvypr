"""
Polynomial calibration of a channel of the norlog ADC measurement sequence
(firmware >= 0.4.16, src/calibration.h).

On the device a calibration is stored under "<sensor>.<channel>" (e.g.
"adc_brd.hf0") and applied to the value x of the step (V, U_in/U_ref or degC):

    y = c0 + c1*x + ... + c5*x^5

Text for the device: "c0,c1[,...,c5];unit[;id[;date]]".
"""

import dataclasses
import re
import time

ORDER_MAX = 5
UNIT_MAX = 11
ID_MAX = 23
NAME_MAX = 23


class CalibrationError(ValueError):
    pass


def cal_name(sensor, channel):
    return f"{sensor}.{channel}"


@dataclasses.dataclass
class PolyCalibration:
    coeffs: list                    # c0, c1, ... (ascending powers)
    unit: str
    id: str = ""
    date: int = 0                   # unix time [s]
    name: str = ""                  # "<sensor>.<channel>"

    def __post_init__(self):
        self.coeffs = [float(c) for c in self.coeffs]

    def check(self):
        if not 2 <= len(self.coeffs) <= ORDER_MAX + 1:
            raise CalibrationError(f"2 to {ORDER_MAX + 1} coefficients (c0, c1 ...)")
        if any(c != c or c in (float("inf"), float("-inf")) for c in self.coeffs):
            raise CalibrationError("coefficients must be finite")
        if not 1 <= len(self.unit) <= UNIT_MAX or re.search(r'[\s,;"]', self.unit):
            raise CalibrationError(f"unit: 1-{UNIT_MAX} characters without spaces , ; \"")
        if len(self.id) > ID_MAX or re.search(r'[;"]', self.id) or re.search(r"\s", self.id):
            raise CalibrationError(f"id: at most {ID_MAX} characters without spaces ; \"")

    def to_text(self):
        """Text for 'norlog cal set <name> <text>' / CoAP 'cal?n=<name>'."""
        self.check()
        coeffs = ",".join(f"{c:.12g}" for c in self.coeffs)
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
                   name=d.get("name", ""))

    def apply(self, x):
        y = 0.0
        for c in reversed(self.coeffs):
            y = y * x + c
        return y

    def summary(self, var="x"):
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
        return f"{self.unit} = " + " + ".join(terms).replace("+ -", "- ")


def linear_from_sensitivity(sensitivity, unit, id="", offset=0.0):
    """
    Linear calibration of a sensor with a given sensitivity (x per unit of y), e.g. a
    heat flux sensor with 62.5e-6 V per W/m2: y = (x - offset) / sensitivity.
    """
    if sensitivity == 0:
        raise CalibrationError("sensitivity must not be 0")
    return PolyCalibration(coeffs=[-offset / sensitivity + 0.0, 1.0 / sensitivity], unit=unit, id=id,
                           date=int(time.time()))


def fit(points, order, unit, id=""):
    """
    Least squares fit of y(x) to reference points [(x, y), ...] (x: value of the step,
    y: reference). Returns (PolyCalibration, rms residual).
    """
    import numpy as np
    order = int(order)
    if not 1 <= order <= ORDER_MAX:
        raise CalibrationError(f"order 1..{ORDER_MAX}")
    pts = np.array([(float(x), float(y)) for x, y in points], dtype=float)
    if len(pts) < order + 1:
        raise CalibrationError(f"order {order} needs at least {order + 1} points")
    if len(np.unique(pts[:, 0])) < order + 1:
        raise CalibrationError(f"order {order} needs at least {order + 1} different x values")
    coeffs = np.polynomial.polynomial.polyfit(pts[:, 0], pts[:, 1], order)
    cal = PolyCalibration(coeffs=list(coeffs), unit=unit, id=id, date=int(time.time()))
    resid = pts[:, 1] - np.array([cal.apply(x) for x in pts[:, 0]])
    return cal, float(np.sqrt(np.mean(resid ** 2)))
