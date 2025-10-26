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
from redvypr.devices.plot.XYPlotWidget import XYPlotWidget, ConfigXYplot
from redvypr.devices.plot.TablePlotWidget import TablePlotWidget, ConfigTablePlot
from redvypr.devices.plot.PcolorPlotDevice import PcolorPlotWidget, ConfigPcolorPlot
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
    plottype: typing.Literal['XY-Plot','Datatable','PColorPlot'] = pydantic.Field(default='XY-Plot')
    docklabel: str = pydantic.Field(default='Dock')
    location: typing.Literal['left','right','top','bottom'] = pydantic.Field(default='left')
    config: typing.Optional[typing.Union[ConfigXYplot, ConfigTablePlot, ConfigPcolorPlot]] = pydantic.Field(default=None, discriminator='type')


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



#class RedvyprDeviceWidget(redvypr.widgets.standard_device_widgets.RedvyprdevicewidgetStartonly):
class RedvyprDeviceWidget(redvypr.widgets.standard_device_widgets.RedvyprdevicewidgetSimple):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        layout = QtWidgets.QGridLayout(self)
        self.dockarea = pyqtgraph.dockarea.DockArea()
        self.plot_widgets = {}
        self.numdocks = 1
        if len(self.device.custom_config.plots.keys()) == 0:
            # This adds a plot, if not existing already
            xyplotconfig = PlotConfig(plottype='XY-Plot',docklabel='XY-Plot')
            self.add_plot_to_config(xyplotconfig)
            datatableconfig = PlotConfig(plottype='Datatable', docklabel='Datatable')
            self.add_plot_to_config(datatableconfig)

        self.add_plots_from_config()
        menu = QtWidgets.QMenu()
        plots = ['XY-Plot','Datatable','PColorPlot']
        for pl in plots:
            menu_XYplot = QtWidgets.QMenu(pl,self)
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
            addButton.__plottype = pl
            addMenuWidget_layout.addWidget(dockName)
            addMenuWidget_layout.addWidget(comboXYplotlocation)
            addMenuWidget_layout.addWidget(addButton)
            addAction.setDefaultWidget(addMenuWidget)
            menu_XYplot.addAction(addAction)


        self.add_button = QtWidgets.QPushButton('Add')
        self.add_button.setMenu(menu)


        #
        #self.killbutton.hide()

        #self.layout.addWidget(self.dockarea,0,0)
        #self.layout.addWidget(self.buttons_widget, 1, 0)
        #self.layout_buttons.addWidget(self.add_button, 0, 4)
        self.layout.addWidget(self.dockarea)
        self.layout_buttons
        self.layout_buttons.removeWidget(self.subscribe_button)
        self.layout_buttons.removeWidget(self.configure_button)
        self.layout_buttons.addWidget(self.add_button, 2, 0, 1, 2)
        self.layout_buttons.addWidget(self.configure_button, 2, 2, 1, 1)
        self.layout_buttons.addWidget(self.subscribe_button, 2, 3, 1, 1)
        #self.layout.addWidget(self.buttons_widget)
        #self.layout_buttons.addWidget(self.add_button)
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
                if plotconfig.config is None:
                    plotconfig.config = ConfigXYplot()
                plotwidget = XYPlotWidget(redvypr_device=self.device,config=plotconfig.config)
            elif plotconfig.plottype == 'Datatable':
                if plotconfig.config is None:
                    plotconfig.config = ConfigTablePlot()
                plotwidget = TablePlotWidget(redvypr_device=self.device,config=plotconfig.config)
            else:
                if plotconfig.config is None:
                    plotconfig.config = ConfigPcolorPlot()
                plotwidget = PcolorPlotWidget(redvypr_device=self.device,config=plotconfig.config)

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
        plottype = button.__plottype
        #if plottype == 'XY-Plot':
        if True:
            position = button.__comboXYplotlocation.currentText().lower()
            dockname_str = button.__dockName.text()
            plottype_str = button.__plottype
            plotconfig = PlotConfig(plottype=plottype_str, docklabel=dockname_str,location=position)
            logger.debug('Adding plot {}'.format(plotconfig))
            self.add_plot_to_config(plotconfig)
            self.add_plots_from_config()
            dockname_str = "Dock {}".format(self.numdocks)
            button.__dockName.setText(dockname_str)
        #elif plottype == 'Datatable':
        #    pass
        #elif plottype == 'PColorPlot':
        #    pass
        #else:
        #    print('Unknown plottype {}'.format(plottype))

    def __dockclosed(self):
        dock = self.sender()
        for w in dock.widgets:
            for k in self.plot_widgets:
                if w == self.plot_widgets[k]:
                    wdict = self.plot_widgets.pop(k)
                    w.close()
                    break

    def update_plot(self, data):
        for w in self.plot_widgets:
            try:
                #print('Updating',data)
                print(w,self.plot_widgets)
                self.plot_widgets[w].update_plot(data)
            except:
                logger.debug('Could not update plot',exc_info=True)



