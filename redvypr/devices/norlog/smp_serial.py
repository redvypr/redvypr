"""
MCUmgr/SMP over a serial port, used to flash norlog firmware via the
norlog_loader (MCUboot firmware-loader image).

Port of tools/uart_update.py from the norlog firmware repository, adapted
to work on an already opened serial.Serial object and to report progress
through callbacks. Framing follows Zephyr's
subsys/mgmt/mcumgr/transport/src/serial_util.c.
"""

import base64
import hashlib
import struct
import time

from . import cbor_mini

OP_READ, OP_WRITE = 0, 2
SMP_VERSION = 1                     # SMP v2 (errors as {"err": {...}})
GROUP_OS, GROUP_IMAGE = 0, 1
CMD_OS_ECHO, CMD_OS_RESET = 0, 5
CMD_IMG_STATE, CMD_IMG_UPLOAD = 0, 1

HDR_PKT = b"\x06\x09"
HDR_FRAG = b"\x04\x14"
MAX_FRAME = 127
RAW_PER_FRAME = ((MAX_FRAME - 3) // 4) * 3     # 93 bytes -> 124 base64 chars

# norlog_loader uses the default SMP UART MTU of 256 bytes
DEFAULT_CHUNK = 176

IMAGE_MAGIC = 0x96F3B83D
TLV_INFO_MAGIC = 0x6907
TLV_PROT_INFO_MAGIC = 0x6908
TLV_SHA256 = 0x10


class SmpError(Exception):
    pass


class SmpCancelled(Exception):
    pass


def crc16_xmodem(data: bytes) -> int:
    """CRC-16/XMODEM (= Zephyr crc16_itu_t with seed 0)."""
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def encode_frames(packet: bytes) -> bytes:
    raw = struct.pack(">H", len(packet) + 2) + packet + struct.pack(">H", crc16_xmodem(packet))
    out = bytearray()
    for i in range(0, len(raw), RAW_PER_FRAME):
        out += HDR_PKT if i == 0 else HDR_FRAG
        out += base64.b64encode(raw[i:i + RAW_PER_FRAME])
        out += b"\n"
    return bytes(out)


def image_info(image: bytes) -> dict:
    """Parse the MCUboot header of a signed image (version, size, SHA-256 hash)."""
    if len(image) < 32 or struct.unpack("<I", image[:4])[0] != IMAGE_MAGIC:
        raise ValueError("not a signed MCUboot image (use zephyr.signed.bin)")
    major, minor, rev, build = struct.unpack("<BBHI", image[20:28])
    return {
        "version": f"{major}.{minor}.{rev}+{build}",
        "size": len(image),
        "hash": image_hash(image),
    }


def image_hash(image: bytes):
    """SHA-256 from the image TLVs (the value MCUmgr reports for a slot)."""
    hdr_size, _, img_size = struct.unpack("<HHI", image[8:16])
    off = hdr_size + img_size
    magic, tlv_len = struct.unpack("<HH", image[off:off + 4])
    if magic == TLV_PROT_INFO_MAGIC:
        off += tlv_len
        magic, tlv_len = struct.unpack("<HH", image[off:off + 4])
    if magic != TLV_INFO_MAGIC:
        return None
    end = off + tlv_len
    off += 4
    while off + 4 <= end:
        t, length = struct.unpack("<HH", image[off:off + 4])
        if t == TLV_SHA256 and length == 32:
            return bytes(image[off + 4:off + 36])
        off += 4 + length
    return None


class SmpSerial:
    """SMP client on an already opened serial.Serial object."""

    def __init__(self, ser, text_callback=None):
        """
        Args:
            ser: open serial.Serial (a short read timeout, e.g. 0.05 s, is expected)
            text_callback: called with every non-SMP text line (e.g. MCUboot boot messages)
        """
        self.ser = ser
        self.seq = 0
        self.text_callback = text_callback
        self._line = bytearray()
        self._rx = bytearray()
        self._rx_len = None

    def write_text(self, text: str):
        self.ser.write(text.encode())
        self.ser.flush()

    def drain(self, duration: float = 0.0):
        """Read and discard (forward as text) incoming data for 'duration' seconds."""
        end = time.monotonic() + duration
        while True:
            data = self.ser.read(4096)
            for b in data:
                if b == 0x0A:
                    self._text(bytes(self._line))
                    self._line.clear()
                else:
                    self._line.append(b)
            if time.monotonic() >= end and not data:
                break
        self._rx.clear()
        self._rx_len = None

    def _text(self, line: bytes):
        if self.text_callback is not None and line and HDR_PKT not in line and HDR_FRAG not in line:
            self.text_callback(line.decode(errors="replace").rstrip("\r"))

    def _feed_line(self, line: bytes):
        pos_pkt = line.find(HDR_PKT)
        pos_frag = line.find(HDR_FRAG)

        if pos_pkt >= 0:
            frag, first = line[pos_pkt + 2:], True
        elif pos_frag >= 0 and self._rx_len is not None:
            frag, first = line[pos_frag + 2:], False
        else:
            self._text(line)
            return None

        try:
            data = base64.b64decode(frag.strip(), validate=False)
        except ValueError:
            self._rx.clear()
            self._rx_len = None
            return None

        if first:
            if len(data) < 2:
                return None
            self._rx = bytearray(data[2:])
            self._rx_len = struct.unpack(">H", data[:2])[0]
        else:
            self._rx += data

        if len(self._rx) < self._rx_len:
            return None

        pkt = bytes(self._rx[:self._rx_len])
        self._rx.clear()
        self._rx_len = None
        if len(pkt) < 10 or crc16_xmodem(pkt) != 0:
            return None
        return pkt[:-2]

    def request(self, op: int, group: int, cmd_id: int, payload: dict, timeout: float) -> dict:
        body = cbor_mini.dumps(payload)
        self.seq = (self.seq + 1) & 0xFF
        hdr = struct.pack(">BBHHBB", (SMP_VERSION << 3) | op, 0, len(body), group, self.seq, cmd_id)
        self.ser.write(encode_frames(hdr + body))
        self.ser.flush()

        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for b in self.ser.read(256):
                if b != 0x0A:
                    self._line.append(b)
                    if len(self._line) > 1024:
                        self._line.clear()
                    continue
                pkt = self._feed_line(bytes(self._line))
                self._line.clear()
                if pkt is None:
                    continue
                _, _, r_len, r_group, r_seq, r_id = struct.unpack(">BBHHBB", pkt[:8])
                if r_seq != self.seq or r_group != group or r_id != cmd_id:
                    continue
                rsp = cbor_mini.loads(pkt[8:8 + r_len]) if r_len else {}
                if not isinstance(rsp, dict):
                    raise SmpError(f"unexpected response {rsp!r}")
                err = rsp.get("err")
                if isinstance(err, dict) and err.get("rc", 0) != 0:
                    raise SmpError(f"group {err.get('group')} rc={err.get('rc')}")
                if rsp.get("rc", 0) != 0:
                    raise SmpError(f"rc={rsp['rc']}")
                return rsp
        raise TimeoutError

    # --- commands ---

    def echo(self, timeout: float = 0.5) -> bool:
        try:
            return self.request(OP_WRITE, GROUP_OS, CMD_OS_ECHO, {"d": "norlog"}, timeout).get("r") == "norlog"
        except (TimeoutError, SmpError):
            return False

    def image_state(self) -> list:
        return self.request(OP_READ, GROUP_IMAGE, CMD_IMG_STATE, {}, timeout=3.0).get("images", [])

    def reset(self):
        try:
            self.request(OP_WRITE, GROUP_OS, CMD_OS_RESET, {}, timeout=2.0)
        except TimeoutError:
            pass

    def wait_for_loader(self, timeout: float, cancel=None) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cancel is not None and cancel():
                raise SmpCancelled()
            self.drain(0.3)
            if self.echo(timeout=0.7):
                return True
        return False

    def enter_loader(self, timeout: float = 20.0, cancel=None) -> bool:
        """Ask the running norlog app to reboot into the loader ('norlog dfu')."""
        self.drain(0.2)
        if self.echo():
            return True
        self.write_text("\r\nnorlog dfu\r\n")
        return self.wait_for_loader(timeout, cancel)

    def upload(self, image: bytes, chunk: int = DEFAULT_CHUNK, progress=None, cancel=None):
        """
        Upload a signed image to slot 0.

        Args:
            progress: callback(offset, size)
            cancel: callable returning True to abort the upload
        """
        size = len(image)
        sha = hashlib.sha256(image).digest()
        off = 0
        while off < size:
            if cancel is not None and cancel():
                raise SmpCancelled()
            req = {"off": off, "data": image[off:off + chunk]}
            if off == 0:
                req.update({"image": 0, "len": size, "sha": sha})
                timeout = 60.0      # first packet erases slot 0 (nRF52: up to ~20 s)
            else:
                timeout = 5.0
            for _ in range(5):
                try:
                    rsp = self.request(OP_WRITE, GROUP_IMAGE, CMD_IMG_UPLOAD, req, timeout)
                    break
                except TimeoutError:
                    self.drain(0.2)
            else:
                raise SmpError(f"upload aborted at offset {off}")
            off = rsp.get("off", off + len(req["data"]))
            if progress is not None:
                progress(off, size)
