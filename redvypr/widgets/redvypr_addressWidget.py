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


class address_filterWidget(QtWidgets.QWidget):
    filterChanged = QtCore.pyqtSignal()  # Signal notifying if the device path was changed
    def __init__(self, redvypr = None):
        """
        """
        self.redvypr = redvypr
        self.filter_address = redvypr_address('*')
        self.filter_on = False
        super(QtWidgets.QWidget, self).__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.btn_nofilter = QtWidgets.QPushButton('Filter off')
        self.btn_nofilter.setCheckable(True)
        self.btn_nofilter.setChecked(False)
        self.btn_nofilter.clicked.connect(self._onfilter_btn_)

        self.btn_showfilter = QtWidgets.QPushButton('Show Filter')
        self.btn_showfilter.setCheckable(True)
        #self.btn_showfilter.setChecked(True)
        self.btn_showfilter.clicked.connect(self._showfilter_btn_)


        self.filter_widget = QtWidgets.QWidget()
        self.filter_layout = QtWidgets.QFormLayout(self.filter_widget)
        self.btn_datakeyfilter = QtWidgets.QPushButton('Datakey')
        self.line_datakeyfilter = QtWidgets.QLineEdit(self.filter_address.datakey)
        self.btn_devicefilter = QtWidgets.QPushButton('Device')
        self.line_devicefilter = QtWidgets.QLineEdit(self.filter_address.devicename)
        self.btn_publishingdevicefilter = QtWidgets.QPushButton('Publishing device')
        self.line_publishingdevicefilter = QtWidgets.QLineEdit(self.filter_address.publisher)
        self.btn_hostfilter = QtWidgets.QPushButton('Redvypr host')
        self.line_hostfilter = QtWidgets.QLineEdit(self.filter_address.hostname)

        buttons = [self.btn_datakeyfilter, self.btn_devicefilter, self.btn_publishingdevicefilter,
                     self.btn_hostfilter]
        for b in buttons:
            b.clicked.connect(self.__open_filterChoiceWidget)
            if redvypr is None:
                b.setEnabled(False)

        lineedits = [self.line_datakeyfilter, self.line_devicefilter, self.line_publishingdevicefilter,self.line_hostfilter]
        for l in lineedits:
            l.editingFinished.connect(self.__update_address_from_lineedits)

        self.line_filterstr = QtWidgets.QLineEdit(self.filter_address.get_str())

        self.filter_layout.addRow(self.btn_datakeyfilter,self.line_datakeyfilter)
        self.filter_layout.addRow(self.btn_devicefilter,self.line_devicefilter)
        self.filter_layout.addRow(self.btn_publishingdevicefilter, self.line_publishingdevicefilter)
        self.filter_layout.addRow(self.btn_hostfilter, self.line_hostfilter)
        self.filter_layout.addRow(self.line_filterstr)

        self.filter_widget.hide()
        self.layout.addWidget(self.btn_nofilter,0,0)
        self.layout.addWidget(self.btn_showfilter,0,1)
        self.layout.addWidget(self.filter_widget,1,0,1,2)

    def __open_filterChoiceWidget(self):
        """
        Opens a widget to let the user choose available choices
        """
        self.__filterChoice = QtWidgets.QWidget()
        self.__filterChoiceLayout = QtWidgets.QVBoxLayout(self.__filterChoice)
        self.__filterChoiceList = QtWidgets.QListWidget()
        self.__filterChoiceApply = QtWidgets.QPushButton('Apply')
        self.__filterChoiceApply.clicked.connect(self.__filterChoiceApplyClicked)
        self.__filterChoiceCancel = QtWidgets.QPushButton('Cancel')
        self.__filterChoiceCancel.clicked.connect(self.__filterChoice.close)
        # Fill the list
        if self.sender() == self.btn_datakeyfilter:
            options = self.redvypr.get_datakeys()
            self.__filterChoiceList.lineedit = self.line_datakeyfilter
        elif self.sender() == self.btn_devicefilter:
            options = self.redvypr.get_devices(local_object=False)
            self.__filterChoiceList.lineedit = self.line_devicefilter
        elif self.sender() == self.btn_publishingdevicefilter:
            options = self.redvypr.get_devices(local_object=True)
            self.__filterChoiceList.lineedit = self.line_publishingdevicefilter
        elif self.sender() == self.btn_hostfilter:
            options = self.redvypr.get_hosts()
            self.__filterChoiceList.lineedit = self.line_hostfilter
        else:
            options = []

        for o in options:
            self.__filterChoiceList.addItem(str(o))

        self.__filterChoiceLayout.addWidget(self.__filterChoiceList)
        self.__filterChoiceLayout.addWidget(self.__filterChoiceApply)
        self.__filterChoiceLayout.addWidget(self.__filterChoiceCancel)
        self.__filterChoice.show()

    def __filterChoiceApplyClicked(self):
        option = self.__filterChoiceList.currentItem()
        optionstr = str(option.text())
        print('Apply',optionstr)
        self.__filterChoiceList.lineedit.setText(optionstr)
        self.__update_address_from_lineedits()
        self.__filterChoice.close()

    def __update_address_from_lineedits(self):
        host = self.line_hostfilter.text()
        datakey = self.line_datakeyfilter.text()
        devicename = self.line_devicefilter.text()
        publisher = self.line_publishingdevicefilter.text()
        self.filter_address = redvypr_address(datakey=datakey, hostname=host, devicename=devicename, publisher=publisher)
        #print('Update filteraddress',self.filter_address.get_str())
        self.line_filterstr.setText(self.filter_address.get_str())
        self.filterChanged.emit()

    def _onfilter_btn_(self):
        if self.btn_nofilter.isChecked():
            print('Will filter')
            self.btn_nofilter.setText('Filter on')
            self.filter_on = True
        else:
            print('Will NOT filter')
            self.btn_nofilter.setText('Filter off')
            self.filter_on = False

        self.filterChanged.emit()


    def _showfilter_btn_(self):
        print('Show filter button')
        button = self.sender()
        if button.isChecked():
            self.filter_widget.show()
            self.btn_showfilter.setText('Hide Filter')
        else:
            self.filter_widget.hide()
            self.btn_showfilter.setText('Show Filter')


#
class datastreamWidget(QtWidgets.QWidget):
    """ Widget that lets the user choose available subscribed devices (if device is not None) and datakeys. This
    devicelock: The user cannot change the device anymore
    """
    device_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the device path was changed
    apply = QtCore.pyqtSignal(dict)  # Signal notifying if the Apply button was clicked
    datakey_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the datakey has changed

    def __init__(self, redvypr, device=None, devicename_highlight=None, datakey=None, deviceonly=False,
                 devicelock=False, subscribed_only=True, showapplybutton=True,datastreamstring='',closeAfterApply=True):
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
        self.closeAfterApply = closeAfterApply
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
        redvypr_addresstypes = redvypr_address().get_common_address_formats()
        for t in redvypr_addresstypes:
            self.addrtype_combo.addItem(t)

        #self.addrtype_combo.setCurrentIndex(2)
        self.addrtype_combo.currentIndexChanged.connect(self.__addrtype_changed__)
        self.filterWidget = address_filterWidget(redvypr = redvypr)

        # Add widgets to layout
        self.layout.addWidget(self.filterWidget)
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
            self.buttondone.setEnabled(False)

        devicelist = []
        self.datakeylist_subscribed = {}

        self.__update_devicetree()
        self.filterWidget.filterChanged.connect(self.__update_devicetree)

    def __addrManualChanged(self,addrstr):
        funcname = __name__ + '.__addrManualChanged():'
        logger.debug(funcname + " manual address: {}".format(addrstr))
        try:
            self.addressline.datakey_address = redvypr_address(addrstr)
            self.buttondone.setEnabled(True)
        except:
            self.buttondone.setEnabled(False)
            return
        self.addressline.device = self.addressline.datakey_address.devicename
        self.addressline.devaddress = self.addressline.datakey_address.address_str
        self.__addrtype_changed__()

    def __device_clicked(self,item):
        """
        Called when an item in the qtree is clicked
        """
        funcname = __name__ + '__device_clicked()'
        logger.debug(funcname)
        print('Item',item.iskey)
        if(item.iskey): # If this is a datakey item
            addrtype = self.addrtype_combo.currentText()
            addrstring = item.datakey_address.get_str(addrtype)
            print('Addrstring',addrstring)
            print('Devstring', item.devaddress)
            self.addressline.setText(addrstring)
            self.addressline.datakey_address = item.datakey_address
            self.addressline.device = item.device
            self.addressline.devaddress = item.devaddress
            self.buttondone.setEnabled(True)

    def __update_devicetree(self):
        if True:
            self.devicelist.clear()
            root = self.devicelist.invisibleRootItem()
            # self.devices_listDevices.addItem(str(device))
            data_provider_all = self.redvypr.get_device_objects(publishes=True, subscribes=False)
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
                    # Check for filter
                    print('Address', dev.address)
                    if self.filterWidget.filter_on:
                        if dev.address not in self.filterWidget.filter_address:
                            print('No filter match for ',dev.address)
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
                                devaddress_redvypr = redvypr_address(devaddress)
                                if self.filterWidget.filter_on:
                                    if devaddress_redvypr not in self.filterWidget.filter_address:
                                        print('No filter match for ', devaddress_redvypr)
                                        continue
                                addrtype = '/d/'
                                print('Hallo',devaddress_redvypr,devaddress_redvypr.get_str())
                                devicename = devaddress_redvypr.devicename
                                itmf = QtWidgets.QTreeWidgetItem([devicename])
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
                                    itmk.datakey_address = redvypr_address(devaddress,datakey=dkey)
                                    if self.filterWidget.filter_on:
                                        if itmk.datakey_address not in self.filterWidget.filter_address:
                                            print('No filter match for ', itmk.datakey_address)
                                            continue
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
            self.buttondone.setEnabled(True)
        except:
            addrstring = ''
            self.buttondone.setEnabled(False)

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

        signal_dict = {'device': device, 'device_address':device_address,'datastream_str': datastream_str,'datastream_address':datastream_address,'address_format':addrtype}
        signal_dict['addrformat'] = self.addressline.datakey_address
        #print('Signal dict',signal_dict)
        self.apply.emit(signal_dict)
        if self.closeAfterApply:
            self.close()





