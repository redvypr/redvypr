"""
Data sources: databases written by the redvypr database writers (SQLite, TimescaleDB),
read back as datastreams.

A data source is configured once in redvypr (``RedvyprConfig.datasources``, saved with
the configuration) and used by name, e.g. by the XY plot. A reader gives

- ``datastreams()``: all datastreams of the data_flat tables with their address, number
  of values and time range,
- ``get_data(address, t_start, t_end, max_points)``: time and values of all datastreams
  matching a redvypr address (e.g. ``board_temp_c @ di:'9AB6...'``), merged in time. With
  more than ``max_points`` values in the range, the values are thinned out in the database:
  minimum and maximum per time bucket (``max_points / 2`` buckets),
- ``get_metadata(address)``: the metadata stored in the database (units etc.).

    from redvypr.datasource import DataSourceConfig, open_datasource
    src = open_datasource(DataSourceConfig(name='archive', filepath='data.sqlite'))
    d = src.get_data("board_temp_c @ di:'9AB64B5C71AE5C1C'", max_points=2000)
    d['t'], d['data'], d['decimated']
"""

import dataclasses
import logging
import sqlite3
import threading
import typing

import numpy as np
import pydantic

import redvypr.metadata
from redvypr.redvypr_address import RedvyprAddress
from redvypr.serialize import deserialize_json

logger = logging.getLogger('redvypr.datasource')

# Datatypes of _redvypr_addresses_ that are numbers (can be plotted and thinned out)
NUMERIC_DATATYPES = ('int', 'float', 'bool')


class DataSourceConfig(pydantic.BaseModel):
    """A database to read from, used by its name."""
    name: str = pydantic.Field(default='database', description='Name of the data source')
    dbtype: typing.Literal['sqlite', 'timescaledb'] = pydantic.Field(default='sqlite')
    filepath: str = pydantic.Field(default='', description='sqlite: the database file')
    host: str = pydantic.Field(default='localhost', description='timescaledb: host')
    port: int = pydantic.Field(default=5432, description='timescaledb: port')
    dbname: str = pydantic.Field(default='postgres', description='timescaledb: database')
    user: str = pydantic.Field(default='postgres', description='timescaledb: user')
    password: str = pydantic.Field(default='', description='timescaledb: password')
    description: str = pydantic.Field(default='')

    def summary(self):
        if self.dbtype == 'sqlite':
            return f"{self.name} (SQLite {self.filepath})"
        return f"{self.name} (TimescaleDB {self.user}@{self.host}:{self.port}/{self.dbname})"


@dataclasses.dataclass
class Datastream:
    """One column of a data_flat table."""
    address: str            # redvypr address of the values (column name before sanitizing)
    table: str              # logical table name
    table_db: str           # table in the database
    column: str             # column in the database
    datatype: typing.Optional[str] = None
    num: typing.Optional[int] = None        # number of values (None: unknown)
    t_first: typing.Optional[float] = None
    t_last: typing.Optional[float] = None

    @property
    def numeric(self):
        return self.datatype in NUMERIC_DATATYPES

    @property
    def raddress(self):
        try:
            return self._raddress
        except AttributeError:
            self._raddress = RedvyprAddress(self.address)
            return self._raddress


class DataSourceError(Exception):
    pass


class DbReader:
    """Common part of the readers; the subclasses give the SQL dialect."""
    PH = '?'                # placeholder of the parameters

    def __init__(self, config: DataSourceConfig):
        self.config = config
        self.conn = None
        self._lock = threading.RLock()
        self._streams = None
        self._metadata = None

    # --- dialect ---
    def _t(self):
        """SQL expression of the time column t in seconds since 1970."""
        return 't'

    def _bucket(self):
        """SQL expression of the bucket number: (t - t0) / dt, two parameters t0, dt."""
        return f"CAST(({self._t()} - {self.PH}) / {self.PH} AS INTEGER)"

    def _time_param(self, t):
        return t

    def _query(self, sql, params=()):
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
                return cur.fetchall()
            finally:
                cur.close()

    def _deserialize(self, value, datatype):
        if value is None:
            return None
        if datatype in ('list', 'dict') and isinstance(value, str):
            try:
                return deserialize_json(value)
            except Exception:
                return value
        return value

    # --- datastreams ---
    def _registered_streams(self):
        """[(address, table, table_db, column, datatype)] of the data_flat tables."""
        rows = self._query("SELECT DISTINCT t.tablename, t.tablename_db, a.address, a.address_db, a.datatype "
                           "FROM _redvypr_tables_ t JOIN _redvypr_addresses_ a ON a.tablename = t.tablename "
                           "WHERE t.tabletype = 'data_flat'")
        streams = {}
        for table, table_db, address, column, datatype in rows:
            key = (table_db, column)
            # several configurations may register the same column; keep one with a datatype
            if key not in streams or (streams[key].datatype is None and datatype):
                streams[key] = Datastream(address=address, table=table, table_db=table_db, column=column,
                                          datatype=datatype)
        return streams

    def _table_columns(self, table_db):
        raise NotImplementedError

    def _stream_stats(self, streams):
        """Fill num, t_first, t_last of the streams (as far as known without counting)."""

    def datastreams(self, refresh=False) -> typing.List[Datastream]:
        """All datastreams (columns of the data_flat tables that exist), sorted by address."""
        with self._lock:
            if self._streams is None or refresh:
                streams = self._registered_streams()
                columns = {}
                result = []
                for (table_db, column), s in streams.items():
                    if table_db not in columns:
                        columns[table_db] = self._table_columns(table_db)
                    if column in columns[table_db]:
                        result.append(s)
                self._stream_stats(result)
                result.sort(key=lambda s: (s.address, s.table))
                self._streams = result
            return list(self._streams)

    def find(self, address, numeric_only=False) -> typing.List[Datastream]:
        """Datastreams matching a redvypr address (str or RedvyprAddress)."""
        raddr = address if isinstance(address, RedvyprAddress) else RedvyprAddress(address)
        found = []
        for s in self.datastreams():
            if numeric_only and not s.numeric:
                continue
            try:
                if raddr.matches(s.raddress):
                    found.append(s)
            except Exception:
                logger.debug(f'could not compare {raddr} with {s.address}', exc_info=True)
        return found

    def time_range(self, stream: Datastream):
        """(t_first, t_last, num) of a datastream, counted in the database if not known."""
        if stream.t_first is None or stream.num is None:
            col, tbl = self._qi(stream.column), self._qi(stream.table_db)
            row = self._query(f"SELECT MIN({self._t()}), MAX({self._t()}), COUNT({col}) FROM {tbl} "
                              f"WHERE {col} IS NOT NULL")[0]
            stream.t_first, stream.t_last, stream.num = row[0], row[1], row[2]
        return stream.t_first, stream.t_last, stream.num

    @staticmethod
    def _qi(name):
        """Quoted identifier."""
        return '"' + str(name).replace('"', '""') + '"'

    # --- data ---
    def _where(self, col, t_start, t_end):
        where, params = [f"{col} IS NOT NULL"], []
        if t_start is not None:
            where.append(f"{self._t()} >= {self.PH}")
            params.append(self._time_param(t_start))
        if t_end is not None:
            where.append(f"{self._t()} <= {self.PH}")
            params.append(self._time_param(t_end))
        return ' AND '.join(where), params

    def get_stream_data(self, stream: Datastream, t_start=None, t_end=None, max_points=None):
        """
        Values of one datastream between t_start and t_end ([s] since 1970, None: open).
        With max_points and more values in the range (numeric streams only): minimum and
        maximum per time bucket. Returns {'t', 'data', 'decimated', 'num'}; num is the
        number of values in the range if known.
        """
        col, tbl = self._qi(stream.column), self._qi(stream.table_db)
        where, params = self._where(col, t_start, t_end)
        limit = f" LIMIT {int(max_points) + 1}" if max_points else ""
        rows = self._query(f"SELECT {self._t()}, {col} FROM {tbl} WHERE {where} ORDER BY t{limit}",
                           tuple(params))
        if not max_points or len(rows) <= max_points:
            t = np.array([r[0] for r in rows], dtype=float)
            data = [self._deserialize(r[1], stream.datatype) for r in rows]
            if stream.numeric:
                data = np.array(data, dtype=float)
            return {'t': t, 'data': data, 'decimated': False, 'num': len(rows)}
        if not stream.numeric:
            # Only numbers can be thinned out: the first max_points values
            t = np.array([r[0] for r in rows[:max_points]], dtype=float)
            data = [self._deserialize(r[1], stream.datatype) for r in rows[:max_points]]
            return {'t': t, 'data': data, 'decimated': True, 'num': None}
        # Thinning out: minimum and maximum per time bucket
        t0, t1 = t_start, t_end
        if t0 is None or t1 is None:
            first, last, _num = self.time_range(stream)
            t0 = first if t0 is None else t0
            t1 = last if t1 is None else t1
        nbuckets = max(1, int(max_points) // 2)
        # slightly wider: t1 itself falls into the last bucket, not into an extra one
        dt = max(t1 - t0, 1e-6) / nbuckets * (1 + 1e-9)
        bucket = self._bucket()
        rows = self._query(f"SELECT {bucket} AS b, MIN({col}), MAX({col}), COUNT({col}), MIN({self._t()}), "
                           f"MAX({self._t()}) FROM {tbl} WHERE {where} GROUP BY b ORDER BY b",
                           (t0, dt, *params))
        t, data, num = [], [], 0
        for _b, vmin, vmax, n, tmin, tmax in rows:
            num += n
            if n == 1 or vmin == vmax:
                t.append(tmin)
                data.append(vmin)
            else:
                # A vertical segment per bucket: the range of the values in that time
                t.extend((tmin, tmax))
                data.extend((vmin, vmax))
        return {'t': np.array(t, dtype=float), 'data': np.array(data, dtype=float), 'decimated': True,
                'num': num}

    def get_data(self, address, t_start=None, t_end=None, max_points=None, numeric_only=True):
        """
        Time and values of all datastreams matching address, merged in time (see
        get_stream_data()). Returns {'t', 'data', 'decimated', 'num', 'streams'}.
        """
        streams = self.find(address, numeric_only=numeric_only)
        ts, ds, decimated, num = [], [], False, 0
        for s in streams:
            d = self.get_stream_data(s, t_start, t_end, max_points)
            ts.append(d['t'])
            ds.append(np.asarray(d['data'], dtype=float if s.numeric else object))
            decimated |= d['decimated']
            num = None if (num is None or d['num'] is None) else num + d['num']
        if not ts:
            return {'t': np.array([]), 'data': np.array([]), 'decimated': False, 'num': 0, 'streams': []}
        t = np.concatenate(ts)
        data = np.concatenate(ds)
        if len(ts) > 1:
            order = np.argsort(t, kind='stable')
            t, data = t[order], data[order]
        return {'t': t, 'data': data, 'decimated': decimated, 'num': num, 'streams': streams}

    # --- metadata ---
    def metadata_storage(self, refresh=False) -> dict:
        """The metadata of the database in the redvypr storage format {address: [entries]}."""
        with self._lock:
            if self._metadata is None or refresh:
                storage = {}
                try:
                    rows = self._query("SELECT redvypr_address, metadata FROM redvypr_metadata")
                except Exception:
                    logger.debug('no metadata table', exc_info=True)
                    rows = []
                for address, content in rows:
                    try:
                        content = deserialize_json(content) if isinstance(content, str) else content
                        # The SQLite writer also stores whole info packets (deviceinfo_all)
                        if isinstance(content, dict) and '_redvypr' in content:
                            continue
                        part = redvypr.metadata.normalize_metadata({address: content})
                        for a, entries in part.items():
                            storage.setdefault(a, []).extend(entries)
                    except Exception:
                        logger.debug(f'could not read metadata of {address}', exc_info=True)
                self._metadata = storage
            return self._metadata

    def get_metadata(self, address, mode='merge', at_time=None, time_range=None):
        """
        Metadata of an address (e.g. {'unit': 'degC'}), from the metadata in the database.
        Without at_time and time_range: the metadata valid during the data of the
        datastreams matching address (not now, the data may be old).
        """
        storage = self.metadata_storage()
        if not storage:
            return {}
        if at_time is None and time_range is None:
            times = [(s.t_first, s.t_last) for s in self.find(address)]
            times = [t for t in times if None not in t]
            if times:
                time_range = (redvypr.metadata.to_isotime(min(t[0] for t in times)),
                              redvypr.metadata.to_isotime(max(t[1] for t in times)))
        try:
            return redvypr.metadata.get_metadata({'metadata': storage}, address=address, mode=mode,
                                                 at_time=at_time, time_range=time_range)
        except Exception:
            logger.debug(f'could not get metadata of {address}', exc_info=True)
            return {}

    def refresh(self):
        with self._lock:
            self._streams = None
            self._metadata = None

    def close(self):
        with self._lock:
            if self.conn is not None:
                try:
                    self.conn.close()
                finally:
                    self.conn = None


class SqliteReader(DbReader):
    PH = '?'

    def __init__(self, config: DataSourceConfig):
        super().__init__(config)
        import os
        if not config.filepath or not os.path.isfile(config.filepath):
            raise DataSourceError(f'SQLite file not found: {config.filepath!r}')
        # used by the thread loading the data of a plot; access is serialized by the lock
        self.conn = sqlite3.connect(config.filepath, check_same_thread=False, timeout=5)

    def _table_columns(self, table_db):
        return {r[1] for r in self._query(f"PRAGMA table_info({self._qi(table_db)})")}

    def _stream_stats(self, streams):
        """Statistics of the writer (_redvypr_data_tables_stats_), counted at the insert."""
        try:
            rows = self._query("SELECT tablename_db, address_db, SUM(num_entries), MIN(t_first), MAX(t_last) "
                               "FROM _redvypr_data_tables_stats_ WHERE address_db != '_global_' "
                               "GROUP BY tablename_db, address_db")
        except sqlite3.Error:
            return
        stats = {(r[0], r[1]): r[2:] for r in rows}
        for s in streams:
            st = stats.get((s.table_db, s.column))
            if st is not None:
                s.num, s.t_first, s.t_last = st


class TimescaleReader(DbReader):
    PH = '%s'

    def __init__(self, config: DataSourceConfig):
        super().__init__(config)
        try:
            import psycopg
        except ImportError as e:
            raise DataSourceError('TimescaleDB needs the package psycopg') from e
        try:
            self.conn = psycopg.connect(dbname=config.dbname, user=config.user, password=config.password,
                                        host=config.host, port=config.port, autocommit=True,
                                        connect_timeout=5)
        except psycopg.Error as e:
            raise DataSourceError(f'could not connect to {config.summary()}: {e}') from e

    def _t(self):
        return 'EXTRACT(EPOCH FROM t)::double precision'

    def _bucket(self):
        return f"FLOOR(({self._t()} - %s) / %s)::bigint"

    def _where(self, col, t_start, t_end):
        # Conditions on t itself (not on the expression), so that an index on t is used
        where, params = [f"{col} IS NOT NULL"], []
        if t_start is not None:
            where.append("t >= to_timestamp(%s)")
            params.append(float(t_start))
        if t_end is not None:
            where.append("t <= to_timestamp(%s)")
            params.append(float(t_end))
        return ' AND '.join(where), params

    def _table_columns(self, table_db):
        rows = self._query("SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                           (table_db,))
        return {r[0] for r in rows}


def open_datasource(config: DataSourceConfig) -> DbReader:
    """Reader of a data source (SqliteReader or TimescaleReader)."""
    if config.dbtype == 'sqlite':
        return SqliteReader(config)
    if config.dbtype == 'timescaledb':
        return TimescaleReader(config)
    raise DataSourceError(f'unknown database type {config.dbtype!r}')


class DatasourceRegistry:
    """
    Named data sources with their open readers (shared by all users, e.g. all plots).
    Redvypr has one (Redvypr.add_datasource() etc.); a plot without redvypr uses its own.
    on_change() is called after a data source was added, changed or removed.
    """

    def __init__(self, datasources=(), on_change=None):
        self._lock = threading.RLock()
        self._datasources = [DataSourceConfig.model_validate(d) for d in datasources]
        self._readers = {}
        self.on_change = on_change

    @property
    def datasources(self) -> typing.List[DataSourceConfig]:
        with self._lock:
            return list(self._datasources)

    def add_datasource(self, datasource):
        """Adds a data source (DataSourceConfig or dict); one with the same name is replaced."""
        datasource = DataSourceConfig.model_validate(datasource)
        with self._lock:
            self._remove(datasource.name)
            self._datasources.append(datasource)
        if self.on_change:
            self.on_change()
        return datasource

    def _remove(self, name):
        n = len(self._datasources)
        self._datasources = [d for d in self._datasources if d.name != name]
        reader = self._readers.pop(name, None)
        if reader is not None:
            reader.close()
        return len(self._datasources) != n

    def remove_datasource(self, name):
        with self._lock:
            removed = self._remove(name)
        if removed and self.on_change:
            self.on_change()

    def get_datasource(self, name) -> typing.Optional[DataSourceConfig]:
        with self._lock:
            for d in self._datasources:
                if d.name == name:
                    return d
        return None

    def get_datasource_reader(self, name, refresh=False) -> DbReader:
        """
        Open reader of the data source name. refresh: reads the datastreams and metadata of
        the database again. Raises DataSourceError if it cannot be opened.
        """
        with self._lock:
            config = self.get_datasource(name)
            if config is None:
                raise DataSourceError(f'unknown data source {name!r}')
            reader = self._readers.get(name)
            if reader is not None and reader.config != config:
                reader.close()
                reader = None
            if reader is None:
                reader = open_datasource(config)
                self._readers[name] = reader
            elif refresh:
                reader.refresh()
            return reader

    def close(self):
        with self._lock:
            for reader in self._readers.values():
                reader.close()
            self._readers = {}
