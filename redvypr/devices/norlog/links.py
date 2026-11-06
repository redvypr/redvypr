"""
Ways (links) from redvypr to a norlog, see the design note doc/design_verbindungen.md of the
norlog firmware.

A link knows how to reach one norlog:

- SerialLink: the Zephyr shell of a norlog at a serial port (commands 'norlog ...')
- ThreadLink: CoAP to a member of the Thread network, sent by the shell of a gateway norlog
  ('norlog coap ...' on the gateway)

Both carry the OtCli of the serial port they use and the address of the norlog (None for the
norlog at the port itself), so the functions of ot_cli that take (cli, ..., address) work with
either of them. Operations that differ between the shell and CoAP (the *_local / *_remote pairs
of ot_cli) are methods of the link.
"""

import json

from . import ot_cli

KIND_SERIAL = "serial"
KIND_THREAD = "thread"


class Link:
    kind = ""

    def __init__(self, cli, address=None, port=""):
        self.cli = cli
        self.address = address      # None: the norlog at the serial port itself
        self.port = port            # serial port used (of the gateway for a ThreadLink)

    @property
    def is_local(self):
        return self.address is None

    def __repr__(self):
        return f"{type(self).__name__}({self.port!r}{', ' + repr(self.address) if self.address else ''})"

    # --- the *_local / *_remote pairs of ot_cli ---

    def info(self, timeout=10.0):
        """Device info: the whole 'norlog info json' (shell) or the CoAP info (compact from 0.4.50)."""
        raise NotImplementedError

    def fs_op(self, op, path):
        """File operation without data: stat, mkdir, rm (JSON answer)."""
        raise NotImplementedError

    def fs_upload(self, data, path, progress=None, resume=True):
        """Write a file block by block (CRC verified); returns the bytes skipped by resuming."""
        return ot_cli.fs_upload(self.cli, self.address, data, path, progress, resume=resume)

    def sd_status(self):
        raise NotImplementedError

    def sd_op(self, op, name="", progress=None):
        """Archive or delete the log files, format the SD card; waits for the result."""
        raise NotImplementedError

    def fw_status(self):
        raise NotImplementedError

    def fw_loader(self):
        """Write /fw/loader.bin of the SD card to slot1 and wait for the result."""
        raise NotImplementedError


class SerialLink(Link):
    """The shell of the norlog at a serial port."""
    kind = KIND_SERIAL

    def __init__(self, cli, port=""):
        super().__init__(cli, None, port)

    def info(self, timeout=10.0):
        return json.loads(self.cli.shell_query("norlog info json", "#NLI ", timeout=timeout))

    def fs_op(self, op, path):
        return ot_cli.fs_local(self.cli, op, ot_cli._fs_quote(path))

    def fs_upload(self, data, path, progress=None, resume=True):
        return ot_cli.fs_upload_local(self.cli, data, path, progress, resume=resume)

    def sd_status(self):
        return ot_cli.sd_status_local(self.cli)

    def sd_op(self, op, name="", progress=None):
        return ot_cli.sd_op_local(self.cli, op, name, progress=progress)

    def fw_status(self):
        return ot_cli.fw_status_local(self.cli)

    def fw_loader(self):
        return ot_cli.fw_loader_local(self.cli)


class ThreadLink(Link):
    """CoAP to a Thread member through the shell of a gateway norlog (its SerialLink)."""
    kind = KIND_THREAD

    def __init__(self, gateway, address):
        if not address:
            raise ValueError("ThreadLink needs the IPv6 address of the member")
        super().__init__(gateway.cli, address, gateway.port)
        self.gateway = gateway

    def has_gateway_sd(self):
        """True if the gateway has a mounted SD card (for 'norlog fs push', faster)."""
        try:
            self.gateway.fs_op("stat", "/")
            return True
        except (ot_cli.OtError, TimeoutError):
            return False

    def push(self, data, path, progress=None, tmp="/fw/xfer.tmp", keep=False):
        """
        Write a file to the member through the SD card of the gateway: PC -> tmp on the gateway
        (skipped if it holds the same data, CRC), then 'norlog fs push' over Thread (resumed).
        progress(phase, done, total) with phase 'gateway', 'cached' (once: the gateway has the
        data already) or 'thread'. keep: leave tmp on the
        gateway (an image sent to several members). Returns the result of the push.
        """
        import zlib
        self.gateway.fs_op("mkdir", "/fw")
        try:
            crc, size = ot_cli.fs_crc(self.cli, None, tmp)
        except ot_cli.OtError:
            crc, size = None, None
        if size == len(data) and crc == zlib.crc32(data):
            if progress:
                progress("cached", len(data), len(data))
        else:
            self.gateway.fs_upload(data, tmp, (lambda d, t: progress("gateway", d, t)) if progress else None)
        res = ot_cli.fs_push(self.cli, self.address, tmp, path,
                             (lambda d, t: progress("thread", d, t)) if progress else None, resume=True)
        if not keep:
            self.gateway.fs_op("rm", tmp)
        return res

    def info(self, timeout=10.0):
        payload = ot_cli.coap_get(self.cli, self.address, "info", timeout=timeout)
        return json.loads(payload.decode(errors="replace"))

    def extinfo(self, timeout=10.0):
        """Rarely changing part of the info (firmware >= 0.4.50)."""
        payload = ot_cli.coap_get(self.cli, self.address, "extinfo", timeout=timeout)
        return json.loads(payload.decode(errors="replace"))

    def fs_op(self, op, path):
        return ot_cli.fs_remote(self.cli, self.address, op, path)

    def sd_status(self):
        return ot_cli.sd_status_remote(self.cli, self.address)

    def sd_op(self, op, name="", progress=None):
        return ot_cli.sd_op_remote(self.cli, self.address, op, name, progress=progress)

    def fw_status(self):
        return ot_cli.fw_status_remote(self.cli, self.address)

    def fw_loader(self):
        return ot_cli.fw_loader_remote(self.cli, self.address)

    def fw_install(self):
        """Install /fw/update.bin (POST fw?op=install): the member reboots into its loader."""
        return ot_cli.fw_install_remote(self.cli, self.address)
