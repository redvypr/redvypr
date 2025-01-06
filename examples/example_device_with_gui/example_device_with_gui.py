import copy
import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import serial
import serial.tools.list_ports
import logging
import sys
import pydantic
import typing
import redvypr.data_packets
from redvypr.data_packets import check_for_command, create_datadict
from redvypr.device import RedvyprDevice
import redvypr.files as redvypr_files
import redvypr.devices.plot.plot_widgets as redvypr_plot_widgets
import redvypr.widgets.standard_device_widgets #import redvypr_deviceInitWidget, displayDeviceWidget_standard

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('example_device_with_gui')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True


def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    i = 0
    counter = 0
    while True:
        try:
            data = datainqueue.get(block = False)
        except:
            data = None
        if(data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            if (command == 'stop'):
                logger.debug('Got a command: {:s}'.format(str(data)))
                logger.debug('Command is for me: {:s}'.format(str(command)))
                break

        data = redvypr.data_packets.create_datadict(device = device_info['device'])
        data['data'] = float(np.random.rand(1)-0.5)
        data['sometext'] = 'Hallo {}'.format(counter)
        dataqueue.put(data)
        time.sleep(1.0)


class initDeviceWidget(redvypr.widgets.standard_device_widgets.redvypr_deviceInitWidget):
    def __init__(self, *args, **kwargs):
        funcname = __name__ + '__init__():'
        logger.debug(funcname)
        super().__init__(*args, **kwargs)
class displayDeviceWidget(redvypr.widgets.standard_device_widgets.displayDeviceWidget_standard):
    def __init__(self, *args, **kwargs):
        funcname = __name__ + '__init__():'
        logger.debug(funcname)
        super().__init__(*args, **kwargs)
