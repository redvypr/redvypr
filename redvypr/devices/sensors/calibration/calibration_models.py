import datetime
import sys
import typing
import uuid
import logging
import json
import yaml
import dateutil
import numpy as np
import pydantic

from redvypr.redvypr_address import RedvyprAddress

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('calibration_models')
logger.setLevel(logging.DEBUG)


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



# Classes the deal with saving, loading and processing calibrations
class CalibrationList(list):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calibration_files = []

    def add_calibration_file(self, calfile, reload=True):
        funcname = __name__ + 'add_calibration_file():'
        logger.debug(funcname)
        calfiles_tmp = list(self.calibration_files)
        if (calfile in calfiles_tmp) and reload:
            # print('Removing file first')
            self.rem_calibration_file(calfile)

        calfiles_tmp = list(self.calibration_files)
        # print('Hallo',calfiles_tmp)
        if calfile not in calfiles_tmp:
            # print('Adding file 2',calfile)
            self.calibration_files.append(calfile)
        else:
            logger.debug(funcname + ' File is already listed')

        self.process_calibrationfiles()

    def process_calibrationfiles(self):
        funcname = __name__ + '.process_calibrationfiles()'
        logger.debug(funcname)
        fnames = []

        for fname in self.calibration_files:
            fnames.append(str(fname))

        self.coeff_filenames = fnames

        for fname in fnames:
            if fname not in self.calfiles_processed:
                logger.debug(funcname + ' reading file {:s}'.format(fname))
                calibration = self.read_calibration_file(fname)
                if calibration is not None:
                    flag_add = self.add_calibration(calibration)
                    if flag_add:
                        self.calfiles_processed.append(fname)
            else:
                logger.debug(funcname + ' file {:s} already processed'.format(fname))

        # print(self.calibration['sn'].keys())
        # self.logger_autocalibration()


    def add_calibration(self, calibration):
        """
        Adds a calibration to the calibration list, checks before, if the calibration exists
        calibration: calibration model
        """
        flag_new_calibration = True
        calibration_json = json.dumps(calibration.model_dump_json())
        for cal_old in self.calibrations:
            if calibration_json == json.dumps(cal_old.model_dump_json()):
                flag_new_calibration = False
                break

        if flag_new_calibration:
            logger.debug('Sending new calibration signal')
            self.calibrations.append(calibration)
            return True
        else:
            logger.warning('Calibration exists already')
            return False


    def read_calibration_file(self, fname):
        """
        Open and reads a calibration file, it will as well determine the type of calibration and call the proper function

        """
        funcname = __name__ + '.read_calibration_file():'
        logger.debug(funcname + 'Opening file {:s}'.format(fname))
        try:
            f = open(fname)
            safe_load = False
            if safe_load:
                loader = yaml.SafeLoader
            else:
                loader = yaml.CLoader

            data = yaml.load(f, Loader=loader)
            # print('data',data)
            if 'structure_version' in data.keys():  # Calibration model
                logger.debug(funcname + ' Version {} pydantic calibration model dump'.format(data['structure_version']))
                for calmodel in self.calibration_models:  # Loop over all calibration models definded in sensor_calibrations.py
                    try:
                        calibration = calmodel.model_validate(data)
                        return calibration
                    except:
                        pass

        except Exception as e:
            logger.exception(e)
            return None


    def rem_calibration_file(self, calfile):
        funcname = __name__ + 'rem_calibration_file():'
        logger.debug(funcname)
        calfiles_tmp = list(self.calibration_files)
        if calfile in calfiles_tmp:
            calibration = self.read_calibration_file(calfile)
            calibration_json = json.dumps(calibration.model_dump_json())
            for cal_old in self.calibrations:
                # Test if the calibration is existing
                if calibration_json == json.dumps(cal_old.model_dump_json()):
                    logger.debug(funcname + ' Removing calibration')
                    self.calibration_files.remove(calfile)
                    self.calibrations.remove(cal_old)
                    self.calfiles_processed.remove(calfile)
                    return True

    def save(self, calfile, group=None):
        """

        Parameters
        ----------
        calfile: The filename
        group: ('sn', 'date', 'sensor_model', 'calibration_id', 'calibration_uuid', 'calibration_type')

        Returns
        -------

        """

        funcname = __name__ + '.save():'
        logger.debug(funcname)
        calfiles = {}
        if group is None:
            calfiles = {calfile:self}
        else:
            calfile_mod = calfile.replace('.yaml','')
            # Add the group as additional filename information
            for g in group:
                calfile_mod += '_{' + g + '}'

            calfile_mod += '.yaml'
            logger.debug(funcname + ' calfile_mod:{}'.format(calfile_mod))
            # Sort the calibrations
            logger.debug(funcname + ' Sorting calibrations')
            for calibration in self:
                calfile_name = calfile_mod.format(sn=calibration.sn,date=calibration.date,sensor_model=calibration.sensor_model,calibration_id=calibration.calibration_id,calibration_uuid=calibration.calibration_uuid,calibration_type=calibration.calibration_type)
                #print('calfile_name',calfile_name)
                try:
                    calfiles[calfile_name]
                except:
                    logger.debug(funcname + ' Creating new file:{}'.format(calfile_name))
                    calfiles[calfile_name] = []

                calfiles[calfile_name].append(calibration)



        for calfile_write in calfiles:
            logger.debug('Writing to file {}'.format(calfile_write))
            f = open(calfile_write,'w')
            for calibration_write in calfiles[calfile_write]:
                calibration_yaml = yaml.dump(calibration_write.model_dump(), explicit_end=True, explicit_start=True)
                f.write(calibration_yaml)
                #print('Calibration dump ...', calibration_yaml)

            f.close()






