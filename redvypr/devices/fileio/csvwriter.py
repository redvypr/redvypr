"""

Logger that writes csv files (comma separated value)

Configuration
-------------
- separator
- format of the data

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
import pydantic
import typing
from redvypr.device import RedvyprDevice
import redvypr.data_packets as data_packets
import redvypr.redvypr_address as redvypr_address
import redvypr.gui

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.csvwriter')
logger.setLevel(logging.INFO)

redvypr_devicemodule = True
class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = "Saves subscribed datastreams in a comma separated value (csv) file"
    gui_tablabel_display: str = 'csv logging status'
    gui_icon: str = 'fa5s.file-csv'


class csv_datastream_strformat(pydantic.BaseModel):
    str_type: str = pydantic.Field(default='"{:s}"')
    int_type: str = pydantic.Field(default='{}')
    float_type: str = pydantic.Field(default='{}')
    dict_type: str = pydantic.Field(default='{}')


class csv_datastream_config(pydantic.BaseModel):
    address: str = pydantic.Field(default='*', type='redvypr_address',description='The redvypr address string of the datastream')
    address_found: str = pydantic.Field(default='', description='The redvypr address string of the datastream that is found for the column')
    mode_address_found: typing.Literal['copy','first fit exact','first fit address format'] = pydantic.Field(default='first fit exact')
    strformat: csv_datastream_strformat = pydantic.Field(default=csv_datastream_strformat())
    comment: str= pydantic.Field(default='', description='Comment')
    unit: str = pydantic.Field(default='', description='Unit of the data')

class DeviceCustomConfig(pydantic.BaseModel):
    separator: str = pydantic.Field(default=',',description='Separator between the columns')
    datastreams: typing.Optional[typing.List[csv_datastream_config]] = pydantic.Field(default=[])
    dt_sync: int = pydantic.Field(default=5,description='Time after which an open file is synced on disk')
    dt_waitbeforewrite: int = pydantic.Field(default=2,description='Time after which the first write to a file is done, this is useful to collect datastreams')
    dt_newfile: int = pydantic.Field(default=300,description='Time after which a new file is created')
    dt_newfile_unit: typing.Literal['none','seconds','hours','days'] = pydantic.Field(default='seconds')
    dt_update:int = pydantic.Field(default=2,description='Time after which an upate is sent to the gui')
    clearqueue: bool = pydantic.Field(default=True,
                                      description='Flag if the buffer of the subscribed queue should be emptied before start')
    size_newfile:int = pydantic.Field(default=0,description='Size after which a new file is created')
    size_newfile_unit: typing.Literal['none','bytes','kB','MB'] = pydantic.Field(default='bytes')
    datafolder:str = pydantic.Field(default='./',description='Folder the data is saved to')
    fileextension:str= pydantic.Field(default='csv',description='File extension, if empty not used')
    fileprefix:str= pydantic.Field(default='redvypr',description='If empty not used')
    filepostfix:str= pydantic.Field(default='csvlogger',description='If empty not used')
    filedateformat:str= pydantic.Field(default='%Y-%m-%d_%H%M%S',description='Dateformat used in the filename, must be understood by datetime.strftime')
    filecountformat:str= pydantic.Field(default='04',description='Format of the counter. Add zero if trailing zeros are wished, followed by number of digits. 04 becomes {:04d}')
    filegzipformat:str= pydantic.Field(default='',description='If empty, no compression done')


def create_logfile(config,count=0):
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

    if (len(config['filegzipformat']) > 0):
        filename += '.' + config['filegzipformat']
        FLAG_GZIP = True
    else:
        FLAG_GZIP = False

    logger.info(funcname + ' Will create a new file: {:s}'.format(filename))
    if FLAG_GZIP:
        try:
            f = gzip.open(filename,'wt')
            logger.debug(funcname + ' Opened file: {:s}'.format(filename))
        except Exception as e:
            logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
            return None
    else:
        try:
            f = open(filename,'w+')
            logger.debug(funcname + ' Opened file: {:s}'.format(filename))
        except Exception as e:
            logger.warning(funcname + ' Error opening file:' + filename + ':' + str(e))
            return None
       
    return [f,filename]

def start(device_info, config, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening writing:')
    #print('Config',config)
    if config['clearqueue']:
        while (datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
            except:
                break
    numline = 0
    header_datatype = []
    header_datakeys = []
    header_device   = []
    header_host     = []
    header_ip       = []
    header_uuid     = []
    header_address  = []

    header_data = [header_datakeys,header_device,header_host,header_ip,header_uuid]
    data_write_to_file = [] # List of columns to be written to file
    csvcolumns = []  # List of datastreams in each column
    csvformat  = []  # List of datastreams in each column, LEGACY?
    csvformatdict = {}  # Dictionary of all datastreams and their formats
    count = 0
    if True:
        try:
            dtneworig  = config['dt_newfile']
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
            logger.info(funcname + ' Will create new file every {:d} {:s}.'.format(config['dt_newfile'],config['dt_newfile_unit']))
        except Exception as e:
            logger.exception(e)
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
            logger.exception(e)
            sizenewb = 0  # Size in bytes
            
            
    try:
        config['dt_sync']
    except:
        config['dt_sync'] = 5

    bytes_written = 0
    packets_written = 0
    bytes_written_total = 0
    packets_written_total = 0

    [f,filename] = create_logfile(config,count)
    flag_header_written = False
    data_stat = {'_deviceinfo': {}}
    data_stat['_deviceinfo']['filename'] = filename
    data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
    data_stat['_deviceinfo']['created'] = time.time()
    data_stat['_deviceinfo']['bytes_written'] = bytes_written
    data_stat['_deviceinfo']['packets_written'] = packets_written
    dataqueue.put(data_stat)
    count += 1
    #statistics = data_packets.create_data_statistic_dict()
    if(f == None):
       return None
    
    tfile = time.time() # Save the time the file was created
    tflush = time.time() # Save the time the file was created
    tupdate = time.time() # Save the time for the update timing
    FLAG_RUN = True
    while FLAG_RUN:
        tcheck      = time.time()
        # Flush file on regular basis
        if ((time.time() - tflush) > config['dt_sync']):
            f.flush()
            os.fsync(f.fileno())
            tflush = time.time()

        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
                if (data is not None):
                    [command,comdata] = data_packets.check_for_command(data, thread_uuid=device_info['thread_uuid'], add_data=True)
                    #logger.debug('Got a command: {:s}'.format(str(data)))
                    if (command is not None):
                        if(command == 'stop'):
                            logger.debug('Stop command')
                            FLAG_RUN = False
                            break
                        elif (command == 'csvcolumns'):
                            logger.debug(funcname + ' Got csvcolumns command')
                            #print('COMDATA')
                            #print('Comdata',comdata)
                            #csvcolumns = data['csvcolumns']
                            continue


                #statistics = data_packets.do_data_statistics(data,statistics)
                datastreams = data_packets.Datapacket(data).datastreams()
                #print('Hallo data',data)
                #print('Got datastreams',datastreams)
                data_write = ['']*len(csvcolumns)
                FLAG_WRITE_PACKET = False
                if len(datastreams) > 0:
                    #datastreams.sort() # Sort the datastreams alphabetically
                    #print('Datastreams',datastreams)
                    data_time = data['_redvypr']['t']
                    data_numpacket = data['_redvypr']['numpacket']
                    # Check if the datastreams are in the list already
                    data_fill = []
                    streamdata = None
                    for ind_dstream, dstream in enumerate(config['datastreams']):
                        data_fill.append(None)
                        for dstr in datastreams:
                            if dstream['address_found'] == '': # Not assigned yet
                                #print('Trying to assign')
                                raddr = redvypr.RedvyprAddress(dstream['address'])
                                if dstr in raddr: # Found something
                                    #print('Found ', dstr, 'in', raddr)
                                    if dstream['mode_address_found'] == 'copy':
                                        dstream['address_found'] = raddr.address_str
                                    if dstream['mode_address_found'] == 'first fit exact':
                                        dstream['address_found'] = dstr.address_str
                                    else:
                                        raise ValueError('Mode "{}" not implented yet'.format(dstream['mode_address_found']))
                                    #print('Got an address',dstream)
                                    streamdata = dstr.get_data(data)
                                    data_fill[ind_dstream] = streamdata
                                    FLAG_WRITE_PACKET = True
                                    #print('Got streamdata',streamdata)
                                    break
                            else: # Get the data
                                streamdata = redvypr.RedvyprAddress(dstream['address_found']).get_data(data) # returns None if not fitting
                                if streamdata is not None:
                                    #print('Adding data',streamdata)
                                    #print('Index dstream',ind_dstream)
                                    data_fill[ind_dstream] = streamdata
                                    FLAG_WRITE_PACKET = True
                                    break

                    # If data to write was found
                    if FLAG_WRITE_PACKET:
                        data_write_to_file.append([data_time, data_fill, data_numpacket])

                # Send statistics
                if ((time.time() - tupdate) > config['dt_update']):
                    tupdate = time.time()
                    data_stat = {'_deviceinfo': {}}
                    data_stat['_deviceinfo']['filename'] = filename
                    data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
                    data_stat['_deviceinfo']['bytes_written'] = bytes_written
                    data_stat['_deviceinfo']['packets_written'] = packets_written
                    dataqueue.put(data_stat)

            except Exception as e:
                logger.exception(e)
                logger.debug(funcname + ':Exception:' + str(e))
                # print(data)

        # Write data to file if available
        if ((time.time() - tfile) > config['dt_waitbeforewrite'])  or (FLAG_RUN == False):
            if flag_header_written == False:
                # Create header
                flag_header_written = True
                header_lines = []
                header_lines.append(['N-Data', 'Packetnum', 'Packettime unix', 'Packettime str'])
                header_lines.append(['Address subscribe', '', '', ''])
                header_lines.append(['Address found', '', '', ''])
                header_lines.append(['Unit', '#', 'seconds since 1970-01-01 00:00:00', 'YYYY-MM-DD HH:MM:SS.000'])
                header_lines.append(['Comment', '', '', ''])
                hstr = 'Redvypr {} csvlogger'.format(redvypr.version)
                hstr += '\n'
                for ihline, hline in enumerate(header_lines):
                    hstr += hline[0] + config['separator'] + hline[1] + config['separator']
                    hstr += hline[2] + config['separator'] + hline[3] + config['separator']
                    for i, d in enumerate(config['datastreams']):
                        if ihline == 0:
                            hstr += "Datastream_{:02d}".format(i) + config['separator']
                        elif ihline == 1:
                            hstr += d['address'] + config['separator']
                        elif ihline == 2:
                            hstr += d['address_found'] + config['separator']
                        elif ihline == 3:
                            hstr += d['unit'] + config['separator']
                        elif ihline == 4:
                            hstr += d['comment'] + config['separator']

                    hstr = hstr[:-len(config['separator'])] + '\n'

                f.write(hstr)
                bytes_written += len(hstr)

            if len(data_write_to_file) > 0:
                #logger.debug('Writing {:d} lines to file now'.format(len(data_write_to_file)))
                for l in data_write_to_file:
                    numline += 1
                    data_time_unix = l[0]  # Time
                    data_time_str = datetime.datetime.fromtimestamp(data_time_unix, tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    data_line = l[1]  # Data
                    data_numpacket = l[2]  # Numpacket
                    # Convert data to str
                    datastr_all = str(numline) + config['separator']
                    datastr_all += str(data_numpacket) + config['separator']
                    datastr_all += str(data_time_unix) + config['separator']
                    datastr_all += str(data_time_str) + config['separator']
                    for index, streamdata in enumerate(data_line):
                        if streamdata is None:
                            streamdata = ''

                        typestr = type(streamdata).__name__ + '_type'
                        #print('Index', typestr, index, streamdata)
                        try:
                            strformat = config['datastreams'][index]['strformat'][typestr]
                        except:
                            #logger.debug('Could not get strformat for {}'.format(index), exc_info=False)
                            strformat = '{}'

                        if ":s" in strformat:  # Convert to str if str format is choosen, this is useful for datatypes different of str (i.e. bytes)
                            streamdata = str(streamdata)

                        # Here errors in conversion could be treated more carefully
                        dtxt = strformat.format(streamdata)
                        # Check if the separator or a newline is within the data string
                        if (config['separator'] in dtxt) or ('\n' in dtxt):
                            dtxt = '"' + dtxt + '"'
                        datastr_all += dtxt + config['separator']

                    datastr_all = datastr_all[:-len(config['separator'])]
                    datastr_all += '\n'

                    f.write(datastr_all)
                    bytes_written += len(datastr_all)
                    packets_written += 1
                    bytes_written_total += len(datastr_all)
                    packets_written_total += 1
                    #print('Written', datastr_all)

                data_write_to_file = []

        if True: # Check if a new file should be created, close the old one and write the header
            file_age = tcheck - tfile
            FLAG_TIME = (dtnews > 0) and (file_age >= dtnews)
            FLAG_SIZE = (sizenewb > 0) and (bytes_written >= sizenewb)
            if (FLAG_TIME or FLAG_SIZE) or (FLAG_RUN == False):
                logger.debug(funcname + 'Closing file ...')
                f.close()
                data_stat = {'_deviceinfo': {}}
                data_stat['_deviceinfo']['filename'] = filename
                data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
                data_stat['_deviceinfo']['closed'] = time.time()
                data_stat['_deviceinfo']['bytes_written'] = bytes_written
                data_stat['_deviceinfo']['packets_written'] = packets_written
                dataqueue.put(data_stat)
                if FLAG_RUN:
                    [f, filename] = create_logfile(config, count)
                    flag_header_written = False
                    count += 1
                    #statistics = data_packets.create_data_statistic_dict()
                    tfile = tcheck
                    bytes_written = 0
                    packets_written = 0
                    data_stat = {'_deviceinfo': {}}
                    data_stat['_deviceinfo']['filename'] = filename
                    data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
                    data_stat['_deviceinfo']['created'] = time.time()
                    data_stat['_deviceinfo']['bytes_written'] = bytes_written
                    data_stat['_deviceinfo']['packets_written'] = packets_written
                    dataqueue.put(data_stat)














class Device(RedvyprDevice):
    """
    csvlogger device
    """

    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)

        self.redvypr.device_status_changed_signal.connect(self.update_datastreamlist)
        self.csvcolumns = []       # List with the columns, containing dictionaries with the format
        self.csvcolumns_info = []  # List with the columns, containing dictionaries with the format

        for dconf in self.custom_config.datastreams:
            address = dconf.address
            #print('Subscribing dconf',dconf)
            self.subscribe_address(address)
            #self.subscribe_address(dconf)
            #print('Datastream conf',dconf)

    def add_datastream(self, datastream, column=-1):
        """
        Adds a datastream to the writer

        Parameters
        ----------
        datastream
        column

        Returns
        -------

        """
        funcname = __name__ + '.add_datastream():'
        logger.debug(funcname)
        datastream_addr = datastream
        datastream_str = datastream.address_str
        metadata = self.redvypr.get_metadata(datastream_addr)
        #print('Metadata', metadata)
        #print('-------')
        try:
            unit = metadata['unit']
        except:
            unit = ''
        newdatastream = csv_datastream_config(address=datastream_str, unit=unit)
        # print('Hallo datastream choosen',datastream_str)
        # print('Hallo bewdatastream', newdatastream)
        # Get the column number
        colnumber = column
        # print('Colnumber',colnumber)
        if colnumber == -1:
            self.custom_config.datastreams.append(newdatastream)
        else:
            datastreamindex = int(colnumber)
            self.custom_config.datastreams.insert(datastreamindex, newdatastream)

        for dconf in self.custom_config.datastreams:
            address = dconf.address
            # print('Subscribing dconf',dconf)
            self.subscribe_address(address)

    def create_csvcolumns(self):
        funcname = __name__ + 'create_csvcolumns():'
        logger.debug(funcname)
        flag_new_datastream = False
        datastreams_subscribed = self.get_subscribed_datastreams()
        #print('datastreams subscribed', datastreams_subscribed)
        for i, d in enumerate(datastreams_subscribed):
            cdict = {'addr':d}
            if d in self.csvcolumns:
                pass
            else:
                self.csvcolumns.append(d)
                self.csvcolumns_info.append(cdict)
                flag_new_datastream = True

        if flag_new_datastream:
            logger.debug(funcname + 'New csvcolumns')
            self.thread_command('csvcolumns', data={'csvcolumns':self.csvcolumns})



    def update_datastreamlist(self):
        funcname = __name__ + 'update_datastreamlist()'
        logger.debug(funcname)
        self.create_csvcolumns()




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
        self.device   = device
        self.redvypr  = device.redvypr
        self.label    = QtWidgets.QLabel("Csvlogger setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')
        self.config_widgets= [] # A list of all widgets that can only be used of the device is not started yet
        # Input output widget
        self.inlabel  = QtWidgets.QLabel("Input")
        self.inlist   = QtWidgets.QListWidget()
        # csv formattable
        self.csvformattable = QtWidgets.QTableWidget()
        csvheader = self.csvformattable.horizontalHeader()
        csvheader.setSectionsMovable(True)
        csvheader.sectionMoved.connect(self.__columnOrderChanged__)
        self.csvformattable.cellChanged.connect(self.cellChanged_csvformattable)
        self.populate_csvformattable()

        #
        #self.adddatastreambtn = QtWidgets.QPushButton("Add datastream")
        #self.adddatastreambtn.clicked.connect(self.addDatastreamClicked)
        self.adddatastreamsbtn = QtWidgets.QPushButton("Add datastreams")
        self.adddatastreamsbtn.clicked.connect(self.addDatastreamsClicked)
        #self.moddatastreambtn = QtWidgets.QPushButton("Modify datastream")
        #self.moddatastreambtn.clicked.connect(self.modDatastreamClicked)
        self.remdatastreambtn = QtWidgets.QPushButton("Remove datastream")
        self.remdatastreambtn.clicked.connect(self.__removeClicked__)
        #
        #self.adddeviceinbtn   = QtWidgets.QPushButton("Subscribe")
        #self.adddeviceinbtn.clicked.connect(self.con_clicked)
        #self.adddeviceinbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
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
        self.size_newfile.setToolTip('Create a new file every N bytes.\nFilename is "filenamebase"_yyyymmdd_HHMMSS_count."ext".\nUse 0 to disable feature.')
        try:
            self.size_newfile.setText(str(self.device.custom_config['size_newfile']))
        except Exception as e:
            self.size_newfile.setText('0')
            
        self.newfiletimecombo = QtWidgets.QComboBox()
        self.newfiletimecombo.addItem('None')
        self.newfiletimecombo.addItem('seconds')
        self.newfiletimecombo.addItem('hours')
        self.newfiletimecombo.addItem('days')
        self.newfiletimecombo.setCurrentIndex(1)
            
        self.newfilesizecombo = QtWidgets.QComboBox()
        self.newfilesizecombo.addItem('None')
        self.newfilesizecombo.addItem('bytes')
        self.newfilesizecombo.addItem('kB')
        self.newfilesizecombo.addItem('MB')
        self.newfilesizecombo.setCurrentIndex(2)
        
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
        self.gzip_text = QtWidgets.QLineEdit('gz')

        self.prefix_check = QtWidgets.QCheckBox('Prefix')
        self.date_check = QtWidgets.QCheckBox('Date/Time')
        self.count_check = QtWidgets.QCheckBox('Counter')
        self.postfix_check = QtWidgets.QCheckBox('Postfix')
        self.extension_check = QtWidgets.QCheckBox('Extension')
        self.gzip_check = QtWidgets.QCheckBox('gzip')
        # The outwidget
        self.outwidget = QtWidgets.QWidget()
        self.outlayout = QtWidgets.QGridLayout(self.outwidget)
        # Datafolder lineedit
        self.outlayout.addWidget(self.folderbtn, 0, 0)
        self.outlayout.addWidget(self.folder_text, 0, 1,1,3)
        # Checkboxes
        self.outlayout.addWidget(self.prefix_check, 1, 0)
        self.outlayout.addWidget(self.date_check, 1, 1)
        self.outlayout.addWidget(self.count_check, 1, 2)
        self.outlayout.addWidget(self.postfix_check, 1, 3)
        self.outlayout.addWidget(self.extension_check, 1, 4)
        self.outlayout.addWidget(self.gzip_check, 1, 5)

        self.outlayout.addWidget(self.prefix_text, 2, 0)
        self.outlayout.addWidget(self.date_text, 2, 1)
        self.outlayout.addWidget(self.count_text, 2, 2)
        self.outlayout.addWidget(self.postfix_text, 2, 3)
        self.outlayout.addWidget(self.extension_text, 2, 4)
        self.outlayout.addWidget(self.gzip_text, 2, 5)


        self.outlayout.addWidget(self.newfilewidget,4,0,1,4)

        self.config_widgets.append(self.csvformattable)
        #self.config_widgets.append(self.adddatastreambtn)
        self.config_widgets.append(self.adddatastreamsbtn)
        self.config_widgets.append(self.remdatastreambtn)
        self.config_widgets.append(self.outlabel)
        #self.config_widgets.append(self.adddeviceinbtn)
        self.config_widgets.append(self.outwidget)

        layout.addWidget(self.label,0,0,1,2)
        #layout.addWidget(self.inlabel,1,0)
        #layout.addWidget(self.inlist,2,0)
        #layout.addWidget(self.adddatastreambtn, 3, 0, 1, 1)
        layout.addWidget(self.adddatastreamsbtn, 3, 0, 1, 1)
        layout.addWidget(self.remdatastreambtn, 3, 3, 1, 1)
        layout.addWidget(self.csvformattable, 4, 0, 1, 4)
        layout.addWidget(self.outlabel,1,0)
        layout.addWidget(self.outwidget,2,0)
        #layout.addWidget(self.adddeviceinbtn, 5, 0)
        layout.addWidget(self.startbtn,5,0,1,4)

        self.config_to_widgets()
        self.connect_widget_signals()
        # Connect the signals that notify a change of the connection
        self.device.redvypr.device_status_changed_signal.connect(self.update_device_list)
        #self.redvypr.devices_connected.connect
        self.device.subscription_changed_signal.connect(self.update_device_list)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def __removeClicked__(self):
        funcname = __name__ + '.__removeClicked__():'
        logger.debug(funcname)
        #indexes = self.csvformattable.selectionModel().selectedRows()
        indexes = self.csvformattable.selectionModel().selectedColumns()
        #print('indexes,',indexes)
        datastreamInd = []
        datastreamsRem = []
        for index in sorted(indexes):
            #print('Row %d is selected',index.column())
            indtmp = index.column() - self.ncols_add
            if indtmp >= 0:
                datastreamInd.append(indtmp)
                datastreamsRem.append(self.device.custom_config.datastreams[indtmp])

        for drem in datastreamsRem:
            self.device.custom_config.datastreams.remove(drem)

        self.populate_csvformattable()
        #print('Datastreamind',datastreamInd)

    def __columnOrderChanged__(self,logIndex,oldVisInd,newVisInd):
        #print('hallo',a,b,c)
        datastreamIndold = oldVisInd - self.ncols_add
        datastreamIndnew = newVisInd - self.ncols_add
        datastreamIndlog = logIndex - self.ncols_add
        if datastreamIndlog > 0:
            # Swap the items
            #print('Swapping')
            tmp = self.device.custom_config.datastreams[datastreamIndnew]
            self.device.custom_config.datastreams[datastreamIndnew] = self.device.custom_config.datastreams[datastreamIndold]
            self.device.custom_config.datastreams[datastreamIndold] = tmp
        else:
            logger.warning('Time & Description columns cannot be changed')
        # Redraw the table
        self.csvformattable.clear()
        self.csvformattable.horizontalHeader().restoreState(self._headerstate)
        self.populate_csvformattable()

    def modDatastreamClicked(self):
        funcname = __name__ + '.modDatastreamClicked():'
        logger.debug(funcname)

    def addDatastreamClicked(self):
        """
        Function to add one datastream

        Returns
        -------

        """
        funcname = __name__ + '.addDatastreamClicked():'
        logger.debug(funcname)
        self.dstreamwidget = redvypr.gui.DatastreamWidget(self.device.redvypr, closeAfterApply=False)
        self.dstreamwidget.apply.connect(self.__datastream_choosen__)
        self.dstreamwidget.layout.removeWidget(self.dstreamwidget.buttondone)
        label = QtWidgets.QLabel('Add at column number')
        self.dstreamwidget.comboCol = QtWidgets.QComboBox()
        self.dstreamwidget.comboCol.addItem('end')
        for i in range(len(self.device.custom_config.datastreams)):
            colindex = self.ncols_add + 1 + i
            self.dstreamwidget.comboCol.addItem(str(colindex))

        self.dstreamwidget.layout.addWidget(label)
        self.dstreamwidget.layout.addWidget(self.dstreamwidget.comboCol)
        self.dstreamwidget.layout.addWidget(self.dstreamwidget.buttondone)
        self.dstreamwidget.show()

    def addDatastreamsClicked(self):
        """
        Function to add several datastreams at once
        Returns
        -------

        """
        funcname = __name__ + '.addDatastreamClicked():'
        logger.debug(funcname)
        self.dstreamswidget = redvypr.gui.datastreamsWidget(self.device.redvypr, closeAfterApply=True)
        self.dstreamswidget.apply.connect(self.__datastreams_choosen__)
        self.dstreamswidget.show()

    def __datastreams_choosen__(self, datastreamsdict):
        for addr in datastreamsdict['datastreams_address']:
            self.device.add_datastream(addr)

        self.populate_csvformattable()

    def __datastream_choosen__(self,datastreamdict):
        funcname = __name__ + '.__datastream_choosen__():'
        logger.debug(funcname)
        datastream_addr = datastreamdict['datastream_address']
        datastream_str = datastreamdict['datastream_str']
        metadata = self.device.redvypr.get_metadata(datastream_addr)
        #print('Metadata',metadata)
        #print('-------')
        try:
            unit = metadata['unit']
        except:
            unit = ''
        newdatastream = csv_datastream_config(address=datastream_str,unit=unit)
        #print('Hallo datastream choosen',datastream_str)
        #print('Hallo bewdatastream', newdatastream)
        # Get the column number
        colnumber = self.dstreamwidget.comboCol.currentText()
        #print('Colnumber',colnumber)
        if colnumber == 'end':
            self.device.custom_config.datastreams.append(newdatastream)
        else:
            datastreamindex = int(colnumber) - (self.ncols_add + 1)
            self.device.custom_config.datastreams.insert(datastreamindex, newdatastream)

        # update the column numbers
        self.dstreamwidget.comboCol.clear()
        self.dstreamwidget.comboCol.addItem('end')
        for i in range(len(self.device.custom_config.datastreams)):
            colindex = self.ncols_add + 1 + i
            self.dstreamwidget.comboCol.addItem(str(colindex))

        self.populate_csvformattable()

    def cellChanged_csvformattable(self,row,col):
        funcname = __name__ + '.cellChanged_csvformattable():'
        logger.debug(funcname + ' Cell changed row {} col {}'.format(row,col))
        item = self.csvformattable.item(row,col)
        if row == self.row_field_comment:
            indexdatastream = col - self.ncols_add
            comment = str(item.text())
            logger.debug(funcname + ' Comment changed to {}'.format(comment))
            self.device.custom_config.datastreams[indexdatastream].comment = comment
            self.populate_csvformattable()
        elif row == self.row_field_unit:
            indexdatastream = col - self.ncols_add
            unit = str(item.text())
            logger.debug(funcname + ' Unit changed to {}'.format(unit))
            self.device.custom_config.datastreams[indexdatastream].unit = unit
            self.populate_csvformattable()
        else:
            try:
                newformat = item.text()
                dstrf = item.__dstrformat__
                f = item.__strtype__
                #print('Hallo',dstrf,f,newformat)
                setattr(dstrf,f,newformat)
                self.populate_csvformattable()
                #print('Config', self.device.custom_config.model_dump())
            except:
                logger.debug('Could not change format',exc_info=True)

    def populate_csvformattable(self):
        funcname = self.__class__.__name__ + '.populate_csvformattable():'
        logger.debug(funcname)
        self.csvformattable.cellChanged.disconnect(self.cellChanged_csvformattable)
        self.ncols_add = 2 # number of additional rows
        ncols = len(self.device.custom_config.datastreams) + self.ncols_add
        self._headerstate = self.csvformattable.horizontalHeader().saveState()
        self.csvformattable.clear()
        self.csvformattable.setColumnCount(ncols)
        formatfields = list(csv_datastream_strformat().model_fields.keys())
        nformattypes = len(formatfields)
        nrows1 = 6
        nrows = nrows1 + nformattypes
        self.csvformattable.setRowCount(nrows)

        # Add format fields
        for i,f in enumerate(formatfields):
            f_item = QtWidgets.QTableWidgetItem(f)
            self.csvformattable.setItem(nrows1 + i, 0, f_item)

        n0_item = QtWidgets.QTableWidgetItem('Description')
        n1_item = QtWidgets.QTableWidgetItem('Address subscribe')
        n2_item = QtWidgets.QTableWidgetItem('Address found')
        n3_item = QtWidgets.QTableWidgetItem('Unit')
        self.row_field_unit = 3
        n4_item = QtWidgets.QTableWidgetItem('Comment')
        self.row_field_comment = 4
        n5_item = QtWidgets.QTableWidgetItem('Field format')
        self.row_field_format = 5
        self.csvformattable.setItem(0, 0, n0_item)
        self.csvformattable.setItem(1, 0, n1_item)
        self.csvformattable.setItem(2, 0, n2_item)
        self.csvformattable.setItem(self.row_field_unit, 0, n3_item)
        self.csvformattable.setItem(self.row_field_comment, 0, n4_item)
        self.csvformattable.setItem(self.row_field_format, 0, n5_item)

        t_item = QtWidgets.QTableWidgetItem('Packet time')
        tu_item = QtWidgets.QTableWidgetItem('seconds since 1970-01-01 00:00:00')
        self.csvformattable.setItem(0, 1, t_item)
        self.csvformattable.setItem(3, 1, tu_item)
        for i,d in enumerate(self.device.custom_config.datastreams):
            #print('d',d)
            ds_item = QtWidgets.QTableWidgetItem("Datastream_{:02d}".format(i))
            addr_item = QtWidgets.QTableWidgetItem(str(d.address))
            addrs_item = QtWidgets.QTableWidgetItem(str(d.address_found))
            self.csvformattable.setItem(0, self.ncols_add + i, ds_item)
            self.csvformattable.setItem(1, self.ncols_add + i, addr_item)
            self.csvformattable.setItem(2, self.ncols_add + i, addrs_item)
            comment_item = QtWidgets.QTableWidgetItem(str(d.comment))
            self.csvformattable.setItem(self.row_field_comment, self.ncols_add + i, comment_item)
            unit_item = QtWidgets.QTableWidgetItem(str(d.unit))
            self.csvformattable.setItem(self.row_field_unit, self.ncols_add + i, unit_item)

            for j, f in enumerate(formatfields):
                strf = getattr(d.strformat,f)
                f_item = QtWidgets.QTableWidgetItem(strf)
                f_item.setData(QtCore.Qt.UserRole,d.strformat)
                f_item.setData(QtCore.Qt.UserRole+1, f)
                f_item.__dstrformat__ = d.strformat
                f_item.__strformat__ = strf
                f_item.__strtype__ = f
                self.csvformattable.setItem(nrows1 + j, self.ncols_add + i, f_item)

        #self.csvformattable.resizeColumnsToContent()
        noneditColor = QtGui.QColor(200, 200, 200)
        for i in range(nrows):
            for j in range(0,2):
                item = self.csvformattable.item(i,j)
                if item is None:
                    item = QtWidgets.QTableWidgetItem('')
                    self.csvformattable.setItem(i, j, item)

                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                item.setBackground(noneditColor)

            if (i < 3) or (i == self.row_field_format): # Non editable rows is not editable
                for j in range(1,ncols):
                    item = self.csvformattable.item(i, j)
                    if item is None:
                        item = QtWidgets.QTableWidgetItem('')
                        self.csvformattable.setItem(i, j, item)

                    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                    item.setBackground(noneditColor)


        self.csvformattable.resizeColumnsToContents()
        self.csvformattable.cellChanged.connect(self.cellChanged_csvformattable)
    def populate_dataformattable(self):
        """
        Populates the dataformattable with information self.config['datatypeformat']
        """
        funcname = self.__class__.__name__ + '.populate_dataformattable():'
        logger.debug(funcname)
        #print('Test', self.device.custom_config['datatypeformat'])
        columns = []
        nrows = 0
        for dtype in self.device.custom_config['datatypeformat'].keys():
            #print('d',dtype)
            d = self.device.custom_config['datatypeformat'][dtype]
            columns.append('Subscription for {:s}'.format(dtype))
            columns.append('Format for {:s}'.format(dtype))

            nrows = max([len(d),nrows])

        #print('Columns',columns)
        ncols = len(columns)
        self.dataformattable.setColumnCount(ncols)
        self.dataformattable.setRowCount(nrows)
        self.dataformattable.setHorizontalHeaderLabels(columns)
        # And now the data itself
        for i,dtype in enumerate(self.device.custom_config['datatypeformat'].keys()):
            #print('d',dtype)
            d = self.device.custom_config['datatypeformat'][dtype]
            for irow,dsub in enumerate(d):
                #print('dsub',dsub)
                item0 = QtWidgets.QTableWidgetItem(str(dsub[0]))
                item1 = QtWidgets.QTableWidgetItem(str(dsub[1]))
                self.dataformattable.setItem(irow, i * 2,item0)
                self.dataformattable.setItem(irow, i * 2 + 1, item1)

        self.dataformattable.resizeColumnToContents()



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
            self.gzip_check.stateChanged.connect(self.update_device_config)
        else:
            self.gzip_check.stateChanged.disconnect()
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


    def update_device_list(self):
        funcname = self.__class__.__name__ + '.update_device_list():'
        logger.debug(funcname)
        #print('Devices',devicestr_provider,devicestr_receiver)
        raddresses = self.device.get_subscribed_deviceaddresses()
        #print('Deviceaddresses',raddresses)
        self.inlist.clear()
        for raddr in raddresses:
            self.inlist.addItem(raddr.address_str)


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
        filename_all.append([config.fileextension, self.extension_text, self.extension_check])
        filename_all.append([config.fileprefix, self.prefix_text, self.prefix_check])
        filename_all.append([config.filepostfix, self.postfix_text, self.postfix_check])
        filename_all.append([config.filedateformat, self.date_text, self.date_check])
        filename_all.append([config.filecountformat, self.count_text, self.count_check])
        filename_all.append([config.filegzipformat, self.gzip_text, self.gzip_check])
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

        if (self.gzip_check.isChecked()):
            config.filegzipformat = self.gzip_text.text()
        else:
            config.filegzipformat = ''


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
    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()
        layout          = QtWidgets.QVBoxLayout(self)
        hlayout         = QtWidgets.QHBoxLayout()
        self.filetable  = QtWidgets.QTableWidget()
        headers = ['Filename','Bytes written','Packets written','Date created','Date closed','Full filepath']
        self.filetable.setColumnCount(len(headers))
        self.filetable.setHorizontalHeaderLabels(headers)
        self.filetable.resizeColumnsToContents()
        self.filelab= QtWidgets.QLabel("File: ")
        self.byteslab   = QtWidgets.QLabel("Bytes written: ")
        self.packetslab = QtWidgets.QLabel("Packets written: ")

        hlayout.addWidget(self.byteslab)
        hlayout.addWidget(self.packetslab)
        layout.addWidget(self.filelab)        
        layout.addLayout(hlayout)
        layout.addWidget(self.filetable)

    def update_data(self,data):
        try:
            funcname = __name__ + '.update()'
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
        
