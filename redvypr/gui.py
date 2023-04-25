import copy
import time
import logging
import sys
import yaml
from PyQt5 import QtWidgets, QtCore, QtGui
from redvypr.device import redvypr_device
from redvypr.widgets.gui_config_widgets import redvypr_ip_widget, configQTreeWidget, configWidget
from redvypr.widgets.standard_device_widgets import displayDeviceWidget_standard, redvypr_deviceInitWidget
from redvypr.widgets.datastream_widget import datastreamWidget
import redvypr.configdata
import redvypr.files as files
import redvypr.data_packets as data_packets
import redvypr.device as device

_logo_file = files.logo_file
_icon_file = files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr')
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

def get_QColor(data):
    funcname = __name__ + '.get_QColor():'
    if(type(data.data) == str):
        color = QtGui.QColor(data.data)
    else:
        colors = data.data
        color = QtGui.QColor(colors['r'].data, colors['g'].data, colors['b'].data)

    return color

class redvyprDeviceWidget(QtWidgets.QWidget):
    """ A widget that lists all devices found in modules and in the python files included in the path list.
    """
    def __init__(self, redvypr_device_scan=None,redvypr=None):
        """

        Args:
            redvypr:
            device:
        """
        super(redvyprDeviceWidget, self).__init__()
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
        self.mp_thread = QtWidgets.QRadioButton('Thread')
        self.mp_multi = QtWidgets.QRadioButton('Multiprocessing')
        self.mp_multi.setChecked(True)
        self.mp_group = QtWidgets.QButtonGroup()
        self.mp_group.addButton(self.mp_thread)
        self.mp_group.addButton(self.mp_multi)

        self.layout = QtWidgets.QFormLayout(self)
        self.layout.addRow(self.devicetree)
        self.layout.addRow(self.deviceinfo)
        self.layout.addRow(self.mp_label)
        self.layout.addRow(self.mp_thread, self.mp_multi)
        self.layout.addRow(self.devnamelabel, self.devname)
        self.layout.addRow(self.addbtn)

        self.setWindowIcon(QtGui.QIcon(_icon_file))
        self.setWindowTitle("redvypr devices")

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
        print('new',new,old)
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
        """
        """
        funcname = __name__ + 'add_device_click():'
        logger.debug(funcname)
        getSelected = self.devicetree.selectedItems()
        if getSelected:
            item = getSelected[0]

        if item.devdict is not None:
            devicemodulename = item.devdict['name']
            thread = self.mp_thread.isChecked()
            config = {'loglevel':logger.level}
            devname = str(self.devname.text())
            if len(devname) > 0:
                config['name'] = devname
            deviceconfig = {'config':config}
            print('devicemodulename',devicemodulename)
            print('Adding device, config',deviceconfig)
            if self.redvypr is not None:
                self.redvypr.add_device(devicemodulename=devicemodulename, thread=thread, deviceconfig=deviceconfig)
            self.devname.clear()
            # Update the name
            #self.__device_name()
        else:
            print('Not a device')



class redvyprSubscribeWidget(QtWidgets.QWidget):
    """ A widget that lists all devices and datastreams as potential inputs and a second list of all the subscriptions
     of the

    """

    def __init__(self, redvypr=None, device=None):
        """

        Args:
            redvypr:
            device:
        """
        super(redvyprSubscribeWidget, self).__init__()
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

        self.device_label = QtWidgets.QLabel('Device')
        self.device_label.setAlignment(QtCore.Qt.AlignCenter)
        self.dataprovider_label = QtWidgets.QLabel('Data providing devices')
        self.dataprovider_label.setAlignment(QtCore.Qt.AlignCenter)
        self.subscribe_label = QtWidgets.QLabel('Subscribed')
        self.subscribe_label.setAlignment(QtCore.Qt.AlignCenter)

        self.devices_listallout = QtWidgets.QTreeWidget()  # All dataproviding devices
        self.devices_listallout.setColumnCount(2)
        self.devices_listallout.setHeaderHidden(True)
        self.devices_listallout.currentItemChanged.connect(self.__update_device_choice__)

        self.devices_listcon = QtWidgets.QListWidget()  # The devices a connection is to be defined
        self.devices_listcon.itemClicked.connect(self.itemcon_clicked)
        self.devices_listcon.itemDoubleClicked.connect(self.itemcon_dclicked)

        self.devices_listallsub = QtWidgets.QListWidget()  # The subscriptions of the device
        self.devices_listallsub.itemClicked.connect(self.__itemsubscribed_clicked__)

        self.subscribe_edit = LineEditFocus()
        self.subscribe_edit.focusInSignal.connect(self.__focus_in__)
        self.subscribe_edit.focusOutSignal.connect(self.__focus_out__)

        self.__commitbtn = QtWidgets.QPushButton('Subscribe')
        self.__commitbtn.clicked.connect(self.commit_clicked)
        self.__commitbtn.setEnabled(False)

        #layout.addWidget(lab, 0, 1,1,3)
        layout.addWidget(lab, 0, 0,1,3)
        layout.addWidget(self.device_label, 1, 0)
        layout.addWidget(self.devices_listcon, 2, 0)
        layout.addWidget(self.subscribe_label, 1, 1)
        layout.addWidget(self.devices_listallsub, 2, 1)
        layout.addWidget(self.dataprovider_label, 1, 2)
        layout.addWidget(self.devices_listallout, 2, 2)
        layout.addWidget(self.subscribe_edit, 3, 0, 1, 3)
        layout.addWidget(self.__commitbtn,4,0,1,3)

        if (len(self.devices) > 0):
            self.update_list(device)

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

    def __update_device_choice__(self,newitem,olditem):
        """
        A device was clicked, update all buttons
        Args:
            item:

        Returns:

        """
        if newitem is not None:
            devstr = newitem.redvypr_address.get_str()

            try:
                subscribed = newitem.subscribed
            except:
                subscribed = False

            if(subscribed):
                self.__commitbtn.setText('Unsubscribe')
                self.__commitbtn.__status__ = 'remove'
                self.__commitbtn.setEnabled(True)
                self.__commitbtn.redvypr_addr_remove = devstr
            else:
                self.subscribe_edit.setText(devstr)
                print(devstr)
                print('Item',newitem.text(0))
                self.__commitbtn.setText('Subscribe')
                self.__commitbtn.__status__ = 'add'
                self.__commitbtn.setEnabled(True)
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
        self.devices_listallout.clear()
        self.devices_listallsub.clear()
        self.devices_listcon.clear()
        self.device = device

        if (len(self.devices) > 0):
            root = self.devices_listallout.invisibleRootItem()
            # self.devices_listcon.addItem(str(device))
            data_provider_all = self.redvypr.get_devices(publishes=True)
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
                            devaddress_redvypr = data_packets.redvypr_address(devaddress)
                            subscribed = False
                            for a in self.device.subscribed_addresses:
                                subscribed = a in devaddress_redvypr
                                if subscribed:
                                    break

                            itmf = QtWidgets.QTreeWidgetItem([devaddress, ''])
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

            self.devices_listallout.expandAll()
            self.devices_listallout.resizeColumnToContents(0)

            # Fill list of devices subscribing
            devitm = None
            if True:
                # connecting devices
                for s in self.devices:
                    sen = s['device']
                    itm = QtWidgets.QListWidgetItem(sen.name)
                    itm.device = sen
                    self.devices_listcon.addItem(itm)
                    if (sen == device):
                        devitm = itm

                if(devitm is not None):
                    self.devices_listcon.setCurrentItem(devitm)

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


        getSelected = self.devices_listallout.selectedItems()
        if getSelected:
            itm = getSelected[0]
            try:
                device = itm.device
                devicename = device.name
            except:
                device = None
                devicename = ''

            # Get subscriber
            subscriber_item  = self.devices_listcon.currentItem()
            subscriber = subscriber_item.device
            try:
                address_forwarded = itm.address_forwarded
            except:
                address_forwarded = None


    def disconnect_clicked(self):
        logger.debug('Disconnect')

    def itemcon_clicked(self, item):
        # Update the connection list
        self.update_list(item.device)

    def itemcon_dclicked(self, item):
        if (item.isSelected()):
            item.setSelected(False)

class deviceinfoWidget(QtWidgets.QWidget):
    """ A widget to display the general info of a device
    """
    device_start = QtCore.pyqtSignal(dict) # Signal requesting a start of the device (starting the thread)
    device_stop  = QtCore.pyqtSignal(dict) # Signal requesting a stop of device
    connect      = QtCore.pyqtSignal(dict) # Signal requesting a change of the connection

    def __init__(self,devicedict,redvyprwidget):
        super(deviceinfoWidget, self).__init__()
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
        self.conbtn = QtWidgets.QPushButton("Connections")
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
class redvypr_deviceInfoWidget(QtWidgets.QWidget):
    def __init__(self, device=None):
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.device = device
        self.layout = QtWidgets.QGridLayout(self)
        self.infowidget       = QtWidgets.QPlainTextEdit()
        self.infowidget.setReadOnly(True)
        self.layout.addWidget(self.infowidget,0,0)

        self.updatetimer = QtCore.QTimer()
        self.updatetimer.timeout.connect(self.__update_info)
        self.updatetimer.start(500)

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








