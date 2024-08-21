"""

The most simple test device

"""


import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import threading
import copy
from redvypr.device import RedvyprDeviceCustomConfig, RedvyprDevice
import redvypr.data_packets
from redvypr.data_packets import check_for_command
import pydantic


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('calibration_autocal_test')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True
description: str = 'A test device for the autocalibration feature of the the calibration device'
def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    print('Config',config)
    temp_set = 20.0
    temp = 10.0
    t_lowpass = 10
    dt_wait = 0.5
    i = 0
    counter = 0
    while True:
        try:
            data = datainqueue.get(block = False)
        except:
            data = None
        if(data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command: {:s}'.format(str(data)))
            if (command == 'stop'):
                logger.debug('Command is for me: {:s}'.format(str(command)))
                break
            elif (command == 'set'):
                logger.debug('Command is for me: {:s}'.format(str(command)))
                temp_set = data['temp']

        dT = temp - temp_set
        temp = temp - dT * dt_wait/t_lowpass
        print('Temp',temp,'dT',dT,dT * dt_wait/t_lowpass)
        data = {}#redvypr.data_packets.create_datadict(device = device_info['device'])
        data['temp'] = temp
        data['temp_set'] = temp_set
        if abs(temp - temp_set)<0.001:
            data['temp_reached'] = 1
        else:
            data['temp_reached'] = 0

        dataqueue.put(data)
        time.sleep(dt_wait)




