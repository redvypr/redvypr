import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import yaml
import copy
import pyqtgraph
import pyqtgraph.dockarea
import qtawesome
import pydantic
import typing
import redvypr.data_packets
from redvypr.device import RedvyprDevice
from redvypr.gui import iconnames
#from redvypr.gui import configWidget
#from redvypr.devices.plot.plot_widgets import redvypr_numdisp_widget, redvypr_graph_widget, config_template_numdisp, config_template_graph
from redvypr.devices.plot.XYPlotWidget import XYPlotWidget
import redvypr.files as files
from redvypr.device import device_start_standard
from redvypr.data_packets import check_for_command
#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict
#from redvypr.configdata import configdata, getdata

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.plot')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Allows to send data manually'
    gui_icon: str = 'ph.chart-line-fill'


class PlotConfig(pydantic.BaseModel):
    plottype: typing.Literal['XY-Plot'] = pydantic.Field(default='XY-Plot')
    docklabel: str = pydantic.Field(default='Dock')
    location: typing.Literal['left','right','top','bottom'] = pydantic.Field(default='left')


class DeviceCustomConfig(pydantic.BaseModel,extra='allow'):
    #plots: list = pydantic.Field(default=[])
    plots: typing.Optional[typing.Dict[str,PlotConfig]] = pydantic.Field(default={}, editable=True)
    dockstate: typing.Optional[dict] = pydantic.Field(default=None)


# Use the standard start function as the start function
start = device_start_standard

class Device(RedvyprDevice):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)

    def get_config(self):
        config = super().get_config()
        state = self.redvyprdevicewidget.dockarea.saveState()
        config.custom_config.dockstate = state
        return config


class PlotDock(pyqtgraph.dockarea.Dock):
    labelClicked = QtCore.pyqtSignal()  #
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs, closable=True)
        self.label.sigClicked.connect(self.__labelClicked)

    def __labelClicked(self):
        self.labelClicked.emit()

    def mousePressEvent(self, ev):
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        super().mouseDoubleClickEvent(ev)


class RedvyprDeviceWidget(redvypr.widgets.standard_device_widgets.RedvyprdevicewidgetStartonly):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        layout = QtWidgets.QGridLayout(self)
        self.dockarea = pyqtgraph.dockarea.DockArea()
        self.plot_widgets = {}
        self.numdocks = 1
        if len(self.device.custom_config.plots.keys()) == 0:
            # This adds a plot, if not existing already
            xyplotconfig = PlotConfig(plottype='XY-Plot',docklabel='Dock 1')
            self.add_plot_to_config(xyplotconfig)

        self.add_plots_from_config()
        menu = QtWidgets.QMenu()
        menu_XYplot = QtWidgets.QMenu('XY-Plot',self)
        menu.addMenu(menu_XYplot)
        addAction = QtWidgets.QWidgetAction(self)
        # Create add XYPlot-Menu
        addMenuWidget = QtWidgets.QWidget()
        addMenuWidget_layout = QtWidgets.QVBoxLayout(addMenuWidget)
        comboXYplotlocation = QtWidgets.QComboBox()
        comboXYplotlocation.addItem('Left')
        comboXYplotlocation.addItem('Right')
        comboXYplotlocation.addItem('Top')
        comboXYplotlocation.addItem('Bottom')
        addButton = QtWidgets.QPushButton('Add')
        addButton.clicked.connect(self.__add_xy_clicked)
        dockname_str = "Dock {}".format(self.numdocks)
        dockName = QtWidgets.QLineEdit(dockname_str)
        addButton.__comboXYplotlocation = comboXYplotlocation
        addButton.__dockName = dockName
        addButton.__addwidget_bare = XYPlotWidget
        addButton.__plottype = 'XY-Plot'
        addMenuWidget_layout.addWidget(dockName)
        addMenuWidget_layout.addWidget(comboXYplotlocation)
        addMenuWidget_layout.addWidget(addButton)
        addAction.setDefaultWidget(addMenuWidget)
        menu_XYplot.addAction(addAction)

        #icon = qtawesome.icon(iconnames['settings'])
        # self.settings_button = QtWidgets.QPushButton('Settings')
        # self.settings_button.setIcon(icon)
        self.add_button = QtWidgets.QPushButton('Add')
        self.add_button.setMenu(menu)


        #self.settings_button.clicked.connect(self.settings_clicked)
        self.layout.removeWidget(self.buttons_widget)
        self.layout.removeWidget(self.killbutton)
        self.killbutton.hide()

        self.layout.addWidget(self.dockarea,0,0)
        self.layout.addWidget(self.buttons_widget, 1, 0)
        self.layout_buttons.addWidget(self.add_button, 0, 4)
        #self.layout_buttons.addWidget(self.settings_button, 0, 6)

    def add_plot_to_config(self, plotconfig):
        funcname = __name__ + '.add_plot_to_config():'
        docklabel = plotconfig.docklabel
        if docklabel in self.device.custom_config.plots:
            logger.warning(funcname + 'Could not add plot {}'.format(docklabel))
        else:
            self.device.custom_config.plots[docklabel] = plotconfig
    def add_plot_from_config(self, plotconfig):
        funcname = __name__ + '.add_plot_from_config():'
        docklabel = plotconfig.docklabel
        if docklabel in self.plot_widgets:
            logger.warning(funcname + 'Plot {} exists already'.format(docklabel))
        else:
            logger.debug(funcname + 'Adding plot {}'.format(plotconfig))
            # Test the dockarea
            dock = PlotDock(plotconfig.docklabel, size=(1, 1))  # give this dock the minimum possible size
            if plotconfig.plottype == 'XY-Plot':
                plotwidget = XYPlotWidget(redvypr_device=self.device)
            else:
                raise 'Unknown plottype'

            self.plot_widgets[docklabel] = plotwidget
            dock.addWidget(plotwidget)
            self.dockarea.addDock(dock, plotconfig.location)
            self.numdocks += 1

    def add_plots_from_config(self):
        funcname = __name__ + '.add_plots_from_config():'
        for docklabel in self.device.custom_config.plots:
            d = self.device.custom_config.plots[docklabel]
            self.add_plot_from_config(d)

        dockstate = self.device.custom_config.dockstate
        if dockstate is not None:
            logger.debug(funcname + 'Found dockstate, will apply')
            self.dockarea.restoreState(dockstate)
            # Remove dockstate
            self.device.custom_config.dockstate = None

    def __add_xy_clicked(self):
        button = self.sender()
        position = button.__comboXYplotlocation.currentText().lower()
        dockname_str = button.__dockName.text()
        plottype_str = button.__plottype
        plotconfig = PlotConfig(plottype=plottype_str, docklabel=dockname_str,location=position)
        logger.debug('Adding plot {}'.format(plotconfig))
        self.add_plot_to_config(plotconfig)
        self.add_plots_from_config()
        dockname_str = "Dock {}".format(self.numdocks)
        button.__dockName.setText(dockname_str)

    def __dockclosed(self):
        dock = self.sender()
        for w in dock.widgets:
            for k in self.plot_widgets:
                if w == self.plot_widgets[k]:
                    wdict = self.plot_widgets.pop(k)
                    w.close()
                    break

    def update_data(self, data):
        for w in self.plot_widgets:
            w.update_plot(data)



