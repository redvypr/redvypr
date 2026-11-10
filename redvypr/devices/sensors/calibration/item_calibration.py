"""
Conversion of the data of a channel into units with the items of the metadata
(design note doc/source/design_items.rst, section "Conversion into units").

Two stages:

1. measuring circuit (setup profile of the channel): input = raw * scale, the
   scale is a parameter of an item (``scale_ref``, e.g. R1 of the board), a
   number (``scale``) or 1;
2. sensor: the calibration whose ``sn`` is the id of the sensor item of the
   channel, the latest with a date before the time of the data;
   value = calibration.raw2data(input), unit = calibration.unit.

Functions work on a metadata storage {address: [entries]} (Redvypr._copy_metadata(),
DbReader.combined_metadata()[0]).
"""

import dataclasses
import datetime
import logging
import typing

import numpy as np

import redvypr.items as ritems
import redvypr.metadata as redvypr_metadata
from redvypr.redvypr_address import RedvyprAddress

logger = logging.getLogger('redvypr.item_calibration')
UTC = datetime.timezone.utc


@dataclasses.dataclass
class CalibrationResult:
    """Value of a conversion and what it was made with."""
    value: typing.Any = None
    unit: str = ''
    items: dict = dataclasses.field(default_factory=dict)       # role -> item
    calibration: typing.Any = None
    scale: float = 1.0
    scale_source: str = ''          # e.g. 'R1 of breakout_board_v01/BO-003', 'nominal 10000', ''
    problems: list = dataclasses.field(default_factory=list)

    @property
    def ok(self):
        return self.value is not None and not self.problems


def _aware(t):
    if t is None:
        return None
    if isinstance(t, datetime.datetime):
        return t if t.tzinfo is not None else t.replace(tzinfo=UTC)
    return redvypr_metadata.to_datetime(t)


def calibrations_from_metadata(storage: dict) -> list:
    """Calibrations stored in the metadata (sensor manager: key 'calibration' at @i:calibration ...)."""
    from .sensor_and_calibration_definitions import CalibrationFactory
    found = []
    # every entry with the key 'calibration' (the addresses of the sensor manager contain content filters)
    md = [e for entries in storage.values() for e in (entries or []) if isinstance(e, dict)]
    seen = set()
    for e in md:
        if e.get('key') != 'calibration' or not isinstance(e.get('value'), dict):
            continue
        uid = e['value'].get('calibration_uuid') or id(e)
        if uid in seen:
            continue
        seen.add(uid)
        try:
            found.append(CalibrationFactory.create(e['value']))
        except Exception:
            logger.debug('could not read a calibration', exc_info=True)
    return found


def _channel_key(calibration):
    channel = getattr(calibration, 'channel', None)
    if channel is None:
        return ''
    try:
        return str(RedvyprAddress(channel).datakey or '') if not isinstance(channel, str) or '@' in channel \
            else channel
    except Exception:
        return str(channel)


NO_MODEL = (None, '', 'NA')


def calibration_fits_type(calibration, itemtype: typing.Optional[str]) -> bool:
    """True if the sensor_model of a calibration is the item type (or not given: any type)."""
    model = getattr(calibration, 'sensor_model', None)
    return itemtype is None or model in NO_MODEL or model == itemtype


def select_calibration(calibrations, sn: str, datakey: str = '', at_time=None,
                       itemtype: typing.Optional[str] = None):
    """
    The calibration of a sensor (serial number sn, item type itemtype) for a datakey at a time:
    the latest with a date before the time. Serial numbers are unique per type only: a
    calibration whose sensor_model is another type is not taken (sensor_model NA or empty: any
    type). If the calibrations of the sensor are for several channels, the one whose channel is
    the datakey (or the datakey without '_suffix'). None if there is none.
    """
    t = _aware(at_time) or datetime.datetime.now(UTC)
    cands = [c for c in calibrations or [] if getattr(c, 'sn', None) == sn and calibration_fits_type(c, itemtype)]
    cands = [c for c in cands if _aware(getattr(c, 'date', None)) is None or _aware(c.date) <= t]
    if not cands:
        return None
    channels = {_channel_key(c) for c in cands}
    if len(channels) > 1:
        keys = ritems._datakey_candidates(str(datakey)) if datakey else []
        match = [c for c in cands if _channel_key(c) in keys]
        if not match:
            match = [c for c in cands if _channel_key(c) == '']
        cands = match
    if not cands:
        return None
    return max(cands, key=lambda c: _aware(getattr(c, 'date', None)) or datetime.datetime.min.replace(tzinfo=UTC))


def channel_props(found: dict, datakey: str) -> dict:
    """Properties of the channel in the setup profile of the items (role 'setup'), {} if none."""
    setup = found.get('setup')
    channels = getattr(setup, 'channels', None) or {}
    for cand in ritems._datakey_candidates(str(datakey or '')):
        props = channels.get(cand)
        if isinstance(props, dict):
            return props
    return {}


def input_scale(found: dict, datakey: str) -> typing.Tuple[float, str, list]:
    """
    Stage 1: (scale, source, problems) of a channel: scale_ref of the profile channel resolved with
    the items, else its scale (number, 'nominal'), else 1.
    """
    props = channel_props(found, datakey)
    ref = props.get('scale_ref')
    if ref and len(ref) == 2:
        role, key = ref
        value, item = ritems.param_from(found, role, key)
        if value is not None and value > 0:
            return value, f'{key} of {item.ref}', []
        nominal = props.get('scale')
        problem = (f'no {key} of the {role}' if item is not None else f'no {role} item') + \
            (f', nominal {nominal:g} used' if isinstance(nominal, (int, float)) else '')
        if isinstance(nominal, (int, float)):
            return float(nominal), f'nominal {nominal:g}', [problem]
        return 1.0, '', [problem]
    if isinstance(props.get('scale'), (int, float)):
        return float(props['scale']), f'scale {props["scale"]:g} of the profile', []
    return 1.0, '', []


_PREFIXES = {'': 1.0, 'k': 1e3, 'm': 1e-3, 'u': 1e-6, '\u00b5': 1e-6, 'n': 1e-9}


def unit_factor(from_unit: str, to_unit: str) -> typing.Optional[float]:
    """
    Factor converting a value in from_unit into to_unit if they differ by an SI prefix only
    (V -> mV: 1000), 1 if equal or one is empty, None if they do not fit.
    """
    a, b = (from_unit or '').strip(), (to_unit or '').strip()
    if not a or not b or a == b or 'NA' in (a, b):
        return 1.0
    for pa, fa in _PREFIXES.items():
        if not a.startswith(pa) or len(a) <= len(pa):
            continue
        for pb, fb in _PREFIXES.items():
            if b.startswith(pb) and len(b) > len(pb) and a[len(pa):] == b[len(pb):]:
                return fa / fb
    return None


def apply_calibration(storage: dict, address, raw, at_time=None, calibrations=None,
                      found: typing.Optional[dict] = None) -> CalibrationResult:
    """
    Convert a raw value (number or array) of a datastream at a time with its items and calibrations.
    calibrations: list of calibration models (default: those in the metadata).
    """
    raddr = address if isinstance(address, RedvyprAddress) else RedvyprAddress(address)
    found = ritems.get_items(storage, raddr, at_time=at_time) if found is None else found
    res = CalibrationResult(items=found)
    sensor = found.get('sensor')
    if sensor is None:
        res.problems.append('no sensor item for the channel')
        return res
    datakey = str(raddr.datakey or '')
    res.scale, res.scale_source, problems = input_scale(found, datakey)
    res.problems.extend(problems)
    if calibrations is None:
        calibrations = calibrations_from_metadata(storage)
    sn = getattr(sensor, 'sn', None) or sensor.id
    cal = select_calibration(calibrations, sn, datakey, at_time, itemtype=sensor.itemtype)
    if cal is None:
        res.problems.append(f'no calibration of {sensor.ref} (sn {sn}, sensor_model {sensor.itemtype} or NA)')
        return res
    res.calibration = cal
    res.unit = getattr(cal, 'unit', '') or ''
    # raw unit of the channel (profile) -> input unit of the calibration (e.g. V -> mV)
    raw_unit = channel_props(found, datakey).get('raw_unit') or ''
    factor = unit_factor(raw_unit, getattr(cal, 'unit_input', '') or '')
    if factor is None:
        res.problems.append(f'raw unit {raw_unit} does not fit the input unit {cal.unit_input} of the calibration')
        return res
    if factor != 1.0:
        res.scale *= factor
        res.scale_source = (res.scale_source + ', ' if res.scale_source else '') + \
            f'{raw_unit} -> {cal.unit_input} x{factor:g}'
    x = np.asarray(raw, dtype=float) * res.scale
    try:
        value = cal.raw2data(x)
    except Exception as exc:
        res.problems.append(f'calibration failed: {exc}')
        return res
    res.value = value.item() if isinstance(value, np.ndarray) and value.ndim == 0 else value
    return res


# --- calibrations of an item (Items window: area "Calibrations") ----------------------------

# Item type of the sensor of a calibration type, if the calibration does not name it
# (sensor_model NA): used to create the sensor item when a calibration is imported
CALIBRATION_ITEMTYPES = {
    'heatflow_classic': 'heatflow_classic',
    'ntc': 'ntc_sensor',
}


def item_sn(item) -> str:
    """Serial number of an item (its sn, else its id)."""
    return getattr(item, 'sn', None) or item.id


def calibrations_of_item(storage: dict, item, calibrations=None) -> list:
    """The calibrations of an item (serial number and type), oldest first."""
    if calibrations is None:
        calibrations = calibrations_from_metadata(storage)
    sn = item_sn(item)
    cals = [c for c in calibrations if getattr(c, 'sn', None) == sn and calibration_fits_type(c, item.itemtype)]
    return sorted(cals, key=lambda c: _aware(getattr(c, 'date', None)) or datetime.datetime.min.replace(tzinfo=UTC))


def calibration_summary(cal) -> str:
    """Short text of the coefficients of a calibration."""
    for key in ('coeff', 'coeffs', 'calibration_HF_SI'):
        value = getattr(cal, key, None)
        if value is None:
            continue
        if isinstance(value, (list, tuple, np.ndarray)):
            return f'{key} = [' + ', '.join(f'{v:.6g}' for v in list(value)[:4]) + (', ...]' if len(value) > 4 else ']')
        try:
            return f'{key} = {float(value):.6g}'
        except (TypeError, ValueError):
            return f'{key} = {value}'
    return ''


def calibration_metadict(cal) -> dict:
    """Metadata of a calibration for Redvypr.set_metadata_from_dict(): {address: {'calibration': ...}}."""
    return {cal.create_redvypr_address().to_address_string(): {'calibration': cal.model_dump(mode='json')}}


def read_calibration_file(path) -> list:
    """The calibrations of a YAML file (one or several documents) of the sensor manager."""
    import yaml
    from .sensor_and_calibration_definitions import CalibrationFactory
    cals = []
    with open(path, 'r', encoding='utf-8') as f:
        for data in yaml.safe_load_all(f):
            if data is None:
                continue
            for d in (data if isinstance(data, list) else [data]):
                cals.append(CalibrationFactory.create(d))
    return cals


def _set_if_field(cal, key, value):
    """Sets a field of a calibration model (not a property)."""
    if key in type(cal).model_fields:
        setattr(cal, key, value)
        return True
    return False


def import_calibrations(redvypr_instance, calibrations, item=None) -> list:
    """
    Puts calibrations into the metadata of a redvypr instance; their sensor items are created if
    missing. item: the selected item; a calibration without serial number or type takes them from it.
    The item type of a sensor: sensor_model of the calibration, else the type of the selected item
    (same serial number), else CALIBRATION_ITEMTYPES of the calibration type.
    Returns [(calibration, sensor reference or None, created: bool)].
    """
    from redvypr import items as ritems_
    report = []
    for cal in calibrations:
        sn = getattr(cal, 'sn', None)
        if item is not None and sn in NO_MODEL:
            _set_if_field(cal, 'sn', item_sn(item))
            sn = getattr(cal, 'sn', None)
        model = getattr(cal, 'sensor_model', None)
        itemtype = None
        if model not in NO_MODEL:
            itemtype = model
        elif item is not None and sn == item_sn(item):
            itemtype = item.itemtype
            _set_if_field(cal, 'sensor_model', itemtype)
        else:
            itemtype = CALIBRATION_ITEMTYPES.get(getattr(cal, 'calibration_type', None))
            if itemtype:
                _set_if_field(cal, 'sensor_model', itemtype)
        ref, created = None, False
        if sn not in NO_MODEL and itemtype:
            ref = ritems_.make_ref(itemtype, sn)
            if redvypr_instance.get_item(ref, builtin=False) is None:
                sensor = _new_sensor_item(itemtype, sn, cal)
                when = _aware(getattr(cal, 'date', None))
                redvypr_instance.add_item(sensor, valid_from=when)
                created = True
        redvypr_instance.set_metadata_from_dict(calibration_metadict(cal))
        report.append((cal, ref, created))
    return report


def _new_sensor_item(itemtype, sn, cal):
    from redvypr import items as ritems_
    from .sensor_and_calibration_definitions import HeatflowClassicSensor, HeatflowClassicCalibration
    if itemtype == HeatflowClassicSensor.ITEMTYPE and isinstance(cal, HeatflowClassicCalibration):
        return HeatflowClassicSensor.from_calibration(cal, name=cal.name or None, sn=sn)
    return ritems_.get_item_type(itemtype)(itemtype=itemtype, id=sn)


def remove_calibration(redvypr_instance, calibration_uuid: str) -> int:
    """Removes a calibration (by its uuid) from the metadata of a redvypr instance; number of addresses."""
    import redvypr.redvypr_datadict as data_packets
    removed = {}
    for addr, entries in redvypr_instance._copy_metadata().items():
        for e in entries or []:
            v = e.get('value') if isinstance(e, dict) else None
            if e.get('key') == 'calibration' and isinstance(v, dict) and v.get('calibration_uuid') == calibration_uuid:
                removed[addr] = {'keys': ['calibration'], 'mode': 'exact'}
    if removed:
        packet = data_packets.commandpacket(command='reply')
        packet['_metadata_remove'] = removed
        redvypr_instance.redvyprqueue.put(packet)
        redvypr_instance.redvyprreplyqueue.get()
    return len(removed)


def change_times(storage: dict, calibrations, t_start: float, t_end: float) -> list:
    """Times (unix) in (t_start, t_end] at which metadata entries or calibrations begin or end."""
    times = set()
    for entries in storage.values():
        for e in entries or []:
            c = e.get('constraints') or {}
            for k in ('valid_from', 'valid_until'):
                t = redvypr_metadata.to_datetime(c.get(k))
                if t is not None:
                    ts = t.timestamp()
                    if t_start < ts <= t_end:
                        times.add(ts)
    for cal in calibrations or []:
        t = _aware(getattr(cal, 'date', None))
        if t is not None and t_start < t.timestamp() <= t_end:
            times.add(t.timestamp())
    return sorted(times)


def calibrate_series(storage: dict, address, t, data, calibrations=None):
    """
    Convert a time series (t: unix times, data: raw values) of a datastream. The series is split where
    items, assignments or calibrations change; every part is converted with the state of its begin.
    Returns (values, unit, parts) with parts [(t_from, t_to, CalibrationResult without value)];
    values NaN where nothing could be converted.
    """
    t = np.asarray(t, dtype=float)
    data = np.asarray(data, dtype=float)
    values = np.full(data.shape, np.nan)
    parts = []
    if t.size == 0:
        return values, '', parts
    if calibrations is None:
        calibrations = calibrations_from_metadata(storage)
    bounds = [float(t.min())] + change_times(storage, calibrations, float(t.min()), float(t.max())) + \
        [float(t.max()) + 1.0]
    units = set()
    for t0, t1 in zip(bounds[:-1], bounds[1:]):
        sel = (t >= t0) & (t < t1)
        if not sel.any():
            continue
        at = datetime.datetime.fromtimestamp(t0, UTC)
        res = apply_calibration(storage, address, data[sel], at_time=at, calibrations=calibrations)
        if res.value is not None:
            values[sel] = res.value
            units.add(res.unit)
        res.value = None
        parts.append((t0, t1, res))
    unit = units.pop() if len(units) == 1 else ''
    return values, unit, parts


def get_data_calibrated(reader, address, t_start=None, t_end=None, max_points=None, calibrations=None):
    """
    Data of a database (redvypr.datasource.DbReader) converted with the items and calibrations of its
    metadata merged with the further sources (e.g. the running instance). Returns the dict of
    reader.get_data() with 'data' converted and 'unit', 'parts', 'raw' added.
    """
    d = reader.get_data(address, t_start, t_end, max_points)
    storage = reader.combined_metadata()[0]
    values, unit, parts = calibrate_series(storage, address, d['t'], d['data'], calibrations=calibrations)
    d = dict(d)
    d['raw'] = d['data']
    d['data'] = values
    d['unit'] = unit
    d['parts'] = parts
    return d
