import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import sys
import csv2dict
from redvypr.device import redvypr_device
from redvypr.data_packets import check_for_command



logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('csvparser')
logger.setLevel(logging.DEBUG)

description = 'Parses comma separated values (csv)'

config_template = {}
config_template['name']              = 'csvparser'
config_template['datakey']           = {'type':'str','default':'data'}
config_template['redvypr_device']    = {}
config_template['redvypr_device']['publish']   = True
config_template['redvypr_device']['subscribe'] = True
config_template['redvypr_device']['description'] = description


def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    """ zeromq receiving data
    """
    funcname = __name__ + '.start()'

    # Some variables for status
    tstatus = time.time()

    print('Version {:s}'.format(csv2dict.__version__))
    csv = csv2dict.csv2dict()
    csv.add_standard_csvdefinitions()
    csv.print_definitions()

    try:
        dtstatus = config['dtstatus']
    except:
        dtstatus = 2  # Send a status message every dtstatus seconds

    #
    npackets = 0  # Number packets received
    while True:
        data = datainqueue.get()
        command = check_for_command(data)
        if(command is not None):
            print('Got a command',command)
            break

        #print('Data',data)
        csvdata = data['data']
        dicts = csv.parse_data(csvdata)
        for k in dicts.keys(): # Loop over all packets and send them
            packet = dicts[k]
            packet['t'] = data['t']
            print('Putting',packet)
            dataqueue.put(packet)

        #print(dicts)



