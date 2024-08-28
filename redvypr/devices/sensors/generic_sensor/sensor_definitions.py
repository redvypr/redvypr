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
from redvypr.data_packets import create_datadict as redvypr_create_datadict, add_metadata2datapacket, Datapacket
from redvypr.redvypr_address import RedvyprAddress
from redvypr.devices.sensors.calibration.calibration_models import calibration_HF, calibration_NTC, calibration_const, \
    calibration_poly


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('sensor_definitions')
logger.setLevel(logging.DEBUG)

def decode_utf8(byte_string):
    return byte_string.decode('utf-8')


def array(byte_string):
    return list(numpy.fromstring(byte_string,sep=','))



def find_calibration_for_sensor(calibrations, sensor, data):
    """
    Searches in the calibrations list for a calibration that fits with the sensor and the data in the datapacket
    :param calibrations:
    :param sensor:
    :return:
    """
    rdata = Datapacket(data)
    for calibration in calibrations:
        print('Checking calibration',calibration)
        sn = calibration.sn
        sensor_model = calibration.sensor_model
        caldate = calibration.date
        parameter_calibrated = calibration.parameter
        # 1: Check if calibration.parameter is existing in the datapacket
        # 2: Compare serial number with packetid
        # 3: save date
        caladdr = RedvyprAddress('/i:fdsf')
        print('data',data)
        try:
            print('parameter calibrated', parameter_calibrated)
            caldata_raw = rdata[parameter_calibrated]
            print('Got caldata raw',caldata_raw)
            flag_parameter = True
        except:
            logger.info('Could not get data',exc_info=True)
            flag_parameter = False




class Sensor(pydantic.BaseModel):
    name: str = pydantic.Field(default='sensor')
    sensortype: typing.Literal['sensor'] = pydantic.Field(default='sensor')
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress('*'))
    autofindcalibration: bool = pydantic.Field(default=True, description='Tries to find automatically calibrations for the sensor')
    calibrations: typing.Dict[str, typing.Annotated[typing.Union[calibration_const, calibration_poly], pydantic.Field(
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
        print(funcname)
        try:
            self.__datapackets_checked_for_calibrations
        except:
            self.__datapackets_checked_for_calibrations = {}

        for calibration in self.__all_calibrations:
            print('Checking calibration', calibration)
            sn = calibration.sn
            sensor_model = calibration.sensor_model
            caldate = calibration.date
            parameter_calibrated = calibration.parameter
            # 1: Check if calibration.parameter is existing in the datapacket
            # 2: Compare serial number with packetid (not done yet)
            # 3: save date (not done yet)
            try:
                print('parameter calibrated', parameter_calibrated)
                caldata_raw = rdata[parameter_calibrated]
                print('Got caldata raw', caldata_raw)
                flag_parameter = True
            except:
                logger.info('Could not get data', exc_info=True)
                flag_parameter = False

            if flag_parameter:
                print('Adding calibration')
                calibration_apply = calibration.model_copy()
                calibration_apply.address_apply = calibration_apply.parameter
                #calibration_apply.datakey_result = 'test1'
                self.add_calibration_for_datapacket(rdata.address,calibration=calibration_apply)


    def datapacket_process(self, data):
        """
        Processes a redvypr datapacket.
        :param data:
        :return:
        """
        #print('Hallo self', self)
        print('Hallo data for sensor', data, data in self.datastream)
        #if data in self.datastream:
        if True: # self.datastream does not work for binary sensors
            rdata = Datapacket(data)
            rdata_addressstr = rdata.get_addressstr('/i')
            # Check if autofindcalibration shall be done
            if self.autofindcalibration:
                print('Autocalibration')
                found_calibration = False
                for datapacket_calkey in self.calibrations.keys():
                    datapacket_calkey_address = RedvyprAddress(datapacket_calkey)
                    if rdata in datapacket_calkey_address:
                        found_calibration = True
                        break

                if found_calibration == False:
                    print('Finding calibrations')
                    self.find_calibration_for_datapacket(rdata)
                    print('Done')
                else:
                    print('Found calibration already')

            # Check if there is a calibration to be found for the datapacket
            for datapacket_calkey in self.calibrations.keys():
                datapacket_calkey_address = RedvyprAddress(datapacket_calkey)
                if rdata in datapacket_calkey_address:
                    calibrations_for_packet = self.calibrations[rdata_addressstr]
                    # Loop over all calibrations for the datapacket
                    for calibration in calibrations_for_packet:
                        print('Processing calibration', calibration)
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
    datakey_metadata: typing.Dict[str, typing.Dict] = pydantic.Field(default={})
    calibrations_raw: typing.Dict[str, typing.Annotated[typing.Union[calibration_const, calibration_poly], pydantic.Field(
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
        for key_input in self.datakey_metadata.keys():
            flag_metadata = True
            metadata = self.datakey_metadata[key_input]
            data_packet = add_metadata2datapacket(data_packet, key_input, metadict=metadata)

        for key_input in self.calibrations_raw.keys():
            flag_metadata = True
            calibration = self.calibrations_raw[key_input]
            unit = calibration.unit
            unit_input = calibration.unit_input
            key_result = calibration.parameter_result
            if (key_input is not None) and (unit_input is not None):
                data_packet = add_metadata2datapacket(data_packet, key_input, metadata=unit_input)
            if (key_result is not None) and (unit is not None):
                data_packet = add_metadata2datapacket(data_packet, key_result, metadata=unit)

        #print('keyinfo_datapacket',data_packet)
        if flag_metadata:
            return data_packet
        else:
            return None
    def datapacket_process(self, data):
        """
        Processes a redvypr datapacket.
        :param data:
        :return:
        """
        #print('Hallo data', data)
        if data in self.__rdatastream__:
            binary_data = self.__rdatastream__.get_data(data)
            #print('Binary data', binary_data)
            data_packets = self.binary_process(binary_data)
            for data_packet in data_packets:
                if 't' not in data_packet.keys():
                    data_packet['t'] = data['t']

            # Check if calibrations exist, if yes, do the calibration procedure
            if (len(self.calibrations.keys()) > 0) or self.autofindcalibration:
                data_packets_calibrated = []
                for data_packet in data_packets:
                    #print('Found calibration for parameter')
                    data_packet = super().datapacket_process(data_packet)
                    data_packets_calibrated.append(data_packet)

                return data_packets_calibrated
            else: # no calibration, just return the data packets
                return data_packets

    def binary_process(self, binary_stream):
        """

        :param binary_stream:
        :return:
        """
        rematches = self.binary_split(binary_stream)
        data_packets = []
        for rematch in rematches:
            data_packet = redvypr_create_datadict(device=self.name)
            flag_data = False
            #print('Processing match', rematch)
            #print('Variables found', rematch.groupdict())
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
                            logger.debug('Could not decode data',exc_info=True)
                            data = self._str_functions_invalid_data[keyname]

                        data_packet[keyname] = data
                        flag_data = True
                        #print('Converted data to', data)

            if self.calibration_python_str is not None:
                #print('Found a python calibration eval str, applying')
                for keyname_eval in self.calibration_python_str:
                    evalcommand = self.calibration_python_str[keyname_eval]
                    evalcommand = evalcommand.split('\n')[0]
                    evalstr_full = 'data_packet[keyname_eval]=' + evalcommand
                    #print('Evalstr full',evalstr_full)
                    try:
                        exec(evalstr_full)
                    except:
                        logger.info('Could evaluate command',exc_info=True)
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
                try:
                    packetidstr = self.packetid_format.format(**data_packet)
                    data_packet['_redvypr']['packetid'] = packetidstr
                except:
                    logger.warning('Could not create an packetidstr:',exc_info=True)
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
        #print('rematch', rematch)
        return rematch



# S4L (sam4log)
s4l_split = b'B\x00(?P<counter32>[\x00-\xFF]{4})(?P<adc16>[\x00-\xFF]{2})\n'
s4l_binary_format = {'counter32': '<L','adc16':'<h'}
Vref = 3.0 # Reference voltage in V
coeff_fac = Vref/2**15
coeff_fac_counter = 1/1024
calibration_adc16 = calibration_const(parameter_result='adc(V)',coeff=coeff_fac,
                                      unit='V',unit_input='counts')
calibration_counter32 = calibration_const(parameter_result='counter(s)',coeff=coeff_fac_counter,
                                      unit='s',unit_input='counts')
calibrations_raw = {'adc16':calibration_adc16,'counter32':calibration_counter32}
S4LB = BinarySensor(name='S4LB', regex_split=s4l_split, binary_format=s4l_binary_format,
                    datastream=str(RedvyprAddress('/k:data')),
                    calibrations_raw=calibrations_raw)


# NMEA RMC
#https://de.wikipedia.org/wiki/NMEA_0183#Recommended_Minimum_Sentence_C_(RMC)
#nmea_rmc_split = b'\$[A-Z]+RMC,(?P<time>[0-9.]*),(?P<status>[A-Z]+),(?P<latdeg>[0-9]{2})(?P<latmin>[0-9.]+),(?P<NS>[NS]+),(?P<londeg>[0-9]{3})(?P<lonmin>[0-9.]+),(?P<EW>[EW]+),[0-9.]*,[0-9.]*,(?P<date>[0-9.]*),.*\n'
nmea_rmc_split = b'\$(?P<devid>[A-Z]+)RMC,(?P<time>[0-9.]+),(?P<status>[A-Z]+),(?P<latstr>[0-9.]*),(?P<NS>[NS]*),(?P<lonstr>[0-9.]*),(?P<EW>[EW]*),(?P<speed>[0-9.]*),(?P<course>[0-9.]*),(?P<date>[0-9.]+),(?P<magdev>[0-9.]*),(?P<magdevdir>[EW]*),(?P<crc>.*)\n'
nmea_rmc_str_format = {'devid':'str','time':'str','date':'str','latstr':'str','lonstr':'str','NS':'str','EW':'str','speed':'float','course':'float'}
nmea_datakey_metadata = {'time':{'unit':'HHMMSS','description':'GNSS in UTC'},'lat':{'unit':'degN'},'lon':{'unit':'degE'}}
nmea_rmc_test1 = b'$GPRMC,162614.22,A,5230.5900,N,01322.3900,E,10.0,90.0,131006,1.2,E,A*13\r\n'
#nmea_rmc_test2 = b'$GPRMC,090413.788,V,,,,,,,310724,,,N*46\r\n'
nmea_rmc_test2 = b'$GPRMC,090413,V,,,,,,,310724,,,N*46\r\n'
latevalstr = '(float(data_packet["latstr"][0:2])+float(data_packet["latstr"][2:])/60)*(float(data_packet["NS"]=="N")-float(data_packet["NS"]=="S"))'
lonevalstr = '(float(data_packet["lonstr"][0:3])+float(data_packet["lonstr"][3:])/60)*(float(data_packet["EW"]=="W")-float(data_packet["EW"]=="E"))'
timeevalstr = 'dateutil.parser.parse(data_packet["date"] + " " + data_packet["time"] + "UTC",yearfirst=False).timestamp()'
nmea_calibration_python_str = {'lat':latevalstr,'lon':lonevalstr,'t':timeevalstr}
NMEARMC = BinarySensor(name='NMEA0183_RMC', regex_split=nmea_rmc_split,
                       str_format=nmea_rmc_str_format,
                       datastream=str(RedvyprAddress('/k:data')),
                       datakey_metadata=nmea_datakey_metadata,
                       calibration_python_str=nmea_calibration_python_str)


# TAR
tar_b2_test1 = b'$FC0FE7FFFE155D8C,TAR,B2,36533.125000,83117,3498.870,3499.174,3529.739,3490.359,3462.923,3467.226,3480.077,3443.092,3523.642,3525.567,3509.492,3561.330,3565.615,3486.693,3588.670,3539.169,3575.104,3523.946,3496.343,3480.160,3531.045,3501.624,3497.010,3557.235,3479.952,3458.297,3523.052,3487.223,3571.087,3525.740,3580.928,3534.818\n'
#tar_b2_split = b'\$(?P<MAC>[A-F,0-9]+),TAR,B2,(?P<counter>[0-9.]+),(?P<np>[0.9]+),(?P<TAR>[0-9.]+,*)\n'
tar_b2_split = b'\$(?P<MAC>.+),TAR,B2,(?P<counter>[0-9.]+),(?P<np>[0-9]+),(?P<TAR>.*)\n'
tar_b2_str_format = {'MAC':'str','counter':'float','np':'int','TAR':'array'}
tar_b2_datakey_metadata = {'MAC':{'unit':'MAC64','description':'MAC of the sensor'},'np':{'unit':'counter'},'TAR':{'unit':'Ohm'}}
tar_b2_packetid_format = 'TAR_B2_{MAC}'
tar_b2 = BinarySensor(name='tar_b2', regex_split=tar_b2_split,
                       str_format=tar_b2_str_format,
                       datakey_metadata=tar_b2_datakey_metadata,
                       packetid_format=tar_b2_packetid_format,
                       datastream=str(RedvyprAddress('/k:data')))

predefined_sensors = []
predefined_sensors.append(S4LB)
predefined_sensors.append(NMEARMC)
predefined_sensors.append(tar_b2)
