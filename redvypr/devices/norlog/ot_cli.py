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

    def command(self, cmd: str, timeout: float = 3.0):
        """Run 'ot <cmd>' and return the response lines (without echo/Done)."""
        full = f"ot {cmd}"
        self.ser.write((full + "\r\n").encode())
        self.ser.flush()

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
