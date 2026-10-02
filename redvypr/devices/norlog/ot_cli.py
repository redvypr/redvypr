"""
OpenThread CLI access through the Zephyr shell of a norlog ("ot <command>").

The Zephyr shell mixes command echo, VT100 escape sequences, prompts and
asynchronous log lines on the same UART. LineReader turns the raw byte stream
into clean text lines, OtCli sends an "ot" command and collects its response
up to "Done" / "Error ...". Every line (response or not) is forwarded to a
callback so it can be shown in a console.
"""

import re
import time

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
PROMPT_RE = re.compile(r"^(?:\S*:~\$ ?)+")
LOG_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\.\d{3},\d{3}\] <\w+> ")


class OtError(Exception):
    pass


def clean_line(raw: bytes) -> str:
    text = ANSI_RE.sub("", raw.decode(errors="replace"))
    # Prompt redraws use '\r': keep the last non-empty segment
    parts = [p for p in text.split("\r") if p.strip()]
    text = parts[-1] if parts else ""
    return PROMPT_RE.sub("", text).rstrip()


class LineReader:
    """Splits a byte stream into cleaned text lines."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes):
        lines = []
        for b in data:
            if b == 0x0A:
                line = clean_line(bytes(self._buf))
                self._buf.clear()
                if line:
                    lines.append(line)
            else:
                self._buf.append(b)
                if len(self._buf) > 4096:
                    self._buf.clear()
        return lines

    def reset(self):
        self._buf.clear()


class OtCli:
    def __init__(self, ser, reader: LineReader, on_line):
        """
        Args:
            ser: open serial.Serial
            reader: LineReader shared with the device's read loop
            on_line: callback(line: str, is_response: bool)
        """
        self.ser = ser
        self.reader = reader
        self.on_line = on_line

    def write_line(self, text: str):
        """Send a line in small chunks so long commands do not overrun the shell RX buffer."""
        data = (text + "\r\n").encode()
        for i in range(0, len(data), 32):
            self.ser.write(data[i:i + 32])
            self.ser.flush()
            if len(data) > 32:
                time.sleep(0.005)

    def command(self, cmd: str, timeout: float = 3.0):
        """Run 'ot <cmd>' and return the response lines (without echo/Done)."""
        full = f"ot {cmd}"
        self.write_line(full)

        result = []
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for line in self.reader.feed(self.ser.read(512)):
                if LOG_RE.match(line) or line.startswith("#NLD "):
                    self.on_line(line, False)     # asynchronous output, not part of the response
                    continue
                self.on_line(line, True)
                if line.endswith(full):
                    continue                      # echo of the command
                if line == "Done":
                    return result
                if line.startswith("Error"):
                    raise OtError(f"'{full}': {line}")
                result.append(line)
        raise TimeoutError(f"'{full}': no 'Done' within {timeout} s")

    def value(self, cmd: str) -> str:
        lines = self.command(cmd)
        return lines[0].strip() if lines else ""


def parse_table(lines):
    """Parse an OpenThread CLI table ('| a | b |' rows) into a list of dicts."""
    rows = [l for l in lines if l.startswith("|")]
    if not rows:
        return []
    header = [h.strip() for h in rows[0].strip("|").split("|")]
    table = []
    for row in rows[1:]:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) == len(header):
            table.append(dict(zip(header, cells)))
    return table


def read_status(cli: OtCli) -> dict:
    """Collect the most important Thread state of the connected node."""
    status = {"state": cli.value("state")}
    for key, cmd in (("channel", "channel"), ("panid", "panid"),
                     ("network_name", "networkname"), ("extpanid", "extpanid"),
                     ("rloc16", "rloc16"), ("extaddr", "extaddr")):
        try:
            status[key] = cli.value(cmd)
        except (OtError, TimeoutError):
            status[key] = ""
    try:
        status["ipaddr"] = [l.strip() for l in cli.command("ipaddr")]
    except (OtError, TimeoutError):
        status["ipaddr"] = []
    try:
        status["children"] = parse_table(cli.command("child table"))
    except (OtError, TimeoutError):
        status["children"] = []
    if status["state"] in ("router", "leader"):
        try:
            status["routers"] = parse_table(cli.command("router table"))
        except (OtError, TimeoutError):
            status["routers"] = []
    else:
        status["routers"] = []
    # Direct neighbors with RSSI (also works on a child: shows its parent)
    try:
        status["neighbors"] = parse_table(cli.command("neighbor table"))
    except (OtError, TimeoutError):
        status["neighbors"] = []
    status["leader_router_id"] = None
    if status["state"] in ("child", "router", "leader"):
        try:
            for line in cli.command("leaderdata"):
                if line.startswith("Leader Router ID:"):
                    status["leader_router_id"] = int(line.split(":", 1)[1])
        except (OtError, TimeoutError, ValueError):
            pass
    return status


def form_network(cli: OtCli, network_name="", channel=None, panid="", extpanid="", networkkey=""):
    """
    Create a new Thread network on the connected node (it becomes leader).
    Empty parameters keep the random values of 'dataset init new'.
    """
    for cmd in ("thread stop", "ifconfig down"):
        try:
            cli.command(cmd)
        except OtError:
            pass
    cli.command("dataset init new")
    if network_name:
        cli.command(f"dataset networkname {network_name}")
    if channel:
        cli.command(f"dataset channel {int(channel)}")
    if panid:
        cli.command(f"dataset panid {panid}")
    if extpanid:
        cli.command(f"dataset extpanid {extpanid}")
    if networkkey:
        cli.command(f"dataset networkkey {networkkey}")
    cli.command("dataset commit active")
    cli.command("ifconfig up")
    cli.command("thread start")


def active_dataset_tlvs(cli: OtCli) -> str:
    """Active operational dataset as hex TLVs (contains the network key!)."""
    return cli.value("dataset active -x")


# Thread MeshCoP TLV types used in an operational dataset
_TLV_CHANNEL, _TLV_PANID, _TLV_EXTPANID, _TLV_NETWORK_NAME, _TLV_NETWORK_KEY = 0, 1, 2, 3, 5


def parse_dataset_tlvs(tlvs_hex: str) -> dict:
    """
    Extract the non-secret parameters of an operational dataset (hex TLVs).
    The network key is only reported as present/absent.
    """
    data = bytes.fromhex(tlvs_hex.strip())
    info = {"network_name": "", "channel": None, "panid": "", "extpanid": "", "has_networkkey": False}
    pos = 0
    while pos + 2 <= len(data):
        t, length = data[pos], data[pos + 1]
        value = data[pos + 2:pos + 2 + length]
        if len(value) != length:
            raise ValueError("truncated dataset TLV")
        if t == _TLV_CHANNEL and length == 3:
            info["channel"] = int.from_bytes(value[1:3], "big")
        elif t == _TLV_PANID and length == 2:
            info["panid"] = f"0x{int.from_bytes(value, 'big'):04x}"
        elif t == _TLV_EXTPANID and length == 8:
            info["extpanid"] = value.hex()
        elif t == _TLV_NETWORK_NAME:
            info["network_name"] = value.decode(errors="replace")
        elif t == _TLV_NETWORK_KEY and length == 16:
            info["has_networkkey"] = True
        pos += 2 + length
    return info


def provision_node(cli: OtCli, tlvs_hex: str, attach_timeout: float = 20.0) -> dict:
    """
    Store the given active dataset on the connected node and start Thread.

    The dataset is persisted by OpenThread; with the norlog firmware the node
    rejoins the network automatically after every reboot.

    Returns the node status after attaching (or after the timeout).
    """
    parse_dataset_tlvs(tlvs_hex)        # validates the hex string
    for cmd in ("thread stop", "ifconfig down"):
        try:
            cli.command(cmd)
        except OtError:
            pass
    cli.command(f"dataset set active {tlvs_hex.strip()}", timeout=5.0)
    cli.command("ifconfig up")
    cli.command("thread start")

    end = time.monotonic() + attach_timeout
    state = ""
    while time.monotonic() < end:
        state = cli.value("state")
        if state in ("child", "router", "leader"):
            break
        time.sleep(1.0)
    return {"state": state, "extaddr": cli.value("extaddr"), "attached": state in ("child", "router", "leader")}


def autoexec_text(tlvs_hex: str) -> str:
    """Content of an autoexec.txt that provisions a norlog from its SD card."""
    info = parse_dataset_tlvs(tlvs_hex)
    return (
        "# norlog Thread provisioning (generated by redvypr)\n"
        f"# Network: {info['network_name']}, channel {info['channel']}, PAN ID {info['panid']}\n"
        "# WARNING: contains the network key in plain text.\n"
        "# The dataset is stored permanently on the node; after the first boot the\n"
        "# node rejoins automatically and this file is no longer needed.\n"
        "ot thread stop\n"
        "ot ifconfig down\n"
        f"ot dataset set active {tlvs_hex.strip()}\n"
        "ot ifconfig up\n"
        "ot thread start\n"
    )
