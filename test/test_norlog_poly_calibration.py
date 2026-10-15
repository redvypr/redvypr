"""
Polynomial calibrations of ADC channels of the norlog (firmware >= 0.4.16):
redvypr.devices.norlog.poly_calibration, bias in adc_sequence, decoding of the calibrated values.
"""
import dataclasses
import struct

import numpy as np
import pytest

from redvypr.devices.norlog import adc_sequence as aseq
from redvypr.devices.norlog import norlog_cbor
from redvypr.devices.norlog import poly_calibration as pc


def test_text_and_apply():
    cal = pc.PolyCalibration(coeffs=[0.5, 16000.0, 0.0, 2.0], unit="W/m2", id="HFP01-123", date=1760000000)
    assert cal.to_text() == "0.5,16000,0,2;W/m2;HFP01-123;1760000000"
    assert cal.apply(2.0) == pytest.approx(0.5 + 32000.0 + 16.0)
    assert pc.PolyCalibration(coeffs=[0, 1], unit="V").to_text() == "0,1;V"
    assert pc.PolyCalibration(coeffs=[0, 1], unit="V", date=5).to_text() == "0,1;V;;5"
    assert "W/m2 = 0.5 + 16000·x + 2·x^3" == cal.summary()


def test_from_device():
    d = {"name": "adc_brd.hf0", "c": [0, 16000], "unit": "W/m2", "id": "", "date": 0}
    cal = pc.PolyCalibration.from_device(d)
    assert cal.name == "adc_brd.hf0" and cal.coeffs == [0.0, 16000.0] and cal.unit == "W/m2"
    assert pc.PolyCalibration.from_device(None) is None


@pytest.mark.parametrize("cal, msg", [
    (pc.PolyCalibration(coeffs=[1], unit="V"), "coefficients"),
    (pc.PolyCalibration(coeffs=[0] * 7, unit="V"), "coefficients"),
    (pc.PolyCalibration(coeffs=[0, float("nan")], unit="V"), "finite"),
    (pc.PolyCalibration(coeffs=[0, 1], unit=""), "unit"),
    (pc.PolyCalibration(coeffs=[0, 1], unit="W/m2;x"), "unit"),
    (pc.PolyCalibration(coeffs=[0, 1], unit="degreeCelsius"), "unit"),
    (pc.PolyCalibration(coeffs=[0, 1], unit="V", id="a b"), "id"),
])
def test_check(cal, msg):
    with pytest.raises(pc.CalibrationError, match=msg):
        cal.to_text()


def test_linear_from_sensitivity():
    # heat flux sensor 62.5 µV per W/m2
    cal = pc.linear_from_sensitivity(62.5e-6, "W/m2")
    assert cal.coeffs == pytest.approx([0.0, 16000.0])
    assert cal.apply(1.25e-3) == pytest.approx(20.0)
    with pytest.raises(pc.CalibrationError):
        pc.linear_from_sensitivity(0, "W/m2")


def test_fit():
    x = np.linspace(-0.02, 0.02, 7)
    y = 3.0 + 1000.0 * x + 2.0e4 * x ** 2
    cal, rms = pc.fit(list(zip(x, y)), 2, "Pa")
    assert cal.coeffs == pytest.approx([3.0, 1000.0, 2.0e4], rel=1e-6)
    assert rms < 1e-9
    with pytest.raises(pc.CalibrationError, match="at least 3"):
        pc.fit([(0, 0), (1, 1)], 2, "Pa")
    with pytest.raises(pc.CalibrationError, match="different"):
        pc.fit([(0, 0), (0, 1), (1, 1)], 2, "Pa")


def test_bias_in_sequence_text():
    seq = aseq.parse("on=1;hf0,2,3,128,INT,0,-,-,10,3;u,0,COM,off,INT,0,-,-,0,AIN5;t,TEMP")
    assert [s.bias for s in seq.steps] == ["3", "5", "-"]
    assert seq.to_text() == ("on=1,sps=20,filter=sinc3,interval=10000;hf0,2,3,128,INT,0,-,-,10,3;"
                             "u,0,COM,off,INT,0,-,-,0,5;t,TEMP,-")
    for bad in ("6", "COM", "x"):
        with pytest.raises(aseq.SequenceError, match="bias"):
            aseq.parse(f"on=1;a,2,3,128,INT,0,-,-,0,{bad}")


def _ntc_table(r25=2000.0, beta=3500.0, temps=np.linspace(-10, 50, 25)):
    return temps, r25 * np.exp(beta * (1 / (temps + 273.15) - 1 / 298.15))


def test_ntc_text_apply_and_device_json():
    cal = pc.PolyCalibration(coeffs=[1e-3, 2e-4, 0, 1e-7], unit="degC", kind="ntc", scale=10000.0, toff=273.15)
    assert cal.to_text() == "ntc:10000,273.15,0.001,0.0002,0,1e-07;degC"
    x = 0.2
    lnr = np.log(x * 10000.0)
    assert cal.apply(x) == pytest.approx(1 / (1e-3 + 2e-4 * lnr + 1e-7 * lnr ** 3) - 273.15)
    assert np.isnan(cal.apply(-0.1))
    d = {"name": "adc_brd.ntc1", "kind": "ntc", "scale": 10000, "toff": 273.15, "c": [1e-3, 2e-4, 0, 1e-7],
         "unit": "degC", "id": "", "date": 0}
    assert pc.PolyCalibration.from_device(d) == dataclasses.replace(cal, name="adc_brd.ntc1")
    assert "1 / (" in cal.summary() and "ln(x·10000)" in cal.summary()
    with pytest.raises(pc.CalibrationError, match="scale"):
        dataclasses.replace(cal, scale=0).to_text()


def test_fit_ntc_ratiometric():
    t, r = _ntc_table()
    cal, rms = pc.fit_ntc(list(zip(r / 10000.0, t)), order=3, scale=10000.0)
    assert rms < 1e-6       # the B equation is exactly a Steinhart-Hart curve
    assert cal.apply(r[3] / 10000.0) == pytest.approx(t[3], abs=1e-6)


def test_compatible_with_redvypr_calibration_ntc():
    from redvypr.devices.sensors.calibration import calibration_models as cm
    t, r = _ntc_table()
    rv = cm.CalibrationNTC(sn="HF1", calibration_id="ntc1",
                           calibration_data=cm.CalibrationData(data=list(r)),
                           calibration_reference_data=cm.CalibrationData(data=list(t)))
    rv.calc_coeffs(3)
    # redvypr fitted on R in Ohm; the norlog measures x = R / 10 kOhm
    nl = pc.from_redvypr(rv, scale=10000.0)
    assert nl.kind == "ntc" and nl.id == "ntc1" and nl.unit == "degC"
    for ri in r[::5]:
        assert nl.apply(ri / 10000.0) == pytest.approx(float(rv.raw2data(ri)), abs=1e-9)
    # and back: the same numbers as redvypr's own model
    back = pc.to_redvypr(nl, channel="ntc1", sn="HF1")
    assert back.calibration_type == "ntc" and back.coeff == pytest.approx(rv.coeff) and back.Toff == rv.Toff
    # text for the device keeps the coefficients
    assert pc.PolyCalibration.from_device({"c": nl.coeffs, "kind": "ntc", "scale": 10000.0, "toff": 273.15,
                                          "unit": "degC"}).apply(0.2) == pytest.approx(nl.apply(0.2))


def test_from_redvypr_poly_linear_heatflow():
    from redvypr.devices.sensors.calibration import calibration_models as cm
    p = pc.from_redvypr(cm.CalibrationPoly(coeff=[2.0, 3.0, 4.0], unit="Pa"))
    assert p.kind == "poly" and p.coeffs == [4.0, 3.0, 2.0] and p.unit == "Pa"
    assert p.apply(2.0) == pytest.approx(float(cm.CalibrationPoly(coeff=[2.0, 3.0, 4.0]).raw2data(2.0)))
    lin = pc.from_redvypr(cm.CalibrationLinearFactor(coeff=5.0, unit="W/m2"))
    assert lin.coeffs == [0.0, 5.0]
    hf = pc.from_redvypr(cm.CalibrationHeatFlow(coeff=16.0))     # 16 W m-2 per mV
    assert hf.coeffs == [0.0, 16000.0] and hf.unit == "W/m2"
    back = pc.to_redvypr(p)
    assert back.calibration_type == "polynom" and back.coeff == [2.0, 3.0, 4.0]


def _packet_with_cal():
    def u(major, v):
        return bytes([(major << 5) | v]) if v < 24 else bytes([(major << 5) | 24, v])

    def t(s):
        return u(3, len(s)) + s.encode()

    def f(v):
        return b"\xfa" + struct.pack(">f", v)

    def lst(items):
        return b"\x9f" + b"".join(items) + b"\xff"
    fields = [(0, u(0, 1)), (9, t("adc_brd")), (90, u(0, 2)),
              (91, lst([t("hf0"), t("temp")])), (92, lst([u(0, 5), u(0, 7)])),
              (93, lst([f(0.00125), f(25.0)])), (94, lst([t("V"), t("degC")])),
              (98, lst([f(20.0), f(float("nan"))])), (99, lst([t("W/m2"), t("")]))]
    body = b"".join(u(0, k) + v for k, v in fields)
    return b"\xd9" + struct.pack(">H", 50009) + b"\xbf" + body + b"\xff"


def test_decode_calibrated_values():
    pkt = norlog_cbor.decode_bytes(_packet_with_cal())
    assert pkt["hf0"] == pytest.approx(0.00125) and pkt["hf0_cal"] == pytest.approx(20.0)
    assert "temp_cal" not in pkt
    units = norlog_cbor.units_of(pkt)
    assert units["hf0"] == "V" and units["hf0_cal"] == "W/m2" and units["temp"] == "degC"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main(["-v", __file__]))
