"""
Calibration of the norlog magnetometer (MMC5983MA): hard and soft iron.

The device is turned in all directions while it records the field (firmware
>= 0.4.12, "norlog mag cal start" / CoAP "mag?op=start"). Without disturbances
the points lie on a sphere with the radius of the earth field; hard iron
(magnetized parts turning with the device: battery, connectors, screws) shifts
it by b, soft iron and different gains/axes make it an ellipsoid. The fit gives
b and A with

    B_cal = A @ (B_raw - b)

so that the calibrated points lie on a sphere. A keeps the volume of the
ellipsoid (radius = geometric mean of the half axes), it does not scale to a
nominal earth field.

fit(points) tries the ellipsoid fit (9 parameters, needs enough directions) and
falls back to a sphere fit (hard iron only, A = identity).
"""

import dataclasses
import datetime
import math

import numpy as np

# Directions for the coverage: 6 faces, 12 edges, 8 corners of a cube
_DIRS = np.array([d for d in np.ndindex(3, 3, 3) if d != (1, 1, 1)], dtype=float) - 1.0
_DIRS /= np.linalg.norm(_DIRS, axis=1)[:, None]
COVERAGE_ANGLE_DEG = 30.0       # a direction counts as covered within this angle
MIN_COVERAGE_ELLIPSOID = 18     # of 26 directions for the full (hard + soft iron) fit
MIN_COVERAGE_SPHERE = 8         # for the hard iron (sphere) fit
MIN_POINTS = 20
MIN_SPREAD = 0.15               # smallest / largest standard deviation of the points (3D spread)


class CalibrationError(Exception):
    pass


@dataclasses.dataclass
class MagCalibration:
    b: np.ndarray                   # hard iron [µT]
    A: np.ndarray                   # soft iron (3x3)
    field_ut: float                 # radius of the calibrated sphere [µT]
    rms_ut: float                   # rms of |B_cal| - field [µT]
    kind: str                       # 'ellipsoid' or 'sphere'
    coverage: int                   # covered directions (of 26)
    n: int                          # number of points
    date: int = 0                   # unix time of the calibration
    id: str = ''

    def apply(self, points):
        return (np.asarray(points, dtype=float) - self.b) @ self.A.T

    def to_text(self):
        """Values for the device: 'b0,b1,b2,a00,...,a22,field_ut,rms_ut,date[,id]' (norlog cal set mag)."""
        values = [*self.b, *self.A.reshape(9)]
        text = ','.join(f'{v:.6g}' for v in values)
        text += f',{self.field_ut:.4f},{self.rms_ut:.4f},{int(self.date)}'
        ident = ''.join(c for c in self.id if c.isalnum() or c in '-_.:')[:23]
        return text + (f',{ident}' if ident else '')

    @classmethod
    def from_device(cls, d):
        """From the device JSON {"b":[..],"A":[..],"field_ut","rms_ut","date","id"} (None: no calibration)."""
        if not d:
            return None
        return cls(b=np.array(d['b'], dtype=float), A=np.array(d['A'], dtype=float).reshape(3, 3),
                   field_ut=float(d.get('field_ut', 0)), rms_ut=float(d.get('rms_ut', 0)), kind='device',
                   coverage=0, n=0, date=int(d.get('date', 0)), id=d.get('id', ''))

    def summary(self):
        when = (datetime.datetime.fromtimestamp(self.date, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
                if self.date else '-')
        return (f"hard iron b = {self.b[0]:.2f}, {self.b[1]:.2f}, {self.b[2]:.2f} µT, field {self.field_ut:.2f} µT, "
                f"residual {self.rms_ut:.2f} µT, {when}" + (f", {self.id}" if self.id else ''))


def coverage(points, center):
    """Number of the 26 directions (from center) with at least one point within COVERAGE_ANGLE_DEG."""
    v = np.asarray(points, dtype=float) - center
    norm = np.linalg.norm(v, axis=1)
    v = v[norm > 0] / norm[norm > 0][:, None]
    if len(v) == 0:
        return 0
    cos_max = (v @ _DIRS.T).max(axis=0)
    return int((cos_max >= math.cos(math.radians(COVERAGE_ANGLE_DEG))).sum())


def fit_sphere(points):
    """Center b and radius r of the best sphere |x - b| = r (linear least squares)."""
    p = np.asarray(points, dtype=float)
    D = np.column_stack([2 * p, np.ones(len(p))])
    sol, *_ = np.linalg.lstsq(D, (p ** 2).sum(axis=1), rcond=None)
    b = sol[:3]
    r2 = sol[3] + b @ b
    if r2 <= 0:
        raise CalibrationError('sphere fit failed')
    return b, math.sqrt(r2)


def fit_ellipsoid(points):
    """
    Center b and matrix M of the ellipsoid (x - b)^T M (x - b) = 1 (algebraic least squares,
    a x² + b y² + c z² + 2d xy + 2e xz + 2f yz + 2g x + 2h y + 2i z = 1).
    """
    p = np.asarray(points, dtype=float)
    x, y, z = p[:, 0], p[:, 1], p[:, 2]
    D = np.column_stack([x * x, y * y, z * z, 2 * x * y, 2 * x * z, 2 * y * z, 2 * x, 2 * y, 2 * z])
    v, *_ = np.linalg.lstsq(D, np.ones(len(p)), rcond=None)
    Q = np.array([[v[0], v[3], v[4]], [v[3], v[1], v[5]], [v[4], v[5], v[2]]])
    g = v[6:9]
    b = -np.linalg.solve(Q, g)
    r = 1.0 + b @ Q @ b
    M = Q / r
    if not np.all(np.linalg.eigvalsh(M) > 0):
        raise CalibrationError('the points do not form an ellipsoid')
    return b, M


def _sqrtm_sym(M):
    w, V = np.linalg.eigh(M)
    return V @ np.diag(np.sqrt(w)) @ V.T


def fit(points, kind='auto'):
    """
    Calibration from the recorded points (N x 3, µT). kind: 'auto' (ellipsoid if the
    coverage is enough, otherwise sphere), 'ellipsoid' or 'sphere'.
    """
    p = np.asarray(points, dtype=float)
    p = p[np.all(np.isfinite(p), axis=1)]
    if len(p) < MIN_POINTS:
        raise CalibrationError(f'too few points ({len(p)}, at least {MIN_POINTS})')
    # The points must span all three dimensions: turned around one axis only they lie on
    # a cone (one ring), the center along that axis is not determined
    sd = np.sqrt(np.clip(np.linalg.eigvalsh(np.cov(p.T)), 0, None))
    if sd[-1] <= 0 or sd[0] / sd[-1] < MIN_SPREAD:
        raise CalibrationError('the points lie almost in one plane (turned around one axis only?): '
                               'turn the device in all directions')
    b_s, r_s = fit_sphere(p)
    cov = coverage(p, b_s)
    if kind == 'auto':
        kind = 'ellipsoid' if cov >= MIN_COVERAGE_ELLIPSOID else 'sphere'
    if cov < MIN_COVERAGE_SPHERE:
        raise CalibrationError(f'only {cov} of 26 directions covered: turn the device in all directions')
    if kind == 'ellipsoid':
        try:
            b, M = fit_ellipsoid(p)
        except (CalibrationError, np.linalg.LinAlgError):
            b, M, kind = None, None, 'sphere'
    if kind == 'ellipsoid':
        field = float(np.linalg.det(M) ** (-1.0 / 6.0))     # geometric mean of the half axes
        A = field * _sqrtm_sym(M)
    else:
        b, field, A = b_s, r_s, np.eye(3)
    cal = MagCalibration(b=np.asarray(b), A=A, field_ut=field, rms_ut=0.0, kind=kind, coverage=cov, n=len(p),
                         date=int(datetime.datetime.now(datetime.timezone.utc).timestamp()))
    radius = np.linalg.norm(cal.apply(p), axis=1)
    cal.rms_ut = float(np.sqrt(np.mean((radius - field) ** 2)))
    return cal
