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
from redvypr.data_packets import get_data, addr_in_data, compare_datastreams
import redvypr.version

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('csvlogger')
logger.setLevel(logging.DEBUG)

description = 'Writes data into a csv format, either into a file or publishes it as a "csv" datakey'
config_template = {}
config_template['name']              = 'csvlogger'
config_template['datastreams_info']  = {'type':'dict','description':'Information about the files, to be filled by csvlogger'}
config_template['datastreams']       = {'type':'list','description':'List of all datastreams'}
config_template['dt_newfile']        = {'type':'int','default':20,'description':'Time after which a new file is created'}
config_template['dt_newfile_unit']   = {'type':'str','default':'seconds','options':['seconds','hours','days']}
config_template['dt_update']         = {'type':'int','default':5,'description':'Time after which an upate is sent to the gui'}
config_template['size_newfile']      = {'type':'int','default':0,'description':'Size after which a new file is created'}
config_template['size_newfile_unit'] = {'type':'str','default':'bytes','options':['bytes','kB','MB']}
config_template['fileextension']     = {'type':'str','default':'redvypr_yaml','description':'File extension, if empty not used'}
config_template['fileprefix']        = {'type':'str','default':'redvypr','description':'If empty not used'}
config_template['filepostfix']       = {'type':'str','default':'raw','description':'If empty not used'}
config_template['filedateformat']    = {'type':'str','default':'%Y-%m-%d_%H%M%S','description':'Dateformat used in the filename, must be understood by datetime.strftime'}
config_template['filecountformat']   = {'type':'str','default':'04','description':'Format of the counter. Add zero if trailing zeros are wished, followed by number of digits. 04 becomes {:04d}'}
config_template['dt_status']         = 1
config_template['separator']         = ','
config_template['speedup']           = {'type':'float','description':'Speedup factor of the data'}
config_template['redvypr_device']    = {}
config_template['redvypr_device']['publish']     = True
config_template['redvypr_device']['subscribe']   = True
config_template['redvypr_device']['description'] = description

def write_csv_header(f,config):
    funcname = __name__ + '.write_csv_header()'
    logger.debug(funcname)
    bytes_written = 0
    datastreams = config['datastreams']
    separator   = config['separator']
    try:
        commentchar = config['commentchar']
    except:
        commentchar = '#'
    
    # Write header
    tstr = datetime.datetime.strftime(datetime.datetime.now(),"%y-%m-%d %H:%M:%S.%f")
    firstline = '{:s}redvypr ({:s}) csv file created on {:s}\n'.format(commentchar,redvypr.version,tstr)
    f.write(firstline)
    bytes_written += len(firstline)
    headerstr = '{:s}hostinfo: {:s}\n'.format(commentchar,str(config['hostinfo']))
    f.write(headerstr)
    bytes_written += len(headerstr)
    # The devices
    headerstr = commentchar + 'datastreams\n'
    f.write(headerstr)
    bytes_written += len(headerstr)
    headerstr = 'time' + separator + 'time' + separator + 'numpacket'
    for datastream in datastreams:
        headerstr += separator + datastream 
     
    headerstr += '\n'
    f.write(headerstr)
    bytes_written += len(headerstr)
    # The units
    f.write(commentchar + 'units\n')
    unitstr = 'yyyy-mm-dd HH:MM:SS' + separator + 'seconds since 1970-01-01 00:00:00' + separator + '#'
    for datastream in datastreams:
        try:
            unit = config['datastreams_info'][datastream]['unit']
        except:
            unit = ''
    
        unitstr += separator + unit
     
    unitstr += '\n'
    f.write(unitstr)
    bytes_written += len(unitstr)
    # All headerkeys
    headerkeys = ['latlon','location','sensortype','serialnumber','comment']
    
    for headerkey in headerkeys:
        f.write(commentchar + headerkey + '\n')
        headerstr = '' + separator + '' + separator + '' # Here could be the data of the device
        for datastream in datastreams:
            try:
                headerdata = config['datastreams_info'][datastream][headerkey]
            except:
                headerdata = ''
        
            headerstr += separator + headerdata
         
        headerstr += '\n'
        f.write(headerstr)
        bytes_written += len(headerstr)
    # Syncing the header
    f.flush()
    os.fsync(f.fileno())
    
    return bytes_written
   
    
def create_logfile(config):
    funcname = __name__ + '.create_logfile()'
    logger.debug(funcname)
    #self.device.config['filename']      = filename_constructed
    #self.device.config['filebase']      = self.outfilename.text()
    #self.device.config['filetime']      = filenametimestr
    #self.device.config['fileextension'] = self.filenameextcombo.currentText()
    FLAG_ADD_TIME = '_yyyy-mm-dd_HHMMSS' in config['filename']
    #print('filename',config['filename'],FLAG_ADD_TIME)
    if(FLAG_ADD_TIME):
        (filebase1,fileext)=os.path.splitext(config['filename'])
        filebase = filebase1.split('_yyyy-mm-dd_HHMMSS')[0]
        tstr     = datetime.datetime.now().strftime('_%Y-%m-%d_%H%M%S')
        filename = filebase + tstr + fileext
    else:
        filename = config['filename']
       
    logger.info(funcname + ': Will create a new file: {:s}'.format(filename))
    if True:
        try:
            f = open(filename,'w+')
            logger.debug(funcname + ': Opened file: {:s}'.format(filename))
            return [f,filename]
        except Exception as e:
            logger.warning(funcname + ': Error opening file:' + filename + ':' + str(e))
            return None
        




def start(datainqueue,dataqueue,comqueue,statusqueue,config={'filename':'','time':True,'host':True,'device':True,'newline':False,'pcktcnt':False,'keys':['data']}):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening writing:')
    #print('Config',config)
    filename = config['filename']
    try:
        logger.info(funcname + ' Will create new file every {:d}s.'.format(config['dt_newfile']))
    except:
        config['dt_newfile'] = 0

    try:
        config['dt_sync']
    except:
        config['dt_sync'] = 5
    
    # The time interval of a status message    
    try:
        config['dt_status']
    except:
        config['dt_status'] = 1
        
    try:
        separator = config['separator']
    except:
        config['separator'] = ','
        
    separator = config['separator']

    try:
        datastreams = config['datastreams']
    except:
        logger.warning(funcname + ': Need to specify datastreams aborting')
        return None
    
    try:
        config['datastreams_info']['format'] 
    except:
        f0 = 'f'
        config['datastreams_info']['format'] = {}
        for stream in datastreams:
            config['datastreams_info'][stream]['format'] = f0
            
    bytes_written   = 0
    packets_written = 0
    [f,filename] = create_logfile(config)
    bytes_written =+ write_csv_header(f,config)
    statusstr = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ': New file {:s}\n'.format(filename)
    status = {'data':statusstr}
    statusqueue.put(status) 
    
    if(f == None):
        logger.warning(funcname + ': Could not open csv file {:s}'.format())
        return None
   
   
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
            logger.debug('Exception dtnews: {:s}'.format(str(e)))
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
            logger.debug('Exception sizenewb: {:s}'.format(str(e)))
            sizenewb = 0  # Size in bytes
    
    
    tfile           = time.time() # Save the time the file was created
    tflush          = time.time() # Save the time the file was flushed to disk
    tstatus         = time.time() # Save the time the status message was sent
    # The main loop forever
    while True:
        tcheck = time.time()
        file_age      = tcheck - tfile
        FLAG_TIME = (dtnews > 0)  and  (file_age >= dtnews)
        FLAG_SIZE = (sizenewb > 0) and (bytes_written >= sizenewb)
        if(FLAG_TIME or FLAG_SIZE):
            # close the old file
            f.close()
            file_size = os.stat(filename).st_size
            statusstr = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ': File {:s} closed, {:d} bytes\n'.format(filename,file_size)
            status = {'data':statusstr}
            statusqueue.put(status)
            # open a new file
            [f,filename] = create_logfile(config)
            bytes_written         = 0
            packets_written       = 0 
            bytes_written =+ write_csv_header(f,config)
            tfile = tcheck  
            statusstr = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ': New file {:s}\n'.format(filename)
            status = {'data':statusstr}
            statusqueue.put(status) 
        try:
            com = comqueue.get(block=False)
            logger.debug(funcname + ': received:' + str(com))
            # Closing all open files
            try:
                f.close()
                logger.info(funcname + ': File closed:' + str(filename))
                file_size = os.stat(filename).st_size
                statusstr = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ': File {:s} closed, {:d} bytes\n'.format(filename,file_size)
                status = {'data':statusstr}
                statusqueue.put(status)
            except Exception as e:
                logger.debug(funcname + ': could not close: {:s} ({:s})'.format(filename,str(e)))
                
            break
        except Exception as e:
            #logger.warning(funcname + ': Error stopping thread:' + str(e))
            pass


        time.sleep(0.05)
        if((time.time() - tstatus) > config['dt_status']):
            status = {}
            status['filename'] = filename
            status['bytes_written'] = bytes_written
            status['packets_written'] = packets_written
            statusqueue.put(status)
            tstatus = time.time()
         
        while(datainqueue.empty() == False):
            try:
                datapacket = datainqueue.get(block=False)
                # Check if a datastream is in the data
                data_save_time = None
                data_save = {}
                maxlen = 0
                FLAG_save_packet = False
                for datastream in datastreams:
                    if(addr_in_data(datastream, datapacket)):
                        FLAG_save_packet = True
                        data     = get_data(datastream,datapacket)
                        data_tmp = copy.deepcopy(data)
                        # Check for iterables and str, save all non iterables (and str) in list
                        if(type(data) == 'str'):
                            data_save[datastream] = [data]
                        else:
                            # Data can be a list or similar, this will be saved as one line
                            # Check if we have an iterable, of not make a one element list
                            try:
                                iterator = iter(data)
                            except TypeError:
                                # not iterable
                                data = [data]
                                
                            data_save[datastream] = data
                        
                        maxlen = max(maxlen,len(data))
                
                # If we have datastreams found to be saved, then write it to the file        
                if(FLAG_save_packet):
                    # Make the time iterable (if its not already)
                    try:
                        iterator = iter(datapacket['t'])
                        timepackets = datapacket['t']
                    except TypeError:
                        # not iterable
                        timepackets = [datapacket['t']]
                        
                    for i in range(maxlen): # Loop over the longest length, this is typically one 
                        try:
                            timepacket = timepackets[i]
                        except:
                            timepacket = timepackets[-1]
                        
                        
                        timepacketd = datetime.datetime.fromtimestamp(timepacket)
                        tstr = datetime.datetime.strftime(timepacketd,"%y-%m-%d %H:%M:%S.%f")    
                        datastr_time = '{:s}{:s}{:f}{:s}{:d}'.format(tstr,separator,timepacket,separator,datapacket['numpacket'])
                        datastr = datastr_time
                        for datastream in datastreams:
                            try:
                                data = data_save[datastream][i]
                            except:
                                data = ''
                                
                            datastr += separator
                            if(data == ''):
                                pass
                            else:

                                dataformat = config['datastreams_info'][datastream]['format']
                                dataformat = '{:' + dataformat + '}' # Add the python specific brackets
                                try: 
                                    datastr += dataformat.format(data)
                                except Exception as e:
                                    logger.warning(funcname + ': Invalid format ({:s}) for data {:s}'.format(dataformat,str(data)))  
                    
                
                        datastr += '\n'
                        bytes_written += len(datastr)
                        packets_written += 1
                        f.write(datastr)
                        
                if((time.time() - tflush) > config['dt_sync']):
                    f.flush()
                    os.fsync(f.fileno())
                    tflush = time.time()
                    
                
                    
            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))
                #print(data)

class Device(redvypr_device):
    def __init__(self,**kwargs):
        """
        """
        super(Device, self).__init__(**kwargs)
        self.publish     = False
        self.subscribe   = True
        self.description = 'csvlogger'
        
        self.config['hostinfo'] = self.redvypr.hostinfo
        
        try:
            self.config['datastreams']
        except:
            self.config['datastreams'] = set()
            
        try:
            self.config['datastreams_info']
        except:
            self.config['datastreams_info'] = {}
            
    def start(self):
        """
        """
        funcname = self.__class__.__name__ + '.start()'
        self.logger.debug(funcname)
        config=copy.deepcopy(self.config)
        start(self.datainqueue,self.dataqueue,self.comqueue,self.statusqueue,config=config)

#
#
# The init widget
#
#
class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device) # Signal requesting a start of the device (starting the thread)
    device_stop  = QtCore.pyqtSignal(Device) # Signal requesting a stop of device
    connect      = QtCore.pyqtSignal(Device) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        self.device   = device
        self.redvypr  = device.redvypr
        self.label    = QtWidgets.QLabel("CSV-Logger setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')
        self.config_widgets = [] # A list of all widgets that can only be used of the device is not started yet

        
        self.create_datasteamwidget()
        self.create_outfilewidget()

        self.__infodict__ = {'format':'','unit':''}
        
        # The rest
        #self.conbtn = QtWidgets.QPushButton("Connect logger to devices")
        #self.conbtn.clicked.connect(self.con_clicked)        
        self.startbtn = QtWidgets.QPushButton("Write CSV-File")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)


        # The full layout
        layout = QtWidgets.QGridLayout(self)
        layout.addWidget(self.label,0,0,1,-1)  
        layout.addWidget(self.filewidget, 2, 1, 1, -1)
        layout.addWidget(self.datastreamwidget,3,0,1,-1)
        layout.addWidget(self.startbtn,5,0,1,-1)
        
        self.update_datastreamwidget()
        self.redvypr.device_status_changed_signal.connect(self.update_datastreamwidget)
        

    def create_outfilewidget(self):
        """
        Creates the outfilewidget
        Returns:

        """

        # The output widgets
        self.outlabel = QtWidgets.QLabel("Logfile")
        self.outfilename = QtWidgets.QLineEdit()
        # Checkboxes
        self.prefix_check = QtWidgets.QCheckBox('Prefix')
        self.date_check = QtWidgets.QCheckBox('Date/Time')
        self.count_check = QtWidgets.QCheckBox('Counter')
        self.postfix_check = QtWidgets.QCheckBox('Postfix')
        self.extension_check = QtWidgets.QCheckBox('Extension')

        try:
            filename = self.device.config['filename']
        except:
            filename = ''

        self.outfilename.setText(filename)

        # Delta t for new file
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
        self.dt_newfile = edit
        self.dt_newfile.setToolTip(
            'Create a new file every N seconds.\nFilename is "filenamebase"_yyyymmdd_HHMMSS_count."ext".\nUse 0 to disable feature.')
        try:
            self.dt_newfile.setText(str(self.device.config['dt_newfile']))
        except Exception as e:
            self.dt_newfile.setText('0')

        # Delta t for new file
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
        self.size_newfile = edit
        self.size_newfile.setToolTip(
            'Create a new file every N bytes.\nFilename is "filenamebase"_yyyymmdd_HHMMSS_count."ext".\nUse 0 to disable feature.')
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
        self.newfilelayout.addRow(self.dt_newfile, self.newfiletimecombo)
        self.newfilelayout.addRow(self.size_newfile, self.newfilesizecombo)

        # Filenamelayout
        self.extension_text = QtWidgets.QLineEdit('csv')
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
        # Checkboxes
        self.outlayout.addWidget(self.prefix_check, 0, 0)
        self.outlayout.addWidget(self.date_check, 0, 1)
        self.outlayout.addWidget(self.count_check, 0, 2)
        self.outlayout.addWidget(self.postfix_check, 0, 3)
        self.outlayout.addWidget(self.extension_check, 0, 4)

        self.outlayout.addWidget(self.prefix_text, 1, 0)
        self.outlayout.addWidget(self.date_text, 1, 1)
        self.outlayout.addWidget(self.count_text, 1, 2)
        self.outlayout.addWidget(self.postfix_text, 1, 3)
        self.outlayout.addWidget(self.extension_text, 1, 4)
        #self.outlayout.addWidget(self.newfilewidget, 3, 0, 1, 4)

        # The final widget
        self.filewidget = QtWidgets.QWidget()
        self.filelayout = QtWidgets.QHBoxLayout(self.filewidget)
        self.filelayout.addWidget(self.outwidget)
        self.filelayout.addWidget(self.newfilewidget)

    def create_datasteamwidget(self):
        """
        """
        self.datastreamwidget = QtWidgets.QWidget()
        self.addallbtn = QtWidgets.QPushButton('Add all')
        self.addallbtn.clicked.connect(self.addremstream)
        self.remallbtn = QtWidgets.QPushButton('Rem all')
        self.remallbtn.clicked.connect(self.addremstream)
        self.arrleft = QtWidgets.QToolButton()
        self.arrleft.setArrowType(QtCore.Qt.LeftArrow)
        self.arrleft.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Fixed)
        self.arrleft.clicked.connect(self.addremstream)
        self.arrright = QtWidgets.QToolButton()
        self.arrright.setArrowType(QtCore.Qt.RightArrow)
        self.arrright.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Fixed)
        self.arrright.clicked.connect(self.addremstream)
        # Datastreams
        self.datastreamlist_all = QtWidgets.QListWidget()
        self.datastreamlist_choosen = QtWidgets.QTableWidget()
        self.__listlabel__        = ['Datastream','Dataformat','Unit','LatLon','Location','Serialnumber','Sensortype','Comment']
        self.__ind_format__       = 1
        self.__ind_unit__         = 2
        self.__ind_latlon__       = 3
        self.__ind_location__     = 4
        self.__ind_serialnumber__ = 5
        self.__ind_sensortype__   = 6
        self.__ind_comment__      = 7
        self.datastreamlist_choosen.setColumnCount(len(self.__listlabel__))
        self.datastreamlist_choosen.itemChanged.connect(self.__table_choosen_changed__)
        
        self.config_widgets.append(self.datastreamlist_all) 
        self.config_widgets.append(self.datastreamlist_choosen) 
        self.config_widgets.append(self.arrleft) 
        self.config_widgets.append(self.arrright) 
        self.config_widgets.append(self.remallbtn) 
        self.config_widgets.append(self.addallbtn) 
        
        if True:
            self.datastreamwidget_layout = QtWidgets.QHBoxLayout(self.datastreamwidget)
            # all datastreams
            layout = QtWidgets.QVBoxLayout()
            layout.addWidget(QtWidgets.QLabel('Available Datastreams'))
            layout.addWidget(self.datastreamlist_all)
            self.datastreamwidget_layout.addLayout(layout, stretch=1)
            #buttons
            layout = QtWidgets.QVBoxLayout()
            layout.addStretch()
            layout.addWidget(self.arrleft)
            layout.addWidget(self.remallbtn)
            layout.addWidget(self.addallbtn)
            layout.addWidget(self.arrright)
            layout.addStretch()
            self.datastreamwidget_layout.addLayout(layout)
            # The choosen datastreams
            layout = QtWidgets.QVBoxLayout()
            layout.addWidget(QtWidgets.QLabel('Datastreams to log'))
            layout.addWidget(self.datastreamlist_choosen)
            self.datastreamwidget_layout.addLayout(layout, stretch=2)

    def __change_fileext__(self,itemindex):
        funcname = self.__class__.__name__ + '.__change_fileext__():'
        logger.debug(funcname)
        if(itemindex == 0):
            self.filenameextcombo.setEditable(True)
            # getting line edit
            line = self.filenameextcombo.lineEdit()
            line.editingFinished.connect(self.__change_fileext_text__)
        else:
            self.filenameextcombo.setEditable(False)
            
            
    def get_filename(self):
        tnow = datetime.datetime.now()
        filename_suggestion = tnow.strftime("redvypr_%Y-%m-%d_%H%M%S.csv")
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(self,"CSV file",filename_suggestion,"CSV Files (*.csv);;All Files (*)")
        if filename:
            (filebase,extension) = os.path.splitext(os.path.basename(filename))
            extension = extension[1:] # Remove the dot
            self.outfilename.setText(filebase)
            # Check if the extension exists
            count = self.filenameextcombo.count()
            FLAG_ADD_EXT = True
            for i in range(count):
                if(extension == self.filenameextcombo.itemText(i)):
                    self.filenameextcombo.setCurrentIndex(i)
                    FLAG_ADD_EXT = False
                    break
                
            if(FLAG_ADD_EXT):
                self.filenameextcombo.addItem(extension)
                count = self.filenameextcombo.count()
                self.filenameextcombo.setCurrentIndex(count-1)
                

        
    def __table_choosen_changed__(self, item):
        """
        """
        row = item.row()
        column = item.column()
        if column == self.__ind_format__:
            datastream = self.datastreamlist_choosen.item(row,0).text()
            dformat    = self.datastreamlist_choosen.item(row,self.__ind_format__).text()
            print("Format changed",datastream,dformat)
            self.device.config['datastreams_info'][datastream]['format'] = dformat
            print(self.device.config['datastreams_info'])
        elif column == self.__ind_unit__:
            datastream = self.datastreamlist_choosen.item(row,0).text()
            dunit      = self.datastreamlist_choosen.item(row,self.__ind_unit__).text()
            print("Unit changed",datastream,dunit)
            self.device.config['datastreams_info'][datastream]['unit'] = dunit
            print(self.device.config['datastreams_info'])
        elif column == self.__ind_latlon__:
            datastream = self.datastreamlist_choosen.item(row,0).text()
            ddata      = self.datastreamlist_choosen.item(row,self.__ind_latlon__).text()
            print("latlon changed",datastream,ddata)
            self.device.config['datastreams_info'][datastream]['latlon'] = ddata
            print(self.device.config['datastreams_info'])
        elif column == self.__ind_location__:
            datastream = self.datastreamlist_choosen.item(row,0).text()
            ddata      = self.datastreamlist_choosen.item(row,self.__ind_location__).text()
            print("location changed",datastream,ddata)
            self.device.config['datastreams_info'][datastream]['location'] = ddata
            print(self.device.config['datastreams_info'])
        elif column == self.__ind_serialnumber__:
            datastream = self.datastreamlist_choosen.item(row,0).text()
            ddata      = self.datastreamlist_choosen.item(row,self.__ind_serialnumber__).text()
            print("serialnum changed",datastream,ddata)
            self.device.config['datastreams_info'][datastream]['serialnumber'] = ddata
            print(self.device.config['datastreams_info'])
        elif column == self.__ind_sensortype__:
            datastream = self.datastreamlist_choosen.item(row,0).text()
            ddata      = self.datastreamlist_choosen.item(row,self.__ind_sensortype__).text()
            print("sensortype changed",datastream,ddata)
            self.device.config['datastreams_info'][datastream]['sensortype'] = ddata
            print(self.device.config['datastreams_info'])    
        elif column == self.__ind_comment__:
            datastream = self.datastreamlist_choosen.item(row,0).text()
            ddata      = self.datastreamlist_choosen.item(row,self.__ind_comment__).text()
            print("Comment changed",datastream,ddata)
            self.device.config['datastreams_info'][datastream]['comment'] = ddata
            print(self.device.config['datastreams_info'])
            
            
        
            
    def addremstream(self):
        funcname = self.__class__.__name__ + '.addremstream():'
        logger.debug(funcname)
        button = self.sender()
        if(button == self.arrright): # Add selected
            print('right')
            streams = self.datastreamlist_all.selectedItems()
            for streamitem in streams:
                stream = streamitem.text()
                print('stream',stream)
                self.device.config['datastreams'].add(stream)
                self.device.subscribe_datastream(stream)                
                try:
                    self.device.config['datastreams_info'][stream]
                except:
                    self.device.config['datastreams_info'][stream] = copy.deepcopy(self.__infodict__)   
                
        elif(button == self.addallbtn): # Add all
            for i in range(self.datastreamlist_all.count()):
                stream = self.datastreamlist_all.item(i).text()
                self.device.config['datastreams'].add(stream)
                self.device.subscribe_datastream(stream)
                try:
                    self.device.config['datastreams_info'][stream]
                except:
                    self.device.config['datastreams_info'][stream] = copy.deepcopy(self.__infodict__)
            
                
        elif(button == self.remallbtn): # Rem all            
            self.device.config['datastreams'] = set()
            self.device.unsubscribe_all()
                
        elif(button == self.arrleft):
            print('left')
            streams = self.datastreamlist_choosen.selectedItems()
            print(self.device.config['datastreams'])
            for streamitem in streams:
                stream = streamitem.text()
                print('stream',stream)
                self.device.unsubscribe_datastream(stream)
                self.device.config['datastreams'].remove(stream)
            
            
            self.device.unsubscribe_datastreams()
            
        self.update_datastreamwidget()
        
    def update_datastreamwidget(self):
        funcname = self.__class__.__name__ + '.update_datastreamwidget():'
        logger.debug(funcname)
        datastreams = self.redvypr.get_datastreams()
        self.datastreamlist_all.clear()
        self.datastreamlist_choosen.clear()
        self.datastreamlist_choosen.setHorizontalHeaderLabels(self.__listlabel__)
        for d in datastreams:
            dshort = d.split('::')[0]
            if(dshort[0] != '?'):
                self.datastreamlist_all.addItem(dshort)
                
        datastreams_subscribed = self.device.config['datastreams'].data
        self.datastreamlist_choosen.setRowCount(len(datastreams_subscribed))
        for i,d in enumerate(datastreams_subscribed):
            item = QtWidgets.QTableWidgetItem(d)
            # The format of the string to be written
            try:
                dformat = self.device.config['datastreams_info'][d]['format']
            except:
                dformat = 'f'  
                
            formatitem = QtWidgets.QTableWidgetItem(dformat)
            try:
                dunit = self.device.config['datastreams_info'][d]['unit']
            except:
                dunit = ''
                
            # Get the unit from the statistics
            try:
                datastream_info = self.redvypr.get_datastream_info(d)
                dunit_stat = datastream_info['unit']
            except Exception as e:
                print('unit stat',e)
                dunit_stat = ''
                
            if(dunit == ''):
                print('Replacing with dunit_stat')
                dunit = dunit_stat
            
            unititem = QtWidgets.QTableWidgetItem(dunit)
            
            
            
            self.datastreamlist_choosen.setItem(i,0,item)
            self.datastreamlist_choosen.setItem(i,self.__ind_format__,formatitem)
            self.datastreamlist_choosen.setItem(i,self.__ind_unit__,unititem)
            
        self.datastreamlist_choosen.resizeColumnsToContents()
        
    


    def con_clicked(self):
        print('Connect clicked')
        button = self.sender()
        self.connect.emit(self.device)        
            
    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            logger.debug("button pressed")
            # The filename
            self.device.config['dt_newfile']        = int(self.dt_newfile.text())
            self.device.config['dt_newfile_unit']   = self.newfiletimecombo.currentText()
            self.device.config['size_newfile']      = int(self.size_newfile.text())
            self.device.config['size_newfile_unit'] = self.newfilesizecombo.currentText()
            self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            self.device_stop.emit(self.device)

    def thread_status(self,status):
        self.update_buttons(status['threadalive'])
        
    def update_buttons(self,thread_status):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """
            # Running
            if(thread_status):
                self.startbtn.setText('Stop writing CSV-File')
                self.startbtn.setChecked(True)
                for w in self.config_widgets:
                    w.setEnabled(False)
            # Not running
            else:
                self.startbtn.setText('Write CSV-File')
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
        self.text       = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.filelab= QtWidgets.QLabel("File: ")
        self.byteslab   = QtWidgets.QLabel("Bytes written: ")
        self.packetslab = QtWidgets.QLabel("Packets written: ")
        self.text.setMaximumBlockCount(10000)
        self.device = device
        hlayout.addWidget(self.byteslab)
        hlayout.addWidget(self.packetslab)
        layout.addWidget(self.filelab)        
        layout.addLayout(hlayout)
        layout.addWidget(self.text)
        #self.text.insertPlainText("hallo!")  
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(500)
        
    def update_status(self):
        funcname = self.__class__.__name__ + '.update_status():'
        
        try:
            data = self.device.statusqueue.get_nowait()
        except:
            data = None
        if(data is not None):
            try:
                self.filelab.setText("File: {:s}".format(data['filename']))        
                self.byteslab.setText("Bytes written: {:d}".format(data['bytes_written']))
                self.packetslab.setText("Packets written: {:d}".format(data['packets_written']))
            except:
                pass
            
            try:
                self.text.insertPlainText(str(data['data']))
            except:
                pass      
