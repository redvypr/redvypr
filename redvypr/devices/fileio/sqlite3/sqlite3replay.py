import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import yaml
import copy
import os
import gzip
import threading
import hashlib
import re
import pydantic
import typing
from redvypr.device import RedvyprDevice
from redvypr.data_packets import check_for_command
#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict
from redvypr.devices.fileio.sqlite3.sqlite3db import RedvyprDbSqlite3

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.sqlite3replay')
logger.setLevel(logging.DEBUG)

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = "Replays a sqlite3 redvypr data file"
    gui_tablabel_display: str = 'Replay status'
    gui_icon: str = 'mdi.code-json'

class DeviceCustomConfig(pydantic.BaseModel):
    files: list = pydantic.Field(default=[], description='List of files to replay')
    replay_index: list = pydantic.Field(default=['0,-1,1'], description='The index of the packets to be replayed [start, end, nth]')
    loop: bool = pydantic.Field(default=False, description='Loop over all files if set')
    speedup: float = pydantic.Field(default=1.0, description='Speedup factor of the data')
    replace_time: bool = pydantic.Field(default=False, description='Replaces the original time in the packet with the time the packet was read')


redvypr_devicemodule = True



def start(device_info, config={'filename': ''}, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    logger_start = logging.getLogger('redvypr.device.sqlite3replay.thread')
    logger_start.debug(funcname + ':Opening reading:')

    files = list(config['files'])
    replay_index = list(config['replay_index'])
    t_status = time.time()
    #dt_status = 2 # Status update
    dt_status = 1.0  # Status update
    t_sent = 0 # The time the last packets was sent
    t_packet_old = 1e12 # The time the last packet had (internally)
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
    
    packets_published_total = 0
    packets_published_file = 0
    ipacket = 0
    npackets = -1
    dt_packet_sum = 0
    FLAG_NEW_FILE = True
    nfile = 0
    dt_packet_wait = 1000
    dt_sleep = 0.2
    while True:
        tcheck = time.time()
        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if (data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            logger_start.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                sstr = funcname + ': Command is for me: {:s}'.format(str(command))
                logger_start.debug(sstr)
                if command == 'stop':
                    logger.debug('Stopping')
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
            #print('Opening file')
            db = RedvyprDbSqlite3(filename)
            stat = db.get_stats()
            npackets = stat['count']
            ipacket = 0
            if npackets > 2:
                packets_published_file = 0
                logger_start.debug('Starting reading data of file with {} packets'.format(npackets))
                nfile += 1
                pnow_all = db.get_packet_by_index(ipacket)
                pnow = pnow_all['data']
                ipacket += 1
                pnext_all = db.get_packet_by_index(ipacket)
                pnext = pnext_all['data']
                FLAG_NEW_FILE = False
                dt_packet_wait = 0
            else:
                FLAG_NEW_FILE = True
                db.close()

        if ipacket <= npackets:
            if dt_packet_wait<=0:
                t_pnow = pnow['_redvypr']['t']
                t_pnext = pnext['_redvypr']['t']
                dt = t_pnext - t_pnow
                t_now = time.time()
                if config['replace_time']:
                    pnow['t'] = t_now
                    pnow['_redvypr']['t'] = t_now

                #print('sending',pnow)
                dataqueue.put(pnow)
                packets_published_file += 1
                packets_published_total += 1
                #print("ipacket",ipacket,npackets,filename)
                if ipacket == npackets:
                    FLAG_NEW_FILE = True
                    dt_sleep = 0.2
                    #print("Last packet published")
                    db.close()
                else:
                    pnow = pnext
                    pnext_all = db.get_packet_by_index(ipacket)
                    pnext = pnext_all['data']
                    ipacket += 1
                    dt_packet = dt / speedup
                    dt_packet_sum += dt_packet
                    #print("dt_packet",dt_packet,speedup)
                    if (dt_packet < 0):
                        dt_packet = 0
                        dt_sleep = 0.0
                    elif (dt_packet <= 0.2):
                        dt_sleep = dt_packet
                    else:
                        dt_sleep = 0.2
                        logger_start.debug(funcname + ' Long dt_packet of {:f} seconds'.format(dt_packet))

                    dt_packet_wait = dt_packet

        time.sleep(dt_sleep)
        dt_packet_wait -= dt_sleep
        # Status update
        if (time.time() - t_status) > dt_status:
            #print('status')
            t_status = time.time()
            td = datetime.datetime.fromtimestamp(t_status)
            tdstr = td.strftime("%Y-%m-%d %H:%M:%S.%f")
            try:
                dt_avg = dt_packet_sum / packets_published_total
            except:
                dt_avg = -1
            sstr = '{:s}: Sent {:d} packets with an avg dt of {:.3f}s.'.format(tdstr, packets_published_total,
                                                                               dt_avg)
            logger_start.debug(sstr)
            try:
                statusqueue.put_nowait(sstr)
            except:
                pass

            status_thread = {}
            status_thread['t'] = time.time()
            td = datetime.datetime.fromtimestamp(status_thread['t'])
            status_thread['time'] = td.strftime('%d %b %Y %H:%M:%S')
            status_thread['filename'] = filename
            #status_thread['filepath'] = filename_path
            status_thread['filesize'] = 1000
            try:
                pc = ipacket / npackets * 100
            except:
                pc = np.nan
            status_thread['pc'] = "{:.2f}".format(pc)
            status_thread['packets_read'] = ipacket
            status_thread['packets_num'] = npackets
            statusqueue.put(status_thread)


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

        self.inlist.setRowCount(1)
        #self.inlist.setSortingEnabled(True)
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
        loopflag = bool(self.device.custom_config.loop)
        self.loop_checkbox.setChecked(loopflag)
        self.loop_checkbox.stateChanged.connect(self.speedup_changed)
        self.replace_time_checkbox = QtWidgets.QCheckBox('Replace time')
        replace_time_flag = bool(self.device.custom_config.replace_time)
        self.replace_time_checkbox.setChecked(replace_time_flag)
        self.replace_time_checkbox.stateChanged.connect(self.speedup_changed)
        # Speedup
        self.speedup_edit  = QtWidgets.QLineEdit(self)
        onlyDouble = QtGui.QDoubleValidator()
        self.speedup_edit.setValidator(onlyDouble)
        self.speedup_edit.setToolTip('Speedup of the packet replay.')
        self.speedup_label = QtWidgets.QLabel("Speedup factor")
        speedup = float(self.device.custom_config.speedup)
        self.speedup_edit.setText("{:.1f}".format(speedup))
        self.speedup_edit.textChanged.connect(self.speedup_changed)
        
        
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
        layout.addWidget(self.replace_time_checkbox, 6, 1)
        layout.addWidget(self.speedup_label,6,2,1,1,QtCore.Qt.AlignRight)
        layout.addWidget(self.speedup_edit,6,3,1,1,QtCore.Qt.AlignRight)
        layout.addWidget(self.startbtn,7,0,2,-1)


        # Update the widgets depending on the configuration
        self.update_filenamelist()
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def speedup_changed(self):
        funcname = self.__class__.__name__ + '.speedup_changed()'
        logger.debug(funcname)
        # Speedup
        self.device.custom_config.speedup = float(self.speedup_edit.text())
        loopflag = self.loop_checkbox.isChecked()
        replace_time_flag = self.replace_time_checkbox.isChecked()
        self.device.custom_config.loop = loopflag
        self.device.custom_config.replace_time = replace_time_flag

    def table_changed(self,row,col):
        funcname = self.__class__.__name__ + '.table_changed()'
        logger.debug(funcname)
        #print('Row',row,'Col',col)
        item = self.inlist.item(row,col)

        if col == self.col_replaypackets: # If the replay index was changed
            rindex = item.text()
            try:
                rs = rindex.split(',')
                istart = int(rs[0])
                iend = int(rs[1])
                istep = int(rs[2])
                self.device.custom_config.replay_index[item.replay_index] = rindex
                item.replay_index_str = rindex
            except Exception as e:
                logger.exception(e)
                replay_index_str = item.replay_index_str
                itemold = QtWidgets.QTableWidgetItem(str(replay_index_str))
                itemold.replay_index_str = replay_index_str
                try:
                    self.inlist.cellChanged.disconnect(self.table_changed)
                except:
                    pass
                self.inlist.setItem(row, col, itemold)
                self.inlist.cellChanged.connect(self.table_changed)


    def update_filenamelist(self):
        """ Update the filetable
        """
        try:
            funcname = self.__class__.__name__ + '.update_filenamelist()'
            logger.debug(funcname)
            try:
                self.inlist.cellChanged.disconnect(self.table_changed)
            except:
                pass
            self.inlist.clear()
            self.inlist.setHorizontalHeaderLabels(self.__filelistheader__)
            nfiles = len(self.device.custom_config.files)
            self.inlist.setRowCount(nfiles)
            rows = []
            for i, f in enumerate(self.device.custom_config.files):
                if len(self.device.custom_config.replay_index) < (i + 1):
                    self.device.custom_config.replay_index.append(self.device.custom_config.replay_index[-1])
                    replayindex = self.device.custom_config.replay_index[-1]
                else:
                    replayindex = self.device.custom_config.replay_index[i]

                db = RedvyprDbSqlite3(f)
                stats = db.get_stats()
                #print("Statistics", db.get_stats())
                db.close()

                # min timestamp
                item = QtWidgets.QTableWidgetItem(str(stats['min_timestamp']))
                item.replay_index = i
                item.replay_index_str = replayindex
                self.inlist.setItem(i, self.col_tmin, item)
                # max timestamp
                item = QtWidgets.QTableWidgetItem(str(stats['max_timestamp']))
                item.replay_index = i
                item.replay_index_str = replayindex
                self.inlist.setItem(i, self.col_tmax, item)
                # numpackets
                item = QtWidgets.QTableWidgetItem(str(stats['count']))
                item.replay_index = i
                item.replay_index_str = replayindex
                self.inlist.setItem(i, self.col_npackets, item)
                # replayindex
                item = QtWidgets.QTableWidgetItem(str(replayindex))
                item.replay_index = i
                item.replay_index_str = replayindex
                self.inlist.setItem(i, self.col_replaypackets, item)
                # Filename
                item = QtWidgets.QTableWidgetItem(str(f))
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.inlist.setItem(i, self.col_fname, item)
                rows.append(i)

            self.inlist.resizeColumnsToContents()
            #for i, f in enumerate(self.device.config.files):
            #    self.scan_file(str(f), i)

            self.inlist.resizeColumnsToContents()

            # Loop flag
            loop = bool(self.device.custom_config.loop)
            self.loop_checkbox.setChecked(loop)
            speedupstr = "{:.1f}".format(float(self.device.custom_config.speedup))
            self.speedup_edit.setText(speedupstr)
            ## Add the packetnumber etc etc
            #self.scan_files(rows)
            self.inlist.cellChanged.connect(self.table_changed)
        except Exception as e:
            logger.exception(e)








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

    def scan_file(self, filename, row):
        """ Scans the selected files from the files list for possible datastreams
        """
        funcname = self.__class__.__name__ + '.scan_files()'
        logger.debug(funcname)

        stat = self.inspect_data(filename,rescan=False)
        if True:
            npackets = len(stat['packets_num'])
            t_min = stat['packets_t'][0]
            t_max = stat['packets_t'][-1]
            packetitem = QtWidgets.QTableWidgetItem(str(npackets))
            packetitem.setFlags(packetitem.flags() & ~QtCore.Qt.ItemIsEditable)
            self.inlist.setItem(row, self.col_npackets, packetitem)
            tdmin = datetime.datetime.fromtimestamp(t_min)
            tminstr = str(tdmin)
            tdmax = datetime.datetime.fromtimestamp(t_max)
            tmaxstr = str(tdmax)
            t_min_item = QtWidgets.QTableWidgetItem(tminstr)
            t_min_item.setFlags(t_min_item.flags() & ~QtCore.Qt.ItemIsEditable)
            t_max_item = QtWidgets.QTableWidgetItem(tmaxstr)
            t_max_item.setFlags(t_max_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.inlist.setItem(row, self.col_tmin, t_min_item)
            self.inlist.setItem(row, self.col_tmax, t_max_item)

        self.inlist.resizeColumnsToContents()

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
            p = packetreader(filename)
            # stat = p.ipacketreadernspect_file()
            self.file_statistics[filename] = p.filestat
        else:
            logger.debug(funcname + ': No rescan of {:s}'.format(filename))

        return self.file_statistics[filename]
        
    def scan_files(self,rows):
        """ Scans the selected files from the files list for possible datastreams 
        """
        funcname = self.__class__.__name__ + '.scan_files()'
        logger.debug(funcname)

        for i in rows:
            filename = self.inlist.item(i,self.col_fname).text()
            #stat = self.inspect_data_thread(filename, i, rescan=False)

        # Start a timer to update
        #if len(rows) > 0:
        #    self.threadtimer = QtCore.QTimer()
        #    self.threadtimer.timeout.connect(self.update_table_from_thread)  # Add to the timer another update
        #    self.threadtimer.start(250)
            
        self.inlist.resizeColumnsToContents()

    def inspect_data_thread(self, filename, row, rescan=False):
        """ Inspects the files for possible datastreams in the file with the filename located in config['files'][fileindex].
        """
        funcname = self.__class__.__name__ + '.inspect_data()'
        logger.debug(funcname)
        self.inspect_threads = []

        try:
            stat = self.file_statistics[filename]
            FLAG_HASSTAT = True
        except:
            FLAG_HASSTAT = False

        if (rescan or (FLAG_HASSTAT == False)):
            logger.debug(funcname + ': Scanning file {:s}'.format(filename))
            p = packetreader(filename, filestat='thread')
            p.row = row
            self.inspect_threads.append(p)
            # stat = p.inspect_file()
            # self.file_statistics[filename] = p.filestat
        else:
            logger.debug(funcname + ': No rescan of {:s}'.format(filename))

    def update_table_from_thread(self):
        funcname = self.__class__.__name__ + '.update_table_from_thread()'
        logger.debug(funcname)
        flag_continue = False
        for p in self.inspect_threads:
            try:
                status = p.statusqueue.get_nowait()
                print(funcname + ' Got status')
                # print('Hallo status',status)
                row = p.row
            except Exception as e:
                status = None
                pass
            if p.index_thread.is_alive() == True:
                flag_continue = True

            if status is not None:
                packetitem = QtWidgets.QTableWidgetItem(str(status['packets_num']))
                packetitem.setFlags(packetitem.flags() & ~QtCore.Qt.ItemIsEditable)
                self.inlist.setItem(row, self.col_npackets, packetitem)
                tdmin = datetime.datetime.fromtimestamp(status['t_min'])
                tminstr = str(tdmin)
                tdmax = datetime.datetime.fromtimestamp(status['t_max'])
                tmaxstr = str(tdmax)
                t_min_item = QtWidgets.QTableWidgetItem(tminstr)
                t_min_item.setFlags(t_min_item.flags() & ~QtCore.Qt.ItemIsEditable)
                t_max_item = QtWidgets.QTableWidgetItem(tmaxstr)
                t_max_item.setFlags(t_max_item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.inlist.setItem(row, self.col_tmin, t_min_item)
                self.inlist.setItem(row, self.col_tmax, t_max_item)
                self.inlist.resizeColumnsToContents()

        if flag_continue == False:
            logger.debug('No thread running anymore')
            self.threadtimer.stop()
            
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
        regex_indexfile = re.compile('.*[.index][0-9a-f]{32}.yaml.gz')
        logger.debug(funcname)
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(self,"Rawdatafiles","","redvypr sqlite3 (*.rdvsql3);;All Files (*)")
        for f in filenames:
            if regex_indexfile.match(f) is None:
                self.device.custom_config.files.append(f)
            else:
                logger.info('Found index file {}, will not use it'.format(f))
            
        self.update_filenamelist()
        self.inlist.sortItems(self.col_fname, QtCore.Qt.AscendingOrder)
            

        
    def resort_files(self):
        """ Resorts the files in config['files'] according to the sorting in the table
        """
        files_new = []
        nfiles = len(self.device.custom_config.files)
        for i in range(nfiles):
            filename = self.inlist.item(i,self.col_fname).text()
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
            # Update the config for replay
            # update loop, replace_time and speedup
            self.speedup_changed()
            # Replay index
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
        hlayout         = QtWidgets.QFormLayout()
        self.device     = device
        self.text       = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.scrollchk  = QtWidgets.QCheckBox('Scroll to end')
        self.scrollchk.setChecked(True)
        self.statuslab= QtWidgets.QLabel("Status")
        self.text.setMaximumBlockCount(10000)
        # Add a table
        self.statustable = QtWidgets.QTableWidget()
        self.__statusheader__ = ['Time','Filename','%','Packets read', 'Packets total']
        self.statustable.setColumnCount(len(self.__statusheader__))
        self.statustable.setHorizontalHeaderLabels(self.__statusheader__)
        self.statustable.setRowCount(1)
        self.statustable.verticalHeader().setVisible(False)
        self.statustable.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        hlayout.addRow(self.statuslab)
        layout.addWidget(self.statustable, 1)
        layout.addLayout(hlayout)
        layout.addWidget(self.text, 5)
        layout.addWidget(self.scrollchk, 1)
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

            if type(data) == dict:
                #print('data',data)
                statuskeys = ['time', 'filename', 'pc', 'packets_read', 'packets_num']
                for i,k in enumerate(statuskeys):
                    datastr = str(data[k])
                    dataitem = QtWidgets.QTableWidgetItem(datastr)
                    self.statustable.setItem(0, i, dataitem)
                    self.statustable.resizeColumnsToContents()
            else:
                #Original position of scrollbar
                pos = self.text.verticalScrollBar().value()
                self.text.moveCursor(QtGui.QTextCursor.End)
                self.text.insertPlainText(str(data) + '\n')
                if(self.scrollchk.isChecked()):
                    self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
                else:
                    self.text.verticalScrollBar().setValue(pos)