import typing
import pydantic
from redvypr.redvypr_address import RedvyprAddressStr
from redvypr.devices.sensors.calibration.calibration_models import calibration_HF, calibration_NTC, calibration_const, calibration_poly

class Sensor(pydantic.BaseModel):
    name: str = pydantic.Field(default='sensor')
    datastream: RedvyprAddressStr = ''
    parameter: typing.Dict[str,typing.Annotated[typing.Union[calibration_const, calibration_poly], pydantic.Field(discriminator='calibration_type')]]  = pydantic.Field(default={})

class BinarySensor(Sensor):
    """
    A binary sensor gets binary data that need to be converted first into a dictionary with the datakeys
    """
    name: str = pydantic.Field(default='binsensor')
    regex_split: bytes = pydantic.Field(default=b'', description='Regex expression to split a binary string')
    binary_format: typing.Dict[str, str] = pydantic.Field(default={'data_char':'c'})
    str_format: typing.Dict[str, str] = pydantic.Field(default={'data_float':'float'})


s4l_split = b'\$\x00(?P<counter32>[\x00-\xFF]{4})(?P<adc16>[\x00-\xFF]{2})\n'
S4LB = BinarySensor(name='S4LB',regex_split=s4l_split)