import datetime
import typing
import uuid

import dateutil
import numpy as np
import pydantic

from redvypr.redvypr_address import RedvyprAddress


def get_date_from_calibration(calibration, parameter, return_str = False, strformat = '%Y-%m-%d %H:%M:%S'):
    """
    Searches within the calibration for a calibration date. This is a helper function as the date might be at different locations
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


class CalibrationGeneric(pydantic.BaseModel):
    """
    Generic calibration model
    """
    structure_version: str = '1.1'
    calibration_type: typing.Literal['generic'] = 'generic'
    parameter: RedvyprAddress = pydantic.Field(default=RedvyprAddress('/k:PARA_CONST'),
                                               description='The address of calibrated parameter in the datapacket',
                                               editable=False)
    parameter_apply: typing.Optional[RedvyprAddress] = pydantic.Field(default=None,
                                               description='The address of the parameter the calibration should '
                                                          'be applied to. This is optional, if the calibrated '
                                                          'parameter shall be applied to a different parameter. '
                                                          'If it is not set parameter will be used.')
    datakey_result: typing.Optional[str] = pydantic.Field(default=None,
                                                          description='The keyname of the output of the calibration. '
                                                                      'Note that this is the basekey of the datadictionary.')
    sn: str = '' # The serial number of the sensor
    sensor_model: str = ''  # The sensor model
    unit: str = 'NA'
    unit_input: str = 'NA'
    date: datetime.datetime = pydantic.Field(default=datetime.datetime(1970,1,1,0,0,0), description='The calibration date')
    calibration_id: str = pydantic.Field(default='', description='ID of the calibration, can be choosen by the user')
    calibration_uuid: str = pydantic.Field(default_factory=lambda: uuid.uuid4().hex,
                                         description='uuid of the calibration, can be choosen by the user')
    comment: typing.Optional[str] = None

    def raw2data(self, raw_data):
        """
        Dummy function.
        Parameters
        ----------
        raw_data

        Returns
        -------

        """
        data = raw_data
        return data


class CalibrationLinearFactor(CalibrationGeneric):
    """
    Calibration model for a sensor with a linear behaviour
    """
    calibration_type: typing.Literal['linearfactor'] = 'linearfactor'
    coeff: float = pydantic.Field(default = 1.0)

    def raw2data(self, raw_data):
        data = raw_data * self.coeff
        return data

class CalibrationPoly(CalibrationGeneric):
    """
    Calibration model for a parameter with a polynomial behaviour
    """
    coeff: list = pydantic.Field(default = [1.0, 0], description='The calibration polynomial. The first entry is the one with the highest exponent, the last the constant: y = coeff[-1] + x * coeff[-2] + x**2 * coeff[-3]')
    date: datetime.datetime = pydantic.Field(default=datetime.datetime(1970,1,1,0,0,0), description='The calibration date')
    calibration_id: str = pydantic.Field(default='', description='ID of the calibration, can be choosen by the user')
    calibration_uuid: str = pydantic.Field(default_factory=lambda: uuid.uuid4().hex,
                                         description='uuid of the calibration, can be choosen by the user')
    comment: typing.Optional[str] = None

    def raw2data(self, raw_data):
        data = np.polyval(self.coeff,raw_data)
        return data


class CalibrationHeatFlow(CalibrationGeneric):
    """
    Calibration model for a heatflow sensor
    """
    calibration_type: typing.Literal['heatflow'] = 'heatflow'
    parameter: str = 'HF'
    coeff: float = np.nan
    coeff_std: typing.Optional[float] = None
    unit:  str = 'W m-2 mV-1'
    unit_input: str = 'mV'

class CalibrationNTC(CalibrationGeneric):
    """
    Calibration model for a NTC sensor
    """
    calibration_type: typing.Literal['ntc'] = 'ntc'
    datakey_result: typing.Optional[str] = pydantic.Field(default='{datakey}_cal_ntc', description='The keyname of the output of the calibration. Note that this is the basekey of the datadictionary.')
    Toff: float = 273.15 # Offset between K and degC
    coeff: list = pydantic.Field(default = [np.nan, np.nan, np.nan, np.nan])
    unit: str = 'degC'
    unit_input: str = 'Ohm'

    def raw2data(self,data):
        """
        Calculate the temperature based on the calibration and a resistance using a polynome
        """
        P_R = self.coeff
        Toff = self.Toff
        T_1 = np.polyval(P_R, np.log(data))
        T = 1 / T_1 - Toff
        return T

calibration_models = []
calibration_models.append(CalibrationLinearFactor)
calibration_models.append(CalibrationPoly)
calibration_models.append(CalibrationHeatFlow)
calibration_models.append(CalibrationNTC)
