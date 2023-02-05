from PyQt5 import QtWidgets, QtCore, QtGui
import logging
import sys
import redvypr.files as files
import redvypr.data_packets as data_packets
from redvypr.data_packets import parse_addrstr, addresstypes as redvypr_addresstypes, redvypr_address


_logo_file = files.logo_file
_icon_file = files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr')
logger.setLevel(logging.DEBUG)
#
class datastreamWidget(QtWidgets.QWidget):
    """ Widget that lets the user choose available subscribed devices (if device is not None) and datakeys. This
    devicelock: The user cannot change the device anymore
    """
    device_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the device path was changed
    apply = QtCore.pyqtSignal(dict)  # Signal notifying if the Apply button was clicked
    datakey_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the datakey has changed

    def __init__(self, redvypr, device=None, devicename_highlight=None, datakey=None, deviceonly=False,
                 devicelock=False, subscribed_only=True, showapplybutton=True,datastreamstring=''):
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
        self.datastreamstring_orig = datastreamstring
        self.datastreamstring      = datastreamstring
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

        self.devicelist = QtWidgets.QTreeWidget()  # List of available devices
        self.devicelist.setColumnCount(1)

        self.addressline = QtWidgets.QLineEdit()
        self.addressline.textChanged[str].connect(self.devicecustom_changed)
        self.layout.addWidget(self.devicelist)
        self.layout.addWidget(self.addressline)


        # The datakeys
        if (deviceonly == False):
            pass

        if (showapplybutton):
            self.buttondone = QtWidgets.QPushButton('Apply')
            self.buttondone.clicked.connect(self.done_clicked)
            self.layout.addWidget(self.buttondone)

        devicelist = []
        self.datakeylist_subscribed = {}

        self.__update_devicetree()


    def __update_devicetree(self):

        if True:
            root = self.devicelist.invisibleRootItem()
            # self.devices_listcon.addItem(str(device))
            data_provider_all = self.redvypr.get_data_providing_devices()
            font1 = QtGui.QFont('Arial')
            font1.setBold(True)
            font0 = QtGui.QFont('Arial')

            # Fill the qtreewidget
            # print('data provider',data_provider_all)
            if (data_provider_all is not None):
                for dev in data_provider_all:
                    if dev == self.device:
                        continue

                    itm = QtWidgets.QTreeWidgetItem([dev.name])
                    itm.device = dev
                    itm.redvypr_address = dev.address
                    root.addChild(itm)
                    # Check for forwarded devices
                    if True:
                        devs_forwarded = dev.get_data_provider_info()
                        for devaddress in devs_forwarded.keys():
                            devaddress_redvypr = data_packets.redvypr_address(devaddress)
                            itmf = QtWidgets.QTreeWidgetItem([devaddress])
                            itmf.device = dev
                            itmf.redvypr_address = devaddress_redvypr
                            itmf.address_forwarded = devaddress
                            itm.addChild(itmf)
                            datakeys = devs_forwarded[devaddress]['datakeys']
                            print('Datakeys',datakeys,devs_forwarded[devaddress])
                            for dkey in datakeys:
                                itmk = QtWidgets.QTreeWidgetItem([dkey])
                                itmf.addChild(itmk)

            self.devicelist.expandAll()
            self.devicelist.resizeColumnToContents(0)


    def __addrtype_changed__(self):
        """ Update the datakeylist whenever the device was changed
        """
        funcname = __name__ + '.__addrtype_changed__():'
        logger.debug(funcname)
        print('datastreamstring', self.datastreamstring)
        addrtype = self.addrtype_combo.currentText()
        print('datastreamstring', self.datastreamstring,addrtype)
        raddr = redvypr_address(self.datastreamstring)
        addrstring = raddr.get_str(addrtype)
        print('addrstring',addrstring)
        self.datastreamcustom.setText(addrstring)


    def update_datakeylist(self, devicename):
        """ Update the datakeylist whenever the device was changed
        """
        funcname = __name__ + '.update_datakeylist():'
        logger.debug(funcname)
        self.datakeylist.clear()

        try:
            self.datastreams = self.redvypr.get_datastreams(devicename)
        except Exception as e:
            print('Hallo', e)
            self.datakeys = []
            self.datastreams = []

        self.datakeys = []
        for d in self.datastreams:
            d_parsed = parse_addrstr(d, self.redvypr.hostinfo)
            datakey = d_parsed['datakey']
            uuid = d_parsed['uuid']
            devicename = d_parsed['devicename']
            hostname = d_parsed['hostname']
            addr = d_parsed['addr']
            self.datakeys.append(datakey)


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
            #datakey = self.datakeycustom.text()
            datastream = self.datastreamcustom.text()
        else:
            datakey = None
            datastream = None

        #signal_dict = {'devicename': devicename, 'datakey': datakey, 'datastream': datastream}
        signal_dict = {'devicename': devicename, 'datastream': datastream}
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
        print('datakeys', self.datakeys)
        print('datastream', self.datastreams)
        print('index',index)
        self.datastreamstring = datastream
        self.__addrtype_changed__()
        #self.datakeycustom.setText(str(datakey))
        #self.datastreamcustom.setText(str(datastream))

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
class datastreamWidget_legacy(QtWidgets.QWidget):
    """ Widget that lets the user choose available subscribed devices (if device is not None) and datakeys. This
    devicelock: The user cannot change the device anymore
    """
    device_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the device path was changed
    apply = QtCore.pyqtSignal(dict)  # Signal notifying if the Apply button was clicked
    datakey_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the datakey has changed

    def __init__(self, redvypr, device=None, devicename_highlight=None, datakey=None, deviceonly=False,
                 devicelock=False, subscribed_only=True, showapplybutton=True,datastreamstring=''):
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
        self.datastreamstring_orig = datastreamstring
        self.datastreamstring      = datastreamstring
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

            self.addrtype_combo = QtWidgets.QComboBox()  # Combo for the different combination types

            for t in redvypr_addresstypes:
                self.addrtype_combo.addItem(t)

            self.addrtype_combo.setCurrentIndex(2)
            self.addrtype_combo.currentIndexChanged.connect(self.__addrtype_changed__)
            self.layout.addWidget(self.addrtype_combo)
            #self.datakeycustom = QtWidgets.QLineEdit() #
            #self.layout.addWidget(self.datakeycustom)
            self.datastreamcustom = QtWidgets.QLineEdit()
            self.__addrtype_changed__() # Update the datastream addressstring
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

    def __addrtype_changed__(self):
        """ Update the datakeylist whenever the device was changed
        """
        funcname = __name__ + '.__addrtype_changed__():'
        logger.debug(funcname)
        print('datastreamstring', self.datastreamstring)
        addrtype = self.addrtype_combo.currentText()
        print('datastreamstring', self.datastreamstring,addrtype)
        raddr = redvypr_address(self.datastreamstring)
        addrstring = raddr.get_str(addrtype)
        print('addrstring',addrstring)
        self.datastreamcustom.setText(addrstring)


    def update_datakeylist(self, devicename):
        """ Update the datakeylist whenever the device was changed
        """
        funcname = __name__ + '.update_datakeylist():'
        logger.debug(funcname)
        self.datakeylist.clear()

        try:
            self.datastreams = self.redvypr.get_datastreams(devicename)
        except Exception as e:
            print('Hallo', e)
            self.datakeys = []
            self.datastreams = []

        self.datakeys = []
        for d in self.datastreams:
            d_parsed = parse_addrstr(d, self.redvypr.hostinfo)
            datakey = d_parsed['datakey']
            uuid = d_parsed['uuid']
            devicename = d_parsed['devicename']
            hostname = d_parsed['hostname']
            addr = d_parsed['addr']
            self.datakeys.append(datakey)


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
            #datakey = self.datakeycustom.text()
            datastream = self.datastreamcustom.text()
        else:
            datakey = None
            datastream = None

        #signal_dict = {'devicename': devicename, 'datakey': datakey, 'datastream': datastream}
        signal_dict = {'devicename': devicename, 'datastream': datastream}
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
        print('datakeys', self.datakeys)
        print('datastream', self.datastreams)
        print('index',index)
        self.datastreamstring = datastream
        self.__addrtype_changed__()
        #self.datakeycustom.setText(str(datakey))
        #self.datastreamcustom.setText(str(datastream))

        self.datakey_name_changed.emit(item.text())

    def devicecustom_changed(self, text):
        """ TODO
        """
        pass
        # self.device_name_changed.emit(str(text))