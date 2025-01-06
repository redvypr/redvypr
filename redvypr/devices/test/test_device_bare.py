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
logger = logging.getLogger('test_device_bare')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True
description: str = 'The most basic redvypr device'
def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    print('Config',config)
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

        data = redvypr.data_packets.create_datadict(device = device_info['device'])
        data['data'] = float(np.random.rand(1)-0.5)
        data['sometext'] = 'Hallo {}'.format(counter)
        dataqueue.put(data)
        time.sleep(1.0)




