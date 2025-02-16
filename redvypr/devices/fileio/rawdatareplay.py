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

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.rawdatareplay')
logger.setLevel(logging.DEBUG)

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = "Replays a raw redvypr data file"
    gui_tablabel_display: str = 'Replay status'
    gui_icon: str = 'mdi.code-json'

class DeviceCustomConfig(pydantic.BaseModel):
    files: list = pydantic.Field(default=[], description='List of files to replay')
    replay_index: list = pydantic.Field(default=['0,-1,1'], description='The index of the packets to be replayed [start, end, nth]')
    loop: bool = pydantic.Field(default=False, description='Loop over all files if set')
    speedup: float = pydantic.Field(default=1.0, description='Speedup factor of the data')
    replace_time: bool = pydantic.Field(default=False, description='Replaces the original time in the packet with the time the packet was read')


redvypr_devicemodule = True

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


def index_file(filestream, chunksize, statusqueue=None):
    funcname = __name__ + '.index_file()'
    npackets_read = 0
    packets = []
    status_thread = {}
    tstatus = time.time()
    stat = {}
    stat['packets_seek'] = []
    stat['packets_size'] = []
    stat['packets_num'] = []
    stat['packets_t'] = []
    stat['npackets'] = 0
    packets_ = []
    seek_start = 0
    seek_now = 0
    nread = 0
    data = ''
    data_buffer = b''
    flag_eof = False
    filestream.seek(0)
    if (filestream is not None):
        while True:
            seek_start = filestream.tell()
            data_read = filestream.read(chunksize)
            seek_now = filestream.tell()
            #print('data read', seek_start,seek_now, seek_now - seek_start,len(data_read))
            lendata = len(data_read)
            nread += lendata
            # print('len', len(data_read))
            if len(data_read) < chunksize:
                flag_eof = True

            # Add potentially old data and the newly read data
            data_buffer += data_read
            seek_data_buffer_end = seek_now
            seek_data_buffer_start = seek_data_buffer_end - len(data_buffer)
            while True:
                # Look for the start of a packet
                try:
                    index_start = data_buffer.index(b'---')
                except Exception as e:
                    index_start = None

                # Look for the end of a packet
                try:
                    pattern_end = b'\0'
                    index_end = data_buffer.index(pattern_end)
                    #index_end += len(pattern_end)
                except Exception as e:
                    index_end = None

                #print('data',data_buffer)
                #print('index start',index_start,index_end)

                if (index_end is not None) and (index_start is not None) and ((index_end - index_start) > 0):
                    datab = data_buffer[index_start:index_end]
                    databs = datab.decode('utf-8')
                    #print('databs',databs,index_start,index_end)
                else:
                    break
                try:
                    data_packet = yaml.safe_load(databs)
                    if (data_packet is not None):
                        numpacket = data_packet['_redvypr']['numpacket']
                        tpacket = data_packet['_redvypr']['t']
                        #print('Found datapacket',seek_data_buffer_start)
                        loc_packet_start = seek_data_buffer_start + index_start
                        loc_packet_length = index_end - index_start
                        packets.append(data_packet)
                        stat['packets_seek'].append(loc_packet_start)
                        stat['packets_size'].append(loc_packet_length)
                        stat['packets_num'].append(numpacket)
                        stat['packets_t'].append(tpacket)

                        npackets_read += 1
                        #print('fdsfd',npackets_read)
                        stat['npackets'] = npackets_read

                        if True:
                            dt = time.time() - tstatus
                            if dt > 0.5:
                                tstatus = time.time()
                                tmin = stat['packets_t'][0]
                                tmax = stat['packets_t'][-1]
                                status_thread['t'] = time.time()
                                status_thread['t_min'] = tmin
                                status_thread['t_max'] = tmax
                                status_thread['seek'] = seek_now
                                status_thread['packets_num'] = npackets_read
                                status_thread['flag_eof'] = flag_eof
                                status_thread['stat'] = None
                                logger.debug(funcname + ' Status:' + str(status_thread))
                                if statusqueue is not None:
                                    statusqueue.put(status_thread)
                        # Remove the packet from the dta_buffer
                        data_buffer = data_buffer[index_end+len(pattern_end):]
                        seek_data_buffer_start = seek_data_buffer_end - len(data_buffer)
                except Exception as e:
                    logger.debug(funcname + ': Could not decode message {:s}'.format(str(databs)))
                    logger.exception(e)
                    #return [packets, packet_ind]

                #break


            if flag_eof:  # EOF, cleanup
                logger.debug(funcname + ': EOF. Rewinding file')
                filestream.seek(0)
                t = time.time()
                td = datetime.datetime.fromtimestamp(t)
                tdstr = td.strftime("%Y-%m-%d %H:%M:%S.%f")
                break

        # In thread mode, add stat to status dictionary
        if statusqueue is not None:
            status_thread['t'] = time.time()
            status_thread['seek'] = seek_now
            status_thread['packets_num'] = npackets_read
            status_thread['flag_eof'] = flag_eof
            status_thread['stat'] = stat
            statusqueue.put(status_thread)

        return stat


class packetreader():
    def __init__(self, filename=None, replay_index = '0,-1,1', npackets = 10, chunksize=1024,statusqueue=None,filestat = None):
        funcname = self.__class__.__name__ + '.__init__()'
        self.filename = filename
        #
        self.ipacket = -1
        self.packet_index = []
        self.npackets_read = 0
        self.nread = 0 # Amount of data read
        self.statusqueue = statusqueue
        #
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
                filestream = gzip.open(filename, 'rb')
                logger.debug(funcname + ' Opened file: {:s}'.format(filename))
            except Exception as e:
                logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
                return None
        else:
            try:
                filestream = open(filename,'rb')
                logger.debug(funcname + ' Opened file: {:s}'.format(filename))
            except Exception as e:
                logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
                return None

        self.filestream = filestream
        # Get the size of the data (within the file, this is different to the filesize, which can be gzipped
        self.fsize = os.path.getsize(filename)
        f = self.filestream
        f.seek(0, os.SEEK_END)
        size = f.tell() # The size of the internal data
        self.datasize = size
        self.filestream.seek(0)
        self.chunksize = chunksize

        # Calculate hash
        #hasher = hashlib.sha256()
        hasher = hashlib.md5()
        while True:
            data = f.read(65536)
            if not data:
                break
            hasher.update(data)
        self.checksum = hasher.hexdigest()
        self.filestream.seek(0)
        #print("MD5 checksum of {}".format(self.checksum))

        if filestat is None:
            # Check for an index file
            filename_index = filename + '.index{}.yaml.gz'.format(self.checksum)
            try:
                logger.debug(funcname + ' loading index file')
                filestream_index = gzip.open(filename_index, 'rb')
                filestat_raw = filestream_index.read()
                filestat = yaml.safe_load(filestat_raw)
                filestat['checksum'] = self.checksum
                logger.debug(funcname + ' loading index file done')
            except:
                logger.debug(funcname, exc_info=True)
                logger.info("Did not find index file, creating one")
                filestat = self.index_file()
                findex = gzip.open(filename_index, 'wb')
                yamlstr = yaml.dump(filestat)
                findex.write(yamlstr.encode('utf-8'))
                findex.close()

            # Inspect file, if not done already
            logger.debug(funcname + ' Indexing file {:s}'.format(filename))
            self.filestat = filestat
        elif filestat == 'thread':
            logger.debug(funcname + ' Starting thread based file statistic')
            self.index_file_thread()
        else:
            self.filestat = filestat

    def index_to_packetindex(self, indexstr):
        """

        """
        rs = indexstr.split(',')
        istart = int(rs[0])
        iend = int(rs[1])
        istep = int(rs[2])
        npackets = self.filestat['npackets']
        if iend < 0:
            iend_abs = npackets + iend + 1
        else:
            iend_abs = iend

        if istart < 0:
            istart_abs = npackets + istart
        else:
            istart_abs = istart


        packetindex = []
        for i in range(istart_abs,iend_abs,istep):
            packetindex.append(i)

        #print('Packetindex',packetindex)
        return packetindex

    def get_packets(self, indexstr):
        packetindex = self.index_to_packetindex(indexstr)
        packets = self.get_packets_by_index(packetindex)
        return packets

    def get_packets_by_index(self, packetindex):
        """
        Get the packets
        """
        packets = []
        for pindex in packetindex:
            iseek = self.filestat['packets_seek'][pindex]
            plen  = self.filestat['packets_size'][pindex]
            self.filestream.seek(iseek)
            packetdata_raw = self.filestream.read(plen)
            packetdata = yaml.safe_load(packetdata_raw)
            packets.append(packetdata)
            #print('Packet',pindex)
            #print('Packetdata',packetdata)

        return packets


    def close_file(self):
        self.filestream.close()

    def index_file(self):
        stat = index_file(self.filestream,self.chunksize)
        return stat

    def index_file_thread(self):
        self.stat_thread = {}
        self.statusqueue = queue.Queue()
        self.index_thread = threading.Thread(target = index_file, args = (self.filestream,self.chunksize,self.statusqueue), daemon = True)
        self.index_thread.start()




def packet_read_thread(filename, chunksize, npacket_buf=10, dataqueue=None, commandqueue=None, statusqueue=None):
    funcname = __name__ + '.packet_read_thread()'

    if filename.lower().endswith('.gz'):
        FLAG_GZIP = True
    else:
        FLAG_GZIP = False

    if FLAG_GZIP:
        try:
            filestream = gzip.open(filename, 'rb')
            logger.debug(funcname + ' Opened file: {:s}'.format(filename))
        except Exception as e:
            logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
            return None
    else:
        try:
            filestream = open(filename, 'rb')
            logger.debug(funcname + ' Opened file: {:s}'.format(filename))
        except Exception as e:
            logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
            return None

    # Get the size of the data (within the file, this is different to the filesize, which can be gzipped
    fsize = os.path.getsize(filename)
    f = filestream
    f.seek(0, os.SEEK_END)
    size = f.tell()
    datasize = size
    filestream.seek(0)

    filename_base = os.path.basename(filename)
    filename_path = os.path.dirname(filename)

    npackets_read = 0
    packets = []
    status_thread = {}
    tstatus = time.time()
    stat = {}
    stat['packets_seek'] = []
    stat['packets_size'] = []
    stat['packets_num'] = []
    stat['packets_t'] = []
    stat['npackets'] = 0
    packets_ = []
    seek_start = 0
    seek_now = 0
    nread = 0
    data = ''
    data_buffer = b''
    flag_eof = False
    filestream.seek(0)
    nread = 0
    nnewread = 0
    if (filestream is not None):
        while True:
            com = commandqueue.get()
            if type(com) == int: # Read n new packets
                nnewread = com
                nread = 0
            elif com == 'stop':  # Read n new packets
                logger.debug(funcname + ' Stopping ...')
                return
            while nread < nnewread:
                #print('Nread:',nread)
                seek_start = filestream.tell()
                data_read = filestream.read(chunksize)
                seek_now = filestream.tell()
                #print('data read', seek_start,seek_now, seek_now - seek_start,len(data_read))
                lendata = len(data_read)
                # print('len', len(data_read))
                if len(data_read) < chunksize:
                    flag_eof = True

                # Add potentially old data and the newly read data
                data_buffer += data_read
                seek_data_buffer_end = seek_now
                seek_data_buffer_start = seek_data_buffer_end - len(data_buffer)
                while True:
                    # Look for the start of a packet
                    try:
                        index_start = data_buffer.index(b'---')
                    except Exception as e:
                        index_start = None

                    # Look for the end of a packet
                    try:
                        pattern_end = b'\0'
                        index_end = data_buffer.index(pattern_end)
                        #index_end += len(pattern_end)
                    except Exception as e:
                        index_end = None

                    #print('data',data_buffer)
                    #print('index start',index_start,index_end)

                    if (index_end is not None) and (index_start is not None) and ((index_end - index_start) > 0):
                        datab = data_buffer[index_start:index_end]
                        databs = datab.decode('utf-8')
                        #print('databs',databs,index_start,index_end)
                    else:
                        break
                    try:
                        data_packet = yaml.safe_load(databs)
                        if (data_packet is not None):
                            numpacket = data_packet['_redvypr']['numpacket']
                            tpacket = data_packet['_redvypr']['t']
                            #print('Found datapacket',seek_data_buffer_start)
                            loc_packet_start = seek_data_buffer_start + index_start
                            loc_packet_length = index_end - index_start
                            #packets.append(data_packet)
                            dataqueue.put(data_packet)
                            nread += 1
                            #stat['packets_seek'].append(loc_packet_start)
                            #stat['packets_size'].append(loc_packet_length)
                            #stat['packets_num'].append(numpacket)
                            #stat['packets_t'].append(tpacket)

                            npackets_read += 1
                            #print('fdsfd',npackets_read)
                            #stat['npackets'] = npackets_read

                            if True:
                                dt = time.time() - tstatus
                                if dt > 0.5:
                                    tstatus = time.time()
                                    #logger.debug(funcname + ' Status:' + str(status_thread))
                            # Remove the packet from the dta_buffer
                            data_buffer = data_buffer[index_end+len(pattern_end):]
                            seek_data_buffer_start = seek_data_buffer_end - len(data_buffer)
                    except Exception as e:
                        logger.debug(funcname + ': Could not decode message:"{:s}"'.format(str(databs)))

                        logger.exception(e)
                        #return [packets, packet_ind]

                    #break


                if flag_eof:  # EOF, cleanup
                    logger.debug(funcname + ': EOF. Rewinding file')
                    filestream.seek(0)
                    t = time.time()
                    td = datetime.datetime.fromtimestamp(t)
                    tdstr = td.strftime("%Y-%m-%d %H:%M:%S.%f")
                    return

            # In thread mode, add stat to status dictionary
            if statusqueue is not None:
                ['time', 'filename', 'seek', 'fsize', 'pc', 'packets_num']
                status_thread['t'] = time.time()
                td = datetime.datetime.fromtimestamp(status_thread['t'])
                status_thread['time'] = td.strftime('%d %b %Y %H:%M:%S')
                status_thread['filename'] = filename_base
                status_thread['filepath'] = filename_path
                status_thread['seek'] = seek_now
                status_thread['datasize'] = size
                status_thread['filesize'] = fsize
                try:
                    pc = seek_now / size * 100
                except:
                    pc = 'NaN'
                status_thread['pc'] = "{:.2f}".format(pc)
                status_thread['packets_num'] = npackets_read
                status_thread['flag_eof'] = flag_eof
                #status_thread['stat'] = stat
                statusqueue.put(status_thread)






def start(device_info, config={'filename': ''}, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening reading:')

    files = list(config['files'])
    replay_index = list(config['replay_index'])
    t_status = time.time()
    #dt_status = 2 # Status update
    dt_status = .5  # Status update
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
    
    
    #statistics = create_data_statistic_dict()
    
    bytes_read         = 0
    packets_published  = 0
    dt_packet_sum      = 0
    bytes_read_total   = 0
    packets_read_total = 0
    
    tfile           = time.time() # Save the time the file was created
    tflush          = time.time() # Save the time the file was created
    FLAG_NEW_FILE = True
    nfile = 0
    packets = []
    read_dataqueue = queue.Queue()
    read_commandqueue = queue.Queue()
    while True:
        tcheck = time.time()
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
                if command == 'stop':
                    logger.debug('Stopping')
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass

                    try:
                        read_commandqueue.put('stop')
                        logger.debug('stopping read thread')
                    except:
                        logger.debug('stopping read thread failed:',exc_info=True)
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
            chunksize = 5000
            npacket_buf = 10
            nfile += 1
            print('Starting reading thread')
            args = (filename, chunksize, npacket_buf, read_dataqueue, read_commandqueue, statusqueue)
            read_thread = threading.Thread(target=packet_read_thread, args=args, daemon=True)
            read_thread.start()
            read_commandqueue.put(npacket_buf)
            for i in range(npacket_buf):
                packets.append(read_dataqueue.get())

            pnow = packets.pop(0)
            pnext = packets.pop(0)
            FLAG_NEW_FILE = False

        # Check if the read thread is still alive
        if not(read_thread.is_alive()):
            logger.debug(funcname + ' Reading thread finished')
            FLAG_NEW_FILE = True
        else:
            if len(packets) > 1:
                while True:
                    try:
                        packets.append(read_dataqueue.get_nowait())
                    except:
                        break
                if True:
                    t_pnow = pnow['_redvypr']['t']
                    t_pnext = pnext['_redvypr']['t']
                    dt = t_pnext - t_pnow
                    t_now = time.time()
                    if config['replace_time']:
                        pnow['t'] = t_now
                        pnow['_redvypr']['t'] = t_now

                    #print('sending',pnow)
                    dataqueue.put(pnow)
                    pnow = pnext
                    pnext = packets.pop(0)
                    packets_published += 1
                    dt_packet = dt / speedup
                    dt_packet_sum += dt_packet


                    if (dt_packet < 0):
                        dt_packet = 0
                    if (dt_packet > 10):
                        logger.warning(funcname + ' Long dt_packet of {:f} seconds'.format(dt_packet))


                    if len(packets) < npacket_buf:
                        dn = npacket_buf - len(packets)
                        #print('Asking for new packets',dn)
                        read_commandqueue.put(dn)

                    #print('sleeping dt_packet',dt_packet)
                    time.sleep(dt_packet)
                    t_sent = time.time()


        # Status update
        if (time.time() - t_status) > dt_status:
            #print('status')
            t_status = time.time()
            td = datetime.datetime.fromtimestamp(t_status)
            tdstr = td.strftime("%Y-%m-%d %H:%M:%S.%f")
            try:
                dt_avg = dt_packet_sum / packets_published
            except:
                dt_avg = -1
            sstr = '{:s}: Sent {:d} packets with an avg dt of {:.3f}s.'.format(tdstr, packets_published,
                                                                               dt_avg)
            logger.debug(sstr)
            try:
                statusqueue.put_nowait(sstr)
            except:
                pass



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
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(self,"Rawdatafiles","","redvypr raw gzip (*.redvypr_yaml.gz);;redvypr raw (*.redvypr_yaml);;All Files (*)")
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
        self.__statusheader__ = ['Time','Filename','Filesize','Bytes read','Bytes total','%','Packets read']
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
                statuskeys = ['time', 'filename', 'filesize', 'seek', 'datasize', 'pc', 'packets_num']
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