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
logger = logging.getLogger('nmea_sensor')
logger.setLevel(logging.DEBUG)


def start(dataqueue,comqueue,serial_name,baud,max_size=10000):
    funcname = __name__ + '.start()'        
    logger.debug(funcname + ':Starting reading nmea data')        
    nmea_sentence = ''
    sentences = 0
    if True:
        try:
            serial_device = serial.Serial(serial_name,baud)
        except Exception as e:
            print('Exception open_serial_device',str(e))

    got_dollar = False    
    while True:
        try:
            com = comqueue.get(block=False)
            print('received',com)
            break
        except:
            pass


        time.sleep(0.05)
        while(serial_device.inWaiting()):
            try:
                value = serial_device.read(1).decode('utf-8')
                nmea_sentence += value
                if(len(nmea_sentence) > max_size):
                    nmea_sentence = ''
                    
                if(value == '$'):
                    got_dollar = True
                    nmea_sentence = value
                    # Get the time
                    ti = time.time()

                elif((value == '\n') and (got_dollar)):
                    got_dollar = False                    
                    data = {'t':time.time()}
                    data['nmeatime'] = ti
                    data['device'] = serial_device.name
                    data['nmea'] = nmea_sentence
                    # Interprete the data
                    nmea_sentence_split = nmea_sentence.split(',')
                    if('GLL' in nmea_sentence):
                        print('GLL',nmea_sentence_split)
                        try:
                            lat = float(nmea_sentence_split[1][0:2]) + float(nmea_sentence_split[1][2:])/60
                            if(nmea_sentence_split[2] == 'S'):
                                lat = -lat
                        except Exception as e:
                            print(e)
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
                        print(data)
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
                        print(data)
                    elif('GSA' in nmea_sentence):
                        pass
                    elif('GSV' in nmea_sentence):
                        pass
                    elif('VTG' in nmea_sentence):
                        pass
                    elif('RMC' in nmea_sentence):
                        data['time'] = nmea_sentence_split[1]
                        data['date'] = nmea_sentence_split[10]                        
                    
                    logger.debug(funcname + ':Read sentence:' + nmea_sentence)
                    nmea_sentence = ''
                    sentences += 1
                    
                    dataqueue.put(data)

            except Exception as e:
                logger.debug(':Exception:' + str(e))            

class Device():
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None):
        """
        """
        self.publish     = True # publishes data, a typical device is doing this
        self.subscribe   = False  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.serial_device = None
        self.serial_name = ''
        self.baud = 0
        self.sentences = 0

    def start(self):
        start(self.dataqueue,self.comqueue,self.serial_name,self.baud)
        

    def __str__(self):
        sstr = 'NMEA device'
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
        self.init_serialwidget()
        self.networkwidget = QtWidgets.QWidget()        
        self.inputtabs.addTab(self.serialwidget,'Serial')
        self.inputtabs.addTab(self.networkwidget,'Network')                
        self.label    = QtWidgets.QLabel("Connect to a NMEA device")
        #self.startbtn = QtWidgets.QPushButton("Open device")
        #self.startbtn.clicked.connect(self.start_clicked)
        #self.stopbtn = QtWidgets.QPushButton("Close device")
        #self.stopbtn.clicked.connect(self.stop_clicked)
        layout.addWidget(self.label)        
        layout.addWidget(self.inputtabs)
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
        self.text     = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)
        self.posstatus= QtWidgets.QPushButton('Position')
        self.posstatus.setStyleSheet("background-color: red")
        layout.addWidget(self.posstatus)
        layout.addWidget(self.text)
        self.goodpos = -1

    def update(self,data):
        #print('data',data)
        self.text.insertPlainText(str(data['nmea']))
        if('lon' in data.keys()):
            self.goodpos = time.time()
            posstr = "Position, Lat: {:.4f} Lon: {:.4f}".format(data['lat'],data['lon'])
            #print(posstr) 
            self.posstatus.setText(posstr)
            self.posstatus.setStyleSheet("background-color: green")
            
        if((time.time() - self.goodpos)>10):
            self.posstatus.setStyleSheet("background-color: red")
        
