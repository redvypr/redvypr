import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
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
import redvypr.data_packets
from redvypr.gui import iconnames
#from redvypr.gui import configWidget
#from redvypr.devices.plot.plot_widgets import redvypr_numdisp_widget, redvypr_graph_widget, config_template_numdisp, config_template_graph
from redvypr.devices.plot.XYplotWidget import XYPlotWidget
import redvypr.files as files
from redvypr.device import RedvyprDevice
from redvypr.data_packets import check_for_command
#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict
#from redvypr.configdata import configdata, getdata

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('manual')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Allows to send data manually'
    gui_icon: str = 'ph.chart-line-fill'


def start(*args,**kwargs):
    return


class PlotDock(pyqtgraph.dockarea.Dock):
    labelClicked = QtCore.pyqtSignal()  #
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs, closable=True)
        self.label.sigClicked.connect(self.__labelClicked)

    def __labelClicked(self):
        self.labelClicked.emit()
    def mousePressEvent(self, ev):
        print('Hallo')
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        print('Double')
        super().mouseDoubleClickEvent(ev)

class RedvyprDeviceWidget(redvypr.widgets.standard_device_widgets.RedvyprDeviceWidget_startonly):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        layout = QtWidgets.QGridLayout(self)
        self.dockarea = pyqtgraph.dockarea.DockArea()

        if True:
            # Test the dockarea
            d1 = PlotDock("Dock1", size=(1, 1))     ## give this dock the minimum possible size
            p1 = XYPlotWidget(redvypr_device=self.device)
            d1.addWidget(p1)

            d2 = PlotDock("Dock2", size=(1, 1))  ## give this dock the minimum possible size
            d2.sigClosed.connect(self.__dockclosed)
            p2 = XYPlotWidget(redvypr_device=self.device)
            d2.addWidget(p2)
            self.dockarea.addDock(d1, 'left')
            self.dockarea.addDock(d2, 'right')

        menu = QtWidgets.QMenu()
        menu_XYplot = QtWidgets.QMenu('XY-Plot',self)
        menu_XYplot.__addwidget_bare = XYPlotWidget
        menu.addMenu(menu_XYplot)
        menu_XYplot.addAction('Left', self.__addXYPlot)
        menu_XYplot.addAction('Right', self.__addXYPlot)
        menu_XYplot.addAction('Top', self.__addXYPlot)
        menu_XYplot.addAction('Bottom', self.__addXYPlot)

        self.numdocks = 0
        icon = qtawesome.icon(iconnames['settings'])
        self.add_button = QtWidgets.QPushButton('Add')
        self.add_button.setMenu(menu)
        self.settings_button = QtWidgets.QPushButton('Settings')
        self.settings_button.setIcon(icon)
        #self.settings_button.clicked.connect(self.settings_clicked)
        self.layout.removeWidget(self.buttons_widget)
        self.layout.removeWidget(self.killbutton)
        self.killbutton.hide()

        self.layout.addWidget(self.dockarea,0,0)
        self.layout.addWidget(self.buttons_widget, 1, 0)
        self.layout_buttons.addWidget(self.add_button, 0, 4)
        self.layout_buttons.addWidget(self.settings_button, 0, 6)

    def __addXYPlot(self):
        action = self.sender()
        print('Adding XY-Plot',action.text(),action.parent().__addwidget_bare)
        position = action.text().lower()
        widget_add = action.parent().__addwidget_bare
        dock = PlotDock("Dock {}".format(self.numdocks), size=(1, 1))  ## give this dock the minimum possible size
        dock.sigClosed.connect(self.__dockclosed)
        plot = widget_add(redvypr_device=self.device)
        dock.addWidget(plot)
        print('Position',position)
        self.dockarea.addDock(dock, position=position)
        self.numdocks += 1

    def __dockclosed(self):
        dock = self.sender()
        print('Dock closed',dock)



