import copy
import time
import logging
import sys
import yaml
import datetime
import pydantic
from pydantic.color import Color as pydColor
from PyQt5 import QtWidgets, QtCore, QtGui
from redvypr.device import redvypr_device, redvypr_device_parameter
from redvypr.widgets.gui_config_widgets import redvypr_ip_widget, configQTreeWidget, configWidget, dictQTreeWidget
from redvypr.widgets.standard_device_widgets import displayDeviceWidget_standard, redvypr_deviceInitWidget
from redvypr.widgets.redvypr_addressWidget import datastreamWidget
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget, pydanticDeviceConfigWidget, pydanticQTreeWidget
import redvypr.configdata
import redvypr.files as files
import redvypr.data_packets as data_packets
import redvypr.device as device
from redvypr.redvypr_address import redvypr_address

_logo_file = files.logo_file
_icon_file = files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr')
logger.setLevel(logging.DEBUG)


class deviceTabWidget(QtWidgets.QTabWidget):
    def resizeEvent(self, event):
        print("Window has been resized",event)
        print('fds',event.size().width())
        wtran = event.size().width()-500
        print('fsfsd',self.widget(1).width())
        self.setStyleSheet("QTabBar::tab:disabled {"+\
                        "width: {:d}px;".format(wtran)+\
                        "color: transparent;"+\
                        "background: transparent;}")
        super(deviceTabWidget, self).resizeEvent(event)

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

def get_QColor(data):
    """
    Returns a qcolor based on the data input, data can be either a string, a list of rgb or a dictionary of type {'r':250,'g':100,'b':0}
    """
    funcname = __name__ + '.get_QColor():'
    logger.debug(funcname)
    colordata = copy.deepcopy(data)

    if(type(colordata) == str):
        color = QtGui.QColor(colordata)
    elif (type(colordata) == list):
        color = QtGui.QColor(colordata[0], colordata[1], colordata[2])
    elif (type(colordata) == pydColor):
        colors = colordata.as_rgb_tuple()
        color = QtGui.QColor(colors[0], colors[1], colors[2])
    else:
        colors = colordata
        color = QtGui.QColor(colors['r'], colors['g'], colors['b'])

    return color

class redvyprAddDeviceWidget(QtWidgets.QWidget):
    """ A widget that lists all devices found in modules and in the python files included in the path list.

    """
    def __init__(self, redvypr_device_scan=None,redvypr=None):
        """

        Args:
            redvypr:
            device:
        """
        super(redvyprAddDeviceWidget, self).__init__()
        self.redvypr = redvypr
        if redvypr is not None:
            self.redvypr_device_scan = redvypr.redvypr_device_scan
        elif (redvypr_device_scan is not None):
            self.redvypr_device_scan = redvypr_device_scan
        else:
            self.redvypr_device_scan = device.redvypr_device_scan()

        # Update the devicetree
        self.create_tree_widget()
        self.update_tree_widget()
        self.create_deviceinfo_widget()
        # Create widgets for adding/removing devices
        self.addbtn = QtWidgets.QPushButton('Add')
        self.addbtn.clicked.connect(self.add_device_click)
        self.devnamelabel = QtWidgets.QLabel('Devicename')
        self.devname = QtWidgets.QLineEdit()
        self.mp_label = QtWidgets.QLabel('Multiprocessing options')
        self.mp_qthread = QtWidgets.QRadioButton('QThread')
        self.mp_thread = QtWidgets.QRadioButton('Thread')
        self.mp_multi = QtWidgets.QRadioButton('Multiprocessing')
        self.mp_group = QtWidgets.QButtonGroup()
        self.mp_group.addButton(self.mp_qthread)
        self.mp_group.addButton(self.mp_thread)
        self.mp_group.addButton(self.mp_multi)
        self.mp_qthread.setChecked(True)

        self.log_label = QtWidgets.QLabel('Loglevel')
        self.logwidget = QtWidgets.QComboBox()  # A Combobox to change the loglevel of the device
        # Fill the logwidget
        if (logger is not None):
            level = logger.getEffectiveLevel()
            levelname = logging.getLevelName(level)
            loglevels = ['INFO', 'DEBUG', 'WARNING', 'ERROR', 'CRITICAL']
            for i, l in enumerate(loglevels):
                self.logwidget.addItem(l)

            self.logwidget.setCurrentText(levelname)
        else:
            self.logwidget.addItem('NA')

        thread_layout = QtWidgets.QHBoxLayout()
        thread_layout.addWidget(self.mp_qthread)
        thread_layout.addWidget(self.mp_multi)
        thread_layout.addWidget(self.mp_thread)
        self.layout = QtWidgets.QFormLayout(self)
        self.layout.addRow(self.devicetree)
        self.layout.addRow(self.deviceinfo)
        self.layout.addRow(self.log_label,self.logwidget)
        self.layout.addRow(self.mp_label,thread_layout)
        #self.layout.addRow(self.mp_thread, self.mp_multi)
        self.layout.addRow(self.devnamelabel, self.devname)
        self.layout.addRow(self.addbtn)

        self.setWindowIcon(QtGui.QIcon(_icon_file))
        self.setWindowTitle("redvypr add device")

    def create_deviceinfo_widget(self):
        """
        Creates a widget that shows the device information
        Returns:

        """
        self.deviceinfo = QtWidgets.QWidget()  #
        self.deviceinfo_layout = QtWidgets.QFormLayout(self.deviceinfo)
        self.__devices_info_sourcelabel2 = QtWidgets.QLabel()
        self.__devices_info_sourcelabel4 = QtWidgets.QLabel()
        self.__devices_info_sourcelabel6 = QtWidgets.QLabel()
        self.deviceinfo_layout.addRow(QtWidgets.QLabel('Name'),self.__devices_info_sourcelabel2)
        self.deviceinfo_layout.addRow(QtWidgets.QLabel('Source'),self.__devices_info_sourcelabel4)
        self.deviceinfo_layout.addRow(QtWidgets.QLabel('Description'),self.__devices_info_sourcelabel6)

    def create_tree_widget(self):
        """
        Creates the QtreeWidget with the
        Returns:

        """
        self.devicetree = QtWidgets.QTreeWidget()  # All dataproviding devices
        self.devicetree.setColumnCount(1)
        #self.devicetree.setHeaderHidden(True)
        self.devicetree.setHeaderLabels(['Device'])
        self.devicetree.currentItemChanged.connect(self.__item_changed__)
        self.devicetree.itemDoubleClicked.connect(self.__apply_item__)
        self.devicetree.setSortingEnabled(True)

    def update_tree_widget(self):
        self.devicetree.clear()
        root = self.devicetree.invisibleRootItem()
        #moduleroot = QtWidgets.QTreeWidgetItem(['modules', ''])
        #root.addChild(moduleroot)
        def update_recursive(moddict,parentitem):
            try:
                keys = moddict.keys()
            except:
                keys = None

            if(keys is None):
                return
            else:
                for k in moddict.keys():
                    if(k == '__devices__'): # List of devices in the module
                        for devdict in moddict[k]:
                            devicename = devdict['name']
                            #print('devdict',devdict)
                            # remove trailing modules separated by '.'
                            devicename = devicename.split('.')[-1]
                            itm = QtWidgets.QTreeWidgetItem([devicename, ''])
                            itm.devdict = devdict # Add device information
                            parentitem.addChild(itm)
                    else:
                        # remove trailing modules separated by '.'
                        if '/' in k: # Check if its a path or a module file
                            ktxt = k
                        else:
                            ktxt = k.split('.')[-1]

                        itm = QtWidgets.QTreeWidgetItem([ktxt, ''])
                        itm.devdict = None # Not a device
                        parentitem.addChild(itm)
                        update_recursive(moddict[k],itm)

        #update_recursive(self.redvypr_device_scan.redvypr_devices['modules'],moduleroot)
        update_recursive(self.redvypr_device_scan.redvypr_devices, root)


        self.devicetree.expandAll()
        self.devicetree.resizeColumnToContents(0)
        self.devicetree.sortByColumn(0, QtCore.Qt.AscendingOrder)

    def __item_changed__(self, new, old):
        print('Item changed')
        print('new',new, old)
        if new.devdict is not None:
            self.__update_device_info__(new.devdict)
            self.addbtn.setEnabled(True)
        else:
            self.addbtn.setEnabled(False)

    def __apply_item__(self):
        print('Apply')

    def __update_device_info__(self,devdict):
        """ Populates the self.__devices_info widget with the info of the module
        """
        infotxt = devdict['name']
        self.__devices_info_sourcelabel2.setText(infotxt)
        infotxt2 = devdict['file']
        self.__devices_info_sourcelabel4.setText(infotxt2)
        try:
            desctxt = devdict['module'].description
        except Exception as e:
            desctxt = ''

        self.__devices_info_sourcelabel6.setText(desctxt)

    def __device_name(self):
        devicemodulename = self.__devices_list.currentItem().text()
        devicename = devicemodulename + '_{:d}'.format(self.redvypr.numdevice + 1)
        self.__devices_devname.setText(devicename)
        self.__device_info()

    def add_device_click(self):
        """ Adds the device
        """
        funcname = __name__ + 'add_device_click():'
        logger.debug(funcname)
        getSelected = self.devicetree.selectedItems()
        if getSelected:
            item = getSelected[0]

        if item.devdict is not None:
            devicemodulename = item.devdict['name']
            device_parameter = redvypr_device_parameter()
            if self.mp_thread.isChecked():
                device_parameter.multiprocess = 'thread'
            elif self.mp_qthread.isChecked():
                device_parameter.multiprocess = 'qthread'
            elif self.mp_multi.isChecked():
                device_parameter.multiprocess = 'multiprocessing'

            levelname = self.logwidget.currentText()
            device_parameter.loglevel = levelname
            devname = str(self.devname.text())
            if len(devname) > 0:
                device_parameter.name = devname

            print('devicemodulename',devicemodulename)
            print('Adding device, config',device_parameter)
            if self.redvypr is not None:
                self.redvypr.add_device(devicemodulename=devicemodulename, device_parameter=device_parameter)
            self.devname.clear()
            # Update the name
            #self.__device_name()
        else:
            print('Not a device')



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
        self.setWindowIcon(QtGui.QIcon(_icon_file))
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
        self.subscribe_edit.redvypr_address = redvypr_address('*')

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
        addr_formats = redvypr_address().get_common_address_formats()
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
        addr_format = self.__formatCombo.currentText()
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
            self.subscribe_edit.redvypr_address = newitem.redvypr_address
            self.__subscribe_editChanged__()

            #if(subscribed):
            #    self.__commitbtn.setText('Unsubscribe')
            #    self.__commitbtn.__status__ = 'remove'
            #    self.__commitbtn.setEnabled(True)
            #    self.__commitbtn.redvypr_addr_remove = devstr
            #else:
            #    self.subscribe_edit.setText(devstr)
            #    #print(devstr)
            #    #print('Item',newitem.text(0))
            #    self.__commitbtn.setText('Subscribe')
            #    self.__commitbtn.__status__ = 'add'
            #    self.__commitbtn.setEnabled(True)
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
            data_provider_all = self.redvypr.get_device_objects(publishes=True)
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
                    if subscribed:
                        status = 'subscribed'
                        itm.setFont(0,font1)
                        itm.subscribed = True
                    else:
                        itm.setFont(0, font0)
                        itm.subscribed = False

                    root.addChild(itm)
                    # Check for forwarded devices
                    if True:
                        devs_forwarded = dev.get_device_info()
                        for devaddress in devs_forwarded.keys():
                            devaddress_redvypr = redvypr_address(devaddress)
                            subscribed = False
                            for a in self.device.subscribed_addresses:
                                subscribed = a in devaddress_redvypr
                                if subscribed:
                                    break

                            devaddress_str = devaddress_redvypr.get_str('/a/h/p/d/')
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
                print('Adding?', address_add)
                if (len(address_add) > 0):
                    print('Adding', address_add)
                    self.device.subscribe_address(address_add)
                    self.update_list(self.device)
                else:
                    print('Nothing to add')
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

class deviceControlWidget(QtWidgets.QWidget):
    """ A widget to set the general settings of the device (start/stop, debug level)
    """
    device_start = QtCore.pyqtSignal(dict) # Signal requesting a start of the device (starting the thread)
    device_stop  = QtCore.pyqtSignal(dict) # Signal requesting a stop of device
    connect      = QtCore.pyqtSignal(dict) # Signal requesting a change of the connection

    def __init__(self,devicedict,redvyprwidget):
        super(deviceControlWidget, self).__init__()
        self.devicedict = devicedict
        self.device = devicedict['device']
        # Connect the status signal
        self.device.status_signal.connect(self.thread_status)
        self.redvyprwidget = redvyprwidget
        self.devicetab = self.redvyprwidget.devicetabs # The parent tab with all devices listed
        self.namelabel = QtWidgets.QLabel(devicedict['device'].name)
        label = self.namelabel
        fsize         = label.fontMetrics().size(0, label.text())
        label.setFont(QtGui.QFont('Arial', fsize.height()+4))        
        #self.numlabel = QtWidgets.QLabel(str(devicedict['device'].numdevice))
        #label = self.numlabel
        #fsize         = label.fontMetrics().size(0, label.text())
        #label.setFont(QtGui.QFont('Arial', fsize.height()+4))                
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout2 = QtWidgets.QGridLayout()
        self.logwidget = QtWidgets.QComboBox() # A Combobox to change the loglevel of the device
        self.logwidget.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)
        # Fill the logwidget
        logger    = self.devicedict['logger']
        if(logger is not None):
            level     = logger.getEffectiveLevel()
            levelname = logging.getLevelName(level)
            loglevels = ['CRITICAL','ERROR','WARNING','INFO','DEBUG']
            for i,l in enumerate(loglevels):
                self.logwidget.addItem(l)
                    
            self.logwidget.setCurrentText(levelname)
        else:
            self.logwidget.addItem('NA')
            
        self.logwidget.currentIndexChanged.connect(self.loglevel_changed)
        
        self.viewbtn = QtWidgets.QPushButton("View")
        self.viewbtn.clicked.connect(self.viewclicked)
        self.viewbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)        
        self.conbtn = QtWidgets.QPushButton("Subscribe")
        self.conbtn.clicked.connect(self.conclicked)
        self.conbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)
        self.rembtn = QtWidgets.QPushButton("Remove")
        self.rembtn.clicked.connect(self.remdevice)
        self.rembtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)        
        self.renbtn = QtWidgets.QPushButton("Rename")
        self.renbtn.clicked.connect(self.rendevice)
        self.renbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)        
        self.startbtn = QtWidgets.QPushButton("Start")
        self.startbtn.setCheckable(True)
        self.startbtn.clicked.connect(self.startstopclicked)
        self.startbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)
        self.infobtn = QtWidgets.QPushButton("Info")
        self.infobtn.clicked.connect(self.get_info)
        self.infobtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)
        #Configuration
        configlayout = QtWidgets.QVBoxLayout()
        # Autostart
        self.autostart = QtWidgets.QPushButton('Autostart')
        self.autostart.setCheckable(True)
        self.autostart.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        try: # If the device has an autostart attribute
            self.autostart.isChecked(self.device.autostart)
        except:
            pass
        self.autostart.clicked.connect(self.autostart_clicked)
        #self.layout2.addWidget(QtWidgets.QLabel('Name' + ' Device #' + str(devicedict['device'].numdevice)),0,0)
        self.layout2.addWidget(self.namelabel,0,0)
        self.layout.addLayout(self.layout2)
        self.layout.addStretch()
        self.layout.addWidget(self.autostart)
        self.layout.addWidget(self.logwidget)
        self.layout.addWidget(self.viewbtn)
        self.layout.addWidget(self.infobtn)
        self.layout.addWidget(self.renbtn)
        self.layout.addWidget(self.conbtn)
        self.layout.addWidget(self.rembtn)
        self.layout.addWidget(self.startbtn)

    def autostart_clicked(self):
        #print('Autostart',self.autostart.isChecked())
        self.device.autostart = self.autostart.isChecked()

    def loglevel_changed(self):
        loglevel = self.logwidget.currentText()
        logger = self.devicedict['logger']
        print('loglevel changed to',loglevel)
        if(logger is not None):
            logger.setLevel(loglevel)

    def get_info(self):        
        self.infowidget       = QtWidgets.QPlainTextEdit()
        self.infowidget.setReadOnly(True)
        sortstat ={}
        for i in sorted(self.devicedict['statistics']):
            sortstat[i]=self.devicedict['statistics'][i]

        sortstat['datakeys'] = sorted(sortstat['datakeys'])
        statstr = yaml.dump(sortstat)
        self.infowidget.insertPlainText(statstr + '\n')
        self.infowidget.show()
        
        
    def viewclicked(self):
        self.redvyprwidget.devicetabs.setCurrentWidget(self.devicedict['widget'])        

    def conclicked(self):
        self.connect.emit(self.devicedict)

    def startstopclicked(self):
        funcname = __name__ + '.startstopclicked()'
        logger.debug(funcname)
        if(self.startbtn.text() == 'Stop'):
            self.device.thread_stop()
        else:
            self.device.thread_start()

    def thread_status(self,statusdict):
        """ Function regularly called by redvypr to update the thread status
        """
        status = statusdict['thread_status']
        if(status):
            self.startbtn.setText('Stop')
            self.startbtn.setChecked(True)            
        else:
            self.startbtn.setText('Start')
            self.startbtn.setChecked(False)                        

    def remdevice(self):
        """ Removing the device
        """
        ret = QtWidgets.QMessageBox.question(self,'', "Are you sure to remove the device?", QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ret == QtWidgets.QMessageBox.Yes:
            widget = self.devicedict['widget']
            for i in range(self.devicetab.count()):
                if(self.devicetab.widget(i) == widget):
                    self.redvyprwidget.closeTab(i)

    def rendevice(self):
        """ Renaming a device
        """
        oldname = self.devicedict['device'].name
        name, okPressed = QtWidgets.QInputDialog.getText(self, "Enter new name","Device name:", QtWidgets.QLineEdit.Normal, oldname)
        if okPressed and name != '':
            renamed = self.redvyprwidget.renamedevice(oldname,name)

#
#
#
# A logging handler for qplaintext
#
#
#
class QPlainTextEditLogger(logging.Handler):
    def __init__(self):
        super(QPlainTextEditLogger, self).__init__()

    def add_widget(self,widget):        
        self.widget = widget

    def emit(self, record):
        msg = self.format(record)
        self.widget.appendPlainText(msg)

    def write(self, m):
        pass   
    



#
#
# Widget shows the statistics of the device
#
#
class redvypr_deviceStatisticWidget(QtWidgets.QWidget):
    """
    Widgets shows the device statistic as text
    """
    def __init__(self, device = None, dt_update=1000):
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.device = device
        self.layout = QtWidgets.QGridLayout(self)
        self.infowidget       = QtWidgets.QPlainTextEdit()
        self.infowidget.setReadOnly(True)
        self.layout.addWidget(self.infowidget,0,0)

        self.__update_info()
        # Todo, let the user choose for an update
        #self.updatetimer = QtCore.QTimer()
        #self.updatetimer.timeout.connect(self.__update_info)
        #self.updatetimer.start(dt_update)

    def __update_info(self):
        funcname = __name__ + '.__update_info():'
        prev_cursor = self.infowidget.textCursor()
        pos  = self.infowidget.verticalScrollBar().value()
        pos2 = self.infowidget.verticalScrollBar().value()
        self.infowidget.clear()
        sortstat = {}
        for i in sorted(self.device.statistics):
            sortstat[i]=self.device.statistics[i]

        sortstat['datakeys'] = sorted(sortstat['datakeys'])
        statstr = yaml.dump(sortstat)
        self.infowidget.insertPlainText(statstr + '\n')
        #self.infowidget.moveCursor(QtGui.QTextCursor.End)
        # cursor.setPosition(0)
        # self.text.setTextCursor(prev_cursor)
        if True:
            self.infowidget.verticalScrollBar().setValue(pos)


class redvypr_deviceInfoWidget(QtWidgets.QWidget):
    """
    Information widget of a device
    """
    connect = QtCore.pyqtSignal(
        redvypr_device)  # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self, device = None, dt_update = 1000):
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.device = device
        self.layout = QtWidgets.QGridLayout(self)
        tstr = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.update_label = QtWidgets.QLabel('Last update {:s}'.format(tstr))
        self.packetRecv_label = QtWidgets.QLabel('Packets received {:d}'.format(0))
        self.packetPubl_label = QtWidgets.QLabel('Packets published {:d}'.format(0))
        self.publist_label = QtWidgets.QLabel('Publishes to')
        self.publist = QtWidgets.QListWidget()
        self.sublist_label = QtWidgets.QLabel('Subscribed devices')
        self.sublist = QtWidgets.QListWidget()
        self.subBtn = QtWidgets.QPushButton('Subscribe')
        self.subBtn.clicked.connect(self.connect_clicked)
        self.confBtn = QtWidgets.QPushButton('Config')
        self.confBtn.clicked.connect(self.config_clicked)
        self.statBtn = QtWidgets.QPushButton('Statistics')
        self.statBtn.clicked.connect(self.statistics_clicked)
        self.layout.addWidget(self.update_label)
        self.layout.addWidget(self.packetRecv_label)
        self.layout.addWidget(self.packetPubl_label)
        self.layout.addWidget(self.sublist_label)
        self.layout.addWidget(self.sublist)
        self.layout.addWidget(self.publist_label)
        self.layout.addWidget(self.publist)
        self.layout.addWidget(self.statBtn)
        self.layout.addWidget(self.confBtn)
        self.layout.addWidget(self.subBtn)

        self.updatetimer = QtCore.QTimer()
        self.updatetimer.timeout.connect(self.__update_info)
        self.updatetimer.start(dt_update)

    def config_clicked(self):
        funcname = __name__ + '.config_clicked():'
        logger.debug(funcname)
        self.config_widget = pydanticDeviceConfigWidget(self.device)
        self.config_widget.show()

    def statistics_clicked(self):
        funcname = __name__ + '.statistics_clicked():'
        logger.debug(funcname)
        self.statistics_widget = redvypr_deviceStatisticWidget(device=self.device)
        self.statistics_widget.show()

    def connect_clicked(self):
        funcname = __name__ + '.connect_clicked():'
        logger.debug(funcname)
        button = self.sender()
        self.connect.emit(self.device)

    def __update_info(self):
        funcname = __name__ + '.__update_info():'
        #logger.debug(funcname)
        tstr = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.update_label.setText('Last update {:s}'.format(tstr))
        nrecv = self.device.statistics['packets_received']
        npub = self.device.statistics['packets_published']
        self.packetRecv_label.setText('Packets received {:d}'.format(nrecv))
        self.packetPubl_label.setText('Packets published {:d}'.format(npub))



        devs = self.device.get_subscribed_devices()
        self.sublist.clear()
        for d in devs:
            devname = d.name
            self.sublist.addItem(devname)

        devs_sub = self.device.publishing_to()
        self.publist.clear()
        for d in devs_sub:
            devname = d.name
            self.publist.addItem(devname)








