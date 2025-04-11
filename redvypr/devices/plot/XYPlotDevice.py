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
from PyQt6 import QtWidgets, QtCore, QtGui
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetStartonly, RedvyprdevicewidgetSimple

import redvypr
from redvypr.device import RedvyprDevice, device_start_standard
from redvypr.data_packets import check_for_command
import redvypr.data_packets as data_packets
import redvypr.gui as gui
from redvypr.redvypr_address import RedvyprAddress
from redvypr.devices.plot import XYplotWidget
import redvypr.files as redvypr_files

_icon_file = redvypr_files.icon_file

redvypr_devicemodule = True

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.xyplot')
logger.setLevel(logging.INFO)


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Device to plot XY-Data'
    gui_icon: str = 'ph.chart-line-fill'


class DeviceCustomConfig(XYplotWidget.configXYplot):
    pass


# Use the standard start function as the start function
start = device_start_standard


class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        funcname = __name__ + '__init__():'
        logger.debug(funcname)
        super().__init__(*args,**kwargs)
        self.xyplot = XYplotWidget.XYPlotWidget(redvypr_device=self.device, config=self.device.custom_config,
                                                loglevel=self.device.loglevel)
        self.layout.addWidget(self.xyplot)
        self.device.config_changed_signal.connect(self.config_changed)
        total_height = self.splitter.height()
        upper_size = int(total_height * 1.0)
        lower_size = total_height - upper_size
        self.splitter.setSizes([upper_size, lower_size])
        # Add a start button to the menu
        self.device.thread_started.connect(self.device_thread_started)
        self.device.thread_stopped.connect(self.device_thread_stopped)
        self.startAction = self.xyplot.plotWidget.plotItem.vb.menu.addAction('Start')
        self.startAction.triggered.connect(self.thread_startstop)

    def thread_startstop(self):
        if 'start' in self.startAction.text().lower():
            self.device.thread_start()
            return

        if 'stop' in self.startAction.text().lower():
            self.device.thread_stop()
            return

    def device_thread_started(self):
        self.startAction.setText('Stop')

    def device_thread_stopped(self):
        self.startAction.setText('Start')

    def config_changed(self):
        funcname = __name__ + '.config_changed():'
        logger.debug(funcname)
        # Check if subscriptions need to be changed
        self.xyplot.config = self.device.custom_config
        self.xyplot.apply_config()

    def update_data(self, data, force_update = False):
        funcname = __name__ + '.update_data():'
        # print(funcname)
        self.xyplot.update_plot(data, force_update)



