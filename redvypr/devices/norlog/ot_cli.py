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
from collections import deque

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
    """
    Splits a byte stream into cleaned text lines.

    Lines that a consumer has not taken yet (e.g. lines after "Done" in the
    same read) stay in 'pending' for the next consumer, so nothing is lost.
    """

    def __init__(self):
        self._buf = bytearray()
        self.pending = deque()

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
        self.pending.clear()

    def read_line(self, ser, deadline: float):
        """Next line (pending first), reading from ser until the monotonic deadline."""
        while True:
            if self.pending:
                return self.pending.popleft()
            if time.monotonic() >= deadline:
                return None
            self.pending.extend(self.feed(ser.read(512)))

    def drain(self, ser):
        """All pending lines plus whatever is available now (non-blocking-ish)."""
        self.pending.extend(self.feed(ser.read(512)))
        lines = list(self.pending)
        self.pending.clear()
        return lines


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

    # Lines up to this length go out in one piece: the shell RX ring buffer of the
    # firmware holds 1024 (since 0.4.0) or 2048 bytes. Longer lines are paced.
    WRITE_UNPACED_MAX = 900

    def write_line(self, text: str):
        """Send a line; very long lines in small chunks so they do not overrun the shell RX buffer."""
        data = (text + "\r\n").encode()
        if len(data) <= self.WRITE_UNPACED_MAX:
            self.ser.write(data)
            self.ser.flush()
            return
        for i in range(0, len(data), 32):
            self.ser.write(data[i:i + 32])
            self.ser.flush()
            time.sleep(0.005)

    def command(self, cmd: str, timeout: float = 3.0):
        """Run 'ot <cmd>' and return the response lines (without echo/Done)."""
        full = f"ot {cmd}"
        self.write_line(full)

        result = []
        end = time.monotonic() + timeout
        while True:
            line = self.reader.read_line(self.ser, end)
            if line is None:
                raise TimeoutError(f"'{full}': no 'Done' within {timeout} s")
            if LOG_RE.match(line) or line.startswith("#NLD "):
                self.on_line(line, False)     # asynchronous output, not part of the response
                continue
            self.on_line(line, True)
            if line.endswith(full):
                continue                      # echo of the command
            if line == "Done":
                return result                 # later lines stay pending
            if line.startswith("Error"):
                raise OtError(f"'{full}': {line}")
            result.append(line)

    def value(self, cmd: str) -> str:
        lines = self.command(cmd)
        return lines[0].strip() if lines else ""

    def wait_line(self, match, timeout: float):
        """Wait for a line for which match(line) is true; other lines go to on_line."""
        end = time.monotonic() + timeout
        while True:
            line = self.reader.read_line(self.ser, end)
            if line is None:
                return None
            if match(line):
                return line
            self.on_line(line, False)

    def shell_query(self, cmd: str, prefix: str, timeout: float = 4.0) -> str:
        """Send a (non-ot) shell command and return the text after 'prefix' of its answer line."""
        self.write_line(cmd)
        end = time.monotonic() + timeout
        while True:
            line = self.reader.read_line(self.ser, end)
            if line is None:
                raise TimeoutError(f"'{cmd}': no '{prefix.strip()}' answer within {timeout} s")
            if line.startswith(prefix):
                self.on_line(line, True)
                return line[len(prefix):]
            # Echo of the command belongs to the response, everything else is asynchronous output
            self.on_line(line, line.endswith(cmd))


COAP_PREFIX = "#NLC "


def parse_coap_line(rest: str):
    """
    Parse the answer of 'norlog coap get' (without the '#NLC ' prefix):
        ok <addr> <code> txt|hex[+] <payload>
        err <addr> <code|timeout|...> [...]
    Returns (ok, code, payload_bytes, truncated).
    """
    parts = rest.split(" ", 4)
    if len(parts) < 3:
        raise OtError(f"malformed CoAP answer: {rest!r}")
    status, _addr, code = parts[0], parts[1], parts[2]
    fmt = parts[3] if len(parts) > 3 else ""
    payload = parts[4] if len(parts) > 4 else ""
    truncated = fmt.endswith("+")
    fmt = fmt.rstrip("+")
    if fmt == "hex":
        data = bytes.fromhex(payload.strip())
    else:
        data = payload.encode()
    return status == "ok", code, data, truncated


def coap_get(cli: OtCli, address: str, uri: str, timeout: float = 10.0) -> bytes:
    """
    CoAP GET through the gateway firmware ('norlog coap get'): the gateway
    waits for the response and prints it as one line, so nothing is lost
    (unlike the asynchronous output of 'ot coap get').
    """
    try:
        rest = cli.shell_query(f"norlog coap get {address} {uri} {int(timeout)}", COAP_PREFIX,
                               timeout=timeout + 4.0)
    except TimeoutError as exc:
        raise TimeoutError(f"{exc} (gateway firmware with 'norlog coap get' required)") from None
    ok, code, data, truncated = parse_coap_line(rest)
    if not ok:
        raise OtError(f"CoAP GET {uri} from {address}: {code} {data.decode(errors='replace')}".strip())
    if truncated:
        raise OtError(f"CoAP GET {uri} from {address}: response truncated by the gateway")
    return data


def coap_request(cli: OtCli, method: str, address: str, uri: str, payload: bytes = b"",
                 timeout: float = 10.0, b64: bool = False) -> bytes:
    """
    CoAP GET/PUT/POST/DELETE through the gateway ('norlog coap <method>').
    uri may contain a query: 'fs?op=ls&p=/fw'. Raises OtError on a non-2.xx code.
    b64: send the payload as "b64:<base64>" (gateway firmware >= 0.4.1) instead of hex.
    """
    import base64
    method = method.lower()
    if method == "get":
        cmd = f"norlog coap get {address} {uri} {int(timeout)}"
    elif method == "delete":
        cmd = f"norlog coap delete {address} {uri} {int(timeout)}"
    else:
        if not payload:
            data = "-"
        elif b64:
            data = "b64:" + base64.b64encode(payload).decode()
        else:
            data = payload.hex()
        cmd = f"norlog coap {method} {address} {uri} {data} {int(timeout)}"
    rest = cli.shell_query(cmd, COAP_PREFIX, timeout=timeout + 4.0)
    ok, code, data, truncated = parse_coap_line(rest)
    if not ok and code == "4.04" and not data:
        # Without text the node's CoAP stack itself answered: the resource does not exist
        resource = uri.split("?", 1)[0]
        raise OtError(f"CoAP {method.upper()} {uri} at {address}: the node has no '{resource}' service "
                      f"(firmware too old? Update it once over serial or SD card)")
    if not ok:
        raise OtError(f"CoAP {method.upper()} {uri} at {address}: {code} {data.decode(errors='replace')}".strip())
    if truncated:
        raise OtError(f"CoAP {method.upper()} {uri} at {address}: response truncated by the gateway")
    return data


# --- Files on the SD card: local (gateway shell) and remote (CoAP 'fs') ---

FS_PREFIX = "#NLF "
FS_LOCAL_CHUNK = 512        # bytes per 'norlog fs write' line (684 base64 chars, shell buffer 1024)
FS_LOCAL_CHUNK_OLD = 384    # gateway firmware 0.4.0 (shell buffer 640)
FS_DIRECT_CHUNK = 512       # bytes per 'norlog coap put' with base64 payload (firmware >= 0.4.1)
FS_DIRECT_CHUNK_OLD = 240   # hex payload, gateway firmware 0.4.0
FS_REMOTE_CHUNK = 512       # bytes per CoAP read
FS_CRC_MAX = 64 * 1024


def _fs_quote(path: str) -> str:
    if not path.startswith("/") or ".." in path or any(c in path for c in ' &=?"\\'):
        raise ValueError(f"invalid path {path!r} (absolute, no spaces or &=?\"\\)")
    return path


def fs_local(cli: OtCli, *args, timeout: float = 10.0):
    """Run 'norlog fs <args>' on the gateway; returns the parsed JSON (or base64 text for read)."""
    import json
    rest = cli.shell_query("norlog fs " + " ".join(str(a) for a in args), FS_PREFIX, timeout=timeout)
    if rest.startswith("err"):
        raise OtError(f"norlog fs {args[0]}: {rest[4:]}")
    if args[0] == "read":
        return rest
    return json.loads(rest)


def _retry_garbled(fn, attempts: int = 3):
    """
    Repeat a CoAP file request whose answer line could not be parsed (e.g. a log
    message of an older gateway firmware inside the line). The file requests are
    idempotent: reading, or writing the same block at the same offset again.
    """
    for attempt in range(attempts):
        try:
            return fn()
        except ValueError:      # json.JSONDecodeError, bad hex
            if attempt == attempts - 1:
                raise OtError("unreadable answer from the gateway (repeated)") from None


def fs_remote(cli: OtCli, address: str, op: str, path: str, timeout: float = 10.0, **params):
    """CoAP file operation on a member: op in stat, ls, crc, mkdir, rm (JSON answer)."""
    import json
    query = f"fs?op={op}&p={_fs_quote(path)}" + "".join(f"&{k}={v}" for k, v in params.items())
    method = "post" if op in ("mkdir", "rm") else "get"
    return _retry_garbled(lambda: json.loads(coap_request(cli, method, address, query, timeout=timeout).decode()))


def fs_list(cli: OtCli, address, path: str):
    """Directory listing (address None = gateway itself); follows 'next' for long directories."""
    entries, start = [], 0
    while True:
        res = (fs_local(cli, "ls", _fs_quote(path), start) if address is None
               else fs_remote(cli, address, "ls", path, i=start))
        entries.extend(res.get("entries", []))
        start = res.get("next", 0)
        if not start:
            return entries


def fs_crc(cli: OtCli, address, path: str, off: int = 0, length: int = None):
    """
    CRC32 (zlib) of a file or of the range [off, off+length): (crc, file size).
    address None = gateway itself.
    """
    if address is None:
        args = ["crc", _fs_quote(path)]
        if off or length is not None:
            args += [off, length if length is not None else 0xFFFFFFFF]
        res = fs_local(cli, *args, timeout=60.0)
        return int(res["crc"], 16), res["size"]
    if length == 0:
        return 0, fs_remote(cli, address, "stat", path)["size"]
    crc, done, size = 0, 0, 0
    while True:
        want = FS_CRC_MAX if length is None else min(FS_CRC_MAX, length - done)
        if want <= 0:
            return crc, size
        res = fs_remote(cli, address, "crc", path, off=off + done, len=want, seed=f"0x{crc:08x}")
        crc, size = int(res["crc"], 16), res["size"]
        done += res["n"]
        if res["n"] < want or (length is None and off + done >= size):
            return crc, size


def fs_write_block(cli: OtCli, address, path: str, off: int, data: bytes, trunc: bool = False,
                   b64: bool = False, total: int = None) -> int:
    """
    Write one block at off (overwrite or append, no holes). trunc cuts the file to off
    first (off=0: new empty file). Max. FS_LOCAL_CHUNK (gateway) / FS_DIRECT_CHUNK with
    b64 resp. FS_DIRECT_CHUNK_OLD as hex (member, limited by the gateway's shell line).
    Returns the new file size.
    """
    import base64
    import json
    if address is None:
        args = ["write", _fs_quote(path), off, base64.b64encode(data).decode() if data else "-"]
        res = fs_local(cli, *(args + ["trunc"] if trunc else args))
    else:
        uri = (f"fs?op=write&p={_fs_quote(path)}&off={off}" + (f"&tot={total}" if total else "")
               + ("&trunc=1" if trunc else ""))
        res = _retry_garbled(lambda: json.loads(
            coap_request(cli, "put", address, uri, data, timeout=8.0, b64=b64).decode()))
    return res["size"]


def fs_read_block(cli: OtCli, address, path: str, off: int, length: int) -> bytes:
    """Read one block (max. FS_LOCAL_CHUNK from the gateway, FS_REMOTE_CHUNK from a member)."""
    import base64
    if address is None:
        text = fs_local(cli, "read", _fs_quote(path), off, min(length, FS_LOCAL_CHUNK))
        return b"" if text == "-" else base64.b64decode(text)
    return _retry_garbled(lambda: coap_request(cli, "get", address,
                        f"fs?op=read&p={_fs_quote(path)}&off={off}&len={min(length, FS_REMOTE_CHUNK)}"))


def _resume_offset(cli: OtCli, address, path: str, data: bytes) -> int:
    """Length of the already present, matching beginning of the file (0 if none)."""
    import zlib
    try:
        st = (fs_local(cli, "stat", _fs_quote(path)) if address is None
              else fs_remote(cli, address, "stat", path))
    except OtError:
        return 0
    have = st.get("size", 0) if st.get("type") == "file" else 0
    if have == 0 or have > len(data):
        return 0
    crc, _ = fs_crc(cli, address, path, 0, have)
    return have if crc == zlib.crc32(data[:have]) else 0


def fs_upload(cli: OtCli, address, data: bytes, path: str, progress=None, resume: bool = True,
              chunk: int = None) -> int:
    """
    Write a whole file block by block (gateway: 'norlog fs write', member: CoAP PUT through
    the gateway) and verify the CRC. resume: continue after the matching beginning of an
    existing file. Returns the number of bytes skipped by resuming.
    """
    import zlib
    # Large blocks need gateway firmware >= 0.4.1 (shell buffer 1024, base64 payload);
    # an older gateway rejects the truncated line -> fall back once to the small blocks
    big = chunk is None and getattr(cli, "fs_big_blocks", True)
    if chunk is None:
        if address is None:
            chunk = FS_LOCAL_CHUNK if big else FS_LOCAL_CHUNK_OLD
        else:
            chunk = FS_DIRECT_CHUNK if big else FS_DIRECT_CHUNK_OLD
    if address is not None and path.count("/") > 1:
        fs_remote(cli, address, "mkdir", path.rsplit("/", 1)[0])
    start = _resume_offset(cli, address, path, data) if resume else 0
    off, first = start, True
    while off < len(data) or first:
        block = data[off:off + chunk]
        try:
            # first block: cut the rest of an older, longer file
            size = fs_write_block(cli, address, path, off, block, trunc=first, b64=big and address is not None,
                                  total=len(data))
            if size < off + len(block):
                # line cut by an older gateway (shell buffer 640), but still valid base64
                raise OtError(f"invalid: block at {off} written incompletely ({size - off}/{len(block)} bytes)")
        except OtError as exc:
            if not (big and first and "invalid" in str(exc)):
                raise
            cli.fs_big_blocks = big = False
            chunk = FS_LOCAL_CHUNK_OLD if address is None else FS_DIRECT_CHUNK_OLD
            continue
        first = False
        off += len(block)
        if progress:
            progress(off, len(data))
        if not block:
            break
    crc, size = fs_crc(cli, address, path)
    if size != len(data) or crc != zlib.crc32(data):
        raise OtError(f"upload to {path}: verification failed (size {size}/{len(data)}, "
                      f"crc 0x{crc:08x}/0x{zlib.crc32(data):08x})")
    return start


def fs_upload_local(cli: OtCli, data: bytes, path: str, progress=None, resume: bool = True) -> int:
    """Write data to a file on the gateway's SD card and verify the CRC (see fs_upload)."""
    return fs_upload(cli, None, data, path, progress, resume)


def fs_download(cli: OtCli, address, path: str, progress=None) -> bytes:
    """Read a whole file (address None = gateway) and verify its CRC."""
    import zlib
    st = (fs_local(cli, "stat", _fs_quote(path)) if address is None
          else fs_remote(cli, address, "stat", path))
    if st.get("type") != "file":
        raise OtError(f"{path} is not a file")
    size, data = st["size"], bytearray()
    while len(data) < size:
        chunk = fs_read_block(cli, address, path, len(data), FS_REMOTE_CHUNK)
        if not chunk:
            break
        data.extend(chunk)
        if progress:
            progress(len(data), size)
    crc, _ = fs_crc(cli, address, path)
    if len(data) != size or crc != zlib.crc32(bytes(data)):
        raise OtError(f"download of {path}: verification failed")
    return bytes(data)


def fs_push(cli: OtCli, address: str, local: str, remote: str, progress=None, stall_timeout: float = 30.0,
            off: int = None, length: int = None, resume: bool = False):
    """
    Let the gateway send a file (or the range off/length) from its own SD card to a
    member ('norlog fs push'). resume: continue after the matching beginning on the
    member. The gateway verifies the CRC. Returns the result dict
    {"off","len","size","crc","resumed","seconds"}.
    """
    import json
    cmd = f"norlog fs push {address} {_fs_quote(local)} {_fs_quote(remote)}"
    if off is not None:
        cmd += f" -o {off}"
    if length is not None:
        cmd += f" -n {length}"
    if resume:
        cmd += " -r"
    cli.write_line(cmd)
    resumed = 0
    while True:
        line = cli.wait_line(lambda l: l.startswith(FS_PREFIX), stall_timeout)
        if line is None:
            raise TimeoutError(f"'{cmd}': no progress for {stall_timeout:.0f} s")
        cli.on_line(line, True)
        rest = line[len(FS_PREFIX):]
        if rest.startswith("resume "):
            resumed = int(rest.split()[1])
        elif rest.startswith("progress "):
            done, total = (int(x) for x in rest.split()[1:3])
            if progress:
                progress(done, total)
        elif rest.startswith("ok "):
            res = json.loads(rest[3:])
            res.setdefault("resumed", resumed)
            return res
        elif rest.startswith("err"):
            raise OtError(f"push to {address}: {rest[4:]}")


def fw_status_remote(cli: OtCli, address: str) -> dict:
    import json
    return json.loads(coap_request(cli, "get", address, "fw").decode())


# --- User properties (sn, desc, loc, ...; firmware >= 0.4.3) ---

PROP_PREFIX = "#NLP "
PROP_SN_MAX = 64
PROP_VALUE_MAX = 256
STANDARD_PROPS = ("sn", "desc", "loc")


def _prop_check(name: str, value: str) -> bytes:
    if not re.fullmatch(r"[a-z0-9_]{1,16}", name or ""):
        raise ValueError(f"invalid property name {name!r} (a-z, 0-9, _, max. 16)")
    data = value.encode()
    limit = PROP_SN_MAX if name == "sn" else PROP_VALUE_MAX
    if len(data) > limit:
        raise ValueError(f"{name}: max. {limit} bytes ({len(data)} given)")
    if any(b < 0x20 for b in data):
        raise ValueError(f"{name}: no control characters (line breaks) allowed")
    return data


def props_read(cli: OtCli, address=None) -> dict:
    """All properties of the gateway (address None) or of a member."""
    import json
    if address is None:
        rest = cli.shell_query("norlog prop json", PROP_PREFIX, timeout=2.0)
        if rest.startswith("err"):
            raise OtError(f"norlog prop json: {rest}")
        return json.loads(rest)
    return _retry_garbled(lambda: json.loads(coap_request(cli, "get", address, "prop").decode()))


def props_write(cli: OtCli, name: str, value: str, address=None):
    """Set a property (empty value deletes it) on the gateway or a member; stored on the device."""
    import base64
    data = _prop_check(name, value)
    if address is None:
        # base64: any characters (UTF-8, quotes) pass the shell unchanged
        payload = base64.b64encode(data).decode() if data else "-"
        rest = cli.shell_query(f"norlog prop setb64 {name} {payload}", PROP_PREFIX, timeout=5.0)
        if not rest.startswith("ok"):
            raise OtError(f"{name}: {rest}")
        return
    coap_request(cli, "post", address, f"prop?n={name}", data, b64=getattr(cli, "fs_big_blocks", True))


def fw_install_remote(cli: OtCli, address: str) -> dict:
    import json
    return json.loads(coap_request(cli, "post", address, "fw?op=install").decode())


BATTERY_PREFIX = "#NLB "
BATTERY_CHUNK = 160     # bytes of .inc text per line (320 hex chars, shell buffer 416)


def upload_battery_model(cli: OtCli, inc_text: str, progress=None) -> str:
    """
    Load a battery model (.inc from nPM PowerUP) into a norlog over the shell
    ('norlog battery inc begin|<hex>|end'). The firmware parses, stores and
    activates it as model 'custom'. Returns the model name.
    progress: optional callback(done_bytes, total_bytes)
    """
    data = inc_text.encode()

    def query(cmd):
        answer = cli.shell_query(cmd, BATTERY_PREFIX, timeout=5.0)
        if not answer.startswith("ok"):
            raise OtError(f"battery model upload: {answer}")
        return answer

    query("norlog battery inc begin")
    try:
        for off in range(0, len(data), BATTERY_CHUNK):
            query("norlog battery inc " + data[off:off + BATTERY_CHUNK].hex())
            if progress:
                progress(min(off + BATTERY_CHUNK, len(data)), len(data))
    except Exception:
        try:
            cli.shell_query("norlog battery inc abort", BATTERY_PREFIX, timeout=2.0)
        except TimeoutError:
            pass
        raise
    return query("norlog battery inc end")[len("ok end"):].strip()


def rloc_address(mesh_local_prefix: str, rloc16: str) -> str:
    """Mesh-local RLOC address: <prefix>:0:ff:fe00:<rloc16>."""
    import ipaddress
    parts = (mesh_local_prefix or "").strip().split()
    if not parts:
        raise ValueError("no mesh-local prefix (Thread not running?)")
    net = ipaddress.IPv6Network(parts[0], strict=False)
    rloc = int(str(rloc16), 16)
    iid = (0x00ff << 32) | (0xfe00 << 16) | rloc
    return str(ipaddress.IPv6Address(int(net.network_address) | iid))


def mesh_local_prefix(cli: OtCli, ipaddrs=None) -> str:
    """
    Mesh-local prefix (e.g. 'fd1e:48dd:8e5f:397f::/64'). Taken from the own RLOC
    address (<prefix>:0:ff:fe00:xxxx) if known; otherwise asked with
    'ot prefix meshlocal' (newer OpenThread) or 'ot meshlocalprefix' (older).
    """
    import ipaddress
    for a in ipaddrs or []:
        try:
            addr = int(ipaddress.IPv6Address(a.strip()))
        except ValueError:
            continue
        if (addr >> 16) & 0xFFFFFFFFFFFF == 0x0000_00FF_FE00 and (addr >> 120) == 0xFD:
            return str(ipaddress.IPv6Network((addr >> 64 << 64, 64)))
    for cmd in ("prefix meshlocal", "meshlocalprefix"):
        try:
            value = cli.value(cmd)
        except OtError:
            continue
        if value:
            return value
    raise ValueError("no mesh-local prefix (Thread not running?)")


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
