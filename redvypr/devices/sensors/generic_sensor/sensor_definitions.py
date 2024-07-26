import typing
from typing import Any

import pydantic
import struct
import re
from  redvypr.data_packets import create_datadict as redvypr_create_datadict
from redvypr.redvypr_address import RedvyprAddress, RedvyprAddressStr
from redvypr.devices.sensors.calibration.calibration_models import calibration_HF, calibration_NTC, calibration_const, calibration_poly

class Sensor(pydantic.BaseModel):
    name: str = pydantic.Field(default='sensor')
    sensortype: typing.Literal['sensor'] = pydantic.Field(default='sensor')
    datastream: RedvyprAddressStr = '*'
    parameter: typing.Dict[str,typing.Annotated[typing.Union[calibration_const, calibration_poly], pydantic.Field(discriminator='calibration_type')]]  = pydantic.Field(default={})

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
    binary_format: typing.Dict[str, str] = pydantic.Field(default={'data_char':'c'})
    str_format: typing.Dict[str, str] = pydantic.Field(default={'data_float':'float'})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print('Hallo')

        self.__rdatastream__ = RedvyprAddress(self.datastream)
        self._str_functions = {}
        # Add functions for datatypes
        for key in self.str_format:
            vartype = self.str_format[key]
            print('key', key, 'vartype', vartype)
            if vartype.lower() == 'float':
                self._str_functions[key] = float
            elif vartype.lower() == 'int':
                self._str_functions[key] = int
            elif vartype.lower() == 'str':
                self._str_functions[key] = str

    def datapacket_process(self, data):
        """
        Processes a redvypr datapacket. Checks if subscription is valid and sends it to the proper sensor
        :param data:
        :return:
        """
        print('Hallo data',data)
        sensors = []

        if data in self.__rdatastream__:
            binary_data = None
            binary_data = self.__rdatastream__.get_data(data)
            print('Binary data',binary_data)
            self.binary_process(binary_data)


    def binary_process(self, binary_stream):
        """

        :param binary_stream:
        :return:
        """
        rematches = self.binary_split(binary_stream)
        data_packets = []
        if True:
            for rematch in rematches:
                data_packet = redvypr_create_datadict(device=self.name)
                flag_data = False
                print('Processing match',rematch)
                print('Variables found',rematch.groupdict())
                redict = rematch.groupdict()
                for keyname in redict:
                    if keyname in self.binary_format.keys():
                        binary_format = self.binary_format[keyname]
                        print('Found binary key with format',keyname, binary_format)
                        # convert the data
                        data = struct.unpack(binary_format,redict[keyname])
                        if len(data) == 1:
                            data = data[0]
                        data_packet[keyname] = data
                        flag_data = True
                    if keyname in self.str_format.keys():
                        print('Found str key',keyname)
                        # get the right function
                        convfunction = self._str_functions[keyname]
                        # convert the data
                        data = convfunction(redict[keyname])
                        data_packet[keyname] = data
                        flag_data = True
                        print('Converted data to',data)

                if flag_data:
                    data_packets.append(data_packet)

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
        print('Regex',regex,binary_stream)
        #rematch = re.search(regex, binary_stream)
        rematchiter = re.finditer(regex, binary_stream)
        rematch = [r for r in rematchiter]
        print('rematch',rematch)
        return rematch


s4l_split = b'B\x00(?P<counter32>[\x00-\xFF]{4})(?P<adc16>[\x00-\xFF]{2})\n'
S4LB = BinarySensor(name='S4LB', regex_split=s4l_split,datastream=str(RedvyprAddress('/k:data')))
NMEARMC = BinarySensor(name='NMEA0183_RMC', regex_split=s4l_split)

predefined_sensors = []
predefined_sensors.append(S4LB)
predefined_sensors.append(NMEARMC)