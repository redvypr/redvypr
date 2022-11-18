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
        self.configwidget  = QtWidgets.QWidget() # The configuration widget
        self.displaywidget = PlotGridWidget()

        self.layout.addWidget(self.splitter)
        self.splitter.addWidget(self.configwidget)
        self.splitter.addWidget(self.displaywidget)

        self.configlayout = QtWidgets.QGridLayout(self.configwidget)
        self.init_configwidget()

    def init_configwidget(self):
        self.add_button = QtWidgets.QPushButton('Add Plot')
        self.add_button.clicked.connect(self.add_plot_clicked)
        self.add_button.setCheckable(True)
        self.addplot_combo = QtWidgets.QComboBox() #(buticon, 'Plot')
        self.addplot_combo.addItem('Plot')
        buticon = qta.icon('mdi6.chart-bell-curve-cumulative')  # Plot
        self.addplot_combo.setItemIcon(0,buticon)
        self.addplot_combo.addItem('Numeric Display')
        buticon = qta.icon('mdi6.order-numeric-ascending')  # Numeric display
        self.addplot_combo.setItemIcon(1,buticon)

        self.addplot_combo.addItem('Test')
        self.addplot_combo.setEnabled(False)
        self.addplot_combo.currentTextChanged.connect(self.add_plot_combo_changed)

        self.mod_button = QtWidgets.QPushButton('Modify')
        self.mod_button.clicked.connect(self.mod_plot_clicked)
        self.mod_button.setCheckable(True)

        self.rem_button = QtWidgets.QPushButton('Remove')
        self.rem_button.clicked.connect(self.rem_plot_clicked)
        self.rem_button.setCheckable(True)

        self.commit_button = QtWidgets.QPushButton('Commit')
        self.commit_button.clicked.connect(self.commit_plot_clicked)
        #self.commit_button.setCheckable(True)

        self.configlayout.addWidget(self.add_button,0,0)
        self.configlayout.addWidget(self.addplot_combo,0,1)
        self.configlayout.addWidget(self.mod_button, 1, 0)
        self.configlayout.addWidget(self.rem_button, 1, 1)
        self.configlayout.addWidget(self.commit_button,2,0,1,2)
        self.configlayout.setRowStretch(self.configlayout.rowCount(), 1)
        #self.configlayout.setRowStretch()

    def add_plot_combo_changed(self):
        plottype = self.addplot_combo.currentText()
        print('Plottype',plottype)
        self.displaywidget.__add_plottype__ = plottype
        if True:
            self.displaywidget.__add_plotwidget__ = RandomDataWidget

    def add_plot_clicked(self):
        self.add_plot_combo_changed()

        if (self.add_button.isChecked()):
            self.addplot_combo.setEnabled(True)
            self.displaywidget.rubber_enabled = True
            # Disable other buttons
            self.mod_button.setChecked(False)
            self.displaywidget.flag_add_plot = self.add_button.isChecked()
            self.displaywidget.flag_mod_plot = False
            self.displaywidget.flag_rem_plot = False
            self.rem_button.setChecked(False)
            self.displaywidget.modPlotclicked(False)
        else:
            self.addplot_combo.setEnabled(False)
            self.displaywidget.rubber_enabled = False

    def rem_plot_clicked(self):
        print('Hallo')
        if (self.rem_button.isChecked()):
            self.displaywidget.flag_rem_plot = True
            self.displaywidget.flag_add_plot = False
            self.displaywidget.flag_mod_plot = False
            self.displaywidget.rubber_enabled = False
            self.addplot_combo.setEnabled(False)
            self.add_button.setChecked(False)
            self.mod_button.setChecked(False)
        else:
            self.displaywidget.flag_rem_plot = False


        self.displaywidget.remPlotclicked(self.rem_button.isChecked())

    def mod_plot_clicked(self):
        if (self.mod_button.isChecked()):
            self.displaywidget.rubber_enabled = False
            self.displaywidget.flag_add_plot = False
            self.displaywidget.flag_rem_plot = False
            self.addplot_combo.setEnabled(False)
            self.add_button.setChecked(False)
            self.rem_button.setChecked(False)

        self.displaywidget.flag_mod_plot = self.mod_button.isChecked()
        self.displaywidget.modPlotclicked(self.mod_button.isChecked())

    def commit_plot_clicked(self):
        self.displaywidget.commit_clicked()



class PlotGridWidget(QtWidgets.QWidget):
    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.rubber_enabled   = False
        self.flag_add_plot    = False
        self.flag_mod_plot    = False
        self.flag_rem_plot    = False
        self.__add_location__ = None
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

        if self.rubberband.isVisible(): # New plot to be added
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

        if (self.flag_rem_plot):  # If we wantto remove a widget
            print('Remove click')


        QtWidgets.QWidget.mouseReleaseEvent(self, event)

    def get_selected_index(self):
        """
        Gets the index of all selected gridbuttons (used for adding a device)
        Returns:

        """
        # Do we have an area larger than zero?
        # Adding the new widget
        iall = []
        jall = []
        for child in self.findChildren(QtWidgets.QPushButton):
            if child.isChecked():
                iall.append(child.__i__)
                jall.append(child.__j__)

        if(len(iall)>0 and len(jall)>0):
            inew = min(iall)
            di = max(iall) - min(iall) + 1
            jnew = min(jall)
            dj = max(jall) - min(jall) + 1
            self.__add_location__ = [jnew,inew,dj,di]
        else:
            self.__add_location__ = None

    def remPlotclicked(self, enabled):
        """
        Modify the existing plots

        Returns:

        """
        logger.debug('Removing')
        self.reset_all_rubberbands()
        if (enabled):  # Adding rubberbands to all plots
            self.show_all_rubberbands()
        else:  # Hiding all rubberbands
            self.hide_all_rubberbands()


    def modPlotclicked(self,enabled):
        """
        Modify the existing plots

        Returns:

        """
        logger.debug('Modifying')
        self.reset_all_rubberbands()
        if(enabled): # Adding rubberbands to all plots
            self.show_all_rubberbands()
        else: # Hiding all rubberbands
            self.hide_all_rubberbands()

    def show_all_rubberbands(self):
        for d in self.all_plots:
            w = d['plot']
            # rubberband = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Rectangle, self)
            try:
                rubberband = d['rubber']
            except:
                rubberband = ResizableRubberBand(self)
                col = QtGui.QPalette()
                col.setBrush(QtGui.QPalette.Highlight, QtGui.QBrush(QtCore.Qt.red))
                rubberband.setPalette(col)
                rubberband.setWindowOpacity(.5)
                # print('Size', b, b.pos().x(), b.pos().y(), b.size())
                # print('Size', self, self.pos(), self.size())
                d['rubber'] = rubberband

            rubberband.setGeometry(QtCore.QRect(w.pos(), w.size()).normalized())
            rubberband.show()

    def hide_all_rubberbands(self):
        for d in self.all_plots:
            try:
                r = d['rubber']
                r.hide()
            except Exception as e:
                pass

    def reset_all_rubberbands(self):
        for d in self.all_plots:
            try:
                r = d['rubber']
                w = d['plot']
                col = QtGui.QPalette()
                col.setBrush(QtGui.QPalette.Highlight, QtGui.QBrush(QtCore.Qt.red))
                #r.setGeometry(QtCore.QRect(w.pos(), w.size()).normalized())
                r.setPalette(col)
                r.setWindowOpacity(.5)
                r.flag_rem_plot = False
                print('Reset done')
            except Exception as e:
                pass



    def addPlot(self, plotwidget, j, i, height, width):
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

    def remPlot(self, plotwidget):
        """

        Args:
            plotwidget:

        Returns:

        """
        self.layout.removeWidget(plotwidget)
        for d in self.all_plots:
            if(d['plot'] == plotwidget):
                print('removing from list')
                self.all_plots.remove(d)
                try:
                    r = d['rubber']
                    r.close()
                except:
                    pass
                break

        plotwidget.close()

    def commit_clicked(self):
        """

        Returns:

        """
        print('Commit')

        if (self.flag_mod_plot):  # Flags are set by the gridwidget buttons
            print('Modifying plot')
            for d in self.all_plots:
                try:
                    r = d['rubber']
                    plotwidget = d['plot']
                except Exception as e:
                    print('ohoh',e)
                    continue

                iall = []
                jall = []
                rect = r.geometry()
                for child in self.gridcells:
                    if rect.intersects(child.geometry()):
                        iall.append(child.__i__)
                        jall.append(child.__j__)

                print('iall', iall)
                print('jall', jall)
                if(len(iall)>0 and len(jall)>0):
                    inew = min(iall)
                    di = max(iall) - min(iall) + 1
                    jnew = min(jall)
                    dj = max(jall) - min(jall) + 1
                    print('Hallo', inew, jnew, di, dj)
                    self.layout.removeWidget(plotwidget)
                    self.layout.addWidget(plotwidget,jnew,inew,dj,di)


            #self.reset_all_rubberbands()

        if (self.flag_add_plot):  # Flags are set by the gridwidget buttons
            print('Adding plot')
            self.get_selected_index() # update self.__add_location__
            if self.__add_location__  is not None:
                addwidgetstr = self.__add_plottype__  # is set by the plotgridwidget combo changed signal
                addwidget = self.__add_plotwidget__  # is set by the plotgridwidget combo changed signal
                logger.debug('Adding widget {:s}'.format(addwidgetstr))
                addwidget_called = addwidget()
                self.addPlot(addwidget_called, self.__add_location__[0], self.__add_location__[1],
                                      self.__add_location__[2], self.__add_location__[3])

                # Remove all selected indices
                self.unselect_all()

            else:
                logger.debug('Not a valid location for adding plot')

        if (self.flag_rem_plot):  # Flags are set by the gridwidget buttons
            print('remove')
            for d in self.all_plots:
                try:
                    r = d['rubber']
                    if r.flag_rem:  # New plot to be added
                        print('removing now',r)
                        self.remPlot(d['plot'])
                except Exception as e:
                    print('Hallo',e)

        #self.flag_mod_plot = False
        #self.flag_add_plot = False

    def unselect_all(self):
        for child in self.findChildren(QtWidgets.QPushButton):
            child.setChecked(False)





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

        self.flag_rem = False # Flag for removal
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

    def mouseReleaseEvent(self, event):
        print('Mouse release')
        try:
            flag_rem = self.parent().flag_rem_plot
            print('remove', self.parent().flag_rem_plot)
        except:
            flag_rem = False
            print('noremove')

        if(flag_rem and self.flag_rem == False):
            col = QtGui.QPalette()
            col.setBrush(QtGui.QPalette.Highlight, QtGui.QBrush(QtCore.Qt.black))
            self.setPalette(col)
            self.flag_rem = True
        else:
            self.flag_rem = False
            col = QtGui.QPalette()
            col.setBrush(QtGui.QPalette.Highlight, QtGui.QBrush(QtCore.Qt.red))
            self.setPalette(col)

        #self.oldPos = event.globalPos()






