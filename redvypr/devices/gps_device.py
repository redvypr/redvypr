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

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('gps_device')
logger.setLevel(logging.DEBUG)


def start(dataqueue,comqueue,datainqueue,devicename):
    funcname = __name__ + '.start()'        
    logger.debug(funcname + ':Starting reading nmea data')        
    nmea_sentence = ''
    sentences = 0
   
    while True:
        data = datainqueue.get() # This is a blocking read
        if('command' in data.keys()):
            if(data['command'] == 'stop'):
                logger.info(funcname + ': received stop command, stopping now')
                break    
        if True:
            if True:
                if('nmea' in data.keys()):
                    nmea_sentence = data['nmea']
                    # Interprete the data
                    nmea_sentence_split = nmea_sentence.split(',')
                    if('GLL' in nmea_sentence):
                        #print('GLL',nmea_sentence_split)
                        try:
                            lat = float(nmea_sentence_split[1][0:2]) + float(nmea_sentence_split[1][2:])/60
                            if(nmea_sentence_split[2] == 'S'):
                                lat = -lat
                        except Exception as e:
                            logger.debug(funcname + ':' +str(e))
                            lat = None
                        
                        try:
                            lon = float(nmea_sentence_split[3][0:3]) + float(nmea_sentence_split[3][3:])/60
                            if(nmea_sentence_split[4] == 'W'):
                                lon = -lon
                        except:
                            lon = None

                        data['lat']  = lat
                        data['lon']  = lon
                        data['time'] = nmea_sentence_split[5]
                        data['nmea_packet'] = 'GLL'
                        #print(data)
                    elif('GGA' in nmea_sentence):
                        data['time'] = nmea_sentence_split[1]
                        try:
                            lat = float(nmea_sentence_split[2][0:2]) + float(nmea_sentence_split[2][2:])/60
                            if(nmea_sentence_split[3] == 'S'):
                                lat = -lat
                        except:
                            lat = None
                        
                        try:
                            lon = float(nmea_sentence_split[4][0:3]) + float(nmea_sentence_split[4][3:])/60
                            if(nmea_sentence_split[5] == 'W'):
                                lon = -lon
                        except:
                            lon = None
                        
                        data['lat']  = lat
                        data['lon']  = lon
                        try:
                            data['gpsquality']  = int(nmea_sentence_split[6])
                        except:
                            data['gpsquality']  = None
                            
                        try:
                            data['numsat']  = int(nmea_sentence_split[7])
                        except:
                            data['numsat']  = None
                            
                        try:
                            data['hordil']  = float(nmea_sentence_split[8])
                        except:
                            data['hordil']  = None
                            
                        try:
                            data['geosep']  = float(nmea_sentence_split[11])
                        except:
                            data['geosep']  = None
                            
                        data['nmea_packet'] = 'GGA'
                        #print(data)
                    elif('GSA' in nmea_sentence):
                        pass
                    elif('GSV' in nmea_sentence):
                        pass
                    elif('VTG' in nmea_sentence):
                        pass
                    elif('RMC' in nmea_sentence):
                        data['time'] = nmea_sentence_split[1]
                        data['date'] = nmea_sentence_split[9]
                        try:
                            lat = float(nmea_sentence_split[2][0:2]) + float(nmea_sentence_split[2][2:])/60
                            if(nmea_sentence_split[3] == 'S'):
                                lat = -lat
                        except:
                            lat = None
                        
                        try:
                            lon = float(nmea_sentence_split[4][0:3]) + float(nmea_sentence_split[4][3:])/60
                            if(nmea_sentence_split[5] == 'W'):
                                lon = -lon
                        except:
                            lon = None
                    
                    logger.debug(funcname + ':Read sentence:' + nmea_sentence)
                    nmea_sentence = ''
                    sentences += 1
                    data['device']  = devicename
                    dataqueue.put(data)


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

    def start(self):
        start(self.dataqueue,self.comqueue,self.datainqueue,devicename=self.name)
        

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
        layout.addWidget(self.text)
        self.goodpos = -1

    def update(self,data):
        #print('data',data)
        self.text.insertPlainText(str(data['nmea']))
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
        
