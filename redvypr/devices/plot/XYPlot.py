import datetime
import numpy as np
import logging
import sys
import threading
import copy
import yaml
import json
import typing
import pydantic
from PyQt5 import QtWidgets, QtCore, QtGui
from redvypr.device import RedvyprDevice
from redvypr.data_packets import check_for_command
#from redvypr.packet_statistics import get_keys_from_data
#import redvypr.packet_statistic as redvypr_packet_statistic
import redvypr.data_packets as data_packets
import redvypr.gui as gui
#import redvypr.config as redvypr_config
from redvypr.redvypr_address import redvypr_address
#from redvypr.devices.plot import plot_widgets
from redvypr.devices.plot import XYplotWidget
import redvypr.files as redvypr_files

_icon_file = redvypr_files.icon_file

redvypr_devicemodule = True

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('xyplot')
logger.setLevel(logging.DEBUG)


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = 'Device to plot XY-Data'




class DeviceCustomConfig(XYplotWidget.configXYplot):
    test: str='dfsd'



def start(device_info, config = None, dataqueue = None, datainqueue = None, statusqueue = None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)




class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None,tabwidget=None):
        funcname = __name__ + '__init__():'
        logger.debug(funcname)
        super(QtWidgets.QWidget, self).__init__()
        self.device = device
        self.layout        = QtWidgets.QGridLayout(self)
        self.xyplot = XYplotWidget.XYplot(redvypr_device=device)
        self.layout.addWidget(self.xyplot)
        self.device.config_changed_signal.connect(self.config_changed)

    def config_changed(self):
        print('XYplot config changed')
        print('Config',self.device.custom_config)