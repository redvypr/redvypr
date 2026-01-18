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
import pytz
import hashlib

import redvypr
from redvypr.redvypr_address import RedvyprAddress

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.calibration_models')
logger.setLevel(logging.DEBUG)


def get_calibration_uuid():
    #return 'CAL_' + str(uuid.uuid4())
    uuid_str = uuid.uuid4().hex
    short_uuid = "CAL" + uuid_str[:28]
    return short_uuid



class CalibrationData(pydantic.BaseModel):
    sn: str = pydantic.Field(default='')
    channel: typing.Optional[str] = pydantic.Field(default='')
    sensor_model: str = pydantic.Field(default='')
    unit: str = pydantic.Field(default='')
    sensortype: str = pydantic.Field(default='')
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''))
    inputtype: str = pydantic.Field(default='')
    comment: str = pydantic.Field(default='')
    data: list = pydantic.Field(default=[])
    time_data: list = pydantic.Field(default=[])

# A class to store sensordata used for the calibration



# Convert to timezone-aware datetime, needed for sorting
def to_aware(dt):
    if dt.tzinfo is None:
        return pytz.utc.localize(dt)
    return dt


def find_calibration_for_channel(channel, calibrations, sn=None, date=None, date2=None, calibration_type=None, calibration_id=None, calibration_uuid=None, sort_by='date'):
    """

    Parameters
    ----------
    sn
    date
    date2
    calibration_type
    calibration_id
    calibration_uuid
    sort_by
    channel
    calibrations

    Returns
    -------

    """
    # make an address out of the parameter
    channel = redvypr.RedvyprAddress(channel)
    calibration_candidates = []
    for calibration in calibrations:
        # Check if the address fits
        flag_candidate = True
        if calibration.channel in channel:
            logger.debug('Found correct parameter')
            if sn is not None:
                flag_candidate = sn in calibration.sn
            if calibration_type is not None:
                flag_candidate = calibration_type == calibration.calibration_type
            if calibration_uuid is not None:
                flag_candidate = calibration_uuid == calibration.calibration_uuid
            if calibration_id is not None:
                flag_candidate = calibration_id == calibration.calibration_id
            if date is not None and date2 is None:
                logger.debug('Exact match of date')
                flag_candidate = date == calibration.date
            if date is not None and date2 is not None:
                logger.debug('Checking for time interval date <= calibration >= date2')
                flag_candidate = (date <= calibration.date) and (date2 >= calibration.date)

            if flag_candidate:
                logger.debug('Adding calibration')
                calibration_candidates.append(calibration)

    # Sort by date
    if sort_by == 'date':
        calibration_candidates = sorted(calibration_candidates, key=lambda x: to_aware(x.date), reverse=True)

    return calibration_candidates
def get_date_from_calibration(calibration, channel, return_str = False, strformat = '%Y-%m-%d %H:%M:%S'):
    """
    Searches within the calibration for a calibration date. This is a helper function as the date might be at different locations
    """
    funcname = __name__ + '.get_date_from_calibration():'
    try:
        coeff = calibration['channel'][channel]
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
    _content_id: typing.Optional[str] = pydantic.PrivateAttr(default=None)

    structure_version: str = '1.1'
    calibration_type: typing.Literal['generic'] = 'generic'
    channel: RedvyprAddress = pydantic.Field(default=RedvyprAddress('@'),
                                             description='The address of calibrated channel in the datapacket',
                                             editable=True)
    channel_apply: typing.Optional[RedvyprAddress] = pydantic.Field(default=None,
                                                                    description='The address of the channel the calibration should '
                                                          'be applied to. This is optional, if the calibrated '
                                                          'channel shall be applied to a different channel. '
                                                          'If it is not set channel will be used.')
    datakey_result: typing.Optional[str] = pydantic.Field(default=None,
                                                          description='The keyname of the output of the calibration. '
                                                                      'Note that this is the basekey of the datadictionary.')
    sn: str = pydantic.Field(default='NA', description='The serial number of the sensor')
    sensor_model: str = pydantic.Field(default='NA', description='The sensor model')
    unit: str = pydantic.Field(default='NA', description='The unit of the sensor data, after the calibration was applied')
    unit_input: str = pydantic.Field(default='NA', description='The unit of the sensor raw data')
    date: datetime.datetime = pydantic.Field(default=datetime.datetime(1970,1,1,0,0,0), description='The calibration date')
    calibration_id: str = pydantic.Field(default='', description='ID of the calibration, can be chosen by the user')
    calibration_uuid: str = pydantic.Field(default_factory=get_calibration_uuid,
                                         description='uuid of the calibration, can be chosen by the user')
    comment: typing.Optional[str] = None
    calibration_data: typing.Optional[CalibrationData] = pydantic.Field(default=None)
    calibration_reference_data: typing.Optional[CalibrationData] = pydantic.Field(default=None)

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

    def calc_content_id(self) -> str:
        """
        Calculates the deterministic content ID based on the calibration data
        and sets the internal _content_id field.

        Returns: The calculated content ID string.
        """
        # 1. Prepare Data for Hashing (Normalization)
        normalized_string_bytes = self.model_dump_json(
            # Pass the exclusions directly to model_dump_json
            exclude={
                '_content_id',
                # Include 'model_uuid' here if it were still present:
                # 'model_uuid',
                # Add other non-content-defining fields here
            },
            exclude_none=True,
            # Ensure output is a byte sequence for hashing
        ).encode('utf-8')


        # 3. Hashing (SHA-256)
        hash_object = hashlib.sha256(normalized_string_bytes)
        hash_hex = hash_object.hexdigest()

        object.__setattr__(self, '_content_id', hash_hex)

        return hash_hex

    def create_redvypr_address(self) -> 'RedvyprAddress':
        try:
            caldate = self.date.isoformat()
            print("channel datakey",RedvyprAddress(self.channel).datakey)
            astr = f"@sn=='{self.sn}'"
            astr += f" and channel=='{self.channel}'"
            astr += f"and calibration_type=='{self.calibration_type}' and date==dt('{caldate}')"
            if len(self.sensor_model) > 0 and self.sensor_model != 'NA':
                astr += f" and sensor_model=='{self.sensor_model}'"
            if len(self.calibration_uuid):
                astr += f" and calibration_uuid=='{self.calibration_uuid}'"

            raddr = RedvyprAddress(astr)
        except:
            logger.warning("Could not create RedvyprAddress",exc_info=True)
            raise ValueError("Could not create RedvyprAddress")
        return raddr


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
    calibration_type: typing.Literal['polynom'] = 'polynom'
    coeff: list = pydantic.Field(default = [1.0, 0], description='The calibration polynomial. The first entry is the one with the highest exponent, the last the constant: y = coeff[-1] + x * coeff[-2] + x**2 * coeff[-3]')
    poly_degree: int = 3
    date: datetime.datetime = pydantic.Field(default=datetime.datetime(1970,1,1,0,0,0), description='The calibration date')
    calibration_id: str = pydantic.Field(default='', description='ID of the calibration, can be choosen by the user')
    calibration_uuid: str = pydantic.Field(default_factory=lambda: uuid.uuid4().hex,
                                         description='uuid of the calibration, can be choosen by the user')
    comment: typing.Optional[str] = None

    def raw2data(self, raw_data):
        print("Raw2data")
        print("raw_data", raw_data)
        print("coeff", self.coeff)
        data = np.polyval(self.coeff,raw_data)
        print("data", data)
        return data


    def calc_coeffs(self, poly_degree=None):
        """
        Polynom calibration

        Parameters
        ----------
        poly_degree

        Returns
        -------

        """
        if poly_degree is not None:
            self.poly_degree = poly_degree

        refdata = np.asarray(self.calibration_reference_data.data)
        caldata = np.asarray(self.calibration_data.data)
        fitdata = np.polyfit(caldata, refdata, self.poly_degree)
        self.coeff = fitdata.tolist()

    def get_formula(self):
        """
        Returns the formula in latex for the calculation of the converted value
        Returns
        -------

        """
        #T_1 = np.polyval(P_R, np.log(data))
        #T = 1 / T_1 - Toff
        channelname = self.channel.datakey
        calc_str = "$y = c_0 + c_1\\times \\text{{{}}} + c_2\\times \\text{{{}}}^2 ... $".format(channelname,channelname)
        #print("calc str",calc_str)
        return calc_str

# Potentially legacy
class CalibrationHeatFlow(CalibrationGeneric):
    """
    Calibration model for a heatflow sensor
    """
    calibration_type: typing.Literal['heatflow'] = 'heatflow'
    channel: str = 'HF'
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
    poly_degree: int = 3
    coeff: list = pydantic.Field(default = [np.nan, np.nan, np.nan, np.nan])
    unit: str = 'degC'
    unit_input: str = 'Ohm'

    def raw2data(self, data):
        """
        Calculate the temperature based on the calibration and a resistance using a polynome
        """
        P_R = self.coeff
        Toff = self.Toff
        T_1 = np.polyval(P_R, np.log(data))
        T = 1 / T_1 - Toff
        return T

    def calc_coeffs(self, poly_degree=None):
        """
        Hoge-type equation for NTC calibration

        Parameters
        ----------
        poly_degree

        Returns
        -------

        """
        if poly_degree is not None:
            self.poly_degree = poly_degree

        T = np.asarray(self.calibration_reference_data.data)
        R = np.asarray(self.calibration_data.data)
        Toff = self.Toff
        TK = T + Toff
        T_1 = 1 / (TK)
        # logR = log(R/R0)
        logR = np.log(R)
        P_R = np.polyfit(logR, T_1, self.poly_degree)
        self.coeff = P_R.tolist()

    def get_formula(self):
        """
        Returns the formula in latex for the calculation of the converted value
        Returns
        -------

        """
        #T_1 = np.polyval(P_R, np.log(data))
        #T = 1 / T_1 - Toff
        channelname = self.channel.datakey
        calc_str = "$T = \\left(c_0 + c_1\\times ln({}) + c_2\\times ln({})^2 ... \\right)^{{-1}} - T_{{off}}$".format(channelname,channelname)
        calc_str += "\n $T_{{off}} = {}$".format(self.Toff)
        print("calc str",calc_str)
        return calc_str

    def get_formula_explicit(self):
        """
        Returns the formula in latex for the calculation of the converted value with the coefficients inserted
        Returns
        -------

        """
        # T_1 = np.polyval(P_R, np.log(data))
        # T = 1 / T_1 - Toff

        calc_str = "$T = \\left["
        for i,c in enumerate(self.coeff[::-1]):
            cstr = "({:+e}) \\times ln(x)^{}".format(c,i)
            calc_str += cstr
        calc_str += "\\right]^{{-1}} - {}$".format(self.Toff)


        return calc_str

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
        self.calfiles_processed = []

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
                calibrations = self.read_calibration_file(fname)
                if calibrations is not None:
                    for calibration in calibrations:
                        flag_add = self.add_calibration(calibration)
                        if flag_add:
                            self.calfiles_processed.append(fname)
            else:
                logger.debug(funcname + ' file {:s} already processed'.format(fname))

        # Remove double entries
        self.calfiles_processed = list(set(self.calfiles_processed))
        # print(self.calibration['sn'].keys())
        # self.logger_autocalibration()

    def add_calibration(self, calibration):
        """
        Adds a calibration to the calibration list, checking for duplicates using
        the deterministic _content_id for high-speed uniqueness verification.

        calibration: calibration model (must have the .calc_content_id() method).
        """

        # 1. Calculate the deterministic Content ID for the new object
        # This also sets the _content_id field within the 'calibration' object itself.
        try:
            new_content_id = calibration.calc_content_id()
        except AttributeError:
            # Fallback if calc_content_id is missing, though this shouldn't happen
            # if the CalibrationGeneric model is correctly implemented.
            logger.error(
                "Incoming calibration object is missing the required .calc_content_id() method.")
            return False

        # 2. Iterate through the list and compare only the Content IDs
        for cal_old in self:
            # IMPORTANT: The _content_id of the existing object MUST have been
            # set previously (e.g., during list loading).
            old_content_id = getattr(cal_old, '_content_id', None)

            if old_content_id is None:
                # This indicates a historical issue: the object was added before
                # the content ID logic was implemented. You may need a fallback
                # to calculate it here if necessary, but it slows things down.
                logger.warning(
                    "Existing calibration object is missing _content_id. Skipping check for this item.")
                continue

            if new_content_id == old_content_id:
                logger.warning(
                    f'Calibration content already exists (ID: {new_content_id})')
                return False  # Duplicate found, exit immediately

        # 3. Append the new object, as no duplicate content was found.
        # The _content_id and model_uuid are already set on the 'calibration' object.
        self.append(calibration)
        # logger.debug(f'New calibration added (ID: {new_content_id})')
        return True

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

            data = f.read()
            calibrations_raw = []
            for databs in data.split('...\n'):  # Split the text into single subpackets
                try:
                    #data = yaml.safe_load(databs)
                    data_yaml = yaml.load(databs, Loader=loader)
                    if (data_yaml is not None):
                        calibrations_raw.append(data_yaml)

                except Exception as e:
                    logger.debug(funcname + ': Could not decode message {:s}'.format(str(databs)))
                    data_yaml = None

            # print('data',data)
            calibrations = []
            for data in calibrations_raw:
                if 'structure_version' in data.keys():  # Calibration model
                    #logger.debug(funcname + ' Version {} pydantic calibration model dump'.format(data['structure_version']))
                    for calmodel in calibration_models:  # Loop over all calibration models definded in sensor_calibrations.py
                        try:
                            calibration = calmodel.model_validate(data)
                            calibrations.append(calibration)
                        except:
                            pass

            return calibrations

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
            for cal_old in self:
                # Test if the calibration is existing
                if calibration_json == json.dumps(cal_old.model_dump_json()):
                    logger.debug(funcname + ' Removing calibration')
                    self.calibration_files.remove(calfile)
                    self.remove(cal_old)
                    self.calfiles_processed.remove(calfile)
                    return True

    def create_filenames_save(self, calfile, datefmt='%Y%m%d_%H%M%S', document_type="calibration"):
        """
        Returns the filenames for all calibrations
        Can be modified by format: {sn}, {date}, {sensor_model}, {calibration_id}, {calibration_uuid}, {calibration_type}

        Parameters
        ----------
        calfile
        datefmt

        Returns
        -------

        """

        funcname = __name__ + '.save():'
        logger.debug(funcname)
        calfiles = []
        calfile_mod = calfile
        for calibration in self:
            logger.debug(funcname + ' Sorting calibrations')
            if calibration is None:
                calfiles.append(None)
            else:
                datestr = calibration.date.strftime(datefmt)
                calfile_name = calfile_mod.format(sn=calibration.sn, date=datestr, sensor_model=calibration.sensor_model,
                                                  calibration_id=calibration.calibration_id,
                                                  document_type=document_type,
                                                  calibration_uuid=calibration.calibration_uuid,
                                                  calibration_type=calibration.calibration_type)

                calfiles.append(calfile_name)

        return calfiles

    def save_report(self, calfiles, report_function):
        funcname = __name__ + '.save_report():'
        logger.debug(funcname)
        calfiles_write = {}
        # Sort the calibrations into file with the same name
        for i,calfile in enumerate(calfiles):
            if calfile is not None:
                try:
                    calfiles_write[calfile]
                except:
                    calfiles_write[calfile] = []

                calfiles_write[calfile].append(self[i])

        for calfile in calfiles_write:
            logger.debug('Writing report to file {}'.format(calfile))
            calibrations_write = calfiles_write[calfile]
            # Call the report function with the calibration and the filename
            report_function(calibrations_write, calfile)

        return calfiles

    def save(self, calfiles):
        """
        Saves the calibrations to the files given in the calfiles list. If the same name is given, the calibration data
        is appended.

        Parameters
        ----------
        calfiles: List of the filenames, length of the list has to be same as the number calibrations (including None)

        Returns
        -------

        """

        funcname = __name__ + '.save():'
        logger.debug(funcname)
        if True:
            logger.debug(funcname + ' Writing calibrations')
            # First empty all files
            for calfile_write in calfiles:
                if calfile_write is not None:
                    open(calfile_write, 'w').close()

            for i,calibration in enumerate(self):
                calfile_write = calfiles[i]
                #print("Saving calibration",calibration)
                #print("To files",calfile_write)
                if calibration is None:
                    logger.info("Will not save entry {}".format(i))
                else:

                    logger.debug('Writing to file {}'.format(calfile_write))
                    f = open(calfile_write, 'a')
                    #print("Data save",calibration.model_dump())
                    calibration_yaml = yaml.dump(calibration.model_dump(), explicit_end=True, explicit_start=True, sort_keys=False)
                    f.write(calibration_yaml)
                    # print('Calibration dump ...', calibration_yaml)
                    f.close()

        return calfiles


CalibrationModel = typing.Annotated[
    typing.Union[CalibrationLinearFactor, CalibrationPoly, CalibrationNTC, CalibrationGeneric],
    pydantic.Field(discriminator='calibration_type')
]
class CalibrationWrapper(pydantic.RootModel):
    """
    This class acts as a wrapper to apply Pydantic's validation methods
    (like model_validate_json) to the CalibrationModel Union type.
    """
    root: CalibrationModel



