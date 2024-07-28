import pydantic
import typing
import numpy as np
import datetime
import dateutil
import uuid


def get_date_from_calibration(calibration, parameter, return_str = False, strformat = '%Y-%m-%d %H:%M:%S'):
    """
    Searches within the calibration for a calibration date. This is a helper function as the date made be at different locations
    """
    funcname = __name__ + '.get_date_from_calibration():'
    try:
        coeff = calibration['parameter'][parameter]
    except:
        coeff = None
    # Get the calibration data, that can be either in each of the parameters, or as a key for all parameter
    datestr = '1970-01-01 00:00:00'
    try:
        datestr = str(coeff['date'])
    except:
        try:
            datestr = str(calibration['date'])
        except:
            datestr = str(calibration.date)

    #logger.debug(funcname + ' dates {:s}'.format(datestr))
    print(funcname + ' dates {:s}'.format(datestr))
    dateformats = ['%d.%m.%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d_%H-%M-%S']
    for df in dateformats:
        try:
            td = datetime.datetime.strptime(datestr, df)  # '18.07.2023 13:42:16'
        except:
            td = None

    # Last resort, dateutil
    if td is None:
        try:
            td = dateutil.parser.parse(datestr)
        except:
            td = None

    if return_str and (td is not None):
        return td.strftime(strformat)
    else:
        return td


class calibration_const(pydantic.BaseModel):
    """
    Calibration model for a NTC sensor
    """
    structure_version: str = '1.0'
    calibration_type: typing.Literal['const'] = 'const'
    parameter: str = pydantic.Field(default = 'XYZ',description='The calibrated parameter')
    parameter_result: typing.Optional[str] = pydantic.Field(default = None,description='The keyname of the output parameter')
    sn: str = '' # The serial number of the sensor
    sensor_model: str = ''  # The sensor model
    coeff: float = pydantic.Field(default = 1.0)
    unit: str = 'NA'
    unit_input: str = 'NA'
    date: datetime.datetime = pydantic.Field(default=datetime.datetime(1970,1,1,0,0,0), description='The calibration date')
    calibration_id: str = pydantic.Field(default='', description='ID of the calibration, can be choosen by the user')
    calibration_uuid: str = pydantic.Field(default_factory=lambda: uuid.uuid4().hex,
                                         description='uuid of the calibration, can be choosen by the user')
    comment: typing.Optional[str] = None

    def raw2data(self, raw_data):
        data = raw_data * self.coeff
        return data

class calibration_poly(pydantic.BaseModel):
    """
    Calibration model for a sensor with a polynomial response
    """
    structure_version: str = '1.0'
    calibration_type: typing.Literal['poly'] = 'poly'
    parameter: str = pydantic.Field(default = 'XYZ',description='The calibrated parameter')
    sn: str = '' # The serial number of the sensor
    sensor_model: str = ''  # The sensor model
    coeff: list = pydantic.Field(default = [1.0, 0], description='The calibration polynomial. The first entry is the one with the highest exponent, the last the constant: y = coeff[-1] + x * coeff[-2] + x**2 * coeff[-3]')
    unit: str = 'NA'
    unit_input: str = 'NA'
    date: datetime.datetime = pydantic.Field(default=datetime.datetime(1970,1,1,0,0,0), description='The calibration date')
    calibration_id: str = pydantic.Field(default='', description='ID of the calibration, can be choosen by the user')
    calibration_uuid: str = pydantic.Field(default_factory=lambda: uuid.uuid4().hex,
                                         description='uuid of the calibration, can be choosen by the user')
    comment: typing.Optional[str] = None

    def raw2data(self, raw_data):
        data = np.polyval(self.coeff,raw_data)
        return data


class calibration_HF(pydantic.BaseModel):
    """
    Calibration model for a heatflow sensor
    """
    structure_version: str = '1.0'
    calibration_type: typing.Literal['heatflow'] = 'heatflow'
    parameter: str = 'HF'
    sn: str = '' # The serial number of the sensor
    sensor_model: str = ''  # The sensor model
    coeff: float = np.NaN
    coeff_std: typing.Optional[float] = None
    unit:  str = 'W m-2 mV-1'
    unit_input: str = 'mV'
    date: datetime.datetime = pydantic.Field(default=datetime.datetime(1970, 1, 1, 0, 0, 0),
                                             description='The calibration date')
    calibration_id: str = pydantic.Field(default='',
                                         description='ID of the calibration, can be choosen by the user.')
    calibration_uuid: str = pydantic.Field(default_factory=lambda: uuid.uuid4().hex, description='uuid of the calibration, can be choosen by the user. ID should be unique')
    comment: typing.Optional[str] = None

class calibration_NTC(pydantic.BaseModel):
    """
    Calibration model for a NTC sensor
    """
    structure_version: str = '1.0'
    calibration_type: typing.Literal['ntc'] = 'ntc'
    parameter: str = pydantic.Field(default = 'NTC_NUMXYZ',description='The calibrated parameter, this links the calibration to a specific sensor, i.e. NTC0 or NTC_A[10]')
    sn: str = '' # The serial number of the sensor
    sensor_model: str = ''  # The sensor model
    Toff: float = 273.15 # Offset between K and degC
    coeff: list = pydantic.Field(default = [np.NaN, np.NaN, np.NaN, np.NaN])
    #coeff_std: typing.Optional[float] = None
    unit: str = 'T'
    unit_input: str = 'ohm'
    date: datetime.datetime = pydantic.Field(default=datetime.datetime(1970,1,1,0,0,0), description='The calibration date')
    calibration_id: str = pydantic.Field(default='', description='ID of the calibration, can be choosen by the user')
    calibration_uuid: str = pydantic.Field(default_factory=lambda: uuid.uuid4().hex,
                                         description='uuid of the calibration, can be choosen by the user')
    comment: typing.Optional[str] = None
