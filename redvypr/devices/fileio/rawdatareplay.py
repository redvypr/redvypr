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
from redvypr.data_packets import do_data_statistics, create_data_statistic_dict,check_for_command

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('rawdatareplay')
logger.setLevel(logging.DEBUG)

description = "Replays a raw redvypr data file"

description = "Saves the raw redvypr packets into a file"
config_template = {}
config_template['name']      = 'rawdatareplay'
config_template['files']             = {'type':'list','description':'List of files ro replay'} # TODO, list
config_template['loop']              = {'type':'bool','default':True,'description':'Loop over all files if set'}
config_template['speedup']           = {'type':'float','description':'Speedup factor of the data'}
config_template['redvypr_device']    = {}
config_template['redvypr_device']['publish']   = False
config_template['redvypr_device']['subscribe'] = True
config_template['redvypr_device']['description'] = description

def get_packets(filestream=None):
    funcname = __name__ + '.get_packets()'
    packets = []
    if(filestream is not None):
        data = filestream.read()
        for databs in data.split('...\n'): # Split the text into single subpackets
            try:
                data = yaml.safe_load(databs)
                if(data is not None):
                    packets.append(data)
                    
            except Exception as e:
                logger.debug(funcname + ': Could not decode message {:s}'.format(str(databs)))
                data = None
    
        return packets
    else:
        return None
        
    


def start(device_info, config={'filename': ''}, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening reading:')
    files = config['files']
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
    
    
    statistics = create_data_statistic_dict()
    
    bytes_read         = 0
    packets_read       = 0
    bytes_read_total   = 0
    packets_read_total = 0
    
    tfile           = time.time() # Save the time the file was created
    tflush          = time.time() # Save the time the file was created
    f = None    
    nfile = 0
    while True:
        tcheck      = time.time()
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
                try:
                    statusqueue.put_nowait(sstr)
                except:
                    pass
                break

        packets = get_packets(f)
        if(packets is None):
            FLAG_NEW_FILE = True
        else:
            FLAG_NEW_FILE = False
            
        if(packets is not None):
            for p in packets:
                t_now = time.time()
                dt = t_now - t_sent
                dt_packet = (p['_redvypr']['t'] - t_packet_old)/speedup
                if(dt_packet < 0):
                    dt_packet = 0

                if True:
                    time.sleep(dt_packet)
                    t_sent = time.time()
                    t_packet_old = p['_redvypr']['t']
                    dataqueue.put(p)

                sstr = 'Sending packet in {:f} s.'.format(dt_packet)
                logger.debug(sstr)
                try:
                    statusqueue.put_nowait(sstr)
                except:
                    pass


            FLAG_NEW_FILE = True
            f.close()
            
        if(FLAG_NEW_FILE):
            if(nfile >= len(files)):
                if(loop == False):
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
            f = open(filename)
            nfile += 1
        
        time.sleep(0.05)


#
#
# The init widget
#
#
class initDeviceWidget(QtWidgets.QWidget):
    connect      = QtCore.pyqtSignal(redvypr_device) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
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

    def inspect_data(self, filename, rescan=False):
        """ Inspects the files for possible datastreams in the file with the filename located in config['files'][fileindex].
        """
        funcname = self.__class__.__name__ + '.inspect_data()'
        logger.debug(funcname)
        try:
            stat = self.file_statistics[filename]
            FLAG_HASSTAT = True
        except:
            FLAG_HASSTAT = False

        if (rescan or (FLAG_HASSTAT == False)):
            logger.debug(funcname + ': Scanning file {:s}'.format(filename))
            stat = create_data_statistic_dict()
            # Create tmin/tmax in statistics
            stat['t_min'] = 1e12
            stat['t_max'] = -1e12
            f = open(filename)
            packets = get_packets(f)
            f.close()
            for p in packets:
                stat = do_data_statistics(p, stat)
                tminlist = [stat['t_min'], p['_redvypr']['t']]
                tmaxlist = [stat['t_max'], p['_redvypr']['t']]
                stat['t_min'] = min(tminlist)
                stat['t_max'] = max(tmaxlist)

            self.file_statistics[filename] = stat
        else:
            logger.debug(funcname + ': No rescan of {:s}'.format(filename))

        return stat
        
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
        rows = []
        for i in self.inlist.selectionModel().selection().indexes():
            row, column = i.row(), i.column()
            rows.append(row)
    
        self.scan_files(rows)
        
    def scan_files(self,rows):
        """ Scans the selected files from the files list for possible datastreams 
        """
        funcname = self.__class__.__name__ + '.scan_files()'
        logger.debug(funcname)

        for i in rows:
            filename = self.inlist.item(i,0).text()
            stat = self.inspect_data(filename,rescan=False)
            packetitem = QtWidgets.QTableWidgetItem(str(stat['packets_sent']))
            self.inlist.setItem(i,1,packetitem)
            tdmin = datetime.datetime.fromtimestamp(stat['t_min'])
            tminstr = str(tdmin)
            tdmax = datetime.datetime.fromtimestamp(stat['t_max'])
            tmaxstr = str(tdmax)
            t_min_item = QtWidgets.QTableWidgetItem(tminstr)
            t_max_item = QtWidgets.QTableWidgetItem(tmaxstr)
            self.inlist.setItem(i,2,t_min_item)
            self.inlist.setItem(i,3,t_max_item)
            
        self.inlist.resizeColumnsToContents()
            
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
            self.device.config['files'].pop(i)
            
        self.update_filenamelist() 

    def add_files(self):
        """ Opens a dialog to choose file to add
        """
        funcname = self.__class__.__name__ + '.add_files()'
        logger.debug(funcname)
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(self,"Rawdatafiles","","redvypr raw (*.redvypr_yaml);;All Files (*)")
        for f in filenames: 
            self.device.config['files'].append(f)
            
        
        self.update_filenamelist()
        self.inlist.sortItems(0, QtCore.Qt.AscendingOrder)
            
    def update_filenamelist(self):
        """ Update the filetable 
        """
        funcname = self.__class__.__name__ + '.add_files()'
        logger.debug(funcname)
        self.inlist.clear()
        self.inlist.setHorizontalHeaderLabels(self.__filelistheader__)
        nfiles = len(self.device.config['files'])
        self.inlist.setRowCount(nfiles)

        rows = []        
        for i,f in enumerate(self.device.config['files']):
            item = QtWidgets.QTableWidgetItem(f)
            self.inlist.setItem(i,0,item)
            rows.append(i)
            
            
        self.scan_files(rows)
        self.inlist.resizeColumnsToContents()
        
    def resort_files(self):
        """ Resorts the files in config['files'] according to the sorting in the table
        """
        files_new = []
        nfiles = len(self.device.config['files'])
        for i in range(nfiles):
            filename = self.inlist.item(i,0).text()
            files_new.append(filename)
            
        self.device.config['files'] = files_new
        
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
            self.device.config['loop']    = loop
            # Speedup
            self.device.config['speedup'] = float(self.speedup_edit.text())
            self.device.thread_start()
        else:
            logger.debug(funcname + 'button released')
            self.device.thread_stop()

            
    def update_buttons(self):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """

            status = self.device.get_thread_status()
            thread_status = status['thread_status']

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
        while (statusqueue.empty() == False):
            try:
                data = statusqueue.get(block=False)
            except:
                break

            self.text.insertPlainText(str(data) + '\n')

        #self.byteslab.setText("Bytes written: {:d}".format(data['bytes_written']))
        #self.packetslab.setText("Packets written: {:d}".format(data['packets_written']))
        #self.text.insertPlainText(str(data['data']))
        
