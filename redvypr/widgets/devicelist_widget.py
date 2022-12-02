from PyQt5 import QtWidgets, QtCore, QtGui
import logging
import sys
import redvypr.files as files

_logo_file = files.logo_file
_icon_file = files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr')
logger.setLevel(logging.DEBUG)
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