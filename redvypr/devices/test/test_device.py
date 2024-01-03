"""

test device

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
from redvypr.device import redvypr_device
import redvypr.data_packets
from redvypr.data_packets import check_for_command
import pydantic


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('test_device')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True
class device_base_config(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = 'A simple test device'

class device_config(pydantic.BaseModel):
    delay_s: float = 1.0



def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    print('Config',config)
    pdconfig = device_config.model_validate(config)
    print('pdconfig',pdconfig)
    #data = {'_keyinfo':config['_keyinfo']}
    # dataqueue.put(data)
    # Send a datapacket with information once (that will be put into the statistics)
    datapacket_info = redvypr.data_packets.add_keyinfo2datapacket(datapacket={}, datakey='sine_rand', unit='random unit', description='sinus with random data', infokey='mac', info='ABCDEF1234')
    dataqueue.put(datapacket_info)

    i = 0
    while True:
        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if(data is not None):
            command = check_for_command(data,thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command: {:s}'.format(str(data)))
            if (command == 'stop'):
                logger.debug('Command is for me: {:s}'.format(str(command)))
                break

        data = redvypr.data_packets.datapacket(device = device_info['device'])
        time.sleep(config['delay_s'])
        



