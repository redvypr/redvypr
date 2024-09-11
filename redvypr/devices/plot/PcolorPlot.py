import datetime
import numpy as np
import logging
import sys
import threading
import copy
import yaml
import json
import typing
import pyqtgraph
import pydantic
import numpy
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
logger = logging.getLogger('pcolorplot')
logger.setLevel(logging.INFO)

start = device_start_standard


class configPcolorPlot(pydantic.BaseModel):
    location: list  = pydantic.Field(default=[])
    type: str = 'PcolorPlot'
    dt_update: float = pydantic.Field(default=0.25,description='Update time of the plot [s]')
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''))

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = 'Device to plot Pcolor-Data'
    gui_icon: str = 'ph.chart-line-fill'


#class DeviceCustomConfig(configPcolorPlot):
class DeviceCustomConfig(pydantic.BaseModel):
    location: list  = pydantic.Field(default=[])
    type: str = 'PcolorPlot'
    dt_update: float = pydantic.Field(default=0.25,description='Update time of the plot [s]')
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''))

# Use the standard start function as the start function






class PcolorPlot(QtWidgets.QWidget):
    def __init__(self, config=None, redvypr_device=None, loglevel=logging.DEBUG):
        funcname = __name__ + '.init():'
        super(QtWidgets.QWidget, self).__init__()
        self.device = redvypr_device
        if self.device is not None:
            self.redvypr = self.device.redvypr
        else:
            self.redvypr = None

        if (config == None):  # Create a config from the template
            self.config = configPcolorPlot()
        else:
            self.config = config
        self.logger = logging.getLogger('XYplot')
        self.logger.setLevel(loglevel)
        self.description = 'Pcolor plot'
        self.layout = QtWidgets.QVBoxLayout(self)
        self.data_z = []
        self.data_x = []
        self.data_y = []
        self.data_all = []
        self.create_widgets()

    def create_widgets(self):

        self.plotwidget = pyqtgraph.PlotWidget()
        self.layout.addWidget(self.plotwidget)
        #win.show()  ## show widget alone in its own window
        #z = numpy.random.rand(10,10)
        pcmi = pyqtgraph.PColorMeshItem()
        self.mesh = pcmi
        self.plotwidget.addItem(pcmi)
        axis = pyqtgraph.DateAxisItem(orientation='bottom', utcOffset=0)
        self.plotwidget.setAxisItems({"bottom": axis})

    def update_data(self,rdata):
        funcname = __name__ + '.update_data():'
        self.logger.debug(funcname + 'Got data {}'.format(rdata))
        data_plot = rdata[self.config.datastream]
        print('Data plot', data_plot)
        self.data_z.append(data_plot)
        self.data_all.append(rdata)
        self.data_x.append(rdata['t'])
        if len(self.data_x) > 2:
            try:
                z = numpy.asarray(self.data_z)
                Z = z[:-1, :]
                ny = numpy.shape(z)[1]
                nx = numpy.shape(z)[0]
                y = numpy.arange(0,ny+1)
                x = numpy.asarray(self.data_x)
                X = numpy.asarray(numpy.tile(x,(ny+1,1)))
                X = X.T
                Y = numpy.asarray(numpy.tile(y, (nx, 1)))
                #Y = Y.T
                print('x',x)
                print('X', X)
                print('y', y)
                print('Y', Y)
                print('z', z)
                print('shapes', numpy.shape(X),numpy.shape(Y),numpy.shape(Z))
                self.mesh.setData(X,Y,Z)
            except:
                logger.warning('Could not update data',exc_info=True)

class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None,tabwidget=None):
        funcname = __name__ + '__init__():'
        logger.debug(funcname)
        super(QtWidgets.QWidget, self).__init__()
        self.device = device
        self.layout = QtWidgets.QGridLayout(self)
        self.pcolorplot = PcolorPlot(redvypr_device=device, config=self.device.custom_config)
        self.layout.addWidget(self.pcolorplot)
        self.device.config_changed_signal.connect(self.config_changed)

    def config_changed(self):
        print('XYplot config changed')
        print('Config',self.device.custom_config)
        # Check if subscriptions need to be changed
        self.pcolorplot.config = self.device.custom_config
        #self.pcolorplot.apply_config()

    def update_data(self, data):
        funcname = __name__ + '.update_data():'
        try:
            print(funcname)
            print('Got data', data)
            print('Datastream', self.device.custom_config.datastream)
            #self.pcolorplot.update_plot(data)
            rdata = redvypr.data_packets.Datapacket(data)
            if rdata in self.device.custom_config.datastream:
                self.pcolorplot.update_data(rdata)

        except:
            pass
            #logger.warning(funcname + 'Could not process data',exc_info=True)