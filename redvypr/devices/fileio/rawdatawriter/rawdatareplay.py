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
import re
import pydantic
import typing
from redvypr.device import RedvyprDevice
from redvypr.redvypr_datadict import check_for_command

# from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.rawdatareplay')
logger.setLevel(logging.DEBUG)


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = "Replays a raw redvypr data file"
    gui_tablabel_display: str = 'Replay status'
    gui_icon: str = 'mdi.code-json'


class DeviceCustomConfig(pydantic.BaseModel):
    files: list = pydantic.Field(default=[], description='List of files to replay')
    replay_index: list = pydantic.Field(default=['0,-1,1'],
                                        description='The index of the packets to be replayed [start, end, nth]')
    loop: bool = pydantic.Field(default=False, description='Loop over all files if set')
    speedup: float = pydantic.Field(default=1.0, description='Speedup factor of the data')
    replace_time: bool = pydantic.Field(default=False,
                                        description='Replaces the original time in the packet with the time the packet was read')


redvypr_devicemodule = True


def quick_scan(filename, chunksize=65536):
    """
    Lightweight, stateless scan of a redvypr raw data file.

    Reads through the file once and extracts only the packet count and the
    first/last packet timestamp. Unlike the old packetreader class, this does
    NOT compute a checksum, does NOT build a seek index and does NOT use an
    on-disk cache file. It is meant purely to feed the preview table in the
    GUI (number of packets, first/last date), not to support random access.

    Returns a dict: {'npackets': int, 't_min': float or None, 't_max': float or None}
    """
    funcname = __name__ + '.quick_scan()'
    npackets = 0
    t_min = None
    t_max = None

    if filename.lower().endswith('.gz'):
        opener = gzip.open
    else:
        opener = open

    try:
        filestream = opener(filename, 'rb')
    except Exception as e:
        logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
        return {'npackets': npackets, 't_min': t_min, 't_max': t_max}

    data_buffer = b''
    try:
        while True:
            chunk = filestream.read(chunksize)
            if not chunk:
                break
            data_buffer += chunk
            # Extract all complete packets currently in the buffer
            while True:
                index_start = data_buffer.find(b'---')
                index_end = data_buffer.find(b'\0')
                if index_start == -1 or index_end == -1 or index_end <= index_start:
                    break

                raw = data_buffer[index_start:index_end]
                packet = None
                try:
                    packet = yaml.safe_load(raw.decode('utf-8'))
                except Exception:
                    logger.debug(funcname + ': Could not decode message {:s}'.format(str(raw)))

                if packet is not None:
                    try:
                        t = packet['_redvypr']['t']
                        if t_min is None:
                            t_min = t
                        t_max = t
                        npackets += 1
                    except Exception:
                        # Packet without the expected structure, skip it
                        pass

                data_buffer = data_buffer[index_end + 1:]
    finally:
        filestream.close()

    return {'npackets': npackets, 't_min': t_min, 't_max': t_max}


def packet_read_thread(filename,
                       chunksize, npacket_buf=10,
                       dataqueue=None,
                       commandqueue=None,
                       stopqueue=None,
                       statusqueue=None):
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
            dataqueue.put(None)
            return None
    else:
        try:
            filestream = open(filename, 'rb')
            logger.debug(funcname + ' Opened file: {:s}'.format(filename))
        except Exception as e:
            logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
            dataqueue.put(None)
            return None

    # Get the size of the data (within the file, this is different to the filesize, which can be gzipped
    fsize = os.path.getsize(filename)
    f = filestream
    try:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        datasize = size
        filestream.seek(0)
    except (EOFError, OSError) as e:
        logger.error(f"Aborting: Could not read file:{e}")
        dataqueue.put(None)
        return None
        # filestream.close()

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
            # print("Waiting for command")
            com = commandqueue.get()
            # print("Got command")
            if type(com) == int:  # Read n new packets
                nnewread = com
                nread = 0
            elif com == 'stop':  # Stop reading immediately
                logger.debug(funcname + ' Stopping ...')
                filestream.close()
                return
            while nread < nnewread:
                # print('Nread:',nread)
                # Non-blocking check for a stop request, so that even a large
                # nnewread batch can be interrupted quickly, regardless of how
                # many pending int-commands are still queued in commandqueue.
                try:
                    if stopqueue.get_nowait() == 'stop':
                        logger.debug(funcname + ' Stopping (inner loop) ...')
                        filestream.close()
                        return
                except queue.Empty:
                    pass

                seek_start = filestream.tell()
                data_read = filestream.read(chunksize)
                seek_now = filestream.tell()
                # print('data read', seek_start,seek_now, seek_now - seek_start,len(data_read),size)
                lendata = len(data_read)
                # print('len', len(data_read))
                if len(data_read) < chunksize:
                    flag_eof = True

                # Add potentially old data and the newly read data
                data_buffer += data_read
                seek_data_buffer_end = seek_now
                seek_data_buffer_start = seek_data_buffer_end - len(data_buffer)
                while True:
                    # print("loopiloop")
                    # Look for the start of a packet
                    try:
                        index_start = data_buffer.index(b'---')
                    except Exception as e:
                        index_start = None

                    # Look for the end of a packet
                    try:
                        pattern_end = b'\0'
                        index_end = data_buffer.index(pattern_end)
                        # index_end += len(pattern_end)
                    except Exception as e:
                        index_end = None

                    # print('data',data_buffer)
                    # print('index start',index_start,index_end)

                    if (index_end is not None) and (index_start is not None) and ((index_end - index_start) > 0):
                        # print("Decoding")
                        datab = data_buffer[index_start:index_end]
                        databs = datab.decode('utf-8')
                        # print('databs',databs,index_start,index_end)
                    else:
                        # print("Breaking")
                        break
                    try:
                        # data_packet = yaml.safe_load(databs)
                        # print("Load")
                        data_packet = yaml.unsafe_load(databs)
                        # print("Load done")
                        if (data_packet is not None):
                            numpacket = data_packet['_redvypr']['numpacket']
                            tpacket = data_packet['_redvypr']['t']
                            # print('Found datapacket',seek_data_buffer_start)
                            loc_packet_start = seek_data_buffer_start + index_start
                            loc_packet_length = index_end - index_start
                            # packets.append(data_packet)
                            dataqueue.put(data_packet)
                            nread += 1
                            # stat['packets_seek'].append(loc_packet_start)
                            # stat['packets_size'].append(loc_packet_length)
                            # stat['packets_num'].append(numpacket)
                            # stat['packets_t'].append(tpacket)

                            npackets_read += 1
                            # print('fdsfd',npackets_read)
                            # stat['npackets'] = npackets_read

                            if True:
                                dt = time.time() - tstatus
                                if dt > 0.5:
                                    tstatus = time.time()
                                    # logger.debug(funcname + ' Status:' + str(status_thread))
                            # Remove the packet from the data_buffer
                            data_buffer = data_buffer[index_end + len(pattern_end):]
                            seek_data_buffer_start = seek_data_buffer_end - len(data_buffer)
                    except:
                        logger.warning(funcname + ': Could not decode message:"{:s}"'.format(str(databs)),
                                       exc_info=True)

                    # print("loopiloop done")
                    # break

                if flag_eof:  # EOF, cleanup
                    # print("EOF")
                    logger.debug(funcname + ': EOF. Rewinding file')
                    filestream.seek(0)
                    t = time.time()
                    td = datetime.datetime.fromtimestamp(t)
                    tdstr = td.strftime("%Y-%m-%d %H:%M:%S.%f")
                    # print("EOF DONE")
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
                # status_thread['stat'] = stat
                statusqueue.put(status_thread)


def start(device_info, config={'filename': ''}, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening reading:')

    files = list(config['files'])
    replay_index = list(config['replay_index'])
    t_status = time.time()
    # dt_status = 2 # Status update
    dt_status = .5  # Status update
    t_sent = 0  # The time the last packets was sent
    t_packet_old = 1e12  # The time the last packet had (internally)
    try:
        config['speedup']
    except:
        config['speedup'] = 1.0  # Realtime

    speedup = config['speedup']
    #
    try:
        config['loop']
    except:
        config['loop'] = False

    loop = config['loop']

    # statistics = create_data_statistic_dict()

    bytes_read = 0
    packets_published = 0
    dt_packet_sum = 0
    bytes_read_total = 0
    packets_read_total = 0

    tfile = time.time()  # Save the time the file was created
    tflush = time.time()  # Save the time the file was created
    FLAG_NEW_FILE = True
    FLAG_PAUSED = False
    nfile = 0
    # These are (re)created for every file inside the FLAG_NEW_FILE block below.
    # Initialized to None here so a 'stop' command arriving before the first
    # file has been opened does not raise a NameError.
    read_commandqueue = None
    read_stopqueue = None
    read_thread = None
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
                        if read_stopqueue is not None:
                            # Picked up immediately by the inner read loop,
                            # independent of how many int-commands are still
                            # queued in read_commandqueue.
                            read_stopqueue.put('stop')
                        if read_commandqueue is not None:
                            # Also unblocks a pending commandqueue.get() in
                            # case the thread is waiting for the next batch.
                            read_commandqueue.put('stop')
                        logger.debug('stopping read thread')
                    except:
                        logger.debug('stopping read thread failed:', exc_info=True)
                    break
                elif command == 'pause':
                    logger.debug('Pausing')
                    FLAG_PAUSED = True
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass
                elif command == 'resume':
                    logger.debug('Resuming')
                    FLAG_PAUSED = False
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass
                elif command == 'speedup':
                    try:
                        comdata = data['_redvypr_command']['data']
                        speedup = float(comdata['speedup'])
                        sstr = funcname + ': Speedup changed to {:.2f}'.format(speedup)
                        logger.debug(sstr)
                    except Exception as e:
                        sstr = funcname + ': Could not apply speedup change: ' + str(e)
                        logger.warning(sstr)
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass

        if FLAG_PAUSED:
            # Keep all replay state (current file, buffered packets, file
            # position) untouched so replay continues exactly where it left
            # off once resumed, instead of restarting like start/stop does.
            time.sleep(0.1)
            continue

        if FLAG_NEW_FILE:
            packets = []
            read_dataqueue = queue.Queue()
            read_commandqueue = queue.Queue()
            read_stopqueue = queue.Queue()
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
            chunksize = 5000
            npacket_buf = 10
            nfile += 1
            logger.info(f'Starting read thread for file:{filename}')
            args = (filename, chunksize, npacket_buf, read_dataqueue, read_commandqueue, read_stopqueue, statusqueue)
            read_thread = threading.Thread(target=packet_read_thread, args=args, daemon=True)
            read_thread.start()
            read_commandqueue.put(npacket_buf)
            for i in range(npacket_buf):
                try:
                    p = read_dataqueue.get(timeout=2)
                    packets.append(p)
                except queue.Empty:
                    # File has fewer than npacket_buf packets (or is broken).
                    break

            # A file needs at least two packets to form a pnow/pnext pair
            # from which the inter-packet dt can be computed. Files with
            # fewer than npacket_buf packets are still replayed as long as
            # at least two were read; only 0 or 1 packets cause a skip.
            if len(packets) >= 2:
                FLAG_NEW_FILE = False
                pnow = packets.pop(0)
                pnext = packets.pop(0)
            else:
                if len(packets) == 1:
                    logger.warning(funcname + ': File {:s} contains only a single packet, skipping it '
                                               '(no dt can be computed).'.format(filename))
                FLAG_NEW_FILE = True

        # Check if the read thread is still alive. Packets it already queued
        # are drained below regardless of its status, so nothing it read
        # right before finishing gets discarded.
        thread_alive = read_thread.is_alive()
        if thread_alive and len(packets) < npacket_buf:
            dn = npacket_buf - len(packets)
            # print('Asking for new packets',dn)
            read_commandqueue.put(dn)
        while True:
            try:
                packets.append(read_dataqueue.get_nowait())
            except queue.Empty:
                break

        if len(packets) > 1:
            t_pnow = pnow['_redvypr']['t']
            t_pnext = pnext['_redvypr']['t']
            dt = t_pnext - t_pnow
            t_now = time.time()
            if config['replace_time']:
                pnow['t'] = t_now
                pnow['_redvypr']['t'] = t_now

            # print('sending',pnow)
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

            # print('sleeping dt_packet',dt_packet)
            time.sleep(dt_packet)
            t_sent = time.time()
        elif not thread_alive:
            # The file is exhausted and at most one packet is left in
            # packets, so the normal pnow/pnext advance above can no longer
            # run. Flush pnow, pnext and that leftover packet here instead
            # of dropping them, then move on to the next file.
            logger.debug(funcname + ' Reading thread finished')
            remaining = [pnow, pnext] + packets
            packets = []
            for i, p in enumerate(remaining):
                if config['replace_time']:
                    t_now = time.time()
                    p['t'] = t_now
                    p['_redvypr']['t'] = t_now
                dataqueue.put(p)
                packets_published += 1
                if i < len(remaining) - 1:
                    dt = remaining[i + 1]['_redvypr']['t'] - p['_redvypr']['t']
                    dt_packet = dt / speedup
                    dt_packet_sum += dt_packet
                    if (dt_packet < 0):
                        dt_packet = 0
                    if (dt_packet > 10):
                        logger.warning(funcname + ' Long dt_packet of {:f} seconds'.format(dt_packet))
                    time.sleep(dt_packet)
            t_sent = time.time()
            FLAG_NEW_FILE = True
        else:
            time.sleep(0.1)

        # Status update
        if (time.time() - t_status) > dt_status:
            # print('status')
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
# Reusable file-selection/replay-config widget. Works on any
# DeviceCustomConfig-like object (files, replay_index, loop, speedup,
# replace_time), not just a full RedvyprDevice, so it can be embedded both
# in rawdatareplay's own initDeviceWidget and elsewhere (e.g. a future
# "subscribe from file" UI on another device).
#
#
class FileReplayConfigWidget(QtWidgets.QWidget):
    speedupChanged = QtCore.pyqtSignal(float)
    loopChanged = QtCore.pyqtSignal(bool)
    replaceTimeChanged = QtCore.pyqtSignal(bool)
    filesChanged = QtCore.pyqtSignal()

    def __init__(self, custom_config, parent=None):
        super().__init__(parent)
        self.custom_config = custom_config
        layout = QtWidgets.QGridLayout(self)
        self.file_statistics = {}
        # Background quick_scan jobs started by inspect_data_thread(), each entry is a
        # dict {'thread', 'queue', 'row', 'filename'}. Polled by update_table_from_thread().
        self.inspect_threads = []
        self.config_widgets = []  # A list of all widgets that can only be used while not replaying
        # Input output widget
        self.inlabel = QtWidgets.QLabel("Filenames")
        self.inlabel.setStyleSheet(''' font-size: 20px; font: bold''')
        self.inlist = QtWidgets.QTableWidget()

        self.inlist.setRowCount(1)
        # self.inlist.setSortingEnabled(True)
        self.col_replaypackets = 0
        self.col_npackets = 1
        self.col_tmin = 2
        self.col_tmax = 3
        self.col_fname = 4
        self.col_scan = 5
        self.col_remove = 6
        self.ncols = 7
        self.inlist.setColumnCount(self.ncols)
        self.__filelistheader__ = [[]] * self.ncols
        self.__filelistheader__[self.col_tmax] = 'Last date'
        self.__filelistheader__[self.col_tmin] = ' First date'
        self.__filelistheader__[self.col_npackets] = 'Packets'
        self.__filelistheader__[self.col_replaypackets] = 'Replay Packets'
        self.__filelistheader__[self.col_fname] = 'Filename'
        self.__filelistheader__[self.col_scan] = ''
        self.__filelistheader__[self.col_remove] = ''
        self.inlist.setHorizontalHeaderLabels(self.__filelistheader__)

        self.addfilesbtn = QtWidgets.QPushButton("Add files")
        self.addfilesbtn.clicked.connect(self.add_files)
        self.remfilesbtn = QtWidgets.QPushButton("Remove all files")
        self.remfilesbtn.clicked.connect(self.remove_all_files_clicked)
        self.scanfilesbtn = QtWidgets.QPushButton("Scan all files")
        self.scanfilesbtn.clicked.connect(self.scan_all_files_clicked)
        self.config_widgets.append(self.inlist)
        self.config_widgets.append(self.addfilesbtn)

        # Looping the data?
        self.loop_checkbox = QtWidgets.QCheckBox('Loop')
        loopflag = bool(self.custom_config.loop)
        self.loop_checkbox.setChecked(loopflag)
        self.loop_checkbox.stateChanged.connect(self.values_changed)
        self.replace_time_checkbox = QtWidgets.QCheckBox('Replace time')
        replace_time_flag = bool(self.custom_config.replace_time)
        self.replace_time_checkbox.setChecked(replace_time_flag)
        self.replace_time_checkbox.stateChanged.connect(self.values_changed)
        # Speedup
        self.speedup_edit = QtWidgets.QLineEdit(self)
        onlyDouble = QtGui.QDoubleValidator()
        self.speedup_edit.setValidator(onlyDouble)
        self.speedup_edit.setToolTip('Speedup of the packet replay.')
        self.speedup_label = QtWidgets.QLabel("Speedup factor")
        speedup = float(self.custom_config.speedup)
        self.speedup_edit.setText("{:.1f}".format(speedup))
        self.speedup_edit.textChanged.connect(self.values_changed)

        layout.addWidget(self.addfilesbtn, 0, 0, 1, -1)
        layout.addWidget(self.remfilesbtn, 1, 0, 1, -1)
        layout.addWidget(self.scanfilesbtn, 2, 0, 1, -1)
        layout.addWidget(self.inlabel, 3, 0, 1, -1, QtCore.Qt.AlignCenter)
        layout.addWidget(self.inlist, 4, 0, 1, -1)
        layout.addWidget(self.loop_checkbox, 5, 0)
        layout.addWidget(self.replace_time_checkbox, 5, 1)
        layout.addWidget(self.speedup_label, 5, 2, 1, 1, QtCore.Qt.AlignRight)
        layout.addWidget(self.speedup_edit, 5, 3, 1, 1, QtCore.Qt.AlignRight)

        # Update the widgets depending on the configuration
        self.update_filenamelist()

    def values_changed(self):
        """ Called whenever loop/replace_time/speedup are edited: writes the
        new values into custom_config and emits signals so an embedding
        widget can react (e.g. push a live speedup update to a running
        thread). Also called explicitly by callers that need custom_config
        guaranteed up to date right before starting a replay.
        """
        funcname = self.__class__.__name__ + '.values_changed()'
        logger.debug(funcname)
        speedup = float(self.speedup_edit.text())
        self.custom_config.speedup = speedup
        loopflag = self.loop_checkbox.isChecked()
        replace_time_flag = self.replace_time_checkbox.isChecked()
        self.custom_config.loop = loopflag
        self.custom_config.replace_time = replace_time_flag

        self.speedupChanged.emit(speedup)
        self.loopChanged.emit(loopflag)
        self.replaceTimeChanged.emit(replace_time_flag)

    def table_changed(self, row, col):
        funcname = self.__class__.__name__ + '.table_changed()'
        logger.debug(funcname)
        # print('Row',row,'Col',col)
        item = self.inlist.item(row, col)

        if col == self.col_replaypackets:  # If the replay index was changed
            rindex = item.text()
            try:
                rs = rindex.split(',')
                istart = int(rs[0])
                iend = int(rs[1])
                istep = int(rs[2])
                self.custom_config.replay_index[item.replay_index] = rindex
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
            nfiles = len(self.custom_config.files)
            self.inlist.setRowCount(nfiles)
            rows = []
            for i, f in enumerate(self.custom_config.files):
                if len(self.custom_config.replay_index) < (i + 1):
                    self.custom_config.replay_index.append(self.custom_config.replay_index[-1])
                    replayindex = self.custom_config.replay_index[-1]
                else:
                    replayindex = self.custom_config.replay_index[i]

                item = QtWidgets.QTableWidgetItem(str(replayindex))
                item.replay_index = i
                item.replay_index_str = replayindex
                self.inlist.setItem(i, self.col_replaypackets, item)
                # Filename
                item = QtWidgets.QTableWidgetItem(str(f))
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.inlist.setItem(i, self.col_fname, item)
                # Per-row scan button
                scanbtn = QtWidgets.QPushButton("Scan")
                scanbtn.clicked.connect(lambda checked, row=i: self.scan_file_row(row))
                self.inlist.setCellWidget(i, self.col_scan, scanbtn)
                # Per-row remove button
                rembtn = QtWidgets.QPushButton("Remove")
                rembtn.clicked.connect(lambda checked, row=i: self.remove_file_row(row))
                self.inlist.setCellWidget(i, self.col_remove, rembtn)
                rows.append(i)

            self.inlist.resizeColumnsToContents()
            # for i, f in enumerate(self.custom_config.files):
            #    self.scan_file(str(f), i)

            self.inlist.resizeColumnsToContents()

            # Loop flag
            loop = bool(self.custom_config.loop)
            self.loop_checkbox.setChecked(loop)
            speedupstr = "{:.1f}".format(float(self.custom_config.speedup))
            self.speedup_edit.setText(speedupstr)
            ## Add the packetnumber etc etc
            # self.scan_files(rows)
            self.inlist.cellChanged.connect(self.table_changed)
        except Exception as e:
            logger.exception(e)

    def scan_all_files_clicked(self):
        """ Scans every file currently in the list, regardless of selection.
        """
        funcname = self.__class__.__name__ + '.scan_all_files_clicked()'
        logger.debug(funcname)
        rows = list(range(self.inlist.rowCount()))
        self.scan_files(rows)

    def scan_file_row(self, row):
        """ Called by a per-row 'Scan' button click; scans just that row's file.
        """
        funcname = self.__class__.__name__ + '.scan_file_row()'
        logger.debug(funcname)
        filename = self.inlist.item(row, self.col_fname).text()
        self.scan_file(filename, row)

    def scan_file(self, filename, row):
        """ Scans a single file (synchronously) and fills in the packet count
        and first/last date for the corresponding table row.
        """
        funcname = self.__class__.__name__ + '.scan_file()'
        logger.debug(funcname)

        stat = self.inspect_data(filename, rescan=False)
        if stat['npackets'] > 0:
            npackets = stat['npackets']
            t_min = stat['t_min']
            t_max = stat['t_max']
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
        """ Returns basic statistics (packet count, first/last timestamp) for
        filename, using a cached result unless rescan is True.
        """
        funcname = self.__class__.__name__ + '.inspect_data()'
        logger.debug(funcname)

        if rescan or (filename not in self.file_statistics):
            logger.debug(funcname + ': Scanning file {:s}'.format(filename))
            self.file_statistics[filename] = quick_scan(filename)
        else:
            logger.debug(funcname + ': No rescan of {:s}'.format(filename))

        return self.file_statistics[filename]

    def scan_files(self, rows):
        """ Scans the selected files from the files list for possible datastreams
        """
        funcname = self.__class__.__name__ + '.scan_files()'
        logger.debug(funcname)

        rows = sorted(set(rows))
        for i in rows:
            filename = self.inlist.item(i, self.col_fname).text()
            self.scan_file(filename, i)

        self.inlist.resizeColumnsToContents()

    @staticmethod
    def _quick_scan_worker(filename, resultqueue):
        """ Runs quick_scan() in a background thread and puts the result into resultqueue. """
        stat = quick_scan(filename)
        resultqueue.put(stat)

    def inspect_data_thread(self, filename, row, rescan=False):
        """ Starts a quick_scan() for filename in a background thread, so the
        GUI stays responsive while larger files are scanned. Progress is
        picked up later by update_table_from_thread().
        """
        funcname = self.__class__.__name__ + '.inspect_data_thread()'
        logger.debug(funcname)

        if rescan or (filename not in self.file_statistics):
            logger.debug(funcname + ': Scanning file {:s}'.format(filename))
            resultqueue = queue.Queue()
            thread = threading.Thread(target=self._quick_scan_worker,
                                      args=(filename, resultqueue), daemon=True)
            thread.start()
            self.inspect_threads.append({'thread': thread, 'queue': resultqueue,
                                         'row': row, 'filename': filename})
        else:
            logger.debug(funcname + ': No rescan of {:s}'.format(filename))

    def update_table_from_thread(self):
        """ Polls the pending background scan jobs started by
        inspect_data_thread() and fills in table rows for the ones that are
        finished. Stops self.threadtimer once no jobs are left.
        """
        funcname = self.__class__.__name__ + '.update_table_from_thread()'
        logger.debug(funcname)
        finished_jobs = []

        for job in self.inspect_threads:
            try:
                status = job['queue'].get_nowait()
            except queue.Empty:
                status = None

            if status is not None:
                row = job['row']
                self.file_statistics[job['filename']] = status
                packetitem = QtWidgets.QTableWidgetItem(str(status['npackets']))
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
                finished_jobs.append(job)

        for job in finished_jobs:
            self.inspect_threads.remove(job)

        if len(self.inspect_threads) == 0:
            logger.debug('No thread running anymore')
            self.threadtimer.stop()

    def remove_all_files_clicked(self):
        """ Removes every file currently in the list, regardless of selection.
        """
        funcname = self.__class__.__name__ + '.remove_all_files_clicked()'
        logger.debug(funcname)
        self.custom_config.files.clear()
        self.update_filenamelist()
        self.filesChanged.emit()

    def remove_file_row(self, row):
        """ Called by a per-row 'Remove' button click; removes just that row's file.
        """
        funcname = self.__class__.__name__ + '.remove_file_row()'
        logger.debug(funcname)
        self.custom_config.files.pop(row)
        self.update_filenamelist()
        self.filesChanged.emit()

    def add_files(self):
        """ Opens a dialog to choose file to add
        """
        funcname = self.__class__.__name__ + '.add_files()'
        regex_indexfile = re.compile('.*[.index][0-9a-f]{32}.yaml.gz')
        logger.debug(funcname)
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Rawdatafiles", "",
                                                              "redvypr raw gzip (*.redvypr_yaml.gz);;redvypr raw (*.redvypr_yaml);;All Files (*)")
        for f in filenames:
            if regex_indexfile.match(f) is None:
                self.custom_config.files.append(f)
            else:
                logger.info('Found index file {}, will not use it'.format(f))

        self.update_filenamelist()
        self.inlist.sortItems(self.col_fname, QtCore.Qt.AscendingOrder)
        self.filesChanged.emit()

    def resort_files(self):
        """ Resorts the files in config['files'] according to the sorting in the table
        """
        files_new = []
        nfiles = len(self.custom_config.files)
        for i in range(nfiles):
            filename = self.inlist.item(i, self.col_fname).text()
            files_new.append(filename)

        self.custom_config.files = files_new


#
#
# Reusable status table + log view for a file replay. Takes a statusqueue
# directly (not a device), so it can be driven by rawdatareplay's own
# device.statusqueue or by a dedicated queue belonging to some other
# mechanism (e.g. a future per-device file subscription).
#
#
class FileReplayStatusWidget(QtWidgets.QWidget):
    def __init__(self, statusqueue, files=None, parent=None):
        super().__init__(parent)
        self.statusqueue = statusqueue
        layout = QtWidgets.QVBoxLayout(self)
        hlayout = QtWidgets.QFormLayout()
        self.text = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.scrollchk = QtWidgets.QCheckBox('Scroll to end')
        self.scrollchk.setChecked(True)
        self.statuslab = QtWidgets.QLabel("Status")
        self.text.setMaximumBlockCount(10000)
        # Add a table
        self.statustable = QtWidgets.QTableWidget()
        self.__statusheader__ = ['Time', 'Filename', 'Filesize', 'Bytes read', 'Bytes total', '%', 'Packets read']
        self.statustable.setColumnCount(len(self.__statusheader__))
        self.statustable.setHorizontalHeaderLabels(self.__statusheader__)
        self.statustable.verticalHeader().setVisible(False)
        self.statustable.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.col_filename = 1
        # Maps a file's basename (as reported in status dicts) to its row
        self.row_for_filename = {}
        self.populate_file_table(files or [])

        hlayout.addRow(self.statuslab)
        layout.addWidget(self.statustable, 2)
        layout.addLayout(hlayout)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.scrollchk, 0)
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update)
        self.statustimer.start(500)

    def populate_file_table(self, files):
        """ Fills the status table with one row per given file, so all files
        are visible even before any status update for them arrived. Callers
        re-invoke this (e.g. on a start/stop transition) if the file list
        may have changed since the widget was created.
        """
        self.statustable.setRowCount(len(files))
        self.row_for_filename = {}
        for row, f in enumerate(files):
            basename = os.path.basename(f)
            self.row_for_filename[basename] = row
            item = QtWidgets.QTableWidgetItem(basename)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.statustable.setItem(row, self.col_filename, item)
        self.statustable.resizeColumnsToContents()

    def update(self):
        while (self.statusqueue.empty() == False):
            try:
                data = self.statusqueue.get(block=False)
            except:
                break

            if type(data) == dict:
                # print('data',data)
                statuskeys = ['time', 'filename', 'filesize', 'seek', 'datasize', 'pc', 'packets_num']
                filename = data.get('filename')
                row = self.row_for_filename.get(filename)
                if row is None:
                    # Not one of the files known at widget creation (e.g. the
                    # file list changed after this widget was built): append
                    # a row for it instead of dropping the update.
                    row = self.statustable.rowCount()
                    self.statustable.setRowCount(row + 1)
                    self.row_for_filename[filename] = row
                for i, k in enumerate(statuskeys):
                    datastr = str(data[k])
                    dataitem = QtWidgets.QTableWidgetItem(datastr)
                    self.statustable.setItem(row, i, dataitem)
                self.statustable.resizeColumnsToContents()
            else:
                # Original position of scrollbar
                pos = self.text.verticalScrollBar().value()
                self.text.moveCursor(QtGui.QTextCursor.End)
                self.text.insertPlainText(str(data) + '\n')
                if (self.scrollchk.isChecked()):
                    self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
                else:
                    self.text.verticalScrollBar().setValue(pos)


#
#
# The init widget
#
#
class initDeviceWidget(QtWidgets.QWidget):
    connect = QtCore.pyqtSignal(
        RedvyprDevice)  # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices

    def __init__(self, device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        self.device = device
        self.label = QtWidgets.QLabel("rawdatareplay setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')

        self.file_config = FileReplayConfigWidget(self.device.custom_config)
        self.file_config.speedupChanged.connect(self.speedup_changed_live)

        self.startbtn = QtWidgets.QPushButton("Start replay")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)
        self.startbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        # Pauses the running replay in place (unlike stop, resuming continues
        # from the exact same file/position instead of starting over)
        self.pausebtn = QtWidgets.QPushButton("Pause")
        self.pausebtn.clicked.connect(self.pause_clicked)
        self.pausebtn.setCheckable(True)
        self.pausebtn.setEnabled(False)
        self.pausebtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        layout.addWidget(self.label, 0, 0, 1, -1)
        layout.addWidget(self.file_config, 1, 0, 1, -1)
        layout.addWidget(self.startbtn, 2, 0, 2, 2)
        layout.addWidget(self.pausebtn, 2, 2, 2, 2)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def speedup_changed_live(self, speedup):
        # The running thread got its own copy of the config at start time,
        # so it will not pick up custom_config.speedup on its own. Push the
        # new value to it directly so the speedup can be changed live.
        if self.device.get_thread_status()['thread_running']:
            self.device.thread_command('speedup', comdata={'speedup': speedup})

    def finalize_init(self):
        """ Util function that is called by redvypr after initializing all config (i.e. the configuration from a yaml file)
        """
        funcname = self.__class__.__name__ + '.finalize_init()'
        logger.debug(funcname)

    def con_clicked(self):
        funcname = self.__class__.__name__ + '.con_clicked():'
        logger.debug(funcname)
        button = self.sender()
        if (button == self.adddeviceinbtn):
            self.connect.emit(self.device)

    def start_clicked(self):
        funcname = self.__class__.__name__ + '.start_clicked():'
        logger.debug(funcname)
        button = self.sender()
        if button.isChecked():
            logger.debug(funcname + "button pressed")
            # Update the config for replay
            # update loop, replace_time and speedup
            self.file_config.values_changed()
            # Replay index
            self.device.thread_start()
        else:
            logger.debug(funcname + 'button released')
            self.device.thread_stop()

    def pause_clicked(self):
        """ Pauses/resumes the running replay in place. Unlike stop/start,
        this does not reset the file index or read position: the replay
        thread simply idles and continues from the same spot on resume.
        """
        funcname = self.__class__.__name__ + '.pause_clicked():'
        logger.debug(funcname)
        if self.pausebtn.isChecked():
            logger.debug(funcname + 'button pressed, pausing')
            self.pausebtn.setText('Resume')
            self.device.thread_command('pause')
        else:
            logger.debug(funcname + 'button released, resuming')
            self.pausebtn.setText('Pause')
            self.device.thread_command('resume')

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']

        # Running
        if (thread_status):
            self.startbtn.setText('Stop')
            self.startbtn.setChecked(True)
            for w in self.file_config.config_widgets:
                w.setEnabled(False)
            self.pausebtn.setEnabled(True)
        # Not running
        else:
            self.startbtn.setText('Start')
            for w in self.file_config.config_widgets:
                w.setEnabled(True)

            # Check if an error occured and the startbutton
            if (self.startbtn.isChecked()):
                self.startbtn.setChecked(False)
            # self.conbtn.setEnabled(True)

            # Pause has no meaning while stopped: disable it and reset its
            # state so the next start always begins unpaused.
            self.pausebtn.setEnabled(False)
            if self.pausebtn.isChecked():
                self.pausebtn.setChecked(False)
            self.pausebtn.setText('Pause')


class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self, device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.device = device
        self.status_widget = FileReplayStatusWidget(self.device.statusqueue,
                                                     files=list(self.device.custom_config.files))
        layout.addWidget(self.status_widget)
        # Tracks the thread's running state so the file table is only
        # rebuilt on a start/stop transition (the file list can only change
        # while stopped, since initDeviceWidget disables it while running).
        self.thread_was_running = self.device.get_thread_status()['thread_running']
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.check_thread_transition)
        self.statustimer.start(500)

    def check_thread_transition(self):
        thread_running = self.device.get_thread_status()['thread_running']
        if thread_running != self.thread_was_running:
            self.status_widget.populate_file_table(list(self.device.custom_config.files))
            self.thread_was_running = thread_running

