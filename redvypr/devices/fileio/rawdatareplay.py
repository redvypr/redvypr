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
import gzip

import redvypr.config
from redvypr.device import redvypr_device
from redvypr.data_packets import do_data_statistics, create_data_statistic_dict,check_for_command

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('rawdatareplay')
logger.setLevel(logging.DEBUG)

description = "Replays a raw redvypr data file"

description = "Saves the raw redvypr packets into a file"
config_template = {}
config_template['name']              = 'rawdatareplay'
config_template['files']             = {'type':'list','description':'List of files to replay'}
config_template['replay_index']      = {'type':'list','default':['0,1,-1'],'description':'The index of the packets to be replayed'}
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


class packetreader():
    def __init__(self,filename=None, npackets = 10, chunksize=1024,statusqueue=None):
        funcname = self.__class__.__name__ + '.__init__()'
        self.filename = filename
        self.packet_index = []
        self.npackets_read = 0
        self.nread = 0 # Amount of data read
        self.statusqueue = statusqueue


        t = time.time()
        td = datetime.datetime.fromtimestamp(t)
        tdstr = td.strftime("%Y-%m-%d %H:%M:%S.%f")
        sstr = '{:s}: Opening file {:s}'.format(tdstr, filename)
        try:
            statusqueue.put_nowait(sstr)
        except:
            pass
        logger.info(sstr)
        if filename.lower().endswith('.gz'):
            FLAG_GZIP = True
        else:
            FLAG_GZIP = False

        if FLAG_GZIP:
            try:
                filestream = gzip.open(filename, 'rt')
                logger.debug(funcname + ' Opened file: {:s}'.format(filename))
            except Exception as e:
                logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
                return None
        else:
            try:
                filestream = open(filename)
                logger.debug(funcname + ' Opened file: {:s}'.format(filename))
            except Exception as e:
                logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
                return None

        self.filestream = filestream
        # Get the size of the data (within the file, this is different to the filesize, which can be gzipped
        self.fsize = os.path.getsize(filename)
        f = self.filestream
        f.seek(0, os.SEEK_END)
        size = f.tell()
        self.datasize = size
        self.filestream.seek(0)

        self.npackets = npackets
        self.chunksize = chunksize
        self.data_buffer = ''
        self.flag_eof = False

    def close_file(self):
        self.filestream.close()
    def inspect_file(self):
        """
        Inspects the whole file
        """
        funcname = self.__class__.__name__ + '.inspect_file()'
        logger.debug(funcname)
        stat = {}
        stat = create_data_statistic_dict()
        # Create tmin/tmax in statistics
        stat['t_min'] = 1e12
        stat['t_max'] = -1e12
        stat['t_all'] = []
        self.filestream.seek(0)
        npackets = 0

        while True:
            [packets,packets_ind] = self.get_packets(npackets=100, send_status=False)
            npackets += len(packets)
            pcread = self.nread / self.datasize * 100
            tdstr = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            logger.debug(funcname + ' {:s}: Read {:d} packets {:d} bytes from {:d} ({:.2f}%)'.format(tdstr,npackets,self.nread,self.datasize,pcread))

            if self.flag_eof:
                logger.debug(funcname + ' EOF reached')
                self.filestream.seek(0)
                self.flag_eof = False
                break


            for p in packets:
                stat = do_data_statistics(p, stat)
                tminlist = [stat['t_min'], p['_redvypr']['t']]
                tmaxlist = [stat['t_max'], p['_redvypr']['t']]
                stat['t_min'] = min(tminlist)
                stat['t_max'] = max(tmaxlist)
                stat['t_all'].append(p['_redvypr']['t'])

        self.file_statistics = stat
        #print('Hallo',stat)
        return stat

    def get_packets(self, npackets = 10, close_file_at_EOF=False, send_status=True):
        funcname = self.__class__.__name__ + '.get_packets()'
        packets = []
        packet_ind = []
        nread = 0
        data = ''

        if (self.filestream is not None):
            while True:
                data_read = self.filestream.read(self.chunksize)
                #print('data read', data_read)
                lendata = len(data_read)
                nread += lendata
                self.nread += lendata
                #print('len', len(data_read))
                if len(data_read) < self.chunksize:
                    self.flag_eof = True

                # Add potentially old data and the newly read data
                self.data_buffer += data_read
                data_chunk_before = ''
                data_split = self.data_buffer.split('...\n')
                data_parse = data_split[:-1]  # The last part is the res
                self.data_buffer = data_split[-1]
                for databs in data_parse:  # Split the text into single subpackets
                    try:
                        data_packet = yaml.safe_load(databs)
                        if (data_packet is not None):
                            packets.append(data_packet)
                            packet_ind.append(self.npackets_read)
                            self.packet_index.append(self.npackets_read)
                            self.npackets_read += 1
                    except Exception as e:
                        logger.debug(funcname + ': Could not decode message {:s}'.format(str(databs)))
                        return [packets,packet_ind]
                if len(packets) >= npackets:
                    return [packets, packet_ind]
                elif self.flag_eof: # EOF, cleanup
                    logger.debug(funcname + ': EOF, closing file {:s}'.format(self.filename))
                    t = time.time()
                    td = datetime.datetime.fromtimestamp(t)
                    tdstr = td.strftime("%Y-%m-%d %H:%M:%S.%f")
                    sstr = '{:s}: EOF, Closing file {:s}'.format(tdstr, self.filename)
                    try:
                        if send_status:
                            self.statusqueue.put_nowait(sstr)
                    except:
                        pass

                    if close_file_at_EOF:
                        self.close_file()

                    return [packets, packet_ind]



def start(device_info, config={'filename': ''}, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening reading:')
    files = list(config['files'])
    t_status = time.time()
    #dt_status = 2 # Status update
    dt_status = .5  # Status update
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
    packets_sent       = 0
    dt_packet_sum      = 0
    bytes_read_total   = 0
    packets_read_total = 0
    
    tfile           = time.time() # Save the time the file was created
    tflush          = time.time() # Save the time the file was created
    FLAG_NEW_FILE = True
    nfile = 0
    while True:
        tcheck      = time.time()
        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if (data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                sstr = funcname + ': Command is for me: {:s}'.format(str(command))
                logger.debug(sstr)
                try:
                    statusqueue.put_nowait(sstr)
                except:
                    pass
                break

        if (FLAG_NEW_FILE):
            if (nfile >= len(files)):
                if (loop == False):
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
            preader = packetreader(filename=filename, statusqueue=statusqueue)
            nfile += 1

        [packets,packets_ind] = preader.get_packets(close_file_at_EOF=True)
        FLAG_NEW_FILE = preader.flag_eof
        packets = [None] + packets # Add a None so that there is at least one packet
        if(packets is not None):
            for p,pind in zip(packets,packets_ind):
                # Status update
                if (time.time() - t_status) > dt_status:
                    t_status = time.time()
                    td = datetime.datetime.fromtimestamp(t_status)
                    tdstr = td.strftime("%Y-%m-%d %H:%M:%S.%f")
                    dt_avg = dt_packet_sum / packets_sent
                    sstr = '{:s}: Sent {:d} packets with an avg dt of {:.3f}s.'.format(tdstr, packets_sent, dt_avg)
                    logger.debug(sstr)
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass

                if p is None:
                    continue
                else:
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
                        packets_sent += 1
                        dt_packet_sum += dt_packet





        
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

        self.inlist.setRowCount(1)
        self.inlist.setSortingEnabled(True)
        self.col_replaypackets = 0
        self.col_npackets = 1
        self.col_tmin = 2
        self.col_tmax = 3
        self.col_fname = 4
        self.ncols = 5
        self.inlist.setColumnCount(self.ncols)
        self.__filelistheader__ = [[]] * self.ncols
        self.__filelistheader__[self.col_tmax] = 'Last date'
        self.__filelistheader__[self.col_tmin] = ' First date'
        self.__filelistheader__[self.col_npackets] = 'Packets'
        self.__filelistheader__[self.col_replaypackets] = 'Replay Packets'
        self.__filelistheader__[self.col_fname] = 'Filename'
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


        # Update the widgets depending on the configuration
        self.update_filenamelist()

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def update_filenamelist(self):
        """ Update the filetable
        """
        funcname = self.__class__.__name__ + '.update_filenamelist()'
        logger.debug(funcname)
        print('Config',self.device.config)
        self.inlist.clear()
        self.inlist.setHorizontalHeaderLabels(self.__filelistheader__)
        nfiles = len(self.device.config['files'])
        self.inlist.setRowCount(nfiles)

        rows = []
        for i, f in enumerate(self.device.config['files']):
            item = QtWidgets.QTableWidgetItem(str(f))
            self.inlist.setItem(i, self.col_fname, item)
            rows.append(i)

        self.scan_files(rows)
        self.inlist.resizeColumnsToContents()

        # Loop flag
        loop = bool(self.device.config['loop'])
        self.loop_checkbox.setChecked(loop)
        speedupstr = "{:.1f}".format(float(self.device.config['speedup']))
        self.speedup_edit.setText(speedupstr)

    def inspect_data(self, filename, rescan=False):
        """ Inspects the files for possible datastreams in the file with the filename located in config['files'][fileindex].
        """
        funcname = self.__class__.__name__ + '.inspect_data()'
        logger.debug(funcname)

        p = packetreader(filename)
        p.inspect_file()

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
            if filename.lower().endswith('.gz'):
                FLAG_GZIP = True
            else:
                FLAG_GZIP = False

            if FLAG_GZIP:
                try:
                    f = gzip.open(filename,'rt')
                    logger.debug(funcname + ' Opened file: {:s}'.format(filename))
                except Exception as e:
                    logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
                    return None
            else:
                try:
                    f = open(filename)
                    logger.debug(funcname + ' Opened file: {:s}'.format(filename))
                except Exception as e:
                    logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
                    return None

            packets = get_packets(f)
            stat['t_all'] = []
            f.close()
            for p in packets:
                stat = do_data_statistics(p, stat)
                tminlist = [stat['t_min'], p['_redvypr']['t']]
                tmaxlist = [stat['t_max'], p['_redvypr']['t']]
                stat['t_min'] = min(tminlist)
                stat['t_max'] = max(tmaxlist)
                stat['t_all'].append(p['_redvypr']['t'])

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
            filename = self.inlist.item(i,self.col_fname).text()
            stat = self.inspect_data(filename,rescan=False)
            packetitem = QtWidgets.QTableWidgetItem(str(stat['packets_sent']))
            self.inlist.setItem(i,self.col_npackets,packetitem)
            tdmin = datetime.datetime.fromtimestamp(stat['t_min'])
            tminstr = str(tdmin)
            tdmax = datetime.datetime.fromtimestamp(stat['t_max'])
            tmaxstr = str(tdmax)
            t_min_item = QtWidgets.QTableWidgetItem(tminstr)
            t_max_item = QtWidgets.QTableWidgetItem(tmaxstr)
            self.inlist.setItem(i,self.col_tmin,t_min_item)
            self.inlist.setItem(i,self.col_tmax,t_max_item)
            
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
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(self,"Rawdatafiles","","redvypr raw gzip (*.redvypr_yaml.gz);;redvypr raw (*.redvypr_yaml);;All Files (*)")
        for f in filenames: 
            self.device.config['files'].append(f)
            
        
        self.update_filenamelist()
        self.inlist.sortItems(0, QtCore.Qt.AscendingOrder)
            

        
    def resort_files(self):
        """ Resorts the files in config['files'] according to the sorting in the table
        """
        files_new = []
        nfiles = len(self.device.config['files'])
        for i in range(nfiles):
            filename = self.inlist.item(i,0).text()
            files_new.append(filename)
            
        self.device.config['files'] = redvypr.config.configList(files_new)
        
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
            self.device.config['loop'].data    = loop
            # Speedup
            self.device.config['speedup'].data = float(self.speedup_edit.text())
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
        hlayout         = QtWidgets.QFormLayout()
        self.device     = device
        self.text       = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.scrollchk  = QtWidgets.QCheckBox('Scroll to end')
        self.scrollchk.setChecked(True)
        self.statuslab= QtWidgets.QLabel("Status")
        self.text.setMaximumBlockCount(10000)
        hlayout.addRow(self.statuslab)
        layout.addLayout(hlayout)
        layout.addWidget(self.text)
        layout.addWidget(self.scrollchk)
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

            pos = self.text.verticalScrollBar().value() # Original position of scrollbar
            self.text.moveCursor(QtGui.QTextCursor.End)
            self.text.insertPlainText(str(data) + '\n')

            if(self.scrollchk.isChecked()):
                self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
            else:
                self.text.verticalScrollBar().setValue(pos)


