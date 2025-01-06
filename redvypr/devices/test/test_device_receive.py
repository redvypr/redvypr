"""

The most simple test device

"""


import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
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
logger = logging.getLogger('test_device_receive')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True
description: str = 'A very basic redvypr device that receives data and prints it'
def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    print('Device info',device_info)
    logger_start = logging.getLogger('Devicename: {}'.format(device_info['name']))
    logger_start.setLevel(logging.DEBUG)
    funcname = __name__ + '.start():'
    logger_start.debug(funcname)
    logger_start.info(funcname + 'Config {}'.format(config))
    while True:
        data = datainqueue.get(block = True)
        if(data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            logger_start.info('Got a command: {:s}'.format(str(data)))
            if (command == 'stop'):
                logger_start.info('Command is for me: {:s}'.format(str(command)))
                break

            logger.info('Got data:{}'.format(data))




