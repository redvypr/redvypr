import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import yaml
import pydantic
import typing
import copy
import os
from redvypr.device import RedvyprDevice
from redvypr.data_packets import check_for_command
from redvypr.packet_statistic import do_data_statistics, create_data_statistic_dict

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.fileread')
logger.setLevel(logging.DEBUG)


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = "Reads a file and publishes the data as chunks defined by the users"
    gui_tablabel_display: str = 'File status'
    gui_icon: str = 'mdi.code-json'

class DeviceCustomConfig(pydantic.BaseModel):
    files: list = pydantic.Field(default=[], description='List of files to replay')
    replay_index: list = pydantic.Field(default=['0,-1,1'], description='The index of the packets to be replayed [start, end, nth]')
    loop: bool = pydantic.Field(default=False, description='Loop over all files if set')
    chunksize: int = pydantic.Field(default=2560, description='The chunksize to be read from the file')
    delimiter: bytes = pydantic.Field(default=b'\n', description='The delimiter for a packet')

redvypr_devicemodule = True

        
def start(device_info, config={'filename': ''}, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening reading:')
    files = config['files']
    print('Config',config)
    t_sent = 0 # The time the last packets was sent
    t_packet_old = 1e12 # The time the last packet had (internally)
    #
    try:
        config['speedup']
    except:
        config['speedup'] = 1.0 # Realtime
    
    speedup = config['speedup']    
    #
    try:
        config['loop']
    except:
        config['loop'] = False
        
    loop = config['loop']
    
    bps_config = 115200

    statistics = create_data_statistic_dict()
    
    bytes_read = 0
    packets_read = 0
    bytes_read_total = 0
    packets_read_total = 0

    bytes_read_bps = 0
    tupdate = time.time()
    f = None    
    nfile = 0
    while True:
        tcheck = time.time()
        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if (data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            # logger.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                sstr = funcname + ': Command is for me: {:s}'.format(str(command))
                logger.debug(sstr)
                if command == 'stop':
                    logger.debug('Stopping')
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass
                    break

        try:
            data_raw = b''
            while True:
                #data_tmp = f.read(config['chunksize'])
                data_tmp = f.read(1)
                data_raw += data_tmp
                bytes_read += 1
                if data_tmp == config['delimiter'] or data_tmp == b'' or len(data_raw) >= config['chunksize']:
                    tread = time.time()
                    bytes_read_bps += len(data_raw)
                    break

        except:
            logger.debug('Could not read data',exc_info=True)
            data_raw = b''

        if(len(data_raw) == 0):
            FLAG_NEW_FILE = True
        else:
            FLAG_NEW_FILE = False
            
        if(len(data_raw) > 0):
            p = {'data':data_raw}
            #print('P',p)
            if True:
                t_now = time.time()
                dataqueue.put(p)

        if FLAG_NEW_FILE:
            try:
                f.close()
            except:
                pass

            if nfile >= len(files):
                if loop == False:
                    sstr = funcname + ': All files read, stopping now.'
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass
                    logger.info(sstr)
                    break
                else:
                    sstr = funcname + ': All files read, loop again.'
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass

                    logger.info(sstr)
                    nfile = 0
            
            filename = files[nfile]
            sstr = 'Opening file {:s}'.format(filename)
            try:
                statusqueue.put_nowait(sstr)
            except:
                pass
            logger.info(sstr)
            filesize = os.path.getsize(filename)
            f = open(filename,'rb')
            bytes_read = 0
            nfile += 1

        if (time.time() - tupdate) > 2.0:
            tupdate = time.time()
            #print('f', bytes_read_bps, bytes_read / filesize * 100)
            sstr = "{}: {}, {} bps, {:.1f}%".format(datetime.datetime.now(), filename, bytes_read_bps, bytes_read / filesize * 100)
            statusqueue.put_nowait(sstr)

        if bytes_read_bps >= bps_config:
            dt_sleep = 0.05
            time.sleep(dt_sleep)
            bytes_read_bps -= int(bps_config * 0.05)

#
#
# The init widget
#
#
class initDeviceWidget(QtWidgets.QWidget):
    connect      = QtCore.pyqtSignal(RedvyprDevice) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QGridLayout(self)
        self.file_statistics = {}
        self.device   = device
        self.label    = QtWidgets.QLabel("rawdatareplay setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')
        self.config_widgets= [] # A list of all widgets that can only be used of the device is not started yet
        # Input output widget
        self.inlabel  = QtWidgets.QLabel("Filenames") 
        self.inlabel.setStyleSheet(''' font-size: 20px; font: bold''')
        self.inlist   = QtWidgets.QTableWidget()
        self.inlist.setColumnCount(4)
        self.inlist.setRowCount(1)
        self.inlist.setSortingEnabled(True)
        
        self.__filelistheader__ = ['Name','Packets','First date','Last date']
        self.inlist.setHorizontalHeaderLabels(self.__filelistheader__)
        self.addfilesbtn   = QtWidgets.QPushButton("Add files")
        self.addfilesbtn.clicked.connect(self.add_files)
        self.remfilesbtn   = QtWidgets.QPushButton("Rem files")
        self.remfilesbtn.clicked.connect(self.rem_files)
        self.scanfilesbtn   = QtWidgets.QPushButton("Scan files")
        self.scanfilesbtn.clicked.connect(self.scan_files_clicked)
        self.config_widgets.append(self.inlist)
        self.config_widgets.append(self.addfilesbtn)
        # Looping the data?
        self.loop_checkbox = QtWidgets.QCheckBox('Loop')
        # Speedup
        self.speedup_edit  = QtWidgets.QLineEdit(self)
        onlyDouble = QtGui.QDoubleValidator()
        self.speedup_edit.setValidator(onlyDouble)
        self.speedup_edit.setToolTip('Speedup of the packet replay.')
        self.speedup_label = QtWidgets.QLabel("Speedup factor")
        self.speedup_edit.setText("1.0")
        
        
        self.startbtn = QtWidgets.QPushButton("Start replay")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)
        self.startbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)
        
        layout.addWidget(self.label,0,0,1,-1)
        
        layout.addWidget(self.addfilesbtn,1,0,1,-1)               
        layout.addWidget(self.remfilesbtn,2,0,1,-1)          
        layout.addWidget(self.scanfilesbtn,3,0,1,-1)
        layout.addWidget(self.inlabel,4,0,1,-1,QtCore.Qt.AlignCenter)         
        layout.addWidget(self.inlist,5,0,1,-1)
        layout.addWidget(self.loop_checkbox,6,0)
        layout.addWidget(self.speedup_label,6,1,1,1,QtCore.Qt.AlignRight)
        layout.addWidget(self.speedup_edit,6,2,1,1,QtCore.Qt.AlignRight)
        layout.addWidget(self.startbtn,7,0,2,-1)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def finalize_init(self):
        """ Util function that is called by redvypr after initializing all config (i.e. the configuration from a yaml file)
        """
        funcname = self.__class__.__name__ + '.finalize_init()'
        logger.debug(funcname)
        
    def scan_files_clicked(self):
        """ Scans the selected files from the files list for possible datastreams 
        """
        funcname = self.__class__.__name__ + '.scan_files_clicked()'
        logger.debug(funcname)

        
    def rem_files(self):
        """ Remove the selected files from the files list
        """
        funcname = self.__class__.__name__ + '.rem_files()'
        logger.debug(funcname)
        rows = []
        for i in self.inlist.selectionModel().selection().indexes():
            row, column = i.row(), i.column()
            rows.append(row)
        
        rows = list(set(rows))
        rows.sort(reverse=True)  
        for i in rows:
            self.device.custom_config.files.pop(i)
            
        self.update_filenamelist() 

    def add_files(self):
        """ Opens a dialog to choose file to add
        """
        funcname = self.__class__.__name__ + '.add_files()'
        logger.debug(funcname)
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(self,"Rawdatafiles","","All Files (*)")
        for f in filenames: 
            self.device.custom_config.files.append(f)
            
        
        self.update_filenamelist()
        self.inlist.sortItems(0, QtCore.Qt.AscendingOrder)
            
    def update_filenamelist(self):
        """ Update the filetable 
        """
        funcname = self.__class__.__name__ + '.add_files()'
        logger.debug(funcname)
        self.inlist.clear()
        self.inlist.setHorizontalHeaderLabels(self.__filelistheader__)
        nfiles = len(self.device.custom_config.files)
        self.inlist.setRowCount(nfiles)

        rows = []        
        for i,f in enumerate(self.device.custom_config.files):
            item = QtWidgets.QTableWidgetItem(f)
            self.inlist.setItem(i,0,item)
            rows.append(i)

        self.inlist.resizeColumnsToContents()
        
    def resort_files(self):
        """ Resorts the files in config['files'] according to the sorting in the table
        """
        files_new = []
        nfiles = len(self.device.custom_config.files)
        for i in range(nfiles):
            filename = self.inlist.item(i,0).text()
            files_new.append(filename)
            
        self.device.custom_config.files = files_new
        
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
            self.resort_files()
            loop = self.loop_checkbox.isChecked()
            # Loop
            self.device.custom_config.loop = loop
            # Speedup
            #self.device.custom_config['speedup'] = float(self.speedup_edit.text())
            self.device.thread_start()
        else:
            logger.debug(funcname + 'button released')
            self.device.thread_stop()

            
    def update_buttons(self):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """

            status = self.device.get_thread_status()
            thread_status = status['thread_running']

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
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout          = QtWidgets.QVBoxLayout(self)
        hlayout         = QtWidgets.QHBoxLayout()
        self.device     = device
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
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update)
        self.statustimer.start(500)

    def update(self):
        statusqueue = self.device.statusqueue
        while True:
            try:
                data = statusqueue.get(block=False)
            except:
                #logger.info('Could not read data',exc_info=True)
                break

            self.text.insertPlainText(str(data) + '\n')

        #self.byteslab.setText("Bytes written: {:d}".format(data['bytes_written']))
        #self.packetslab.setText("Packets written: {:d}".format(data['packets_written']))
        #self.text.insertPlainText(str(data['data']))
        
