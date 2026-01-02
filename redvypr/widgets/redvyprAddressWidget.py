import json

from PyQt6 import QtWidgets, QtCore, QtGui
import logging
import sys
import qtawesome
import redvypr.files as files
import redvypr.data_packets as data_packets
from redvypr.redvypr_address import RedvyprAddress


_logo_file = files.logo_file
_icon_file = files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.widgets.redvyprAddressWidget')
logger.setLevel(logging.DEBUG)



class RedvyprAddressEditWidget(QtWidgets.QWidget):
    """ A widget that allows to enter an address and to modify each key individually
    """
    address_finished = QtCore.pyqtSignal(dict)  # Signal notifying that the configuration has changed
    def __init__(self, redvypr_address_str=None):
        """
        """
        super(QtWidgets.QWidget, self).__init__()
        self.addrentries_for_str_format = ['h' 'd', 'i', 'k']
        self.redvypr_address_full = None
        self.redvypr_address_format = None
        if redvypr_address_str is None:
            self.redvypr_address_full = RedvyprAddress()
        elif isinstance(redvypr_address_str, RedvyprAddress):
            self.redvypr_address_full = redvypr_address_str
        elif isinstance(redvypr_address_str, str):
            self.redvypr_address_full = RedvyprAddress(redvypr_address_str)

        #print("REDVYPR ADDRESSES",)
        self.layout = QtWidgets.QGridLayout(self)
        self.key_widget = QtWidgets.QWidget()

        self.layout_keys = QtWidgets.QGridLayout(self.key_widget)

        atmp = RedvyprAddress()
        self.address_entries = {}
        self.address_entries_check = {}
        for i,k in enumerate(atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY.keys()):
            entry_tmp = atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY[k]
            keyedit = QtWidgets.QLineEdit()
            keyedit.editingFinished.connect(self.update_address_from_linedits)
            keycheck = QtWidgets.QCheckBox()
            if k in self.addrentries_for_str_format:
                keycheck.setChecked(True)

            keycheck.stateChanged.connect(self.update_address_from_linedits)
            label = QtWidgets.QLabel(k)
            label.setToolTip(atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY[k])
            self.address_entries[k] = keyedit
            self.address_entries_check[k] = keycheck
            self.layout_keys.addWidget(label,i,0)
            self.layout_keys.addWidget(keyedit,i,1)
            self.layout_keys.addWidget(keycheck, i, 2)

        self.fulladdr = QtWidgets.QLineEdit()
        self.fulladdr.setReadOnly(True)
        self.submitaddr = QtWidgets.QLineEdit()
        self.submitaddr.setReadOnly(True)
        # Buttons
        self.configwidget_apply = QtWidgets.QPushButton('Apply')
        self.configwidget_apply.clicked.connect(self.applyClicked)
        self.configwidget_apply.__configType = 'configRedvyprAddressStr'

        self.layout.addWidget(QtWidgets.QLabel('Address Entries'), 0, 0)
        self.layout.addWidget(self.key_widget, 1, 0)
        self.layout.addWidget(QtWidgets.QLabel('Full address'), 2, 0)
        self.layout.addWidget(self.fulladdr, 3, 0)
        self.layout.addWidget(QtWidgets.QLabel('Address'), 4, 0)
        self.layout.addWidget(self.submitaddr, 5, 0)
        self.layout.addWidget(self.configwidget_apply, 6, 0)
        self.setAddress(self.redvypr_address_full)

    def setAddress(self, address):
        funcname = __name__ + '.setAddress():'
        logger.debug(funcname)
        self.redvypr_address_full = address
        atmp = RedvyprAddress()
        for k in atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY.keys():
            entry_tmp = atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY[k]
            keyentry = getattr(address,k)
            if keyentry not in ("", None):
                self.address_entries[k].blockSignals(True)
                self.address_entries[k].setText(keyentry)
                self.address_entries[k].blockSignals(False)
            else:
                self.address_entries[k].setText("")

        self.update_address_from_linedits()

    def update_address_from_linedits(self):
        atmp = RedvyprAddress()
        addr_input = {}
        addr_input_submit = {}
        addr_input_submit_format = ''
        for k in atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY.keys():
            entry_tmp = self.address_entries[k].text()
            #print("Got text for {}:{}".format(k,entry_tmp))
            longform = atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY[k]
            if entry_tmp not in ("", None):
                addr_input[longform] = entry_tmp
                if self.address_entries_check[k].isChecked():
                    addr_input_submit[longform] = entry_tmp
                    addr_input_submit_format += atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY[k] + ','

        addr_input_submit_format = addr_input_submit_format.rstrip(',')
        try:
            raddr = RedvyprAddress(**addr_input)
        except:
            logger.warning('Could not update address',exc_info=True)
            return

        try:
            raddr_submit = RedvyprAddress(**addr_input_submit)
        except:
            logger.warning('Could not update address',exc_info=True)
            return

        self.redvypr_address_full = raddr
        self.fulladdr.setText(raddr.to_address_string())
        submit_str = raddr_submit.to_address_string(addr_input_submit_format)
        self.submitaddr.setText(submit_str)
        self.address_format = addr_input_submit_format
        self.redvypr_address = raddr_submit

    def applyClicked(self):
        funcname = __name__ + '.applyClicked():'
        logger.debug(funcname + 'Address: {} ({})'.format(self.redvypr_address_full,type(self.redvypr_address_full)))
        #self.address_finished.emit(str(self.redvypr_address))
        signal_dict = {'address_str': self.submitaddr.text(), 'address':self.redvypr_address,
                       'address_format': self.address_format, 'address_full':self.redvypr_address_full}

        self.address_finished.emit(signal_dict)


class RedvyprAddressWidgetSimple(QtWidgets.QWidget):
    """ A widget that allows to enter an address
    """
    address_finished = QtCore.pyqtSignal(str)  # Signal notifying that the configuration has changed
    def __init__(self, redvypr_address_str='@'):
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




class AddressFilterwidget(QtWidgets.QWidget):
    """
    Widget allows to create a redvypr address that can be used to filter addresses.
    """
    filterChanged = QtCore.pyqtSignal()  # Signal notifying if the device path was changed
    def __init__(self, redvypr = None):
        """
        """
        self.redvypr = redvypr
        self.filter_address = RedvyprAddress()
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
        self.line_devicefilter = QtWidgets.QLineEdit(self.filter_address.device)
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

        self.line_filterstr = QtWidgets.QLineEdit(self.filter_address.to_address_string())

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
        options.append("@")

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
            if '@' in optionslist:
                optionstr = '@'
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
        device = self.line_devicefilter.text()
        publisher = self.line_publishingdevicefilter.text()
        self.filter_address = RedvyprAddress(datakey=datakey,
                                             packetid=packetid,
                                             host=host,
                                             device=device,
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


class RedvyprAddressWidget(QtWidgets.QWidget):
    """
    Widget that lets the user to enter a RedvyprAddress.
    devicelock: The user cannot change the device anymore
    """
    apply = QtCore.pyqtSignal(dict)  # Signal notifying if the Apply button was clicked
    datakey_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the datakey has changed

    def __init__(self, redvypr, device=None, device_highlight=None, datakey=None, deviceonly=False,
                 devicelock=False, subscribed_only=True, showapplybutton=True, datastreamstring=None, closeAfterApply=True,
                 filter_include=[], datakeys_expanded=True, manual_address=None):
        """
        Args:
            redvypr:
            device:
            device_highlight: The device that is highlighted in the list
            datakey:
            deviceonly:
            devicelock:
            filter_include: List of RedvyprAdresses the will be checked
            subscribed_only: Show the subscribed devices only
            manual_address: String for the manual address
        """

        super(QtWidgets.QWidget, self).__init__()
        logger.setLevel(logging.DEBUG)
        self.setWindowIcon(QtGui.QIcon(_icon_file))
        self.closeAfterApply = closeAfterApply
        self.redvypr = redvypr
        self.datakeys_expanded = datakeys_expanded

        self.external_filter_include = filter_include
        self.datastreamstring_orig = datastreamstring
        self.datastreamstring  = datastreamstring
        self.layout = QtWidgets.QGridLayout(self)
        self.deviceonly = deviceonly
        if (device_highlight == None):
            self.device_highlight = 'Na'
        else:
            self.device_highlight = device_highlight

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

        if self.datakeys_expanded == False:
            self.expandlevel = 0
        else:
            self.expandlevel = 30

        self.addrentries_show_for_publishing_devices = ['h','d','i']  # The entries that are shown for the devices
        self.devicelist = QtWidgets.QTreeWidget()  # List of available devices
        self.devicelist.setHeaderLabels(['Datastreams'])
        self.devicelist.setColumnCount(1)
        self.devicelist.itemClicked.connect(self.__device_clicked)
        # Add menus to the qtreewidgetitems
        self.devicelist.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.devicelist.customContextMenuRequested.connect(self.show_menu_for_treeitem)



        self.filterWidget = AddressFilterwidget(redvypr = redvypr)
        # Expansion level
        expandlayout = QtWidgets.QHBoxLayout()
        self.expandlevel_spin = QtWidgets.QSpinBox()
        self.expandlevel_spin.setValue(self.expandlevel)
        self.expandlevel_spin.valueChanged.connect(self.__expandlevelChanged)
        expandlayout.addWidget(QtWidgets.QLabel('Expansion level'))
        expandlayout.addWidget(self.expandlevel_spin)
        #
        self.address_edit = RedvyprAddressEditWidget(datastreamstring)
        self.address_edit.address_finished.connect(self.done_clicked)
        # Add widgets to layout
        # Right/left layout side
        self.layout_left = QtWidgets.QVBoxLayout()
        self.layout_right = QtWidgets.QVBoxLayout()
        # Left side
        self.layout_left.addWidget(self.devicelist)
        self.layout_left.addLayout(expandlayout)
        self.layout_left.addWidget(self.filterWidget)
        # Right side
        self.layout_right.addWidget(self.address_edit)

        self.layout.addLayout(self.layout_left,0,0)
        self.layout.addLayout(self.layout_right,0,1)

        # The datakeys
        if deviceonly == False:
            pass

        #if showapplybutton == False:
        #    self.address_edit.__configwidget_apply.hide()

        self.datakeylist_subscribed = {}
        if True:
            self.__update_devicetree_expanded()
            self.filterWidget.filterChanged.connect(self.__update_devicetree_expanded)

    def show_menu_for_treeitem(self,pos: QtCore.QPoint):
        tree = self.devicelist
        item = tree.itemAt(pos)  # Get the item


        try:
            addrentries = item.addrentries
        except:
            addrentries = self.addrentries_show_for_publishing_devices

        #print('Item', item,'Addrentries',addrentries)
        if True:
            menu = QtWidgets.QMenu(tree)
            check_all = QtWidgets.QWidget()
            check_all_layout = QtWidgets.QVBoxLayout(check_all)
            atmp = RedvyprAddress()
            all_check = {}
            #print('Hallo',atmp.__addr_entries_short_r)
            for k in atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY.keys():
                entry_tmp = atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY[k]
                check = QtWidgets.QCheckBox(k)
                check.__item = item
                if entry_tmp in addrentries:
                    check.setChecked(True)
                check.stateChanged.connect(self.__update_item)
                check_all_layout.addWidget(check)
                all_check[entry_tmp] = check
                item.all_check = all_check
            checkAction = QtWidgets.QWidgetAction(self)
            checkAction.setDefaultWidget(check_all)
            menu.addAction(checkAction)
            menu.exec_(tree.mapToGlobal(pos))

    def __expandlevelChanged(self):
        funcname = __name__ + '.____expandlevelChanged():'
        logger.debug(funcname)
        self.expandlevel = self.expandlevel_spin.value()
        self.__update_devicetree_expanded()

    def __device_clicked(self,item):
        """
        Called when an item in the qtree is clicked
        """
        funcname = __name__ + '__device_clicked()'
        logger.debug(funcname)
        #print('Item',item.iskey)
        #if(item.iskey): # If this is a datakey item
        if True:
            print(funcname + "Setting address to:{}".format(item.datakey_address))
            self.address_edit.setAddress(item.datakey_address)
            #print('Addresstype', addrtype)
            #print('Address',item.datakey_address)
            #print('Addrstring',addrstring)
            #print('Devstring', item.devaddress)
        else:
            logger.debug('this is not an address with a datakey, doing nothing')

    def __update_devicetree_simple(self):
        """

        Returns
        -------

        """
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
                                devicename = devaddress_redvypr.device
                                itmf = QtWidgets.QTreeWidgetItem([devicename])
                                itmf.setBackground(0, col)
                                itmf.device = dev
                                itmf.redvypr_address = devaddress_redvypr
                                itmf.address_forwarded = devaddress
                                itmf.iskey = True
                                itm.addChild(itmf)


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
        colgrey = QtGui.QColor(210, 210, 210)
        colgrey_key = QtGui.QColor(240, 240, 240)
        def update_recursive(data_new_key, data_new, parent_item, datakey_construct, expandlevel):
            funcname = __name__ + '.__update_recursive():'
            logger.debug(funcname)

            #if self.expandlevel == 0:
            #    datakey_construct_new = data_new_key
            #else:
            #    datakey_construct_new = datakey_construct + '[' + json.dumps(data_new_key) + ']'

            datakey_construct_new = str(data_new_key)
            print('Hallo',data_new_key, data_new,type(data_new))
            print('Datakey construct new',datakey_construct_new)
            # Check if we are at an item level that is a datakey to be used as a datastream
            if isinstance(data_new, tuple) or (expandlevel >= self.expandlevel):
                print('Set',data_new,self.expandlevel)
                datakey_construct_new = data_new[0]
                addrstr_expanded = datakey_construct_new
                if expandlevel >= self.expandlevel:
                    #print('Level reached')
                    addrstr_expanded = datakey_construct_new

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
                # check if data_new_key is an index, if yes enclose it
                if type(data_new_key) == int:
                    data_new_key = '[{}]'.format(data_new_key)
                itmk.redvypr_address = RedvyprAddress(devaddress, datakey=data_new_key)
                itmk.iskey = True
                itmk.device = dev
                itmk.setBackground(0, colgrey_key)
                itmk.datakey_address = itmk.redvypr_address
                parent_item.addChild(itmk)
                for data_new_index, data_new_item in enumerate(data_new):
                    update_recursive(data_new_index, data_new_item, parent_item=itmk, datakey_construct=datakey_construct_new, expandlevel=expandlevel+1)

            elif isinstance(data_new, dict):
                itmk = QtWidgets.QTreeWidgetItem([data_new_key])
                itmk.redvypr_address = RedvyprAddress(devaddress, datakey=data_new_key)
                #itmk.redvypr_address = RedvyprAddress(data_new_key,packetid="BLAR")
                itmk.iskey = False
                itmk.device = dev
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
                        test_filter = not(self.filterWidget.filter_address).matches_filter(dev.address)
                        test_filter_sub = True
                        if test_filter == True:
                            # Test all devices of publisher in brute force and check if one of them fits
                            devs_forwarded = dev.get_device_info()
                            for devaddress in devs_forwarded:
                                datakey_dict = devs_forwarded[devaddress]['datakeys_expanded']
                                #print('Datakeys', datakey_dict)
                                devaddress_redvypr = RedvyprAddress(devaddress)
                                if self.filterWidget.filter_address.matches_filter(devaddress_redvypr):
                                    test_filter_sub = False
                                    #print('Filter match for ', devaddress_redvypr)
                                    continue

                        logger.debug('Testing {} not in {}: {}'.format(dev.address, self.filterWidget.filter_address, test_filter))
                        if test_filter and test_filter_sub:
                            #print('No filter match for ', dev.address)
                            continue

                    # The device itself
                    itm = QtWidgets.QTreeWidgetItem([dev.name])
                    itm.setBackground(0, colgrey)
                    itm.device = dev
                    itm.redvypr_address = dev.address
                    itm.datakey_address = RedvyprAddress(dev.address)
                    itm.iskey = False
                    # Loop over all devices that have published through this device
                    if True:
                        devs_forwarded = dev.get_device_info()
                        print("\n\nDeviceinfo:\n{}".format(devs_forwarded))
                        devkeys = list(devs_forwarded.keys())
                        devkeys.sort()
                        for devaddress in devkeys:
                            datakey_dict = devs_forwarded[devaddress]['datakeys_expanded']
                            print('Datakeys',datakey_dict)
                            devaddress_redvypr = RedvyprAddress(devaddress)
                            if self.filterWidget.filter_on:
                                if devaddress_redvypr not in self.filterWidget.filter_address:
                                    #print('No filter match for ', devaddress_redvypr)
                                    continue

                            #print('Addr', devaddress_redvypr, devaddress_redvypr.get_str())
                            devicestr = self.get_addressstr_for_item(devaddress_redvypr,self.addrentries_show_for_publishing_devices)
                            itmf = QtWidgets.QTreeWidgetItem([devicestr])
                            itmf.setBackground(0, colgrey)
                            itmf.device = dev
                            itmf.addrentries = self.addrentries_show_for_publishing_devices
                            itmf.redvypr_address = devaddress_redvypr
                            itmf.datakey_address = devaddress_redvypr
                            itmf.address_forwarded = devaddress
                            itmf.iskey = False
                            if len(datakey_dict.keys())>0:  # Only add the device if it has some datakey to show
                                itm.addChild(itmf)
                                for key in datakey_dict.keys():
                                    data_new = datakey_dict[key]
                                    datakey_construct_new = ''
                                    update_recursive(key, data_new, parent_item=itmf, datakey_construct=datakey_construct_new, expandlevel=0)
                                    flag_datastreams = True

                    if flag_datastreams:  # If we have datastreams found, add the itm
                        root.addChild(itm)

            self.devicelist.expandAll()
            self.devicelist.resizeColumnToContents(0)

    def get_addressstr_for_item(self,raddr, addrentrylist, newline=True):
        #self.addrtype_for_publishing_devices = '/{h}\n/{d}\n/{i}'  # The addrtype to show for publishin devices
        funcname = "get_addressstr_for_item()"
        print(funcname)
        print("Entries ...:",addrentrylist)
        devicestr = raddr.to_address_string(addrentrylist)
        print("Devicestr", devicestr)
        return devicestr
        if False:
            addrformat = ''
            if newline:
                newlinestr = '\n'
            else:
                newlinestr = ''
            for k in addrentrylist:
                addrformat += '{' + k + '}' + newlinestr

            if newline:  # remove the last newline
                addrformat = addrformat[:-1]

            print("Address test",raddr)
            print("Address test format", addrformat)
            devicestr = raddr.get_str_from_format(addrformat)
            return devicestr

    def __update_item(self):
        try:
            item = self.sender().__item
        except:
            print('No item selected')
            return

        entries = []
        for entry in item.all_check:
            check = item.all_check[entry]
            if check.isChecked():
                entries.append(entry)

        item.addrentries = entries
        raddr = item.redvypr_address
        devicestr = self.get_addressstr_for_item(raddr,entries)
        item.setText(0,devicestr)

    def __update_all_items(self):
        tree = self.devicelist
        #
        def iterate_items(parent):
            for i in range(parent.childCount()):
                child = parent.child(i)
                print(child.text(0))
                iterate_items(child)


        for i in range(tree.topLevelItemCount()):
            root = tree.topLevelItem(i)
            print(root.text(0))
            iterate_items(root)

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

    def done_clicked(self,address_dict):
        funcname = __name__ + '.done_clicked():'
        #device = self.device
        #device_address = self.addressline.devaddress
        datastream_str = address_dict['address_str']
        datastream_address = address_dict['address']
        addrformat = address_dict['address_format']
        #signal_dict_new = {'device': device, 'device_address':device_address,'datastream_str': datastream_str,'datastream_address':datastream_address,'address_format':addrformat}
        signal_dict_new = {'datastream_str': datastream_str,
                           'datastream_address': datastream_address, 'address_format': addrformat}
        #print(funcname + 'Signal dict {}'.format(signal_dict_new))
        self.redvypr_address = datastream_address
        self.apply.emit(signal_dict_new)
        if self.closeAfterApply:
            self.close()


class RedvyprMultipleAddressesWidget(RedvyprAddressWidget):
    """ Widget that lets the user choose several datastreams
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args,**kwargs)
        self.addrentries_for_str_format = ['h', 'd', 'i', 'k']
        self.devicelist.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.datastreamtable = QtWidgets.QTableWidget()
        #self.datastreamtable.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.layout.addWidget(self.datastreamtable,0,2)
        #self.layout.removeWidget(self.buttondone)
        #self.buttondone.clicked.disconnect(self.done_clicked)
        self.apply_button = QtWidgets.QPushButton('Apply')
        self.apply_button.clicked.connect(self.apply_clicked_datastreams)
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
        self.button_add.clicked.connect(self.add_datastreams_clicked)
        self.button_add_manual = QtWidgets.QPushButton('Add manual')
        self.button_add_manual.setIcon(icon)
        self.button_add_manual.clicked.connect(self.add_manual_datastream)
        self.button_add_all = QtWidgets.QPushButton('Add all')
        self.button_add_all.setIcon(icon)
        self.button_add_all.clicked.connect(self.add_all_datastreams)

        self.layout_right.removeWidget(self.address_edit)
        self.address_edit.hide()

        # Create check boxes for the format
        check_all = QtWidgets.QWidget()
        check_all_layout = QtWidgets.QVBoxLayout(check_all)
        atmp = RedvyprAddress()
        all_check = {}
        # print('Hallo',atmp.__addr_entries_short_r)
        addrentries = self.addrentries_for_str_format
        for k in atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY.keys():
            entry_tmp = atmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY[k]
            #print("k test", k, entry_tmp, addrentries)
            check = QtWidgets.QCheckBox(k)
            if (k in addrentries) or (entry_tmp in addrentries):
                check.setChecked(True)
            check.stateChanged.connect(self.update_datastreamtable)
            check_all_layout.addWidget(check)
            all_check[entry_tmp] = check

        self.str_format_checkboxes = all_check
        self.layout_right.addWidget(check_all)
        self.layout.addWidget(self.button_add, 1, 0)
        self.layout.addWidget(self.button_add_all, 2, 0)
        self.layout.addWidget(self.button_add_manual, 3, 0)
        self.layout.addWidget(self.button_rem, 1, 2)
        self.layout.addWidget(self.button_rem_all, 2, 2)
        self.layout.addWidget(self.apply_button,3,0,1,-1)
        self.addresses_chosen = []
        self.update_datastreamtable()

    def apply_clicked_datastreams(self):
        funcname = __name__ + '.apply_clicked_datastreams()'
        logger.debug(funcname)
        addresses_choosen = []
        addresses_str_choosen = []

        entries = []
        for entry in self.str_format_checkboxes:
            check = self.str_format_checkboxes[entry]
            if check.isChecked():
                entries.append(entry)

        for irow, raddr in enumerate(self.addresses_chosen):
            addrstr = self.get_addressstr_for_item(raddr, entries, newline=False)
            addresses_choosen.append(RedvyprAddress(addrstr))
            addresses_str_choosen.append(addrstr)

        # Create a signal dict, with a format similar to the dict returned by the "apply" signal of the datastreamWidget
        signal_dict = {'addresses':addresses_choosen,'datastreams_address':addresses_choosen,'datastreams_str':addresses_str_choosen}

        #print('Signal dict',signal_dict)
        self.apply.emit(signal_dict)
        if self.closeAfterApply:
            self.close()

    def update_datastreamtable(self):
        entries = []
        for entry in self.str_format_checkboxes:
            check = self.str_format_checkboxes[entry]
            if check.isChecked():
                entries.append(entry)

        self.datastreamtable.clear()
        nrows = len(self.addresses_chosen)
        self.datastreamtable.setRowCount(nrows)
        self.datastreamtable.setColumnCount(1)
        for irow, raddr in enumerate(self.addresses_chosen):
            addrstr = self.get_addressstr_for_item(raddr, entries, newline=False)
            item = QtWidgets.QTableWidgetItem(addrstr)
            #item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            item.datakey_address = raddr
            self.datastreamtable.setItem(irow,0, item)

        self.datastreamtable.setHorizontalHeaderLabels(['Address'])
        self.datastreamtable.setWordWrap(True)
        self.datastreamtable.resizeColumnsToContents()
        self.datastreamtable.resizeRowsToContents()
        self.datastreamtable.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.datastreamtable.horizontalHeader().setStretchLastSection(True)
        self.datastreamtable.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.datastreamtable.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)
        #if len(self.addresses_chosen)>0:
        #    self.buttondone.setEnabled(True)
        #else:
        #    self.buttondone.setEnabled(False)

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
            self.addresses_chosen.remove(item.datakey_address)

        self.update_datastreamtable()

    def add_manual_datastream(self):
        funcname = __name__ + '.add_manual_datastream():'
        logger.debug(funcname)
        # Here the
        self.address_edit_tmp = RedvyprAddressEditWidget()
        self.address_edit_tmp.show()
        #self.address_edit.show()
        #self.update_datastreamtable()
    def add_all_datastreams(self):
        items = self.get_all_items()
        self.add_datastreams(items)

    def add_datastreams_clicked(self):
        items = self.devicelist.selectedItems()
        self.add_datastreams(items)

    def add_datastreams(self, items=None):
        funcname = __name__ + '.add_datastreams():'
        logger.debug(funcname)
        if items is None:
            raise ValueError('No datastreams given')

        for i,item in enumerate(items):
            #print(i,item.text(0))
            try:
                iskey = item.iskey
            except:
                iskey= False
            if iskey:
                print('Item {} is a valid address'.format(item.text(0)))
                if item.datakey_address not in self.addresses_chosen:
                    self.addresses_chosen.append(item.datakey_address)
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


        self.filterWidget = AddressFilterwidget(redvypr = redvypr)
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
        colgrey_key = QtGui.QColor(150, 150, 150)
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
                    itm.setBackground(0, colgrey)
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
                            addrtype = 'd,i'
                            #print('Hallo', devaddress_redvypr, devaddress_redvypr.get_str())
                            devicestr = devaddress_redvypr.devicename
                            # TODO, this should be defined in the configuration of the widget
                            #devicestr = devaddress_redvypr.get_str(addrtype)
                            devicestr = devaddress_redvypr.get_str()
                            itmf = QtWidgets.QTreeWidgetItem([devicestr])
                            itmf.setBackground(0, colgrey)
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






