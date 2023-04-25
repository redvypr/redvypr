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

import redvypr.data_packets
from redvypr.data_packets import addr_in_data, get_keys_from_data
from redvypr.gui import configWidget
from redvypr.devices.plot.plot_widgets import redvypr_numdisp_widget, redvypr_graph_widget, config_template_numdisp, config_template_graph
import redvypr.files as files
from redvypr.device import redvypr_device
from redvypr.data_packets import do_data_statistics, create_data_statistic_dict, check_for_command, parse_addrstr
from redvypr.configdata import configdata, getdata

_logo_file = files.logo_file
_icon_file = files.icon_file
pyqtgraph.setConfigOption('background', 'w')
pyqtgraph.setConfigOption('foreground', 'k')

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('plot')
logger.setLevel(logging.DEBUG)

description = 'Device that plots the received data'
config_template = {}
config_template['template_name']  = 'plot'
config_template['plots'] = {'type': 'list', 'modify': True, 'options': [config_template_numdisp, config_template_graph]}
config_template['dt_update'] = {'type':'float','default':0.25}
config_template['nx'] = {'type':'int','default':7}
config_template['ny'] = {'type':'int','default':6}
config_template['redvypr_device'] = {}
config_template['redvypr_device']['publish'] = False
config_template['redvypr_device']['subscribe'] = True
config_template['redvypr_device']['description'] = description


def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    while True:
        time.sleep(0.05)
        while (datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
            except:
                data = None

            if (data is not None):
                command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
                # logger.debug('Got a command: {:s}'.format(str(data)))
                if (command is not None):
                    logger.debug('Command is for me: {:s}'.format(str(command)))
                    if(command == 'stop'):
                        logger.info(funcname + ': Stopped')
                        return

                #print('Got data')
                dataqueue.put(data)  # This has to be done, otherwise the gui does not get any data ...


class Device(redvypr_device):
    def __init__(self, **kwargs):
        """
        """
        super(Device, self).__init__(**kwargs)
        self.start = start

    def thread_start(self):
        """

        Returns:

        """
        self.connect_devices()
        super(Device,self).thread_start()

    def connect_devices(self):
        """ Connects devices, if they are not already connected
        """
        funcname = self.__class__.__name__ + '.connect_devices():'
        logger.debug(funcname)
        print('Connecting devices')
        # Check of devices have not been added
        plot_devices = []
        for plot in self.config['plots']:  # Loop over all plots
            print('Config',self.config)
            print('plot',plot)
            if (str(getdata(plot['type'])).lower() == 'numdisp'):
                datastream = plot['datastream']
                if (len(datastream) > 0):
                    address = redvypr.data_packets.redvypr_address(datastream)
                    plot_devices.append(address)

            elif (str(plot['type']).lower() == 'graph'):
                for l in plot['lines']:  # Loop over all lines in a plot
                    if (len(l['x']) > 0) and (len(l['y']) > 0):
                        xaddress = redvypr.data_packets.redvypr_address(str(l['x']))
                        yaddress = redvypr.data_packets.redvypr_address(str(l['y']))
                        xaddress = l['x'].xaddr
                        yaddress = l['y'].yaddr
                        plot_devices.append(xaddress)
                        plot_devices.append(yaddress)

        if True:
            print('Plot devices',plot_devices,self.name)
            for name in plot_devices:
                logger.info(funcname + 'Subscribing to device {:s}'.format(str(name)))
                ret = self.subscribe_address(name.get_str(),force=True)
                if (ret == False):
                    logger.info(funcname + 'Device is already subscribed')
                elif (ret == True):
                    logger.info(funcname + 'Device subscribed')


#
#
#
#
class displayDeviceWidget(QtWidgets.QWidget):
    """ Widget is a wrapper for several plotting widgets (numdisp, graph) 
    This widget can be configured with a configuration dictionary 
    """

    def __init__(self, device=None,deviceinitwidget=None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.deviceinitwidget = deviceinitwidget
        # Let the configuration only be done by here, not in the initwidget
        #self.deviceinitwidget.config_widget.configtree.setEnabled(False)
        self.config = device.config
        self.layout = QtWidgets.QVBoxLayout(self)
        self.device = device
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.configwidget = QtWidgets.QWidget()  # The configuration widget
        self.configplotwidget = QtWidgets.QWidget(
            parent=self.configwidget)  # The configuration widget of the individual plots
        self.configplotlayout = QtWidgets.QVBoxLayout(self.configplotwidget)
        self.displaywidget = PlotGridWidget(configplotwidget=self.configplotwidget,device=self.device,displaywidget = self)
        self.all_plots = self.displaywidget.all_plots
        self.layout.addWidget(self.splitter)
        self.splitter.addWidget(self.configwidget)
        self.splitter.addWidget(self.displaywidget)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 10)
        self.databuf = []
        self.configlayout = QtWidgets.QGridLayout(self.configwidget)
        self.status = {}
        self.status['last_update'] = time.time()
        self.init_configwidget()
        # Remove the plots from the list, this is necessary because addPlot will add the plot to the list again
        plots = []
        for p in reversed(self.config['plots']):
            print('p',p)
            p2 = copy.deepcopy(p)
            plots.append(p2)
            self.config['plots'].remove(p)

        if len(plots) == 0:
            graph = self.displaywidget.create_plot_widget('graph')
            self.displaywidget.addPlot(graph, 0, 0, 6, 6)

        for p in reversed(plots):
            print('p',p)
            x      = p['location']['x']
            y      = p['location']['y']
            width  = p['location']['width']
            height = p['location']['height']
            plotconfig = p
            w = self.displaywidget.create_plot_widget(p['type'],config = plotconfig)
            print('Adding plot',w)
            self.displaywidget.addPlot(w, y, x, height, width)



    def init_configwidget(self):
        self.add_button = QtWidgets.QPushButton('Add Plot')
        self.add_button.clicked.connect(self.add_plot_clicked)
        self.add_button.setCheckable(True)
        self.addplot_combo = QtWidgets.QComboBox()  # (buticon, 'Plot')
        self.addplot_combo.addItem('Graph')
        buticon = qta.icon('mdi6.chart-bell-curve-cumulative')  # Plot
        self.addplot_combo.setItemIcon(0, buticon)
        self.addplot_combo.addItem('Numeric Display')
        buticon = qta.icon('mdi6.order-numeric-ascending')  # Numeric display
        self.addplot_combo.setItemIcon(1, buticon)

        self.addplot_combo.addItem('Test')
        self.addplot_combo.setEnabled(False)
        self.addplot_combo.currentTextChanged.connect(self.add_plot_combo_changed)

        self.mod_button = QtWidgets.QPushButton('Modify')
        self.mod_button.clicked.connect(self.mod_plot_clicked)
        self.mod_button.setCheckable(True)

        self.rem_button = QtWidgets.QPushButton('Remove plot')
        self.rem_button.clicked.connect(self.rem_plot_clicked)
        self.rem_button.setCheckable(True)

        self.commit_button = QtWidgets.QPushButton('Commit')
        self.commit_button.clicked.connect(self.commit_plot_clicked)
        # self.commit_button.setCheckable(True)


        self.configlayout.addWidget(self.addplot_combo, 0, 0,1,2)
        self.configlayout.addWidget(self.add_button, 1, 0)
        self.configlayout.addWidget(self.rem_button, 1, 1)
        self.configlayout.addWidget(self.mod_button, 2, 0,1,2)
        self.configlayout.addWidget(self.commit_button, 3, 0,1,2)
        self.configlayout.setRowStretch(self.configlayout.rowCount(), 1)
        #self.configlayout.addWidget(self.configplotwidget, 3, 0, 3, 2)
        # self.configlayout.setRowStretch()

    def add_plot_combo_changed(self):
        plottype = self.addplot_combo.currentText()
        print('Plottype', plottype)


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

    def update(self, data):
        funcname = __name__ + '.update():'
        print('Plot update ...')
        tnow = time.time()
        self.databuf.append(data)

        #print('got data', data)
        #print('status', self.status)
        #print('config', self.config)
        #print(tnow,self.status['last_update'])
        #print((tnow - self.status['last_update']))
        # print('statistics',self.device.statistics)
        # Only plot the data in intervals of dt_update length, this prevents high CPU loads for fast devices
        if True:
            update = (tnow - self.status['last_update']) > self.config['dt_update']
            #print('update update', update)
            if (update):
                #self.status['last_update'] = tnow
                #print('updating', update)
                try:
                    for data in self.databuf:
                        #print('data',data)
                        for plotdict in self.all_plots:
                            plot = plotdict['plot']
                            #print('Plot ...',plot,plot.update_plot)
                            plot.update_plot(data)

                    self.databuf = []

                except Exception as e:
                    logger.exception(e)
                    logger.debug(funcname + 'Exception:' + str(e))

#
#
#
#
#
class PlotGridWidget(QtWidgets.QWidget):
    """
    The widget of the grid where the single plots can be added by the user
    """
    def __init__(self, configplotwidget,device=None,displaywidget = None):
        super(QtWidgets.QWidget, self).__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.configplotwidget = configplotwidget
        if(device is not None):
            initwidget = device.deviceinitwidget
            self.configwidget_global = initwidget.config_widget # The configuration widget that is shown on the init widget
            self.configwidget_global.config_changed_flag.connect(self.config_changed)
        self.displaywidget = displaywidget # The widget that is actually shown in the tabulator
        self.device = device
        self.redvypr = device.redvypr
        self.rubber_enabled = False
        self.flag_add_plot = False
        self.flag_mod_plot = False
        self.flag_rem_plot = False
        self.__add_location__ = None
        self.nx = self.device.config['nx'].data
        self.ny = self.device.config['ny'].data
        for i in range(self.ny):
            self.layout.setRowStretch(i, 1)

        for i in range(self.nx):
            self.layout.setColumnStretch(i, 1)

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
                # b.setEnabled(False)
                b.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
                self.layout.addWidget(b, j, i)
                if(i==0) and (j == 0):
                    b.resize_signal.connect(self.resize_all_rubberbands)

        #testw = RandomDataWidget()
        #testw = redvypr_numdisp_widget()
        # self.addPlot(testw, 1, 1, 2, 2)
        #testg = redvypr_graph_widget()
        #self.addPlot(testg, 0, 3, 5, 3)


        self.rubberband = QtWidgets.QRubberBand(
            QtWidgets.QRubberBand.Rectangle, self)

        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        self.origin = event.pos()
        if (self.rubber_enabled):
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

        if self.rubberband.isVisible():  # New plot to be added
            self.rubberband.hide()
            selected = []

            rect = self.rubberband.geometry()
            FLAG_CHECKED = False
            FLAG_ALL_CHECKED = True

            for child in self.findChildren(QtWidgets.QPushButton):
                if rect.intersects(child.geometry()):
                    if (child.isChecked()):
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

        if (len(iall) > 0 and len(jall) > 0):
            inew = min(iall)
            di = max(iall) - min(iall) + 1
            jnew = min(jall)
            dj = max(jall) - min(jall) + 1
            self.__add_location__ = [jnew, inew, dj, di]
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

    def modPlotclicked(self, enabled):
        """
        Modify the existing plots

        Returns:

        """
        logger.debug('Modifying')
        self.reset_all_rubberbands()
        if (enabled):  # Adding rubberbands to all plots
            self.show_all_rubberbands()
        else:  # Hiding all rubberbands
            self.hide_all_rubberbands()

    def show_all_rubberbands(self):
        for d in self.all_plots:
            w = d['plot']
            # rubberband = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Rectangle, self)
            try:
                rubberband = d['rubber']
            except:
                rubberband = ResizableRubberBand(self)
                rubberband.mouse_pressed_right.connect(self.rubberband_clicked)
                rubberband.__config_widget__ = d['config']  # Add the configuration widget
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
                # r.setGeometry(QtCore.QRect(w.pos(), w.size()).normalized())
                r.setPalette(col)
                r.setWindowOpacity(.5)
                r.flag_rem_plot = False
                print('Reset done')
            except Exception as e:
                pass

    def resize_all_rubberbands(self):
        for d in self.all_plots:
            try:
                r = d['rubber']
                w = d['plot']
                r.setGeometry(QtCore.QRect(w.pos(), w.size()).normalized())
            except Exception as e:
                pass

    def rubberband_clicked(self):
        funcname = self.__class__.__name__ + '.rubberband_clicked'
        logger.debug(funcname)
        rubberband = self.sender()
        configplotwidget = rubberband.__config_widget__
        if True:
            configplotwidget.show()


    def create_plot_widget(self,plottype,config=None):
        """
        Creates a plot widget of type plottype and returns the widget
        Args:
            plottype:

        Returns:

        """
        funcname = __name__ + '.create_plot_widget():'

        self.displaywidget.__add_plottype__ = plottype
        if ('random' in plottype.lower()):
            plotwidget_ = RandomDataWidget
        elif ('num' in plottype.lower()):
            plotwidget_ = redvypr_numdisp_widget
        elif ('graph' in plottype.lower()):
            plotwidget_ = redvypr_graph_widget
        else:
            print('Not implemented yet: {:s}'.format(plottype))

        plotwidget = plotwidget_(config=config) # Call the plotwidget
        config_widget = configWidget(config=plotwidget.config, loadsavebutton=False, redvypr_instance=self.redvypr)
        config_widget.setWindowIcon(QtGui.QIcon(_icon_file))
        config_widget.config_changed_flag.connect(
            self.config_changed)  # whenever the configuration was changed, apply it for all plots with config_changed
        config_widget.plotwidget = plotwidget
        # Set the size
        config_widget.resize(1000, 800)  # TODO, calculate the size of the widget
        # plotwidget.config = config_widget.config
        plotwidget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        # Add the configuration widget to the plotwidget
        plotwidget.config_widget = config_widget
        # Add a clear buffer button to the config widget if its a graph
        if ('graph' in plottype.lower()):
            config_widget.clearbtn = QtWidgets.QPushButton('Clear buffer')
            config_widget.layout.addWidget(config_widget.clearbtn, 1, 0,1,2)
            config_widget.clearbtn.clicked.connect(plotwidget.clear_buffer)

        return plotwidget



    def addPlot(self, plotwidget, j, i, height, width):
        """
        Adds a plot to the gridwidget.
        Args:
            plotwidget: The widget to be added
            j:
            i:
            height:
            width:

        Returns:

        """
        self.layout.addWidget(plotwidget, j, i, height, width)
        # Add the location information
        configuration = plotwidget.config
        configuration['location']['x'].data = i
        configuration['location']['y'].data = j
        configuration['location']['height'].data = height
        configuration['location']['width'].data = width
        configuration.config_widget = plotwidget.config_widget
        configuration.plotwidget = plotwidget
        print('Added plot',type(configuration))
        self.device.config['plots'].append(configuration)
        d = {'plot': plotwidget, 'config': plotwidget.config_widget}
        self.all_plots.append(d)
        self.config_changed()
        plotwidget.show()
        
    def config_changed(self):
        """
        Function is called whenever the configuration has been changed. It updates the configuration of the plotwidgets
        and checkes the subscriptions


        Args:

        Returns:

        """
        funcname = self.__class__.__name__ + '.config_changed'
        configwidget = self.sender()

        if (configwidget is not self.configwidget_global):  # Reload the configwidget, if its not the sender
            self.configwidget_global.reload_config()

        if True:
            for p in self.device.config['plots']:
                try:
                    configwidget_tmp = p.config_widget
                except:
                    configwidget_tmp = None
                if(configwidget_tmp is not self.configwidget_global): # Reload the configwidget, if its not the sender
                    try:
                        p.config_widget.reload_config()
                    except:
                        pass

                try:
                    p.plotwidget.apply_config()
                except Exception as e:
                    logger.exception(e)

        #(re)connecting the devices
        self.device.connect_devices()

    def remPlot(self, plotwidget):
        """
        Removes a plotwidget from the grid

        Args:
            plotwidget:

        Returns:

        """
        self.layout.removeWidget(plotwidget)
        for d in self.all_plots:
            if (d['plot'] == plotwidget):
                print('removing from list')
                self.all_plots.remove(d)
                self.device.config['plots'].remove(plotwidget.config)
                try:
                    r = d['rubber']
                    r.close()
                except:
                    pass
                break

        plotwidget.close()

    def remAllPlots(self):
        """
        Removes all plotwidget from the grid

        Args:

        Returns:

        """

        for d in reversed(self.all_plots):
            plotwidget = d['plot']
            print('removing from list')
            self.all_plots.remove(d)
            self.layout.removeWidget(plotwidget)
            self.device.config['plots'].remove(plotwidget.config)
            try:
                r = d['rubber']
                r.close()
            except:
                pass

            plotwidget.close()


    def commit_clicked(self):
        """

        Returns:

        """
        logger.debug('Commit')
        # Plots have been moved
        if (self.flag_mod_plot):  # Flags are set by the gridwidget buttons
            for d in self.all_plots:
                try:
                    r = d['rubber']
                    plotwidget = d['plot']
                except Exception as e:
                    print('ohoh', e)
                    continue

                iall = []
                jall = []
                rect = r.geometry()
                for child in self.gridcells:
                    if rect.intersects(child.geometry()):
                        iall.append(child.__i__)
                        jall.append(child.__j__)

                if (len(iall) > 0 and len(jall) > 0):
                    inew = min(iall)
                    di = max(iall) - min(iall) + 1
                    jnew = min(jall)
                    dj = max(jall) - min(jall) + 1
                    print('d',d['plot'].config)
                    # Update the location of the configuration
                    d['plot'].config['location']['x'].data = inew
                    d['plot'].config['location']['y'].data = jnew
                    d['plot'].config['location']['width'].data = di
                    d['plot'].config['location']['height'].data = dj
                    self.layout.removeWidget(plotwidget)
                    self.layout.addWidget(plotwidget, jnew, inew, dj, di)

        # Plots have been added
        if (self.flag_add_plot):  # Flags are set by the gridwidget buttons
            self.get_selected_index()  # update self.__add_location__
            if self.__add_location__ is not None:
                plottype = self.displaywidget.addplot_combo.currentText()
                addwidget_called = self.create_plot_widget(plottype)
                self.addPlot(addwidget_called, self.__add_location__[0], self.__add_location__[1],
                             self.__add_location__[2], self.__add_location__[3])

                # Remove all selected indices
                self.unselect_all()

            else:
                logger.debug('Not a valid location for adding plot')

        # Plots have been removed
        if (self.flag_rem_plot):  # Flags are set by the gridwidget buttons
            for d in reversed(self.all_plots):
                try:
                    r = d['rubber']
                    if r.flag_rem:  # If the remove flag is set
                        self.remPlot(d['plot'])
                except Exception as e:
                    logger.debug('Exception {:s}'.format(str(e)))

        print('Calling config changed')
        self.config_changed()


    def unselect_all(self):
        for child in self.findChildren(QtWidgets.QPushButton):
            child.setChecked(False)


class PlotGridWidgetButton(QtWidgets.QPushButton):
    resize_signal = QtCore.pyqtSignal()  # Signal notifying resize

    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()

    def resizeEvent(self, event):
        self.resize_signal.emit()

    def mousePressEvent(self, event):
        QtWidgets.QWidget.mousePressEvent(self.parent(), event)


class RandomDataWidget(QtWidgets.QWidget):
    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()
        self.i = 0
        self.texts = ['Hello', 'redvypr', 'data']
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_status)
        self.statustimer.start(2000)
        self.label = QtWidgets.QLabel(self.texts[0])
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.addWidget(self.label)
        self.config = {}
        self.config['random'] = 10
        self.config_template = {}
        self.config_template['random'] = {'type': 'int', 'default': 11}
        self.setStyleSheet("background-color:green;")

    def update_status(self):
        self.i += 1
        self.i = self.i % len(self.texts)
        self.label.setText(self.texts[self.i])


class ResizableRubberBand(QtWidgets.QWidget):
    """Wrapper to make QRubberBand mouse-resizable using QSizeGrip

    Source: http://stackoverflow.com/a/19067132/435253
    """
    mouse_pressed_left = QtCore.pyqtSignal()  # Signal
    mouse_pressed_right = QtCore.pyqtSignal()  # Signal

    def __init__(self, parent):
        # super(Device, self).__init__(**kwargs)
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

        self.flag_rem = False  # Flag for removal
        self.show()

    def resizeEvent(self, event):
        self.rubberband.resize(self.size())

    def mousePressEvent(self, event):
        print('Mouse press')
        if event.button() == QtCore.Qt.LeftButton:
            print("Left Button Clicked")
        elif event.button() == QtCore.Qt.RightButton:
            #do what you want here
            print("Right Button Clicked")
            self.mouse_pressed_right.emit()

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

        if (flag_rem and self.flag_rem == False):
            col = QtGui.QPalette()
            col.setBrush(QtGui.QPalette.Highlight, QtGui.QBrush(QtCore.Qt.black))
            self.setPalette(col)
            self.flag_rem = True
        else:
            self.flag_rem = False
            col = QtGui.QPalette()
            col.setBrush(QtGui.QPalette.Highlight, QtGui.QBrush(QtCore.Qt.red))
            self.setPalette(col)

        # self.__config_widget__
        # self.oldPos = event.globalPos()
