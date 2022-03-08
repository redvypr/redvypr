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
from redvypr.data_packets import datadict

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('nmea_logbook')
logger.setLevel(logging.DEBUG)


def start(dataqueue,comqueue,datainqueue):
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
        else:
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
        start(self.dataqueue,self.comqueue,self.datainqueue)
        

    def __str__(self):
        sstr = 'nmea loogbook'
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
        self.label    = QtWidgets.QLabel("NMEA Logbook")
        self.startbtn = QtWidgets.QPushButton("Start")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)       
        #self.startbtn.clicked.connect(self.start_clicked)
        #self.stopbtn = QtWidgets.QPushButton("Close device")
        #self.stopbtn.clicked.connect(self.stop_clicked)
        layout.addWidget(self.label)        
        #layout.addWidget(self.inputtabs)
        #layout.addWidget(self.startbtn)
        #layout.addWidget(self.stopbtn)
        
        
    def update_buttons(self,thread_status):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """
            # Running
            if(thread_status):
                self.startbtn.setText('Stop')
                self.startbtn.setChecked(True)
            # Not running
            else:
                self.startbtn.setText('Start')
                # Check if an error occured and the startbutton 
                if(self.startbtn.isChecked()):
                    self.startbtn.setChecked(False)
                #self.conbtn.setEnabled(True)

    def start_clicked(self):
        funcname = __name__ + '.start_clicked()'
        button = self.sender()
        if button.isChecked():
            self.device_start.emit(self.device)
            button.setText("Starting")
        else:
            self.device_stop.emit(self.device)
            button.setText("Stopping")


class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        self.device = device
        layout        = QtWidgets.QVBoxLayout(self)
        hlayout       = QtWidgets.QGridLayout()
        flayout        = QtWidgets.QFormLayout()
        self.loperator=QtWidgets.QLabel("Operator")
        self.operator = QtWidgets.QLineEdit()
        self.llocation=QtWidgets.QLabel("Location")
        self.location = QtWidgets.QLineEdit()
        flayout.addRow(self.loperator,self.operator)
        flayout.addRow(self.llocation,self.location)
        self.logtextedit     = QtWidgets.QPlainTextEdit()
        self.loglabel=QtWidgets.QLabel("Add logbookentry here")
        
        
        flayout.addRow(self.loglabel)
        flayout.addRow(self.logtextedit)
        # The header before the log entry
        self.logheader = QtWidgets.QLineEdit()
        self.logheader.setReadOnly(True)
        self.logheadercheck = QtWidgets.QCheckBox('Add header')
        self.logheadercheck.setChecked(True)
        self.logheadercheck.setToolTip('Check/Unchecking will update the header, the commit time will be updated, not the one shown here.')
        self.logheadercheck.stateChanged.connect(self.update_logheader)
        flayout.addRow(self.logheadercheck,self.logheader)
        #self.logstr = ''
        self.logcommitbutton=QtWidgets.QPushButton("Commit log entry")
        self.logcommitbutton.clicked.connect(self.commit_logentry)
        flayout.addRow(self.logcommitbutton)
        
        self.text     = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)
        self.lonstatus= QtWidgets.QPushButton('Lon')
        self.lonstatus.setStyleSheet("background-color: red")
        self.loninput = QtWidgets.QLineEdit()
        self.loninput.setText("0.0")
        self.latstatus= QtWidgets.QPushButton('Lat')
        self.latstatus.setStyleSheet("background-color: red")
        self.latinput = QtWidgets.QLineEdit()
        self.latinput.setText("0.0")        
        self.datestatus= QtWidgets.QPushButton('Date')
        self.datestatus.setStyleSheet("background-color: red")
        self.dateinput = QtWidgets.QLineEdit()                
        self.timestatus= QtWidgets.QPushButton('Time')

        self.timestatus.setStyleSheet("background-color: red")
        self.timeinput = QtWidgets.QLineEdit()
        tnow = datetime.datetime.now()
        nowtimestr = tnow.strftime("%H:%M:%S")        
        nowdatestr = tnow.strftime("%d.%m.%Y")
        self.dateinput.setText(nowtimestr)        
        self.timeinput.setText(nowdatestr)
        hlayout.addWidget(self.latstatus,0,0)        
        hlayout.addWidget(self.lonstatus,0,1)
        hlayout.addWidget(self.timestatus,0,2)
        hlayout.addWidget(self.datestatus,0,3)
        hlayout.addWidget(self.latinput,1,0)        
        hlayout.addWidget(self.loninput,1,1)
        hlayout.addWidget(self.dateinput,1,2)
        hlayout.addWidget(self.timeinput,1,3)
        self.logposcheck = QtWidgets.QCheckBox('Use GPS Position/Time')
        self.logposcheck.setChecked(True)
        hlayout.addWidget(self.logposcheck,2,0,1,3)        
        layout.addLayout(hlayout)        
        layout.addLayout(flayout)
        layout.addWidget(self.text)
        self.goodpos = -1
        # Create a first header
        self.update_logheader()
        
    def commit_logentry(self):
        text = self.logtextedit.toPlainText()
        text = '"' + text + '"'
        self.logtextedit.clear()
        
        # Update the logheader
        self.update_logheader()
        if self.logheadercheck.isChecked():
            textcommit = self.logheaderstr + text
        else:
            textcommit = text
            
        if(len(text)>0):   
            self.text.insertPlainText(textcommit + '\n')
            datadict = datadict(textcommit)
            self.device.datainqueue.put(datadict)
            
    def update_logheader(self):
        hosttime = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        if(self.logposcheck.isChecked()):
            try:
                self.timestr
            except:
                self.timestr = "?.?.? ?:?:?"
            try:
                self.posstrheader
            except:
                self.posstrheader = "?N,?E"
        else:
            self.timestr = self.dateinput.text() + ' ' + self.timeinput.text()
            self.posstrheader = self.latinput.text() + ',N,' + self.loninput.text()+ ',E'
            
                
        
        self.logheaderstr = '$NMEALOG,' + hosttime + ',' + self.timestr + ',' + self.posstrheader + ',' + self.operator.text() + ',' + self.location.text() + ',log,'
        print(self.logheaderstr)   
        self.logheader.setText(self.logheaderstr)

    def update(self,data):
        print('data',data)
        #self.text.insertPlainText(str(data['nmea']))
        self.logstr = ''
        lon = -999
        lat = -99
        dd = '00'
        mm = '00'
        yy = '00'
        hh = '00'
        mm = '00'
        ss = '00'
        
        if('lon' in data.keys()):
            self.goodpos = time.time()
            if(data['lon'] == None):
                self.posstatus.setStyleSheet("background-color: yellow")
                lonstr = "Lon: NA"
                latstr = "Lat: NA"                
                self.lonstatus.setText(lonstr)
                self.latstatus.setText(latstr)                
            else:
                lonstr = "Lon: {:.4f}".format(data['lon'])
                latstr = "Lat: {:.4f}".format(data['lat'])
                lon = data['lon']
                lat = data['lat']
                #print(posstr) 
                self.lonstatus.setText(lonstr)
                self.latstatus.setText(latstr)                                
                self.posstatus.setStyleSheet("background-color: green")
                
                
        if('time' in data.keys()):
            self.goodtime = time.time()
            if(data['time'] == None):
                self.timestatus.setStyleSheet("background-color: yellow")
                posstr = "Time: NA"
                self.timestatus.setText(posstr)
            else:
                hh = data['time'][0:2]
                mm = data['time'][2:4]
                ss = data['time'][4:]
                posstr = "Time: {:s}:{:s}:{:s}".format(hh,mm,ss)
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
                dd = data['date'][0:2]
                mm = data['date'][2:4]
                yy = data['date'][4:]
                posstr = "Date: {:s}.{:s}.{:s}".format(dd,mm,yy)
                #print(posstr) 
                self.datestatus.setText(posstr)
                self.datestatus.setStyleSheet("background-color: green")
            
        if((time.time() - self.goodpos)>10):
            self.posstatus.setStyleSheet("background-color: red")
        
        self.timestr = "{:s}.{:s}.{:s} {:s}:{:s}:{:s}".format(dd,mm,yy,hh,mm,ss)    
        self.posstrheader = "{:2.4f},N,{:3.4f},E".format(lat,lon)
        self.update_logheader()
        
