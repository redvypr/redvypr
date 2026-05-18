import hashlib
import re
import json
import os
import sqlite3
import logging
import sys
import os
import time
import pydantic
import typing
import threading
from datetime import datetime, timezone
import json
import copy
import logging
from PyQt6 import QtWidgets, QtCore
import qtawesome
from abc import ABC, abstractmethod
from typing import Union, Iterator, Optional, Any, Dict, List, Literal
from dataclasses import dataclass
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket
from .db_config_util import DbWriteConfig, sanitize_name_for_db, json_safe_dumps, json_safe_loads
import numpy as np

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db_engine_sqlite')
logger.setLevel(logging.DEBUG)


@dataclass
class DataQuery:
    """Configuration class defining filters and slicing for database reads."""
    t_start: Optional[float] = None
    t_end: Optional[float] = None
    t_packet_start: Optional[float] = None
    t_packet_end: Optional[float] = None
    limit: Optional[int] = None
    offset: Optional[int] = None  # <-- Added for index-based slicing
    order: Literal['ASC', 'DESC'] = 'ASC'


class SqliteConfig(pydantic.BaseModel):
    dbtype: typing.Literal["sqlite"] = pydantic.Field(
        default="sqlite",
        description="The type of the database engine."
    )
    filepath: str = pydantic.Field(
        default="data.sql",
        description="The base filename or path for the SQLite database."
    )
    max_file_size_mb: typing.Optional[float] = pydantic.Field(
        default=500,
        description="Maximum file size in MB before rotating. If None, rotation is disabled."
    )
    size_check_interval: int = pydantic.Field(
        default=10,
        description="Number of packets to wait between file size checks."
    )
    file_format: str = pydantic.Field(
        default="{name}_{filecount}_{filedate}",
        description="Naming template for rotated files. Placeholders: {name}, {filecount}, {filedate}."
    )

    dt_backup: int = pydantic.Field(default=120,
                                     description='Time after which the sqlite memory is written to the disk')

    dt_newfile: int = pydantic.Field(default=3600,
                                     description='Time after which a new file is created')
    dt_newfile_unit: typing.Literal[
        'none', 'seconds', 'hours', 'days'] = pydantic.Field(default='seconds')

    filedateformat: str = pydantic.Field(default='%Y-%m-%d_%H%M%S',
                                         description='Dateformat used in the filename, must be understood by datetime.strftime')
    write_config: DbWriteConfig = pydantic.Field(default_factory=DbWriteConfig)





class DbSqlite:
    def __init__(self, config: SqliteConfig, mode="write"):
        self.mode = mode
        self.config = config
        self.dtbackup = self.config.dt_backup
        # Initialisierung der Rotations-Parameter
        self.base_name = self.config.filepath
        self.max_file_size_mb = getattr(self.config, 'max_file_size_mb', None)
        self.file_format = getattr(self.config, 'file_format', "{name}_{filecount}")
        self._file_index = -1
        self._packet_counter = 0
        self.size_check_interval = 10  # Check every n packets

        self.file_statistics_total = {'packets_raw_written':0,
                                'packets_flat_written':0,
                                'metadata_written':0,
                                'entries_flat_written':0,
                                'columns_flat_active':{}}

        self.dtnews = None
        self.file_statistics = {}
        # Check mode and either load file from disk or create file in memory for writing and
        # new filename based in configuration
        if self.mode == "read":
            self.filepath = config.filepath
            self.connect_with_file()
        elif self.mode == "write":
            self.filepath = self.generate_new_filename()
            # Convert the addresses in string format into redvypr addresses
            self.write_config_raddr = self.convert_write_config_raddr(self.config)
            try:
                dtneworig = config.dt_newfile
                dtunit = config.dt_newfile_unit
                if (dtunit.lower() == 'seconds'):
                    dtfac = 1.0
                elif (dtunit.lower() == 'hours'):
                    dtfac = 3600.0
                elif (dtunit.lower() == 'days'):
                    dtfac = 86400.0
                else:
                    dtfac = 0

                self.dtnews = dtneworig * dtfac
                logger.info(
                    f' Will create new file every {config.dt_newfile} {config.dt_newfile_unit}.')
            except:
                logger.warning("Configuration incomplete", exc_info=True)
                self.dtnews = 0
            self.init_db_write()

    def connect_with_file(self):
        """Connects to the sqlite database"""
        print(f"Opening database file: {self.filepath}")
        if not os.path.isfile(self.filepath):
            raise FileExistsError(f"❌ Database file does not exist: {self.filepath}")

        self.file_created = time.time()
        self.file_last_check = time.time() - self.dtbackup + 10
        self.conn = sqlite3.connect(self.filepath)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        # Increase cache size
        self.conn.execute("PRAGMA cache_size = -20000;") # approx. 20MB Cache

    def init_db_write(self):
        self.file_statistics_total = {'packets_raw_written': 0,
                                      'packets_flat_written': 0,
                                      'metadata_written': 0,
                                      'entries_flat_written': 0,
                                      'columns_flat_active': {}}
        self.file_statistics[self.filepath] = {'packets_raw_written': 0,
                                               'packets_flat_written': 0,
                                               'metadata_written': 0,
                                               'entries_flat_written': 0,
                                               'columns_flat_active': {}}
        print(f"Opening database file: {self.filepath}")
        self.file_created = time.time()
        self.file_last_check = time.time() - self.dtbackup + 10
        # self.conn = sqlite3.connect(self.filepath)
        # self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute("PRAGMA foreign_keys = ON;")
        # Increase cache size
        self.conn.execute("PRAGMA cache_size = -20000;")  # approx. 20MB Cache
        self._initialize_metadata_tables()
        self.numconfig = self._determine_numconfig()
        self._register_config()
        self._initialize_data_tables()
        self._tables_flat = {}


    def get_memory_usage(self) -> int:
        """
        Calculate the memory usage (in bytes) of a SQLite in-memory database.

        Uses the provided `_execute` method to query the database for page count and size.

        Returns:
            int: Memory usage in bytes.
        """
        # Query the number of pages in the database
        page_count = self._execute("PRAGMA page_count").fetchone()[0]

        # Query the size of each page in bytes
        page_size = self._execute("PRAGMA page_size").fetchone()[0]

        # Calculate total memory usage
        memory_usage = page_count * page_size

        return memory_usage

    def save_to_disk(self, blocking=False):
        """Copies the RAM database onto the harddisk."""
        if not hasattr(self, 'conn'):
            return

        logger.debug(f"Saving data from ram into file:{self.filepath}")
        # A direct copy of the database
        if blocking:
            try:
                #logger.info(f"Saving data from ram into file:{self.filepath}")
                #dest_conn = sqlite3.connect(self.filepath)
                #self.conn.backup(dest_conn, pages=-1)
                #dest_conn.close()
                self._db_save_and_close(self.conn,self.filepath)
            except Exception as e:
                logger.error(f"Backup (blocking mode) failed: {e}")
        else: # Nonblocking
            try:
                # Backup sqlite database first onto another ram database
                # Disable thread check, this is possible as this is only a backup/read from ram_clone_conn thread
                ram_clone_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self.conn.backup(ram_clone_conn, pages=-1)
                bg_thread = threading.Thread(target=self._db_save_and_close,
                                             args=(ram_clone_conn,
                                                   self.filepath,),
                                             daemon=True,
                )
                bg_thread.start()
            except Exception as e:
                logger.error(f"Backup (background thread mode) failed: {e}")

    def _db_save_and_close(self, old_conn, target_filepath):
        """Writes the DB onto a file, function works in a thread"""
        filepath_dir = os.path.dirname(target_filepath)
        if filepath_dir:
            os.makedirs(filepath_dir, exist_ok=True)
        try:
            dest_conn = sqlite3.connect(target_filepath)
            old_conn.backup(dest_conn, pages=-1)
            dest_conn.close()
            logger.info(f"✅ Backup finished: {target_filepath}")
        except Exception as e:
            logger.error(f"❌ Backup failed: {e}")
        finally:
            old_conn.close()  # Closes the connection


    def _check_rotation(self):
        """Checks if the file has to be rotated"""
        if time.time() >= self.file_last_check + self.dtbackup:
            logger.info("Backup of file to disk")
            self.save_to_disk()
            self.file_last_check = time.time()

        self._packet_counter += 1
        if self._packet_counter >= self.size_check_interval:
            self._packet_counter = 0
            if (time.time() >= self.file_created + self.dtnews) and (self.dtnews>0):
                logger.info(
                    f"🔄 Limit of file age {self.dtnews}s reached. Rotating...")
                self.rotate_database()
            if self.max_file_size_mb:
                ram_size_mb = self.get_memory_usage() / (1024 * 1024)
                #print(f"Ram size:{ram_size_mb}")
                if ram_size_mb >= self.max_file_size_mb:
                    logger.info(
                        f"🔄 Limit {self.max_file_size_mb}MB reached. Rotating...")
                    self.rotate_database()

    def rotate_database(self):
        if self.mode == "write":
            self.save_to_disk()
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()

            self.filepath = self.generate_new_filename()
            self.init_db_write()
        else:
            raise ValueError("rotate_database only implemented in write mode")

    def convert_write_config_raddr(self, dbconfig):
        write_config_raddr = dbconfig.write_config.model_dump()
        for table_name, t_cfg in write_config_raddr["tables"].items():
            t_cfg["raddresses"] = []
            t_cfg["table_name_db"] = sanitize_name_for_db(table_name)
            for addr in t_cfg["addresses"]:
                addr_db = sanitize_name_for_db(addr)
                t_cfg["address_db"] = addr_db
                raddr = RedvyprAddress(addr)
                t_cfg["raddresses"].append(raddr)

        return write_config_raddr

    def _execute(self, query: str, params: tuple = ()):
        with self.conn:
            return self.conn.execute(query, params)

    def _execute_list(self, sql_commands: list[tuple[str, tuple]]) -> None:
        """
        Executes a list of SQL commands in a single transaction, with conditional commit/rollback.
        Uses Python's context manager (`with self.conn`) to automatically handle transaction lifecycle.

        This method is optimized for batch operations, ensuring atomicity (all commands succeed or none do).
        It is useful for bulk inserts, updates, or mixed operations that should be treated as a single unit.

        Args:
            sql_commands: A list of tuples, where each tuple contains:
                - The SQL query string (e.g., "INSERT INTO table VALUES (?, ?)").
                - A tuple of parameters for the query (e.g., (value1, value2)).

        Raises:
            sqlite3.Error: If any SQL command fails, the transaction is rolled back, and the error is re-raised.
            ValueError: If `sql_commands` is empty or contains invalid entries (e.g., not a tuple of (str, tuple)).

        Example:
            # Example usage for bulk inserts
            commands = [
                ("INSERT INTO users (name, age) VALUES (?, ?)", ("Alice", 30)),
                ("INSERT INTO users (name, age) VALUES (?, ?)", ("Bob", 25)),
            ]
            db._execute_list(commands)  # Auto-commits if no errors

            # Example with conditional commit
            commands = [...]
            db._execute_list(commands, condition=validate_data())  # Commits only if validate_data() is True
        """
        try:
            with self.conn:  # Automatically starts a transaction (BEGIN)
                for sql, params in sql_commands:
                    self.conn.execute(sql, params)
        except Exception as e:
            # The context manager (with self.conn) will automatically roll back on exception
            raise sqlite3.Error(f"Transaction failed: {str(e)}") from e



    def _initialize_metadata_tables(self):
        """
        Create internal tracking and configuration tables for the system.

        This method sets up the base relational schema required for tracking
        database configurations, structural layouts, and address mappings. If
        the tables already exist, execution passes safely via IF NOT EXISTS
        guards.

        The following internal management tables are initialized:

        _redvypr_config_
            Stores system engine configurations, execution state flags,
            and a fallback serialized JSON dump of the active database settings.
        _redvypr_tables_
            Acts as a registry tracking logical table configurations, their
            sanitized physical database names, data layouts, and associated
            configuration IDs.
        _redvypr_addresses_
            Tracks unique ingestion addresses, mapping raw keys to dynamically
            allocated metrics and columns.
        """
        # Main Config table with 'active' status
        self._execute("""
            CREATE TABLE IF NOT EXISTS _redvypr_config_ (
                uuid TEXT PRIMARY KEY,
                numconfig INTEGER,
                state INTEGER DEFAULT 0,
                name TEXT,
                description TEXT,
                full_config_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table Registry
        self._execute("""
            CREATE TABLE IF NOT EXISTS _redvypr_tables_ (
                tablename TEXT,
                tablename_db TEXT,
                tabletype TEXT,
                config_uuid TEXT,
                numconfig INTEGER,
                state INTEGER DEFAULT 0,
                PRIMARY KEY (tablename, config_uuid),
                FOREIGN KEY (config_uuid) REFERENCES _redvypr_config_(uuid)
            )
        """)

        # Address Mapping
        self._execute("""
            CREATE TABLE IF NOT EXISTS _redvypr_addresses_ (
                address TEXT,
                address_db TEXT,
                tablename TEXT,
                config_uuid TEXT,
                numconfig INTEGER,
                state INTEGER DEFAULT 0,
                datatype TEXT, 
                PRIMARY KEY (address, tablename, config_uuid),
                FOREIGN KEY (config_uuid) REFERENCES _redvypr_config_(uuid)
            )
        """)
        # Create metadata table
        self._execute("""
            CREATE TABLE IF NOT EXISTS redvypr_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                redvypr_address TEXT NOT NULL,
                uuid TEXT NOT NULL,
                packetid TEXT,
                device TEXT,
                host TEXT,
                metadata TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (redvypr_address, uuid) 
            );
        """)

    def _determine_numconfig(self) -> int:
        """Determines the next available numconfig or retrieves the existing one for this UUID."""
        uuid = self.config.write_config.uuid
        cursor = self.conn.execute(
            "SELECT numconfig FROM _redvypr_config_ WHERE uuid = ?", (uuid,))
        row = cursor.fetchone()
        if row:
            return row[0]

        cursor = self.conn.execute("SELECT MAX(numconfig) FROM _redvypr_config_")
        max_row = cursor.fetchone()
        if max_row and max_row[0] is not None:
            return max_row[0] + 1
        return 1

    def _register_config(self):
        """Saves configuration and ensures only the current one is marked as active."""
        wc = self.config.write_config

        with self.conn:
            # 1. Set all existing configs to inactive
            self.conn.execute("UPDATE _redvypr_config_ SET state = 0")

            # 2. Insert or Update current config as active (1)
            self.conn.execute("""
                INSERT OR REPLACE INTO _redvypr_config_ (uuid, numconfig, state, name, description, full_config_json)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
            wc.uuid, self.numconfig, 1, wc.name, wc.description, wc.model_dump_json()))

    def _initialize_data_tables(self):
        """Dynamically creates data tables based on config."""
        wc = self.config.write_config

        for table_name, t_cfg in wc.tables.items():
            # Update Table Metadata - mark as active (1) for this config
            table_name_db = sanitize_name_for_db(table_name)
            # Update statistics
            try:
                self.file_statistics_total['columns_flat_active'][table_name]
            except:
                self.file_statistics_total['columns_flat_active'][
                    table_name] = {'table_name_db': table_name_db}

            #table_name_db = self.write_config_raddr[table_name]["table_name_db"]
            self._execute("""
                INSERT OR REPLACE INTO _redvypr_tables_ (tablename, tablename_db, tabletype, config_uuid, numconfig)
                VALUES (?, ?, ?, ?, ?)
            """, (table_name, table_name_db, t_cfg.tabletype, wc.uuid, self.numconfig))

            columns = [
                "numconfig INTEGER",
                "numpacket INTEGER",
                "t_packet DATETIME NOT NULL",
                "t DATETIME"
            ]

            if t_cfg.tabletype == "redvypr_datapacket":
                columns.append("redvypr_address TEXT NOT NULL")
                columns.append("packetid TEXT")
                columns.append("publisher TEXT")
                columns.append("device TEXT")
                columns.append("host TEXT")
                columns.append("uuid")
                columns.append("data TEXT NOT NULL")
                #columns.append("raw_data BLOB")
            else:
                pass
                # Dont add anything, the addresses will be added dynamicall during insert_data
                if False:
                    for addr in t_cfg.addresses:
                        col_name_db = sanitize_name_for_db(addr)
                        #col_name_db = self.write_config_raddr[table_name]["addresses"][addr]["address_db"]
                        # We dont include yet, because the datatype is not known yet
                        #columns.append(f"{col_name_db} TEXT")

                        # Log Address Metadata
                        self._execute("""
                            INSERT OR REPLACE INTO _redvypr_addresses_ (address, address_db, tablename, config_uuid, numconfig, state)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (addr, col_name_db, table_name, wc.uuid, self.numconfig, 0))

            # Create the data table
            self._execute(
                f"CREATE TABLE IF NOT EXISTS {table_name_db} ({', '.join(columns)})")

    def close(self):
        self.save_to_disk()
        self.conn.close()


    def add_metadata(self, address: str, uuid: str,
                     metadata_dict: dict, mode: str = "merge"):

        try:
            raddr = RedvyprAddress(address, uuid=uuid)
            packetid = raddr.packetid
            device = raddr.device
            host = raddr.host
        except:
            logger.info("Could not get address details, will use None instead",exc_info=True)
            # Fallback
            packetid, device, host = None, None, None

        # SQLite Upsert
        sql = """
            INSERT INTO redvypr_metadata (redvypr_address, uuid, metadata, packetid, device, host)
            VALUES (?, ?, ?, ?, ?, ? )
            ON CONFLICT(redvypr_address, uuid) DO UPDATE SET
                metadata = excluded.metadata,
                created_at = CURRENT_TIMESTAMP;
        """
        sql_data = (address, uuid, json_safe_dumps(metadata_dict), packetid, device, host)
        self._execute(sql, sql_data)

        self.file_statistics[self.filepath]['metadata_written'] += 1
        self.file_statistics_total['metadata_written'] += 1


    def insert_packet(self, data):
        """
        Inserts a redvypr datadict into the database. Checks first if the address matches.

        Parameters
        ----------
        data

        Returns
        -------

        """
        #["redvypr_datapacket", "data_flat", "redvypr_metadata"]
        wcra = self.write_config_raddr
        #print("Writing data",data)
        flag_packet_written = False
        for table_name, t_cfg in wcra["tables"].items():
            table_type = t_cfg["tabletype"]
            flag_address_match = False
            for iaddr,raddr in enumerate(t_cfg["raddresses"]):
                if flag_address_match:
                    break
                addr = t_cfg["addresses"][iaddr]
                #print("raddr",raddr)
                #print(f"{table_name=},{table_type=},{raddr=}")
                if table_type == "redvypr_datapacket":
                    if raddr.matches_filter(data):
                        #print("Write packet to db table:{table_name}")
                        sql_command = self.get_sql_insert_datapacket(table_name, data)
                        if sql_command:
                            #print(f"{sql_command=}")
                            try:
                                self._execute(sql_command[0],sql_command[1])
                            except:
                                logger.warning(f"Could not insert data:{sql_command}",exc_info=True)
                                print("data",data)
                                print("table_name", table_name)
                            #print(f"Stored packet in {table_name}")
                            flag_packet_written = True
                            self.file_statistics[self.filepath]['packets_raw_written'] += 1
                            self.file_statistics_total['packets_raw_written'] += 1
                            try:
                                self.file_statistics_total['columns_flat_active'][
                                    table_name][addr]
                            except:
                                self.file_statistics_total['columns_flat_active'][
                                    table_name][
                                    addr] = {
                                    'colname_db': sanitize_name_for_db(addr),
                                    'entries_written': 0}

                            self.file_statistics_total['columns_flat_active'][
                                table_name][addr]['entries_written'] += 1

                            flag_address_match = True # Packet for address found, no need to look for further addresses
                elif table_type == "data_flat":
                    #print("Checking address")
                    rv_meta = data.get('_redvypr', {})
                    data_addr = raddr(data,strict=False)
                    numpacket = rv_meta.get('numpacket',-1)
                    tpacket = rv_meta.get('t',-1)
                    tdata = data.get('t', -1)
                    #print(f"{data_addr=}")
                    if data_addr:
                        # Check if we have a packet filter only, if yes expand data packet
                        # and save all datakeys
                        if raddr.datakey is None and isinstance(data_addr,dict):
                            #print("Got a datapacket, expanding")
                            rdata = Datapacket(data)
                            data_expanded = rdata.expand_data()
                            #print("data_expanded all", data_expanded)
                            #print("data_expanded",data_expanded.keys())
                        else:
                            #(t, data, datakey, raddress, address_format='k,i,h,d,p'):
                            data_expanded = {}
                            data_expanded_tmp = Datapacket.create_expanded_datadict(t=tdata,data=data_addr,datakey=raddr.datakey,raddress=raddr)
                            data_expanded[data_expanded_tmp['address']] = data_expanded_tmp
                            #print("Data expanded",data_expanded)
                            #data_expanded = {addr:{}}
                            #data_expanded[addr]['t'] = tdata
                            #data_expanded[addr]['data'] = data_addr
                            #data_expanded[addr]['key'] = None
                            #data_expanded[addr]['address'] = addr
                            #data_expanded['format'] = '0d'

                        for addr_write, data_expanded_tmp in data_expanded.items():
                            data_addr_write_final = data_expanded_tmp['data']
                            #print("\nType:",type(data_addr_write_final))
                            if data_expanded_tmp['format'] == '0d':
                                nlines = 1
                                tdata = [data_expanded_tmp['t']]
                                #if isinstance(data_addr_write_final, (list,dict)): #
                                data_addr_write_final = [data_addr_write_final]
                            elif data_expanded_tmp['format'] == '0d_stacked':
                                nlines = len(tdata)

                            #print("\nData write final:", data_addr_write_final)
                            #print("nlines",nlines)
                            # Check if addr in table exists
                            #print(
                            #    f"Checking if {addr_write=} exists in db table:{table_name}")
                            try:
                                self.check_addr_in_table(address=addr_write,
                                                         table_name=table_name,
                                                         value=data_addr_write_final[0])

                            except:
                                logger.warning(f"Error checking table with data: {self.serialize_value(data_addr_write_final[0])}", exc_info=True)

                            #print(f"Write data to db table:{table_name}")
                            sql_commands = []
                            for nline in range(nlines):
                                data_write_db = self.serialize_value(data_addr_write_final[nline])

                                sql_command = self.get_sql_insert_address_data(table_name=table_name,
                                                            address=addr_write,
                                                            t=tdata[nline],
                                                            t_packet=tpacket,
                                                            numpacket=numpacket,
                                                            data=data_write_db)

                                sql_commands.append(sql_command)
                                #print("SQL",sql_command)
                                #try:
                                #    self._execute(sql_command[0],sql_command[1])
                                #except:
                                #    print("\nError")
                                #    print(data_expanded_tmp)
                                #    print(f"{sql_command[0]=}")
                                #    print(f"{sql_command[1]=}")
                                #    print(data_write_db)
                                #    # print(data_expanded_tmp)
                                #    print(
                                #       f"Could not write addr {addr_write=} in db table:{table_name}")
                                #   logger.warning("Error writing", exc_info=True)
                                # Statistics
                                self.file_statistics_total['entries_flat_written']+=1
                                try:
                                    self.file_statistics_total['columns_flat_active'][table_name][addr_write]
                                except:
                                    self.file_statistics_total['columns_flat_active'][table_name][
                                        addr_write] = {'colname_db':sanitize_name_for_db(addr_write),
                                                       'entries_written':0}

                                self.file_statistics_total['columns_flat_active'][
                                    table_name][addr_write]['entries_written'] += 1

                                #self.file_statistics[self.filepath]['entries_flat_written'] += 1

                            try:
                                self._execute_list(sql_commands)
                            except:
                                logger.warning("Error writing",exc_info=True)
                            flag_packet_written = True
                            flag_address_match = True  # Packet for address found, no need to look for further addresses

        if flag_packet_written:
            #print("Flag packet written")
            self.file_statistics[self.filepath]['packets_flat_written'] += 1
            self.file_statistics_total['packets_flat_written'] += 1
            self._check_rotation()

    @staticmethod
    def serialize_value(value):
        """
        Serialize a value for SQLite storage:
        - NumPy arrays → bytes (BLOB)
        - list/dict → JSON string (TEXT)
        - Other types → unchanged
        """
        if isinstance(value, np.ndarray):
            return value.tobytes()  # BLOB
        elif isinstance(value, (list, dict)):
            return json.dumps(value)  # TEXT (JSON)
        elif isinstance(value, (bytes, bytearray)):
            return bytes(value)  # BLOB
        else:
            return value  # INTEGER, REAL, TEXT, etc.

    @staticmethod
    def deserialize_value(value, datatype: Optional[str]):
        """Reconstructs the original data type based on the stored datatype string."""
        if value is None:
            return None

        if datatype in ("list", "dict"):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value

        elif datatype == "ndarray":
            try:
                # Falls es als JSON-Array oder String-Repräsentation vorliegt
                return np.array(json.loads(value))
            except:
                # Falls es als roher BLOB/Bytes gespeichert wurde
                return np.frombuffer(value, dtype=np.float64)

        elif datatype == "float":
            return float(value)
        elif datatype == "int":
            return int(value)
        elif datatype == "bool":
            return bool(value)

        return value

    def check_addr_in_table(self, address: str, table_name: str, value: any):
        """
        Ensures that a specific address exists as a column in the data table.

        Checks the local cache, metadata table, and the physical SQLite schema.
        If the column is missing in any of these, it maps the Python data type
        to SQLite, alters the table, and updates all registries.

        Parameters
        ----------
        address : str
            The original redvypr address string.
        table_name : str
            The name of the logical table.
        value : any
            The data value to be inserted, used to determine the SQL data type.
        """
        table_name_db = sanitize_name_for_db(table_name)
        address_db = sanitize_name_for_db(address)

        # 1. Quick check: Local Cache
        if table_name_db in self._tables_flat and address_db in self._tables_flat[
            table_name_db]:
            return

        # 2. Determine SQLite data type AND Python datatype string (UPDATED)
        if isinstance(value, int):
            sql_type = "INTEGER"
            type_str = "int"
        elif isinstance(value, (bytes, bytearray)):
            sql_type = "BLOB"
            type_str = "bytes"
        elif isinstance(value, list):
            sql_type = "TEXT"
            type_str = "list"
        elif isinstance(value, dict):
            sql_type = "TEXT"
            type_str = "dict"
        elif isinstance(value, float):
            sql_type = "REAL"
            type_str = "float"
        elif isinstance(value, bool):
            sql_type = "INTEGER"  # SQLite uses 0/1 for booleans
            type_str = "bool"
        elif isinstance(value, np.ndarray):
            sql_type = "BLOB"
            type_str = "ndarray"
        else:
            sql_type = "TEXT"
            type_str = type(value).__name__

        # 3. Physical Schema Check (Does the column actually exist in the table?)
        cursor = self.conn.execute(f"PRAGMA table_info({table_name_db})")
        existing_columns = [row[1] for row in cursor.fetchall()]

        if address_db not in existing_columns:
            logger.info(
                f"Adding missing column '{address_db}' ({sql_type}) to table '{table_name_db}'")
            try:
                # SQLite ALTER TABLE does not support parameters for column names
                self._execute(
                    f"ALTER TABLE {table_name_db} ADD COLUMN {address_db} {sql_type}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise e

        # 4. Metadata Registry Check & Update (_redvypr_addresses_ table) (UPDATED)
        cursor = self._execute("""
            SELECT datatype FROM _redvypr_addresses_ 
            WHERE address_db = ? AND tablename = ? AND config_uuid = ?
        """, (address_db, table_name, self.config.write_config.uuid))

        row = cursor.fetchone()

        if not row:
            # Address completely unknown in this configuration -> Insert with datatype
            self._execute("""
                INSERT OR REPLACE INTO _redvypr_addresses_ 
                (address, address_db, tablename, config_uuid, numconfig, state, datatype)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (address, address_db, table_name, self.config.write_config.uuid,
                  self.numconfig, 0, type_str))
        elif row[0] is None:
            # Address exists from initialization, but datatype was missing -> Update it now
            self._execute("""
                UPDATE _redvypr_addresses_ 
                SET datatype = ? 
                WHERE address_db = ? AND tablename = ? AND config_uuid = ?
            """, (type_str, address_db, table_name, self.config.write_config.uuid))

        # 5. Update Local Cache
        if table_name_db not in self._tables_flat:
            self._tables_flat[table_name_db] = set()
        self._tables_flat[table_name_db].add(address_db)



    def get_sql_insert_address_data(
            self,
            table_name: str,
            address: str,
            t: float,
            t_packet: float,
            numpacket: int,
            data: Any,
    ) -> tuple | None:
        #table_name_db = self.write_config_raddr[table_name]["table_name_db"]
        table_name_db = sanitize_name_for_db(table_name)
        address_db = sanitize_name_for_db(address)

        #print(f"Insert data into {table_name=}({table_name_db=}) for {address=}({address_db=})")
        # Insert or update the data
        sql = f"""
                 INSERT INTO {table_name_db} (t, t_packet,numpacket, numconfig, {address_db})
                 VALUES (?,?,?,?,?)                 
              """

        sql_command = (sql, (
            t,
            t_packet,
            numpacket,
            self.numconfig,
            data
        ))

        return sql_command

    def get_sql_insert_datapacket(self, table_name: str, data_dict: Dict[str, Any]) -> tuple | None:
        """
        Inserts a data packet into the table_name of the SQLite database.
        """
        try:
            # 3. Extract addressing and timing information
            raddr = RedvyprAddress(data_dict)

            # Use 't' from the main dict for the entry timestamp
            ts_utc_all = data_dict.get('t',-1)
            # If t is a list, take the first element
            try:
                ts_utc = ts_utc_all[0]
            except:
                ts_utc = ts_utc_all

            # Extract internal redvypr metadata
            rv_meta = data_dict.get('_redvypr', {})
            ts_pkt_utc = rv_meta.get('t', -1)

            # 4. Prepare data for SQL
            data_dict_json = json_safe_dumps(data_dict)

            sql = f"""
                INSERT INTO {table_name} 
                (numconfig, t, t_packet, data, redvypr_address, host, publisher, device, packetid, numpacket, uuid) 
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """

            sql_command = (sql, (
                self.numconfig,
                ts_utc,
                ts_pkt_utc,
                data_dict_json,
                raddr.to_address_string(),
                raddr.host,
                raddr.publisher,
                raddr.device,
                raddr.packetid,
                rv_meta.get('numpacket', '-1'),
                raddr.uuid
            ))

            return sql_command

        except Exception as e:
            logger.error(f"❌ Failed to create sql ommand for insert packet into SQLite: {e}")
            return None

    def generate_new_filename(self) -> str:
        self._file_index += 1
        return self.format_filename(
            base_name=self.base_name,
            file_format=self.file_format,
            file_index=self._file_index,
            max_file_size_mb=self.max_file_size_mb,
            file_dateformat=self.config.filedateformat
        )

    @staticmethod
    def format_filename(base_name: str, file_format: str, file_index: int,
                        max_file_size_mb: Optional[float], file_dateformat: str) -> str:
        """
        Pure logic to generate the filename.
        Used by both the Database class and the UI Widget.
        """
        directory = os.path.dirname(base_name)
        filename = os.path.basename(base_name)
        clean_name, extension = os.path.splitext(filename)

        # Most users put '.db' in the format field, so we clean the template-extension too
        format_base, _ = os.path.splitext(file_format)
        now_str = datetime.now().strftime(file_dateformat)
        try:
            new_filename_base = format_base.format(
                name=clean_name,
                filecount=f"{file_index:03d}",
                filedate=now_str
            )
        except (KeyError,ValueError,IndexError):
            # Simple fallback if template is broken
            new_filename_base = f"{clean_name}_{file_index:03d}_{now_str}"

        filename_final = os.path.join(directory, f"{new_filename_base}{extension}")
        #print("Filename final",filename_final)
        return filename_final

    def get_status(self):
        return [self.file_statistics_total, self.file_statistics]

    def read_db_layout(self) -> dict | None:
        """
        Read the active system tracking configuration and layout from SQLite metadata tables.
        """
        if not hasattr(self, 'conn') or self.conn is None:
            logger.warning("⚠️ No active database connection found.")
            return None

        # 1. Check if the required tracking tables exist using YOUR _execute method
        check_query = """
            SELECT name FROM sqlite_master 
            WHERE type='table' 
              AND name IN ('_redvypr_config_', '_redvypr_tables_', '_redvypr_addresses_')
        """
        try:
            cursor = self._execute(check_query)
            tables_found = len(cursor.fetchall())
            print("Tables found",tables_found)
            if tables_found < 3:
                logger.warning(
                    "⚠️ Core tracking tables are missing or incomplete in SQLite.")
                return None
        except Exception as e:
            logger.error(f"❌ Failed to verify SQLite tables existence: {e}")
            return None

        layout = {"configs": {}, "tables": [], "addresses": []}
        old_row_factory = self.conn.row_factory

        try:
            # Enable name-based column lookups locally
            self.conn.row_factory = sqlite3.Row

            # Fetch data using YOUR _execute method
            cur_config = self._execute("SELECT * FROM _redvypr_config_")
            for row in cur_config.fetchall():
                row_dict = dict(row)
                uuid_key = row_dict.pop("uuid")
                layout["configs"][uuid_key] = row_dict

            cur_tables = self._execute("SELECT * FROM _redvypr_tables_")
            layout["tables"] = [dict(row) for row in cur_tables.fetchall()]

            cur_addrs = self._execute("SELECT * FROM _redvypr_addresses_")
            layout["addresses"] = [dict(row) for row in cur_addrs.fetchall()]

            logger.info(
                f"📊 Loaded SQLite layout: {len(layout['configs'])} configs, "
                f"{len(layout['tables'])} tables, {len(layout['addresses'])} addresses registered."
            )
            return layout

        except Exception as e:
            logger.error(f"❌ Failed to parse database layout from SQLite metadata: {e}")
            raise RuntimeError("SQLite layout retrieval failed") from e

        finally:
            # Always restore the connection's original row factory
            self.conn.row_factory = old_row_factory

    def get_data_tables(self, tabletype: typing.Literal['all', 'raw', 'flat'] = 'all') -> dict:
        """
        Get registered data tables filtered by their architectural type with
        extended table-level and address-level metrics.

        Parameters
        ----------
        tabletype : {'all', 'raw', 'flat'}, default 'all'
            The structural type of the tables to retrieve.
            Maps locally to 'redvypr_datapacket' and 'data_flat'.

        Returns
        -------
        dict
            A structured dictionary of tables, their global stats, and containing metrics.
        """
        if not hasattr(self, 'conn') or self.conn is None:
            logger.warning("⚠️ No active database connection found.")
            return {}

        # Backup the current row_factory status
        old_row_factory = self.conn.row_factory
        result = {}

        try:
            # Enable column name-based access
            self.conn.row_factory = sqlite3.Row

            # 1. Fetch all active tables from the metadata registry
            table_query = "SELECT tablename, tablename_db, tabletype FROM _redvypr_tables_ WHERE state = 0"
            cur_tables = self._execute(table_query)
            tables = cur_tables.fetchall()

            if not tables:
                return {}

            # Map parameter tokens to internal database types
            if tabletype == 'all':
                target_types = ['redvypr_datapacket', 'data_flat']
            elif tabletype == 'flat':
                target_types = ['data_flat']
            else:
                target_types = ['redvypr_datapacket']

            # Build structural framework and filter by targeted type
            for t in tables:
                if t['tabletype'] not in target_types:
                    continue

                logical_name = t['tablename']
                result[logical_name] = {
                    'tablename_db': t['tablename_db'],
                    'tabletype': t['tabletype'],
                    'num_entries': 0,
                    't_first': None,
                    't_last': None,
                    't_packet_first': None,
                    't_packet_last': None,
                    'addresses': {}
                }

            if not result:
                return {}

            # 2. Fetch all registered addresses for the filtered tables in a single batch query
            placeholders = ",".join(["?"] * len(result))
            addr_query = f"""
                SELECT address, address_db, tablename 
                FROM _redvypr_addresses_ 
                WHERE tablename IN ({placeholders}) AND state = 0
            """
            cur_addrs = self._execute(addr_query, tuple(result.keys()))

            for addr in cur_addrs.fetchall():
                logical_table = addr['tablename']
                if logical_table in result:
                    result[logical_table]['addresses'][addr['address']] = {
                        'address_db': addr['address_db'],
                        'num_entries': 0,
                        't_first': None,
                        't_last': None,
                        't_packet_first': None,
                        't_packet_last': None
                    }

            # 3. Compute structural metrics dynamically from active data tables
            for logical_name, table_info in result.items():
                phys_table = table_info['tablename_db']
                addresses_dict = table_info['addresses']

                # Verify that the target physical table exists within the SQLite schema
                table_check = self._execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (phys_table,)
                ).fetchone()

                if not table_check:
                    continue

                # --- GLOBAL STATS FOR THE ENTIRE TABLE ---
                global_query = f"""
                    SELECT 
                        COUNT(*) as total_rows, 
                        MIN(t) as t_first, 
                        MAX(t) as t_last,
                        MIN(t_packet) as t_packet_first,
                        MAX(t_packet) as t_packet_last
                    FROM "{phys_table}"
                """
                try:
                    global_row = self._execute(global_query).fetchone()
                    if global_row and global_row['total_rows'] > 0:
                        table_info['num_entries'] = global_row['total_rows']
                        table_info['t_first'] = global_row['t_first']
                        table_info['t_last'] = global_row['t_last']
                        table_info['t_packet_first'] = global_row['t_packet_first']
                        table_info['t_packet_last'] = global_row['t_packet_last']
                except Exception as table_err:
                    logger.debug(
                        f"Could not fetch global stats for table {phys_table}: {table_err}")

                # --- METRICS FOR EACH INDIVIDUAL ADDRESS FIELD ---
                for raw_addr, addr_meta in addresses_dict.items():
                    col_db = addr_meta['address_db']

                    stats_query = f"""
                        SELECT 
                            COUNT("{col_db}") as num_entries,
                            MIN(t) as t_first,
                            MAX(t) as t_last,
                            MIN(t_packet) as t_packet_first,
                            MAX(t_packet) as t_packet_last
                        FROM "{phys_table}"
                        WHERE "{col_db}" IS NOT NULL
                    """
                    try:
                        stats_row = self._execute(stats_query).fetchone()
                        if stats_row and stats_row['num_entries'] > 0:
                            addr_meta['num_entries'] = stats_row['num_entries']
                            addr_meta['t_first'] = stats_row['t_first']
                            addr_meta['t_last'] = stats_row['t_last']
                            addr_meta['t_packet_first'] = stats_row['t_packet_first']
                            addr_meta['t_packet_last'] = stats_row['t_packet_last']
                    except Exception as col_err:
                        logger.debug(
                            f"Could not fetch stats for column {col_db} in {phys_table}: {col_err}")

            return result

        except Exception as e:
            logger.error(f"❌ Error compiling data tables dictionary: {e}")
            raise RuntimeError("Failed to build data tables dictionary") from e

        finally:
            # Cleanly restore connection row factory state
            self.conn.row_factory = old_row_factory

    def get_data(
            self,
            tablename: str,
            addresses: Union[str, List[str]],
            query: Optional[DataQuery] = None
    ) -> dict:
        """
        Retrieve clean, address-centric timeseries datasets.
        ...
        """
        if not hasattr(self, 'conn') or self.conn is None:
            logger.warning("⚠️ No active database connection found.")
            return {}

        # 1. Resolve table physical name
        table_info_query = "SELECT tablename_db FROM _redvypr_tables_ WHERE tablename = ? AND state = 0"
        table_row = self._execute(table_info_query, (tablename,)).fetchone()
        if not table_row:
            logger.warning(f"⚠️ Table '{tablename}' is not registered or active.")
            return {}
        phys_table = table_row[0]

        # Normalize input to a list
        address_list = [addresses] if isinstance(addresses, str) else addresses

        # 2. Fetch physical column mappings AND the stored datatype (UPDATED)
        if not address_list:
            return {}

        placeholders = ",".join(["?"] * len(address_list))
        addr_query = f"""
            SELECT address, address_db, datatype 
            FROM _redvypr_addresses_ 
            WHERE tablename = ? AND address IN ({placeholders}) AND state = 0
        """
        cur_addrs = self._execute(addr_query, (tablename, *address_list))

        # We store both the DB column name and the datatype string in our map
        col_map = {row[0]: (row[1], row[2]) for row in cur_addrs.fetchall()}

        result = {}
        old_row_factory = self.conn.row_factory

        try:
            # Enforce standard tuple rows for fast array construction
            self.conn.row_factory = None

            # 3. Query each address individually to isolate its data and strip Nones
            for logical_addr, (physical_col, datatype) in col_map.items():

                # Base dynamic conditions
                where_clauses = [f'"{physical_col}" IS NOT NULL']
                sql_params = []

                if query:
                    if query.t_start is not None:
                        where_clauses.append("t >= ?")
                        sql_params.append(query.t_start)
                    if query.t_end is not None:
                        where_clauses.append("t <= ?")
                        sql_params.append(query.t_end)
                    if query.t_packet_start is not None:
                        where_clauses.append("t_packet >= ?")
                        sql_params.append(query.t_packet_start)
                    if query.t_packet_end is not None:
                        where_clauses.append("t_packet <= ?")
                        sql_params.append(query.t_packet_end)

                # Stitching query fragments safely
                where_str = f"WHERE {" AND ".join(where_clauses)}"
                order_str = f"ORDER BY t {query.order if query else 'ASC'}"

                limit_str = ""
                if query and query.limit is not None:
                    limit_str = f"LIMIT {query.limit}"
                    if query.offset is not None:
                        limit_str += f" OFFSET {query.offset}"
                elif query and query.offset is not None:
                    limit_str = f"LIMIT -1 OFFSET {query.offset}"

                # We only pull exactly what belongs to this single address timeline
                final_query = f'SELECT t, t_packet, numpacket, "{physical_col}" FROM "{phys_table}" {where_str} {order_str} {limit_str}'

                cursor = self._execute(final_query, tuple(sql_params))
                records = cursor.fetchall()

                # Separate the columns into clean, individual Python lists
                t_array = []
                t_packet_array = []
                numpacket_array = []
                v_array = []

                for row in records:
                    t_array.append(row[0])
                    t_packet_array.append(row[1])
                    numpacket_array.append(row[2])
                    # --- AUTOMATIC DESERIALIZATION BASED ON METADATA ---
                    raw_value = row[3]
                    clean_value = self.deserialize_value(raw_value, datatype)
                    v_array.append(clean_value)

                result[logical_addr] = {
                    "t": t_array,
                    "t_packet": t_packet_array,
                    "numpacket": numpacket_array,
                    "data": v_array
                }

            return result

        except Exception as e:
            logger.error(f"❌ Failed address-centric retrieval from '{phys_table}': {e}")
            return {}
        finally:
            self.conn.row_factory = old_row_factory

    def get_data_legacy(
            self,
            tablename: str,
            addresses: Union[str, List[str]],
            query: Optional[DataQuery] = None
    ) -> dict:
        """
        Retrieve clean, address-centric timeseries datasets.

        Extracts only valid records where data exists for the specific address,
        completely stripping away unrelated None values and returning localized
        timelines per metric.

        Parameters
        ----------
        tablename : str
            The logical name of the table as registered in the config.
        addresses : str or list of str
            The address string or list of address strings to query.
        query : DataQuery, optional
            A DataQuery object defining time windows, limits, offsets, and order.

        Returns
        -------
        dict
            An address-mapped dictionary containing stripped timeline arrays.
            Format:
            {
                "sensor_temperature_A": {
                    "t": [1779085000.0, 1779085020.0],
                    "t_packet": [1779085000.1, 1779085020.3],
                    "v": [23.4, 23.6]
                }
            }
        """
        if not hasattr(self, 'conn') or self.conn is None:
            logger.warning("⚠️ No active database connection found.")
            return {}

        # 1. Resolve table physical name
        table_info_query = "SELECT tablename_db FROM _redvypr_tables_ WHERE tablename = ? AND state = 0"
        table_row = self._execute(table_info_query, (tablename,)).fetchone()
        if not table_row:
            logger.warning(f"⚠️ Table '{tablename}' is not registered or active.")
            return {}
        phys_table = table_row[0]

        # Normalize input to a list
        address_list = [addresses] if isinstance(addresses, str) else addresses

        # 2. Fetch physical column mappings
        if not address_list:
            return {}

        placeholders = ",".join(["?"] * len(address_list))
        addr_query = f"""
            SELECT address, address_db 
            FROM _redvypr_addresses_ 
            WHERE tablename = ? AND address IN ({placeholders}) AND state = 0
        """
        cur_addrs = self._execute(addr_query, (tablename, *address_list))
        col_map = {row[0]: row[1] for row in cur_addrs.fetchall()}

        result = {}
        old_row_factory = self.conn.row_factory

        try:
            # Enforce standard tuple rows for fast array construction
            self.conn.row_factory = None

            # 3. Query each address individually to isolate its data and strip Nones
            for logical_addr, physical_col in col_map.items():

                # Base dynamic conditions
                where_clauses = [f'"{physical_col}" IS NOT NULL']
                sql_params = []

                if query:
                    if query.t_start is not None:
                        where_clauses.append("t >= ?")
                        sql_params.append(query.t_start)
                    if query.t_end is not None:
                        where_clauses.append("t <= ?")
                        sql_params.append(query.t_end)
                    if query.t_packet_start is not None:
                        where_clauses.append("t_packet >= ?")
                        sql_params.append(query.t_packet_start)
                    if query.t_packet_end is not None:
                        where_clauses.append("t_packet <= ?")
                        sql_params.append(query.t_packet_end)

                # Stitching query fragments safely
                where_str = f"WHERE {" AND ".join(where_clauses)}"
                order_str = f"ORDER BY t {query.order if query else 'ASC'}"

                limit_str = ""
                if query and query.limit is not None:
                    limit_str = f"LIMIT {query.limit}"
                    if query.offset is not None:
                        limit_str += f" OFFSET {query.offset}"
                elif query and query.offset is not None:
                    limit_str = f"LIMIT -1 OFFSET {query.offset}"

                # We only pull exactly what belongs to this single address timeline
                final_query = f'SELECT t, t_packet, "{physical_col}" FROM "{phys_table}" {where_str} {order_str} {limit_str}'

                cursor = self._execute(final_query, tuple(sql_params))
                records = cursor.fetchall()

                # Separate the columns into clean, individual Python lists
                # (Great for immediate plotting or passing to numpy/pandas)
                t_array = []
                t_packet_array = []
                v_array = []

                for row in records:
                    t_array.append(row[0])
                    t_packet_array.append(row[1])
                    v_array.append(row[2])

                result[logical_addr] = {
                    "t": t_array,
                    "t_packet": t_packet_array,
                    "v": v_array
                }

            return result

        except Exception as e:
            logger.error(f"❌ Failed address-centric retrieval from '{phys_table}': {e}")
            return {}
        finally:
            self.conn.row_factory = old_row_factory



    def __enter__(self):
        """Allows usage: with DatabaseInstance as db:"""
        self.connect_with_file()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ensures the connection is closed when exiting the 'with' block."""
        self.disconnect()

    def disconnect(self):
        """Closes the connection safely."""
        if self.conn:
            try:
                self.conn.close()
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
            finally:
                self.conn = None




class SqliteConfigWidget(QtWidgets.QWidget):
    db_config_changed = QtCore.Signal(dict)

    def __init__(self, initial_config: SqliteConfig, parent=None):
        super().__init__(parent)
        self.config = initial_config
        self.setup_ui()

    def setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        layout = QtWidgets.QFormLayout()

        # --- 1. Base File Path ---
        self.path_edit = QtWidgets.QLineEdit(self.config.filepath)
        self.path_edit.textChanged.connect(self.config_changed)
        self.browse_btn = QtWidgets.QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.handle_browse)
        self.query_button = QtWidgets.QPushButton("Query DB")
        self.query_button.setIcon(qtawesome.icon('mdi6.database-search-outline'))
        self.query_button.clicked.connect(self.query_db_clicked)

        file_layout = QtWidgets.QHBoxLayout()
        file_layout.addWidget(self.path_edit)
        file_layout.addWidget(self.browse_btn)
        file_layout.addWidget(self.query_button)
        layout.addRow("Database Name/Path:", file_layout)

        # --- 2. File Rotation (Size-based) ---
        self.rotate_cb = QtWidgets.QCheckBox("Enable File Rotation (Limit Size)")
        self.rotate_cb.setChecked(self.config.max_file_size_mb is not None)
        self.rotate_cb.setEnabled(False)
        self.rotate_cb.stateChanged.connect(self.toggle_rotation_ui)
        self.rotate_cb.stateChanged.connect(self.config_changed)
        layout.addRow(self.rotate_cb)

        # Max Size (MB)
        self.size_spin = QtWidgets.QDoubleSpinBox()
        self.size_spin.setRange(0.1, 9999.0)
        self.size_spin.setSuffix(" MB")
        self.size_spin.setValue(self.config.max_file_size_mb or 100.0)
        self.size_spin.valueChanged.connect(self.config_changed)
        layout.addRow("Max File Size:", self.size_spin)

        # Check Interval (Packets)
        self.interval_spin = QtWidgets.QSpinBox()
        self.interval_spin.setRange(1, 10000)
        self.interval_spin.setValue(self.config.size_check_interval)
        self.interval_spin.setSuffix(" Packets")
        self.interval_spin.valueChanged.connect(self.config_changed)
        layout.addRow("Check Interval:", self.interval_spin)

        # --- 3. Time-based Rotation (NEU) ---
        self.time_rotation_cb = QtWidgets.QCheckBox("Enable Time-based Rotation")
        self.time_rotation_cb.setChecked(self.config.dt_newfile > 0)
        self.time_rotation_cb.stateChanged.connect(self.toggle_time_rotation_ui)
        self.time_rotation_cb.stateChanged.connect(self.config_changed)
        layout.addRow(self.time_rotation_cb)

        # Time Interval (Value)
        self.time_spin = QtWidgets.QSpinBox()
        self.time_spin.setRange(1, 999999)
        self.time_spin.setValue(self.config.dt_newfile)
        self.time_spin.valueChanged.connect(self.config_changed)
        layout.addRow("Time Interval:", self.time_spin)

        # Time Unit (Seconds/Hours/Days)
        self.time_unit_combo = QtWidgets.QComboBox()
        self.time_unit_combo.addItems(["seconds", "hours", "days"])
        self.time_unit_combo.setCurrentText(self.config.dt_newfile_unit)
        self.time_unit_combo.currentTextChanged.connect(self.config_changed)
        layout.addRow("Time Unit:", self.time_unit_combo)

        # --- 4. Naming Format ---
        self.format_edit = QtWidgets.QLineEdit(self.config.file_format)
        self.format_edit.textChanged.connect(self.config_changed)
        layout.addRow("File Naming Format:", self.format_edit)

        # --- 5. Date Format ---
        self.date_format_edit = QtWidgets.QLineEdit(self.config.filedateformat)
        self.date_format_edit.textChanged.connect(self.config_changed)
        layout.addRow("Date Format (strftime):", self.date_format_edit)

        # --- 6. Live Preview Label ---
        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setStyleSheet(
            "color: gray; font-style: italic; font-size: 11px;"
        )
        self.preview_label.setWordWrap(True)
        layout.addRow("Filename Preview:", self.preview_label)

        # --- UI Initialization ---
        self.toggle_rotation_ui()
        self.toggle_time_rotation_ui()
        self.update_preview()

        main_layout.addLayout(layout)

    def toggle_rotation_ui(self):
        """Enables/Disables size-based rotation sub-settings."""
        enabled = self.rotate_cb.isChecked()
        self.size_spin.setEnabled(enabled)
        self.interval_spin.setEnabled(enabled)

    def toggle_time_rotation_ui(self):
        """Enables/Disables time-based rotation sub-settings."""
        enabled = self.time_rotation_cb.isChecked()
        self.time_spin.setEnabled(enabled)
        self.time_unit_combo.setEnabled(enabled)

    def get_config(self) -> SqliteConfig:
        """Returns a valid SqliteConfig object based on UI state."""
        max_size = self.size_spin.value() if self.rotate_cb.isChecked() else None
        dt_newfile = self.time_spin.value() if self.time_rotation_cb.isChecked() else 0
        dt_newfile_unit = self.time_unit_combo.currentText() if self.time_rotation_cb.isChecked() else "none"
        c = SqliteConfig(
            dbtype="sqlite",
            filepath=self.path_edit.text(),
            max_file_size_mb=max_size,
            size_check_interval=self.interval_spin.value(),
            file_format=self.format_edit.text(),
            filedateformat=self.date_format_edit.text(),
            dt_newfile=dt_newfile,
            dt_newfile_unit=dt_newfile_unit
        )

        print("config",c)

        return c

    def update_preview(self):
        """Updates the filename preview."""
        config = self.get_config()
        preview_path = DbSqlite.format_filename(
            base_name=config.filepath,
            file_format=config.file_format,
            file_index=1,
            max_file_size_mb=config.max_file_size_mb,
            file_dateformat=config.filedateformat
        )
        self.preview_label.setText(os.path.basename(preview_path))

    def config_changed(self):
        """Triggers preview update and emits the changed config."""
        self.update_preview()
        config = self.get_config()
        self.db_config_changed.emit(config.model_dump())

    def handle_browse(self):
        """Opens a file dialog to select the database path."""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Select SQLite Database", "",
            "DB Files (*.db *.sqlite);;All Files (*)"
        )
        if path:
            self.path_edit.setText(path)

    def query_db_clicked(self):
        """Handles the 'Query DB' button click."""
        config = self.get_config()
        filename = config.filepath
        DbSqliteReader.get_file_info(filename)
        dbtest = DbSqliteReader(config=config)
        test_result = dbtest.check_file_consistency()
        print("Test result", test_result)




class SqliteStatusTableWidget(QtWidgets.QWidget):
    """
    A reusable widget with two QTableWidgets:
    - Generic info table: Timestamp, packets, failures, metadata, device info (single row, updated).
    - SQLite info table: Displays data from status_db[0]['columns_flat_active'].
      Rows are identified by (table_name_db, address).
      Columns: Table Name, Address, Column Name (colname_db), Entries Written.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- Layout ---
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)

        # --- Generic Info Table (Top) ---
        self.generic_infotable = QtWidgets.QTableWidget()
        self._setup_generic_table()

        # --- SQLite Info Table (Bottom) ---
        self.sqlite_infotable = QtWidgets.QTableWidget()
        self._setup_sqlite_table()

        # Add tables to layout
        self.layout.addWidget(QtWidgets.QLabel("General Status:"))
        self.layout.addWidget(self.generic_infotable)
        self.layout.addWidget(QtWidgets.QLabel("Columns Flat Active Status:"))
        self.layout.addWidget(self.sqlite_infotable)



        # Track rows by filename to avoid duplicated
        self.file_keys = {}  #

        # Track rows by (table_name_db, address) to avoid duplicates
        self.row_keys = {}  # {(table_name_db, address): row_index}

    def _setup_generic_table(self):
        """Configure the generic info table."""
        self.generic_infotable.setColumnCount(5)
        self.generic_infotable.setHorizontalHeaderLabels([
            "Filename","Filesize (MB)","Timestamp", "Packets Inserted", "Metadata Inserted"
        ])
        self.generic_infotable.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.generic_infotable.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers
        )

    def _setup_sqlite_table(self):
        """Configure the SQLite info table for columns_flat_active."""
        self.sqlite_infotable.setColumnCount(4)
        self.sqlite_infotable.setHorizontalHeaderLabels([
            "Table Name (table_name_db)", "Address", "Column Name (colname_db)", "Entries Written"
        ])
        self.sqlite_infotable.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.sqlite_infotable.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers
        )

    def update_table(self, status_dict: dict):
        """
        Update both tables with data from a status dictionary.
        - Generic table: Updates the single row with latest values.
        - SQLite table: Updates rows for entries in status_db[0]['columns_flat_active'].
        """
        self._update_generic_table(status_dict)
        self._update_sqlite_table(status_dict)

    def _update_generic_table(self, status_dict: dict):
        """Update the first row in the generic info table."""

        timestamp = datetime.fromtimestamp(status_dict.get("t", 0)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        filename = str(status_dict.get("filename", "NA"))
        try:
            self.file_keys[filename]
        except:
            # Initialize generic table with one row
            self.generic_infotable.insertRow(0)
            for k in self.file_keys.keys():
                self.file_keys[k] +=1

            self.file_keys[filename] = 0


        filesize = "{:.2f}".format(status_dict.get("filesize", 0)/1024/1024)
        packets = str(status_dict.get("packet_inserted", 0))
        failures = str(status_dict.get("packet_inserted_failure", 0))
        metadata = str(status_dict.get("metadata_address_inserted", 0))

        # Extract device info from statistics (first key)
        device_info = "N/A"
        if status_dict.get("statistics"):
            stats = status_dict["statistics"]
            if isinstance(stats, dict):
                device_info = next(iter(stats.keys()), "N/A")

        # Update the first row
        #"Filename", "Filesize", "Timestamp", "Packets Inserted", "Metadata Inserted"
        self.generic_infotable.setItem(0, 0, QtWidgets.QTableWidgetItem(filename))
        self.generic_infotable.setItem(0, 1, QtWidgets.QTableWidgetItem(filesize))
        self.generic_infotable.setItem(0, 2, QtWidgets.QTableWidgetItem(timestamp))
        self.generic_infotable.setItem(0, 3, QtWidgets.QTableWidgetItem(packets))
        self.generic_infotable.setItem(0, 4, QtWidgets.QTableWidgetItem(metadata))

    def _update_sqlite_table(self, status_dict: dict):
        """Update the SQLite table with data from status_db[0]['columns_flat_active']."""
        status_dict = copy.deepcopy(status_dict)
        if not status_dict.get("status_db"):
            return

        db_entry = status_dict["status_db"][0]
        # Get columns_flat_active
        columns_flat_active = db_entry.get("columns_flat_active")
        # Iterate through each entry in status_db[0]
        if True:
            # Iterate through each table in the entry
            for table_name, table_data in columns_flat_active.items():
                if not isinstance(table_data, dict):
                    continue

                table_name_db = table_data.get("table_name_db", "N/A")
                # Process each address in columns_flat_active
                for address, column_data in table_data.items():
                    if not isinstance(column_data, dict):
                        continue

                    colname_db = column_data.get("colname_db", "N/A")
                    entries_written = str(column_data.get("entries_written", "N/A"))

                    # Create a unique key for this row: (table_name_db, address)
                    row_key = (table_name_db, address)

                    # Check if this row already exists
                    if row_key not in self.row_keys:
                        # Add new row
                        row_position = self.sqlite_infotable.rowCount()
                        self.sqlite_infotable.insertRow(row_position)
                        self.sqlite_infotable.setItem(row_position, 0, QtWidgets.QTableWidgetItem(table_name_db))
                        self.sqlite_infotable.setItem(row_position, 1, QtWidgets.QTableWidgetItem(address))
                        self.row_keys[row_key] = row_position

                    # Update the row with new data
                    row = self.row_keys[row_key]
                    self.sqlite_infotable.setItem(row, 2, QtWidgets.QTableWidgetItem(colname_db))
                    self.sqlite_infotable.setItem(row, 3, QtWidgets.QTableWidgetItem(entries_written))

