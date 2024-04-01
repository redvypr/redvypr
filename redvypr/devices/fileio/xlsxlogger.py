"""

Logger that writes xlsx files

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
import xlsxwriter
import pympler.asizeof
import pydantic
import typing
from redvypr.device import redvypr_device
import redvypr.data_packets as data_packets
import redvypr.redvypr_address as redvypr_address
import redvypr.gui

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('xlsxlogger')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True
class device_base_config(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = "Saves subscribed devices in a xlsx file"
    gui_tablabel_display: str = 'xlsx logging status'

class device_config(pydantic.BaseModel):
    dt_sync: int = pydantic.Field(default=5,description='Time after which an open file is synced on disk')
    dt_newfile: int = pydantic.Field(default=300,description='Time after which a new file is created')
    dt_newfile_unit: typing.Literal['none','seconds','hours','days'] = pydantic.Field(default='seconds')
    dt_update:int = pydantic.Field(default=2,description='Time after which an upate is sent to the gui')
    size_newfile:int = pydantic.Field(default=5,description='Size after which a new file is created')
    size_newfile_unit: typing.Literal['none','bytes','kB','MB'] = pydantic.Field(default='MB')
    datafolder:str = pydantic.Field(default='./',description='Folder the data is saved to')
    fileextension:str= pydantic.Field(default='xlsx',description='File extension, if empty not used')
    fileprefix:str= pydantic.Field(default='redvypr',description='If empty not used')
    filepostfix:str= pydantic.Field(default='xlsxlogger',description='If empty not used')
    filedateformat:str= pydantic.Field(default='%Y-%m-%d_%H%M%S',description='Dateformat used in the filename, must be understood by datetime.strftime')
    filecountformat:str= pydantic.Field(default='04',description='Format of the counter. Add zero if trailing zeros are wished, followed by number of digits. 04 becomes {:04d}')

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

    logger.info(funcname + ' Will create a new file: {:s}'.format(filename))

    # Create a workbook and add a worksheet.
    workbook = xlsxwriter.Workbook(filename)
    date_format = workbook.add_format({'num_format': 'yyyy-mm-dd HH:MM:SS.000'})
    formats = {}
    formats['date'] = date_format
    return [workbook,filename,formats]

def start(device_info, config, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening writing:')
    print('Config',config)

    data_write_to_file = [] # List of columns to be written to file
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
    device_worksheets = {} # The workbooks for the devices
    device_worksheets_indices = {}
    numworksheet = 0

    [workbook,filename,formats] = create_logfile(config,count)
    worksheet_summary = workbook.add_worksheet('summary')
    redvypr_version_str = 'redvypr {}'.format(redvypr.version)
    worksheet_summary.write(0,0,redvypr_version_str)
    data_stat = {'_deviceinfo': {}}
    data_stat['_deviceinfo']['filename'] = filename
    data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
    data_stat['_deviceinfo']['created'] = time.time()
    data_stat['_deviceinfo']['bytes_written'] = bytes_written
    data_stat['_deviceinfo']['packets_written'] = packets_written
    dataqueue.put(data_stat)
    count += 1

    tfile           = time.time() # Save the time the file was created
    tflush          = time.time() # Save the time the file was created
    tupdate         = time.time() # Save the time for the update timing
    FLAG_RUN = True
    while FLAG_RUN:
        tcheck      = time.time()


        # Flush file on regular basis
        if ((time.time() - tflush) > config['dt_sync']):
            print('Flushing, not implemented (yet)')
            bytes_written = pympler.asizeof.asizeof(workbook)
            print('Bytes written',bytes_written)
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

                #statistics = data_packets.do_data_statistics(data,statistics)
                packet_address = redvypr.redvypr_address(data)
                address_format = '/h/p/d/'
                packet_address_str = packet_address.get_str(address_format)
                print('Address',packet_address)
                row_datakey = 1
                row_firstdata = 3
                coloffset = 1
                try:
                    device_worksheets[packet_address_str]
                except:
                    numworksheet += 1
                    numworksheet_offset = 2
                    devicename = packet_address.devicename.replace('/','_').replace('[','_').replace(']','_').replace('\\','_').replace('*','_').replace(':','_')
                    packet_address_str_xlsx = '{:02d}_{}'.format(numworksheet,devicename)
                    if len(packet_address_str_xlsx) > 31:
                        packet_address_str_xlsx = packet_address_str_xlsx[0:31]

                    worksheet_summary.write(numworksheet_offset, 0, 'redvypr address')
                    worksheet_summary.write(numworksheet_offset, 1, 'worksheet')
                    worksheet_summary.write(numworksheet + numworksheet_offset, 0, packet_address_str)
                    worksheet_summary.write(numworksheet + numworksheet_offset, 1, packet_address_str_xlsx)
                    logger.debug('Will create workbook for {}'.format(packet_address_str_xlsx))
                    device_worksheets[packet_address_str] = workbook.add_worksheet(packet_address_str_xlsx)
                    device_worksheets_indices[packet_address_str] = {'datakeys':[],'numline':0,'colindex':{}}
                    device_worksheets_indices[packet_address_str]['worksheet'] = packet_address_str_xlsx
                    device_worksheets[packet_address_str].write(row_datakey, 0, 'Excel time')


                # Write data
                if True:
                    datakeys = data_packets.redvypr_datapacket(data).datakeys()
                    datakeys.remove('t')
                    datakeys.insert(0,'t')
                    # Write data in datakeys
                    # Write time
                    colindex_time = 0
                    lineindex = row_firstdata + device_worksheets_indices[packet_address_str]['numline']
                    datatime = datetime.datetime.fromtimestamp(data['t'])
                    device_worksheets[packet_address_str].write_datetime(lineindex, colindex_time, datatime,formats['date'])
                    for k in datakeys:
                        try:
                            colindex = device_worksheets_indices[packet_address_str]['colindex'][k]
                        except:
                            device_worksheets_indices[packet_address_str]['datakeys'].append(k)
                            colindex = len(device_worksheets_indices[packet_address_str]['datakeys']) - 1 + coloffset
                            device_worksheets_indices[packet_address_str]['colindex'][k] = colindex
                            device_worksheets[packet_address_str].write(row_datakey,colindex,k)

                        print('Will write data from {} to column {} and line {}'.format(packet_address_str, colindex,lineindex))
                        datawrite = data[k]
                        if (type(datawrite) is not str) and (type(datawrite) is not int) and (type(datawrite) is not float):
                            print('Datatype {} not supported, converting data to str'.format(str(type(datawrite))))
                            datawrite = str(datawrite)

                        device_worksheets[packet_address_str].write(lineindex, colindex, datawrite)

                    device_worksheets_indices[packet_address_str]['numline'] += 1
                    size = sys.getsizeof(workbook)
                    print('Size:',size)

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
            if FLAG_TIME or FLAG_SIZE or (FLAG_RUN == False):
                # Autofit
                print('Autofit')
                worksheet_summary.autofit()
                for w in device_worksheets:
                    device_worksheets[w].autofit()
                    device_worksheets[w].set_column(0, 0, 25)
                workbook.close()
                data_stat = {'_deviceinfo': {}}
                data_stat['_deviceinfo']['filename'] = filename
                data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
                data_stat['_deviceinfo']['closed'] = time.time()
                data_stat['_deviceinfo']['bytes_written'] = bytes_written
                data_stat['_deviceinfo']['packets_written'] = packets_written
                dataqueue.put(data_stat)
                if FLAG_RUN:
                    [workbook, filename,formats] = create_logfile(config, count)
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














class Device(redvypr_device):
    """
    csvlogger device
    """

    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)


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
        print('Hallo,device config',device.config)
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
            self.size_newfile.setText(str(self.device.config.size_newfile))
        except Exception as e:
            self.size_newfile.setText('0')
            
        self.newfiletimecombo = QtWidgets.QComboBox()
        times = typing.get_args(self.device.config.model_fields['size_newfile_unit'].annotation)
        timeunit = self.device.config.size_newfile_unit
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
        self.outlayout.addWidget(self.folder_text, 0, 1,1,3)
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
        layout.addWidget(self.startbtn,5,1,1,2)

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
        print(funcname)
        datastreams_subscribed = self.device.get_subscribed_datastreams()
        print('datastreams subscribed',datastreams_subscribed)
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
        print('Deviceaddresses',raddresses)
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
        
