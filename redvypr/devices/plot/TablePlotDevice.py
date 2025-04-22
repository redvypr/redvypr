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
from redvypr.devices.plot import TablePlotWidget
import redvypr.files as redvypr_files

_icon_file = redvypr_files.icon_file

redvypr_devicemodule = True

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.tableplot')
logger.setLevel(logging.INFO)


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = 'Device to plot Data in a table'
    gui_icon: str = 'ph.table'


class DeviceCustomConfig(TablePlotWidget.ConfigTablePlot):
    pass


# Use the standard start function as the start function
start = device_start_standard


class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        funcname = __name__ + '__init__():'
        logger.debug(funcname)
        super().__init__(*args,**kwargs)
        self.tablewidget = TablePlotWidget.TablePlotWidget()
        self.layout.addWidget(self.tablewidget)
        self.device.config_changed_signal.connect(self.config_changed)

    def config_changed(self):
        funcname = __name__ + '.config_changed():'
        logger.debug(funcname)

    def update_data(self, data, force_update = False):
        funcname = __name__ + '.update_data():'
        logger.debug(funcname)
        print('update data',data)
        try:
            self.tablewidget.update_data(data)
        except:
            logger.info('Could not update data',exc_info=True)