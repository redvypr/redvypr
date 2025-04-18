import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import sys
import pydantic
import typing
import copy
import redvypr.data_packets
import redvypr.data_packets as data_packets
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import check_for_command
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.datafilter')
logger.setLevel(logging.DEBUG)

description = 'Filters data (average, high pass, low pass)'

redvypr_devicemodule = True
class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = description

class FilterConfig(pydantic.BaseModel):
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress('*'), description='The address of the datastream to filter')
    cutoff_freq: float = 10
    filter_type: typing.Literal['butter', 'hat'] = pydantic.Field(default='butter', description='')
    avg_dimension: typing.Optional[RedvyprAddress] = pydantic.Field(default=None, editable=True)

class AverageFilterConfig(pydantic.BaseModel):
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress('*'), description='The address of the datastream to filter')
    avg_interval: float = 10
    avg_dimension: typing.Optional[RedvyprAddress] = pydantic.Field(default=None, editable=True)

class DeviceCustomConfig(pydantic.BaseModel):
    filters: typing.List[typing.Union[AverageFilterConfig,FilterConfig]] = pydantic.Field(default=[], editable=True)


def create_avg_databuffer(config, datatype=None):
    avg_intervals = config['avg_intervals']
    avg_dimensions = config['avg_dimensions']
    avg_databuffers = []
    for avg_int,avg_dim in zip(avg_intervals,avg_dimensions):
        avg_databuffer = redvypr.utils.databuffer.DatapacketAvg(avg_dimension=avg_dim,avg_interval=avg_int,address=datatype)
        avg_databuffers.append(avg_databuffer)

    return avg_databuffers


def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    """ 
    """
    funcname = __name__ + '.start()'

    # Some variables for status
    tstatus = time.time()
    pdconfig = DeviceCustomConfig.model_validate(config)

    databuffers = []

    for f in pdconfig.filters:
        if isinstance(f,AverageFilterConfig):
            print('Average filter')
            avg_databuffer = redvypr.utils.databuffer.DatapacketAvg(avg_dimension=f.avg_dimension, avg_interval=f.avg_interval,
                                                                    address=f.datastream)
            print('databuffer',avg_databuffer)
            databuffers.append(avg_databuffer)

    #
    while True:
        data = datainqueue.get()
        command = check_for_command(data)
        if command is not None:
            if command == 'stop':
                logger.debug('Got a stop command, stopping thread')
                break

        for d in databuffers:
            packet_avg = d.append(data)
            print('Packet avg',packet_avg)
            # print('Packet avg raw',packet_avg)
            if packet_avg is not None:
                dpublish = redvypr.Datapacket()  # packetid=packetid_final)
                #packet_avg.update(dpublish)
                #packet_avg['mac'] = mac
                #packet_avg['np'] = d.__counter__
                #packet_avg['counter'] = d.__counter__
                # print('Publishing average data', d.datakey_save)
                #dataqueue.put(packet_avg)






class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)


