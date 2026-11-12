"""
Calibration assignments: which data a calibration converts.

A calibration (``raw2data()``) knows nothing about the datastream it is applied to: the same
sensor can be mounted at other channels. The assignment names it in the configuration of the
device that applies the calibrations::

    calibration_assignments:
      - filter: "hf0 @ i:'adc' and di:'30572ED22A0BE4E8'"   # redvypr address of the raw data
        sn: '1158'                 # the calibration of the sensor valid at the time of the data
        type: hf_sensor            # item type of the sensor (optional)
        result: hf0_W_m2           # datakey of the result (optional, default: replaces the raw data)
        raw_unit: V                # unit of the raw data (optional), converted to the input unit of
                                   # the calibration (V -> mV)
      - filter: "ntc0 @ i:'adc' and di:'30572ED22A0BE4E8'"
        uuid: CALNTC_...           # exactly this calibration

The assignments of a configuration are also metadata (design note design_items.rst, "Calibration
assignments"): one entry per filter address, key ``calibration_assignment``, with the history of
the metadata (valid_from / valid_until) and the flag ``persistent``. :func:`store_assignments`
writes a configuration into a metadata storage (as a new state from a time on, assignments that
are not in it any more end), :func:`assignments_from_storage` reads the state at a time, so a
configuration can be rebuilt for any date.
"""

import copy
import datetime
import logging
import typing

import numpy as np
import pydantic

import redvypr.metadata as redvypr_metadata
from redvypr.redvypr_address import RedvyprAddress
from redvypr.redvypr_datadict import RedvyprDatadict
from redvypr.devices.sensors.calibration import item_calibration

logger = logging.getLogger('redvypr.calibration_assignments')

KEY = 'calibration_assignment'


class CalibrationAssignment(pydantic.BaseModel):
    """The data (filter) a calibration converts."""
    filter: RedvyprAddress = pydantic.Field(
        description='Redvypr address of the raw data: packet filters and the datakey, e.g. '
                    "hf0 @ i:'adc' and di:'<hwid>'")
    sn: typing.Optional[str] = pydantic.Field(
        default=None, description='Serial number of the sensor: its calibration valid at the time of the data')
    type: typing.Optional[str] = pydantic.Field(
        default=None, description='Item type of the sensor (serial numbers are unique per type only)')
    uuid: typing.Optional[str] = pydantic.Field(
        default=None, description='calibration_uuid: exactly this calibration (instead of sn)')
    result: typing.Optional[str] = pydantic.Field(
        default=None, description='Datakey of the converted data; may contain {datakey}. Default: replaces the raw data')
    raw_unit: typing.Optional[str] = pydantic.Field(
        default=None, description='Unit of the raw data, converted to the input unit of the calibration (V -> mV)')

    @pydantic.model_validator(mode='after')
    def _names_a_calibration(self):
        if not self.sn and not self.uuid:
            raise ValueError('an assignment needs the sn of the sensor or the uuid of the calibration')
        return self

    @property
    def address(self) -> str:
        """Metadata address of the assignment: the filter."""
        return RedvyprAddress(self.filter).to_address_string()

    def __eq__(self, other) -> bool:
        # RedvyprAddress has no value comparison: compare the address string
        return isinstance(other, CalibrationAssignment) and self.address == other.address \
            and self.value() == other.value()

    def value(self) -> dict:
        """The metadata value (everything but the filter)."""
        return {k: v for k, v in self.model_dump(exclude={'filter'}).items() if v is not None}


# --- the calibration of an assignment, conversion --------------------------------------------

def _t_of(data) -> typing.Optional[float]:
    try:
        return float(data['_redvypr']['t'])
    except Exception:
        return None


def find_calibration(assignment: CalibrationAssignment, calibrations, at_time=None):
    """The calibration of an assignment from a list: by uuid, else the one of the sensor valid at a time."""
    if assignment.uuid:
        for c in calibrations or []:
            if getattr(c, 'calibration_uuid', None) == assignment.uuid:
                return c
        return None
    datakey = str(RedvyprAddress(assignment.filter).datakey or '')
    return item_calibration.select_calibration(calibrations, assignment.sn, datakey, at_time,
                                               itemtype=assignment.type)


def convert(assignment: CalibrationAssignment, calibration, raw):
    """raw (number or array) converted with the calibration (unit of the raw data -> input unit first)."""
    factor = item_calibration.unit_factor(assignment.raw_unit or '', getattr(calibration, 'unit_input', '') or '')
    if factor is None:
        raise ValueError(f'raw unit {assignment.raw_unit} does not fit the input unit {calibration.unit_input}')
    value = calibration.raw2data(np.asarray(raw, dtype=float) * factor)
    return value.item() if isinstance(value, np.ndarray) and value.ndim == 0 else value


def apply_assignments(assignments, data: dict, calibrations, at_time=None):
    """
    Applies the assignments whose filter matches a datapacket. Returns (datapacket, applied):
    the packet with the converted data (the packet itself if nothing matches) and the list of
    (assignment, calibration) applied. at_time: time of the calibration (default: time of the packet).
    """
    matching = []
    for a in assignments or []:
        try:
            if RedvyprAddress(a.filter).matches(data):
                matching.append(a)
        except Exception:
            logger.debug('filter %s', a.filter, exc_info=True)
    if not matching:
        return data, []
    t = at_time if at_time is not None else _t_of(data)
    rdata = RedvyprDatadict(copy.deepcopy(data))
    applied = []
    for a in matching:
        cal = find_calibration(a, calibrations, t)
        if cal is None:
            logger.info('no calibration for %s (sn %s, uuid %s)', a.filter, a.sn, a.uuid)
            continue
        try:
            raw = rdata[a.filter]
            value = convert(a, cal, raw)
            if a.result:
                datakey = RedvyprAddress(a.filter).datakey
                target = RedvyprAddress(a.filter, datakey=a.result.format(datakey=datakey))
            else:
                target = a.filter
            rdata[target] = value
        except Exception:
            logger.info('assignment %s not applied', a.filter, exc_info=True)
            continue
        applied.append((a, cal))
    return (dict(rdata) if applied else data), applied


# --- metadata -----------------------------------------------------------------------------------

def _active(entry: dict, t: datetime.datetime) -> bool:
    c = entry.get('constraints') or {}
    f = redvypr_metadata.to_datetime(c.get('valid_from'))
    u = redvypr_metadata.to_datetime(c.get('valid_until'))
    return (f is None or f <= t) and (u is None or t < u)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def assignments_from_storage(storage: dict, at_time=None, owner: typing.Optional[str] = None
                             ) -> typing.List[CalibrationAssignment]:
    """
    The assignments valid at a time (default now) in a metadata storage {address: [entries]};
    owner: only those stored for that owner (e.g. the name of the device), default all.
    """
    t = redvypr_metadata.to_datetime(at_time) if at_time is not None else _now()
    out = []
    for address, entries in (storage or {}).items():
        valid = [e for e in entries or [] if isinstance(e, dict) and e.get('key') == KEY and _active(e, t)
                 and (owner is None or (e.get('value') or {}).get('owner') == owner)]
        if not valid:
            continue
        # the later valid_from wins
        e = max(valid, key=lambda x: redvypr_metadata.to_datetime((x.get('constraints') or {}).get('valid_from'))
                or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
        try:
            out.append(CalibrationAssignment.model_validate(dict(e['value'], filter=address)))   # owner: ignored
        except Exception:
            logger.warning('invalid calibration assignment at %s', address, exc_info=True)
    return sorted(out, key=lambda a: a.address)


def store_assignments(storage: dict, assignments, valid_from=None, hostinfo=None,
                      owner: typing.Optional[str] = None) -> typing.List[str]:
    """
    Writes the assignments of a configuration into a metadata storage as the state from valid_from
    on (default now): new or changed assignments start, assignments that are not in the list any
    more end. Unchanged ones add nothing. Several assignments with the same filter: the last one
    counts (a filter has one calibration at a time, whoever owns it). owner (e.g. the name of the
    device): stored with the entries; only the entries of that owner end, so several devices can
    store their configurations. Returns the changed addresses.
    """
    t = redvypr_metadata.to_datetime(valid_from) if valid_from is not None else _now()
    wanted = {a.address: a for a in assignments or []}
    changed = []
    for address, a in wanted.items():
        md = redvypr_metadata.create_metadata_dict(address, {KEY: dict(a.value(), **({'owner': owner} if owner else {}))},
                                                   valid_from=t, hostinfo=hostinfo,
                                                   constraints={'persistent': True})
        before = copy.deepcopy(storage.get(address))
        redvypr_metadata.add_metadata_to_entries(md, storage)
        if storage.get(address) != before:
            changed.append(address)
    for address, entries in storage.items():
        if address in wanted:
            continue
        for e in entries or []:
            if e.get('key') == KEY and _active(e, t) and (e.get('value') or {}).get('owner') == (owner or None):
                c = e.setdefault('constraints', {})
                f = redvypr_metadata.to_datetime(c.get('valid_from'))
                if f is not None and f >= t:
                    continue
                c['valid_until'] = t.isoformat()
                if address not in changed:
                    changed.append(address)
    return changed
