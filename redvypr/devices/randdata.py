import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import sys

logging.basicConfig(stream=sys.stderr)

description = 'Publishes random data.'

class Device():
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None,config=None):
        """
        """
        self.publish     = True # publishes data, a typical device is doing this
        self.subscribe   = False  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        if(config == None):
            config = {'dt':0.5,'functions':[]}
            function = {'name':'rand','range':[0,5]}
            config['functions'].append(function)
            function = {'name':'sin','amp':10,'f':0.3,'phase':0.0}
            config['functions'].append(function)
        self.config      = config


        self.logger = logging.getLogger('randdata')
        self.logger.setLevel(logging.INFO)

        
    def start(self):
        # This is bad, as the logger is in a different thread
        self.logger.info('Starting randdata with dt {:f}'.format(self.config['dt']))
        self.logger.info('Functions (added):')
        for f in self.config['functions']:
            fstr = str(f)
            self.logger.info('\t {:s}'.format(fstr))
                
        try:
            n = self.config['n']
        except:
            n = 1 
            
        print('n',n)               
        rng = np.random.default_rng()
        xold = 0
        while True:
            
            try:
                com = self.comqueue.get(block=False)
                print('received',com)
                break
            except:
                pass
            
            #x = np.random.rand(1)[0] * 100 + 50
            xall = []
            tall = []
            for isample in range(n):
                x = 0
                t = time.time()
                for func in self.config['functions']:
                    if(func['name']=='rand'):
                        #x += rng.integers(low=func['range'][0], high=func['range'][1], size=1)[0]
                        dx = float(func['range'][1]) - float(func['range'][0]) 
                        xoff = func['range'][0]
                        x += rng.random() * dx - xoff
                        
                    elif(func['name']=='sin'):
                        try:
                            x += func['amp'] * np.sin(func['f'] * t + func['phase'])
                        except Exception as e:
                            self.logger.debug(str(e))
    
                    elif(func['name']=='count'):
                        try:
                            x += func['count'] + xold
                        except Exception as e:
                            self.logger.debug(str(e))
                
                tall.append(t)
                xall.append(float(x))            
                time.sleep(self.config['dt'])  
                xold = x                      
                        
            try:
                data_unit = self.config['unit']
            except:
                data_unit = 'randomunit'

            if(n==1):
                tall = tall[0]
                xall = xall[0]
            data = {'t':tall,'data':xall,'props@data':{'unit':data_unit,'type':'f'}}
            #print('data',data)
            self.dataqueue.put(data)
            tend = time.time()
            # Sleep 'dt' minus the time needed for processing
            #time.sleep(self.config['dt']- (tend-t))
            
    def __str__(self):
        sstr = 'Random data device'
        return sstr



class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device)
    device_stop = QtCore.pyqtSignal(Device)        
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        self.device   = device
        self.label    = QtWidgets.QLabel("Hello, this is random")
        self.startbtn = QtWidgets.QPushButton("Start data")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)        
        layout.addWidget(self.label)
        layout.addWidget(self.startbtn)

    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            self.device_start.emit(self.device)
            button.setText("Starting")
            #self.conbtn.setEnabled(False)
        else:
            self.device_stop.emit(self.device)
            button.setText("Stopping")
            #self.conbtn.setEnabled(True)

    def thread_status(self,status):
        """ This function is called by redvypr whenever the thread is started/stopped
        """   
        self.update_buttons(status['threadalive'])

       
    def update_buttons(self,thread_status):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """
            if(thread_status):
                self.startbtn.setText('Stop logging')
                self.startbtn.setChecked(True)
                #self.conbtn.setEnabled(False)
            else:
                self.startbtn.setText('Start logging')
                #self.conbtn.setEnabled(True)


class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        self.lcd      = QtWidgets.QLCDNumber()
        self.lcd.setSmallDecimalPoint(True)
        layout.addWidget(self.lcd)
        self.lcd.display(0.0)        

    def update(self,data):
        try:
            self.lcd.display(data['data'])
        except:
            self.lcd.display(data['data'][0])