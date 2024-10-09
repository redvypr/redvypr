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

import redvypr
from redvypr.device import RedvyprDevice, device_start_standard
from redvypr.data_packets import check_for_command
#from redvypr.packet_statistics import get_keys_from_data
#import redvypr.packet_statistic as redvypr_packet_statistic
import redvypr.data_packets as data_packets
import redvypr.gui as gui
#import redvypr.config as redvypr_config
from redvypr.redvypr_address import RedvyprAddress
#from redvypr.devices.plot import plot_widgets
from redvypr.devices.plot import XYplotWidget
import redvypr.files as redvypr_files

_icon_file = redvypr_files.icon_file

redvypr_devicemodule = True

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('xyplot')
logger.setLevel(logging.INFO)


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = 'Device to plot XY-Data'
    gui_icon: str = 'ph.chart-line-fill'




class DeviceCustomConfig(XYplotWidget.configXYplot):
    pass


# Use the standard start function as the start function
start = device_start_standard

class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None,tabwidget=None):
        funcname = __name__ + '__init__():'
        logger.debug(funcname)
        super(QtWidgets.QWidget, self).__init__()
        self.device = device
        self.layout = QtWidgets.QGridLayout(self)
        self.xyplot = XYplotWidget.XYPlotWidget(redvypr_device=device, config=self.device.custom_config)
        self.layout.addWidget(self.xyplot)
        self.device.config_changed_signal.connect(self.config_changed)

    def config_changed(self):
        print('XYplot config changed')
        print('Config',self.device.custom_config)
        # Check if subscriptions need to be changed
        self.xyplot.config = self.device.custom_config
        self.xyplot.apply_config()

    def update_data(self, data):
        funcname = __name__ + '.update_data():'
        #print(funcname)
        self.xyplot.update_plot(data)
