import datetime
import numpy as np
import logging
import sys
import pyqtgraph
import pydantic
import numpy
from PyQt6 import QtWidgets, QtCore, QtGui
import redvypr
from redvypr.device import RedvyprDevice, device_start_standard
from redvypr.widgets.pydanticConfigWidget import pydanticDeviceConfigWidget
from redvypr.widgets.standard_device_widgets import RedvyprDeviceWidget_startonly
from redvypr.data_packets import check_for_command
from redvypr.redvypr_address import RedvyprAddress
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
    buffersize: int = pydantic.Field(default=100,description='Size of the buffer that is used to store the plot data')
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
    buffersize: int = pydantic.Field(default=100, description='Size of the buffer that is used to store the plot data')
    dt_update: float = pydantic.Field(default=0.25, description='Update time of the plot [s]')
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''))

# Use the standard start function as the start function
class PcolorPlotWidget(QtWidgets.QWidget):
    def __init__(self, config=None, redvypr_device=None, loglevel=logging.DEBUG):
        funcname = __name__ + '.init():'
        super(QtWidgets.QWidget, self).__init__()
        self.device = redvypr_device
        if self.device is not None:
            self.redvypr = self.device.redvypr
            self.device.thread_started.connect(self.device_thread_started)
            self.device.thread_stopped.connect(self.device_thread_stopped)
        else:
            self.redvypr = None

        if (config == None):  # Create a config from the template
            self.config = configPcolorPlot()
        else:
            self.config = config

        self.config_backup = self.config.model_dump()
        self.logger = logging.getLogger('PcolorPlot')
        self.logger.setLevel(loglevel)
        self.description = 'Pcolor plot'
        self.layout = QtWidgets.QGridLayout(self)
        self.data_z = []
        self.data_x = []
        self.data_y = []
        self.data_all = []
        self.create_widgets()
        self.applyConfig()

    def thread_startstop(self):
        if 'start' in self.startAction.text().lower():
            self.device.thread_start()
            return

        if 'stop' in self.startAction.text().lower():
            self.device.thread_stop()
            return

    def device_thread_started(self):
        print('started')
        self.startAction.setText('Stop')

    def device_thread_stopped(self):
        print('stopped')
        self.startAction.setText('Start')

    def pyqtgraphConfigAction(self):
        if self.device is not None:
            self.config_widget = pydanticDeviceConfigWidget(self.device)
            self.config_widget.showMaximized()

    def applyConfig(self):
        funcname = __name__ + '.applyConfig():'
        self.logger.debug(funcname)
        self.setTitle()
        try:
            self.device.subscribe_address(self.config.datastream)
        except:
            self.logger.warning('Could not subscribe to address: "{}"'.format(self.config.datastream))

    def setTitle(self):
        titlestr = str(self.config.datastream)
        self.plotwidget.setTitle(titlestr)

    def create_widgets(self):
        self.graphiclayout = pyqtgraph.GraphicsLayoutWidget()
        self.plotwidget = self.graphiclayout.addPlot()
        self.setTitle()
        # Modify the right-click menu
        #self.plotwidget.vb.menu.clear()
        # Add the general config
        configAction = self.plotwidget.vb.menu.addAction('General config')
        configAction.triggered.connect(self.pyqtgraphConfigAction)

        self.startAction = self.plotwidget.vb.menu.addAction('Start')
        self.startAction.triggered.connect(self.thread_startstop)
        z = numpy.random.rand(10,10)
        pcmi = pyqtgraph.PColorMeshItem()
        pcmi.setData(z)
        colbar = pyqtgraph.ColorBarItem()
        colbar.setImageItem(pcmi)
        self.mesh = pcmi
        self.plotwidget.addItem(pcmi)
        self.graphiclayout.addItem(colbar)
        axis = pyqtgraph.DateAxisItem(orientation='bottom', utcOffset=0)
        self.plotwidget.setAxisItems({"bottom": axis})
        self.layout.addWidget(self.graphiclayout, 0, 0, 1, 2)

    def update_data(self,rdata):
        funcname = __name__ + '.update_data():'
        self.logger.debug(funcname + 'Got data to plot {}'.format(rdata))
        data_plot = rdata[self.config.datastream]
        print('Data to plot', data_plot)
        try:
            if len(self.data_x) > self.config.buffersize:
                print('Bufferoverflow')
                self.data_z.pop(0)
                self.data_all.pop(0)
                self.data_x.pop(0)

            self.data_z.append(data_plot)
            self.data_all.append(rdata)
            self.data_x.append(rdata['t'])
        except:
            logger.warning('Could append update data', exc_info=True)
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

class RedvyprDeviceWidget(RedvyprDeviceWidget_startonly):
    def __init__(self,*args,**kwargs):
        funcname = __name__ + '__init__():'
        logger.debug(funcname)
        super().__init__(*args,**kwargs)
        #self.layout = QtWidgets.QGridLayout(self)
        self.pcolorplot = PcolorPlotWidget(redvypr_device=self.device, config=self.device.custom_config)
        self.layout.addWidget(self.pcolorplot)
        self.device.config_changed_signal.connect(self.config_changed)

    def config_changed(self):
        print('PcolorPlotDevice config changed')
        print('Config',self.device.custom_config)
        # Check if subscriptions need to be changed
        self.pcolorplot.config = self.device.custom_config
        self.pcolorplot.applyConfig()

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