import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import logging
import sys
import yaml
from redvypr.device import redvypr_device
from redvypr.widgets.gui_config_widgets import redvypr_config_widget

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr')
logger.setLevel(logging.DEBUG)


class displayDeviceWidget_standard(QtWidgets.QWidget):
    """ Widget is displaying incoming data as text
    """

    def __init__(self, device=None, tabwidget=None):
        """
        device [optional]
        tabwidget [optional]

        """
        funcname = __name__ + '.start()'
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        self.device = device
        # A timer that is regularly calling the device.status function
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_status)
        self.statustimer.start(2000)

        self.text = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)
        layout.addWidget(self.text, 0, 0)

    def thread_status(self, status):
        """ This function is regularly called by redvypr whenever the thread is started/stopped
        """
        pass
        # self.update_buttons(status['threadalive'])

    def update_status(self):
        """
        """
        funcname = __name__ + 'update_status():'
        try:
            statusdata = self.device.status()
            # print(funcname + str(statusdata))
            self.text.clear()
            self.text.insertPlainText(str(statusdata))
        except Exception as e:
            # logger.debug(funcname + str(e) + 'hallo')
            pass

    def update(self, data):
        """
        """
        funcname = __name__ + '.update()'
        tnow = time.time()
        # print('got data',data)

        devicename = data['device']
        # Only plot the data in intervals of dt_update length, this prevents high CPU loads for fast devices
        update = (tnow - self.config['last_update']) > self.config['dt_update']

        if (update):
            self.config['last_update'] = tnow


#
class redvypr_devicelist_widget(QtWidgets.QWidget):
    """ Widget that lets the user choose available subscribed devices (if device is not None) and datakeys. This
    devicelock: The user cannot change the device anymore
    """
    device_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the device path was changed
    apply = QtCore.pyqtSignal(dict)  # Signal notifying if the Apply button was clicked
    datakey_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the datakey has changed

    def __init__(self, redvypr, device=None, devicename_highlight=None, datakey=None, deviceonly=False,
                 devicelock=False, subscribed_only=True, showapplybutton=True):
        """
        Args:
            redvypr:
            device:
            devicename_highlight: The devicename that is highlighted in the list
            datakey:
            deviceonly:
            devicelock:
            subscribed_only: Show the subscribed devices only
        """

        super(QtWidgets.QWidget, self).__init__()
        self.setWindowIcon(QtGui.QIcon(_icon_file))
        self.redvypr = redvypr
        self.layout = QtWidgets.QVBoxLayout(self)
        self.deviceonly = deviceonly
        if (devicename_highlight == None):
            self.devicename_highlight = 'Na'
        else:
            self.devicename_highlight = devicename_highlight

        self.device = device
        flag_all_devices = (self.device == None) or (subscribed_only == False)  # All devices or only one device?
        try:
            self.devicename = device.name
        except:
            self.devicename = device
        if (device is not None):
            self.devicenamelabel = QtWidgets.QLabel('Device: ' + self.devicename)
            self.layout.addWidget(self.devicenamelabel)
        else:
            self.devicename = ''

        self.deviceavaillabel = QtWidgets.QLabel('Available devices')
        self.layout.addWidget(self.deviceavaillabel)

        self.devicelist = QtWidgets.QListWidget()  # List of available devices

        self.devicecustom = QtWidgets.QLineEdit()
        self.devicecustom.textChanged[str].connect(self.devicecustom_changed)
        self.layout.addWidget(self.devicelist)
        self.layout.addWidget(self.devicecustom)
        # The datakeys
        if (deviceonly == False):
            self.datakeylist = QtWidgets.QListWidget()  # List of available datakeys
            self.devicedatakeyslabel = QtWidgets.QLabel('Data keys of device')
            self.layout.addWidget(self.devicedatakeyslabel)
            self.layout.addWidget(self.datakeylist)
            self.datakeycustom = QtWidgets.QLineEdit()
            self.layout.addWidget(self.datakeycustom)
            self.datastreamcustom = QtWidgets.QLineEdit()
            self.layout.addWidget(self.datastreamcustom)
            self.datakeylist.itemDoubleClicked.connect(
                self.datakey_clicked)  # TODO here should by an apply signal emitted
            self.datakeylist.currentItemChanged.connect(self.datakey_clicked)

        if (showapplybutton):
            self.buttondone = QtWidgets.QPushButton('Apply')
            self.buttondone.clicked.connect(self.done_clicked)
            self.layout.addWidget(self.buttondone)

        devicelist = []
        self.datakeylist_subscribed = {}

        #
        if (subscribed_only):
            data_providing_devicenames = self.redvypr.get_data_providing_devicenames(device=device)
        else:
            data_providing_devicenames = self.redvypr.get_data_providing_devicenames(None)

        print('data providing devicenames', data_providing_devicenames)
        #
        # Add devices to show
        print('Devices', self.redvypr.devices)
        for devname in data_providing_devicenames:
            devdict = self.redvypr.get_devicedict_from_str(devname)
            print('Devname', devname, 'devdict', devdict)
            if (devname != self.devicename):
                devicelist.append(str(devname))

        # Populate devices
        for devname in devicelist:
            self.devicelist.addItem(devname)

        self.devicelist.itemDoubleClicked.connect(self.device_clicked)  # TODO here should by an apply signal emitted
        self.devicelist.currentItemChanged.connect(self.device_clicked)
        if (len(devicelist) > 0):
            self.device_clicked(self.devicelist.item(0))
        # Update the custom text with the given devicename and check if it exists in the item list
        # If its existing update the datakeylist
        self.devicecustom.setText(str(self.devicename_highlight))

        for i in range(self.devicelist.count() - 1):
            if (self.devicelist.item(i).text() == self.devicename_highlight):
                self.devicelist.setCurrentItem(self.devicelist.item(i))
                # self.device_clicked(self.devicelist.item(i))
                break

                # Update the datakeys of the device
        if (deviceonly == False):
            self.update_datakeylist(self.devicename_highlight)

        if (devicelock):
            self.devicelist.setEnabled(False)

    def update_datakeylist(self, devicename):
        """ Update the datakeylist whenever the device was changed
        """
        funcname = __name__ + '.update_datakeylist():'
        logger.debug(funcname)
        self.datakeylist.clear()

        try:
            self.datakeys = self.redvypr.get_datakeys(devicename)
            self.datastreams = self.redvypr.get_datastreams(devicename)
        except Exception as e:
            print('Hallo', e)
            self.datakeys = []
            self.datastreams = []
        for key in self.datakeys:
            # If a conversion to an int works, make quotations around it, otherwise leave it as it is
            try:
                keyint = int(key)
                keystr = '"' + key + '"'
            except:
                keystr = key

            self.datakeylist.addItem(keystr)

    def done_clicked(self):
        devicename = self.devicecustom.text()
        if (self.deviceonly == False):
            datakey = self.datakeycustom.text()
            datastream = self.datastreamcustom.text()
        else:
            datakey = None
            datastream = None

        signal_dict = {'devicename': devicename, 'datakey': datakey, 'datastream': datastream}
        self.apply.emit(signal_dict)
        self.close()

    def device_clicked(self, item):
        """ If the device was changed, update the datakeylist and emit a signal
        """
        funcname = self.__class__.__name__ + '.device_clicked():'
        logger.debug(funcname)
        devicename = item.text()
        # print('Click',item.text())
        if (self.deviceonly == False):
            self.devicedatakeyslabel.setText('Data keys of device ' + str(devicename))
            self.update_datakeylist(devicename)
        self.devicecustom.setText(str(devicename))
        self.device_name_changed.emit(item.text())

    def datakey_clicked(self, item):
        index = self.datakeylist.currentRow()
        # datakey    = item.text()
        datakey = self.datakeys[index]
        datastream = self.datastreams[index]
        self.datakeycustom.setText(str(datakey))
        self.datastreamcustom.setText(str(datastream))

        self.datakey_name_changed.emit(item.text())

    def devicecustom_changed(self, text):
        """ TODO
        """
        pass
        # self.device_name_changed.emit(str(text))


#
#
#
#
#
class redvypr_deviceInitWidget(QtWidgets.QWidget):
    connect = QtCore.pyqtSignal(
        redvypr_device)  # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices

    def __init__(self, device=None):
        """
        Standard deviceinitwidget if the device is not providing one by itself.

        Args:
            device:
        """
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.config_widgets = []
        self.device = device
        self.config_widget = redvypr_config_widget(template=device.template, config=device.config)

        self.config_widgets.append(self.config_widget)

        # Start-button
        self.startbutton = QtWidgets.QPushButton('Start')
        self.startbutton.clicked.connect(self.start_clicked)
        self.startbutton.setCheckable(True)
        # Process kill button (if thread)
        if (self.device.mp == 'multiprocess'):
            # Killbutton
            self.killbutton = QtWidgets.QPushButton('Kill process')
            self.killbutton.clicked.connect(self.kill_clicked)

        # Connect button
        self.conbutton = QtWidgets.QPushButton("Connect")
        self.conbutton.clicked.connect(self.connect_clicked)
        self.config_widgets.append(self.conbutton)

        self.layout.addWidget(self.config_widget, 0, 0, 1, 4)
        self.layout.addWidget(self.conbutton, 1, 0, 1, 4)
        if (self.device.mp == 'multiprocess'):
            self.layout.addWidget(self.startbutton, 2, 0, 1, 3)
            self.layout.addWidget(self.killbutton, 2, 3)
        else:
            self.layout.addWidget(self.startbutton, 2, 0, 1, 4)

        # If the config is changed, update the device widget

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

        self.config_widget.config_changed.connect(self.config_changed)

    def config_changed(self, config):
        """


        Args:
            config:

        Returns:

        """
        self.device.config = config

    def kill_clicked(self):
        button = self.sender()
        logger.debug("Kill device {:s}".format(self.device.name))
        self.device.kill_process()

    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            logger.debug("button pressed")
            button.setText('Starting')
            config = self.config_widget.get_config()
            self.device.config = config
            self.device.thread_start()
            # self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            # button.setText('Stopping')
            self.startbutton.setChecked(True)
            self.device.thread_stop()

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_status']
        # Running
        if (thread_status):
            self.startbutton.setText('Stop')
            self.startbutton.setChecked(True)
            for w in self.config_widgets:
                w.setEnabled(False)
        # Not running
        else:
            self.startbutton.setText('Start')
            for w in self.config_widgets:
                w.setEnabled(True)

            # Check if an error occured and the startbutton
            if (self.startbutton.isChecked()):
                self.startbutton.setChecked(False)
            # self.conbtn.setEnabled(True)

    def connect_clicked(self):
        button = self.sender()
        self.connect.emit(self.device)