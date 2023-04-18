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

import redvypr.data_packets
from redvypr.device import redvypr_device
from redvypr.data_packets import check_for_command


description = 'Device converts raw data of a sensor to meaningful units.'


config_template_poly = {}
config_template_poly['template_name']  = 'polynom'
config_template_poly['coefficients']   = {'type': 'list', 'default':[0.0,1.0],'modify': True, 'options': ['float']}
config_template_poly['unit'] = {'type':'str','default':''}
config_template_poly['address_in']  = {'type':'datastream'}
config_template_poly['device_out'] = {'type':'str','default':'{device}'}
config_template_poly['datakey_out'] = {'type':'str','default':'{datakey}'}



config_template_hf = {}
config_template_hf['template_name']  = 'heatflow'
config_template_hf['sensitivity']    = {'type':'float','default':1.0}
config_template_hf['unit'] = {'type':'str','default':'W m-2'}
config_template_hf['address_in']  = {'type':'datastream','default':'HF_mV/*'}
config_template_hf['device_out'] = {'type':'str','default':'{device}'}
config_template_hf['datakey_out'] = {'type':'str','default':'HF_Wm2'}



config_template = {}
config_template['template_name'] = "sensor_raw2unit"
config_template['sensors'] = {'type': 'list', 'modify': True, 'default':[config_template_hf], 'options': [config_template_hf, config_template_poly]}
config_template['redvypr_device'] = {}
config_template['redvypr_device']['publishes']     = True
config_template['redvypr_device']['subscribes']   = True
config_template['redvypr_device']['description'] = description


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('sensor_raw2unit')
logger.setLevel(logging.DEBUG)

def placeholder(data):
    return np.NaN

def start(device_info,config=None,dataqueue=None,datainqueue=None,statusqueue=None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    print('config',config)
    # Configure the conversion functions
    for sen in config['sensors']:
        sen['function'] = placeholder # Add a placeholder function first
        sen['raddr']    = redvypr.data_packets.redvypr_address(sen['address_in'])
        if(sen['template_name'] == 'polynom'):
            sen['function'] = np.polynomial.Polynomial(sen['coefficients'])
        if (sen['template_name'] == 'heatflow'):
            sen['function'] = np.polynomial.Polynomial([0,sen['sensitivity']])

    i = 0
    while True:
        try:
            data = datainqueue.get()
        except:
            data = None
        if(data is not None):
            command = check_for_command(data,thread_uuid=device_info['thread_uuid'])
            if (command is not None):
                logger.debug('Got a command: {:s}'.format(str(data)))
                if(command == 'stop'):
                    logger.debug('Stopping: {:s}'.format(str(command)))
                    break
            else:
                print('Got data',data)


        # loop over all sensors and check if there is a match
        datapackets_by_device = {}
        for sen in config['sensors']:
            if(data in sen['raddr']):
                print('Got a match')
                rawdata_all = sen['raddr'].get_data(data)
                for rawdata in rawdata_all:
                    print('rawdata',rawdata)
                    data_conv = sen['function'](rawdata[0])
                    # "{datakey}{device_orig}{device}".format(datakey=rawdata[1],device_orig=data['_redvypr']['device'],device=device_info['device'])
                    datakey_out = sen['datakey_out'].format(datakey=rawdata[1],device_orig=data['_redvypr']['device'],device=device_info['device'])
                    device_out = sen['device_out'].format(datakey=rawdata[1],device_orig=data['_redvypr']['device'],device=device_info['device'])
                    print('data_conv', data_conv)
                    print('datakey_out', datakey_out)
                    print('device_out', device_out)
                    # Is there already a datapacket, if yes use it for the new data, otherwise create one
                    try:
                        data_packet = datapackets_by_device[device_out]
                    except:
                        datapackets_by_device[device_out] = redvypr.data_packets.datapacket(device = device_out)
                        data_packet = datapackets_by_device[device_out]

                    data_packet[datakey_out] = data_conv
                    # Add _keyinfo
                    if len(sen['unit']) > 0:
                        redvypr.data_packets.add_keyinfo2datapacket(data_packet,unit=sen['unit'])

        # Send all packets
        for k in datapackets_by_device:
            data_out = datapackets_by_device[k]
            print('Sending packet',data_out)
            dataqueue.put(data_out)

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
            self.subscribe_address(s['address_in'])

        start(device_info, config, dataqueue, datainqueue, statusqueue)