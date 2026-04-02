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

import redvypr
from redvypr.data_packets import check_for_command
from redvypr.redvypr_address import RedvyprAddress
#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict

description = 'Reading data from a serial device'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.serial_single')
logger.setLevel(logging.DEBUG)


packet_start = ['<None>','$','custom']
packet_delimiter = ['None','CR/LF','LF','custom']


class SerialDeviceConfig(pydantic.BaseModel):
    """
    Hardware configuration of a serial device
    """
    comport_device: str = pydantic.Field(default='')
    comport_device_short: typing.Optional[str] = pydantic.Field(default='',
                                                                description="short devicename of the comport, used in linux systems to get rid of the path")
    baud: int = pydantic.Field(default=2400)
    parity: typing.Literal[serial.PARITY_NONE, serial.PARITY_ODD, serial.PARITY_EVEN, serial.PARITY_MARK, serial.PARITY_SPACE] = pydantic.Field(default=serial.PARITY_NONE)
    stopbits: typing.Literal[serial.STOPBITS_ONE, serial.STOPBITS_ONE_POINT_FIVE,serial.STOPBITS_TWO] = pydantic.Field(default=serial.STOPBITS_ONE)
    bytesize: typing.Literal[serial.EIGHTBITS, serial.SEVENBITS, serial.SIXBITS] = pydantic.Field(default=serial.EIGHTBITS)
    comport_packetid_format: str = pydantic.Field(default='{device_short}',
                                                  description="Formatstring of the packetid of the comport, can be edited")
    comport_packetid: str = pydantic.Field(default='', description="Packetid of the comport. Created by applying comport_packetid_format")
    serial_number:  typing.Optional[str] = pydantic.Field(default='', description="Serial number of the comport")
    vid:  typing.Optional[str] = pydantic.Field(default='', description="vid of the comport")
    pid:  typing.Optional[str] = pydantic.Field(default='', description="pid of the comport")
    manufacturer:  typing.Optional[str] = pydantic.Field(default='', description="Manufacturer of the comport")
    comport_compare: typing.Optional[
        typing.List[typing.Literal["device","serial_number","vid","pid","manufactuer"]]] = pydantic.Field(default=["device"])

    def create_packetid(self):
        device_short = self.comport_device.split('/')[-1]
        self.comport_packetid = self.comport_packetid_format.format(device_short=device_short, device=self.comport_device, vid=self.vid, pid=self.pid, serial_number=self.serial_number, manufacturer=self.manufacturer)
        self.comport_device_short = device_short


class SerialDeviceConfigRedvypr(SerialDeviceConfig):
    """
    Extended config for redvypr specific configuration used by the thread
    """
    use_device: bool = pydantic.Field(default=True, description='Flag if the device should be used')
    receive_data: bool = pydantic.Field(default=True,
                                      description='Flag if the device shall receive data')
    send_data: bool = pydantic.Field(default=True,
                                     description='Flag if the device shall send data')
    dt_poll: float = 0.05
    dt_maxwait: float = pydantic.Field(default=-1.0,description='Wait time in s for valid data, if time without a valid packets exceeds dt_maxwait the comport is closed and the read thread is stopped')
    send_mode: typing.Literal["raw", "redvypr_datapacket"] = pydantic.Field(
        default="raw",
        description="The mode for data sending, raw for , redvypr_datapacket to send redvpyr datapackets")
    send_data_address: RedvyprAddress = pydantic.Field(default=RedvyprAddress("data@"),description='The address of the data to be sent')
    send_serializer: typing.Literal["utf-8", "redvypr_datapacket"] = pydantic.Field(default="utf-8",description="Mode of data conversion to binary format")
    recv_mode: typing.Literal["raw","redvypr_datapacket"] = pydantic.Field(default="raw",description="The mode for data reception, raw for serial data, redvypr_datapacket to read redvpyr datapackets")
    datakey_recv_raw: str = pydantic.Field(default="data",
                                    description='The datakey in the redvype packet for the received raw data')
    chunksize: int = pydantic.Field(default=0, description='The maximum amount of bytes read with one chunk')
    packetdelimiter: str = pydantic.Field(default='LF', description='The delimiter to distinguish packets, leave empty to disable')
    packetstart: str = pydantic.Field(default='', description='The delimiter to distinguish packets, leave empty to disable')


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Reads to and write from a serial device'
    gui_tablabel_display: str = 'Serial data'

class DeviceCustomConfig(pydantic.BaseModel):
    serial_device: SerialDeviceConfigRedvypr = pydantic.Field(default=SerialDeviceConfigRedvypr(baud=2400), description='Configuration of the serial device')
    baud: int = 4800
    parity: int = serial.PARITY_NONE
    stopbits: int = serial.STOPBITS_ONE
    bytesize: int = serial.EIGHTBITS
    dt_poll: float = 0.05
    chunksize: int = pydantic.Field(default=1000, description='The maximum amount of bytes read with one chunk')
    packetdelimiter: str = pydantic.Field(default='\n', description='The delimiter to distinuish packets')
    comport: str = ''

redvypr_devicemodule = True

def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Starting reading serial data')
    chunksize = config['chunksize'] #The maximum amount of bytes read with one chunk
    serial_name = config['serial_device']['comport_device']
    baud = config['serial_device']['baud']
    parity = config['serial_device']['parity']
    stopbits = config['serial_device']['stopbits']
    bytesize = config['serial_device']['bytesize']
    dt_poll = config['serial_device']['dt_poll']

    print('Starting',config)
    
    newpacket = config['serial_device']['packetdelimiter']
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
    bytes_read_old = 0 # To calculate the amount of bytes read per second
    t_update = time.time()
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
                    data = {'t':time.time()}
                    data['data'] = rawdata_all
                    data['comport'] = serial_device.name
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
                                data = {'t':time.time()}
                                data[config['datakey_recv_raw']] = raw
                                data['comport'] = serial_device.name
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

    def __init__(self, config=None, parent=None, add_packetid=False):
        super().__init__(parent)
        self.config = config
        self.add_packetid = add_packetid
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

    def _setup_ui(self):
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(5)

        self.grid_layout = QtWidgets.QGridLayout()
        self.grid_layout.setSpacing(8)

        # Labels
        labels = ["Port", "Baud", "Parity", "Data", "Stop", "ID Format",
                  "Resulting Packet ID"]
        if self.add_packetid == False:
            labels.remove("ID Format")
            labels.remove("Resulting Packet ID")
        for i, text in enumerate(labels):
            lbl = QtWidgets.QLabel(text)
            lbl.setStyleSheet("font-weight: bold; color: #666; font-size: 11px;")
            self.grid_layout.addWidget(lbl, 0, i)

        # Input Widgets
        self.combo_device = QtWidgets.QComboBox()
        self.combo_baud = QtWidgets.QComboBox()
        self.combo_parity = QtWidgets.QComboBox()
        self.combo_databits = QtWidgets.QComboBox()
        self.combo_stopbits = QtWidgets.QComboBox()
        if self.add_packetid:
            self.lineedit_format = QtWidgets.QLineEdit()
            self.lineedit_format.setPlaceholderText("{device_short}")
            # Add the Info-Tooltip to the format field
            self.lineedit_format.setToolTip(self.FORMAT_INFO)

            self.lineedit_packetid = QtWidgets.QLineEdit()
            self.lineedit_packetid.setReadOnly(True)
            self.lineedit_packetid.setStyleSheet(
                "background-color: #f4f4f4; border: 1px solid #ddd; color: #b22222; font-weight: bold;")

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
        self.grid_layout.addWidget(self.combo_device, 1, 0)
        self.grid_layout.addWidget(self.combo_baud, 1, 1)
        self.grid_layout.addWidget(self.combo_parity, 1, 2)
        self.grid_layout.addWidget(self.combo_databits, 1, 3)
        self.grid_layout.addWidget(self.combo_stopbits, 1, 4)
        if self.add_packetid:
            self.grid_layout.addWidget(self.lineedit_format, 1, 5)
            self.grid_layout.addWidget(self.lineedit_packetid, 1, 6)
        self.grid_layout.addWidget(self.btn_details, 1, 7)
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
        self.btn_details.clicked.connect(self._show_details)

    def _populate_options(self):
        self.combo_baud.blockSignals(True)
        self.combo_parity.blockSignals(True)
        self.combo_databits.blockSignals(True)
        self.combo_stopbits.blockSignals(True)
        for b in [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 921600]:
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
                self.config.create_packetid()
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




class SerialDeviceWidgetRedvypr_legacy(SerialDeviceWidget):
    """
    Extended Serial Widget with separate Send/Receive sections.
    Start and End Delimiters are now part of the Receive logic.
    """

    def __init__(self, config=None, parent=None, add_packetid=False):
        if config is None:
            config = SerialDeviceConfigRedvypr()
        super().__init__(config=config, parent=parent, add_packetid=add_packetid)

        self._setup_redvypr_ui()
        self._sync_redvypr_config_to_ui()

    def _setup_redvypr_ui(self):
        # Haupt-Container für die Redvypr-Erweiterung
        self.redvypr_group = QtWidgets.QGroupBox("Redvypr Thread Configuration")
        self.main_redvypr_layout = QtWidgets.QVBoxLayout(self.redvypr_group)

        # --- TOP: General Thread Control ---
        gen_layout = QtWidgets.QHBoxLayout()
        self.chk_use_device = QtWidgets.QCheckBox("Use Device")
        self.spin_dt_poll = QtWidgets.QDoubleSpinBox()
        self.spin_dt_poll.setRange(0.001, 1.0)
        self.spin_dt_poll.setDecimals(3)
        self.spin_dt_poll.setSuffix(" s")

        gen_layout.addWidget(self.chk_use_device)
        gen_layout.addSpacing(20)
        gen_layout.addWidget(QtWidgets.QLabel("Poll Int.:"))
        gen_layout.addWidget(self.spin_dt_poll)
        gen_layout.addStretch()
        self.main_redvypr_layout.addLayout(gen_layout)

        # --- MIDDLE: Split Send/Receive Layout ---
        split_layout = QtWidgets.QHBoxLayout()

        # --- RECEIVE SECTION ---
        self.recv_group = QtWidgets.QGroupBox("Receive")
        self.recv_group.setCheckable(True)
        recv_l = QtWidgets.QGridLayout(self.recv_group)

        self.combo_recv_mode = QtWidgets.QComboBox()
        self.combo_recv_mode.addItems(["raw", "redvypr_datapacket"])

        self.spin_maxwait = QtWidgets.QDoubleSpinBox()
        self.spin_maxwait.setRange(-1.0, 3600.0)
        self.spin_maxwait.setSpecialValueText("Disabled")
        self.spin_maxwait.setSuffix(" s")

        self.line_datakey = QtWidgets.QLineEdit()
        self.line_datakey.setPlaceholderText("data")

        self.spin_chunk = QtWidgets.QSpinBox()
        self.spin_chunk.setRange(0, 65535)
        self.spin_chunk.setSpecialValueText("Auto")

        # Delimiter gehören zur Reception Logic
        self.line_start = QtWidgets.QLineEdit()
        self.line_start.setPlaceholderText("e.g. $")
        self.line_end = QtWidgets.QLineEdit()
        self.line_end.setPlaceholderText("e.g. LF")

        # Grid Layout für Receive
        recv_l.addWidget(QtWidgets.QLabel("Mode:"), 0, 0)
        recv_l.addWidget(self.combo_recv_mode, 0, 1)
        recv_l.addWidget(QtWidgets.QLabel("Max Wait:"), 1, 0)
        recv_l.addWidget(self.spin_maxwait, 1, 1)
        recv_l.addWidget(QtWidgets.QLabel("Data Key:"), 2, 0)
        recv_l.addWidget(self.line_datakey, 2, 1)
        recv_l.addWidget(QtWidgets.QLabel("Chunksize:"), 3, 0)
        recv_l.addWidget(self.spin_chunk, 3, 1)
        recv_l.addWidget(QtWidgets.QLabel("Start Delim:"), 4, 0)
        recv_l.addWidget(self.line_start, 4, 1)
        recv_l.addWidget(QtWidgets.QLabel("End Delim:"), 5, 0)
        recv_l.addWidget(self.line_end, 5, 1)

        split_layout.addWidget(self.recv_group)

        # --- SEND SECTION ---
        self.send_group = QtWidgets.QGroupBox("Send")
        self.send_group.setCheckable(True)
        send_l = QtWidgets.QGridLayout(self.send_group)

        self.combo_send_mode = QtWidgets.QComboBox()
        self.combo_send_mode.addItems(["raw", "redvypr_datapacket"])

        self.combo_serializer = QtWidgets.QComboBox()
        self.combo_serializer.addItems(["utf-8", "redvypr_datapacket"])

        send_l.addWidget(QtWidgets.QLabel("Mode:"), 0, 0)
        send_l.addWidget(self.combo_send_mode, 0, 1)
        send_l.addWidget(QtWidgets.QLabel("Serializer:"), 1, 0)
        send_l.addWidget(self.combo_serializer, 1, 1)
        # Spacer, um die Höhe an die Receive-Box anzupassen
        send_l.setRowStretch(2, 1)

        split_layout.addWidget(self.send_group)
        self.main_redvypr_layout.addLayout(split_layout)

        # Ins Erweiterungs-Layout der Basisklasse einfügen
        self.extension_layout.addWidget(self.redvypr_group)

        # --- SIGNAL CONNECTIONS ---
        self.chk_use_device.toggled.connect(
            lambda v: self._update_config("use_device", v))
        self.spin_dt_poll.valueChanged.connect(
            lambda v: self._update_config("dt_poll", v))

        self.recv_group.toggled.connect(
            lambda v: self._update_config("receive_data", v))
        self.send_group.toggled.connect(lambda v: self._update_config("send_data", v))

        # Receive Fields (inkl. Delimiter)
        self.combo_recv_mode.currentTextChanged.connect(
            lambda t: self._update_config("recv_mode", t))
        self.spin_maxwait.valueChanged.connect(
            lambda v: self._update_config("dt_maxwait", v))
        self.line_datakey.textChanged.connect(
            lambda t: self._update_config("datakey_recv_raw", t))
        self.spin_chunk.valueChanged.connect(
            lambda v: self._update_config("chunksize", v))
        self.line_start.textChanged.connect(
            lambda t: self._update_config("packetstart", t))
        self.line_end.textChanged.connect(
            lambda t: self._update_config("packetdelimiter", t))

        # Send Fields
        self.combo_send_mode.currentTextChanged.connect(
            lambda t: self._update_config("send_mode", t))
        self.combo_serializer.currentTextChanged.connect(
            lambda t: self._update_config("send_serializer", t))

    def _sync_redvypr_config_to_ui(self):
        if not self.config: return
        c = self.config

        # Signale blockieren um rekursive 'config_changed' Prints zu vermeiden
        self.redvypr_group.blockSignals(True)

        self.chk_use_device.setChecked(c.use_device)
        self.spin_dt_poll.setValue(c.dt_poll)

        # Gruppen-Status
        self.recv_group.setChecked(c.receive_data)
        self.send_group.setChecked(c.send_data)

        # Receive Sync
        self.combo_recv_mode.setCurrentText(c.recv_mode)
        self.spin_maxwait.setValue(c.dt_maxwait)
        self.line_datakey.setText(c.datakey_recv_raw)
        self.spin_chunk.setValue(c.chunksize)
        self.line_start.setText(c.packetstart)
        self.line_end.setText(c.packetdelimiter)

        # Send Sync
        self.combo_send_mode.setCurrentText(c.send_mode)
        self.combo_serializer.setCurrentText(c.send_serializer)

        self.redvypr_group.blockSignals(False)

    def _update_config(self, attr, value):
        """Schreibt Werte in die Config und emittiert Signal."""
        if self.config and hasattr(self.config, attr):
            setattr(self.config, attr, value)
            self.config_changed.emit(True)


class SerialDeviceWidgetRedvypr(SerialDeviceWidget):
    """
    Extended Serial Widget with separate Send/Receive sections.
    Includes editable ComboBoxes for Delimiters and Address field for Sending.
    """

    def __init__(self, config=None, parent=None, add_packetid=False):
        if config is None:
            config = SerialDeviceConfigRedvypr()
        super().__init__(config=config, parent=parent, add_packetid=add_packetid)

        self._setup_redvypr_ui()
        self._sync_redvypr_config_to_ui()

    def _setup_redvypr_ui(self):
        # Haupt-Container für die Redvypr-Erweiterung
        self.redvypr_group = QtWidgets.QGroupBox("Redvypr Thread Configuration")
        self.main_redvypr_layout = QtWidgets.QVBoxLayout(self.redvypr_group)

        # --- TOP: General Thread Control ---
        gen_layout = QtWidgets.QHBoxLayout()
        self.chk_use_device = QtWidgets.QCheckBox("Use Device")
        self.spin_dt_poll = QtWidgets.QDoubleSpinBox()
        self.spin_dt_poll.setRange(0.001, 1.0)
        self.spin_dt_poll.setDecimals(3)
        self.spin_dt_poll.setSuffix(" s")

        gen_layout.addWidget(self.chk_use_device)
        gen_layout.addSpacing(20)
        gen_layout.addWidget(QtWidgets.QLabel("Poll Int.:"))
        gen_layout.addWidget(self.spin_dt_poll)
        gen_layout.addStretch()
        self.main_redvypr_layout.addLayout(gen_layout)

        # --- MIDDLE: Split Send/Receive Layout ---
        split_layout = QtWidgets.QHBoxLayout()

        # --- RECEIVE SECTION ---
        self.recv_group = QtWidgets.QGroupBox("Receive")
        self.recv_group.setCheckable(True)
        recv_l = QtWidgets.QGridLayout(self.recv_group)

        self.combo_recv_mode = QtWidgets.QComboBox()
        self.combo_recv_mode.addItems(["raw", "redvypr_datapacket"])

        self.spin_maxwait = QtWidgets.QDoubleSpinBox()
        self.spin_maxwait.setRange(-1.0, 3600.0)
        self.spin_maxwait.setSpecialValueText("Disabled")
        self.spin_maxwait.setSuffix(" s")

        self.line_datakey = QtWidgets.QLineEdit()
        self.line_datakey.setPlaceholderText("data")

        self.spin_chunk = QtWidgets.QSpinBox()
        self.spin_chunk.setRange(0, 65535)
        self.spin_chunk.setSpecialValueText("Auto")

        # Delimiter als EDITIERBARE ComboBoxen
        self.combo_start = QtWidgets.QComboBox()
        self.combo_start.setEditable(True)
        self.combo_start.addItems(["<None>", "$"])

        self.combo_end = QtWidgets.QComboBox()
        self.combo_end.setEditable(True)
        self.combo_end.addItems(["None", "CR/LF", "LF"])

        # Grid Layout für Receive
        recv_l.addWidget(QtWidgets.QLabel("Mode:"), 0, 0)
        recv_l.addWidget(self.combo_recv_mode, 0, 1)
        recv_l.addWidget(QtWidgets.QLabel("Max Wait:"), 1, 0)
        recv_l.addWidget(self.spin_maxwait, 1, 1)
        recv_l.addWidget(QtWidgets.QLabel("Data Key:"), 2, 0)
        recv_l.addWidget(self.line_datakey, 2, 1)
        recv_l.addWidget(QtWidgets.QLabel("Chunksize:"), 3, 0)
        recv_l.addWidget(self.spin_chunk, 3, 1)
        recv_l.addWidget(QtWidgets.QLabel("Start Delim:"), 4, 0)
        recv_l.addWidget(self.combo_start, 4, 1)
        recv_l.addWidget(QtWidgets.QLabel("End Delim:"), 5, 0)
        recv_l.addWidget(self.combo_end, 5, 1)

        split_layout.addWidget(self.recv_group)

        # --- SEND SECTION ---
        self.send_group = QtWidgets.QGroupBox("Send")
        self.send_group.setCheckable(True)
        send_l = QtWidgets.QGridLayout(self.send_group)

        self.combo_send_mode = QtWidgets.QComboBox()
        self.combo_send_mode.addItems(["raw", "redvypr_datapacket"])

        self.combo_serializer = QtWidgets.QComboBox()
        self.combo_serializer.addItems(["utf-8", "redvypr_datapacket"])

        # Neues Adress-Feld
        self.line_send_address = QtWidgets.QLineEdit()
        self.line_send_address.setPlaceholderText("data@")

        send_l.addWidget(QtWidgets.QLabel("Mode:"), 0, 0)
        send_l.addWidget(self.combo_send_mode, 0, 1)
        send_l.addWidget(QtWidgets.QLabel("Serializer:"), 1, 0)
        send_l.addWidget(self.combo_serializer, 1, 1)
        send_l.addWidget(QtWidgets.QLabel("Send Address:"), 2, 0)
        send_l.addWidget(self.line_send_address, 2, 1)

        # Spacer
        send_l.setRowStretch(3, 1)

        split_layout.addWidget(self.send_group)
        self.main_redvypr_layout.addLayout(split_layout)

        # Ins Erweiterungs-Layout der Basisklasse einfügen
        self.extension_layout.addWidget(self.redvypr_group)

        # --- SIGNAL CONNECTIONS ---
        self.chk_use_device.toggled.connect(
            lambda v: self._update_config("use_device", v))
        self.spin_dt_poll.valueChanged.connect(
            lambda v: self._update_config("dt_poll", v))

        self.recv_group.toggled.connect(
            lambda v: self._update_config("receive_data", v))
        self.send_group.toggled.connect(lambda v: self._update_config("send_data", v))

        # Receive Fields
        self.combo_recv_mode.currentTextChanged.connect(
            lambda t: self._update_config("recv_mode", t))
        self.spin_maxwait.valueChanged.connect(
            lambda v: self._update_config("dt_maxwait", v))
        self.line_datakey.textChanged.connect(
            lambda t: self._update_config("datakey_recv_raw", t))
        self.spin_chunk.valueChanged.connect(
            lambda v: self._update_config("chunksize", v))

        # Delimiter Signale (editierbare Combobox nutzt editTextChanged für sofortige Updates)
        self.combo_start.editTextChanged.connect(
            lambda t: self._update_config("packetstart", t))
        self.combo_end.editTextChanged.connect(
            lambda t: self._update_config("packetdelimiter", t))

        # Send Fields
        self.combo_send_mode.currentTextChanged.connect(
            lambda t: self._update_config("send_mode", t))
        self.combo_serializer.currentTextChanged.connect(
            lambda t: self._update_config("send_serializer", t))
        self.line_send_address.textChanged.connect(
            lambda t: self._update_config("send_data_address", t))

    def _sync_redvypr_config_to_ui(self):
        if not self.config: return
        c = self.config

        self.redvypr_group.blockSignals(True)

        self.chk_use_device.setChecked(c.use_device)
        self.spin_dt_poll.setValue(c.dt_poll)

        self.recv_group.setChecked(c.receive_data)
        self.send_group.setChecked(c.send_data)

        # Receive Sync
        self.combo_recv_mode.setCurrentText(c.recv_mode)
        self.spin_maxwait.setValue(c.dt_maxwait)
        self.line_datakey.setText(c.datakey_recv_raw)
        self.spin_chunk.setValue(c.chunksize)

        # Delimiter Sync
        self.combo_start.setCurrentText(c.packetstart if c.packetstart else "<None>")
        self.combo_end.setCurrentText(
            c.packetdelimiter if c.packetdelimiter else "None")

        # Send Sync
        self.combo_send_mode.setCurrentText(c.send_mode)
        self.combo_serializer.setCurrentText(c.send_serializer)
        self.line_send_address.setText(str(c.send_data_address))

        self.redvypr_group.blockSignals(False)

    def _update_config(self, attr, value):
        if self.config and hasattr(self.config, attr):
            # Spezialbehandlung für Address-Objekt, falls nötig (abhängig von Pydantic-Parsing)
            if attr == "send_data_address" and not isinstance(value,
                                                              redvypr.RedvyprAddress):
                try:
                    value = redvypr.RedvyprAddress(value)
                except:
                    pass

            setattr(self.config, attr, value)
            self.config_changed.emit(True)


class initDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.device = device
        self.serialconfigwidget = SerialDeviceWidgetRedvypr(config=self.device.custom_config.serial_device)
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

    def update_data(self,data):
        funcname = __name__ + '.update():'
        #print('data',data)
        try:
            bstr = "Bytes read: {:d}".format(data['bytes_read'])
            lstr = "Sentences read: {:d}".format(data['sentences_read'])
            self.bytes_read.setText(bstr)
            self.lines_read.setText(lstr)
        except Exception as e:
            logger.exception(e)
        try:
            self.text.insertPlainText(str(data['data']))
            self.text.insertPlainText('\n')
        except Exception as e:
            logger.debug(funcname,exc_info=True)
        
