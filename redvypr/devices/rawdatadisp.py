import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import yaml

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('rawdatadisp')
logger.setLevel(logging.DEBUG)

description = 'Displays data as text received from connected devices'


def start(datainqueue,dataqueue,comqueue):
    funcname = __name__ + '.start()'        
    while True:
        try:
            com = comqueue.get(block=False)
            print('received',com)
            break
        except:
            pass


        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
                dataqueue.put(data)

            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))            

class Device():
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None):
        """
        """
        self.publish     = False # publishes data, a typical device is doing this
        self.subscribe   = True  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
                
    def start(self):
        start(self.datainqueue,self.dataqueue,self.comqueue)
        
    def __str__(self):
        sstr = 'rawdatadisp'
        return sstr



class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device) # Signal requesting a start of the device (starting the thread)
    device_stop  = QtCore.pyqtSignal(Device) # Signal requesting a stop of device
    connect      = QtCore.pyqtSignal(Device) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QFormLayout(self)
        self.device   = device
        self.label    = QtWidgets.QLabel("Rawdatadisplay setup")
        self.conbtn = QtWidgets.QPushButton("Connect logger to devices")
        self.conbtn.clicked.connect(self.con_clicked)        
        self.startbtn = QtWidgets.QPushButton("Start logging")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)

        layout.addRow(self.label)        
        layout.addRow(self.conbtn)
        layout.addRow(self.startbtn)        

    def con_clicked(self):
        button = self.sender()
        self.connect.emit(self.device)        
            
    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            print("button pressed")
            self.device_start.emit(self.device)
            button.setText("Stop logging")
            self.conbtn.setEnabled(False)
        else:
            print('button released')
            self.device_stop.emit(self.device)
            button.setText("Start logging")
            self.conbtn.setEnabled(True)
        




class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QFormLayout(self)
        self.text     = QtWidgets.QPlainTextEdit(self)
        self.clearbtn = QtWidgets.QPushButton('Clear')
        self.clearbtn.clicked.connect(self.cleartext)
        self.scrollchk= QtWidgets.QCheckBox('Scroll to end')
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)
        layout.addRow(self.text)
        layout.addRow(self.scrollchk,self.clearbtn)
        self.text.insertPlainText("This is the raw data display device!\n")
        
    def cleartext(self):
        self.text.clear()        

    def update(self,data):
        #cursor = QtGui.QTextCursor(self.text.document())
        prev_cursor = self.text.textCursor()
        pos = self.text.verticalScrollBar().value()
        self.text.moveCursor(QtGui.QTextCursor.End)
        self.text.insertPlainText(str(data) + '\n')
        #cursor.setPosition(0)
        #self.text.setTextCursor(prev_cursor)
        if(self.scrollchk.isChecked()):
            self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
        else:
            self.text.verticalScrollBar().setValue(pos)
        
