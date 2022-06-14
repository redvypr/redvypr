import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import sys

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('randdata')
logger.setLevel(logging.DEBUG)

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
        
    def get_datakeys(self):
        """ Returns a list of datakey that the device has in their data dictionary
        """
        return ['t','data','?data']

        
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
            
        #print('n',n)               
        rng = np.random.default_rng()
        xold = 0
        while True:
            try:
                com = self.comqueue.get(block=False)
                logger.debug('Received {:s}'.format(str(com)))
                break
            except Exception as e:
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
                        
                    elif(func['name']=='const'):
                        try:
                            x += float(func['const'])
                        except Exception as e:
                            self.logger.debug(str(e))
                        
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
            data = {'t':tall,'data':xall,'?data':{'unit':data_unit,'type':'f'}}
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
        layout        = QtWidgets.QGridLayout(self)
        self.device   = device
        self.label    = QtWidgets.QLabel("Random data setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')
        
        self.editwidget = [] # A list of all widgets that are editable and need to be enabled/disabled
        self.startbtn = QtWidgets.QPushButton("Start data")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)    
        
        # Sampling time
        self.dt_edit = QtWidgets.QLineEdit(self)
        onlyDouble = QtGui.QDoubleValidator()
        self.dt_edit.setValidator(onlyDouble)
        self.dt_edit.setToolTip('Time of a new sample')
        self.dt_label = QtWidgets.QLabel("Sampling time [s]")
        self.editwidget.append(self.dt_edit)
        # Number of samples
        self.n_edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        self.n_edit.setValidator(onlyInt)
        self.n_edit.setToolTip('Number of samples before packet is sent')
        self.n_label = QtWidgets.QLabel("Sample number per packet")
        self.editwidget.append(self.n_edit)
        
        # Unit
        self.unit_edit = QtWidgets.QLineEdit(self)
        self.unit_edit.setToolTip('The unit of the random data')
        self.unit_label = QtWidgets.QLabel("Unit")
        self.unit_edit.setText('Urand')
        self.editwidget.append(self.unit_edit)
        
        # Constant function
        self.constlabel    = QtWidgets.QLabel("Constant function")
        #self.constlabel.setAlignment(QtCore.Qt.AlignCenter)
        self.constlabel.setStyleSheet(''' font-size: 20px; font: bold''')
        self.const_edit = QtWidgets.QLineEdit(self)
        self.editwidget.append(self.const_edit)
        onlyDouble = QtGui.QDoubleValidator()
        self.const_edit.setValidator(onlyDouble)
        self.const_edit.setToolTip('Constant value')
        self.const_label = QtWidgets.QLabel("Constant")
        self.const_edit.setText('10.0')
        # random function
        self.randlabel    = QtWidgets.QLabel("Random function")
        #self.randlabel.setAlignment(QtCore.Qt.AlignCenter)
        self.randlabel.setStyleSheet(''' font-size: 20px; font: bold''')
        self.rand_edit1 = QtWidgets.QLineEdit(self)
        onlyDouble = QtGui.QDoubleValidator()
        self.rand_edit1.setValidator(onlyDouble)
        self.rand_edit1.setToolTip('Lower value of random range')
        self.rand_label1 = QtWidgets.QLabel("Lower value")
        self.rand_edit2 = QtWidgets.QLineEdit(self)
        onlyDouble = QtGui.QDoubleValidator()
        self.rand_edit2.setValidator(onlyDouble)
        self.rand_edit2.setToolTip('Upper value of random range')
        self.rand_label2 = QtWidgets.QLabel("Upper value")
        self.rand_edit1.setText("-5.0")
        self.rand_edit2.setText("5.0")
        self.editwidget.append(self.rand_edit1)
        self.editwidget.append(self.rand_edit2)
        # sine function
        self.sinelabel    = QtWidgets.QLabel("Sinusodial function")
        #self.sinelabel.setAlignment(QtCore.Qt.AlignCenter)
        self.sinelabel.setStyleSheet(''' font-size: 20px; font: bold''')
        self.sine_edit = QtWidgets.QLineEdit(self)
        onlyDouble = QtGui.QDoubleValidator()
        self.sine_edit.setValidator(onlyDouble)
        self.sine_edit.setToolTip('Amplitude')
        self.sine_label = QtWidgets.QLabel("Amplitude")
        self.sinef_edit = QtWidgets.QLineEdit(self)
        onlyDouble = QtGui.QDoubleValidator()
        self.sinef_edit.setValidator(onlyDouble)
        self.sinef_edit.setToolTip('Frequency')
        self.sinef_label = QtWidgets.QLabel("Frequency")
        self.sine_edit.setText('1.0')
        self.sinef_edit.setText('1.0')
        self.editwidget.append(self.sine_edit)
        self.editwidget.append(self.sinef_edit)
        # counter function
        self.countlabel    = QtWidgets.QLabel("Counter function")
        self.countlabel.setStyleSheet(''' font-size: 20px; font: bold''')
        self.count_edit = QtWidgets.QLineEdit(self)
        onlyDouble = QtGui.QDoubleValidator()
        self.count_edit.setValidator(onlyDouble)
        self.count_edit.setToolTip('Counts the number of packets and scales it by the factor.')
        self.count_label = QtWidgets.QLabel("Factor")
        self.count_edit.setText('1.0')
        self.editwidget.append(self.count_edit)
        # Function checkbox
        self.funccheck_const  = QtWidgets.QCheckBox("Constant")
        self.funccheck_rand   = QtWidgets.QCheckBox("Random")
        self.funccheck_rand.setChecked(True)
        self.funccheck_sine   = QtWidgets.QCheckBox("Sine")
        self.funccheck_count  = QtWidgets.QCheckBox("Counter")
        self.editwidget.append(self.funccheck_const)
        self.editwidget.append(self.funccheck_rand)
        self.editwidget.append(self.funccheck_sine)
        self.editwidget.append(self.funccheck_count)
        checkwidget           = QtWidgets.QWidget()
        hlayout               = QtWidgets.QHBoxLayout(checkwidget)
        hlayout.addWidget(self.funccheck_const)
        hlayout.addWidget(self.funccheck_rand)
        hlayout.addWidget(self.funccheck_sine)
        hlayout.addWidget(self.funccheck_count)
        
        hwidget = QtWidgets.QWidget()
        hlayout = QtWidgets.QHBoxLayout(hwidget)
        hlayout.addWidget(self.dt_label)
        hlayout.addWidget(self.dt_edit)
        hlayout.addWidget(self.n_label)
        hlayout.addWidget(self.n_edit)
        hlayout.addWidget(self.unit_label)
        hlayout.addWidget(self.unit_edit)
        
        layout.addWidget(self.label,0,0,1,-1)
        layout.addWidget(hwidget,1,0,1,-1)
        layout.addWidget(self.constlabel,5,0,1,2)
        layout.addWidget(self.const_label,6,0)
        layout.addWidget(self.const_edit,6,1)
        layout.addWidget(self.randlabel,2,0,1,2)
        layout.addWidget(self.rand_label1,3,0)
        layout.addWidget(self.rand_edit1,3,1)
        layout.addWidget(self.rand_label2,4,0)
        layout.addWidget(self.rand_edit2,4,1)
        
        layout.addWidget(self.sinelabel,2,2,1,2)
        layout.addWidget(self.sine_label,3,2)
        layout.addWidget(self.sine_edit,3,3)
        layout.addWidget(self.sinef_label,4,2)
        layout.addWidget(self.sinef_edit,4,3)
        layout.addWidget(self.countlabel,5,2,1,2)
        layout.addWidget(self.count_label,6,2)
        layout.addWidget(self.count_edit,6,3)
        
        layout.addWidget(checkwidget,7,0,1,-1)
        layout.addWidget(self.startbtn,8,0,1,-1)
        
    def finalize_init(self):
        try:
            self.dt_edit.setText(str(self.device.config['dt']))
        except Exception as e:
            self.dt_edit.setText('0.5')
            
        try:
            self.n_edit.setText(str(self.device.config['n']))
        except Exception as e:
            self.n_edit.setText('1')
            
    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            self.device.config = {'functions':[]}
            self.device.config['dt']   = float(self.dt_edit.text()) 
            self.device.config['n']    = int(self.n_edit.text())
            self.device.config['unit'] = self.unit_edit.text()
             
            # Constant function
            if(self.funccheck_const.isChecked()):
                func = {'name':'const'}
                func['const'] = float(self.const_edit.text())
                self.device.config['functions'].append(func)
            # Random function
            if(self.funccheck_rand.isChecked()):
                func = {'name':'rand'}
                func['range'] = [float(self.rand_edit1.text()), float(self.rand_edit2.text())]
                self.device.config['functions'].append(func)
            # Sine function
            if(self.funccheck_sine.isChecked()):
                func = {'name':'sine'}
                func['amp']   = float(self.sine_edit.text())
                func['f']     = float(self.sinef_edit.text())
                func['phase'] = 0.0
                self.device.config['functions'].append(func)
            # Count function
            if(self.funccheck_count.isChecked()):
                func = {'name':'count'}
                func['count']   = float(self.count_edit.text())
                self.device.config['functions'].append(func)
            
            
            self.device_start.emit(self.device)
            button.setText("Starting")
            
            for e in self.editwidget:
                e.setEnabled(False)
        else:
            button.setText("Stopping")
            self.device_stop.emit(self.device)
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
                self.startbtn.setChecked(False)
                for e in self.editwidget:
                    e.setEnabled(True)
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
