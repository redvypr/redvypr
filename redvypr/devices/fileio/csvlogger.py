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
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import logging
import sys
import yaml
import copy
import gzip
import os
from redvypr.device import redvypr_device
import redvypr.data_packets as data_packets

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('csvlogger')
logger.setLevel(logging.DEBUG)

description = "Saves subscribed datastreams in a comma separated value (csv) file"
config_template = {}
config_template['name']              = 'csvlogger'
config_template['dt_sync']           = {'type':'int','default':5,'description':'Time after which an open file is synced on disk'}
config_template['dt_waitbeforewrite']= {'type':'int','default':10,'description':'Time after which the first write to a file is done, this is useful to collect datastreams'}
config_template['dt_newfile']        = {'type':'int','default':300,'description':'Time after which a new file is created'}
config_template['dt_newfile_unit']   = {'type':'str','default':'seconds','options':['seconds','hours','days']}
config_template['dt_update']         = {'type':'int','default':2,'description':'Time after which an upate is sent to the gui'}
config_template['size_newfile']      = {'type':'int','default':0,'description':'Size after which a new file is created'}
config_template['size_newfile_unit'] = {'type':'str','default':'bytes','options':['bytes','kB','MB']}
config_template['datafolder']        = {'type':'str','default':'./','description':'Folder the data is saved to'}
config_template['fileextension']     = {'type':'str','default':'csv','description':'File extension, if empty not used'}
config_template['fileprefix']        = {'type':'str','default':'redvypr','description':'If empty not used'}
config_template['filepostfix']       = {'type':'str','default':'csvlogger','description':'If empty not used'}
config_template['filedateformat']    = {'type':'str','default':'%Y-%m-%d_%H%M%S','description':'Dateformat used in the filename, must be understood by datetime.strftime'}
config_template['filecountformat']   = {'type':'str','default':'04','description':'Format of the counter. Add zero if trailing zeros are wished, followed by number of digits. 04 becomes {:04d}'}
config_template['filegzipformat']    = {'type':'str','default':'','description':'If empty, no compression done'}
config_template['datastreams']       = {'type':'list','default':['§HF.*§','§.*§'],'description':'List of all datastreams to be saved'}
config_template['separator']         = {'type':'str','default':',','description':'Separator between the columns'}
config_template['datatypeformat']    = {'type':'dict','default':{'str':[['*','"{:s}"']],'float':[['t/*','{:06.6f}'],['*','{:f}']],'int':[['*','{:d}']],'bytes':[['*','"{:s}"']]},'description':'Format description for the different datatypes and subscriptions'}
config_template['redvypr_device']    = {}
config_template['redvypr_device']['publishes']   = False
config_template['redvypr_device']['subscribes']  = True
config_template['redvypr_device']['description'] = description
config_template['redvypr_device']['gui_tablabel_init'] = 'Setup'
config_template['redvypr_device']['gui_tablabel_display'] = 'File status'
redvypr_devicemodule = True

def get_strformat(config,data,redvypr_addr,csvformatdict):
    funcname = 'get_strformat'
    #logger.debug(funcname)
    typestr = type(data).__name__
    #print('Typestr',typestr)
    try:
        csvformatdict[typestr]
    except:
        csvformatdict[typestr] = {}

    try:
        csvformatdict[typestr][redvypr_addr]
        FLAG_FINDFORMAT = False
    except:
        csvformatdict[typestr][redvypr_addr] = ''
        FLAG_FINDFORMAT = True

    if FLAG_FINDFORMAT:
        # Get all subscriptions for the datatype and search for the valid one
        subscriptions = config['datatypeformat'][typestr]
        for sub in subscriptions:
            saddr = data_packets.redvypr_address(sub[0])
            if redvypr_addr in saddr:
                csvformatdict[typestr][redvypr_addr] = sub[1]
                break

    #print('strformat',csvformatdict)
    try:
        formatstr = csvformatdict[typestr][redvypr_addr]
    except:
        formatstr = '{:s}'
    return formatstr



def create_logfile(config,count=0):
    funcname = __name__ + '.create_logfile():'
    logger.debug(funcname)

    filename = ''
    if len(config['datafolder']) > 0:
        if os.path.isdir(config['datafolder']):
            filename += config['datafolder']
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
    print('Config',config)

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
            dtunit     = config['dt_newfile_unit']
            if(dtunit.lower() == 'seconds'):
                dtfac = 1.0
            elif(dtunit.lower() == 'hours'):
                dtfac = 3600.0
            elif(dtunit.lower() == 'days'):
                dtfac = 86400.0
            else:
                dtfac = 0
                
            dtnews     = dtneworig * dtfac
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
    data_stat = {'_deviceinfo': {}}
    data_stat['_deviceinfo']['filename'] = filename
    data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
    data_stat['_deviceinfo']['created'] = time.time()
    data_stat['_deviceinfo']['bytes_written'] = bytes_written
    data_stat['_deviceinfo']['packets_written'] = packets_written
    dataqueue.put(data_stat)
    count += 1
    statistics = data_packets.create_data_statistic_dict()
    if(f == None):
       return None
    

    
    tfile           = time.time() # Save the time the file was created
    tflush          = time.time() # Save the time the file was created
    tupdate         = time.time() # Save the time for the update timing
    FLAG_RUN = True
    while FLAG_RUN:
        tcheck      = time.time()
        # Write data to file if available
        if (time.time() - tfile) > config['dt_waitbeforewrite']:
            if len(data_write_to_file) > 0:
                #logger.debug('Writing {:d} lines to file now'.format(len(data_write_to_file)))
                for l in data_write_to_file:
                    data_time = l[0] # Time
                    data_line = l[1] # Data
                    # Convert data to str
                    datastr_all = str(data_time) + config['separator']
                    for index,streamdata in enumerate(data_line):
                        redvypr_addr = header_address[index]
                        strformat = get_strformat(config,streamdata,redvypr_addr,csvformatdict)
                        if ":s" in strformat: # Convert to str if str format is choosen, this is useful for datatypes different of str (i.e. bytes)
                            streamdata = str(streamdata)
                        # TODO, here errors in conversion should be treated more carefully
                        dtxt = strformat.format(streamdata)
                        datastr_all += dtxt + config['separator']

                    datastr_all = datastr_all[:-len(config['separator'])]
                    datastr_all += '\n'

                    f.write(datastr_all)
                    bytes_written += len(datastr_all)
                    packets_written += 1
                    bytes_written_total += len(datastr_all)
                    packets_written_total += 1

                data_write_to_file = []

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


                statistics = data_packets.do_data_statistics(data,statistics)
                datastreams = data_packets.get_datastreams_from_data(data)
                data_write = ['']*len(csvcolumns)
                FLAG_WRITE_PACKET = False
                if datastreams is not None:
                    datastreams.sort() # Sort the datastreams alphabetically
                    #print('Datastreams',datastreams)
                    data_time = data['_redvypr']['t']
                    # Check if the datastreams are in the list already
                    for dstr in datastreams:
                        streamdata = data_packets.get_data(dstr,data)
                        if dstr in csvcolumns: # Check if datastream in already in csvcolumns
                            FLAG_WRITE_PACKET = True
                        else: # If not, check if it should be added
                            daddr = data_packets.redvypr_address(dstr)
                            for dconf in config['datastreams']:
                                #print('Hallo',dconf)
                                dconfaddr = data_packets.redvypr_address(dconf)
                                if dstr in dconfaddr: # Found a match, will add it to the file
                                    FLAG_WRITE_PACKET = True
                                    #print('Adding datastream to file',dstr)
                                    header_datakeys.append(daddr.datakey)
                                    header_device.append(daddr.devicename)
                                    header_host.append(daddr.hostname)
                                    header_ip.append(daddr.addr)
                                    header_address.append(dstr)
                                    header_uuid.append(daddr.uuid)
                                    csvcolumns.append(dstr)
                                    # The datatype and the format
                                    header_datatype.append(type(streamdata).__name__)
                                    strformat = get_strformat(config, streamdata, dstr, csvformatdict)
                                    csvformat.append(strformat)
                                    data_write.append('') # Add another field
                                    # Make an update about the change of the csvcolumns
                                    data_stat = {'_deviceinfo': {}}
                                    data_stat['_deviceinfo']['csvcolumns'] = csvcolumns
                                    data_stat['_deviceinfo']['csvformat'] = csvformat
                                    data_stat['_deviceinfo']['header_datakeys'] = header_datakeys
                                    data_stat['_deviceinfo']['header_device']   = header_device
                                    data_stat['_deviceinfo']['header_host']     = header_host
                                    data_stat['_deviceinfo']['header_ip']       = header_ip
                                    data_stat['_deviceinfo']['header_datatype'] = header_datatype

                                    dataqueue.put(data_stat)

                        #print('csvcolumns',csvcolumns)
                        index = csvcolumns.index(dstr)
                        #print('Index',index)
                        if index is not None:
                            #print('dstr',dstr)
                            #print('data',data)
                            #print('streamdata',streamdata)
                            data_write[index] = streamdata
                            #print('saving data',dtxt)

                if FLAG_WRITE_PACKET:
                    data_write_to_file.append([data_time, data_write])

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

        if True: # Check if a new file should be created, close the old one and write the header
            file_age = tcheck - tfile
            FLAG_TIME = (dtnews > 0) and (file_age >= dtnews)
            FLAG_SIZE = (sizenewb > 0) and (bytes_written >= sizenewb)
            if (FLAG_TIME or FLAG_SIZE) or (FLAG_RUN == False):
                hstr = ''
                for header_tmp in header_data:
                    # Write the header information
                    hstr += 'unix time' + config['separator']
                    for h in header_tmp:
                        hstr += '"' + h + '"' + config['separator']

                    hstr = hstr[:-len(config['separator'])] + '\n'
                #print('Writing hstr', hstr)
                f.seek(0)
                lines = f.read() # read old content
                f.seek(0)
                #print('Writing hstr', hstr)
                f.write(hstr)
                #print('Writing original data', lines)
                f.write(lines)
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
                    count += 1
                    statistics = data_packets.create_data_statistic_dict()
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














class Device(redvypr_device):
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

        for dconf in self.config['datastreams']:
            #print('Subscribing')
            self.subscribe_address(dconf)
            #print('Datastream conf',dconf)

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
    connect      = QtCore.pyqtSignal(redvypr_device) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
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
        #
        self.dataformattable = QtWidgets.QTableWidget()
        # Populate the table
        self.populate_dataformattable()
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
            filename = self.device.config['filename']
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
            self.dt_newfile.setText(str(self.device.config['dt_newfile']))
        except Exception as e:
            self.dt_newfile.setText('0')
            
        # Delta t for new file
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
        self.size_newfile = edit
        self.size_newfile.setToolTip('Create a new file every N bytes.\nFilename is "filenamebase"_yyyymmdd_HHMMSS_count."ext".\nUse 0 to disable feature.')
        try:
            self.size_newfile.setText(str(self.device.config['size_newfile']))
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
        self.newfilesizecombo.addItem('Bytes')
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

        #self.outlayout.addStretch(1)
            
        layout.addWidget(self.label,0,0,1,2)
        layout.addWidget(self.inlabel,1,0)         
        layout.addWidget(self.inlist,2,0)
        layout.addWidget(self.dataformattable, 3, 0,1,4)
        layout.addWidget(self.outlabel,1,1)
        layout.addWidget(self.outwidget,2,2,1,1)
        layout.addWidget(self.adddeviceinbtn, 4, 0)
        layout.addWidget(self.startbtn,4,1,1,2)

        self.config_to_widgets()
        self.connect_widget_signals()
        # Connect the signals that notify a change of the connection
        self.device.redvypr.device_status_changed_signal.connect(self.update_device_list)
        #self.redvypr.devices_connected.connect
        self.device.subscription_changed_signal.connect(self.update_device_list)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def populate_dataformattable(self):
        """
        Populates the dataformattable with information self.config['datatypeformat']
        """
        funcname = self.__class__.__name__ + '.populate_dataformattable():'
        logger.debug(funcname)
        print('Hallo',self.device.config['datatypeformat'])
        columns = []
        nrows = 0
        for dtype in self.device.config['datatypeformat'].keys():
            print('d',dtype)
            d = self.device.config['datatypeformat'][dtype]
            columns.append('Subscription for {:s}'.format(dtype))
            columns.append('Format for {:s}'.format(dtype))

            nrows = max([len(d),nrows])

        print('Columns',columns)
        ncols = len(columns)
        self.dataformattable.setColumnCount(ncols)
        self.dataformattable.setRowCount(nrows)
        self.dataformattable.setHorizontalHeaderLabels(columns)
        # And now the data itself
        for i,dtype in enumerate(self.device.config['datatypeformat'].keys()):
            print('d',dtype)
            d = self.device.config['datatypeformat'][dtype]
            for irow,dsub in enumerate(d):
                print('dsub',dsub)
                item0 = QtWidgets.QTableWidgetItem(str(dsub[0]))
                item1 = QtWidgets.QTableWidgetItem(str(dsub[1]))
                self.dataformattable.setItem(irow, i * 2,item0)
                self.dataformattable.setItem(irow, i * 2 + 1, item1)

        self.dataformattable.resizeColumnsToContents()



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

    def update_datastream_table(self):
        """

        """
        # columns = ['Columnnr.', 'Datakey', 'Device', 'Format', 'Full Address String']
        funcname = self.__class__.__name__ + '.update_datastream_table():'
        print(funcname)
        datastreams_subscribed = self.device.get_subscribed_datastreams()
        print('datastreams subscribed',datastreams_subscribed)
        self.datastreamtable.clear()
        self.datastreamtable.setRowCount(len(datastreams_subscribed))
        for i,d in enumerate(datastreams_subscribed):
            dadr = data_packets.redvypr_address(d)
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
            self.inlist.addItem(raddr.address_str)


    def config_to_widgets(self):
        """
        Updates the widgets according to the device config

        Returns:

        """
        funcname = self.__class__.__name__ + '.config_to_widgets():'
        logger.debug(funcname)

        config = self.device.config
        print('config',config)
        self.dt_newfile.setText(str(config['dt_newfile'].data))
        for i in range(self.newfiletimecombo.count()):
            self.newfiletimecombo.setCurrentIndex(i)
            if(self.newfiletimecombo.currentText().lower() == config['dt_newfile_unit'].data):
                break

        for i in range(self.newfilesizecombo.count()):
            self.newfilesizecombo.setCurrentIndex(i)
            if (self.newfilesizecombo.currentText().lower() == config['size_newfile_unit'].data):
                break

        self.size_newfile.setText(str(config['size_newfile'].data))

        if len(config['datafolder'].data)>0:
            self.folder_text.setText(config['datafolder'].data)
        # Update filename and checkboxes
        filename_all = []
        filename_all.append([config['fileextension'].data,self.extension_text,self.extension_check])
        filename_all.append([config['fileprefix'].data,self.prefix_text,self.prefix_check])
        filename_all.append([config['filepostfix'].data,self.postfix_text,self.postfix_check])
        filename_all.append([config['filedateformat'].data,self.date_text,self.date_check])
        filename_all.append([config['filecountformat'].data,self.count_text,self.count_check])
        filename_all.append([config['filegzipformat'].data, self.gzip_text, self.gzip_check])
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
        config['dt_newfile'].data        = int(self.dt_newfile.text())
        config['dt_newfile_unit'].data   = self.newfiletimecombo.currentText()
        config['size_newfile'].data      = int(self.size_newfile.text())
        config['size_newfile_unit'].data = self.newfilesizecombo.currentText()

        if(self.extension_check.isChecked()):
            config['fileextension'].data = self.extension_text.text()
        else:
            config['fileextension'].data = ''

        if(self.prefix_check.isChecked()):
            config['fileprefix'].data = self.prefix_text.text()
        else:
            config['fileprefix'].data = ''

        if(self.postfix_check.isChecked()):
            config['filepostfix'].data = self.postfix_text.text()
        else:
            config['filepostfix'].data = ''

        if(self.date_check.isChecked()):
            config['filedateformat'].data    = self.date_text.text()
        else:
            config['filedateformat'].data = ''

        if(self.count_check.isChecked()):
            config['filecountformat'].data = self.count_text.text()
        else:
            config['filecountformat'].data = ''

        if (self.gzip_check.isChecked()):
            config['filegzipformat'].data = self.gzip_text.text()
        else:
            config['filegzipformat'].data = ''


        print('Config',config)
        return config

    def update_device_config(self):
        """
        Updates the device config based on the widgets
        Returns:

        """
        funcname = self.__class__.__name__ + '.update_device_config():'
        logger.debug(funcname)
        self.widgets_to_config(self.device.config)

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
        # Table that displays all datastreams and the format as it is written to the file
        self.datastreamtable = QtWidgets.QTableWidget()
        self.datastreamtable_columns = ['Columnnr.', 'Datakey', 'Device', 'Datatype', 'Format', 'Address']

        # self.datastreamtable.setRowCount(len(rows))
        self.datastreamtable.setColumnCount(len(self.datastreamtable_columns))
        self.datastreamtable.setHorizontalHeaderLabels(self.datastreamtable_columns)
        self.datastreamtable.resizeColumnsToContents()
        self.datastreamtable.verticalHeader().hide()


        hlayout.addWidget(self.byteslab)
        hlayout.addWidget(self.packetslab)
        layout.addWidget(self.filelab)        
        layout.addLayout(hlayout)
        layout.addWidget(self.filetable)
        layout.addWidget(self.datastreamtable)
        #self.text.insertPlainText("hallo!")        

    def update(self,data):
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
        
