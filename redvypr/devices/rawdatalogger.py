# TODO, improve keys!
import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import yaml
import copy
import os

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('rawdatalogger')
logger.setLevel(logging.DEBUG)

description = "Saves the raw redvypr packets into a file"

def create_logfile(config):
    funcname = __name__ + '.create_logfile()'
    if((config['dt_newfile'] > 0)):
       tstr = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
       (filebase,fileext)=os.path.splitext(config['filename'])
       filename = filebase + '_' + tstr + fileext
    else:
       filename = config['filename']
       
    logger.info(funcname + ': Will create a new file: {:s}'.format(filename))
    if True:
        try:
            f = open(filename,'w+')
            logger.debug(funcname + 'Opened file: {:s}'.format(filename))
        except Exception as e:
            logger.warning(funcname + ': Error opening file:' + filename + ':' + str(e))
            return None
       
    return [f,filename]



def start(datainqueue,dataqueue,comqueue,config={'filename':''}):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening writing:')
    filename = config['filename']
    try:
        logger.info(funcname + ' Will create new file every {:d}s.'.format(config['dt_newfile']))
    except:
        config['dt_newfile'] = 0

    try:
        config['dt_sync']
    except:
        config['dt_sync'] = 5

    print('Config',config)    
    #[f,filename] = create_logfile(config)
    #if(f == None):
    #   return None
    
    bytes_written   = 0
    packets_written = 0
    tfile   = time.time() # Save the time the file was created
    tflush  = time.time() # Save the time the file was created    
    while True:
        tcheck = time.time()
        try:
            dt = tcheck - tfile
            if((config['dt_newfile'] > 0) and (config['dt_newfile'] <= dt)):
                f.close()
                [f,filename] = create_logfile(config)
                tfile = tcheck                
        except:
            pass
       
        try:
            com = comqueue.get(block=False)
            logger.debug(funcname + ': received:' + str(com))
            # Closing all open files
            try:
                f.close()
            except Exception as e:
                logger.debug(funcname + ': could not close:' + str(f))
                
            break
        except Exception as e:
            #logger.warning(funcname + ': Error stopping thread:' + str(e))
            pass


        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
                yamlstr = yaml.dump(data,explicit_end=True,explicit_start=True)
                print(yamlstr)   
                #print('Datastr',datastr)
                bytes_written += len(yamlstr)
                packets_written += 1
                #f.write(datastr)
                #if((time.time() - tflush) > config['dt_sync']):
                #    f.flush()
                #    os.fsync(f.fileno())
                #    tflush = time.time()
                    
                # Send statistics
                data_stat = {}
                data_stat['filename'] = filename
                data_stat['bytes_written']   = bytes_written
                data_stat['packets_written'] = packets_written                
                #dataqueue.put(data_stat)

            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))
                #print(data)

class Device():
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None):
        """
        """
        self.publish     = False  # publishes data, a typical device is doing this
        self.subscribe   = True   # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.config      = {}
        self.config['filename']= ''
                
    def start(self):
        funcname = self.__class__.__name__
        logger.debug(funcname)
        print('Starting',self.config)
        config=copy.deepcopy(self.config)
        start(self.datainqueue,self.dataqueue,self.comqueue,config=config)
        
    def __str__(self):
        sstr = 'rawdatalogger'
        return sstr

#
#
# The init widget
#
#


class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device) # Signal requesting a start of the device (starting the thread)
    device_stop  = QtCore.pyqtSignal(Device) # Signal requesting a stop of device
    connect      = QtCore.pyqtSignal(Device) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QGridLayout(self)
        self.device   = device
        self.label    = QtWidgets.QLabel("rawdatalogger setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')
        self.config_widgets= [] # A list of all widgets that can only be used of the device is not started yet
        # Input output widget
        self.inlabel  = QtWidgets.QLabel("Input") 
        self.inlist   = QtWidgets.QListWidget()
        self.adddeviceinbtn   = QtWidgets.QPushButton("Add/Rem device")
        self.adddeviceinbtn.clicked.connect(self.con_clicked)
        self.addallbtn   = QtWidgets.QPushButton("Add all devices")
        self.addallbtn.clicked.connect(self.con_clicked)                
        # The output widgets
        self.outlabel = QtWidgets.QLabel("Logfile")
        self.outfilename = QtWidgets.QLineEdit()
        try:
            filename = self.device.config['filename']
        except:
            filename = ''

        self.outfilename.setText(filename)
        
        self.addfilebtn   = QtWidgets.QPushButton("Add file")
        self.config_widgets.append(self.addfilebtn)       
        self.addfilebtn.clicked.connect(self.get_filename)
        
        # The rest
        #self.conbtn = QtWidgets.QPushButton("Connect logger to devices")
        #self.conbtn.clicked.connect(self.con_clicked)        
        self.startbtn = QtWidgets.QPushButton("Start logging")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)
        self.startbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)


        # Delta t for new file
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
        self.dt_newfile = edit
        self.dt_newfile.setToolTip('Create a new file every N seconds.\nFilename is "filenamebase"_yyyymmdd_HHMMSS."ext".\nUse 0 to disable feature.')
        try:
            self.dt_newfile.setText(str(self.device.config['dt_newfile']))
        except Exception as e:
            self.dt_newfile.setText('0')
            
        
            
        self.outwidget = QtWidgets.QWidget()
        self.outlayout = QtWidgets.QVBoxLayout(self.outwidget)
        self.outlayout.addWidget(self.outfilename)
        self.outlayout.addWidget(self.addfilebtn)
        self.outlayout.addWidget(QtWidgets.QLabel('dt newfile'))
        self.outlayout.addWidget(self.dt_newfile)
        self.outlayout.addStretch(1)
            
        layout.addWidget(self.label,0,0,1,2)
        layout.addWidget(self.inlabel,1,0)         
        layout.addWidget(self.inlist,2,0)      
        layout.addWidget(self.adddeviceinbtn,3,0)      
        layout.addWidget(self.addallbtn,4,0)   
        layout.addWidget(self.outlabel,1,1)
        layout.addWidget(self.outwidget,2,1,3,1)   
        layout.addWidget(self.startbtn,6,0,2,2)
        
    def finalize_init(self):
        """ Util function that is called by redvypr after initializing all config (i.e. the configuration from a yaml file)
        """
        # Update the device list, if devices have been connected
        self.redvypr.devices_connected.connect(self.update_device_list)

    def get_filename(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(self,"Logging file","","All Files (*);;Text Files (*.txt)")
        if filename:
            self.outfilename.setText(filename)
            self.device.config['filename'] = filename


    def con_clicked(self):
        funcname = self.__class__.__name__ + '.con_clicked():'
        logger.debug(funcname)
        button = self.sender()
        if(button == self.adddeviceinbtn):
            self.connect.emit(self.device)
        elif(button == self.addallbtn):
            print('Add all')
            #devices = self.redvypr.get_data_providing_devices(self.device)
            devices = self.redvypr.get_data_providing_devices()
            for d in devices:
                print('Adding',d.name)
                self.redvypr.addrm_device_as_data_provider(d,self.device)
            
            #self.update_device_list()
                            
    def update_device_list(self,devicestr_provider='',devicestr_receiver=''):
        funcname = self.__class__.__name__ + '.update_device_list():'
        logger.debug(funcname)
        print('Devices',devicestr_provider,devicestr_receiver)
        devices = self.redvypr.get_data_providing_devices(self.device)
        self.inlist.clear()
        for d in devices:
            print(d)
            devname = d.name
            self.inlist.addItem(devname)
        
    def start_clicked(self):
        funcname = self.__class__.__name__ + '.start_clicked():'
        logger.debug(funcname)        
        button = self.sender()
        if button.isChecked():
            logger.debug("button pressed")
            self.device.config['dt_filename']= int(self.dt_newfile.text())
            self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            self.device_stop.emit(self.device)

            
    def thread_status(self,status):
        self.update_buttons(status['threadalive'])
        
    def update_buttons(self,thread_status):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """
            # Running
            if(thread_status):
                self.startbtn.setText('Stop')
                self.startbtn.setChecked(True)
                for w in self.config_widgets:
                    w.setEnabled(False)
            # Not running
            else:
                self.startbtn.setText('Start')
                for w in self.config_widgets:
                    w.setEnabled(True)
                    
                # Check if an error occured and the startbutton 
                if(self.startbtn.isChecked()):
                    self.startbtn.setChecked(False)
                #self.conbtn.setEnabled(True)


class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()
        layout          = QtWidgets.QVBoxLayout(self)
        hlayout         = QtWidgets.QHBoxLayout()        
        self.text       = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.filelab= QtWidgets.QLabel("File: ")
        self.byteslab   = QtWidgets.QLabel("Bytes written: ")
        self.packetslab = QtWidgets.QLabel("Packets written: ")
        self.text.setMaximumBlockCount(10000)
        hlayout.addWidget(self.byteslab)
        hlayout.addWidget(self.packetslab)
        layout.addWidget(self.filelab)        
        layout.addLayout(hlayout)
        layout.addWidget(self.text)
        #self.text.insertPlainText("hallo!")        

    def update(self,data):
        #print('data',data)
        self.filelab.setText("File: {:s}".format(data['filename']))        
        self.byteslab.setText("Bytes written: {:d}".format(data['bytes_written']))
        self.packetslab.setText("Packets written: {:d}".format(data['packets_written']))
        self.text.insertPlainText(str(data['data']))
        
