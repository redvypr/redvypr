import copy
import time
import logging
import sys
import yaml
from PyQt5 import QtWidgets, QtCore, QtGui
from redvypr.utils import addrm_device_as_data_provider,get_data_receiving_devices,get_data_providing_devices,configtemplate_to_dict
from redvypr.device import redvypr_device
from redvypr.widgets.gui_config_widgets import redvypr_ip_widget, configQTreeWidget, configWidget
from redvypr.widgets.standard_device_widgets import displayDeviceWidget_standard, redvypr_deviceInitWidget
from redvypr.widgets.datastream_widget import datastreamWidget
import redvypr.utils
import redvypr.files as files

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


class redvyprConnectWidget2(QtWidgets.QWidget):
    """A widget that lets the user connect the input and output queues of
    the devices with each other

    """

    def __init__(self, redvypr=None, device=None):
        """

        Args:
            redvypr:
            device:
        """
        super(redvyprConnectWidget2, self).__init__()
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

        layout = QtWidgets.QGridLayout(self)

        font = QtGui.QFont('Arial', 20)
        font.setBold(True)
        lab = QtWidgets.QLabel('Connecting devices for data exchange')
        lab.setFont(font)

        self.device_label = QtWidgets.QLabel('Device')
        self.dataprovider_label = QtWidgets.QLabel('Data providing devices')

        self.devices_listallout = QtWidgets.QTreeWidget()  # All dataproviding devices
        self.devices_listallout.setColumnCount(2)
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

        layout.addWidget(lab, 0, 1,1,2)
        layout.addWidget(self.device_label, 1, 0)
        layout.addWidget(self.devices_listcon, 2, 0)
        layout.addWidget(self.devices_listallsub, 2, 1)
        layout.addWidget(self.dataprovider_label, 1, 2)
        layout.addWidget(self.devices_listallout, 2, 2)
        layout.addWidget(self.subscribe_edit, 3, 0, 1, 3)
        layout.addWidget(self.__commitbtn,4,0,1,2)

        if (len(self.devices) > 0):
            self.update_list(device)

    def __itemsubscribed_clicked__(self,item):
        self.__commitbtn.setText('Remove')
        self.__commitbtn.setEnabled(True)
        self.__commitbtn.__status__ = 'remove'
        self.__commitbtn.redvypr_addr_remove = item.redvypr_addr

    def __focus_in__(self):
        print('Focus in')
        self.__commitbtn.setText('Subscribe')
        self.__commitbtn.__status__ = 'add'
        self.__commitbtn.setEnabled(True)

    def __focus_out__(self):
        print('Focus out')
        #self.__commitbtn.__status__ = None

    def __devices_connected__(self, dev1=None, dev2=None):
        print('Devices have been connected',dev1,dev2)
        self.update_list(self.device)

    def __update_device_choice__(self,newitem,olditem):
        """
        A device was clicked, update all buttons
        Args:
            item:

        Returns:

        """
        if newitem is not None:
            devstr = newitem.device.address_str
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
            data_provider_all = self.redvypr.get_data_providing_devices()
            font1 = QtGui.QFont('Arial')
            font1.setBold(True)
            font0 = QtGui.QFont('Arial')


            # Fill the qtreewidget
            print('data provider',data_provider_all)
            if (data_provider_all is not None):
                for dev in data_provider_all:
                    if dev == self.device:
                        continue

                    # Check if the device is already subscribed
                    subscribed = False
                    for a in self.device.subscribed_addresses:
                        print('Test', a, dev.address)
                        subscribed = dev.address == a
                        print('Test', a, dev.address,subscribed)
                        if subscribed:
                            break

                    itm = QtWidgets.QTreeWidgetItem([dev.name, ''])
                    itm.device = dev
                    if subscribed:
                        status = 'subscribed'
                        itm.setFont(0,font1)
                        itm.subscribed = True
                    else:
                        itm.setFont(0, font0)
                        itm.subscribed = False

                    root.addChild(itm)
                    # Check for forwarded devices
                    if False:
                        devs_forwarded = dev.get_data_provider_info()
                        for devaddress in devs_forwarded.keys():
                            print(devs_forwarded)
                            print(devaddress)
                            print('stat',devs_forwarded[devaddress]['_redvypr'])
                            itmf = QtWidgets.QTreeWidgetItem([devaddress, ''])
                            itmf.device = dev
                            itmf.address_forwarded = devaddress
                            try:
                                itmf.subscribed = devs_forwarded[devaddress]['_redvypr']['subscribed']
                                itmf.subscribeable = devs_forwarded[devaddress]['_redvypr']['subscribeable']
                            except:
                                itmf.subscribed = False
                                itmf.subscribeable = False

                            if(itmf.subscribed):
                                itmf.setFont(0, font1)
                            else:
                                itmf.setFont(0, font0)

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
                    sstr = str(s)
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


class redvyprConnectWidget(QtWidgets.QWidget):
    """A widget that lets the user connect the input and output queues of
the devives with each other

    """
    def __init__(self,devices=None,device=None):
        super(redvyprConnectWidget, self).__init__()
        if(len(devices) > 0):    
            if(device == None): # Take the first one
                device = devices[0]['device']

        # Set icon
        self.setWindowIcon(QtGui.QIcon(_icon_file))
        self.devices = devices
        layout = QtWidgets.QVBoxLayout(self)
        lab = QtWidgets.QLabel('Connect datastreams to device:')

        lablayout = QtWidgets.QHBoxLayout()
        lablayout.addStretch()
        lablayout.addWidget(lab)
        lablayout.addStretch()


        self.device_label = QtWidgets.QLabel('Device')
        devlablayout = QtWidgets.QHBoxLayout()
        devlablayout.addStretch()
        devlablayout.addWidget(self.device_label)
        devlablayout.addStretch()                        
        font = QtGui.QFont('Arial', 20)
        font.setBold(True)
        self.device_label.setFont(font)
        layout.addLayout(lablayout)
        layout.addLayout(devlablayout)

        conwidget  = QtWidgets.QWidget(self)
        conlayout = QtWidgets.QHBoxLayout(conwidget)
        self.devices_listallout= QtWidgets.QListWidget() # All dataproviding devices
        self.devices_listallin = QtWidgets.QListWidget() # All datareceiving devices
        self.devices_listin    = QtWidgets.QListWidget() # All connected datareceiving devices
        self.devices_listout   = QtWidgets.QListWidget() # All connected dataproviding devices
        self.devices_listcon   = QtWidgets.QListWidget() # The devices a connection is to be defined
        self.devices_listcon.itemClicked.connect(self.itemcon_clicked)
        self.devices_listcon.itemDoubleClicked.connect(self.itemcon_dclicked)                

        self.__commitbtn  = QtWidgets.QPushButton('Commit')
        self.__commitbtn.clicked.connect(self.commit_clicked)

        self.arroutleft = QtWidgets.QToolButton()
        self.arroutleft.setArrowType(QtCore.Qt.LeftArrow)
        self.arroutleft.clicked.connect(self.addrm_out)
        self.arroutright = QtWidgets.QToolButton()
        self.arroutright.setArrowType(QtCore.Qt.RightArrow)
        self.arroutright.clicked.connect(self.addrm_out)        
        self.arrinleft = QtWidgets.QToolButton()
        self.arrinleft.setArrowType(QtCore.Qt.LeftArrow)
        self.arrinleft.clicked.connect(self.addrm_in)                
        self.arrinright = QtWidgets.QToolButton()
        self.arrinright.setArrowType(QtCore.Qt.RightArrow)
        self.arrinright.clicked.connect(self.addrm_in)                        
        arroutlayout = QtWidgets.QVBoxLayout()
        arroutlayout.addWidget(self.arroutleft)
        arroutlayout.addWidget(self.arroutright)
        arrinlayout = QtWidgets.QVBoxLayout()
        arrinlayout.addWidget(self.arrinleft)
        arrinlayout.addWidget(self.arrinright)                

        # Subscribe devices all
        devicesoutlayout = QtWidgets.QVBoxLayout()
        devicesoutlayout.addWidget(QtWidgets.QLabel('Subscribable devices'))
        devicesoutlayout.addWidget(self.devices_listallout)
        conlayout.addLayout(devicesoutlayout)
        conlayout.addLayout(arroutlayout)
        # Subscribed devices of the choosen device
        devicessubscribedlayout = QtWidgets.QVBoxLayout()
        devicessubscribedlayout.addWidget(QtWidgets.QLabel('Subscribed devices'))        
        devicessubscribedlayout.addWidget(self.devices_listout)
        conlayout.addLayout(devicessubscribedlayout)
        # The device to choose
        convlayout = QtWidgets.QVBoxLayout()
        convlayout.addWidget(QtWidgets.QLabel('Device'))        
        convlayout.addWidget(self.devices_listcon)     
        #conlayout.addWidget(self.devices_listcon)
        conlayout.addLayout(convlayout)
        # Published devices
        devicespublishedlayout = QtWidgets.QVBoxLayout()
        devicespublishedlayout.addWidget(QtWidgets.QLabel('Publishing to devices'))        
        devicespublishedlayout.addWidget(self.devices_listin)
        conlayout.addLayout(devicespublishedlayout)
        conlayout.addLayout(arrinlayout)
        # All devices data can be published to
        devicespublishablelayout = QtWidgets.QVBoxLayout()
        devicespublishablelayout.addWidget(QtWidgets.QLabel('Data receivable devices'))        
        devicespublishablelayout.addWidget(self.devices_listallin)
        conlayout.addLayout(devicespublishablelayout)
        
        layout.addWidget(conwidget)
        layout.addWidget(self.__commitbtn)


        if(len(devices) > 0):    
            self.update_list(device)
        
        
    def addrm_out(self):
        """ Connecting publishing devices with device
        """
        funcname = 'addrm_in'
        logger.debug(funcname)        
        button = self.sender()
        if(button == self.arroutleft):
            #print('remove')
            ind = self.devices_listout.currentRow()
            self.devices_listout.takeItem(ind)
            
        if(button == self.arroutright):
            #print('add')
            itmadd = self.devices_listallout.currentItem()
            sen = itmadd.device
            itm = QtWidgets.QListWidgetItem(sen.name)
            itm.device = sen
            self.devices_listout.addItem(itm)            
            #print('add',itmadd.device)
            #self.devices_listout.addItem(itmadd.text())
            
    def addrm_in(self):
        """ Connecting receiving devices with dataqueue of this device
        """
        funcname = 'addrm_in'
        logger.debug(funcname)
        button = self.sender()
        if(button == self.arrinright):
            logger.debug(funcname + ': remove')
            ind = self.devices_listin.currentRow()
            self.devices_listin.takeItem(ind)
            
        elif(button == self.arrinleft):
            logger.debug(funcname + ': add')            
            itmadd = self.devices_listallin.currentItem()
            sen = itmadd.device
            itm = QtWidgets.QListWidgetItem(sen.name)
            itm.device = sen
            self.devices_listin.addItem(itm)
            

    def commit_clicked(self):
        """ Apply changes to the publishing/receiving devices
        """
        funcname = 'commit_clicked'
        logger.debug(funcname)
        outdevices = []
        # Add device as receiver for publishing devices
        for inditm in range(self.devices_listout.count()):
            itm = self.devices_listout.item(inditm)
            sen = itm.device
            outdevices.append(sen)
            logger.debug(funcname + ':' + 'add as publisher:' + str(sen))            
            addrm_device_as_data_provider(self.devices,sen,self.device,remove=False)

        # Check if there are devices to be removed
        data_provider = get_data_providing_devices(self.devices,self.device)
        for sen in data_provider:
            device = sen['device']
            if(device in outdevices):
                pass
            else:
                logger.debug(funcname + ': Removing device {:s} as a data publisher for {:s} '.format(self.device.name,device.name))
                addrm_device_as_data_provider(self.devices,device,self.device,remove=True)
                

        # Add device as publisher for receiving devices
        indevices = []        
        for inditm in range(self.devices_listin.count()):
            itm = self.devices_listin.item(inditm)
            sen = itm.device
            indevices.append(sen)
            logger.debug(funcname + ':' + 'add as receiver:' + str(sen))            
            addrm_device_as_data_provider(self.devices,self.device,sen,remove=False)

        # Check if there are devices to be removed
        data_receiver = get_data_receiving_devices(self.devices,self.device)
        for sen in data_receiver:
            device = sen['device']
            if(device in indevices):
                pass
            else:
                logger.debug(funcname + ': Removing device {:s} as a data receiver from {:s} '.format(self.device.name,device.name))                
                addrm_device_as_data_provider(self.devices,self.device,device,remove=True)            
            
            
    def update_list(self,device):
        """ Update the list
        """
        
        funcname = __name__ + '.update_list()'
        logger.debug(funcname + ':update_list:' + str(device))                        
        self.devices_listallin.clear()
        self.devices_listallout.clear()        
        self.devices_listin.clear()
        self.devices_listout.clear()
        self.devices_listcon.clear()
        self.device = device
        self.device_label.setText(device.name)
        
        if(len(self.devices) > 0):
            #self.devices_listcon.addItem(str(device))
            data_provider = get_data_providing_devices(self.devices,device)
            data_receiver = get_data_receiving_devices(self.devices,device)
            if(data_provider is not None):
                for s in data_provider:
                    sen = s['device']
                    itm = QtWidgets.QListWidgetItem(sen.name)
                    itm.device = sen            
                    self.devices_listout.addItem(itm)

            if(data_receiver is not None):                    
                for s in data_receiver:
                    sen = s['device']
                    itm = QtWidgets.QListWidgetItem(sen.name)
                    itm.device = sen
                    self.devices_listin.addItem(itm)


            # connecting devices
            for s in self.devices:
                sen = s['device']
                itm = QtWidgets.QListWidgetItem(sen.name)
                itm.device = sen            
                self.devices_listcon.addItem(itm)
                if(sen == device):
                    self.devices_listcon.setCurrentItem(itm)

            # data receiving devices
            if(device.publish):
                self.devices_listin.setEnabled(True)
                self.devices_listallin.setEnabled(True)
                for s in self.devices:
                    sen = s['device']
                    if(sen.subscribe == False):
                        continue
                    if(device == sen): # Dont list the device itself
                        continue                    
                           
                    itm = QtWidgets.QListWidgetItem(sen.name)
                    itm.device = sen            
                    self.devices_listallin.addItem(itm)
                
            else:
                self.devices_listin.setEnabled(False)
                self.devices_listallin.setEnabled(False)
                
            # data providing devices
            if(device.subscribe):
                self.devices_listout.setEnabled(True)
                self.devices_listallout.setEnabled(True)
                for s in self.devices:
                    sen = s['device']
                    if(sen.publish == False):
                        continue
                    if(device == sen): # Dont list the device itself
                        continue
                    
                    itm = QtWidgets.QListWidgetItem(sen.name)
                    itm.device = sen            
                    self.devices_listallout.addItem(itm)
            else:
                self.devices_listout.setEnabled(False)                
                self.devices_listallout.setEnabled(False)                    
                    
            
    def disconnect_clicked(self):
        logger.debug('Disconnect')

    def itemcon_clicked(self,item):
        # Update the connection list 
        self.update_list(item.device)

    def itemcon_dclicked(self,item):
        if(item.isSelected()):
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








