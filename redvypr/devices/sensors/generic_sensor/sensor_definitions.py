"""
Sensor definitions
"""
import typing
import datetime
import dateutil
import pydantic
import struct
import re
import sys
import numpy
import copy
import logging
import yaml
from redvypr.data_packets import create_datadict as redvypr_create_datadict, add_metadata2datapacket, Datapacket
from redvypr.redvypr_address import RedvyprAddress
from redvypr.devices.sensors.calibration.calibration_models import CalibrationHeatFlow, CalibrationNTC, CalibrationLinearFactor, \
    CalibrationPoly


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.sensor_definitions')
logger.setLevel(logging.DEBUG)

def decode_utf8(byte_string):
    return byte_string.decode('utf-8')


def array(byte_string):
    return numpy.fromstring(byte_string,sep=',').tolist()



class Sensor(pydantic.BaseModel):
    """
    The sensor class processes redvypr datapackets and converts the data with calibrations into more meaningful units.
    the :py:method:`datapacket_process` method checks first if the packets fits with self.datastream, after this check the packet is checked
    for each datakey of self.calibration, which is a dictionary with the keys being redvypr address strings.
    For each key (address string) it is checked if it is within the datapacket.
    """
    name: str = pydantic.Field(default='sensor')
    description: str = pydantic.Field(default='Sensor')
    example_data: typing.Union[None,bytes, str] = pydantic.Field(default=None)
    sensortype: typing.Literal['sensor'] = pydantic.Field(default='sensor')
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress('*'))
    autofindcalibration: bool = pydantic.Field(default=True, description='Tries to find automatically calibrations for the sensor')
    calibrations: typing.Dict[str, typing.Annotated[typing.Union[CalibrationLinearFactor, CalibrationPoly], pydantic.Field(
        discriminator='calibration_type')]] = pydantic.Field(default={})

    def add_calibration_for_datapacket(self, packetaddress=RedvyprAddress('/i:*'), addrformat='/i',calibration=None):
        """
        Adds a calibration to the packetaddress. During process data it is checked if the provided datapacket fits with the packetaddress of the calibration and if so all calibrations found are applied.
        :param packetaddress:
        :param calibration:
        :return:
        """
        if calibration is not None:
            key = packetaddress.get_str(addrformat)
            try:
                self.calibrations[key]
            except:
                self.calibrations[key] = []

            self.calibrations[key].append(calibration)

    def add_all_calibrations(self, calibrations):
        """
        Adding a list of all calibrations to sensor. The calibrations are used for the automatic search for the correct calibrations for the processed sensor data
        :param calibrations:
        :return:
        """
        self.__all_calibrations = calibrations


    def find_calibration_for_datapacket(self, rdata: Datapacket):
        """
        Tries to find the right calibration for the datapacket
        :param rdata:
        :return:
        """
        funcname = __name__ + '.find_calibration_for_datapacket():'
        logger.debug(funcname)
        # TODO: Find a smart way to check if an autocalibration has been already done
        try:
            self.__datapackets_checked_for_calibrations
        except:
            self.__datapackets_checked_for_calibrations = []

        self.__datapackets_checked_for_calibrations.append(rdata.address)
        for calibration in self.__all_calibrations:
            logger.debug(funcname + 'Checking calibration {}'.format(calibration))
            sn = calibration.sn
            sensor_model = calibration.sensor_model
            caldate = calibration.date
            parameter_calibrated = calibration.channel
            # 1: Check if calibration.parameter is existing in the datapacket
            # 2: Compare serial number with packetid (not done yet)
            # 3: save date (not done yet)
            try:
                #print('parameter calibrated', parameter_calibrated)
                caldata_raw = rdata[parameter_calibrated]
                #print('Got caldata raw', caldata_raw)
                flag_parameter = True
            except:
                logger.debug(funcname + 'Could not get data', exc_info=True)
                flag_parameter = False

            if flag_parameter:
                logger.debug(funcname+ 'Adding calibration')
                calibration_apply = calibration.model_copy()
                calibration_apply.channel_apply = calibration_apply.channel
                #calibration_apply.datakey_result = 'test1'
                self.add_calibration_for_datapacket(rdata.address,calibration=calibration_apply)


    def datapacket_process(self, data, check_own_address=True):
        """
        Processes a redvypr datapacket. This is mainly applying calibrations
        :param data:
        :return:
        """
        funcname = __name__ + '.datapacket_process():'

        if data in self.datastream or (check_own_address==False):
        #if True: # self.datastream does not work for binary sensors
            rdata = Datapacket(data)
            rdata_addressstr = rdata.get_addressstr('/i')
            # Check if autofindcalibration shall be done
            if self.autofindcalibration:
                #print('Autocalibration')
                try:
                    self.__datapackets_checked_for_calibrations
                except:
                    self.__datapackets_checked_for_calibrations = []

                if rdata.address in self.__datapackets_checked_for_calibrations:
                    #print('Datapacket was already checked, doing nothing')
                    pass
                else:
                    found_calibration = False
                    for datapacket_calkey in self.calibrations.keys():
                        datapacket_calkey_address = RedvyprAddress(datapacket_calkey)
                        if rdata in datapacket_calkey_address:
                            found_calibration = True
                            break

                    # Did not find a calibration, but it is wished to search for one
                    if found_calibration == False:
                        self.find_calibration_for_datapacket(rdata)
                    else:
                        pass
                        #print('Found calibration already')

            # Check if there is a calibration to be found for the datapacket
            #print('Calibrations',self.calibrations)
            if len(self.calibrations.keys()) == 0:
                #print('Returning data')
                return data
            else:
                for datapacket_calkey in self.calibrations.keys():
                    datapacket_calkey_address = RedvyprAddress(datapacket_calkey)
                    if rdata in datapacket_calkey_address:
                        calibrations_for_packet = self.calibrations[rdata_addressstr]
                        #print('Calibrations for packet',calibrations_for_packet)
                        # Loop over all calibrations for the datapacket
                        for calibration in calibrations_for_packet:
                            #print('Processing calibration', calibration)
                            caldata_raw = rdata[calibration.address_apply]
                            #print(caldata_raw)
                            # And now the most important thing, applying the calibration
                            caldata_cal = calibration.raw2data(caldata_raw)
                            #print(caldata_raw,caldata_cal)
                            # Copy the data to the original location or make a copy
                            if calibration.datakey_result is None:
                                #print('Applying to data')
                                rdata[calibration.address_apply] = caldata_cal
                            else: # If the base datakey shall be changed, copy the data first
                                if calibration.address_apply.parsed_addrstr_expand['datakeyeval']:
                                    datakey_orig = calibration.address_apply.parsed_addrstr_expand['datakeyentries'][0]
                                    datakey_new = calibration.datakey_result.format(datakey=datakey_orig)
                                    datakey_new_eval = calibration.address_apply.datakey.replace(datakey_orig,"{}".format(datakey_new))
                                    address_result = RedvyprAddress(calibration.address_apply, datakey=datakey_new_eval)
                                else:
                                    datakey_orig = calibration.address_apply.datakey
                                    # Create the new RedvyprAddress
                                    datakey_new = calibration.datakey_result.format(datakey=datakey_orig)
                                    address_result = RedvyprAddress(calibration.address_apply, datakey=datakey_new)

                                # And finally copy the data into the new datakey
                                try:
                                    rdata[datakey_new]
                                except:
                                    data_orig = data[datakey_orig]
                                    rdata[datakey_new] = copy.deepcopy(data_orig)

                                #print('Data orig',data_orig)
                                #print('Hallo',calibration.address_apply.parsed_addrstr_expand['datakeyentries'])
                                rdata[address_result] = caldata_cal

                        #print('data done', rdata)
                        #print('yaml2', yaml.dump(dict(rdata)))
                        return dict(rdata)


class BinarySensor(Sensor):
    """
    A binary sensor gets binary data that need to be converted first into a dictionary with the datakeys
    """
    name: str = pydantic.Field(default='binsensor')
    sensortype: typing.Literal['binsensor'] = pydantic.Field(default='binsensor')
    regex_split: bytes = pydantic.Field(default=b'', description='Regex expression to split a binary string')
    binary_format: typing.Dict[str, str] = pydantic.Field(default={}, description='https://docs.python.org/3/library/struct.html, for example for 16bit signed data {"adc_data":"<h"}')
    str_format: typing.Dict[str, str] = pydantic.Field(default={})
    packetid_format: typing.Optional[str] = pydantic.Field(default=None,description='Format of the packetid of the datapacket')
    device_format: typing.Optional[str] = pydantic.Field(default=None,
                                                           description='Format of the device of the datapacket')
    datakey_metadata: typing.Dict[str, typing.Dict] = pydantic.Field(default={})
    calibrations_raw: typing.Dict[str, typing.Annotated[typing.Union[CalibrationLinearFactor, CalibrationPoly], pydantic.Field(
        discriminator='calibration_type')]] = pydantic.Field(default={})

    calibration_python_str: typing.Optional[dict] = pydantic.Field(default=None, description='A python str that is evaluated and processes the raw data')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__rdatastream__ = RedvyprAddress(self.datastream)
        self._str_functions = {}
        self._str_functions_invalid_data = {}
        self._flag_binary_keys = len(self.binary_format.keys()) > 0
        self._flag_str_format_keys = len(self.str_format.keys()) > 0
        # Add functions for datatypes
        for key in self.str_format:
            vartype = self.str_format[key]
            #print('key', key, 'vartype', vartype)
            if vartype.lower() == 'float':
                self._str_functions[key] = float
                self._str_functions_invalid_data[key] = None
            elif vartype.lower() == 'int':
                self._str_functions[key] = int
                self._str_functions_invalid_data[key] = None
            elif vartype.lower() == 'str':
                self._str_functions[key] = decode_utf8
                self._str_functions_invalid_data[key] = None
            elif vartype.lower() == 'array':
                self._str_functions[key] = array
                self._str_functions_invalid_data[key] = None

    def create_metadata_datapacket(self):
        """
        Creates a datapacket with the metadata information
        :return:
        """
        data_packet = redvypr_create_datadict(device=self.name)

        flag_metadata = False
        print('self.datakey_metadata',self.datakey_metadata)
        for key_input in self.datakey_metadata.keys():
            print('key input',key_input)
            flag_metadata = True
            metadata = self.datakey_metadata[key_input]
            print('metadata', metadata)
            metadata_address = RedvyprAddress(device=self.name, datakey=key_input)
            #data_packet = add_metadata2datapacket(data_packet, key_input, metadict=metadata)
            print('address', metadata_address)
            data_packet = add_metadata2datapacket(data_packet, address=metadata_address, metadict=metadata)
            print('dta_packet', data_packet)
            print('Done\n\n')
        for key_input in self.calibrations_raw.keys():
            flag_metadata = True

            calibration = self.calibrations_raw[key_input]
            unit = calibration.unit
            unit_input = calibration.unit_input
            key_result = calibration.parameter_result
            if (key_input is not None) and (unit_input is not None):
                metadata_address = RedvyprAddress(device=self.name, datakey=key_input)
                data_packet = add_metadata2datapacket(data_packet, address=metadata_address, metadata=unit_input)
                #data_packet = add_metadata2datapacket(data_packet, key_input, metadata=unit_input)
            if (key_result is not None) and (unit is not None):
                metadata_address = RedvyprAddress(device=self.name, datakey=key_result)
                data_packet = add_metadata2datapacket(data_packet, address=metadata_address, metadata=unit)


        if flag_metadata:
            return data_packet
        else:
            return None
    def datapacket_process(self, data, datakey=None):
        """
        Processes a redvypr datapacket.
        :param data:
        :return:
        """
        #print('Hallo data', data)
        #print('address',self.__rdatastream__)
        flag_data = False
        if datakey is None:
            if data in self.__rdatastream__:
                binary_data = self.__rdatastream__.get_data(data)
                flag_data = True
        else:
            binary_data = data[datakey]
            flag_data = True

        if flag_data:
            #print('Processing data',data)

            #print('Binary data', binary_data)
            data_packets = self.binary_process(binary_data, datapacket_orig=data)
            #print('data packets',data_packets)
            for data_packet in data_packets:
                if 't' not in data_packet.keys():
                    data_packet['t'] = data['t']

            # Check if calibrations exist, if yes, do the calibration procedure
            if (len(self.calibrations.keys()) > 0) or self.autofindcalibration:
                #print('Calibrations',self.calibrations)
                #print('Autofindcalibration',self.autofindcalibration)
                data_packets_calibrated = []
                for data_packet in data_packets:
                    #print('Found calibration for parameter')
                    data_packet = super().datapacket_process(data_packet, check_own_address=False)
                    data_packets_calibrated.append(data_packet)

                #print('Autocalibration',data_packets_calibrated)
                if len(data_packets_calibrated)>0:
                    return data_packets_calibrated
                else:
                    return None
            else: # no calibration, just return the data packets
                if len(data_packets) > 0:
                    return data_packets
                else:
                    return None

    def binary_process(self, binary_stream, datapacket_orig):
        """

        """
        rematches = self.binary_split(binary_stream)
        data_packets = []
        #print('Rematches',rematches)
        # Loop over all split raw string packages
        for rematch in rematches:
            data_packet = redvypr_create_datadict(device=self.name)
            flag_data = False
            print('Processing match', rematch)
            print('Variables found', rematch.groupdict())
            redict = rematch.groupdict()
            if self._flag_binary_keys:
                for keyname in redict:
                    if keyname in self.binary_format.keys():
                        binary_format = self.binary_format[keyname]
                        #print('Found binary key with format', keyname, binary_format)
                        # convert the data
                        data = struct.unpack(binary_format, redict[keyname])
                        if len(data) == 1:
                            data = data[0]
                        data_packet[keyname] = data
                        flag_data = True


            if self._flag_str_format_keys:
                #print('Str format')
                for keyname in redict:
                    if keyname in self.str_format.keys():
                        #print('Found str key', keyname)
                        # get the right function
                        convfunction = self._str_functions[keyname]
                        # convert the data, if this fails, take invalid data value
                        try:
                            data = convfunction(redict[keyname])
                        except:
                            #print('Data',redict[keyname])
                            logger.debug('Could not decode data for key {}'.format(keyname),exc_info=True)
                            data = self._str_functions_invalid_data[keyname]

                        data_packet[keyname] = data
                        flag_data = True
                        #print('Converted data to', data, flag_data,type(data))
                        #print('yaml',yaml.dump(data))

            if self.calibration_python_str is not None:
                logger.debug('Found a python calibration eval str, applying')
                for keyname_eval in self.calibration_python_str:
                    evalcommand = self.calibration_python_str[keyname_eval]
                    evalcommand = evalcommand.split('\n')[0]
                    evalstr_full = 'data_packet[keyname_eval]=' + evalcommand
                    #print('Evalstr full',evalstr_full)
                    try:
                        exec(evalstr_full)
                    except:
                        logger.info('Could not evaluate command',exc_info=True)
                    #print('Data packet',data_packet)


            # Check for calibrations
            datakeys = list(data_packet.keys())
            for keyname in datakeys:
                # Check if there is a calibration
                if keyname in self.calibrations_raw.keys():
                    data = data_packet[keyname]
                    #print('Found a calibration to convert raw data for {}'.format(keyname))
                    calibration = self.calibrations_raw[keyname]
                    try:
                        keyname_cal = calibration.datakey_result
                        if keyname_cal is None:
                            keyname_cal = keyname
                    except:
                        keyname_cal = keyname + '_cal'

                    data_cal = calibration.raw2data(data)
                    #print('Data cal',data_cal)
                    data_packet[keyname_cal] = data_cal

            # Check for packetid
            if self.packetid_format is not None:
                # Define variables that can be used for the packetid, see RMC as an example
                datapacket_orig_dict = {}
                datapacket_orig_dict['packetid_rawdata'] = datapacket_orig['_redvypr']['packetid']
                datapacket_orig_dict['publisher_rawdata'] = datapacket_orig['_redvypr']['publisher']
                datapacket_orig_dict['device_rawdata'] = datapacket_orig['_redvypr']['device']
                try:
                    packetidstr = self.packetid_format.format(**data_packet, **datapacket_orig_dict)
                    data_packet['_redvypr']['packetid'] = packetidstr
                except:
                    logger.warning('Could not create an packetidstr:',exc_info=True)
            else:
                packetidstr = self.name
                data_packet['_redvypr']['packetid'] = packetidstr

            # Change the device str of the packet, if wished
            if self.device_format is not None:
                try:
                    devicestr = self.device_format.format(**data_packet,
                                                              **datapacket_orig_dict)
                    data_packet['_redvypr']['device'] = devicestr
                except:
                    logger.warning('Could not create an devicestr:', exc_info=True)


            #print('Test flag data',flag_data)
            if flag_data:
                data_packets.append(data_packet)

        #print('Data packets',data_packets)
        return data_packets

    def binary_split(self, binary_stream):
        """
        Splits the data into pieces
        :param binary_stream:
        :param sensors:
        :return:
        """

        regex = self.regex_split
        matches = []
        #print('Regex', regex, binary_stream)
        # rematch = re.search(regex, binary_stream)
        rematchiter = re.finditer(regex, binary_stream)
        rematch = [r for r in rematchiter]
        #print('rematch 1', rematch)
        return rematch



# S4L (sam4log)
s4l_split = b'B\x00(?P<counter32>[\x00-\xFF]{4})(?P<adc16>[\x00-\xFF]{2})\n'
s4l_binary_format = {'counter32': '<L','adc16':'<h'}
Vref = 3.0 # Reference voltage in V
coeff_fac = Vref/2**15
coeff_fac_counter = 1/1024
calibration_adc16 = CalibrationLinearFactor(parameter_result='adc(V)', coeff=coeff_fac,
                                            unit='V', unit_input='counts')
calibration_counter32 = CalibrationLinearFactor(parameter_result='counter(s)', coeff=coeff_fac_counter,
                                                unit='s', unit_input='counts')
calibrations_raw = {'adc16':calibration_adc16,'counter32':calibration_counter32}
S4LB = BinarySensor(name='S4LB', regex_split=s4l_split, binary_format=s4l_binary_format,
                    datastream=RedvyprAddress('/k:data'),
                    calibrations_raw=calibrations_raw)


# NMEA RMC
#https://de.wikipedia.org/wiki/NMEA_0183#Recommended_Minimum_Sentence_C_(RMC)
nmea_rmc_description = 'NMEA Recommended Minimum Sentence\nhttps://de.wikipedia.org/wiki/NMEA_0183#Recommended_Minimum_Sentence_C_(RMC)'
#nmea_rmc_split = b'\$[A-Z]+RMC,(?P<time>[0-9.]*),(?P<status>[A-Z]+),(?P<latdeg>[0-9]{2})(?P<latmin>[0-9.]+),(?P<NS>[NS]+),(?P<londeg>[0-9]{3})(?P<lonmin>[0-9.]+),(?P<EW>[EW]+),[0-9.]*,[0-9.]*,(?P<date>[0-9.]*),.*\n'
nmea_rmc_split = b'\$(?P<devid>[A-Z]+)RMC,(?P<time>[0-9.]+),(?P<status>[A-Z]+),(?P<latstr>[0-9.]*),(?P<NS>[NS]*),(?P<lonstr>[0-9.]*),(?P<EW>[EW]*),(?P<speed>[0-9.]*),(?P<course>[0-9.]*),(?P<date>[0-9.]+),(?P<magdev>[0-9.]*),(?P<magdevdir>[EW]*),(?P<crc>.*)\n'
nmea_rmc_str_format = {'devid':'str','time':'str','date':'str','latstr':'str','lonstr':'str','NS':'str','EW':'str','speed':'float','course':'float'}
nmea_datakey_metadata = {'time':{'unit':'HHMMSS','description':'GNSS in UTC'},'lat':{'unit':'degN'},'lon':{'unit':'degE'}}
nmea_rmc_test1 = b'$GPRMC,162614.22,A,5230.5900,N,01322.3900,E,10.0,90.0,131006,1.2,E,A*13\r\n'
#nmea_rmc_test2 = b'$GPRMC,090413.788,V,,,,,,,310724,,,N*46\r\n'
nmea_rmc_test2 = b'$GPRMC,090413,V,,,,,,,310724,,,N*46\r\n'
nmea_rmc_packetid_format = 'RMC_{packetid_rawdata}_{publisher_rawdata}_{devid}'
latevalstr = '(float(data_packet["latstr"][0:2])+float(data_packet["latstr"][2:])/60)*(float(data_packet["NS"]=="N")-float(data_packet["NS"]=="S"))'
lonevalstr = '(float(data_packet["lonstr"][0:3])+float(data_packet["lonstr"][3:])/60)*(float(data_packet["EW"]=="W")-float(data_packet["EW"]=="E"))'
timeevalstr = 'dateutil.parser.parse(data_packet["date"] + " " + data_packet["time"] + "UTC",yearfirst=False).timestamp()'
nmea_calibration_python_str = {'lat':latevalstr,'lon':lonevalstr,'t':timeevalstr}
NMEARMC = BinarySensor(name='NMEA0183_RMC', regex_split=nmea_rmc_split,
                       str_format=nmea_rmc_str_format,
                       description=nmea_rmc_description,
                       example_data=nmea_rmc_test1,
                       datastream=RedvyprAddress('/k:data'),
                       datakey_metadata=nmea_datakey_metadata,
                       packetid_format=nmea_rmc_packetid_format,
                       calibration_python_str=nmea_calibration_python_str)


# TAR (temperature array)
tar_b2_test1 = b'$FC0FE7FFFE155D8C,TAR,B2,36533.125000,83117,3498.870,3499.174,3529.739,3490.359,3462.923,3467.226,3480.077,3443.092,3523.642,3525.567,3509.492,3561.330,3565.615,3486.693,3588.670,3539.169,3575.104,3523.946,3496.343,3480.160,3531.045,3501.624,3497.010,3557.235,3479.952,3458.297,3523.052,3487.223,3571.087,3525.740,3580.928,3534.818\n'
#tar_b2_split = b'\$(?P<MAC>[A-F,0-9]+),TAR,B2,(?P<counter>[0-9.]+),(?P<np>[0.9]+),(?P<TAR>[0-9.]+,*)\n'
tar_b2_split = b'\$(?P<mac>.+),TAR,B2,(?P<counter>[0-9.]+),(?P<np>[0-9]+),(?P<TAR>.*)\n'
tar_b2_str_format = {'mac':'str','counter':'float','np':'int','tar':'array'}
tar_b2_datakey_metadata = {'mac':{'unit':'mac64','description':'mac of the sensor'},'np':{'unit':'counter'},'TAR':{'unit':'Ohm'}}
tar_b2_packetid_format = 'TAR_B2_{mac}'
tar_b2_description = 'Temperature array NMEA like text format'
tar_b2 = BinarySensor(name='tar_b2', regex_split=tar_b2_split,
                       str_format=tar_b2_str_format,
                       description=tar_b2_description,
                       example_data=tar_b2_test1,
                       datakey_metadata=tar_b2_datakey_metadata,
                       packetid_format=tar_b2_packetid_format,
                       datastream=RedvyprAddress('/k:data'))


# HF (Heatflow)
HF_test1 = b'$FC0FE7FFFE1567E3,HF,00000431.3125,108,-0.000072,2774.364,2782.398,2766.746\n'
HF_test2 = b'$FC0FE7FFFE1567E3,HF,00054411.3125,13603,0.000037,2780.217,2786.642,2774.316\n'
HF_split = b'\$(?P<mac>.+),HF,(?P<counter>[0-9.]+),(?P<np>[0-9]+),(?P<HF_V>[-,\+]*[0-9.]+),(?P<NTC_R>.*)\n'
HF_str_format = {'mac':'str','counter':'float','np':'int','HF_V':'float','NTC_R':'array'}
HF_datakey_metadata = {'mac':{'unit':'mac64','description':'Mac of the sensor'},'np':{'unit':'counter'},'HF_V':{'unit':'Volt'},'NTC_R':{'unit':'Ohm'}}
HF_packetid_format = 'HF_{mac}'
HF_description = 'Heatflow sensor raw data (units are Volt and Ohm)'
HF = BinarySensor(name='HF', regex_split=HF_split,
                       str_format=HF_str_format,
                       description=HF_description,
                       example_data=HF_test1,
                       datakey_metadata=HF_datakey_metadata,
                       packetid_format=HF_packetid_format,
                       datastream=RedvyprAddress('/k:data'))


# HFS (Heatflow)
HFS_test1 = b'$FC0FE7FFFE153BDC,HFS,00182595.0000,45649,2.151728,29.609,29.561,29.631\n'
HFS_test2 = b'$FC0FE7FFFE153BDC,HFS,00182635.0000,45659,2.152100,29.609,29.560,29.631\n'
HFS_split = b'\$(?P<mac>.+),HFS,(?P<counter>[0-9.]+),(?P<np>[0-9]+),(?P<HF_Wm2>[-,\+]*[0-9.]+),(?P<T_degC>.*)\n'
HFS_str_format = {'mac':'str','counter':'float','np':'int','HF_Wm2':'float','T_degC':'array'}
HFS_datakey_metadata = {'mac':{'unit':'mac64','description':'mac of the sensor'},'np':{'unit':'counter'},'HF_Wm2':{'unit':'W m-2'},'T_degC':{'unit':'degC'}}
HFS_packetid_format = 'HFS_{mac}'
HFS_description = 'Heatflow sensor data in SI units'
HFS = BinarySensor(name='HFS', regex_split=HFS_split,
                       str_format=HFS_str_format,
                       description=HFS_description,
                       example_data=HFS_test1,
                       datakey_metadata=HFS_datakey_metadata,
                       packetid_format=HFS_packetid_format,
                       datastream=RedvyprAddress('/k:data'))


predefined_sensors = []
predefined_sensors.append(HF)
predefined_sensors.append(HFS)
predefined_sensors.append(S4LB)
predefined_sensors.append(NMEARMC)
predefined_sensors.append(tar_b2)
