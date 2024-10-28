import json

from PyQt5 import QtWidgets, QtCore, QtGui
import logging
import sys
import qtawesome
import redvypr.files as files
import redvypr.data_packets as data_packets
from redvypr.redvypr_address import RedvyprAddress


_logo_file = files.logo_file
_icon_file = files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvyprAddressWidget')
logger.setLevel(logging.DEBUG)


class RedvyprAddressTreeWidget(QtWidgets.QTreeWidget):
    """ A widget that shows all RedvyprAdresses of a device
    Not done yet
    """
    def __init__(self, device=None):
        """
        """
        super(QtWidgets.QWidget, self).__init__()
        self.device = device
        self.root = self.invisibleRootItem()
        self.setColumnCount(1)
        self.populate_tree()
        self.expandAll()
        self.resizeColumnToContents(0)

    def populate_tree(self):
        funcname = __name__ + '.populate_tree():'
        self.clear()
        addresses = self.device.get_deviceaddresses()

        parent = self.root
        for a in addresses:
            item = QtWidgets.QTreeWidgetItem([str(a)])

        parent.addChild(item)


class RedvyprAddressWidget(QtWidgets.QWidget):
    """ A widget that allows to enter an address
    """
    address_finished = QtCore.pyqtSignal(str)  # Signal notifying that the configuration has changed
    def __init__(self, redvypr_address_str=None, redvypr=None):
        """
        """
        super(QtWidgets.QWidget, self).__init__()
        self.layout = QtWidgets.QFormLayout(self)
        self.__configwidget = QtWidgets.QWidget()
        self.redvypr_address = None
        if redvypr_address_str is None:
            manual_address = None
        elif isinstance(redvypr_address_str,RedvyprAddress):
            manual_address = redvypr_address_str.address_str
        elif isinstance(redvypr_address_str, str):
            manual_address = RedvyprAddress(redvypr_address_str).address_str
        else:
            manual_address = None
        self.__datastreamwidget = datastreamWidget(redvypr=redvypr, showapplybutton=False, manual_address=manual_address, datakeys_expanded=True)
        self.__configwidget_input = self.__datastreamwidget.addressline
        self.layout.addRow(self.__datastreamwidget)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.applyClicked)
        self.__configwidget_apply.__configType = 'configRedvyprAddressStr'
        self.layout.addRow(self.__configwidget_apply)

    def applyClicked(self):
        funcname = __name__ + '.applyClicked():'
        self._test_input()
        logger.debug(funcname + 'Address: {} ({})'.format(self.redvypr_address,type(self.redvypr_address)))
        self.address_finished.emit(str(self.redvypr_address))
    def _test_input(self):
        """
        Tests if the text in the qlineedit is a valid redvypr address
        :return: RedvyprAddress or None
        """
        addr_str = self.__configwidget_input.text()
        #print('Addr str',addr_str)
        try:
            self.redvypr_address = RedvyprAddress(addr_str)
            self.__configwidget_apply.setEnabled(True)
        except:
            logger.debug('Could not parse address string {}'.format(addr_str),exc_info=True)
            self.redvypr_address = None
            self.__configwidget_apply.setEnabled(False)

        #print('Redvypr address',self.redvypr_address)
        return self.redvypr_address


class RedvyprAddressWidgetSimple(QtWidgets.QWidget):
    """ A widget that allows to enter an address
    """
    address_finished = QtCore.pyqtSignal(str)  # Signal notifying that the configuration has changed
    def __init__(self, redvypr_address_str='/d:*'):
        """
        """
        super(QtWidgets.QWidget, self).__init__()
        self.layout = QtWidgets.QFormLayout(self)
        self.__configwidget = QtWidgets.QWidget()
        self.redvypr_address = None
        self.__configwidget_input = QtWidgets.QLineEdit()
        self.__configwidget_input.editingFinished.connect(self._test_input)
        self.__configwidget_input.setText(redvypr_address_str)  # str(data))

        self.layout.addRow(QtWidgets.QLabel('Enter redvypr address'))
        self.layout.addRow(QtWidgets.QLabel('Address string'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.applyClicked)
        self.__configwidget_apply.__configType = 'configRedvyprAddressStr'
        self.__configwidget_cancel = QtWidgets.QPushButton('Cancel')
        self.layout.addRow(self.__configwidget_apply)
        self.layout.addRow(self.__configwidget_cancel)

    def applyClicked(self):
        self._test_input()
        self.address_finished.emit(str(self.redvypr_address))
    def _test_input(self):
        """
        Tests if the text in the qlineedit is a valid redvypr address
        :return: RedvyprAddress or None
        """
        addr_str = self.__configwidget_input.text()
        #print('Addr str',addr_str)
        try:
            self.redvypr_address = RedvyprAddress(addr_str)
            self.__configwidget_apply.setEnabled(True)
        except:
            logger.debug('Could not parse address string {}'.format(addr_str),exc_info=True)
            self.redvypr_address = None
            self.__configwidget_apply.setEnabled(False)

        #print('Redvypr address',self.redvypr_address)
        return self.redvypr_address




class address_filterWidget(QtWidgets.QWidget):
    filterChanged = QtCore.pyqtSignal()  # Signal notifying if the device path was changed
    def __init__(self, redvypr = None):
        """
        """
        self.redvypr = redvypr
        self.filter_address = RedvyprAddress('*')
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
        self.btn_packetidfilter = QtWidgets.QPushButton('Packet Id')
        self.line_packetidfilter = QtWidgets.QLineEdit(self.filter_address.packetid)
        self.btn_devicefilter = QtWidgets.QPushButton('Device')
        self.line_devicefilter = QtWidgets.QLineEdit(self.filter_address.devicename)
        self.btn_publishingdevicefilter = QtWidgets.QPushButton('Publishing device')
        self.line_publishingdevicefilter = QtWidgets.QLineEdit(self.filter_address.publisher)
        self.btn_hostfilter = QtWidgets.QPushButton('Redvypr host')
        self.line_hostfilter = QtWidgets.QLineEdit(self.filter_address.hostname)

        buttons = [self.btn_datakeyfilter, self.btn_packetidfilter,
                   self.btn_devicefilter, self.btn_publishingdevicefilter,
                   self.btn_hostfilter]
        for b in buttons:
            b.clicked.connect(self.__open_filterChoiceWidget)
            if redvypr is None:
                b.setEnabled(False)

        lineedits = [self.line_datakeyfilter, self.line_packetidfilter,
                     self.line_devicefilter, self.line_publishingdevicefilter,
                     self.line_hostfilter]

        for l in lineedits:
            l.editingFinished.connect(self.__update_address_from_lineedits)

        self.line_filterstr = QtWidgets.QLineEdit(self.filter_address.get_str())

        self.filter_layout.addRow(self.btn_datakeyfilter,self.line_datakeyfilter)
        self.filter_layout.addRow(self.btn_packetidfilter, self.line_packetidfilter)
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
        elif self.sender() == self.btn_packetidfilter:
            options = self.redvypr.get_packetids()
            self.__filterChoiceList.lineedit = self.line_packetidfilter
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

        # Append the wildcard
        options.append('*')

        for o in options:
            self.__filterChoiceList.addItem(str(o))

        self.__filterChoiceLayout.addWidget(self.__filterChoiceList)
        self.__filterChoiceLayout.addWidget(self.__filterChoiceApply)
        self.__filterChoiceLayout.addWidget(self.__filterChoiceCancel)
        self.__filterChoiceList.setSelectionMode(QtWidgets.QListWidget.MultiSelection)
        self.__filterChoice.show()

    def __filterChoiceApplyClicked(self):
        options = self.__filterChoiceList.selectedItems()
        if len(options) == 1:
            option = self.__filterChoiceList.currentItem()
            optionstr = str(option.text())
        elif len(options) > 1:
            optionslist = []
            for o in options:
                optionslist.append(o.text())
            if '*' in optionslist:
                optionstr = '*'
            else:
                optionstr ='{'
                for o in optionslist:
                    optionstr += o + '|'

                optionstr = optionstr[:-1] + '}'
        else:
            return

        logger.debug('Apply {}'.format(optionstr))
        self.__filterChoiceList.lineedit.setText(optionstr)
        self.__update_address_from_lineedits()
        self.__filterChoice.close()

    def __update_address_from_lineedits(self):
        host = self.line_hostfilter.text()
        datakey = self.line_datakeyfilter.text()
        packetid = self.line_packetidfilter.text()
        devicename = self.line_devicefilter.text()
        publisher = self.line_publishingdevicefilter.text()
        self.filter_address = RedvyprAddress(datakey=datakey,
                                             packetid=packetid,
                                             hostname=host,
                                             devicename=devicename,
                                             publisher=publisher)
        #print('Update filteraddress',self.filter_address.get_str())
        self.line_filterstr.setText(self.filter_address.get_str())
        self.filterChanged.emit()

    def _onfilter_btn_(self):
        if self.btn_nofilter.isChecked():
            logger.debug('Will filter')
            self.btn_nofilter.setText('Filter on')
            self.filter_on = True
        else:
            logger.debug('Will NOT filter')
            self.btn_nofilter.setText('Filter off')
            self.filter_on = False

        self.filterChanged.emit()


    def _showfilter_btn_(self):
        logger.debug('Show filter button')
        button = self.sender()
        if button.isChecked():
            self.filter_widget.show()
            self.btn_showfilter.setText('Hide Filter')
        else:
            self.filter_widget.hide()
            self.btn_showfilter.setText('Show Filter')


class datastreamWidget(QtWidgets.QWidget):
    """ Widget that lets the user choose available subscribed devices (if device is not None) and datakeys. This
    devicelock: The user cannot change the device anymore
    """
    device_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the device path was changed
    apply = QtCore.pyqtSignal(dict)  # Signal notifying if the Apply button was clicked
    datakey_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the datakey has changed

    def __init__(self, redvypr, device=None, devicename_highlight=None, datakey=None, deviceonly=False,
                 devicelock=False, subscribed_only=True, showapplybutton=True,datastreamstring='',closeAfterApply=True,
                 filter_include=[], datakeys_expanded=True, manual_address=None):
        """
        Args:
            redvypr:
            device:
            devicename_highlight: The devicename that is highlighted in the list
            datakey:
            deviceonly:
            devicelock:
            filter_include: List of RedvyprAdresses the will be checked
            subscribed_only: Show the subscribed devices only
            manual_address: String for the manual address
        """

        super(QtWidgets.QWidget, self).__init__()
        logger.setLevel(logging.DEBUG)
        #logger.debug('HALLLOHALLO')
        self.setWindowIcon(QtGui.QIcon(_icon_file))
        self.closeAfterApply = closeAfterApply
        self.redvypr = redvypr
        self.datakeys_expanded = datakeys_expanded
        self.expandlevel = 3
        self.external_filter_include = filter_include
        self.datastreamstring_orig = datastreamstring
        self.datastreamstring  = datastreamstring
        self.layout = QtWidgets.QGridLayout(self)
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
        if manual_address is not None:
            self.addressline_manual.setText(manual_address)
        self.addressline_manual.textChanged.connect(self.__addrManualChanged)

        self.addressline = QtWidgets.QLineEdit()
        self.addressline.setReadOnly(True)

        # A combobox to choose between different styles of the address
        self.addrtype_combo = QtWidgets.QComboBox()  # Combo for the different combination types
        redvypr_addresstypes = RedvyprAddress().get_common_address_formats()
        for t in redvypr_addresstypes:
            self.addrtype_combo.addItem(t)

        #self.addrtype_combo.setCurrentIndex(2)
        self.addrtype_combo.currentIndexChanged.connect(self.__addrtype_changed__)
        self.filterWidget = address_filterWidget(redvypr = redvypr)

        # Expansion level
        expandlayout = QtWidgets.QHBoxLayout()
        self.expandlevel_spin = QtWidgets.QSpinBox()
        self.expandlevel_spin.setValue(self.expandlevel)
        self.expandlevel_spin.valueChanged.connect(self.__expandlevelChanged)
        expandlayout.addWidget(QtWidgets.QLabel('Expansion level'))
        expandlayout.addWidget(self.expandlevel_spin)

        # Add widgets to layout
        self.layout_left = QtWidgets.QVBoxLayout()
        self.layout_right = QtWidgets.QVBoxLayout()
        self.layout_right.addLayout(expandlayout)
        self.layout_right.addWidget(self.filterWidget)
        self.layout_left.addWidget(self.deviceavaillabel)
        self.layout_left.addWidget(self.devicelist)

        self.layout_right.addWidget(QtWidgets.QLabel('Manual Address'))
        self.layout_right.addWidget(self.addressline_manual)
        self.layout_right.addWidget(QtWidgets.QLabel('Address format'))
        self.layout_right.addWidget(self.addrtype_combo)
        self.addresslabel = QtWidgets.QLabel('Address')
        self.layout_right.addWidget(self.addresslabel)
        self.layout_right.addWidget(self.addressline)

        self.layout.addLayout(self.layout_left,0,0)
        self.layout.addLayout(self.layout_right,0,1)

        # The datakeys
        if (deviceonly == False):
            pass

        if True:
            self.buttondone = QtWidgets.QPushButton('Apply')
            self.buttondone.clicked.connect(self.done_clicked)
            self.buttondone.setEnabled(False)
        if (showapplybutton):
            self.layout_right.addWidget(self.buttondone)
        else:
            self.buttondone.hide()

        # Add a stretch
        self.layout_right.addStretch()
        devicelist = []
        self.datakeylist_subscribed = {}
        if self.datakeys_expanded:
            self.__update_devicetree_expanded()
            self.filterWidget.filterChanged.connect(self.__update_devicetree_expanded)
        else:
            self.__update_devicetree()
            self.filterWidget.filterChanged.connect(self.__update_devicetree)

    def __expandlevelChanged(self):
        funcname = __name__ + '.____expandlevelChanged():'
        logger.debug(funcname)
        self.expandlevel = self.expandlevel_spin.value()
        self.__update_devicetree_expanded()
    def __addrManualChanged(self,addrstr):
        funcname = __name__ + '.__addrManualChanged():'
        logger.debug(funcname + " manual address: {}".format(addrstr))
        try:
            self.addressline.datakey_address = RedvyprAddress(addrstr)
            self.buttondone.setEnabled(True)
        except:
            logger.info('fdsf',exc_info=True)
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
        #print('Item',item.iskey)
        if(item.iskey): # If this is a datakey item
            addrtype = self.addrtype_combo.currentText()
            addrstring = item.datakey_address.get_str(addrtype)
            #print('Addresstype', addrtype)
            #print('Address',item.datakey_address)
            #print('Addrstring',addrstring)
            #print('Devstring', item.devaddress)
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

                    logger.debug('Address {}'.format(dev.address))
                    # Check for external filter
                    flag_external_filter = True
                    for addr_include in self.external_filter_include:
                        filter_test = dev.address not in addr_include
                        logger.debug('Testing filter {} with {}'.format(dev.address,addr_include))
                        if filter_test:
                            logger.debug('No filter match for external filter {}'.format(dev.address))
                            flag_external_filter = False

                    if flag_external_filter == False:
                        continue
                    # Check for filter from filter widget
                    if self.filterWidget.filter_on:
                        filter_test = dev.address not in self.filterWidget.filter_address
                        logger.debug(
                            'Testing filter for {} in {}: {}'.format(dev.address, self.filterWidget.filter_address,filter_test))
                        if filter_test:
                            logger.debug('No filter match for {} in {}'.format(dev.address, self.filterWidget.filter_address))
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
                                devaddress_redvypr = RedvyprAddress(devaddress)
                                if self.filterWidget.filter_on:
                                    filter_test = devaddress_redvypr not in self.filterWidget.filter_address
                                    logger.info(
                                        'Testing filter for forwarded {} in {}: {}'.format(devaddress_redvypr,
                                                                                 self.filterWidget.filter_address,
                                                                                 filter_test))

                                    if filter_test:
                                        logger.debug('No filter match for {}'.format(devaddress_redvypr))
                                        continue
                                addrtype = '/d/'
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
                                    itmk.datakey_address = RedvyprAddress(devaddress, datakey=dkey)
                                    if self.filterWidget.filter_on:
                                        if itmk.datakey_address not in self.filterWidget.filter_address:
                                            logger.debug('No filter match for {}'.format(itmk.datakey_address))
                                            continue
                                    itmf.addChild(itmk)

                    if flag_datastreams: # If we have datastreams found, add the itm
                        root.addChild(itm)



            self.devicelist.expandAll()
            self.devicelist.resizeColumnToContents(0)

    def __update_devicetree_expanded(self):
        funcname = __name__ + '.__update_devicetree_expanded():'
        logger.debug(funcname)
        colgrey = QtGui.QColor(220, 220, 220)
        def update_recursive(data_new_key, data_new, parent_item, datakey_construct, expandlevel):
            funcname = __name__ + '.__update_recursive():'
            logger.debug(funcname)
            if self.expandlevel == 0:
                datakey_construct_new = data_new_key
            else:
                datakey_construct_new = datakey_construct + '[' + json.dumps(data_new_key) + ']'

            #print('Hallo',data_new_key, data_new,type(data_new))
            #print('Datakey construct new',datakey_construct_new)
            # Check if we are at an item level that is a datakey to be used as a datastream
            if isinstance(data_new, tuple) or (expandlevel >= self.expandlevel):
                #print('Set',data_new,self.expandlevel)
                if expandlevel >= self.expandlevel:
                    #print('Level reached')
                    addrstr_expanded = datakey_construct_new
                else:
                    addrstr = data_new[0]  # Index 0 of set is the address, index 1 the datatype
                    datakeyaddr = RedvyprAddress(addrstr)
                    # Construct a datakey based on the expansion level
                    dkeys_expanded = datakeyaddr.parsed_addrstr_expand['datakeyentries_str']
                    #print('Datakeyaddr', datakeyaddr)
                    #print('expanded datakeys', datakeyaddr.parsed_addrstr_expand['datakeyentries_str'])
                    if datakeyaddr.parsed_addrstr_expand['datakeyeval']:
                        addrstr_expanded = ''
                        for iexpand in range(len(dkeys_expanded)):
                            if iexpand < self.expandlevel:
                                addrstr_expanded += '[' + dkeys_expanded[iexpand] + ']'

                        #print('Addresstr expanded',addrstr_expanded)
                    else:
                        addrstr_expanded = addrstr

                #print('Addresstr expanded',addrstr_expanded)
                itmk = QtWidgets.QTreeWidgetItem([addrstr_expanded])
                itmk.iskey = True
                itmk.device = dev
                itmk.devaddress = devaddress
                #print('Creating address with devaddress',devaddress)
                #print('Creating address with devaddress parsed', devaddress.parsed_addrstr)
                #print('Creating address with datakey', addrstr)
                itmk.datakey_address = RedvyprAddress(devaddress, datakey=addrstr_expanded)
                #print('Address',itmk.datakey_address)
                #print('Address parsed', itmk.datakey_address.parsed_addrstr)
                if self.filterWidget.filter_on:
                    test_filter = itmk.datakey_address not in self.filterWidget.filter_address
                    logger.debug('Testing (@tuple): {} not in {}: {}'.format(itmk.datakey_address,
                                                                             self.filterWidget.filter_address,
                                                                             test_filter))
                    if test_filter:
                        logger.debug('No filter match for {}'.format(itmk.datakey_address))
                    else:
                        parent_item.addChild(itmk)
                else:
                    parent_item.addChild(itmk)

            elif isinstance(data_new, list):
                itmk = QtWidgets.QTreeWidgetItem([str(data_new_key)])
                itmk.setBackground(0, colgrey)
                parent_item.addChild(itmk)
                for data_new_index, data_new_item in enumerate(data_new):
                    update_recursive(data_new_index, data_new_item, parent_item=itmk, datakey_construct=datakey_construct_new, expandlevel=expandlevel+1)

            elif isinstance(data_new, dict):
                itmk = QtWidgets.QTreeWidgetItem([data_new_key])
                itmk.setBackground(0, colgrey)
                parent_item.addChild(itmk)
                for data_new_key in data_new.keys():
                    update_recursive(data_new_key, data_new[data_new_key], parent_item=itmk, datakey_construct=datakey_construct_new, expandlevel=expandlevel+1)

        if True:
            self.devicelist.clear()
            root = self.devicelist.invisibleRootItem()
            # self.devices_listDevices.addItem(str(device))
            data_provider_all = self.redvypr.get_device_objects(publishes=True, subscribes=False)
            font1 = QtGui.QFont('Arial')
            font1.setBold(True)
            font0 = QtGui.QFont('Arial')

            # Fill the qtreewidget
            #print('data provider',data_provider_all)
            if (data_provider_all is not None):
                for dev in data_provider_all:
                    flag_datastreams = False
                    if dev == self.device:
                        continue

                    #print('Device {}'.format(dev.name))
                    #print('Address', dev.address)
                    # Check for external filter
                    flag_external_filter = True
                    for addr_include in self.external_filter_include:
                        test_include = dev.address not in addr_include
                        logger.debug('Testing {} not in {}: {}'.format(dev.address, addr_include, test_include))
                        if test_include:
                            #print('No filter match for external filter', dev.address)
                            flag_external_filter = False

                    if flag_external_filter == False:
                        continue
                    # Check for filter from filter widget
                    if self.filterWidget.filter_on:
                        test_filter = dev.address not in self.filterWidget.filter_address
                        test_filter_sub = True
                        if test_filter == True:
                            # Test all devices of publisher in brute force and check if one of them fits
                            devs_forwarded = dev.get_device_info()
                            for devaddress in devs_forwarded:
                                datakey_dict = devs_forwarded[devaddress]['datakeys_expanded']
                                #print('Datakeys', datakey_dict)
                                devaddress_redvypr = RedvyprAddress(devaddress)
                                if devaddress_redvypr in self.filterWidget.filter_address:
                                    test_filter_sub = False
                                    #print('Filter match for ', devaddress_redvypr)
                                    continue

                        logger.debug('Testing {} not in {}: {}'.format(dev.address, self.filterWidget.filter_address, test_filter))
                        if test_filter and test_filter_sub:
                            #print('No filter match for ', dev.address)
                            continue

                    itm = QtWidgets.QTreeWidgetItem([dev.name])
                    col = QtGui.QColor(220, 220, 220)
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
                            datakey_dict = devs_forwarded[devaddress]['datakeys_expanded']
                            #print('Datakeys',datakey_dict)

                            #fdsfdsf
                            flag_datastreams = True
                            devaddress_redvypr = RedvyprAddress(devaddress)
                            if self.filterWidget.filter_on:
                                if devaddress_redvypr not in self.filterWidget.filter_address:
                                    #print('No filter match for ', devaddress_redvypr)
                                    continue
                            addrtype = '/d/i/'
                            #print('Hallo', devaddress_redvypr, devaddress_redvypr.get_str())
                            devicestr = devaddress_redvypr.devicename
                            # TODO, this should be defined in the configuration of the widget
                            #devicestr = devaddress_redvypr.get_str(addrtype)
                            devicestr = devaddress_redvypr.get_str()
                            itmf = QtWidgets.QTreeWidgetItem([devicestr])
                            itmf.setBackground(0, col)
                            itmf.device = dev
                            itmf.redvypr_address = devaddress_redvypr
                            itmf.address_forwarded = devaddress
                            itm.addChild(itmf)
                            itmf.iskey = False

                            for key in datakey_dict.keys():
                                data_new = datakey_dict[key]
                                datakey_construct_new = ''
                                update_recursive(key, data_new, parent_item=itmf, datakey_construct=datakey_construct_new, expandlevel=0)

                    if flag_datastreams:  # If we have datastreams found, add the itm
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

    def get_all_items(self):
        tree_widget = self.devicelist
        items = []

        def traverse_items(item):
            items.append(item)
            for i in range(item.childCount()):
                traverse_items(item.child(i))

        # recursively get all items
        for i in range(tree_widget.topLevelItemCount()):
            traverse_items(tree_widget.topLevelItem(i))

        return items

    def done_clicked(self):
        funcname = __name__ + '.done_clicked():'
        addrformat = self.addrtype_combo.currentText()
        device = self.addressline.device
        device_address = self.addressline.devaddress
        datastream_address = self.addressline.datakey_address
        datastream_str = datastream_address.get_str(addrformat)

        signal_dict = {'device': device, 'device_address':device_address,'datastream_str': datastream_str,'datastream_address':datastream_address,'address_format':addrformat}
        signal_dict['addrformat'] = self.addressline.datakey_address
        print(funcname + 'Signal dict {}'.format(signal_dict))
        self.apply.emit(signal_dict)
        if self.closeAfterApply:
            self.close()



class datastreamsWidget(datastreamWidget):
    """ Widget that lets the user choose several datastreams
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args,**kwargs)
        self.devicelist.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.datastreamtable = QtWidgets.QTableWidget()
        #self.datastreamtable.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.layout.addWidget(self.datastreamtable,0,2)
        self.layout.removeWidget(self.buttondone)
        self.buttondone.clicked.disconnect(self.done_clicked)
        self.buttondone.clicked.connect(self.apply_clicked_datastreams)

        self.layout_right.removeWidget(self.addresslabel)
        self.addresslabel.hide()
        self.layout_right.removeWidget(self.addressline)
        self.addressline.hide()
        self.addrtype_combo.currentIndexChanged.disconnect(self.__addrtype_changed__)
        self.addrtype_combo.currentIndexChanged.connect(self.update_datastreamtable)

        iconname='ei.remove'
        icon = qtawesome.icon(iconname)
        self.button_rem = QtWidgets.QPushButton('Remove')
        self.button_rem.setIcon(icon)
        self.button_rem.clicked.connect(self.rem_datastreams)
        icon = qtawesome.icon(iconname)
        self.button_rem_all = QtWidgets.QPushButton('Remove all')
        self.button_rem_all.setIcon(icon)
        self.button_rem_all.clicked.connect(self.rem_datastreams)
        iconname='ei.caret-right'
        icon = qtawesome.icon(iconname)
        self.button_add = QtWidgets.QPushButton('Add')
        self.button_add.setIcon(icon)
        self.button_add.clicked.connect(self.add_datastreams)
        self.button_add_manual = QtWidgets.QPushButton('Add manual')
        self.button_add_manual.setIcon(icon)
        self.button_add_manual.clicked.connect(self.add_manual_datastream)
        self.button_add_all = QtWidgets.QPushButton('Add all')
        self.button_add_all.setIcon(icon)
        self.button_add_all.clicked.connect(self.add_all_datastreams)

        self.layout_right.addWidget(self.button_add_manual)
        #self.layout_right.addWidget(self.button_rem)
        #self.layout_right.addWidget(self.button_add)
        #self.layout_right.addWidget(self.button_rem_all)
        #self.layout_right.addWidget(self.button_add_all)
        self.layout.addWidget(self.buttondone,3,0,1,3)
        self.layout.addWidget(self.button_add, 1, 0)
        self.layout.addWidget(self.button_add_all, 2, 0)
        self.layout.addWidget(self.button_rem, 1, 2)
        self.layout.addWidget(self.button_rem_all, 2, 2)
        self.addresses_choosen = []
        self.update_datastreamtable()

    def apply_clicked_datastreams(self):
        funcname = __name__ + '.apply_clicked_datastreams()'
        logger.debug(funcname)
        addresses_choosen = []
        addresses_str_choosen = []
        for irow, raddr in enumerate(self.addresses_choosen):
            addrtype = self.addrtype_combo.currentText()
            addrstr = raddr.get_str(addrtype)  # Here a format would be nice
            addresses_choosen.append(RedvyprAddress(addrstr))
            addresses_str_choosen.append(addrstr)

        # Create a signal dict, with a format similar to the dict returned by the "apply" signal of the datastreamWidget
        signal_dict = {'addresses':addresses_choosen,'datastreams_address':addresses_choosen,'datastreams_str':addresses_str_choosen}

        #print('Signal dict',signal_dict)
        self.apply.emit(signal_dict)
        if self.closeAfterApply:
            self.close()

    def update_datastreamtable(self):
        self.datastreamtable.clear()
        nrows = len(self.addresses_choosen)
        self.datastreamtable.setRowCount(nrows)
        self.datastreamtable.setColumnCount(1)
        for irow,raddr in enumerate(self.addresses_choosen):
            addrtype = self.addrtype_combo.currentText()
            addrstr = raddr.get_str(addrtype) # Here a format would be nice
            item = QtWidgets.QTableWidgetItem(addrstr)
            item.datakey_address = raddr
            self.datastreamtable.setItem(irow,0, item)

        self.datastreamtable.setHorizontalHeaderLabels(['Address'])
        #self.datastreamtable.resizeColumnsToContents()
        self.datastreamtable.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        #self.datastreamtable.resizeColumnToContent(0)
        self.datastreamtable.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.datastreamtable.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)
        if len(self.addresses_choosen)>0:
            self.buttondone.setEnabled(True)
        else:
            self.buttondone.setEnabled(False)

    def rem_datastreams(self):
        funcname = __name__ + '.rem_datastreams():'
        logger.debug(funcname)
        if self.sender() == self.button_rem:
            items = self.datastreamtable.selectedItems()
        elif self.sender() == self.button_rem_all:
            items = []
            for row in range(self.datastreamtable.rowCount()):
                item = self.datastreamtable.item(row, 0)
                items.append(item)
        else:
            logger.warning('Error in removing')

        for item in items:
            #print("selectedItem", item.text())
            self.addresses_choosen.remove(item.datakey_address)

        self.update_datastreamtable()

    def add_manual_datastream(self):
        funcname = __name__ + '.add_manual_datastream():'
        logger.debug(funcname)
        addressstr = self.addressline_manual.text()
        datakey_address = RedvyprAddress(addressstr)
        if datakey_address not in self.addresses_choosen:
            self.addresses_choosen.append(datakey_address)

        self.update_datastreamtable()
    def add_all_datastreams(self):
        items = self.get_all_items()
        self.add_datastreams(items)

    def add_datastreams(self, items=None):
        funcname = __name__ + '.add_datastreams():'
        logger.debug(funcname)
        if items is None:
            items = self.devicelist.selectedItems()
        for i,item in enumerate(items):
            #print(i,item.text(0))
            try:
                iskey = item.iskey
            except:
                iskey= False
            if iskey:
                print('Item {} is a valid address'.format(item.text(0)))
                if item.datakey_address not in self.addresses_choosen:
                    self.addresses_choosen.append(item.datakey_address)
                else:
                    print('Address is existing already')

            else:
                print('Item {} is not a datastream'.format(item.text(0)))


        #print('Addresses',self.addresses_choosen)
        self.update_datastreamtable()


class datastreamQTreeWidget(QtWidgets.QWidget):
    """ Widget shows all datastreams in a QTree style
    """
    def __init__(self, redvypr, device=None, filter_include=[], headerlabel=''):
        super(QtWidgets.QWidget, self).__init__()
        logger.setLevel(logging.DEBUG)
        self.setWindowIcon(QtGui.QIcon(_icon_file))
        self.redvypr = redvypr
        self.datakeys_expanded = True
        self.expandlevel = 3
        self.external_filter_include = filter_include
        self.layout = QtWidgets.QGridLayout(self)
        self.device = device
        try:
            self.devicename = device.name
        except:
            self.devicename = device
        if (device is not None):
            pass
            #self.devicenamelabel = QtWidgets.QLabel('Device: ' + self.devicename)
            #self.layout.addWidget(self.devicenamelabel)
        else:
            self.devicename = ''

        self.deviceavaillabel = QtWidgets.QLabel('Available devices')
        self.devicelist = QtWidgets.QTreeWidget()  # List of available devices
        self.devicelist.setColumnCount(1)
        self.devicelist.setHeaderLabels([headerlabel])
        self.devicelist.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.devicelist.header().setStretchLastSection(False)
        #self.devicelist.setAutoScroll(True)


        self.filterWidget = address_filterWidget(redvypr = redvypr)
        # Expansion level
        expandlayout = QtWidgets.QHBoxLayout()
        self.expandlevel_spin = QtWidgets.QSpinBox()
        self.expandlevel_spin.setValue(self.expandlevel)
        self.expandlevel_spin.valueChanged.connect(self.__expandlevelChanged)
        expandlayout.addWidget(QtWidgets.QLabel('Expansion level'))
        expandlayout.addWidget(self.expandlevel_spin)

        # Add widgets to layout
        self.deviceWidget = QtWidgets.QWidget()
        self.layout_left = QtWidgets.QVBoxLayout(self.deviceWidget)
        self.settingsWidget = QtWidgets.QWidget()
        self.layout_right = QtWidgets.QVBoxLayout(self.settingsWidget)
        self.layout_right.addLayout(expandlayout)
        self.layout_right.addWidget(self.filterWidget)
        self.layout_left.addWidget(self.deviceavaillabel)
        self.layout_left.addWidget(self.devicelist)

        # Create a splitter
        # if self.config_location == 'bottom':
        #    sdir = QtCore.Qt.Vertical
        # else:
        #    sdir = QtCore.Qt.Horizontal

        sdir = QtCore.Qt.Vertical
        self.splitter = QtWidgets.QSplitter(sdir)
        self.splitter.addWidget(self.deviceWidget)
        self.splitter.addWidget(self.settingsWidget)

        self.layout.addWidget(self.splitter,0,0)

        ## Add a stretch
        #self.layout_right.addStretch()
        if self.datakeys_expanded:
            self.__update_devicetree_expanded()
            self.filterWidget.filterChanged.connect(self.__update_devicetree_expanded)
        else:
            self.__update_devicetree()
            self.filterWidget.filterChanged.connect(self.__update_devicetree)

    def __expandlevelChanged(self):
        funcname = __name__ + '.____expandlevelChanged():'
        logger.debug(funcname)
        self.expandlevel = self.expandlevel_spin.value()
        self.__update_devicetree_expanded()


    def apply_address_filter(self,device, filter_address):#
        funcname = __name__ + '.apply_address_filter():'
        logger.debug(funcname + 'Testing {} in {} (with subsearch)'.format(device.address, filter_address))
        test_filter = device.address in filter_address
        test_filter_sub = False
        if test_filter == False: # Check if subdevices have a match
            # Test all devices of publisher in brute force and check if one of them fits
            devs_forwarded = device.get_device_info()
            for devaddress in devs_forwarded:
                datakey_dict = devs_forwarded[devaddress]['datakeys_expanded']
                # print('Datakeys', datakey_dict)
                devaddress_redvypr = RedvyprAddress(devaddress)
                if devaddress_redvypr in filter_address:
                    test_filter_sub = True
                    print('Filter match for subsearch:', devaddress_redvypr)
                    break


        if test_filter or test_filter_sub:
            print('Filter match for ', device.address)
            return True
        else:
            print('No filter match for ', device.address)
            return False


    def __update_devicetree_expanded(self):
        funcname = __name__ + '.__update_devicetree_expanded():'
        logger.debug(funcname)
        colgrey = QtGui.QColor(220, 220, 220)
        def update_recursive(data_new_key, data_new, parent_item, datakey_construct, expandlevel):
            funcname = __name__ + '.__update_recursive():'
            #logger.debug(funcname)
            if self.expandlevel == 0:
                datakey_construct_new = data_new_key
            else:
                datakey_construct_new = datakey_construct + '[' + json.dumps(data_new_key) + ']'

            raddress_constructed = RedvyprAddress(devaddress, datakey=datakey_construct_new)
            #print('Hallo',data_new_key, data_new,type(data_new))
            #print('Datakey construct new',datakey_construct_new)
            # Check if we are at an item level that is a datakey to be used as a datastream
            if isinstance(data_new, tuple) or (expandlevel >= self.expandlevel):
                #print('Set',data_new,self.expandlevel)
                if expandlevel >= self.expandlevel:
                    #print('Level reached')
                    addrstr_expanded = datakey_construct_new
                else:
                    addrstr = data_new[0]  # Index 0 of set is the address, index 1 the datatype
                    datakeyaddr = RedvyprAddress(addrstr)
                    # Construct a datakey based on the expansion level
                    dkeys_expanded = datakeyaddr.parsed_addrstr_expand['datakeyentries_str']
                    #print('Datakeyaddr', datakeyaddr)
                    #print('expanded datakeys', datakeyaddr.parsed_addrstr_expand['datakeyentries_str'])
                    if datakeyaddr.parsed_addrstr_expand['datakeyeval']:
                        addrstr_expanded = ''
                        for iexpand in range(len(dkeys_expanded)):
                            if iexpand < self.expandlevel:
                                addrstr_expanded += '[' + dkeys_expanded[iexpand] + ']'

                        #print('Addresstr expanded',addrstr_expanded)
                    else:
                        addrstr_expanded = addrstr

                #print('Addresstr expanded',addrstr_expanded)
                itmk = QtWidgets.QTreeWidgetItem([addrstr_expanded])
                itmk.iskey = True
                itmk.device = dev
                itmk.devaddress = devaddress
                #print('Creating address with devaddress',devaddress)
                #print('Creating address with devaddress parsed', devaddress.parsed_addrstr)
                #print('Creating address with datakey', addrstr)
                itmk.datakey_address = RedvyprAddress(devaddress, datakey=addrstr_expanded)
                itmk.raddress = itmk.datakey_address
                #print('Address',itmk.datakey_address)
                #print('Address parsed', itmk.datakey_address.parsed_addrstr)
                if self.filterWidget.filter_on:
                    test_filter = itmk.datakey_address not in self.filterWidget.filter_address
                    # TODO: Here also the external filter should be checked
                    logger.debug('Testing (@tuple): {} not in {}: {}'.format(itmk.datakey_address,
                                                                             self.filterWidget.filter_address,
                                                                             test_filter))
                    if test_filter:
                        logger.debug('No filter match for {}'.format(itmk.datakey_address))
                    else:
                        parent_item.addChild(itmk)
                else:
                    parent_item.addChild(itmk)

            elif isinstance(data_new, list):
                itmk = QtWidgets.QTreeWidgetItem([str(data_new_key)])
                itmk.setBackground(0, colgrey)
                itmk.raddress = raddress_constructed
                parent_item.addChild(itmk)
                for data_new_index, data_new_item in enumerate(data_new):
                    update_recursive(data_new_index, data_new_item, parent_item=itmk, datakey_construct=datakey_construct_new, expandlevel=expandlevel+1)

            elif isinstance(data_new, dict):
                itmk = QtWidgets.QTreeWidgetItem([data_new_key])
                itmk.setBackground(0, colgrey)
                itmk.raddress = raddress_constructed
                parent_item.addChild(itmk)
                for data_new_key in data_new.keys():
                    update_recursive(data_new_key, data_new[data_new_key], parent_item=itmk, datakey_construct=datakey_construct_new, expandlevel=expandlevel+1)

        if True:
            self.devicelist.clear()
            root = self.devicelist.invisibleRootItem()
            # self.devices_listDevices.addItem(str(device))
            data_provider_all = self.redvypr.get_device_objects(publishes=True, subscribes=False)
            font1 = QtGui.QFont('Arial')
            font1.setBold(True)
            font0 = QtGui.QFont('Arial')

            # Fill the qtreewidget
            #print('data provider',data_provider_all)
            if (data_provider_all is not None):
                for dev in data_provider_all:
                    flag_datastreams = False
                    #if dev == self.device:
                    #    continue

                    #print('Device {}'.format(dev.name))
                    #print('Address', dev.address)
                    # Check for external filter
                    flag_external_filter = True
                    for addr_include in self.external_filter_include:
                        flag_external_filter = self.apply_address_filter(dev,addr_include)
                    if flag_external_filter == False:
                        continue
                    # Check for filter from filter widget
                    if self.filterWidget.filter_on:
                        test_filter = dev.address not in self.filterWidget.filter_address
                        test_filter_sub = True
                        if test_filter == True:
                            # Test all devices of publisher in brute force and check if one of them fits
                            devs_forwarded = dev.get_device_info()
                            for devaddress in devs_forwarded:
                                datakey_dict = devs_forwarded[devaddress]['datakeys_expanded']
                                #print('Datakeys', datakey_dict)
                                devaddress_redvypr = RedvyprAddress(devaddress)
                                #print('a',devaddress_redvypr,self.filterWidget.filter_address)
                                if devaddress_redvypr in self.filterWidget.filter_address:
                                    test_filter_sub = False
                                    #print('Filter match for ', devaddress_redvypr)
                                    continue

                        logger.debug('Testing {} not in {}: {}'.format(dev.address, self.filterWidget.filter_address, test_filter))
                        if test_filter and test_filter_sub:
                            #print('No filter match for ', dev.address)
                            continue

                    itm = QtWidgets.QTreeWidgetItem([dev.name])
                    col = QtGui.QColor(220, 220, 220)
                    itm.setBackground(0, col)
                    itm.device = dev
                    itm.redvypr_address = dev.address
                    itm.raddress = dev.address

                    itm.iskey = False
                    # Check for forwarded devices
                    if True:
                        devs_forwarded = dev.get_device_info()
                        devkeys = list(devs_forwarded.keys())
                        devkeys.sort()
                        for devaddress in devkeys:
                            datakey_dict = devs_forwarded[devaddress]['datakeys_expanded']
                            #print('Datakeys',datakey_dict)

                            #fdsfdsf
                            flag_datastreams = True
                            devaddress_redvypr = RedvyprAddress(devaddress)
                            # Filter the addresses
                            flag_external_filter_match = False
                            for addr_include in self.external_filter_include:
                                if devaddress_redvypr in addr_include:
                                    flag_external_filter_match = True
                                    break

                            # No external filter match, ignore device
                            if not(flag_external_filter_match):
                                continue
                            if self.filterWidget.filter_on:
                                if devaddress_redvypr not in self.filterWidget.filter_address:
                                    #print('No filter match for ', devaddress_redvypr)
                                    continue
                            addrtype = '/d/i/'
                            #print('Hallo', devaddress_redvypr, devaddress_redvypr.get_str())
                            devicestr = devaddress_redvypr.devicename
                            # TODO, this should be defined in the configuration of the widget
                            #devicestr = devaddress_redvypr.get_str(addrtype)
                            devicestr = devaddress_redvypr.get_str()
                            itmf = QtWidgets.QTreeWidgetItem([devicestr])
                            itmf.setBackground(0, col)
                            itmf.device = dev
                            itmf.redvypr_address = devaddress_redvypr
                            itmf.address_forwarded = devaddress
                            itmf.raddress = devaddress_redvypr
                            itm.addChild(itmf)
                            itmf.iskey = False

                            for key in datakey_dict.keys():
                                data_new = datakey_dict[key]
                                datakey_construct_new = ''
                                update_recursive(key, data_new, parent_item=itmf, datakey_construct=datakey_construct_new, expandlevel=0)

                    if flag_datastreams:  # If we have datastreams found, add the itm
                        root.addChild(itm)

            self.devicelist.expandAll()
            #self.devicelist.header().setStretchLastSection(True)
            self.devicelist.resizeColumnToContents(0)






