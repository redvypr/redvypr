"""
.

The gps device converts stadard nmea messages used in marine navigation into redvypr format 


Configuration options for the gps device:

.. code-block::

    - deviceconfig:
    name: gps
    config:
      key: 'data' # The dictionary key of the raw NMEA string, defaults to 'data'
      append: True # If the raw message is tranported in pieces, append data until a valid message was found
      maxlen: 10000 # The maximum length of text buffer to search for NMEA messages
      #sentences: all Set sentences to all, or a list of sentences (see next line)
      sentences: # Filter for the NMEA sentences 
          - RMC
          - GGA
                     

  devicemodulename: gps_device


"""

import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import serial
import serial.tools.list_ports
import logging
import sys
import pynmea2

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('gps_device')
logger.setLevel(logging.DEBUG)

def parse_nmea(nmea_data):
    try:
        msg = pynmea2.parse(nmea_data)
        logger.debug('Valid message:' + str(msg))
        data_nmea = {'valid_nmea':True}
        data_nmea['nmea'] = str(msg) + '\n'
        data_nmea['lat'] = msg.latitude
        data_nmea['lon'] = msg.longitude
        try: # If there is a date
            data_nmea['date'] = msg.datestamp.strftime("%m%d%y")
        except:
            pass
        try: # If there is a date
            data_nmea['time'] = msg.timestamp.strftime("%H%M%S.%f")[:-4]
        except:
            pass    
        
        data_nmea['sentence_type'] = msg.sentence_type
        return data_nmea
    except Exception as e:
        data_nmea = {'valid_nmea':False}
        return data_nmea

    
def start(dataqueue,comqueue,datainqueue,devicename,config):
    funcname = __name__ + '.start()'        
    logger.debug(funcname + ':Starting reading NMEA data')        
    nmea_sentence = ''
    sentences = 0
    try:
        nmea_key = config['key']
    except:
        nmea_key = 'data'
        
    try:
        config['append']
    except:
        config['append'] = False
        
    try:
        config['sentences']
    except:
        config['sentences'] = 'all'
        
    try:
        config['maxlen']
    except:
        config['maxlen'] = 10000
        
    logger.debug(funcname + ': config {:s}'.format(str(config)))
    nmea_sentence_append = '' # Only used for append
    while True:
        data = datainqueue.get() # This is a blocking read
        if('command' in data.keys()):
            if(data['command'] == 'stop'):
                logger.info(funcname + ': received stop command, stopping now')
                break    
        if True:
            if(nmea_key in data.keys()):
                nmea_sentence_raw = data[nmea_key]
                if(config['append']):
                    #print('appending')
                    nmea_sentence_append += nmea_sentence_raw
                    # Precheck if there is at all valid data
                    if(('\n' in nmea_sentence_append) and ('$' in nmea_sentence_append)):
                        nmea_sentence_all = nmea_sentence_append.split('\n')
                        nmea_last = nmea_sentence_all[-1]
                    else:
                        nmea_sentence_all = []
                else:
                    nmea_sentence_all = [nmea_sentence_raw]
                    nmea_last = nmea_sentence_all[-1]
                # save the last sentence 
                
                if(len(nmea_sentence_all)>0):
                    if(len(nmea_sentence_all[-1])>0): # This happens if the last character is not a \n
                        nmea_sentence_append = nmea_sentence_all[-1]
                        
                    nmea_sentence_all.pop(-1) # Remove last sentence (either '' or rest)
                    
                # loop over all NMEA sentences 
                for nmea_sentence in nmea_sentence_all:  
                    data_parse = parse_nmea(nmea_sentence)  
                    #print(data_parse)
                    #print(nmea_sentence_all)
                    
                    data_parse['device']  = devicename
                    if(data_parse['valid_nmea']):
                        nmea_sentence_all.remove(nmea_sentence)
                        sentence_right = config['sentences'] == 'all'
                        sentence_right = sentence_right or (data_parse['sentence_type'] in config['sentences'])
                        if(sentence_right): # Which message shall be used?
                            dataqueue.put(data_parse)
                            data_parse['host'] = data['host']
                            data_parse['t'] = data['t']
                            sentences += 1
                                
                            


class Device():
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None):
        """
        """
        self.publish     = True # publishes data, a typical device is doing this
        self.subscribe   = True  # subscribing data, a typical datalogger is doing this
        self.datainqueuestop  = True  # Send the stop command into the dataqueuue
        self.autostart   = True # Start the thread directly after initialization
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.config = {}

    def start(self):
        start(self.dataqueue,self.comqueue,self.datainqueue,devicename=self.name,config=self.config)
        

    def __str__(self):
        sstr = 'GPS device'
        return sstr



class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device)
    device_stop = QtCore.pyqtSignal(Device)        
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        self.device   = device
        self.inputtabs = QtWidgets.QTabWidget() # Create tabs for different connection types
        self.serialwidget = QtWidgets.QWidget()
        #self.init_serialwidget()
        #self.networkwidget = QtWidgets.QWidget()        
        #self.inputtabs.addTab(self.serialwidget,'Serial')
        #self.inputtabs.addTab(self.networkwidget,'Network')                
        self.label    = QtWidgets.QLabel("GPS device")
        #self.startbtn = QtWidgets.QPushButton("Open device")
        #self.startbtn.clicked.connect(self.start_clicked)
        #self.stopbtn = QtWidgets.QPushButton("Close device")
        #self.stopbtn.clicked.connect(self.stop_clicked)
        layout.addWidget(self.label)        
        #layout.addWidget(self.inputtabs)
        #layout.addWidget(self.startbtn)
        #layout.addWidget(self.stopbtn)

    def init_serialwidget(self):
        """Fills the serial widget with content
        """
        layout = QtWidgets.QGridLayout(self.serialwidget)
        # Serial baud rates
        baud = [300,600,1200,2400,4800,9600,19200,38400,57600,115200,576000,921600]
        self._combo_serial_devices = QtWidgets.QComboBox()
        #self._combo_serial_devices.currentIndexChanged.connect(self._serial_device_changed)
        self._combo_serial_baud = QtWidgets.QComboBox()
        for b in baud:
            self._combo_serial_baud.addItem(str(b))

        self._combo_serial_baud.setCurrentIndex(4)
        self._button_serial_openclose = QtWidgets.QPushButton('Open')
        self._button_serial_openclose.clicked.connect(self.start_clicked)


        # Check for serial devices and list them
        for comport in serial.tools.list_ports.comports():
            self._combo_serial_devices.addItem(str(comport.device))

        layout.addWidget(self._combo_serial_devices,0,0)
        layout.addWidget(self._combo_serial_baud,0,1)
        layout.addWidget(self._button_serial_openclose,0,2)            
            
    def start_clicked(self):
        button = self.sender()
        if('Open' in button.text()):
            button.setText('Close')
            serial_name = str(self._combo_serial_devices.currentText())
            serial_baud = int(self._combo_serial_baud.currentText())
            #self.device.open_serial_device(serial_name,serial_baud)
            self.device.serial_name = serial_name
            self.device.baud = serial_baud
            self.device_start.emit(self.device)
        else:
            self.stop_clicked()

    def stop_clicked(self):
        button = self.sender()        
        self.device_stop.emit(self.device)
        button.setText('Open')        



class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        hlayout        = QtWidgets.QHBoxLayout(self)
        self.text     = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)
        self.scrollchk= QtWidgets.QCheckBox('Scroll to end')        
        self.posstatus= QtWidgets.QPushButton('Position')
        self.posstatus.setStyleSheet("background-color: red")
        self.datestatus= QtWidgets.QPushButton('Date')
        self.datestatus.setStyleSheet("background-color: red")
        self.timestatus= QtWidgets.QPushButton('Time')
        self.timestatus.setStyleSheet("background-color: red")
        hlayout.addWidget(self.posstatus)
        hlayout.addWidget(self.timestatus)
        hlayout.addWidget(self.datestatus)
        layout.addLayout(hlayout)
        hlayout.addWidget(self.scrollchk)        
        layout.addWidget(self.text)
        self.goodpos = -1

    def update(self,data):
        #print('data',data)
        prev_cursor = self.text.textCursor()
        pos = self.text.verticalScrollBar().value()
        self.text.moveCursor(QtGui.QTextCursor.End)        
        self.text.insertPlainText(str(data['nmea']))
        if(self.scrollchk.isChecked()):
            self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
        else:
            self.text.verticalScrollBar().setValue(pos)        
        if('lon' in data.keys()):
            self.goodpos = time.time()
            if(data['lon'] == None):
                self.posstatus.setStyleSheet("background-color: yellow")
                posstr = "Position, Lat: NA Lon: NA"
                self.posstatus.setText(posstr)
            else:
                posstr = "Position, Lat: {:.4f} Lon: {:.4f}".format(data['lat'],data['lon'])
                #print(posstr) 
                self.posstatus.setText(posstr)
                self.posstatus.setStyleSheet("background-color: green")
                
        if('time' in data.keys()):
            self.goodtime = time.time()
            if(data['time'] == None):
                self.timestatus.setStyleSheet("background-color: yellow")
                posstr = "Time: NA"
                self.timestatus.setText(posstr)
            else:
                posstr = "Time: {:s}:{:s}:{:s}".format(data['time'][0:2],data['time'][2:4],data['time'][4:])
                #print(posstr) 
                self.timestatus.setText(posstr)
                self.timestatus.setStyleSheet("background-color: green")
                
        if('date' in data.keys()):
            self.gooddate = time.time()
            if(data['date'] == None):
                self.datestatus.setStyleSheet("background-color: yellow")
                posstr = "Date: NA"
                self.datestatus.setText(posstr)
            else:
                posstr = "Date: {:s}.{:s}.{:s}".format(data['date'][0:2],data['date'][2:4],data['date'][4:])
                #print(posstr) 
                self.datestatus.setText(posstr)
                self.datestatus.setStyleSheet("background-color: green")
            
        if((time.time() - self.goodpos)>10):
            self.posstatus.setStyleSheet("background-color: red")
        
