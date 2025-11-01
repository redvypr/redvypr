"""

Logger that writes xlsx files

"""

import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import logging
import sys
import yaml
import copy
import gzip
import os
import xlsxwriter
import pympler.asizeof
import pydantic
import typing
from redvypr.device import RedvyprDevice
import redvypr.data_packets as data_packets
import redvypr.redvypr_address as redvypr_address
import redvypr.packet_statistic as packet_statistics
import redvypr.gui

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.xlsxwriter')
logger.setLevel(logging.INFO)

time_format = 'yyyy-mm-dd HH:MM:SS.000'

row_address = 0
row_host = 1
row_uuid = 2
row_device = 3
row_publisher = 4
row_packetid = 5
row_datakey = 6
row_dataunit = 7
row_firstdata = row_dataunit + 1

redvypr_devicemodule = True
class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = "Saves subscribed devices in a xlsx file"
    clear_datainqueue_before_thread_starts: bool = True
    gui_tablabel_display: str = 'xlsx logging status'
    gui_icon: str = 'fa5s.file-excel'

class DeviceCustomConfig(pydantic.BaseModel):
    dt_sync: int = pydantic.Field(default=5,description='Time after which an open file is synced on disk')
    dt_newfile: int = pydantic.Field(default=3600,description='Time after which a new file is created')
    dt_newfile_unit: typing.Literal['none','seconds','hours','days'] = pydantic.Field(default='seconds')
    dt_update: int = pydantic.Field(default=2,description='Time after which an upate is sent to the gui')
    datakey_expansionlevel: int = pydantic.Field(default=3, description='Level of the datakey expansionlevel')
    size_newfile:int = pydantic.Field(default=500,description='Size of object in RAM after which a new file is created')
    size_newfile_unit: typing.Literal['none','bytes','kB','MB'] = pydantic.Field(default='MB')
    datafolder:str = pydantic.Field(default='./',description='Folder the data is saved to')
    fileextension:str= pydantic.Field(default='xlsx',description='File extension, if empty not used')
    fileprefix:str= pydantic.Field(default='redvypr',description='If empty not used')
    filepostfix:str= pydantic.Field(default='xlsxwriter',description='If empty not used')
    filedateformat:str= pydantic.Field(default='%Y-%m-%d_%H%M%S',description='Dateformat used in the filename, must be understood by datetime.strftime')
    filecountformat:str= pydantic.Field(default='04',description='Format of the counter. Add zero if trailing zeros are wished, followed by number of digits. 04 becomes {:04d}')

def create_logfile(config,count=0,all_worksheets={}):
    funcname = __name__ + '.create_logfile():'
    logger.debug(funcname)

    filename = ''
    if len(config['datafolder']) > 0:
        if os.path.isdir(config['datafolder']):
            filename += config['datafolder'] + os.sep
        else:
            logger.warning(funcname + ' Data folder {:s} does not exist.'.format(filename))
            return None

    if(len(config['fileprefix'])>0):
        filename += config['fileprefix']

    if (len(config['filedateformat']) > 0):
        tstr = datetime.datetime.now().strftime(config['filedateformat'])
        filename += '_' + tstr

    if (len(config['filecountformat']) > 0):
        cstr = "{:" + config['filecountformat'] +"d}"
        filename += '_' + cstr.format(count)

    if (len(config['filepostfix']) > 0):
        filename += '_' + config['filepostfix']

    if (len(config['fileextension']) > 0):
        filename += '.' + config['fileextension']

    logger.info(funcname + ' Will create a new file: {:s}'.format(filename))

    # Create a workbook and add a worksheet.
    workbook = xlsxwriter.Workbook(filename,{'in_memory': True})
    date_format = workbook.add_format({'num_format': time_format})
    header_format = workbook.add_format({'bold': True,'bg_color':'#F0F0F0'})
    text_wrap_format = workbook.add_format({'text_wrap': True})
    all_worksheets['header_format'] = header_format
    all_worksheets['text_wrap_format'] = text_wrap_format
    formats = {}
    formats['date'] = date_format

    worksheet_summary = workbook.add_worksheet('summary')
    # Write some information
    worksheet_summary.write(0, 0, 'redvypr')
    worksheet_summary.write(0, 1, 'xlsxwriter')
    redvypr_version_str = 'redvypr {}'.format(redvypr.version)
    worksheet_summary.write(1, 0, 'version')
    worksheet_summary.write(1, 1, redvypr_version_str)
    all_worksheets['summary'] = worksheet_summary
    all_worksheets['metadata'] = workbook.add_worksheet('metadata')
    all_worksheets['metadata_indices'] = {'rows': [], 'columns': []}
    return [workbook,filename,formats]

def write_metadata(workbook, all_worksheets, datakey, data, deviceinfo_all, device_info, config):
    funcname = 'write_metadata():'
    logger.debug(funcname)
    raddress_tmp = redvypr_address.RedvyprAddress(data, datakey=datakey)
    raddress_tmp_str = raddress_tmp.to_address_string('h,d,i,k')
    metadata_tmp = packet_statistics.get_metadata_deviceinfo_all(deviceinfo_all, raddress_tmp)
    header_rows = [(row_host, raddress_tmp.hostname, 'hostname')]
    header_rows.append((row_uuid, raddress_tmp.uuid, 'uuid'))
    header_rows.append((row_device, raddress_tmp.device, 'device'))
    header_rows.append((row_publisher, raddress_tmp.publisher, 'publisher'))
    header_rows.append((row_packetid, raddress_tmp.packetid, 'packetid'))
    header_rows.append((row_datakey, datakey, 'datakey'))
    for header_row in header_rows:
        colindex = 0
        all_worksheets['metadata'].write(header_row[0], colindex, header_row[1],
                                                    all_worksheets['header_format'])
        all_worksheets['metadata'].write(header_row[0], 0, header_row[2], all_worksheets['header_format'])
    #device_worksheets[packet_address_str].write(lineindex, colindex, datawrite)
    if len(metadata_tmp.keys())>0: # Check if something was found
        mkeys = list(metadata_tmp.keys())
        #print('-----')
        #print('Got metadata keys',metadata_tmp)
        try:
            datakey_unit = metadata_tmp['unit']
            mkeys.remove('unit')
            mkeys.insert(0,'unit')
        except:
            datakey_unit = None

        for metakey in mkeys:
            # Get the rows and columns
            try:
                rowind = all_worksheets['metadata_indices']['rows'].index(metakey)
                rowind_write = rowind + row_firstdata
            except:
                all_worksheets['metadata_indices']['rows'].append(metakey)
                rowind = all_worksheets['metadata_indices']['rows'].index(metakey)
                rowind_write = rowind + row_firstdata
                colind_datakey = 0
                # Write the metakey in the correct row
                #all_worksheets['metadata'].write(row_firstdata, 0, 'Metadata key')
                all_worksheets['metadata'].write(rowind_write, colind_datakey, metakey, all_worksheets['header_format'])

            # And finally write the metadata
            try:
                colind = all_worksheets['metadata_indices']['columns'].index(raddress_tmp_str)
                colind_write = colind + 1
            except:
                try:
                    all_worksheets['metadata_indices']['columns'].append(raddress_tmp_str)
                    colind = all_worksheets['metadata_indices']['columns'].index(raddress_tmp_str)
                    colind_write = colind + 1
                    rowind_write_col = 0
                    #all_worksheets['metadata'].write(rowind_write_col, colind_write, raddress_tmp_str,all_worksheets['header_format'])
                    #all_worksheets['metadata'].write(rowind_write_col+1, colind_write, raddress_tmp_str_full,all_worksheets['header_format'])
                    for header_row in header_rows:
                        all_worksheets['metadata'].write(header_row[0], colind_write, header_row[1],
                                                         all_worksheets['header_format'])

                except:
                    logger.info('Error',exc_info=True)


            #print('Writing metadata for address')
            datawrite = metadata_tmp[metakey]
            all_worksheets['metadata'].write(rowind_write, colind_write, datawrite)

        all_worksheets['metadata'].autofit()
        return datakey_unit

def start(device_info, config, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    logger_start = logging.getLogger('redvypr.device.xlsxwriter.thread')
    logger_start.setLevel(logging.DEBUG)
    funcname = __name__ + '.start()'
    logger_start.debug(funcname + ':Opening writing:')
    #print('Config',config)
    data_write_to_file = [] # List of columns to be written to file
    count = 0
    all_worksheets = {}
    deviceinfo_all = None
    if True:
        try:
            dtneworig = config['dt_newfile']
            dtunit = config['dt_newfile_unit']
            if(dtunit.lower() == 'seconds'):
                dtfac = 1.0
            elif(dtunit.lower() == 'hours'):
                dtfac = 3600.0
            elif(dtunit.lower() == 'days'):
                dtfac = 86400.0
            else:
                dtfac = 0
                
            dtnews = dtneworig * dtfac
            logger_start.info(funcname + ' Will create new file every {:d} {:s}.'.format(config['dt_newfile'],config['dt_newfile_unit']))
        except:
            logger_start.warning(funcname + 'Could not start',exc_info=True)
            dtnews = 0
            
        try:
            sizeneworig = config['size_newfile']
            sizeunit = config['size_newfile_unit']
            if(sizeunit.lower() == 'kb'):
                sizefac = 1000.0
            elif(sizeunit.lower() == 'mb'):            
                sizefac = 1e6
            elif(sizeunit.lower() == 'bytes'):            
                sizefac = 1 
            else:
                sizefac = 0
                
            sizenewb = sizeneworig * sizefac # Size in bytes
            logger_start.info(funcname + ' Will create new file every {:d} {:s}.'.format(config['size_newfile'],config['size_newfile_unit']))
        except:
            logger_start.debug("Could not open new file",exc_info=True)
            sizenewb = 0  # Size in bytes
            
    try:
        config['dt_sync']
    except:
        config['dt_sync'] = 5

    bytes_written = 0
    packets_written = 0
    bytes_written_total = 0
    packets_written_total = 0
    device_worksheets = {} # The extended info of the worksheets for the devices
    device_worksheets_reduced = {} # The worksheets for the devices
    device_worksheets_indices = {}
    numworksheet = 0
    [workbook,filename,formats] = create_logfile(config,count,all_worksheets)
    worksheet_summary = all_worksheets['summary']

    data_stat = {'_deviceinfo': {}}
    data_stat['_deviceinfo']['filename'] = filename
    data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
    data_stat['_deviceinfo']['created'] = time.time()
    data_stat['_deviceinfo']['bytes_written'] = bytes_written
    data_stat['_deviceinfo']['packets_written'] = packets_written
    dataqueue.put(data_stat)
    count += 1

    tfile = time.time() # Save the time the file was created
    tflush = time.time() # Save the time the file was created
    tupdate = time.time() # Save the time for the update timing
    FLAG_RUN = True
    file_status = {}
    file_status_reduced = {}
    while FLAG_RUN:
        tcheck = time.time()
        # Flush file on regular basis
        if ((time.time() - tflush) > config['dt_sync']):
            #print('Flushing, not implemented (yet)')
            bytes_written = pympler.asizeof.asizeof(workbook)
            #print('Bytes written',bytes_written)
            tflush = time.time()

        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
                packet_address = redvypr.RedvyprAddress(data)
                #print('xlsxlogger: Got data',data)

                if (data is not None):
                    [command,comdata] = data_packets.check_for_command(data, thread_uuid=device_info['thread_uuid'], add_data=True)
                    if (command is not None):
                        logger_start.debug('Command: {:s}'.format(str(command)))
                        if(command == 'stop'):
                            logger_start.debug('Stop command')
                            FLAG_RUN = False
                            break

                        if (command == 'info'):
                            logger_start.debug('Metadata command')
                            if packet_address.packetid == 'metadata':
                                deviceinfo_all = data['deviceinfo_all']

                #statistics = data_packets.do_data_statistics(data,statistics)
                address_format = 'h,p,d'
                packet_address_str = packet_address.to_address_string(address_format)
                colindex_time = 1
                colindex_numpacket = 0
                coloffset = colindex_time + 1
                # Ignore some packages
                if redvypr_address.RedvyprAddress(redvypr.metadata_address)(data,strict=False):
                    logger_start.debug('Ignoring metadata packet')
                    continue

                try:
                    device_worksheets[packet_address_str]
                except:
                    numworksheet += 1
                    numworksheet_offset = 2
                    devicename = packet_address.device.replace('/','_').replace('[','_').replace(']','_').replace('\\','_').replace('*','_').replace(':','_')
                    packet_address_str_xlsx = '{:02d}_{}'.format(numworksheet,devicename)
                    if len(packet_address_str_xlsx) > 31:
                        packet_address_str_xlsx = packet_address_str_xlsx[0:31]

                    worksheet_summary.write(numworksheet_offset, 0, 'device')
                    worksheet_summary.write(numworksheet_offset, 1, 'worksheet')
                    worksheet_summary.write(numworksheet + numworksheet_offset, 0, packet_address_str)
                    worksheet_summary.write(numworksheet + numworksheet_offset, 1, packet_address_str_xlsx)
                    logger_start.debug('Will create workbook for {}'.format(packet_address_str_xlsx))
                    device_worksheets[packet_address_str] = workbook.add_worksheet(packet_address_str_xlsx)
                    device_worksheets_indices[packet_address_str] = {'datakeys':[],'numline':0,'colindex':{}}
                    device_worksheets_indices[packet_address_str]['worksheet'] = packet_address_str_xlsx
                    device_worksheets_reduced[packet_address_str] = "worksheet: {}, #written: {}".format(packet_address_str_xlsx,0)
                    #
                    device_worksheets[packet_address_str].write(row_address,0,'Address',all_worksheets['header_format'])
                    device_worksheets[packet_address_str].write(row_address,1,packet_address_str,all_worksheets['header_format'])
                    #
                    device_worksheets[packet_address_str].write(row_datakey, colindex_time, 'Excel time',all_worksheets['header_format'])
                    for row in range(row_host,row_datakey):
                        device_worksheets[packet_address_str].write(row, colindex_time, '',
                                                                    all_worksheets['header_format'])
                    device_worksheets[packet_address_str].write(row_dataunit, colindex_time, time_format,all_worksheets['header_format'])
                    device_worksheets[packet_address_str].write(row_datakey, colindex_numpacket, 'Numpacket',all_worksheets['header_format'])
                    device_worksheets[packet_address_str].write(row_dataunit, colindex_numpacket, '#',all_worksheets['header_format'])
                    try:
                        file_status[filename]['worksheets']
                    except:
                        file_status[filename] = {'worksheets':{}}
                    try:
                        file_status_reduced[filename]['worksheets']
                    except:
                        file_status_reduced[filename] = {'worksheets': {}}

                    data_stat = {'_deviceinfo': {}}
                    file_status[filename]['worksheets'][packet_address_str] = device_worksheets_indices[packet_address_str]
                    file_status_reduced[filename]['worksheets'] = device_worksheets_reduced
                    data_stat['_deviceinfo']['file_status'] = file_status
                    data_stat['_deviceinfo']['file_status_reduced'] = file_status_reduced
                    dataqueue.put(data_stat)

                # Write data
                if True:
                    try:
                        data['t']
                    except:
                        data['t'] = data['_redvypr']['t']

                    try:
                        numpacket = data['_redvypr']['numpacket']
                    except:
                        numpacket = -1

                    datapacket = data_packets.Datapacket(data)
                    datakeys = datapacket.datakeys(expand=config['datakey_expansionlevel'],return_type='list')
                    #print('datakeys',datakeys)
                    lineindex = row_firstdata + device_worksheets_indices[packet_address_str]['numline']
                    # Write numpacket
                    device_worksheets[packet_address_str].write(lineindex, colindex_numpacket, numpacket)
                    # Write time
                    datakeys.remove('t')
                    datakeys.insert(0,'t')
                    datatime = datetime.datetime.fromtimestamp(data['t'])
                    device_worksheets[packet_address_str].write_datetime(lineindex, colindex_time, datatime,formats['date'])
                    # Write data in datakeys
                    for datakey in datakeys:
                        raddress_datakey = redvypr_address.RedvyprAddress(data, datakey=datakey)
                        # Get metadata
                        if deviceinfo_all is not None:
                            datakey_unit = write_metadata(workbook, all_worksheets, datakey, data, deviceinfo_all, device_info, config)
                        else:
                            #print('No metadata to check for')
                            datakey_unit = None

                        if (datakey == 't') and (datakey_unit is None):
                            datakey_unit = 'unix time'

                        try:
                            colindex = device_worksheets_indices[packet_address_str]['colindex'][datakey]
                        except:
                            device_worksheets_indices[packet_address_str]['datakeys'].append(datakey)
                            colindex = len(device_worksheets_indices[packet_address_str]['datakeys']) - 1 + coloffset
                            device_worksheets_indices[packet_address_str]['colindex'][datakey] = colindex
                            header_rows = [(row_host,raddress_datakey.hostname,'hostname')]
                            header_rows.append((row_uuid, raddress_datakey.uuid,'uuid'))
                            header_rows.append((row_device, raddress_datakey.device,'device'))
                            header_rows.append((row_publisher, raddress_datakey.publisher,'publisher'))
                            header_rows.append((row_packetid, raddress_datakey.packetid,'packetid'))
                            header_rows.append((row_datakey, datakey,'datakey'))
                            for header_row in header_rows:
                                device_worksheets[packet_address_str].write(header_row[0],colindex,header_row[1],
                                                                            all_worksheets['header_format'])
                                device_worksheets[packet_address_str].write(header_row[0], 0, header_row[2],
                                                                            all_worksheets['header_format'])


                            #device_worksheets[packet_address_str].write(row_datakey,colindex,datakey,all_worksheets['header_format'])


                        if datakey_unit is not None:
                            device_worksheets[packet_address_str].write(row_dataunit, colindex, datakey_unit,all_worksheets['header_format'])
                        else:
                            datakey_unit_tmp = ''
                            device_worksheets[packet_address_str].write(row_dataunit, colindex, datakey_unit_tmp,
                                                                        all_worksheets['header_format'])
                        #print('Will write data from {} to column {} and line {}'.format(packet_address_str, colindex,lineindex))
                        datawrite = datapacket[datakey]
                        if not(isinstance(datawrite,str)) and not(isinstance(datawrite,int)) and not(isinstance(datawrite,float)):
                            #print('Datatype {} not supported, converting data to str'.format(str(type(datawrite))))
                            datawrite = str(datawrite)

                        device_worksheets[packet_address_str].write(lineindex, colindex, datawrite)

                    device_worksheets_indices[packet_address_str]['numline'] += 1
                    numline = device_worksheets_indices[packet_address_str]['numline']
                    numkeys = len(device_worksheets_indices[packet_address_str]['datakeys'])
                    worksheet_tmp = device_worksheets_indices[packet_address_str]['worksheet']
                    device_worksheets_reduced[packet_address_str] = "worksheet: {}, numkeys: {}, numlines: {}".format(
                        worksheet_tmp, numkeys, numline)
                    #size = sys.getsizeof(workbook)
                    packets_written += 1
                    #print('Size:',size)

                # Send statistics
                if ((time.time() - tupdate) > config['dt_update']):
                    tupdate = time.time()
                    data_stat = {'_deviceinfo': {}}
                    data_stat['_deviceinfo']['filename'] = filename
                    data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
                    data_stat['_deviceinfo']['bytes_written'] = bytes_written
                    data_stat['_deviceinfo']['packets_written'] = packets_written
                    file_status[filename]['worksheets'] = device_worksheets_indices
                    data_stat['_deviceinfo']['file_status'] = file_status
                    data_stat['_deviceinfo']['file_status_reduced'] = file_status_reduced
                    dataqueue.put(data_stat)

            except:
                logger_start.debug('Could not write data',exc_info=True)
                #logger.exception(e)
                #logger.debug(funcname + ':Exception:' + str(e))
                # print(data)

        if True: # Check if a new file should be created, close the old one and write the header
            file_age = tcheck - tfile
            FLAG_TIME = (dtnews > 0) and (file_age >= dtnews)
            FLAG_SIZE = (sizenewb > 0) and (bytes_written >= sizenewb)
            if FLAG_TIME or FLAG_SIZE or (FLAG_RUN == False):
                # Autofit
                #print('Autofit')
                if True:
                    try:
                        worksheet_summary.autofit()
                    except:
                        logger_start.info(funcname + 'Could not autofit summary',exc_info=True)
                    for w in device_worksheets:
                        try:
                            device_worksheets[w].autofit()
                        except:
                            logger_start.info(funcname + 'Could not autofit {}'.format(w), exc_info=True)
                # Make the Excel time column wider, autofit does not work properly here
                #device_worksheets[w].set_column(colindex_time, colindex_time, 25)
                workbook.close()
                data_stat = {'_deviceinfo': {}}
                data_stat['_deviceinfo']['filename'] = filename
                data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
                data_stat['_deviceinfo']['closed'] = time.time()
                data_stat['_deviceinfo']['bytes_written'] = bytes_written
                data_stat['_deviceinfo']['packets_written'] = packets_written
                dataqueue.put(data_stat)
                if FLAG_RUN:
                    tfile = tcheck
                    bytes_written = 0
                    packets_written = 0
                    #bytes_written_total = 0
                    #packets_written_total = 0
                    device_worksheets = {}  # The worksheets for the devices
                    device_worksheets_reduced = {}  # The worksheets for the devices
                    device_worksheets_indices = {}
                    numworksheet = 0
                    [workbook, filename, formats] = create_logfile(config, count, all_worksheets)
                    worksheet_summary = all_worksheets['summary']
                    data_stat = {'_deviceinfo': {}}
                    data_stat['_deviceinfo']['filename'] = filename
                    data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
                    data_stat['_deviceinfo']['created'] = time.time()
                    data_stat['_deviceinfo']['bytes_written'] = bytes_written
                    data_stat['_deviceinfo']['packets_written'] = packets_written
                    dataqueue.put(data_stat)




class Device(RedvyprDevice):
    """
    xlsxwriter device
    """

    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)

    def thread_start(self, *args,**kwargs):
        """
        Custom thread start that clear the queue if config wants to and send a deviceinfo into the datainqueue

        Parameters
        ----------
        args
        kwargs

        Returns
        -------

        """
        funcname = __name__ + '.thread_start():'
        self.logger.debug(funcname)
        compacket = self.redvypr.get_metadata_commandpacket()
        # Let the thread start, it will clear the queue
        super().thread_start(*args,**kwargs)
        self.datainqueue.put(compacket)


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
        #print('Hallo,device config',device.config)
        self.device   = device
        self.redvypr  = device.redvypr
        self.label    = QtWidgets.QLabel("xlsx logger setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')
        self.config_widgets= [] # A list of all widgets that can only be used of the device is not started yet
        # Input output widget
        self.inlabel  = QtWidgets.QLabel("Input")
        self.inlist   = QtWidgets.QListWidget()
        #
        self.adddeviceinbtn   = QtWidgets.QPushButton("Subscribe")
        self.adddeviceinbtn.clicked.connect(self.con_clicked)
        self.adddeviceinbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        # The output widgets
        self.outlabel        = QtWidgets.QLabel("Logfile")
        self.outfilename     = QtWidgets.QLineEdit()
        # Checkboxes
        self.prefix_check    = QtWidgets.QCheckBox('Prefix')
        self.date_check      = QtWidgets.QCheckBox('Date/Time')
        self.count_check     = QtWidgets.QCheckBox('Counter')
        self.postfix_check   = QtWidgets.QCheckBox('Postfix')
        self.extension_check = QtWidgets.QCheckBox('Extension')

        try:
            filename = self.device.custom_config['filename']
        except:
            filename = ''

        self.outfilename.setText(filename)
        
        self.folderbtn   = QtWidgets.QPushButton("Folder")
        self.config_widgets.append(self.folderbtn)
        self.folderbtn.clicked.connect(self.get_datafolder)
        
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
        self.dt_newfile.setToolTip('Create a new file every N seconds.\nFilename is "filenamebase"_yyyymmdd_HHMMSS_count."ext".\nUse 0 to disable feature.')
        try:
            self.dt_newfile.setText(str(self.device.custom_config['dt_newfile']))
        except Exception as e:
            self.dt_newfile.setText('0')
            
        # Delta t for new file
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
        self.size_newfile = edit
        self.size_newfile.setToolTip('Create a new file if N bytes of RAM are used.\nFilename is "filenamebase"_yyyymmdd_HHMMSS_count."ext".\nUse 0 to disable feature.')
        try:
            self.size_newfile.setText(str(self.device.custom_config.size_newfile))
        except Exception as e:
            self.size_newfile.setText('0')
            
        self.newfiletimecombo = QtWidgets.QComboBox()
        times = typing.get_args(self.device.custom_config.model_fields['dt_newfile_unit'].annotation)
        timeunit = self.device.custom_config.dt_newfile_unit
        for t in times:
            self.newfiletimecombo.addItem(t)

        index = self.newfiletimecombo.findText(timeunit)
        self.newfiletimecombo.setCurrentIndex(index)
        #self.newfiletimecombo.addItem('None')
        #self.newfiletimecombo.addItem('seconds')
        #self.newfiletimecombo.addItem('hours')
        #self.newfiletimecombo.addItem('days')
        #self.newfiletimecombo.setCurrentIndex(1)
            
        self.newfilesizecombo = QtWidgets.QComboBox()
        self.newfilesizecombo.addItem('None')
        self.newfilesizecombo.addItem('bytes')
        self.newfilesizecombo.addItem('kB')
        self.newfilesizecombo.addItem('MB')
        self.newfilesizecombo.setCurrentIndex(3)
        
        sizelabel = QtWidgets.QLabel('New file after')
         # File change layout
        self.newfilewidget = QtWidgets.QWidget()
        self.newfilelayout = QtWidgets.QFormLayout(self.newfilewidget)
        self.newfilelayout.addRow(sizelabel)
        self.newfilelayout.addRow(self.dt_newfile,self.newfiletimecombo)
        self.newfilelayout.addRow(self.size_newfile,self.newfilesizecombo)
        
        # Filenamelayout
        self.folder_text = QtWidgets.QLineEdit('')
        self.extension_text = QtWidgets.QLineEdit('redvypr_raw')
        self.prefix_text = QtWidgets.QLineEdit('')
        self.date_text = QtWidgets.QLineEdit('%Y-%m-%d_%H%M%S')
        self.count_text = QtWidgets.QLineEdit('04d')
        self.postfix_text = QtWidgets.QLineEdit('')

        self.prefix_check = QtWidgets.QCheckBox('Prefix')
        self.date_check = QtWidgets.QCheckBox('Date/Time')
        self.count_check = QtWidgets.QCheckBox('Counter')
        self.postfix_check = QtWidgets.QCheckBox('Postfix')
        self.extension_check = QtWidgets.QCheckBox('Extension')
        # The outwidget
        self.outwidget = QtWidgets.QWidget()
        self.outlayout = QtWidgets.QGridLayout(self.outwidget)
        # Datafolder lineedit
        self.outlayout.addWidget(self.folderbtn, 0, 0)
        self.outlayout.addWidget(self.folder_text, 0, 1,1,4)
        # Checkboxes
        self.outlayout.addWidget(self.prefix_check, 1, 0)
        self.outlayout.addWidget(self.date_check, 1, 1)
        self.outlayout.addWidget(self.count_check, 1, 2)
        self.outlayout.addWidget(self.postfix_check, 1, 3)
        self.outlayout.addWidget(self.extension_check, 1, 4)

        self.outlayout.addWidget(self.prefix_text, 2, 0)
        self.outlayout.addWidget(self.date_text, 2, 1)
        self.outlayout.addWidget(self.count_text, 2, 2)
        self.outlayout.addWidget(self.postfix_text, 2, 3)
        self.outlayout.addWidget(self.extension_text, 2, 4)

        self.outlayout.addWidget(self.newfilewidget,4,0,1,4)

        #self.outlayout.addStretch(1)
            
        layout.addWidget(self.label,0,0,1,2)
        #layout.addWidget(self.inlabel,1,0)
        #layout.addWidget(self.inlist,2,0)
        layout.addWidget(self.outlabel,1,0)
        layout.addWidget(self.outwidget,2,0)
        layout.addWidget(self.adddeviceinbtn, 5, 0)
        layout.addWidget(self.startbtn,6,0)

        self.config_to_widgets()
        self.connect_widget_signals()
        # Connect the signals that notify a change of the connection
        self.device.redvypr.device_status_changed_signal.connect(self.update_device_list)
        #self.redvypr.devices_connected.connect
        self.device.subscription_changed_signal.connect(self.update_device_list)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)


    def connect_widget_signals(self,connect=True):
        """
        Connects the signals of the widgets such that an update of the config is done

        Args:
            connect:

        Returns:

        """
        funcname = self.__class__.__name__ + '.connect_widget_signals():'
        logger.debug(funcname)
        if(connect):
            self.prefix_check.stateChanged.connect(self.update_device_config)
            self.postfix_check.stateChanged.connect(self.update_device_config)
            self.date_check.stateChanged.connect(self.update_device_config)
            self.count_check.stateChanged.connect(self.update_device_config)
            self.extension_check.stateChanged.connect(self.update_device_config)
            self.prefix_text.editingFinished.connect(self.update_device_config)
            self.postfix_text.editingFinished.connect(self.update_device_config)
            self.date_text.editingFinished.connect(self.update_device_config)
            self.count_text.editingFinished.connect(self.update_device_config)
            self.extension_text.editingFinished.connect(self.update_device_config)
            self.newfilesizecombo.currentIndexChanged.connect(self.update_device_config)
            self.newfiletimecombo.currentIndexChanged.connect(self.update_device_config)
        else:
            self.prefix_check.stateChanged.disconnect()
            self.postfix_check.stateChanged.disconnect()
            self.date_check.stateChanged.disconnect()
            self.count_check.stateChanged.disconnect()
            self.extension_check.stateChanged.disconnect()
            self.prefix_text.editingFinished.disconnect()
            self.postfix_text.editingFinished.disconnect()
            self.date_text.editingFinished.disconnect()
            self.count_text.editingFinished.disconnect()
            self.extension_text.editingFinished.disconnect()
            self.newfilesizecombo.currentIndexChanged.disconnect()
            self.newfiletimecombo.currentIndexChanged.disconnect()


    def get_datafolder(self):
        funcname = self.__class__.__name__ + '.get_datafolder():'
        logger.debug(funcname)
        retdata = QtWidgets.QFileDialog.getExistingDirectory(self,"Choose datafolder")
        #print('Datafolder',retdata)
        datafolder = retdata
        if datafolder:
            self.folder_text.setText(datafolder)
            
    def con_clicked(self):
        funcname = self.__class__.__name__ + '.con_clicked():'
        logger.debug(funcname)
        button = self.sender()
        if(button == self.adddeviceinbtn):
            self.connect.emit(self.device) # The connect signal is connected with connect_device that will open a subscribe/connect widget
            self.update_device_list()

    def update_datastream_table(self):
        """

        """
        # columns = ['Columnnr.', 'Datakey', 'Device', 'Format', 'Full Address String']
        funcname = self.__class__.__name__ + '.update_datastream_table():'
        logger.debug(funcname)
        datastreams_subscribed = self.device.get_subscribed_datastreams()
        logger.debug('datastreams subscribed {}'.format(datastreams_subscribed))
        self.datastreamtable.clear()
        self.datastreamtable.setRowCount(len(datastreams_subscribed))
        for i,d in enumerate(datastreams_subscribed):
            dadr = redvypr_address(d)
            item = QtWidgets.QTableWidgetItem(d)
            self.datastreamtable.setItem(i,4,item)

        self.datastreamtable.resizeColumnsToContents()

    def update_device_list(self):
        funcname = self.__class__.__name__ + '.update_device_list():'
        logger.debug(funcname)
        #print('Devices',devicestr_provider,devicestr_receiver)
        raddresses = self.device.get_subscribed_deviceaddresses()
        #print('Deviceaddresses',raddresses)
        self.inlist.clear()
        for raddr in raddresses:
            self.inlist.addItem(raddr.to_address_string())


    def config_to_widgets(self):
        """
        Updates the widgets according to the device config

        Returns:

        """
        funcname = self.__class__.__name__ + '.config_to_widgets():'
        logger.debug(funcname)

        config = self.device.custom_config
        #print('config',config)
        self.dt_newfile.setText(str(config.dt_newfile))
        for i in range(self.newfiletimecombo.count()):
            self.newfiletimecombo.setCurrentIndex(i)
            if(self.newfiletimecombo.currentText().lower() == config.dt_newfile_unit):
                break

        for i in range(self.newfilesizecombo.count()):
            self.newfilesizecombo.setCurrentIndex(i)
            if (self.newfilesizecombo.currentText().lower() == config.size_newfile_unit):
                break

        self.size_newfile.setText(str(config.size_newfile))

        if len(config.datafolder)>0:
            self.folder_text.setText(config.datafolder)
        # Update filename and checkboxes
        filename_all = []
        filename_all.append([config.fileextension,self.extension_text,self.extension_check])
        filename_all.append([config.fileprefix,self.prefix_text,self.prefix_check])
        filename_all.append([config.filepostfix,self.postfix_text,self.postfix_check])
        filename_all.append([config.filedateformat,self.date_text,self.date_check])
        filename_all.append([config.filecountformat,self.count_text,self.count_check])
        for i in range(len(filename_all)):
            widgets = filename_all[i]
            if(len(widgets[0])==0):
                widgets[2].setChecked(False)
                widgets[1].setText('')
            else:
                widgets[2].setChecked(True)
                widgets[1].setText(widgets[0])

    def widgets_to_config(self,config):
        """
        Reads the widgets and creates a config
        Returns:
            config: Config dictionary
        """
        funcname = self.__class__.__name__ + '.widgets_to_config():'
        logger.debug(funcname)
        config.dt_newfile = int(self.dt_newfile.text())
        config.dt_newfile_unit = self.newfiletimecombo.currentText()
        config.size_newfile = int(self.size_newfile.text())
        config.size_newfile_unit = self.newfilesizecombo.currentText()

        config.datafolder = self.folder_text.text()

        if(self.extension_check.isChecked()):
            config.fileextension = self.extension_text.text()
        else:
            config.fileextension = ''

        if(self.prefix_check.isChecked()):
            config.fileprefix = self.prefix_text.text()
        else:
            config.fileprefix = ''

        if(self.postfix_check.isChecked()):
            config.filepostfix = self.postfix_text.text()
        else:
            config.filepostfix = ''

        if(self.date_check.isChecked()):
            config.filedateformat = self.date_text.text()
        else:
            config.filedateformat = ''

        if(self.count_check.isChecked()):
            config.filecountformat = self.count_text.text()
        else:
            config.filecountformat = ''

        #print('Config',config)
        return config

    def update_device_config(self):
        """
        Updates the device config based on the widgets
        Returns:

        """
        funcname = self.__class__.__name__ + '.update_device_config():'
        logger.debug(funcname)
        self.widgets_to_config(self.device.custom_config)

    def start_clicked(self):
        funcname = self.__class__.__name__ + '.start_clicked():'
        logger.debug(funcname)
        button = self.sender()
        if button.isChecked():
            logger.debug(funcname + "button pressed")
            self.update_device_config()
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
        self.device = device
        layout          = QtWidgets.QVBoxLayout(self)
        hlayout         = QtWidgets.QHBoxLayout()
        self.filetable  = QtWidgets.QTableWidget()
        headers = ['Filename','Bytes written','Packets written','Date created','Date closed','Full filepath']
        self.filetable.setColumnCount(len(headers))
        self.filetable.setHorizontalHeaderLabels(headers)
        self.filetable.resizeColumnsToContents()
        self.filelab = QtWidgets.QLabel("File: ")
        self.byteslab = QtWidgets.QLabel("Bytes written: ")
        self.packetslab = QtWidgets.QLabel("Packets written: ")
        # Table that displays all datastreams and the format as it is written to the file
        self.deviceinfoQtree = redvypr.widgets.pydanticConfigWidget.dictQTreeWidget(dataname='file status', show_datatype=False)
        # Update layout
        updatelayout = QtWidgets.QHBoxLayout()
        self.update_auto = QtWidgets.QCheckBox('Autoupdate file status')
        self.update_auto.setChecked(True)
        updatelayout.addWidget(self.update_auto)
        self.update_show_all_files = QtWidgets.QRadioButton('Show all files')
        #self.update_show_all_files.setChecked(True)
        self.update_show_cur_file = QtWidgets.QRadioButton('Show current file')
        self.update_show_cur_file.setChecked(True)
        show_group=QtWidgets.QButtonGroup()
        show_group.addButton(self.update_show_all_files)
        show_group.addButton(self.update_show_cur_file)
        self.show_group = show_group
        updatelayout.addWidget(self.update_show_all_files)
        updatelayout.addWidget(self.update_show_cur_file)

        self.update_show_full = QtWidgets.QRadioButton('Show all information')
        #self.update_show_full.setChecked(True)
        self.update_show_red = QtWidgets.QRadioButton('Show reduced information')
        self.update_show_red.setChecked(True)
        showred_group = QtWidgets.QButtonGroup()
        showred_group.addButton(self.update_show_full)
        showred_group.addButton(self.update_show_red)
        self.showred_group = showred_group
        updatelayout.addWidget(self.update_show_full)
        updatelayout.addWidget(self.update_show_red)



        hlayout.addWidget(self.byteslab)
        hlayout.addWidget(self.packetslab)
        layout.addWidget(self.filelab)        
        layout.addLayout(hlayout)
        layout.addWidget(self.filetable)
        layout.addWidget(self.deviceinfoQtree)
        # Add update options
        layout.addLayout(updatelayout)
        #self.text.insertPlainText("hallo!")

    def update_qtreewidget(self, data):
        funcname = __name__ + '.update_qtreewidget()'
        logger.debug(funcname)
        if self.update_auto.isChecked():
            devinfo = data
            #devinfo = self.device.get_device_info(address=self.device.address_str)
            # devinfo = self.device.get_device_info()
            # print('Deviceinfo!!!!', devinfo)
            # print('__________')

            filename = devinfo['_deviceinfo']['filename']

            if self.update_show_red.isChecked():
                #print('Hallo show reduced is checked')
                file_status = devinfo['_deviceinfo']['file_status_reduced']
            else:
                #print('Hallo show full is checked')
                file_status = devinfo['_deviceinfo']['file_status']

            if self.update_show_cur_file.isChecked():
                #print('Hallo current file is checked')
                file_status = file_status[filename]
            else:
                #print('Hallo is not checked')
                pass


            # Update the qtree
            # https://stackoverflow.com/questions/9364754/remembering-scroll-value-of-a-qtreewidget-in-pyqt?rq=3
            bar = self.deviceinfoQtree.verticalScrollBar()
            yScroll = bar.value()
            self.deviceinfoQtree.reload_data(file_status)
            self.deviceinfoQtree.verticalScrollBar().setSliderPosition(yScroll)

    def update_data(self,data):
        funcname = __name__ + '.update()'
        try:
            data['_deviceinfo']
        except:
            return

        # Update qtree
        try:
            # Test if the file status has changed, if yes make an update
            file_status_tmp = data['_deviceinfo']['file_status']
            try:
                self.update_qtreewidget(data)
            except:
                logger.debug(funcname+ 'Qtreeupdate',exc_info=True)

        except Exception as e:
            #logger.debug(funcname, exc_info=True)
            pass

        try:
            #print('data',data)
            try:
                filename_table = self.filetable.item(0,0).text()
            except:
                filename_table = ''

            try:
                data['_deviceinfo']['filename']
                FLAG_FILEUPDATE = True
            except:
                FLAG_FILEUPDATE = False

            try:
                data['_deviceinfo']['csvcolumns']
                FLAG_CSVCOLUMNUPDATE = True
            except:
                FLAG_CSVCOLUMNUPDATE = False

            if FLAG_CSVCOLUMNUPDATE:
                #print('csv column update')
                csvcolumns = data['_deviceinfo']['csvcolumns']
                nrows = len(csvcolumns)
                self.datastreamtable.setRowCount(nrows)
                iaddr = self.datastreamtable_columns.index('Address')
                idatatype = self.datastreamtable_columns.index('Datatype')
                idatakey = self.datastreamtable_columns.index('Datakey')
                idevice = self.datastreamtable_columns.index('Device')
                iformat = self.datastreamtable_columns.index('Format')
                icolnr = self.datastreamtable_columns.index('Columnnr.')
                #self.datastreamtable_columns = ['Columnnr.', 'Datakey', 'Device', 'Datatype', 'Format', 'Address']

                for i,c in enumerate(csvcolumns):
                    item = QtWidgets.QTableWidgetItem(str(i))
                    self.datastreamtable.setItem(i, icolnr, item)

                    datatype = data['_deviceinfo']['header_datatype'][i]
                    item = QtWidgets.QTableWidgetItem(datatype)
                    self.datastreamtable.setItem(i, idatatype, item)

                    datakey = data['_deviceinfo']['header_datakeys'][i]
                    item = QtWidgets.QTableWidgetItem(datakey)
                    self.datastreamtable.setItem(i, idatakey, item)

                    dataformat = data['_deviceinfo']['csvformat'][i]
                    item = QtWidgets.QTableWidgetItem(dataformat)
                    self.datastreamtable.setItem(i, iformat, item)

                    datadevice = data['_deviceinfo']['header_device'][i]
                    item = QtWidgets.QTableWidgetItem(datadevice)
                    self.datastreamtable.setItem(i, idevice, item)

                    item = QtWidgets.QTableWidgetItem(str(c))
                    self.datastreamtable.setItem(i, iaddr, item)

                self.datastreamtable.resizeColumnsToContents()
            if FLAG_FILEUPDATE:
                #print('Filename table',filename_table,data['_deviceinfo']['filename'])
                try:
                    tclose = datetime.datetime.fromtimestamp(data['_deviceinfo']['closed']).strftime(
                        '%d-%m-%Y %H:%M:%S')
                    item = QtWidgets.QTableWidgetItem(tclose)
                    self.filetable.setItem(0, 4, item)
                except:
                    pass

                if filename_table != data['_deviceinfo']['filename']:
                    self.filetable.insertRow(0)
                    try:
                        #headers = ['Filename', 'Date created', 'Bytes written', 'Date closed']
                        item = QtWidgets.QTableWidgetItem(data['_deviceinfo']['filename'])
                        self.filetable.setItem(0,0,item)
                        item = QtWidgets.QTableWidgetItem(data['_deviceinfo']['filename_full'])
                        self.filetable.setItem(0, 5, item)
                        tcreate = datetime.datetime.fromtimestamp(data['_deviceinfo']['created']).strftime('%d-%m-%Y %H:%M:%S')
                        item = QtWidgets.QTableWidgetItem(tcreate)
                        self.filetable.setItem(0, 3, item)
                    except Exception as e:
                        logger.exception(e)

                item = QtWidgets.QTableWidgetItem(str(data['_deviceinfo']['bytes_written']))
                self.filetable.setItem(0, 1, item)
                item = QtWidgets.QTableWidgetItem(str(data['_deviceinfo']['packets_written']))
                self.filetable.setItem(0, 2, item)
                self.filetable.resizeColumnsToContents()
                self.filelab.setText("File: {:s}".format(data['_deviceinfo']['filename']))
                self.byteslab.setText("Bytes written: {:d}".format(data['_deviceinfo']['bytes_written']))
                self.packetslab.setText("Packets written: {:d}".format(data['_deviceinfo']['packets_written']))
        except Exception as e:
            logger.exception(e)


        #self.text.insertPlainText(str(data['_deviceinfo']['data']))
        
