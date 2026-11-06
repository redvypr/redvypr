"""
Serial ports of the norlog gateway device: search, matching with the configuration, and the
state of an open port (see the design note doc/design_verbindungen.md of the firmware).

A configured port is found again by its USB serial number (if the port has one), otherwise by its
name: the COM number of a USB serial port can change after plugging it in again. Ports that are
not configured are only opened on request (a foreign device at the port gets no shell commands).
"""

import time

import serial
import serial.tools.list_ports

from . import device_list
from . import links
from . import ot_cli

# USB vendor IDs of norlogs: Nordic Semiconductor, Zephyr (USB CDC of the nRF52840)
NORLOG_USB_VIDS = (0x1915, 0x2FE3)

# Retry opening a configured port after an error [s]
OPEN_RETRY_S = 10.0


def port_sort_key(name):
    """COM3 before COM16 (numeric order), /dev/ttyACM0 ..."""
    digits = ''.join(c for c in name if c.isdigit())
    return name.rstrip('0123456789'), int(digits) if digits else -1


def scan():
    """Serial ports of this computer: list of {name, description, usb_sn, vid, pid}."""
    found = []
    for p in serial.tools.list_ports.comports():
        found.append({'name': p.device, 'description': p.description or '', 'usb_sn': p.serial_number or '',
                      'vid': p.vid, 'pid': p.pid})
    return sorted(found, key=lambda p: port_sort_key(p['name']))


def looks_like_norlog(found):
    """USB port of a Nordic/Zephyr device or named norlog (only a hint, nothing is opened)."""
    text = f"{found.get('description', '')}".lower()
    return found.get('vid') in NORLOG_USB_VIDS or 'norlog' in text


def match(configs, found):
    """
    Assign the configured ports to the ports found.
    configs: list of PortConfig (port, usb_sn, ...); found: result of scan().
    Returns (rows, configs_by_name): rows = list of {name, config (PortConfig or None), found (dict or None)}
    in display order: configured ports first (in configuration order), then the others found
    (norlog-like first). configs_by_name: current port name -> PortConfig.
    """
    rest = list(found)
    rows = []
    for cfg in configs:
        hit = None
        if cfg.usb_sn:
            hit = next((f for f in rest if f['usb_sn'] == cfg.usb_sn), None)
        if hit is None and cfg.port:
            hit = next((f for f in rest if f['name'] == cfg.port and (not cfg.usb_sn or not f['usb_sn'])), None)
        if hit is not None:
            rest.remove(hit)
        rows.append({'name': hit['name'] if hit else cfg.port, 'config': cfg, 'found': hit})
    rest.sort(key=lambda f: (0 if looks_like_norlog(f) else 1, port_sort_key(f['name'])))
    rows.extend({'name': f['name'], 'config': None, 'found': f} for f in rest)
    return rows, {r['name']: r['config'] for r in rows if r['config'] is not None}


class Port:
    """An open serial port with a norlog: shell (OtCli), Thread state, received data."""

    _opened = 0     # counter: order of opening (gateway choice on a tie)

    def __init__(self, name, baud, role=device_list.PORT_ROLE_AUTO, on_line=None):
        self.name = name
        self.baud = baud
        self.role = role
        self.on_line = on_line          # on_line(port, line, is_response)
        self.ser = None
        self.reader = ot_cli.LineReader()
        self.cli = None
        self.last_rx = None             # time.monotonic() of the last line
        self.status = {}                # ot_cli.read_status()
        self.hwid = None                # hardware ID of the norlog (from its info)
        self.error = ''
        self.opened = 0
        self.npackets = 0
        self.data_sources = {}          # '#NLD' source -> {'last_seen', 'packets', 'mac'}
        self.t_leader_attempt = None    # prefer_leader: last attempt
        self.sink = None                # last 'norlog sink' state set by redvypr (True/False)

    def open(self):
        self.ser = serial.Serial(self.name, self.baud, timeout=0.05)
        self.cli = ot_cli.OtCli(self.ser, self.reader, self._line)
        Port._opened += 1
        self.opened = Port._opened
        self.error = ''

    def close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.cli = None

    @property
    def is_open(self):
        return self.ser is not None

    def _line(self, line, is_response=False):
        self.last_rx = time.monotonic()
        if self.on_line is not None:
            self.on_line(self, line, is_response)

    def poll(self):
        for line in self.reader.drain(self.ser):
            self._line(line)

    def rx_age(self):
        return None if self.last_rx is None else time.monotonic() - self.last_rx

    def link(self):
        return links.SerialLink(self.cli, self.name)

    @property
    def key(self):
        return self.hwid or device_list.port_key(self.name)
