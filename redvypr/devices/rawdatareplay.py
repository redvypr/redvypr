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
from redvypr.data_packets import do_data_statistics, create_data_statistic_dict

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('rawdatareplay')
logger.setLevel(logging.DEBUG)

description = "Replays a raw redvypr data file"

def create_logfile(config):
    funcname = __name__ + '.create_logfile():'
    logger.debug(funcname)
    filebase= config['filename']
    fileext = '.' + config['fileextension']
    if((config['dt_newfile'] > 0) or (config['size_newfile'] > 0)):
       tstr = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
       if(len(filebase) > 0):
           filename = filebase + '_' + tstr + fileext
       else:
           filename = tstr + fileext
    else:
       filename = config['filename']
       
    logger.info(funcname + ' Will create a new file: {:s}'.format(filename))
    if True:
        try:
            f = open(filename,'w+')
            logger.debug(funcname + ' Opened file: {:s}'.format(filename))
        except Exception as e:
            logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
            return None
       
    return [f,filename]



def start(datainqueue,dataqueue,comqueue,config={'filename':''}):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening writing:')
    filename = config['filename']
    if True:
        try:
            dtneworig  = config['dt_newfile']
            dtunit     = config['dt_newfile_unit']
            if(dtunit.lower() == 'second'):
                dtfac = 1.0
            elif(dtunit.lower() == 'hour'):
                dtfac = 3600.0
            elif(dtunit.lower() == 'day'):
                dtfac = 86400.0
            else:
                dtfac = 0
                
            dtnews     = dtneworig * dtfac
            logger.info(funcname + ' Will create new file every {:d} {:s}.'.format(config['dt_newfile'],config['dt_newfile_unit']))
        except Exception as e:
            print('Exception',e)
            dtnews = 0
            
        try:
            sizeneworig  = config['size_newfile']
            sizeunit     = config['size_newfile_unit']
            if(sizeunit.lower() == 'kb'):
                sizefac = 1000.0
            elif(sizeunit.lower() == 'mb'):            
                sizefac = 1e6
            elif(sizeunit.lower() == 'bytes'):            
                sizefac = 1 
            else:
                sizefac = 0
                
            sizenewb     = sizeneworig * sizefac # Size in bytes
            logger.info(funcname + ' Will create new file every {:d} {:s}.'.format(config['size_newfile'],config['size_newfile_unit']))
        except Exception as e:
            print('Exception',e)
            sizenewb = 0  # Size in bytes
            
            
    try:
        config['dt_sync']
    except:
        config['dt_sync'] = 5

    print(funcname,'Config',config)    
    [f,filename] = create_logfile(config)
    statistics = create_data_statistic_dict()
    if(f == None):
       return None
    
    bytes_written         = 0
    packets_written       = 0
    bytes_written_total   = 0
    packets_written_total = 0
    
    tfile           = time.time() # Save the time the file was created
    tflush          = time.time() # Save the time the file was created    
    while True:
        tcheck      = time.time()
        if True:
            file_age      = tcheck - tfile
            FLAG_TIME = (dtnews > 0)  and (file_age >= dtnews)
            FLAG_SIZE = (sizenewb > 0) and (bytes_written >= sizenewb)
            if(FLAG_TIME or FLAG_SIZE):
                f.close()
                [f,filename] = create_logfile(config)
                statistics = create_data_statistic_dict()
                tfile = tcheck   
                bytes_written         = 0
                packets_written       = 0             
       
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
                statistics = do_data_statistics(data,statistics)
                yamlstr = yaml.dump(data,explicit_end=True,explicit_start=True)
                bytes_written         += len(yamlstr)
                packets_written       += 1
                bytes_written_total   += len(yamlstr)
                packets_written_total += 1
                f.write(yamlstr)
                if((time.time() - tflush) > config['dt_sync']):
                    f.flush()
                    os.fsync(f.fileno())
                    tflush = time.time()
                    
                # Send statistics
                data_stat = {}
                data_stat['filename']        = filename
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
        self.publish     = True  # publishes data, a typical device is doing this
        self.subscribe   = False   # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.config      = {}
        self.config['files'] = []
                
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
        self.label    = QtWidgets.QLabel("rawdatareplay setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')
        self.config_widgets= [] # A list of all widgets that can only be used of the device is not started yet
        # Input output widget
        self.inlabel  = QtWidgets.QLabel("Filenames") 
        self.inlist   = QtWidgets.QListWidget()
        self.addfilesbtn   = QtWidgets.QPushButton("Add files")
        self.addfilesbtn.clicked.connect(self.add_files)
        self.config_widgets.append(self.inlist)
        self.config_widgets.append(self.addfilesbtn)
        
        self.startbtn = QtWidgets.QPushButton("Start logging")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)
        self.startbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)
        
        layout.addWidget(self.label,0,0,1,2)
        layout.addWidget(self.inlabel,1,0)
        layout.addWidget(self.addfilesbtn,2,0)               
        layout.addWidget(self.inlist,3,0)      
        layout.addWidget(self.startbtn,4,0,2,2)
        
    def finalize_init(self):
        """ Util function that is called by redvypr after initializing all config (i.e. the configuration from a yaml file)
        """
        pass

    def add_files(self):
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(self,"Rawdatafiles","","redvypr raw (*.redvypr_raw);;All Files (*)")
        print('Filenames',filenames)
        for f in filenames: 
            self.device.config['files'].append(f)
            
        self.update_filenamelist()
            
    def update_filenamelist(self):
        self.inlist.clear()
        for f in self.device.config['files']:
            self.inlist.addItem(f)

    def con_clicked(self):
        funcname = self.__class__.__name__ + '.con_clicked():'
        logger.debug(funcname)
        button = self.sender()
        if(button == self.adddeviceinbtn):
            self.connect.emit(self.device)
            

    def start_clicked(self):
        funcname = self.__class__.__name__ + '.start_clicked():'
        logger.debug(funcname)
        button = self.sender()
        if button.isChecked():
            logger.debug(funcname + "button pressed")
            self.device_start.emit(self.device)
        else:
            logger.debug(funcname + 'button released')
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
        
