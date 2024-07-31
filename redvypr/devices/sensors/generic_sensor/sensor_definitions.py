import typing
from typing import Any
import datetime
import dateutil
import pydantic
import struct
import re
import sys
import logging
from redvypr.data_packets import create_datadict as redvypr_create_datadict, add_metadata2datapacket
from redvypr.redvypr_address import RedvyprAddress, RedvyprAddressStr
from redvypr.devices.sensors.calibration.calibration_models import calibration_HF, calibration_NTC, calibration_const, \
    calibration_poly


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('sensor_definitions')
logger.setLevel(logging.DEBUG)

def decode_utf8(byte_string):
    return byte_string.decode('utf-8')


class Sensor(pydantic.BaseModel):
    name: str = pydantic.Field(default='sensor')
    sensortype: typing.Literal['sensor'] = pydantic.Field(default='sensor')
    datastream: RedvyprAddressStr = pydantic.Field(default=RedvyprAddress('/k:data'))
    parameter: typing.Dict[str, typing.Annotated[typing.Union[calibration_const, calibration_poly], pydantic.Field(
        discriminator='calibration_type')]] = pydantic.Field(default={})

    def datapacket_process(self, data):
        """
        Processes a redvypr datapacket. Checks if subscription is valid and sends it to the proper sensor
        :param data:
        :return:
        """
        print('Hallo data for sensor', data)


class BinarySensor(Sensor):
    """
    A binary sensor gets binary data that need to be converted first into a dictionary with the datakeys
    """
    name: str = pydantic.Field(default='binsensor')
    sensortype: typing.Literal['binsensor'] = pydantic.Field(default='binsensor')
    regex_split: bytes = pydantic.Field(default=b'', description='Regex expression to split a binary string')
    binary_format: typing.Dict[str, str] = pydantic.Field(default={}, description='https://docs.python.org/3/library/struct.html, for example for 16bit signed data {"adc_data":"<h"}')
    str_format: typing.Dict[str, str] = pydantic.Field(default={})
    datakey_metadata: typing.Dict[str, typing.Dict] = pydantic.Field(default={})
    calibrations_raw: typing.Dict[str, typing.Annotated[typing.Union[calibration_const, calibration_poly], pydantic.Field(
        discriminator='calibration_type')]] = pydantic.Field(default={})

    calibration_python_str: typing.Optional[dict] = pydantic.Field(default=None, description='A python str that is evaluated and processes the raw data')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__rdatastream__ = RedvyprAddress(self.datastream)
        self._str_functions = {}
        self._flag_binary_keys = len(self.binary_format.keys()) > 0
        self._flag_str_format_keys = len(self.str_format.keys()) > 0
        # Add functions for datatypes
        for key in self.str_format:
            vartype = self.str_format[key]
            print('key', key, 'vartype', vartype)
            if vartype.lower() == 'float':
                self._str_functions[key] = float
            elif vartype.lower() == 'int':
                self._str_functions[key] = int
            elif vartype.lower() == 'str':
                self._str_functions[key] = decode_utf8

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

        print('keyinfo_datapacket',data_packet)
        if flag_metadata:
            return data_packet
        else:
            return None
    def datapacket_process(self, data):
        """
        Processes a redvypr datapacket. Checks if subscription is valid and sends it to the proper sensor
        :param data:
        :return:
        """
        print('Hallo data', data)
        sensors = []

        if data in self.__rdatastream__:
            binary_data = None
            binary_data = self.__rdatastream__.get_data(data)
            print('Binary data', binary_data)
            data_packets = self.binary_process(binary_data)
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
            print('Processing match', rematch)
            print('Variables found', rematch.groupdict())
            redict = rematch.groupdict()
            if self._flag_binary_keys:
                for keyname in redict:
                    if keyname in self.binary_format.keys():
                        binary_format = self.binary_format[keyname]
                        print('Found binary key with format', keyname, binary_format)
                        # convert the data
                        data = struct.unpack(binary_format, redict[keyname])
                        if len(data) == 1:
                            data = data[0]
                        data_packet[keyname] = data
                        flag_data = True


            if self._flag_str_format_keys:
                for keyname in redict:
                    if keyname in self.str_format.keys():
                        print('Found str key', keyname)
                        # get the right function
                        convfunction = self._str_functions[keyname]
                        # convert the data
                        data = convfunction(redict[keyname])
                        data_packet[keyname] = data
                        flag_data = True
                        print('Converted data to', data)

            if self.calibration_python_str is not None:
                print('Found a python calibration eval str, applying')
                for keyname_eval in self.calibration_python_str:
                    evalcommand = self.calibration_python_str[keyname_eval]
                    evalcommand = evalcommand.split('\n')[0]
                    evalstr_full = 'data_packet[keyname_eval]=' + evalcommand
                    print('Evalstr full',evalstr_full)
                    try:
                        exec(evalstr_full)
                    except:
                        logger.info('Could evaluate command',exc_info=True)
                    print('Data packet',data_packet)


            # Check for calibrations
            datakeys = list(data_packet.keys())
            for keyname in datakeys:
                # Check if there is a calibration
                if keyname in self.calibrations_raw.keys():
                    data = data_packet[keyname]
                    print('Found a calibration to convert raw data for {}'.format(keyname))
                    calibration = self.calibrations_raw[keyname]
                    try:
                        keyname_cal = calibration.parameter_result
                        if keyname_cal is None:
                            keyname_cal = keyname
                    except:
                        keyname_cal = keyname + '_cal'

                    data_cal = calibration.raw2data(data)
                    print('Data cal',data_cal)
                    data_packet[keyname_cal] = data_cal


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
        print('Regex', regex, binary_stream)
        # rematch = re.search(regex, binary_stream)
        rematchiter = re.finditer(regex, binary_stream)
        rematch = [r for r in rematchiter]
        print('rematch', rematch)
        return rematch


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


#https://de.wikipedia.org/wiki/NMEA_0183#Recommended_Minimum_Sentence_C_(RMC)
nmea_rmc_split = b'\$[A-Z]+RMC,(?P<time>[0-9.]*),(?P<status>[A-Z]+),(?P<latdeg>[0-9]{2})(?P<latmin>[0-9.]+),(?P<NS>[NS]+),(?P<londeg>[0-9]{3})(?P<lonmin>[0-9.]+),(?P<EW>[EW]+),[0-9.]*,[0-9.]*,(?P<date>[0-9.]*),.*\n'
nmea_rmc_str_format = {'time':'str','date':'str','latdeg':'float','latmin':'float','londeg':'float','lonmin':'float','NS':'str','EW':'str'}
nmea_datakey_metadata = {'time':{'unit':'HHMMSS','description':'GNSS in UTC'},'lat':{'unit':'degN'},'lon':{'unit':'degE'}}
nmea_rmc_test1 = b'$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n'
nmea_rmc_test2 = b'$GPRMC,162614.22,A,5230.5900,N,01322.3900,E,10.0,90.0,131006,1.2,E,A*13\r\n'
latevalstr = '(data_packet["latdeg"]+data_packet["latmin"]/60)*(float(data_packet["NS"]=="N")-float(data_packet["NS"]=="S"))'
lonevalstr = '(data_packet["londeg"]+data_packet["lonmin"]/60)*(float(data_packet["EW"]=="W")-float(data_packet["EW"]=="E"))'
timeevalstr = 'dateutil.parser.parse(data_packet["date"] + " " + data_packet["time"] + "UTC",yearfirst=False).timestamp()'


nmea_calibration_python_str = {'lat':latevalstr,'lon':lonevalstr,'t':timeevalstr}
#nmea_unit = {'lat':'degN','lon':'degW'}
calibration_lat = calibration_const(coeff=1.0, unit_input='degN')
calibration_lon = calibration_const(coeff=1.0, unit_input='degW')
#calibrations_nmea_rmc = {'lat':calibration_lat,'lon':calibration_lon}
NMEARMC = BinarySensor(name='NMEA0183_RMC', regex_split=nmea_rmc_split,
                       str_format=nmea_rmc_str_format,
                       datastream=str(RedvyprAddress('/k:data')),
                       datakey_metadata = nmea_datakey_metadata,
#                       calibrations_raw=calibrations_nmea_rmc,
                       calibration_python_str = nmea_calibration_python_str)

predefined_sensors = []
predefined_sensors.append(S4LB)
predefined_sensors.append(NMEARMC)
