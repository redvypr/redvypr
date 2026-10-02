"""
norlog gateway device

A norlog connected via UART acts as the gateway between redvypr and a Thread
network of norlog sensor nodes. The device

- provides a console to the norlog Zephyr shell,
- forms a Thread network and shows its state (OpenThread CLI, "ot ..."),
- flashes the gateway firmware over UART (MCUmgr/SMP via the norlog_loader),
- publishes norlog data packets received from the Thread network.

Data lines from the gateway firmware (planned, not yet implemented there):

    #NLD <source> <base64 encoded norlog CBOR packet>

<source> identifies the sending node (e.g. its RLOC16 or IPv6 address).
Decoded packets are published with the packetid "norlog_<mac>".
"""

import base64
import binascii
import logging
import pathlib
import queue
import secrets
import sys
import time
import typing

import pydantic
import serial
import serial.tools.list_ports
from PyQt6 import QtCore, QtGui, QtWidgets

from redvypr.device import RedvyprDeviceCustomConfig
from redvypr.redvypr_datadict import check_for_command, create_redvypr_dict
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple

from . import device_list
from . import norlog_cbor
from . import ot_cli
from . import smp_serial
from .cbor_mini import CBORDecodeError

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.norlog_gateway')
logger.setLevel(logging.INFO)

redvypr_devicemodule = True

DATA_PREFIX = "#NLD "


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = 'norlog Thread gateway (UART): console, Thread network, firmware update, data'
    gui_tablabel_display: str = 'norlog gateway'


class DeviceCustomConfig(RedvyprDeviceCustomConfig):
    comport: str = pydantic.Field(default='', description='Serial port of the gateway norlog')
    baud: int = pydantic.Field(default=115200, description='Baud rate of the norlog shell UART')
    network_name: str = pydantic.Field(default='NorlogMesh', description='Thread network name')
    channel: int = pydantic.Field(default=18, ge=11, le=26, description='IEEE 802.15.4 channel (11-26)')
    panid: str = pydantic.Field(default='0x1234', description='PAN ID, empty for random')
    extpanid: str = pydantic.Field(default='', description='Extended PAN ID (16 hex digits), empty for random')
    networkkey: str = pydantic.Field(default='', description='Network key (32 hex digits), empty for random. '
                                                             'Stored in plain text in the redvypr configuration!')
    status_interval_s: float = pydantic.Field(default=10.0, description='Interval for reading the Thread '
                                                                        'status and device list, '
                                                                        '0 = only on request')
    console_show_commands: bool = pydantic.Field(default=False, description='Show the traffic of internal '
                                                                            'ot commands in the console')
    dataset_tlvs: str = pydantic.Field(default='', description='Active operational dataset (hex TLVs) used to '
                                                               'provision nodes. Contains the network key!')
    node_comport: str = pydantic.Field(default='', description='Serial port of a node to be provisioned')
    firmware_image: str = pydantic.Field(default='', description='Signed firmware image (zephyr.signed.bin)')
    firmware_force: bool = pydantic.Field(default=False, description='Flash even if the image is already installed')


# --------------------------------------------------------------------------
# Device thread
# --------------------------------------------------------------------------

class _Gateway:
    """State of the running device thread."""

    def __init__(self, device_info, pdconfig, dataqueue, datainqueue):
        self.device_info = device_info
        self.device = device_info['device']
        self.config = pdconfig
        self.dataqueue = dataqueue
        self.datainqueue = datainqueue
        self.ser = None
        self.reader = ot_cli.LineReader()
        self.cli = None
        self.stop_requested = False
        self.npackets = 0
        self.last_rx = None             # time.monotonic() of the last line from the gateway
        self.data_sources = {}          # '#NLD' source -> {'last_seen', 'packets', 'mac'}

    # --- publishing ---

    def publish(self, packetid, payload):
        data = create_redvypr_dict(device=self.device, packetid=packetid)
        data.update(payload)
        self.dataqueue.put(data)

    def console(self, line):
        self.publish('console', {'line': line})

    def result(self, command, ok, message='', **extra):
        self.publish('command_result', {'command': command, 'ok': ok, 'message': message, **extra})

    # --- incoming lines ---

    def on_gateway_line(self, line, is_response=False):
        self.last_rx = time.monotonic()
        self.on_line(line, is_response)

    def on_line(self, line, is_response=False):
        if line.startswith(DATA_PREFIX):
            self.handle_data_line(line)
            return
        if is_response and not self.config.console_show_commands:
            return
        self.console(line)

    def handle_data_line(self, line):
        parts = line.split(" ", 2)
        if len(parts) != 3:
            self.console(line)
            return
        _, source, payload = parts
        try:
            pkt = norlog_cbor.decode_bytes(base64.b64decode(payload, validate=True))
        except (binascii.Error, CBORDecodeError, ValueError) as exc:
            logger.warning(f'Could not decode data line from {source}: {exc}')
            return
        if pkt is None:
            return
        pkt['source'] = source
        mac = pkt.get('mac', source)
        t = pkt.get('rtc_time') or pkt.get('gps_time') or time.time()
        data = create_redvypr_dict(device=self.device, packetid=f'norlog_{mac}', tu=t)
        data.update(pkt)
        data['t'] = t
        self.dataqueue.put(data)
        self.npackets += 1

        src = self.data_sources.setdefault(source, {'packets': 0})
        src['packets'] += 1
        src['last_seen'] = time.time()
        src['mac'] = pkt.get('mac', '')

    # --- serial ---

    def open(self):
        self.ser = serial.Serial(self.config.comport, self.config.baud, timeout=0.05)
        self.cli = ot_cli.OtCli(self.ser, self.reader, self.on_gateway_line)

    def close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass

    def poll_serial(self):
        for line in self.reader.feed(self.ser.read(512)):
            self.on_gateway_line(line)

    # --- commands ---

    def check_commands(self, during_flash=False):
        """Process commands from the GUI. Returns True if a running flash shall be cancelled."""
        cancel = False
        while True:
            try:
                data = self.datainqueue.get(block=False)
            except queue.Empty:
                break
            command, comdata = check_for_command(data, thread_uuid=self.device_info['thread_uuid'],
                                                 add_data=True)
            if command is None:
                continue
            args = {}
            try:
                args = comdata['command_data']['data'] or {}
            except (KeyError, TypeError):
                pass

            if command == 'stop':
                self.stop_requested = True
                cancel = True
            elif during_flash:
                if command == 'flash_cancel':
                    cancel = True
                else:
                    logger.info(f'Ignoring command {command!r} while flashing')
            else:
                self.execute(command, args)
        return cancel

    def execute(self, command, args):
        try:
            if command == 'config':
                self.config = DeviceCustomConfig.model_validate(args['config'])
            elif command == 'send':
                self.ser.write((args.get('text', '') + "\r\n").encode())
                self.ser.flush()
            elif command == 'ot_status':
                self.read_status()
            elif command == 'form_network':
                ot_cli.form_network(self.cli, network_name=args.get('network_name', ''),
                                    channel=args.get('channel'), panid=args.get('panid', ''),
                                    extpanid=args.get('extpanid', ''), networkkey=args.get('networkkey', ''))
                self.result(command, True, 'Thread network formed, waiting for leader role')
                time.sleep(1.0)
                self.read_status()
            elif command == 'dataset':
                tlvs = ot_cli.active_dataset_tlvs(self.cli)
                # Not published as data (contains the network key), only as command result
                self.result(command, True, 'Active dataset', dataset_tlvs=tlvs)
            elif command == 'provision':
                self.provision(args.get('port', ''), args.get('dataset', ''))
            elif command == 'flash':
                self.flash(args.get('image', ''), bool(args.get('force', False)))
            else:
                self.result(command, False, f'Unknown command {command!r}')
        except (ot_cli.OtError, TimeoutError, smp_serial.SmpError, OSError, ValueError) as exc:
            self.result(command, False, str(exc))

    def provision(self, port, dataset):
        """Store the dataset on a node (own port or a second serial port) and start Thread."""
        if not dataset:
            raise ValueError('No dataset available, read it from the gateway first')
        if not port or port == self.config.comport:
            node_cli, node_ser, label = self.cli, None, 'this device'
        else:
            node_ser = serial.Serial(port, self.config.baud, timeout=0.05)
            label = port
            node_cli = ot_cli.OtCli(node_ser, ot_cli.LineReader(),
                                    lambda line, is_resp: self.on_line(f'[{port}] {line}', is_resp))
        try:
            self.result('provision', True, f'Provisioning {label} ...')
            st = ot_cli.provision_node(node_cli, dataset)
            if st['attached']:
                self.result('provision', True, f"{label} joined the network as {st['state']} "
                                               f"(extaddr {st['extaddr']})")
            else:
                self.result('provision', False, f"{label}: dataset stored, but not attached yet "
                                                f"(state {st['state']!r}). Out of range or no "
                                                f"leader running?")
        finally:
            if node_ser is not None:
                node_ser.close()

    def read_status(self):
        status = ot_cli.read_status(self.cli)
        status['packets_received'] = self.npackets
        rx_age = None if self.last_rx is None else time.monotonic() - self.last_rx
        devices = device_list.build_device_list(status, gateway_port=self.config.comport,
                                                serial_rx_age_s=rx_age, data_sources=self.data_sources)
        self.publish('thread_status', {'thread_status': status, 'devices': devices})

    # --- firmware update ---

    def flash_status(self, state, message='', progress=None, **extra):
        payload = {'state': state, 'message': message}
        if progress is not None:
            payload['progress'] = progress
        payload.update(extra)
        self.publish('flash_status', payload)

    def flash(self, image_path, force):
        path = pathlib.Path(image_path)
        if not path.is_file():
            raise ValueError(f'Image not found: {image_path}')
        image = path.read_bytes()
        info = smp_serial.image_info(image)
        self.flash_status('start', f'{path.name}: version {info["version"]}, {info["size"] // 1024} KB')

        smp = smp_serial.SmpSerial(self.ser, text_callback=self.console)
        cancel = lambda: self.check_commands(during_flash=True)
        self.reader.reset()
        try:
            self.flash_status('loader', "Rebooting into the loader ('norlog dfu') ...")
            if not smp.enter_loader(timeout=20.0, cancel=cancel):
                raise smp_serial.SmpError('Loader does not respond')

            images = smp.image_state()
            slot0 = next((i for i in images if i.get('image', 0) == 0 and i.get('slot', 0) == 0), {})
            self.flash_status('loader', f'Loader ready, installed version: {slot0.get("version", "-")}')

            if slot0.get('hash') == info['hash'] and not force:
                smp.reset()
                self.flash_status('done', 'Image already installed, nothing to do', progress=100)
                return

            t0 = time.monotonic()
            last = [0.0]

            def progress(off, size):
                now = time.monotonic()
                if now - last[0] >= 0.5 or off >= size:
                    last[0] = now
                    rate = off / max(now - t0, 1e-3) / 1024
                    self.flash_status('upload', f'{off // 1024}/{size // 1024} KB, {rate:.1f} KB/s',
                                      progress=off * 100 // size)

            self.flash_status('upload', 'Erasing slot 0 (about 20 s) ...', progress=0)
            smp.upload(image, progress=progress, cancel=cancel)
            images = smp.image_state()
            slot0 = next((i for i in images if i.get('image', 0) == 0 and i.get('slot', 0) == 0), {})
            smp.reset()
            self.flash_status('done', f'Installed version {slot0.get("version", "?")}, rebooting', progress=100)
        except smp_serial.SmpCancelled:
            self.flash_status('cancelled', 'Cancelled. The loader restarts the app after 5 min '
                                           '(or press RESET).')
        except (smp_serial.SmpError, TimeoutError) as exc:
            self.flash_status('error', str(exc))
        finally:
            self.reader.reset()


def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start():'
    pdconfig = DeviceCustomConfig.model_validate(config)
    gw = _Gateway(device_info, pdconfig, dataqueue, datainqueue)

    if not pdconfig.comport:
        gw.result('start', False, 'No serial port configured')
        return
    try:
        gw.open()
    except serial.SerialException as exc:
        gw.result('start', False, f'Could not open {pdconfig.comport}: {exc}')
        return

    logger.info(funcname + f'Opened {pdconfig.comport} with {pdconfig.baud} baud')
    gw.result('start', True, f'Connected to {pdconfig.comport}')
    t_status = time.monotonic()

    try:
        while not gw.stop_requested:
            gw.check_commands()
            if gw.stop_requested:
                break
            try:
                gw.poll_serial()
            except serial.SerialException as exc:
                gw.result('serial', False, f'Serial port error: {exc}')
                break

            interval = gw.config.status_interval_s
            if interval > 0 and time.monotonic() - t_status >= interval:
                t_status = time.monotonic()
                try:
                    gw.read_status()
                except (ot_cli.OtError, TimeoutError) as exc:
                    logger.debug(funcname + f'Status poll failed: {exc}')
    finally:
        gw.close()
        logger.info(funcname + 'Stopped')


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cfg = self.device.custom_config
        self.run_widgets = []       # only enabled while the thread is running

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_devices_tab(), 'Devices')
        self.tabs.addTab(self._build_console_tab(), 'Console')
        self.tabs.addTab(self._build_thread_tab(), 'Thread network')
        self.tabs.addTab(self._build_firmware_tab(), 'Firmware')
        self.tabs.addTab(self._build_data_tab(), 'Data')
        self.layout.addWidget(self._build_port_row())
        self.layout.addWidget(self.tabs)

        self.device.new_data.connect(self.on_new_data)
        self.run_timer = QtCore.QTimer()
        self.run_timer.timeout.connect(self.update_run_state)
        self.run_timer.start(500)

    # --- port ---

    def _build_port_row(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.port_combo = QtWidgets.QComboBox()
        self.port_combo.setEditable(True)
        self.port_refresh = QtWidgets.QPushButton('Refresh')
        self.port_refresh.clicked.connect(self.refresh_ports)
        self.baud_edit = QtWidgets.QSpinBox()
        self.baud_edit.setRange(1200, 3000000)
        self.baud_edit.setValue(self.cfg.baud)
        self.baud_edit.valueChanged.connect(lambda v: setattr(self.cfg, 'baud', v))
        lay.addWidget(QtWidgets.QLabel('Port'))
        lay.addWidget(self.port_combo, 1)
        lay.addWidget(self.port_refresh)
        lay.addWidget(QtWidgets.QLabel('Baud'))
        lay.addWidget(self.baud_edit)
        self.refresh_ports()
        self.port_combo.currentTextChanged.connect(self.port_changed)
        # Disabled while the thread is running (handled by the base class)
        self.config_widgets.extend([self.port_combo, self.port_refresh, self.baud_edit])
        return w

    def refresh_ports(self):
        current = self.cfg.comport
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for p in serial.tools.list_ports.comports():
            self.port_combo.addItem(f'{p.device}  ({p.description})', p.device)
        idx = self.port_combo.findData(current)
        if idx >= 0:
            self.port_combo.setCurrentIndex(idx)
        else:
            self.port_combo.setEditText(current)
        self.port_combo.blockSignals(False)

    def port_changed(self, text):
        data = self.port_combo.currentData()
        self.cfg.comport = data if data else text.split()[0] if text.strip() else ''

    # --- devices ---

    DEVICE_COLUMNS = ['Device', 'RLOC16', 'Connection', 'Role', 'Thread role', 'Link', 'Quality',
                      'RSSI avg/last [dBm]', 'LQ in/out', 'Path cost', 'Seen [s]', 'Packets']

    QUALITY_COLORS = {
        device_list.QUALITY_GOOD: '#7bc96f',
        device_list.QUALITY_FAIR: '#f2c14e',
        device_list.QUALITY_POOR: '#e8743b',
        device_list.QUALITY_NONE: '#d64545',
    }

    def _build_devices_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        refresh = QtWidgets.QPushButton('Refresh now')
        refresh.clicked.connect(lambda: self.device.thread_command('ot_status', {}))
        self.devices_info = QtWidgets.QLabel('No data yet (refreshed with the Thread status)')
        row.addWidget(refresh)
        row.addWidget(self.devices_info, 1)
        self.devices_table = QtWidgets.QTableWidget(0, len(self.DEVICE_COLUMNS))
        self.devices_table.setHorizontalHeaderLabels(self.DEVICE_COLUMNS)
        self.devices_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.devices_table.horizontalHeader().setStretchLastSection(True)
        self.devices_table.verticalHeader().setVisible(False)
        legend = QtWidgets.QLabel('Quality: Thread links from link quality (0-3) and average RSSI '
                                  '(good >= -70 dBm, fair >= -85 dBm); multi-hop routers from the path '
                                  'cost (good <= 3, fair <= 6, 16 = unreachable); serial = data from the gateway within 30 s.')
        legend.setWordWrap(True)
        legend.setStyleSheet('color: gray;')
        lay.addLayout(row)
        lay.addWidget(self.devices_table, 1)
        lay.addWidget(legend)
        self.run_widgets.append(refresh)
        return w

    @staticmethod
    def _fmt_pair(a, b):
        if a is None and b is None:
            return ''
        return f"{'' if a is None else a} / {'' if b is None else b}"

    def show_devices(self, devices):
        self.devices_table.setRowCount(len(devices))
        for row, d in enumerate(devices):
            name = d.get('extaddr') or d.get('mac') or d.get('id', '')
            if d.get('connection') == device_list.CONNECTION_SERIAL and d.get('port'):
                name = f"{name} ({d['port']})" if d.get('extaddr') else d['port']
            seen = d.get('age_s')
            if seen is None:
                seen = d.get('last_data_s')
            cells = [
                name,
                d.get('rloc16', ''),
                d.get('connection', ''),
                d.get('role', ''),
                d.get('thread_role', ''),
                d.get('link', ''),
                d.get('quality', ''),
                self._fmt_pair(d.get('rssi_avg'), d.get('rssi_last')),
                self._fmt_pair(d.get('lq_in'), d.get('lq_out')),
                '' if d.get('path_cost') is None else str(d['path_cost']),
                '' if seen is None else f'{seen:.0f}',
                str(d.get('packets', 0) or ''),
            ]
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(str(text))
                if col == 6 and d.get('quality') in self.QUALITY_COLORS:
                    item.setBackground(QtGui.QColor(self.QUALITY_COLORS[d['quality']]))
                self.devices_table.setItem(row, col, item)
        self.devices_table.resizeColumnsToContents()
        members = len(devices) - 1
        self.devices_info.setText(f'{members} member(s), updated {time.strftime("%H:%M:%S")}')

    # --- console ---

    def _build_console_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        self.console_text = QtWidgets.QPlainTextEdit()
        self.console_text.setReadOnly(True)
        self.console_text.setMaximumBlockCount(5000)
        font = self.console_text.font()
        font.setFamily('Consolas')
        self.console_text.setFont(font)
        row = QtWidgets.QHBoxLayout()
        self.console_input = QtWidgets.QLineEdit()
        self.console_input.setPlaceholderText('Shell command, e.g. "ot state" or "norlog fw status"')
        self.console_input.returnPressed.connect(self.send_console)
        send = QtWidgets.QPushButton('Send')
        send.clicked.connect(self.send_console)
        clear = QtWidgets.QPushButton('Clear')
        clear.clicked.connect(self.console_text.clear)
        row.addWidget(self.console_input, 1)
        row.addWidget(send)
        row.addWidget(clear)
        lay.addWidget(self.console_text)
        lay.addLayout(row)
        self.run_widgets.extend([self.console_input, send])
        return w

    def send_console(self):
        text = self.console_input.text()
        if text:
            self.console_text.appendPlainText(f'> {text}')
            self.device.thread_command('send', {'text': text})
            self.console_input.clear()

    # --- Thread network ---

    def _build_thread_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)

        form_box = QtWidgets.QGroupBox('Network parameters')
        form = QtWidgets.QFormLayout(form_box)
        self.net_name = QtWidgets.QLineEdit(self.cfg.network_name)
        self.net_name.textChanged.connect(lambda t: setattr(self.cfg, 'network_name', t))
        self.net_channel = QtWidgets.QSpinBox()
        self.net_channel.setRange(11, 26)
        self.net_channel.setValue(self.cfg.channel)
        self.net_channel.valueChanged.connect(lambda v: setattr(self.cfg, 'channel', v))
        self.net_panid = QtWidgets.QLineEdit(self.cfg.panid)
        self.net_panid.textChanged.connect(lambda t: setattr(self.cfg, 'panid', t))
        self.net_extpanid = QtWidgets.QLineEdit(self.cfg.extpanid)
        self.net_extpanid.setPlaceholderText('empty = random')
        self.net_extpanid.textChanged.connect(lambda t: setattr(self.cfg, 'extpanid', t))
        key_row = QtWidgets.QHBoxLayout()
        self.net_key = QtWidgets.QLineEdit(self.cfg.networkkey)
        self.net_key.setPlaceholderText('empty = random')
        self.net_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.net_key.textChanged.connect(lambda t: setattr(self.cfg, 'networkkey', t))
        gen_key = QtWidgets.QPushButton('Generate')
        gen_key.clicked.connect(self.generate_credentials)
        key_row.addWidget(self.net_key, 1)
        key_row.addWidget(gen_key)
        form.addRow('Network name', self.net_name)
        form.addRow('Channel', self.net_channel)
        form.addRow('PAN ID', self.net_panid)
        form.addRow('Ext. PAN ID', self.net_extpanid)
        form.addRow('Network key', key_row)

        btn_row = QtWidgets.QHBoxLayout()
        form_btn = QtWidgets.QPushButton('Form network')
        form_btn.clicked.connect(self.form_network)
        status_btn = QtWidgets.QPushButton('Read status')
        status_btn.clicked.connect(lambda: self.device.thread_command('ot_status', {}))
        for b in (form_btn, status_btn):
            btn_row.addWidget(b)
        self.run_widgets.extend([form_btn, status_btn])

        self.status_tree = QtWidgets.QTreeWidget()
        self.status_tree.setHeaderLabels(['Item', 'Value'])
        self.status_tree.setColumnWidth(0, 160)

        prov_box = QtWidgets.QGroupBox('Provision nodes (the dataset contains the network key)')
        prov = QtWidgets.QGridLayout(prov_box)
        self.dataset_label = QtWidgets.QLabel()
        read_ds = QtWidgets.QPushButton('Read dataset from gateway')
        read_ds.clicked.connect(lambda: self.device.thread_command('dataset', {}))
        copy_ds = QtWidgets.QPushButton('Copy')
        copy_ds.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.cfg.dataset_tlvs))
        self.node_port = QtWidgets.QComboBox()
        self.node_port.setEditable(True)
        self.node_port.currentTextChanged.connect(self.node_port_changed)
        node_refresh = QtWidgets.QPushButton('Refresh')
        node_refresh.clicked.connect(self.refresh_node_ports)
        prov_btn = QtWidgets.QPushButton('Provision node via UART')
        prov_btn.clicked.connect(self.provision_node)
        export_btn = QtWidgets.QPushButton('Export autoexec.txt ...')
        export_btn.clicked.connect(self.export_autoexec)
        prov.addWidget(QtWidgets.QLabel('Dataset'), 0, 0)
        prov.addWidget(self.dataset_label, 0, 1)
        prov.addWidget(read_ds, 0, 2)
        prov.addWidget(copy_ds, 0, 3)
        prov.addWidget(QtWidgets.QLabel('Node port'), 1, 0)
        prov.addWidget(self.node_port, 1, 1)
        prov.addWidget(node_refresh, 1, 2)
        prov.addWidget(prov_btn, 1, 3)
        prov.addWidget(export_btn, 2, 2, 1, 2)
        prov.addWidget(QtWidgets.QLabel('Node port = gateway port provisions the device on this port '
                                        '(e.g. after reconnecting the cable to a node).'), 3, 0, 1, 4)
        self.run_widgets.extend([read_ds, prov_btn])
        self.refresh_node_ports()
        self.update_dataset_label()

        lay.addWidget(form_box)
        lay.addLayout(btn_row)
        lay.addWidget(prov_box)
        lay.addWidget(self.status_tree, 1)
        return w

    def refresh_node_ports(self):
        current = self.cfg.node_comport
        self.node_port.blockSignals(True)
        self.node_port.clear()
        for p in serial.tools.list_ports.comports():
            self.node_port.addItem(f'{p.device}  ({p.description})', p.device)
        idx = self.node_port.findData(current)
        if idx >= 0:
            self.node_port.setCurrentIndex(idx)
        else:
            self.node_port.setEditText(current)
        self.node_port.blockSignals(False)

    def node_port_changed(self, text):
        data = self.node_port.currentData()
        self.cfg.node_comport = data if data else text.split()[0] if text.strip() else ''

    def update_dataset_label(self):
        if not self.cfg.dataset_tlvs:
            self.dataset_label.setText('none - read it from the gateway')
            return
        try:
            info = ot_cli.parse_dataset_tlvs(self.cfg.dataset_tlvs)
            self.dataset_label.setText(f"{info['network_name']}, channel {info['channel']}, "
                                       f"PAN ID {info['panid']}"
                                       + ('' if info['has_networkkey'] else ' (no network key!)'))
        except ValueError as exc:
            self.dataset_label.setText(f'invalid dataset: {exc}')

    def provision_node(self):
        port = self.cfg.node_comport
        target = 'the device on the gateway port' if not port or port == self.cfg.comport else port
        answer = QtWidgets.QMessageBox.question(
            self, 'Provision node',
            f'Store the Thread dataset on {target}? The node leaves its current network.')
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self.device.thread_command('provision', {'port': port, 'dataset': self.cfg.dataset_tlvs})

    def export_autoexec(self):
        if not self.cfg.dataset_tlvs:
            QtWidgets.QMessageBox.warning(self, 'Export autoexec.txt', 'Read the dataset from the gateway first.')
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save autoexec.txt (copy to the SD card root)',
                                                        'autoexec.txt', 'Text files (*.txt)')
        if not path:
            return
        try:
            with open(path, 'w', newline='\n') as f:
                f.write(ot_cli.autoexec_text(self.cfg.dataset_tlvs))
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(self, 'Export autoexec.txt', str(exc))

    def generate_credentials(self):
        self.net_key.setText(secrets.token_hex(16))
        if not self.net_extpanid.text():
            self.net_extpanid.setText(secrets.token_hex(8))

    def form_network(self):
        answer = QtWidgets.QMessageBox.question(
            self, 'Form Thread network',
            'The connected norlog leaves its current Thread network and creates a new one '
            f'("{self.cfg.network_name}", channel {self.cfg.channel}). Continue?')
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.device.thread_command('form_network', {
            'network_name': self.cfg.network_name, 'channel': self.cfg.channel,
            'panid': self.cfg.panid, 'extpanid': self.cfg.extpanid, 'networkkey': self.cfg.networkkey})

    def show_status(self, status):
        self.status_tree.clear()
        for key in ('state', 'network_name', 'channel', 'panid', 'extpanid', 'rloc16', 'extaddr',
                    'packets_received'):
            QtWidgets.QTreeWidgetItem(self.status_tree, [key, str(status.get(key, ''))])
        ip = QtWidgets.QTreeWidgetItem(self.status_tree, ['ipaddr', str(len(status.get('ipaddr', [])))])
        for a in status.get('ipaddr', []):
            QtWidgets.QTreeWidgetItem(ip, ['', a])
        for name in ('children', 'routers'):
            entries = status.get(name, [])
            node = QtWidgets.QTreeWidgetItem(self.status_tree, [name, str(len(entries))])
            for e in entries:
                label = e.get('RLOC16', e.get('Router ID', ''))
                child = QtWidgets.QTreeWidgetItem(node, [label, e.get('Extended MAC', '')])
                for k, v in e.items():
                    QtWidgets.QTreeWidgetItem(child, [k, v])
        self.status_tree.expandToDepth(0)

    # --- firmware ---

    def _build_firmware_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        self.fw_path = QtWidgets.QLineEdit(self.cfg.firmware_image)
        self.fw_path.setPlaceholderText('.../build/norlog_firmware_v0_X_rev02/zephyr/zephyr.signed.bin')
        self.fw_path.textChanged.connect(lambda t: setattr(self.cfg, 'firmware_image', t))
        browse = QtWidgets.QPushButton('Browse ...')
        browse.clicked.connect(self.browse_image)
        row.addWidget(QtWidgets.QLabel('Image'))
        row.addWidget(self.fw_path, 1)
        row.addWidget(browse)
        self.fw_info = QtWidgets.QLabel('')
        self.fw_force = QtWidgets.QCheckBox('Flash even if this image is already installed')
        self.fw_force.setChecked(self.cfg.firmware_force)
        self.fw_force.toggled.connect(lambda v: setattr(self.cfg, 'firmware_force', v))
        btn_row = QtWidgets.QHBoxLayout()
        self.fw_flash = QtWidgets.QPushButton('Flash gateway')
        self.fw_flash.clicked.connect(self.flash)
        self.fw_cancel = QtWidgets.QPushButton('Cancel')
        self.fw_cancel.clicked.connect(lambda: self.device.thread_command('flash_cancel', {}))
        btn_row.addWidget(self.fw_flash)
        btn_row.addWidget(self.fw_cancel)
        self.fw_progress = QtWidgets.QProgressBar()
        self.fw_progress.setRange(0, 100)
        self.fw_log = QtWidgets.QPlainTextEdit()
        self.fw_log.setReadOnly(True)
        lay.addLayout(row)
        lay.addWidget(self.fw_info)
        lay.addWidget(self.fw_force)
        lay.addLayout(btn_row)
        lay.addWidget(self.fw_progress)
        lay.addWidget(self.fw_log, 1)
        self.run_widgets.extend([self.fw_flash, self.fw_cancel])
        self.fw_path.textChanged.connect(self.update_image_info)
        self.update_image_info()
        return w

    def browse_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Signed firmware image', self.fw_path.text(),
                                                        'MCUboot images (*.signed.bin);;All files (*)')
        if path:
            self.fw_path.setText(path)

    def update_image_info(self):
        path = pathlib.Path(self.fw_path.text())
        if not path.is_file():
            self.fw_info.setText('')
            return
        try:
            info = smp_serial.image_info(path.read_bytes())
            self.fw_info.setText(f'Version {info["version"]}, {info["size"] // 1024} KB, '
                                 f'hash {info["hash"].hex()[:16]}...')
        except (ValueError, OSError, TypeError) as exc:
            self.fw_info.setText(f'Invalid image: {exc}')

    def flash(self):
        self.fw_progress.setValue(0)
        self.fw_log.clear()
        self.device.thread_command('flash', {'image': self.cfg.firmware_image, 'force': self.cfg.firmware_force})

    # --- data ---

    def _build_data_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel('Last packet per node and packet type (requires gateway firmware '
                                       'that forwards Thread data as "#NLD" lines)'))
        self.data_table = QtWidgets.QTableWidget(0, 5)
        self.data_table.setHorizontalHeaderLabels(['Node (MAC)', 'Type', 'Packet #', 'Received', 'Values'])
        self.data_table.horizontalHeader().setStretchLastSection(True)
        self.data_rows = {}
        lay.addWidget(self.data_table)
        return w

    def show_data(self, data):
        key = (data.get('mac', data.get('source', '?')), data.get('packet_type', '?'))
        row = self.data_rows.get(key)
        if row is None:
            row = self.data_table.rowCount()
            self.data_table.insertRow(row)
            self.data_rows[key] = row
        skip = {'packet_type', 'mac', 'packet_num', '_redvypr', 't', 'raw_data'}
        values = ', '.join(f'{k}={v:.4g}' if isinstance(v, float) else f'{k}={v}'
                           for k, v in data.items() if k not in skip and not k.startswith('_'))
        cells = [key[0], key[1], str(data.get('packet_num', '')), time.strftime('%H:%M:%S'), values]
        for col, text in enumerate(cells):
            self.data_table.setItem(row, col, QtWidgets.QTableWidgetItem(text))

    # --- data from the device thread ---

    def on_new_data(self, data_list):
        for data in data_list:
            try:
                packetid = data['_redvypr']['packetid']
            except (KeyError, TypeError):
                continue
            if packetid == 'console':
                self.console_text.appendPlainText(data.get('line', ''))
            elif packetid == 'thread_status':
                self.show_status(data.get('thread_status', {}))
                if 'devices' in data:
                    self.show_devices(data['devices'])
            elif packetid == 'flash_status':
                if 'progress' in data:
                    self.fw_progress.setValue(int(data['progress']))
                self.fw_log.appendPlainText(f"[{data.get('state')}] {data.get('message', '')}")
            elif packetid == 'command_result':
                self.show_result(data)
            elif str(packetid).startswith('norlog_') and 'packet_type' in data:
                self.show_data(data)

    def show_result(self, data):
        text = f"[{data.get('command')}] {'OK' if data.get('ok') else 'ERROR'}: {data.get('message', '')}"
        self.console_text.appendPlainText(text)
        if data.get('command') == 'dataset' and data.get('ok'):
            self.cfg.dataset_tlvs = data.get('dataset_tlvs', '')
            self.update_dataset_label()
        elif data.get('command') == 'flash' and not data.get('ok'):
            self.fw_log.appendPlainText(text)

    def update_run_state(self):
        running = self.device.get_thread_status()['thread_running']
        for w in self.run_widgets:
            w.setEnabled(running)
