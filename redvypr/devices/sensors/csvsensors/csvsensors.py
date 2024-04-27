import datetime
import numpy as np
import logging
import sys
import threading
import copy
import yaml
import json
import typing
import pydantic
from PyQt5 import QtWidgets, QtCore, QtGui
from redvypr.device import redvypr_device
from redvypr.data_packets import check_for_command
#from redvypr.packet_statistics import get_keys_from_data
#import redvypr.packet_statistic as redvypr_packet_statistic
import redvypr.data_packets as data_packets
import redvypr.gui as gui
#import redvypr.config as redvypr_config
from redvypr.redvypr_address import redvypr_address
from redvypr.devices.plot import plot_widgets
from redvypr.devices.plot import XYplotWidget
import redvypr.files as redvypr_files
from redvypr.devices.sensors.calibration.calibration_models import  calibration_HF, calibration_NTC, get_date_from_calibration
from .heatflow_sensors import convert_HF, parse_HF_raw, add_keyinfo_HF_raw, parse_HFV_raw, process_IMU_packet, process_HFS_data, process_HF_data
from .temperature_array_sensors import process_TAR_data, sensor_TAR, TARWidget, TARWidget_config
from .sensorWidgets import sensorCoeffWidget

_icon_file = redvypr_files.icon_file

redvypr_devicemodule = True


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('csvsensors')
logger.setLevel(logging.DEBUG)


class device_base_config(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Processing of temperature and heatflow sensordata'


class parameter_DHFS50(pydantic.BaseModel):
    HF: calibration_HF = calibration_HF(parameter='HF')
    NTC0: calibration_NTC = calibration_NTC(parameter='NTC0')
    NTC1: calibration_NTC = calibration_NTC(parameter='NTC1')
    NTC2: calibration_NTC = calibration_NTC(parameter='NTC2')

class logger_DHFS50(pydantic.BaseModel):
    description: str = 'Digital heat flow sensor DHFS50'
    sensor_id: typing.Literal['DHFS50'] = 'DHFS50'
    logger_model: str = 'DHFS50'
    logger_configuration: str = 'DHFS50-1m'
    parameter: parameter_DHFS50 = parameter_DHFS50()
    sn: str = pydantic.Field(default='', description='The serial number and/or MAC address of the sensor')
    comment: str = pydantic.Field(default='')
    use_config: bool = pydantic.Field(default=False, description='Use the configuration (True)')
    avg_data: list = pydantic.Field(default=[60, 300], description='List of averaging intervals')

class channels_HFV4CH(pydantic.BaseModel):
    C0: calibration_HF = calibration_HF(parameter='C0')
    C1: calibration_HF = calibration_HF(parameter='C1')
    C2: calibration_HF = calibration_HF(parameter='C2')
    C3: calibration_HF = calibration_HF(parameter='C3')

class logger_HFV4CH(pydantic.BaseModel):
    description: str = '4 Channel voltage logger'
    sensor_id: typing.Literal['hfv4ch'] = 'hfv4ch'
    logger_model: str = '4 Channel ADS logger'
    logger_configuration: str = 'Raspberry PI board'
    channels: channels_HFV4CH = channels_HFV4CH()
    sn: str = pydantic.Field(default='', description='The serial number and/or MAC address of the sensor')
    comment: str = pydantic.Field(default='')

class device_config(pydantic.BaseModel):
    sensorconfigurations: typing.Dict[str,typing.Annotated[typing.Union[logger_DHFS50,logger_HFV4CH, sensor_TAR], pydantic.Field(discriminator='sensor_id')]] = pydantic.Field(default={},description='Configuration of sensors, keys are their serial numbers')
    calibrations: typing.List[typing.Annotated[typing.Union[calibration_NTC, calibration_HF], pydantic.Field(discriminator='calibration_type')]] = pydantic.Field(default=[], description = 'List of sensor calibrations')
    calibration_files: list = pydantic.Field(default=[])
    datakeys: list =  pydantic.Field(default = ['data'], description = 'The datakeys to be looked for csv data')






packettypes = ['HF','HFS','HFV','IMU','TAR'] # This should be specified within the logger templates, work for later


def start(device_info, config = None, dataqueue = None, datainqueue = None, statusqueue = None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    config = device_config.model_validate(config)
    macs_found_HF = []  # List of all mac addresses found
    macs_found_HFSI = []  # List of all mac addresses found
    macs_found_IMU = []  # List of all mac addresses found
    macs_found = {'IMU':[],'HFSI':[],'HF':[],'TAR':[]}  # List of all mac addresses found
    avg_objs = {}
    print('Device info',device_info)
    #try:
    #    calfile = open(config['calibration_file'],'r')
    #    calibrations = yaml.safe_load(calfile)
    #except Exception as e:
    #    calibrations = None
    #    logger.exception(e)

    try:
        sensorconfigurations = config.sensorconfigurations
    except Exception as e:
        sensorconfigurations = None
        logger.exception(e)

    print('Logger configurations',sensorconfigurations)
    i = 0
    while True:
        data = datainqueue.get(block = True)
        if data is not None:
            #print('Got data',data)
            command = check_for_command(data,thread_uuid=device_info['thread_uuid'])
            #print('Got command',command, data)
            if (command == 'stop'):
                logger.debug('Command is for me: {:s}'.format(str(command)))
                statusqueue.put('stop')
                break
            elif (command == 'sensorconfigurations'):
                #config['sensorconfigurations'] = data['sensorconfigurations']
                logger.debug(funcname + ' sensorconfigurations updated (sensorconfigurations)')
            elif (command == 'config'):
                config = device_config.model_validate(data['config'])
                logger.debug(funcname + ' sensorconfigurations updated (config)')


            #print('Got data',i,data)
            for datakey in config.datakeys:
                try:
                    hfdata = data[datakey]
                    break
                except:
                    hfdata = None
                    pass

            if hfdata is not None:
                if type(hfdata) == bytes:
                    try:
                        hfdatastr = hfdata.decode('utf-8')
                    except:
                        hfdatastr = 'X'
                elif type(hfdata) == str:
                    hfdatastr = hfdata
                else:
                    hfdatastr = 'X'
                        

                # Loop over all lines and check if we have a $ as start
                for dataline in hfdatastr.split('\n'):
                    valid_package = False
                    if len(dataline) > 0:
                        if dataline[0] == "$":
                            datasplit = dataline.split(',')
                            if len(datasplit) > 2:
                                sn = datasplit[0][1:]
                                # Check for a valid mac
                                try:
                                    macstr = datasplit[0][1:17]
                                    macint = int(macstr,16)
                                    logger.debug(funcname + 'Valid MAC: {:s}'.format(str(hex(macint))))
                                except:
                                    macint = None
                                    macstr = None
                                    logger.debug(funcname + 'Not valid MAC', exc_info = True)

                                packettype = datasplit[1]
                                #datapacket = None
                                #datapacket_HFSI = None
                                # Try to parse datapackets
                                print('Packettype',packettype)
                                if macstr is not None:
                                    # Check if the logger is already existing
                                    try:
                                        loggerconfig = config.sensorconfigurations[sn]
                                    except:
                                        logger.debug(funcname + ' New sensor', exc_info=True)
                                        statusmessage = {'status': 'newlogger', 'sn': sn, 'packettype': packettype,'dataline':dataline,'data':data}
                                        statusqueue.put(statusmessage)
                                        #print('new logger statusmessage', statusmessage)
                                        loggerconfig = None

                                    if packettype == 'IMU':
                                        try:
                                            datapacket = process_IMU_packet(dataline, data, macstr, macs_found)
                                            dataqueue.put(datapacket)
                                        except:
                                            logger.debug(' Could not decode {:s}'.format(str(dataline)), exc_info=True)
                                            datapacket = None

                                    elif packettype == 'TAR':
                                        #print('Parsing TAR')
                                        try:
                                            datapackets_TAR = process_TAR_data(dataline, data, device_info, loggerconfig)
                                        except:
                                            logger.info(' Could not process data {:s}'.format(str(dataline)), exc_info=True)
                                            datapackets_TAR = []

                                        for datapacket_TAR in datapackets_TAR:
                                            dataqueue.put(datapacket_TAR)

                                    elif packettype == 'HFS':
                                        # Heatflow data in physical units
                                        try:
                                            datapacket_HFS = process_HFS_data(dataline, data, device_info)
                                            dataqueue.put(datapacket_HFS)
                                        except:
                                            logger.debug(' Could not decode {:s}'.format(str(dataline)), exc_info=True)
                                            datapacket_HFS = None

                                    elif packettype == 'HF':
                                        # Heatflow data in raw units
                                        print('HF packet')
                                        try:
                                            datapacket_HF = process_HF_data(dataline, data, device_info, loggerconfig, config, macs_found)
                                            if datapacket_HF is not None:
                                                dataqueue.put(datapacket_HF)
                                        except:
                                            logger.debug(' Could not decode {:s}'.format(str(dataline)), exc_info=True)
                                            datapacket_HF = None

                                    elif packettype == 'HFV': # Voltage packet from a raspberry pi board
                                        #print('HFV')
                                        try:
                                            datapacket = parse_HFV_raw(dataline)
                                            #datapacket['t'] = data['t']
                                            datapacket['devicename'] = 'HFV_raw_' + sn
                                            # Check if there is a conversion to be done
                                            #datapacket_HFVSI = convert_HF(datapacket, calibrations)
                                            #datapacket_HFVSI['devicename'] = 'HFV_SI_' + sn
                                            #print('HALLO',config['sensorconfigurations'][sn]['channels'].keys())
                                            # Check if the logger is already existing
                                            try:
                                                config.sensorconfigurations[sn]
                                                flag_convert = True
                                            except:
                                                logger.debug(funcname + ' New logger.',exc_info=True)
                                                statusqueue.put({'status':'newlogger','sn':sn,'packettype':'HFV'})
                                                #print('datapacket',datapacket)
                                                flag_convert = False

                                            if flag_convert:
                                                flag_have_coeff = False
                                                #print('Converting data')
                                                try:
                                                    datapacket_HFSI = {'devicename':'HFV_SI_' + sn}
                                                    datapacket_HFSI['sn'] = datapacket['sn']
                                                    datapacket_HFSI['t'] = datapacket['t']
                                                    for channelconfig in config.sensorconfigurations[sn].channels:
                                                        channel = channelconfig[0]
                                                        calibration = channelconfig[1]
                                                        sn_sensor = calibration.sn
                                                        coeff = calibration.coeff
                                                        #print('Channelconfig', channelconfig, sn_sensor, coeff)
                                                        if len(sn_sensor) > 0:
                                                            #print('sensor',sn_sensor)
                                                            # This needs to be done more general ... checking units etc.
                                                            data_conv = datapacket[channel] * coeff * 1000
                                                            datapacket_HFSI[channel] = data_conv
                                                            datapacket_HFSI['type'] = 'HFVSI'
                                                            flag_have_coeff = True
                                                            # create a sn out of the logger and the attached sensor
                                                            sn_combined = datapacket_HFSI['sn'] + '_' + sn_sensor
                                                            # Check if the logger/sensor combinationis already known, otherwise send keyinfo
                                                            if sn_combined in macs_found['HFSI']:
                                                                pass
                                                            else:
                                                                logger.debug(
                                                                    'New HFV logger {:s}'.format(datapacket_HFSI['sn']))
                                                                macs_found_HFSI.append(datapacket_HFSI['sn'])
                                                                data_packets.add_keyinfo2datapacket(datapacket_HFSI,
                                                                                                    datakey=channel,
                                                                                                    unit='W m-2',
                                                                                                    description=None,
                                                                                                    infokey='sn',
                                                                                                    info=sn_sensor)
                                                                data_packets.add_keyinfo2datapacket(datapacket_HFSI,
                                                                                                    datakey=channel,
                                                                                                    infokey='sensortype',
                                                                                                    info=calibration.sensor_model)

                                                                macs_found['HFSI'].append(sn_combined)


                                                    if flag_have_coeff == False:
                                                        datapacket_HFSI = None


                                                except Exception as e:
                                                    coeff = None
                                                    logger.debug('Conversion error',exc_info=True)

                                        except Exception as e:
                                            logger.debug(' Could not decode {:s}'.format(str(dataline)))
                                            datapacket = None

                                        # print('HF packet',datapacket)
                                else:
                                    logger.debug(funcname + 'unknown packettype {:s}'.format(packettype))

                                #if datapacket is not None:
                                #    devicename = datapacket.pop('devicename')
                                #    datapacket_redvypr = data_packets.datapacket(device = devicename, tu = data['_redvypr']['t'], hostinfo=device_info['hostinfo'])
                                #    datapacket_redvypr.update(datapacket)
                                #    dataqueue.put(datapacket_redvypr)

                                #if datapacket_HFSI is not None:
                                #    #print('Hallo HFSI',datapacket_HFSI)
                                #    devicename = datapacket_HFSI.pop('devicename')
                                #    datapacket_redvypr = data_packets.datapacket(device=devicename, tu = data['_redvypr']['t'],
                                #                                                 hostinfo=device_info['hostinfo'])
                                #    datapacket_redvypr.update(datapacket_HFSI)
                                #    # datapacket['_redvypr']['device']
                                #    #print('Sensing datapacket SI ....',datapacket_redvypr)
                                #    dataqueue.put(datapacket_redvypr)


class Device(redvypr_device):
    """
    heatflow_serial device
    """
    newlogger_signal = QtCore.pyqtSignal(dict)  # Signal with the new logger
    newcalibration_signal = QtCore.pyqtSignal()  # Signal for a new calibration
    newloggerconfig_signal = QtCore.pyqtSignal(dict)  # Signal when a new loggerconfiguration was applied
    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)
        logger.debug(funcname)
        #configtest = redvypr_config.dict_to_configDict(sensorconfig)
        #self.config['sensorconfigurations'][configtest['sn']] = configtest
        #for i,s in enumerate(self.config['sensors'].data):
        #    print('Subscribing to sensor',s)
        #    self.config['datastreams'].data.Device(append(redvypr.config.configString(''))
        #    self.subscribe_address(s)
        self.nosensorname = '<no sensor>'
        try:
            self.config.calibrations[0]
        except:
            logger.debug(funcname + ' Will add <no sensor>')
            nosensor = calibration_HF()
            nosensor.sn = self.nosensorname
            #print('nosensorconfig',nosensorconfig)
            self.config.calibrations.append(nosensor)
        # Sensordata
        self.sensordata_raw = {} # The datapackets
        self.sensordata = {} # The data by mac/parameter
        self.calfiles_processed = []
        # Check if there are already calibrations saved, and if yes, add the original files as read
        # Here a md5sum check could be done
        #for sn in self.config['calibrations'].keys():
        #    for cal in self.config['calibrations'][sn]:
        #        fname = cal['original_file']
        #        self.calfiles_processed.append(fname)

        self.populate_calibration()



    def logger_autocalibration(self):
        """
        Searches self.config.calibrations for calibration of loggers that can be autocalibrated,
        if loggers are found they are added to self.config.sensorconfigurations

        """
        funcname = __name__ + '.logger_autocalibration():'
        logger.debug(funcname)
        # Find calibrations for loggers
        loggers_autocal = ['DHFS50']
        # sn of the logger and the calibrations are the same for autocalibration
        for calibration in self.config.calibrations:
            sn = calibration.sn
            if True:
                try:
                    sensor_model = calibration.sensor_model
                except:
                    sensor_model = None

                # Check if we can automatically find calibrations for the logger
                if sensor_model in loggers_autocal:
                    #print('Got calibration coefficients',sn)
                    latest = self.get_latest_callibration_coeffs(sn)
                    #print('Got calibration coefficients')
                    #print('latest',latest)

                    if latest is not None:
                        ret = self.add_sensorconfig(sn, sensor_model)
                        #print('Add loggerconfig', ret)
                        #print('latest',latest,latest.keys())
                        for parameter in latest.keys():
                            logger.debug(funcname + ' updating {:s}'.format(parameter))
                            self.config.sensorconfigurations[sn]['parameter'][parameter] = latest[parameter]

                        if ret == True:
                            #print('Newlogger')
                            status = {}
                            self.newlogger_signal.emit(status)
                        else:
                            status = {}
                            self.newloggerconfig_signal.emit(status)
    def add_calibration_file(self, calfile, reload=True):
        funcname = __name__ + 'add_calibration_file():'
        logger.debug(funcname)
        calfiles_tmp = list(self.config.calibration_files)
        if (calfile in calfiles_tmp) and reload:
            #print('Removing file first')
            self.rem_calibration_file(calfile)

        calfiles_tmp = list(self.config.calibration_files)
        #print('Hallo',calfiles_tmp)
        if calfile not in calfiles_tmp:
            #print('Adding file 2',calfile)
            self.config.calibration_files.append(calfile)
        else:
            logger.debug(funcname + ' File is already listed')

        self.populate_calibration()

    def rem_calibration_file(self, calfile):
        funcname = __name__ + 'rem_calibration_file():'
        logger.debug(funcname)
        calfiles_tmp = list(self.config.calibration_files)
        if calfile in calfiles_tmp:
            calibration = self.read_calibration_file(calfile)
            calibration_json = json.dumps(calibration.model_dump())
            for cal_old in self.config.calibrations:
                # Test if the calibration is existing
                if calibration_json == json.dumps(cal_old.model_dump()):
                    logger.debug(funcname + ' Removing calibration')
                    self.config.calibration_files.remove(calfile)
                    self.config.calibrations.remove(cal_old)
                    self.calfiles_processed.remove(calfile)
                    return True

    def populate_calibration(self):
        funcname = __name__ + '.populate_calibration()'
        logger.debug(funcname)
        self.calibration = {'sn': {}}
        fnames = []
        #if False:
        #    globstr = str(self.config['calibration_folder']) + '/*.yaml'
        #    for fname in glob.glob(globstr):
        #        fnames.append(fname)

        for fname in self.config.calibration_files:
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


        #print(self.calibration['sn'].keys())
        self.logger_autocalibration()

    def add_calibration(self, calibration):
        """
        Adds a calibration to the calibration list, checks before, if the calibration exists
        calibration: calibration model
        """
        flag_new_calibration = True
        calibration_json = json.dumps(calibration.model_dump())
        for cal_old in self.config.calibrations:
            if calibration_json == json.dumps(cal_old.model_dump()):
                flag_new_calibration = False
                break

        if flag_new_calibration:
            print('Sending new calibration signal')
            self.config.calibrations.append(calibration)
            self.newcalibration_signal.emit()
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
            data = yaml.safe_load(f)
            # print('data',data)
            if 'structure_version' in data.keys(): # Calibration model
                logger.debug(funcname + ' Version {} pydantic calibration model dump'.format(data['structure_version']))
                calmodels = [calibration_HF, calibration_NTC]
                for calmodel in calmodels:
                    try:
                        calibration = calmodel.model_validate(data)
                        print('Calibration', calibration)
                        return calibration
                    except:
                        pass

            elif 'sn' in data.keys():
                calibration = {}
                calibration['sn'] = {}
                logger.debug(funcname + ' Version 2 file')
                for sn in data['sn'].keys():  # Add the filename the data was loaded from
                    try:
                        calibration['sn'][sn]
                    except:
                        calibration['sn'][sn] = {}
                        #calibration['sn'][sn]['coeff_files'] = []

                    #calibration['sn'][sn]['coeff_files'].append(fname)
                    calibration['sn'][sn].update(data['sn'][sn])
                    calibration['sn'][sn]['original_file'] = fname
                #    data['sn'][sn].filenames = []
                #    data['sn'][sn].filenames.append(fname)
                # self.calibration['sn'].update(data['sn'])
                return calibration

            elif 'calibration_HF_SI' in data.keys(): # Version 1 file
                logger.debug(funcname + ' Version 1 file')

                sn = data['manufacturer_sn']
                if len(sn) ==0:
                    logger.debug(funcname + ' No serial number')
                else:
                    calibration = calibration_HF(sn=sn,coeff=data['calibration_HF_SI'],date=data['calibration_date'],sensor_model = data['series'])
                    #sn:
                    #    "9299":
                    #    model: F - 005 - 4
                    #    coeffs:
                    #        HF:
                    #        coeff: 8.98
                    #        parameter: HF
                    #        unit: W m-2
                    #        unitraw: mV
                    #        date: 1970 - 01 - 01_00 - 00 - 00
                    return calibration
                    if False:
                        calibration['sn'][sn] = {}
                        calibration['sn'][sn]['model'] = data['series']
                        calibration['sn'][sn]['original_file'] = fname
                        calibration['sn'][sn]['sn'] = sn
                        calibration['sn'][sn]['parameter'] = {}
                        calibration['sn'][sn]['parameter']['HF'] = {}
                        calibration['sn'][sn]['parameter']['HF']['coeff'] = data['calibration_HF_SI']
                        calibration['sn'][sn]['parameter']['HF']['unit'] = 'W m-2'
                        calibration['sn'][sn]['parameter']['HF']['unitraw'] = 'mW'
                        calibration['sn'][sn]['parameter']['HF']['date'] = data['calibration_date']

        except Exception as e:
            logger.exception(e)
            return None




    def get_latest_callibration_coeffs(self, sn):
        """
        Function is searching for the latest calibration
        """
        funcname = __name__ + '.get_latest_callibration_coeffs():'
        try:
            self.config.calibrations[sn]
        except Exception as e:
            logger.warning('sn not found')
            return None

        parameters = {}
        parameters_latest = {}
        # Find all calibrations for sn
        calibrations_sn = []
        for calibration in self.config.calibrations:
            if calibration.sn == sn:
                calibrations_sn.append(calibration)

        for calibration in calibrations_sn:
            if True:
                parameter = calibration.parameter
                try:
                    parameters[parameter]
                except:
                    parameters[parameter] = None
                    parameters_latest[parameter] = datetime.datetime(1,1,1,0,0,0)

                td = get_date_from_calibration(calibration,parameter)
                coeff = calibration['parameter'][parameter]
                #print('Got date',td)
                # Get the latest one here
                if parameters_latest[parameter] < td:
                    logger.debug(funcname + 'Found more recent coefficient for parameter {:s}'.format(parameter))
                    parameters[parameter] = coeff
                    parameters_latest[parameter] = td

        # Setting the parameters
        logger.debug(funcname + ' Setting the coefficient')

        #for parameter in parameters:
        #    self.config['calibrations'][sn]['used'][parameter] = parameters[parameter]

        return parameters

    def read_calibration_v02(self):
        """
        Reads calibration files of version 2. Written by the heatflow_calibration redvypr device
        """
        pass
    def read_calibration_v01(self):
        """
        Reads calibration files of version 1. Written by the calibration program
        """
        pass

    def thread_start(self):
        config = copy.deepcopy(self.config)
        #config['calibration'] = self.calibration
        self.statusqueue_thread = threading.Thread(target=self.read_statusqueue, daemon=True)
        self.statusqueue_thread.start()
        super(Device, self).thread_start(config=config)


    def add_sensorconfig(self, sn, sensor_id, config = None, address=None):
        """

        """
        funcname = __name__ + '.add_sensorconfig():'
        logger.debug(funcname)
        try:
            sensor_new = sn not in self.config.sensorconfigurations.keys()
            if sensor_new:
                logger.debug(funcname + 'Adding new sensor of type {:s} with sn {:s}'.format(sensor_id, sn))
                if sensor_id.lower() == 'hfv4ch':
                    sensor_config = logger_HFV4CH()
                    sensor_config.sn = sn
                    self.config.sensorconfigurations[sn] = sensor_config
                    return True
                elif sensor_id.lower() == 'dhfs50':
                    sensor_config = logger_DHFS50()
                    sensor_config.sn = sn
                    self.config.sensorconfigurations[sn] = sensor_config
                    return True
                elif sensor_id.lower() == 'tar':
                    # Add a temperature array logger
                    sensor_config = sensor_TAR()
                    sensor_config.init_from_data(config)
                    self.config.sensorconfigurations[sn] = sensor_config
                    return True
                else:
                    return None
            else:
                logger.debug(funcname + ' Configuration for {:s} is already existing'.format(sn))
                return False
        except:
            logger.warning(funcname + 'Could not add new sensor:',exc_info=True)




    def read_statusqueue(self):
        """
        Functions reads statusqueue
        """
        funcname = __name__ + '.read_statusqueue():'
        logger.debug(funcname)
        while True:
            status = self.statusqueue.get()
            logger.debug('Got status {:s}'.format(str(status)))
            if status == 'stop':
                #print('stopping')
                logger.debug(funcname + ' Stopping')
                return
            elif type(status) == dict:
                if status['status'] == 'newlogger':
                    logger.debug('New Sensor')
                    newsensor_address = redvypr_address(status['data'])
                    if status['packettype'] == 'HFV':
                        logger.info('New 4Channel logger')
                        sn = status['sn']
                        ret = self.add_sensorconfig(sn, sensor_id ='hfv4ch', address=newsensor_address)
                        if ret is not None:
                            config = self.config.model_dump()
                            print('config for new logger',config)
                            self.thread_command('config',data={'config':config})
                            self.newlogger_signal.emit(status)
                    elif status['packettype'] == 'TAR':
                        logger.info('New Temperature array')
                        sn = status['sn']
                        dataline = status['dataline']
                        ret = self.add_sensorconfig(sn, sensor_id='tar', config=dataline, address=newsensor_address)
                        if ret is not None:
                            config = self.config.model_dump()
                            # print('config',config)
                            self.thread_command('config', data={'config': config})
                            self.newlogger_signal.emit(status)
                    elif status['packettype'] == 'HF':
                        logger.info('New DHFS50')
                        sn = status['sn']
                        ret = self.add_sensorconfig(sn, sensor_id ='dhfs50')
                        if ret is not None:
                            config = self.config.model_dump()
                            # print('config',config)
                            self.thread_command('config', data={'config': config})
                            self.newlogger_signal.emit(status)
                        #try:
                        #    self.deviceinitwidget.__update_configLoggerList__()
                        #except Exception as e:
                        #    logger.exception(e)
                    else:
                        logger.warning('Unknown packet type')



def find_calibration_for_logger(sn, calibration, caltype = 'latest'):
    """

    """
    pass






#
#
# Here the widgets start
#
#
class DHFS50Widget_config(QtWidgets.QWidget):
    """
    Widget to configure a DHFS50 logger
    """

    def __init__(self, *args, sn=None, redvypr_device=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        self.device = redvypr_device
        self.nosensorstr = ''
        self.sn = sn
        # Try to find a configuration for the logger
        try:
            self.device.config.sensorconfigurations[self.sn]
            logger.debug(funcname + ' Found a configuration')
        except:
            logger.warning(funcname + ' Did not find a configuration')
            return

        self.layout = QtWidgets.QGridLayout(self)
        self.coeffInput = []
        self.coeff_widget = QtWidgets.QTabWidget()
        print('Configuration',self.device.config.sensorconfigurations[self.sn])
        snlabel = QtWidgets.QLabel('DHFS50 calibration coefficients of\n' + self.sn)
        self.layout.addWidget(snlabel,0,0)

        nparameter = len(list(self.device.config.sensorconfigurations[self.sn].parameter))

        #self.coeff_table = QtWidgets.QTableWidget()
        #self.coeff_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.layout.addWidget(self.coeff_widget, 2, 0)

        self.parameter_buttons = {}
        self.parameter_widgets = {}
        self.parameter_calwidgets = {}
        for i,k_tmp in enumerate(self.device.config.sensorconfigurations[self.sn].parameter):
            k = k_tmp[0]
            calibration = k_tmp[1]
            self.parameter_widgets[k] = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(self.parameter_widgets[k])
            self.parameter_buttons[k] = QtWidgets.QPushButton('Choose calibration')
            self.parameter_buttons[k].clicked.connect(self.choose_calibration)
            self.parameter_buttons[k].parameter = k
            layout.addWidget(self.parameter_buttons[k])
            calwidget = gui.pydanticQTreeWidget(calibration,dataname = k)
            self.parameter_calwidgets[k] = calwidget
            layout.addWidget(calwidget)
            self.coeff_widget.addTab(self.parameter_widgets[k], k)
            #self.layout.addWidget(self.parameter_buttons[k], 1, i+0)

        #self.fill_coeff_table()

    def choose_calibration(self):
        """
        Let the user choose a calibration for the parameter
        """
        but = self.sender()

        funcname = __name__ + '.choose_calibration():'
        logger.debug(funcname)
        self._sensor_choose_dialog = sensorCoeffWidget(redvypr_device=self.device)
        self._sensor_choose_dialog.coeff.connect(self.calibration_chosen)
        self._sensor_choose_dialog.parameter = self.sender().parameter
        self._sensor_choose_dialog.show()

    def calibration_chosen(self, calibration_sent):
        funcname = __name__ + '.calibration_chosen():'
        logger.debug(funcname)
        #print('Coeff sent',calibration_sent)
        calibration_new = calibration_sent['calibration']
        # Use only the chosen parameter, remove the rest
        parameter = self.sender().parameter
        # print('Coeff',coeff,'sn',sn,'channel',channel)
        ## Make a test configuration for KAL1
        # channelconfig = redvypr_config.configuration(calibration_template_channel)
        # channelconfig['sn'] = self.nosensorstr  # The serialnumber of the channel
        if True:
            logger.debug('Adding {} to channel {:s}'.format(calibration_sent, parameter))
            #channels = self.device.config.sensorconfigurations[self.sn].channels
            #setattr(channels, channelname, calibration)
            calibration_old = self.device.config.sensorconfigurations[self.sn].parameter
            print('calibration_old', type(calibration_old))
            print('calibration_new', type(calibration_sent))
            print('hallohallo',calibration_old.model_validate(calibration_new))
            # Check if the new coefficients fit
            try:
                calibration_old.model_validate(calibration_new)
                setattr(self.device.config.sensorconfigurations[self.sn].parameter, parameter, calibration_new)
                self.parameter_calwidgets[parameter].reload_data(calibration_new)
            except:
                logger.debug('Calibration format does not fit',exc_info = True)



        #self.fill_coeff_table()
        print('configuration',self.device.config.sensorconfigurations[self.sn])


#
#
#
#
#
class HFVWidget_config(QtWidgets.QWidget):
    """
    Widget to display information from a 4 Channel Voltage board
    """

    def __init__(self, *args, sn=None, redvypr_device=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        self.device = redvypr_device
        self.nosensorstr = ''
        self.sn = sn

        # Get the channel names
        ch_tmp = channels_HFV4CH()
        self.channelnames = []
        for i, ch in enumerate(ch_tmp):
            print(ch)
            self.channelnames.append(ch[0])

        print('Channelsnames',self.channelnames)

        # Try to find a configuration for the logger
        try:
            self.device.config.sensorconfigurations[self.sn]
            logger.debug(funcname + ' Found a configuration')
        except:
            logger.warning(funcname + ' Did not find a configuration')
            return

        self.layout = QtWidgets.QGridLayout(self)
        self.coeffInput = []
        self.coeff_widget = QtWidgets.QWidget()
        self.create_coeff_widget()
        self.layout.addWidget(self.coeff_widget, 0, 0, 1, 2)


    def create_coeff_widget(self):
        """

        """
        # Coeffs
        # Serialnum
        # Sensortype
        # Comment
        # Show converted data

        self.coeff_layout = QtWidgets.QGridLayout(self.coeff_widget)
        self.use_coeff_checks = []
        self.serialnum_texts = []
        self.comment_texts = []
        self.sensor_choose_buttons = []

        # Get the channel names
        for i,chname in enumerate(self.channelnames):
            but = QtWidgets.QPushButton('Sensor {:s}'.format(chname))
            but.clicked.connect(self.choose_sensor)
            self.sensor_choose_buttons.append(but)
            self.coeff_layout.addWidget(but,0,i)
            but.channelname  = chname
            but.channelindex = i

        row = 0
        col = 0
        self.coeff_table = QtWidgets.QTableWidget()
        self.coeff_layout.addWidget(self.coeff_table, 1, 0,1,4)

        self.index_serialnum = 0
        self.index_coeff = 2
        self.index_model = 1
        self.index_date = 3
        self.index_fname = 4

        # Fill table with configuration data
        #addresses = ["<broadcast>", "<IP>", myip]
        #completer = QtWidgets.QCompleter(addresses)
        #self.addressline.setCompleter(completer)
        self.fill_coeff_table()

    def sensor_chosen(self,coeff_sent):
        funcname = __name__ + '.sensor_chosen():'
        logger.debug(funcname)

        calibration = coeff_sent['calibration']#
        sn = calibration.sn
        # Use only the chosen parameter, remove the rest
        channelname = self.sender().channelname
        #print('Coeff',coeff,'sn',sn,'channel',channel)
        ## Make a test configuration for KAL1
        #channelconfig = redvypr_config.configuration(calibration_template_channel)
        #channelconfig['sn'] = self.nosensorstr  # The serialnumber of the channel
        if sn == self.nosensorstr:
            logger.debug(funcname + 'Removing sensor')
        else:
            logger.debug('Adding {:s} to channel {:s}'.format(sn, channelname))
            channels = self.device.config.sensorconfigurations[self.sn].channels
            setattr(channels,channelname,calibration)

        self.fill_coeff_table()
        #print('configuration',self.device.config['sensorconfigurations'][self.sn])

    def choose_sensor(self):
        """
        Let the user choose a sensor for the channel
        """
        but = self.sender()

        funcname = __name__ + '.choose_sensor():'
        logger.debug(funcname)
        self._sensor_choose_dialog = sensorCoeffWidget(redvypr_device=self.device)
        self._sensor_choose_dialog.coeff.connect(self.sensor_chosen)
        self._sensor_choose_dialog.channelname = self.sender().channelname
        self._sensor_choose_dialog.show()


    def fill_coeff_table(self):
        """

        """
        funcname = __name__ + '.fill_coeff_table()'
        logger.debug(funcname)


        self.coeff_table.clear()
        self.coeff_table.setRowCount(5)
        self.coeff_table.setColumnCount(len(self.channelnames))
        self.coeff_table.setVerticalHeaderLabels(
            ['Serialnum', 'Model', 'Coefficient', 'Calibration date', 'Comment'])
        self.coeff_table.setHorizontalHeaderLabels(self.channelnames )
        for ch,ch_tmp in enumerate(self.device.config.sensorconfigurations[self.sn].channels):
            chstr = ch_tmp[0]
            sn_sensor_attached = None
            channels = self.device.config.sensorconfigurations[self.sn].channels
            calibration = getattr(channels,chstr)
            print('Got channel',calibration)
            sn_sensor_attached = calibration.sn

            if sn_sensor_attached is None:
                logger.warning('Could not find coeffcients for {:s}'.format(sn_sensor_attached))
                continue
            elif len(sn_sensor_attached) == 0:
                logger.warning('No sensor attached at channel {:s}'.format(chstr))
                continue
            else:
                print('Using calibration',calibration)
                # Try to find coefficients for the sensor
                try:
                    coeff = str(calibration.coeff)
                except Exception as e:
                    coeff = np.NaN
                    logger.debug(funcname)
                    logger.exception(e)
                    logger.debug(funcname)

                #
                try:
                    fname = str(calibration['original_file'])
                except Exception as e:
                    fname = ''
                    logger.debug(funcname, exc_info=True)

                # Try to find coefficients for the sensor
                try:
                    coeff_date = str(calibration.date)
                except Exception as e:
                    coeff_date = ''
                    logger.debug(funcname)
                    logger.exception(e)
                    logger.debug(funcname)

                # Try to find coefficients for the sensor
                try:
                    model = str(calibration.sensor_model)
                except Exception as e:
                    model = ''
                    logger.debug(funcname)
                    logger.exception(e)
                    logger.debug(funcname)

                index_col = ch
                index_row = self.index_serialnum
                item = QtWidgets.QTableWidgetItem(str(sn_sensor_attached))
                self.coeff_table.setItem(index_row,index_col,item)

                if coeff is np.NaN:
                    coeffstr = ''
                else:
                    coeffstr = str(coeff)

                index_row = self.index_coeff
                item = QtWidgets.QTableWidgetItem(coeffstr)
                self.coeff_table.setItem(index_row, index_col, item)

                index_row = self.index_model
                item = QtWidgets.QTableWidgetItem(str(model))
                self.coeff_table.setItem(index_row, index_col, item)

                index_row = self.index_date
                item = QtWidgets.QTableWidgetItem(str(coeff_date))
                self.coeff_table.setItem(index_row, index_col, item)

                #index_row = self.index_fname
                #item = QtWidgets.QTableWidgetItem(str(fname))
                #self.coeff_table.setItem(index_row, index_col, item)

        self.coeff_table.resizeColumnsToContents()

class HFVWidget(QtWidgets.QWidget):
    """
    Widget to display information from a 4 Channel Voltage board
    """

    def __init__(self, *args, sn=None, redvypr_device=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        self.device = redvypr_device

        self.sn = sn
        # Try to find a configuration for the logger
        try:
            self.device.config.sensorconfigurations[self.sn]
            logger.debug(funcname + ' Found a configuration')
        except:
            logger.warning(funcname + ' Did not find a configuration, will need to create one')
            return
            # Make a test configuration for KAL1
            #channelconfig = config.configuration(calibration_template_channel)

        self.rawconvtabs = QtWidgets.QTabWidget()

        # Add table with the data
        self.datatable_raw = QtWidgets.QTableWidget()
        self.datatable_raw.setColumnCount(6)
        self.datatable_raw.setRowCount(2)
        self.datatable_raw.resizeRowsToContents()
        self.datatable_raw.horizontalHeader().hide()
        self.datatable_raw.verticalHeader().hide()
        self.datatable_raw.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.datatable_raw.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        # Add table with the data
        self.datatable_conv = QtWidgets.QTableWidget()
        self.datatable_conv.setColumnCount(6)
        self.datatable_conv.setRowCount(2)
        self.datatable_conv.horizontalHeader().hide()
        self.datatable_conv.verticalHeader().hide()
        self.datatable_conv.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.datatable_conv.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        # Fill the tables
        for i in range(4):
            item = QtWidgets.QTableWidgetItem('CH' + str(i))
            self.datatable_raw.setItem(0, i + 1, item)
            item = QtWidgets.QTableWidgetItem('CH' + str(i))
            self.datatable_conv.setItem(0, i + 1, item)

        item = QtWidgets.QTableWidgetItem('Time')
        self.datatable_raw.setItem(0, 0, item)
        item = QtWidgets.QTableWidgetItem('Time')
        self.datatable_conv.setItem(0, 0, item)
        item = QtWidgets.QTableWidgetItem('Unit')
        self.datatable_raw.setItem(0, 5, item)
        item = QtWidgets.QTableWidgetItem('Unit')
        self.datatable_conv.setItem(0, 5, item)
        item = QtWidgets.QTableWidgetItem('V')
        self.datatable_raw.setItem(1, 5, item)
        item = QtWidgets.QTableWidgetItem('Wm-2')
        self.datatable_conv.setItem(1, 5, item)

        self.layout = QtWidgets.QGridLayout(self)
        self.layout.addWidget(self.rawconvtabs,0,0)

        self.rawdatawidget = QtWidgets.QWidget()
        rawlayout = QtWidgets.QGridLayout(self.rawdatawidget)
        rawlayout.addWidget(self.datatable_raw, 0, 0, 1, 2)

        self.convdatawidget = QtWidgets.QWidget()
        convlayout = QtWidgets.QGridLayout(self.convdatawidget)
        convlayout.addWidget(self.datatable_conv, 0, 0, 1, 2)


        self.plot_widgets_HFV = []
        self.plot_widgets_HFVSI = []
        self.coeffInput = []
        self.layout.setRowStretch(0, 1)
        row = 0
        col = 0
        for i in range(4):
            # Create plots
            plot_widgets.logger.setLevel(logging.INFO)
            config = XYplotWidget.configXYplot(title='Voltage CH{:d}'.format(i))
            plot_widget_HFV = XYplotWidget.XYplot(config=config, redvypr_device=self.device.redvypr)
            # Subscribe to channel
            plot_widget_HFV.set_line(0, 'C{:d}'.format(i) + '/{HFV_raw_.*}', name='HFV C{:d}'.format(i), color='red', linewidth=2)
            self.plot_widgets_HFV.append(plot_widget_HFV)
            rawlayout.addWidget(plot_widget_HFV, row+1, col)
            rawlayout.setRowStretch(row+1, 3)

            config = XYplotWidget.configXYplot(title='Heat flow CH{:d}'.format(i))
            plot_widget_HFVSI = XYplotWidget.XYplot(config=config, redvypr_device=self.device.redvypr)
            # Subscribe to channel
            plot_widget_HFVSI.set_line(0, 'C{:d}'.format(i) + '/{HFV_SI_.*}', name='HFVSI C{:d}'.format(i), color='red',
                                     linewidth=2)
            self.plot_widgets_HFVSI.append(plot_widget_HFVSI)
            convlayout.addWidget(plot_widget_HFVSI, row + 1, col)
            convlayout.setRowStretch(row + 1, 1)

            col += 1
            if col > 1:
                col = 0
                row += 1

        self.rawconvtabs.addTab(self.rawdatawidget,'Raw data')
        self.rawconvtabs.addTab(self.convdatawidget, 'Converted data')


    def update(self, data):
        """
        Updating the local data with datapacket
        """
        funcname = __name__ + '.update()'
        logger.debug(funcname)
        mac = data['sn']
        if mac in self.sn:
            #print(funcname + ' Got data',data)
            # Update table
            if data['type'] == 'HFV':  # Raw data
                tdata = datetime.datetime.utcfromtimestamp(data['t'])
                tdatastr = tdata.strftime('%Y-%m-%d %H:%M:%S.%f')
                item = QtWidgets.QTableWidgetItem(tdatastr)
                self.datatable_raw.setItem(1,0, item)
                for chi in range(4):
                    channelname = 'C' + str(chi)
                    chdata = "{:+.6f}".format(data[channelname])
                    item = QtWidgets.QTableWidgetItem(str(chdata))
                    self.datatable_raw.setItem(1, chi + 1, item)

                #self.datatable_raw.resizeColumnsToContents()
                for i in range(4):
                    try:
                        #print('data',data,i)
                        self.plot_widgets_HFV[i].update_plot(data)
                    except Exception as e:
                        pass
            elif data['type'] == 'HFVSI':  # Converted data
                try:
                    tdata = datetime.datetime.utcfromtimestamp(data['t'])
                    tdatastr = tdata.strftime('%Y-%m-%d %H:%M:%S.%f')
                    item = QtWidgets.QTableWidgetItem(tdatastr)
                    self.datatable_conv.setItem(1, 0, item)
                    for chi in range(4):
                        try:
                            channelname = 'C' + str(chi)
                            chdata = "{:+.6f}".format(data[channelname])
                            item = QtWidgets.QTableWidgetItem(str(chdata))
                            self.datatable_conv.setItem(1, chi + 1, item)
                        except:
                            pass
                except:
                    pass

                for i in range(4):
                    print('Updating')
                    try:
                        self.plot_widgets_HFVSI[i].update_plot(data)
                    except Exception as e:
                        logger.info('Error',exc_info=True)
                        pass



class DHFSWidget(QtWidgets.QWidget):
    """
    Widget to display Digital Heat flow sensor data
    """
    def __init__(self,*args, sn=None, redvypr_device=None):
        funcname = __name__ + '__init__()'
        logger.debug(funcname)
        super(QtWidgets.QWidget, self).__init__(*args)

        self.device = redvypr_device
        self.sn = sn
        self.configuration = None
        if self.device is not None:
            try:
                self.configuration = self.device.config.sensorconfigurations[sn]
            except Exception as e:
                logger.exception(e)

        self.parameter = ['HF', 'NTC0', 'NTC1', 'NTC2']
        self.parameter = []
        self.parameter_unit = []
        self.parameter_unitconv = []
        print('Adding parameter')
        for ptmp in self.configuration.parameter:
            print('ptmp',ptmp)
            p = ptmp[0]
            self.parameter.append(p)
            self.parameter_unit.append(None)
            self.parameter_unitconv.append(None)

        #self.create_coeff_widget()
        self.XYplots = []
        self.rawconvtabs = QtWidgets.QTabWidget()
        self.rawwidget = QtWidgets.QWidget()
        self.layout_raw = QtWidgets.QGridLayout(self.rawwidget)
        self.convwidget = QtWidgets.QWidget()
        self.layout_conv = QtWidgets.QGridLayout(self.convwidget)
        self.rawconvtabs.addTab(self.rawwidget,'Rawdata')
        self.rawconvtabs.addTab(self.convwidget, 'Converted data')

        self.layout = QtWidgets.QGridLayout(self)
        self.layout.addWidget(self.rawconvtabs,0,0)

        # Add a table for the raw data
        self.datatable_raw = QtWidgets.QTableWidget()

        self.datatable_raw.setRowCount(2)
        self.datatable_raw_columnheader = ['Time']
        for i, p in enumerate(self.parameter):
            self.datatable_raw_columnheader.append(p)

        self.datatable_raw.setColumnCount(len(self.datatable_raw_columnheader))
        self.datatable_raw.setHorizontalHeaderLabels(self.datatable_raw_columnheader)
        self.datatable_raw.setVerticalHeaderLabels(['Unit','Data'])
        self.datatable_raw.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.datatable_raw.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        # Add a table for the conv data
        self.datatable_conv = QtWidgets.QTableWidget()
        self.datatable_conv.setRowCount(2)
        self.datatable_conv_columnheader = []
        #for i, p in enumerate(self.parameter):
        #    self.datatable_columnheader.append(p)
        self.datatable_conv.setColumnCount(len(self.datatable_raw_columnheader))
        self.datatable_conv.setHorizontalHeaderLabels(self.datatable_raw_columnheader)
        self.datatable_conv.setVerticalHeaderLabels(['Unit', 'Data'])
        self.datatable_conv.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.datatable_conv.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        config = XYplotWidget.configXYplot(title='Heat flow raw')
        self.plot_widget_HF_raw = XYplotWidget.XYplot(config=config, redvypr_device=redvypr_device)
        self.plot_widget_HF_raw.set_line(0,'/d:{DHF_raw_.*}/k:HF/', name='HF', color='red',linewidth = 2)

        config = XYplotWidget.configXYplot(title='Heat flow')
        self.plot_widget_HF_SI = XYplotWidget.XYplot(config=config, redvypr_device=redvypr_device)
        self.plot_widget_HF_SI.set_line(0, '/d:{DHF_SI_.*}/k:HF/', name='HF', color='red', linewidth=2)

        if True:
            config = XYplotWidget.configXYplot(title='Temperature raw (NTC)')
            self.plot_widget_NTC_raw = XYplotWidget.XYplot(config=config, redvypr_device=redvypr_device)
            self.plot_widget_NTC_raw.set_line(0,'/d:{DHF_raw_.*}/k:NTC0/', name='NTC0', color='red', linewidth = 2)
            self.plot_widget_NTC_raw.add_line('/d:{DHF_raw_.*}/k:NTC1/', name='NTC1', color='green',linewidth = 2)
            self.plot_widget_NTC_raw.add_line('/d:{DHF_raw_.*}/k:NTC2/', name='NTC2', color='purple',linewidth = 2)

        if True:
            config = XYplotWidget.configXYplot(title='Temperature (NTC)')
            self.plot_widget_NTC_SI = XYplotWidget.XYplot(config=config, redvypr_device=redvypr_device)
            self.plot_widget_NTC_SI.set_line(0, '/d:{DHF_SI_.*}/k:NTC0/', name='NTC0', color='red', linewidth=2)
            self.plot_widget_NTC_SI.add_line('/d:{DHF_SI_.*}/k:NTC1/', name='NTC1', color='green', linewidth=2)
            self.plot_widget_NTC_SI.add_line('/d:{DHF_SI_.*}/k:NTC2/', name='NTC2', color='purple', linewidth=2)


        if True: # Average data
            print('Average data!! 0')
            self.avgWidget = QtWidgets.QWidget()
            self.avgWidget_layout = QtWidgets.QVBoxLayout(self.avgWidget)
            self.rawconvtabs.addTab(self.avgWidget, 'Average')

            config = XYplotWidget.configXYplot(title='Heat flow average')
            self.plot_widget_HF_SI_AVG = XYplotWidget.XYplot(config=config, redvypr_device=redvypr_device, add_line=False)
            for i,avg_s in enumerate(self.configuration.avg_data):
                avg_str = str(avg_s) + 's'
                avg_datakey = 'HF_avg_{}'.format(avg_str)
                std_datakey = 'HF_std_{}'.format(avg_str)
                raddress = redvypr_address(datakey=avg_datakey,devicename='{DHF_SIAVG_.*}')
                raddress_std = redvypr_address(datakey=std_datakey, devicename='{DHF_SIAVG_.*}')
                address = raddress.address_str
                address_std = raddress_std.address_str
                #'HF_avg_10s'
                #Publishing avg:10s packet
                #{'_redvypr': {'t': 1707832080.2044983, 'device': 'DHF_SIAVG_FC0FE7FFFE164EE0', 'host': {'hostname': 'redvypr', 'tstart': 1708066243.1493528, 'addr': '192.168.178.157', 'uuid': '176473386979093-187'}}, 't_avg_10s': 1707832073.2196076, 't_std_10s': 3.4081697616298503, 't_n_10s': 6, 'HF_avg_10s': 3.607291333333333, 'HF_std_10s': 0.04859570904468358, 'HF_n_10s': 6, 'NTC0_avg_10s': 21.016166666666663, 'NTC0_std_10s': 0.0003726779962504204, 'NTC0_n_10s': 6, 'NTC1_avg_10s': 21.119, 'NTC1_std_10s': 0.0, 'NTC1_n_10s': 6, 'NTC2_avg_10s': 21.113333333333333, 'NTC2_std_10s': 0.00047140452079160784, 'NTC2_n_10s': 6}
                self.plot_widget_HF_SI_AVG.add_line(address, name=address, linewidth=1, error_addr=address_std)
                self.avgWidget_layout.addWidget(self.plot_widget_HF_SI_AVG)

            # Add the three temperature sensors as well
            for NNTC in range(0,3):
                config = XYplotWidget.configXYplot(title='Temperature (average)')
                plot_widget_NTC_SI_AVG = XYplotWidget.XYplot(config=config, redvypr_device=redvypr_device,
                                                                 add_line=False)
                for i, avg_s in enumerate(self.configuration.avg_data):
                    avg_str = str(avg_s) + 's'
                    avg_datakey = 'NTC{}_avg_{}'.format(NNTC,avg_str)
                    std_datakey = 'NTC{}_std_{}'.format(NNTC,avg_str)
                    raddress = redvypr_address(datakey=avg_datakey, devicename='{DHF_SIAVG_.*}')
                    raddress_std = redvypr_address(datakey=std_datakey, devicename='{DHF_SIAVG_.*}')
                    address = raddress.address_str
                    address_std = raddress_std.address_str
                    plot_widget_NTC_SI_AVG.add_line(address, name=address, linewidth=1, error_addr=address_std)
                    self.avgWidget_layout.addWidget(plot_widget_NTC_SI_AVG)
                    self.XYplots.append(plot_widget_NTC_SI_AVG)

        # Add all the plots, such that they can be updated
        self.XYplots.append(self.plot_widget_HF_SI_AVG)
        self.XYplots.append(self.plot_widget_HF_raw)
        self.XYplots.append(self.plot_widget_NTC_raw)
        self.XYplots.append(self.plot_widget_HF_SI)
        self.XYplots.append(self.plot_widget_NTC_SI)

        self.layout_raw.addWidget(self.datatable_raw, 0, 0, 1, 1)
        self.layout_conv.addWidget(self.datatable_conv, 0, 0, 1, 1)
        self.layout_raw.addWidget(self.plot_widget_HF_raw,1,0)
        self.layout_raw.addWidget(self.plot_widget_NTC_raw,2,0)
        self.layout_conv.addWidget(self.plot_widget_HF_SI,1,0)
        self.layout_conv.addWidget(self.plot_widget_NTC_SI,2,0)

        self.layout_raw.setRowStretch(1, 1)
        self.layout_raw.setRowStretch(2, 1)
        self.layout_conv.setRowStretch(1, 1)
        self.layout_conv.setRowStretch(2, 1)


    def update(self,data):
        """
        Updating the local data with datapacket
        """
        funcname = __name__ + '__update__()'
        logger.debug(funcname)
        #print('Got data for widget',data)
        mac = data['sn']
        #print('Got data', data['_redvypr']['device'],mac)
        if mac in self.sn:
            for plot in self.XYplots:
                #print('plot update',plot)
                plot.update_plot(data)

            # Update table
            if data['type'] == 'HF':  # Raw data
                #print('Updating')
                tdata = datetime.datetime.utcfromtimestamp(data['t'])
                tdatastr = tdata.strftime('%Y-%m-%d %H:%M:%S.%f')
                item = QtWidgets.QTableWidgetItem(tdatastr)
                self.datatable_raw.setItem(1, 0, item)
                for p_index,p in enumerate(self.parameter):
                    if self.parameter_unit[p_index] is None:
                        #datastream = data_packets.get_datastream_from_data(data,p)
                        datastream = redvypr_address(data, datakey = p)
                        #print('datastream',datastream)
                        #keyinfo = self.device.get_metadata_datakey(datastream)
                        keyinfo = {}
                        try:
                            self.parameter_unit[p_index] = str(keyinfo['unit'])
                        except:
                            self.parameter_unit[p_index] = str('NA')

                        item = QtWidgets.QTableWidgetItem(self.parameter_unit[p_index])
                        self.datatable_raw.setItem(0, p_index + 1, item)
                        #print('Keyinfo', keyinfo)
                        #print('Parameter', p)
                        #print('datastream',datastream)
                        #print('keyinfo', keyinfo)
                    try:
                        chdata = "{:+.6f}".format(data[p])
                        item = QtWidgets.QTableWidgetItem(str(chdata))
                        self.datatable_raw.setItem(1, p_index + 1, item)
                    except Exception as e:
                        logger.debug(funcname, exc_info=True)

            elif data['type'] == 'HFSI':  # Raw data
                #print('Updating HFSI')
                tdata = datetime.datetime.utcfromtimestamp(data['t'])
                tdatastr = tdata.strftime('%Y-%m-%d %H:%M:%S.%f')
                item = QtWidgets.QTableWidgetItem(tdatastr)
                self.datatable_conv.setItem(1, 0, item)
                for p_index, p in enumerate(self.parameter):
                    if self.parameter_unitconv[p_index] is None:
                        datastream = redvypr_address(data, datakey=p)
                        ##datastream = data_packets.get_datastream_from_data(data, p)
                        #keyinfo = self.device.get_metadata_datakey(datastream)
                        keyinfo = {}
                        try:
                            self.parameter_unitconv[p_index] = str(keyinfo['unit'])
                        except:
                            self.parameter_unitconv[p_index] = str('NA')

                        item = QtWidgets.QTableWidgetItem(self.parameter_unitconv[p_index])
                        self.datatable_conv.setItem(0, p_index + 1, item)
                        # print('Keyinfo', keyinfo)
                        #print('Parameter', p)
                        #print('datastream', datastream)
                        #print('keyinfo', keyinfo)

                    try:
                        chdata = "{:+.6f}".format(data[p])
                        item = QtWidgets.QTableWidgetItem(str(chdata))
                        self.datatable_conv.setItem(1, p_index + 1, item)
                    except Exception as e:
                        logger.debug(funcname, exc_info=True)

        # Fill the datatables







#
#
# Init Widget
#
#
#
class initDeviceWidget(QtWidgets.QWidget):
    connect = QtCore.pyqtSignal(
        redvypr_device)  # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices

    def __init__(self, device = None):
        """
        Standard deviceinitwidget if the device is not providing one by itself.

        Args:
            device:
        """
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.config_widgets = []
        self.device = device
        self.create_sensorcoefficientWidget()
        self.config_widgets.append(self.sensorCoeffWidget)



        self.coeffbutton = QtWidgets.QPushButton('Calibration coefficients')
        self.coeffbutton.clicked.connect(self.show_coeffwidget)
        self.config_widgets.append(self.coeffbutton)

        self.__create_configLoggers_widget__()
        self.addLoggerButton = QtWidgets.QPushButton('Add sensor manually')
        self.addLoggerButton.clicked.connect(self.__configlogger_add_clicked__)
        self.config_widgets.append(self.addLoggerButton)

        self.coefffiles = QtWidgets.QListWidget()
        self.populate_coefffiles()
        self.create_sensorcoefffilesWidget()

        # Start-button
        self.startbutton = QtWidgets.QPushButton('Start')
        self.startbutton.clicked.connect(self.start_clicked)
        self.startbutton.setCheckable(True)
        # Process kill button (if thread)
        if (self.device.mp == 'multiprocess'):
            # Killbutton
            self.killbutton = QtWidgets.QPushButton('Kill process')
            self.killbutton.clicked.connect(self.kill_clicked)

        # Connect button
        self.conbutton = QtWidgets.QPushButton("Subscribe")
        self.conbutton.clicked.connect(self.connect_clicked)
        self.config_widgets.append(self.conbutton)
        sensorlabel = QtWidgets.QLabel('Sensors')
        sensorlabel.setAlignment(QtCore.Qt.AlignCenter)
        sensorlabel.setStyleSheet(''' font-size: 24px; font: bold''')
        self.layout.addWidget(sensorlabel, 0, 0)
        self.layout.addWidget(self.configLoggerWidgets['loggerlist'], 1, 0, 1, 4)
        self.layout.addWidget(self.coeffbutton, 2, 0, 1, 2)
        self.layout.addWidget(self.addLoggerButton,2, 2, 1, 2)
        self.layout.addWidget(self.conbutton, 3, 0, 1, 4)
        if (self.device.mp == 'multiprocess'):
            self.layout.addWidget(self.startbutton, 4, 0, 1, 3)
            self.layout.addWidget(self.killbutton, 4, 3)
        else:
            self.layout.addWidget(self.startbutton, 4, 0, 1, 4)

        # If the config is changed, update the device widget
        self.layout.setRowStretch(0, 0)
        self.layout.setRowStretch(1, 20)
        self.layout.setRowStretch(2, 1)
        self.layout.setRowStretch(3, 2)
        #GL.setColumnStretch(GL.columnCount(), 1)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)
        #self.config_widget.config_changed_flag.connect(self.config_changed)
        self.device.newlogger_signal.connect(self.__newlogger__)
        self.device.newloggerconfig_signal.connect(self.loggerconfig_changed)

        #config = XYplotWidget.configXYplot(title='Test')
        #self.plot_widget_HF_raw = XYplotWidget.XYplot(config=config, redvypr_device=self.device.redvypr)
        #self.plot_widget_HF_raw.show()

    def loggerconfig_changed(self):
        funcname = __name__ + '.loggerconfig_changed():'
        logger.debug(funcname)
        self.__update_configLoggerList__()
    def __newlogger__(self,newlogger):
        funcname = __name__ + '.__newlogger__():'
        logger.debug(funcname)
        self.__update_configLoggerList__()
    def finalize_init(self):
        funcname = __name__ + '.__create_configLoggers_widget__():'
        logger.debug(funcname)
        self.__update_configLoggerList__()

    def __create_configLoggers_widget__(self):
        """

        """
        funcname = __name__ + '.__create_configLoggers_widget__():'
        logger.debug(funcname)

        self.configLoggerWidgets = {}
        #self.configLoggerWidgets['loggerlist'] = QtWidgets.QListWidget()  # A list with all loggers
        self.configLoggerWidgets['loggerlist'] = QtWidgets.QTableWidget()  # A list with all loggers
        #self.configLoggerWidgets['loggerlist'].currentRowChanged.connect(self.__configloggerlist_changed__)
        self.configLoggerWidgets['loggerconfig'] = QtWidgets.QWidget()
        self.configLoggerWidgets['loggerconfig_layout'] = QtWidgets.QVBoxLayout(self.configLoggerWidgets['loggerconfig'])
        self.__update_configLoggerList__()

    def __configlogger_clicked__(self):
        funcname = __name__ + '__configlogger_clicked__():'
        logger.debug(funcname)
        item = self.sender().item
        layout = self.configLoggerWidgets['loggerconfig_layout']
        if item is not None:
            #print('item', item)
            #print('item', item.sn)
            #print('item', item.configwidget)
            while layout.count():
                itemold = layout.takeAt(0)
                widget = itemold.widget()
                widget.hide()

            self.configLoggerWidgets['loggerconfig_layout'].addWidget(item.configwidget)
            item.configwidget.show()
            self.configLoggerWidgets['loggerconfig'].show()


    def __configlogger_add_clicked__(self):
        self.configLoggerWidgets['addwidget'] = QtWidgets.QWidget()
        self.configLoggerWidgets['addwidget_layout'] = QtWidgets.QGridLayout(self.configLoggerWidgets['addwidget'])
        layout = self.configLoggerWidgets['addwidget_layout']
        self.configLoggerWidgets['loggercombo'] = QtWidgets.QComboBox()
        #print('Options',typing.get_type_hints(self.device.config.sensorconfigurations))
        print('Options',typing.get_type_hints(device_config))
        sensorconfigurations_options_tmp = typing.get_type_hints(device_config)['sensorconfigurations'] # This is a typing.Dict
        sensorconfigurations_options_tmp2 = typing.get_args(sensorconfigurations_options_tmp)[1] # This is a Union
        sensorconfigurations_options = typing.get_args(sensorconfigurations_options_tmp2) # This is a tuple with the arguments
        for hf_logger in sensorconfigurations_options:
            hf_logger_called = hf_logger()
            print('hf_logger',hf_logger)
            logger_model = hf_logger_called.logger_model
            logger_data = hf_logger # Store the hf_logger template
            #item = QtWidgets.QStandardItem(logger_model)
            #item.logger_model = logger_model
            self.configLoggerWidgets['loggercombo'].addItem(logger_model)
            cnt = self.configLoggerWidgets['loggercombo'].count()
            self.configLoggerWidgets['loggercombo'].setItemData(cnt-1,logger_data)
        self.configLoggerWidgets['loggeraddbutton'] = QtWidgets.QPushButton('Apply')
        self.configLoggerWidgets['loggeraddbutton'].clicked.connect(self.__configlogger_add_apply__)
        self.configLoggerWidgets['loggername'] = QtWidgets.QLineEdit()
        self.configLoggerWidgets['loggernamelabel'] = QtWidgets.QLabel('SN')
        self.configLoggerWidgets['loggertypelabel'] = QtWidgets.QLabel('Type')

        layout.addWidget(self.configLoggerWidgets['loggertypelabel'], 0, 0)
        layout.addWidget(self.configLoggerWidgets['loggernamelabel'], 0, 1)
        layout.addWidget(self.configLoggerWidgets['loggercombo'],1, 0)
        layout.addWidget(self.configLoggerWidgets['loggername'], 1, 1)
        layout.addWidget(self.configLoggerWidgets['loggeraddbutton'], 2, 0, 1, 2)
        self.configLoggerWidgets['addwidget'].show()

    def __configlogger_add_apply__(self):
        funcname = __name__ + '__configloggerlist_add__():'
        logger.debug(funcname)
        sn = str(self.configLoggerWidgets['loggername'].text())
        comboindex = self.configLoggerWidgets['loggercombo'].currentIndex()
        logger_template = self.configLoggerWidgets['loggercombo'].currentData()
        print('data',logger_template)
        loggertype = self.configLoggerWidgets['loggercombo'].currentText()
        if len(sn) > 0:
            logger.debug(funcname + ' Will add logger {:s} of type {:s}'.format(sn, loggertype))
        else:
            logger.debug(funcname + ' Specify a valid name')



        if sn in list(self.device.config.sensorconfigurations.keys()):
            logger.warning(' Cannot add logger {:s}, as it exsits already'.format(sn))
            return None
        else:
            logger_new = logger_template()
            logger_new.sn = sn
            # Get the template
            logger_new.sn = sn
            self.device.config.sensorconfigurations[sn] = logger_new

            self.__update_configLoggerList__()
            self.configLoggerWidgets['addwidget'].close()

    def __update_configLoggerList_status__(self):
        """
        updates the status of the configloggerlist
        """
        funcname = __name__ + '____update_configLoggerList_status__():'
        logger.debug(funcname)

        colpub = 3
        coldev = 4
        colnp = 5
        for irow, sn in enumerate(self.device.config.sensorconfigurations.keys()):
            try:
                raddr = self.device.sensordata[sn]['__raddr__']
                item_publisher = QtWidgets.QTableWidgetItem(raddr.publisher)
                item_publisher_old = self.configLoggerWidgets['loggerlist'].item(irow, colpub)
                if item_publisher_old.text() != item_publisher.text():
                    self.configLoggerWidgets['loggerlist'].setItem(irow, colpub, item_publisher)

                devices = str(self.device.sensordata[sn]['__devices__'])
                item_devices = QtWidgets.QTableWidgetItem(devices)
                item_devices_old = self.configLoggerWidgets['loggerlist'].item(irow, coldev)
                if item_devices_old.text() != item_devices.text():
                    self.configLoggerWidgets['loggerlist'].setItem(irow, coldev, item_devices)

                np = self.device.sensordata[sn]['__np__']
                item_np = QtWidgets.QTableWidgetItem(str(np))
                item_np_old = self.configLoggerWidgets['loggerlist'].item(irow, colnp)
                if item_np_old.text() != item_np.text():
                    self.configLoggerWidgets['loggerlist'].setItem(irow, colnp, item_np)
            except:
                logger.info(funcname,exc_info=True)
                raddr = None

        self.configLoggerWidgets['loggerlist'].resizeColumnsToContents()

    def __update_configLoggerList__(self):
        """
        update the logger list of logger configuration widget
        """
        funcname = __name__ + '____update_configLoggerList__():'
        logger.debug(funcname)
        self.configLoggerWidgets['loggerlist'].clear()
        nrows = len(self.device.config.sensorconfigurations.keys())
        ncols = 6
        self.configLoggerWidgets['loggerlist'].setRowCount(nrows)
        self.configLoggerWidgets['loggerlist'].setColumnCount(ncols)
        self.configLoggerWidgets['loggerlist'].setHorizontalHeaderLabels(['SN','Sensortype','Configure','Publisher','Devices','Numpackets'])
        for irow,sn in enumerate(self.device.config.sensorconfigurations.keys()):
            # Set blank everywhere
            for icol in range(ncols):
                item_blank = QtWidgets.QTableWidgetItem('')
                self.configLoggerWidgets['loggerlist'].setItem(irow, icol, item_blank)


            item = QtWidgets.QTableWidgetItem(str(sn))
            sensor_id = str(self.device.config.sensorconfigurations[sn].sensor_id)
            #print('logger_short', logger_short)
            # Create a configuration widget for the sensor
            configwidget = self.__create_sensor_config_widget__(str(sn), sensor_id)
            item.configwidget = configwidget
            item.sn = sn
            #print('Item',item.configwidget)
            self.configLoggerWidgets['loggerlist'].setItem(irow,0,item)
            item_type = QtWidgets.QTableWidgetItem(sensor_id)
            self.configLoggerWidgets['loggerlist'].setItem(irow, 1, item_type)
            button_configure = QtWidgets.QPushButton('Configure')
            button_configure.clicked.connect(self.__configlogger_clicked__)
            button_configure.item = item
            self.configLoggerWidgets['loggerlist'].setCellWidget(irow, 2, button_configure)
            try:
                raddr = self.device.sensordata[sn]['__raddr__']
                item_publisher = QtWidgets.QTableWidgetItem(raddr.publisher)
                self.configLoggerWidgets['loggerlist'].setItem(irow, 4, item_publisher)
                print('Done')
            except:
                logger.info('fdsf',exc_info=True)
                raddr = None

        self.configLoggerWidgets['loggerlist'].resizeColumnsToContents()

    def __create_sensor_config_widget__(self, sn, sensor_id):
        funcname = __name__ + '__create_sensor_config_widget__()'
        logger.debug(funcname + ' sn: {:s}, sensor_short {:s}'.format(sn,sensor_id))
        cwidget = QtWidgets.QWidget()
        clayout = QtWidgets.QVBoxLayout(cwidget)
        clabel = QtWidgets.QLabel('Config of \n' + sn)
        clayout.addWidget(clabel)

        if sensor_id.lower() == 'generic logger':
            print('Generic logger ...')
        elif sensor_id.lower() == 'tar':
            logger.debug('Config widget for temperature array (TAR)')
            config_widget = TARWidget_config(self, sn=sn, redvypr_device=self.device)
            clayout.addWidget(config_widget)
        elif sensor_id.lower() == 'dhfs50':
            logger.debug('DHFS50')
            config_widget = DHFS50Widget_config(sn = sn, redvypr_device = self.device)
            clayout.addWidget(config_widget)
        elif sensor_id.lower() == 'hfv4ch':
            logger.debug('Four channel logger')
            config_widget = HFVWidget_config(sn = sn, redvypr_device = self.device)
            clayout.addWidget(config_widget)



        return cwidget

    def show_coefffileswidget(self):
        self.coefffileswidget.show()

    def create_sensorcoefffilesWidget(self):
        self.coefffileswidget = QtWidgets.QWidget()
        self.coefffileswidget_layout = QtWidgets.QHBoxLayout(self.coefffileswidget)
        self.coefffileswidget_layout.addWidget(self.coefffiles)

    def populate_coefffiles(self):
        for fname in self.device.coeff_filenames:
            self.coefffiles.addItem(fname)
    def show_coeffwidget(self):
        self.create_sensorcoefficientWidget()
        self.sensorCoeffWidget.show()




    def create_sensorcoefficientWidget(self):
        self.sensorCoeffWidget = sensorCoeffWidget(redvypr_device=self.device)

    def config_changed(self):
        """


        Args:
            config:

        Returns:

        """
        funcname = __name__ + '.config_changed():'
        logger.debug(funcname)

    def kill_clicked(self):
        button = self.sender()
        logger.debug("Kill device {:s}".format(self.device.name))
        self.device.kill_process()

    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            logger.debug("button pressed")
            button.setText('Starting')
            self.device.thread_start()
            # self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            # button.setText('Stopping')
            self.startbutton.setChecked(True)
            self.device.thread_stop()

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']
        # Running
        if (thread_status):
            self.startbutton.setText('Stop')
            self.startbutton.setChecked(True)
            for w in self.config_widgets:
                w.setEnabled(False)
        # Not running
        else:
            self.startbutton.setText('Start')
            for w in self.config_widgets:
                w.setEnabled(True)

            # Check if an error occured and the startbutton
            if (self.startbutton.isChecked()):
                self.startbutton.setChecked(False)
            # self.conbtn.setEnabled(True)

    def connect_clicked(self):
        button = self.sender()
        self.connect.emit(self.device)





class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None,tabwidget=None, deviceinitwidget=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QFormLayout(self)
        self.device   = device
        self.maxlen = 50000

        # Table for the raw data
        self.rawdatatableWidget = QtWidgets.QTableWidget(self)
        self.rawdatatableWidget.sensordata = {}
        self.rawrows    = []
        self.rawcolumns = []
        self.rawcolumns.append('') # Add an empty column for the Rowtype
        self.rawrows.append('Serialnum/MAC')
        self.rawrows.append('Model')

        layout.addRow(self.rawdatatableWidget)
        # Widget and Table for the converted data
        self.allconvertedWidget = QtWidgets.QWidget()
        self.allconvertedWidgetlayout = QtWidgets.QFormLayout(self.allconvertedWidget)
        self.converteddatableWidget = QtWidgets.QTableWidget(self.allconvertedWidget)
        self.converteddatableWidget.sensordata = {}
        self.convrows = []
        self.convcolumns = []
        self.convcolumns.append('')
        self.convrows.append('Serialnum/MAC')
        self.convrows.append('Model')

        self.allconvertedWidgetlayout.addRow(self.converteddatableWidget)


        # Sensorwidgets, sorted by sn, the widgets can be accessed by self.sensorwidget
        self.sensorwidget = QtWidgets.QTableWidget(self)
        self.create_sensorwidget()
        self.sensorwidgets = {}

        tabwidget.addTab(self,'Raw data')
        tabwidget.addTab(self.allconvertedWidget,'Converted data')
        tabwidget.addTab(self.sensorwidget, 'Sensors')
        #testwidget = DHFSWidget(sn='fdsfsdsf')
        #tabwidget.addTab(testwidget, 'Test')

        #sn = 'KAL1'
        #testwidget2 = HFVWidget(sn=sn,redvypr_device = self.device)
        #tabwidget.addTab(testwidget2, 'KAL1')
        #self.sensorwidgets[sn] = testwidget2

        #testwidget3 = HFVWidget(sn='KALTEST', redvypr_device=self.device)
        #tabwidget.addTab(testwidget3, 'KALTEST')



    def change_sensor(self, index):
        """
        Changes the active widget that is shown when clicked on the QListWidget
        """
        funcname = __name__ + '.change_sensor()'
        logger.debug(funcname)
        self.sensorstack.setCurrentIndex(index)

    def create_sensorwidget(self):
        funcname = __name__ + '.create_sensorwidget()'
        logger.debug(funcname)
        layout = QtWidgets.QVBoxLayout(self.sensorwidget)
        self.sensorlist = QtWidgets.QListWidget()
        self.sensorlist.currentRowChanged.connect(self.change_sensor)
        self.sensorstack = QtWidgets.QStackedWidget()
        splitter1 = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter1.addWidget(self.sensorlist)
        splitter1.addWidget(self.sensorstack)
        layout.addWidget(splitter1)


    def add_sensorwidget(self, sn, sensortype):
        funcname = __name__ + '.add_sensorwidget():'
        logger.debug(funcname+ ' Adding widget for {} and type {}'.format(sn, sensortype))
        # Add widgets
        # can beIMU, HFV, HF, TAR
        if sensortype == 'HFV':
            sensorwidget = HFVWidget(sn=sn, redvypr_device=self.device)
            self.sensorwidgets[sn] = sensorwidget
            self.sensorlist.addItem(sn)
            self.sensorstack.addWidget(sensorwidget)
        elif sensortype == 'TAR':
            sensorwidget = TARWidget(sn=sn, redvypr_device=self.device)
            self.sensorwidgets[sn] = sensorwidget
            self.sensorlist.addItem(sn)
            self.sensorstack.addWidget(sensorwidget)
        else:# HF, IMU
            sensorwidget = DHFSWidget(sn=sn, redvypr_device=self.device)
            self.sensorwidgets[sn] = sensorwidget
            self.sensorlist.addItem(sn)
            self.sensorstack.addWidget(sensorwidget)


        self.device.sensordata[sn] = {'__np__':0,'__raddr__':None,'__devices__':[]}
        self.device.sensordata_raw[sn] = []



    def update(self, data):
        funcname = __name__ + '.update():'
        print(funcname)
        #return
        print(funcname + '  got data',data)
        try:
            sn = data['sn']
            # ptype is packettype
            ptype = data['type']
            datatype = data['datatype']
            # can be IMU, HFV, HF, TAR
            print('Ptype',ptype,sn)
            try:
                self.device.sensordata_raw[sn] # List for the raw datapackets
            except:
                logger.debug('New sensor',exc_info=True)
                logger.debug(funcname + 'New sensor found with sn {:s}'.format(sn))
                try:
                    self.add_sensorwidget(sn, sensortype=ptype)
                except:
                    logger.debug(funcname, exc_info=True)
                    logger.debug('Could not add sensorwidget for {:s}'.format(sn))
                    return None

            print('Hallo',sn)
            print('fds',redvypr_address)
            raddr = redvypr_address(data)
            print('Hallo',raddr)
            # Add the data to self.device
            self.device.sensordata_raw[sn].append(data)
            self.device.sensordata[sn]['__np__'] += 1
            self.device.sensordata[sn]['__raddr__'] = raddr
            self.device.sensordata[sn]['__devices__'].append(raddr.devicename)
            self.device.sensordata[sn]['__devices__'] = list(set(self.device.sensordata[sn]['__devices__']))
            print('fdsfds')
            self.device.deviceinitwidget.__update_configLoggerList_status__()
            print('fdsfd_done')
            # Check if data needs to be removed
            if len(self.device.sensordata_raw[sn]) > self.maxlen:
                self.device.sensordata_raw[sn] = self.device.sensordata_raw[sn][-self.maxlen:]


            rdata = data_packets.datapacket(data)
            parameter = rdata.datakeys(expand=1)
            #try:
            #    parameter.remove('type')  # Remove type
            #    parameter.remove('sn')  # Remove mac
            #except:
            #    logger.debug(exc_info=True)

            #print('Parameter',parameter)
            for p in parameter:
                # Update data
                try:
                    self.device.sensordata[sn][ptype]
                except:
                    self.device.sensordata[sn][ptype] = {}
                try:
                    self.device.sensordata[sn][ptype][p]
                except:
                    self.device.sensordata[sn][ptype][p] = []

                self.device.sensordata[sn][ptype][p].append(rdata[p])
                # Check if data needs to be removed
                if len(self.device.sensordata[sn][ptype][p]) > self.maxlen:
                    self.device.sensordata[sn][ptype][p] = self.device.sensordata[sn][ptype][p][-self.maxlen:]

            # Update rows and columns
            nsensors  = len(list(self.device.sensordata_raw.keys()))

            if 'converted' in datatype.lower():
                #print('Updating converted table',ptype)
                rows = self.convrows
                columns = self.convcolumns
                table = self.converteddatableWidget
                # Store the last datapacket in each table
                table.sensordata[sn] = data
            else:
                print('Updating raw table',ptype)
                rows = self.rawrows
                columns = self.rawcolumns
                table = self.rawdatatableWidget
                print('rdata',rdata)
                table.sensordata[sn] = data

            flag_redraw = False
            for p in parameter:
                pstr = "{:s}.{:s}".format(data['type'],p)
                if pstr not in rows:
                    rows.append(pstr)
                    flag_redraw = True

            try:
                index = columns.index(sn)
            except:
                columns.append(sn)
                flag_redraw = True
                index = columns.index(sn)


            if flag_redraw:
                # Add publisher/device/numpackets to init
                # Peterself.device.deviceinitwidget.
                #print('redraw table')
                #r = rows[0:2]
                #rows[0] = '0'
                #rows[1] = '1'
                #rows.sort()
                #rows[0] = r[0]
                #rows[1] = r[1]
                #print('Rows', rows)
                #table.clear()
                table.setRowCount(len(rows))
                table.setColumnCount(len(columns))
                table.setHorizontalHeaderLabels(columns)

                for irow,r in enumerate(rows):
                    if irow < 2:
                        r = str(irow)

                    item = QtWidgets.QTableWidgetItem(r)
                    table.setItem(irow, 0, item)

                table.sortItems(0)
                for irow, r in enumerate(rows):
                    if irow >= 2:
                        rows[irow] = table.item(irow,0).text()
                    else:
                        item = QtWidgets.QTableWidgetItem(rows[irow])
                        table.setItem(irow, 0, item)

                table.setVerticalHeaderLabels(rows)
                #mac_redraw = list(table.sensordata.keys())
                mac_redraw = [sn]
            else:
                mac_redraw = [sn]

            # Send the data to the sensorwidget
            try:
                self.sensorwidgets[sn].update(data)
            except Exception as e:
                logger.debug(funcname, exc_info=True)
                #logger.exception(e)

            # Fill the table with data
            print('redraw',mac_redraw)
            for macdraw in mac_redraw:
                data_redraw = table.sensordata[macdraw]
                data_redraw_rdata = data_packets.datapacket(data_redraw)
                parameter_redraw = data_redraw_rdata.datakeys(expand=1)
                #print('parameter redraw',parameter_redraw)
                index_col = columns.index(macdraw)
                #print('data redraw',data_)
                #print('filling table',macdraw, index_col)
                for p in parameter_redraw:
                    #print('P',p)
                    pstr = "{:s}.{:s}".format(data_redraw['type'], p)
                    index_row = rows.index(pstr)
                    # Packettype can be 'IMU','HF', 'HFSI'
                    #print('data redraw',data_redraw)
                    #print('fdsfdsfds',index_row,p,data_redraw_rdata[p])
                    if 'SI' in ptype:
                        if 'NTC' in p:
                            dstr = "{:.3f}".format(data_redraw_rdata[p])
                        elif 'HF' in p:
                            dstr = "{:.6f}".format(data_redraw_rdata[p])
                        elif p == 't': # Unix time stamp
                            dstr = "{:.3f}".format(data_redraw_rdata[p])
                        else:
                            dstr = str(data_redraw_rdata[p])
                    else:
                        dstr = str(data_redraw_rdata[p])

                    # Time string
                    if p == 't':
                        td = datetime.datetime.utcfromtimestamp(data_redraw[p])
                        dstr = td.strftime('%Y-%m-%d %H:%M:%S.%f')

                    item = QtWidgets.QTableWidgetItem(dstr)
                    #print('rows',rows)
                    #print('Item',p,pstr,index_row,index_col,dstr)
                    table.setItem(index_row,index_col,item)

            table.resizeColumnsToContents()
        except:
            logger.debug(funcname, exc_info=True)


        #print('Hallo',data)


