"""
Save the data packets of the norlog gateway ('#NLD', live data over Thread) in the
device thread, independent of the redvypr data distribution. Several channels can
be configured (save_channels of the gateway configuration), each one has a type:

    sqlite  SQLite database in the redvypr format (redvypr SQLite engine DbSqlite,
            table data_flat, metadata in redvypr_metadata), every value once
            (skip_duplicates).

The packets are saved as the gateway publishes them: device norlog_<sn>, deviceid =
hardware ID, packetid = packet type, host = this redvypr instance, publisher = the
gateway device; a redvypr SQLite writer subscribing to the gateway writes the same
columns.

A channel saves all packet types or the chosen ones (names of ot_cli.PACKET_TYPES,
adcseq packets by their base type), into one continued file or a new file every
N hours/days. More types: a pydantic model with its own channel_type and a writer
class in WRITERS.
"""

import logging
import pathlib
import time
import typing

import pydantic

from . import norlog_cbor
from .norlog_convert import _add_metadata, _stored_metadata

logger = logging.getLogger('redvypr.device.norlog_save')


class SaveChannelSqlite(pydantic.BaseModel):
    channel_type: typing.Literal['sqlite'] = 'sqlite'
    name: str = pydantic.Field(default='SQLite', description='Name of the channel')
    enabled: bool = pydantic.Field(default=True, description='Channel saves (with "Save data" on)')
    filepath: str = pydantic.Field(default='norlog_live.sqlite', description='SQLite file; with a new file every '
                                                                             'N hours/days the base name of the '
                                                                             'files (<name>_<count>_<date>)')
    new_file: typing.Literal['none', 'hours', 'days'] = pydantic.Field(default='none', description='none: one '
                                                                                                   'file, '
                                                                                                   'continued')
    dt_newfile: int = pydantic.Field(default=1, ge=1, description='New file every dt_newfile hours/days')
    packet_types: typing.List[str] = pydantic.Field(default_factory=list, description='Packet types to save, '
                                                                                      'empty = all')
    table: str = pydantic.Field(default='norlog', description='Name of the data_flat table')


# More channel types: typing.Annotated[typing.Union[...], pydantic.Field(discriminator='channel_type')]
SaveChannel = SaveChannelSqlite
CHANNEL_TYPES = {'sqlite': SaveChannelSqlite}


def channel_from_dict(d):
    return CHANNEL_TYPES[d.get('channel_type', 'sqlite')].model_validate(d)


def wants(channel, pkt):
    """Does the channel save this packet (its type)?"""
    return not channel.packet_types or norlog_cbor.base_type(pkt) in channel.packet_types


class SqliteWriter:
    """One SQLite channel: DbSqlite in the data_flat format of norlog_convert."""

    def __init__(self, channel, hostinfo):
        from redvypr.devices.db.db_engine_sqlite import DbSqlite
        self.channel = channel
        self.hostinfo = hostinfo
        self.db = DbSqlite(self.db_config(channel))
        self.metadata = {'metadata': _stored_metadata(self.db.filepath, hostinfo['uuid'])}
        self.meta_sent = set()
        self.meta_file = None
        self.packets = 0

    @staticmethod
    def db_config(ch):
        from redvypr.devices.db.db_engine_sqlite import SqliteConfig
        from redvypr.devices.db.db_config_util import DbWriteConfig, DbTableConfig
        tables = {ch.table: DbTableConfig(tablename=ch.table, tabletype='data_flat', addresses=['@'],
                                          skip_duplicates=True)}
        one = ch.new_file == 'none'
        return SqliteConfig(filepath=ch.filepath, storage='file', append_to_file=one, batch_size=500, dt_commit=2.0,
                            dt_newfile=0 if one else ch.dt_newfile, dt_newfile_unit=ch.new_file,
                            max_file_size_mb=None,
                            write_config=DbWriteConfig(tables=tables, name='norlog_live',
                                                       description='norlog live data saved by the norlog gateway'))

    def write(self, data, pkt, sn):
        """data: the published redvypr packet (copied), pkt: the decoded norlog packet (units)."""
        import redvypr.metadata
        data = dict(data)
        _add_metadata(data, pkt, sn, self.meta_sent, hostinfo=self.hostinfo)
        new_meta = '_metadata' in data
        if new_meta:
            redvypr.metadata.do_metadata(data, self.metadata)
            del data['_metadata']
        self.db.insert_packet(data)
        self.packets += 1
        if new_meta or self.meta_file != self.db.filepath:     # new metadata or a new file (rotation)
            self.write_metadata()

    def write_metadata(self):
        for address, entries in self.metadata['metadata'].items():
            self.db.add_metadata(address, self.hostinfo['uuid'], entries)
        self.meta_file = self.db.filepath

    def poll(self):
        self.db.flush_if_due()

    def close(self):
        try:
            self.write_metadata()
        finally:
            self.db.close()

    def status(self):
        st = self.db.file_statistics_total
        return {'file': str(pathlib.Path(self.db.filepath).resolve()), 'packets': self.packets,
                'values': st.get('entries_flat_written', 0),
                'duplicates': st.get('entries_duplicate_skipped', 0)}


WRITERS = {'sqlite': SqliteWriter}


class DataSaver:
    """The channels of the gateway configuration: opened with the first packet, reopened after a change."""

    def __init__(self, hostinfo):
        self.hostinfo = hostinfo    # this redvypr instance (host of the packets and the metadata)
        self.on = False
        self.channels = []          # [channel config]
        self.writers = {}           # index -> writer
        self.errors = {}            # index -> error text (channel stopped until the configuration changes)
        self.t_status = 0.0

    def configure(self, on, channels):
        channels = [c if isinstance(c, pydantic.BaseModel) else channel_from_dict(c) for c in channels]
        if on == self.on and [c.model_dump() for c in channels] == [c.model_dump() for c in self.channels]:
            return False
        self.close()
        self.on, self.channels, self.errors = bool(on), channels, {}
        return True

    def write(self, data, pkt, sn=None):
        if not self.on:
            return
        for i, ch in enumerate(self.channels):
            if not ch.enabled or i in self.errors or not wants(ch, pkt):
                continue
            try:
                writer = self.writers.get(i)
                if writer is None:
                    writer = self.writers[i] = WRITERS[ch.channel_type](ch, self.hostinfo)
                writer.write(data, pkt, sn)
            except Exception as exc:
                logger.warning(f'Save channel {ch.name}: {exc}', exc_info=True)
                self.errors[i] = str(exc)
                self._close(i)

    def poll(self):
        for i in list(self.writers):
            try:
                self.writers[i].poll()
            except Exception as exc:
                logger.warning(f'Save channel {self.channels[i].name}: {exc}', exc_info=True)
                self.errors[i] = str(exc)
                self._close(i)

    def status_due(self, interval=5.0):
        if time.monotonic() - self.t_status < interval:
            return False
        self.t_status = time.monotonic()
        return True

    def status(self):
        result = []
        for i, ch in enumerate(self.channels):
            s = {'name': ch.name, 'channel_type': ch.channel_type, 'enabled': ch.enabled, 'error': self.errors.get(i)}
            if i in self.writers:
                s.update(self.writers[i].status())
            result.append(s)
        return {'on': self.on, 'channels': result}

    def _close(self, i):
        writer = self.writers.pop(i, None)
        if writer is not None:
            try:
                writer.close()
            except Exception:
                logger.debug('Could not close save channel', exc_info=True)

    def close(self):
        for i in list(self.writers):
            self._close(i)
