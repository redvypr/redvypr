import ast
import copy
import os
import time
import datetime
import logging
import queue
import sys
import yaml
from PyQt5 import QtWidgets, QtCore, QtGui
import qtawesome
import inspect
import uuid
import re
from pyqtconsole.console import PythonConsole
from pyqtconsole.highlighter import format

import redvypr.widgets.redvyprSubscribeWidget
# Import redvypr specific stuff
from redvypr.widgets.standard_device_widgets import displayDeviceWidget_standard, redvypr_deviceInitWidget, RedvyprDeviceWidget_simple, RedvyprDeviceWidget_startonly
#from redvypr.gui import datastreamWidget # Do we need this?
import redvypr.gui as gui
from redvypr.version import version
import redvypr.files as files
import redvypr
import faulthandler
faulthandler.enable()

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr_main_widget')
logger.setLevel(logging.INFO)

_logo_file = files.logo_file
_icon_file = files.icon_file


class TabGroupButton(QtWidgets.QPushButton):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
#
#
#
# redvyprwidget
#
#
#

class redvyprWidget(QtWidgets.QWidget):
    """This is the main widget of redvypr.

    """

    def __init__(self, width=None, height=None, config=None, hostname='redvypr', loglevel=None, redvypr_device_scan=None):
        """ Args:
            width:
            height:
            config: Either a string containing a path of a yaml file, or a list with strings of yaml files
        """
        super(redvyprWidget, self).__init__()
        self.setGeometry(50, 50, 500, 300)
        # global loglevel
        if loglevel is not None:
            logger.debug('Setting loglevel to global: "{}"'.format(loglevel))
            logger.setLevel(loglevel)
        else:  # config loglevel
            try:
                logger.setLevel(config.loglevel)
            except:
                logger.debug('Could not set loglevel')

        # Lets create the heart of redvypr
        if config is not None:
            config_tmp = config.model_dump(exclude='devices')
            config_tmp_obj = redvypr.RedvyprConfig(**config_tmp)
        else:
            config_tmp_obj = config

        # Configuration comes later after all widgets are initialized
        self.redvypr = redvypr.Redvypr(hostname=hostname,
                                       config=config_tmp_obj,
                                       redvypr_device_scan=redvypr_device_scan,
                                       loglevel=loglevel)
        self.redvypr.device_path_changed.connect(self.__populate_devicepathlistWidget)
        self.redvypr.device_added.connect(self._add_device_gui)
        # Fill the layout
        self.devicetabs = QtWidgets.QTabWidget()
        self.devicetabs.setMovable(True)
        self.devicetabs.setTabsClosable(True)
        self.devicetabs.tabCloseRequested.connect(self.closeTab)


        # Create home tab
        self.createHomeWidget()
        tab_index = self.devicetabs.addTab(self.__homeWidget, 'Home')
        # Add an icon
        try:
            iconname = self.redvypr.config.gui_home_icon
            if iconname == 'redvypr':
                home_icon = QtGui.QIcon(_icon_file)
            else:
                home_icon = qtawesome.icon(iconname)
            logger.debug('Found icon for home')
            self.devicetabs.setTabIcon(tab_index, home_icon)
        except:
            device_icon = None

        # A timer to gather all the data from the devices
        self.devicereadtimer = QtCore.QTimer()
        self.devicereadtimer.timeout.connect(self.readguiqueue)
        self.devicereadtimer.start(100)
        # self.devicereadtimer.start(500)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.addWidget(self.devicetabs)
        if ((width is not None) and (height is not None)):
            self.resize(int(width), int(height))

        # TODO, configuration was done earlier, check if this is still ok
        self.redvypr.add_devices_from_config(config)
        # Update hostinformation widgets
        self.__update_hostinfo_widget__()
        self.__populate_devicepathlistWidget()

    def createHomeWidget(self):
        """
        Creates the home widget with the basic information/control/config functionality
        :return:
        """
        self.__homeWidget = QtWidgets.QTabWidget()
        self.__homeWidget_layout = QtWidgets.QVBoxLayout(self.__homeWidget)
        self.__deviceTableWidget = gui.deviceTableWidget(redvyprWidget=self)
        #font = QtGui.QFont('Arial', 20)
        font = QtGui.QFont('Arial')
        font.setBold(True)
        self.__mainLabel = QtWidgets.QLabel('Host information')
        self.__mainLabel.setFont(font)
        self.__mainLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.__homeWidget_layout.addWidget(self.__mainLabel)
        # The configuration of the redvypr
        self.create_devicepathwidget()
        self.create_statuswidget_compact()
        # self.devicetabs.addTab(self.__devicepathwidget,'Status')
        self.__homeWidget_layout.addWidget(self.__statuswidget_compact)

        # Device path
        self.__deviceAddButton = QtWidgets.QPushButton('Add device')
        self.__deviceAddButton.clicked.connect(self.open_add_device_widget)
        self.__deviceAddButton.setFont(font)
        #self.__groupAddButton = QtWidgets.QPushButton('Add group')
        #self.__groupAddButton.clicked.connect(self.__add_group_clicked)
        #self.__groupAddButton.setFont(font)
        self.__homeWidget_layout.addWidget(self.__deviceAddButton)
        #self.__homeWidget_layout.addWidget(self.__groupAddButton)
        self.__homeWidget_layout.addWidget(self.__deviceTableWidget)
        ## Configure button
        #self.__homeWidget_layout.addWidget(self.__host_config_btn)

    def __add_group_clicked(self):
        funcname = __name__ + '.__add_group_clicked():'
        logger.debug(funcname)
        # Create a test group tab
        tab_index = self.devicetabs.addTab(QtWidgets.QWidget(), '')
        tabbar = self.devicetabs.tabBar()
        ind_tab = self.devicetabs.count()
        button = QtWidgets.QPushButton("G G G")
        button.setFixedSize(100, 30)  #
        menu = QtWidgets.QMenu()
        action1 = QtWidgets.QAction("Option 1", self)
        action2 = QtWidgets.QAction("Option 2", self)
        menu.addAction(action1)
        menu.addAction(action2)
        button.setMenu(menu)
        print('Ind tab', ind_tab)
        tabbar.setTabButton(ind_tab - 1, QtWidgets.QTabBar.RightSide, button)
        self.bbbbb = button

    def open_ipwidget(self):
        pass
        #self.ipwidget = redvypr_ip_widget()

    def open_console(self):
        """ Opens a pyqtconsole console widget

        """
        if True:
            width = 800
            height = 500
            # Console
            self.console = PythonConsole(formats={
                'keyword': format('darkBlue', 'bold')
            })
            self.console.setWindowIcon(QtGui.QIcon(_icon_file))
            self.console.setWindowTitle("redvypr console")
            self.console.push_local_ns('redvypr_widget', self)
            self.console.push_local_ns('redvypr', self.redvypr)
            self.console.resize(width, height)
            self.console.show()

            self.console.eval_queued()

        # self.devicetabs.addTab(self.console,'Console')

    def renamedevice(self, oldname, name):
        """ Renames a devices
        """
        funcname = 'renamedevice()'
        for dev in self.redvypr.devices:
            devname = dev['device'].name
            if (devname == name):  # Found a device with that name already, lets do nothging
                logger.debug(funcname + ': Name already in use. Will not rename')
                return False

        for dev in self.redvypr.devices:
            devname = dev['device'].name
            if (devname == oldname):  # Found the device, lets rename it
                dev['device'].change_name(name)
                widget = dev['widget']
                for i in range(self.devicetabs.count()):
                    if (self.devicetabs.widget(i) == widget):
                        self.devicetabs.setTabText(i, name)
                        break

                break

        return True

    def readguiqueue(self):
        """This periodically called function reads the guiqueue and calls
        the widgets of the devices update function (if they exist)

        """
        # Update devices
        for devicedict in self.redvypr.devices:
            device = devicedict['device']
            if True:
                # Feed the data into the modules/functions/objects and
                # let them treat the data
                for i, (guiqueue, gui_widget) in enumerate(devicedict['guiqueues']):
                    while True:
                        try:
                            data = guiqueue.get(block=False)
                        except Exception as e:
                            # print('Exception gui',e)
                            break

                        # Updating the widget, if existing
                        try:
                            gui_widget.update_data(data)
                        except Exception as e:
                            break
                            # logger.exception(e)

    def readguiqueue_legacy(self):
        """This periodically called function reads the guiqueue and calls
        the widgets of the devices update function (if they exist)

        """
        # Update devices
        for devicedict in self.redvypr.devices:
            device = devicedict['device']
            if True:
                # Feed the data into the modules/functions/objects and
                # let them treat the data
                for i, guiqueue in enumerate(devicedict['guiqueue']):
                    while True:
                        try:
                            data = guiqueue.get(block=False)
                        except Exception as e:
                            # print('Exception gui',e)
                            break
                        try:
                            devicedict['gui'][i].update(data)
                        except Exception as e:
                            break
                            # logger.exception(e)

    def load_config(self):
        """ Loads a configuration file
        """
        funcname = self.__class__.__name__ + '.load_config():'
        logger.debug(funcname)
        conffile, _ = QtWidgets.QFileDialog.getOpenFileName(self, "QFileDialog.getOpenFileName()", "",
                                                            "Yaml Files (*.yaml);;All Files (*)")
        if conffile:
            self.redvypr.parse_configuration(conffile)

    def save_config(self):
        """ Saves a configuration file
        """
        funcname = self.__class__.__name__ + '.save_config():'
        logger.debug(funcname)
        config = self.redvypr.get_config()
        data_save = config.model_dump()
        #print('Data save',data_save)
        if True:
            tstr = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
            fname_suggestion = 'config_' + self.redvypr.hostinfo['hostname'] + '_' + tstr + '.yaml'

            fname_full, _ = QtWidgets.QFileDialog.getSaveFileName(self, "QFileDialog.getSaveFileName()",
                                                                  fname_suggestion,
                                                                  "Yaml Files (*.yaml);;All Files (*)")
            #print('fname',fname_full)
            if fname_full:
                logger.debug('Saving to file {:s}'.format(fname_full))
                with open(fname_full, 'w') as fyaml:
                    yaml.dump(data_save, fyaml)

    def open_add_device_widget(self):
        """
        Opens a widget to let the user add redvypr devices
        """
        app = QtWidgets.QApplication.instance()
        screen = app.primaryScreen()
        # print('Screen: %s' % screen.name())
        size = screen.size()
        # print('Size: %d x %d' % (size.width(), size.height()))
        rect = screen.availableGeometry()
        # print('Available: %d x %d' % (rect.width(), rect.height()))
        self.add_device_widget = gui.redvyprAddDeviceWidget(redvypr=self.redvypr)
        self.add_device_widget.resize(int(rect.width() * 0.75), int(rect.height() * 0.75))
        self.add_device_widget.show()

    def _add_device_gui(self, devicelist):
        """ Function is called via the redvypr.add_device signal and is adding
        all the gui functionality to the device

        """
        funcname = __name__ + '._add_device_gui():'
        logger.debug(funcname)
        devicedict = devicelist[0]
        ind_devices = devicelist[1]
        devicemodule = devicelist[2]
        # The widget shown in the tab
        device = devicedict['device']
        devicewidget = QtWidgets.QWidget()
        devicewidget.device = device  # Add the device to the devicewidget
        devicelayout = QtWidgets.QVBoxLayout(devicewidget)

        # Search first for a redvyprdevicewidget, if one is found, take it, otherwise use a init/display widget pair
        try:
            redvyprdevicewidget = devicemodule.RedvyprDeviceWidget
        except:
            logger.debug(funcname + 'Widget does not have a RedvyprDeviceWidget using init/display combination')
            redvyprdevicewidget = None

        if redvyprdevicewidget is not None:
            initargs = inspect.signature(redvyprdevicewidget.__init__)
            initargs_parameters = dict(initargs.parameters)
            initargs2 = None
            if (RedvyprDeviceWidget_startonly in redvyprdevicewidget.__mro__):
                initargs2 = inspect.signature(redvypr_deviceInitWidget.__init__)
            if (RedvyprDeviceWidget_simple in redvyprdevicewidget.__mro__):
                initargs2 = inspect.signature(redvypr_deviceInitWidget.__init__)
            if initargs2 is not None:
                logger.debug(funcname + 'adding arguments {}'.format(dict(initargs2.parameters)))
                initargs_parameters.update(dict(initargs2.parameters))

            initdict = {}
            if ('device' in initargs_parameters.keys()):
                initdict['device'] = device
            if ('redvypr' in initargs_parameters.keys()):
                initdict['redvypr'] = self.redvypr

            device.redvyprdevicewidget = redvyprdevicewidget(**initdict)
            devicelayout.addWidget(device.redvyprdevicewidget)
            self.redvypr.devices[ind_devices]['guiqueues'][0][1] = device.redvyprdevicewidget
            self.redvypr.devices[ind_devices]['displaywidget'] = device.redvyprdevicewidget
            self.redvypr.devices[ind_devices]['initwidget'] = device.redvyprdevicewidget
        else: # Use the init/displaywidget, using tabs
            # The tab for the init and device tab
            devicetab = QtWidgets.QTabWidget()
            devicetab.setMovable(True)
            devicelayout.addWidget(devicetab)
            # Now add all the widgets to the device
            #
            # Create the init widget
            try:
                deviceinitwidget_bare = devicemodule.initDeviceWidget
            except:
                logger.debug(funcname + 'Widget does not have a deviceinitwidget using standard one')
                # logger.exception(e)
                deviceinitwidget_bare = redvypr_deviceInitWidget  # Use a standard widget


            # Call the deviceinitwidget with extra arguments
            initargs = inspect.signature(deviceinitwidget_bare.__init__)
            initargs_parameters = dict(initargs.parameters)
            logger.debug(funcname + 'Initargs for initwidget {}'.format( initargs_parameters))
            # Check if the parent is a deviceinitwidget
            #print('fdsfsd',deviceinitwidget_bare.__mro__)
            if redvypr_deviceInitWidget in deviceinitwidget_bare.__mro__:
                logger.debug(funcname + ' Child of deviceinitwidet')
                initargs2 = inspect.signature(redvypr_deviceInitWidget.__init__)
                logger.debug(funcname + 'adding arguments {}'.format(dict(initargs2.parameters)))
                initargs_parameters.update(dict(initargs2.parameters))
            else:
                initargs_parameters = dict(initargs.parameters)

            initdict = {}
            if ('device' in initargs_parameters.keys()):
                initdict['device'] = device

            if ('redvypr' in initargs_parameters.keys()):
                initdict['redvypr'] = self.redvypr

            if ('tabwidget' in initargs_parameters.keys()):
                initdict['tabwidget'] = devicetab

            # https://stackoverflow.com/questions/334655/passing-a-dictionary-to-a-function-as-keyword-parameters
            try:
                deviceinitwidget = deviceinitwidget_bare(**initdict)
            except Exception as e:
                logger.warning(funcname + 'Could not add deviceinitwidget because of:')
                logger.exception(e)
                deviceinitwidget = QtWidgets.QWidget()  # Use a standard widget

            # Connect the connect signal with connect_device()
            try:
                logger.debug(funcname + 'Connect signal connected')
                deviceinitwidget.connect.connect(self.connect_device)
            except Exception as e:
                logger.debug(funcname + 'Widget does not have connect signal:' + str(e))

            device.deviceinitwidget = deviceinitwidget
            #
            # Check if we have a widget to display the data
            # Create the displaywidget
            #
            try:
                devicedisplaywidget = devicemodule.displayDeviceWidget
            except Exception as e:
                logger.debug(funcname + 'No displaywidget found for {:s}'.format(str(devicemodule)))
                ## Using the standard display widget
                # devicedisplaywidget = displayDeviceWidget_standard
                devicedisplaywidget = None

            # Add init widget
            try:
                tablabelinit = str(device.device_parameter.gui_tablabel_init)
            except:
                tablabelinit = 'Init'
            # print('Device hallo hallo',device.config)
            # device.config['redvypr_device']['gui_tablabel_status']

            devicetab.addTab(deviceinitwidget, tablabelinit)

            # Devices can have their specific display objects, if one is
            # found, initialize it, otherwise just the init Widget
            if (devicedisplaywidget is not None):
                initargs = inspect.signature(devicedisplaywidget.__init__)
                initdict = {}
                if ('device' in initargs.parameters.keys()):
                    initdict['device'] = device

                if ('tabwidget' in initargs.parameters.keys()):
                    initdict['tabwidget'] = devicetab

                if ('deviceinitwidget' in initargs.parameters.keys()):
                    initdict['deviceinitwidget'] = deviceinitwidget

                # https://stackoverflow.com/questions/334655/passing-a-dictionary-to-a-function-as-keyword-parameters
                devicedisplaywidget_called = devicedisplaywidget(**initdict)
                # Add the widget to the device
                device.devicedisplaywidget = devicedisplaywidget_called
                # Test if the widget has a tabname
                try:
                    tablabeldisplay = devicedisplaywidget_called.tabname
                except:
                    try:
                        tablabeldisplay = str(device.device_parameter.gui_tablabel_display)
                    except:
                        tablabeldisplay = 'Display'

                # Check if the widget has included itself, otherwise add the displaytab
                # This is useful to have the displaywidget add several tabs
                # by using the tabwidget argument of the initdict
                if (devicetab.indexOf(devicedisplaywidget_called)) < 0:
                    devicetab.addTab(devicedisplaywidget_called, tablabeldisplay)
                    # Append the widget to the processing queue

                # Update the first entry of the guiqueue list with the displaywidget
                self.redvypr.devices[ind_devices]['guiqueues'][0][1] = devicedisplaywidget_called
                self.redvypr.devices[ind_devices]['displaywidget'] = devicedisplaywidget_called
                self.redvypr.devices[ind_devices]['initwidget'] = deviceinitwidget
            else:
                self.redvypr.devices[ind_devices]['initwidget'] = deviceinitwidget
                self.redvypr.devices[ind_devices]['displaywidget'] = None


        self.redvypr.devices[ind_devices]['widget'] = devicewidget  # This is the displaywidget
        #
        # Add the devicelistentry to the widget, this gives the full information to the device
        #
        # 22.11.2022 TODO, this needs to be replaced by functional arguments instead of properties
        self.redvypr.devices[ind_devices]['initwidget'].redvyprdevicelistentry = self.redvypr.devices[ind_devices]
        self.redvypr.devices[ind_devices]['initwidget'].redvypr = self.redvypr
        if (len(self.redvypr.devices[ind_devices]['guiqueues']) > 0):
            if self.redvypr.devices[ind_devices]['guiqueues'][0][1] is not None:
                self.redvypr.devices[ind_devices]['guiqueues'][0][1].redvyprdevicelistentry = self.redvypr.devices[ind_devices]
                self.redvypr.devices[ind_devices]['guiqueues'][0][1].redvypr = self.redvypr

        # Get an icon for the device
        try:
            iconname = device.device_parameter.gui_icon
            device_icon = qtawesome.icon(iconname)
            logger.debug(funcname + 'Found icon for device')
        except:
            device_icon = None
        # Add the widget to the devicetab, or as a sole window or hide
        widgetname = device.name
        widgetloc = device.device_parameter.gui_dock
        if widgetloc == 'Window':
            devicewidget.setParent(None)
            devicewidget.setWindowTitle(widgetname)
            devicewidget.show()
        elif widgetloc == 'Hide':
            devicewidget.setParent(None)
            devicewidget.setWindowTitle(widgetname)
            devicewidget.hide()
        else:
            if device_icon is not None:
                self.devicetabs.addTab(devicewidget, device_icon, widgetname)
            else:
                self.devicetabs.addTab(devicewidget, widgetname)
            #self.devicetabs.setCurrentWidget(devicewidget)

        # All set, now call finalizing functions
        # Finalize the initialization by calling a helper function (if exist)
        try:
            deviceinitwidget.finalize_init()
        except Exception as e:
            pass
            #logger.debug(funcname + ':finalize_init():' + str(e))

        try:
            devicedisplaywidget_called.finalize_init()
        except Exception as e:
            pass
            #logger.debug(funcname + ':finalize_init():' + str(e))

    def connect_device_gui(self):
        """ Wrapper for the gui
        """
        # Get the current tab
        curtab = self.devicetabs.currentWidget()
        try:
            device = curtab.device
        except:
            device = None
        self.open_connect_widget(device=device)

    def connect_device(self, device):
        """ Handles the connect signal from devices, called when the connection between the device shall be changed
        """
        logger.debug('Connect clicked')
        if (type(device) == dict):
            device = device['device']
        self.open_connect_widget(device=device)

    def open_connect_widget(self, device=None):
        funcname = __name__ + '.open_connect_widget()'
        logger.debug(funcname + ':' + str(device))
        # self.__con_widget = redvyprConnectWidget(devices=self.redvypr.devices, device=device)
        self.__con_widget = redvypr.widgets.redvyprSubscribeWidget.redvyprSubscribeWidget(redvypr=self.redvypr, device=device)
        self.__con_widget.show()

    def __hostname_changed_click(self):
        hostname, ok = QtWidgets.QInputDialog.getText(self, 'redvypr hostname', 'Enter new hostname:')
        if ok:
            self.redvypr.hostinfo['hostname'] = hostname
            self.__hostname_line.setText(hostname)

    def __update_hostinfo_widget__(self):
        """
        Updates the hostinformation
        Returns:

        """
        funcname = __name__ + '.__update_hostinfo_widget__()'
        print(funcname)

    def __update_status_widget__(self):
        """
        Updates the status information
        Returns:

        """


        if self.redvypr.datadistthread.is_alive() == False:
            self.__status_thread.setText(
                'Datadistribution thread is not running! This is bad, consider restarting redvypr.')
            self.__status_thread.setStyleSheet("QLabel { background-color : white; color : red; }")
        else:
            try:
                npackets = self.redvypr.packets_processed
            except:
                npackets = 0
            if (npackets > 0) and (self.redvypr.dt_avg_datadist > 0):
                packets_pstr = npackets / self.redvypr.dt_avg_datadist
            else:
                packets_pstr = 0.0

            trun = time.time() - self.redvypr.t_thread_start
            npackets_total = self.redvypr.packets_counter
            statusstr = 'Running: {:.0f}s, dt: {:0.5f}s (needed {:0.5f}s, {:6.1f} packets/s), Packets processed {:d}'.format(trun, self.redvypr.dt_datadist, self.redvypr.dt_avg_datadist, packets_pstr, npackets_total)
            self.__status_thread.setText(statusstr)

    def create_statuswidget_compact(self):
        """Creates the statuswidget

        """
        self.redvypr.status_update_signal.connect(self.__update_status_widget__)
        self.redvypr.hostconfig_changed_signal.connect(self.__update_hostinfo_widget__)
        self.__statuswidget_compact = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(self.__statuswidget_compact)
        self.__status_thread_label = QtWidgets.QLabel('Data distribution thread:')
        # dt
        self.__status_thread = QtWidgets.QLabel('')
        self.__update_status_widget__()
        layout.addRow(self.__status_thread_label,self.__status_thread)#, self.__status_dtneeded)

        # Hostname
        self.__hostname_label = QtWidgets.QLabel('Hostname:')
        self.__hostname_line = QtWidgets.QLabel('')
        self.__hostname_line.setAlignment(QtCore.Qt.AlignRight)
        self.__hostname_line.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.__hostname_line.setText(self.redvypr.hostinfo['hostname'])
        # UUID
        self.__uuid_label = QtWidgets.QLabel('UUID:')
        self.__uuid_line = QtWidgets.QLabel('')
        self.__uuid_line.setAlignment(QtCore.Qt.AlignRight)
        self.__uuid_line.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.__uuid_line.setText(self.redvypr.hostinfo['uuid'])
        # IP
        self.__ip_label = QtWidgets.QLabel('IP:')
        self.__ip_line = QtWidgets.QLabel('')
        self.__ip_line.setAlignment(QtCore.Qt.AlignRight)
        self.__ip_line.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.__ip_line.setText(self.redvypr.hostinfo['addr'])
        # Configuration
        #self.__host_config_btn = QtWidgets.QPushButton('Configure')
        #self.__host_config_btn.clicked.connect(self.__open_configWidget)
        #self.__host_config_widget = QtWidgets.QWidget()
        #self.__host_config_widget_layout = QtWidgets.QFormLayout(self.__host_config_widget)
        # Configuration widgets for detailed configuration, opened when clicked configure button
        # Change the hostname
        self.__hostinfo_opt_btn = QtWidgets.QPushButton('Edit optional information')
        self.__hostinfo_opt_btn.clicked.connect(self.__hostinfo_opt_changed_click)

        self.__statuswidget_pathbtn = QtWidgets.QPushButton('Edit device path')
        self.__statuswidget_pathbtn.clicked.connect(self.show_devicepathwidget)

        layout.addRow(self.__hostname_label, self.__hostname_line)
        layout.addRow(self.__uuid_label, self.__uuid_line)
        layout.addRow(self.__ip_label, self.__ip_line)
        layout.addRow(self.__ip_label, self.__ip_line)
        #layout.addRow(self.__host_config_label,self.__host_config_btn)
        #self.__host_config_widget_layout.addRow(self.__hostinfo_opt_btn)
        #self.__host_config_widget_layout.addRow(self.__statuswidget_pathbtn)


        logo = QtGui.QPixmap(_logo_file)
        logolabel = QtWidgets.QLabel()
        logolabel.setPixmap(logo)
        # layout.addRow(logolabel)

    def __open_configWidget(self):
        self.__host_config_widget.show()

    def create_statuswidget(self):
        """Creates the statuswidget

        """
        self.redvypr.status_update_signal.connect(self.__update_status_widget__)
        self.redvypr.hostconfig_changed_signal.connect(self.__update_hostinfo_widget__)
        self.__statuswidget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(self.__statuswidget)
        # dt
        self.__status_dt = QtWidgets.QLabel('Distribution time: {:0.5f}s'.format(self.redvypr.dt_datadist))
        self.__status_dtneeded = QtWidgets.QLabel(' (needed {:0.5f}s)'.format(self.redvypr.dt_avg_datadist))

        layout.addRow(self.__status_dt, self.__status_dtneeded)

        # Hostname
        self.__hostname_label = QtWidgets.QLabel('Hostname:')
        self.__hostname_line = QtWidgets.QLabel('')
        self.__hostname_line.setAlignment(QtCore.Qt.AlignRight)
        self.__hostname_line.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.__hostname_line.setText(self.redvypr.hostinfo['hostname'])
        # UUID
        self.__uuid_label = QtWidgets.QLabel('UUID:')
        self.__uuid_line = QtWidgets.QLabel('')
        self.__uuid_line.setAlignment(QtCore.Qt.AlignRight)
        self.__uuid_line.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.__uuid_line.setText(self.redvypr.hostinfo['uuid'])
        # IP
        self.__ip_label = QtWidgets.QLabel('IP:')
        self.__ip_line = QtWidgets.QLabel('')
        self.__ip_line.setAlignment(QtCore.Qt.AlignRight)
        self.__ip_line.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.__ip_line.setText(self.redvypr.hostinfo['addr'])

        # Location
        try:
            location = self.redvypr.metadata['location'].data
        except:
            location = ''

        self.__loc_label = QtWidgets.QLabel('Location:')
        self.__loc_text = QtWidgets.QLineEdit(location)
        self.__loc_text.textold = self.__loc_text.text()  # the old text to check again
        self.__loc_text.editingFinished.connect(self.__hostinfo_opt_changed_text)

        # Description
        try:
            description = self.redvypr.metadata['description'].data
        except:
            description = ''

        self.__desc_label = QtWidgets.QLabel('Description:')
        self.__desc_text = QtWidgets.QLineEdit(description)
        self.__desc_text.textold = self.__desc_text.text()  # the old text to check again
        self.__desc_text.editingFinished.connect(self.__hostinfo_opt_changed_text)

        # Lon
        try:
            lon = self.redvypr.metadata['lon'].data
        except:
            lon = -9999.0

        # Lon/Lat
        try:
            lat = self.redvypr.metadata['lat'].data
        except:
            lat = -9999.0

        self.__lon_label = QtWidgets.QLabel('Longitude:')
        self.__lat_label = QtWidgets.QLabel('Latitude:')
        self.__lon_text = QtWidgets.QDoubleSpinBox()
        self.__lon_text.setMinimum(-9999)
        self.__lon_text.setMaximum(360)
        self.__lon_text.setSingleStep(0.00001)
        self.__lon_text.setDecimals(5)
        self.__lon_text.setValue(lon)
        self.__lon_text.oldvalue = self.__lon_text.value()
        self.__lon_text.editingFinished.connect(self.__hostinfo_opt_changed_text)

        self.__lat_text = QtWidgets.QDoubleSpinBox()
        self.__lat_text.setMinimum(-9999)
        self.__lat_text.setMaximum(90)
        self.__lat_text.setSingleStep(0.00001)
        self.__lat_text.setDecimals(5)
        self.__lat_text.setValue(lat)
        self.__lat_text.oldvalue = self.__lat_text.value()
        self.__lat_text.editingFinished.connect(self.__hostinfo_opt_changed_text)

        # Change the hostname
        self.__hostinfo_opt_btn = QtWidgets.QPushButton('Edit optional information')
        self.__hostinfo_opt_btn.clicked.connect(self.__hostinfo_opt_changed_click)

        self.__statuswidget_pathbtn = QtWidgets.QPushButton('Edit device path')
        self.__statuswidget_pathbtn.clicked.connect(self.show_devicepathwidget)

        layout.addRow(self.__hostname_label, self.__hostname_line)
        layout.addRow(self.__uuid_label, self.__uuid_line)
        layout.addRow(self.__ip_label, self.__ip_line)
        layout.addRow(self.__desc_label, self.__desc_text)
        layout.addRow(self.__loc_label, self.__loc_text)
        layout.addRow(self.__lon_label, self.__lon_text)
        layout.addRow(self.__lat_label, self.__lat_text)
        layout.addRow(self.__hostinfo_opt_btn)
        layout.addRow(self.__statuswidget_pathbtn)

        logo = QtGui.QPixmap(_logo_file)
        logolabel = QtWidgets.QLabel()
        logolabel.setPixmap(logo)
        # layout.addRow(logolabel)

    def __hostinfo_opt_changed_text(self):
        """
        Called when the textedit was done, updates the hostinformation,
        Returns:

        """
        funcname = __name__ + '.__hostinfo_opt_changed_text()'
        print(funcname)
        FLAG_CHANGE = False
        # Location text
        if self.__loc_text.textold == self.__loc_text.text():
            print('Not really a change of the text')
        else:
            self.__loc_text.textold = self.__loc_text.text()
            self.redvypr.metadata['location'].data = self.__loc_text.text()
            FLAG_CHANGE = True

        # Location text
        if self.__desc_text.textold == self.__desc_text.text():
            print('Not really a change of the description text')
        else:
            self.__desc_text.textold = self.__desc_text.text()
            self.redvypr.metadata['description'].data = self.__desc_text.text()
            FLAG_CHANGE = True

        # Longitude
        if self.__lon_text.oldvalue == self.__lon_text.value():
            print('Not really a change of the longitude')
        else:
            self.__lon_text.oldvalue = self.__lon_text.value()
            self.redvypr.metadata['lon'].data = self.__lon_text.value()
            FLAG_CHANGE = True

        # Latitude
        if self.__lat_text.oldvalue == self.__lat_text.value():
            print('Not really a change of the latitude')
        else:
            self.__lat_text.oldvalue = self.__lat_text.value()
            self.redvypr.metadata['lat'].data = self.__lat_text.value()
            FLAG_CHANGE = True

        if FLAG_CHANGE:
            print('Things have changed, lets send a signal')
            try:
                self.__hostinfo_opt_edit.reload_config()
            except:
                pass
            self.redvypr.hostconfig_changed_signal.emit()

    def __hostinfo_opt_changed_click(self):
        """
        Opens a widget that allow to change the optional hostinformation
        Returns:

        """
        # Optional hostinformation
        self.__hostinfo_opt_edit = gui.configWidget(self.redvypr.metadata, loadsavebutton=False,
                                                    redvypr_instance=self.redvypr)

        self.__hostinfo_opt_edit.show()

    def show_devicepathwidget(self):
        """A widget to show the pathes to search for additional devices

        """
        self.__devicepathwidget.show()

    def create_devicepathwidget(self):
        """A widget to show the pathes to search for additional devices

        """
        self.__devicepathwidget = QtWidgets.QWidget()
        self.__devicepathlab = QtWidgets.QLabel('Devicepathes')  # Button to add a path
        self.__deviceaddpathbtn = QtWidgets.QPushButton('Add')  # Button to add a path
        self.__deviceaddpathbtn.clicked.connect(self.adddevicepath)
        self.__devicerempathbtn = QtWidgets.QPushButton('Remove')  # Button to remove a path
        self.__devicerempathbtn.clicked.connect(self.remdevicepath)
        layout = QtWidgets.QFormLayout(self.__devicepathwidget)
        self.__devicepathlist = QtWidgets.QListWidget()
        layout.addRow(self.__devicepathlab)
        layout.addRow(self.__devicepathlist)
        layout.addRow(self.__deviceaddpathbtn, self.__devicerempathbtn)
        self.__populate_devicepathlistWidget()

    def __populate_devicepathlistWidget(self):
        self.__devicepathlist.clear()
        for d in self.redvypr.device_paths:
            itm = QtWidgets.QListWidgetItem(d)
            self.__devicepathlist.addItem(itm)

    def __property_widget(self, device=None):
        """

        Returns:

        """
        w = QtWidgets.QWidget()
        if (device == None):
            props = self.properties
        else:
            props = device.properties

    def adddevicepath(self):
        """Adds a path to the devicepathlist
        """
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Devicepath', '')
        if folder:
            self.redvypr.adddevicepath(folder)

    def remdevicepath(self):
        """Removes the selected device pathes
        """
        ind = self.__devicepathlist.currentRow()
        rempath = self.__devicepathlist.item(ind).text()
        # Remove from the main widget and redraw the whole list (is done by the signal emitted by redvypr)
        self.redvypr.remdevicepath(rempath)

    def closeTab(self, currentIndex):
        """ Closing a device tab and removing the device
        """
        funcname = __name__ + '.closeTab()'
        logger.debug('Closing the tab now')
        currentWidget = self.devicetabs.widget(currentIndex)
        # Search for the corresponding device
        for sendict in self.redvypr.devices:
            if (sendict['widget'] == currentWidget):
                device = sendict['device']
                self.redvypr.rem_device(device)
                # Close the widgets (init/display)
                currentWidget.close()
                # TODO: remove
                ## Info
                #sendict['controlwidget'].close()

                self.devicetabs.removeTab(currentIndex)
                break

    def close_application(self):
        funcname = __name__ + '.close_application():'
        print(funcname + ' Closing ...')
        try:
            self.add_device_widget.close()
        except:
            pass

        for sendict in self.redvypr.devices:
            print(funcname + ' Stopping {:s}'.format(sendict['device'].name))
            sendict['device'].thread_stop()

        time.sleep(1)
        for sendict in self.redvypr.devices:
            try:
                sendict['device'].thread.kill()
            except:
                pass

        print('All stopped, sys.exit()')
        # sys.exit()
        os._exit(1)

    def closeEvent(self, event):
        self.close_application()


#
#
# The main widget
#
#
class redvyprMainWidget(QtWidgets.QMainWindow):
    def __init__(self, width=None,height=None,config=None,hostname=None,loglevel=None,redvypr_device_scan=None):
        super(redvyprMainWidget, self).__init__()
        # self.setGeometry(0, 0, width, height)

        # self.setWindowTitle("redvypr")
        self.setWindowTitle(hostname)
        # Add the icon
        # self.setWindowIcon(QtGui.QIcon(_icon_file))

        self.redvypr_widget = redvyprWidget(config=config,
                                            hostname=hostname,
                                            redvypr_device_scan=redvypr_device_scan,
                                            loglevel=loglevel)
        self.setCentralWidget(self.redvypr_widget)
        quitAction = QtWidgets.QAction("&Quit", self)
        quitAction.setShortcut("Ctrl+Q")
        quitAction.setStatusTip('Close the program')
        quitAction.triggered.connect(self.close_application)

        loadcfgAction = QtWidgets.QAction("&Load", self)
        loadcfgAction.setShortcut("Ctrl+O")
        loadcfgAction.setStatusTip('Load a configuration file')
        loadcfgAction.triggered.connect(self.load_config)

        savecfgAction = QtWidgets.QAction("&Save", self)
        savecfgAction.setShortcut("Ctrl+S")
        savecfgAction.setStatusTip('Saves a configuration file')
        savecfgAction.triggered.connect(self.save_config)

        pathAction = QtWidgets.QAction("&Devicepath", self)
        pathAction.setShortcut("Ctrl+L")
        pathAction.setStatusTip('Edit the device path')
        pathAction.triggered.connect(self.redvypr_widget.show_devicepathwidget)

        deviceAction = QtWidgets.QAction("&Add device", self)
        deviceAction.setShortcut("Ctrl+A")
        deviceAction.setStatusTip('Add a device')
        deviceAction.triggered.connect(self.open_add_device_widget)

        devcurAction = QtWidgets.QAction("&Go to home tab", self)
        devcurAction.setShortcut("Ctrl+H")
        devcurAction.setStatusTip('Go to the home tab')
        devcurAction.triggered.connect(self.goto_home_tab)

        # TODO rename to subscribe
        conAction = QtWidgets.QAction("&Connect devices", self)
        conAction.setShortcut("Ctrl+C")
        conAction.setStatusTip('Connect the input/output datastreams of the devices')
        conAction.triggered.connect(self.connect_device_gui)

        self.statusBar()

        mainMenu = self.menuBar()
        fileMenu = mainMenu.addMenu('&File')
        fileMenu.addAction(loadcfgAction)
        fileMenu.addAction(savecfgAction)
        fileMenu.addAction(pathAction)
        fileMenu.addAction(quitAction)

        deviceMenu = mainMenu.addMenu('&Devices')
        deviceMenu.addAction(devcurAction)
        deviceMenu.addAction(deviceAction)
        deviceMenu.addAction(conAction)

        # Help and About menu
        toolMenu = mainMenu.addMenu('&Tools')
        toolAction = QtWidgets.QAction("&Choose Datastreams ", self)
        toolAction.setStatusTip('Opens a window to choose datastreams from the available devices')
        toolAction.triggered.connect(self.show_deviceselect)
        consoleAction = QtWidgets.QAction("&Open console", self)
        consoleAction.triggered.connect(self.open_console)
        consoleAction.setShortcut("Ctrl+N")
        #IPAction = QtWidgets.QAction("&Network interfaces", self)
        #IPAction.triggered.connect(self.open_ipwidget)
        toolMenu.addAction(toolAction)
        #toolMenu.addAction(IPAction)
        toolMenu.addAction(consoleAction)

        # Help and About menu
        helpAction = QtWidgets.QAction("&About", self)
        helpAction.setStatusTip('Information about the software version')
        helpAction.triggered.connect(self.about)

        helpMenu = mainMenu.addMenu('&Help')
        helpMenu.addAction(helpAction)

        self.resize(width, height)
        self.show()

    def open_console(self):
        self.redvypr_widget.open_console()

    def open_ipwidget(self):
        self.redvypr_widget.open_ipwidget()

    def goto_home_tab(self):
        self.redvypr_widget.devicetabs.setCurrentWidget(self.redvypr_widget.__homeWidget)

    def connect_device_gui(self):
        self.redvypr_widget.connect_device_gui()

    def about(self):
        """
        Opens an "about" widget showing basic information.
        """
        self._about_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self._about_widget)
        label1 = QtWidgets.QTextEdit()
        label1.setReadOnly(True)
        label1.setText(self.redvypr_widget.redvypr.__platform__)
        font = label1.document().defaultFont()
        fontMetrics = QtGui.QFontMetrics(font)
        textSize = fontMetrics.size(0, label1.toPlainText())
        w = textSize.width() + 10
        h = textSize.height() + 20
        label1.setMinimumSize(w, h)
        label1.setMaximumSize(w, h)
        label1.resize(w, h)
        label1.setReadOnly(True)

        layout.addWidget(label1)
        icon = QtGui.QPixmap(_logo_file)
        iconlabel = QtWidgets.QLabel()
        iconlabel.setPixmap(icon)
        layout.addWidget(iconlabel)
        self._about_widget.show()

    def show_deviceselect(self):
        #self.__deviceselect__ = redvypr.widgets.redvyprAddressWidget.datastreamWidget(
        #    redvypr=self.redvypr_widget.redvypr)

        self.__deviceselect__ = redvypr.widgets.redvyprAddressWidget.datastreamQTreeWidget(
            redvypr=self.redvypr_widget.redvypr)
        self.__deviceselect__.show()

    def open_add_device_widget(self):
        self.redvypr_widget.open_add_device_widget()

    def load_config(self):
        self.redvypr_widget.load_config()

    def save_config(self):
        self.redvypr_widget.save_config()

    def close_application(self):
        self.redvypr_widget.close_application()

        sys.exit()

    def closeEvent(self, event):
        self.close_application()



