import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import serial
import serial.tools.list_ports
import logging
import sys
from redvypr.data_packets import do_data_statistics, create_data_statistic_dict,check_for_command


description = 'Reading data from a serial device'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('serial_device')
logger.setLevel(logging.DEBUG)


config_template              = {}
config_template['comport']   = {'type':'str'}
config_template['baud']      = {'type':'int','default':4800}
config_template['parity']    = {'type':'int','default':serial.PARITY_NONE}
config_template['stopbits']  = {'type':'int','default':serial.STOPBITS_ONE}
config_template['bytesize']  = {'type':'int','default':serial.EIGHTBITS}
config_template['dt_poll']   = {'type':'float','default':0.05}
config_template['chunksize'] = {'type':'int','default':1000} # The maximum amount of bytes read with one chunk
config_template['packetdelimiter'] = {'type':'str','default':'\n'} # The maximum amount of bytes read with one chunk
config_template['redvypr_device'] = {}
config_template['redvypr_device']['publishes']   = True
config_template['redvypr_device']['subscribes'] = False
config_template['redvypr_device']['description'] = description


def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Starting reading serial data')
    chunksize   = config['chunksize'] #The maximum amount of bytes read with one chunk    
    serial_name = config['comport']
    baud        = config['baud']
    parity      = config['parity']    
    stopbits    = config['stopbits']    
    bytesize    = config['bytesize']    
    dt_poll     = config['dt_poll']

    print('Starting',config)
    
    newpacket   = config['packetdelimiter']
    # Check if a delimiter shall be used (\n, \r\n, etc ...)
    if(len(newpacket)>0):
        FLAG_DELIMITER = True
    else:
        FLAG_DELIMITER = False
    if(type(newpacket) is not bytes):
        newpacket = newpacket.encode('utf-8')
        
    rawdata_all    = b''
    dt_update      = 1 # Update interval in seconds
    bytes_read     = 0
    sentences_read = 0
    bytes_read_old = 0 # To calculate the amount of bytes read per second
    t_update       = time.time()
    serial_device = False
    if True:
        try:
            serial_device = serial.Serial(serial_name,baud,parity=parity,stopbits=stopbits,bytesize=bytesize,timeout=0)
            #print('Serial device 0',serial_device)
            #serial_device.timeout(0.05)
            #print('Serial device 1',serial_device)                        
        except Exception as e:
            #print('Serial device 2',serial_device)
            logger.debug(funcname + ': Exception open_serial_device {:s} {:d}: '.format(serial_name,baud) + str(e))
            return False

    got_dollar = False    
    while True:
        # TODO, here commands could be send as well
        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if (data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            # logger.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                if command == 'stop':
                    serial_device.close()
                    sstr = funcname + ': Command is for me: {:s}'.format(str(command))
                    logger.debug(sstr)
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass
                    return


        time.sleep(dt_poll)
        ndata = serial_device.inWaiting()
        try:
            rawdata_tmp = serial_device.read(ndata)
        except Exception as e:
            print(e)
            #print('rawdata_tmp', rawdata_tmp)

        nread = len(rawdata_tmp)
        if True:
            if nread > 0:
                bytes_read  += nread
                rawdata_all += rawdata_tmp
                #print('rawdata_all',rawdata_all)
                FLAG_CHUNK = len(rawdata_all) > chunksize
                if(FLAG_CHUNK):
                    data               = {'t':time.time()}
                    data['data']       = rawdata_all
                    data['comport']    = serial_device.name
                    data['bytes_read'] = bytes_read
                    dataqueue.put(data)
                    rawdata_all = b''

                # Check if the newpacket character in the data
                if(FLAG_DELIMITER):
                    FLAG_CHAR = newpacket in rawdata_all
                    if(FLAG_CHAR):
                        rawdata_split = rawdata_all.split(newpacket)
                        #print('rawdata_all', rawdata_all)
                        if(len(rawdata_split)>1): # If len==0 then character was not found
                            for ind in range(len(rawdata_split)-1): # The last packet does not have the split character
                                sentences_read += 1
                                raw = rawdata_split[ind] + newpacket # reconstruct the data
                                #print('raw', raw)
                                data               = {'t':time.time()}
                                data['data']       = raw
                                data['comport']    = serial_device.name
                                data['bytes_read'] = bytes_read
                                data['sentences_read'] = sentences_read
                                dataqueue.put(data)

                            rawdata_all = rawdata_split[-1]
        
            
            
        if((time.time() - t_update) > dt_update):
            dbytes = bytes_read - bytes_read_old
            bytes_read_old = bytes_read
            bps = dbytes/dt_update# bytes per second
            #print('ndata',len(rawdata_all),'rawdata',rawdata_all,type(rawdata_all))
            #print('bps',bps)
            t_update = time.time()
            
                





class initDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        self.device   = device
        self.serialwidget = QtWidgets.QWidget()
        self.init_serialwidget()
        self.label    = QtWidgets.QLabel("Serial device")
        #self.startbtn = QtWidgets.QPushButton("Open device")
        #self.startbtn.clicked.connect(self.start_clicked)
        #self.stopbtn = QtWidgets.QPushButton("Close device")
        #self.stopbtn.clicked.connect(self.stop_clicked)
        layout.addWidget(self.label)        
        layout.addWidget(self.serialwidget)
        #layout.addWidget(self.startbtn)
        #layout.addWidget(self.stopbtn)
        
    def init_serialwidget(self):
        """Fills the serial widget with content
        """
        layout = QtWidgets.QGridLayout(self.serialwidget)
        # Serial baud rates
        baud = [300,600,1200,2400,4800,9600,19200,38400,57600,115200,576000,921600]
        self._combo_serial_devices = QtWidgets.QComboBox()
        #self._combo_serial_devices.currentIndexChanged.connect(self._serial_device_changed)
        self._combo_serial_baud = QtWidgets.QComboBox()
        for b in baud:
            self._combo_serial_baud.addItem(str(b))

        self._combo_serial_baud.setCurrentIndex(4)
        # creating a line edit
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
  
        # setting line edit
        self._combo_serial_baud.setLineEdit(edit)
        
        self._combo_parity = QtWidgets.QComboBox()
        self._combo_parity.addItem('None')
        self._combo_parity.addItem('Odd')
        self._combo_parity.addItem('Even')
        self._combo_parity.addItem('Mark')
        self._combo_parity.addItem('Space')
        
        self._combo_stopbits = QtWidgets.QComboBox()
        self._combo_stopbits.addItem('1')
        self._combo_stopbits.addItem('1.5')
        self._combo_stopbits.addItem('2')
        
        self._combo_databits = QtWidgets.QComboBox()
        self._combo_databits.addItem('8')
        self._combo_databits.addItem('7')
        self._combo_databits.addItem('6')
        self._combo_databits.addItem('5')
        
        self._button_serial_openclose = QtWidgets.QPushButton('Open')
        self._button_serial_openclose.clicked.connect(self.start_clicked)


        # Check for serial devices and list them
        for comport in serial.tools.list_ports.comports():
            self._combo_serial_devices.addItem(str(comport.device))

        #How to differentiate packets
        self._packet_ident_lab = QtWidgets.QLabel('Packet identification')
        self._packet_ident     = QtWidgets.QComboBox()
        self._packet_ident.addItem('newline \\n')
        self._packet_ident.addItem('newline \\r\\n')
        self._packet_ident.addItem('None')
        # Max packetsize
        self._packet_size_lab   = QtWidgets.QLabel("Maximum packet size")
        self._packet_size_lab.setToolTip('The number of received bytes after which a packet is sent.\n Add 0 for no size check')
        onlyInt = QtGui.QIntValidator()
        self._packet_size       = QtWidgets.QLineEdit()
        self._packet_size.setValidator(onlyInt)
        self._packet_size.setText('0')
        #self.packet_ident

        layout.addWidget(self._packet_ident,0,1)
        layout.addWidget(self._packet_ident_lab,0,0)
        layout.addWidget(self._packet_size_lab,0,2)
        layout.addWidget(self._packet_size,0,3)
        layout.addWidget(QtWidgets.QLabel('Serial device'),1,0)
        layout.addWidget(self._combo_serial_devices,2,0)
        layout.addWidget(QtWidgets.QLabel('Baud'),1,1)
        layout.addWidget(self._combo_serial_baud,2,1)
        layout.addWidget(QtWidgets.QLabel('Parity'),1,2)  
        layout.addWidget(self._combo_parity,2,2) 
        layout.addWidget(QtWidgets.QLabel('Databits'),1,3)  
        layout.addWidget(self._combo_databits,2,3) 
        layout.addWidget(QtWidgets.QLabel('Stopbits'),1,4)  
        layout.addWidget(self._combo_stopbits,2,4) 
        layout.addWidget(self._button_serial_openclose,2,5)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)
        
    
    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_status']

        if(thread_status):
            self._button_serial_openclose.setText('Close')
            self._combo_serial_baud.setEnabled(False)
            self._combo_serial_devices.setEnabled(False)
        else:
            self._button_serial_openclose.setText('Open')
            self._combo_serial_baud.setEnabled(True)
            self._combo_serial_devices.setEnabled(True)
        
            
    def start_clicked(self):
        #print('Start clicked')
        button = self._button_serial_openclose
        #print('Start clicked:' + button.text())
        #config_template['comport'] = {'type': 'str'}
        #config_template['baud'] = {'type': 'int', 'default': 4800}
        #config_template['parity'] = {'type': 'int', 'default': serial.PARITY_NONE}
        #config_template['stopbits'] = {'type': 'int', 'default': serial.STOPBITS_ONE}
        #config_template['bytesize'] = {'type': 'int', 'default': serial.EIGHTBITS}
        #config_template['dt_poll'] = {'type': 'float', 'default': 0.05}
        #config_template['chunksize'] = {'type': 'int',
        #                                'default': 1000}  # The maximum amount of bytes read with one chunk
        #config_template['packetdelimiter'] = {'type': 'str',
        #                                      'default': '\n'}  # The maximum amount of bytes read with one chunk
        if('Open' in button.text()):
            button.setText('Close')
            serial_name = str(self._combo_serial_devices.currentText())
            serial_baud = int(self._combo_serial_baud.currentText())
            self.device.config['comport'].data = serial_name
            self.device.config['baud'].data = serial_baud
            stopbits = self._combo_stopbits.currentText()
            if(stopbits=='1'):
                self.device.config['stopbits'].data =  serial.STOPBITS_ONE
            elif(stopbits=='1.5'):
                self.device.config['stopbits'].data =  serial.STOPBITS_ONE_POINT_FIVE
            elif(stopbits=='2'):
                self.device.config['stopbits'].data =  serial.STOPBITS_TWO
                
            databits = int(self._combo_databits.currentText())
            self.device.config['bytesize'].data = databits

            parity = self._combo_parity.currentText()
            if(parity=='None'):
                self.device.config['parity'] = serial.PARITY_NONE
            elif(parity=='Even'):                
                self.device.config['parity'] = serial.PARITY_EVEN
            elif(parity=='Odd'):                
                self.device.config['parity'] = serial.PARITY_ODD
            elif(parity=='Mark'):                
                self.device.config['parity'] = serial.PARITY_MARK
            elif(parity=='Space'):                
                self.device.config['parity'] = serial.PARITY_SPACE
                

            self.device.thread_start()
        else:
            self.stop_clicked()

    def stop_clicked(self):
        button = self._button_serial_openclose
        self.device.thread_stop()
        button.setText('Closing') 
        #self._combo_serial_baud.setEnabled(True)
        #self._combo_serial_devices.setEnabled(True)      



class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        hlayout        = QtWidgets.QHBoxLayout()
        self.device = device
        self.bytes_read = QtWidgets.QLabel('Bytes read: ')
        self.lines_read = QtWidgets.QLabel('Lines read: ')
        self.text     = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)
        hlayout.addWidget(self.bytes_read)
        hlayout.addWidget(self.lines_read)
        layout.addLayout(hlayout)
        layout.addWidget(self.text)

    def update(self,data):
        #print('data',data)
        try:
            bstr = "Bytes read: {:d}".format(data['bytes_read'])
            lstr = "Sentences read: {:d}".format(data['sentences_read'])
        except Exception as e:
            logger.exception(e)
        try:
            self.bytes_read.setText(bstr)
            self.lines_read.setText(lstr)
            self.text.insertPlainText(str(data['data']))
            self.text.insertPlainText('\n')
        except Exception as e:
            logger.exception(e)
        
