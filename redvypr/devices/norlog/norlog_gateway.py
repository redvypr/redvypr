"""
norlog gateway device

A norlog connected via UART acts as the gateway between redvypr and a Thread
network of norlog sensor nodes. The device

- provides a console to the norlog Zephyr shell,
- forms a Thread network and shows its state (OpenThread CLI, "ot ..."),
- flashes the gateway firmware over UART (MCUmgr/SMP via the norlog_loader),
- publishes norlog data packets received from the Thread network.

Live data over Thread (firmware >= 0.4.32): a device sends its logged packets with
'norlog pub <types> [sinks|<ipv6> ...]', the gateway receives them as sink ('norlog sink on')
and prints each one as

    #NLD <source> <base64 encoded norlog CBOR packet>

<source> is the RLOC16 of the sending node. The packets are identical to the log on the SD
card. The tab "Live data" shows the incoming packets with the lost ones (gaps in
packet_num_type); its "Subscriptions" sets what the devices send (stored on them and in the
configuration: live_pub per hardware ID, set again at the start with live_apply; the gateway
is always the sink, live_sink).

"Save data" (save_data) starts the writer devices of save_channels (gear button next to it):
ordinary redvypr writer devices (for now sqlite_writer) that subscribe to the packets of this
gateway ("@p:'<gateway>'", optionally only some packet types) and are shown in the device list.

All packets carry the norlog they belong to in the header:

    device   = 'norlog_<sn>', or 'norlog' without serial number (or before
               the info of the norlog was read)
    deviceid = hardware ID (hwid, FICR device ID of the nRF52840, unique per
               chip; the 'mac' of the CBOR packets), None if not known yet
    sensorid = serial number (user property 'sn'), if set
    publisher = this gateway device (set by redvypr)

Published packets (packetid = type of the packet):

    info            device info (gateway: 'norlog info json', members: CoAP GET /info)
    <packet_type>   decoded '#NLD' data packet (e.g. 'board_temp')

The messages for the GUI of this device (console, command_result,
thread_status with the device list, flash_status, props, fs_progress,
fs_result, time_result, sync_progress, sync_result) go through the statusqueue of the device to its widget. They are
published as well only with the option publish_raw_data (default off), with
the same header. Messages about a node keep its key ('gateway' or RLOC16) in
'target'.

Data download ("Data" tab of the settings window): the log files of the SD card
are copied 1:1 into <archive_folder>/<hwid>/ (only what is new, see
norlog_archive); optionally the new packets are published with their
measurement time, e.g. for the database writers. "Convert to SQLite" turns
selected archive files into an SQLite database in the redvypr format: the packets in
redvypr_raw and optionally a data_flat table for the plots (norlog_convert, also on the
command line). Live data and SD card packets have the same deviceid (mac), boot and
packet_num (uid_keys of the raw table): in one database each packet is stored once. Their
time 't' is uptime_ms + offset_ms of the node (t_source 'node', firmware >= 0.4.35).

The info packet contains the info JSON as it is (nested) plus 'link': the radio
link as seen from the gateway (RSSI, LQ, role, next hop, ...). Metadata is
attached to the addresses '@di:<hwid>' (user properties, board, firmware) and
'<key>@di:<hwid>' (units); it is sent with the first info packet of a device
and again when it changes. These addresses name the norlog (deviceid), so redvypr
does not bind them to the device name or packetid: they stay valid after a
change of the serial number and apply to the '#NLD' data as well.
"""

import base64
import collections
import datetime
import copy
import binascii
import json
import logging
import pathlib
import queue
import re
import secrets
import sys
import time
import typing
import zlib

import pydantic
import qtawesome
import serial
import serial.tools.list_ports
from PyQt6 import QtCore, QtGui, QtWidgets

import redvypr.metadata
from redvypr.device import RedvyprDeviceCustomConfig
from redvypr.gui import iconnames
from redvypr.redvypr_datadict import check_for_command, create_redvypr_dict
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple

from . import adc_sequence
from . import device_list
from . import mag_calibration
from . import norlog_archive
from . import norlog_cbor
from . import norlog_convert
from . import ot_cli
from . import poly_calibration
from . import smp_serial
from .cbor_mini import CBORDecodeError

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.norlog_gateway')
logger.setLevel(logging.INFO)

redvypr_devicemodule = True

DATA_PREFIX = "#NLD "
LIVE_GATEWAY_DEFAULT = "all"    # 'norlog pub' of the gateway without an entry in live_pub: all own packets


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
    info_interval_s: float = pydantic.Field(default=10.0, ge=0, description='Interval for reading the device '
                                                                            'info (battery, temperature, '
                                                                            'firmware) of all devices, '
                                                                            '0 = only on request')
    coap_timeout_s: int = pydantic.Field(default=5, ge=1, le=60, description='Timeout of a CoAP request to a '
                                                                             'Thread member')
    console_show_commands: bool = pydantic.Field(default=False, description='Show the traffic of internal '
                                                                            'ot commands in the console')
    archive_folder: str = pydantic.Field(default='norlog_archive', description='Folder of the downloaded log files '
                                                                          '(one subfolder per hardware ID)')
    archive_publish: bool = pydantic.Field(default=False, description='Publish the downloaded packets with their '
                                                                      'measurement time (e.g. for the database '
                                                                      'writers)')
    publish_raw_data: bool = pydantic.Field(default=False, description='Publish also the raw data of the gateway: '
                                                                       'console lines, command results, Thread '
                                                                       'status with device list, transfer status')
    dataset_tlvs: str = pydantic.Field(default='', description='Active operational dataset (hex TLVs) used to '
                                                               'provision nodes. Contains the network key!')
    node_comport: str = pydantic.Field(default='', description='Serial port of a node to be provisioned')
    firmware_image: str = pydantic.Field(default='', description='Signed firmware image (zephyr.signed.bin)')
    firmware_force: bool = pydantic.Field(default=False, description='Flash even if the image is already installed')
    loader_image: str = pydantic.Field(default='', description='Signed loader image '
                                                                '(build/norlog_loader/zephyr/zephyr.signed.bin)')
    prefer_leader: bool = pydantic.Field(default=False, description='The gateway prefers the Thread leader role: '
                                                                    'leader weight 72 (default 64, set again after '
                                                                    'a restart of the gateway); if it is not '
                                                                    'leader, it becomes leader again (at most '
                                                                    'every 10 minutes)')
    live_sink: bool = pydantic.Field(default=True, description='Live data: the gateway is a sink of the Thread '
                                                               'network ("norlog sink on", firmware >= 0.4.32): '
                                                               'devices that send to "sinks" send to it, and it '
                                                               'outputs its own packets (firmware >= 0.4.33)')
    live_sink_types: typing.List[str] = pydantic.Field(default_factory=list, description='Not used anymore: the '
                                                                                         'gateway is the sink for '
                                                                                         'all packet types')
    live_pub: typing.Dict[str, str] = pydantic.Field(default_factory=dict, description='Live data sent by the '
                                                                                       'devices ("norlog pub"), '
                                                                                       'key: hardware ID, value: '
                                                                                       '"off" or "<types> '
                                                                                       '[sinks|<ipv6> ...]"')
    live_apply: bool = pydantic.Field(default=True, description='Set live_sink on the gateway at the start and '
                                                                'live_pub on each device once per start when it '
                                                                'is seen (both are also stored on the devices)')
    save_data: bool = pydantic.Field(default=False, description='Save data: start the writer devices of '
                                                                'save_channels (stop them when switched off)')
    save_channels: typing.List[str] = pydantic.Field(default_factory=list, description='Names of the writer '
                                                                                       'devices (e.g. '
                                                                                       'sqlite_writer) that save '
                                                                                       'the data of this gateway')


# --------------------------------------------------------------------------
# Device thread
# --------------------------------------------------------------------------

class RateMeter:
    """
    Transfer rate over a sliding window. The clock starts with the first progress
    report, so waiting times before the transfer (e.g. erasing slot 0) do not count.
    """

    def __init__(self, window_s=5.0):
        self.window_s = window_s
        self.samples = collections.deque()
        self.first = None

    def update(self, done):
        """Add a progress value (bytes); returns the current rate in KB/s."""
        now = time.monotonic()
        if self.first is None:
            self.first = (now, done)
        self.samples.append((now, done))
        while len(self.samples) > 2 and now - self.samples[0][0] > self.window_s:
            self.samples.popleft()
        t, d = self.samples[0]
        return (done - d) / (now - t) / 1024 if now > t else 0.0

    def average(self):
        """Average rate in KB/s from the first to the last progress report."""
        if self.first is None or len(self.samples) < 1:
            return 0.0
        (t0, d0), (t1, d1) = self.first, self.samples[-1]
        return (d1 - d0) / (t1 - t0) / 1024 if t1 > t0 else 0.0


class _Gateway:
    """State of the running device thread."""

    def __init__(self, device_info, pdconfig, dataqueue, datainqueue, statusqueue=None):
        self.device_info = device_info
        self.device = device_info['device']
        self.config = pdconfig
        self.dataqueue = dataqueue
        self.datainqueue = datainqueue
        self.statusqueue = statusqueue  # messages for the GUI (not published)
        self.ser = None
        self.reader = ot_cli.LineReader()
        self.cli = None
        self.stop_requested = False
        self.deferred = []              # commands that arrived during a flash, download or file list
        self.npackets = 0
        self.last_rx = None             # time.monotonic() of the last line from the gateway
        self.data_sources = {}          # '#NLD' source -> {'last_seen', 'packets', 'mac'}
        self.infos = {}                 # 'gateway' or RLOC16 -> info dict (norlog info / CoAP /info)
        self.info_times = {}            # 'gateway' or RLOC16 -> time.time() of the last successful read
        self.info_mid = {}              # ... middle of that request (device time of the info ~ this PC time)
        self.info_rtt = {}              # ... duration of that request [s]
        self.props_cache = {}           # hwid (or 'gateway'/RLOC16) -> user properties (sn, desc, loc, ...)
        self.last_status = {}
        self.meta_sent = {}             # hwid -> device metadata sent last
        self.units_sent = {}            # hwid -> set of keys whose unit was sent
        self.live_applied = set()       # hwids whose live_pub was set in this start

    # --- publishing ---

    def identity(self, target='gateway', hwid=None):
        """
        device, deviceid and sensorid of a norlog for the packet header.
        target: 'gateway' or RLOC16 (its read info gives the hwid), or hwid directly.
        """
        key = target or 'gateway'
        info = self.infos.get(key) or {}
        if hwid and info.get('hwid') != hwid:
            # hwid given (e.g. 'mac' of a packet): not the device behind key
            info = next((i for i in self.infos.values() if i and i.get('hwid') == hwid), {})
            props = self.props_cache.get(hwid) or {}
        else:
            hwid = hwid or info.get('hwid')
            props = (self.props_cache.get(hwid) if hwid else None) or self.props_cache.get(key) or {}
        sn = props.get('sn') or info.get('sn') or None
        return (f'norlog_{sn}' if sn else 'norlog'), hwid, sn

    def to_gui(self, packetid, payload):
        """
        Message for the GUI of this device (console, results, device list, ...). It goes
        through the statusqueue and is not published as redvypr data. Same form as a
        packet, the header names the norlog payload['target'] (default: the gateway).
        """
        device, hwid, sn = self.identity(payload.get('target', 'gateway'))
        data = create_redvypr_dict(device=device, deviceid=hwid, sensorid=sn, packetid=packetid)
        data.update(payload)
        if self.config.publish_raw_data:
            # Own header for the published copy: redvypr changes it when distributing
            pub = dict(data)
            pub['_redvypr'] = copy.deepcopy(data['_redvypr'])
            self.dataqueue.put(pub)
        if self.statusqueue is None:
            return
        try:
            self.statusqueue.put_nowait(data)
        except queue.Full:
            logger.debug('statusqueue full, GUI message dropped')

    def console(self, line):
        self.to_gui('console', {'line': line})

    def result(self, command, ok, message='', **extra):
        self.to_gui('command_result', {'command': command, 'ok': ok, 'message': message, **extra})

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
        t, t_source = norlog_cbor.packet_time(pkt)
        if t is None:
            t, t_source = time.time(), 'received'
        # 'mac' of the CBOR packets is the hwid of the sending norlog
        device, hwid, sn = self.identity(device_list.norm_rloc16(source), hwid=pkt.get('mac'))
        data = create_redvypr_dict(device=device, deviceid=hwid, sensorid=sn,
                                   packetid=pkt.get('packet_type', 'data'), tu=t)
        data.update(pkt)
        data['t'] = t
        data['t_source'] = t_source
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
        for line in self.reader.drain(self.ser):
            self.on_gateway_line(line)

    # --- commands ---

    def check_commands(self, during_flash=False):
        """
        Process commands from the GUI. Returns True if a running flash shall be cancelled.
        during_flash: only stop/cancel act at once (flash, download, file list are running); other
        commands wait and run afterwards, e.g. "List files" of a second device.
        """
        cancel = False
        if not during_flash:
            while self.deferred and not self.stop_requested:
                self.execute(*self.deferred.pop(0))
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
                if command in ('flash_cancel', 'sync_cancel', 'mag_cal_stop'):
                    cancel = True
                elif (command, args) not in self.deferred:
                    logger.info(f'Command {command!r} waits for the running flash/download')
                    self.deferred.append((command, args))
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
            elif command == 'make_leader':
                self.make_leader()
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
            elif command == 'read_device_info':
                self.query_info(args.get('targets', 'all'))
            elif command == 'refresh':
                self.read_status()
                self.query_info('all', refresh_props=True)
            elif command == 'data_sync':
                self.data_sync(args.get('target', 'gateway'), args.get('folder') or self.config.archive_folder,
                               bool(args.get('publish', self.config.archive_publish)), args.get('stems'),
                               bool(args.get('newest_first', False)), args.get('reload'))
            elif command == 'data_list':
                self.data_list(args.get('target', 'gateway'), args.get('folder') or self.config.archive_folder,
                               bool(args.get('verify', False)))
            elif command == 'set_time':
                self.set_time(args.get('targets') or ['gateway'], force=bool(args.get('force')))
            elif command == 'radio_set':
                self.set_radio(args.get('target') or 'gateway', args.get('dbm'))
            elif command == 'mag_read':
                self.mag_read(args.get('target') or 'gateway')
            elif command == 'mag_cal':
                self.mag_calibration_record(args.get('target') or 'gateway', int(args.get('dur', 60)),
                                            int(args.get('hz', 10)))
            elif command == 'cal_get':
                self.cal_get(args.get('target') or 'gateway')
            elif command == 'cal_set':
                self.cal_set(args.get('target') or 'gateway', args.get('name', 'mag'), args.get('text', ''))
            elif command in ('adc_get', 'adc_set', 'adc_read', 'adc_cal_set'):
                self.adc_command(args.get('target') or 'gateway', command[4:], args.get('sensor', 'adc_brd'),
                                 args.get('text', ''), args.get('channel', ''))
            elif command in ('nmea_get', 'nmea_set'):
                self.nmea_command(args.get('target') or 'gateway', command[5:], args.get('values') or {})
            elif command == 'props_read':
                self.props_command(args.get('target', 'gateway'), {})
            elif command == 'props_set':
                self.props_command(args.get('target', 'gateway'), args.get('values', {}))
            elif command == 'fs':
                self.fs_command(args)
            elif command == 'fw_update_node':
                self.fw_update_node(args.get('target', ''), args.get('image', ''), bool(args.get('force', False)))
            elif command == 'loader_update':
                self.loader_update(args.get('target', ''), args.get('image', ''))
            elif command == 'live_read':
                self.live_read(args.get('targets', 'all'))
            elif command == 'live_pub_set':
                self.live_pub_set(args.get('target', 'gateway'), args.get('text', 'off'), args.get('hwid'))
            elif command == 'live_sink_set':
                self.live_sink_apply(report=True)
            elif command == 'battery_upload':
                self.battery_upload(args.get('path', ''))
            elif command == 'provision':
                self.provision(args.get('port', ''), args.get('dataset', ''))
            elif command == 'flash':
                self.flash(args.get('image', ''), bool(args.get('force', False)))
            else:
                # e.g. redvypr's own 'info' broadcast: not for us, ignore quietly
                logger.debug(f'Ignoring command {command!r}')
        except (ot_cli.OtError, TimeoutError, smp_serial.SmpError, OSError, ValueError) as exc:
            self.result(command, False, str(exc))
        except Exception as exc:    # never let a single command kill the device thread
            logger.exception(f'Command {command!r} failed')
            self.result(command, False, f'Internal error: {exc!r}')

    def battery_upload(self, path):
        """Load a battery model (.inc from nPM PowerUP) into the gateway norlog (serial)."""
        p = pathlib.Path(path)
        if not p.is_file():
            raise ValueError(f'Battery model not found: {path}')
        text = p.read_text(errors='replace')
        last = [0.0]

        def progress(done, total):
            if time.monotonic() - last[0] >= 1.0 or done >= total:
                last[0] = time.monotonic()
                self.result('battery_upload', True, f'{p.name}: {done * 100 // total} %',
                            progress=done * 100 // total)

        name = ot_cli.upload_battery_model(self.cli, text, progress=progress)
        self.result('battery_upload', True, f'Battery model "{name}" loaded and active (custom)',
                    progress=100, done=True)
        self.query_info(['gateway'], report=False)

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

    # Automatic leader role (prefer_leader): at most one attempt in this time [s]
    LEADER_RETRY_S = 600

    def make_leader(self, automatic=False):
        """Make the gateway the Thread leader (button, or prefer_leader)."""
        self.t_leader_attempt = time.monotonic()
        what = 'Gateway is not leader (prefer leader role): ' if automatic else ''
        self.result('make_leader', True, what + 'becoming leader, the network is interrupted shortly ...')
        res = ot_cli.make_leader(self.cli)
        if res['leader']:
            self.result('make_leader', True, f"Gateway is leader (leader weight {res['leader_weight']}, "
                                             f"partition {res['partition_id']})")
        else:
            self.result('make_leader', False, f"Gateway is not leader yet (state {res['state']!r}), "
                                              f"see 'Read status' later")
        self.read_status(check_leader=False)

    def check_prefer_leader(self, status):
        """prefer_leader: leader weight after a restart of the gateway, leader role again."""
        if not self.config.prefer_leader or status.get('state') not in ('child', 'router', 'leader'):
            return False
        if status.get('state') in ('router', 'leader') and status.get('leader_weight') is not None \
                and status['leader_weight'] != ot_cli.LEADER_WEIGHT_PREFERRED:
            ot_cli.ensure_leader_weight(self.cli)
            self.result('make_leader', True, f'Leader weight set to {ot_cli.LEADER_WEIGHT_PREFERRED} '
                                             f'(prefer leader role)')
        last = getattr(self, 't_leader_attempt', None)
        if status.get('state') != 'leader' and (last is None or time.monotonic() - last >= self.LEADER_RETRY_S):
            self.make_leader(automatic=True)
            return True
        return False

    def read_status(self, check_leader=True):
        status = ot_cli.read_status(self.cli)
        status['packets_received'] = self.npackets
        self.last_status = status
        self.publish_devices()
        if check_leader and self.check_prefer_leader(status):
            return

    def build_devices(self):
        rx_age = None if self.last_rx is None else time.monotonic() - self.last_rx
        devices = device_list.build_device_list(self.last_status, gateway_port=self.config.comport,
                                                serial_rx_age_s=rx_age, data_sources=self.data_sources,
                                                infos=self.infos)
        now = time.time()
        for d in devices:
            key = 'gateway' if d.get('role') == device_list.ROLE_GATEWAY else d.get('rloc16')
            if key in self.info_times:
                d['info_age_s'] = now - self.info_times[key]
                d['clock_offset_s'] = self._clock_offset(d.get('info'), self.info_mid.get(key, self.info_times[key]))
                d['clock_tolerance_s'] = self._clock_tolerance(d.get('info'), self.info_rtt.get(key))
            props = self.props_cache.get(d.get('hwid')) or self.props_cache.get(key) or {}
            d['props'] = props
            for name in ('sn', 'desc', 'loc'):
                if props.get(name):
                    d[name] = props[name]
        return devices

    @staticmethod
    def _clock_has_ms(info):
        t = (info or {}).get('time') or ''
        return '.' in t     # firmware >= 0.4.8: system time with ms

    @classmethod
    def _clock_offset(cls, info, read_time):
        """
        System clock of the device (info 'time') minus this PC in the middle of the
        info request; None without a time. Firmware < 0.4.8 sends whole seconds
        (truncated: +0.5 s on average).
        """
        t = (info or {}).get('time')
        if not t or t == '-':
            return None
        try:
            dt = datetime.datetime.fromisoformat(t.replace('Z', '+00:00'))
        except ValueError:
            return None
        return dt.timestamp() + (0.0 if cls._clock_has_ms(info) else 0.5) - read_time

    @classmethod
    def _clock_tolerance(cls, info, rtt):
        """Offsets within this are 'ok': half the request time (+ margin), whole seconds: 2 s."""
        if not cls._clock_has_ms(info):
            return 2.0
        return 0.25 + (rtt or 0.0) / 2

    def publish_devices(self):
        self.to_gui('thread_status', {'thread_status': self.last_status, 'devices': self.build_devices()})

    # --- info packets (one redvypr device per norlog, device = hwid) ---

    # Radio link as seen from the gateway (entry of the device list) -> 'link'
    LINK_FIELDS = ('rloc16', 'extaddr', 'connection', 'link', 'thread_role', 'quality', 'rssi_avg',
                   'rssi_last', 'lq_in', 'lq_out', 'path_cost', 'next_hop', 'age_s')
    # Units of the info values, sent once per device as metadata
    INFO_UNITS = {
        "uptime_s": 's', "board_temp_c": 'degC', "nrf_temp_c": 'degC', "gnss['cno']": 'dB-Hz', "gnss['age']": 's', "gnss['lat']": 'degN', "gnss['lon']": 'degE', "gnss['alt']": 'm',
        "battery['mv']": 'mV', "battery['soc']": '%', "battery['current_ma']": 'mA',
        "battery['tte_min']": 'min', "battery['ttf_min']": 'min',
        "radio['txpower_dbm']": 'dBm', "radio['antenna_dbm']": 'dBm', "radio['soc_dbm']": 'dBm',
        "radio['pa_gain_db']": 'dB', "radio['max_dbm']": 'dBm',
        "thread['parent']['rssi']": 'dBm',
        "link['rssi_avg']": 'dBm', "link['rssi_last']": 'dBm', "link['age_s']": 's',
    }

    @staticmethod
    def _has_key(data, key):
        """True if the (nested) key "a['b']['c']" exists in data."""
        node = data
        for part in key.replace("']", '').split("['"):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return True

    def publish_info(self, entry):
        """Publish the info of one device (entry of build_devices()) as packet 'info'."""
        info = entry.get('info') or {}
        hwid = info.get('hwid')
        if not hwid or (len(info) == 1 and 'error' in info):
            return
        key = 'gateway' if entry.get('role') == device_list.ROLE_GATEWAY else entry.get('rloc16')
        props = entry.get('props') or {}
        device, hwid, sn = self.identity(key, hwid=hwid)

        t = self.info_times.get(key) or time.time()
        data = create_redvypr_dict(device=device, deviceid=hwid, packetid='info', sensorid=sn, tu=t)
        data.update({k: v for k, v in info.items() if k != 'error'})
        data['link'] = {f: entry.get(f) for f in self.LINK_FIELDS}
        data['t'] = t

        # Device metadata: user properties, board and firmware; sent again on changes.
        # A deleted property is sent once with an empty value.
        meta = {'hwid': hwid, 'board': info.get('board', ''), 'firmware': info.get('image') or
                info.get('firmware', ''), **{k: v for k, v in props.items() if v not in (None, '')}}
        for k in self.meta_sent.get(hwid, {}):
            meta.setdefault(k, '')
        if meta != self.meta_sent.get(hwid):
            redvypr.metadata.add_metadata2datapacket(data, address=f"@di:'{hwid}'", metadict=meta)
            self.meta_sent[hwid] = {k: v for k, v in meta.items() if v != ''}

        # Units of the values present (once per device and key)
        sent = self.units_sent.setdefault(hwid, set())
        for datakey, unit in self.INFO_UNITS.items():
            if datakey not in sent and self._has_key(data, datakey):
                redvypr.metadata.add_metadata2datapacket(data, address=f"{datakey}@di:'{hwid}'",
                                                         metadict={'unit': unit})
                sent.add(datakey)
        self.dataqueue.put(data)

    def store_info(self, key, info=None, error=None, t_request=None):
        """
        Store a read info; on error the last good values are kept and marked with the error.
        t_request: time.time() when the request was sent (for the clock offset).
        """
        if error is None:
            now = time.time()
            self.infos[key] = info
            self.info_times[key] = now
            self.info_mid[key] = (t_request + now) / 2 if t_request else now
            self.info_rtt[key] = now - t_request if t_request else None
        else:
            last = {k: v for k, v in (self.infos.get(key) or {}).items() if k != 'error'}
            self.infos[key] = {**last, 'error': error}

    def _props_key(self, key):
        """Properties are cached per hardware ID (the RLOC16 of a node can change)."""
        return (self.infos.get(key) or {}).get('hwid') or key

    def update_props(self, key, address, force=False):
        """Read the user properties of a device once (or again with force) into the cache."""
        pk = self._props_key(key)
        if pk in self.props_cache and not force:
            return
        try:
            self.props_cache[pk] = ot_cli.props_read(self.cli, address)
        except (ot_cli.OtError, TimeoutError, ValueError):
            self.props_cache[pk] = {}       # e.g. firmware without properties: do not ask on every poll

    def query_info(self, targets='all', report=True, refresh_props=False):
        """
        Read the device info: gateway via 'norlog info json' (UART), members via
        CoAP GET /info ('norlog coap get' on the gateway).
        targets: 'all' or a list of keys ('gateway' or RLOC16 like '0xc001').
        report: publish a command result (False for the periodic poll).
        refresh_props: read the user properties again (otherwise only once per device).
        """
        if not self.last_status:
            self.read_status()
        wanted = None if targets == 'all' else set(targets)
        done, failed = 0, 0
        read_ok = set()     # keys whose info was read now -> 'info' packets

        if wanted is None or 'gateway' in wanted:
            try:
                t_request = time.time()
                self.store_info('gateway', json.loads(self.cli.shell_query('norlog info json', '#NLI ')),
                                t_request=t_request)
                self.update_props('gateway', None, refresh_props)
                read_ok.add('gateway')
                done += 1
            except (TimeoutError, ValueError) as exc:
                self.store_info('gateway', error=str(exc))
                failed += 1

        members = [d for d in self.build_devices()[1:]
                   if d.get('rloc16') and (wanted is None or d['rloc16'] in wanted)]
        if members:
            prefix = ot_cli.mesh_local_prefix(self.cli, self.last_status.get('ipaddr'))
            for d in members:
                rloc = d['rloc16']
                try:
                    addr = ot_cli.rloc_address(prefix, rloc)
                    t_request = time.time()
                    payload = ot_cli.coap_get(self.cli, addr, 'info', timeout=self.config.coap_timeout_s)
                    self.store_info(rloc, json.loads(payload.decode(errors='replace')), t_request=t_request)
                    self.update_props(rloc, addr, refresh_props)
                    read_ok.add(rloc)
                    done += 1
                except (ot_cli.OtError, TimeoutError, ValueError) as exc:
                    self.store_info(rloc, error=str(exc))
                    failed += 1

        devices = self.build_devices()
        self.to_gui('thread_status', {'thread_status': self.last_status, 'devices': devices})
        for d in devices:
            key = 'gateway' if d.get('role') == device_list.ROLE_GATEWAY else d.get('rloc16')
            if key in read_ok:
                self.publish_info(d)
        self.live_apply_seen(devices, read_ok)
        if report:
            self.result('read_device_info', failed == 0, f'Device info read: {done} ok, {failed} failed')

    # --- firmware update ---

    # --- files (SD card) and firmware update over Thread ---

    GATEWAY_XFER_FILE = '/fw/push.bin'      # firmware image on the gateway's SD card for 'fs push'

    def target_address(self, target):
        """None for the gateway itself, otherwise the RLOC address of the member (target = RLOC16)."""
        if not target or target == 'gateway':
            return None
        if not self.last_status:
            self.read_status()
        prefix = ot_cli.mesh_local_prefix(self.cli, self.last_status.get('ipaddr'))
        return ot_cli.rloc_address(prefix, target)

    def gateway_has_sd(self):
        try:
            ot_cli.fs_local(self.cli, 'stat', '/')
            return True
        except (ot_cli.OtError, TimeoutError):
            return False

    def fs_progress(self, target, op, done, total):
        self.to_gui('fs_progress', {'target': target, 'op': op, 'done': done, 'total': total})

    def fs_result(self, target, op, ok, message='', **extra):
        self.to_gui('fs_result', {'target': target, 'op': op, 'ok': ok, 'message': message, **extra})

    def fs_write_direct(self, address, data, remote, progress=None):
        """Write a file to a member block by block through the gateway (no SD card on the gateway)."""
        return ot_cli.fs_upload(self.cli, address, data, remote, progress, resume=True)

    # --- data download (archive of the SD card log files) ---

    def data_list(self, target, folder, verify=False):
        """
        Log files of the card compared with the archive, without download: answer 'sync_list'.
        verify: compare the archived files completely by CRC (slow), progress as 'sync_progress'.
        """
        last = [0.0]

        def progress(i, n, name):
            if time.monotonic() - last[0] >= 0.3 or i >= n:
                last[0] = time.monotonic()
                self.to_gui('sync_progress', {'target': target, 'verify': True, 'done': i, 'total': n,
                                              'file': name})

        def list_progress(entries, total=None):
            # each page of the directory (about 12 entries) at once to the table
            self.to_gui('sync_list_partial', {'target': target, 'n': len(entries), 'total': total,
                                              'files': [{'name': e['n'], 'card': e.get('s', 0)} for e in entries
                                                        if not e.get('d') and e['n'].startswith('data_')]})
            if self.check_commands(during_flash=True):
                raise norlog_archive.ArchiveError('cancelled while reading the file list')

        def catalog_progress(done, total):
            if time.monotonic() - last[0] >= 0.3 or done >= total:
                last[0] = time.monotonic()
                self.to_gui('sync_progress', {'target': target, 'catalog': True, 'done': done, 'total': total})

        try:
            hwid = (self.infos.get(target or 'gateway') or {}).get('hwid')
            remote = norlog_archive.RemoteFiles(self.cli, self.target_address(target))
            res = norlog_archive.plan(remote, folder, hwid=hwid, verify=verify,
                                      progress=progress if verify else None,
                                      cancel=lambda: self.check_commands(during_flash=True),
                                      list_progress=list_progress, catalog_progress=catalog_progress)
        except (norlog_archive.ArchiveError, ot_cli.OtError, TimeoutError, OSError, ValueError) as exc:
            self.to_gui('sync_list', {'target': target, 'ok': False, 'message': str(exc)})
            return
        self.to_gui('sync_list', {'target': target, 'ok': True, **res})

    def data_sync(self, target, folder, publish, stems=None, newest_first=False, reload=None):
        """
        Copy the new log data of a norlog into the archive folder and, with publish,
        publish the packets that were not published yet (with their measurement time).
        stems: only these data files (norlog_archive.file_stem), None = all; newest_first: order;
        reload: file names to load again (found different by a verified list).
        """
        meter = RateMeter()
        last = [0.0]

        def progress(done, total, name):
            now = time.monotonic()
            if now - last[0] >= 0.3 or done >= total:
                last[0] = now
                self.to_gui('sync_progress', {'target': target, 'done': done, 'total': total, 'file': name,
                                              'rate': meter.update(done)})

        try:
            address = self.target_address(target)
            hwid = (self.infos.get(target or 'gateway') or {}).get('hwid')
            remote = norlog_archive.RemoteFiles(self.cli, address)
            res = norlog_archive.sync(remote, folder, hwid=hwid, progress=progress,
                                      cancel=lambda: self.check_commands(during_flash=True),
                                      stems=set(stems) if stems is not None else None, newest_first=newest_first,
                                      reload=set(reload or ()))
        except (norlog_archive.ArchiveError, ot_cli.OtError, TimeoutError, OSError, ValueError) as exc:
            self.to_gui('sync_result', {'target': target, 'ok': False, 'message': str(exc)})
            return
        changed = [f for f in res['files'] if f['new'] != f['old'] or f['status'] == 'replaced']
        replaced = [f['name'] for f in res['files'] if f['status'] == 'replaced']
        text = (f"{res['bytes'] / 1024:.1f} KB in {len(changed)} file(s) "
                f"({meter.average():.1f} KB/s) to {res['dir']}" if res['bytes'] else
                f"nothing new, archive {res['dir']}")
        if replaced:
            text += f"; card changed, old copies kept: {', '.join(replaced)}"
        if res['cancelled']:
            text = 'cancelled after ' + text
        published = 0
        if publish and not res['cancelled']:
            try:
                for pkt in norlog_archive.new_packets(res['dir']):
                    self.publish_archive_packet(pkt)
                    published += 1
                waiting = norlog_archive.waiting_files(res['dir'])
            except (OSError, ValueError) as exc:
                self.to_gui('sync_result', {'target': target, 'ok': False, 'message': f'{text}; publishing: {exc}'})
                return
            text += f"; {published} packet(s) published"
            if waiting:
                text += (f"; {len(waiting)} file(s) wait for the time of their boot "
                         f"(clock not set, see 'Set clock')")
        errors = res.get('errors') or []
        if errors:
            text += f"; {len(errors)} file(s) FAILED (loaded again at the next download): " + "; ".join(errors)
        self.to_gui('sync_result', {'target': target, 'ok': not res['cancelled'] and not errors, 'message': text,
                                    'files': res['files'], 'dir': res['dir'], 'published': published})

    def publish_archive_packet(self, pkt):
        """Publish a packet of the archive like the live data: header of its norlog, measurement time."""
        _device, _hwid, sn = self.identity(hwid=pkt.get('mac'))
        self.dataqueue.put(norlog_archive.to_redvypr_packet(pkt, sn))

    # --- clock ---

    TIME_MAX_OFFSET_S = 0.5     # set again if the clock is further off after setting
    TIME_ATTEMPTS = 3

    def measure_time(self, address):
        """
        Read the clock of a device and compare it with this PC: offset = device time
        minus PC time in the middle of the request, error bound = half the round trip.
        """
        t1 = time.time()
        st = ot_cli.time_get(self.cli, address, timeout=self.config.coap_timeout_s)
        t4 = time.time()
        return st, st['t'] / 1000.0 - (t1 + t4) / 2, (t4 - t1) / 2

    # --- magnetometer and calibrations (firmware >= 0.4.12) ---

    def mag_read(self, target):
        result = {'target': target, 'ok': False}
        try:
            result.update(ok=True, mag=ot_cli.mag_read(self.cli, self.target_address(target),
                                                       timeout=self.config.coap_timeout_s))
        except (ot_cli.OtError, TimeoutError, ValueError) as exc:
            result['message'] = str(exc)
        self.to_gui('mag_result', result)

    def mag_calibration_record(self, target, dur, hz):
        """
        Record points for the magnetometer calibration on the device: start, then every
        second the status and the new values (to the GUI as 'mag_cal_progress'), at the end
        all values ('mag_cal_done'). 'mag_cal_stop' from the GUI ends the recording.
        """
        address = None
        points = []
        result = {'target': target, 'ok': False, 'points': points}
        try:
            address = self.target_address(target)
            st = ot_cli.mag_cal_start(self.cli, dur, hz, address, timeout=self.config.coap_timeout_s)
            stopped = False
            deadline = time.monotonic() + dur + 30
            while True:
                if self.check_commands(during_flash=True) and not stopped:
                    ot_cli.mag_cal_stop(self.cli, address, timeout=self.config.coap_timeout_s)
                    stopped = True
                time.sleep(1.0)
                st = ot_cli.mag_cal_status(self.cli, address, timeout=self.config.coap_timeout_s)
                while len(points) < st.get('n', 0):
                    chunk = ot_cli.mag_cal_data(self.cli, len(points), address=address,
                                                timeout=self.config.coap_timeout_s)
                    if not chunk:
                        break
                    points.extend(chunk)
                    self.to_gui('mag_cal_progress', {'target': target, 'state': st.get('state'), 'n': len(points),
                                                     'total': st.get('total'), 'new': chunk})
                if st.get('state') != 'run' or time.monotonic() > deadline:
                    break
            result.update(ok=bool(points), state=st.get('state'),
                          message=f"{len(points)} values recorded" + (' (stopped)' if stopped else ''))
        except (ot_cli.OtError, TimeoutError, ValueError, KeyError) as exc:
            result['message'] = str(exc)
        self.to_gui('mag_cal_done', result)

    def cal_get(self, target):
        result = {'target': target, 'ok': False}
        try:
            result.update(ok=True, cal=ot_cli.cal_get(self.cli, self.target_address(target),
                                                      timeout=self.config.coap_timeout_s))
        except (ot_cli.OtError, TimeoutError, ValueError) as exc:
            result['message'] = str(exc)
        self.to_gui('cal_result', result)

    def cal_set(self, target, name, text):
        result = {'target': target, 'ok': False}
        try:
            address = self.target_address(target)
            ot_cli.cal_set(self.cli, name, text, address, timeout=self.config.coap_timeout_s)
            result.update(ok=True, message=f"calibration {name} {'stored' if text else 'deleted'}",
                          cal=ot_cli.cal_get(self.cli, address, timeout=self.config.coap_timeout_s))
        except (ot_cli.OtError, TimeoutError, ValueError) as exc:
            result['message'] = str(exc)
        self.to_gui('cal_result', result)

    # --- ADC measurement sequence (firmware >= 0.4.15) ---

    def adc_command(self, target, op, sensor, text='', channel=''):
        """
        op 'get': read the sequence and the calibrations of its channels, 'set': write the text,
        'read': measure once, 'cal_set': set (text) or delete (empty) the calibration of a channel.
        Answer 'adc_result' (with 'cals' {channel: {...}} for 'get' and 'cal_set').
        """
        result = {'target': target, 'sensor': sensor, 'op': op, 'ok': False}
        try:
            address = self.target_address(target)
            timeout = self.config.coap_timeout_s
            if op == 'set':
                ot_cli.adc_set(self.cli, sensor, text, address, timeout=timeout)
                st = ot_cli.adc_get(self.cli, sensor, address, timeout=timeout)
                result['message'] = f"{sensor}: configuration {st.get('cfg_id')} stored"
            elif op == 'read':
                st = ot_cli.adc_measure(self.cli, sensor, address, timeout=timeout)
                result['message'] = f"{sensor}: measured"
            elif op == 'cal_set':
                ot_cli.cal_set(self.cli, f"{sensor}.{channel}", text, address, timeout=timeout)
                st = ot_cli.adc_get(self.cli, sensor, address, timeout=timeout)
                result['message'] = f"{sensor}.{channel}: calibration {'stored' if text else 'deleted'}"
            else:
                st = ot_cli.adc_get(self.cli, sensor, address, timeout=timeout)
            if op in ('get', 'cal_set'):
                try:
                    result['cals'] = ot_cli.adc_calibrations(self.cli, sensor, address, timeout=timeout)
                except (ot_cli.OtError, TimeoutError, ValueError) as exc:
                    result['cal_message'] = f"calibrations not readable: {exc}"
            result.update(ok=True, adc=st)
        except (ot_cli.OtError, TimeoutError, ValueError) as exc:
            result['message'] = str(exc)
        self.to_gui('adc_result', result)

    # --- NMEA sensor at UART1 (status firmware >= 0.4.13, settings >= 0.4.21) ---

    def nmea_command(self, target, op, values):
        """op 'get': status, 'set': store values {'on', 'baud', 'raw'} and read back. Answer 'nmea_result'."""
        result = {'target': target, 'op': op, 'ok': False}
        try:
            address = self.target_address(target)
            timeout = self.config.coap_timeout_s
            if op == 'set':
                ot_cli.nmea_set(self.cli, values.get('on'), values.get('baud'), values.get('raw'), address,
                                timeout=timeout)
                result['message'] = 'NMEA settings stored'
            result.update(ok=True, nmea=ot_cli.nmea_get(self.cli, address, timeout=timeout))
        except (ot_cli.OtError, TimeoutError, ValueError) as exc:
            result['message'] = str(exc)
        self.to_gui('nmea_result', result)

    # --- live data over Thread: 'norlog pub' / 'norlog sink' (firmware >= 0.4.32) ---

    def _live_result(self, target, ok, message='', status=None, hwid=None):
        self.to_gui('live_result', {'target': target, 'ok': ok, 'message': message, 'status': status or {},
                                    'hwid': hwid or (self.infos.get(target) or {}).get('hwid', '')})

    def live_read(self, targets='all'):
        """Read what the devices send and whether they are sinks. Answer 'live_result' per device."""
        if not self.last_status:
            self.read_status()
        keys = ['gateway'] + [d['rloc16'] for d in self.build_devices()[1:] if d.get('rloc16')]
        if targets != 'all':
            keys = [k for k in keys if k in set(targets)]
        for key in keys:
            try:
                status = ot_cli.pub_status(self.cli, self.target_address(key), timeout=self.config.coap_timeout_s)
                self._live_result(key, True, status=status)
            except (ot_cli.OtError, TimeoutError, ValueError) as exc:
                self._live_result(key, False, str(exc))

    def live_pub_set(self, target, text, hwid=None):
        """Set 'norlog pub <text>' on a device (stored there)."""
        try:
            status = ot_cli.pub_set(self.cli, text, self.target_address(target), timeout=self.config.coap_timeout_s)
            hwid = hwid or (self.infos.get(target) or {}).get('hwid')
            if hwid:
                self.live_applied.add(hwid)
            self._live_result(target, True, f'pub {text}', status, hwid)
        except (ot_cli.OtError, TimeoutError, ValueError) as exc:
            self._live_result(target, False, f'pub {text}: {exc}', hwid=hwid)

    def live_sink_apply(self, report=False):
        """Make the gateway a sink for all packet types ('norlog sink on'), or not (live_sink)."""
        text = ot_cli.sink_text(self.config.live_sink)
        try:
            status = ot_cli.sink_set(self.cli, text)
            self._live_result('gateway', True, f'sink {text}', status)
        except (ot_cli.OtError, TimeoutError, ValueError) as exc:
            if report or self.config.live_sink:
                self._live_result('gateway', False, f'sink {text}: {exc}')

    def live_apply_seen(self, devices, read_ok):
        """
        live_pub of the configuration, once per start for each device whose info was just read.
        The gateway without an entry: all its own packets (LIVE_GATEWAY_DEFAULT).
        """
        if not self.config.live_apply:
            return
        for d in devices:
            is_gateway = d.get('role') == device_list.ROLE_GATEWAY
            key = 'gateway' if is_gateway else d.get('rloc16')
            hwid = d.get('hwid')
            if key not in read_ok or not hwid or hwid in self.live_applied:
                continue
            text = self.config.live_pub.get(hwid) or (LIVE_GATEWAY_DEFAULT if is_gateway else None)
            if text:
                self.live_applied.add(hwid)         # also on error: not on every poll
                self.live_pub_set(key, text, hwid)

    def set_radio(self, target, dbm):
        """Set the transmit power at the antenna of the gateway or a member (stored on the device)."""
        result = {'target': target, 'ok': False}
        try:
            address = self.target_address(target)
            st = ot_cli.radio_set(self.cli, int(dbm), address, timeout=self.config.coap_timeout_s)
            result.update(ok=True, radio=st,
                          message=f"{st.get('antenna_dbm')} dBm at the antenna (set {st.get('txpower_dbm')} dBm, "
                                  f"nRF {st.get('soc_dbm')} dBm + PA {st.get('pa_gain_db')} dB), stored")
            if int(dbm) > st.get('max_dbm', int(dbm)):
                result['message'] += f"; at most {st['max_dbm']} dBm possible"
        except (ot_cli.OtError, TimeoutError, ValueError, KeyError, TypeError) as exc:
            text = str(exc)
            if target != 'gateway' and ('4.04' in text or 'Not Found' in text or 'not found' in text):
                text += ' (firmware >= 0.4.5 required)'
            result['message'] = text
        self.to_gui('radio_result', result)
        if result['ok']:
            try:
                self.query_info([target], report=False)
            except (ot_cli.OtError, TimeoutError, ValueError):
                pass

    def set_time(self, targets, force=False):
        """
        Set the clock of the gateway and/or members ('gateway' or RLOC16) to the
        time of this PC: read (offset before), set, read again; set again while the
        offset is larger than TIME_MAX_OFFSET_S (e.g. a CoAP retransmission delivered
        the old time). Devices whose time came from GNSS within the last 2 minutes
        are skipped unless force.
        """
        done, failed, skipped = 0, 0, 0
        for target in targets:
            result = {'target': target, 'ok': False}
            try:
                address = self.target_address(target)
                st0, off0, err0 = self.measure_time(address)
                # uncertainty of the time sent: the delay of the request, at most its round trip
                # (2 x half round trip of the measurement); firmware >= 0.4.35 (offset_ms in the status)
                unc_ms = round(2000 * err0) if 'offset_ms' in st0 else None
                result['offset_before_s'] = off0 if st0.get('valid') else None
                result['src_before'] = st0.get('src')
                if st0.get('src') == 'gnss' and 0 <= st0.get('set_age_s', -1) < 120 and not force:
                    result.update(ok=True, skipped=True,
                                  message=f'skipped: clock from GNSS ({off0 * 1000:+.0f} ms)')
                    skipped += 1
                else:
                    for attempt in range(1, self.TIME_ATTEMPTS + 1):
                        ot_cli.time_set(self.cli, address, timeout=self.config.coap_timeout_s, unc_ms=unc_ms)
                        st, off, err = self.measure_time(address)
                        if abs(off) <= self.TIME_MAX_OFFSET_S:
                            break
                    result.update(ok=abs(off) <= self.TIME_MAX_OFFSET_S, attempts=attempt,
                                  offset_s=off, error_s=err, src=st.get('src'))
                    before = (f'{off0:+.3f} s' if result['offset_before_s'] is not None
                              else 'not set')
                    result['message'] = (f'before {before}, now {off * 1000:+.0f} ms '
                                         f'(± {err * 1000:.0f} ms)'
                                         + (f', {attempt} attempts' if attempt > 1 else ''))
                    if result['ok']:
                        done += 1
                    else:
                        failed += 1
            except (ot_cli.OtError, TimeoutError, ValueError, KeyError) as exc:
                result['message'] = str(exc)
                failed += 1
            self.to_gui('time_result', result)
        self.result('set_time', failed == 0,
                    f'Clock set: {done} ok, {skipped} skipped (GNSS), {failed} failed')
        if done:
            self.query_info(targets, report=False)      # RTC column of the device table

    def props_command(self, target, values):
        """Set (values: {name: text}, '' deletes) and/or read the user properties of a device."""
        try:
            address = self.target_address(target)
            for name, value in values.items():
                ot_cli.props_write(self.cli, name, value, address)
            props = ot_cli.props_read(self.cli, address)
            self.props_cache[self._props_key(target)] = props
            self.to_gui('props', {'target': target, 'ok': True, 'props': props,
                                   'message': f'{len(values)} propert(y/ies) saved' if values else 'read'})
            if values:
                self.query_info([target], report=False)     # serial number in the device list
            else:
                self.publish_devices()
        except (ot_cli.OtError, TimeoutError, ValueError) as exc:
            self.to_gui('props', {'target': target, 'ok': False, 'message': str(exc)})

    def fs_command(self, args):
        """File operations on the SD card of the gateway (target 'gateway') or of a member."""
        target, op, path = args.get('target', 'gateway'), args.get('op', ''), args.get('path', '/')
        try:
            address = self.target_address(target)
            if op == 'ls':
                self.fs_result(target, op, True, path=path, entries=ot_cli.fs_list(self.cli, address, path))
            elif op in ('stat', 'mkdir', 'rm'):
                res = (ot_cli.fs_local(self.cli, op, ot_cli._fs_quote(path)) if address is None
                       else ot_cli.fs_remote(self.cli, address, op, path))
                self.fs_result(target, op, True, f'{op} {path}', path=path, data=res)
            elif op == 'crc':
                crc, size = ot_cli.fs_crc(self.cli, address, path)
                self.fs_result(target, op, True, f'{path}: {size} bytes, CRC32 0x{crc:08x}', path=path,
                               crc=crc, size=size)
            elif op == 'upload':
                data = pathlib.Path(args['local']).read_bytes()
                progress = lambda d, t: self.fs_progress(target, op, d, t)
                if address is None:
                    skipped = ot_cli.fs_upload_local(self.cli, data, path, progress)
                elif self.gateway_has_sd():
                    tmp = '/fw/xfer.tmp'
                    ot_cli.fs_local(self.cli, 'mkdir', '/fw')
                    ot_cli.fs_upload_local(self.cli, data, tmp, lambda d, t: progress(d // 2, t))
                    res = ot_cli.fs_push(self.cli, address, tmp, path,
                                         lambda d, t: progress(len(data) // 2 + d // 2, len(data)), resume=True)
                    skipped = res.get('resumed', 0)
                    ot_cli.fs_local(self.cli, 'rm', tmp)
                else:
                    skipped = self.fs_write_direct(address, data, path, progress)
                note = f', resumed after {skipped} bytes' if skipped else ''
                self.fs_result(target, op, True, f'{len(data)} bytes written to {path} (CRC verified{note})',
                               path=path)
            elif op == 'download':
                data = ot_cli.fs_download(self.cli, address, path,
                                          lambda d, t: self.fs_progress(target, op, d, t))
                pathlib.Path(args['local']).write_bytes(data)
                self.fs_result(target, op, True, f'{len(data)} bytes saved to {args["local"]}', path=path)
            else:
                raise ValueError(f'unknown file operation {op!r}')
        except (ot_cli.OtError, TimeoutError, OSError, ValueError, KeyError) as exc:
            self.fs_result(target, op, False, str(exc), path=path)

    def fw_update_node(self, target, image_path, force):
        """
        Firmware update of a member over Thread: image -> /fw/update.bin on the member
        (through the gateway's SD card and 'norlog fs push', or chunk by chunk without
        gateway SD card), then POST fw?op=install; the member's loader installs it.
        """
        def status(state, message, progress=None):
            self.flash_status(state, message, progress, target=target)

        try:
            path = pathlib.Path(image_path)
            if not path.is_file():
                raise ValueError(f'Image not found: {image_path}')
            image = path.read_bytes()
            info = smp_serial.image_info(image)
            address = self.target_address(target)
            if address is None:
                raise ValueError('Use the serial flash for the gateway')
            status('start', f'{path.name}: version {info["version"]}, {len(image) // 1024} KB -> {target}')

            fw = ot_cli.fw_status_remote(self.cli, address)
            status('loader', f'Node runs {fw.get("running", "?")}, auto update {"on" if fw.get("auto") else "off"}')
            if fw.get('running') == info['version'] and not force:
                status('done', 'This version is already installed, nothing to do', 100)
                return

            self.image_to_node(address, image, '/fw/update.bin', status)
            ot_cli.fw_install_remote(self.cli, address)
            status('done', 'Installing: the node reboots into its loader and starts the new firmware '
                           '(about 1 min, check the version with "Read info")', 100)
        except (ot_cli.OtError, TimeoutError, OSError, ValueError, smp_serial.SmpError) as exc:
            status('error', str(exc))

    def image_to_node(self, address, image, remote, status, share_to=95):
        """
        Write an image to a file on a member: through the gateway's SD card and
        'norlog fs push', or chunk by chunk without gateway SD card.
        """
        last = [0.0]
        to_gw = share_to * 30 // 95

        def progress(share_from, share_to, label):
            meter = RateMeter()

            def cb(done, total):
                now = time.monotonic()
                rate = meter.update(done)
                if now - last[0] >= 1.0 or done >= total:
                    last[0] = now
                    pct = share_from + (share_to - share_from) * done // max(total, 1)
                    text = f'{label}: {done // 1024}/{total // 1024} KB, {rate:.1f} KB/s'
                    if done >= total:
                        text += f' (average {meter.average():.1f} KB/s)'
                    status('upload', text, pct)
            return cb

        if self.gateway_has_sd():
            ot_cli.fs_local(self.cli, 'mkdir', '/fw')
            try:
                crc, size = ot_cli.fs_crc(self.cli, None, self.GATEWAY_XFER_FILE)
            except ot_cli.OtError:
                crc, size = None, None
            if size == len(image) and crc == zlib.crc32(image):
                status('upload', 'Image already on the gateway SD card', to_gw)
            else:
                ot_cli.fs_upload_local(self.cli, image, self.GATEWAY_XFER_FILE,
                                       progress(0, to_gw, 'PC -> gateway SD'))
            res = ot_cli.fs_push(self.cli, address, self.GATEWAY_XFER_FILE, remote,
                                 progress(to_gw, share_to, 'Gateway -> node over Thread'), resume=True)
            resumed = f', resumed after {res["resumed"] // 1024} KB' if res.get('resumed') else ''
            status('upload', f'Node has the image ({res.get("seconds", "?")} s, CRC {res.get("crc")}'
                             f'{resumed})', share_to)
        else:
            status('upload', 'Gateway without SD card: sending directly (slower)', 0)
            self.fs_write_direct(address, image, remote, progress(0, share_to, 'PC -> node over Thread'))

    LOADER_SLOT_SIZE = 144 * 1024     # slot1 (norlog_flash_layout.dtsi)

    def loader_update(self, target, image_path):
        """
        Install a new norlog_loader without SWD (firmware >= 0.4.42): signed loader image
        -> /fw/loader.bin on the SD card of the gateway or a member, then the app writes it
        to slot1 ('norlog fw loader' / POST fw?op=loader). No reboot; if it fails, only
        the loader is invalid and the app keeps running: try again.
        """
        def status(state, message, progress=None):
            self.flash_status(state, message, progress, target=target)

        try:
            path = pathlib.Path(image_path)
            if not path.is_file():
                raise ValueError(f'Loader image not found: {image_path}')
            image = path.read_bytes()
            info = smp_serial.image_info(image)
            if len(image) > self.LOADER_SLOT_SIZE:
                raise ValueError(f'{path.name} has {len(image) // 1024} KB, slot1 holds '
                                 f'{self.LOADER_SLOT_SIZE // 1024} KB: an app image instead of '
                                 f'build/norlog_loader/zephyr/zephyr.signed.bin?')
            status('start', f'Loader {path.name}: version {info["version"]}, {len(image) // 1024} KB -> {target}')

            address = self.target_address(target)
            if address is None:
                fw = ot_cli.fw_status_local(self.cli)
                status('loader', f'Gateway loader {fw.get("loader") or "?"}')
                if not self.gateway_has_sd():
                    raise ValueError('The gateway has no SD card mounted')
                ot_cli.fs_local(self.cli, 'mkdir', '/fw')
                ot_cli.fs_upload_local(self.cli, image, ot_cli.LOADER_FILE,
                                       lambda d, t: status('upload', f'PC -> gateway SD: {d // 1024}/'
                                                                     f'{t // 1024} KB', 80 * d // max(t, 1)))
                status('upload', 'Writing the loader to slot1 ...', 85)
                fw = ot_cli.fw_loader_local(self.cli)
            else:
                fw = ot_cli.fw_status_remote(self.cli, address)
                if 'loader' not in fw:
                    raise ValueError(f'{target} runs {fw.get("running", "?")}: firmware >= 0.4.42 '
                                     f'required to install the loader')
                status('loader', f'Node loader {fw.get("loader") or "?"}')
                self.image_to_node(address, image, ot_cli.LOADER_FILE, status, share_to=85)
                status('upload', 'Writing the loader to slot1 ...', 90)
                fw = ot_cli.fw_loader_remote(self.cli, address)
            same = fw.get('loader_state') == 'same'
            status('done', f'Loader {fw.get("loader") or info["version"]} '
                           f'{"was already installed" if same else "installed and verified"}', 100)
        except (ot_cli.OtError, TimeoutError, OSError, ValueError, smp_serial.SmpError) as exc:
            status('error', str(exc))

    def flash_status(self, state, message='', progress=None, **extra):
        payload = {'state': state, 'message': message}
        if progress is not None:
            payload['progress'] = progress
        payload.update(extra)
        self.to_gui('flash_status', payload)

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

            last = [0.0]
            meter = RateMeter()

            def progress(off, size):
                now = time.monotonic()
                rate = meter.update(off)    # first call: after erasing slot 0
                if now - last[0] >= 0.5 or off >= size:
                    last[0] = now
                    self.flash_status('upload', f'{off // 1024}/{size // 1024} KB, {rate:.1f} KB/s',
                                      progress=off * 100 // size)

            self.flash_status('upload', 'Erasing slot 0 (about 20 s) ...', progress=0)
            smp.upload(image, progress=progress, cancel=cancel)
            images = smp.image_state()
            slot0 = next((i for i in images if i.get('image', 0) == 0 and i.get('slot', 0) == 0), {})
            smp.reset()
            self.flash_status('done', f'Installed version {slot0.get("version", "?")}, rebooting '
                                      f'(upload average {meter.average():.1f} KB/s)', progress=100)
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
    gw = _Gateway(device_info, pdconfig, dataqueue, datainqueue, statusqueue)

    if not pdconfig.comport:
        gw.result('start', False, 'No serial port configured')
        return
    try:
        gw.open()
    except serial.SerialException as exc:
        gw.result('start', False, f'Could not open {pdconfig.comport}: {exc}')
        return

    logger.info(funcname + f'Opened {pdconfig.comport} with {pdconfig.baud} baud')
    # Info of the gateway first: its hwid and serial number go into the header of all packets
    try:
        gw.query_info(['gateway'], report=False)
    except (ot_cli.OtError, TimeoutError, ValueError) as exc:
        logger.debug(funcname + f'Gateway info not read: {exc}')
    if pdconfig.live_apply:
        gw.live_sink_apply()
    gw.result('start', True, f'Connected to {pdconfig.comport}')
    t_status = time.monotonic()
    t_info = None                   # first info read right after the first status

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

            interval = gw.config.info_interval_s
            if interval > 0 and (t_info is None or time.monotonic() - t_info >= interval):
                t_info = time.monotonic()
                try:
                    gw.query_info('all', report=False)
                except (ot_cli.OtError, TimeoutError, ValueError) as exc:
                    logger.debug(funcname + f'Info poll failed: {exc}')
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
        self.settings_dialogs = {}  # device key -> open DeviceSettingsDialog

        self.tabs = QtWidgets.QTabWidget()
        # Scroll areas: otherwise the highest tab sets the minimum height of the redvypr main window,
        # which then reaches under the taskbar on small or scaled screens
        scroll = DeviceSettingsDialog._scrollable
        self.live_dialog = None
        self.device_live_dialogs = {}   # hwid -> LiveSubscriptionsDialog of one device
        self.tabs.addTab(scroll(self._build_devices_tab()), 'Devices')
        # Live data over Thread ('#NLD')
        self.live_tab = LiveDataTab(self)
        self.tabs.addTab(self.live_tab, 'Live data')
        self.tabs.addTab(self._build_console_tab(), 'Console')
        self.tabs.addTab(scroll(self._build_thread_tab()), 'Thread network')
        self.live_status = {}       # hwid -> last 'norlog pub json' status of the device
        self.save_dialog = None
        self.save_was_running = False   # gateway thread: start the save channels when it starts
        self.layout.addWidget(self._build_port_row())
        self.layout.addWidget(self.tabs)

        self.device.new_data.connect(self.on_new_data)       # published data ('#NLD')
        self.status_timer = QtCore.QTimer()                  # messages of the device thread
        self.status_timer.timeout.connect(self.read_statusqueue)
        self.status_timer.start(100)
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
        # Can be changed while running (sent to the device thread)
        self.publish_raw = QtWidgets.QCheckBox('Publish raw data')
        self.publish_raw.setToolTip('Publish also the console lines, command results, Thread status with '
                                    'device list and transfer status of the gateway as redvypr data '
                                    '(otherwise only for this window)')
        self.publish_raw.setChecked(self.cfg.publish_raw_data)
        self.publish_raw.toggled.connect(self.publish_raw_changed)
        lay.addWidget(self.publish_raw)
        self.save_data = QtWidgets.QCheckBox('Save data')
        self.save_data.setToolTip('Save the live data packets of the Thread network (#NLD) into the channels '
                                  'of the options (gear button), e.g. an SQLite file')
        self.save_data.setChecked(self.cfg.save_data)
        self.save_data.toggled.connect(self.save_data_changed)
        lay.addWidget(self.save_data)
        self.save_options = QtWidgets.QToolButton()
        self.save_options.setIcon(qtawesome.icon(iconnames['settings']))
        self.save_options.setToolTip('Options of "Save data": channels (SQLite, ...), files, packet types')
        self.save_options.clicked.connect(self.open_save_options)
        lay.addWidget(self.save_options)
        self.refresh_ports()
        self.port_combo.currentTextChanged.connect(self.port_changed)
        # Disabled while the thread is running (handled by the base class)
        self.config_widgets.extend([self.port_combo, self.port_refresh, self.baud_edit])
        return w

    @staticmethod
    def _port_key(device):
        """COM3 before COM16 (numeric order), /dev/ttyACM0 ..."""
        digits = ''.join(c for c in device if c.isdigit())
        return device.rstrip('0123456789'), int(digits) if digits else -1

    def ports_in_use(self):
        """Serial ports configured in the other devices of this redvypr (not opened to test them)."""
        used = set()
        rv = getattr(self.device, 'redvypr', None)
        for d in getattr(rv, 'devices', None) or []:
            dev = d.get('device')
            cfg = getattr(dev, 'custom_config', None)
            if dev is None or dev is self.device or cfg is None:
                continue
            for name in ('comport', 'node_comport', 'port', 'serial_port'):
                value = getattr(cfg, name, None)
                if isinstance(value, str) and value:
                    used.add(value)
        return used

    def refresh_ports(self):
        ports = sorted(serial.tools.list_ports.comports(), key=lambda p: self._port_key(p.device))
        current = self.cfg.comport
        if not current:
            # Default: the first port no other device of this redvypr uses (the configured port stays)
            used = self.ports_in_use()
            free = [p.device for p in ports if p.device not in used]
            if free:
                current = self.cfg.comport = free[0]
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for p in ports:
            self.port_combo.addItem(f'{p.device}  ({p.description})', p.device)
        idx = self.port_combo.findData(current)
        if idx >= 0:
            self.port_combo.setCurrentIndex(idx)
        else:
            self.port_combo.setEditText(current)
        self.port_combo.blockSignals(False)

    def publish_raw_changed(self, checked):
        self.cfg.publish_raw_data = bool(checked)
        if self.device.get_thread_status()['thread_running']:
            self.device.thread_command('config', {'config': self.cfg.model_dump()})

    def port_changed(self, text):
        data = self.port_combo.currentData()
        self.cfg.comport = data if data else text.split()[0] if text.strip() else ''

    # --- devices ---

    DEVICE_COLUMNS = ['', 'HW ID', 'Device', 'SN', 'Description', 'Location', 'RLOC16', 'Connection', 'Role', 'Thread role', 'Link', 'Quality',
                      'RSSI avg/last [dBm]', 'LQ in/out', 'Path cost', 'Seen [s]', 'Packets',
                      'Firmware', 'Battery', 'Board temp [C]', 'nRF temp [C]', 'GNSS', 'Clock', 'Info age [s]']

    QUALITY_COLORS = {
        device_list.QUALITY_GOOD: '#7bc96f',
        device_list.QUALITY_FAIR: '#f2c14e',
        device_list.QUALITY_POOR: '#e8743b',
        device_list.QUALITY_NONE: '#d64545',
    }

    @staticmethod
    def board_temp_warning(info):
        """Text if the board temperature (ADC) is implausible compared with the nRF chip, else ''."""
        info = info or {}
        adc, nrf = info.get('board_temp_c'), info.get('nrf_temp_c')
        text = ''
        if adc is not None and nrf is not None and abs(adc - nrf) > 15:
            text = (f"Board temperature {adc:.1f} C differs from the nRF chip ({nrf:.1f} C): the ADC is "
                    f"probably misconfigured (firmware >= 0.4.7 resets it).")
        if info.get('adc_resets'):
            text += (' ' if text else '') + (f"ADC reset {info['adc_resets']} time(s) since the start because of "
                                             f"an implausible board temperature.")
        return text

    @staticmethod
    def gnss_position(info, altitude=True):
        """'lat, lon[, alt m]' of the last fix (firmware >= 0.4.11), '' without position."""
        st = (info or {}).get('gnss')
        if not isinstance(st, dict) or st.get('lat') is None or st.get('lon') is None:
            return ''
        text = f"{st['lat']:.6f}, {st['lon']:.6f}"
        if altitude and st.get('alt') is not None:
            text += f", {st['alt']:.1f} m"
        return text

    @staticmethod
    def fmt_gnss(info):
        """(text, quality color key, tooltip) of the GNSS reception (firmware >= 0.4.10)."""
        info = info or {}
        receiver = (info.get('hw') or {}).get('gnss') or ''
        st = info.get('gnss')
        if not isinstance(st, dict):
            if not receiver:
                return '', None, ''
            return 'no status', None, f'{receiver}: no reception status (firmware >= 0.4.10, "norlog gnss")'
        used, view, trk = st.get('used', 0), st.get('view', 0), st.get('trk', 0)
        tip = (f"{receiver}: {'fix' if st.get('fix') else 'no fix'}, satellites used {used}, in view {view}, "
               f"received {trk}, best signal {st.get('cno', 0)} dB-Hz (good > 35, weak < 25), "
               f"last message {st.get('age', '?')} s ago")
        pos = RedvyprDeviceWidget.gnss_position(info)
        if pos:
            tip += f"\nPosition: {pos} (right click: copy)"
        if st.get('age') is not None and st['age'] > 10:
            return 'no data', device_list.QUALITY_NONE, tip + '\nNo NMEA data from the receiver for > 10 s'
        if st.get('fix'):
            return f'fix, {used} sat.', device_list.QUALITY_GOOD, tip
        if trk > 0:
            return f'no fix, {trk}/{view} sat.', device_list.QUALITY_FAIR, tip
        return 'no satellites', device_list.QUALITY_NONE, tip + '\nAntenna connected? Free view of the sky?'

    @staticmethod
    def fem_stuck(radio):
        """TX_EN (almost) always HIGH: the PA of the front end hangs in transmit mode."""
        fem = (radio or {}).get('fem') or {}
        return fem.get('tx') is not None and fem['tx'] >= 90

    def _build_devices_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        refresh = QtWidgets.QPushButton('Refresh')
        refresh.setToolTip('Read the Thread status and the info (battery, temperature, firmware) of all devices')
        refresh.clicked.connect(lambda: self.device.thread_command('refresh', {}))
        info_sel = QtWidgets.QPushButton('Read info (selected)')
        info_sel.clicked.connect(self.read_info_selected)
        self.info_interval = QtWidgets.QSpinBox()
        self.info_interval.setRange(0, 3600)
        self.info_interval.setSuffix(' s')
        self.info_interval.setSpecialValueText('off')
        self.info_interval.setToolTip('Interval for reading the info of all devices (CoAP /info), 0 = off')
        self.info_interval.setValue(int(self.cfg.info_interval_s))
        self.info_interval.valueChanged.connect(self.info_interval_changed)
        self.devices_info = QtWidgets.QLabel('No data yet (refreshed with the Thread status)')
        row.addWidget(refresh)
        row.addWidget(info_sel)
        row.addWidget(QtWidgets.QLabel('Auto info'))
        row.addWidget(self.info_interval)
        row.addWidget(self.devices_info, 1)
        self.current_devices = []
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
        self.devices_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.devices_table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.devices_table.customContextMenuRequested.connect(self.devices_context_menu)
        lay.addLayout(row)
        lay.addWidget(self.devices_table, 1)
        lay.addWidget(legend)
        self.run_widgets.extend([refresh, info_sel])
        return w

    def info_interval_changed(self, value):
        self.cfg.info_interval_s = float(value)
        if self.device.get_thread_status()['thread_running']:
            self.device.thread_command('config', {'config': self.cfg.model_dump()})

    @staticmethod
    def _device_key(d):
        return 'gateway' if d.get('role') == device_list.ROLE_GATEWAY else d.get('rloc16', '')

    @classmethod
    def device_key(cls, d):
        """Key of a device in the info/settings bookkeeping ('gateway', RLOC16 or id)."""
        return cls._device_key(d) or d.get('id', '')

    def _settings_button(self, d):
        btn = QtWidgets.QPushButton()
        btn.setIcon(qtawesome.icon(iconnames['settings']))
        btn.setToolTip('Settings and firmware update of this device')
        btn.setFlat(True)
        key = self.device_key(d)
        btn.clicked.connect(lambda checked=False, k=key: self.open_settings(k))
        return btn

    def _row_buttons(self, d):
        """First column: settings and live data subscriptions of the device."""
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self._settings_button(d))
        sub = QtWidgets.QPushButton('Subscribe')
        hwid = d.get('hwid')
        sub.setEnabled(bool(hwid))
        sub.setToolTip('Packet types this device sends live (norlog pub, firmware >= 0.4.32)' if hwid
                       else 'Hardware ID not known yet (Refresh)')
        sub.clicked.connect(lambda checked=False, h=hwid: self.open_device_subscriptions(h))
        lay.addWidget(sub)
        return w

    def open_settings(self, key):
        dlg = self.settings_dialogs.get(key)
        if dlg is None:
            dlg = DeviceSettingsDialog(self, key)
            dlg.finished.connect(lambda _r, k=key: self.settings_dialogs.pop(k, None))
            self.settings_dialogs[key] = dlg
        entry = next((d for d in self.current_devices if self.device_key(d) == key), None)
        if entry is not None:
            dlg.update_entry(entry)
        dlg.update_run_state(self.device.get_thread_status()['thread_running'])
        if dlg.running and not dlg.props_loaded:
            dlg.read_props()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def serial_dialogs(self):
        """Open settings dialogs of devices connected via serial (the flash target)."""
        return [dlg for dlg in self.settings_dialogs.values() if dlg.is_serial()]

    def devices_context_menu(self, point):
        """Right click in the device table: copy the GNSS position or the cell."""
        item = self.devices_table.itemAt(point)
        if item is None:
            return
        row = item.row()
        device = self.current_devices[row] if row < len(self.current_devices) else {}
        info = device.get('info') or {}
        menu = QtWidgets.QMenu(self)
        clipboard = QtWidgets.QApplication.clipboard()
        pos = self.gnss_position(info, altitude=False)
        pos_alt = self.gnss_position(info)
        act = menu.addAction(f'Copy GNSS position ({pos})' if pos else 'Copy GNSS position (no fix)')
        act.setEnabled(bool(pos))
        act.triggered.connect(lambda: clipboard.setText(pos))
        act = menu.addAction('Copy GNSS position with altitude')
        act.setEnabled(bool(pos_alt))
        act.triggered.connect(lambda: clipboard.setText(pos_alt))
        menu.addSeparator()
        text = item.text()
        act = menu.addAction('Copy cell')
        act.triggered.connect(lambda: clipboard.setText(text))
        tip = item.toolTip()
        act = menu.addAction('Copy tooltip')
        act.setEnabled(bool(tip))
        act.triggered.connect(lambda: clipboard.setText(tip))
        menu.exec(self.devices_table.viewport().mapToGlobal(point))

    def selected_devices(self):
        rows = sorted({i.row() for i in self.devices_table.selectedIndexes()})
        return [self.current_devices[r] for r in rows if r < len(self.current_devices)]

    def read_info_selected(self):
        keys = [self._device_key(d) for d in self.selected_devices()]
        keys = [k for k in keys if k]
        if keys:
            self.device.thread_command('read_device_info', {'targets': keys})

    @staticmethod
    def _fmt_battery(d):
        if d.get('battery_mv') is None:
            return ''
        text = f"{d['battery_mv'] / 1000:.2f} V"
        if d.get('battery_soc') is not None:
            text += f" {d['battery_soc']} %"
        ma = d.get('battery_current_ma')
        if ma is not None:
            # firmware: positive current = charging, "charging" from the current direction
            text += f", {'chg' if d.get('battery_charging') else 'dischg'} {abs(ma)} mA"
        elif d.get('battery_charging'):
            text += ', chg'
        return text

    @staticmethod
    def _short(text, n=32):
        """Long property texts shortened for the table (full text as tooltip)."""
        return text if len(text) <= n else text[:n - 1] + '\u2026'

    @staticmethod
    def _fmt_pair(a, b):
        if a is None and b is None:
            return ''
        return f"{'' if a is None else a} / {'' if b is None else b}"

    @staticmethod
    def _fmt_rtc(info):
        """RTC compared with the system clock (firmware >= 0.4.8), text or ''."""
        rtc = (info or {}).get('rtc') or {}
        if rtc.get('off_ms') is None:
            return ''
        return (f"System clock - RTC: {rtc['off_ms']:+d} ms (measured {rtc.get('chk_s', '?')} s ago at the second "
                f"change of the RTC; the system clock is set to the RTC every minute from 5 ms)")

    def _fmt_clock(self, d):
        """(text, quality color key, tooltip) of the Clock column: system clock of the device vs. this PC."""
        info = d.get('info') or {}
        if 'time' not in info:
            return '', None, ''
        rtc = info.get('rtc') or {}
        off = d.get('clock_offset_s')
        tol = d.get('clock_tolerance_s') or 2.0
        tip = (f"System clock of the device {info.get('time')} at the last info read "
               f"(RTC {'valid' if rtc.get('valid') else 'not valid'})")
        no_rtc = '' if rtc.get('present', True) else ', no RTC'
        if no_rtc:
            tip += '\nNo RTC chip: the time is lost at a restart'
        rtc_text = self._fmt_rtc(info)
        if rtc_text:
            tip += '\n' + rtc_text
        try:
            year_ok = info['time'][:4].isdigit() and int(info['time'][:4]) >= 2025
        except (TypeError, ValueError):
            year_ok = False
        if off is None or not year_ok:
            return 'not set' + no_rtc, device_list.QUALITY_NONE, tip + '\nSet it with "Set clock" in the settings'
        tip += f'\nOffset to this PC: {off:+.2f} s (uncertainty about ±{tol:.2f} s'
        tip += ')' if self._clock_has_ms_info(info) else ', firmware < 0.4.8 sends whole seconds)'
        if abs(off) <= tol:
            return 'ok' + no_rtc, device_list.QUALITY_GOOD, tip
        return (f'{off:+.1f} s' if abs(off) < 10 else f'{off:+.0f} s') + no_rtc, device_list.QUALITY_FAIR, tip

    @staticmethod
    def _clock_has_ms_info(info):
        return '.' in ((info or {}).get('time') or '')

    def show_devices(self, devices):
        selected_ids = {d.get('id') for d in self.selected_devices()}
        self.current_devices = devices
        self.devices_table.blockSignals(True)
        self.devices_table.clearSelection()
        self.devices_table.setRowCount(len(devices))
        for row, d in enumerate(devices):
            name = d.get('extaddr') or d.get('mac') or d.get('id', '')
            if d.get('connection') == device_list.CONNECTION_SERIAL and d.get('port'):
                name = f"{name} ({d['port']})" if d.get('extaddr') else d['port']
            seen = d.get('age_s')
            if seen is None:
                seen = d.get('last_data_s')
            cells = [
                d.get('hwid', ''),
                name,
                d.get('sn', ''),
                self._short(d.get('desc', '')),
                self._short(d.get('loc', '')),
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
                d.get('firmware') or ('error' if d.get('info_error') else ''),
                self._fmt_battery(d),
                '' if d.get('board_temp_c') is None else f"{d['board_temp_c']:.1f}",
                '' if (d.get('info') or {}).get('nrf_temp_c') is None else f"{d['info']['nrf_temp_c']:.1f}",
                self.fmt_gnss(d.get('info'))[0],
                self._fmt_clock(d)[0],
                '' if d.get('info_age_s') is None else f"{d['info_age_s']:.0f}",
            ]
            cols = self.DEVICE_COLUMNS
            stale_cols = [cols.index(c) for c in ('Firmware', 'Battery', 'Board temp [C]', 'nRF temp [C]', 'GNSS', 'Clock',
                                                  'Info age [s]')]
            self.devices_table.setCellWidget(row, 0, self._row_buttons(d))
            full_text = {cols.index('Description'): d.get('desc', ''), cols.index('Location'): d.get('loc', '')}
            for col, text in enumerate([''] + cells):
                item = QtWidgets.QTableWidgetItem(str(text))
                if full_text.get(col) and full_text[col] != text:
                    item.setToolTip(full_text[col])
                if cols[col] == 'Quality' and d.get('quality') in self.QUALITY_COLORS:
                    item.setBackground(QtGui.QColor(self.QUALITY_COLORS[d['quality']]))
                if cols[col] == 'GNSS':
                    _text, quality, tip = self.fmt_gnss(d.get('info'))
                    if quality in self.QUALITY_COLORS:
                        item.setBackground(QtGui.QColor(self.QUALITY_COLORS[quality]))
                    item.setToolTip(tip)
                if cols[col] == 'Clock':
                    _text, quality, tip = self._fmt_clock(d)
                    if quality in self.QUALITY_COLORS:
                        item.setBackground(QtGui.QColor(self.QUALITY_COLORS[quality]))
                    item.setToolTip(tip)
                radio = (d.get('info') or {}).get('radio')
                if cols[col] == 'Quality' and self.fem_stuck(radio):
                    item.setText(f"{text} / PA stuck?")
                    item.setBackground(QtGui.QColor(self.QUALITY_COLORS[device_list.QUALITY_NONE]))
                    item.setToolTip(f"Front end: TX_EN {radio['fem']['tx']} % HIGH - the PA seems to hang in "
                                    f"transmit mode (reception only by leakage). Restart the device; "
                                    f"details in its settings (TX power).")
                if cols[col] == 'Board temp [C]':
                    warn = self.board_temp_warning(d.get('info'))
                    if warn:
                        item.setBackground(QtGui.QColor(self.QUALITY_COLORS[device_list.QUALITY_FAIR]))
                        item.setToolTip(warn)
                if col in stale_cols and d.get('info_error'):
                    # Last read failed: older values in gray, error as tooltip
                    item.setForeground(QtGui.QColor('gray'))
                    item.setToolTip(f"Last read failed: {d['info_error']}")
                self.devices_table.setItem(row, col, item)
        for row, d in enumerate(devices):
            if d.get('id') in selected_ids:
                self.devices_table.selectRow(row)
        self.devices_table.blockSignals(False)
        self.devices_table.resizeColumnsToContents()
        for key, dlg in self.settings_dialogs.items():
            entry = next((d for d in devices if self.device_key(d) == key), None)
            if entry is not None:
                dlg.update_entry(entry)
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
        import_btn = QtWidgets.QPushButton('Import autoexec.txt ...')
        import_btn.setToolTip('Take the network parameters (and the dataset for provisioning) from an '
                              'autoexec.txt, e.g. one exported here or from the SD card of a node')
        import_btn.clicked.connect(self.import_autoexec)
        import_row = QtWidgets.QHBoxLayout()
        import_row.addWidget(import_btn)
        import_row.addStretch(1)
        form.addRow('', import_row)

        btn_row = QtWidgets.QHBoxLayout()
        form_btn = QtWidgets.QPushButton('Form network')
        form_btn.clicked.connect(self.form_network)
        status_btn = QtWidgets.QPushButton('Read status')
        status_btn.clicked.connect(lambda: self.device.thread_command('ot_status', {}))
        leader_btn = QtWidgets.QPushButton('Make gateway leader')
        leader_btn.setToolTip('The gateway becomes the leader of the Thread network (leader weight '
                              f'{ot_cli.LEADER_WEIGHT_PREFERRED}, the nodes have 64). The network is '
                              'interrupted shortly, RLOC16 addresses may change.')
        leader_btn.clicked.connect(self.make_leader)
        self.prefer_leader = QtWidgets.QCheckBox('Gateway prefers leader role')
        self.prefer_leader.setToolTip('While redvypr is connected: leader weight '
                                      f'{ot_cli.LEADER_WEIGHT_PREFERRED} also after a restart of the '
                                      'gateway, and the gateway becomes leader again if it is not '
                                      '(checked with the status, at most every 10 minutes)')
        self.prefer_leader.setChecked(self.cfg.prefer_leader)
        self.prefer_leader.toggled.connect(self.prefer_leader_changed)
        for b in (form_btn, status_btn, leader_btn):
            btn_row.addWidget(b)
        btn_row.addWidget(self.prefer_leader)
        btn_row.addStretch(1)
        self.run_widgets.extend([form_btn, status_btn, leader_btn])

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
        self.prov_btn = prov_btn
        self.provision_worker = None
        # Provisioning works also without a running gateway (directly on the node port)
        self.run_widgets.append(read_ds)
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
        if not self.cfg.dataset_tlvs:
            QtWidgets.QMessageBox.warning(self, 'Provision node', 'No dataset: read it from the gateway or '
                                                                  'import an autoexec.txt first.')
            return
        port = self.cfg.node_comport or self.cfg.comport
        running = self.device.get_thread_status()['thread_running']
        target = 'the device on the gateway port' if running and port == self.cfg.comport else port
        if not port:
            QtWidgets.QMessageBox.warning(self, 'Provision node', 'Choose the node port first.')
            return
        answer = QtWidgets.QMessageBox.question(
            self, 'Provision node',
            f'Store the Thread dataset on {target}? The node leaves its current network.')
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if running:
            # The gateway thread has the gateway port (and opens a second port itself)
            self.device.thread_command('provision', {'port': self.cfg.node_comport, 'dataset': self.cfg.dataset_tlvs})
            return
        # Gateway not running: directly on the node port
        self.provision_worker = ProvisionWorker(port, self.cfg.baud, self.cfg.dataset_tlvs, parent=self)
        self.provision_worker.message.connect(
            lambda ok, text: self.console_text.appendPlainText(f"[provision] {'OK' if ok else 'ERROR'}: {text}"))
        self.provision_worker.finished_result.connect(self.on_provision_done)
        self.prov_btn.setEnabled(False)
        self.provision_worker.start()

    def on_provision_done(self, ok, text):
        self.provision_worker = None
        self.prov_btn.setEnabled(True)
        if ok:
            QtWidgets.QMessageBox.information(self, 'Provision node', text)
        else:
            QtWidgets.QMessageBox.warning(self, 'Provision node', text)

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

    def import_autoexec(self):
        """Network parameters (and dataset) from an autoexec.txt, counterpart of export_autoexec()."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Import autoexec.txt', 'autoexec.txt',
                                                        'Text files (*.txt);;All files (*)')
        if not path:
            return
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                net = ot_cli.parse_autoexec(f.read())
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(self, 'Import autoexec.txt', str(exc))
            return
        if net['network_name'] is not None:
            self.net_name.setText(net['network_name'])
        if net['channel'] is not None:
            self.net_channel.setValue(int(net['channel']))
        if net['panid'] is not None:
            self.net_panid.setText(net['panid'])
        if net['extpanid'] is not None:
            self.net_extpanid.setText(net['extpanid'])
        if net['networkkey'] is not None:
            self.net_key.setText(net['networkkey'])
        found = [name for name, key in (('network name', 'network_name'), ('channel', 'channel'),
                                         ('PAN ID', 'panid'), ('ext. PAN ID', 'extpanid'),
                                         ('network key', 'networkkey')) if net[key] is not None]
        text = f'Taken from {pathlib.Path(path).name}: {", ".join(found)}.'
        if net['dataset_tlvs']:
            # The complete dataset (also mesh-local prefix, PSKc, ...): for provisioning nodes
            self.cfg.dataset_tlvs = net['dataset_tlvs']
            self.update_dataset_label()
            text += ('\n\nThe complete dataset is now used for provisioning nodes. To start the gateway '
                     'itself in exactly this network (instead of "Form network", which creates new values '
                     'for the other parameters), use "Provision node via UART" with the gateway port as '
                     'node port.')
        else:
            text += '\n\nThe file has no complete dataset; "Form network" creates a network with these parameters.'
        QtWidgets.QMessageBox.information(self, 'Import autoexec.txt', text)

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

    def make_leader(self):
        answer = QtWidgets.QMessageBox.question(
            self, 'Make gateway leader',
            'The gateway becomes the leader of the Thread network. It starts a new partition that the '
            'other devices join; the network is interrupted shortly (seconds up to about a minute), '
            'RLOC16 addresses may change and running transfers can fail. Continue?')
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self.device.thread_command('make_leader', {})

    def prefer_leader_changed(self, checked):
        self.cfg.prefer_leader = bool(checked)
        if self.device.get_thread_status()['thread_running']:
            self.device.thread_command('config', {'config': self.cfg.model_dump()})

    def show_status(self, status):
        self.status_tree.clear()
        for key in ('state', 'network_name', 'channel', 'panid', 'extpanid', 'rloc16', 'extaddr',
                    'leader_weight', 'partition_id', 'packets_received'):
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

    # --- live data over Thread ---

    def open_device_subscriptions(self, hwid):
        """Live data subscriptions of one device (same dialog as Subscriptions, one row)."""
        if not hwid:
            return
        dlg = self.device_live_dialogs.get(hwid)
        if dlg is None:
            dlg = LiveSubscriptionsDialog(self, hwid=hwid)
            dlg.finished.connect(lambda _r, h=hwid: self.device_live_dialogs.pop(h, None))
            self.device_live_dialogs[hwid] = dlg
        dlg.populate()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        if self.device.get_thread_status()['thread_running'] and dlg.read_targets():
            self.device.thread_command('live_read', {'targets': dlg.read_targets()})

    def open_live_subscriptions(self):
        if self.live_dialog is None:
            self.live_dialog = LiveSubscriptionsDialog(self)
            self.live_dialog.finished.connect(lambda _r: setattr(self, 'live_dialog', None))
        self.live_dialog.populate()
        self.live_dialog.show()
        self.live_dialog.raise_()
        self.live_dialog.activateWindow()
        if self.device.get_thread_status()['thread_running']:
            self.device.thread_command('live_read', {'targets': 'all'})

    # --- save data: writer devices of redvypr (save_channels) ---

    def save_channel_devices(self):
        """[(name, device or None)] of save_channels; None: not (any more) in redvypr."""
        rv = getattr(self.device, 'redvypr', None)
        devices = {d['device'].name: d['device'] for d in (getattr(rv, 'devices', None) or [])}
        return [(name, devices.get(name)) for name in self.cfg.save_channels]

    def create_save_channel(self, kind='SQLite'):
        """New writer device for the data of this gateway, added to save_channels; returns it or None."""
        rv = getattr(self.device, 'redvypr', None)
        if rv is None or kind not in SAVE_CHANNEL_TYPES:
            return None
        module, make_config = SAVE_CHANNEL_TYPES[kind]
        devicemodulename = rv.get_devicemodulename_from_str(module)
        dev = rv.add_device(devicemodulename=devicemodulename, custom_config=make_config(self.device.name),
                            base_config={'name': f'{self.device.name}_{module}'})
        if dev is None:
            self.console_text.appendPlainText(f'[save data] ERROR: could not add a {module} device')
            return None
        self.cfg.save_channels.append(dev.name)
        self.console_text.appendPlainText(f'[save data] added the device {dev.name} ({module})')
        return dev

    def remove_save_channel(self, name, remove_device=True):
        dev = dict(self.save_channel_devices()).get(name)
        if name in self.cfg.save_channels:
            self.cfg.save_channels.remove(name)
        if dev is not None and remove_device:
            self.device.redvypr.rem_device(dev)

    def start_save_channels(self):
        if not any(dev for _name, dev in self.save_channel_devices()):
            self.create_save_channel()
        for _name, dev in self.save_channel_devices():
            if dev is not None and not dev.thread_running():
                dev.thread_start()

    def stop_save_channels(self):
        for _name, dev in self.save_channel_devices():
            if dev is not None and dev.thread_running():
                dev.thread_stop()

    def save_data_changed(self, checked):
        self.cfg.save_data = bool(checked)
        if checked:
            self.start_save_channels()
        else:
            self.stop_save_channels()
        self.update_save_text()

    def open_save_options(self):
        if self.save_dialog is None:
            self.save_dialog = SaveOptionsDialog(self)
            self.save_dialog.finished.connect(lambda _r: setattr(self, 'save_dialog', None))
        self.save_dialog.refresh()
        self.save_dialog.show()
        self.save_dialog.raise_()
        self.save_dialog.activateWindow()

    def update_save_text(self):
        parts = []
        for name, dev in self.save_channel_devices():
            if dev is None:
                parts.append(f'{name}: missing')
            else:
                parts.append(f"{name}: {'running' if dev.thread_running() else 'stopped'}, "
                             f"{save_channel_file(dev)}")
        text = '; '.join(parts) or 'no channel (a SQLite writer is added when switched on)'
        self.save_data.setToolTip('Save data: start the writer devices of this gateway (gear button: channels), '
                                  'they are in the device list of redvypr\n\n' + text.replace('; ', '\n'))
        self.live_tab.set_save_text(f'Save data: {text}' if self.cfg.save_data else '')

    def send_config(self):
        """Hand the changed configuration to the running device thread."""
        if self.device.get_thread_status()['thread_running']:
            self.device.thread_command('config', {'config': self.cfg.model_dump()})

    def on_live_result(self, data):
        hwid = data.get('hwid')
        if data.get('ok') and hwid:
            self.live_status[hwid] = data.get('status') or {}
        if data.get('message'):
            state = 'OK' if data.get('ok') else 'ERROR'
            self.console_text.appendPlainText(f"[live {data.get('target')}] {state}: {data['message']}")
        for dlg in [self.live_dialog] + list(self.device_live_dialogs.values()):
            if dlg is not None:
                dlg.on_result(data)

    # --- data from the device thread ---

    def read_statusqueue(self):
        """Messages of the device thread for the GUI (not published as data)."""
        q = getattr(self.device, 'statusqueue', None)
        if q is None:
            return
        messages = []
        while len(messages) < 1000:
            try:
                messages.append(q.get_nowait())
            except queue.Empty:
                break
            except Exception:
                break
        if messages:
            self.on_new_data(messages)

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
                # Thread update: dialog of that member; serial flash: dialog of the serial device
                dialogs = ([self.settings_dialogs[data['target']]] if data.get('target') in self.settings_dialogs
                           else [] if data.get('target') else self.serial_dialogs())
                for dlg in dialogs:
                    dlg.on_flash_status(data)
            elif packetid == 'props':
                dlg = self.settings_dialogs.get(data.get('target'))
                if dlg is not None:
                    dlg.on_props(data)
                if not data.get('ok'):
                    self.console_text.appendPlainText(f"[props {data.get('target')}] ERROR: {data.get('message')}")
            elif packetid in ('fs_progress', 'fs_result'):
                dlg = self.settings_dialogs.get(data.get('target'))
                if dlg is not None:
                    dlg.on_fs_message(packetid, data)
                if packetid == 'fs_result':
                    self.console_text.appendPlainText(
                        f"[fs {data.get('op')} {data.get('target')}] {'OK' if data.get('ok') else 'ERROR'}: "
                        f"{data.get('message', '')}")
            elif packetid in ('sync_progress', 'sync_result', 'sync_list', 'sync_list_partial'):
                dlg = self.settings_dialogs.get(data.get('target'))
                if dlg is not None:
                    dlg.on_sync_message(packetid, data)
                if packetid == 'sync_result':
                    self.console_text.appendPlainText(
                        f"[data {data.get('target')}] {'OK' if data.get('ok') else 'ERROR'}: {data.get('message', '')}")
            elif packetid in ('mag_result', 'mag_cal_progress', 'mag_cal_done', 'cal_result'):
                if packetid in ('mag_cal_done', 'cal_result') and data.get('message'):
                    state = 'OK' if data.get('ok') else 'ERROR'
                    self.console_text.appendPlainText(f"[{packetid.split('_')[0]} {data.get('target')}] {state}: "
                                                      f"{data.get('message', '')}")
                dlg = self.settings_dialogs.get(data.get('target'))
                if dlg is not None:
                    dlg.on_mag_message(packetid, data)
            elif packetid == 'adc_result':
                if data.get('message'):
                    state = 'OK' if data.get('ok') else 'ERROR'
                    self.console_text.appendPlainText(f"[adc {data.get('target')}] {state}: {data.get('message')}")
                dlg = self.settings_dialogs.get(data.get('target'))
                if dlg is not None:
                    dlg.on_adc_message(data)
            elif packetid == 'nmea_result':
                if data.get('message'):
                    state = 'OK' if data.get('ok') else 'ERROR'
                    self.console_text.appendPlainText(f"[nmea {data.get('target')}] {state}: {data.get('message')}")
                dlg = self.settings_dialogs.get(data.get('target'))
                if dlg is not None:
                    dlg.on_nmea_message(data)
            elif packetid == 'radio_result':
                state = 'OK' if data.get('ok') else 'ERROR'
                self.console_text.appendPlainText(f"[radio {data.get('target')}] {state}: {data.get('message', '')}")
                dlg = self.settings_dialogs.get(data.get('target'))
                if dlg is not None:
                    dlg.on_radio_result(data)
            elif packetid == 'time_result':
                state = 'OK' if data.get('ok') else 'ERROR'
                self.console_text.appendPlainText(f"[clock {data.get('target')}] {state}: {data.get('message', '')}")
                dlg = self.settings_dialogs.get(data.get('target'))
                if dlg is not None:
                    dlg.on_time_result(data)
            elif packetid == 'command_result':
                self.show_result(data)
            elif packetid == 'live_result':
                self.on_live_result(data)
            elif 'packet_type' in data and 'source' in data:    # '#NLD' packet (archive packets: no source)
                self.live_tab.add_packet(data)

    def show_result(self, data):
        text = f"[{data.get('command')}] {'OK' if data.get('ok') else 'ERROR'}: {data.get('message', '')}"
        self.console_text.appendPlainText(text)
        if data.get('command') == 'dataset' and data.get('ok'):
            self.cfg.dataset_tlvs = data.get('dataset_tlvs', '')
            self.update_dataset_label()
        elif data.get('command') == 'battery_upload':
            for dlg in self.serial_dialogs():
                dlg.on_battery_upload(data)
        elif data.get('command') == 'flash' and not data.get('ok'):
            for dlg in self.serial_dialogs():
                dlg.fw_log.appendPlainText(text)

    def update_run_state(self):
        running = self.device.get_thread_status()['thread_running']
        if running and not self.save_was_running and self.cfg.save_data:
            self.start_save_channels()
        self.save_was_running = running
        self.update_save_text()
        for w in self.run_widgets:
            w.setEnabled(running)
        for dlg in self.settings_dialogs.values():
            dlg.update_run_state(running)


def _live_pub_text(status):
    """'norlog pub' text of a device from its status ({'pub': {...}}), '' if unknown."""
    pub = (status or {}).get('pub')
    if not pub:
        return ''
    types = ot_cli.types_from_mask(int(pub.get('mask', 0)))
    targets = (['sinks'] if pub.get('sinks') else []) + list(pub.get('to') or [])
    return ot_cli.pub_text(types, targets)


def _live_parse(text):
    """'norlog pub' text -> (frozenset of types, tuple of targets); no target = sinks, 'off' = nothing."""
    parts = (text or 'off').split()
    if parts[0] == 'off':
        return frozenset(), ()
    types = frozenset(ot_cli.PACKET_TYPES) if parts[0] == 'all' else frozenset(parts[0].split(','))
    return types, tuple(parts[1:]) or ('sinks',)


def _live_text(types, targets):
    """(types, targets) -> 'norlog pub' text: 'off', 'all' or '<types> [targets]' (sinks is the default)."""
    if not types:
        return 'off'
    names = 'all' if set(types) == set(ot_cli.PACKET_TYPES) else ','.join(t for t in ot_cli.PACKET_TYPES
                                                                          if t in types)
    extra = [] if tuple(targets) in ((), ('sinks',)) else list(targets)
    return ' '.join([names] + extra)


class LiveSubscriptionsDialog(QtWidgets.QDialog):
    """
    Live data over Thread: one row per device (the gateway too), ticks = the packet types that
    come live from it ('norlog pub' of the device, stored there and in live_pub of the
    configuration). The gateway is always the sink for all types (set at the start).
    Yellow: changed, not applied yet; grey: state of the device not known (not read).
    """
    COL_DEVICE, COL_HWID, COL_RLOC = range(3)
    COL_TYPES = 3
    COL_RECEIVED = COL_TYPES + len(ot_cli.PACKET_TYPES)
    COL_LAST = COL_RECEIVED + 1
    PENDING = QtGui.QColor('#fff2b3')
    UNKNOWN = QtGui.QColor('#e6e6e6')

    def __init__(self, widget, hwid=None):
        super().__init__(widget)
        self.widget = widget
        self.cfg = widget.cfg
        self.only_hwid = hwid       # None: all devices, else only this device
        self.setWindowTitle('norlog live data: subscriptions' if hwid is None
                            else f'norlog live data: subscriptions of {self._device_name(widget, hwid)}')
        self.setModal(False)
        self.resize(1100, 480 if hwid is None else 260)
        lay = QtWidgets.QVBoxLayout(self)
        self.sink_status = QtWidgets.QLabel('Gateway: not read yet')
        self.sink_status.setWordWrap(True)
        self.sink_status.setVisible(hwid is None)
        lay.addWidget(self.sink_status)
        lay.addWidget(QtWidgets.QLabel('Ticked packet types come live from the device. Right click: all, none, '
                                       'targets. Yellow: not applied yet, grey: device not read.'))
        self.table = QtWidgets.QTableWidget(0, self.COL_LAST + 1)
        self.table.setHorizontalHeaderLabels(['Device', 'HW ID', 'RLOC16'] + list(ot_cli.PACKET_TYPES)
                                             + ['Received', 'Last [s]'])
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.table.itemChanged.connect(self.item_changed)
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        self.all_box = QtWidgets.QCheckBox('All')
        self.all_box.setToolTip('Tick or untick all packet types' + (' of all devices' if hwid is None else ''))
        self.all_box.clicked.connect(self.all_clicked)
        row.addWidget(self.all_box)
        self.apply_button = QtWidgets.QPushButton('Apply')
        self.apply_button.setToolTip('Send the changed rows to the devices (stored there and in the configuration)')
        self.apply_button.clicked.connect(self.apply_devices)
        self.read_button = QtWidgets.QPushButton('Reload')
        self.read_button.setToolTip('Read again what the devices send')
        self.read_button.clicked.connect(
            lambda: self.read_targets() and self.widget.device.thread_command('live_read',
                                                                              {'targets': self.read_targets()}))
        self.apply_start = QtWidgets.QCheckBox('Set at every start of the gateway device')
        self.apply_start.setChecked(self.cfg.live_apply)
        self.apply_start.toggled.connect(self.apply_start_changed)
        row.addWidget(self.apply_button)
        row.addWidget(self.read_button)
        row.addStretch(1)
        row.addWidget(self.apply_start)
        lay.addLayout(row)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(200)
        self.log.setMaximumHeight(70)
        lay.addWidget(self.log)
        self.rows = {}              # hwid -> row
        self.targets = {}           # hwid -> targets of the row (default ('sinks',))
        self.actual = {}            # hwid -> (types, targets) read from the device
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    # --- table ---

    @staticmethod
    def _device_name(widget, hwid):
        d = next((d for d in getattr(widget, 'current_devices', []) if d.get('hwid') == hwid), {})
        return f"{d.get('sn') or '?'} ({hwid})"

    def read_targets(self):
        """Targets of 'live_read': 'all', or the key of the single device ([] if it is not in the list)."""
        if self.only_hwid is None:
            return 'all'
        d = next((d for d in getattr(self.widget, 'current_devices', []) if d.get('hwid') == self.only_hwid), None)
        key = self.widget.device_key(d) if d is not None else ''
        return [key] if key else []

    def populate(self):
        """One row per device with a hardware ID: state of the device, or the stored wish if it differs."""
        devices = [d for d in getattr(self.widget, 'current_devices', []) if d.get('hwid')
                   and (self.only_hwid is None or d['hwid'] == self.only_hwid)]
        self.table.blockSignals(True)
        self.table.setRowCount(len(devices))
        self.rows = {}
        for row, d in enumerate(devices):
            hwid = d['hwid']
            self.rows[hwid] = row
            is_gateway = d.get('role') == device_list.ROLE_GATEWAY
            name = d.get('sn') or ''
            name = f'{name} (gateway)' if is_gateway else name
            for col, text in ((self.COL_DEVICE, name), (self.COL_HWID, hwid), (self.COL_RLOC, d.get('rloc16', ''))):
                item = QtWidgets.QTableWidgetItem(text)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                if col == self.COL_DEVICE:
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, self.widget.device_key(d))
                self.table.setItem(row, col, item)
            for col in (self.COL_RECEIVED, self.COL_LAST):
                item = QtWidgets.QTableWidgetItem('')
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
            now = _live_pub_text(self.widget.live_status.get(hwid))
            if now:
                self.actual[hwid] = _live_parse(now)
            wanted = self.cfg.live_pub.get(hwid) or now or (LIVE_GATEWAY_DEFAULT if is_gateway else 'off')
            self._set_row(row, hwid, _live_parse(wanted))
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.refresh()

    def _set_row(self, row, hwid, wanted):
        types, targets = wanted
        self.targets[hwid] = targets
        self.table.blockSignals(True)
        for i, name in enumerate(ot_cli.PACKET_TYPES):
            item = QtWidgets.QTableWidgetItem()
            item.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(QtCore.Qt.CheckState.Checked if name in types else QtCore.Qt.CheckState.Unchecked)
            self.table.setItem(row, self.COL_TYPES + i, item)
        self.table.blockSignals(False)
        self._color_row(row, hwid)
        self.update_all_box()

    def _checks(self):
        """All packet type items of the table."""
        items = (self.table.item(r, self.COL_TYPES + i) for r in self.rows.values()
                 for i in range(len(ot_cli.PACKET_TYPES)))
        return [it for it in items if it is not None]

    def update_all_box(self):
        checks = self._checks()
        n = sum(it.checkState() == QtCore.Qt.CheckState.Checked for it in checks)
        state = (QtCore.Qt.CheckState.Checked if checks and n == len(checks) else
                 QtCore.Qt.CheckState.Unchecked if n == 0 else QtCore.Qt.CheckState.PartiallyChecked)
        self.all_box.setTristate(state == QtCore.Qt.CheckState.PartiallyChecked)
        self.all_box.setCheckState(state)

    def all_clicked(self, _checked=False):
        """'All': tick everything unless everything is ticked already, then untick everything."""
        checks = self._checks()
        on = not (checks and all(it.checkState() == QtCore.Qt.CheckState.Checked for it in checks))
        types = frozenset(ot_cli.PACKET_TYPES) if on else frozenset()
        for hwid, row in self.rows.items():
            self._set_row(row, hwid, (types, (self.targets.get(hwid) or ('sinks',)) if on else ()))
        self.update_all_box()

    def _wanted(self, row, hwid):
        types = frozenset(name for i, name in enumerate(ot_cli.PACKET_TYPES)
                          if self.table.item(row, self.COL_TYPES + i).checkState() == QtCore.Qt.CheckState.Checked)
        return types, (self.targets.get(hwid) or ('sinks',)) if types else ()

    def _color_row(self, row, hwid):
        actual = self.actual.get(hwid)
        color = self.UNKNOWN if actual is None else self.PENDING if actual != self._wanted(row, hwid) else None
        tip = ('state of the device not known' if actual is None else
               f'device sends: {_live_text(*actual)}' if color is None else
               f'not applied yet; device sends: {_live_text(*actual)}')
        targets = ' '.join(self.targets.get(hwid) or ('sinks',))
        self.table.blockSignals(True)
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is not None:
                item.setBackground(color if color is not None else QtGui.QBrush())
                item.setToolTip(f'{tip}\ntargets: {targets}')
        self.table.blockSignals(False)

    def item_changed(self, item):
        hwid = next((h for h, r in self.rows.items() if r == item.row()), None)
        if hwid is not None:
            self._color_row(item.row(), hwid)
            self.update_all_box()

    def refresh(self):
        """Received packets and their age per device (from the device list), run state of the buttons."""
        running = self.widget.device.get_thread_status()['thread_running']
        self.apply_button.setEnabled(running)
        self.read_button.setEnabled(running)
        by_hwid = {d.get('hwid'): d for d in getattr(self.widget, 'current_devices', []) if d.get('hwid')}
        self.table.blockSignals(True)
        for hwid, row in self.rows.items():
            d = by_hwid.get(hwid) or {}
            last = d.get('last_data_s')
            for col, text in ((self.COL_RECEIVED, str(d.get('packets') or '')),
                              (self.COL_LAST, '' if last is None else f'{last:.0f}')):
                item = self.table.item(row, col)
                if item is not None and item.text() != text:
                    item.setText(text)
        self.table.blockSignals(False)

    def context_menu(self, point):
        item = self.table.itemAt(point)
        if item is None:
            return
        row = item.row()
        hwid = next((h for h, r in self.rows.items() if r == row), None)
        if hwid is None:
            return
        menu = QtWidgets.QMenu(self)
        menu.addAction('All packet types', lambda: self._set_row(row, hwid, (frozenset(ot_cli.PACKET_TYPES),
                                                                              self.targets.get(hwid) or ('sinks',))))
        menu.addAction('No packet types', lambda: self._set_row(row, hwid, (frozenset(), ())))
        menu.addSeparator()
        menu.addAction('Targets ...', lambda: self.edit_targets(row, hwid))
        menu.exec(self.table.viewport().mapToGlobal(point))

    def edit_targets(self, row, hwid):
        current = ' '.join(self.targets.get(hwid) or ('sinks',))
        text, ok = QtWidgets.QInputDialog.getText(
            self, 'Targets', 'Where the device sends: "sinks" (all sinks, e.g. this gateway) and/or IPv6 '
                             'addresses (ML-EID) of single devices, separated by spaces (at most 4 addresses)',
            text=current)
        if ok:
            self.targets[hwid] = tuple(text.split()) or ('sinks',)
            self._color_row(row, hwid)

    # --- apply ---

    def apply_start_changed(self, checked):
        self.cfg.live_apply = bool(checked)
        self.widget.send_config()

    def apply_devices(self):
        sent = 0
        for hwid, row in self.rows.items():
            wanted = self._wanted(row, hwid)
            if self.actual.get(hwid) == wanted:
                continue
            text = _live_text(*wanted)
            self.cfg.live_pub[hwid] = text
            key = self.table.item(row, self.COL_DEVICE).data(QtCore.Qt.ItemDataRole.UserRole)
            self.widget.device.thread_command('live_pub_set', {'target': key, 'text': text, 'hwid': hwid})
            sent += 1
            for dlg in [self.widget.live_dialog] + list(self.widget.device_live_dialogs.values()):
                if dlg is not None and dlg is not self and hwid in dlg.rows:
                    dlg._set_row(dlg.rows[hwid], hwid, wanted)    # other open dialogs show the new wish
        self.widget.send_config()
        self.log.appendPlainText(f'{sent} device(s) set' if sent else 'Nothing to change')

    def on_result(self, data):
        hwid = data.get('hwid')
        if self.only_hwid is not None and hwid != self.only_hwid:
            return
        if data.get('message'):
            self.log.appendPlainText(f"{data.get('target')}: {'OK' if data.get('ok') else 'ERROR'} "
                                     f"{data['message']}")
        status = data.get('status') or {}
        row = self.rows.get(hwid)
        if data.get('ok') and status.get('pub') and row is not None:
            self.actual[hwid] = _live_parse(_live_pub_text(status))
            if hwid not in self.cfg.live_pub:
                self._set_row(row, hwid, self.actual[hwid])
            else:
                self._color_row(row, hwid)
        if data.get('ok') and data.get('target') == 'gateway':
            sink = status.get('sink') or {}
            others = [k for k in sink.get('known') or []]
            self.sink_status.setText(
                f"Gateway: {'sink for the live data of the network' if sink.get('on') else 'NOT a sink'}, "
                f"received {sink.get('received', 0)} packets, dropped {sink.get('rx_dropped', 0)}"
                + (f"; other sinks: {', '.join(k.get('addr', '') for k in others)}" if others else ''))


class LiveDataTab(QtWidgets.QWidget):
    """
    Tab "Live data": live data received from the Thread network ('#NLD'), last packet per
    device and packet type with the lost packets (gaps in packet_num_type), and a log of the
    incoming packets. "Subscriptions" sets what the devices send.
    """
    COLUMNS = ['Device', 'HW ID', 'Type', 'Measured', 'Received', 'Packet # (type)', 'Lost', 'Count', 'Values']
    SKIP = {'packet_type', 'mac', 'packet_num', 'packet_num_type', 'uptime_ms', 'boot', 'source', 't',
            'rtc_time', 'rtc_time_iso', 'gps_time_iso', 'raw_data', 'offset_ms', 't_source'}

    def __init__(self, widget):
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.summary = QtWidgets.QLabel('No live data yet (devices send with "norlog pub", see Subscriptions)')
        self.subs_button = QtWidgets.QPushButton('Subscriptions ...')
        self.subs_button.setToolTip('What each device sends live (norlog pub, firmware >= 0.4.32); the gateway '
                                    'is the sink')
        self.subs_button.clicked.connect(widget.open_live_subscriptions)
        self.pause = QtWidgets.QCheckBox('Pause log')
        clear = QtWidgets.QPushButton('Clear')
        clear.clicked.connect(self.clear)
        row.addWidget(self.summary, 1)
        row.addWidget(self.subs_button)
        row.addWidget(self.pause)
        row.addWidget(clear)
        lay.addLayout(row)
        self.save_label = QtWidgets.QLabel('')
        self.save_label.setWordWrap(True)
        self.save_label.setVisible(False)
        lay.addWidget(self.save_label)
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.table = QtWidgets.QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        split.addWidget(self.table)
        split.addWidget(self.log)
        split.setSizes([350, 250])
        lay.addWidget(split, 1)
        self.clear()

    def clear(self):
        self.rows = {}              # (hwid, packet_type) -> row
        self.gaps = {}              # (hwid, base type) -> {'boot', 'num', 'lost'}
        self.counts = {}            # (hwid, packet_type) -> packets
        self.total = 0
        self.table.setRowCount(0)
        self.log.clear()

    def set_save_text(self, text):
        self.save_label.setText(text)
        self.save_label.setVisible(bool(text))

    @staticmethod
    def base_type(data):
        return norlog_cbor.base_type(data)

    def add_packet(self, data):
        hwid = str(data.get('mac', '?'))
        ptype = data.get('packet_type', '?')
        try:
            device = data['_redvypr']['device']
        except (KeyError, TypeError):
            device = ''
        num = data.get('packet_num_type')
        gap = self.gaps.setdefault((hwid, self.base_type(data)), {'boot': None, 'num': None, 'lost': 0})
        if isinstance(num, int):
            if gap['boot'] == data.get('boot') and gap['num'] is not None and num > gap['num'] + 1:
                gap['lost'] += num - gap['num'] - 1
            gap['boot'], gap['num'] = data.get('boot'), num
        key = (hwid, ptype)
        self.counts[key] = self.counts.get(key, 0) + 1
        self.total += 1
        t = data.get('t')
        measured = time.strftime('%H:%M:%S', time.localtime(t)) if isinstance(t, (int, float)) else ''
        received = time.strftime('%H:%M:%S')
        values = ', '.join(f'{k}={v:.4g}' if isinstance(v, float) else f'{k}={v}'
                           for k, v in data.items() if k not in self.SKIP and not k.startswith('_'))
        row = self.rows.get(key)
        if row is None:
            row = self.rows[key] = self.table.rowCount()
            self.table.insertRow(row)
        cells = [device, hwid, ptype, measured, received, '' if num is None else str(num), str(gap['lost']),
                 str(self.counts[key]), values]
        for col, text in enumerate(cells):
            self.table.setItem(row, col, QtWidgets.QTableWidgetItem(text))
        lost = sum(g['lost'] for g in self.gaps.values())
        self.summary.setText(f'{self.total} packets from {len({k[0] for k in self.rows})} device(s), '
                             f'{lost} lost (gaps in packet_num_type)')
        if not self.pause.isChecked():
            self.log.appendPlainText(f'{received} {device or hwid} {ptype} #{num if num is not None else "-"} '
                                     f'{values}')


def _sqlite_channel_config(gateway):
    """
    sqlite_writer configuration: the packets of this gateway as they are (raw data, no flat table), each
    packet once (uid_keys boot, packet_num: also with the same packets converted from the SD card into
    the same file).
    """
    from redvypr.devices.db import sqlite_writer
    from redvypr.devices.db.db_config_util import DbTableConfig
    cfg = sqlite_writer.DeviceCustomConfig()
    cfg.database = cfg.database.model_copy(deep=True)
    cfg.database.filepath = f'{gateway}.sqlite'
    cfg.database.write_config.name = f'norlog gateway {gateway}'
    addresses = save_addresses(gateway, [])
    cfg.database.write_config.tables = {
        'redvypr_raw': DbTableConfig(tablename='redvypr_raw', tabletype='redvypr_datapacket', addresses=addresses,
                                     skip_duplicates=True, uid_keys=norlog_convert.UID_KEYS)}
    return cfg


# "Save data" channels: label -> (redvypr device module, configuration for a gateway)
SAVE_CHANNEL_TYPES = {'SQLite': ('sqlite_writer', _sqlite_channel_config)}


def save_addresses(gateway, packetids):
    """Subscriptions of a channel: all packets of the gateway or only these packet IDs (packet types)."""
    if not packetids:
        return [f"@p:'{gateway}'"]
    return [f"@p:'{gateway}' and i:'{p}'" for p in packetids]


def save_channel_packetids(dev):
    """Packet IDs the channel saves (from its table addresses), [] = all packets of the gateway."""
    tables = getattr(getattr(getattr(dev.custom_config, 'database', None), 'write_config', None), 'tables', {})
    ids = []
    for t in tables.values():
        for a in t.addresses:
            ids += [p for p in re.findall(r"\bi:'([^']*)'", a) if p not in ids]
    return ids


def save_channel_file(dev):
    db = getattr(dev.custom_config, 'database', None)
    return getattr(db, 'filepath', '') or '?'


class SaveOptionsDialog(QtWidgets.QDialog):
    """
    Options of "Save data": the channels are writer devices of redvypr (for now sqlite_writer) that
    subscribe to the packets of this gateway; here: add, remove, file and packet types. All other
    settings in the device itself (device list of redvypr).
    """

    def __init__(self, widget):
        super().__init__(widget)
        self.widget = widget
        self.setWindowTitle(f'{widget.device.name}: save data')
        self.setModal(False)
        self.resize(820, 460)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel('Channels: writer devices of redvypr that save the data of this gateway. '
                                       '"Save data" starts and stops them.'))
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Device', 'Type', 'State', 'File'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.select)
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QToolButton()
        add.setText('Add')
        add.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QtWidgets.QMenu(add)
        for kind in SAVE_CHANNEL_TYPES:
            menu.addAction(kind, lambda k=kind: self.add_channel(k))
        add.setMenu(menu)
        self.remove_button = QtWidgets.QPushButton('Remove')
        self.remove_button.clicked.connect(self.remove_channel)
        row.addWidget(add)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        lay.addLayout(row)
        self.editor = QtWidgets.QGroupBox('Channel')
        form = QtWidgets.QFormLayout(self.editor)
        file_row = QtWidgets.QHBoxLayout()
        self.e_file = QtWidgets.QLineEdit()
        self.e_file.setToolTip('SQLite file; the writer makes <name>_<count>_<date>.sqlite of it unless it '
                               'continues one file (settings of the device)')
        browse = QtWidgets.QToolButton()
        browse.setText('...')
        browse.clicked.connect(self.browse_file)
        file_row.addWidget(self.e_file, 1)
        file_row.addWidget(browse)
        form.addRow('File', file_row)
        types = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(types)
        grid.setContentsMargins(0, 0, 0, 0)
        self.e_all = QtWidgets.QCheckBox('all packets of the gateway')
        self.e_all.toggled.connect(self.all_toggled)
        grid.addWidget(self.e_all, 0, 0, 1, 4)
        self.e_types = {}
        for i, name in enumerate(t for t in ot_cli.PACKET_TYPES if not t.startswith('adcseq')):
            cb = QtWidgets.QCheckBox(name)
            grid.addWidget(cb, 1 + i // 4, i % 4)
            self.e_types[name] = cb
        self.e_other = QtWidgets.QLineEdit()
        self.e_other.setPlaceholderText('more packet IDs, e.g. ADC sequences by sensor name: adc_brd hfm; info')
        grid.addWidget(self.e_other, 3, 0, 1, 4)
        form.addRow('Packet types', types)
        self.apply_button = QtWidgets.QPushButton('Apply')
        self.apply_button.setToolTip('Store file and packet types in the device (a running device is restarted)')
        self.apply_button.clicked.connect(self.apply)
        hint = QtWidgets.QLabel('More settings (storage, new files, tables): the device itself in the device '
                                'list of redvypr.')
        hint.setWordWrap(True)
        form.addRow(self.apply_button, hint)
        lay.addWidget(self.editor)
        self.log = QtWidgets.QLabel('')
        lay.addWidget(self.log)
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        lay.addWidget(close)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_states)
        self.timer.start(1000)
        self.refresh()

    def refresh(self):
        selected = self.current_name()
        channels = self.widget.save_channel_devices()
        self.table.blockSignals(True)
        self.table.setRowCount(len(channels))
        for row, (name, dev) in enumerate(channels):
            kind = next((k for k, (m, _f) in SAVE_CHANNEL_TYPES.items()
                         if dev is not None and str(dev.devicemodulename).split('.')[-1] == m), '?')
            for col, text in enumerate([name, kind, '', '' if dev is None else save_channel_file(dev)]):
                self.table.setItem(row, col, QtWidgets.QTableWidgetItem(text))
        self.table.blockSignals(False)
        self.update_states()
        names = [n for n, _d in channels]
        if names:
            self.table.selectRow(names.index(selected) if selected in names else 0)
        self.select()

    def update_states(self):
        for row, (_name, dev) in enumerate(self.widget.save_channel_devices()):
            item = self.table.item(row, 2)
            if item is not None:
                item.setText('missing (removed from redvypr)' if dev is None else
                             'running' if dev.thread_running() else 'stopped')

    def current_name(self):
        rows = self.table.selectionModel().selectedRows()
        item = self.table.item(rows[0].row(), 0) if rows else None
        return item.text() if item is not None else None

    def current_device(self):
        return dict(self.widget.save_channel_devices()).get(self.current_name())

    def select(self):
        dev = self.current_device()
        self.editor.setEnabled(dev is not None)
        self.remove_button.setEnabled(self.current_name() is not None)
        if dev is None:
            return
        self.editor.setTitle(f'Channel {dev.name}')
        self.e_file.setText(save_channel_file(dev))
        ids = save_channel_packetids(dev)
        self.e_all.setChecked(not ids)
        for name, cb in self.e_types.items():
            cb.setChecked(name in ids)
        self.e_other.setText(' '.join(i for i in ids if i not in self.e_types))
        self.all_toggled(not ids)

    def all_toggled(self, checked):
        for cb in self.e_types.values():
            cb.setEnabled(not checked)
        self.e_other.setEnabled(not checked)

    def browse_file(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'SQLite file', self.e_file.text(), 'SQLite (*.sqlite *.db);;All files (*)',
            options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
        if path:
            self.e_file.setText(path)

    def add_channel(self, kind):
        dev = self.widget.create_save_channel(kind)
        if dev is not None and self.widget.cfg.save_data:
            dev.thread_start()
        self.refresh()
        if dev is not None:
            self.table.selectRow(self.table.rowCount() - 1)
        self.log.setText(f'Added {dev.name}' if dev is not None else 'Could not add the device')

    def remove_channel(self):
        name = self.current_name()
        if name is None:
            return
        answer = QtWidgets.QMessageBox.question(
            self, 'Remove channel', f'Remove the channel {name} and its device from redvypr? (The files stay.)')
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.widget.remove_save_channel(name)
        self.refresh()
        self.log.setText(f'Removed {name}')

    def apply(self):
        dev = self.current_device()
        if dev is None:
            return
        path = self.e_file.text().strip()
        if not path:
            QtWidgets.QMessageBox.warning(self, 'Save data', 'The channel needs a file.')
            return
        ids = [] if self.e_all.isChecked() else (
            [n for n, cb in self.e_types.items() if cb.isChecked()] + self.e_other.text().replace(',', ' ').split())
        db = dev.custom_config.database
        db.filepath = path
        for t in db.write_config.tables.values():
            t.addresses = save_addresses(self.widget.device.name, ids)
        if dev.thread_running():
            dev.thread_stop()
            restart = QtCore.QTimer(self)

            def start_when_stopped():
                if not dev.thread_running():
                    restart.stop()
                    dev.thread_start()
            restart.timeout.connect(start_when_stopped)
            restart.start(200)
            self.log.setText(f'{dev.name}: stored, restarting')
        else:
            self.log.setText(f'{dev.name}: stored (used at the next start)')
        self.refresh()


class ProvisionWorker(QtCore.QThread):
    """Stores the dataset on a node at a serial port (gateway not running), without blocking the GUI."""
    message = QtCore.pyqtSignal(bool, str)              # ok, text (progress for the console)
    finished_result = QtCore.pyqtSignal(bool, str)      # ok, text

    def __init__(self, port, baud, dataset, parent=None):
        super().__init__(parent)
        self.port, self.baud, self.dataset = port, baud, dataset

    def run(self):
        try:
            ser = serial.Serial(self.port, self.baud, timeout=0.05)
        except (serial.SerialException, OSError) as exc:
            self.finished_result.emit(False, f'Could not open {self.port}: {exc}')
            return
        try:
            cli = ot_cli.OtCli(ser, ot_cli.LineReader(), lambda line, is_resp: None)
            self.message.emit(True, f'Provisioning {self.port} ...')
            st = ot_cli.provision_node(cli, self.dataset)
            if st['attached']:
                text = f"{self.port} joined the network as {st['state']} (extaddr {st['extaddr']})"
            else:
                text = (f"{self.port}: dataset stored, but not attached yet (state {st['state']!r}). "
                        f"Out of range or no leader running?")
            self.message.emit(st['attached'], text)
            self.finished_result.emit(st['attached'], text)
        except Exception as exc:        # shown in the GUI, the GUI must not die
            text = f'{self.port}: {type(exc).__name__}: {exc}'
            self.message.emit(False, text)
            self.finished_result.emit(False, text)
        finally:
            ser.close()


class ConvertWorker(QtCore.QThread):
    """Converts *.cbor files into an SQLite database (norlog_convert) without blocking the GUI."""
    progress = QtCore.pyqtSignal(int, int, str)
    finished_result = QtCore.pyqtSignal(dict, str)     # result, error text

    def __init__(self, files, db_path, sn=None, flat=True, parent=None):
        super().__init__(parent)
        self.files, self.db_path, self.sn, self.flat = files, db_path, sn, flat

    def run(self):
        try:
            res = norlog_convert.convert(self.files, self.db_path, sn=self.sn, flat=self.flat,
                                         progress=lambda i, n, name: self.progress.emit(i, n, name),
                                         cancel=self.isInterruptionRequested)
        except Exception as exc:        # shown in the dialog, the GUI must not die
            self.finished_result.emit({}, f'{type(exc).__name__}: {exc}')
            return
        self.finished_result.emit(res, '')


class AdcCalibrationDialog(QtWidgets.QDialog):
    """
    Calibration of one channel of the ADC sequence, stored and applied on the device:
    - Polynomial (firmware >= 0.4.16): y = c0 + c1*x + ... + c5*x^5, x = value of the step
    - NTC (firmware >= 0.4.17), like redvypr's CalibrationNTC: R = x * R_ref,
      T = 1 / (c0 + c1*ln(R) + ...) - Toff
    The coefficients are entered directly, set from a sensitivity (linear sensors, e.g.
    heat flux sensors), fitted to reference points or loaded from a redvypr calibration file.
    """

    SCALES = {'V': 1.0, 'mV': 1e-3, 'µV': 1e-6}
    KIND_LABELS = {'poly': 'Polynomial', 'ntc': 'NTC (Steinhart-Hart / Hoge, as redvypr CalibrationNTC)'}

    def __init__(self, parent, name, x_unit, cal=None, x_value=None):
        super().__init__(parent)
        self.setWindowTitle(f'Calibration {name}')
        self.name = name
        self.x_unit = x_unit
        self.x_value = x_value
        self.calibration = None
        self.delete_requested = False
        lay = QtWidgets.QVBoxLayout(self)
        xu = {'degC': '°C', '1': 'U_in/U_ref'}.get(x_unit, x_unit)
        self.xu = xu
        head = QtWidgets.QLabel(f'<b>{name}</b>: x = value of the step [{xu}]'
                                + (f', last measured x = {x_value:.7g}' if x_value is not None else ''))
        head.setWordWrap(True)
        lay.addWidget(head)

        form = QtWidgets.QGridLayout()
        self.kind = QtWidgets.QComboBox()
        for kind, label in self.KIND_LABELS.items():
            self.kind.addItem(label, kind)
        self.kind.currentIndexChanged.connect(self.kind_changed)
        self.formula = QtWidgets.QLabel('')
        self.formula.setStyleSheet('color: gray;')
        self.unit = QtWidgets.QLineEdit(cal.unit if cal else '')
        self.unit.setPlaceholderText('e.g. W/m2, degC, Pa')
        self.unit.setMaxLength(poly_calibration.UNIT_MAX)
        self.unit.textChanged.connect(self.update_preview)
        self.ident = QtWidgets.QLineEdit(cal.id if cal else '')
        self.ident.setPlaceholderText('optional, e.g. serial number of the sensor')
        self.ident.setMaxLength(poly_calibration.ID_MAX)
        self.scale = QtWidgets.QLineEdit(f'{cal.scale:.12g}' if cal and cal.kind == 'ntc' else '10000')
        self.scale.setToolTip('R = x * R_ref: the reference resistor of a ratiometric measurement (x = R/R_ref); '
                              '1 if x is already the resistance in Ohm')
        self.scale.textChanged.connect(self.update_preview)
        self.toff = QtWidgets.QLineEdit(f'{cal.toff:.12g}' if cal and cal.kind == 'ntc' else '273.15')
        self.toff.setToolTip('T = 1/(...) - Toff; 273.15 for degC')
        self.toff.textChanged.connect(self.update_preview)
        form.addWidget(QtWidgets.QLabel('Kind'), 0, 0)
        form.addWidget(self.kind, 0, 1, 1, 3)
        form.addWidget(self.formula, 1, 0, 1, 4)
        form.addWidget(QtWidgets.QLabel('Unit of y'), 2, 0)
        form.addWidget(self.unit, 2, 1)
        form.addWidget(QtWidgets.QLabel('Id'), 2, 2)
        form.addWidget(self.ident, 2, 3)
        self.ntc_widgets = [QtWidgets.QLabel('R_ref [Ohm]'), self.scale, QtWidgets.QLabel('Toff'), self.toff]
        for i, wdg in enumerate(self.ntc_widgets):
            form.addWidget(wdg, 3, i)
        self.coeffs = []
        for i in range(poly_calibration.ORDER_MAX + 1):
            edit = QtWidgets.QLineEdit()
            if cal and i < len(cal.coeffs):
                edit.setText(f'{cal.coeffs[i]:.12g}')
            edit.textChanged.connect(self.update_preview)
            self.coeffs.append(edit)
            form.addWidget(QtWidgets.QLabel(f'c{i}'), 4 + i // 2, 2 * (i % 2))
            form.addWidget(edit, 4 + i // 2, 2 * (i % 2) + 1)
        lay.addLayout(form)

        self.sens_box = QtWidgets.QGroupBox('Linear from the sensitivity of the sensor')
        row = QtWidgets.QHBoxLayout(self.sens_box)
        self.sens = QtWidgets.QLineEdit()
        self.sens.setPlaceholderText('e.g. 62.5')
        self.sens_scale = QtWidgets.QComboBox()
        self.sens_scale.addItems(list(self.SCALES) if x_unit == 'V' else [xu])
        if x_unit == 'V':
            self.sens_scale.setCurrentText('µV')     # typical for thermopiles / heat flux sensors
        sens_btn = QtWidgets.QPushButton('Set c0, c1')
        sens_btn.clicked.connect(self.set_from_sensitivity)
        row.addWidget(QtWidgets.QLabel('Sensitivity'))
        row.addWidget(self.sens)
        row.addWidget(self.sens_scale)
        row.addWidget(QtWidgets.QLabel('per unit of y'))
        row.addWidget(sens_btn)
        lay.addWidget(self.sens_box)

        box = QtWidgets.QGroupBox('Fit to reference points')
        grid = QtWidgets.QGridLayout(box)
        self.points = QtWidgets.QTableWidget(0, 2)
        self.points.setHorizontalHeaderLabels([f'x [{xu}]', 'y (reference)'])
        self.points.horizontalHeader().setStretchLastSection(True)
        self.points.setMinimumHeight(120)
        add_btn = QtWidgets.QPushButton('Add point')
        add_btn.clicked.connect(lambda: self.add_point(''))
        cur_btn = QtWidgets.QPushButton('Add last measured x')
        cur_btn.setEnabled(x_value is not None)
        cur_btn.setToolTip('"Measure once" in the ADC tab updates the value')
        cur_btn.clicked.connect(lambda: self.add_point(f'{x_value:.9g}' if x_value is not None else ''))
        del_btn = QtWidgets.QPushButton('Remove')
        del_btn.clicked.connect(lambda: [self.points.removeRow(r) for r in
                                         sorted({i.row() for i in self.points.selectedIndexes()}, reverse=True)])
        self.order = QtWidgets.QSpinBox()
        self.order.setRange(1, poly_calibration.ORDER_MAX)
        fit_btn = QtWidgets.QPushButton('Fit')
        fit_btn.clicked.connect(self.do_fit)
        self.fit_note = QtWidgets.QLabel('')
        self.fit_note.setStyleSheet('color: gray;')
        self.fit_note.setWordWrap(True)
        grid.addWidget(self.points, 0, 0, 1, 6)
        grid.addWidget(add_btn, 1, 0)
        grid.addWidget(cur_btn, 1, 1)
        grid.addWidget(del_btn, 1, 2)
        grid.addWidget(QtWidgets.QLabel('Order'), 1, 3)
        grid.addWidget(self.order, 1, 4)
        grid.addWidget(fit_btn, 1, 5)
        grid.addWidget(self.fit_note, 2, 0, 1, 6)
        lay.addWidget(box)

        row = QtWidgets.QHBoxLayout()
        load_btn = QtWidgets.QPushButton('Load redvypr calibration ...')
        load_btn.setToolTip('Calibration file of redvypr (calibration device): ntc, polynom, linearfactor, heatflow')
        load_btn.clicked.connect(self.load_redvypr)
        save_btn = QtWidgets.QPushButton('Save as redvypr calibration ...')
        save_btn.clicked.connect(self.save_redvypr)
        row.addWidget(load_btn)
        row.addWidget(save_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self.preview = QtWidgets.QLabel('')
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.preview)
        buttons = QtWidgets.QDialogButtonBox()
        apply_btn = buttons.addButton('Apply to device', QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        apply_btn.clicked.connect(self.apply)
        if cal is not None:
            delete_btn = buttons.addButton('Delete on device', QtWidgets.QDialogButtonBox.ButtonRole.DestructiveRole)
            delete_btn.clicked.connect(self.delete)
        buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.kind.setCurrentIndex(list(self.KIND_LABELS).index(cal.kind) if cal else 0)
        self.kind_changed()

    def current_kind(self):
        return self.kind.currentData() or 'poly'

    def kind_changed(self, *_args):
        ntc = self.current_kind() == 'ntc'
        for wdg in self.ntc_widgets:
            wdg.setVisible(ntc)
        self.sens_box.setVisible(not ntc)
        self.formula.setText('T = 1 / (c0 + c1·ln R + c2·(ln R)² + c3·(ln R)³ ...) - Toff,  R = x · R_ref [Ohm]'
                             if ntc else 'y = c0 + c1·x + c2·x² + ... + c5·x⁵')
        self.order.setValue(3 if ntc else self.order.value())
        self.fit_note.setText('NTC: x = R/R_ref of the step, y = reference temperature; order 3 = Steinhart-Hart '
                              'with ln² term (redvypr default), needs at least 4 points' if ntc else
                              'x = value of the step, y = reference')
        if ntc and not self.unit.text():
            self.unit.setText('degC')
        self.update_preview()

    def add_point(self, x_text):
        r = self.points.rowCount()
        self.points.insertRow(r)
        self.points.setItem(r, 0, QtWidgets.QTableWidgetItem(x_text))
        self.points.setItem(r, 1, QtWidgets.QTableWidgetItem(''))
        self.points.setCurrentCell(r, 1)
        self.points.editItem(self.points.item(r, 1))

    def _set_coeffs(self, coeffs):
        for i, edit in enumerate(self.coeffs):
            edit.setText(f'{coeffs[i]:.12g}' if i < len(coeffs) else '')

    def _set_calibration(self, cal):
        self.kind.setCurrentIndex(list(self.KIND_LABELS).index(cal.kind))
        self.unit.setText(cal.unit)
        if cal.id:
            self.ident.setText(cal.id)
        if cal.kind == 'ntc':
            self.scale.setText(f'{cal.scale:.12g}')
            self.toff.setText(f'{cal.toff:.12g}')
        self._set_coeffs(cal.coeffs)

    def _error(self, text):
        self.preview.setStyleSheet('color: #d64545;')
        self.preview.setText(text)

    @staticmethod
    def _num(text):
        return float(text.strip().replace(',', '.'))

    def set_from_sensitivity(self):
        try:
            s = self._num(self.sens.text()) * self.SCALES.get(self.sens_scale.currentText(), 1.0)
            cal = poly_calibration.linear_from_sensitivity(s, self.unit.text() or '?')
        except (ValueError, poly_calibration.CalibrationError) as exc:
            self._error(f'sensitivity: {exc}')
            return
        self._set_coeffs(cal.coeffs)

    def do_fit(self):
        pts = []
        try:
            for r in range(self.points.rowCount()):
                x, y = (self.points.item(r, c).text().strip() if self.points.item(r, c) else '' for c in (0, 1))
                if x or y:
                    pts.append((self._num(x), self._num(y)))
            if self.current_kind() == 'ntc':
                cal, rms = poly_calibration.fit_ntc(pts, self.order.value(), scale=self._num(self.scale.text()),
                                                    toff=self._num(self.toff.text()), unit=self.unit.text() or 'degC')
            else:
                cal, rms = poly_calibration.fit(pts, self.order.value(), self.unit.text() or '?')
        except (ValueError, poly_calibration.CalibrationError) as exc:
            self._error(f'fit: {exc}')
            return
        self._set_coeffs(cal.coeffs)
        self.preview.setText(self.preview.text() + f'; fit: {len(pts)} points, rms residual {rms:.4g}')

    def current(self):
        """Calibration of the fields (coefficients up to the last one filled in)."""
        texts = [e.text().strip().replace(',', '.') for e in self.coeffs]
        n = max([i + 1 for i, t in enumerate(texts) if t] + [2])
        coeffs = [float(t) if t else 0.0 for t in texts[:n]]
        kind = self.current_kind()
        cal = poly_calibration.PolyCalibration(
            coeffs=coeffs, unit=self.unit.text().strip(), id=self.ident.text().strip(), date=int(time.time()),
            name=self.name, kind=kind, scale=self._num(self.scale.text()) if kind == 'ntc' else 1.0,
            toff=self._num(self.toff.text()) if kind == 'ntc' else 273.15)
        cal.check()
        return cal

    def update_preview(self, *_args):
        try:
            cal = self.current()
        except (ValueError, poly_calibration.CalibrationError) as exc:
            self._error(str(exc))
            return
        self.preview.setStyleSheet('')
        text = cal.summary()
        if self.x_value is not None:
            text += f';  last x = {self.x_value:.7g} → y = {cal.apply(self.x_value):.7g} {cal.unit}'
        self.preview.setText(text)

    def load_redvypr(self):
        from redvypr.devices.sensors.calibration.calibration_models import CalibrationList
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'redvypr calibration', '',
                                                         'Calibration (*.yaml *.yml);;All files (*)')
        if not fname:
            return
        cals = [c for c in (CalibrationList().read_calibration_file(fname) or [])
                if getattr(c, 'calibration_type', '') in ('ntc', 'polynom', 'linearfactor', 'heatflow')]
        if not cals:
            self._error(f'no usable calibration (ntc, polynom, linearfactor, heatflow) in {fname}')
            return
        cal = cals[0]
        if len(cals) > 1:
            labels = [f"{i}: {c.calibration_type}  sn {c.sn}  channel {c.channel}  {c.date:%Y-%m-%d}  "
                      f"{c.calibration_id}" for i, c in enumerate(cals)]
            choice, ok = QtWidgets.QInputDialog.getItem(self, 'redvypr calibration', 'Calibration', labels, 0, False)
            if not ok:
                return
            cal = cals[labels.index(choice)]
        scale = None
        if cal.calibration_type == 'ntc':
            try:
                scale = self._num(self.scale.text())
            except ValueError:
                scale = 10000.0
            scale, ok = QtWidgets.QInputDialog.getDouble(
                self, 'NTC', 'redvypr NTC calibrations take R in Ohm.\nR_ref of the ratiometric measurement '
                             '(x = R/R_ref) in Ohm, 1 if x is already R:', scale, 1e-6, 1e12, 3)
            if not ok:
                return
        try:
            self._set_calibration(poly_calibration.from_redvypr(cal, scale=scale))
        except poly_calibration.CalibrationError as exc:
            self._error(str(exc))
            return
        self.preview.setText(self.preview.text() + f'; loaded {cal.calibration_type} of sn {cal.sn} '
                                                   f'({pathlib.Path(fname).name})')

    def save_redvypr(self):
        from redvypr.devices.sensors.calibration.calibration_models import CalibrationList
        try:
            cal = self.current()
        except (ValueError, poly_calibration.CalibrationError) as exc:
            self._error(str(exc))
            return
        channel = self.name.split('.', 1)[-1]
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save as redvypr calibration',
                                                         f'calibration_{self.name.replace(".", "_")}.yaml',
                                                         'Calibration (*.yaml)')
        if not fname:
            return
        rv = poly_calibration.to_redvypr(cal, channel=channel, sn=cal.id or 'NA')
        CalibrationList([rv]).save([fname])
        self.preview.setText(self.preview.text() + f'; saved as redvypr {rv.calibration_type}: {fname}')

    def apply(self):
        try:
            self.calibration = self.current()
            self.calibration.to_text()
        except (ValueError, poly_calibration.CalibrationError) as exc:
            self._error(str(exc))
            return
        self.accept()

    def delete(self):
        if QtWidgets.QMessageBox.question(self, 'Delete calibration',
                                          f'Delete the calibration {self.name} on the device?') \
                == QtWidgets.QMessageBox.StandardButton.Yes:
            self.delete_requested = True
            self.accept()


class DeviceSettingsDialog(QtWidgets.QDialog):
    """
    Settings of one norlog of the device table: general info and firmware
    update. Firmware updates are only possible over serial (the gateway port)
    so far; for Thread members the firmware tab is disabled.
    """

    GENERAL_FIELDS = ['Device', 'RLOC16', 'Connection', 'Role', 'Thread role', 'Thread', 'Image', 'Firmware', 'Build',
                      'Board', 'HW ID', 'Battery', 'Board temp', 'GNSS', 'Uptime', 'Clock', 'Reset cause', 'Hardware',
                      'SD card',
                      'Battery model', 'USB', 'TX power', 'Log level', 'Info age']

    USB_MODES = ['auto', 'manual', 'off']
    # Battery models built into the firmware ('custom' = loaded with "Load .inc")
    BATTERY_MODELS = ['akyga_lp805080', 'nordic_example', 'custom']

    def __init__(self, widget, key):
        super().__init__(widget)
        self.widget = widget
        self.device = widget.device
        self.cfg = widget.cfg
        self.key = key
        self.entry = {}
        self.running = False
        self.setWindowTitle(f'norlog settings: {key}')
        self.setWindowIcon(qtawesome.icon(iconnames['settings']))
        # Höchstens 85 % der Bildschirmhöhe; der Inhalt der Reiter scrollt
        screen = QtWidgets.QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        self.resize(640, min(720, int(avail.height() * 0.85)) if avail is not None else 720)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._scrollable(self._build_general_tab()), 'General')
        self.fw_tab_index = self.tabs.addTab(self._build_firmware_tab(), 'Firmware')
        self.files_tab_index = self.tabs.addTab(self._build_files_tab(), 'Files')
        self.data_tab_index = self.tabs.addTab(self._build_data_tab(), 'Data')
        self.mag_tab_index = self.tabs.addTab(self._scrollable(self._build_mag_tab()), 'Magnetometer')
        self.adc_tab_index = self.tabs.addTab(self._scrollable(self._build_adc_tab()), 'ADC')
        self.nmea_tab_index = self.tabs.addTab(self._scrollable(self._build_nmea_tab()), 'NMEA')
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(buttons)

    @staticmethod
    def _scrollable(widget):
        """Wrap a tab in a scroll area (vertical scrollbar when the window is too small)."""
        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(widget)
        return area

    def is_serial(self):
        return self.entry.get('connection') == device_list.CONNECTION_SERIAL

    # --- general ---

    def _build_general_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        form = QtWidgets.QFormLayout()
        self.general_labels = {}
        for name in self.GENERAL_FIELDS:
            label = QtWidgets.QLabel('')
            label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            self.general_labels[name] = label
            form.addRow(name, label)
        row = QtWidgets.QHBoxLayout()
        self.read_info_btn = QtWidgets.QPushButton('Read info')
        self.read_info_btn.setToolTip('Read the info of this device now (norlog info / CoAP /info)')
        self.read_info_btn.clicked.connect(
            lambda: self.device.thread_command('read_device_info', {'targets': [self.key]}))
        self.info_error = QtWidgets.QLabel('')
        self.info_error.setStyleSheet('color: #d64545;')
        self.info_error.setWordWrap(True)
        row.addWidget(self.read_info_btn)
        row.addWidget(self.info_error, 1)
        lay.addLayout(form)
        lay.addLayout(row)
        lay.addWidget(self._build_clock_box())
        lay.addWidget(self._build_props_box())
        lay.addWidget(self._build_battery_box())
        lay.addWidget(self._build_usb_box())
        lay.addWidget(self._build_radio_box())
        lay.addStretch(1)
        return w

    def _build_radio_box(self):
        box = QtWidgets.QGroupBox('Radio (Thread transmit power)')
        grid = QtWidgets.QGridLayout(box)
        self.radio_power = QtWidgets.QSpinBox()
        self.radio_power.setRange(-40, 30)
        self.radio_power.setSuffix(' dBm')
        self.radio_power.setToolTip('Transmit power at the antenna. The firmware splits it into the power of '
                                    'the nRF52840 and the fixed gain of the power amplifier (PA).')
        self.radio_btn = QtWidgets.QPushButton('Set')
        self.radio_btn.setToolTip('Set the transmit power of this device; stored on the device (also after a '
                                  'restart). Needs firmware >= 0.4.5.')
        self.radio_btn.clicked.connect(self.set_radio)
        self.radio_status = QtWidgets.QLabel('')
        self.radio_status.setWordWrap(True)
        self.radio_status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        note = QtWidgets.QLabel('Observe the permitted transmit power of the country. BMD-345 data sheet '
                                '(PA gain 24 dB): CE-RED (EU) at most -16 dBm of the nRF52840, i.e. about 8 dBm '
                                'here; FCC/ISED -8 dBm, i.e. about 16 dBm (channel 26: bypass mode only). A lower '
                                'power of a node can also break its link to the network.')
        note.setWordWrap(True)
        note.setStyleSheet('color: gray;')
        grid.addWidget(QtWidgets.QLabel('At the antenna'), 0, 0)
        grid.addWidget(self.radio_power, 0, 1)
        grid.addWidget(self.radio_btn, 0, 2)
        grid.addWidget(self.radio_status, 0, 3)
        grid.setColumnStretch(3, 1)
        grid.addWidget(note, 1, 0, 1, 4)
        return box

    def set_radio(self):
        dbm = self.radio_power.value()
        radio = ((self.entry or {}).get('info') or {}).get('radio') or {}
        if not self.is_serial() and radio.get('antenna_dbm') is not None and dbm < radio['antenna_dbm']:
            answer = QtWidgets.QMessageBox.question(
                self, 'Transmit power',
                f"Lower the transmit power of this node from {radio['antenna_dbm']} to {dbm} dBm? If its link "
                f"gets too weak, it can no longer be reached over Thread (only over UART).")
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.radio_status.setStyleSheet('')
        self.radio_status.setText('Setting ...')
        self.radio_btn.setEnabled(False)
        self.device.thread_command('radio_set', {'target': self.key, 'dbm': dbm})

    def on_radio_result(self, data):
        self.radio_btn.setEnabled(self.running)
        self.radio_status.setStyleSheet('' if data.get('ok') else 'color: #d64545;')
        self.radio_status.setText(data.get('message', ''))

    def _build_clock_box(self):
        box = QtWidgets.QGroupBox('Clock')
        lay = QtWidgets.QHBoxLayout(box)
        self.clock_btn = QtWidgets.QPushButton('Set clock')
        self.clock_btn.setToolTip('Set the clock of this device to the time of this PC (system clock in ms, '
                                  'RTC in whole seconds), read it back and set it again if it is more than '
                                  '0.5 s off. Needs firmware >= 0.4.4.')
        self.clock_btn.clicked.connect(self.set_clock)
        self.clock_gnss = QtWidgets.QCheckBox('also if the time comes from GNSS')
        self.clock_gnss.setToolTip('Without: a device whose clock was set by GNSS within the last 2 minutes '
                                   'is not changed')
        self.clock_status = QtWidgets.QLabel('')
        self.clock_status.setWordWrap(True)
        self.clock_status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.clock_btn)
        lay.addWidget(self.clock_gnss)
        lay.addWidget(self.clock_status, 1)
        return box

    def set_clock(self):
        self.clock_status.setStyleSheet('')
        self.clock_status.setText('Setting ...')
        self.clock_btn.setEnabled(False)
        self.device.thread_command('set_time', {'targets': [self.key], 'force': self.clock_gnss.isChecked()})

    def on_time_result(self, data):
        self.clock_btn.setEnabled(self.running)
        self.clock_status.setStyleSheet('' if data.get('ok') else 'color: #d64545;')
        self.clock_status.setText(data.get('message', ''))

    def _build_props_box(self):
        box = QtWidgets.QGroupBox('Properties (stored on the device)')
        lay = QtWidgets.QVBoxLayout(box)
        self.props_table = QtWidgets.QTableWidget(0, 2)
        self.props_table.setHorizontalHeaderLabels(['Name', 'Value'])
        self.props_table.horizontalHeader().setStretchLastSection(True)
        self.props_table.verticalHeader().setVisible(False)
        self.props_table.setToolTip('sn: serial number (max. 64 bytes), desc: description, loc: location '
                                    '(max. 256 bytes). Further names: a-z, 0-9, _ (max. 16). '
                                    'An empty value deletes the property.')
        self.props_table.setMaximumHeight(150)
        row = QtWidgets.QHBoxLayout()
        self.props_read_btn = QtWidgets.QPushButton('Read')
        self.props_read_btn.clicked.connect(self.read_props)
        self.props_add_btn = QtWidgets.QPushButton('Add row')
        self.props_add_btn.clicked.connect(lambda: self._props_add_row('', ''))
        self.props_save_btn = QtWidgets.QPushButton('Save')
        self.props_save_btn.clicked.connect(self.save_props)
        self.props_note = QtWidgets.QLabel('')
        self.props_note.setStyleSheet('color: gray;')
        self.props_note.setWordWrap(True)
        for w in (self.props_read_btn, self.props_add_btn, self.props_save_btn):
            row.addWidget(w)
        row.addWidget(self.props_note, 1)
        lay.addWidget(self.props_table)
        lay.addLayout(row)
        self.props_loaded = False
        self.props_device = {}
        self.show_props({})
        return box

    def _props_add_row(self, name, value, name_editable=True):
        r = self.props_table.rowCount()
        self.props_table.insertRow(r)
        item = QtWidgets.QTableWidgetItem(name)
        if not name_editable:
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
        self.props_table.setItem(r, 0, item)
        self.props_table.setItem(r, 1, QtWidgets.QTableWidgetItem(value))
        if name_editable and not name:
            self.props_table.editItem(item)

    def show_props(self, props):
        self.props_device = dict(props)
        self.props_table.setRowCount(0)
        for name in ot_cli.STANDARD_PROPS:
            self._props_add_row(name, props.get(name, ''), name_editable=False)
        for name in sorted(set(props) - set(ot_cli.STANDARD_PROPS)):
            self._props_add_row(name, props[name], name_editable=False)
        self.props_table.resizeColumnToContents(0)

    def read_props(self):
        self.props_note.setText('reading ...')
        self.device.thread_command('props_read', {'target': self.key})

    def save_props(self):
        values = {}
        for r in range(self.props_table.rowCount()):
            name = (self.props_table.item(r, 0).text() if self.props_table.item(r, 0) else '').strip()
            value = (self.props_table.item(r, 1).text() if self.props_table.item(r, 1) else '').strip()
            if not name:
                continue
            if value != self.props_device.get(name, ''):
                try:
                    ot_cli._prop_check(name, value)
                except ValueError as exc:
                    self.props_note.setText(str(exc))
                    return
                values[name] = value
        if not values:
            self.props_note.setText('nothing changed')
            return
        self.props_note.setText(f'saving {", ".join(values)} ...')
        self.device.thread_command('props_set', {'target': self.key, 'values': values})

    def on_props(self, data):
        if data.get('ok'):
            self.props_loaded = True
            self.show_props(data.get('props', {}))
            self.props_note.setText(data.get('message', ''))
        else:
            self.props_note.setText(f"Error: {data.get('message', '')}")

    def _build_battery_box(self):
        box = QtWidgets.QGroupBox('Battery model (state of charge via nRF Fuel Gauge)')
        grid = QtWidgets.QGridLayout(box)
        self.bat_model = QtWidgets.QComboBox()
        self.bat_model.addItems(self.BATTERY_MODELS)
        self.bat_model.setToolTip('Battery model used for the state of charge (stored on the device). '
                                  '"custom" is the model loaded last with "Load .inc ...".')
        self.bat_model.activated.connect(
            lambda i: self.usb_command(f'norlog battery model {self.BATTERY_MODELS[i]}'))
        self.bat_upload = QtWidgets.QPushButton('Load .inc ...')
        self.bat_upload.setToolTip('Load a battery model exported by nPM PowerUP (.inc) into the device; '
                                   'it becomes the model "custom"')
        self.bat_upload.clicked.connect(self.upload_battery_model)
        self.bat_progress = QtWidgets.QProgressBar()
        self.bat_progress.setRange(0, 100)
        self.bat_progress.setVisible(False)
        self.bat_note = QtWidgets.QLabel('')
        self.bat_note.setStyleSheet('color: gray;')
        self.bat_note.setWordWrap(True)
        grid.addWidget(QtWidgets.QLabel('Model'), 0, 0)
        grid.addWidget(self.bat_model, 0, 1)
        grid.addWidget(self.bat_upload, 0, 2)
        grid.addWidget(self.bat_progress, 1, 0, 1, 3)
        grid.addWidget(self.bat_note, 2, 0, 1, 3)
        return box

    def upload_battery_model(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Battery model (nPM PowerUP)', '',
                                                        'Battery models (*.inc);;All files (*)')
        if not path:
            return
        self.bat_progress.setValue(0)
        self.bat_progress.setVisible(True)
        self.bat_note.setText(f'Loading {pathlib.Path(path).name} ...')
        self.device.thread_command('battery_upload', {'path': path})

    def on_battery_upload(self, data):
        if 'progress' in data:
            self.bat_progress.setValue(int(data['progress']))
        if not data.get('ok') or data.get('done'):
            self.bat_progress.setVisible(False)
            self.bat_note.setText(('' if data.get('ok') else 'Error: ') + data.get('message', ''))

    def _build_usb_box(self):
        box = QtWidgets.QGroupBox('USB (SD card as mass storage)')
        grid = QtWidgets.QGridLayout(box)
        self.usb_mode = QtWidgets.QComboBox()
        self.usb_mode.addItems(self.USB_MODES)
        self.usb_mode.setToolTip('auto: a connected computer gets the SD card (logging stops)\n'
                                 'manual: USB only powers/charges, release the card with "SD card to USB"\n'
                                 'off: never mass storage, only power/charging\n'
                                 'Stored on the device (norlog usb mode).')
        self.usb_mode.activated.connect(self.set_usb_mode)
        self.usb_msc_on = QtWidgets.QPushButton('SD card to USB')
        self.usb_msc_on.setToolTip('Stop logging and give the SD card to the connected computer '
                                   '(until "SD card back" or the cable is unplugged)')
        self.usb_msc_on.clicked.connect(lambda: self.usb_command('norlog usb msc on'))
        self.usb_msc_off = QtWidgets.QPushButton('SD card back')
        self.usb_msc_off.setToolTip('Take the SD card back from the computer and continue logging')
        self.usb_msc_off.clicked.connect(lambda: self.usb_command('norlog usb msc off'))
        self.usb_note = QtWidgets.QLabel('')
        self.usb_note.setStyleSheet('color: gray;')
        grid.addWidget(QtWidgets.QLabel('Mode'), 0, 0)
        grid.addWidget(self.usb_mode, 0, 1)
        grid.addWidget(self.usb_msc_on, 0, 2)
        grid.addWidget(self.usb_msc_off, 0, 3)
        grid.addWidget(self.usb_note, 1, 0, 1, 4)
        return box

    def usb_command(self, text):
        # USB settings work over the serial shell only (Thread: no CoAP command yet)
        self.device.thread_command('send', {'text': text})
        self.device.thread_command('read_device_info', {'targets': [self.key]})

    def set_usb_mode(self, index):
        self.usb_command(f'norlog usb mode {self.USB_MODES[index]}')

    @staticmethod
    def _yes_no(d):
        return ', '.join(f"{k}: {v if not isinstance(v, bool) else ('yes' if v else 'no')}"
                         for k, v in (d or {}).items())

    def update_entry(self, entry):
        self.entry = entry
        info = {k: v for k, v in (entry.get('info') or {}).items() if k != 'error'}
        name = entry.get('extaddr') or entry.get('mac') or entry.get('port') or entry.get('id', '')
        self.setWindowTitle(f'norlog settings: {name}'
                            + (f" ({entry['rloc16']})" if entry.get('rloc16') else ''))
        batt = RedvyprDeviceWidget._fmt_battery(entry)
        uptime = info.get('uptime_s')
        values = {
            'Device': name,
            'RLOC16': entry.get('rloc16', ''),
            'Connection': entry.get('connection', '') + (f" ({entry['port']})" if entry.get('port') else ''),
            'Role': entry.get('role', ''),
            'Thread role': entry.get('thread_role', ''),
            'Image': info.get('image', ''),
            'Firmware': info.get('firmware', ''),
            'Build': info.get('build', ''),
            'Board': info.get('board', ''),
            'HW ID': info.get('hwid', ''),
            'Battery': batt,
            'Board temp': self._fmt_temps(info),
            'GNSS': ' - '.join(x for x in (RedvyprDeviceWidget.fmt_gnss(info)[0],
                                           RedvyprDeviceWidget.gnss_position(info),
                                           RedvyprDeviceWidget.fmt_gnss(info)[2].split('\n')[0]) if x),
            'Uptime': '' if uptime is None else f"{uptime // 3600} h {uptime // 60 % 60} min {uptime % 60} s",
            'Clock': ' - '.join(x for x in (info.get('time', ''), RedvyprDeviceWidget._fmt_rtc(info)) if x),
            'Reset cause': str(info.get('reset_cause', '')),
            'Hardware': self._yes_no(info.get('hw')),
            'SD card': self._yes_no(info.get('sd')),
            'USB': self._fmt_usb(info.get('usb')),
            'Thread': self._fmt_thread(info.get('thread')),
            'Battery model': self._fmt_battery_model(info.get('battery')),
            'TX power': self._fmt_radio(info.get('radio')),
            'Log level': str(info.get('log', '')),
            'Info age': '' if entry.get('info_age_s') is None else f"{entry['info_age_s']:.0f} s",
        }
        for k, v in values.items():
            self.general_labels[k].setText(str(v))
        batt = info.get('battery') or {}
        if batt.get('model') in self.BATTERY_MODELS:
            self.bat_model.setCurrentIndex(self.BATTERY_MODELS.index(batt['model']))
        if not self.is_serial():
            self.bat_note.setText('Battery model settings over Thread are not available yet (serial only)')
        elif info and not batt.get('model'):
            self.bat_note.setText('No battery model info (firmware without fuel gauge?)')
        radio = info.get('radio') or {}
        if radio.get('min_dbm') is not None and radio.get('max_dbm') is not None:
            self.radio_power.setRange(int(radio['min_dbm']), int(radio['max_dbm']))
        if radio.get('txpower_dbm') is not None and not self.radio_power.hasFocus():
            self.radio_power.setValue(int(radio['txpower_dbm']))
        usb = info.get('usb') or {}
        if usb.get('mode') in self.USB_MODES:
            self.usb_mode.setCurrentIndex(self.USB_MODES.index(usb['mode']))
        if not self.is_serial():
            self.usb_note.setText('USB settings over Thread are not available yet (serial only)')
        elif not usb:
            self.usb_note.setText('No USB info (firmware without "norlog usb"?)')
        else:
            self.usb_note.setText('')
        self.info_error.setText(f"Last read failed: {entry['info_error']}" if entry.get('info_error') else '')

        if self.is_serial():
            self.fw_method.setText('Serial: the gateway reboots into its loader, upload via MCUmgr (UART).')
            self.fw_flash.setText('Flash device')
        else:
            self.fw_method.setText('Thread: the image is copied to the node\'s SD card (/fw/update.bin, through '
                                   'the gateway\'s SD card if present), then the node installs it with its loader. '
                                   'The node needs an SD card.')
            self.fw_flash.setText('Update over Thread')
        if 'fw_auto' in info:
            self.fw_auto.blockSignals(True)
            self.fw_auto.setChecked(bool(info['fw_auto']))
            self.fw_auto.blockSignals(False)
        self.update_run_state(self.running)

    @staticmethod
    def _fmt_thread(th):
        if not th:
            return ''
        if not th.get('commissioned'):
            return f"not commissioned ({th.get('role', '?')})"
        parts = [f"{th.get('role', '?')}, {th.get('network', '')}, channel {th.get('channel', '?')}"]
        if th.get('panid'):
            parts.append(f"PAN {th['panid']}")
        if 'partition' in th:
            parts.append(f"partition {th['partition']}, leader ID {th.get('leader_id', '?')}")
            parts.append(f"{th.get('neighbors', 0)} neighbor(s), {th.get('children', 0)} child(ren)")
        parent = th.get('parent')
        if parent:
            parts.append(f"parent {parent.get('rloc16', '?')} ({parent.get('rssi', '?')} dBm, "
                         f"LQ {parent.get('lq_in', '?')})")
        return '\n'.join(parts)

    @staticmethod
    def _fmt_battery_model(batt):
        if not batt or not batt.get('model'):
            return ''
        text = batt['model']
        if not batt.get('gauge'):
            text += ' (no fuel gauge result yet, SoC from voltage)'
        elif batt.get('tte_min') is not None:
            text += f", remaining {batt['tte_min'] // 60} h {batt['tte_min'] % 60} min"
        elif batt.get('ttf_min') is not None:
            text += f", full in {batt['ttf_min'] // 60} h {batt['ttf_min'] % 60} min"
        return text

    @staticmethod
    def _fmt_temps(info):
        parts = []
        if info.get('board_temp_c') is not None:
            parts.append(f"{info['board_temp_c']:.2f} \u00b0C (ADC)")
        if info.get('nrf_temp_c') is not None:
            parts.append(f"nRF chip {info['nrf_temp_c']:.2f} \u00b0C")
        warn = RedvyprDeviceWidget.board_temp_warning(info)
        return ', '.join(parts) + (f" - {warn}" if warn else '')

    @staticmethod
    def _fmt_radio(radio):
        if not radio:
            return ''
        text = f"{radio.get('antenna_dbm', '?')} dBm at the antenna"
        details = []
        if radio.get('txpower_dbm') is not None and radio.get('txpower_dbm') != radio.get('antenna_dbm'):
            details.append(f"set {radio['txpower_dbm']} dBm")
        if radio.get('soc_dbm') is not None:
            details.append(f"nRF {radio['soc_dbm']} dBm + PA {radio.get('pa_gain_db', 0)} dB")
        if radio.get('max_dbm') is not None:
            details.append(f"max {radio['max_dbm']} dBm")
        text += f" ({', '.join(details)})" if details else ''
        fem = radio.get('fem')
        if fem:
            # Share of 50 samples (5 ms) with the pin HIGH (firmware >= 0.4.6)
            text += (f"; front end pins HIGH: TX_EN {fem.get('tx')} %, RX_EN {fem.get('rx')} %, "
                     f"MODE {fem.get('mode')} %")
            if RedvyprDeviceWidget.fem_stuck(radio):
                text += ' - PA STUCK IN TRANSMIT MODE?'
        return text

    @staticmethod
    def _fmt_usb(usb):
        if not usb:
            return ''
        return (f"mode {usb.get('mode', '?')}, cable {'connected' if usb.get('vbus') else 'not connected'}, "
                f"SD card {'on USB (logging stopped)' if usb.get('msc') else 'logger'}")

    def update_run_state(self, running):
        self.running = running
        for w in self.mag_run_widgets:
            w.setEnabled(running and not self.mag_recording)
        self.mag_stop_btn.setEnabled(running and self.mag_recording)
        self.mag_update_buttons()
        for w in self.adc_run_widgets:
            w.setEnabled(running and not self.adc_busy)
        for w in self.nmea_run_widgets:
            w.setEnabled(running and not self.nmea_busy)
        self.read_info_btn.setEnabled(running)
        self.clock_btn.setEnabled(running)
        self.radio_btn.setEnabled(running)
        for w in (self.props_read_btn, self.props_add_btn, self.props_save_btn):
            w.setEnabled(running)
        for w in (self.usb_mode, self.usb_msc_on, self.usb_msc_off, self.bat_model, self.bat_upload):
            w.setEnabled(running and self.is_serial())
        self.fw_flash.setEnabled(running)
        # gateway (serial) or Thread member; other serial devices are not reachable by key
        self.loader_install.setEnabled(running and (self.key == 'gateway' or not self.is_serial()))
        self.fw_cancel.setEnabled(running and self.is_serial())
        self.fw_auto.setEnabled(running and self.is_serial())
        for w in self.files_run_widgets:
            w.setEnabled(running)
        self.data_sync_btn.setEnabled(running and not self.data_busy)
        self.data_list_btn.setEnabled(running and not self.data_busy)
        for w in self.data_select_widgets:
            w.setEnabled(not self.data_busy)
        self.data_cancel_btn.setEnabled((running and self.data_busy) or self.convert_worker is not None)

    # --- firmware ---

    # --- ADC measurement sequence (firmware >= 0.4.15; bias and calibrations >= 0.4.16) ---

    ADC_COLS = ['Name', 'p', 'n', 'Gain', 'Ref', 'IDAC µA', 'IDAC1', 'IDAC2', 'Delay ms', 'Bias', 'Value',
                'Calibrated', 'Raw']
    COL_DELAY, COL_BIAS, COL_VALUE, COL_CAL, COL_RAW = 8, 9, 10, 11, 12
    ADC_HINTS = {
        'adc_brd': 'norlog rev02: COM (AINCOM) is GND - measure voltages near 0 V with gain "off" (the PGA needs '
                   'headroom to the supply rails). Floating sensors with small voltages (thermopiles, heat flux '
                   'sensors): differential between two inputs, bias (AVDD/2) on the negative one, high gain. Bias '
                   'is possible at AIN0-5. REF0 is not usable (REFP0 open); an external reference goes to '
                   'REF1 = AIN6 (+) / AIN7 (-). J15 pins 3-12 = AIN0-9, J17 pins 3-14 = AIN0-11, J17 pin 16 = '
                   'REFOUT (2.5 V while the internal reference is used), pin 1 = GND.',
        'adc_hfm': 'hfmeter module at J1: the NTC is connected to AIN5 (IDAC 50 µA, measured separately as ntc '
                   'packet).',
    }

    def _build_adc_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        self.adc_state = {}             # sensor -> last answer of the device (adc_get)
        self.adc_cals = {}              # sensor -> {channel: PolyCalibration} on the device
        self.adc_busy = False
        self.adc_loading = False

        row = QtWidgets.QHBoxLayout()
        self.adc_sensor = QtWidgets.QComboBox()
        self.adc_sensor.addItems(adc_sequence.SENSORS)
        for i, name in enumerate(adc_sequence.SENSORS):
            self.adc_sensor.setItemData(i, adc_sequence.SENSOR_INFO.get(name, ''),
                                        QtCore.Qt.ItemDataRole.ToolTipRole)
        self.adc_sensor.currentTextChanged.connect(self.adc_sensor_changed)
        self.adc_info = QtWidgets.QLabel('- (Read from device)')
        self.adc_info.setWordWrap(True)
        row.addWidget(QtWidgets.QLabel('Sensor'))
        row.addWidget(self.adc_sensor)
        row.addWidget(self.adc_info, 1)
        lay.addLayout(row)

        box = QtWidgets.QGroupBox('Sequence')
        grid = QtWidgets.QGridLayout(box)
        self.adc_on = QtWidgets.QCheckBox('run and store on the SD card')
        self.adc_on.setToolTip('Off: nothing is stored; "Measure once" still works')
        self.adc_sps = QtWidgets.QComboBox()
        self.adc_sps.addItems(adc_sequence.SPS)
        self.adc_filter = QtWidgets.QComboBox()
        self.adc_filter.addItems(adc_sequence.FILTERS)
        self.adc_filter.setToolTip('sinc3: 3 periods per conversion, best noise; ll: low latency, 1 period')
        self.adc_interval = QtWidgets.QDoubleSpinBox()
        self.adc_interval.setRange(0.1, 86400.0)
        self.adc_interval.setDecimals(1)
        self.adc_interval.setValue(10.0)
        self.adc_interval.setSuffix(' s')
        self.adc_on.toggled.connect(self.adc_changed)
        for wdg in (self.adc_sps, self.adc_filter):
            wdg.currentTextChanged.connect(self.adc_changed)
        self.adc_interval.valueChanged.connect(self.adc_changed)
        grid.addWidget(self.adc_on, 0, 0, 1, 2)
        grid.addWidget(QtWidgets.QLabel('Data rate'), 0, 2)
        grid.addWidget(self.adc_sps, 0, 3)
        grid.addWidget(QtWidgets.QLabel('SPS, filter'), 0, 4)
        grid.addWidget(self.adc_filter, 0, 5)
        grid.addWidget(QtWidgets.QLabel('Interval'), 0, 6)
        grid.addWidget(self.adc_interval, 0, 7)
        grid.setColumnStretch(8, 1)

        self.adc_table = QtWidgets.QTableWidget(0, len(self.ADC_COLS))
        self.adc_table.setHorizontalHeaderLabels(self.ADC_COLS)
        self.adc_table.verticalHeader().setDefaultSectionSize(26)
        self.adc_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.adc_table.setMinimumHeight(220)
        self.adc_table.horizontalHeader().setStretchLastSection(True)
        self.adc_table.itemChanged.connect(lambda _item: self.adc_changed())
        self.adc_table.cellDoubleClicked.connect(
            lambda r, c: self.adc_calibrate(r) if c == self.COL_CAL else None)
        tips = ['Channel name: 1-11 characters a-z A-Z 0-9 _, field name in the data',
                'Positive input: AIN0-11, COM or internal: TEMP (chip temperature), AVDD, DVDD (supply), '
                'OFS (inputs shorted)', 'Negative input: AIN0-11 or COM',
                'PGA gain; off = PGA bypassed (inputs may go down to GND)',
                'Reference: INT 2.5 V (value in V) or external REF0/REF1 (value = U_in / U_ref)',
                'Current of the excitation current sources', 'Output of IDAC1', 'Output of IDAC2',
                'Wait after switching (e.g. settling of the IDAC current or the bias)',
                'Input that gets the bias voltage AVDD/2 (AIN0-5, firmware >= 0.4.16): common mode for floating '
                'sensors measured with the PGA', 'Last measured value',
                'Calibrated value (polynomial on the device, firmware >= 0.4.16); double click or "Calibration ..."',
                'Raw value (24 bit)']
        for i, tip in enumerate(tips):
            self.adc_table.horizontalHeaderItem(i).setToolTip(tip)
        grid.addWidget(self.adc_table, 1, 0, 1, 9)

        btns = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton('Add step')
        add_btn.clicked.connect(self.adc_add_step)
        del_btn = QtWidgets.QPushButton('Remove')
        del_btn.clicked.connect(self.adc_remove_step)
        up_btn = QtWidgets.QPushButton('Up')
        up_btn.clicked.connect(lambda: self.adc_move_step(-1))
        down_btn = QtWidgets.QPushButton('Down')
        down_btn.clicked.connect(lambda: self.adc_move_step(1))
        for b_ in (add_btn, del_btn, up_btn, down_btn):
            btns.addWidget(b_)
        btns.addStretch(1)
        self.adc_dur_label = QtWidgets.QLabel('')
        btns.addWidget(self.adc_dur_label)
        grid.addLayout(btns, 2, 0, 1, 9)

        self.adc_text = QtWidgets.QLineEdit()
        self.adc_text.setToolTip('Configuration as text (as "norlog adc set <sensor> <text>" on the shell); '
                                 'edit or paste and press "Use text"')
        text_btn = QtWidgets.QPushButton('Use text')
        text_btn.clicked.connect(self.adc_use_text)
        grid.addWidget(QtWidgets.QLabel('Text'), 3, 0)
        grid.addWidget(self.adc_text, 3, 1, 1, 7)
        grid.addWidget(text_btn, 3, 8)
        lay.addWidget(box)

        row = QtWidgets.QHBoxLayout()
        read_btn = QtWidgets.QPushButton('Read from device')
        read_btn.setToolTip('Read the sequence and the calibrations of its channels')
        read_btn.clicked.connect(lambda: self.adc_command('get'))
        write_btn = QtWidgets.QPushButton('Write to device')
        write_btn.setToolTip('Store the sequence on the device (settings); every change increases the '
                             'configuration number')
        write_btn.clicked.connect(self.adc_write)
        measure_btn = QtWidgets.QPushButton('Measure once')
        measure_btn.setToolTip('Run the sequence stored on the device once and show the values (not stored)')
        measure_btn.clicked.connect(lambda: self.adc_command('read'))
        cal_btn = QtWidgets.QPushButton('Calibration ...')
        cal_btn.setToolTip('Polynomial calibration of the selected channel, stored and applied on the device '
                           '(firmware >= 0.4.16)')
        cal_btn.clicked.connect(lambda: self.adc_calibrate(self.adc_table.currentRow()))
        for b_ in (read_btn, write_btn, measure_btn, cal_btn):
            row.addWidget(b_)
        row.addStretch(1)
        lay.addLayout(row)
        self.adc_status = QtWidgets.QLabel('')
        self.adc_status.setWordWrap(True)
        self.adc_status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.adc_status)
        self.adc_hint = QtWidgets.QLabel('')
        self.adc_hint.setWordWrap(True)
        self.adc_hint.setStyleSheet('color: gray;')
        lay.addWidget(self.adc_hint)
        lay.addStretch(1)
        self.adc_run_widgets = [read_btn, write_btn, measure_btn, cal_btn]
        self.adc_sensor_changed(self.adc_sensor.currentText())
        return w

    def _adc_combo(self, items, value):
        cb = QtWidgets.QComboBox()
        cb.addItems(items)
        if value in items:
            cb.setCurrentText(value)
        cb.currentTextChanged.connect(lambda _t: self.adc_changed())
        return cb

    def _adc_set_row(self, r, st, value='', cal='', raw=''):
        t = self.adc_table
        t.setItem(r, 0, QtWidgets.QTableWidgetItem(st.name))
        t.setCellWidget(r, 1, self._adc_combo(adc_sequence.P_INPUTS, st.p))
        t.setCellWidget(r, 2, self._adc_combo(adc_sequence.INPUTS, st.n if st.n != '-' else 'COM'))
        t.setCellWidget(r, 3, self._adc_combo(adc_sequence.GAINS, st.gain))
        t.setCellWidget(r, 4, self._adc_combo(adc_sequence.REFS, st.ref))
        t.setCellWidget(r, 5, self._adc_combo([str(v) for v in adc_sequence.IDAC_UA], str(st.idac_ua)))
        t.setCellWidget(r, 6, self._adc_combo(adc_sequence.IDAC_PINS, st.i1))
        t.setCellWidget(r, 7, self._adc_combo(adc_sequence.IDAC_PINS, st.i2))
        delay = QtWidgets.QSpinBox()
        delay.setRange(0, 2000)
        delay.setValue(st.delay_ms)
        delay.valueChanged.connect(lambda _v: self.adc_changed())
        t.setCellWidget(r, self.COL_DELAY, delay)
        t.setCellWidget(r, self.COL_BIAS, self._adc_combo(adc_sequence.BIAS_PINS, st.bias))
        for col, text in ((self.COL_VALUE, value), (self.COL_CAL, cal), (self.COL_RAW, raw)):
            item = QtWidgets.QTableWidgetItem(text)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            t.setItem(r, col, item)

    def _adc_row_step(self, r):
        t = self.adc_table
        item = t.item(r, 0)
        st = adc_sequence.AdcStep(name=item.text().strip() if item else '')
        st.p = t.cellWidget(r, 1).currentText()
        st.n = t.cellWidget(r, 2).currentText()
        st.gain = t.cellWidget(r, 3).currentText()
        st.ref = t.cellWidget(r, 4).currentText()
        st.idac_ua = int(t.cellWidget(r, 5).currentText())
        st.i1 = t.cellWidget(r, 6).currentText()
        st.i2 = t.cellWidget(r, 7).currentText()
        st.delay_ms = t.cellWidget(r, self.COL_DELAY).value()
        st.bias = t.cellWidget(r, self.COL_BIAS).currentText()
        if st.internal:
            st.n = '-'
            st.bias = '-'
        return st

    def adc_sequence_from_gui(self):
        return adc_sequence.AdcSequence(on=self.adc_on.isChecked(), sps=self.adc_sps.currentText(),
                                        filter=self.adc_filter.currentText(),
                                        interval_ms=int(round(self.adc_interval.value() * 1000)),
                                        steps=[self._adc_row_step(r) for r in range(self.adc_table.rowCount())])

    def adc_show_sequence(self, seq, values=None):
        """Fill the table; values: {name: (value text, calibrated text, raw text)}."""
        values = values or {}
        self.adc_loading = True
        try:
            self.adc_on.setChecked(seq.on)
            self.adc_sps.setCurrentText(seq.sps)
            self.adc_filter.setCurrentText(seq.filter)
            self.adc_interval.setValue(seq.interval_ms / 1000.0)
            self.adc_table.setRowCount(len(seq.steps))
            for r, st in enumerate(seq.steps):
                self._adc_set_row(r, st, *values.get(st.name, ('', '', '')))
            self.adc_show_calibrations()
            self.adc_table.resizeColumnsToContents()
        finally:
            self.adc_loading = False
        self.adc_changed()

    def adc_show_calibrations(self):
        """Tooltips of the 'Calibrated' cells, unit for channels with a calibration but no value yet."""
        cals = self.adc_cals.get(self.adc_sensor.currentText(), {})
        loading, self.adc_loading = self.adc_loading, True
        for r in range(self.adc_table.rowCount()):
            name = self.adc_table.item(r, 0).text() if self.adc_table.item(r, 0) else ''
            item = self.adc_table.item(r, self.COL_CAL)
            if item is None:
                continue
            cal = cals.get(name)
            item.setToolTip(cal.summary() + (f' ({cal.id})' if cal.id else '') if cal
                            else 'no calibration (double click to add one)')
            if cal and not item.text():
                item.setText(f'[{cal.unit}]')
            elif not cal and item.text().startswith('['):
                item.setText('')
        self.adc_loading = loading

    def adc_changed(self, *_args):
        if self.adc_loading:
            return
        t = self.adc_table
        for r in range(t.rowCount()):
            if t.cellWidget(r, 1) is None:
                continue
            internal = t.cellWidget(r, 1).currentText() in adc_sequence.INTERNAL
            idac = t.cellWidget(r, 5).currentText() != '0'
            for col in range(2, self.COL_BIAS + 1):
                t.cellWidget(r, col).setEnabled(not internal and (col not in (6, 7) or idac))
        seq = self.adc_sequence_from_gui()
        text = seq.to_text()
        if self.adc_text.text() != text:
            self.adc_text.setText(text)
        dur = seq.duration_ms()
        self.adc_dur_label.setText(f'one run approx. {dur / 1000:.2f} s'
                                   + (' - longer than the interval, runs without pause'
                                      if seq.steps and dur > seq.interval_ms else ''))
        device = self.adc_state.get(self.adc_sensor.currentText())
        try:
            canonical = adc_sequence.parse(text).to_text()
            error = ''
        except adc_sequence.SequenceError as exc:
            canonical, error = None, str(exc)
        if error:
            self.adc_status.setStyleSheet('color: #d64545;')
            self.adc_status.setText(f'invalid: {error}')
        elif device is not None and canonical != device.get('cfg'):
            self.adc_status.setStyleSheet('color: #c08000;')
            self.adc_status.setText('changed - not yet written to the device')
        elif device is not None:
            self.adc_status.setStyleSheet('')
            self.adc_status.setText('same as on the device')

    def adc_add_step(self):
        names = {self._adc_row_step(r).name for r in range(self.adc_table.rowCount())}
        i = 0
        while f'ch{i}' in names:
            i += 1
        if self.adc_table.rowCount() >= adc_sequence.MAX_STEPS:
            return
        r = self.adc_table.rowCount()
        self.adc_loading = True
        self.adc_table.insertRow(r)
        self._adc_set_row(r, adc_sequence.AdcStep(name=f'ch{i}', p=str(min(r, 11)), n='COM', gain='off'))
        self.adc_loading = False
        self.adc_changed()

    def adc_remove_step(self):
        rows = sorted({i.row() for i in self.adc_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.adc_table.removeRow(r)
        self.adc_changed()

    def adc_move_step(self, delta):
        r = self.adc_table.currentRow()
        seq = self.adc_sequence_from_gui()
        if not 0 <= r < len(seq.steps) or not 0 <= r + delta < len(seq.steps):
            return
        seq.steps[r], seq.steps[r + delta] = seq.steps[r + delta], seq.steps[r]
        self.adc_show_sequence(seq, self._adc_table_values())
        self.adc_table.selectRow(r + delta)

    def _adc_table_values(self):
        t = self.adc_table

        def text(r, c):
            return t.item(r, c).text() if t.item(r, c) else ''
        return {self._adc_row_step(r).name: (text(r, self.COL_VALUE), text(r, self.COL_CAL), text(r, self.COL_RAW))
                for r in range(t.rowCount())}

    def adc_use_text(self):
        try:
            seq = adc_sequence.parse(self.adc_text.text(), base=self.adc_sequence_from_gui())
        except adc_sequence.SequenceError as exc:
            self.adc_status.setStyleSheet('color: #d64545;')
            self.adc_status.setText(f'invalid: {exc}')
            return
        self.adc_show_sequence(seq, self._adc_table_values())

    def adc_sensor_changed(self, sensor):
        self.adc_hint.setText(self.ADC_HINTS.get(sensor, ''))
        st = self.adc_state.get(sensor)
        if st is not None:
            self.adc_show_device(st)
        else:
            self.adc_info.setText('- (Read from device)')
            self.adc_show_sequence(adc_sequence.AdcSequence())
            self.adc_status.setText('')

    def adc_command(self, op, text='', channel=''):
        self.adc_busy = True
        self.update_run_state(self.running)
        self.adc_status.setStyleSheet('')
        self.adc_status.setText({'get': 'reading ...', 'set': 'writing ...', 'read': 'measuring ...',
                                 'cal_set': 'storing the calibration ...'}[op])
        self.device.thread_command(f'adc_{op}', {'target': self.key, 'sensor': self.adc_sensor.currentText(),
                                                 'text': text, 'channel': channel})

    def adc_write(self):
        seq = self.adc_sequence_from_gui()
        try:
            text = seq.validate()
        except adc_sequence.SequenceError as exc:
            self.adc_status.setStyleSheet('color: #d64545;')
            self.adc_status.setText(f'invalid: {exc}')
            return
        if not seq.steps and seq.on:
            self.adc_status.setStyleSheet('color: #d64545;')
            self.adc_status.setText('add at least one step')
            return
        self.adc_command('set', text)

    def _adc_last_value(self, name):
        """(value, unit) of the last measurement of a channel on the device, or (None, unit)."""
        st = self.adc_state.get(self.adc_sensor.currentText()) or {}
        try:
            seq = adc_sequence.parse(st.get('cfg', ''))
        except adc_sequence.SequenceError:
            return None, ''
        last = st.get('last') or {}
        for i, step in enumerate(seq.steps):
            if step.name == name:
                vals = last.get('val') or []
                ok = last.get('cfg_id') == st.get('cfg_id') and i < len(vals) and not last.get('err', 0) & (1 << i)
                return (vals[i] if ok else None), step.unit()
        return None, ''

    def adc_calibrate(self, row):
        if not 0 <= row < self.adc_table.rowCount():
            self.adc_status.setStyleSheet('color: #d64545;')
            self.adc_status.setText('select a channel (row) first')
            return
        step = self._adc_row_step(row)
        sensor = self.adc_sensor.currentText()
        x, x_unit = self._adc_last_value(step.name)
        dlg = AdcCalibrationDialog(self, poly_calibration.cal_name(sensor, step.name), x_unit or step.unit(),
                                   self.adc_cals.get(sensor, {}).get(step.name), x)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        if dlg.delete_requested:
            self.adc_command('cal_set', '', step.name)
        else:
            self.adc_command('cal_set', dlg.calibration.to_text(), step.name)

    @staticmethod
    def _adc_fmt_value(value, unit, err=False, ovr=False):
        if err:
            return 'error'
        if value is None:
            return '-'
        unit = {'degC': '°C', '1': ''}.get(unit, unit)
        text = f'{value:.7g} {unit}'.strip()
        return text + (' OVERRANGE' if ovr else '')

    def adc_show_device(self, st, table=True):
        """
        Show the answer of the device: state, last values and (table=True) its configuration.
        table=False: only the values of the steps with the same name (unsaved changes stay).
        """
        try:
            seq = adc_sequence.parse(st.get('cfg', ''))
        except adc_sequence.SequenceError as exc:
            self.adc_status.setStyleSheet('color: #d64545;')
            self.adc_status.setText(f"configuration of the device not readable: {exc}")
            return
        values = {}
        last = st.get('last') or {}
        cals = self.adc_cals.get(st.get('sensor', self.adc_sensor.currentText()), {})
        if last and last.get('cfg_id') == st.get('cfg_id'):
            vals, raws, cvals = last.get('val') or [], last.get('raw') or [], last.get('cal') or []
            for i, step in enumerate(seq.steps):
                if i < len(vals):
                    err = bool(last.get('err', 0) & (1 << i))
                    ovr = bool(last.get('ovr', 0) & (1 << i))
                    cal = cals.get(step.name)
                    cval = cvals[i] if i < len(cvals) else None
                    values[step.name] = (self._adc_fmt_value(vals[i], step.unit(), err, ovr),
                                         self._adc_fmt_value(cval, cal.unit, err)
                                         if cval is not None and cal is not None else '',
                                         str(raws[i]) if i < len(raws) and not err else '')
        if table:
            self.adc_show_sequence(seq, values)
        else:
            self.adc_loading = True
            for r in range(self.adc_table.rowCount()):
                item = self.adc_table.item(r, 0)
                for col, text in zip((self.COL_VALUE, self.COL_CAL, self.COL_RAW),
                                     values.get(item.text() if item else '', ('', '', ''))):
                    self.adc_table.item(r, col).setText(text)
            self.adc_show_calibrations()
            self.adc_loading = False
            self.adc_changed()
        age = f", last run {last.get('age_ms', 0) / 1000:.0f} s ago" if last else ''
        ncal = len(cals)
        self.adc_info.setText(f"{'found' if st.get('present') else 'NOT FOUND'}, sequence "
                              f"{'on' if st.get('on') else 'off'}, configuration {st.get('cfg_id')}, "
                              f"{st.get('runs', 0)} runs{age}" + (f", {ncal} calibrated" if ncal else ''))

    def adc_unsaved(self):
        """True if the table differs from the configuration last read from the device."""
        device = self.adc_state.get(self.adc_sensor.currentText())
        if device is None:
            return False
        try:
            return adc_sequence.parse(self.adc_sequence_from_gui().to_text()).to_text() != device.get('cfg')
        except adc_sequence.SequenceError:
            return True

    def on_adc_message(self, data):
        self.adc_busy = False
        self.update_run_state(self.running)
        if not data.get('ok'):
            if data.get('sensor') == self.adc_sensor.currentText():
                self.adc_status.setStyleSheet('color: #d64545;')
                self.adc_status.setText(data.get('message', 'error'))
            return
        sensor = data['sensor']
        current = sensor == self.adc_sensor.currentText()
        keep_table = current and data.get('op') in ('read', 'cal_set') and self.adc_unsaved()
        if 'cals' in data:
            self.adc_cals[sensor] = {ch: poly_calibration.PolyCalibration.from_device(d)
                                     for ch, d in (data.get('cals') or {}).items()}
        self.adc_state[sensor] = data['adc']
        if current:
            self.adc_show_device(data['adc'], table=not keep_table)
            message = data.get('message', '')
            if data.get('cal_message'):
                message = (message + '; ' if message else '') + data['cal_message']
            if keep_table:
                self.adc_status.setStyleSheet('color: #c08000;')
                self.adc_status.setText((message + ' - ' if message else '') +
                                        'the changes in the table are not yet written')
            elif message:
                self.adc_status.setStyleSheet('')
                self.adc_status.setText(message)

    # --- NMEA sensor at UART1, e.g. a wind meter (status firmware >= 0.4.13, settings >= 0.4.21) ---

    def _build_nmea_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        self.nmea_busy = False
        self.nmea_device = None         # last answer of the device (nmea_get)

        box = QtWidgets.QGroupBox('Settings (stored on the device)')
        grid = QtWidgets.QGridLayout(box)
        self.nmea_on = QtWidgets.QCheckBox('receive at UART1 (RX: J1 pin 16 / J10 pin 4)')
        self.nmea_on.setToolTip('The receiver keeps the high frequency clock of the nRF52840 running '
                                '(about 0.5-1 mA). Every $xxMWV sentence is stored as wind packet on the SD card.')
        self.nmea_baud = QtWidgets.QComboBox()
        self.nmea_baud.setEditable(True)
        self.nmea_baud.addItems(['auto'] + [str(b) for b in ot_cli.NMEA_BAUDS])
        self.nmea_baud.setToolTip('auto: without a valid sentence the next of '
                                  + ', '.join(str(b) for b in ot_cli.NMEA_BAUDS) + ' baud is tried every 4 s')
        self.nmea_raw = QtWidgets.QCheckBox('store every sentence as raw packet on the SD card')
        self.nmea_raw.setToolTip('For diagnosis or sentences the norlog does not decode; '
                                 'about twice the amount of data')
        grid.addWidget(self.nmea_on, 0, 0, 1, 3)
        grid.addWidget(QtWidgets.QLabel('Baud rate'), 1, 0)
        grid.addWidget(self.nmea_baud, 1, 1)
        grid.addWidget(self.nmea_raw, 2, 0, 1, 3)
        grid.setColumnStretch(2, 1)
        lay.addWidget(box)

        box = QtWidgets.QGroupBox('Status')
        form = QtWidgets.QFormLayout(box)
        self.nmea_labels = {}
        for name in ('State', 'Sentences', 'Wind', 'Last sentence'):
            label = QtWidgets.QLabel('-')
            label.setWordWrap(True)
            label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(name, label)
            self.nmea_labels[name] = label
        self.nmea_labels['Last sentence'].setFont(QtGui.QFontDatabase.systemFont(
            QtGui.QFontDatabase.SystemFont.FixedFont))
        lay.addWidget(box)

        row = QtWidgets.QHBoxLayout()
        read_btn = QtWidgets.QPushButton('Read from device')
        read_btn.clicked.connect(lambda: self.nmea_command('get'))
        write_btn = QtWidgets.QPushButton('Write to device')
        write_btn.setToolTip('Store the settings on the device, effective at once (firmware >= 0.4.21)')
        write_btn.clicked.connect(self.nmea_write)
        self.nmea_auto = QtWidgets.QCheckBox('refresh every 2 s')
        self.nmea_auto.setToolTip('Read the status repeatedly (over Thread one CoAP request every 2 s)')
        self.nmea_timer = QtCore.QTimer(self)
        self.nmea_timer.setInterval(2000)
        self.nmea_timer.timeout.connect(self.nmea_refresh)
        self.nmea_auto.toggled.connect(lambda on: self.nmea_timer.start() if on else self.nmea_timer.stop())
        self.finished.connect(lambda _r: self.nmea_timer.stop())
        for b_ in (read_btn, write_btn, self.nmea_auto):
            row.addWidget(b_)
        row.addStretch(1)
        lay.addLayout(row)
        self.nmea_status = QtWidgets.QLabel('')
        self.nmea_status.setWordWrap(True)
        self.nmea_status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.nmea_status)
        hint = QtWidgets.QLabel('Shell of the device: "norlog nmea" (status), "norlog nmea monitor" (sentences '
                                'live, firmware >= 0.4.19). Wind packets: wind_dir [deg], wind_speed [m/s], '
                                'wind_ref (0 relative, 1 true), wind_valid.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: gray;')
        lay.addWidget(hint)
        lay.addStretch(1)
        self.nmea_run_widgets = [read_btn, write_btn, self.nmea_auto]
        return w

    def nmea_command(self, op, values=None):
        self.nmea_busy = True
        self.update_run_state(self.running)
        if op == 'set':
            self.nmea_status.setStyleSheet('')
            self.nmea_status.setText('writing ...')
        self.device.thread_command(f'nmea_{op}', {'target': self.key, 'values': values or {}})

    def nmea_refresh(self):
        if self.running and not self.nmea_busy:
            self.nmea_command('get')

    def nmea_write(self):
        baud = self.nmea_baud.currentText().strip().lower()
        try:
            values = {'on': self.nmea_on.isChecked(), 'raw': self.nmea_raw.isChecked(),
                      'baud': 'auto' if baud in ('auto', '0', '') else int(baud)}
            ot_cli.nmea_settings_text(**values)
        except ValueError:
            self.nmea_status.setStyleSheet('color: #d64545;')
            self.nmea_status.setText('baud rate: auto or 1200..1000000')
            return
        self.nmea_command('set', values)

    def nmea_show_device(self, st, settings=True):
        """Show the status of the device; settings=True also takes over its settings into the controls."""
        if settings:
            self.nmea_on.setChecked(bool(st.get('on')))
            self.nmea_raw.setChecked(bool(st.get('raw')))
            self.nmea_baud.setCurrentText('auto' if st.get('auto', True) else str(st.get('baud', '')))
        on = bool(st.get('on'))
        self.nmea_labels['State'].setText(
            f"{'on' if on else 'off'}, {st.get('baud', '?')} baud "
            f"({'automatic' if st.get('auto', True) else 'fixed'}), raw packets {'on' if st.get('raw') else 'off'}")
        age = st.get('age_ms', -1)
        self.nmea_labels['Sentences'].setText(
            f"{st.get('ok', 0)} valid, {st.get('err', 0)} checksum wrong"
            + (f", last {age / 1000:.1f} s ago" if age is not None and age >= 0 else ', none yet'))
        wind = st.get('wind')
        if wind:
            ref = 'true' if wind.get('ref') == 'T' else 'relative'
            self.nmea_labels['Wind'].setText(
                f"{wind.get('dir', 0):.1f}° ({ref}), {wind.get('spd', 0):.2f} m/s"
                f"{'' if wind.get('ok', True) else ', INVALID'}, {wind.get('age_ms', 0) / 1000:.1f} s ago")
        else:
            self.nmea_labels['Wind'].setText('- (no MWV sentence yet)')
        self.nmea_labels['Last sentence'].setText(st.get('last') or '-')

    def nmea_unsaved(self):
        st = self.nmea_device
        if st is None:
            return False
        baud = self.nmea_baud.currentText().strip().lower()
        device_baud = 'auto' if st.get('auto', True) else str(st.get('baud'))
        return (self.nmea_on.isChecked() != bool(st.get('on')) or self.nmea_raw.isChecked() != bool(st.get('raw'))
                or (baud or 'auto') != device_baud)

    def on_nmea_message(self, data):
        self.nmea_busy = False
        self.update_run_state(self.running)
        if not data.get('ok'):
            self.nmea_status.setStyleSheet('color: #d64545;')
            self.nmea_status.setText(data.get('message', 'error'))
            return
        # Refreshing keeps settings the user is editing; reading or writing takes over the device's
        keep = data.get('op') == 'get' and self.nmea_auto.isChecked() and self.nmea_unsaved()
        self.nmea_device = data['nmea']
        self.nmea_show_device(data['nmea'], settings=not keep)
        if keep:
            self.nmea_status.setStyleSheet('color: #c08000;')
            self.nmea_status.setText('the changed settings are not yet written')
        elif data.get('message') or not self.nmea_auto.isChecked():
            self.nmea_status.setStyleSheet('')
            self.nmea_status.setText(data.get('message', ''))

    # --- magnetometer: measurement and calibration (firmware >= 0.4.12) ---

    MAG_PLANES = (('x', 'y', 0, 1), ('x', 'z', 0, 2), ('y', 'z', 1, 2))

    def _build_mag_tab(self):
        import pyqtgraph
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        self.mag_points = []            # recorded points (µT)
        self.mag_fit = None             # MagCalibration of the last fit
        self.mag_device_cal = None      # calibration on the device
        self.mag_recording = False
        self.mag_run_widgets = []

        box = QtWidgets.QGroupBox('On the device')
        grid = QtWidgets.QGridLayout(box)
        self.mag_cal_label = QtWidgets.QLabel('calibration: - (Read)')
        self.mag_cal_label.setWordWrap(True)
        self.mag_cal_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.mag_value_label = QtWidgets.QLabel('field: -')
        self.mag_value_label.setWordWrap(True)
        self.mag_value_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        read_btn = QtWidgets.QPushButton('Read')
        read_btn.setToolTip('Read the calibration and the last measurement of the device (firmware >= 0.4.12)')
        read_btn.clicked.connect(self.mag_read_device)
        del_btn = QtWidgets.QPushButton('Delete calibration')
        del_btn.clicked.connect(self.mag_delete_calibration)
        grid.addWidget(self.mag_cal_label, 0, 0, 1, 3)
        grid.addWidget(self.mag_value_label, 1, 0, 1, 3)
        grid.addWidget(read_btn, 2, 0)
        grid.addWidget(del_btn, 2, 1)
        grid.setColumnStretch(2, 1)
        lay.addWidget(box)

        box = QtWidgets.QGroupBox('Calibrate (hard and soft iron)')
        grid = QtWidgets.QGridLayout(box)
        note = QtWidgets.QLabel('Mount the device as it will be used (battery, housing). Start the recording and turn '
                                'the device slowly in all directions (all sides up, rotate around every axis) until '
                                'all directions are covered. Keep away from iron, magnets and cables with current.')
        note.setWordWrap(True)
        note.setStyleSheet('color: gray;')
        self.mag_dur = QtWidgets.QSpinBox()
        self.mag_dur.setRange(10, 120)
        self.mag_dur.setValue(60)
        self.mag_dur.setSuffix(' s')
        self.mag_hz = QtWidgets.QSpinBox()
        self.mag_hz.setRange(1, 20)
        self.mag_hz.setValue(10)
        self.mag_hz.setSuffix(' Hz')
        self.mag_start_btn = QtWidgets.QPushButton('Start recording')
        self.mag_start_btn.clicked.connect(self.mag_start_recording)
        self.mag_stop_btn = QtWidgets.QPushButton('Stop')
        self.mag_stop_btn.setEnabled(False)
        self.mag_stop_btn.clicked.connect(lambda: self.device.thread_command('mag_cal_stop', {}))
        self.mag_progress = QtWidgets.QProgressBar()
        self.mag_progress.setRange(0, 100)
        self.mag_status = QtWidgets.QLabel('')
        self.mag_status.setWordWrap(True)
        self.mag_kind = QtWidgets.QComboBox()
        self.mag_kind.addItems(['auto', 'ellipsoid', 'sphere'])
        self.mag_kind.setToolTip('auto: hard and soft iron (ellipsoid) if enough directions are covered, otherwise '
                                 'hard iron only (sphere)')
        self.mag_fit_btn = QtWidgets.QPushButton('Fit')
        self.mag_fit_btn.clicked.connect(self.mag_do_fit)
        self.mag_apply_btn = QtWidgets.QPushButton('Apply to device')
        self.mag_apply_btn.setEnabled(False)
        self.mag_apply_btn.clicked.connect(self.mag_apply)
        save_btn = QtWidgets.QPushButton('Save points ...')
        save_btn.clicked.connect(self.mag_save_points)
        load_btn = QtWidgets.QPushButton('Load points ...')
        load_btn.clicked.connect(self.mag_load_points)
        self.mag_fit_label = QtWidgets.QLabel('')
        self.mag_fit_label.setWordWrap(True)
        self.mag_fit_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(note, 0, 0, 1, 6)
        grid.addWidget(QtWidgets.QLabel('Duration'), 1, 0)
        grid.addWidget(self.mag_dur, 1, 1)
        grid.addWidget(QtWidgets.QLabel('Rate'), 1, 2)
        grid.addWidget(self.mag_hz, 1, 3)
        grid.addWidget(self.mag_start_btn, 1, 4)
        grid.addWidget(self.mag_stop_btn, 1, 5)
        grid.addWidget(self.mag_progress, 2, 0, 1, 6)
        grid.addWidget(self.mag_status, 3, 0, 1, 6)
        grid.addWidget(QtWidgets.QLabel('Fit'), 4, 0)
        grid.addWidget(self.mag_kind, 4, 1)
        grid.addWidget(self.mag_fit_btn, 4, 2)
        grid.addWidget(self.mag_apply_btn, 4, 3)
        grid.addWidget(save_btn, 4, 4)
        grid.addWidget(load_btn, 4, 5)
        grid.addWidget(self.mag_fit_label, 5, 0, 1, 6)
        lay.addWidget(box)

        plots = QtWidgets.QHBoxLayout()
        self.mag_plots = []
        for a, b, _i, _j in self.MAG_PLANES:
            pw = pyqtgraph.PlotWidget()
            pw.setBackground('w')
            pw.setAspectLocked(True)
            pw.showGrid(x=True, y=True, alpha=0.3)
            pw.setLabel('bottom', f'{a} [µT]')
            pw.setLabel('left', f'{b} [µT]')
            pw.setMinimumHeight(220)
            raw = pyqtgraph.ScatterPlotItem(size=4, pen=None, brush=pyqtgraph.mkBrush(150, 150, 150, 160))
            cal = pyqtgraph.ScatterPlotItem(size=4, pen=None, brush=pyqtgraph.mkBrush(30, 100, 220, 200))
            circle = pyqtgraph.PlotDataItem(pen=pyqtgraph.mkPen((220, 60, 60), width=1.5))
            for item in (raw, cal, circle):
                pw.addItem(item)
            self.mag_plots.append((raw, cal, circle))
            plots.addWidget(pw)
        lay.addLayout(plots)
        legend = QtWidgets.QLabel('gray: recorded (raw), blue: calibrated, red: sphere of the calibration')
        legend.setStyleSheet('color: gray;')
        lay.addWidget(legend)
        self.mag_run_widgets = [read_btn, del_btn, self.mag_start_btn, self.mag_dur, self.mag_hz]
        self.mag_update_buttons()
        return w

    def mag_update_buttons(self):
        self.mag_fit_btn.setEnabled(len(self.mag_points) >= mag_calibration.MIN_POINTS and not self.mag_recording)
        self.mag_apply_btn.setEnabled(self.running and self.mag_fit is not None and not self.mag_recording)

    def mag_read_device(self):
        self.device.thread_command('cal_get', {'target': self.key})
        self.device.thread_command('mag_read', {'target': self.key})

    def mag_delete_calibration(self):
        answer = QtWidgets.QMessageBox.question(self, 'Delete calibration',
                                                'Delete the magnetometer calibration on the device? The device then '
                                                'stores the raw field only.')
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self.device.thread_command('cal_set', {'target': self.key, 'name': 'mag', 'text': ''})

    def mag_start_recording(self):
        self.mag_points = []
        self.mag_fit = None
        self.mag_recording = True
        self.mag_progress.setValue(0)
        self.mag_status.setStyleSheet('')
        self.mag_status.setText('Starting ... turn the device slowly in all directions')
        self.mag_fit_label.setText('')
        self.mag_plot()
        self.update_run_state(self.running)
        self.mag_update_buttons()
        self.device.thread_command('mag_cal', {'target': self.key, 'dur': self.mag_dur.value(),
                                               'hz': self.mag_hz.value()})

    def on_mag_message(self, packetid, data):
        if packetid == 'mag_result':
            if data.get('ok'):
                m = data['mag']
                text = f"field raw: x {m['x']:.2f}, y {m['y']:.2f}, z {m['z']:.2f} µT"
                if 'xc' in m:
                    text += f"; calibrated: x {m['xc']:.2f}, y {m['yc']:.2f}, z {m['zc']:.2f} µT"
                text += f"; |B| {m.get('b', 0):.2f} µT, heading {m.get('heading', 0):.1f}° (only level)"
                self.mag_value_label.setText(text)
            else:
                self.mag_value_label.setText(f"field: {data.get('message', '')}")
        elif packetid == 'cal_result':
            if data.get('ok'):
                self.mag_device_cal = mag_calibration.MagCalibration.from_device((data.get('cal') or {}).get('mag'))
                self.mag_cal_label.setText('calibration: ' + (self.mag_device_cal.summary() if self.mag_device_cal
                                                              else 'none (raw field)'))
                if data.get('message'):
                    self.mag_status.setStyleSheet('')
                    self.mag_status.setText(data['message'])
            else:
                self.mag_cal_label.setText(f"calibration: {data.get('message', '')}")
        elif packetid == 'mag_cal_progress':
            self.mag_points.extend(tuple(p) for p in data.get('new', []))
            total = data.get('total') or 1
            self.mag_progress.setValue(int(100 * len(self.mag_points) / total))
            self.mag_status.setText(f"{len(self.mag_points)} of {total} values, {self.mag_coverage_text()}"
                                    + (" - keep turning" if len(self.mag_points) < total else ""))
            self.mag_plot()
        elif packetid == 'mag_cal_done':
            self.mag_recording = False
            if data.get('points') and len(data['points']) >= len(self.mag_points):
                self.mag_points = [tuple(p) for p in data['points']]
            self.mag_progress.setValue(100 if data.get('ok') else self.mag_progress.value())
            self.mag_status.setStyleSheet('' if data.get('ok') else 'color: #d64545;')
            self.mag_status.setText(f"{data.get('message', '')}; {self.mag_coverage_text()}")
            self.update_run_state(self.running)
            self.mag_update_buttons()
            if len(self.mag_points) >= mag_calibration.MIN_POINTS:
                self.mag_do_fit()
            else:
                self.mag_plot()

    def mag_coverage_text(self):
        import numpy as np
        if len(self.mag_points) < mag_calibration.MIN_POINTS:
            return 'coverage: -'
        try:
            center, _r = mag_calibration.fit_sphere(np.array(self.mag_points))
            return f'coverage {mag_calibration.coverage(self.mag_points, center)} of 26 directions'
        except (mag_calibration.CalibrationError, np.linalg.LinAlgError):
            return 'coverage: -'

    def mag_do_fit(self):
        import numpy as np
        try:
            self.mag_fit = mag_calibration.fit(np.array(self.mag_points), kind=self.mag_kind.currentText())
            self.mag_fit.id = f"redvypr {datetime.datetime.now():%Y%m%d}"
            f = self.mag_fit
            what = 'hard and soft iron (ellipsoid)' if f.kind == 'ellipsoid' else 'hard iron only (sphere)'
            self.mag_fit_label.setStyleSheet('')
            self.mag_fit_label.setText(
                f"Fit: {what}, {f.n} values, {f.coverage} of 26 directions\n"
                f"hard iron b = {f.b[0]:.2f}, {f.b[1]:.2f}, {f.b[2]:.2f} µT; field {f.field_ut:.2f} µT "
                f"(earth field about 25-65 µT, Germany about 49 µT); residual {f.rms_ut:.2f} µT\n"
                f"A = {np.array2string(f.A, precision=4, suppress_small=True).replace(chr(10), ' ')}")
        except (mag_calibration.CalibrationError, np.linalg.LinAlgError) as exc:
            self.mag_fit = None
            self.mag_fit_label.setStyleSheet('color: #d64545;')
            self.mag_fit_label.setText(f'Fit: {exc}')
        self.mag_update_buttons()
        self.mag_plot()

    def mag_apply(self):
        if self.mag_fit is None:
            return
        answer = QtWidgets.QMessageBox.question(
            self, 'Apply calibration', f'Store this calibration on the device?\n\n{self.mag_fit.summary()}')
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self.device.thread_command('cal_set', {'target': self.key, 'name': 'mag', 'text': self.mag_fit.to_text()})

    def mag_plot(self):
        import numpy as np
        pts = np.array(self.mag_points, dtype=float).reshape(-1, 3)
        cal = self.mag_fit.apply(pts) if self.mag_fit is not None and len(pts) else np.zeros((0, 3))
        phi = np.linspace(0, 2 * np.pi, 120)
        for (raw_item, cal_item, circle), (_a, _b, i, j) in zip(self.mag_plots, self.MAG_PLANES):
            raw_item.setData(pts[:, i], pts[:, j]) if len(pts) else raw_item.clear()
            cal_item.setData(cal[:, i], cal[:, j]) if len(cal) else cal_item.clear()
            if self.mag_fit is not None:
                r = self.mag_fit.field_ut
                circle.setData(r * np.cos(phi), r * np.sin(phi))
            else:
                circle.clear()

    def mag_save_points(self):
        if not self.mag_points:
            return
        name = (self.entry or {}).get('hwid') or self.key
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save magnetometer points',
                                                        f'mag_points_{name}.csv', 'CSV (*.csv)')
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('x_ut,y_ut,z_ut\n')
                for x, y, z in self.mag_points:
                    f.write(f'{x:.4f},{y:.4f},{z:.4f}\n')

    def mag_load_points(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Load magnetometer points', '', 'CSV (*.csv)')
        if not path:
            return
        points = []
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    points.append(tuple(float(v) for v in line.strip().split(',')[:3]))
                except ValueError:
                    continue        # header
        self.mag_points = [p for p in points if len(p) == 3]
        self.mag_fit = None
        self.mag_status.setText(f'{len(self.mag_points)} values loaded; {self.mag_coverage_text()}')
        self.mag_do_fit() if len(self.mag_points) >= mag_calibration.MIN_POINTS else self.mag_plot()

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
        self.fw_method = QtWidgets.QLabel('')
        self.fw_method.setWordWrap(True)
        self.fw_method.setStyleSheet('color: gray;')
        self.fw_auto = QtWidgets.QCheckBox('Auto update at power-up: install a newer /fw/update.bin '
                                           '(or /fw/zephyr.signed.bin) from the SD card')
        self.fw_auto.setToolTip('Stored on the device (norlog fw auto on|off); serial only for now')
        self.fw_auto.toggled.connect(
            lambda on: self.device.thread_command('send', {'text': f'norlog fw auto {"on" if on else "off"}'}))
        self.fw_force = QtWidgets.QCheckBox('Flash even if this image is already installed')
        self.fw_force.setChecked(self.cfg.firmware_force)
        self.fw_force.toggled.connect(lambda v: setattr(self.cfg, 'firmware_force', v))
        btn_row = QtWidgets.QHBoxLayout()
        self.fw_flash = QtWidgets.QPushButton('Flash device')
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
        lay.addWidget(self.fw_method)
        lay.addWidget(self.fw_force)
        lay.addWidget(self.fw_auto)
        lay.addLayout(btn_row)
        lay.addWidget(self.fw_progress)

        # Loader (slot1) without SWD, firmware >= 0.4.42
        box = QtWidgets.QGroupBox('Loader (slot1, without SWD)')
        box_lay = QtWidgets.QVBoxLayout(box)
        row = QtWidgets.QHBoxLayout()
        self.loader_path = QtWidgets.QLineEdit(self.cfg.loader_image)
        self.loader_path.setPlaceholderText('.../build/norlog_loader/zephyr/zephyr.signed.bin')
        self.loader_path.textChanged.connect(lambda t: setattr(self.cfg, 'loader_image', t))
        browse = QtWidgets.QPushButton('Browse ...')
        browse.clicked.connect(self.browse_loader)
        row.addWidget(QtWidgets.QLabel('Image'))
        row.addWidget(self.loader_path, 1)
        row.addWidget(browse)
        self.loader_info = QtWidgets.QLabel('')
        self.loader_install = QtWidgets.QPushButton('Install loader')
        self.loader_install.setToolTip('Copies the image to /fw/loader.bin on the SD card; the app writes it to '
                                       'slot1 and verifies it (no reboot, firmware >= 0.4.42). If it fails, only '
                                       'the loader is invalid and the app keeps running: try again.')
        self.loader_install.clicked.connect(self.install_loader)
        box_lay.addLayout(row)
        box_lay.addWidget(self.loader_info)
        box_lay.addWidget(self.loader_install)
        lay.addWidget(box)

        lay.addWidget(self.fw_log, 1)
        self.fw_path.textChanged.connect(self.update_image_info)
        self.loader_path.textChanged.connect(self.update_loader_info)
        self.update_image_info()
        self.update_loader_info()
        return w

    def browse_loader(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Signed loader image', self.loader_path.text(),
                                                        'MCUboot images (*.signed.bin);;All files (*)')
        if path:
            self.loader_path.setText(path)

    def update_loader_info(self):
        path = pathlib.Path(self.loader_path.text())
        if not path.is_file():
            self.loader_info.setText('')
            return
        try:
            image = path.read_bytes()
            info = smp_serial.image_info(image)
            text = f'Version {info["version"]}, {len(image) // 1024} KB'
            if len(image) > _Gateway.LOADER_SLOT_SIZE:
                text += ' - too large for slot1 (app image?)'
            self.loader_info.setText(text)
        except (ValueError, OSError, TypeError) as exc:
            self.loader_info.setText(f'Invalid image: {exc}')

    def install_loader(self):
        self.fw_progress.setValue(0)
        self.fw_log.clear()
        self.device.thread_command('loader_update', {'target': self.key, 'image': self.cfg.loader_image})

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
        if self.is_serial():
            self.device.thread_command('flash', {'image': self.cfg.firmware_image,
                                                 'force': self.cfg.firmware_force})
        else:
            self.device.thread_command('fw_update_node', {'target': self.key, 'image': self.cfg.firmware_image,
                                                          'force': self.cfg.firmware_force})

    # --- files (SD card) ---

    def _build_data_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        info = QtWidgets.QLabel('Copies the log files of the SD card (data_*.cbor, index, catalog) 1:1 into the '
                                'archive folder, one subfolder per hardware ID. Only what is new is loaded; an '
                                'interrupted download continues where it stopped.')
        info.setWordWrap(True)
        lay.addWidget(info)
        row = QtWidgets.QHBoxLayout()
        self.data_folder = QtWidgets.QLineEdit(self.cfg.archive_folder)
        self.data_folder.editingFinished.connect(
            lambda: setattr(self.cfg, 'archive_folder', self.data_folder.text().strip() or 'norlog_archive'))
        browse = QtWidgets.QPushButton('Browse ...')
        browse.clicked.connect(self.data_browse)
        open_btn = QtWidgets.QPushButton('Open')
        open_btn.setToolTip('Open the archive folder of this device')
        open_btn.clicked.connect(self.data_open_folder)
        row.addWidget(QtWidgets.QLabel('Archive folder'))
        row.addWidget(self.data_folder, 1)
        row.addWidget(browse)
        row.addWidget(open_btn)
        lay.addLayout(row)
        self.data_publish = QtWidgets.QCheckBox('Publish the downloaded packets (measurement time, e.g. for the '
                                                'database writers)')
        self.data_publish.setToolTip('Every packet is published once. Packets written before the clock was set '
                                     'get their time from the uptime when the clock of their boot is known.')
        self.data_publish.setChecked(self.cfg.archive_publish)
        self.data_publish.toggled.connect(lambda v: setattr(self.cfg, 'archive_publish', bool(v)))
        lay.addWidget(self.data_publish)
        row = QtWidgets.QHBoxLayout()
        self.data_list_btn = QtWidgets.QPushButton('List files')
        self.data_list_btn.setToolTip('Compare the log files of the SD card with the archive, nothing is '
                                      'downloaded; then select the files to load')
        self.data_list_btn.clicked.connect(self.data_list)
        self.data_verify = QtWidgets.QCheckBox('verify (CRC)')
        self.data_verify.setToolTip('Also compare every archived file completely with the card (CRC). Slow: over '
                                    'Thread one request per 64 KB. Without it, files of the same size count as '
                                    'up to date (the names are unique, downloads are verified by CRC).')
        self.data_order = QtWidgets.QComboBox()
        self.data_order.addItems(['oldest first', 'newest first'])
        self.data_order.setToolTip('Order of the download (the file names are chronological)')
        self.data_order.currentIndexChanged.connect(lambda _i: self.data_show_rows())
        sel_all = QtWidgets.QPushButton('All')
        sel_all.setToolTip('Select all files with something to load')
        sel_all.clicked.connect(lambda: self.data_select('all'))
        sel_none = QtWidgets.QPushButton('None')
        sel_none.clicked.connect(lambda: self.data_select('none'))
        sel_rows = QtWidgets.QPushButton('Marked rows')
        sel_rows.setToolTip('Select only the rows marked in the table (click, Shift/Ctrl+click)')
        sel_rows.clicked.connect(lambda: self.data_select('rows'))
        self.data_sel_label = QtWidgets.QLabel('')
        row.addWidget(self.data_list_btn)
        row.addWidget(self.data_verify)
        row.addWidget(QtWidgets.QLabel('Order'))
        row.addWidget(self.data_order)
        row.addWidget(QtWidgets.QLabel('Select'))
        for b_ in (sel_all, sel_none, sel_rows):
            row.addWidget(b_)
        row.addWidget(self.data_sel_label, 1)
        lay.addLayout(row)
        self.data_select_widgets = [sel_all, sel_none, sel_rows, self.data_order, self.data_verify]
        row = QtWidgets.QHBoxLayout()
        self.data_sync_btn = QtWidgets.QPushButton('Download')
        self.data_sync_btn.setToolTip('Load the selected files (all new data if the list was not read)')
        self.data_sync_btn.clicked.connect(self.data_sync)
        self.data_cancel_btn = QtWidgets.QPushButton('Cancel')
        self.data_cancel_btn.clicked.connect(self.data_cancel)
        self.data_convert_btn = QtWidgets.QPushButton('Convert to SQLite ...')
        self.data_convert_btn.setToolTip('Convert selected log files (*.cbor) of the archive into an SQLite '
                                         'database in the redvypr format: the packets in the table redvypr_raw '
                                         '(like "Save data" of the gateway) with their measurement time. Works '
                                         'without the device; packets already in the database (also received '
                                         'live) are not added twice.')
        self.data_convert_flat = QtWidgets.QCheckBox('Flat table for plots')
        self.data_convert_flat.setChecked(True)
        self.data_convert_flat.setToolTip('Also a data_flat table (one column per datastream): needed by the '
                                          'redvypr data sources, e.g. XY plot "Add line from database ..."')
        self.data_convert_btn.clicked.connect(self.data_convert)
        self.data_progress = QtWidgets.QProgressBar()
        self.data_progress.setRange(0, 100)
        self.data_progress.setValue(0)
        row.addWidget(self.data_sync_btn)
        row.addWidget(self.data_convert_btn)
        row.addWidget(self.data_convert_flat)
        row.addWidget(self.data_cancel_btn)
        row.addWidget(self.data_progress, 1)
        lay.addLayout(row)
        self.data_status = QtWidgets.QLabel('')
        self.data_status.setWordWrap(True)
        self.data_status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.data_status)
        self.data_files = QtWidgets.QTableWidget(0, len(self.DATA_COLS))
        self.data_files.setHorizontalHeaderLabels(self.DATA_COLS)
        self.data_files.horizontalHeader().setStretchLastSection(True)
        self.data_files.verticalHeader().setVisible(False)
        self.data_files.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.data_files.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.data_files.itemChanged.connect(self.data_item_changed)
        lay.addWidget(self.data_files, 1)
        self.data_busy = False
        self.data_dir = None
        self.convert_worker = None
        self.data_rows = {}             # stem -> {'files': {name: {'card', 'local', 'state'}}, 'sel', 'run'}
        self.data_listed = False        # list read: download only the selected files
        self.data_loading = False
        self.data_current = None        # (stem, done at its start, bytes to load) during the download
        self.data_queue = None          # selected stems in download order
        return w

    # --- data: file list, selection and order ---

    DATA_COLS = ['File', 'No.', 'Boot', 'Start', 'On card', 'In archive', 'To load', 'State']
    COL_DATA_STATE = 7
    DATA_NAME_RE = re.compile(r'data_(\d+)_(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(\d{2})_(\d+)$')
    DATA_STATES = {'unchanged': 'up to date', 'new': 'new', 'grown': 'more on the card',
                   'mismatch': 'differs from the card: load again (old copy kept)', 'listing': 'reading ...'}

    @staticmethod
    def _kb(n):
        return f'{n / 1024:.1f} KB' if n < 1024 * 1024 else f'{n / 1024 / 1024:.2f} MB'

    @staticmethod
    def _data_to_load(files):
        return sum(f['card'] if f['state'] == 'mismatch' else max(0, f['card'] - f['local'])
                   for f in files.values())

    def _data_state(self, files):
        for state in ('mismatch', 'grown', 'new'):
            if any(f['state'] == state for f in files.values()):
                return state
        return 'unchanged'

    def data_list(self):
        self.cfg.archive_folder = self.data_folder.text().strip() or 'norlog_archive'
        self.data_busy = True
        self.update_run_state(self.running)
        self.data_status.setStyleSheet('')
        verify = self.data_verify.isChecked()
        self.data_prev_rows = self.data_rows if self.data_listed else {}    # keeps the selection
        self.data_progress.setRange(0, 0)       # number of files unknown until the listing is complete
        self.data_status.setText('Reading the file list' + (' and comparing the archive by CRC' if verify else '')
                                 + ' ...')
        self.device.thread_command('data_list', {'target': self.key, 'folder': self.cfg.archive_folder,
                                                 'verify': verify})

    def data_stems(self):
        """Stems in download order."""
        return sorted(self.data_rows, reverse=self.data_order.currentIndex() == 1)

    def data_show_rows(self):
        self.data_loading = True
        t = self.data_files
        stems = self.data_stems()
        t.setRowCount(len(stems))
        for r, stem in enumerate(stems):
            d = self.data_rows[stem]
            data = d['files'].get(stem + '.cbor') or next(iter(d['files'].values()))
            m = self.DATA_NAME_RE.match(stem)
            # file name: data_<file number>_<start date>_<time>_<uptime s>; the boot comes from the catalog
            number, start = (str(int(m.group(1))), f'{m.group(2)} {m.group(3)}:{m.group(4)}:{m.group(5)}') if m \
                else ('', '')
            boot = '' if data.get('boot') is None else str(data['boot'])
            todo = self._data_to_load(d['files'])
            listing = data['state'] == 'listing'
            state = 'reading ...' if listing else \
                (d.get('run') or self.DATA_STATES.get(self._data_state(d['files']), ''))
            item = QtWidgets.QTableWidgetItem(stem + '.cbor')
            if self.data_listed:
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.CheckState.Checked if d.get('sel') else QtCore.Qt.CheckState.Unchecked)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, stem)
            t.setItem(r, 0, item)
            local = '...' if listing else self._kb(data['local'])
            todo_text = '...' if listing else (self._kb(todo) if todo else '-')
            for col, text in enumerate([number, boot, start, self._kb(data['card']), local, todo_text, state],
                                       start=1):
                it = QtWidgets.QTableWidgetItem(text)
                if col in (1, 2, 4, 5, 6):
                    it.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
                t.setItem(r, col, it)
        t.resizeColumnsToContents()
        self.data_loading = False
        self.data_update_selection_label()

    def data_update_selection_label(self):
        if not self.data_listed:
            self.data_sel_label.setText('')
            return
        sel = [s for s, d in self.data_rows.items() if d.get('sel')]
        todo = sum(self._data_to_load(self.data_rows[s]['files']) for s in sel)
        new = sum(1 for d in self.data_rows.values() if self._data_to_load(d['files']))
        self.data_sel_label.setText(f'{len(sel)} of {len(self.data_rows)} files selected, {self._kb(todo)} to load '
                                    f'({new} with new data)')

    def data_item_changed(self, item):
        if self.data_loading or item.column() != 0:
            return
        stem = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if stem in self.data_rows:
            self.data_rows[stem]['sel'] = item.checkState() == QtCore.Qt.CheckState.Checked
            self.data_update_selection_label()

    def data_select(self, how):
        if not self.data_listed:
            self.data_status.setStyleSheet('color: #c08000;')
            self.data_status.setText('read the file list first ("List files")')
            return
        rows = {self.data_files.item(i.row(), 0).data(QtCore.Qt.ItemDataRole.UserRole)
                for i in self.data_files.selectedIndexes()}
        for stem, d in self.data_rows.items():
            d['sel'] = (how == 'all' and self._data_to_load(d['files']) > 0) or (how == 'rows' and stem in rows)
        self.data_show_rows()

    def on_data_list_partial(self, data):
        """A page of the directory listing: show the files already, the comparison follows."""
        self.data_listed = False
        self.data_rows = {}
        for f in data.get('files', []):
            d = self.data_rows.setdefault(norlog_archive.file_stem(f['name']), {'files': {}})
            d['files'][f['name']] = {'card': f['card'], 'local': 0, 'state': 'listing'}
        self.data_show_rows()
        n, total = data.get('n', 0), data.get('total')
        if total:       # firmware >= 0.4.22: number of entries known, otherwise the bar keeps running
            self.data_progress.setRange(0, 100)
            self.data_progress.setValue(int(100 * n / total))
        self.data_status.setText(f"Reading the file list: {n}" + (f" of {total}" if total else '')
                                 + f" entries ({len(self.data_rows)} data files) ...")

    def on_data_list(self, data):
        self.data_busy = False
        self.update_run_state(self.running)
        self.data_progress.setRange(0, 100)
        if not data.get('ok'):
            self.data_status.setStyleSheet('color: #d64545;')
            self.data_status.setText(data.get('message', 'error'))
            return
        self.data_dir = data.get('dir') or self.data_dir
        old = getattr(self, 'data_prev_rows', {})
        self.data_rows = {}
        for f in data.get('files', []):
            stem = norlog_archive.file_stem(f['name'])
            d = self.data_rows.setdefault(stem, {'files': {}})
            d['files'][f['name']] = {k: f.get(k) for k in ('card', 'local', 'state', 'boot')}
        for stem, d in self.data_rows.items():
            # keep a selection made before, otherwise everything with new data
            d['sel'] = old[stem].get('sel', False) if stem in old else self._data_to_load(d['files']) > 0
        self.data_listed = True
        self.data_show_rows()
        todo = sum(self._data_to_load(d['files']) for d in self.data_rows.values())
        self.data_status.setStyleSheet('')
        self.data_status.setText(f"{len(self.data_rows)} data files on the card, {self._kb(todo)} not in the archive "
                                 f"({data.get('dir')})")

    def _data_row_of(self, stem):
        for r in range(self.data_files.rowCount()):
            item = self.data_files.item(r, 0)
            if item is not None and item.data(QtCore.Qt.ItemDataRole.UserRole) == stem:
                return r
        return -1

    def _data_set_run(self, stem, text, active=False):
        """State text of a row during the download; the active row is highlighted and kept visible."""
        d = self.data_rows.get(stem)
        if d is None:
            return
        d['run'] = text
        r = self._data_row_of(stem)
        if r < 0:
            return
        self.data_loading = True
        self.data_files.item(r, self.COL_DATA_STATE).setText(text)
        font = self.data_files.item(r, 0).font()
        font.setBold(active)
        for c in range(self.data_files.columnCount()):
            self.data_files.item(r, c).setFont(font)
        self.data_loading = False
        if active:
            self.data_files.scrollToItem(self.data_files.item(r, 0))

    def _device_archive_dir(self):
        hwid = (self.entry.get('info') or {}).get('hwid') if getattr(self, 'entry', None) else None
        folder = self.data_dir or (str(pathlib.Path(self.cfg.archive_folder) / hwid) if hwid else
                                   self.cfg.archive_folder)
        return folder if pathlib.Path(folder).exists() else self.cfg.archive_folder

    def data_cancel(self):
        if self.convert_worker is not None:
            self.convert_worker.requestInterruption()
        else:
            self.device.thread_command('sync_cancel', {})

    def data_convert(self):
        folder = self._device_archive_dir()
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, 'Log files to convert', folder,
                                                          'norlog log files (data_*.cbor);;All files (*)')
        if not files:
            return
        default = str(pathlib.Path(folder) / f'{pathlib.Path(folder).name}.sqlite')
        db_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'SQLite database (new or extended)', default, 'SQLite (*.sqlite *.db);;All files (*)',
            options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
        if not db_path:
            return
        self.start_convert(files, db_path)

    def start_convert(self, files, db_path):
        sn = (getattr(self, 'entry', None) or {}).get('sn')
        self.convert_flat = self.data_convert_flat.isChecked()
        self.convert_worker = ConvertWorker(files, db_path, sn=sn, flat=self.convert_flat, parent=self)
        self.convert_worker.progress.connect(self.on_convert_progress)
        self.convert_worker.finished_result.connect(lambda res, err: self.on_convert_done(res, err, db_path))
        self.data_convert_btn.setEnabled(False)
        self.data_cancel_btn.setEnabled(True)
        self.data_progress.setValue(0)
        self.data_status.setStyleSheet('')
        self.data_status.setText(f'Converting {len(files)} file(s) into {db_path} ...')
        self.convert_worker.start()

    def on_convert_progress(self, i, n, name):
        self.data_progress.setValue(int(100 * i / n) if n else 0)
        if name:
            self.data_status.setText(f'Converting {name} ({i + 1}/{n}) ...')

    def on_convert_done(self, res, err, db_path):
        self.convert_worker = None
        self.data_convert_btn.setEnabled(True)
        self.update_run_state(self.running)
        if err:
            self.data_status.setStyleSheet('color: #d64545;')
            self.data_status.setText(f'Conversion failed: {err}')
            return
        self.data_progress.setValue(100)
        text = norlog_convert.summary(res, db_path)
        name = self._register_datasource(db_path) if self.convert_flat else None
        if name:
            text += f'; data source "{name}" of redvypr (XY plot: "Add line from database ...")'
        self.data_status.setText(text)

    def _register_datasource(self, db_path):
        """The converted database as data source of redvypr (once per file); returns its name."""
        rv = getattr(self.device, 'redvypr', None)
        if rv is None or not hasattr(rv, 'add_datasource'):
            return None
        try:
            path = pathlib.Path(db_path).resolve()
            for d in rv.datasources:
                if d.dbtype == 'sqlite' and d.filepath and pathlib.Path(d.filepath).resolve() == path:
                    rv.get_datasource_reader(d.name, refresh=True)   # new datastreams and metadata
                    return d.name
            names = {d.name for d in rv.datasources}
            name, i = path.stem, 2
            while name in names:
                name, i = f'{path.stem}_{i}', i + 1
            rv.add_datasource({'name': name, 'dbtype': 'sqlite', 'filepath': str(path),
                               'description': 'norlog log files (norlog_convert)'})
            return name
        except Exception:
            logger.info('could not add the database as data source', exc_info=True)
            return None

    def data_browse(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Archive folder', self.data_folder.text())
        if folder:
            self.data_folder.setText(folder)
            self.cfg.archive_folder = folder

    def data_open_folder(self):
        folder = self._device_archive_dir()
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(pathlib.Path(folder).resolve())))

    def data_sync(self):
        self.cfg.archive_folder = self.data_folder.text().strip() or 'norlog_archive'
        args = {'target': self.key, 'folder': self.cfg.archive_folder, 'publish': self.data_publish.isChecked(),
                'newest_first': self.data_order.currentIndex() == 1}
        if self.data_listed:
            stems = [s for s in self.data_stems() if self.data_rows[s].get('sel')]
            if not stems:
                self.data_status.setStyleSheet('color: #c08000;')
                self.data_status.setText('no file selected')
                return
            args['stems'] = stems
            # found different by a verified list: the same size does not show it to the download
            args['reload'] = [n for s in stems for n, f in self.data_rows[s]['files'].items()
                              if f['state'] == 'mismatch']
            for s in self.data_rows:
                self.data_rows[s]['run'] = 'waiting' if s in stems else None
            self.data_show_rows()
        self.data_queue = args.get('stems')
        self.data_current = None
        self.data_busy = True
        self.update_run_state(self.running)
        self.data_progress.setValue(0)
        self.data_status.setStyleSheet('')
        self.data_status.setText('Comparing with the archive ...')
        self.device.thread_command('data_sync', args)

    def data_track_progress(self, data):
        """Rows during the download: finished files 'loaded', the current one with its percentage."""
        stem = norlog_archive.file_stem(data.get('file', ''))
        done = data.get('done', 0)
        if stem not in self.data_rows:
            return
        if self.data_current is None or self.data_current[0] != stem:
            if self.data_current is not None:
                self._data_set_run(self.data_current[0], 'loaded')
            # the files before it in the order are loaded (or had nothing to load); its bytes start after theirs
            start = 0
            for s in (self.data_queue or []):
                if s == stem:
                    break
                start += self._data_to_load(self.data_rows[s]['files'])
                if self.data_rows[s].get('run') == 'waiting':
                    self._data_set_run(s, 'loaded')
            self.data_current = (stem, start, self._data_to_load(self.data_rows[stem]['files']))
        _stem, start, size = self.data_current
        pct = max(0, min(99, int(100 * (done - start) / size))) if size else 0
        self._data_set_run(stem, f'loading {pct} %', active=True)

    def on_sync_message(self, packetid, data):
        if packetid == 'sync_list':
            self.on_data_list(data)
            return
        if packetid == 'sync_list_partial':
            self.on_data_list_partial(data)
            return
        if packetid == 'sync_progress' and data.get('catalog'):
            n = data.get('total') or 0
            self.data_progress.setRange(0, 100)
            self.data_progress.setValue(int(100 * data.get('done', 0) / n) if n else 0)
            self.data_status.setText(f"Reading the catalog of the card: {self._kb(data.get('done', 0))} of "
                                     f"{self._kb(n)} (only what is new) ...")
            return
        if packetid == 'sync_progress' and data.get('verify'):
            n = data.get('total') or 0
            self.data_progress.setRange(0, 100)
            self.data_progress.setValue(int(100 * data.get('done', 0) / n) if n else 0)
            self.data_status.setText(f"Comparing the archive by CRC: file {data.get('done', 0)} of {n} "
                                     f"({data.get('file', '')}) ...")
            return
        if packetid == 'sync_progress':
            total = data.get('total') or 0
            done = data.get('done', 0)
            rate = data.get('rate', 0)
            self.data_progress.setValue(int(100 * done / total) if total else 0)
            eta = (total - done) / 1024 / rate if rate > 0 else None
            n_files = len(self.data_queue) if self.data_queue else None
            pos = ''
            if n_files and data.get('file'):
                stem = norlog_archive.file_stem(data['file'])
                if stem in self.data_queue:
                    pos = f'file {self.data_queue.index(stem) + 1} of {n_files}, '
            self.data_status.setText(
                f"{pos}{data.get('file', '')}: {self._kb(done)} of {self._kb(total)}, {rate:.1f} KB/s"
                + (f", about {int(eta // 60)}:{int(eta % 60):02d} min left" if eta is not None else ''))
            self.data_track_progress(data)
            return
        self.data_busy = False
        self.update_run_state(self.running)
        if data.get('ok'):
            self.data_progress.setValue(100)
        self.data_dir = data.get('dir') or self.data_dir
        self.data_status.setStyleSheet('' if data.get('ok') else 'color: #d64545;')
        self.data_status.setText(data.get('message', ''))
        # Archive sizes from the result; rows of a download without list are added
        failed = set()
        for f in data.get('files') or []:
            stem = norlog_archive.file_stem(f['name'])
            if f.get('status') == 'failed':
                failed.add(stem)
            d = self.data_rows.setdefault(stem, {'files': {}})
            entry = d['files'].setdefault(f['name'], {'card': f['new'], 'local': 0, 'state': 'new'})
            entry['local'] = f['new']
            entry['card'] = max(entry['card'], f['new'])
            entry['state'] = 'unchanged' if entry['local'] >= entry['card'] else 'grown'
        for stem, d in self.data_rows.items():
            left = self._data_to_load(d['files'])
            # the row interrupted by a cancel or error says so; all others show their state again
            d['run'] = 'FAILED (CRC), try again' if stem in failed else \
                ('stopped' if left and (d.get('run') or '').startswith('loading') else None)
            if not left:
                d['sel'] = False
        self.data_current = None
        self.data_show_rows()

    def _build_files_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        self.files_path = QtWidgets.QLineEdit('/')
        self.files_path.returnPressed.connect(self.files_list)
        up = QtWidgets.QPushButton('Up')
        up.clicked.connect(self.files_up)
        refresh = QtWidgets.QPushButton('List')
        refresh.clicked.connect(self.files_list)
        row.addWidget(QtWidgets.QLabel('Directory'))
        row.addWidget(self.files_path, 1)
        row.addWidget(up)
        row.addWidget(refresh)
        self.files_table = QtWidgets.QTableWidget(0, 2)
        self.files_table.setHorizontalHeaderLabels(['Name', 'Size'])
        self.files_table.horizontalHeader().setStretchLastSection(True)
        self.files_table.verticalHeader().setVisible(False)
        self.files_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.files_table.cellDoubleClicked.connect(self.files_open)
        btns = QtWidgets.QHBoxLayout()
        actions = [('Upload ...', self.files_upload), ('Download ...', self.files_download),
                   ('New folder ...', self.files_mkdir), ('Delete', self.files_delete),
                   ('CRC', self.files_crc)]
        self.files_run_widgets = [up, refresh]
        for label, fn in actions:
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(fn)
            btns.addWidget(b)
            self.files_run_widgets.append(b)
        self.files_progress = QtWidgets.QProgressBar()
        self.files_progress.setRange(0, 100)
        self.files_progress.setVisible(False)
        self.files_status = QtWidgets.QLabel('SD card of this device; for Thread members over CoAP via the gateway.')
        self.files_status.setWordWrap(True)
        self.files_status.setStyleSheet('color: gray;')
        lay.addLayout(row)
        lay.addWidget(self.files_table, 1)
        lay.addLayout(btns)
        lay.addWidget(self.files_progress)
        lay.addWidget(self.files_status)
        self.files_entries = []
        return w

    def _files_cmd(self, op, **args):
        self.files_status.setText(f'{op} ...')
        self.device.thread_command('fs', {'target': self.key, 'op': op, **args})

    def _files_selected(self):
        rows = sorted({i.row() for i in self.files_table.selectedIndexes()})
        return [self.files_entries[r] for r in rows if r < len(self.files_entries)]

    def _files_join(self, name):
        base = self.files_path.text().rstrip('/')
        return f'{base}/{name}' if base else f'/{name}'

    def files_list(self):
        path = self.files_path.text().strip() or '/'
        self._files_cmd('ls', path=path)

    def files_up(self):
        path = self.files_path.text().rstrip('/')
        self.files_path.setText(path.rsplit('/', 1)[0] or '/')
        self.files_list()

    def files_open(self, row, _col):
        if row < len(self.files_entries) and self.files_entries[row].get('d'):
            self.files_path.setText(self._files_join(self.files_entries[row]['n']))
            self.files_list()

    def files_upload(self):
        local, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Upload file to the SD card')
        if local:
            self.files_progress.setValue(0)
            self.files_progress.setVisible(True)
            self._files_cmd('upload', local=local, path=self._files_join(pathlib.Path(local).name))

    def files_download(self):
        sel = [e for e in self._files_selected() if not e.get('d')]
        if not sel:
            return
        local, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save file', sel[0]['n'])
        if local:
            self.files_progress.setValue(0)
            self.files_progress.setVisible(True)
            self._files_cmd('download', path=self._files_join(sel[0]['n']), local=local)

    def files_mkdir(self):
        name, ok = QtWidgets.QInputDialog.getText(self, 'New folder', 'Name')
        if ok and name.strip():
            self._files_cmd('mkdir', path=self._files_join(name.strip()))

    def files_delete(self):
        sel = self._files_selected()
        if not sel:
            return
        names = ', '.join(e['n'] for e in sel)
        if QtWidgets.QMessageBox.question(self, 'Delete', f'Delete {names} on the device?') == \
                QtWidgets.QMessageBox.StandardButton.Yes:
            for e in sel:
                self._files_cmd('rm', path=self._files_join(e['n']))

    def files_crc(self):
        for e in self._files_selected():
            if not e.get('d'):
                self._files_cmd('crc', path=self._files_join(e['n']))

    def show_files(self, path, entries):
        self.files_path.setText(path)
        self.files_entries = sorted(entries, key=lambda e: (not e.get('d'), e.get('n', '').lower()))
        self.files_table.setRowCount(len(self.files_entries))
        for row, e in enumerate(self.files_entries):
            self.files_table.setItem(row, 0, QtWidgets.QTableWidgetItem(e['n'] + ('/' if e.get('d') else '')))
            self.files_table.setItem(row, 1, QtWidgets.QTableWidgetItem('' if e.get('d') else str(e.get('s', ''))))
        self.files_table.resizeColumnsToContents()

    def on_fs_message(self, packetid, data):
        if packetid == 'fs_progress':
            total = max(int(data.get('total', 0)), 1)
            self.files_progress.setVisible(True)
            self.files_progress.setValue(int(data.get('done', 0)) * 100 // total)
            return
        self.files_progress.setVisible(False)
        op = data.get('op')
        if not data.get('ok'):
            self.files_status.setText(f'{op} failed: {data.get("message", "")}')
            return
        if op == 'ls':
            self.show_files(data.get('path', '/'), data.get('entries', []))
            self.files_status.setText(f'{len(data.get("entries", []))} entries')
        else:
            self.files_status.setText(data.get('message', 'OK'))
            if op in ('upload', 'mkdir', 'rm'):
                self.files_list()

    def on_flash_status(self, data):
        if 'progress' in data:
            self.fw_progress.setValue(int(data['progress']))
        self.fw_log.appendPlainText(f"[{data.get('state')}] {data.get('message', '')}")
