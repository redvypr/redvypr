"""
sensor
function binary2raw -> dict with datakey (parameter)
generic_sensor (with optional calibrations)

"""

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
import re
import struct

from PyQt5 import QtWidgets, QtCore, QtGui
from redvypr.device import RedvyprDevice
from redvypr.data_packets import check_for_command
#from redvypr.packet_statistics import get_keys_from_data
#import redvypr.packet_statistic as redvypr_packet_statistic
from  redvypr.data_packets import create_datadict as redvypr_create_datadict
import redvypr.data_packets as data_packets
import redvypr.gui as gui
#import redvypr.config as redvypr_config
from redvypr.redvypr_address import RedvyprAddress, RedvyprAddressStr
from redvypr.devices.plot import plot_widgets
from redvypr.devices.plot import XYplotWidget
import redvypr.files as redvypr_files
from redvypr.devices.sensors.calibration.calibration_models import calibration_HF, calibration_NTC, calibration_const, calibration_poly
from redvypr.devices.sensors.csvsensors.sensorWidgets import sensorCoeffWidget, sensorConfigWidget

_icon_file = redvypr_files.icon_file

redvypr_devicemodule = True

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('generic_sensor')
logger.setLevel(logging.DEBUG)

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
    binary_format: typing.Dict = pydantic.Field(default={})
    str_format: typing.Dict = pydantic.Field(default={})


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Processing and conversion of raw data to unit using calibration models'

class DeviceCustomConfig(pydantic.BaseModel):
    sensors: typing.List[typing.Union[Sensor, BinarySensor]] = pydantic.Field(default=[], description = 'List of sensors')
    sensors2: typing.Dict[str,typing.Union[Sensor, BinarySensor]] = pydantic.Field(default=[],
                                                                                                         description='List of sensors')
    calibration_files: list = pydantic.Field(default=[])





class BinaryDataSplitter():
    """

    """
    def __init__(self, sensors=[]):
        self.regex_splitters = []
        self.sensors = sensors
        for sensor in sensors:
            sensor._str_functions = {}
            self.regex_splitters.append(sensor.regex_split)
            # Add functions for datatypes
            for key in sensor.str_format:
                vartype = sensor.str_format[key]
                print('key',key,'vartype',vartype)
                if vartype.lower() == 'float':
                    sensor._str_functions[key] = float
                elif vartype.lower() == 'int':
                    sensor._str_functions[key] = int
                elif vartype.lower() == 'str':
                    sensor._str_functions[key] = str


    def binary_process(self, binary_stream):
        matches_all = self.binary_split(binary_stream)
        data_packets = []
        for rematches,sensor in zip(matches_all,self.sensors):
            print('Match/Sensor',rematches,sensor)
            for rematch in rematches:
                data_packet = redvypr_create_datadict(device=sensor.name)
                flag_data = False
                print('Processing match',rematch)
                print('Variables found',rematch.groupdict())
                redict = rematch.groupdict()
                for keyname in redict:
                    if keyname in sensor.binary_format.keys():
                        binary_format = sensor.binary_format[keyname]
                        print('Found binary key with format',keyname, binary_format)
                        # convert the data
                        data = struct.unpack(binary_format,redict[keyname])
                        if len(data) == 1:
                            data = data[0]
                        data_packet[keyname] = data
                        flag_data = True
                    if keyname in sensor.str_format.keys():
                        print('Found str key',keyname)
                        # get the right function
                        convfunction = sensor._str_functions[keyname]
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
        :return:
        """
        matches_all = []
        for sensor in self.sensors:
            regex = sensor.regex_split
            matches = []
            print('Regex',regex,binary_stream)
            #rematch = re.search(regex, binary_stream)
            rematchiter = re.finditer(regex, binary_stream)
            rematch = [r for r in rematchiter]
            print('Match',rematch)
            matches_all.append(rematch)

        return matches_all



def start(device_info, config = None, dataqueue = None, datainqueue = None, statusqueue = None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    config = DeviceCustomConfig.model_validate(config)