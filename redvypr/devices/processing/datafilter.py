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
from redvypr.device import RedvyprDevice
from redvypr.data_packets import check_for_command

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.datafilter')
logger.setLevel(logging.DEBUG)

description = 'Filters data (average, high pass, low pass)'

redvypr_devicemodule = True
class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = description

class DeviceCustomConfig(pydantic.BaseModel):
    dt_status: float = 2.0
    messages:list = pydantic.Field(default=[])
    datakey: str = pydantic.Field(default='',description='The datakey to look for NMEA data, if empty scan all fields and use the first match')
    average: bool = False
    avg_intervals: list = [300,30,10]
    avg_dimensions: list = ['t','t','n']
    #avg_intervals: list = [2]
    #avg_dimensions: list = ['n']



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
    dtstatus = config['dt_status']
    packetbuffer_avg = {}

    #
    while True:
        data = datainqueue.get()
        command = check_for_command(data)
        if(command is not None):
            if command == 'stop':
                logger.debug('Got a stop command, stopping thread')
                break

        # Averaging the data
        if config['average']:
            try:
                packetbuffer_avg[mac]
            except:
                packetbuffer_avg[mac] = {}
            try:
                packetbuffer_avg[mac][datatype]
            except:
                packetbuffer_avg[mac][datatype] = create_avg_databuffer(config, datatype=datatype)
            try:
                for d in packetbuffer_avg[mac][datatype]:  # loop over all average buffers and do the averaging
                    packet_avg = d.append(p)
                    print('Packet avg')
                    try:
                        d.__counter__ += 1
                    except:
                        d.__counter__ = 0
                    # print('Packet avg raw',packet_avg)
                    if packet_avg is not None:
                        dpublish = redvypr.Datapacket()  # packetid=packetid_final)
                        packet_avg.update(dpublish)
                        packet_avg['mac'] = mac
                        packet_avg['np'] = d.__counter__
                        packet_avg['counter'] = d.__counter__
                        # print('Publishing average data', d.datakey_save)
                        dataqueue.put(packet_avg)
                        # print('Packet avg publish',packet_avg)
            except:
        logger.info('Could not average the data', exc_info=True)


