from PyQt5 import QtWidgets, QtCore, QtGui
import logging
import sys
import redvypr.files as files
import redvypr.data_packets as data_packets
from redvypr.redvypr_address import redvypr_address


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


        self.devicelist = QtWidgets.QTreeWidget()  # List of available devices
        self.devicelist.setHeaderLabels(['Datastreams'])
        self.devicelist.setColumnCount(1)
        self.devicelist.itemClicked.connect(self.__device_clicked)

        self.addressline_manual = QtWidgets.QLineEdit()
        self.addressline_manual.setReadOnly(False)
        self.addressline_manual.textChanged.connect(self.__addrManualChanged)

        self.addressline = QtWidgets.QLineEdit()
        self.addressline.setReadOnly(True)


        # A combobox to choose between different styles of the address
        self.addrtype_combo = QtWidgets.QComboBox()  # Combo for the different combination types
        #for t in redvypr_addresstypes:
        #    self.addrtype_combo.addItem(t)

        self.addrtype_combo.setCurrentIndex(2)
        self.addrtype_combo.currentIndexChanged.connect(self.__addrtype_changed__)

        # Add widgets to layout
        self.layout.addWidget(self.deviceavaillabel)
        self.layout.addWidget(self.devicelist)

        self.layout.addWidget(QtWidgets.QLabel('Manual Address'))
        self.layout.addWidget(self.addressline_manual)
        self.layout.addWidget(QtWidgets.QLabel('Address format'))
        self.layout.addWidget(self.addrtype_combo)
        self.layout.addWidget(QtWidgets.QLabel('Address'))
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

    def __addrManualChanged(self,addrstr):
        funcname = __name__ + '.__addrManualChanged():'
        logger.debug(funcname)
        self.addressline.datakey_address = redvypr_address(addrstr)
        self.addressline.device = self.addressline.datakey_address.devicename
        self.addressline.devaddress = self.addressline.datakey_address.address_str
        self.__addrtype_changed__()

    def __device_clicked(self,item):
        """
        Called when an item in the qtree is clicked
        """
        if(item.iskey): # If this is a datakey item
            addrtype = self.addrtype_combo.currentText()
            addrstring = item.datakey_address.get_str(addrtype)
            self.addressline.setText(addrstring)
            self.addressline.datakey_address = item.datakey_address
            self.addressline.device = item.device
            self.addressline.devaddress = item.devaddress

    def __update_devicetree(self):
        if True:
            self.devicelist.clear()
            root = self.devicelist.invisibleRootItem()
            # self.devices_listDevices.addItem(str(device))
            data_provider_all = self.redvypr.get_devices(publishes=True, subscribes=False)
            font1 = QtGui.QFont('Arial')
            font1.setBold(True)
            font0 = QtGui.QFont('Arial')

            # Fill the qtreewidget
            # print('data provider',data_provider_all)
            if (data_provider_all is not None):
                for dev in data_provider_all:
                    flag_datastreams = False
                    if dev == self.device:
                        continue

                    itm = QtWidgets.QTreeWidgetItem([dev.name])
                    col = QtGui.QColor(220,220,220)
                    itm.setBackground(0, col)
                    itm.device = dev
                    itm.redvypr_address = dev.address

                    itm.iskey = False
                    # Check for forwarded devices
                    if True:
                        devs_forwarded = dev.get_device_info()
                        devkeys = list(devs_forwarded.keys())
                        devkeys.sort()
                        for devaddress in devkeys:
                            datakeys = devs_forwarded[devaddress]['datakeys']
                            if len(datakeys) > 0:
                                flag_datastreams = True
                                devaddress_redvypr = data_packets.redvypr_address(devaddress)
                                addrtype = 'full'
                                addrstring = devaddress_redvypr.get_str(addrtype)
                                itmf = QtWidgets.QTreeWidgetItem([addrstring])
                                itmf.setBackground(0, col)
                                itmf.device = dev
                                itmf.redvypr_address = devaddress_redvypr
                                itmf.address_forwarded = devaddress
                                itm.addChild(itmf)
                                itmf.iskey = False

                                #print('Datakeys',datakeys,devs_forwarded[devaddress])
                                # Sort the datakey
                                datakeys.sort()
                                for dkey in datakeys:
                                    itmk = QtWidgets.QTreeWidgetItem([dkey])
                                    itmk.iskey = True
                                    itmk.device = dev
                                    itmk.devaddress = devaddress
                                    itmk.datakey_address = data_packets.redvypr_address(data_packets.modify_addrstr(devaddress,datakey=dkey))
                                    itmf.addChild(itmk)

                    if flag_datastreams: # If we have datastreams found, add the itm
                        root.addChild(itm)



            self.devicelist.expandAll()
            self.devicelist.resizeColumnToContents(0)


    def __addrtype_changed__(self):
        """ Update the datakeylist whenever the device was changed
        """
        funcname = __name__ + '.__addrtype_changed__():'
        logger.debug(funcname)
        addrtype = self.addrtype_combo.currentText()
        try:
            addrstring =  self.addressline.datakey_address.get_str(addrtype)
        except:
            addrstring = ''
        self.addressline.setText(addrstring)

    def done_clicked(self):
        try:
            datastream_address = self.addressline.datakey_address
        except Exception as e:
            #logger.exception(e)
            return

        addrtype = self.addrtype_combo.currentText()
        datastream_str = datastream_address.get_str(addrtype)
        device = self.addressline.device
        device_address = self.addressline.devaddress

        signal_dict = {'device': device, 'device_address':device_address,'datastream_str': datastream_str,'datastream_address':datastream_address}
        signal_dict['addrformat'] = self.addressline.datakey_address
        #print('Signal dict',signal_dict)
        self.apply.emit(signal_dict)
        self.close()





