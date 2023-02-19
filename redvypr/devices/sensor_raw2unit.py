"""

Device converts sensor raw data to units using conversion rules as polynomials, NTC etc ...


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
from redvypr.data_packets import check_for_command


description = 'Device converts raw data of a sensor to meaningful units.'


config_template_poly = {}
config_template_poly['template_name']  = 'polynom'
config_template_poly['coefficients']   = {'type': 'list', 'default':[0.0,1.0],'modify': True, 'options': ['float']}
config_template_poly['unit'] = {'type':'str'}
config_template_poly['datastream_in']  = {'type':'datastream'}
config_template_poly['datastream_out'] = {'type':'datastream'}


config_template_hf = {}
config_template_hf['template_name']  = 'heatflow'
config_template_hf['sensitivity']    = {'type':'float','default':1.0}
config_template_hf['unit'] = {'type':'str','default':'W kg-1'}
config_template_hf['datastream_in']  = {'type':'datastream'}
config_template_hf['datastream_out'] = {'type':'datastream'}



config_template = {}
config_template['template_name'] = "sensor_raw2unit"
config_template['sensors'] = {'type': 'list', 'modify': True, 'default':[config_template_poly], 'options': [config_template_hf, config_template_poly]}
config_template['redvypr_device'] = {}
config_template['redvypr_device']['publish']     = True
config_template['redvypr_device']['subscribe']   = True
config_template['redvypr_device']['description'] = description


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('sensor_raw2unit')
logger.setLevel(logging.DEBUG)



def start(device_info,config=None,dataqueue=None,datainqueue=None,statusqueue=None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    print('config',config)
    i = 0
    while True:
        try:
            data = datainqueue.get()
        except:
            data = None
        if(data is not None):
            command = check_for_command(data,thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                if(command == 'stop'):
                    logger.debug('Stopping: {:s}'.format(str(command)))
                break
            else:
                print('Got data',data)


        #time.sleep(0.5)


class Device(redvypr_device):
    def __init__(self, **kwargs):
        """
        """
        super(Device, self).__init__(**kwargs)

    def start(self, device_info, config, dataqueue, datainqueue, statusqueue):
        """
        Custom start function that is called by self.thread_start()

        Args:
            device_info:
            config:
            dataqueue:
            datainqueue:
            statusqueue:

        Returns:

        """
        funcname = __name__ + '.start()'
        for s in self.config['sensors']:
            print('Subscribing to',s)
            self.subscribe_address(s['datastream_in'])

        start(device_info, config, dataqueue, datainqueue, statusqueue)