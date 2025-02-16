"""
The serial device reads data from the serial interface and publishes them.
"""
import copy
import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import serial
import serial.tools.list_ports
import logging
import sys
import threading
import pydantic
import typing
import re
from redvypr.data_packets import check_for_command, create_datadict
from redvypr.redvypr_address import RedvyprAddress
from redvypr.device import RedvyprDevice
import redvypr.files as redvypr_files
from redvypr.data_packets import RedvyprMetadata, RedvyprDeviceMetadata
import redvypr.devices.plot.plot_widgets as redvypr_plot_widgets
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget, pydanticDeviceConfigWidget, dictQTreeWidget, datastreamMetadataWidget

_logo_file = redvypr_files.logo_file
_icon_file = redvypr_files.icon_file
description = 'Reading data from a serial device'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.serial')
logger.setLevel(logging.INFO)


packet_start = ['<None>','$','custom']
packet_delimiter = ['None','CR/LF','LF','custom']
redvypr_devicemodule = True

class RedvyprSerialDeviceMetadata(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")
    comment: str = ''

class DeviceBaseConfig(pydantic.BaseModel):
    """
    BaseConfig
    Attributes:
        publishes: True
    """
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Reads to and writes from a serial devices'
    gui_tablabel_display: str = 'Serial device status'
    gui_icon: str = 'mdi.serial-port'

class SerialDeviceCustomConfig(pydantic.BaseModel):
    use_device: bool = pydantic.Field(default=True, description='Flag if the device should be used')
    baud: int = 9600
    parity: typing.Literal[serial.PARITY_NONE, serial.PARITY_ODD, serial.PARITY_EVEN, serial.PARITY_MARK, serial.PARITY_SPACE] = pydantic.Field(default=serial.PARITY_NONE)
    stopbits: typing.Literal[serial.STOPBITS_ONE, serial.STOPBITS_ONE_POINT_FIVE,serial.STOPBITS_TWO] = pydantic.Field(default=serial.STOPBITS_ONE)
    bytesize: typing.Literal[serial.EIGHTBITS, serial.SEVENBITS, serial.SIXBITS] = pydantic.Field(default=serial.EIGHTBITS)
    dt_poll: float = 0.05
    dt_maxwait: float = pydantic.Field(default=-1.0,description='Wait time in s for valid data, if time without a valid packets exceeds dt_maxwait the comport is closed and the read thread is stopped')
    chunksize: int = pydantic.Field(default=0, description='The maximum amount of bytes read with one chunk')
    packetdelimiter: str = pydantic.Field(default='LF', description='The delimiter to distinguish packets, leave empty to disable')
    packetstart: str = pydantic.Field(default='', description='The delimiter to distinguish packets, leave empty to disable')
    device: str = pydantic.Field(default='')
    devicename: str = pydantic.Field(default='')


class DeviceCustomConfig(pydantic.BaseModel):
    serial_devices: typing.Optional[typing.List[SerialDeviceCustomConfig]] = pydantic.Field(default=[])
    ignore_devices: str = pydantic.Field(default='.*/ttyS[0-9][0-9]*', description='Regular expression of serial device names, that are ignored.')
    baud_standard: list = [300, 600, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

def read_serial(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """ Thread to read one serial device, is started for each device/comport

    """
    funcname = __name__ + '.read_serial()'
    logger.debug(funcname + ':Starting reading serial data')
    devicename_redvypr = device_info['device']
    chunksize = config['chunksize']  # The maximum amount of bytes read with one chunk
    serial_name = config['device']
    baud = config['baud']
    parity = config['parity']
    stopbits = config['stopbits']
    bytesize = config['bytesize']
    dt_poll = config['dt_poll']
    dt_maxwait = config['dt_maxwait']
    tnewpacket = time.time() # Time a new packet has arrived

    logger.debug('Starting to read serial device {:s} with baudrate {:d}'.format(serial_name,baud))

    devicename = config['devicename']
    # Get the packet end and packet start characters
    newpacket = config['packetdelimiter']
    # Check if a delimiter shall be used (\n, \r\n, etc ...)
    if (len(newpacket) > 0):
        FLAG_DELIMITER = True
    else:
        FLAG_DELIMITER = False
    if (type(newpacket) is not bytes):
        newpacket = newpacket.encode('utf-8')


    startpacket = config['packetstart'].encode('utf-8')

    rawdata_all = b''
    dt_update = 1  # Update interval in seconds
    bytes_read = 0
    sentences_read = 0
    bytes_read_old = 0  # To calculate the amount of bytes read per second
    t_update = time.time()
    serial_device = False
    if True:
        try:
            serial_device = serial.Serial(serial_name, baud, parity=parity, stopbits=stopbits, bytesize=bytesize,
                                          timeout=0)
            data = create_datadict(device= devicename_redvypr,packetid=devicename)
            data['t'] = time.time()
            data['comport'] = serial_device.name
            data['status'] = 'reading'
            # statusqueue.put(data)
            dataqueue.put(data)
            # print('Serial device 0',serial_device)
            # serial_device.timeout(0.05)
            # print('Serial device 1',serial_device)
        except Exception as e:
            # print('Serial device 2',serial_device)
            logger.debug(funcname + ': Exception open_serial_device {:s} {:d}: '.format(serial_name, baud) + str(e))
            data = create_datadict(packetid=devicename)
            data['t'] = time.time()
            data['comport'] = serial_device.name
            data['status'] = 'could not open'
            # statusqueue.put(data)
            dataqueue.put(data)
            return False

    got_dollar = False
    while True:
        # Note: Here commands could be sent as well
        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if (data is not None):
            command = data
            # logger.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                if command == 'stop':
                    serial_device.close()
                    sstr = funcname + ': Command is for me ({:s}): {:s}'.format(config['device'],str(command))
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
            # print('rawdata_tmp', rawdata_tmp)

        nread = len(rawdata_tmp)
        if True:
            if nread > 0:
                bytes_read += nread
                rawdata_all += rawdata_tmp
                #print('rawdata_all',rawdata_all)
                FLAG_CHUNK = (len(rawdata_all)) > chunksize and (chunksize > 0)
                if (FLAG_CHUNK):
                    data = create_datadict(device=devicename_redvypr,packetid=devicename)
                    data['t'] =  time.time()
                    data['data'] = rawdata_all
                    data['comport'] = serial_device.name
                    data['bytes_read'] = bytes_read
                    dataqueue.put(data)
                    rawdata_all = b''

                # Check if the newpacket character in the data
                if (FLAG_DELIMITER):
                    FLAG_CHAR = newpacket in rawdata_all
                    if (FLAG_CHAR):
                        rawdata_split = rawdata_all.split(newpacket)
                        #print('Found packets')
                        # print('rawdata_all', rawdata_all)
                        if (len(rawdata_split) > 1):  # If len==0 then character was not found
                            for ind in range( len(rawdata_split) - 1):  # The last packet does not have the split character
                                if rawdata_split[ind].startswith(startpacket):
                                    #print('Startmatch')
                                    tnewpacket = time.time()
                                    sentences_read += 1
                                    raw = rawdata_split[ind] + newpacket  # reconstruct the data
                                    # print('raw', raw)
                                    data = create_datadict(device=devicename_redvypr,packetid=devicename)
                                    data['t' ] = tnewpacket
                                    data['data'] = raw
                                    data['comport'] = serial_device.name
                                    data['bytes_read'] = bytes_read
                                    data['sentences_read'] = sentences_read
                                    #print('data',data)
                                    dataqueue.put(data)

                            rawdata_all = rawdata_split[-1]

        if ((time.time() - tnewpacket) > dt_maxwait) and (dt_maxwait > 0):
            logger.warning('Did not find valid packet on serial device {:s}'.format(serial_name))
            data = create_datadict(device=devicename_redvypr,packetid=devicename)
            data['t'] = time.time()
            data['comport'] = serial_device.name
            data['status'] = 'timout (dt_maxwait)'
            #statusqueue.put(data)
            dataqueue.put(data)
            return

        if ((time.time() - t_update) > dt_update):
            dbytes = bytes_read - bytes_read_old
            bytes_read_old = bytes_read
            bps = dbytes / dt_update  # bytes per second
            data = create_datadict(device=devicename_redvypr,packetid=devicename)
            data['t'] = time.time()
            data['comport'] = serial_device.name
            data['bps'] = bps
            data['bytes_read'] = bytes_read
            dataqueue.put(data)
            #statusqueue.put(data)
            # print('ndata',len(rawdata_all),'rawdata',rawdata_all,type(rawdata_all))
            # print('bps',bps)
            t_update = time.time()

def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Starting reading serial data')
    logger.debug('Will open comports {:s}'.format(str(config['serial_devices'])))

    serial_threads = []
    serial_threads_datainqueues = []
    dt_poll = 0.05
    for comportconfig in config['serial_devices']:
        logger.debug('Processing device {}'.format(comportconfig['devicename']))
        if comportconfig['use_device'] == False:
            logger.debug('Ignoring device {}'.format(comportconfig['devicename']))
        else:
            logger.debug('Configuring device {}'.format(comportconfig['devicename']))
            queuesize = 100
            config_thread = copy.deepcopy(comportconfig)
            datainqueue_thread = queue.Queue(maxsize=queuesize)
            serial_threads_datainqueues.append(datainqueue_thread)
            args = [device_info,config_thread,dataqueue,datainqueue_thread,statusqueue]
            serial_thread = threading.Thread(target=read_serial, args=args, daemon=True)
            serial_threads.append(serial_thread)
            logger.debug('Starting thread with config: {:s}'.format(str(config_thread)))
            serial_thread.start()

    while True:
        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if (data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            # logger.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                if command == 'stop':
                    sstr = funcname + ': Command is for me: {:s}'.format(str(command))
                    logger.debug(sstr)
                    # Sending stop command to the threads
                    for datainqueue in serial_threads_datainqueues:
                        datainqueue.put('stop')

                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass
                    return

        # Check if any of the threads is running, if not stop main thread as well
        all_dead = True
        for serial_thread in serial_threads:
            if serial_thread.is_alive():
                all_dead = False
                break

        if all_dead:
            return

        time.sleep(dt_poll)





class Device(RedvyprDevice):
    """
    heatflow_serial device
    """

    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)
        logger.debug(funcname)
        self.get_comports()

    def thread_start(self):
        try:
            self.deviceinitwidget.widgets_to_config()
        except:
            logger.debug('Could not init using gui settings',exc_info=True)
        super().thread_start()

    def get_comports(self):
        funcname = __name__ + '.get_comports():'
        logger.debug(funcname)
        comports = serial.tools.list_ports.comports()
        self.comports = []
        serial_devices_new = []
        for comport in comports:
            FLAG_DEVICE_EXISTS = False
            for d in self.custom_config.serial_devices:
                if comport.device == d.device:
                    logger.debug(funcname + ' Found new device {}'.format(d.device))
                    FLAG_DEVICE_EXISTS = True
                    serial_devices_new.append(d)
                    self.comports.append(comport)
                    break

            if re.match(self.custom_config.ignore_devices,comport.device):
                logger.info('Ignoring device {}'.format(comport.device))
            else:
                if FLAG_DEVICE_EXISTS == False:
                    devicename = comport.device.split('/')[-1]
                    config = SerialDeviceCustomConfig(device=comport.device, devicename=devicename)
                    #self.config.serial_devices.append(config)
                    serial_devices_new.append(config)
                    self.comports.append(comport)

        self.custom_config.serial_devices = serial_devices_new
        logger.debug(funcname + ' serial devices {}'.format(self.custom_config.serial_devices))


class initDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        self.device   = device
        #self.serialwidget = QtWidgets.QWidget()
        self.serialwidgets_parent = QtWidgets.QWidget()
        layout_all = QtWidgets.QGridLayout(self.serialwidgets_parent)
        self.layout_serialwidgets = layout_all
        self.serialwidgets = []
        self.label= QtWidgets.QLabel("Serial device")

        self.comscanbutton = QtWidgets.QPushButton("Rescan comports")
        self.comscanbutton.clicked.connect(self.comscan_clicked)
        # self.comscanbutton.setCheckable(True)
        layout.addWidget(self.comscanbutton)


        self.init_serialwidgets()
        layout.addWidget(self.serialwidgets_parent)

        self.startbutton = QtWidgets.QPushButton("Start")
        self.startbutton.clicked.connect(self.start_clicked)
        self.startbutton.setCheckable(True)
        layout.addWidget(self.startbutton)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def comscan_clicked(self):
        funcname = __name__ + '.comscan_clicked()'
        logger.debug(funcname)
        self.device.get_comports()
        layout = self.layout_serialwidgets
        for i in reversed(range(layout.count())):
            layout.itemAt(i).widget().setParent(None)
        self.init_serialwidgets()
        # Redraw also the devicedisplaywidget
        self.device.devicedisplaywidget.populate_statustable()


    def init_serialwidgets(self):
        layout_all = self.layout_serialwidgets
        layout_all.addWidget(QtWidgets.QLabel('Comport'), 0, 0)
        layout_all.addWidget(QtWidgets.QLabel('Devicename'), 0, 1)
        layout_all.addWidget(QtWidgets.QLabel('Baud'), 0, 2)
        layout_all.addWidget(QtWidgets.QLabel('Parity'), 0, 3)
        layout_all.addWidget(QtWidgets.QLabel('Databits'), 0, 4)
        layout_all.addWidget(QtWidgets.QLabel('Stopbits'), 0, 5)
        #layout_all.addWidget(QtWidgets.QLabel('Packet start'), 0, 6)
        layout_all.addWidget(QtWidgets.QLabel('Packet delimiter'), 0, 7)
        layout_all.addWidget(QtWidgets.QLabel('Packet size'), 0, 8)
        layout_all.addWidget(QtWidgets.QLabel('Metadata'), 0, 9)
        layout_all.addWidget(QtWidgets.QLabel('Use port'), 0, 10)
        lwidth = 80 # width of the qlineedits

        for irow,serial_device in enumerate(self.device.custom_config.serial_devices):
            widget = QtWidgets.QWidget()
            serialwidgetdict = {}
            serialwidgetdict['widget'] = widget
            serialwidgetdict['serial_device'] = serial_device
            self.serialwidgets.append(serialwidgetdict)
            layout = QtWidgets.QGridLayout(widget)
            # Serial baud rates
            #baud = [300, 600, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 576000, 921600]
            baudrates = self.device.custom_config.baud_standard
            # find the index of the baudrate of the device, if its none add it to the list
            try:
                ibaud = baudrates.index(serial_device.baud)
            except:
                baudrates.append(serial_device.baud)
                baudrates.sort()
                ibaud = baudrates.index(serial_device.baud)

            serialwidgetdict['combo_serial_devices'] = QtWidgets.QLabel(serial_device.device)
            # self._combo_serial_devices.currentIndexChanged.connect(self._serial_device_changed)
            serialwidgetdict['combo_serial_baud'] = QtWidgets.QComboBox()
            for b in baudrates:
                serialwidgetdict['combo_serial_baud'].addItem(str(b))

            serialwidgetdict['combo_serial_baud'].setCurrentIndex(ibaud)
            # creating a line edit to give the user the choice to edit a baudrate
            edit = QtWidgets.QLineEdit(self)
            onlyInt = QtGui.QIntValidator()
            edit.setValidator(onlyInt)
            # setting line edit
            serialwidgetdict['combo_serial_baud'].setLineEdit(edit)

            devicename = serial_device.devicename
            serialwidgetdict['devicename'] = QtWidgets.QLineEdit()
            serialwidgetdict['devicename'].setText(devicename)

            serialwidgetdict['combo_parity'] = QtWidgets.QComboBox()
            serialwidgetdict['combo_parity'].addItem('None')
            serialwidgetdict['combo_parity'].addItem('Odd')
            serialwidgetdict['combo_parity'].addItem('Even')
            serialwidgetdict['combo_parity'].addItem('Mark')
            serialwidgetdict['combo_parity'].addItem('Space')

            serialwidgetdict['combo_stopbits'] = QtWidgets.QComboBox()
            serialwidgetdict['combo_stopbits'].addItem('1')
            serialwidgetdict['combo_stopbits'].addItem('1.5')
            serialwidgetdict['combo_stopbits'].addItem('2')

            serialwidgetdict['combo_databits'] = QtWidgets.QComboBox()
            serialwidgetdict['combo_databits'].addItem('8')
            serialwidgetdict['combo_databits'].addItem('7')
            serialwidgetdict['combo_databits'].addItem('6')
            serialwidgetdict['combo_databits'].addItem('5')

            serialwidgetdict['button_serial_openclose'] = QtWidgets.QPushButton('Use')
            serialwidgetdict['button_serial_openclose'].setCheckable(True)
            serialwidgetdict['button_serial_openclose'].setChecked(serial_device.use_device)
            serialwidgetdict['button_serial_openclose'].clicked.connect(self.use_device_clicked)

            serialwidgetdict['button_metadata'] = QtWidgets.QPushButton('Metadata')
            serialwidgetdict['button_metadata'].clicked.connect(self.__metadata_clicked)
            serialwidgetdict['button_metadata'].__index_serial = irow

            # Define packet delimiter
            packet_del = serial_device.packetdelimiter
            serialwidgetdict['packet_ident_lab'] = QtWidgets.QLabel('Packet identification')
            serialwidgetdict['packet_ident'] = QtWidgets.QComboBox()
            idel_index = -1
            for idel, d in enumerate(packet_delimiter):
                if packet_del == d:
                    idel_index = idel
                elif idel == len(packet_delimiter) - 1:
                    if len(packet_del) > 0 and (idel_index==-1):
                        d = packet_del
                        idel_index = idel

                serialwidgetdict['packet_ident'].addItem(d)

            if idel_index >=0:
                serialwidgetdict['packet_ident'].setCurrentIndex(idel_index)
            serialwidgetdict['packet_ident'].setEditable(True)

            #.currentTextChanged.connect(self.current_text_changed)
            serialwidgetdict['packet_ident_lineedit'] = serialwidgetdict['packet_ident'].lineEdit()
            serialwidgetdict['packet_ident_lineedit'].__combo__ = serialwidgetdict['packet_ident']
            serialwidgetdict['packet_ident_lineedit'].textEdited.connect(self.handle_delimiter_text_edited)

            #serialwidgetdict['packet_ident'].setText(packet_del)
            #serialwidgetdict['packet_ident'].setFixedWidth(lwidth)
            # Set the tooltip
            desc = serial_device.model_fields['packetdelimiter'].description
            serialwidgetdict['packet_ident'].setToolTip(desc)

            #packet_start = serial_device.packetstart
            ## Handle new line character
            #packet_start = packet_start.replace('\n','\\n')
            #serialwidgetdict['packet_start_lab'] = QtWidgets.QLabel('Packet start')
            #serialwidgetdict['packet_start'] = QtWidgets.QLineEdit()
            #serialwidgetdict['packet_start'].setText(packet_start)
            #serialwidgetdict['packet_start'].setFixedWidth(lwidth)
            # Set the tooltip
            #desc = serial_device.model_fields['packetstart'].description
            #serialwidgetdict['packet_start'].setToolTip(desc)
            # Max packetsize
            serialwidgetdict['packet_size_lab'] = QtWidgets.QLabel("Maximum packet size")
            onlyInt = QtGui.QIntValidator()
            packet_size = str(serial_device.chunksize)
            serialwidgetdict['packet_size'] = QtWidgets.QLineEdit()
            serialwidgetdict['packet_size'].setValidator(onlyInt)
            serialwidgetdict['packet_size'].setText(packet_size)
            serialwidgetdict['packet_size'].setFixedWidth(lwidth)
            # Set the tooltip
            desc = serial_device.model_fields['chunksize'].description
            serialwidgetdict['packet_size'].setToolTip(desc)

            #layout.addWidget(serialwidgetdict['packet_start'], 2, 1)
            #layout.addWidget(serialwidgetdict['packet_start_lab'], 2, 0)
            layout.addWidget(serialwidgetdict['packet_ident'], 2, 1+2)
            layout.addWidget(serialwidgetdict['packet_ident_lab'], 2, 0+2)
            layout.addWidget(serialwidgetdict['packet_size_lab'], 2, 2+2)
            layout.addWidget(serialwidgetdict['packet_size'], 2, 3+2)

            layout_all.addWidget(serialwidgetdict['combo_serial_devices'], irow+1, 0)
            layout_all.addWidget(serialwidgetdict['devicename'], irow + 1, 1)
            layout_all.addWidget(serialwidgetdict['combo_serial_baud'], irow+1, 2)
            layout_all.addWidget(serialwidgetdict['combo_parity'], irow+1, 3)
            layout_all.addWidget(serialwidgetdict['combo_databits'], irow+1, 4)
            layout_all.addWidget(serialwidgetdict['combo_stopbits'], irow+1, 5)
            #layout_all.addWidget(serialwidgetdict['packet_start'], irow + 1, 6)
            layout_all.addWidget(serialwidgetdict['packet_ident'], irow + 1, 7)
            layout_all.addWidget(serialwidgetdict['packet_size'], irow + 1, 8)
            layout_all.addWidget(serialwidgetdict['button_metadata'], irow+1, 9)
            layout_all.addWidget(serialwidgetdict['button_serial_openclose'], irow+1, 10)

            #self.statustimer = QtCore.QTimer()
            #self.statustimer.timeout.connect(self.update_buttons)
            #self.statustimer.start(500)

        layout_all.setRowStretch(layout_all.rowCount(), 1)

    def __metadata_clicked(self):
        funcname = __name__ + '.__metadata_clicked():'
        logger.debug(funcname)
        self.widgets_to_config()
        irow = self.sender().__index_serial
        serial_device = self.device.custom_config.serial_devices[irow]
        devicename = serial_device.devicename
        devicename_redvypr = self.device.name

        metadata_device = copy.deepcopy(self.device.statistics['metadata'])
        deviceAddress = RedvyprAddress(devicename=self.device.name,packetid=devicename)
        try:
            metadata_raw = metadata_device[deviceAddress.address_str]
        except:
            logger.info('Could not load metadata', exc_info=True)
            metadata_raw = {}

        metadata = RedvyprSerialDeviceMetadata(**metadata_raw)
        print('Metadata', metadata)

        self.__metadata_edit = metadata
        self.__metadata_address = deviceAddress
        self.metadata_config = pydanticConfigWidget(metadata, configname=deviceAddress.address_str)
        self.metadata_config.config_editing_done.connect(self.__metadata_config_apply)
        self.metadata_config.setWindowTitle('redvypr, Metadata for {}'.format(devicename))
        self.metadata_config.show()

    def __metadata_config_apply(self):
        funcname = __name__ + '__metadata_config_apply():'
        logger.debug(funcname)

        #print('Metadata new', self.__metadata_edit)
        metadata = self.__metadata_edit.model_dump()
        self.device.set_metadata(self.__metadata_address, metadata)

    def handle_delimiter_text_edited(self, text):

        comboBox = self.sender().__combo__
        line_edit = self.sender()
        current_index = comboBox.currentIndex()
        nitems = comboBox.count()
        # Check of items shall be edited?
        #print('Hallo',current_index,nitems)
        if current_index != (nitems -1):  # Check if last item
            original_text = comboBox.itemText(current_index)
            #print('Not editable',original_text)
            line_edit.setText(original_text)
        else: # editable item
            pass

    def use_device_clicked(self):
        button = self.sender()
        if button.isChecked():
            button.setText('Use')
        else:
            button.setText('Ignore')
    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']

        if(thread_status):
            self._button_serial_openclose.setText('Close')
            self._combo_serial_baud.setEnabled(False)
            self._combo_serial_devices.setEnabled(False)
        else:
            self._button_serial_openclose.setText('Open')
            self._combo_serial_baud.setEnabled(True)
            self._combo_serial_devices.setEnabled(True)
        

    def widgets_to_config(self):
        """
        Copies the widget data to the configuration
        """
        funcname = __name__ + '.widgets_to_config()'
        logger.debug(funcname)
        # print('hallo',len(self.serialwidgets))
        configs = []
        for w in self.serialwidgets:
            serial_device = w['serial_device']
            config = {}
            serial_name = str(w['combo_serial_devices'].text())
            serial_device.device = serial_name
            devicename = str(w['devicename'].text())
            serial_device.devicename = devicename
            serial_baud = int(w['combo_serial_baud'].currentText())
            serial_device.baud = serial_baud
            stopbits = w['combo_stopbits'].currentText()
            if (stopbits == '1'):
                serial_device.stopbits = serial.STOPBITS_ONE
            elif (stopbits == '1.5'):
                serial_device.stopbits = serial.STOPBITS_ONE_POINT_FIVE
            elif (stopbits == '2'):
                serial_device.stopbits = serial.STOPBITS_TWO

            databits = int(w['combo_databits'].currentText())
            serial_device.bytesize = databits

            parity = w['combo_parity'].currentText()
            if (parity == 'None'):
                serial_device.parity = serial.PARITY_NONE
            elif (parity == 'Even'):
                serial_device.parity = serial.PARITY_EVEN
            elif (parity == 'Odd'):
                serial_device.parity = serial.PARITY_ODD
            elif (parity == 'Mark'):
                serial_device.parity = serial.PARITY_MARK
            elif (parity == 'Space'):
                serial_device.parity = serial.PARITY_SPACE

            #
            serial_device.chunksize = int(w['packet_size'].text())
            serial_device.packetdelimiter = w['packet_ident'].currentText()#.replace('\\n', '\n').replace('\\r', '\r')
            serial_device.packetdelimiter = serial_device.packetdelimiter.replace('CR/LF','\r\n')
            serial_device.packetdelimiter = serial_device.packetdelimiter.replace('LF', '\n')
            serial_device.packetdelimiter = serial_device.packetdelimiter.replace('None', '')
            print(funcname + 'Test',w['packet_ident'].currentText())
            #serial_device.packetstart = w['packet_start'].text()
            if w['button_serial_openclose'].isChecked():
                serial_device.use_device = True
            else:
                serial_device.use_device = False

    def start_clicked(self):
        button = self.sender()
        if ('Start' in button.text()):
            self.widgets_to_config()
            self.device.thread_start()
            button.setText('Stop')
        else:
            self.stop_clicked()

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']
        # Running
        if (thread_status):
            self.startbutton.setText('Stop')
            self.startbutton.setChecked(True)
            #for w in self.config_widgets:
            #    w.setEnabled(False)
        # Not running
        else:
            self.startbutton.setText('Start')
            #for w in self.config_widgets:
            #    w.setEnabled(True)

            # Check if an error occured and the startbutton
            if (self.startbutton.isChecked()):
                self.startbutton.setChecked(False)
            # self.conbtn.setEnabled(True)

    def stop_clicked(self):
        """

        Returns:

        """
        self.device.thread_stop()
        self.startbutton.setText('Closing')


class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        self.device = device
        self.serialwidgets = []
        self.serialwidgetsdict = {}
        self.comporttable = QtWidgets.QTableWidget()
        layout.addWidget(self.comporttable,0,0)
        self.device = device
        self.populate_statustable()


    def populate_statustable(self):
        funcname = __name__ + '.populate_statustable():'
        logger.debug(funcname)
        self.comporttable.clear()
        columns = ['Comport', 'Bytes read', 'Packets read', 'Status', 'Show rawdata']
        self.comporttable.setColumnCount(len(columns))
        self.comporttable.horizontalHeader().ResizeMode(self.comporttable.horizontalHeader().ResizeToContents)
        self.comporttable.setHorizontalHeaderLabels(columns)
        comports = self.device.comports
        self.comporttable.setRowCount(len(comports))
        self.comports = []
        for irow, comport in enumerate(comports):
            self.comports.append(comport.device)
            serialwidgetdict = {}
            serialwidgetdict['datawidget'] = QtWidgets.QPlainTextEdit()
            serialwidgetdict['datawidget'].setReadOnly(True)
            serialwidgetdict['datawidget'].setMaximumBlockCount(10000)
            serialwidgetdict['datawidget'].setWindowIcon(QtGui.QIcon(_icon_file))
            serialwidgetdict['datawidget'].setWindowTitle(comport.device)
            self.serialwidgets.append(serialwidgetdict)
            self.serialwidgetsdict[comport.device] = serialwidgetdict

            item = QtWidgets.QTableWidgetItem(comport.device)
            self.comporttable.setItem(irow, 0, item)
            item = QtWidgets.QTableWidgetItem('0')
            self.comporttable.setItem(irow, 1, item)
            item = QtWidgets.QTableWidgetItem('0')
            self.comporttable.setItem(irow, 2, item)
            # Status
            item = QtWidgets.QTableWidgetItem('closed')
            self.comporttable.setItem(irow, 3, item)

            button = QtWidgets.QPushButton('Show')
            button.clicked.connect(self.__showdata__)
            button.displaywidget = serialwidgetdict['datawidget']
            self.comporttable.setCellWidget(irow, 4, button)

        self.comporttable.resizeColumnsToContents()

    def __showdata__(self):
        """
        Opens the raw data widget
        """
        button = self.sender()

        button.displaywidget.show()
        button.displaywidget.setFocus()
        button.displaywidget.raise_()
        button.displaywidget.activateWindow()
        #try:
        #    isshowing = button.showing
        #except:
        #    isshowing = False#

        #if not(isshowing):
        #    button.setText('Hide')
        #    button.showing = True
        #    button.displaywidget.show()
        #else:
        #    button.showing = False
        #    button.setText('Show')
        #    button.displaywidget.hide()
    def update_data(self, data):
        #print('data',data)
        try:
            comport = data['comport']
            datawidget = self.serialwidgetsdict[comport]['datawidget']
        except:
            return

        try:
            status = data['status']
            index = self.comports.index(comport)
            itemstatus = QtWidgets.QTableWidgetItem(status)
            self.comporttable.setItem(index, 3, itemstatus)
        except:
            pass
        try:
            index = self.comports.index(comport)
            bstr = "{:d}".format(data['bytes_read'])
            lstr = "{:d}".format(data['sentences_read'])
            itemb = QtWidgets.QTableWidgetItem(bstr)
            items = QtWidgets.QTableWidgetItem(lstr)
            itemstatus = QtWidgets.QTableWidgetItem('open')
            self.comporttable.setItem(index, 1, itemb)
            self.comporttable.setItem(index, 2, items)
            self.comporttable.setItem(index, 3, itemstatus)

        except Exception as e:
            # logger.exception(e)
            pass

        try:
            datawidget.insertPlainText(str(data['data']))
            datawidget.insertPlainText('\n')
        except Exception as e:
            #logger.exception(e)
            pass
        
