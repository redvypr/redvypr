import copy

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
from redvypr.utils import addrm_device_as_data_provider,get_data_receiving_devices,get_data_providing_devices,configtemplate_to_dict
from redvypr.device import redvypr_device
import redvypr.utils
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


#
#
class redvypr_ip_widget(QtWidgets.QWidget):
    """ Widget that shows the IP and network devices of the host
    """
    def __init__(self):
        """
        """
        funcname = __name__ + '.__init__():'
        super(QtWidgets.QWidget, self).__init__()
        #self.setWindowIcon(QtGui.QIcon(_icon_file))
        #self.table = QtWidgets.QTableWidget()
        self.show()
         

                
#
#
#
class redvypr_dictionary_widget(QtWidgets.QWidget):
    """ Widget that lets the user interact with a configuration dictionary
    """
    def __init__(self,dictionary):
        """
        """
        funcname = __name__ + '.__init__():'
        super(QtWidgets.QWidget, self).__init__()
        self.setWindowIcon(QtGui.QIcon(_icon_file))
        self.dictionary = dictionary
        self.dictionary_local = copy.deepcopy(dictionary)
        logger.debug(funcname)
        self.layout = QtWidgets.QGridLayout(self)
        dictreewidget = redvypr_dictionary_tree(data=self.dictionary_local)
        self.layout.addWidget(dictreewidget)





class redvypr_qtreewidgetitem(QtWidgets.QTreeWidgetItem):
    """
    Custom QTreeWidgetItem class that keeps a record of the data
    dict
    list
    set (replace by list*?)
    """

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        print('Hallo!')

    def setText(self,*args,**kwargs):
        super().setText(*args,**kwargs)
        print('Text')
    def setData(self,*args,**kwargs):
        super().setData(*args,**kwargs)
        print('Data')


#
#
#
#
#
class redvypr_dictionary_tree(QtWidgets.QTreeWidget):
    """ Qtreewidget that display and modifies the configuration of the calibration config
    """

    def __init__(self, data={}, dataname='data',editable=True):
        funcname = __name__ + '.__init__():'
        super().__init__()

        logger.debug(funcname + str(data))
        # make only the first column editable
        #self.setEditTriggers(self.NoEditTriggers)
        self.datatypes = [['int', int], ['float', float], ['str', str],['list',list],['dict',dict]] # The datatypes
        self.datatypes_dict = {} # Make a dictionary out of it, thats easier to reference
        for d in self.datatypes:
            self.datatypes_dict[d[0]] = d[1]
        self.header().setVisible(False)
        self.data = data
        self.dataname = dataname
        self.olddata = []
        self.numhistory = 100
        # Create the root item
        self.root = self.invisibleRootItem()
        #self.root.__data__ = data
        self.root.__dataindex__ = ''
        self.root.__datatypestr__ = ''
        self.root.__parent__ = None
        self.setColumnCount(3)
        self.create_qtree()
        print('Again check if update works')
        self.create_qtree()
        self.itemExpanded.connect(self.resize_view)
        self.itemCollapsed.connect(self.resize_view)
        # Connect edit triggers
        self.itemDoubleClicked.connect(self.checkEdit)
        self.itemChanged.connect(self.item_changed) # If an item is changed
        self.currentItemChanged.connect(self.current_item_changed)  # If an item is changed

        # Connect the contextmenu
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.menuContextTree)

    def rawcopy(self,data):
        """
        Functions that simply returns the input data, used as the basic field conversion function
        """
        return data

    def menuContextTree(self, point):
        # Infos about the node selected.
        index = self.indexAt(point)

        if not index.isValid():
            return

        item = self.itemAt(point)
        name = item.text(0)  # The text of the node.

        # We build the menu.
        datatype = item.__datatypestr__
        if ((datatype == 'list' or (datatype == 'dict'))):
            menu = QtWidgets.QMenu('Edit dict entry')
            action_add = menu.addAction("Add item")
            action_add.__item__ = item
            action_add.triggered.connect(self.add_rm_item_menu)
        else:
            menu = QtWidgets.QMenu('Edit dict entry')
            action_edit = menu.addAction("Edit item")
            action_edit.__item__ = item
            action_edit.triggered.connect(self.add_rm_item_menu)

        action_del = menu.addAction("Delete item")
        action_del.__item__ = item
        action_del.triggered.connect(self.add_rm_item_menu)
        menu.exec_(self.mapToGlobal(point))

    def seq_iter(self,obj):
        if isinstance(obj, dict):
            return obj
        elif isinstance(obj, list):
            return range(0,len(obj))
        else:
            return None

    def create_item(self, index, data, parent):
        """
        Creates recursively qtreewidgetitems. If the item to be created is a sequence (dict or list), it calls itself as often as it finds a real value
        Args:
            index:
            data:
            parent:

        Returns:

        """
        sequence = self.seq_iter(data)
        typestr = data.__class__.__name__
        if(sequence == None): # Check if we have an item that is something with data (not a list or dict)
            item = QtWidgets.QTreeWidgetItem([str(index), str(data),typestr])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)  # editable
            item.__data__         = data
            item.__dataindex__    = index
            item.__datatypestr__  = typestr
            item.__parent__       = parent
            index_child = self.item_is_child(parent, item)
            if  index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(item)
            else: # Update the data (even if it hasnt changed
                parent.child(index_child).setText(1,str(data))

        else:
            if(index is not None):
                indexstr = index
            newparent = QtWidgets.QTreeWidgetItem([str(index), '',typestr])
            newparent.__data__         = data
            newparent.__dataindex__    = index
            newparent.__datatypestr__  = typestr
            newparent.__parent__       = parent
            index_child = self.item_is_child(parent, newparent)
            if index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(newparent)
            else:
                newparent = parent.child(index_child)

            for newindex in sequence:
                newdata = data[newindex]
                self.create_item(newindex,newdata,newparent)

    def item_is_child(self,parent,child):
        """
        Checks if the item is a child already

        Args:
            parent:
            child:

        Returns:

        """
        numchilds  = parent.childCount()
        #print('numchilds',numchilds,parent.text(0),parent)
        for i in range(numchilds):
            testchild = parent.child(i)
            #flag1 = testchild.__data__        == child.__data__
            flag1 = True
            flag2 = testchild.__dataindex__   == child.__dataindex__
            #flag3 = testchild.__datatypestr__ == child.__datatypestr__
            flag3 = True
            flag4 = testchild.__parent__      == child.__parent__

            #print('fdsfd',i,testchild.__data__,child.__data__)
            #print('flags',flag1,flag2,flag3,flag4)
            if(flag1 and flag2 and flag3 and flag4):
                #print('The same ...')
                return i

        return None


    def create_qtree(self, editable=True):
        """Creates a new qtree from the configuration and replaces the data in
        the dictionary with a configdata obejct, that save the data
        but also the qtreeitem, making it possible to have a synced
        config dictionary from/with a qtreewidgetitem. TODO: Worth to
        replace with a qviewitem?

        """
        funcname = __name__ + '.create_qtree():'
        logger.debug(funcname)
        self.blockSignals(True)
        if True:
            self.create_item(self.dataname,self.data,self.root)

        self.resizeColumnToContents(0)
        self.blockSignals(False)

    def checkEdit(self, item, column):
        """ Helper function that only allows to edit column 1
        """
        funcname = __name__ + '.checkEdit():'
        logger.debug(funcname + '{:d}'.format(column))

        if (column == 1) and (self.seq_iter(item.__data__) == None):
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)  # editable
        else:
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)  # not editable
            #self.edititem(item, column)

    def current_item_changed(self, current, previous):
        """ Save the data in the currently changed item, this is used to
        restore if newly entered data is not valid
        """
        #self.backup_data = current.text(1)
        item = current
        if(item is not None):
            if (item.parent() is not None):
                print(item.text(0), item.parent().text(0))


    def item_changed(self, item, column):
        """ Updates the dictionary with the changed data
        """
        funcname = __name__ + '.item_changed():'
        #logger.debug(funcname + 'Changed {:s} {:d} to {:s}'.format(item.text(0), column, item.text(1)))
        print(funcname + 'Changed {:s} {:d} to {:s}'.format(item.text(0), column, item.text(1)))

        index      = item.__dataindex__
        datatypestr= item.__datatypestr__
        parentdata = item.__parent__.__data__
        newdatastr = item.text(1)
        self.change_dictionary(item,column,newdatastr,index,datatypestr,parentdata)
        self.resizeColumnToContents(0)



    def change_dictionary(self, item, column, newdatastr, index, datatypestr, parentdata):
        """
        Changes the dictionary
        Args:
            index:
            datatype:
            parentdata:

        Returns:

        """
        olddata = parentdata[index]

        convfunc = str
        for dtype in self.datatypes:
            if(datatypestr == dtype[0]):
                convfunc = dtype[1]

        print('Column',column)
        # Try to convert the new data, if not possible, except take the old data
        try:
            self.update_history()
            parentdata[index] = convfunc(newdatastr)
        except:
            item.setText(column,str(olddata))

    def update_history(self):
        """
        Manages the history of self.data by updating a list with a deepcopy of prior versions.

        Returns:

        """
        funcname = __name__ + 'update_history()'
        logger.debug(funcname)
        if(len(self.olddata) > self.numhistory):
            logger.debug('History overflow')
            self.olddata.pop(0)

        olddata = copy.deepcopy(self.data)
        self.olddata.append(olddata)  # Make a backup of the data

    def add_rm_item_menu(self):
        funcname = __name__ + 'add_rm_item_menu()'
        sender = self.sender()
        print('Sender', )
        item = sender.__item__
        if ('add' in sender.text().lower()):
            logger.debug(funcname + ' Adding item')
            self.add_item_widget(item)
        if ('edit' in sender.text().lower()):
            logger.debug(funcname + ' Editing item')
            self.add_item_widget(item)
        elif ('del' in sender.text().lower()):
            logger.debug(funcname + ' Deleting item')
            self.rm_item_widget(item)

    def rm_item_widget(self, item):
        """
        Remove item from qtreewidget and from self.data dictionary
        Args:
            item:

        Returns:

        """
        funcname = __name__ + 'rm_item_widget()'
        if True: # Removing item
            index = item.__parent__.indexOfChild(item)
            # Remove from data
            if(item.__parent__ is not self.root):
                parentdata = item.__parent__.__data__
                parentdata.pop(item.__dataindex__)
                # Remove from qtreewidget
                item.__parent__.takeChild(index)
                print('data',self.data)


    def add_item_widget(self, item):
        """
        Widget for the user to add an item

        Returns:

        """
        self.__add_item_widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(self.__add_item_widget)
        self.__keyinput = QtWidgets.QLineEdit()
        self.__datainput = QtWidgets.QLineEdit()
        self.__datatypeinput = QtWidgets.QComboBox()
        listlist = ['list', 'dict']
        index_datatype = 0
        for i,d in enumerate(self.datatypes):
            if(item.__datatypestr__ == d[0]):
                index_datatype = i

            if(d[0] not in listlist):
                self.__datatypeinput.addItem(d[0])
            elif(item.__datatypestr__ in listlist):
                self.__datatypeinput.addItem(d[0])



        self.__datatypeinput.currentIndexChanged.connect(self.__combo_type_changed)
        self.__datatypeinput.__item__ = item
        self.__combo_type_changed() # Grey out unnecessary input lines
        self.__apply = QtWidgets.QPushButton('Apply')
        self.__apply.__item__ = item
        self.__cancel = QtWidgets.QPushButton('Cancel')
        self.__apply.clicked.connect(self.__add_item_widget_click)
        self.__cancel.clicked.connect(self.__add_item_widget_click)
        layout.addRow(QtWidgets.QLabel('Key'),self.__keyinput)
        layout.addRow(QtWidgets.QLabel('Value'), self.__datainput)
        layout.addRow(QtWidgets.QLabel('Datatype'), self.__datatypeinput)
        layout.addRow(self.__apply, self.__cancel)
        self.__add_item_widget.show()

    def __combo_type_changed(self):
        datatype = self.__datatypeinput.currentText()
        item = self.__datatypeinput.__item__
        self.__keyinput.setEnabled(False)
        self.__datainput.setEnabled(True)
        parenttype      = item.__parent__.__datatypestr__
        parenttype_list = (item.__parent__.__datatypestr__ == 'list')
        listlist = ['dict','list']
        datatype_item = item.__datatypestr__

        # Check if we have an item to edit, show the key
        if not(datatype_item in listlist):
            self.__keyinput.setText(str(item.__data__))
        # If an item is to be added to a dictionary, we need the key, otherwise not
        if(datatype_item == 'dict'):
            self.__keyinput.setEnabled(True)


    def __add_item_widget_click(self):
        sender = self.sender()
        funcname = __name__ + '__add_item_widget_click()'
        logger.debug(funcname)
        if(sender == self.__apply):
            logger.debug(funcname + ' Apply')
            item = sender.__item__
            newdata = self.__datainput.text()
            newdataindex = self.__keyinput.text()
            newdatatype = self.__datatypeinput.currentText()
            self.add_edit_item(item,newdata,newdataindex,newdatatype)
            print('Item',item)
        elif(sender == self.__cancel):
            logger.debug(funcname + ' Cancel')

        self.__add_item_widget.close()

    def add_edit_item(self, item, newdata, newdataindex, newdatatype):
        """
        Depending on the datatype of item either add newdata or modifies existing data
        Args:
            item:
            newdata:
            newdataindex:
            newdatatype:

        Returns:

        """
        funcname = __name__ + 'add_rm_item()'
        print('Hallo!',item)
        logger.debug(funcname + str(item.text(0)) + ' ' + str(item.text(1)))
        # Convert the text to the right format using the conversion function
        data = self.datatypes_dict[newdatatype](newdata)
        # Check how to append the data (depends on list or dict type of the item)
        if(item.__datatypestr__ == 'list'):
            logger.debug(funcname + ' Appending item to list')
            self.update_history()
            item.__data__.append(data)
            print('data', self.data)
            self.create_qtree()
        elif(item.__datatypestr__ == 'dict'):
            logger.debug(funcname + ' Adding item with key {:s} to dictionary'.format(newdataindex))
            self.update_history()
            item.__data__[newdataindex] = data
            print('data', self.data)
            self.create_qtree()
        else:
            print('Editing item',newdata,newdataindex,newdatatype)
            print('data before edit', self.data)
            index = item.__dataindex__
            item.__parent__.__data__[index] = newdata
            item.__datatypestr__ = newdatatype
            print('data edit', self.data)
            self.create_qtree()



    def resize_view(self):
        self.resizeColumnToContents(0)


#
#
#
#
#
class redvypr_data_tree(QtWidgets.QTreeWidget):
    """ Qtreewidget that display a data structure
    """

    def __init__(self, data={}, dataname='data'):
        funcname = __name__ + '.__init__():'
        super().__init__()

        logger.debug(funcname + str(data))
        # make only the first column editable
        #self.setEditTriggers(self.NoEditTriggers)
        self.datatypes = [['int', int], ['float', float], ['str', str],['list',list],['dict',dict]] # The datatypes
        self.datatypes_dict = {} # Make a dictionary out of it, thats easier to reference
        for d in self.datatypes:
            self.datatypes_dict[d[0]] = d[1]
        self.header().setVisible(False)
        self.data = data
        self.dataname = dataname
        # Create the root item
        self.root = self.invisibleRootItem()
        #self.root.__data__ = data
        self.root.__dataindex__ = ''
        self.root.__datatypestr__ = ''
        self.root.__parent__ = None
        self.setColumnCount(3)
        self.create_qtree()
        self.itemExpanded.connect(self.resize_view)
        self.itemCollapsed.connect(self.resize_view)

    def rawcopy(self,data):
        """
        Functions that simply returns the input data, used as the basic field conversion function
        """
        return data

    def seq_iter(self,obj):
        if isinstance(obj, dict):
            return obj
        elif isinstance(obj, list):
            return range(0,len(obj))
        else:
            return None

    def create_item(self, index, data, parent):
        """
        Creates recursively qtreewidgetitems. If the item to be created is a sequence (dict or list), it calls itself as often as it finds a real value
        Args:
            index:
            data:
            parent:

        Returns:

        """
        sequence = self.seq_iter(data)
        typestr = data.__class__.__name__
        if(sequence == None): # Check if we have an item that is something with data (not a list or dict)
            item = QtWidgets.QTreeWidgetItem([str(index), str(data),typestr])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)  # editable
            item.__data__         = data
            item.__dataindex__    = index
            item.__datatypestr__  = typestr
            item.__parent__       = parent
            index_child = self.item_is_child(parent, item)
            if  index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(item)
            else: # Update the data (even if it hasnt changed
                parent.child(index_child).setText(1,str(data))

        else:
            if(index is not None):
                indexstr = index
            newparent = QtWidgets.QTreeWidgetItem([str(index), '',typestr])
            item = newparent
            newparent.__data__         = data
            newparent.__dataindex__    = index
            newparent.__datatypestr__  = typestr
            newparent.__parent__       = parent
            index_child = self.item_is_child(parent, newparent)
            if index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(newparent)
            else:
                newparent = parent.child(index_child)

            for newindex in sequence:
                newdata = data[newindex]
                self.create_item(newindex,newdata,newparent)

    def item_is_child(self,parent,child):
        """
        Checks if the item is a child already

        Args:
            parent:
            child:

        Returns:

        """
        numchilds  = parent.childCount()
        for i in range(numchilds):
            testchild = parent.child(i)
            #flag1 = testchild.__data__        == child.__data__
            flag1 = True
            flag2 = testchild.__dataindex__   == child.__dataindex__
            #flag3 = testchild.__datatypestr__ == child.__datatypestr__
            flag3 = True
            flag4 = testchild.__parent__      == child.__parent__

            #print('fdsfd',i,testchild.__data__,child.__data__)
            #print('flags',flag1,flag2,flag3,flag4)
            if(flag1 and flag2 and flag3 and flag4):
                return i

        return None

    def create_qtree(self, editable=True):
        """Creates a new qtree from the configuration and replaces the data in
        the dictionary with a configdata obejct, that save the data
        but also the qtreeitem, making it possible to have a synced
        config dictionary from/with a qtreewidgetitem. TODO: Worth to
        replace with a qviewitem?

        """
        funcname = __name__ + '.create_qtree():'
        logger.debug(funcname)
        self.blockSignals(True)
        if True:
            self.create_item(self.dataname,self.data,self.root)

        self.dataitem = self.root.child(0)
        self.resizeColumnToContents(0)
        self.blockSignals(False)

    def resize_view(self):
        self.resizeColumnToContents(0)


#
#
#
#
#
class redvypr_deviceInitWidget(QtWidgets.QWidget):
    #device_start = QtCore.pyqtSignal(redvypr_device) # Signal requesting a start of the device (starting the thread)
    #device_stop  = QtCore.pyqtSignal(redvypr_device) # Signal requesting a stop of device
    connect      = QtCore.pyqtSignal(redvypr_device) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self, device=None):
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.config_widgets = []
        self.device = device
        self.config_widget = redvypr_config_widget(template=device.template,config = device.config)

        self.config_widgets.append(self.config_widget)

        # Startbutton
        self.startbutton = QtWidgets.QPushButton('Start')
        self.startbutton.clicked.connect(self.start_clicked)
        self.startbutton.setCheckable(True)
        # Process kill button (if thread)
        if (self.device.mp == 'multiprocess'):
            # Killbutton
            self.killbutton = QtWidgets.QPushButton('Kill process')
            self.killbutton.clicked.connect(self.kill_clicked)


        # Connect button
        self.conbutton = QtWidgets.QPushButton("Connect")
        self.conbutton.clicked.connect(self.connect_clicked)
        self.config_widgets.append(self.conbutton)

        self.layout.addWidget(self.config_widget, 0, 0,1,4)
        self.layout.addWidget(self.conbutton, 1, 0, 1, 4)
        if (self.device.mp == 'multiprocess'):
            self.layout.addWidget(self.startbutton, 2, 0,1,3)
            self.layout.addWidget(self.killbutton, 2, 3)
        else:
            self.layout.addWidget(self.startbutton, 2, 0, 1,4)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def kill_clicked(self):
        button = self.sender()
        logger.debug("Kill device {:s}".format(self.device.name))
        self.device.kill_process()
    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            logger.debug("button pressed")
            button.setText('Starting')
            config = self.config_widget.get_config()
            self.device.config = config
            self.device.thread_start()
            #self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            #button.setText('Stopping')
            self.startbutton.setChecked(True)
            self.device.thread_stop()

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_status']
        # Running
        if(thread_status):
            self.startbutton.setText('Stop')
            self.startbutton.setChecked(True)
            for w in self.config_widgets:
                w.setEnabled(False)
        # Not running
        else:
            self.startbutton.setText('Start')
            for w in self.config_widgets:
                w.setEnabled(True)

            # Check if an error occured and the startbutton
            if (self.startbutton.isChecked()):
                self.startbutton.setChecked(False)
            # self.conbtn.setEnabled(True)

    def connect_clicked(self):
        button = self.sender()
        self.connect.emit(self.device)


#
#
#
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
        self.infowidget.clear()
        sortstat = {}
        for i in sorted(self.device.statistics):
            sortstat[i]=self.device.statistics[i]

        sortstat['datakeys'] = sorted(sortstat['datakeys'])
        statstr = yaml.dump(sortstat)
        self.infowidget.insertPlainText(statstr + '\n')


#
#
#
#
#
class redvypr_config_widget(QtWidgets.QWidget):
    def __init__(self, template={}, config=None):
        funcname = __name__ + '.__init__():'
        super().__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.layout.setColumnStretch(0, 1)
        self.layout.setColumnStretch(1, 1)
        try:
            configname = config['name']
        except:
            configname = 'config'

        conftemplate = configtemplate_to_dict(template=template)
        if(config is not None):
            logger.debug(funcname + 'Applying config to template')
            redvypr.utils.apply_config_to_dict(config, conftemplate)



        self.configtree = redvypr_config_tree(conftemplate,dataname=configname)

        #self.itemExpanded.connect(self.resize_view)
        #self.itemCollapsed.connect(self.resize_view)
        self.configtree.itemDoubleClicked.connect(self.__open_config_gui)
        #self.configtree.itemChanged.connect(self.item_changed)  # If an item is changed
        #self.configtree.currentItemChanged.connect(self.current_item_changed)  # If an item is changed
        self.configgui = QtWidgets.QWidget() # Widget where the user can modify the content
        self.configgui_layout = QtWidgets.QVBoxLayout(self.configgui)

        # Add load/save buttons
        self.load_button = QtWidgets.QPushButton('Load')
        self.load_button.clicked.connect(self.load_config)
        self.save_button = QtWidgets.QPushButton('Save')
        self.save_button.clicked.connect(self.save_config)

        self.layout.addWidget(self.configtree,0,0)
        self.layout.addWidget(self.configgui, 0, 1)
        self.layout.addWidget(self.load_button, 1, 0)
        self.layout.addWidget(self.save_button, 1, 1)

    def load_config(self):
        funcname = __name__ + '.load_config():'
        fname_open = QtWidgets.QFileDialog.getOpenFileName(self, 'Open file', '',"YAML files (*.yaml);; All files (*)")
        if(len(fname_open[0]) > 0):
            logger.info(funcname + 'Opening file {:s}'.format(fname_open[0]))
            fname = fname_open[0]
            with open(fname, 'r') as yfile:
                data_yaml = yaml.safe_load(yfile)
                self.apply_config(data_yaml)

    def save_config(self):
        funcname = __name__ + '.save_config():'
        fname_open = QtWidgets.QFileDialog.getSaveFileName(self, 'Save file', '',"YAML files (*.yaml);; All files (*)")
        if(len(fname_open[0]) > 0):
            logger.info(funcname + 'Save file file {:s}'.format(fname_open[0]))
            config = copy.deepcopy(self.configtree.data)
            fname = fname_open[0]
            with open(fname, 'w') as yfile:
                yaml.dump(config, yfile)

    def get_config(self):
        """
        Returns a configuation dictionary of the

        Returns:

        """
        config = copy.deepcopy(self.configtree.data)
        return config


    def apply_config(self,config):
        """
        Applies a configuration dictionary to the configtree

        Args:
            config: config dictionary

        Returns:

        """

        self.configtree.apply_config(config)

    def __open_config_gui(self,item):
        """

        Returns:

        """
        data = item.__data__
        if((type(data) == list) or (type(data) == dict)):
            return


        try:
            dtype = data.template['type']
        except:
            if(type(data) == redvypr.utils.configdata):
                dtype = data.value.__class__.__name__
            else:
                dtype = data.__class__.__name__

            print('dtpye',dtype)
            #dtype = 'str'

        self.remove_input_widgets()
        if(dtype == 'int'):
            self.config_widget_number(item,'int')
        elif (dtype == 'float'):
            self.config_widget_number(item,'float')
        elif(dtype == 'str'):
            # If we have options
            try:
                data.template['options']
                self.config_widget_str_combo(item)
            # Let the user enter
            except Exception as e:
                print('Exception',e)
                self.config_widget_str(item)

    def __config_widget_button(self):
        funcname = __name__ + '.__config_widget_button(): '
        btn = self.sender()
        if(btn == self.__configwidget_apply):
            item = btn.item
            logger.debug(funcname + 'Apply')
            data = None
            try:
                data = self.__configwidget_input.value()
            except:
                pass
            try:
                data = self.__configwidget_input.text()
            except:
                pass

            try:
                data = str(self.__configwidget_input.currentText())
            except Exception as e:
                pass

            if(data is not None):
                logger.debug(funcname + 'Got data')
                item.setText(1,str(data))
                try: # If configdata
                    item.__dataparent__[item.__dataindex__].value = data
                except:
                    item.__dataparent__[item.__dataindex__] = data
            else:
                logger.debug(funcname + 'No valid data')


    def config_widget_number(self,item,dtype='int'):
        """
        Creates a widgets to modify an integer value

        Returns:

        """
        index = item.__dataindex__
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        #self.__configwidget_input = QtWidgets.QLineEdit()
        if(dtype=='int'):
            self.__configwidget_input = QtWidgets.QSpinBox()
            self.__configwidget_input.setRange(int(-1e9),int(1e9))
            try:
                value = int(item.text(1))
            except:
                value = 0
            self.__configwidget_input.setValue(value)
        else:
            self.__configwidget_input = QtWidgets.QDoubleSpinBox()
            self.__configwidget_input.setRange(-1e9, 1e9)
            try:
                value = float(item.text(1))
            except:
                value = 0.0
            self.__configwidget_input.setValue(value)

        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Enter value for {:s}'.format(index)))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.__layoutwidget_int.addRow(self.__configwidget_apply)
        self.configgui_layout.addWidget(self.__configwidget_int)

    def config_widget_str(self,item):

        index = item.__dataindex__
        data = ''
        try:
            data = str(item.__data__)
        except:
            pass
        try:
            data = str(item.__data__.value)
        except:
            pass

        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__configwidget_input = QtWidgets.QLineEdit()
        self.__configwidget_input.setText(data)
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Enter string for {:s}'.format(index)))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addRow(self.__configwidget_apply)


    def config_widget_str_combo(self, item):
        index = item.__dataindex__
        data = item.__data__
        options = data.template['options']
        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__configwidget_input = QtWidgets.QComboBox()
        for option in options:
            self.__configwidget_input.addItem(option)
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Options for {:s}'.format(index)))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addRow(self.__configwidget_apply)


    def remove_input_widgets(self):
        """
        Removes all widgets from configgui
        Returns:

        """
        layout = self.configgui_layout
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        #for i in range(len(self.__configgui_list)):
        #    widget = self.__configgui_list.pop()
        #    self.configgui_layout.remWidget(widget)

#
#
#
#
#
class redvypr_config_tree(QtWidgets.QTreeWidget):
    """ Qtreewidget that display a data structure
    """

    def __init__(self, data={}, dataname='data'):
        funcname = __name__ + '.__init__():'
        super().__init__()

        logger.debug(funcname + str(data))
        # make only the first column editable
        #self.setEditTriggers(self.NoEditTriggers)
        self.datatypes = [['int', int], ['float', float], ['str', str],['list',list],['dict',dict]] # The datatypes
        self.datatypes_dict = {} # Make a dictionary out of it, thats easier to reference
        for d in self.datatypes:
            self.datatypes_dict[d[0]] = d[1]
        self.header().setVisible(False)
        self.data     = data
        self.dataname = dataname
        # Create the root item
        self.root = self.invisibleRootItem()
        #self.root.__data__ = data
        self.root.__dataindex__ = ''
        self.root.__datatypestr__ = ''
        self.root.__parent__ = None
        self.setColumnCount(3)
        self.create_qtree()
        self.itemExpanded.connect(self.resize_view)
        self.itemCollapsed.connect(self.resize_view)

    def apply_config(self, config):
        """

        Args:
            config:

        Returns:

        """

        pass


    def seq_iter(self,obj):
        if isinstance(obj, dict):
            return obj
        elif isinstance(obj, list):
            return range(0,len(obj))
        else:
            return None

    def create_item(self, index, data, parent):
        """
        Creates recursively qtreewidgetitems. If the item to be created is a sequence (dict or list), it calls itself as often as it finds a real value
        Args:
            index:
            data:
            parent:

        Returns:

        """
        sequence = self.seq_iter(data)
        if(sequence == None): # Check if we have an item that is something with data (not a list or dict)
            data_value = data.value  # Data is a configdata object, or list or dict

            try:
                typestr = data.template['type']
            except:
                typestr = data_value.__class__.__name__

            print('Data value', data_value,'typestr',typestr)
            item       = QtWidgets.QTreeWidgetItem([str(index), str(data_value),typestr])
            #item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)  # editable
            item.__data__ = data
            item.__dataparent__   = parent.__data__ # can be used to reference the data (and change it)
            item.__dataindex__    = index
            item.__datatypestr__  = typestr
            item.__parent__       = parent
            index_child = self.item_is_child(parent, item)
            if  index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(item)
            else: # Update the data (even if it hasnt changed
                parent.child(index_child).setText(1,str(data))

        else:
            typestr = data.__class__.__name__
            if(index is not None):
                indexstr = index
            newparent = QtWidgets.QTreeWidgetItem([str(index), '',typestr])
            item = newparent
            newparent.__data__         = data
            newparent.__dataindex__    = index
            newparent.__datatypestr__  = typestr
            newparent.__parent__       = parent
            index_child = self.item_is_child(parent, newparent)
            if index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(newparent)
            else:
                newparent = parent.child(index_child)

            for newindex in sequence:
                newdata = data[newindex]
                self.create_item(newindex,newdata,newparent)

    def item_is_child(self,parent,child):
        """
        Checks if the item is a child already

        Args:
            parent:
            child:

        Returns:

        """
        numchilds  = parent.childCount()
        for i in range(numchilds):
            testchild = parent.child(i)
            #flag1 = testchild.__data__        == child.__data__
            flag1 = True
            flag2 = testchild.__dataindex__   == child.__dataindex__
            #flag3 = testchild.__datatypestr__ == child.__datatypestr__
            flag3 = True
            flag4 = testchild.__parent__      == child.__parent__

            #print('fdsfd',i,testchild.__data__,child.__data__)
            #print('flags',flag1,flag2,flag3,flag4)
            if(flag1 and flag2 and flag3 and flag4):
                return i

        return None

    def create_qtree(self, editable=True):
        """Creates a new qtree from the configuration and replaces the data in
        the dictionary with a configdata obejct, that save the data
        but also the qtreeitem, making it possible to have a synced
        config dictionary from/with a qtreewidgetitem. TODO: Worth to
        replace with a qviewitem?

        """
        funcname = __name__ + '.create_qtree():'
        logger.debug(funcname)
        self.blockSignals(True)
        if True:
            self.create_item(self.dataname,self.data,self.root)

        self.dataitem = self.root.child(0)
        self.resizeColumnToContents(0)
        self.blockSignals(False)

    def resize_view(self):
        self.resizeColumnToContents(0)



