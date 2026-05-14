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
from datetime import datetime, timezone
import json
import copy
import logging
from PyQt6 import QtWidgets, QtCore
import qtawesome
from typing import Any, Dict, List, Optional, Iterator
from abc import ABC, abstractmethod
from typing import Iterator, Optional, Any, Dict
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket
from .db_config_util import DbWriteConfig, sanitize_name_for_db, json_safe_dumps, json_safe_loads
import numpy as np

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db_engine_sqlite')
logger.setLevel(logging.DEBUG)


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
        default=None,
        description="Maximum file size in MB before rotating. If None, rotation is disabled."
    )
    size_check_interval: int = pydantic.Field(
        default=100,
        description="Number of packets to wait between file size checks."
    )
    file_format: str = pydantic.Field(
        default="{name}_{filecount}_{filedate}",
        description="Naming template for rotated files. Placeholders: {name}, {filecount}, {filedate}."
    )

    filedateformat: str = pydantic.Field(default='%Y-%m-%d_%H%M%S',
                                         description='Dateformat used in the filename, must be understood by datetime.strftime')
    write_config: DbWriteConfig = pydantic.Field(default_factory=DbWriteConfig)


class DbSqliteReader:
    def __init__(self, config: SqliteConfig):
        """
        Initializes the reader with a specific configuration to check against.
        """
        self.config = config
        self.filepath = config.filepath

    @staticmethod
    def get_file_info(filename: str) -> Dict[str, Any]:
        """
        Static method to inspect a SQLite file for Redvypr metadata without
        requiring a full class instantiation or a config object.

        Useful for UI file browsers or quick pre-loading checks.
        """
        info = {
            "exists": False,
            "is_redvypr": False,
            "config_name": None,
            "config_uuid": None,
            "tables_count": 0,
            "last_entry": None,
            "error": None
        }

        if not os.path.exists(filename):
            return info

        info["exists"] = True
        try:
            # Open in read-only mode to avoid locking issues with active writers
            conn = sqlite3.connect(f"file:{filename}?mode=ro", uri=True)
            cursor = conn.cursor()

            # Check if the main metadata table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='_redvypr_config_'"
            )
            if cursor.fetchone():
                info["is_redvypr"] = True

                # Fetch the active configuration metadata
                cursor.execute(
                    "SELECT name, uuid, created_at, full_config_json FROM _redvypr_config_"
                )
                row = cursor.fetchall()
                print("row",row)
                if row:
                    info["configs"] = []
                    for r in row:
                        c = {}
                        c["config_name"], c["config_uuid"], c["created_at"], c["config_json"] = r
                        # Try to convert JSON to Pydantic model
                        c["config_pydantic"] = SqliteConfig.model_validate_json(c["config_json"])
                        info["configs"].append(c)

                # Count registered tables
                cursor.execute("SELECT COUNT(*) FROM _redvypr_tables_")
                info["tables_count"] = cursor.fetchone()[0]

            conn.close()
        except:
            logger.error("Error in getting file information",exc_info=True)

        print(f"get_file_info():{info=}")
        return info

    def check_file_consistency(self) -> str:
        """
        Compares the physical database structure with the current SqliteConfig.

        Returns
        -------
        "correct"   : All tables and columns required by config exist.
        "incorrect" : Structural conflict (e.g., table exists but has wrong type).
        "partially" : File belongs to project, but some tables/columns are missing (can be expanded).
        "empty"     : File does not exist or contains no Redvypr schema.
        """
        if not os.path.exists(self.filepath):
            return "empty"

        try:
            # Use read-only to be safe
            conn = sqlite3.connect(f"file:{self.filepath}?mode=ro", uri=True)
            cursor = conn.cursor()

            # 1. Basic Schema Check
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='_redvypr_tables_'"
            )
            if not cursor.fetchone():
                conn.close()
                return "empty"

            write_cfg = self.config.write_config
            is_partial = False

            # 2. Iterate through tables defined in the config
            for table_name, t_cfg in write_cfg.tables.items():
                table_name_db = sanitize_name_for_db(table_name)

                # Check if table exists physically
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name_db,)
                )
                if not cursor.fetchone():
                    is_partial = True
                    continue

                # 3. Deep check for 'data_flat' tables (column-level consistency)
                if t_cfg.tabletype == "data_flat":
                    cursor.execute(f"PRAGMA table_info({table_name_db})")
                    existing_cols = [row[1] for row in cursor.fetchall()]

                    for addr in t_cfg.addresses:
                        addr_db = sanitize_name_for_db(addr)
                        if addr_db not in existing_cols:
                            is_partial = True
                            break

            conn.close()

            if is_partial:
                return "partially"
            return "correct"

        except Exception as e:
            logger.error(f"Consistency check failed: {e}")
            return "incorrect"

    def fetch_full_config(self) -> Optional[Dict]:
        """Retrieves the full JSON configuration stored in the database metadata."""
        try:
            conn = sqlite3.connect(f"file:{self.filepath}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT full_config_json FROM _redvypr_config_")
            rows = cursor.fetchall()
            conn.close()
            return json.loads(rows[0]) if rows else None
        except:
            logger.error("Could not fetch configurations",exc_info=True)
            return None


class DbSqliteWriter:
    def __init__(self, config: SqliteConfig):
        self.config = config
        # Initialisierung der Rotations-Parameter
        self.base_name = self.config.filepath
        self.max_file_size_mb = getattr(self.config, 'max_file_size_mb', None)
        self.file_format = getattr(self.config, 'file_format', "{name}_{filecount}")
        self._file_index = -1
        self._packet_counter = 0
        self.size_check_interval = 100  # Alle 100 Pakete prüfen
        self.filepath = self.generate_new_filename()
        self.file_statistics_total = {'packets_raw_written':0,
                                'packets_flat_written':0,
                                'metadata_written':0,
                                'entries_flat_written':0,
                                'columns_flat_active':{}}

        self.file_statistics = {}
        # Convert the addresses in string format into redvypr addresses
        self.write_config_raddr = self.convert_write_config_raddr(self.config)

        # 3. Log the configuration and setup data tables
        self.connect()

    def connect(self):
        """Connects to the sqlite database"""
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
        self.conn = sqlite3.connect(self.filepath)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._initialize_metadata_tables()
        self.numconfig = self._determine_numconfig()
        self._register_config()
        self._initialize_data_tables()
        self._tables_flat = {}


    def _check_rotation(self):
        """Prüft, ob die Datei zu groß ist und rotiert werden muss."""
        if self.max_file_size_mb is None:
            return

        self._packet_counter += 1
        if self._packet_counter >= self.size_check_interval:
            self._packet_counter = 0

            if os.path.exists(self.filepath):
                file_size_mb = os.path.getsize(self.filepath) / (1024 * 1024)
                if file_size_mb >= self.max_file_size_mb:
                    logger.info(
                        f"🔄 Limit {self.max_file_size_mb}MB reached. Rotating...")
                    self.rotate_database()

    def rotate_database(self):
        """Schließt aktuelle DB und öffnet die nächste."""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

        # Neuen Dateinamen generieren
        self.filepath = self.generate_new_filename()

        # Neu verbinden (Initialisiert auch automatisch das Schema)
        self.connect()



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
        """Initializes internal tracking tables with 'active' columns."""
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
            for iaddr,raddr in enumerate(t_cfg["raddresses"]):
                addr = t_cfg["addresses"][iaddr]
                #print("raddr",raddr)
                #print(f"{table_name=},{table_type=},{raddr=}")
                if table_type == "redvypr_datapacket":
                    if raddr.matches_filter(data):
                        #print("Write packet to db table:{table_name}")
                        sql_command = self.get_sql_insert_datapacket(table_name, data)
                        #print(f"{sql_command=}")
                        try:
                            self._execute(sql_command[0],sql_command[1])
                        except:
                            logger.warning(f"Could not insert data:{sql_command}",exc_info=True)
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


                        break
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
                        else:
                            data_expanded = {addr:{}}
                            data_expanded[addr]['t'] = tdata
                            data_expanded[addr]['tpacket'] = tpacket
                            data_expanded[addr]['data'] = data_addr
                            data_expanded[addr]['key'] = None
                            data_expanded[addr]['address'] = addr

                        for addr_write, data_expanded_tmp in data_expanded.items():
                            # Check if addr in table exists
                            #print(f"Checking if {addr_write=} exists in db table:{table_name}")
                            data_addr_write_final = data_expanded_tmp['data']
                            self.check_addr_in_table(address=addr_write, table_name=table_name, value=data_addr_write_final)
                            # Check how many entries we have to write
                            try:
                                nlines = len(tdata)
                            except:
                                nlines = 1
                                tdata = [tdata]

                            # Check how many entries we have to write
                            try:
                                nlines_data = len(data_addr_write_final)
                            except:
                                nlines_data = 1
                                data_addr_write_final = [data_addr_write_final]

                            #print(f"Write data to db table:{table_name}")
                            sql_commands = []
                            for nline in range(nlines):
                                sql_command = self.get_sql_insert_address_data(table_name=table_name,
                                                            address=addr_write,
                                                            t=tdata[nline],
                                                            t_packet=tpacket,
                                                            numpacket=numpacket,
                                                            data=data_addr_write_final[nline])

                                #print(f"{sql_command=}")
                                sql_commands.append(sql_command)
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

                            self._execute_list(sql_commands)
                            flag_packet_written = True
                            break

        if flag_packet_written:
            self.file_statistics[self.filepath]['packets_flat_written'] += 1
            self.file_statistics_total['packets_flat_written'] += 1
            self._check_rotation()




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

        # 2. Determine SQLite data type from Python type
        if isinstance(value, int):
            sql_type = "INTEGER"
        elif isinstance(value, float):
            sql_type = "REAL"
        elif isinstance(value, bool):
            sql_type = "INTEGER"  # SQLite uses 0/1 for booleans
        else:
            sql_type = "TEXT"

        # 3. Physical Schema Check (Does the column actually exist in the table?)
        # PRAGMA table_info returns rows: (id, name, type, notnull, default_value, pk)
        cursor = self.conn.execute(f"PRAGMA table_info({table_name_db})")
        existing_columns = [row[1] for row in cursor.fetchall()]

        if address_db not in existing_columns:
            print(
                f"Adding missing column '{address_db}' ({sql_type}) to table '{table_name_db}'")
            try:
                # SQLite ALTER TABLE does not support parameters for column names
                self._execute(
                    f"ALTER TABLE {table_name_db} ADD COLUMN {address_db} {sql_type}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise e

        # 4. Metadata Registry Check (_redvypr_addresses_ table)
        cursor = self._execute("""
            SELECT 1 FROM _redvypr_addresses_ 
            WHERE address_db = ? AND tablename = ? AND config_uuid = ?
        """, (address_db, table_name, self.config.write_config.uuid))

        if not cursor.fetchone():
            self._execute("""
                INSERT OR REPLACE INTO _redvypr_addresses_ 
                (address, address_db, tablename, config_uuid, numconfig, state)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (address, address_db, table_name, self.config.write_config.uuid,
                  self.numconfig, 0))

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







class SqliteConfigWidget(QtWidgets.QWidget):
    db_config_changed = QtCore.Signal(dict)

    def __init__(self, initial_config: SqliteConfig, parent=None):
        super().__init__(parent)
        self.config = initial_config
        self.setup_ui()

    def setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        layout = QtWidgets.QFormLayout()

        # 1. Base File Path
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

        # 5. Naming Format
        self.format_edit = QtWidgets.QLineEdit(self.config.file_format)
        self.format_edit.textChanged.connect(self.config_changed)
        layout.addRow("File Naming Format:", self.format_edit)

        # 6. Live Preview Label
        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setStyleSheet(
            "color: gray; font-style: italic; font-size: 11px;")
        self.preview_label.setWordWrap(True)
        layout.addRow("Filename Preview:", self.preview_label)

        # 2. Rotation Toggle
        self.rotate_cb = QtWidgets.QCheckBox("Enable File Rotation (Limit Size)")
        self.rotate_cb.setChecked(self.config.max_file_size_mb is not None)
        self.rotate_cb.stateChanged.connect(self.toggle_rotation_ui)
        self.rotate_cb.stateChanged.connect(self.config_changed)
        layout.addRow(self.rotate_cb)

        # 3. Max Size (MB)
        self.size_spin = QtWidgets.QDoubleSpinBox()
        self.size_spin.setRange(0.1, 9999.0)
        self.size_spin.setSuffix(" MB")
        self.size_spin.setValue(self.config.max_file_size_mb or 100.0)
        self.size_spin.valueChanged.connect(self.config_changed)
        layout.addRow("Max File Size:", self.size_spin)

        # 4. Check Interval (Packets)
        self.interval_spin = QtWidgets.QSpinBox()
        self.interval_spin.setRange(1, 10000)
        self.interval_spin.setValue(self.config.size_check_interval)
        self.interval_spin.setSuffix(" Packets")
        self.interval_spin.valueChanged.connect(self.config_changed)
        layout.addRow("Check Interval:", self.interval_spin)


        # UI Initialization
        self.toggle_rotation_ui()
        self.update_preview()

        main_layout.addLayout(layout)

    def update_preview(self):
        """Updates the UI preview using the shared logic from the DB class."""
        config = self.get_config()
        print("Config",config)
        # We simulate the preview for the first file (index 1)
        preview_path = DbSqliteWriter.format_filename(
            base_name=config.filepath,
            file_format=config.file_format,
            file_index=1,
            max_file_size_mb=config.max_file_size_mb,
            file_dateformat=config.filedateformat
        )
        print("Preview path",preview_path)
        # Optional: Display only the filename in the preview for better readability
        self.preview_label.setText(os.path.basename(preview_path))

    def toggle_rotation_ui(self):
        """Enables/Disables sub-settings based on the rotation checkbox."""
        enabled = self.rotate_cb.isChecked()
        self.size_spin.setEnabled(enabled)
        self.interval_spin.setEnabled(enabled)
        #self.format_edit.setEnabled(enabled)
        #self.preview_label.setVisible(enabled)

    def get_config(self) -> SqliteConfig:
        """Returns a valid SqliteConfig object based on UI state."""
        max_size = self.size_spin.value() if self.rotate_cb.isChecked() else None

        return SqliteConfig(
            dbtype="sqlite",
            filepath=self.path_edit.text(),
            max_file_size_mb=max_size,
            size_check_interval=self.interval_spin.value(),
            file_format=self.format_edit.text()
        )

    def config_changed(self):
        """Triggers preview update and emits the changed config."""
        self.update_preview()
        config = self.get_config()
        # Logging to console as in your original script
        # print(f"Sqlite config changed: {config}")
        self.db_config_changed.emit(config.model_dump())

    def handle_browse(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Select SQLite Database", "",
            "DB Files (*.db *.sqlite);;All Files (*)"
        )
        if path:
            self.path_edit.setText(path)

    def query_db_clicked(self):
        config = self.get_config()
        filename = config.filepath
        DbSqliteReader.get_file_info(filename)
        dbtest = DbSqliteReader(config=config)
        test_result = dbtest.check_file_consistency()
        print("Test result",test_result)




class StatusTableWidget(QtWidgets.QWidget):
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

        # Initialize generic table with one row
        self.generic_infotable.insertRow(0)

        # Track rows by (table_name_db, address) to avoid duplicates
        self.row_keys = {}  # {(table_name_db, address): row_index}

    def _setup_generic_table(self):
        """Configure the generic info table."""
        self.generic_infotable.setColumnCount(5)
        self.generic_infotable.setHorizontalHeaderLabels([
            "Timestamp", "Packets Inserted", "Failures",
            "Metadata Inserted", "Device Info"
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
        self.generic_infotable.setItem(0, 0, QtWidgets.QTableWidgetItem(timestamp))
        self.generic_infotable.setItem(0, 1, QtWidgets.QTableWidgetItem(packets))
        self.generic_infotable.setItem(0, 2, QtWidgets.QTableWidgetItem(failures))
        self.generic_infotable.setItem(0, 3, QtWidgets.QTableWidgetItem(metadata))
        self.generic_infotable.setItem(0, 4, QtWidgets.QTableWidgetItem(device_info))

    def _update_sqlite_table(self, status_dict: dict):
        """Update the SQLite table with data from status_db[0]['columns_flat_active']."""
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

