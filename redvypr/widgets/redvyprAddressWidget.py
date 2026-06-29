import json

from PyQt6 import QtWidgets, QtCore, QtGui
import logging
import sys
import qtawesome
import redvypr.files as files
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket
from .redvyprMetadataTable import RedvyprMetadataTable

_logo_file = files.logo_file
_icon_file = files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.widgets.redvyprAddressWidget')
logger.setLevel(logging.DEBUG)


class DataInfoDialog(QtWidgets.QDialog):
    """ A dialog that displays datakey information inside a clean QTableWidget structure. """

    def __init__(self, data_info, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Data Info")
        self.resize(500, 300)
        print("Metadata",data_info)
        layout = QtWidgets.QVBoxLayout(self)

        # Create Table Widget
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Property", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)

        # Populating data into the table view
        if data_info and isinstance(data_info, dict):
            self.table.setRowCount(len(data_info))
            for row, (key, value) in enumerate(data_info.items()):
                # Property Key Item
                key_item = QtWidgets.QTableWidgetItem(str(key))
                key_item.setFlags(key_item.flags() ^ QtCore.Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 0, key_item)

                # Property Value Item
                val_item = QtWidgets.QTableWidgetItem(str(value))
                val_item.setFlags(val_item.flags() ^ QtCore.Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 1, val_item)
        else:
            self.table.setRowCount(1)
            self.table.setItem(0, 0, QtWidgets.QTableWidgetItem("Info"))
            self.table.setItem(0, 1, QtWidgets.QTableWidgetItem("No data info available for this item."))

        layout.addWidget(self.table)

        # Close Button
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)



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
class RedvyprTreeItem:
    """
    Lightweight, non-GUI data node for the tree hierarchy.
    Replaces QTreeWidgetItem to prevent UI-thread choking on heavy datasets.
    """

    def __init__(self, data, parent=None):
        self.item_data = data  # List of strings matching columns
        self.parent_item = parent
        self.child_items = []

        # Internal property mirrors from original architecture
        self.isdatastream = False
        self.device = None
        self.devaddress = None
        self.redvypr_address = None
        self.datakey_address = None
        self.address_forwarded = None
        self.addrentries = ['h', 'd', 'i']
        self.all_check = {}

    def appendChild(self, child):
        child.parent_item = self
        self.child_items.append(child)

    def child(self, row):
        if 0 <= row < len(self.child_items):
            return self.child_items[row]
        return None

    def childCount(self):
        return len(self.child_items)

    def columnCount(self):
        return len(self.item_data)

    def data(self, column):
        if 0 <= column < len(self.item_data):
            return self.item_data[column]
        return None

    def setText(self, column, text):
        if 0 <= column < len(self.item_data):
            self.item_data[column] = text

    def row(self):
        if self.parent_item:
            return self.parent_item.child_items.index(self)
        return 0

    def parent(self):
        return self.parent_item


class RedvyprTreeModel(QtCore.QAbstractItemModel):
    """
    Hierarchical item model delivering optimized dynamic data retrieval
    for thousands of telemetry records instantly.
    """

    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.root_item = RedvyprTreeItem([""] * len(columns))

    def clear(self):
        self.beginResetModel()
        self.root_item = RedvyprTreeItem([""] * len(self.columns))
        self.endResetModel()

    def invisibleRootItem(self):
        return self.root_item

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self.columns)

    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if orientation == QtCore.Qt.Orientation.Horizontal and role == QtCore.Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.columns):
                return self.columns[section]
        return None

    def index(self, row, column, parent=QtCore.QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()

        if not parent.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent.internalPointer()

        child_item = parent_item.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)
        return QtCore.QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QtCore.QModelIndex()

        child_item = index.internalPointer()
        parent_item = child_item.parent()

        if parent_item == self.root_item or parent_item is None:
            return QtCore.QModelIndex()

        return self.createIndex(parent_item.row(), 0, parent_item)

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.column() > 0:
            return 0

        if not parent.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent.internalPointer()

        return parent_item.childCount()

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        item = index.internalPointer()

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return item.data(index.column())

        elif role == QtCore.Qt.ItemDataRole.BackgroundRole:
            # Replicates background highlights for container layers
            if index.column() == 0:
                if not item.isdatastream and item.parent_item != self.root_item:
                    return QtGui.QColor(240, 240, 240)  # col_grey_key fallback
                elif not item.isdatastream:
                    return QtGui.QColor(210, 210, 210)  # col_grey fallback
        return None


class RedvyprFilterDialog(QtWidgets.QDialog):
    """
    A standalone dialog window containing the dynamic Excel-like matrix filter interface.
    """

    def __init__(self, parent_widget):
        super().__init__(parent_widget)
        self.p = parent_widget
        self.setWindowTitle("Dynamic Filter Matrix")
        self.resize(320, 450)
        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(QtWidgets.QLabel("Target Column:"))
        self.column_selector = QtWidgets.QComboBox()
        self.column_selector.addItems(self.p.COLUMNS)
        self.column_selector.currentTextChanged.connect(self.populate_value_checkboxes)
        layout.addWidget(self.column_selector)

        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_select_all = QtWidgets.QPushButton("Select All")
        self.btn_deselect_all = QtWidgets.QPushButton("Deselect All")
        self.btn_select_all.clicked.connect(lambda: self.set_all_checkboxes_state(True))
        self.btn_deselect_all.clicked.connect(
            lambda: self.set_all_checkboxes_state(False))
        btn_layout.addWidget(self.btn_select_all)
        btn_layout.addWidget(self.btn_deselect_all)
        layout.addLayout(btn_layout)

        layout.addWidget(QtWidgets.QLabel("Allowed Unique Values:"))
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QtWidgets.QWidget()
        self.checkbox_layout = QtWidgets.QVBoxLayout(self.scroll_widget)
        self.checkbox_layout.addStretch()
        self.scroll_area.setWidget(self.scroll_widget)
        layout.addWidget(self.scroll_area)

        self.close_button = QtWidgets.QPushButton("Apply & Close")
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.close_button)

        current_col = self.column_selector.currentText()
        self.populate_value_checkboxes(current_col)

    def populate_value_checkboxes(self, active_column):
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
            self.checkbox_layout.insertWidget(self.checkbox_layout.count() - 1, cb)
            self.p.active_rendered_checkboxes[val_str] = cb

    def set_all_checkboxes_state(self, checked_state):
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
    Component wrapping a multi-column tree view built over an optimized QTreeView
    architecture using a dedicated ViewModel layout for high volume processing speeds.
    """
    addressSelected = QtCore.pyqtSignal(object)
    COLUMNS = ["Datastreams", "Host", "Device", "Publisher", "UUID", "Address",
               "Datatype"]

    def __init__(self, redvypr,
                 parent=None,
                 multi_select=False,
                 visible_columns=None,
                 show_host=True,
                 **kwargs):
        super().__init__(parent)
        self.redvypr = redvypr
        self.multi_select = multi_select
        self.show_host=show_host
        self.external_filter_include = [RedvyprAddress(f) for f in
                                        kwargs.get('filter_device', ["@"])]
        self.external_filter_datastream = [RedvyprAddress(f) for f in
                                           kwargs.get('filter_datastream', ["@"])]
        self.expandlevel = kwargs.get('expansion_level', 10)
        self.force_time_series_expansion = kwargs.get('force_time_series_expansion',
                                                      False)
        self.addrentries_show_for_publishing_devices = ['h', 'd', 'i']

        if visible_columns is None:
            self.default_visible_columns = ["Datastreams", "Host", "Device",
                                            "Publisher", "Datatype"]
        else:
            self.default_visible_columns = list(visible_columns)

        self.filter_states = {}
        self.active_rendered_checkboxes = {}

        # Initialize the underlying Item ViewModel
        self.tree_model = RedvyprTreeModel(self.COLUMNS, self)

        self.init_ui()
        self.update_device_tree()

    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.menu_bar = QtWidgets.QMenuBar()
        self.view_menu = self.menu_bar.addMenu("Show / Hide Columns")
        main_layout.addWidget(self.menu_bar)

        control_bar_layout = QtWidgets.QHBoxLayout()
        self.filter_button = QtWidgets.QPushButton("Filter")
        self.filter_button.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_FileDialogContentsView))
        self.filter_button.clicked.connect(self._open_filter_dialog)
        control_bar_layout.addWidget(self.filter_button)
        control_bar_layout.addStretch()
        main_layout.addLayout(control_bar_layout)

        # TREE VIEW REPLACEMENT
        self.device_tree = QtWidgets.QTreeView()
        self.device_tree.setModel(self.tree_model)

        header = self.device_tree.header()
        header.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_context_menu)
        header.setSectionsMovable(True)

        self.device_tree.setSortingEnabled(True)
        header.setSortIndicator(0, QtCore.Qt.SortOrder.AscendingOrder)

        if self.multi_select:
            self.device_tree.setSelectionMode(
                QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        else:
            self.device_tree.clicked.connect(self._on_item_clicked)

        self.device_tree.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.device_tree.customContextMenuRequested.connect(
            self._show_item_context_menu)
        main_layout.addWidget(self.device_tree, stretch=1)

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

        # Initial default visibility assignment
        for i, col_name in enumerate(self.COLUMNS):
            if i == 0:
                continue
            self.device_tree.setColumnHidden(i,
                                             col_name not in self.default_visible_columns)

        self._rebuild_view_menu()

    def _open_filter_dialog(self):
        dialog = RedvyprFilterDialog(self)
        dialog.exec()

    def build_filter_matrix_states(self):
        old_states = self.filter_states
        self.filter_states = {col: {} for col in self.COLUMNS}

        def collect_values(item):
            for col_idx in range(len(self.COLUMNS)):
                col_name = self.COLUMNS[col_idx]
                val = item.data(col_idx) or ""
                if old_states and col_name in old_states and val in old_states[
                    col_name]:
                    self.filter_states[col_name][val] = old_states[col_name][val]
                else:
                    self.filter_states[col_name][val] = True

            for child in item.child_items:
                collect_values(child)

        collect_values(self.tree_model.invisibleRootItem())

    def on_checkbox_toggled(self, col_key, value_str, check_state):
        is_checked = (check_state == 2 or check_state == QtCore.Qt.CheckState.Checked)
        self.filter_states[col_key][value_str] = is_checked
        self.apply_calculated_filters()

    def apply_calculated_filters(self):
        """Uses row hidings on TreeView indices via row filtering."""

        def evaluate_item_visibility(item):
            row_matches_filter = True
            for col_idx, col_name in enumerate(self.COLUMNS):
                val = item.data(col_idx) or ""
                allowed_map = self.filter_states.get(col_name, {})
                if allowed_map and not allowed_map.get(val, True):
                    row_matches_filter = False
                    break

            any_child_visible = False
            for child in item.child_items:
                if evaluate_item_visibility(child):
                    any_child_visible = True

            final_visibility = row_matches_filter or any_child_visible

            # Use QTreeView's setRowHidden mapping indexes via parent
            if item.parent_item and item.parent_item != self.tree_model.invisibleRootItem():
                p_item = item.parent_item
                p_index = self.tree_model.createIndex(p_item.row(), 0, p_item)
                self.device_tree.setRowHidden(item.row(), p_index, not final_visibility)
            elif item.parent_item:
                self.device_tree.setRowHidden(item.row(), QtCore.QModelIndex(),
                                              not final_visibility)

            return final_visibility

        for top_item in self.tree_model.invisibleRootItem().child_items:
            evaluate_item_visibility(top_item)

    def _rebuild_view_menu(self):
        self.view_menu.clear()
        for i, col_name in enumerate(self.COLUMNS):
            if i == 0:
                continue
            action = QtGui.QAction(col_name, self.view_menu, checkable=True)
            action.setChecked(not self.device_tree.isColumnHidden(i))
            action.setData(i)
            action.triggered.connect(self._toggle_column_visibility)
            self.view_menu.addAction(action)

    def _show_header_context_menu(self, pos: QtCore.QPoint):
        menu = QtWidgets.QMenu(self)
        for i, col_name in enumerate(self.COLUMNS):
            if i == 0:
                continue
            action = QtGui.QAction(col_name, menu, checkable=True)
            action.setChecked(not self.device_tree.isColumnHidden(i))
            action.setData(i)
            action.triggered.connect(self._toggle_column_visibility)
            menu.addAction(action)
        menu.exec_(self.device_tree.header().mapToGlobal(pos))

    def _toggle_column_visibility(self):
        action = self.sender()
        if action:
            col_index = action.data()
            is_visible = action.isChecked()
            self.device_tree.setColumnHidden(col_index, not is_visible)
            if is_visible:
                self.device_tree.resizeColumnToContents(col_index)
            self._rebuild_view_menu()

    def _is_item_selectable(self, item):
        return item.isdatastream or (
                    self.allow_all_checkbox.isChecked() and self.show_devices_checkbox.isChecked())

    def _on_show_devices_toggled(self):
        if not self.show_devices_checkbox.isChecked():
            self.allow_all_checkbox.setChecked(False)
            self.allow_all_checkbox.setEnabled(False)
        else:
            self.allow_all_checkbox.setEnabled(True)
        self.update_device_tree()

    def _on_item_clicked(self, index):
        item = index.internalPointer()
        if not item or not self._is_item_selectable(item):
            return
        raddress = getattr(item, 'datakey_address',
                           getattr(item, 'redvypr_address', None))
        if raddress:
            self.addressSelected.emit(raddress)

    def _on_apply_clicked(self):
        selected_indexes = self.device_tree.selectionModel().selectedRows()
        selected_addresses = []
        for index in selected_indexes:
            item = index.internalPointer()
            if item and self._is_item_selectable(item):
                raddress = getattr(item, 'datakey_address',
                                   getattr(item, 'redvypr_address', None))
                if raddress and raddress not in selected_addresses:
                    selected_addresses.append(raddress)
        self.addressSelected.emit(selected_addresses)

    def _on_unselect_clicked(self):
        self.device_tree.clearSelection()

    def _show_item_context_menu(self, pos: QtCore.QPoint):
        print("Opening Menu for item")
        index = self.device_tree.indexAt(pos)
        item = index.internalPointer()
        if not item:
            return

        action = None
        menu = QtWidgets.QMenu(self.device_tree)
        # 1. Action: Metadata (Left blank/disabled for now)
        metadata_action = menu.addAction("Metadata")
        #metadata_action.setEnabled(False)

        try:
            data_info = item.data_info
        except:
            data_info = None

        if data_info:
            # 2. Action: Data Info
            datainfo_action = menu.addAction("Data Info")
            # Display the context menu at the cursor position

        action = menu.exec(self.device_tree.mapToGlobal(pos))

        # Handle Action Triggers
        if action:
            if data_info:
                if action == datainfo_action:
                    # Extract the correct datakey string depending on the item structure
                    # Construct and exhibit the visual table view dialog
                    dialog = DataInfoDialog(data_info, parent=self)
                    dialog.exec()

            if action == metadata_action:
                redvypr_address = item.datakey_address
                print(f"Getting metdata for:{redvypr_address}")
                self._metdatawidget_menu = RedvyprMetadataTable(redvypr_instance=self.redvypr, redvypr_address=redvypr_address)
                self._metdatawidget_menu.show()




    def get_address_string_for_item(self, raddr, addr_entry_list):
        return raddr.to_address_string(addr_entry_list)

    def update_device_tree(self):
        """Constructs data coordinates natively streaming through the custom model layer."""
        logger.debug("Updating device tree model elements.")

        self.device_tree.setUpdatesEnabled(False)
        self.tree_model.clear()

        show_devices = self.show_devices_checkbox.isChecked()
        actual_root = self.tree_model.invisibleRootItem()

        if self.show_host == False:
            root = actual_root
        else:
            if show_devices == False:
                root = actual_root
            else:
                hostinfo = self.redvypr.hostinfo
                host_row = [hostinfo["host"], hostinfo["addr"], "N/A", "N/A", "N/A", hostinfo["addr"], "dict"]
                root_host_item = RedvyprTreeItem(host_row)
                root_host_item.isdatastream = False
                root_host_item.device = True
                root_host_item.redvypr_address = self.redvypr.address
                root_host_item.datakey_address = self.redvypr.address
                actual_root.appendChild(root_host_item)
                root = root_host_item

        def make_row_data(p0, raddress, datatype_str=""):
            row = [str(p0), "N/A", "N/A", "N/A", "N/A", "N/A", str(datatype_str)]
            if raddress:
                row[1] = str(getattr(raddress, 'h', 'N/A'))
                row[2] = str(getattr(raddress, 'd', 'N/A'))
                row[3] = str(getattr(raddress, 'p', 'N/A'))
                row[4] = str(getattr(raddress, 'u', 'N/A'))
                row[5] = raddress.to_address_string() if hasattr(raddress, 'to_address_string') else str(raddress)
            return row

        publishing_devices = self.redvypr.get_device_objects(publishes=True, subscribes=False)

        if publishing_devices is not None:
            for publishing_device in publishing_devices:
                flag_datastreams = False

                test_ext_filter = any(
                    addr_inc.matches(publishing_device.address) for addr_inc in self.external_filter_include
                )
                if not test_ext_filter:
                    continue

                row_data = make_row_data(publishing_device.name, publishing_device.address, "")
                itm_publishingdevice = RedvyprTreeItem(row_data)
                itm_publishingdevice.device = publishing_device
                itm_publishingdevice.redvypr_address = publishing_device.address
                itm_publishingdevice.datakey_address = RedvyprAddress(publishing_device.address)
                itm_publishingdevice.isdatastream = False

                devs_forwarded = publishing_device.get_device_info()
                device_addresses = sorted(list(devs_forwarded.keys()))
                # Devices
                for device_address in device_addresses:
                    print(f"device address:{device_address}")
                    devaddress_redvypr = RedvyprAddress(device_address)
                    device_str = self.get_address_string_for_item(devaddress_redvypr,
                                                                  self.addrentries_show_for_publishing_devices)

                    row_sub_data = make_row_data(device_str, devaddress_redvypr, "")
                    itm_deviceaddress = RedvyprTreeItem(row_sub_data)
                    itm_deviceaddress.device = publishing_device
                    itm_deviceaddress.addrentries = self.addrentries_show_for_publishing_devices
                    itm_deviceaddress.redvypr_address = devaddress_redvypr
                    itm_deviceaddress.datakey_address = devaddress_redvypr
                    itm_deviceaddress.address_forwarded = device_address
                    itm_deviceaddress.isdatastream = False

                    datakeys_info = devs_forwarded[device_address]['datakeys_info']
                    print(f"datakeys_info:{datakeys_info}")
                    if datakeys_info:
                        if show_devices:
                            itm_publishingdevice.appendChild(itm_deviceaddress)
                            current_parent_device_node = itm_deviceaddress
                        else:
                            current_parent_device_node = root

                        # Keep track of generated tree node items to dynamically build their child relationships
                        created_items = {}
                        # Sort keys sequentially to ensure parent nodes are generated before child nodes
                        for key in sorted(datakeys_info.keys()):
                            # Fetch metadata seamlessly using the hybrid static O(1) classmethod
                            meta = Datapacket.get_datakey_info_from_dict(datakeys_info, key)
                            print(f"update_device_tree metadata:{meta}")

                            # Build tree entry metadata row
                            row_data = make_row_data(key, RedvyprAddress(device_address, datakey=key), meta["data_type"])
                            itm_k = RedvyprTreeItem(row_data)
                            itm_k.data_info = meta # the datastream information
                            itm_k.redvypr_address = RedvyprAddress(device_address, datakey=key)
                            itm_k.datakey_address = itm_k.redvypr_address
                            itm_k.device = publishing_device

                            # Distinguish flat streaming data vs. structural containers
                            # This should be refined
                            print(f"datatype:{meta["data_type"]}")
                            if ("float" in meta["data_type"]
                                or "int" in meta["data_type"]
                                or "str" in meta["data_type"]):
                                itm_k.isdatastream = True
                            if (meta["is_concatenated"]
                                    or "timestamp" in meta["type"]
                                    or meta["type"] == "single_t_array"
                                    or meta["type"] == "standard"):
                                itm_k.isdatastream = True
                            else:
                                itm_k.isdatastream = False

                            created_items[key] = itm_k

                            # Figure out where to append this node in the layout hierarchy
                            parent_key = None
                            # Reverse lookup to find if this node belongs inside another container's child array
                            for potential_parent, p_meta in datakeys_info.items():
                                if "children" in p_meta and key in p_meta["children"]:
                                    parent_key = potential_parent
                                    break

                            if parent_key and parent_key in created_items and show_devices:
                                created_items[parent_key].appendChild(itm_k)
                            else:
                                current_parent_device_node.appendChild(itm_k)

                        flag_datastreams = True

                if flag_datastreams and show_devices:
                    root.appendChild(itm_publishingdevice)

        # Notify layout updates and trigger auto expansion
        self.tree_model.layoutChanged.emit()
        self.device_tree.expandAll()

        self.build_filter_matrix_states()

        for i in range(len(self.COLUMNS)):
            if not self.device_tree.isColumnHidden(i):
                self.device_tree.resizeColumnToContents(i)

        self.device_tree.setUpdatesEnabled(True)


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
        #print(f"set_address({address})")
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


