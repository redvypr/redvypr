"""
Item types of the norlog (redvypr.items, design note doc/source/design_items.rst):
the loggers, the breakout boards and the sensors on them.

A norlog item names its data source with ``deviceid`` = hardware ID (the
``di`` of its packets). Boards sit on a norlog (``parent``), sensors on a
board, in the slot of their channel (e.g. ``ntc0``).
"""

import typing

import pydantic

from redvypr import items


@items.register_item_type
class NorlogV02(items.Item):
    """norlog main board v02 (deviceid = hardware ID of the nRF52840)."""
    ITEMTYPE: typing.ClassVar[str] = 'norlog_v02'
    REVISION: typing.ClassVar[int] = 1


@items.register_item_type
class NorlogV021(items.Item):
    """norlog main board v02.1 (deviceid = hardware ID of the nRF52840)."""
    ITEMTYPE: typing.ClassVar[str] = 'norlog_v021'
    REVISION: typing.ClassVar[int] = 1


@items.register_item_type
class BreakoutBoardV01(items.Item):
    """
    Breakout norlog_v02_breakout_v01: two heat flux sensors (hf0, hf1) and two NTCs
    (ntc0, ntc1) measured ratiometrically against R1 (REF1 = AIN6/AIN7).
    """
    ITEMTYPE: typing.ClassVar[str] = 'breakout_board_v01'
    REVISION: typing.ClassVar[int] = 1
    SLOTS: typing.ClassVar[dict] = {
        'hf0': {'accepts': ['hf_sensor'], 'label': 'heat flux 0 (J2 1/2)'},
        'ntc0': {'accepts': ['ntc_sensor'], 'label': 'NTC 0 (J2 3/4)'},
        'hf1': {'accepts': ['hf_sensor'], 'label': 'heat flux 1 (J2 5/6)'},
        'ntc1': {'accepts': ['ntc_sensor'], 'label': 'NTC 1 (J2 7/8)'},
    }
    R1: typing.Optional[items.Quantity] = pydantic.Field(
        default=None, description='Reference resistor of the NTCs (nominal 10 kOhm, ERA-6ARB103V), '
                                  'measured: R_ref of the NTC calibration')


@items.register_item_type
class NtcSensor(items.Item):
    """An NTC thermistor."""
    ITEMTYPE: typing.ClassVar[str] = 'ntc_sensor'
    REVISION: typing.ClassVar[int] = 1
    r25: typing.Optional[items.Quantity] = pydantic.Field(default=None, description='Resistance at 25 degC')
    beta: typing.Optional[float] = pydantic.Field(default=None, description='B value [K]')
    dissipation_constant: typing.Optional[items.Quantity] = pydantic.Field(
        default=None, description='Self heating: power per temperature rise, e.g. mW/K')

