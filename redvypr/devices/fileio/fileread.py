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
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple

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
    packets_per_second: float = pydantic.Field(default=2.0, description='Number of packets per second')
    loop: bool = pydantic.Field(default=False, description='Loop over all files if set')
    chunksize: int = pydantic.Field(default=2560, description='The chunksize to be read from the file and used as a package')
    bytes_per_second: int = pydantic.Field(default=-1, description='The datarate in bytes per second to read data')
    delimiter: bytes = pydantic.Field(default=b'\n', description='The delimiter for a packet, leave empty to disable')

redvypr_devicemodule = True

        
def start(device_info, config={'filename': ''}, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening reading:')
    files = config['files']
    t_sent = 0 # The time the last packets was sent
    t_packet_old = 1e12 # The time the last packet had (internally)
    #

    try:
        config['loop']
    except:
        config['loop'] = False
        
    loop = config['loop']
    
    #bps_config = 115200
    bps_config = -1
    packets_per_second = config['packets_per_second']
    t_last = -1
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

        packet_per_second_tmp = 1/(time.time() - t_last)
        if (packet_per_second_tmp > packets_per_second) and (packets_per_second>0):
            time.sleep(0.01)
        else:
            try:
                data_raw = b''
                while True:
                    #data_tmp = f.read(config['chunksize'])
                    data_tmp = f.read(1)
                    data_raw += data_tmp
                    bytes_read += 1
                    if (len(config['delimiter']) > 0) and (data_tmp == config['delimiter']):
                        tread = time.time()
                        bytes_read_bps += len(data_raw)
                        break
                    elif (data_tmp == b'') or ((len(data_raw) >= config['chunksize']) and config['chunksize']>0):
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
                    t_last = t_now
                    packets_read += 1

            if FLAG_NEW_FILE:
                try:
                    f.close()
                except:
                    pass

                if nfile >= len(files):
                    if loop == False:
                        sstr = funcname + ': All files read, stopping now.'
                        #try:
                        #    statusqueue.put_nowait(sstr)
                        #except:
                        #    pass
                        logger.info(sstr)
                        break
                    else:
                        sstr = funcname + ': All files read, loop again.'
                        #try:
                        #    statusqueue.put_nowait(sstr)
                        #except:
                        #    pass

                        logger.info(sstr)
                        nfile = 0

                filename = files[nfile]
                sstr = 'Opening file {:s}'.format(filename)
                #try:
                #    statusqueue.put_nowait(sstr)
                #except:
                #    pass
                logger.info(sstr)
                filesize = os.path.getsize(filename)
                f = open(filename,'rb')
                bytes_read = 0
                packets_read = 0
                nfile += 1

        if (time.time() - tupdate) > 1.0:
            tupdate = time.time()
            #print('f', bytes_read_bps, bytes_read / filesize * 100)
            statusdict = {'nfile':nfile,'td':datetime.datetime.now(), 'filename':filename, 'bps':bytes_read_bps, 'pc':bytes_read / filesize * 100,'packets_sent':packets_read}
            statusqueue.put_nowait(statusdict)

        if (bytes_read_bps >= bps_config) and (bps_config>0):
            dt_sleep = 0.05
            time.sleep(dt_sleep)
            bytes_read_bps -= int(bps_config * 0.05)

#
#
# The init widget
#
#
class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args, **kwargs)
        layout = QtWidgets.QGridLayout()
        self.file_statistics = {}
        #self.device   = device
        self.label    = QtWidgets.QLabel("Fileread")
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
        
        self.__filelistheader__ = ['Name','Size','% read','Packets sent']
        self.inlist.setHorizontalHeaderLabels(self.__filelistheader__)
        self.addfilesbtn   = QtWidgets.QPushButton("Add files")
        self.addfilesbtn.clicked.connect(self.add_files)
        self.remfilesbtn   = QtWidgets.QPushButton("Rem files")
        self.remfilesbtn.clicked.connect(self.rem_files)
        self.config_widgets.append(self.remfilesbtn)
        self.config_widgets.append(self.addfilesbtn)
        # Looping the data?
        self.loop_checkbox = QtWidgets.QCheckBox('Loop')
        self.loop_checkbox.setChecked(self.device.custom_config.loop)
        # Delimiter
        self.delimiter_edit  = QtWidgets.QLineEdit(self)
        self.delimiter_edit.setToolTip("Delimiter for a new packet, leave empty if not required (i.e. '\n', '\r')")
        self.delimiter_label = QtWidgets.QLabel("Delimiter for new packet")
        delimiter_text = self.device.custom_config.delimiter.decode('utf-8').replace("\n", "\\n").replace("\0", "\\0").replace("\r", "\\r")
        self.delimiter_edit.setText(delimiter_text)

        self.chunksize_edit = QtWidgets.QSpinBox()
        self.chunksize_edit.setMaximum(1000000)
        self.chunksize_edit.setMinimum(0)
        self.chunksize_edit.setToolTip("The chunksize to be read per packet.")
        self.chunksize_label = QtWidgets.QLabel("Chunksize")
        self.chunksize_edit.setValue(self.device.custom_config.chunksize)

        self.packets_per_second_edit = QtWidgets.QDoubleSpinBox()
        self.packets_per_second_edit.setToolTip("The number of packets to be sent per second")
        self.packets_per_second_label = QtWidgets.QLabel("Packets per second")
        self.packets_per_second_edit.setValue(self.device.custom_config.packets_per_second)
        
        layout.addWidget(self.label,0,0,1,-1)
        
        layout.addWidget(self.addfilesbtn,1,0,1,-1)               
        layout.addWidget(self.remfilesbtn,2,0,1,-1)          
        layout.addWidget(self.inlabel,4,0,1,-1,QtCore.Qt.AlignCenter)
        layout.addWidget(self.inlist,5,0,1,-1)
        layout.addWidget(self.loop_checkbox,6,0)
        layout.addWidget(self.delimiter_label,6, 1, 1, 1,QtCore.Qt.AlignRight)
        layout.addWidget(self.delimiter_edit, 6, 2, 1, 1, QtCore.Qt.AlignRight)
        layout.addWidget(self.chunksize_label, 6, 3, 1, 1, QtCore.Qt.AlignRight)
        layout.addWidget(self.chunksize_edit, 6, 4, 1, 1, QtCore.Qt.AlignRight)
        layout.addWidget(self.packets_per_second_label, 6, 5, 1, 1, QtCore.Qt.AlignRight)
        layout.addWidget(self.packets_per_second_edit, 6, 6, 1, 1, QtCore.Qt.AlignRight)

        self.layout_buttons.removeWidget(self.subscribe_button)
        self.layout_buttons.removeWidget(self.configure_button)
        self.layout_buttons.addWidget(self.configure_button,3,5,1,1)
        #self.layout_buttons.addWidget(self.configure_button, 2, 2, 1, 2)
        self.subscribe_button.close()
        self.startbutton.disconnect()
        self.startbutton.clicked.connect(self.start_clicked)
        self.layout.addLayout(layout)

        self.statustimer_2 = QtCore.QTimer()
        self.statustimer_2.timeout.connect(self.update_status)
        self.statustimer_2.start(500)

    def finalize_init(self):
        """ Util function that is called by redvypr after initializing all config (i.e. the configuration from a yaml file)
        """
        funcname = self.__class__.__name__ + '.finalize_init()'
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
            size_in_bytes = os.path.getsize(f)
            sizestr = str(size_in_bytes)
            item = QtWidgets.QTableWidgetItem(sizestr)
            self.inlist.setItem(i, 1, item)
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
            # Delimiter
            str_newlines = self.delimiter_edit.text().replace("\\n", "\n").replace("\\r", "\r").replace("\\0", "\0")
            byte_array = str_newlines.encode("utf-8")
            self.device.custom_config.delimiter = byte_array
            self.device.custom_config.packets_per_second = self.packets_per_second_edit.value()
            self.device.thread_start()
        else:
            logger.debug(funcname + 'button released')
            self.device.thread_stop()

    def update_status(self):
        statusqueue = self.device.statusqueue
        while (statusqueue.empty() == False):
            try:
                statusdata = statusqueue.get(block=False)
                print('Data',statusdata)
                filename = statusdata['filename']
                for i, f in enumerate(self.device.custom_config.files):
                    if f == filename:
                        percentstr = "{:.2f}".format(statusdata['pc'])
                        item = QtWidgets.QTableWidgetItem(percentstr)  # Percent read
                        self.inlist.setItem(i, 2, item)
                        packetstr = "{:d}".format(statusdata['packets_sent'])
                        item = QtWidgets.QTableWidgetItem(packetstr)  # Packets sent
                        self.inlist.setItem(i, 3, item)
            except:
                logger.info('Problem',exc_info=True)
                break





