"""
Magnetometer calibration of the norlog (hard and soft iron), redvypr.devices.norlog.mag_calibration.
"""
import numpy as np
import pytest

from redvypr.devices.norlog import mag_calibration as mc

EARTH = np.array([18.0, 1.0, 46.0])
B_TRUE = np.array([12.0, -30.0, 7.5])
S_TRUE = np.array([[1.10, 0.05, 0.02], [0.05, 0.92, -0.03], [0.02, -0.03, 1.02]])


def _rotation(rng):
    q = rng.normal(size=4)
    w, x, y, z = q / np.linalg.norm(q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _record(n, noise=0.3, seed=1):
    rng = np.random.default_rng(seed)
    return np.array([S_TRUE @ (_rotation(rng).T @ EARTH) + B_TRUE + rng.normal(0, noise, 3) for _ in range(n)])


def test_ellipsoid_fit():
    points = _record(600)
    cal = mc.fit(points)
    assert cal.kind == 'ellipsoid' and cal.coverage == 26
    assert np.allclose(cal.b, B_TRUE, atol=0.3)
    radius = np.linalg.norm(cal.apply(points), axis=1)
    assert cal.rms_ut < 0.5 and abs(radius.mean() - cal.field_ut) < 0.1


def test_text_round_trip():
    cal = mc.fit(_record(300))
    cal.id = 'redvypr test'
    v = cal.to_text().split(',')
    assert len(v) == 16 and v[-1] == 'redvyprtest'     # id without spaces
    back = mc.MagCalibration.from_device({'b': [float(x) for x in v[:3]], 'A': [float(x) for x in v[3:12]],
                                          'field_ut': float(v[12]), 'rms_ut': float(v[13]), 'date': int(v[14])})
    assert np.allclose(back.b, cal.b, atol=1e-3) and np.allclose(back.A, cal.A, atol=1e-5)


def test_sphere_only():
    cal = mc.fit(_record(300), kind='sphere')
    assert cal.kind == 'sphere' and np.allclose(cal.A, np.eye(3))
    assert np.allclose(cal.b, B_TRUE, atol=2.0)


def test_one_axis_only_is_rejected():
    rng = np.random.default_rng(3)
    points = []
    for phi in rng.uniform(0, 2 * np.pi, 300):      # turned around z only: points on a cone
        c, s = np.cos(phi), np.sin(phi)
        points.append(S_TRUE @ (np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]) @ EARTH) + B_TRUE)
    with pytest.raises(mc.CalibrationError):
        mc.fit(np.array(points))


def test_too_few_points():
    with pytest.raises(mc.CalibrationError):
        mc.fit(_record(5))
