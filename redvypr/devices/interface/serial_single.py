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
import pydantic
import typing
import threading
import redvypr
import yaml
import redvypr.files as redvypr_files
from redvypr.data_packets import check_for_command, create_datadict
from redvypr.redvypr_address import RedvyprAddress
from redvypr.device import RedvyprDevice
#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict


yaml.add_constructor(
    u"tag:yaml.org,2002:python/name:builtins.NoneType",
    lambda loader, suffix: type(None),
    Loader=yaml.CUnsafeLoader,
)


_logo_file = redvypr_files.logo_file
_icon_file = redvypr_files.icon_file
description = 'Reading data from a serial device'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.serial_single')
logger.setLevel(logging.DEBUG)


packet_start = ['<None>','$','custom']
packet_delimiter = ['None','CR/LF','LF','custom']
baud_standard: list = [300, 600, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 691200, 921600]


class SerialDeviceConfig(pydantic.BaseModel):
    """
    Hardware configuration of a serial device
    """
    use_device: bool = pydantic.Field(default=True,
                                      description='Flag if the device should be used')
    comport_device: str = pydantic.Field(default='')
    comport_device_short: typing.Optional[str] = pydantic.Field(default='',
                                                                description="short devicename of the comport, used in linux systems to get rid of the path")
    baud: int = pydantic.Field(default=2400)
    parity: typing.Literal[serial.PARITY_NONE, serial.PARITY_ODD, serial.PARITY_EVEN, serial.PARITY_MARK, serial.PARITY_SPACE] = pydantic.Field(default=serial.PARITY_NONE)
    stopbits: typing.Literal[serial.STOPBITS_ONE, serial.STOPBITS_ONE_POINT_FIVE,serial.STOPBITS_TWO] = pydantic.Field(default=serial.STOPBITS_ONE)
    bytesize: typing.Literal[serial.EIGHTBITS, serial.SEVENBITS, serial.SIXBITS] = pydantic.Field(default=serial.EIGHTBITS)
    comport_packetid_format: str = pydantic.Field(default='serial_{device_short}',
                                                  description="Formatstring of the packetid of the comport, can be edited")
    comport_packetid: str = pydantic.Field(default='', description="Packetid of the comport. Created by applying comport_packetid_format")
    serial_number:  typing.Optional[str] = pydantic.Field(default='', description="Serial number of the comport")
    vid:  typing.Optional[str] = pydantic.Field(default='', description="vid of the comport")
    pid:  typing.Optional[str] = pydantic.Field(default='', description="pid of the comport")
    manufacturer:  typing.Optional[str] = pydantic.Field(default='', description="Manufacturer of the comport")
    comport_compare: typing.Optional[
        typing.List[typing.Literal["device","serial_number","vid","pid","manufactuer"]]] = pydantic.Field(default=["device"])

    def create_packetid_device_short(self):
        device_short = self.comport_device.split('/')[-1]
        self.comport_packetid = self.comport_packetid_format.format(device_short=device_short,
                                                                    device=self.comport_device,
                                                                    vid=self.vid,
                                                                    pid=self.pid,
                                                                    serial_number=self.serial_number,
                                                                    manufacturer=self.manufacturer)
        self.comport_device_short = device_short
        #return self.comport_packetid


class SerialDeviceConfigRedvypr(SerialDeviceConfig):
    """
    Extended config for redvypr specific configuration used by the serial thread
    """
    receive_data: bool = pydantic.Field(default=True,
                                      description='Flag if the device shall receive data')
    send_data: bool = pydantic.Field(default=True,
                                     description='Flag if the device shall send data')
    dt_poll: float = 0.05
    dt_maxwait: float = pydantic.Field(default=-1.0,description='Wait time in s for valid data, if time without a valid packets exceeds dt_maxwait the comport is closed and the read thread is stopped')
    send_mode: typing.Literal["raw", "redvypr_datapacket"] = pydantic.Field(
        default="raw",
        description="The mode for data sending, raw for , redvypr_datapacket to send redvpyr datapackets")
    send_data_address: RedvyprAddress = pydantic.Field(default=RedvyprAddress("@"),description='The address of the data to be sent')
    send_serializer: typing.Literal["utf-8", "redvypr_datapacket"] = pydantic.Field(default="utf-8",description="Mode of data conversion to binary format")
    recv_mode: typing.Literal["raw","redvypr_datapacket"] = pydantic.Field(default="raw",description="The mode for data reception, raw for serial data, redvypr_datapacket to read redvpyr datapackets")
    datakey_recv_raw: str = pydantic.Field(default="data",
                                    description='The datakey in the redvype packet for the received raw data')
    chunksize: int = pydantic.Field(default=-1, description='The maximum amount of bytes read with one chunk')
    packetdelimiter: str = pydantic.Field(default='LF', description='The delimiter to distinguish packets, leave empty to disable')
    packetstart: str = pydantic.Field(default='', description='The delimiter to distinguish packets, leave empty to disable')
    comport_nread: int = pydantic.Field(default=512, description='The amount of bytes read maximum within one ser.read() call')
    comport_timeout: float = pydantic.Field(default=0.01, description='The timout [s] if not comport_nread bytes have been read ')
    calc_recv_time: bool = pydantic.Field(default=True,
                                     description='Flag if the device shall compute '
                                                 '(approximately) the receive time of '
                                                 'the bytes. This is done by calculating'
                                                 ' the transmission per byte together '
                                                 'with the receive time of a chunk of bytes')
    command_history: list = pydantic.Field(default_factory=list,
                                           description='List of command data sent to the device')

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Reads to and write from a serial device'
    gui_tablabel_display: str = 'Serial data'

class DeviceCustomConfig(SerialDeviceConfigRedvypr):
    """Alias for Redvypr config to be used in generic device contexts."""
    pass

redvypr_devicemodule = True


def read_serial(config: SerialDeviceConfigRedvypr, queue_data_read, queue_data_send, queue_thread_command ):
    """
    The function that actually reads from the serial port
    Parameters
    ----------
    config
    queue_data_read
    queue_data_send
    queue_thread_command

    Returns
    -------

    """
    # Setup serial connection
    dt_timeout = config["comport_timeout"]
    nread = config["comport_nread"]
    baud = config["baud"]
    port = config["comport_device"]
    comport_device = config["comport_device"]
    parity = config["parity"]
    stopbits = config["stopbits"]
    bytesize = config["bytesize"]
    ser = serial.Serial(
        port=port,
        baudrate=baud,
        parity=parity,
        stopbits=stopbits,
        bytesize=bytesize,
        timeout=dt_timeout
    )

    if not ser.is_open:
        ser.open()


    while True:
        current_time = time.time()
        data = ser.read(nread)
        queue_data_read.put([data,current_time,ser.name,comport_device])
        try:
            data_send = queue_data_send.get_nowait()
            #print(f"Sending data to serial device {ser.name}")
            ser.write(data_send)
        except:
            pass

        try:
            queue_thread_command.get_nowait()
            return
        except:
            pass



def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Starting reading serial data')
    pdconfig = SerialDeviceConfigRedvypr.model_validate(config)
    pdconfig.create_packetid_device_short()
    packetid = pdconfig.comport_packetid
    chunksize = pdconfig.chunksize #The maximum amount of bytes read with one chunk
    dt_poll = pdconfig.dt_poll
    devicename_redvypr = device_info['device']

    logger_start = logging.getLogger('redvypr.device.serial_single.start')

    loglevel = device_info['device_config']['base_config']['loglevel']
    #print("Loglevel",loglevel)
    logger_start.setLevel(loglevel)
    logger_start.debug(f"Starting ...\n")
    logger_start.debug(f"Starting with device_info:{device_info}")
    logger_start.debug(f"Starting with config:{config}")
    logger_start.debug(f"Starting ...\n")

    #print("pdfonfig",pdconfig)
    #print("packetid",packetid)
    flag_send_data = config['send_data']
    raddress_send = RedvyprAddress(config['send_data_address'])
    send_mode = config['send_mode']

    #print('Starting',config)

    
    newpacket = pdconfig.packetdelimiter
    newpacket = newpacket.replace('CR/LF','\r\n')
    newpacket = newpacket.replace('LF','\n')
    newpacket = newpacket.replace('None','')
    # Check if a delimiter shall be used (\n, \r\n, etc ...)
    if(len(newpacket)>0):
        FLAG_DELIMITER = True
    else:
        FLAG_DELIMITER = False
    if(type(newpacket) is not bytes):
        newpacket = newpacket.encode('utf-8')
        
    rawdata_all = b''
    dt_update = 1 # Update interval in seconds
    bytes_read = 0
    sentences_read = 0
    bytes_sent = 0
    sentences_sent = 0
    bytes_read_old = 0 # To calculate the amount of bytes read per second

    queuesize = 10000
    queue_data_read_thread = queue.Queue(maxsize=queuesize)
    queue_data_send_thread = queue.Queue(maxsize=queuesize)
    queue_command_thread = queue.Queue(maxsize=queuesize)
    args = [config, queue_data_read_thread, queue_data_send_thread, queue_command_thread]
    serial_thread = threading.Thread(target=read_serial, args=args, daemon=True)
    logger_start.debug('Starting serial read/write thread of comport: {serial_name}')
    serial_thread.start()

    t_update = time.time()
    while True:
        try:
            data = datainqueue.get(block=False)
        except:
            data = None


        if (data is not None):
            if data == 'stop':
                command = 'stop'
            else:
                #command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
                [command, comdata] = check_for_command(data, thread_uuid=device_info[
                    'thread_uuid'], add_data=True)
            # logger_start.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                if command == 'stop':
                    queue_command_thread.put('stop')
                    sstr = funcname + ': Command is for me: {:s}'.format(str(command))
                    logger_start.debug(sstr)
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass
                    return
                elif command == 'send':  # Something to send
                    data_com = comdata['command_data']['data']
                    comport = data_com['comport']
                    data_send = data_com['data_send']
                    print("Got a send command, sending", data_send)
                    bytes_sent += len(data_send)
                    sentences_sent += 1
                    queue_data_send_thread.put(data_send)
            elif flag_send_data and raddress_send.matches(data):
                #print("Sending datapacket")
                #print("data",data)
                if send_mode == 'raw':
                    datasend_raw = raddress_send(data)
                    datasend_raw = str(datasend_raw).encode('utf-8')
                    #print("Sending datakey", datasend_raw)
                    queue_data_send_thread.put(datasend_raw)
                    bytes_sent += len(datasend_raw)
                    sentences_sent += 1
                elif send_mode == "redvypr_datapacket": # Serialize whole packet
                    datasend_raw = yaml.dump(data, explicit_end=True, explicit_start=True)
                    datasend_raw = str(datasend_raw).encode('utf-8')
                    #print("Sending packet",datasend_raw)
                    queue_data_send_thread.put(datasend_raw)
                    bytes_sent += len(datasend_raw)
                    sentences_sent += 1


        time.sleep(dt_poll)
        rawdata_tmp = b''
        while True:
            try:
                [rawdata_tmptmp,time_tmp,serial_port, comport_device] = queue_data_read_thread.get_nowait()
                rawdata_tmp += rawdata_tmptmp
            except:
                break

        nread = len(rawdata_tmp)
        if True:
            if nread > 0:
                bytes_read  += nread
                rawdata_all += rawdata_tmp
                #print('rawdata_all',rawdata_all)
                if chunksize > 0:
                    FLAG_CHUNK = len(rawdata_all) > chunksize
                    if(FLAG_CHUNK):
                        data = create_datadict(device=devicename_redvypr,
                                               packetid=packetid)
                        data['t'] = time.time()
                        data['data'] = rawdata_all
                        data['comport'] = comport_device
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
                                data = create_datadict(device=devicename_redvypr,
                                                       packetid=packetid)
                                data['t'] = time.time()
                                data[pdconfig.datakey_recv_raw] = raw
                                data['comport'] = comport_device
                                data['bytes_read'] = bytes_read
                                data['sentences_read'] = sentences_read
                                #print("publishing",data)
                                #print(f"packetid={packetid} device:{devicename_redvypr}")
                                dataqueue.put(data)

                            rawdata_all = rawdata_split[-1]
        
        if((time.time() - t_update) > dt_update):
            dbytes = bytes_read - bytes_read_old
            bytes_read_old = bytes_read
            bps = dbytes/dt_update# bytes per second
            # Send status message
            data = {'t': time.time()}
            data['status'] = comport_device
            data['comport'] = comport_device
            data['bytes_read'] = bytes_read
            data['sentences_read'] = sentences_read
            data['bytes_sent'] = bytes_sent
            data['sentences_sent'] = sentences_sent
            data['bps'] = bps
            dataqueue.put(data)
            #print('ndata',len(rawdata_all),'rawdata',rawdata_all,type(rawdata_all))
            #print('bps',bps)
            t_update = time.time()


class Device(RedvyprDevice):
    """
    calibration device
    """

    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)
        logger.debug(funcname)
        # Connect thread start/stop signals to subscribe functions
        self.thread_started.connect(self.subscribe_to_sensors)
        self.thread_stopped.connect(self.unsubscribe_all)

    def subscribe_to_sensors(self):
        funcname = __name__ + '.subscribe_to_sensors():'
        logger.debug(funcname)
        self.unsubscribe_all()
        if self.custom_config.send_data:
            datastream = self.custom_config.send_data_address
            logger.info(f"{funcname} subscribing to {datastream}")
            self.subscribe_address(datastream)



class SerialDeviceWidget(QtWidgets.QWidget):
    """
    A generic PyQt6 Widget to configure SerialDeviceConfig objects.
    Includes Tooltips and detailed hardware information popups.
    """
    config_changed = QtCore.pyqtSignal(bool)

    # Central definition of available placeholders for consistency
    FORMAT_INFO = (
        "Available placeholders for ID Format:\n"
        "• {device} - Full system path\n"
        "• {device_short} - Just the name (e.g. ttyUSB0)\n"
        "• {vid} - Vendor ID\n"
        "• {pid} - Product ID\n"
        "• {serial_number} - Device serial\n"
        "• {manufacturer} - Manufacturer name"
    )

    def __init__(self, config=None,
                 parent=None,
                 add_usedevice=False,
                 fix_serial_device=True,
                 add_packetid=False):
        super().__init__(parent)
        self.config = config
        self.add_packetid = add_packetid
        self.add_usedevice = add_usedevice
        self.fix_serialdevice = fix_serial_device
        self._port_objects = {}

        self._setup_ui()
        self._populate_options()
        self._refresh_serial_devices()

        # Ensure we have a config object
        if self.config is None:
            # Note: Ensure SerialDeviceConfig is available in your namespace
            self.config = SerialDeviceConfig(baud=4800)

        # Initial generation of the ID and UI sync
        self._update_packetid_display()
        self._sync_config_to_ui()
        self._on_device_changed(self.combo_device.currentText())

    def _use_device_toggled(self, flag_use_device):
        print("Use device",flag_use_device)
        self.config.use_device = flag_use_device
        for w in self.inputwidgets:
            w.setEnabled(flag_use_device)

    def _setup_ui(self):
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(5)

        self.grid_layout = QtWidgets.QGridLayout()
        self.grid_layout.setSpacing(8)

        # Labels
        labels = ["", "Port", "Baud", "Parity", "Data", "Stop", "ID Format",
                  "Resulting Packet ID"]

        if self.add_usedevice == False:
            #labels.pop(0)
            self.chk_use_device = None
        else:
            self.chk_use_device = QtWidgets.QCheckBox("Use Device")
            self.chk_use_device.setChecked(self.config.use_device)
            self.chk_use_device.toggled.connect(self._use_device_toggled)

        if self.add_packetid == False:
            labels.remove("ID Format")
            labels.remove("Resulting Packet ID")
        for i, text in enumerate(labels):
            lbl = QtWidgets.QLabel(text)
            lbl.setStyleSheet("font-weight: bold; color: #666; font-size: 11px;")
            self.grid_layout.addWidget(lbl, 0, i)

        # Input Widgets
        self.inputwidgets = []
        self.combo_device = QtWidgets.QComboBox()
        if self.fix_serialdevice == False:
            self.inputwidgets.append(self.combo_device)
        else:
            # Change the style
            self.combo_device.setStyleSheet("""
                /* Disabled state: Looks like a flat label or text field */
                QComboBox:disabled {
                    background-color: #f0f0f0;  /* Light gray background */
                    color: black;               /* Keep text black (overrides default gray-out) */
                    border: 1px solid #d3d3d3;  /* Subtle border */
                    padding-right: 2px;         /* Reset padding since the arrow is removed */
                }

                /* Completely eliminate the dropdown button area when disabled */
                QComboBox::drop-down:disabled {
                    width: 0px;
                    border: none;
                }

                /* Make the actual arrow icon invisible when disabled */
                QComboBox::down-arrow:disabled {
                    image: none;
                    border: none;
                }
            """)

            self.combo_device.setEnabled(False)

        self.combo_baud = QtWidgets.QComboBox()
        self.inputwidgets.append(self.combo_baud)
        self.combo_parity = QtWidgets.QComboBox()
        self.inputwidgets.append(self.combo_parity)
        self.combo_databits = QtWidgets.QComboBox()
        self.inputwidgets.append(self.combo_databits)
        self.combo_stopbits = QtWidgets.QComboBox()
        self.inputwidgets.append(self.combo_stopbits)
        if self.add_packetid:
            self.lineedit_format = QtWidgets.QLineEdit()
            self.inputwidgets.append(self.lineedit_format)
            # Add the Info-Tooltip to the format field
            self.lineedit_format.setToolTip(self.FORMAT_INFO)

            self.lineedit_packetid = QtWidgets.QLineEdit()
            self.inputwidgets.append(self.lineedit_packetid)
            self.lineedit_packetid.setReadOnly(True)
            self.lineedit_packetid.setStyleSheet("""
                QLineEdit {
                    background-color: #f4f4f4; 
                    border: 1px solid #ddd; 
                    color: #b22222; 
                    font-weight: bold;
                }
                QLineEdit:disabled {
                    background-color: #e0e0e0; 
                    color: #888888;           
                    border: 1px solid #ccc;
                }
            """)

        self.btn_details = QtWidgets.QPushButton("Details")
        self.btn_details.setFixedWidth(65)

        # Widths
        self.combo_device.setMinimumWidth(150)
        self.combo_baud.setFixedWidth(80)
        self.combo_parity.setFixedWidth(70)
        self.combo_databits.setFixedWidth(55)
        self.combo_stopbits.setFixedWidth(55)
        if self.add_packetid:
            self.lineedit_format.setMinimumWidth(120)
            self.lineedit_packetid.setMinimumWidth(180)

        # Grid Placement
        if self.add_usedevice:
            self.grid_layout.addWidget(self.chk_use_device, 1, 0)
        self.grid_layout.addWidget(self.combo_device, 1, 0+1)
        self.grid_layout.addWidget(self.combo_baud, 1, 1+1)
        self.grid_layout.addWidget(self.combo_parity, 1, 2+1)
        self.grid_layout.addWidget(self.combo_databits, 1, 3+1)
        self.grid_layout.addWidget(self.combo_stopbits, 1, 4+1)
        if self.add_packetid:
            self.grid_layout.addWidget(self.lineedit_format, 1, 5+1)
            self.grid_layout.addWidget(self.lineedit_packetid, 1, 6+1)
        self.grid_layout.addWidget(self.btn_details, 1, 7+1)
        # Add stretch
        self.grid_layout.setRowStretch(2, 1)

        self.main_layout.addLayout(self.grid_layout)
        self.extension_layout = QtWidgets.QVBoxLayout()
        self.main_layout.addLayout(self.extension_layout)

        # Signal Connections
        self.combo_device.currentTextChanged.connect(self._on_device_changed)
        self.combo_baud.currentTextChanged.connect(
            lambda t: self._update_config("baud", int(t)))
        self.combo_parity.currentIndexChanged.connect(
            lambda: self._update_config("parity", self.combo_parity.currentData()))
        self.combo_databits.currentIndexChanged.connect(
            lambda: self._update_config("bytesize", self.combo_databits.currentData()))
        self.combo_stopbits.currentIndexChanged.connect(
            lambda: self._update_config("stopbits", self.combo_stopbits.currentData()))
        if self.add_packetid:
            self.lineedit_format.textChanged.connect(self._on_format_changed)
            self.lineedit_format.setPlaceholderText(self.config.comport_packetid_format)
        self.btn_details.clicked.connect(self._show_details)

    def _populate_options(self):
        self.combo_baud.blockSignals(True)
        self.combo_parity.blockSignals(True)
        self.combo_databits.blockSignals(True)
        self.combo_stopbits.blockSignals(True)
        for b in baud_standard:
            self.combo_baud.addItem(str(b), b)
        for n, v in [('None', serial.PARITY_NONE), ('Odd', serial.PARITY_ODD),
                     ('Even', serial.PARITY_EVEN)]:
            self.combo_parity.addItem(n, v)
        for b, v in [(8, serial.EIGHTBITS), (7, serial.SEVENBITS), (6, serial.SIXBITS)]:
            self.combo_databits.addItem(str(b), v)
        for n, v in [('1', serial.STOPBITS_ONE),
                     ('1.5', serial.STOPBITS_ONE_POINT_FIVE),
                     ('2', serial.STOPBITS_TWO)]:
            self.combo_stopbits.addItem(n, v)

        self.combo_baud.blockSignals(False)
        self.combo_parity.blockSignals(False)
        self.combo_databits.blockSignals(False)
        self.combo_stopbits.blockSignals(False)

    def _refresh_serial_devices(self):
        self.combo_device.blockSignals(True)
        self.combo_device.clear()
        self._port_objects.clear()
        for p in serial.tools.list_ports.comports():
            self.combo_device.addItem(p.device)
            self._port_objects[p.device] = p
        self.combo_device.blockSignals(False)

    def _sync_config_to_ui(self):
        if not self.config: return
        c = self.config
        self.blockSignals(True)
        self._set_combo_by_data(self.combo_baud, c.baud)
        self._set_combo_by_data(self.combo_parity, c.parity)
        self._set_combo_by_data(self.combo_databits, c.bytesize)
        self._set_combo_by_data(self.combo_stopbits, c.stopbits)
        idx = self.combo_device.findText(c.comport_device)
        if idx >= 0: self.combo_device.setCurrentIndex(idx)
        if self.add_packetid:
            self.lineedit_format.setText(c.comport_packetid_format or "")
            self.lineedit_packetid.setText(c.comport_packetid or "")
        self.blockSignals(False)

    def _set_combo_by_data(self, combo, data):
        idx = combo.findData(data)
        if idx >= 0: combo.setCurrentIndex(idx)

    def _update_config(self, attr, value):
        if self.config and hasattr(self.config, attr):
            setattr(self.config, attr, value)
            self.config_changed.emit(True)

    def _on_device_changed(self, device_path):
        if not self.config or not device_path: return
        self.config.comport_device = device_path
        p = self._port_objects.get(device_path)
        if p:
            self.config.vid = str(p.vid) if p.vid is not None else ""
            self.config.pid = str(p.pid) if p.pid is not None else ""
            self.config.serial_number = str(p.serial_number) if p.serial_number else ""
            self.config.manufacturer = str(p.manufacturer) if p.manufacturer else ""
        self._update_packetid_display()
        self.config_changed.emit(True)

    def _on_format_changed(self, text):
        if not self.config: return
        self.config.comport_packetid_format = text
        self._update_packetid_display()
        self.config_changed.emit(True)

    def _update_packetid_display(self):
        if self.config:
            try:
                self.config.create_packetid_device_short()
                if self.add_packetid:
                    self.lineedit_packetid.setText(str(self.config.comport_packetid))
            except Exception:
                if self.add_packetid:
                    self.lineedit_packetid.setText("Invalid Format!")

    def _show_details(self):
        if not self.config: return
        # Construct hardware info + the help text for formatters
        details = (
            f"<h3>Hardware Metadata</h3>"
            f"<b>Port:</b> {self.config.comport_device}<br>"
            f"<b>Manufacturer:</b> {self.config.manufacturer}<br>"
            f"<b>VID:</b> {self.config.vid}<br>"
            f"<b>PID:</b> {self.config.pid}<br>"
            f"<b>Serial No:</b> {self.config.serial_number}<br>"
            f"<hr>"
            f"<h4>ID Format Help</h4>"
            f"{self.FORMAT_INFO.replace('\n', '<br>')}"
        )
        QtWidgets.QMessageBox.information(self, "Device Details & Help", details)

    def get_config(self):
        return self.config



class RedvyprConfigWidget(QtWidgets.QWidget):
    """ Separate widget containing all Send/Receive and Thread configurations. """
    changed = QtCore.pyqtSignal(str, object)  # Emits (attribute_name, value)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- General Section ---
        gen_group = QtWidgets.QGroupBox("General Thread Control")
        gen_l = QtWidgets.QHBoxLayout(gen_group)
        self.spin_dt_poll = QtWidgets.QDoubleSpinBox()
        self.spin_dt_poll.setRange(0.001, 1.0)
        self.spin_dt_poll.setDecimals(3)
        self.spin_dt_poll.setSuffix(" s")

        gen_l.addWidget(QtWidgets.QLabel("Poll Interval:"))
        gen_l.addWidget(self.spin_dt_poll)
        gen_l.addStretch()
        layout.addWidget(gen_group)

        # --- Split Section ---
        split_layout = QtWidgets.QHBoxLayout()

        # Receive
        self.recv_group = QtWidgets.QGroupBox("Receive")
        self.recv_group.setCheckable(True)
        recv_l = QtWidgets.QGridLayout(self.recv_group)
        self.combo_recv_mode = QtWidgets.QComboBox()
        self.combo_recv_mode.addItems(["raw", "redvypr_datapacket"])
        self.line_datakey = QtWidgets.QLineEdit()
        self.spin_chunk = QtWidgets.QSpinBox()
        self.spin_chunk.setRange(0, 65535)
        self.combo_start = QtWidgets.QComboBox()
        self.combo_start.setEditable(True)
        self.combo_start.addItems(["<None>", "$"])
        self.combo_end = QtWidgets.QComboBox()
        self.combo_end.setEditable(True)
        self.combo_end.addItems(["None", "CR/LF", "LF"])

        recv_l.addWidget(QtWidgets.QLabel("Mode:"), 0, 0)
        recv_l.addWidget(self.combo_recv_mode, 0, 1)
        recv_l.addWidget(QtWidgets.QLabel("Data Key:"), 2, 0)
        recv_l.addWidget(self.line_datakey, 2, 1)
        recv_l.addWidget(QtWidgets.QLabel("Chunksize:"), 3, 0)
        recv_l.addWidget(self.spin_chunk, 3, 1)
        recv_l.addWidget(QtWidgets.QLabel("Start Delim:"), 4, 0)
        recv_l.addWidget(self.combo_start, 4, 1)
        recv_l.addWidget(QtWidgets.QLabel("End Delim:"), 5, 0)
        recv_l.addWidget(self.combo_end, 5, 1)
        split_layout.addWidget(self.recv_group)

        # Send
        self.send_group = QtWidgets.QGroupBox("Send")
        self.send_group.setCheckable(True)
        send_l = QtWidgets.QGridLayout(self.send_group)
        self.combo_send_mode = QtWidgets.QComboBox()
        self.combo_send_mode.addItems(["raw", "redvypr_datapacket"])
        self.combo_serializer = QtWidgets.QComboBox()
        self.combo_serializer.addItems(["utf-8", "redvypr_datapacket"])
        self.line_send_address = QtWidgets.QLineEdit()
        self.line_send_address.setPlaceholderText("data@")

        send_l.addWidget(QtWidgets.QLabel("Mode:"), 0, 0)
        send_l.addWidget(self.combo_send_mode, 0, 1)
        send_l.addWidget(QtWidgets.QLabel("Serializer:"), 1, 0)
        send_l.addWidget(self.combo_serializer, 1, 1)
        send_l.addWidget(QtWidgets.QLabel("Send Address:"), 2, 0)
        send_l.addWidget(self.line_send_address, 2, 1)
        send_l.setRowStretch(3, 1)
        split_layout.addWidget(self.send_group)

        layout.addLayout(split_layout)
        self._connect_internal_signals()

    def _connect_internal_signals(self):
        self.spin_dt_poll.valueChanged.connect(
            lambda v: self.changed.emit("dt_poll", v))
        self.recv_group.toggled.connect(lambda v: self.changed.emit("receive_data", v))
        self.send_group.toggled.connect(lambda v: self.changed.emit("send_data", v))
        self.combo_recv_mode.currentTextChanged.connect(
            lambda t: self.changed.emit("recv_mode", t))
        self.line_datakey.textChanged.connect(
            lambda t: self.changed.emit("datakey_recv_raw", t))
        self.spin_chunk.valueChanged.connect(
            lambda v: self.changed.emit("chunksize", v))
        self.combo_start.editTextChanged.connect(
            lambda t: self.changed.emit("packetstart", t))
        self.combo_end.editTextChanged.connect(
            lambda t: self.changed.emit("packetdelimiter", t))
        self.combo_send_mode.currentTextChanged.connect(
            lambda t: self.changed.emit("send_mode", t))
        self.combo_serializer.currentTextChanged.connect(
            lambda t: self.changed.emit("send_serializer", t))
        self.line_send_address.textChanged.connect(
            lambda t: self.changed.emit("send_data_address", t))

    def sync_to_ui(self, c):
        self.blockSignals(True)
        self.spin_dt_poll.setValue(c.dt_poll)
        self.recv_group.setChecked(c.receive_data)
        self.send_group.setChecked(c.send_data)
        self.combo_recv_mode.setCurrentText(c.recv_mode)
        self.line_datakey.setText(c.datakey_recv_raw)
        self.spin_chunk.setValue(c.chunksize)
        self.combo_start.setCurrentText(c.packetstart if c.packetstart else "<None>")
        self.combo_end.setCurrentText(
            c.packetdelimiter if c.packetdelimiter else "None")
        self.combo_send_mode.setCurrentText(c.send_mode)
        self.combo_serializer.setCurrentText(c.send_serializer)
        self.line_send_address.setText(str(c.send_data_address))
        self.blockSignals(False)


class SerialDeviceWidgetRedvypr(SerialDeviceWidget):
    def __init__(self, config: SerialDeviceConfigRedvypr | None = None,
                 parent=None,
                 add_packetid=True,
                 fix_serial_device=True,
                 add_usedevice=True,
                 show_sendrecv_config=False):
        if config is None:
            config = SerialDeviceConfigRedvypr()

        self._show_inline = show_sendrecv_config
        super().__init__(config=config,
                         parent=parent,
                         add_packetid=add_packetid,
                         add_usedevice=add_usedevice,
                         fix_serial_device=fix_serial_device)
        # Check if the serial device shall be kept
        if fix_serial_device:
            print("Keeping serial device")


        # Initialize the config widget
        self.redvypr_cfg_widget = RedvyprConfigWidget(self.config)
        self.redvypr_cfg_widget.changed.connect(self._update_config)

        if self._show_inline:
            # Traditional: Add to the extension area (below details)
            self.extension_layout.addWidget(self.redvypr_cfg_widget)
        else:
            # Slim: Add button to header, keep widget hidden for Dialog
            self.btn_redvypr_config = QtWidgets.QPushButton("Send/Recv config")
            self.btn_redvypr_config.clicked.connect(self._show_config_dialog)
            self.inputwidgets.append(self.btn_redvypr_config)
            self.grid_layout.addWidget(self.btn_redvypr_config, 1, 8+1)
            self.redvypr_cfg_widget.hide()

        self._sync_redvypr_config_to_ui()

    def _show_config_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Redvypr serial configuration - {self.config.comport_device_short}")
        dialog.setMinimumWidth(700)

        dlg_layout = QtWidgets.QVBoxLayout(dialog)
        dlg_layout.addWidget(self.redvypr_cfg_widget)
        self.redvypr_cfg_widget.show()

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        btns.accepted.connect(dialog.accept)
        dlg_layout.addWidget(btns)

        dialog.exec_()

        # Reparent back after closing
        self.redvypr_cfg_widget.hide()
        self.redvypr_cfg_widget.setParent(self)

    def _sync_redvypr_config_to_ui(self):
        if self.config:
            self.redvypr_cfg_widget.sync_to_ui(self.config)

    def _update_config(self, attr, value):
        if self.config and hasattr(self.config, attr):
            # Special parsing for Address if needed
            if attr == "send_data_address" and not isinstance(value,
                                                              redvypr.RedvyprAddress):
                try:
                    value = redvypr.RedvyprAddress(value)
                except:
                    pass

            setattr(self.config, attr, value)
            self.config_changed.emit(True)


class HistoryLineEdit(QtWidgets.QLineEdit):
    def __init__(self, parent=None, history=None):
        super().__init__(parent)
        if history is None:
            self.history = []
        else:
            self.history = history
        self.history_index = -1
        self.temp_text = ""

        # Setup Completer
        self.completer_model = QtCore.QStringListModel()
        self.completer = QtWidgets.QCompleter(self.completer_model, self)
        # CaseInsensitive: "hel" findet "HELP"
        self.completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        # Popup-Modus (wie eine Dropdown-Liste beim Tippen)
        self.completer.setCompletionMode(
            QtWidgets.QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(self.completer)

    def keyPressEvent(self, event):
        # Wenn das Completer-Popup offen ist, lassen wir den Completer
        # die Pfeiltasten steuern, damit man dort auswählen kann.
        if self.completer and self.completer.popup() and self.completer.popup().isVisible():
            if event.key() in (QtCore.Qt.Key.Key_Enter, QtCore.Qt.Key.Key_Return):
                # Bei Enter im Popup: Auswahl übernehmen
                super().keyPressEvent(event)
                return

        # Deine bisherige Pfeiltasten-Logik für die Historie
        if event.key() == QtCore.Qt.Key.Key_Up:
            if self.history:
                if self.history_index == -1:
                    self.temp_text = self.text()
                if self.history_index < len(self.history) - 1:
                    self.history_index += 1
                    self.setText(self.history[-(self.history_index + 1)])
            return

        elif event.key() == QtCore.Qt.Key.Key_Down:
            if self.history_index > -1:
                self.history_index -= 1
                if self.history_index == -1:
                    self.setText(self.temp_text)
                else:
                    self.setText(self.history[-(self.history_index + 1)])
            return

        super().keyPressEvent(event)

    def add_to_history(self, text):
        """Fügt Text zur Historie hinzu und aktualisiert den Completer."""
        if text and (not self.history or text != self.history[-1]):
            self.history.append(text)

            # Update Completer Modell (einmalige Einträge)
            unique_commands = list(set(self.history))
            self.completer_model.setStringList(unique_commands)

        self.history_index = -1

class SerialDataShowSendWidget(QtWidgets.QWidget):
    """
    Widget shows the data received by a serial port
    """
    def __init__(self, serial_config, device = None):
        super().__init__()
        self.device = device
        self.serial_config = serial_config
        self.comport_device = self.serial_config.comport_device
        self.layout = QtWidgets.QVBoxLayout(self)
        hlayout = QtWidgets.QHBoxLayout()

        self.bytes_read = QtWidgets.QLabel('Bytes read: ')
        self.lines_read = QtWidgets.QLabel('Lines read: ')
        hlayout.addWidget(self.bytes_read)
        hlayout.addWidget(self.lines_read)
        self.bytes_sent = QtWidgets.QLabel('Bytes sent: ')
        self.lines_sent = QtWidgets.QLabel('Lines sent: ')
        hlayout.addWidget(self.bytes_sent)
        hlayout.addWidget(self.lines_sent)

        self.datatext = QtWidgets.QPlainTextEdit()
        self.datatext.setReadOnly(True)
        self.datatext.setMaximumBlockCount(10000)
        self.datatext.setWindowIcon(QtGui.QIcon(_icon_file))
        self.datatext.setWindowTitle(self.comport_device)

        self.layout.addLayout(hlayout)
        self.layout.addWidget(self.datatext)
        layout = QtWidgets.QHBoxLayout()
        self.layout.addLayout(layout)
        self.clearbtn = QtWidgets.QPushButton('Clear')
        self.clearbtn.clicked.connect(self.cleartext)
        self.scrollchk = QtWidgets.QCheckBox('Scroll to end')
        self.scrollchk.setChecked(True)
        self.updatechk = QtWidgets.QCheckBox('Update')
        self.updatechk.setChecked(True)

        #self.text.setMaximumBlockCount(self.device.custom_config.bufsize)
        layout.addWidget(self.scrollchk)
        layout.addWidget(self.updatechk)
        layout.addWidget(self.clearbtn)

        # Add send widgets
        if True:
            layoutsend = QtWidgets.QHBoxLayout()
            #self.sendedit = QtWidgets.QLineEdit()
            self.sendedit = HistoryLineEdit(history=self.serial_config.command_history)
            self.senddelimiter = QtWidgets.QComboBox()
            self.senddelimiter.addItem("None")
            self.senddelimiter.addItem("LF")
            self.senddelimiter.addItem("CR/LF")
            self.senddelimiter.addItem("CR")
            self.sendbtn = QtWidgets.QPushButton('Send')
            self.sendbtn.clicked.connect(self.send_clicked)
            layoutsend.addWidget(self.sendedit)
            layoutsend.addWidget(self.senddelimiter)
            layoutsend.addWidget(self.sendbtn)
            self.layout.addLayout(layoutsend)

    def send_clicked(self):
        datastr = str(self.sendedit.text())
        self.sendedit.add_to_history(datastr)
        data_delimiter = self.senddelimiter.currentText()
        if "CR" in data_delimiter:
            datastr += "\r"
        if "LF" in data_delimiter:
            datastr += "\n"

        data = datastr.encode('utf-8')
        print("Sending data ...",data)
        data_dict = {'comport':self.comport_device,'data_send':data}
        self.device.thread_command('send',data_dict)

    def cleartext(self):
        self.datatext.clear()

    def add_data(self, data_list):
        datakey = self.serial_config.datakey_recv_raw
        for data in data_list:
            if "bytes_read" in data.keys() and "sentences_read" in data.keys():
                bstr = "Bytes read: {:d}".format(data['bytes_read'])
                lstr = "Sentences read: {:d}".format(data['sentences_read'])
                self.bytes_read.setText(bstr)
                self.lines_read.setText(lstr)

            if "bytes_sent" in data.keys() and "sentences_sent" in data.keys():
                bstr = "Bytes sent: {:d}".format(data['bytes_sent'])
                lstr = "Sentences sent: {:d}".format(data['sentences_sent'])
                self.bytes_sent.setText(bstr)
                self.lines_sent.setText(lstr)

            if (self.updatechk.isChecked()):
                if datakey in data.keys():
                    data_new = str(data[datakey])
                    prev_cursor = self.datatext.textCursor()
                    pos = self.datatext.verticalScrollBar().value()
                    self.datatext.moveCursor(QtGui.QTextCursor.End)
                    self.datatext.insertPlainText(str(data_new) + '\n')
                    if (self.scrollchk.isChecked()):
                        self.datatext.verticalScrollBar().setValue(
                            self.datatext.verticalScrollBar().maximum())
                    else:
                        self.datatext.verticalScrollBar().setValue(pos)


class initDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.device = device
        self.serialconfigwidget = SerialDeviceWidgetRedvypr(config=self.device.custom_config,
                                                            add_usedevice=False,
                                                            fix_serial_device=False)
        layout.addWidget(self.serialconfigwidget)
        layout.addStretch()
        self._button_serial_openclose = QtWidgets.QPushButton('Open')
        self._button_serial_openclose.clicked.connect(self.start_clicked)
        layout.addWidget(self._button_serial_openclose)
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)
        
    
    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']

        if(thread_status):
            self._button_serial_openclose.setText('Close')
            self.serialconfigwidget.setEnabled(False)
        else:
            self._button_serial_openclose.setText('Open')
            self.serialconfigwidget.setEnabled(True)

    def start_clicked(self):
        #print('Start clicked')
        button = self._button_serial_openclose
        #print('Start clicked:' + button.text())
        if('Open' in button.text()):
            button.setText('Close')
            self.device.thread_start()
        else:
            self.stop_clicked()

    def stop_clicked(self):
        button = self._button_serial_openclose
        self.device.thread_stop()
        button.setText('Closing') 


class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.device = device
        serial_config = self.device.custom_config
        self.serial_data_show = SerialDataShowSendWidget(serial_config=serial_config, device=self.device)
        layout.addWidget(self.serial_data_show)
        self.device.new_data.connect(self.serial_data_show.add_data)


        
