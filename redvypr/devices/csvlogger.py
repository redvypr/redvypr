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
from redvypr.device import redvypr_device

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('csvlogger')
logger.setLevel(logging.DEBUG)


def create_logfile(config):
    funcname = __name__ + '.create_logfile()'
    if((config['dt_newfile'] > 0)):
       tstr = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
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



def start(datainqueue,dataqueue,comqueue,config={'filename':'','time':True,'host':True,'device':True,'newline':False,'pcktcnt':False,'keys':['data']}):
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

    try:
        config['datastreams']
    except:
        logger.warning(funcname + ': Need to specify datastreams aborting')
        return None
        
    [f,filename] = create_logfile(config)
    if(f == None):
        logger.warning(funcname + ': Could not open csv file {:s}'.format())
        return None
   
   
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
    
    bytes_written   = 0
    packets_written = 0
    tfile           = time.time() # Save the time the file was created
    tflush          = time.time() # Save the time the file was created    
    while True:
        tcheck = time.time()
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
                datastr = ''
                tstr = datetime.datetime.fromtimestamp(data['t']).strftime('%Y-%m-%d %H:%M:%S.%f')
                datastr += tstr
                datastr += '\n'
                    
                print('Datastr',datastr)
                bytes_written += len(datastr)
                packets_written += 1
                f.write(datastr)
                if((time.time() - tflush) > config['dt_sync']):
                    f.flush()
                    os.fsync(f.fileno())
                    tflush = time.time()
                    
            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))
                #print(data)

class Device(redvypr_device):
    def __init__(self,**kwargs):
        """
        """
        super(Device, self).__init__(**kwargs)
        try:
            self.config['datastreams']
        except:
            self.config['datastreams'] = set()
            

    def start(self):
        config=copy.deepcopy(self.config)
        try:
            config['datastreams']
        except:
            config['datastreams'] = set()

        start(self.datainqueue,self.dataqueue,self.comqueue,config=config)
        
    def __str__(self):
        sstr = 'csvlogger'
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
        self.redvypr  = device.redvypr
        self.label    = QtWidgets.QLabel("CSV-Logger setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')
        self.config_widgets = [] # A list of all widgets that can only be used of the device is not started yet
        # The output tree widget
        self.outfilebutton = QtWidgets.QPushButton("Logfile")
        self.outfilebutton.clicked.connect(self.get_filename)
        self.outfilename = QtWidgets.QLineEdit()
        self.config_widgets.append(self.outfilebutton)
        self.config_widgets.append(self.outfilename)
        try:
            filename = self.device.config['filename']
        except:
            tnow = datetime.datetime.now()
            filename = tnow.strftime("redvypr_%Y-%m-%d_%H%M%S.csv")

        self.outfilename.setText(filename)
        
        self.create_datasteamwidget()
        
        # The rest
        #self.conbtn = QtWidgets.QPushButton("Connect logger to devices")
        #self.conbtn.clicked.connect(self.con_clicked)        
        self.startbtn = QtWidgets.QPushButton("Start logging")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)

        layout.addWidget(self.label,0,0)  
        layout.addWidget(self.outfilebutton,1,0)
        layout.addWidget(self.outfilename,2,0)
        layout.addWidget(self.datastreamwidget,3,0)
        layout.addWidget(self.startbtn,5,0)
        
        self.update_datastreamwidget()
        self.redvypr.device_added.connect(self.update_datastreamwidget)
        
    def finalize_init(self):
        """ Util function that is called by redvypr after initializing all config (i.e. the configuration from a yaml file)
        """
        funcname = self.__class__.__name__ + '.finalize_init()'
        logger.debug(funcname)
        
        
    def create_datasteamwidget(self):
        """
        """
        self.datastreamwidget = QtWidgets.QWidget()
        self.datastreamwidget_layout = QtWidgets.QGridLayout(self.datastreamwidget)
        self.addallbtn = QtWidgets.QPushButton('Add all')
        self.addallbtn.clicked.connect(self.addremstream)
        self.remallbtn = QtWidgets.QPushButton('Rem all')
        self.remallbtn.clicked.connect(self.addremstream)
        self.arrleft = QtWidgets.QToolButton()
        self.arrleft.setArrowType(QtCore.Qt.LeftArrow)
        self.arrleft.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Fixed)
        self.arrleft.clicked.connect(self.addremstream)
        self.arrright = QtWidgets.QToolButton()
        self.arrright.setArrowType(QtCore.Qt.RightArrow)
        self.arrright.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Fixed)
        self.arrright.clicked.connect(self.addremstream)
        # Datastreams
        self.datastreamlist_all = QtWidgets.QListWidget()
        self.datastreamlist_choosen = QtWidgets.QListWidget()
        
        self.config_widgets.append(self.datastreamlist_all) 
        self.config_widgets.append(self.datastreamlist_choosen) 
        self.config_widgets.append(self.arrleft) 
        self.config_widgets.append(self.arrright) 
        self.config_widgets.append(self.remallbtn) 
        self.config_widgets.append(self.addallbtn) 
        
        self.datastreamwidget_layout.addWidget(QtWidgets.QLabel('Available Datastreams'),0,0,1,2)
        self.datastreamwidget_layout.addWidget(self.datastreamlist_all,1,0,6,2)
        self.datastreamwidget_layout.addWidget(self.arrleft,5,2)
        self.datastreamwidget_layout.addWidget(self.remallbtn,4,2)
        self.datastreamwidget_layout.addWidget(self.addallbtn,3,2)
        self.datastreamwidget_layout.addWidget(self.arrright,2,2)
        self.datastreamwidget_layout.addWidget(QtWidgets.QLabel('Datastreams to log'),0,3,1,2)
        self.datastreamwidget_layout.addWidget(self.datastreamlist_choosen,1,3,6,2)
        
    def addremstream(self):
        funcname = self.__class__.__name__ + '.addremstream():'
        logger.debug(funcname)
        button = self.sender()
        if(button == self.arrright): # Add selected
            print('right')
            streams = self.datastreamlist_all.selectedItems()
            for streamitem in streams:
                stream = streamitem.text()
                print('stream',stream)
                self.device.config['datastreams'].add(stream)
                
        elif(button == self.addallbtn): # Add all
            for i in range(self.datastreamlist_all.count()):
                stream = self.datastreamlist_all.item(i).text()
                self.device.config['datastreams'].add(stream)
                
        elif(button == self.remallbtn): # Rem all            
            self.device.config['datastreams'] = set()
                
        elif(button == self.arrleft):
            print('left')
            streams = self.datastreamlist_choosen.selectedItems()
            print(self.device.config['datastreams'])
            for streamitem in streams:
                stream = streamitem.text()
                print('stream',stream)
                self.device.config['datastreams'].remove(stream)
            
        self.update_datastreamwidget()
        
    def update_datastreamwidget(self):
        funcname = self.__class__.__name__ + '.update_datastreamwidget():'
        logger.debug(funcname)
        datastreams = self.redvypr.get_datastreams()
        self.datastreamlist_all.clear()
        self.datastreamlist_choosen.clear()
        for d in datastreams:
            dshort = d.split('::')[0]
            if(dshort[0] != '?'):
                self.datastreamlist_all.addItem(dshort)
                
        datastreams_subscribed = self.device.config['datastreams']
        for d in datastreams_subscribed:
            self.datastreamlist_choosen.addItem(d)

    def get_filename(self):
        tnow = datetime.datetime.now()
        filename_suggestion = tnow.strftime("redvypr_%Y-%m-%d_%H%M%S.csv")
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(self,"CSV file",filename_suggestion,"CSV Files (*.csv);;All Files (*)")
        if filename:
            self.outfilename.setText(filename)
            self.device.config['filename'] = filename


    def con_clicked(self):
        print('Connect clicked')
        button = self.sender()
        self.connect.emit(self.device)        
            
    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            logger.debug("button pressed")
            # The filename
            self.device.config['filename'] = self.outfilename.text()
            # Connect the datastreams
            
            self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            self.device_stop.emit(self.device)

            
    def thread_status(self,status):
        self.update_device_list()        
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
        
