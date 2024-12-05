from PyQt5 import QtWidgets, QtGui, QtCore
import logging
import sys
from redvypr.redvypr_address import RedvyprAddress


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('RedvyprSubsribeWidget')
logger.setLevel(logging.DEBUG)

class LineEditFocus(QtWidgets.QLineEdit):
    focusInSignal = QtCore.pyqtSignal()
    focusOutSignal = QtCore.pyqtSignal()
    def focusInEvent(self, event):
        # do custom stuff
        self.focusInSignal.emit()
        super(LineEditFocus, self).focusInEvent(event)

    def focusOutEvent(self, event):
        # do custom stuff
        self.focusOutSignal.emit()
        super(LineEditFocus, self).focusOutEvent(event)
class redvyprSubscribeWidget(QtWidgets.QWidget):
    """ Widget that lets the user add/modify/remove subscriptions of a device

    """

    def __init__(self, redvypr=None, device=None, show_devices = False):
        """

        Args:
            redvypr:
            device: The device the user can change the
            show_devices: lets the user choose between different devices, otherwise only the subscriptions of device=device can be changed.
        """
        super(redvyprSubscribeWidget, self).__init__()
        self.show_devices = show_devices
        self.redvypr = redvypr
        self.devices = self.redvypr.devices
        self.redvypr.devices_connected.connect(self.__devices_connected__)
        self.redvypr.devices_disconnected.connect(self.__devices_connected__)
        self.redvypr.device_status_changed_signal.connect(self.__devices_connected__)
        if (len(self.devices) > 0):
            if (device == None):  # Take the first one
                device = self.devices[0]['device']

        # Set icon
        #self.setWindowIcon(QtGui.QIcon(_icon_file))
        self.setWindowTitle("redvypr subscribe")
        layout = QtWidgets.QGridLayout(self)

        font = QtGui.QFont('Arial', 20)
        font.setBold(True)
        lab = QtWidgets.QLabel('Device subscriptions')
        lab.setFont(font)
        lab.setAlignment(QtCore.Qt.AlignCenter)
        self.lab = lab

        self.device_label = QtWidgets.QLabel('Device')
        self.device_label.setAlignment(QtCore.Qt.AlignCenter)
        self.dataprovider_label = QtWidgets.QLabel('Data providing devices')
        self.dataprovider_label.setAlignment(QtCore.Qt.AlignCenter)
        self.subscribe_label = QtWidgets.QLabel('Subscriptions')
        self.subscribe_label.setAlignment(QtCore.Qt.AlignCenter)

        self.devices_listPublisher = QtWidgets.QTreeWidget()  # All data publishing devices
        self.devices_listPublisher.setColumnCount(2)
        self.devices_listPublisher.setHeaderHidden(True)
        self.devices_listPublisher.currentItemChanged.connect(self.__update_device_choice__)

        self.devices_listDevices = QtWidgets.QListWidget()  # The devices a connection is to be defined
        self.devices_listDevices.itemClicked.connect(self.itemcon_clicked)
        self.devices_listDevices.itemDoubleClicked.connect(self.itemcon_dclicked)

        self.devices_listallsub = QtWidgets.QListWidget()  # The subscriptions of the device
        self.devices_listallsub.itemClicked.connect(self.__itemsubscribed_clicked__)

        self.subscribe_edit = LineEditFocus()
        self.subscribe_edit.focusInSignal.connect(self.__focus_in__)
        self.subscribe_edit.focusOutSignal.connect(self.__focus_out__)
        self.subscribe_edit.redvypr_address = RedvyprAddress('*')

        self.__commitbtn = QtWidgets.QPushButton('Subscribe')
        self.__commitbtn.clicked.connect(self.commit_clicked)
        self.__commitbtn.setEnabled(False)

        self.__subscribeAllBtn = QtWidgets.QPushButton('Subscribe all (*)')
        self.__subscribeAllBtn.clicked.connect(self.subscribeAll_clicked)

        self.__closeBtn = QtWidgets.QPushButton('Close')
        self.__closeBtn.clicked.connect(self.close_clicked)
        #self.__commitbtn.setEnabled(False)
        # Combo with formats
        self.__formatLabel = QtWidgets.QLabel('Address format')
        addr_formats = RedvyprAddress().get_common_address_formats()
        self.__formatCombo = QtWidgets.QComboBox()
        self.__formatCombo.currentIndexChanged.connect(self.__subscribe_editChanged__)
        for f in addr_formats:
            self.__formatCombo.addItem(f)

        self.__formatCombo.setCurrentIndex(0)
        #layout.addWidget(lab, 0, 1,1,3)
        layout.addWidget(lab, 0, 0,1,4)

        if self.show_devices:
            layout.addWidget(self.device_label, 1, 0)
            layout.addWidget(self.devices_listDevices, 2, 0)


        layout.addWidget(self.subscribe_label, 1, 0 , 1, 2)
        layout.addWidget(self.dataprovider_label, 1, 2, 1, 2)
        layout.addWidget(self.devices_listallsub, 2, 0 ,1,2)
        layout.addWidget(self.devices_listPublisher, 2, 2, 1, 2)
        layout.addWidget(self.subscribe_edit, 3, 0, 1, 2)
        layout.addWidget(self.__formatLabel, 3, 2, 1, 1)
        layout.addWidget(self.__formatCombo, 3, 3, 1, 1)
        layout.addWidget(self.__commitbtn,4,0,1,-1)
        layout.addWidget(self.__subscribeAllBtn, 5, 0, 1, -1)
        layout.addWidget(self.__closeBtn, 6, 0, 1, -1)

        if (len(self.devices) > 0):
            self.update_list(device)

    def close_clicked(self):
        self.close()

    def __itemsubscribed_clicked__(self,item):
        self.__commitbtn.setText('Remove')
        self.__commitbtn.setEnabled(True)
        self.__commitbtn.__status__ = 'remove'
        self.__commitbtn.redvypr_addr_remove = item.redvypr_addr

    def __focus_in__(self):
        self.__commitbtn.setText('Subscribe')
        self.__commitbtn.__status__ = 'add'
        self.__commitbtn.setEnabled(True)

    def __focus_out__(self):
        pass

    def __devices_connected__(self, dev1=None, dev2=None):
        #print('Devices have been connected',dev1,dev2)
        self.update_list(self.device)

    def __subscribe_editChanged__(self):
        # Check if the format shall be used or the publisher part
        if self.__formatCombo.isEnabled():
            addr_format = self.__formatCombo.currentText()
        else:
            addr_format = '/p:=='

        print('addr_format',addr_format)
        print('address',self.subscribe_edit.redvypr_address)
        devstr = self.subscribe_edit.redvypr_address.get_str(addr_format)
        self.subscribe_edit.setText(devstr)

    def __update_device_choice__(self, newitem, olditem):
        """
        A device was clicked, update all buttons
        Args:
            item:

        Returns:

        """
        #addr_format = self.__formatCombo.currentText()
        if newitem is not None:
            #devstr = newitem.redvypr_address.get_str(addr_format)

            try:
                subscribed = newitem.subscribed
            except:
                subscribed = False

            self.__commitbtn.setText('Subscribe')
            self.__commitbtn.__status__ = 'add'
            self.__commitbtn.setEnabled(True)
            #self.__commitbtn.redvypr_addr_remove = devstr
            self.subscribe_edit.redvypr_address = newitem.redvypr_address#.RedvyprAddress
            try:
                publisher = newitem.publisher
            except:
                publisher = False

            if publisher: # Treat a publishing device differently
                self.__formatCombo.setEnabled(False)
            else:
                self.__formatCombo.setEnabled(True)

            self.__subscribe_editChanged__()
        else:
            self.__commitbtn.setEnabled(False)

    def update_list(self, device):
        """ Update the list
        """

        funcname = __name__ + '.update_list()'
        try:
            devname = device.name
        except:
            devname = 'NA'
        logger.debug(funcname + ':update_list for device: {:s}, name {:s}'.format(str(device),devname))
        self.devices_listPublisher.clear()
        self.devices_listallsub.clear()
        self.devices_listDevices.clear()
        self.device = device

        if (len(self.devices) > 0):
            root = self.devices_listPublisher.invisibleRootItem()
            # self.devices_listDevices.addItem(str(device))
            data_provider_all = self.redvypr.get_device_objects(publishes=True, subscribes=False)
            font1 = QtGui.QFont('Arial')
            font1.setBold(True)
            font0 = QtGui.QFont('Arial')

            # Fill the qtreewidget
            #print('data provider',data_provider_all)
            if (data_provider_all is not None):
                for dev in data_provider_all:
                    if dev == self.device:
                        continue

                    # Check if the device is already subscribed
                    subscribed = False
                    #print('dev',dev.name,dev.redvypr.hostinfo)
                    for a in self.device.subscribed_addresses:
                        subscribed = a in dev.address
                        if subscribed:
                            break

                    itm = QtWidgets.QTreeWidgetItem([dev.name, ''])
                    itm.device = dev
                    itm.redvypr_address = dev.address
                    itm.publisher = True # Flag to set that the device is a publisher
                    if subscribed:
                        status = 'subscribed'
                        itm.setFont(0, font1)
                        itm.subscribed = True
                    else:
                        itm.setFont(0, font0)
                        itm.subscribed = False

                    root.addChild(itm)
                    # Add all data_devices
                    if True:
                        devs_forwarded = dev.get_device_info()
                        for devaddress in devs_forwarded.keys():
                            devaddress_redvypr = RedvyprAddress(devaddress)
                            subscribed = False
                            for a in self.device.subscribed_addresses:
                                subscribed = a in devaddress_redvypr
                                if subscribed:
                                    print('Subscribed',a,devaddress_redvypr)
                                    break

                            devaddress_str = devaddress_redvypr.get_str('/a/h/p/i/d/')
                            itmf = QtWidgets.QTreeWidgetItem([devaddress_str, ''])
                            #itmf.setData(0, 0, devaddress_redvypr)
                            itmf.device = dev
                            itmf.redvypr_address = devaddress_redvypr
                            itmf.address_forwarded = devaddress
                            if(subscribed):
                                itmf.setFont(0, font1)
                                itmf.subscribed = True
                            else:
                                itmf.setFont(0, font0)
                                itmf.subscribed = False

                            itm.addChild(itmf)
                            subscribed = False

            self.devices_listPublisher.expandAll()
            self.devices_listPublisher.resizeColumnToContents(0)

            # Fill list of devices subscribing
            devitm = None
            if True:
                # connecting devices
                for s in self.devices:
                    sen = s['device']
                    itm = QtWidgets.QListWidgetItem(sen.name)
                    itm.device = sen
                    self.devices_listDevices.addItem(itm)
                    if (sen == device):
                        devitm = itm

                if(devitm is not None):
                    self.devices_listDevices.setCurrentItem(devitm)
                    self.lab.setText('Subscriptions for\n ' + str(sen.name))

            # Fill the subscribed list
            if True:
                # connecting devices
                for s in self.device.subscribed_addresses:
                    sstr = s.address_str
                    litm = QtWidgets.QListWidgetItem(sstr)
                    litm.redvypr_addr = s
                    self.devices_listallsub.addItem(litm)

    # End update_list()
    def commit_clicked(self):
        """ Apply changes to subscribe/unsubscribe
        """
        funcname = 'commit_clicked'
        logger.debug(funcname)

        if (self.device is not None):
            if self.__commitbtn.__status__ == 'add':
                address_add = str(self.subscribe_edit.text())
                logger.debug('Adding? {}'.format(address_add))
                if (len(address_add) > 0):
                    logger.debug('Adding {}'.format(address_add))
                    self.device.subscribe_address(address_add)
                    self.update_list(self.device)
                else:
                    logger.debug('Nothing to add')
            elif self.__commitbtn.__status__ == 'remove':
                raddr = self.__commitbtn.redvypr_addr_remove
                self.device.unsubscribe_address(raddr)
                self.update_list(self.device)


        getSelected = self.devices_listPublisher.selectedItems()
        if getSelected:
            itm = getSelected[0]
            try:
                device = itm.device
                devicename = device.name
            except:
                device = None
                devicename = ''

            # Get subscriber
            subscriber_item  = self.devices_listDevices.currentItem()
            subscriber = subscriber_item.device
            try:
                address_forwarded = itm.address_forwarded
            except:
                address_forwarded = None

    def subscribeAll_clicked(self):
        logger.debug('Subscribe all')
        self.device.subscribe_address('*')
        self.update_list(self.device)
        self.close()

    def disconnect_clicked(self):
        logger.debug('Disconnect')

    def itemcon_clicked(self, item):
        # Update the connection list
        self.update_list(item.device)

    def itemcon_dclicked(self, item):
        if (item.isSelected()):
            item.setSelected(False)
