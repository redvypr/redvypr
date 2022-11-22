"""

zeromq device

Configuration options for a network device:

.. code-block::

- devicemodulename: network_device  
  deviceconfig:
    name: tcpserial1 # The name, must be unique
    config:
       address: <ip> # Address IP, localhost. <broadcast> for UDP broadcast in local network. <ip> for local ip
       port: 10001 # Port
       serialize: str # yaml,str default yaml
       protocol: tcp # tcp, udp default tcp
       direction: publish # publish, receive default receive
       data: nmea # dictionary keys, default all
       tcp_reconnect: True # Try to reconnect to host if connection was closed
       tcp_numreconnect: 10 # The number of reconnection attempts
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
#from apt_pkg import config
import yaml
import copy
import zmq
import socket
from redvypr.device import redvypr_device
from redvypr.data_packets import check_for_command



zmq_context = zmq.Context()
description = 'A simple test device'

config_template = {}
config_template['string_send']    = {'type': 'str','default':'Hello World!'}
config_template['delay_s']        = {'type': 'float','default':2}
config_template['redvypr_device'] = {}
config_template['redvypr_device']['publish']     = True
config_template['redvypr_device']['subscribe']   = False
config_template['redvypr_device']['description'] = description


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('test_device')
logger.setLevel(logging.DEBUG)



def start(device_info,config=None,dataqueue=None,datainqueue=None,statusqueue=None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    print('config',config)
    i = 0
    while True:
        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if(data is not None):
            command = check_for_command(data,thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                logger.debug('Command is for me: {:s}'.format(str(command)))
                break

        dstr = config['string_send']
        print(dstr)
        dataqueue.put(dstr)
        dataqueue.put({'count':i})
        i+=1
        time.sleep(config['delay_s'])
        



