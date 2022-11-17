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
import qtawesome as qta
from redvypr.data_packets import device_in_data, get_keys_from_data
from redvypr.gui import redvypr_devicelist_widget
import redvypr.files as files
from redvypr.device import redvypr_device
from redvypr.data_packets import do_data_statistics, create_data_statistic_dict,check_for_command

_logo_file = files.logo_file
_icon_file = files.icon_file
pyqtgraph.setConfigOption('background', 'w')
pyqtgraph.setConfigOption('foreground', 'k')

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('plot')
logger.setLevel(logging.DEBUG)

description = 'Device that plots the received data'
config_template = {}
config_template['plots']    = []
config_template['redvypr_device'] = {}
config_template['redvypr_device']['publish']     = False
config_template['redvypr_device']['subscribe']   = True
config_template['redvypr_device']['description'] = description


def get_bare_graph_config():
    """ Returns a valid bare configuration for a graph plot
    """
    plotdict_bare = {}
    plotdict_bare['type'] = 'graph'        
    plotdict_bare['title'] = 'Graph title'
    plotdict_bare['name'] = 'Graph'
    plotdict_bare['location'] = [0,0,0,0]
    plotdict_bare['xlabel'] = 'x label'
    plotdict_bare['ylabel'] = 'y label'
    plotdict_bare['datetick'] = True
    plotdict_bare['lines'] = []
    plotdict_bare['lines'].append(get_bare_graph_line_config())
    #plotdict_bare['lines'].append(get_bare_graph_line_config())
    return plotdict_bare


def get_bare_graph_line_config():
    line_bare = {}
    line_bare['device'] = 'add devicename here'
    line_bare['name'] = 'this is a line'
    line_bare['x'] = 't'
    line_bare['y'] = 'data'
    line_bare['linewidth'] = 2
    line_bare['color'] = [255,0,0]
    line_bare['buffersize'] = 5000
    return line_bare


def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    while True:
        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
            except:
                data = None

            if(data is not None):
                command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
                #logger.debug('Got a command: {:s}'.format(str(data)))
                if (command is not None):
                    logger.debug('Command is for me: {:s}'.format(str(command)))
                    logger.info(funcname + ': Stopped')
                    return

                dataqueue.put(data) # This has to be done, otherwise the gui does not get any data ...



class Device(redvypr_device):
    def __init__(self, **kwargs):
        """
        """
        super(Device, self).__init__(**kwargs)
        self.connect_devices()
        self.start = start
        print('Hallo!!',self.config)

    def connect_devices(self):
        """ Connects devices, if they are not already connected
        """
        funcname = self.__class__.__name__ + '.connect_devices():'                                
        logger.debug(funcname)
        # Check of devices have not been added
        devices = self.redvypr.get_devices() # Get all devices
        plot_devices = []
        for plot in self.config['plots']: # Loop over all plots
            if(str(plot['type']).lower() == 'numdisp'):
                name = plot['device']
                plot_devices.append(name)

            elif(str(plot['type']).lower() == 'graph'):
                for l in plot['lines']: # Loop over all lines in a plot
                    name = l['device']
                    plot_devices.append(name)                    
                    
        # Add the device if not already done so
        if True:
            for name in plot_devices:
                logger.info(funcname + 'Connecting device {:s}'.format(name))
                ret = self.redvypr.addrm_device_as_data_provider(name,self,remove=False)
                if(ret == None):
                    logger.info(funcname + 'Device was not found')
                elif(ret == False):
                    logger.info(funcname + 'Device was already connected')
                elif(ret == True):
                    logger.info(funcname + 'Device was successfully connected')                                                            



class displayDeviceWidget(QtWidgets.QWidget):
    """ Widget is a wrapper for several plotting widgets (numdisp, graph) 
    This widget can be configured with a configuration dictionary 
    """
    def __init__(self,dt_update = 0.25,device=None,buffersize=100):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout        = QtWidgets.QVBoxLayout(self)
        self.device = device
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.configwidget = QtWidgets.QWidget() # The configuration widget
        self.displaywidget = PlotGridWidget()

        self.layout.addWidget(self.splitter)
        self.splitter.addWidget(self.configwidget)
        self.splitter.addWidget(self.displaywidget)

        self.configlayout = QtWidgets.QVBoxLayout(self.configwidget)
        self.init_configwidget()

    def init_configwidget(self):
        self.add_button = QtWidgets.QPushButton('Add Plot')
        self.add_button.clicked.connect(self.add_plot_clicked)
        self.add_button.setCheckable(True)
        # TODO, replace by combobox
        buticon = qta.icon('mdi6.chart-bell-curve-cumulative')
        self.addplot_button = QtWidgets.QPushButton(buticon, 'Plot')
        self.addplot_button.setEnabled(False)
        buticon = qta.icon('mdi6.order-numeric-ascending')
        self.addnumdisp_button = QtWidgets.QPushButton(buticon, 'Numeric display')
        self.addnumdisp_button.setEnabled(False)

        self.mod_button = QtWidgets.QPushButton('Modify')
        self.mod_button.clicked.connect(self.mod_plot_clicked)
        self.mod_button.setCheckable(True)

        self.commit_button = QtWidgets.QPushButton('Commit')
        self.commit_button.clicked.connect(self.commit_plot_clicked)
        #self.commit_button.setCheckable(True)

        self.configlayout.addWidget(self.add_button)
        self.configlayout.addWidget(self.addplot_button)
        self.configlayout.addWidget(self.addnumdisp_button)
        self.configlayout.addWidget(self.mod_button)
        self.configlayout.addWidget(self.commit_button)
        self.configlayout.addStretch()

    def add_plot_clicked(self):
        if(self.add_button.isChecked()):
            self.addplot_button.setEnabled(True)
            self.addnumdisp_button.setEnabled(True)
            self.displaywidget.rubber_enabled = True
        else:
            self.addplot_button.setEnabled(False)
            self.addnumdisp_button.setEnabled(False)
            self.displaywidget.rubber_enabled = False

    def mod_plot_clicked(self):
        self.displaywidget.modPlotclicked(self.mod_button.isChecked())

    def commit_plot_clicked(self):
        self.displaywidget.commit_clicked()



class PlotGridWidget(QtWidgets.QWidget):
    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.rubber_enabled = False
        self.nx = 6
        self.ny = 5
        self.gridcells = []
        self.all_plots = []  # A list of all plots added to the grid
        for i in range(self.nx):
            for j in range(self.ny):
                b = PlotGridWidgetButton()
                # b = QtWidgets.QPushButton()
                b.setCheckable(True)
                # Store the location indices as extra attributes
                b.__i__ = i
                b.__j__ = j
                self.gridcells.append(b)
                #b.setEnabled(False)
                b.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
                self.layout.addWidget(b, j, i)

        #b = QtWidgets.QPushButton()
        #b.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        #self.layout.addWidget(b, 1, 1,2,2)
        testw = RandomDataWidget()
        self.addPlot(testw,1,1,2,2)

        self.rubberband = QtWidgets.QRubberBand(
            QtWidgets.QRubberBand.Rectangle, self)




        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        self.origin = event.pos()
        if(self.rubber_enabled):
            self.rubberband.setGeometry(
                QtCore.QRect(self.origin, QtCore.QSize()))
            self.rubberband.show()
        QtWidgets.QWidget.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if self.rubberband.isVisible():
            self.rubberband.setGeometry(
                QtCore.QRect(self.origin, event.pos()).normalized())


            print(self.origin)
            print(
                QtCore.QRect(self.origin, event.pos()).normalized())
        QtWidgets.QWidget.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if self.rubberband.isVisible():
            self.rubberband.hide()
            selected = []
            rect = self.rubberband.geometry()
            FLAG_CHECKED = False
            FLAG_ALL_CHECKED = True

            for child in self.findChildren(QtWidgets.QPushButton):
                if rect.intersects(child.geometry()):
                    if(child.isChecked()):
                        FLAG_CHECKED = True
                    else:
                        FLAG_ALL_CHECKED = False

                    selected.append(child)
            for child in selected:
                if ((child.isChecked()) and (FLAG_CHECKED == False)) or FLAG_ALL_CHECKED:
                    child.setChecked(False)
                else:
                    child.setChecked(True)

        QtWidgets.QWidget.mouseReleaseEvent(self, event)

    def modPlotclicked(self,enabled):
        """
        Modify the existing plots

        Returns:

        """
        if(enabled):
            for d in self.all_plots:
                w = d['plot']
                #rubberband = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Rectangle, self)

                rubberband = ResizableRubberBand(self)
                rubberband.setGeometry(QtCore.QRect(w.pos(), w.size()).normalized())
                col = QtGui.QPalette()
                col.setBrush(QtGui.QPalette.Highlight, QtGui.QBrush(QtCore.Qt.red))
                rubberband.setPalette(col)
                rubberband.setWindowOpacity(.5)
                #print('Size', b, b.pos().x(), b.pos().y(), b.size())
                #print('Size', self, self.pos(), self.size())
                d['rubber'] = rubberband
                rubberband.show()
        else:
            for d in self.all_plots:
                try:
                    r = d['rubber']
                    r.hide()
                except Exception as e:
                    print('Hallo',e)



    def addPlot(self, plotwidget, i, j, width, height):
        """

        Args:
            plotwidget:

        Returns:

        """
        plotwidget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.layout.addWidget(plotwidget, j, i, height, width)
        d = {'plot':plotwidget}
        self.all_plots.append(d)
        plotwidget.show()

    def remPlot(self, plotwidget, i, j, width, height):
        """

        Args:
            plotwidget:

        Returns:

        """
        widgetbutton = QtWidgets.QPushButton('Hallo')
        plotwidget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.layout.addWidget(plotwidget, j, i, height, width)
        self.layout.addWidget(widgetbutton, j, i, height, width)
        plotwidget.show()

    def movePlot(self,plotwidget):
        # Test rubberband

        if False:
            self.rubberband_test = QtWidgets.QRubberBand(
                QtWidgets.QRubberBand.Rectangle, self)
            self.rubberband_test.setGeometry(
                QtCore.QRect(b.pos(), b.size()).normalized())

            bla = QtGui.QPalette()
            bla.setBrush(QtGui.QPalette.Highlight, QtGui.QBrush(QtCore.Qt.red))
            self.rubberband_test.setPalette(bla)
            self.rubberband_test.setWindowOpacity(1.0)

            print('Size', b, b.pos().x(), b.pos().y(), b.size())
            print('Size', self, self.pos(), self.size())
            self.rubberband_test.show()

    def commit_clicked(self):
        iall = []
        jall = []
        for d in self.all_plots:
            try:
                r = d['rubber']
                plotwidget = d['plot']
            except Exception as e:
                continue

            rect = r.geometry()
            for child in self.gridcells:
                if rect.intersects(child.geometry()):
                    iall.append(child.__i__)
                    jall.append(child.__j__)

            if(len(iall)>0 and len(jall)>0):
                inew = min(iall)
                di = max(iall) - min(iall) + 1
                jnew = min(jall)
                dj = max(jall) - min(jall) + 1
                self.layout.removeWidget(plotwidget)
                self.layout.addWidget(plotwidget,jnew,inew,dj,di)
                r.hide()
                self.modPlotclicked(True)
                #r.hide()






class PlotGridWidgetButton(QtWidgets.QPushButton):
    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()

    def mousePressEvent(self, event):
        #QtWidgets.QWidget.mousePressEvent(self, event)
        QtWidgets.QWidget.mousePressEvent(self.parent(), event)


class RandomDataWidget(QtWidgets.QWidget):
    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()
        self.i = 0
        self.texts = ['Hello','redvypr','data']
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_status)
        self.statustimer.start(2000)
        self.label = QtWidgets.QLabel(self.texts[0])
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.addWidget(self.label)
        self.setStyleSheet("background-color:green;")

    def update_status(self):
        self.i += 1
        self.i = self.i % len(self.texts)
        self.label.setText(self.texts[self.i])


class ResizableRubberBand(QtWidgets.QWidget):
    """Wrapper to make QRubberBand mouse-resizable using QSizeGrip

    Source: http://stackoverflow.com/a/19067132/435253
    """
    def __init__(self, parent):
        #super(Device, self).__init__(**kwargs)
        super(ResizableRubberBand, self).__init__(parent)

        self.setWindowFlags(QtCore.Qt.SubWindow)
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.grip1 = QtWidgets.QSizeGrip(self)
        self.grip2 = QtWidgets.QSizeGrip(self)
        self.layout.addWidget(self.grip1, 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.layout.addWidget(self.grip2, 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignBottom)

        self.rubberband = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Rectangle, self)
        self.rubberband.move(0, 0)
        self.rubberband.show()
        self.show()

    def resizeEvent(self, event):
        self.rubberband.resize(self.size())

    def mousePressEvent(self, event):
        print('Mouse press')
        self.oldPos = event.globalPos()

    def mouseMoveEvent(self, event):
        print('Move')
        delta = QtCore.QPoint(event.globalPos() - self.oldPos)
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = event.globalPos()






