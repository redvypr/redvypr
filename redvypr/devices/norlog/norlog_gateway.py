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
fs_result) go through the statusqueue of the device to its widget. They are
published as well only with the option publish_raw_data (default off), with
the same header. Messages about a node keep its key ('gateway' or RLOC16) in
'target'.

The info packet contains the info JSON as it is (nested) plus 'link': the radio
link as seen from the gateway (RSSI, LQ, role, next hop, ...). Metadata is
attached to the addresses '@di:<hwid>' (user properties, board, firmware) and
'<key>@di:<hwid>' (units); it is sent with the first info packet of a device,
again when it changes and completely when the device name changes (redvypr
stores metadata with the device of the packet).
"""

import base64
import collections
import copy
import binascii
import json
import logging
import pathlib
import queue
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
    info_interval_s: float = pydantic.Field(default=10.0, ge=0, description='Interval for reading the device '
                                                                            'info (battery, temperature, '
                                                                            'firmware) of all devices, '
                                                                            '0 = only on request')
    coap_timeout_s: int = pydantic.Field(default=5, ge=1, le=60, description='Timeout of a CoAP request to a '
                                                                             'Thread member')
    console_show_commands: bool = pydantic.Field(default=False, description='Show the traffic of internal '
                                                                            'ot commands in the console')
    publish_raw_data: bool = pydantic.Field(default=False, description='Publish also the raw data of the gateway: '
                                                                       'console lines, command results, Thread '
                                                                       'status with device list, transfer status')
    dataset_tlvs: str = pydantic.Field(default='', description='Active operational dataset (hex TLVs) used to '
                                                               'provision nodes. Contains the network key!')
    node_comport: str = pydantic.Field(default='', description='Serial port of a node to be provisioned')
    firmware_image: str = pydantic.Field(default='', description='Signed firmware image (zephyr.signed.bin)')
    firmware_force: bool = pydantic.Field(default=False, description='Flash even if the image is already installed')


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
        self.npackets = 0
        self.last_rx = None             # time.monotonic() of the last line from the gateway
        self.data_sources = {}          # '#NLD' source -> {'last_seen', 'packets', 'mac'}
        self.infos = {}                 # 'gateway' or RLOC16 -> info dict (norlog info / CoAP /info)
        self.info_times = {}            # 'gateway' or RLOC16 -> time.time() of the last successful read
        self.props_cache = {}           # hwid (or 'gateway'/RLOC16) -> user properties (sn, desc, loc, ...)
        self.last_status = {}
        self.meta_sent = {}             # hwid -> device metadata sent last
        self.units_sent = {}            # hwid -> set of keys whose unit was sent
        self.meta_device = {}           # hwid -> device name the metadata was sent with

    # --- publishing ---

    def identity(self, target='gateway', hwid=None):
        """
        device, deviceid and sensorid of a norlog for the packet header.
        target: 'gateway' or RLOC16 (its read info gives the hwid), or hwid directly.
        """
        key = target or 'gateway'
        info = self.infos.get(key) or {}
        hwid = hwid or info.get('hwid')
        props = (self.props_cache.get(hwid) if hwid else None) or self.props_cache.get(key) or {}
        if not info and hwid:
            info = next((i for i in self.infos.values() if i and i.get('hwid') == hwid), {})
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
        t = pkt.get('rtc_time') or pkt.get('gps_time') or time.time()
        # 'mac' of the CBOR packets is the hwid of the sending norlog
        device, hwid, sn = self.identity(device_list.norm_rloc16(source), hwid=pkt.get('mac'))
        data = create_redvypr_dict(device=device, deviceid=hwid, sensorid=sn,
                                   packetid=pkt.get('packet_type', 'data'), tu=t)
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
        for line in self.reader.drain(self.ser):
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
            elif command == 'read_device_info':
                self.query_info(args.get('targets', 'all'))
            elif command == 'refresh':
                self.read_status()
                self.query_info('all', refresh_props=True)
            elif command == 'props_read':
                self.props_command(args.get('target', 'gateway'), {})
            elif command == 'props_set':
                self.props_command(args.get('target', 'gateway'), args.get('values', {}))
            elif command == 'fs':
                self.fs_command(args)
            elif command == 'fw_update_node':
                self.fw_update_node(args.get('target', ''), args.get('image', ''), bool(args.get('force', False)))
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

    def read_status(self):
        status = ot_cli.read_status(self.cli)
        status['packets_received'] = self.npackets
        self.last_status = status
        self.publish_devices()

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
            props = self.props_cache.get(d.get('hwid')) or self.props_cache.get(key) or {}
            d['props'] = props
            for name in ('sn', 'desc', 'loc'):
                if props.get(name):
                    d[name] = props[name]
        return devices

    def publish_devices(self):
        self.to_gui('thread_status', {'thread_status': self.last_status, 'devices': self.build_devices()})

    # --- info packets (one redvypr device per norlog, device = hwid) ---

    # Radio link as seen from the gateway (entry of the device list) -> 'link'
    LINK_FIELDS = ('rloc16', 'extaddr', 'connection', 'link', 'thread_role', 'quality', 'rssi_avg',
                   'rssi_last', 'lq_in', 'lq_out', 'path_cost', 'next_hop', 'age_s')
    # Units of the info values, sent once per device as metadata
    INFO_UNITS = {
        "uptime_s": 's', "board_temp_c": 'degC',
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

        # redvypr stores metadata with the device of the packet: new device name
        # (serial number changed) -> send all metadata again
        if self.meta_device.get(hwid) != device:
            self.meta_device[hwid] = device
            self.meta_sent.pop(hwid, None)
            self.units_sent.pop(hwid, None)

        # Device metadata: user properties, board and firmware; sent again on changes.
        # A deleted property is sent once with an empty value.
        meta = {'hwid': hwid, 'board': info.get('board', ''), 'firmware': info.get('image') or
                info.get('firmware', ''), **{k: v for k, v in props.items() if v not in (None, '')}}
        for k in self.meta_sent.get(hwid, {}):
            meta.setdefault(k, '')
        if meta != self.meta_sent.get(hwid):
            redvypr.metadata.add_metadata2datapacket(data, address=f'@di:{hwid}', metadict=meta)
            self.meta_sent[hwid] = {k: v for k, v in meta.items() if v != ''}

        # Units of the values present (once per device and key)
        sent = self.units_sent.setdefault(hwid, set())
        for datakey, unit in self.INFO_UNITS.items():
            if datakey not in sent and self._has_key(data, datakey):
                redvypr.metadata.add_metadata2datapacket(data, address=f'{datakey}@di:{hwid}',
                                                         metadict={'unit': unit})
                sent.add(datakey)
        self.dataqueue.put(data)

    def store_info(self, key, info=None, error=None):
        """Store a read info; on error the last good values are kept and marked with the error."""
        if error is None:
            self.infos[key] = info
            self.info_times[key] = time.time()
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
                self.store_info('gateway', json.loads(self.cli.shell_query('norlog info json', '#NLI ')))
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
                    payload = ot_cli.coap_get(self.cli, addr, 'info', timeout=self.config.coap_timeout_s)
                    self.store_info(rloc, json.loads(payload.decode(errors='replace')))
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

            last = [0.0]

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
                    status('upload', 'Image already on the gateway SD card', 30)
                else:
                    ot_cli.fs_upload_local(self.cli, image, self.GATEWAY_XFER_FILE,
                                           progress(0, 30, 'PC -> gateway SD'))
                res = ot_cli.fs_push(self.cli, address, self.GATEWAY_XFER_FILE, '/fw/update.bin',
                                     progress(30, 95, 'Gateway -> node over Thread'), resume=True)
                resumed = f', resumed after {res["resumed"] // 1024} KB' if res.get('resumed') else ''
                status('upload', f'Node has the image ({res.get("seconds", "?")} s, CRC {res.get("crc")}'
                                 f'{resumed})', 95)
            else:
                status('upload', 'Gateway without SD card: sending directly (slower)', 0)
                self.fs_write_direct(address, image, '/fw/update.bin', progress(0, 95, 'PC -> node over Thread'))

            ot_cli.fw_install_remote(self.cli, address)
            status('done', 'Installing: the node reboots into its loader and starts the new firmware '
                           '(about 1 min, check the version with "Read info")', 100)
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
        self.tabs.addTab(self._build_devices_tab(), 'Devices')
        self.tabs.addTab(self._build_console_tab(), 'Console')
        self.tabs.addTab(self._build_thread_tab(), 'Thread network')
        self.tabs.addTab(self._build_data_tab(), 'Data')
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

    def publish_raw_changed(self, checked):
        self.cfg.publish_raw_data = bool(checked)
        if self.device.get_thread_status()['thread_running']:
            self.device.thread_command('config', {'config': self.cfg.model_dump()})

    def port_changed(self, text):
        data = self.port_combo.currentData()
        self.cfg.comport = data if data else text.split()[0] if text.strip() else ''

    # --- devices ---

    DEVICE_COLUMNS = ['', 'Device', 'SN', 'Description', 'Location', 'RLOC16', 'Connection', 'Role', 'Thread role', 'Link', 'Quality',
                      'RSSI avg/last [dBm]', 'LQ in/out', 'Path cost', 'Seen [s]', 'Packets',
                      'Firmware', 'Battery', 'Board temp [C]', 'Info age [s]']

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
        self.devices_table.itemSelectionChanged.connect(self.show_device_details)
        self.device_details = QtWidgets.QPlainTextEdit()
        self.device_details.setReadOnly(True)
        self.device_details.setPlaceholderText('Select a device to see its info: firmware, battery, '
                                               'hardware, SD and Thread details (norlog info / CoAP /info).')
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        split.addWidget(self.devices_table)
        split.addWidget(self.device_details)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        lay.addLayout(row)
        lay.addWidget(split, 1)
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

    def selected_devices(self):
        rows = sorted({i.row() for i in self.devices_table.selectedIndexes()})
        return [self.current_devices[r] for r in rows if r < len(self.current_devices)]

    def read_info_selected(self):
        keys = [self._device_key(d) for d in self.selected_devices()]
        keys = [k for k in keys if k]
        if keys:
            self.device.thread_command('read_device_info', {'targets': keys})

    def show_device_details(self):
        sel = self.selected_devices()
        if not sel:
            return
        d = sel[0]
        info = {k: v for k, v in (d.get('info') or {}).items() if k != 'error'}
        text = f"Last read failed: {d['info_error']}\n" if d.get('info_error') else ''
        if info:
            if d.get('info_error'):
                text += 'Last good info:\n'
            text += json.dumps(info, indent=2, ensure_ascii=False)
        elif not text:
            text = 'No info read yet (button "Refresh").'
        self.device_details.setPlainText(text)

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
                '' if d.get('info_age_s') is None else f"{d['info_age_s']:.0f}",
            ]
            cols = self.DEVICE_COLUMNS
            stale_cols = [cols.index(c) for c in ('Firmware', 'Battery', 'Board temp [C]', 'Info age [s]')]
            self.devices_table.setCellWidget(row, 0, self._settings_button(d))
            full_text = {cols.index('Description'): d.get('desc', ''), cols.index('Location'): d.get('loc', '')}
            for col, text in enumerate([''] + cells):
                item = QtWidgets.QTableWidgetItem(str(text))
                if full_text.get(col) and full_text[col] != text:
                    item.setToolTip(full_text[col])
                if cols[col] == 'Quality' and d.get('quality') in self.QUALITY_COLORS:
                    item.setBackground(QtGui.QColor(self.QUALITY_COLORS[d['quality']]))
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
        self.show_device_details()
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
            elif packetid == 'command_result':
                self.show_result(data)
            elif 'packet_type' in data:     # decoded '#NLD' data packet
                self.show_data(data)

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
        for w in self.run_widgets:
            w.setEnabled(running)
        for dlg in self.settings_dialogs.values():
            dlg.update_run_state(running)


class DeviceSettingsDialog(QtWidgets.QDialog):
    """
    Settings of one norlog of the device table: general info and firmware
    update. Firmware updates are only possible over serial (the gateway port)
    so far; for Thread members the firmware tab is disabled.
    """

    GENERAL_FIELDS = ['Device', 'RLOC16', 'Connection', 'Role', 'Thread role', 'Thread', 'Image', 'Firmware', 'Build',
                      'Board', 'HW ID', 'Battery', 'Board temp', 'Uptime', 'Reset cause', 'Hardware', 'SD card',
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
        lay.addWidget(self._build_props_box())
        lay.addWidget(self._build_battery_box())
        lay.addWidget(self._build_usb_box())
        lay.addStretch(1)
        return w

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
            'Board temp': '' if info.get('board_temp_c') is None else f"{info['board_temp_c']:.2f} \u00b0C",
            'Uptime': '' if uptime is None else f"{uptime // 3600} h {uptime // 60 % 60} min {uptime % 60} s",
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
        return text + (f" ({', '.join(details)})" if details else '')

    @staticmethod
    def _fmt_usb(usb):
        if not usb:
            return ''
        return (f"mode {usb.get('mode', '?')}, cable {'connected' if usb.get('vbus') else 'not connected'}, "
                f"SD card {'on USB (logging stopped)' if usb.get('msc') else 'logger'}")

    def update_run_state(self, running):
        self.running = running
        self.read_info_btn.setEnabled(running)
        for w in (self.props_read_btn, self.props_add_btn, self.props_save_btn):
            w.setEnabled(running)
        for w in (self.usb_mode, self.usb_msc_on, self.usb_msc_off, self.bat_model, self.bat_upload):
            w.setEnabled(running and self.is_serial())
        self.fw_flash.setEnabled(running)
        self.fw_cancel.setEnabled(running and self.is_serial())
        self.fw_auto.setEnabled(running and self.is_serial())
        for w in self.files_run_widgets:
            w.setEnabled(running)

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
        lay.addWidget(self.fw_log, 1)
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
        if self.is_serial():
            self.device.thread_command('flash', {'image': self.cfg.firmware_image,
                                                 'force': self.cfg.firmware_force})
        else:
            self.device.thread_command('fw_update_node', {'target': self.key, 'image': self.cfg.firmware_image,
                                                          'force': self.cfg.firmware_force})

    # --- files (SD card) ---

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
