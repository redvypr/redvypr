import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import logging
import sys
import yaml

description = 'An example device'

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('exampledevice')
logger.setLevel(logging.DEBUG)

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
    """ Widget that displays information collected in the statistics
    """
    device_name_changed        = QtCore.pyqtSignal(str) # Signal notifying if the device path was changed
    datakey_name_changed       = QtCore.pyqtSignal(str) # Signal notifying if the datakey has changed
    def __init__(self,redvypr,device=None,devicename=None,datakey=None):
        super(QtWidgets.QWidget, self).__init__()
        self.redvypr = redvypr
        self.layout = QtWidgets.QVBoxLayout(self)
        if(devicename == None):
            self.devicename = 'Na'
        else:
            self.devicename = devicename

        self.device = device            
        if(device is not None):
            self.devicenamelabel = QtWidgets.QLabel('Device: ' + device.name)
            self.layout.addWidget(self.devicenamelabel)

        self.deviceavaillabel = QtWidgets.QLabel('Available devices')
        self.layout.addWidget(self.deviceavaillabel)
        
        self.devicelist  = QtWidgets.QListWidget() # List of available devices
        self.datakeylist = QtWidgets.QListWidget() # List of available datakeys
        self.devicecustom = QtWidgets.QLineEdit()
        self.devicecustom.textChanged[str].connect(self.devicecustom_changed)
        self.layout.addWidget(self.devicelist)
        self.layout.addWidget(self.devicecustom)
        self.devicedatakeyslabel = QtWidgets.QLabel('Data keys of device')
        self.layout.addWidget(self.devicedatakeyslabel)        
        self.layout.addWidget(self.datakeylist)
        self.datakeycustom = QtWidgets.QLineEdit()
        self.layout.addWidget(self.datakeycustom)

        self.buttondone = QtWidgets.QPushButton('Done')
        self.buttondone.clicked.connect(self.done_clicked)
        self.layout.addWidget(self.buttondone)                

        devicelist = []
        self.datakeylist_subscribed = {}
        flag_all_devices = self.device == None
        for devdict in self.redvypr.devices:
            devname = devdict['device'].name
            print(devname,devname in device.data_receiver)
            flag_subscribed_device = devname in device.data_receiver
            flag_device_itself = devdict['device'] == self.device
            if(flag_all_devices or flag_subscribed_device or flag_device_itself):
                devices = devdict['statistics']['devices']
                #print('Devices',devices)
                for dev in devices:
                    devicelist.append(str(dev))
                    #print(devdict['statistics']['devicekeys'])
                    self.datakeylist_subscribed[dev] = devdict['statistics']['devicekeys'][dev]

        for devname in devicelist:
            self.devicelist.addItem(devname)
            
        #print('data provider',device.data_provider)
        #print('data receiver',device.data_receiver)
        
        self.devicelist.itemDoubleClicked.connect(self.device_clicked)
        self.datakeylist.itemDoubleClicked.connect(self.datakey_clicked)

        # Update the custom text with the given devicename and check if it exists in the item list
        # If its existing update the datakeylist
        self.devicecustom.setText(str(devicename))                
        for i in range(self.devicelist.count()-1):
            if(self.devicelist.item(i).text() == self.devicename):
                self.devicelist.setCurrentItem(self.devicelist.item(i))
                self.device_clicked(self.devicelist.item(i))                

        #self.devicecustom_changed(self.devicename)
        
    def update_datakeylist(self,devicename):
        print('Updating list')
        self.datakeylist.clear()
        for key in self.datakeylist_subscribed[devicename]:
            self.datakeylist.addItem(key)

    def done_clicked(self):
        self.close()
        
    def device_clicked(self,item):
        """ If the device was changed, update the datakeylist and emit a signal
        """
        devicename = item.text()
        #print('Click',item.text())
        self.devicedatakeyslabel.setText('Data keys of device ' + devicename)
        self.update_datakeylist(devicename)
        self.devicecustom.setText(str(devicename))        
        self.device_name_changed.emit(item.text())

    def datakey_clicked(self,item):
        datakey = item.text()
        print('Click',item.text())
        self.datakeycustom.setText(str(datakey))
        self.datakey_name_changed.emit(item.text())        

        
    def devicecustom_changed(self,text):
        pass
        #self.device_name_changed.emit(str(text))                    
