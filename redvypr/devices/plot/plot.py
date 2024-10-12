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
from redvypr.device import device_start_standard
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


# Use the standard start function as the start function
start = device_start_standard


class PlotDock(pyqtgraph.dockarea.Dock):
    labelClicked = QtCore.pyqtSignal()  #
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs, closable=True)
        self.label.sigClicked.connect(self.__labelClicked)

    def __labelClicked(self):
        self.labelClicked.emit()
    def mousePressEvent(self, ev):
        #print('Hallo')
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        #print('Double')
        super().mouseDoubleClickEvent(ev)

class RedvyprDeviceWidget(redvypr.widgets.standard_device_widgets.RedvyprDeviceWidget_startonly):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        layout = QtWidgets.QGridLayout(self)
        self.dockarea = pyqtgraph.dockarea.DockArea()
        self.plot_widgets = []
        self.numdocks = 1
        if True:
            # Test the dockarea
            d1 = PlotDock("Dock 1", size=(1, 1))     # give this dock the minimum possible size
            p1 = XYPlotWidget(redvypr_device=self.device)
            self.plot_widgets.append(p1)
            d1.addWidget(p1)
            self.dockarea.addDock(d1, 'left')
            self.numdocks += 1

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

    def __add_xy_clicked(self):
        button = self.sender()
        position = button.__comboXYplotlocation.currentText().lower()
        dockname_str = button.__dockName.text()
        widget_add = button.__addwidget_bare
        dock = PlotDock(dockname_str, size=(1, 1))  ## give this dock the minimum possible size
        dock.sigClosed.connect(self.__dockclosed)
        plot = widget_add(redvypr_device=self.device)
        self.plot_widgets.append(plot)
        dock.addWidget(plot)
        #print('Position', position)
        self.dockarea.addDock(dock, position=position)
        self.numdocks += 1
        dockname_str = "Dock {}".format(self.numdocks)
        button.__dockName.setText(dockname_str)

    def __dockclosed(self):
        dock = self.sender()
        #print('Dock closed',dock)
        for w in dock.widgets:
            self.plot_widgets.remove(w)
            w.close()

    def update_data(self, data):
        #print('Update data')
        for w in self.plot_widgets:
            w.update_plot(data)



