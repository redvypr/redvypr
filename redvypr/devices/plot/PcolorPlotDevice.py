import datetime
import numpy as np
import logging
import sys
import pyqtgraph
import pydantic
import typing
import numpy
from PyQt6 import QtWidgets, QtCore, QtGui
import redvypr
from redvypr.device import RedvyprDevice, device_start_standard
from redvypr.widgets.pydanticConfigWidget import pydanticDeviceConfigWidget
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetStartonly
from redvypr.data_packets import check_for_command
from redvypr.redvypr_address import RedvyprAddress
import redvypr.files as redvypr_files

_icon_file = redvypr_files.icon_file

redvypr_devicemodule = True

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.pcolorplot')
logger.setLevel(logging.INFO)

start = device_start_standard

class configPcolorPlot(pydantic.BaseModel):
    location: list  = pydantic.Field(default=[])
    type: str = 'PcolorPlot'
    buffersize: int = pydantic.Field(default=100,description='Size of the buffer that is used to store the plot data')
    dt_update: float = pydantic.Field(default=0.25,description='Update time of the plot [s]')
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''))
    datastreamformat: str = pydantic.Field(default='/k/i/d/h/', description='The string format of the datastream')
    collevel_auto: bool = pydantic.Field(default=True, description='If true colorlevels will be set automatically')
    collevel_min: typing.Optional[float] = pydantic.Field(default=None, description='Minimum color level')
    collevel_max: typing.Optional[float] = pydantic.Field(default=None, description='Maximum color level')

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
    datastreamformat: str = pydantic.Field(default='/k/i/d/h/', description='The string format of the datastream')
    collevel_auto: bool = pydantic.Field(default=True, description='If true colorlevels will be set automatically')
    collevel_min: typing.Optional[float] = pydantic.Field(default=None, description='Minimum color level')
    collevel_max: typing.Optional[float] = pydantic.Field(default=None, description='Maximum color level')


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

        if config is None:  # Create a config from the template
            self.config = configPcolorPlot()
        else:
            self.config = config

        self.config_backup = self.config.model_dump()
        self.logger = logging.getLogger('redvypr.PcolorPlot')
        self.logger.setLevel(loglevel)
        self.description = 'Pcolor plot'
        self.layout = QtWidgets.QGridLayout(self)
        self.levels = None
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
        self.startAction.setText('Stop')

    def device_thread_stopped(self):
        self.startAction.setText('Start')

    def pyqtgraphAddressAction(self):
        if self.device is not None:
            self.configWidget = redvypr.widgets.redvyprAddressWidget.RedvyprAddressWidget(redvypr=self.redvypr,
                                                                                          device=self.device)
            self.configWidget.setWindowTitle('Address for {}'.format(self.device.name))
            self.configWidget.apply.connect(self.apply_config_address)
            self.configWidget._pcolor = self.sender()._pcolor
            self.configWidget.show()

    def pyqtgraphClearBufferAction(self):
        self.logger.debug('Clearing buffer')
        self.data_z = []
        self.data_x = []
        self.data_y = []
        self.data_all = []
        z = numpy.random.rand(10, 10) * 0
        self.mesh.setData(z)

    def pyqtgraphLevelAction(self):
        self.config.collevel_auto = self.autolevelcheck.isChecked()

    def pyqtgraphConfigAction(self):
        if self.device is not None:
            self.config_widget = pydanticDeviceConfigWidget(self.device)
            self.config_widget.showMaximized()

    def apply_config_address(self, address_dict):
        funcname = __name__ + '.apply_config_address():'
        self.logger.debug(funcname)
        pcolor = self.sender()._pcolor
        # print('Line',line,line.y_addr)
        # line.y_addr = address_dict['datastream_str']
        #print('Address dict', address_dict)
        self.device.custom_config.datastream = redvypr.RedvyprAddress(address_dict['datastream_address'])
        # print('Line config',line.confg)
        self.applyConfig()

    def applyConfig(self):
        funcname = __name__ + '.applyConfig():'
        self.logger.debug(funcname)
        self.setTitle()
        try:
            self.device.subscribe_address(self.config.datastream)
        except:
            self.logger.warning('Could not subscribe to address: "{}"'.format(self.config.datastream))

    def setTitle(self):
        titlestr = 'Datastream: ' + self.config.datastream.get_str(self.config.datastreamformat)
        self.plotwidget.setTitle(titlestr)

    def create_widgets(self):
        self.graphiclayout = pyqtgraph.GraphicsLayoutWidget()
        self.plotwidget = self.graphiclayout.addPlot()
        self.setTitle()
        # Modify the right-click menu
        self.plotwidget.vb.menu.clear()
        # Add the general config
        addressAction = self.plotwidget.vb.menu.addAction('Address')
        addressAction.triggered.connect(self.pyqtgraphAddressAction)
        # Add the general config
        clearbufAction = self.plotwidget.vb.menu.addAction('Clear Buffer')
        clearbufAction.triggered.connect(self.pyqtgraphClearBufferAction)
        # Add the general config
        configAction = self.plotwidget.vb.menu.addAction('General config')
        configAction.triggered.connect(self.pyqtgraphConfigAction)

        self.startAction = self.plotwidget.vb.menu.addAction('Start')
        self.startAction.triggered.connect(self.thread_startstop)



        z = numpy.random.rand(10,10)
        pcmi = pyqtgraph.PColorMeshItem()
        pcmi.setData(z)
        cmenu = pyqtgraph.ColorMapMenu(showColorMapSubMenus=True)
        autolevelcheck = QtWidgets.QCheckBox('Automatic Colorlevel')
        self.autolevelcheck = autolevelcheck
        autolevelcheck.setChecked(self.config.collevel_auto)
        autolevelcheck.stateChanged.connect(self.pyqtgraphLevelAction)
        autolevelAction = QtWidgets.QWidgetAction(self)
        autolevelAction.setDefaultWidget(autolevelcheck)
        self.autolevelAction = cmenu.addAction(autolevelAction)
        colbar = pyqtgraph.ColorBarItem(rounding=0.01,colorMapMenu=cmenu)
        colbar.setImageItem(pcmi)

        self.mesh = pcmi
        self.colorbar = colbar
        colbar.sigLevelsChangeFinished.connect(self.colorlevels_changed)
        self.plotwidget.addItem(pcmi)
        self.graphiclayout.addItem(colbar)
        axis = pyqtgraph.DateAxisItem(orientation='bottom', utcOffset=0)
        self.plotwidget.setAxisItems({"bottom": axis})
        self.layout.addWidget(self.graphiclayout, 0, 0, 1, 2)

        addressAction._pcolor = pcmi

    def colorlevels_changed(self):

        levels = self.colorbar.levels()
        self.levels = levels
        self.mesh.setLevels(self.levels)
        print('Scale',self.levels)

    def update_data(self,rdata):
        funcname = __name__ + '.update_data():'
        self.logger.debug(funcname + 'Got data to plot {}'.format(rdata.address))
        data_plot = rdata[self.config.datastream]
        #print('Data to plot', data_plot)
        try:
            if len(self.data_x) > self.config.buffersize:
                self.logger.debug('Bufferoverflow')
                self.data_z.pop(0)
                self.data_all.pop(0)
                self.data_x.pop(0)

            self.data_z.append(data_plot)
            self.data_all.append(rdata)
            self.data_x.append(rdata['t'])
        except:
            self.logger.warning('Could append update data', exc_info=True)

        if len(self.data_x) > 2:
            try:
                print('Plotting')
                #print(self.data_z)
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
                #print('x',x)
                #print('X', X)
                #print('y', y)
                #print('Y', Y)
                #print('z', z)
                #print('shapes', numpy.shape(X),numpy.shape(Y),numpy.shape(Z))
                #levels_old = self.mesh.getLevels()
                #print('levels', self.levels,self.mesh.getLevels())
                self.mesh.setData(X,Y,Z)
                if self.levels is not None:
                    if self.config.collevel_auto:
                        self.levels = self.mesh.getLevels()
                    else:
                        self.mesh.setLevels(self.levels)
                    #print('Set levels', self.levels)
            except:
                print('Problem')
                self.logger.info('Could not update data', exc_info=True)
                logger.warning('Could not update data',exc_info=True)

class RedvyprDeviceWidget(RedvyprdevicewidgetStartonly):
    def __init__(self,*args,**kwargs):
        funcname = __name__ + '__init__():'
        logger.debug(funcname)
        super().__init__(*args,**kwargs)
        #self.layout = QtWidgets.QGridLayout(self)
        self.pcolorplot = PcolorPlotWidget(redvypr_device=self.device, config=self.device.custom_config)
        self.layout.addWidget(self.pcolorplot)
        self.device.config_changed_signal.connect(self.config_changed)

    def config_changed(self):
        #print('PcolorPlotDevice config changed')
        #print('Config',self.device.custom_config)
        # Check if subscriptions need to be changed
        self.pcolorplot.config = self.device.custom_config
        self.pcolorplot.applyConfig()

    def update_data(self, data):
        funcname = __name__ + '.update_data():'
        try:
            #print(funcname)
            #print('Got data', data)
            #print('Datastream', self.device.custom_config.datastream)
            rdata = redvypr.data_packets.Datapacket(data)
            if rdata in self.device.custom_config.datastream:
                self.pcolorplot.update_data(rdata)

        except:
            self.logger.warning(funcname + 'Could not process data',exc_info=True)