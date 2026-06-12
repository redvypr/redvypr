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

        print(f"{addr_input_submit=}")
        try:
            raddr_submit = RedvyprAddress(**addr_input_submit)
        except:
            logger.warning('Could not update address',exc_info=True)
            return

        print(f"{raddr.to_address_string()=}")
        print(f"{addr_input_submit_format=}")
        self.redvypr_address_full = raddr
        self.fulladdr.setText(raddr.to_address_string())
        #submit_str = raddr_submit.to_address_string(addr_input_submit_format)
        submit_str = raddr_submit.to_address_string()
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
        self.line_hostfilter = QtWidgets.QLineEdit(self.filter_address.host)

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
        self.line_filterstr.setText(self.filter_address.to_address_string())
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


class RedvyprAddressWidget_legacy(QtWidgets.QWidget):
    """
    Widget that lets the user enter a RedvyprAddress.
    devicelock: The user cannot change the device anymore
    """
    apply = QtCore.pyqtSignal(dict)  # Signal notifying if the Apply button was clicked
    datakey_name_changed = QtCore.pyqtSignal(str)  # Signal notifying if the datakey has changed

    def __init__(self, redvypr, device=None,
                 device_highlight=None,
                 datakey=None,
                 deviceonly=False,
                 devicelock=False,
                 subscribed_only=True,
                 showapplybutton=True,
                 datastreamstring=None,
                 closeAfterApply=True,
                 filter_device = ["@"],
                 filter_datastream= ["@"],
                 allow_all_addresses=True,
                 expansion_level=10,
                 force_time_series_expansion=False,
                 manual_address=None):
        """
        Args:
            redvypr:
            device:
            device_highlight: The device that is highlighted in the list
            datakey:
            deviceonly:
            devicelock:
            filter_device: List of RedvyprAdresses the will be checked
            subscribed_only: Show the subscribed devices only
            manual_address: String for the manual address
        """

        super(QtWidgets.QWidget, self).__init__()
        logger.setLevel(logging.DEBUG)
        self.setWindowIcon(QtGui.QIcon(_icon_file))
        self.closeAfterApply = closeAfterApply
        self.redvypr = redvypr
        self.allow_all_addresses = allow_all_addresses
        self.force_time_series_expansion = force_time_series_expansion
        # For the moment
        self.external_filter_include = []
        for f in filter_device:
            self.external_filter_include.append(RedvyprAddress(f))

        self.external_filter_datastream = []
        for f in filter_datastream:
            self.external_filter_datastream.append(RedvyprAddress(f))
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

        self.expandlevel = expansion_level

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
        # Force expansion
        self.force_expand_checkbox = QtWidgets.QCheckBox("Force time series expansion")
        self.force_expand_checkbox.setChecked(self.force_time_series_expansion)
        self.force_expand_checkbox.toggled.connect(self.__force_expand_toggled)
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
        self.layout_left.addWidget(self.force_expand_checkbox)
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

    def __force_expand_toggled(self):
        funcname = __name__ + '._force_expand_toggled():'
        logger.debug(funcname)
        self.force_time_series_expansion = self.force_expand_checkbox.isChecked()
        self.__update_devicetree_expanded()
    def __expandlevelChanged(self):
        funcname = __name__ + '.__expandlevelChanged():'
        logger.debug(funcname)
        self.expandlevel = self.expandlevel_spin.value()
        self.__update_devicetree_expanded()

    def __device_clicked(self,item):
        """
        Called when an item in the qtree is clicked
        """
        funcname = __name__ + '__device_clicked()'
        logger.debug(funcname)
        #print('Item',item.isdatastream)
        #if(item.isdatastream): # If this is a datakey item
        try:
            raddress = item.datakey_address
        except:
            raddress = item.redvypr_address

        print(funcname + "Setting address to:{}".format(raddress))
        self.address_edit.setAddress(raddress)


    def __update_devicetree_expanded(self):
        funcname = __name__ + '.__update_devicetree_expanded():'
        logger.debug(funcname)
        colgrey = QtGui.QColor(210, 210, 210)
        colgrey_key = QtGui.QColor(240, 240, 240)
        def update_recursive(data_new_key, data_new, parent_item, datakey_construct, expandlevel, local_maxexpansionlevel=9999):
            funcname = __name__ + '.__update_recursive():'
            logger.debug(funcname)
            datakey_construct_new = str(data_new_key)
            if len(datakey_construct_new) == 0:
                return
            print('Hallo',data_new_key, data_new,type(data_new))
            print('Datakey construct new',datakey_construct_new)
            print("len datakey",len(datakey_construct_new))
            # Check if we are at an item level that is a datakey to be used as a datastream
            if isinstance(data_new, tuple) or (expandlevel >= self.expandlevel) or (expandlevel >= local_maxexpansionlevel):
                #print('Set',data_new,self.expandlevel)
                #print("data new key",data_new_key)
                datakey_construct_new = data_new[0]
                addrstr_expanded = datakey_construct_new
                if (expandlevel >= self.expandlevel) or (expandlevel >= local_maxexpansionlevel):
                    print('Level reached',datakey_construct_new)
                    #addrstr_expanded = datakey_construct_new
                    addrstr_expanded = data_new_key

                #print('Addresstr expanded',addrstr_expanded)
                itmk = QtWidgets.QTreeWidgetItem([addrstr_expanded])
                itmk.isdatastream = True
                itmk.device = publishing_device
                itmk.devaddress = devaddress
                #print('Creating address with devaddress',devaddress)
                #print('Creating address with devaddress parsed', devaddress.parsed_addrstr)
                #print('Creating address with datakey', addrstr)
                itmk.datakey_address = RedvyprAddress(devaddress, datakey=addrstr_expanded)
                #print('Address',itmk.datakey_address)
                #print('Address parsed', itmk.datakey_address.parsed_addrstr)

                test_external_filter = False
                for f in self.external_filter_datastream:
                    logger.debug(
                        'Testing datastream: {} matches {}: {}'.format(f, itmk.datakey_address,
                                                           f.matches(itmk.datakey_address)))
                    if f.matches(itmk.datakey_address):
                        test_external_filter = True
                        break
                # Test gui filter widget
                if self.filterWidget.filter_on:
                    test_filter_widget = self.filterWidget.filter_address.matches(
                        itmk.datakey_address)
                    logger.debug(
                        f'Testing (@tuple): {self.filterWidget.filter_address}.matches({itmk.datakey_address}): {test_filter_widget}')
                else:
                    test_filter_widget = True

                if test_external_filter and test_filter_widget:
                    print("Add item ...\n\n\n",itmk.datakey_address)
                    parent_item.addChild(itmk)
                else:
                    print("Will not add item ...")

            elif isinstance(data_new, list):
                print("List entry\n")
                print(f'Parameter:{data_new_key=}, {data_new=},type:{type(data_new)}')
                print(f'Datakey construct new:{datakey_construct_new}')
                print(f"Parent address:{parent_item.redvypr_address}")
                parent_address_datakey = parent_item.redvypr_address.datakey
                # check if data_new_key is an index, if yes enclose it
                if parent_address_datakey:
                    if type(data_new_key) == int:
                        data_new_key = f'{parent_address_datakey}[{data_new_key}]'
                    else:
                        data_new_key = f'{parent_address_datakey}["{data_new_key}"]'

                #if type(data_new_key) == int:
                #    data_new_key = f'{parent_address_datakey}[{data_new_key}]'

                itmk = QtWidgets.QTreeWidgetItem([data_new_key])
                itmk.redvypr_address = RedvyprAddress(devaddress, datakey=data_new_key)
                itmk.isdatastream = True
                itmk.device = publishing_device
                itmk.setBackground(0, colgrey_key)
                itmk.datakey_address = itmk.redvypr_address
                # Check filter
                test_external_filter = False
                for f in self.external_filter_datastream:
                    logger.debug(
                        'Testing datastream: {} matches {}: {}'.format(f,
                                                                       itmk.datakey_address,
                                                                       f.matches(
                                                                           itmk.datakey_address)))
                    if f.matches(itmk.datakey_address):
                        test_external_filter = True
                        break
                # Test gui filter widget
                if self.filterWidget.filter_on:
                    test_filter_widget = self.filterWidget.filter_address.matches(
                        itmk.datakey_address)
                    logger.debug(
                        f'Testing (@tuple): {self.filterWidget.filter_address}.matches({itmk.datakey_address}): {test_filter_widget}')
                else:
                    test_filter_widget = True

                if test_external_filter and test_filter_widget:
                    parent_item.addChild(itmk)
                    for data_new_index, data_new_item in enumerate(data_new):
                        update_recursive(data_new_index, data_new_item, parent_item=itmk, datakey_construct=datakey_construct_new, expandlevel=expandlevel+1)

            elif isinstance(data_new, dict):
                print("Dict entry\n")
                print(f'Parameter:{data_new_key=}, {data_new=},type:{type(data_new)}')
                print(f'Datakey construct new:{datakey_construct_new}')
                print(f"Parent address:{parent_item.redvypr_address}")
                parent_address_datakey = parent_item.redvypr_address.datakey
                if parent_address_datakey:
                    if type(data_new_key) == int:
                        data_new_key = f'{parent_address_datakey}[{data_new_key}]'
                    else:
                        data_new_key = f'{parent_address_datakey}["{data_new_key}"]'

                itmk = QtWidgets.QTreeWidgetItem([data_new_key])
                itmk.redvypr_address = RedvyprAddress(devaddress, datakey=data_new_key)
                itmk.isdatastream = False
                itmk.device = publishing_device
                itmk.setBackground(0, colgrey)
                parent_item.addChild(itmk)
                for data_new_key in data_new.keys():
                    update_recursive(data_new_key, data_new[data_new_key], parent_item=itmk, datakey_construct=datakey_construct_new, expandlevel=expandlevel+1)

        if True:
            self.devicelist.clear()
            root = self.devicelist.invisibleRootItem()
            # self.devices_listDevices.addItem(str(device))
            publishing_devices = self.redvypr.get_device_objects(publishes=True, subscribes=False)
            font1 = QtGui.QFont('Arial')
            font1.setBold(True)
            font0 = QtGui.QFont('Arial')

            # Fill the qtreewidget
            #print('data provider',data_provider_all)
            if (publishing_devices is not None):
                for publishing_device in publishing_devices:
                    flag_datastreams = False
                    if publishing_device == self.device:
                        continue

                    #print('Device {}'.format(dev.name))
                    #print('Address', dev.address)
                    # Check for external filter
                    test_external_filter = False
                    for addr_include in self.external_filter_include:
                        test_external_filter = addr_include.matches(publishing_device.address)
                        logger.debug('Testing {} not in {}: {}'.format(publishing_device.address, addr_include, test_external_filter))
                        if test_external_filter:
                            break

                    if test_external_filter == False:
                        continue
                    # Check for filter from filter widget
                    if self.filterWidget.filter_on:
                        test_filter = not(self.filterWidget.filter_address).matches_filter(publishing_device.address)
                        test_filter_sub = True
                        if test_filter == True:
                            # Test all devices of publisher in brute force and check if one of them fits
                            devs_forwarded = publishing_device.get_device_info()
                            for devaddress in devs_forwarded:
                                datakey_dict = devs_forwarded[devaddress]['datakeys_expanded']
                                #print('Datakeys', datakey_dict)
                                devaddress_redvypr = RedvyprAddress(devaddress)
                                if self.filterWidget.filter_address.matches_filter(devaddress_redvypr):
                                    test_filter_sub = False
                                    #print('Filter match for ', devaddress_redvypr)
                                    continue

                        logger.debug('Testing {} not in {}: {}'.format(publishing_device.address, self.filterWidget.filter_address, test_filter))
                        if test_filter and test_filter_sub:
                            #print('No filter match for ', dev.address)
                            continue

                    # The device itself
                    itm = QtWidgets.QTreeWidgetItem([publishing_device.name])
                    itm.setBackground(0, colgrey)
                    itm.device = publishing_device
                    itm.redvypr_address = publishing_device.address
                    itm.datakey_address = RedvyprAddress(publishing_device.address)
                    itm.isdatastream = False
                    # Loop over all devices that have published through this device
                    if True:
                        devs_forwarded = publishing_device.get_device_info()
                        #print("\n\nDeviceinfo:\n{}".format(devs_forwarded))
                        devkeys = list(devs_forwarded.keys())
                        devkeys.sort()
                        for devaddress in devkeys:
                            datakey_dict = devs_forwarded[devaddress]['datakeys_expanded']
                            #print('Datakeys',datakey_dict)
                            devaddress_redvypr = RedvyprAddress(devaddress)
                            if self.filterWidget.filter_on:
                                if not(self.filterWidget.filter_address.matches(devaddress_redvypr)):
                                    print('No filter match for ', devaddress_redvypr)
                                    continue

                            #print('Addr', devaddress_redvypr, devaddress_redvypr.get_str())
                            devicestr = self.get_addressstr_for_item(devaddress_redvypr,self.addrentries_show_for_publishing_devices)
                            itmf = QtWidgets.QTreeWidgetItem([devicestr])
                            itmf.setBackground(0, colgrey)
                            itmf.device = publishing_device
                            itmf.addrentries = self.addrentries_show_for_publishing_devices
                            itmf.redvypr_address = devaddress_redvypr
                            itmf.datakey_address = devaddress_redvypr
                            itmf.address_forwarded = devaddress
                            itmf.isdatastream = False
                            # Check for time and potential length

                            if len(datakey_dict.keys())>0:  # Only add the device if it has some datakey to show
                                itm.addChild(itmf)
                                # Check if we have a list of time data
                                if (isinstance(datakey_dict["t"], list)):
                                    len_t = len(datakey_dict["t"])
                                else:
                                    len_t = None
                                for key in datakey_dict.keys():
                                    local_expansion_level = 9999
                                    if isinstance(datakey_dict[key], list):
                                        if len_t == len(datakey_dict["t"]) and (self.force_time_series_expansion == False):
                                            print(f"Setting local expansion level to 0 for {key}")
                                            local_expansion_level = 0

                                    data_new = datakey_dict[key]
                                    datakey_construct_new = ''
                                    update_recursive(key, data_new, parent_item=itmf, datakey_construct=datakey_construct_new, expandlevel=0, local_maxexpansionlevel=local_expansion_level)
                                    flag_datastreams = True

                    if flag_datastreams:  # If we have datastreams found, add the itm
                        root.addChild(itm)

            self.devicelist.expandAll()
            self.devicelist.resizeColumnToContents(0)

    def get_addressstr_for_item(self, raddr, addrentrylist):
        #self.addrtype_for_publishing_devices = '/{h}\n/{d}\n/{i}'  # The addrtype to show for publishin devices
        funcname = "get_addressstr_for_item()"
        #print(funcname)
        #print("Entries ...:",addrentrylist)
        devicestr = raddr.to_address_string(addrentrylist)
        #print("Devicestr", devicestr)
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
                itmk.isdatastream = True
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

                    itm.isdatastream = False
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
                            itmf.isdatastream = False

                            for key in datakey_dict.keys():
                                data_new = datakey_dict[key]
                                datakey_construct_new = ''
                                update_recursive(key, data_new, parent_item=itmf, datakey_construct=datakey_construct_new, expandlevel=0)

                    if flag_datastreams:  # If we have datastreams found, add the itm
                        root.addChild(itm)

            self.devicelist.expandAll()
            #self.devicelist.header().setStretchLastSection(True)
            self.devicelist.resizeColumnToContents(0)


# AddressTable
class RedvyprAddressTableModel(QtCore.QAbstractTableModel):
    """
    A high-performance, dynamic table model for RedvyprAddress tracks.
    """
    # Define all available column keys and how to extract them from the address object
    # Modify the lambda functions if your RedvyprAddress property names differ
    ALL_COLUMNS = {
        "datakey": lambda addr: addr.datakey,
        "host": lambda addr: getattr(addr, 'h', 'N/A'),
        "device": lambda addr: getattr(addr, 'd', 'N/A'),
        "publisher": lambda addr: getattr(addr, 'p', 'N/A'),
        "uuid": lambda addr: getattr(addr, 'u', 'N/A'),
        "packetid": lambda addr: getattr(addr, 'i', 'N/A'),
        "datatype": lambda addr, dtype: dtype.__name__ if dtype else 'NoneType'
    }

    def __init__(self, datastreams, visible_columns=None, parent=None):
        super().__init__(parent)
        # datastreams is expected to be a list of [RedvyprAddress, type]
        self._raw_data = datastreams

        # Default layout if nothing is passed
        if visible_columns is None:
            self._visible_columns = ["datakey", "host", "device", "publisher", "uuid",
                                     "packetid"]
        else:
            self._visible_columns = list(visible_columns)

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._raw_data)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self._visible_columns)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._raw_data)):
            return None

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            col_key = self._visible_columns[index.column()]
            address_obj, data_type = self._raw_data[index.row()]

            # Extract value safely using our schema mapping
            extractor = self.ALL_COLUMNS.get(col_key)
            if col_key == "datatype":
                return extractor(address_obj, data_type)
            return extractor(address_obj) if extractor else ""

        return None

    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if orientation == QtCore.Qt.Orientation.Horizontal and role == QtCore.Qt.ItemDataRole.DisplayRole:
            # Capitalize column headers cleanly
            return self._visible_columns[section].upper()
        return None

    # --- Modular Column Manipulation API ---

    def get_visible_columns(self):
        return self._visible_columns

    def set_visible_columns(self, column_keys):
        """Rebuilds the table layout dynamically."""
        self.beginResetModel()
        self._visible_columns = [k for k in column_keys if k in self.ALL_COLUMNS]
        self.endResetModel()


class RedvyprUniversalFilterProxyModel(QtCore.QSortFilterProxyModel):
    """
    A multi-column evaluation matrix proxy. Filters rows based on arbitrary
    column keys mapped to sets of whitelisted string expressions.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Structure: { 'column_key': { 'allowed_value_1', 'allowed_value_2' } }
        self._filter_matrix = {}

    def update_filter_matrix(self, filter_matrix):
        """Update active criteria configurations and run structural verification."""
        self._filter_matrix = filter_matrix
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        source_model = self.sourceModel()
        if not source_model:
            return True

        # If matrix is completely empty, pass everything
        if not self._filter_matrix:
            return True

        address_obj, data_type = source_model._raw_data[source_row]

        # Evaluate the row criteria across every registered column limit
        for col_key, allowed_values in self._filter_matrix.items():
            # NOTE: If the column key is in the matrix, it MUST match the allowed_values set.
            # An empty set means NO values are allowed for this column.

            extractor = RedvyprAddressTableModel.ALL_COLUMNS.get(col_key)
            if col_key == "datatype":
                cell_value = extractor(address_obj, data_type)
            else:
                cell_value = str(extractor(address_obj)) if extractor else ""

            # If the calculated cell value is missing from the active whitelist, discard the row
            if cell_value not in allowed_values:
                return False

        return True


class RedvyprAddressTable(QtWidgets.QWidget):
    """
    Main UI Component featuring an on-the-fly multi-column filtering engine
    and dynamic data expansion level adjustments.
    """

    def __init__(self, redvypr_obj, parent=None):
        super().__init__(parent)
        self.redvypr = redvypr_obj

        # State tracking: { 'col_key': { 'value_string': True/False } }
        self.filter_states = {}
        # Tracks live checkbox references currently rendered in the UI sidebar viewport
        self.active_rendered_checkboxes = {}

        self.init_ui()

        # Trigger initial data load via refresh_data directly
        self.refresh_data()

    def init_ui(self):
        main_layout = QtWidgets.QHBoxLayout(self)

        # --- UNIVERSAL FILTER PANEL (LEFT SIDEBAR) ---
        self.sidebar = QtWidgets.QGroupBox("Dynamic Filter Matrix")
        sidebar_layout = QtWidgets.QVBoxLayout(self.sidebar)

        # --- EXPANSION LEVEL CONTROL (NEW) ---
        expansion_layout = QtWidgets.QHBoxLayout()
        expansion_layout.addWidget(QtWidgets.QLabel("Expansion Level:"))

        self.expansion_spinbox = QtWidgets.QSpinBox()
        self.expansion_spinbox.setRange(0, 10)
        self.expansion_spinbox.setValue(
            1)  # Default starting level matching your prior True logic
        # Re-fetch structural tracking maps when user alters the spinbox integer value
        self.expansion_spinbox.valueChanged.connect(self.refresh_data)
        expansion_layout.addWidget(self.expansion_spinbox)

        sidebar_layout.addLayout(expansion_layout)

        # Separator line for clarity
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        sidebar_layout.addWidget(line)

        # Column Selection Dropdown Menu
        sidebar_layout.addWidget(QtWidgets.QLabel("Target Column:"))
        self.column_selector = QtWidgets.QComboBox()
        self.column_selector.currentTextChanged.connect(self.populate_value_checkboxes)
        sidebar_layout.addWidget(self.column_selector)

        # --- SELECT / DESELECT ALL BUTTONS ---
        button_layout = QtWidgets.QHBoxLayout()
        self.btn_select_all = QtWidgets.QPushButton("Select All")
        self.btn_deselect_all = QtWidgets.QPushButton("Deselect All")

        self.btn_select_all.clicked.connect(lambda: self.set_all_checkboxes_state(True))
        self.btn_deselect_all.clicked.connect(
            lambda: self.set_all_checkboxes_state(False))

        button_layout.addWidget(self.btn_select_all)
        button_layout.addWidget(self.btn_deselect_all)
        sidebar_layout.addLayout(button_layout)

        # Scroll Area holding the dynamic checkbox rows
        sidebar_layout.addWidget(QtWidgets.QLabel("Allowed Unique Values:"))
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QtWidgets.QWidget()
        self.checkbox_layout = QtWidgets.QVBoxLayout(self.scroll_widget)
        self.checkbox_layout.addStretch()  # Initial layout anchor
        self.scroll_area.setWidget(self.scroll_widget)
        sidebar_layout.addWidget(self.scroll_area)

        main_layout.addWidget(self.sidebar, stretch=1)

        # --- SYSTEM METADATA GRID (RIGHT VIEWPORT) ---
        self.table_view = QtWidgets.QTableView(self)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.horizontalHeader().setStretchLastSection(True)

        header = self.table_view.horizontalHeader()
        header.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_header_menu)

        main_layout.addWidget(self.table_view, stretch=3)

        # Bind proxy structures
        self.proxy_model = RedvyprUniversalFilterProxyModel(self)
        self.table_view.setModel(self.proxy_model)

    def refresh_data(self):
        """Fetches fresh data tracks using active SpinBox expansion parameters."""
        # Read the current dynamic depth value from our spinbox
        current_expansion_level = self.expansion_spinbox.value()

        # Pass the integer parameter straight down into the data subsystem mapping engine
        datastreams = self.redvypr.get_datastreams(expand=current_expansion_level,
                                                   return_type="address_type")

        current_columns = None
        if self.table_view.model() and self.table_view.model().sourceModel():
            current_columns = self.table_view.model().sourceModel().get_visible_columns()

        self.source_model = RedvyprAddressTableModel(datastreams,
                                                     visible_columns=current_columns)
        self.proxy_model.setSourceModel(self.source_model)
        self.table_view.resizeColumnsToContents()

        # Save previous column target token if it existed to avoid resets during runtime fetches
        previous_active_col = self.column_selector.currentText()

        # Build clean state maps out of the updated payload array
        self.build_filter_matrix_states(datastreams)

        # Block signal updates loop to prevent UI cascade spikes while rebuilding choices
        self.column_selector.blockSignals(True)
        self.column_selector.clear()
        self.column_selector.addItems(list(RedvyprAddressTableModel.ALL_COLUMNS.keys()))

        # Restore previous selection context safely if it still exists within current schema definitions
        if previous_active_col and previous_active_col in RedvyprAddressTableModel.ALL_COLUMNS:
            self.column_selector.setCurrentText(previous_active_col)
        self.column_selector.blockSignals(False)

        # Repopulate actual list entries for active visible frame boundaries
        self.populate_value_checkboxes(self.column_selector.currentText())

        # Sync active states to proxy
        self.apply_calculated_filters()

    def build_filter_matrix_states(self, datastreams):
        """Pre-calculates unique track attributes to build full filter matrix mappings."""
        self.filter_states = {col: {} for col in
                              RedvyprAddressTableModel.ALL_COLUMNS.keys()}

        for address_obj, data_type in datastreams:
            for col_key in self.filter_states.keys():
                extractor = RedvyprAddressTableModel.ALL_COLUMNS[col_key]
                if col_key == "datatype":
                    val = extractor(address_obj, data_type)
                else:
                    val = str(extractor(address_obj)) if extractor else ""

                # Track unique values, default to True (checked)
                self.filter_states[col_key][val] = True

    def populate_value_checkboxes(self, active_column):
        """Re-renders checkbox matrix arrays inside the viewport."""
        for cb in list(self.active_rendered_checkboxes.values()):
            self.checkbox_layout.removeWidget(cb)
            cb.setParent(None)
        self.active_rendered_checkboxes.clear()

        if not active_column or active_column not in self.filter_states:
            return

        column_value_map = self.filter_states[active_column]

        for val_str, checked_state in sorted(column_value_map.items()):
            cb = QtWidgets.QCheckBox(val_str)
            cb.setChecked(checked_state)

            cb.stateChanged.connect(
                lambda state, col=active_column, v=val_str: self.on_checkbox_toggled(
                    col, v, state))

            self.checkbox_layout.insertWidget(self.checkbox_layout.count() - 1, cb)
            self.active_rendered_checkboxes[val_str] = cb

    def set_all_checkboxes_state(self, checked_state):
        """Toggles all checkboxes for the currently active column."""
        active_column = self.column_selector.currentText()
        if not active_column or active_column not in self.filter_states:
            return

        for val_str in self.filter_states[active_column].keys():
            self.filter_states[active_column][val_str] = checked_state

        for cb in self.active_rendered_checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(checked_state)
            cb.blockSignals(False)

        self.apply_calculated_filters()

    def on_checkbox_toggled(self, col_key, value_str, check_state):
        """Updates internal status arrays when a viewport row element shifts."""
        is_checked = (check_state == QtCore.Qt.CheckState.Checked.value)
        self.filter_states[col_key][value_str] = is_checked
        self.apply_calculated_filters()

    def apply_calculated_filters(self):
        """Converts internal UI checkbox states into target sets for the filter proxy."""
        runtime_matrix = {}

        for col_key, value_map in self.filter_states.items():
            allowed = [val for val, checked in value_map.items() if checked]
            if len(allowed) < len(value_map):
                runtime_matrix[col_key] = set(allowed)

        self.proxy_model.update_filter_matrix(runtime_matrix)

    def show_header_menu(self, position):
        """Context menu on table headers to toggle column visibility."""
        menu = QtWidgets.QMenu(self)
        visible_cols = self.source_model.get_visible_columns()

        for col_key in RedvyprAddressTableModel.ALL_COLUMNS.keys():
            action = QtGui.QAction(col_key.upper(), menu, checkable=True)
            action.setChecked(col_key in visible_cols)
            action.triggered.connect(
                lambda checked, key=col_key: self.toggle_column(key, checked))
            menu.addAction(action)

        menu.exec_(self.table_view.horizontalHeader().mapToGlobal(position))

    def toggle_column(self, col_key, checked):
        current_cols = list(self.source_model.get_visible_columns())

        if checked and col_key not in current_cols:
            current_cols.append(col_key)
        elif not checked and col_key in current_cols:
            if len(current_cols) > 1:
                current_cols.remove(col_key)

        ordered_cols = [k for k in RedvyprAddressTableModel.ALL_COLUMNS.keys() if
                        k in current_cols]
        self.source_model.set_visible_columns(ordered_cols)
        self.table_view.resizeColumnsToContents()

#
#
# Tree model
#
#
class RedvyprTreeFilterProxyModel(QtCore.QSortFilterProxyModel):
    """
    Hochperformanter Matrix-Filter für QTreeWidgets.
    Nutzt eine Whitelist-Matrix pro Spalten-Key.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Struktur: { 'column_key_or_index': { 'allowed_val1', 'allowed_val2' } }
        self._filter_matrix = {}
        self.column_keys = []

    def update_filter_matrix(self, filter_matrix, column_keys):
        self._filter_matrix = filter_matrix
        self.column_keys = column_keys
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        source_model = self.sourceModel()
        if not source_model or not self._filter_matrix:
            return True

        # Index des aktuellen Elements holen
        index = source_model.index(source_row, 0, source_parent)
        item = source_model.itemFromIndex(index) if hasattr(source_model,
                                                            'itemFromIndex') else None

        # Falls direkt mit QTreeWidget gearbeitet wird, nutzen wir das Item-basierte Filtern:
        if not item:
            # Bei QTreeWidget greift filterAcceptsRow auf das interne Model zu.
            # Um es einfach zu halten, prüfen wir den Inhalt der Spalten:
            for col_idx, allowed_values in self._filter_matrix.items():
                col_index_in_tree = col_idx
                # Wert der Zelle auslesen
                cell_index = source_model.index(source_row, col_index_in_tree,
                                                source_parent)
                cell_value = source_model.data(cell_index,
                                               QtCore.Qt.ItemDataRole.DisplayRole)

                if cell_value not in allowed_values:
                    return False
            return True

        # Falls es sich um einen Parent-Knoten (Device) handelt, prüfen wir,
        # ob mindestens eines seiner Kinder den Filter erlaubt.
        if index.model().hasChildren(index):
            for i in range(index.model().rowCount(index)):
                if self.filterAcceptsRow(i, index):
                    return True
            return False

        # Validierung des echten Datastreams gegen die Matrix
        for col_key, allowed_values in self._filter_matrix.items():
            try:
                col_idx = self.column_keys.index(col_key)
                cell_index = source_model.index(source_row, col_idx, source_parent)
                cell_value = source_model.data(cell_index,
                                               QtCore.Qt.ItemDataRole.DisplayRole)
                if cell_value not in allowed_values:
                    return False
            except ValueError:
                continue

        return True



class RedvyprFilterDialog(QtWidgets.QDialog):
    """
    A standalone dialog window containing the dynamic Excel-like matrix filter interface.
    """

    def __init__(self, parent_widget):
        super().__init__(parent_widget)
        self.p = parent_widget  # Reference back to the main device tree widget
        self.setWindowTitle("Dynamic Filter Matrix")
        self.resize(320, 450)

        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Column Selection Dropdown
        layout.addWidget(QtWidgets.QLabel("Target Column:"))
        self.column_selector = QtWidgets.QComboBox()
        self.column_selector.addItems(self.p.COLUMNS)
        self.column_selector.currentTextChanged.connect(self.populate_value_checkboxes)
        layout.addWidget(self.column_selector)

        # Selection Utility Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_select_all = QtWidgets.QPushButton("Select All")
        self.btn_deselect_all = QtWidgets.QPushButton("Deselect All")
        self.btn_select_all.clicked.connect(lambda: self.set_all_checkboxes_state(True))
        self.btn_deselect_all.clicked.connect(
            lambda: self.set_all_checkboxes_state(False))
        btn_layout.addWidget(self.btn_select_all)
        btn_layout.addWidget(self.btn_deselect_all)
        layout.addLayout(btn_layout)

        # Scroll Area for dynamic unique value checkboxes
        layout.addWidget(QtWidgets.QLabel("Allowed Unique Values:"))
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QtWidgets.QWidget()
        self.checkbox_layout = QtWidgets.QVBoxLayout(self.scroll_widget)
        self.checkbox_layout.addStretch()  # Anchor layout items to the top
        self.scroll_area.setWidget(self.scroll_widget)
        layout.addWidget(self.scroll_area)

        # Close action dialog button
        self.close_button = QtWidgets.QPushButton("Apply & Close")
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.close_button)

        # Trigger initial checkbox populating matching parent state
        current_col = self.column_selector.currentText()
        self.populate_value_checkboxes(current_col)

    def populate_value_checkboxes(self, active_column):
        """Clears and re-renders the unique checkbox matrix rows inside the viewport."""
        for cb in list(self.p.active_rendered_checkboxes.values()):
            self.checkbox_layout.removeWidget(cb)
            cb.setParent(None)
        self.p.active_rendered_checkboxes.clear()

        if not active_column or active_column not in self.p.filter_states:
            return

        column_value_map = self.p.filter_states[active_column]
        for val_str, checked_state in sorted(column_value_map.items()):
            cb = QtWidgets.QCheckBox(val_str)
            cb.setChecked(checked_state)
            cb.stateChanged.connect(
                lambda state, col=active_column, v=val_str: self.p.on_checkbox_toggled(
                    col, v, state)
            )
            # Insert before the layout stretch anchor element
            self.checkbox_layout.insertWidget(self.checkbox_layout.count() - 1, cb)
            self.p.active_rendered_checkboxes[val_str] = cb

    def set_all_checkboxes_state(self, checked_state):
        """Batch overrides selection states across the active target filter matrix column."""
        active_column = self.column_selector.currentText()
        if not active_column or active_column not in self.p.filter_states:
            return

        for val_str in self.p.filter_states[active_column].keys():
            self.p.filter_states[active_column][val_str] = checked_state

        for cb in self.p.active_rendered_checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(checked_state)
            cb.blockSignals(False)

        self.p.apply_calculated_filters()


class RedvyprDeviceTreeWidget(QtWidgets.QWidget):
    """
    Component wrapping a multi-column tree view with dynamic,
    Excel-like column matrix filtering and hierarchy toggles.
    """
    # Emits the selected RedvyprAddress (or a list of addresses if multi_select=True)
    addressSelected = QtCore.pyqtSignal(object)

    # Defined column headers matching the data schema
    COLUMNS = ["Datastreams", "Host", "Device", "Publisher", "UUID", "Address",
               "Datatype"]

    def __init__(self, redvypr, parent=None, multi_select=False, visible_columns=None,
                 **kwargs):
        super().__init__(parent)
        self.redvypr = redvypr
        self.multi_select = multi_select

        # Configuration extraction with fallback defaults
        self.external_filter_include = [RedvyprAddress(f) for f in
                                        kwargs.get('filter_device', ["@"])]
        self.external_filter_datastream = [RedvyprAddress(f) for f in
                                           kwargs.get('filter_datastream', ["@"])]
        self.expandlevel = kwargs.get('expansion_level', 10)
        self.force_time_series_expansion = kwargs.get('force_time_series_expansion',
                                                      False)
        self.addrentries_show_for_publishing_devices = ['h', 'd', 'i']

        # Define default visible columns if none are explicitly provided
        if visible_columns is None:
            self.default_visible_columns = ["Datastreams", "Host", "Device",
                                            "Publisher", "Datatype"]
        else:
            self.default_visible_columns = list(visible_columns)

        # Matrix filter state tracking: { 'col_key': { 'value_string': True/False } }
        self.filter_states = {}
        self.active_rendered_checkboxes = {}

        self.init_ui()
        self.update_device_tree()

    def init_ui(self):
        # Main layout spanning across the entire widget viewport space
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Dropdown menu bar for alternative column visibility toggle
        self.menu_bar = QtWidgets.QMenuBar()
        self.view_menu = self.menu_bar.addMenu("Show / Hide Columns")
        main_layout.addWidget(self.menu_bar)

        # Top Control Bar for structural actions and opening filters
        control_bar_layout = QtWidgets.QHBoxLayout()
        self.filter_button = QtWidgets.QPushButton("Filter")
        self.filter_button.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_FileDialogContentsView))
        self.filter_button.clicked.connect(self._open_filter_dialog)
        control_bar_layout.addWidget(self.filter_button)
        control_bar_layout.addStretch()
        main_layout.addLayout(control_bar_layout)

        # Tree Widget Core Setup
        self.device_tree = QtWidgets.QTreeWidget()
        self.device_tree.setColumnCount(len(self.COLUMNS))
        self.device_tree.setHeaderLabels(self.COLUMNS)

        # Configure Header View interactions
        header = self.device_tree.header()
        header.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_context_menu)
        header.setSectionsMovable(True)

        # Enable default column sorting behavior
        self.device_tree.setSortingEnabled(True)
        self.device_tree.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)

        if self.multi_select:
            self.device_tree.setSelectionMode(
                QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        else:
            self.device_tree.itemClicked.connect(self._on_item_clicked)

        # Context menu exclusively dedicated to row content manipulation
        self.device_tree.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.device_tree.customContextMenuRequested.connect(
            self._show_item_context_menu)
        main_layout.addWidget(self.device_tree, stretch=1)

        # --- BOTTOM BAR: DESIGN CHANGED TO HOUSE TREE LAYOUT OPTIONS ---
        options_layout = QtWidgets.QHBoxLayout()
        options_layout.addWidget(QtWidgets.QLabel("Tree Layout Options:"))

        self.allow_all_checkbox = QtWidgets.QCheckBox("Allow device selection")
        self.allow_all_checkbox.setChecked(False)
        options_layout.addWidget(self.allow_all_checkbox)

        self.show_devices_checkbox = QtWidgets.QCheckBox("Show devices hierarchy")
        self.show_devices_checkbox.setChecked(True)
        self.show_devices_checkbox.toggled.connect(self._on_show_devices_toggled)
        options_layout.addWidget(self.show_devices_checkbox)
        options_layout.addStretch()

        main_layout.addLayout(options_layout)

        # Multi-Select Execution Actions Layout (Appears beneath options if multi_select=True)
        if self.multi_select:
            self.button_layout = QtWidgets.QHBoxLayout()
            self.apply_button = QtWidgets.QPushButton("Apply Selection")
            self.apply_button.clicked.connect(self._on_apply_clicked)
            self.unselect_button = QtWidgets.QPushButton("Unselect All")
            self.unselect_button.clicked.connect(self._on_unselect_clicked)
            self.button_layout.addWidget(self.apply_button)
            self.button_layout.addWidget(self.unselect_button)
            self.button_layout.addStretch()
            main_layout.addLayout(self.button_layout)

        # Apply the initial column visibility based on the init parameter
        for i, col_name in enumerate(self.COLUMNS):
            if i == 0:
                continue  # Always keep the primary "Datastreams" column visible
            should_hide = col_name not in self.default_visible_columns
            self.device_tree.setColumnHidden(i, should_hide)

        self._rebuild_view_menu()

    def _open_filter_dialog(self):
        """Spawns the dynamic matrix column configuration dialog window context safely."""
        dialog = RedvyprFilterDialog(self)
        dialog.exec()

    def build_filter_matrix_states(self):
        """Analyzes the current tree structure to pre-calculate unique metadata filter whitelists."""
        old_states = self.filter_states
        self.filter_states = {col: {} for col in self.COLUMNS}

        def collect_values(item):
            for col_idx in range(len(self.COLUMNS)):
                col_name = self.COLUMNS[col_idx]
                val = item.text(col_idx) or ""
                # Retain previous check configurations seamlessly if applicable
                if old_states and col_name in old_states and val in old_states[
                    col_name]:
                    self.filter_states[col_name][val] = old_states[col_name][val]
                else:
                    self.filter_states[col_name][val] = True

            for i in range(item.childCount()):
                collect_values(item.child(i))

        root = self.device_tree.invisibleRootItem()
        for i in range(root.childCount()):
            collect_values(root.child(i))

    def on_checkbox_toggled(self, col_key, value_str, check_state):
        """Updates internal status matrices upon checkbox interaction."""
        is_checked = (check_state == 2 or check_state == QtCore.Qt.CheckState.Checked)
        self.filter_states[col_key][value_str] = is_checked
        self.apply_calculated_filters()

    def apply_calculated_filters(self):
        """Evaluates tree item visibility against active matrix constraints via setHidden."""

        def evaluate_item_visibility(item):
            row_matches_filter = True
            for col_idx, col_name in enumerate(self.COLUMNS):
                val = item.text(col_idx) or ""
                allowed_map = self.filter_states.get(col_name, {})
                if allowed_map and not allowed_map.get(val, True):
                    row_matches_filter = False
                    break

            any_child_visible = False
            for i in range(item.childCount()):
                child_visible = evaluate_item_visibility(item.child(i))
                if child_visible:
                    any_child_visible = True

            final_visibility = row_matches_filter or any_child_visible
            item.setHidden(not final_visibility)
            return final_visibility

        root = self.device_tree.invisibleRootItem()
        for i in range(root.childCount()):
            evaluate_item_visibility(root.child(i))

    def _rebuild_view_menu(self):
        """Dynamically recreates the menu items for the main top drop-down menu bar."""
        self.view_menu.clear()
        header = self.device_tree.header()

        for i, col_name in enumerate(self.COLUMNS):
            if i == 0:
                continue
            action = QtGui.QAction(col_name, self.view_menu, checkable=True)
            action.setChecked(not header.isSectionHidden(i))
            action.setData(i)
            action.triggered.connect(self._toggle_column_visibility)
            self.view_menu.addAction(action)

    def _show_header_context_menu(self, pos: QtCore.QPoint):
        """Generates the interactive visibility menu on header view right click."""
        header = self.device_tree.header()
        menu = QtWidgets.QMenu(self)

        for i, col_name in enumerate(self.COLUMNS):
            if i == 0:
                continue
            action = QtGui.QAction(col_name, menu, checkable=True)
            action.setChecked(not header.isSectionHidden(i))
            action.setData(i)
            action.triggered.connect(self._toggle_column_visibility)
            menu.addAction(action)

        menu.exec_(header.mapToGlobal(pos))

    def _toggle_column_visibility(self):
        """Applies layout visibility adjustments to the target tree view column index."""
        action = self.sender()
        if action:
            col_index = action.data()
            is_visible = action.isChecked()

            self.device_tree.setColumnHidden(col_index, not is_visible)
            if is_visible:
                self.device_tree.resizeColumnToContents(col_index)
            self._rebuild_view_menu()

    def _is_item_selectable(self, item):
        is_datastream = getattr(item, 'isdatastream', False)
        return is_datastream or (
                    self.allow_all_checkbox.isChecked() and self.show_devices_checkbox.isChecked())

    def _on_show_devices_toggled(self):
        show_devices = self.show_devices_checkbox.isChecked()
        if not show_devices:
            self.allow_all_checkbox.setChecked(False)
            self.allow_all_checkbox.setEnabled(False)
        else:
            self.allow_all_checkbox.setEnabled(True)
        self.update_device_tree()

    def _on_item_clicked(self, item):
        if not self._is_item_selectable(item):
            return
        raddress = getattr(item, 'datakey_address',
                           getattr(item, 'redvypr_address', None))
        if raddress:
            self.addressSelected.emit(raddress)

    def _on_apply_clicked(self):
        selected_items = self.device_tree.selectedItems()
        selected_addresses = []
        for item in selected_items:
            if self._is_item_selectable(item):
                raddress = getattr(item, 'datakey_address',
                                   getattr(item, 'redvypr_address', None))
                if raddress and raddress not in selected_addresses:
                    selected_addresses.append(raddress)
        self.addressSelected.emit(selected_addresses)

    def _on_unselect_clicked(self):
        self.device_tree.clearSelection()

    def _show_item_context_menu(self, pos: QtCore.QPoint):
        """Context menu specifically built for individual cell item configuration parameters."""
        item = self.device_tree.itemAt(pos)
        if not item:
            return

        addr_entries = getattr(item, 'addrentries',
                               self.addrentries_show_for_publishing_devices)
        menu = QtWidgets.QMenu(self.device_tree)
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(container)
        addr_tmp = RedvyprAddress()
        all_checks = {}

        for key, short_form in addr_tmp.REV_LONGFORM_TO_SHORT_MAP_DATAKEY.items():
            checkbox = QtWidgets.QCheckBox(key)
            checkbox.__item = item
            if short_form in addr_entries:
                checkbox.setChecked(True)
            checkbox.stateChanged.connect(self._update_menu_item)
            container_layout.addWidget(checkbox)
            all_checks[short_form] = checkbox

        item.all_check = all_checks
        action = QtWidgets.QWidgetAction(self)
        action.setDefaultWidget(container)
        menu.addAction(action)
        menu.exec_(self.device_tree.viewport().mapToGlobal(pos))

    def _update_menu_item(self):
        sender = self.sender()
        item = getattr(sender, '__item', None)
        if not item:
            return
        entries = [entry for entry, cb in item.all_check.items() if cb.isChecked()]
        item.addrentries = entries
        dev_str = self.get_address_string_for_item(item.redvypr_address, entries)
        item.setText(0, dev_str)

    def get_address_string_for_item(self, raddr, addr_entry_list):
        return raddr.to_address_string(addr_entry_list)

    def update_device_tree(self):
        """Builds structural schema data components directly into tree layout coordinates."""
        logger.debug("Updating device tree elements.")
        col_grey = QtGui.QColor(210, 210, 210)
        col_grey_key = QtGui.QColor(240, 240, 240)

        show_devices = self.show_devices_checkbox.isChecked()
        root = self.device_tree.invisibleRootItem()

        self.device_tree.setSortingEnabled(False)
        self.device_tree.clear()

        def fill_item_columns(tree_item, raddress, datatype_str=""):
            if raddress:
                tree_item.setText(1, str(getattr(raddress, 'h', 'N/A')))
                tree_item.setText(2, str(getattr(raddress, 'd', 'N/A')))
                tree_item.setText(3, str(getattr(raddress, 'p', 'N/A')))
                tree_item.setText(4, str(getattr(raddress, 'u', 'N/A')))
                tree_item.setText(5, raddress.to_address_string() if hasattr(raddress,
                                                                             'to_address_string') else str(
                    raddress))
            tree_item.setText(6, str(datatype_str))

        def update_recursive(data_new_key, data_new, parent_item, datakey_construct,
                             expand_level, local_max_expansion=9999):
            datakey_construct_new = str(data_new_key)
            if len(datakey_construct_new) == 0:
                return

            if isinstance(data_new, tuple) or (expand_level >= self.expandlevel) or (
                    expand_level >= local_max_expansion):
                addr_str_expanded = data_new[0] if not (
                    ((expand_level >= self.expandlevel) or (
                            expand_level >= local_max_expansion))) else data_new_key

                itm_k = QtWidgets.QTreeWidgetItem([addr_str_expanded])
                itm_k.isdatastream = True
                itm_k.device = publishing_device
                itm_k.devaddress = devaddress
                itm_k.datakey_address = RedvyprAddress(devaddress,
                                                       datakey=addr_str_expanded)

                dtype = str(data_new[1].__name__) if isinstance(data_new,
                                                                tuple) and len(
                    data_new) > 1 and hasattr(data_new[1], '__name__') else type(
                    data_new).__name__
                fill_item_columns(itm_k, itm_k.datakey_address, dtype)

                if show_devices:
                    parent_item.addChild(itm_k)
                else:
                    root.addChild(itm_k)

            elif isinstance(data_new, list):
                parent_address_datakey = parent_item.redvypr_address.datakey
                if parent_address_datakey:
                    data_new_key = f'{parent_address_datakey}[{data_new_key}]' if isinstance(
                        data_new_key,
                        int) else f'{parent_address_datakey}["{data_new_key}"]'

                itm_k = QtWidgets.QTreeWidgetItem([data_new_key])
                itm_k.redvypr_address = RedvyprAddress(devaddress, datakey=data_new_key)
                itm_k.isdatastream = True
                itm_k.device = publishing_device
                itm_k.setBackground(0, col_grey_key)
                itm_k.datakey_address = itm_k.redvypr_address

                fill_item_columns(itm_k, itm_k.datakey_address, "list")

                if show_devices:
                    parent_item.addChild(itm_k)
                else:
                    root.addChild(itm_k)

                for idx, item_val in enumerate(data_new):
                    update_recursive(idx, item_val, parent_item=itm_k,
                                     datakey_construct=datakey_construct_new,
                                     expand_level=expand_level + 1)

            elif isinstance(data_new, dict):
                if not show_devices:
                    for k in data_new.keys():
                        update_recursive(k, data_new[k], parent_item=parent_item,
                                         datakey_construct=datakey_construct_new,
                                         expand_level=expand_level + 1)
                    return

                parent_address_datakey = parent_item.redvypr_address.datakey
                if parent_address_datakey:
                    data_new_key = f'{parent_address_datakey}[{data_new_key}]' if isinstance(
                        data_new_key,
                        int) else f'{parent_address_datakey}["{data_new_key}"]'

                itm_k = QtWidgets.QTreeWidgetItem([data_new_key])
                itm_k.redvypr_address = RedvyprAddress(devaddress, datakey=data_new_key)
                itm_k.isdatastream = False
                itm_k.device = publishing_device
                itm_k.setBackground(0, col_grey)

                fill_item_columns(itm_k, itm_k.redvypr_address, "dict")
                parent_item.addChild(itm_k)

                for k in data_new.keys():
                    update_recursive(k, data_new[k], parent_item=itm_k,
                                     datakey_construct=datakey_construct_new,
                                     expand_level=expand_level + 1)

        publishing_devices = self.redvypr.get_device_objects(publishes=True,
                                                             subscribes=False)

        if publishing_devices is not None:
            for publishing_device in publishing_devices:
                flag_datastreams = False

                test_ext_filter = any(
                    addr_inc.matches(publishing_device.address) for addr_inc in
                    self.external_filter_include)
                if not test_ext_filter:
                    continue

                itm = QtWidgets.QTreeWidgetItem([publishing_device.name])
                itm.setBackground(0, col_grey)
                itm.device = publishing_device
                itm.redvypr_address = publishing_device.address
                itm.datakey_address = RedvyprAddress(publishing_device.address)
                itm.isdatastream = False

                fill_item_columns(itm, itm.redvypr_address, "dict")

                devs_forwarded = publishing_device.get_device_info()
                dev_keys = sorted(list(devs_forwarded.keys()))

                for devaddress in dev_keys:
                    datakey_dict = devs_forwarded[devaddress]['datakeys_expanded']
                    devaddress_redvypr = RedvyprAddress(devaddress)

                    device_str = self.get_address_string_for_item(devaddress_redvypr,
                                                                  self.addrentries_show_for_publishing_devices)
                    itm_f = QtWidgets.QTreeWidgetItem([device_str])
                    itm_f.setBackground(0, col_grey)
                    itm_f.device = publishing_device
                    itm_f.addrentries = self.addrentries_show_for_publishing_devices
                    itm_f.redvypr_address = devaddress_redvypr
                    itm_f.datakey_address = devaddress_redvypr
                    itm_f.address_forwarded = devaddress
                    itm_f.isdatastream = False

                    fill_item_columns(itm_f, itm_f.redvypr_address, "dict")

                    if len(datakey_dict.keys()) > 0:
                        if show_devices:
                            itm.addChild(itm_f)

                        len_t = len(datakey_dict["t"]) if isinstance(
                            datakey_dict.get("t"), list) else None

                        for key in datakey_dict.keys():
                            local_expansion = 9999
                            if isinstance(datakey_dict[key], list) and len_t == len(
                                    datakey_dict[
                                        "t"]) and not self.force_time_series_expansion:
                                local_expansion = 0

                            current_parent = itm_f if show_devices else itm
                            update_recursive(key, datakey_dict[key],
                                             parent_item=current_parent,
                                             datakey_construct='', expand_level=0,
                                             local_max_expansion=local_expansion)
                            flag_datastreams = True

                if flag_datastreams and show_devices:
                    root.addChild(itm)

        self.device_tree.setSortingEnabled(True)
        self.device_tree.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)
        self.device_tree.expandAll()

        self.build_filter_matrix_states()

        for i in range(len(self.COLUMNS)):
            if not self.device_tree.isColumnHidden(i):
                self.device_tree.resizeColumnToContents(i)

    def get_all_items(self):
        items = []

        def traverse(item):
            items.append(item)
            for i in range(item.childCount()):
                traverse(item.child(i))

        for i in range(self.device_tree.topLevelItemCount()):
            traverse(self.device_tree.topLevelItem(i))
        return items



class RedvyprAddressEditWrapper(QtWidgets.QWidget):
    """
    Component wrapping the address input and editing functionality.
    """
    addressApplied = QtCore.pyqtSignal(dict)  # Notifies when the apply/done button is clicked

    def __init__(self, datastream_string=None, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.address_edit = RedvyprAddressEditWidget(datastream_string)
        self.address_edit.address_finished.connect(self._on_address_finished)
        layout.addWidget(self.address_edit)

    def set_address(self, address):
        self.address_edit.setAddress(address)

    def _on_address_finished(self, address_dict):
        # Package data cleanly
        signal_data = {
            'datastream_str': address_dict['address_str'],
            'datastream_address': address_dict['address'],
            'address_format': address_dict['address_format']
        }
        self.addressApplied.emit(signal_data)


class RedvyprAddressWidget(QtWidgets.QWidget):
    """
    Main entry widget combining the device navigation (Tree)
    and the detailed address data entry (Edit view).
    """
    apply = QtCore.pyqtSignal(dict)  # Signal notifying if the Apply button was clicked
    datakey_name_changed = QtCore.pyqtSignal(
        str)  # Signal notifying if the datakey has changed

    def __init__(self, redvypr, device=None, device_highlight=None, datakey=None,
                 deviceonly=False, subscribed_only=True, datastreamstring=None,
                 closeAfterApply=True, window_icon_file=None, **kwargs):
        super().__init__()

        # Core property assignments
        logger.setLevel(logging.DEBUG)
        if window_icon_file:
            self.setWindowIcon(QtGui.QIcon(window_icon_file))

        self.redvypr = redvypr
        self.close_after_apply = closeAfterApply
        self.device = device
        self.device_highlight = device_highlight if device_highlight is not None else 'Na'
        self.device_only = deviceonly

        # Resolve device name labels
        try:
            self.device_name = device.name
        except AttributeError:
            self.device_name = device if device is not None else ''

        # Layout Initialization
        self.main_layout = QtWidgets.QGridLayout(self)

        if self.device_name:
            self.device_name_label = QtWidgets.QLabel(f'Device: {self.device_name}')
            self.main_layout.addWidget(self.device_name_label, 0, 0, 1, 2)

        # 1. Component left: Build the Tree component
        self.navigation_component = RedvyprDeviceTreeWidget(
            redvypr=self.redvypr,
            **kwargs
        )
        self.navigation_component.addressSelected.connect(
            self._on_address_selected_from_nav)

        # 2. Component right: Build the Edit component
        self.edit_component = RedvyprAddressEditWrapper(
            datastream_string=datastreamstring)
        self.edit_component.addressApplied.connect(self._on_address_applied)

        # Structure inside main view layout
        # (Row 1 Column 0 for Nav, Row 1 Column 1 for Edit View)
        self.main_layout.addWidget(self.navigation_component, 1, 0)
        self.main_layout.addWidget(self.edit_component, 1, 1)

    def _on_address_selected_from_nav(self, raddress):
        """Triggered when tree item is clicked: forwards to the edit widget"""
        logger.debug(f"Setting input address view to: {raddress}")
        self.edit_component.set_address(raddress)

    def _on_address_applied(self, signal_dict_new):
        """Triggered when user hits save/apply on the input fields"""
        self.redvypr_address = signal_dict_new['datastream_address']
        self.apply.emit(signal_dict_new)

        if self.close_after_apply:
            self.close()

class RedvyprMultipleAddressEditWidget(QtWidgets.QWidget):
    addressesApplied = QtCore.pyqtSignal(dict)
    def __init__(
            self,
            address_names=None,
            parent=None):
        super().__init__(parent)
        self.address_names = address_names
        self.addresses_chosen = []
        self.main_layout = QtWidgets.QVBoxLayout(self)
        #
        # Address format selection
        #
        self.addrentries_for_str_format = ['h', 'd', 'i', 'k']
        self.str_format_checkboxes = {}
        format_widget = QtWidgets.QGroupBox("Address format")
        format_layout = QtWidgets.QHBoxLayout(format_widget)
        atmp = RedvyprAddress()
        for long_name in atmp.LONGFORM_TO_SHORT_MAP_DATAKEY.keys():
            short_name = atmp.LONGFORM_TO_SHORT_MAP_DATAKEY[long_name]
            cb = QtWidgets.QCheckBox(long_name)
            if short_name in self.addrentries_for_str_format:
                cb.setChecked(True)

            cb.stateChanged.connect(self.update_table)
            self.str_format_checkboxes[short_name] = cb
            format_layout.addWidget(cb)
        format_layout.addStretch()
        self.main_layout.addWidget(format_widget)
        #
        # Table
        #
        self.datastreamtable = QtWidgets.QTableWidget()
        self.datastreamtable.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.datastreamtable.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.main_layout.addWidget(self.datastreamtable)
        #
        # Buttons
        #
        button_layout = QtWidgets.QHBoxLayout()
        self.button_remove = QtWidgets.QPushButton("Remove")
        self.button_remove_all = QtWidgets.QPushButton("Remove all")
        self.button_apply = QtWidgets.QPushButton("Apply")
        button_layout.addWidget(self.button_remove)
        button_layout.addWidget(self.button_remove_all)
        button_layout.addStretch()
        button_layout.addWidget(self.button_apply)
        self.main_layout.addLayout(button_layout)
        self.button_remove.clicked.connect(self.remove_selected)
        self.button_remove_all.clicked.connect(self.clear_addresses)
        self.button_apply.clicked.connect(self.apply_clicked)
        #
        # Named mode initialization
        #
        if self.address_names is not None:
            for _, addr in self.address_names.items():
                try:
                    self.addresses_chosen.append(
                        RedvyprAddress(addr)
                    )
                except Exception:
                    self.addresses_chosen.append(None)
        self.update_table()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def selected_address_entries(self):
        entries = []
        for entry, checkbox in self.str_format_checkboxes.items():
            if checkbox.isChecked():
                entries.append(entry)
        return entries

    def _address_to_string(self, raddress):
        if raddress is None:
            return ""

        entries = self.selected_address_entries()
        #
        # Replace by your existing implementation if needed
        #
        try:
            return raddress.to_address_string(entries)
        except Exception:
            return str(raddress)

    # ------------------------------------------------------------------
    # Address management
    # ------------------------------------------------------------------
    def add_address(self, raddress, update_table=False):
        if raddress is None:
            return
        #
        # Append mode
        #
        if self.address_names is None:
            if raddress not in self.addresses_chosen:
                self.addresses_chosen.append(raddress)
        #
        # Named mode
        #
        else:
            for i, current in enumerate(self.addresses_chosen):
                if current is None:
                    self.addresses_chosen[i] = raddress
                    key = list(self.address_names.keys())[i]
                    self.address_names[key] = self._address_to_string(
                        raddress
                    )

                    break
        self.update_table()

    def add_addresses(self, addresses):
        for addr in addresses:
            self.add_address(addr, update_table=False)

        self.update_table()
    def set_address_for_slot(self, index, raddress):
        if self.address_names is None:
            raise RuntimeError(
                "set_address_for_slot only available in named mode"
            )
        if index >= len(self.addresses_chosen):
            return
        self.addresses_chosen[index] = raddress
        key = list(self.address_names.keys())[index]
        self.address_names[key] = self._address_to_string(raddress)
        self.update_table()
    def remove_selected(self):
        rows = sorted(
            {index.row()
             for index in self.datastreamtable.selectedIndexes()},
            reverse=True
        )
        if self.address_names is None:
            for row in rows:
                if row < len(self.addresses_chosen):
                    self.addresses_chosen.pop(row)
        else:
            for row in rows:
                if row < len(self.addresses_chosen):
                    self.addresses_chosen[row] = None
                    key = list(self.address_names.keys())[row]
                    self.address_names[key] = ""
        self.update_table()

    def clear_addresses(self):
        if self.address_names is None:
            self.addresses_chosen.clear()
        else:
            self.addresses_chosen = [
                None for _ in self.address_names
            ]
            for key in self.address_names:
                self.address_names[key] = ""
        self.update_table()

    # ------------------------------------------------------------------
    # Table update
    # ------------------------------------------------------------------
    def update_table(self):
        named_mode = self.address_names is not None
        if named_mode:
            self.datastreamtable.setColumnCount(2)
            self.datastreamtable.setHorizontalHeaderLabels(
                ["Name", "Address"]
            )
        else:
            self.datastreamtable.setColumnCount(1)
            self.datastreamtable.setHorizontalHeaderLabels(
                ["Address"]
            )
        self.datastreamtable.setRowCount(
            len(self.addresses_chosen)
        )
        for row, addr in enumerate(self.addresses_chosen):
            #
            # Name column
            #
            if named_mode:
                name = list(self.address_names.keys())[row]
                self.datastreamtable.setItem(
                    row,
                    0,
                    QtWidgets.QTableWidgetItem(name)
                )
            #
            # Address column
            #
            text = self._address_to_string(addr)
            column = 1 if named_mode else 0
            item = QtWidgets.QTableWidgetItem(text)
            item.redvypr_address = addr
            self.datastreamtable.setItem(
                row,
                column,
                item
            )
        header = self.datastreamtable.horizontalHeader()
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        header.setStretchLastSection(True)
        self.datastreamtable.resizeRowsToContents()

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def apply_clicked(self):
        addresses = [
            addr
            for addr in self.addresses_chosen
            if addr is not None
        ]

        address_strings = [
            self._address_to_string(addr)
            for addr in addresses
        ]
        signal_dict = {
            "addresses": addresses,
            "datastreams_address": addresses,
            "datastreams_str": address_strings,
        }
        if self.address_names is not None:
            signal_dict["addresses_named"] = (
                self.address_names
            )
        self.addressesApplied.emit(signal_dict)



class RedvyprMultipleAddressesWidget(QtWidgets.QWidget):
    apply = QtCore.pyqtSignal(dict)
    def __init__(
            self,
            redvypr,
            address_names=None,
            window_icon_file=None,
            parent=None,
            **tree_kwargs):

        super().__init__(parent)

        if window_icon_file:
            from PyQt6.QtGui import QIcon
            self.setWindowIcon(QIcon(window_icon_file))
        self.main_layout = QtWidgets.QGridLayout(self)
        #
        # Left side
        #
        self.navigation_component = RedvyprDeviceTreeWidget(
            redvypr=redvypr,
            multi_select=True,
            **tree_kwargs
        )
        #
        # Right side
        #
        self.edit_component = (
            RedvyprMultipleAddressEditWidget(
                address_names=address_names
            )
        )
        self.main_layout.addWidget(
            self.navigation_component,
            0,
            0
        )
        self.main_layout.addWidget(
            self.edit_component,
            0,
            1
        )
        #
        # Signal connections
        #
        self.navigation_component.addressSelected.connect(
            self._address_selected
        )
        self.edit_component.addressesApplied.connect(
            self._apply_clicked
        )
    def _address_selected(self, raddresses):
        self.edit_component.add_addresses(raddresses)
    def _apply_clicked(self, signal_dict):
        self.apply.emit(signal_dict)



class RedvyprMultipleAddressesWidget_legacy(RedvyprAddressWidget):
    """ Widget that lets the user choose several datastreams
    """

    def __init__(self, *args, address_names=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.address_names = address_names
        # Add select all, deselect all menu
        self.devicelist.customContextMenuRequested.disconnect()
        self.devicelist.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        if self.address_names is None:
            self.devicelist.customContextMenuRequested.connect(
                self.show_device_context_menu)
        else:
            self.devicelist.customContextMenuRequested.connect(
                self.show_device_context_menu_name)
        self.addrentries_for_str_format = ['h', 'd', 'i', 'k']
        if self.address_names is None:
            self.devicelist.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        else:
            self.devicelist.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
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
        if self.address_names is None:  # Name mode, do not add remove buttons
            self.layout.addWidget(self.button_add, 1, 0)
            self.layout.addWidget(self.button_add_all, 2, 0)
            self.layout.addWidget(self.button_add_manual, 3, 0)
            self.layout.addWidget(self.button_rem, 1, 2)
            self.layout.addWidget(self.button_rem_all, 2, 2)

        self.layout.addWidget(self.apply_button,3,0,1,-1)
        self.addresses_chosen = []
        if self.address_names is not None:
            for aname,aaddr in self.address_names.items():
                self.addresses_chosen.append(RedvyprAddress(aaddr))
        self.update_datastreamtable()

    def show_device_context_menu_name(self, position):
        """ Creates a context menu to assign selected data to specific named slots """
        if not self.address_names:
            return

        menu = QtWidgets.QMenu(self)
        icon_assign = qtawesome.icon('ei.hand-right')

        # Holen der selektierten Items aus der Geräteliste
        selected_items = self.devicelist.selectedItems()
        if not selected_items:
            return

        # Wir nehmen das erste selektierte Item für die Zuweisung
        source_item = selected_items[0]

        # Dynamische Menüeinträge für jeden Namen in address_names
        for i, name in enumerate(self.address_names.keys()):
            action = menu.addAction(icon_assign, f'Assign to "{name}"')
            # Wir nutzen einen Lambda-Capture (idx=i), um den Index zu speichern
            action.triggered.connect(
                lambda checked, idx=i: self.assign_to_slot(idx, source_item))

        menu.exec_(self.devicelist.viewport().mapToGlobal(position))

    def assign_to_slot(self, index, item):
        """ Assigns a specific data address to a fixed slot in the list """
        keys = list(self.address_names.keys())
        try:
            raddress = getattr(item, 'datakey_address',
                               getattr(item, 'redvypr_address', None))
            if raddress:

                # Da wir im Name-Modus sind, ist self.addresses_chosen vorbefüllt
                # Wir ersetzen den Eintrag am spezifischen Index
                if index < len(self.addresses_chosen):
                    target_name = keys[index]  # Get the name for the dictionary
                    entries = [entry for entry, check in self.str_format_checkboxes.items() if check.isChecked()]
                    new_addr_str = self.get_addressstr_for_item(raddress, entries)
                    self.address_names[target_name] = new_addr_str
                    self.addresses_chosen[index] = raddress
                    logger.info(f"Assigned {raddress} to slot {index}")
                    self.update_datastreamtable()
        except Exception as e:
            logger.error(f"Error assigning to slot: {e}")

    def show_device_context_menu(self, position):
        """ Creates and displays a context menu for the device list """
        menu = QtWidgets.QMenu(self)

        # Reuse your existing icons
        icon_add = qtawesome.icon('ei.caret-right')

        # Create actions
        action_add = menu.addAction(icon_add, "Add selected")
        action_add_all = menu.addAction(icon_add, "Add all items")
        menu.addSeparator()
        action_select_all = menu.addAction("Select all (Ctrl+A)")
        action_deselect_all = menu.addAction("Deselect all (Esc)")

        # Display the menu at the cursor position
        # mapToGlobal converts widget coordinates to screen coordinates
        action = menu.exec_(self.devicelist.viewport().mapToGlobal(position))

        # Handle the selected action
        if action == action_add:
            self.add_datastreams_clicked()
        elif action == action_add_all:
            self.add_all_datastreams()
        elif action == action_select_all:
            self.devicelist.selectAll()
        elif action == action_deselect_all:
            self.devicelist.clearSelection()

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
            addrstr = self.get_addressstr_for_item(raddr, entries)
            addresses_choosen.append(RedvyprAddress(addrstr))
            addresses_str_choosen.append(addrstr)

        # Create a signal dict, with a format similar to the dict returned by the "apply" signal of the datastreamWidget
        signal_dict = {'addresses':addresses_choosen,'datastreams_address':addresses_choosen,'datastreams_str':addresses_str_choosen}
        if self.address_names is not None: # Add the named addresses
            signal_dict['addresses_named'] = self.address_names



        #print('Signal dict',signal_dict)
        self.apply.emit(signal_dict)
        if self.closeAfterApply:
            self.close()

    def update_datastreamtable(self):
        if self.address_names is None:
            icol_datastream = 0
            numcol = 1
            colheader = ['Redvypr Address']
        else:
            icol_datastream = 1
            icol_name = 0
            numcol = 2
            colheader = ['Name','Redvypr Address']

        entries = []
        for entry in self.str_format_checkboxes:
            check = self.str_format_checkboxes[entry]
            if check.isChecked():
                entries.append(entry)

        self.datastreamtable.clear()
        nrows = len(self.addresses_chosen)
        self.datastreamtable.setRowCount(nrows)
        self.datastreamtable.setColumnCount(numcol)
        for irow, raddr in enumerate(self.addresses_chosen):
            addrstr = self.get_addressstr_for_item(raddr, entries)
            item = QtWidgets.QTableWidgetItem(addrstr)
            #item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            item.datakey_address = raddr
            self.datastreamtable.setItem(irow,icol_datastream, item)

        # Display also the datastream names, if wanted by user
        if self.address_names is not None:
            for irow, aname in enumerate(self.address_names.keys()):
                item = QtWidgets.QTableWidgetItem(aname)
                # item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                self.datastreamtable.setItem(irow, icol_name, item)

        self.datastreamtable.setHorizontalHeaderLabels(colheader)
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
                iskey = item.isdatastream
            except:
                iskey= False
            if iskey or self.allow_all_addresses:
                print('Item {} is a valid address'.format(item.text(0)))
                try:
                    raddress = item.datakey_address
                except:
                    raddress = item.redvypr_address
                if raddress not in self.addresses_chosen:
                    if self.address_names is None: # Append mode
                        self.addresses_chosen.append(raddress)
                    else: # Name mode
                        if i >= len(self.addresses_chosen):
                            break
                        self.addresses_chosen[i] = raddress
                        for ikey,key in enumerate(self.address_names.keys()):
                            if ikey == i:
                                self.address_names[key] = raddress
                else:
                    print('Address is existing already')
            else:
                print('Item {} is not a datastream'.format(item.text(0)))

        #print('Addresses',self.addresses_choosen)
        self.update_datastreamtable()