import serial
import serial.tools
import os
import time
import datetime
import logging
import queue
import sys
import yaml
import pkg_resources
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np
import inspect
import threading
import multiprocessing
import redvypr.devices as redvyprdevices
from redvypr.data_packets import device_in_data, get_devicename_from_data
from redvypr.utils import addrm_device_as_data_provider,get_data_receiving_devices,get_data_providing_devices
import socket
import argparse
import importlib.util
import glob
import pathlib
import signal
import uuid
from redvypr.version import version
import redvypr.files as files

_logo_file = files.logo_file
_icon_file = files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr')
logger.setLevel(logging.DEBUG)


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
        print('Disconnect')

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
        self.layout2.addWidget(QtWidgets.QLabel('Name' + ' Device #' + str(devicedict['device'].numdevice)),0,0)        
        self.layout2.addWidget(self.namelabel,1,0)
        self.layout.addLayout(self.layout2)
        self.layout.addStretch()
        self.layout.addWidget(self.logwidget)
        self.layout.addWidget(self.viewbtn)
        self.layout.addWidget(self.infobtn)         
        self.layout.addWidget(self.renbtn)
        self.layout.addWidget(self.conbtn)
        self.layout.addWidget(self.rembtn)
        self.layout.addWidget(self.startbtn)
        
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
            self.device_stop.emit(self.devicedict)
        else:
            self.device_start.emit(self.devicedict)

    def thread_status(self,statusdict):
        """ Function regularly called by redvypr to update the thread status
        """
        status = statusdict['threadalive']
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
    
    
class displayDeviceWidget_standard(QtWidgets.QWidget):
    """ Widget is plotting realtimedata using the pyqtgraph functionality
    This widget can be configured with a configuration dictionary 
    """
    def __init__(self,device=None,tabwidget=None):
        """
        device [optional]
        tabwidget [optional]
        
        """
        funcname = __name__ + '.start()'
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QGridLayout(self)
        self.device = device
        # A timer that is regularly calling the device.status function
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_status)
        self.statustimer.start(2000)

        self.text     = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)
        layout.addWidget(self.text,0,0)

                
    def thread_status(self,status):
        """ This function is regularly called by redvypr whenever the thread is started/stopped
        """
        pass        
        #self.update_buttons(status['threadalive'])
        
    def update_status(self):
        """
        """
        funcname = __name__ + 'update_status():'
        try:
            statusdata = self.device.status()
            #print(funcname + str(statusdata))
            self.text.clear()
            self.text.insertPlainText(str(statusdata))
        except Exception as e:
            #logger.debug(funcname + str(e) + 'hallo')
            pass

        
    def update(self,data):
        """ 
        """
        funcname = __name__ + '.update()'
        tnow = time.time()
        #print('got data',data)
        
        devicename = data['device']
        # Only plot the data in intervals of dt_update length, this prevents high CPU loads for fast devices
        update = (tnow - self.config['last_update']) > self.config['dt_update']
        
        if(update):
            self.config['last_update'] = tnow



#
class redvypr_devicelist_widget(QtWidgets.QWidget):
    """ Widget that lets the user choose available subscribed devices (if device is not None) and datakeys. This
    devicelock: The user cannot change the device anymore 
    """
    device_name_changed        = QtCore.pyqtSignal(str) # Signal notifying if the device path was changed
    apply                      = QtCore.pyqtSignal(dict) # Signal notifying if the Apply button was clicked
    datakey_name_changed       = QtCore.pyqtSignal(str) # Signal notifying if the datakey has changed
    def __init__(self,redvypr,device=None,devicename_highlight=None,datakey=None,deviceonly=False,devicelock=False,subscribed_only=True):
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
        self.layout = QtWidgets.QVBoxLayout(self)
        self.deviceonly = deviceonly
        if(devicename_highlight == None):
            self.devicename_highlight = 'Na'
        else:
            self.devicename_highlight = devicename_highlight

        self.device = device 
        flag_all_devices = (self.device == None) or (subscribed_only == False) # All devices or only one device?
        try:  
            self.devicename = device.name
        except:
            self.devicename = device
        if(device is not None):
            self.devicenamelabel = QtWidgets.QLabel('Device: ' + self.devicename)
            self.layout.addWidget(self.devicenamelabel)
        else:
            self.devicename = ''

        self.deviceavaillabel = QtWidgets.QLabel('Available devices')
        self.layout.addWidget(self.deviceavaillabel)
        
        self.devicelist  = QtWidgets.QListWidget() # List of available devices
        
        self.devicecustom = QtWidgets.QLineEdit()
        self.devicecustom.textChanged[str].connect(self.devicecustom_changed)
        self.layout.addWidget(self.devicelist)
        self.layout.addWidget(self.devicecustom)
        # The datakeys
        if(deviceonly == False):
            self.datakeylist = QtWidgets.QListWidget() # List of available datakeys
            self.devicedatakeyslabel = QtWidgets.QLabel('Data keys of device')
            self.layout.addWidget(self.devicedatakeyslabel)        
            self.layout.addWidget(self.datakeylist)
            self.datakeycustom = QtWidgets.QLineEdit()
            self.layout.addWidget(self.datakeycustom)
            self.datastreamcustom = QtWidgets.QLineEdit()
            self.layout.addWidget(self.datastreamcustom)
            self.datakeylist.itemDoubleClicked.connect(self.datakey_clicked) # TODO here should by an apply signal emitted
            self.datakeylist.currentItemChanged.connect(self.datakey_clicked)

        self.buttondone = QtWidgets.QPushButton('Apply')
        self.buttondone.clicked.connect(self.done_clicked)
        self.layout.addWidget(self.buttondone)                

        devicelist = []
        self.datakeylist_subscribed = {}
        
        #
        if(subscribed_only):
            data_providing_devicenames = self.redvypr.get_data_providing_devicenames(device=device)
        else:
            data_providing_devicenames = self.redvypr.get_data_providing_devicenames(None)
            
        print('data providing devicenames',data_providing_devicenames)
        #
        # Add devices to show
        print('Devices',self.redvypr.devices)
        for devname in data_providing_devicenames:
            devdict = self.redvypr.get_devicedict_from_str(devname)
            print('Devname',devname,'devdict',devdict)
            if(devname != self.devicename):
                devicelist.append(str(devname))
                
                
        # Populate devices
        for devname in devicelist:
            self.devicelist.addItem(devname)
            
        self.devicelist.itemDoubleClicked.connect(self.device_clicked) # TODO here should by an apply signal emitted
        self.devicelist.currentItemChanged.connect(self.device_clicked)
        if(len(devicelist)>0):
            self.device_clicked(self.devicelist.item(0))
        # Update the custom text with the given devicename and check if it exists in the item list
        # If its existing update the datakeylist
        self.devicecustom.setText(str(self.devicename_highlight))
        
        for i in range(self.devicelist.count()-1):
            if(self.devicelist.item(i).text() == self.devicename_highlight):
                self.devicelist.setCurrentItem(self.devicelist.item(i))
                #self.device_clicked(self.devicelist.item(i)) 
                break 
            
        # Update the datakeys of the device    
        if(deviceonly == False):
            self.update_datakeylist(self.devicename_highlight)
        

        if(devicelock):
            self.devicelist.setEnabled(False)
            
        
    def update_datakeylist(self,devicename):
        """ Update the datakeylist whenever the device was changed
        """
        self.datakeylist.clear()
        
        try:
            self.datakeys    = self.redvypr.get_datakeys(devicename)
            self.datastreams = self.redvypr.get_datastreams(devicename)
        except:
            self.datakeys    = []
            self.datastreams = []
        for key in self.datakeys:
            # If a conversion to an int works, make quotations around it, otherwise leave it as it is
            try:
                keyint = int(key)
                keystr = '"' + key + '"'
            except:
                keystr = key
                    
            self.datakeylist.addItem(keystr)


    def done_clicked(self):
        devicename  = self.devicecustom.text()
        if(self.deviceonly == False):
            datakey    = self.datakeycustom.text()
            datastream = self.datastreamcustom.text()
        else:
            datakey    = None
            datastream = None
        
        signal_dict = {'devicename':devicename,'datakey':datakey,'datastream':datastream}
        self.apply.emit(signal_dict)    
        self.close()
        
    def device_clicked(self,item):
        """ If the device was changed, update the datakeylist and emit a signal
        """
        funcname       = self.__class__.__name__ + '.device_clicked():'    
        logger.debug(funcname)                            
        devicename = item.text()
        #print('Click',item.text())
        if(self.deviceonly == False):
            self.devicedatakeyslabel.setText('Data keys of device ' + str(devicename))
            self.update_datakeylist(devicename)
        self.devicecustom.setText(str(devicename))        
        self.device_name_changed.emit(item.text())

    def datakey_clicked(self,item):
        index      = self.datakeylist.currentRow()
        #datakey    = item.text()
        datakey = self.datakeys[index]
        datastream = self.datastreams[index]
        self.datakeycustom.setText(str(datakey))
        self.datastreamcustom.setText(str(datastream))
        
        self.datakey_name_changed.emit(item.text())        

        
    def devicecustom_changed(self,text):
        """ TODO
        """
        pass
        #self.device_name_changed.emit(str(text))                    
         

                

