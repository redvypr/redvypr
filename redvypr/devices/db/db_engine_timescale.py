import json
import os
import sqlite3
import logging
import sys
import os
import pydantic
import typing
from datetime import datetime, timezone
import json
import logging
import copy
from typing import Any, Dict, List, Optional, Iterator
from PyQt6 import QtWidgets, QtCore, QtGui
import qtawesome
import psycopg
from abc import ABC, abstractmethod
from typing import Iterator, Optional, Any, Dict
from redvypr.redvypr_address import RedvyprAddress
from redvypr.redvypr_datadict import RedvyprDatadict
from .db_config_util import DbWriteConfig, sanitize_name_for_db
from redvypr.serialize import serialize_json, deserialize_json

import numpy as np

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db_engine_timescale')
logger.setLevel(logging.DEBUG)



class TimescaleConfig(pydantic.BaseModel):
    dbtype: typing.Literal["timescaledb"] = "timescaledb"
    dbname: str = "postgres"
    user: str = "postgres"
    password: str = "password"
    host: str = "pi5server1"
    port: int = 5433
    write_config: DbWriteConfig = pydantic.Field(default_factory=DbWriteConfig)


class DbTimescaleWriter():
    """
    Db writer for TimescaleDB.
    """

    def __init__(self, config: TimescaleConfig, mode="write"):
        super().__init__()
        self.config = config
        self.conn = None
        self.engine_type = None
        self.file_statistics_total = None
        # Convert the addresses in string format into redvypr addresses
        self.write_config_raddr = self.convert_write_config_raddr(self.config)
        if mode == "write":
            self.file_statistics_total = {'packets_raw_written': 0,
                                          'packets_flat_written': 0,
                                          'metadata_written': 0,
                                          'entries_flat_written': 0,
                                          'columns_flat_active': {}}
            self._tables_flat = {}
            self.init_db_write()


    def connect(self):
        """Implementation of the abstract connect method."""
        #print("Connecting")
        if not self.conn:
            try:
                self.conn = psycopg.connect(dbname = self.config.dbname,
                                            user=self.config.user,
                                            password=self.config.password,
                                            host=self.config.host,
                                            port=self.config.port
                                            )
                #print("Could connect to database")
            except psycopg.Error as e:
                logger.error(f"❌ Connection failed: {e}",exc_info=True)
                raise
        return self.conn

    def init_db_write(self):
        self.connect()
        if self.conn.closed:
            raise RuntimeError("Could not init database (connection failure!)")

        self._initialize_metadata_tables()
        self.numconfig = self._determine_numconfig()
        self._register_config() # Writing the actual config to the database
        self._initialize_data_tables()


    def _execute(self, query: str, params: tuple = ()):
        if self.conn.closed:
            logger.warning("🔄 Connection was closed. Reconnecting...")
            self.connect()

        # Wir erstellen den Cursor manuell ohne 'with', damit er beim Return offen bleibt
        cur = self.conn.cursor()
        try:
            cur.execute(query, params)

            # Wenn es eine Schreiboperation war (INSERT, UPDATE, ALTER, etc.),
            # gibt es keine Spaltenbeschreibungen (cur.description ist None).
            if cur.description is None:
                self.conn.commit()
                cur.close()  # Cursor wird nicht mehr gebraucht
                return None

            # Wenn es ein SELECT war, committen wir (schadet nicht) und geben
            # den OFFENEN Cursor zurück, damit .fetchone() / .fetchall() funktionieren.
            self.conn.commit()
            return cur

        except psycopg.Error as e:
            self.conn.rollback()  # Wichtig bei Postgres: Fehlerzustand bereinigen
            cur.close()
            logger.error(f"❌ SQL Error for query: {query.strip()[:100]}... Error: {e}")
            raise e

    def _execute_list(self, sql_commands: list[tuple]) -> None:
        """
        Executes a list of different SQL commands within a single,
        highly efficient transaction block.
        """
        if not sql_commands:
            return

        if self.conn.closed:
            logger.warning("🔄 Connection was closed. Reconnecting...")
            self.connect()

        # Ein einziger Cursor für alle Befehle garantiert atomare Ingestion
        with self.conn.cursor() as cur:
            try:
                for sql, params in sql_commands:
                    if sql:
                        cur.execute(sql, params)

                # Erst ganz am Ende wird ALLES auf einmal auf die Platte geschrieben
                self.conn.commit()

            except psycopg.Error as e:
                self.conn.rollback()  # Schützt Postgres vor dem Blockade-Zustand
                logger.error(f"❌ Batch SQL Error inside _execute_list: {e}")
                raise e

    def _initialize_metadata_tables(self):
        """Initializes internal tracking tables for TimescaleDB / PostgreSQL."""
        # Main Config table with 'active' status
        self._execute("""
            CREATE TABLE IF NOT EXISTS "_redvypr_config_" (
                uuid TEXT PRIMARY KEY,
                numconfig INTEGER,
                state INTEGER DEFAULT 0,
                name TEXT,
                description TEXT,
                full_config_json TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Table Registry
        self._execute("""
            CREATE TABLE IF NOT EXISTS "_redvypr_tables_" (
                tablename TEXT,
                tablename_db TEXT,
                tabletype TEXT,
                config_uuid TEXT,
                numconfig INTEGER,
                state INTEGER DEFAULT 0,
                PRIMARY KEY (tablename, config_uuid),
                FOREIGN KEY (config_uuid) REFERENCES "_redvypr_config_"(uuid) ON DELETE CASCADE
            );
        """)

        # Address Mapping
        self._execute("""
            CREATE TABLE IF NOT EXISTS "_redvypr_addresses_" (
                address TEXT,
                address_db TEXT,
                tablename TEXT,
                config_uuid TEXT,
                numconfig INTEGER,
                state INTEGER DEFAULT 0,
                datatype TEXT,
                PRIMARY KEY (address, tablename, config_uuid),
                FOREIGN KEY (config_uuid) REFERENCES "_redvypr_config_"(uuid) ON DELETE CASCADE
            );
        """)

        # Create metadata table (PostgreSQL / TimescaleDB Syntax)
        self._execute("""
            CREATE TABLE IF NOT EXISTS redvypr_metadata (
                id BIGSERIAL, 
                redvypr_address TEXT NOT NULL,
                uuid TEXT NOT NULL,
                packetid TEXT,
                device TEXT,
                host TEXT,
                metadata TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id, created_at),
                UNIQUE (redvypr_address, uuid) 
            );
        """)


    def identify_and_check_health(self) -> Dict[str, Any]:
        if not self.conn:
            self.connect()

        # 2. Probe for PostgreSQL
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT version();")
                version_str = cur.fetchone()[0].lower()
                if "postgresql" in version_str:
                    self.engine_type = "postgresql"
                    self.placeholder = "%s"
                    # Check for TimescaleDB
                    try:
                        cur.execute(
                            "SELECT 1 FROM pg_extension WHERE extname = 'timescaledb';")
                        is_timescale = bool(cur.fetchone())
                        if is_timescale:
                            self.engine_type = "timescale"
                    except Exception:
                        self.conn.rollback()

                    self.conn.commit()  # Alles okay, Transaktion abschließen

        except Exception as e:
            print(f"Exception test timescaledb:{e}")
            self.conn.rollback()

        health = {
            "engine": self.engine_type,
            "is_timescale": is_timescale,
            "tables_exist": False,
            "can_write": False
        }

        if not self.conn:
            return health

        print(f"database Engine type:{self.engine_type}")
        # Cursor manuell öffnen für maximale Kompatibilität
        cur = self.conn.cursor()
        try:
            if True:
                # PostgreSQL Syntax (Wichtig: Spalte * oder 1 nach SELECT)
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'redvypr_packets');"
                )
                res = cur.fetchone()
                health["tables_exist"] = bool(res[0]) if res else False

            # 2. Schreibrechte prüfen
            try:
                cur.execute("CREATE TEMPORARY TABLE _health_test (id INTEGER);")
                cur.execute("DROP TABLE _health_test;")
                health["can_write"] = True
                self.conn.commit()
            except Exception:
                health["can_write"] = False
                self.conn.rollback()

        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
        finally:
            cur.close()

        return health

    def __enter__(self):
        """Allows usage: with DatabaseInstance as db:"""
        self.connect()
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

    def get_status(self):
        return self.file_statistics_total

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

    def _determine_numconfig(self) -> int:
        """Determines the next available numconfig or retrieves the existing one for this UUID."""
        uuid = self.config.write_config.uuid

        # 1. Check if the configuration already exists (using %s placeholder)
        cursor = self._execute(
            "SELECT numconfig FROM _redvypr_config_ WHERE uuid = %s", (uuid,)
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        # 2. Get the maximum numconfig used so far to increment it
        cursor = self._execute("SELECT MAX(numconfig) FROM _redvypr_config_")
        max_row = cursor.fetchone()
        if max_row and max_row[0] is not None:
            return max_row[0] + 1

        # Fallback if it is the very first configuration entry
        return 1

    def _register_config(self):
        """Saves configuration and ensures only the current one is marked as active."""
        wc = self.config.write_config

        try:
            # 1. Set all existing configs to inactive (state = 0)
            self._execute("UPDATE _redvypr_config_ SET state = 0")

            # 2. Insert or Update current config as active (state = 1) using PostgreSQL Upsert
            # We assume 'uuid' is the PRIMARY KEY of the _redvypr_config_ table.
            self._execute("""
                INSERT INTO _redvypr_config_ (uuid, numconfig, state, name, description, full_config_json)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (uuid) DO UPDATE SET
                    numconfig = EXCLUDED.numconfig,
                    state = EXCLUDED.state,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    full_config_json = EXCLUDED.full_config_json
            """, (
                wc.uuid,
                self.numconfig,
                1,
                wc.name,
                wc.description,
                wc.model_dump_json()
            ))

        except Exception as e:
            logger.error(f"❌ Failed to register configuration in TimescaleDB: {e}")
            raise e

    def _initialize_data_tables(self):
        """Dynamically creates data tables based on TimescaleDB."""
        wc = self.config.write_config

        for table_name, t_cfg in wc.tables.items():
            # Update Table Metadata - mark as active (1) for this config
            table_name_db = sanitize_name_for_db(table_name)

            # Update statistics
            try:
                self.file_statistics_total['columns_flat_active'][table_name]
            except KeyError:  # 'except:' ohne Typ ist in Python unschön, hier zu KeyError korrigiert
                self.file_statistics_total['columns_flat_active'][table_name] = {
                    'table_name_db': table_name_db}

            # 1. HINWEIS: 'INSERT OR REPLACE' wird zu 'INSERT ... ON CONFLICT' in PostgreSQL
            # Voraussetzung: tablename und config_uuid (oder ähnliche) müssen ein UNIQUE Constraint in '_redvypr_tables_' haben!
            self._execute("""
                INSERT INTO _redvypr_tables_ (tablename, tablename_db, tabletype, config_uuid, numconfig)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tablename, config_uuid) DO UPDATE SET
                    tablename_db = EXCLUDED.tablename_db,
                    tabletype = EXCLUDED.tabletype,
                    numconfig = EXCLUDED.numconfig
            """, (table_name, table_name_db, t_cfg.tabletype, wc.uuid, self.numconfig))

            # 2. Datentypen für PostgreSQL/Timescale angepasst
            # 't_packet' oder 't' MUSS als Primärschlüssel/Zeitspalte für die Hypertable dienen.
            # In Timescale dürfen diese Spalten NICHT einfach NULL sein, wenn sie für die Partitionierung genutzt werden.
            columns = [
                "numconfig INTEGER",
                "numpacket INTEGER",
                "t_packet TIMESTAMPTZ NOT NULL",
                # DATETIME wird zu TIMESTAMPTZ (mit Zeitzone)
                "t TIMESTAMPTZ"
            ]

            if t_cfg.tabletype == "redvypr_datapacket":
                columns.append("redvypr_address TEXT NOT NULL")
                columns.append("packetid TEXT")
                columns.append("publisher TEXT")
                columns.append("device TEXT")
                columns.append("host TEXT")
                columns.append(
                    "uuid TEXT")  # SQLite erlaubt typenlose Spalten, Postgres braucht explizit TEXT
                columns.append("data TEXT NOT NULL")
            else:
                for addr in t_cfg.addresses:
                    col_name_db = sanitize_name_for_db(addr)

                    # 'INSERT OR REPLACE' zu 'ON CONFLICT' für Adressen
                    self._execute("""
                        INSERT INTO _redvypr_addresses_ (address, address_db, tablename, config_uuid, numconfig, state)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (address, tablename, config_uuid) DO UPDATE SET
                            address_db = EXCLUDED.address_db,
                            tablename = EXCLUDED.tablename,
                            numconfig = EXCLUDED.numconfig,
                            state = EXCLUDED.state
                    """, (addr, col_name_db, table_name, wc.uuid, self.numconfig, 0))

            # 3. Tabelle erstellen (Identifier in Anführungszeichen setzen, falls Großbuchstaben/Sonderzeichen enthalten sind)
            self._execute(
                f'CREATE TABLE IF NOT EXISTS "{table_name_db}" ({", ".join(columns)})'
            )

            # 4. TIMESCALEDB SPEZIFISCH: In Hypertable konvertieren
            # Wir prüfen vorher, ob es bereits eine Hypertable ist, um Fehler zu vermeiden.
            # Hier wird 't_packet' als Zeit-Achse gewählt.
            self._execute(f"""
                SELECT create_hypertable('"{table_name_db}"', 't_packet', if_not_exists => TRUE);
            """)

    def add_metadata(self, address: str, uuid: str,
                     metadata_dict: dict, mode: str = "merge"):

        try:
            raddr = RedvyprAddress(address, uuid=uuid)
            packetid = raddr.packetid
            device = raddr.device
            host = raddr.host
        except Exception:
            logger.info("Could not get address details, will use None instead",
                        exc_info=True)
            packetid, device, host = None, None, None

        # PostgreSQL Upsert syntax
        sql = """
            INSERT INTO redvypr_metadata (redvypr_address, uuid, metadata, packetid, device, host)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (redvypr_address, uuid) DO UPDATE SET
                metadata = EXCLUDED.metadata,
                created_at = CURRENT_TIMESTAMP;
        """

        # Psycopg natively serializes Python dicts if the column type is JSONB
        sql_data = (address, uuid, serialize_json(metadata_dict), packetid, device, host)

        try:
            self._execute(sql, sql_data)
        except Exception as e:
            raise RuntimeError(
                f"Error writing metadata with commands:{sql=} and data:{sql_data=}") from e

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
                    if raddr.matches_packetfilter(data):
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
                            rdata = RedvyprDatadict(data)
                            data_expanded = rdata.expand_data()
                            #print("data_expanded all", data_expanded)
                            #print("data_expanded",data_expanded.keys())
                        else:
                            #(t, data, datakey, raddress, address_format='k,i,h,d,p'):
                            data_expanded = {}
                            data_expanded_tmp = RedvyprDatadict.create_expanded_datadict(t=tdata, data=data_addr, datakey=raddr.datakey, raddress=raddr)
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
                                                         value=self.serialize_value(data_addr_write_final[0]))

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

                            try:
                                self._execute_list(sql_commands)
                            except:
                                logger.warning("Error writing",exc_info=True)
                            flag_packet_written = True
                            flag_address_match = True  # Packet for address found, no need to look for further addresses

        if flag_packet_written:
            self.file_statistics_total['packets_flat_written'] += 1

    @staticmethod
    def serialize_value(value):
        """
        Serialize a value for TimescaleDB (PostgreSQL) storage:
        - NumPy arrays → bytes/memoryview (BYTEA)
        - list/dict → JSON string or psycopg Json object (JSONB)
        - Other types → unchanged
        """
        if isinstance(value, np.ndarray):
            # tobytes() liefert ein bytes-Objekt, das psycopg nativ als BYTEA mappt
            return value.tobytes()
        elif isinstance(value, (list, dict)):
            # Für PostgreSQL/Timescale nutzt man idealerweise JSONB.
            # Wenn du psycopg2 nutzt, kannst du 'from psycopg2.extras import Json' nutzen.
            # Alternativ hier als valider JSON-String (Postgres parst den String im JSONB-Feld):
            return serialize_json(value)
        elif isinstance(value, (bytes, bytearray)):
            return bytes(value)  # Wird zu BYTEA
        else:
            return value  # INT, FLOAT, TEXT, etc. bleiben nativ

    def check_addr_in_table(self, address: str, table_name: str, value: any):
        """
        Ensures that a specific address exists as a column in the TimescaleDB table.

        Checks the local cache, metadata table, and the physical PostgreSQL schema.
        If the column is missing in any of these, it maps the Python data type
        to PostgreSQL, alters the table, and updates all registries.

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

        # 2. Determine TimescaleDB (PostgreSQL) data type from Python type
        if isinstance(value, int):
            sql_type = "INTEGER"
            type_str = "int"
        elif isinstance(value, (bytes, bytearray)):
            sql_type = "BYTEA"
            type_str = "bytes"
        elif isinstance(value, np.ndarray):
            sql_type = "BYTEA"
            type_str = "ndarray"
        elif isinstance(value, list):
            sql_type = "JSONB"
            type_str = "list"
        elif isinstance(value, dict):
            sql_type = "JSONB"
            type_str = "dict"
        elif isinstance(value, float):
            sql_type = "DOUBLE PRECISION"
            type_str = "float"
        elif isinstance(value, bool):
            sql_type = "BOOLEAN"
            type_str = "bool"
        else:
            sql_type = "TEXT"
            type_str = type(value).__name__

        # 3. Physical Schema Check (Does the column actually exist in PostgreSQL?)
        # We query the standard ANSI information_schema instead of SQLite's PRAGMA.
        # Note: 'table_name_db' must be lowercased in the query if sanitized that way,
        # as PostgreSQL stores unquoted identifiers in lowercase.
        cursor = self._execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s AND column_name = %s
        """, (table_name_db.lower(), address_db.lower()))

        column_exists = cursor.fetchone() is not None

        if not column_exists:
            logger.info(
                f"Adding missing column '{address_db}' ({sql_type}) to table '{table_name_db}'")
            try:
                # Dynamic DDL: Identifiers must be enclosed in double quotes to handle mixed case/special chars safely
                self._execute(
                    f'ALTER TABLE "{table_name_db}" ADD COLUMN "{address_db}" {sql_type}')
            except Exception as e:
                # PostgreSQL driver (psycopg) raises specific error states.
                # Error code '42701' corresponds to 'duplicate_column' in PostgreSQL.
                if hasattr(e, 'pgcode') and e.pgcode == '42701':
                    pass
                elif "already exists" in str(e).lower():
                    pass
                else:
                    raise e

        # 4. Metadata Registry Check (_redvypr_addresses_ table)
        cursor = self._execute("""
            SELECT 1 FROM _redvypr_addresses_ 
            WHERE address_db = %s AND tablename = %s AND config_uuid = %s
        """, (address_db, table_name, self.config.write_config.uuid))

        if not cursor.fetchone():
            # Standard PostgreSQL upsert using ON CONFLICT instead of INSERT OR REPLACE
            self._execute("""
                INSERT INTO _redvypr_addresses_ 
                (address, address_db, tablename, config_uuid, numconfig, state, datatype)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (address, tablename, config_uuid) DO UPDATE SET
                    address_db = EXCLUDED.address_db,
                    tablename = EXCLUDED.tablename,
                    numconfig = EXCLUDED.numconfig,
                    state = EXCLUDED.state,
                    datatype = EXCLUDED.datatype
            """, (address, address_db, table_name, self.config.write_config.uuid,
                  self.numconfig, 0, type_str))

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
        table_name_db = sanitize_name_for_db(table_name)
        address_db = sanitize_name_for_db(address)

        # 1. Change placeholders to %s for PostgreSQL/TimescaleDB
        # 2. Quote identifiers with double quotes to ensure case-safety
        sql = f"""
            INSERT INTO "{table_name_db}" (t, t_packet, numpacket, numconfig, "{address_db}")
            VALUES (to_timestamp(%s), to_timestamp(%s), %s, %s, %s)                 
        """

        sql_command = (sql, (
            t,
            t_packet,
            numpacket,
            self.numconfig,
            data
        ))

        return sql_command

    def get_sql_insert_datapacket(self, table_name: str,
                                  data_dict: Dict[str, Any]) -> tuple | None:
        """
        Inserts a data packet into the table_name of the TimescaleDB database.
        """
        try:
            # 1. Sanitize table name and prepare addressing / timing information
            table_name_db = sanitize_name_for_db(table_name)
            raddr = RedvyprAddress(data_dict)

            # Use 't' from the main dict for the entry timestamp
            ts_utc_all = data_dict.get('t', -1)
            # If t is a list, take the first element
            try:
                ts_utc = ts_utc_all[0]
            except (TypeError, IndexError):  # Replaced bare except with explicit types
                ts_utc = ts_utc_all

            # Extract internal redvypr metadata
            rv_meta = data_dict.get('_redvypr', {})
            ts_pkt_utc = rv_meta.get('t', -1)

            # 2. Prepare data for SQL
            data_dict_json = serialize_json(data_dict)

            # 3. Change placeholders to %s and enforce quoted table names
            sql = f"""
                INSERT INTO "{table_name_db}" 
                (numconfig, t, t_packet, data, redvypr_address, host, publisher, device, packetid, numpacket, uuid) 
                VALUES (%s,to_timestamp(%s),to_timestamp(%s),%s,%s,%s,%s,%s,%s,%s,%s)
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
            logger.error(
                f"❌ Failed to create sql command for insert packet into TimescaleDB: {e}")
            return None



class TimescaleDbConfigWidget(QtWidgets.QWidget):
    """
    A dedicated widget for configuring and testing
    database connection settings based on a Pydantic model.
    """
    db_config_changed = QtCore.Signal(dict)
    def __init__(self, initial_config: TimescaleConfig, parent=None):
        super().__init__(parent)
        self.initial_config = initial_config
        self.input_fields: typing.Dict[str, QtWidgets.QLineEdit] = {}
        self.setup_ui()

    def setup_ui(self):
        """Creates a form layout for the DB fields and adds the Test button/label."""

        # Main layout for the entire widget (Vertical arrangement)
        main_layout = QtWidgets.QVBoxLayout(self)

        # 1. Form for input fields
        form_layout = QtWidgets.QFormLayout()
        form_layout.setLabelAlignment(QtCore.Qt.AlignLeft)

        db_fields = ['dbname', 'user', 'password', 'host', 'port']

        for field_name in db_fields:
            field_value = getattr(self.initial_config, field_name)
            line_edit = QtWidgets.QLineEdit(str(field_value))

            if field_name == 'password':
                # --- NEW: Password field with toggle button ---
                line_edit.setEchoMode(QtWidgets.QLineEdit.Password)

                # Container for password field and button
                password_container = QtWidgets.QWidget()
                h_layout = QtWidgets.QHBoxLayout(password_container)
                h_layout.setContentsMargins(0, 0, 0, 0)
                h_layout.addWidget(line_edit)

                show_button = QtWidgets.QPushButton("Show")
                show_button.setCheckable(True)
                show_button.setToolTip("Toggle password visibility")
                # Connect the button's checked state to the toggle function
                show_button.clicked.connect(
                    lambda checked, le=line_edit: self.toggle_password_visibility(le,
                                                                                  checked))
                h_layout.addWidget(show_button)

                self.input_fields[field_name] = line_edit
                form_layout.addRow(f"{field_name.capitalize()}:", password_container)

            elif field_name == 'port':
                # Use QIntValidator from QtGui
                line_edit.setValidator(QtGui.QIntValidator(1, 65535, self))
                self.input_fields[field_name] = line_edit
                form_layout.addRow(f"{field_name.capitalize()}:", line_edit)
            else:
                self.input_fields[field_name] = line_edit
                form_layout.addRow(f"{field_name.capitalize()}:", line_edit)

            line_edit.textChanged.connect(self.config_changed)
        main_layout.addLayout(form_layout)

        # 2. Test/Query Buttons
        self.test_button = QtWidgets.QPushButton("Test DB Connection")
        # Placeholder icon from qtawesome stub
        icon = qtawesome.icon('mdi6.database-outline')
        self.test_button.setIcon(icon)
        self.query_button = QtWidgets.QPushButton("Query DB")
        icon = qtawesome.icon('mdi6.database-search-outline')
        self.query_button.setIcon(icon)
        self.button_layout = QtWidgets.QHBoxLayout()
        self.button_layout.addWidget(self.test_button)
        self.button_layout.addWidget(self.query_button)

        self.test_button.clicked.connect(self.test_connection_clicked)
        self.query_button.clicked.connect(self.query_db_clicked)
        main_layout.addLayout(self.button_layout)

    def config_changed(self):
        config = self.get_config()
        print(f"TimescaleDb config changed:{config}")
        self.db_config_changed.emit(config.model_dump())

    def toggle_password_visibility(self, line_edit: QtWidgets.QLineEdit, checked: bool):
        """Toggles the echo mode of the password field based on the button state."""
        if checked:
            line_edit.setEchoMode(QtWidgets.QLineEdit.Normal)
        else:
            line_edit.setEchoMode(QtWidgets.QLineEdit.Password)

    def get_config(self) -> TimescaleConfig:
        """
        Retrieves current values from QLineEdits and creates a new
        TimescaleConfig instance, ensuring proper type conversion.
        """

        # 1. Start with base configuration data (incl. default values for unexposed fields)
        config_data = self.initial_config.model_dump()

        # 2. Overwrite exposed DB fields with current UI values
        for field_name, line_edit in self.input_fields.items():
            value = line_edit.text()

            # Type conversion back to Pydantic model
            if field_name == 'port':
                try:
                    config_data[field_name] = int(value)
                except ValueError:
                    # Fallback to default value on invalid input
                    config_data[field_name] = self.initial_config.port
            else:
                config_data[field_name] = value

        # 3. Create and validate the new Pydantic instance
        try:
            return TimescaleConfig(**config_data)
        except pydantic.ValidationError as e:
            print(f"Configuration Validation Error: {e}")
            return self.initial_config

    def query_db_clicked(self):
        config = self.get_config()
        db = DbTimescaleWriter(config)
        self.query_widdget = DBQueryDialog(db_instance=db)
        self.query_widdget.show()

    def test_connection_clicked(self):
        # pconfig is an instance of TimescaleConfig
        pconfig = self.get_config()

        try:
            diag = TimescaleDBStatusDialog(pconfig, self)
            diag.exec_()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Connection Error",
                                           f"Failed: {str(e)}")





class TimescaleDBStatusDialog(QtWidgets.QDialog):
    """
    A Database Status and Management Dialog.
    Allows users to verify connection health and manually initialize the basic tables if not present.
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.db = DbTimescaleWriter(config=config)


        # Default state ensures dictionary is always subscriptable
        self.status = {
            'engine': 'Unknown',
            'connected': False,
            'tables_exist': False,
            'can_write': False,
            'is_timescale': False
        }



        # Step 1: Perform observational checks
        self.refresh_db_status()

        # Step 2: Configure Dialog window
        self.setWindowTitle(f"Database Status: {self.status.get('engine')}")
        self.setMinimumWidth(480)
        self.setup_ui()

    def refresh_db_status(self):
        """
        Connects to the database to identify engine type and health parameters.
        No structural changes (schema) are made here.
        """
        try:
            with self.db:
                    # Queries system tables (information_schema) to check health
                health = self.db.identify_and_check_health()
                if isinstance(health, dict):
                    self.status.update(health)
                    self.status['connected'] = True
        except Exception as e:
            self.status['connected'] = False
            self.status['error'] = str(e)
            self.status['engine'] = "Discovery Failed"

    def setup_ui(self):
        """Creates a modern, icon-driven interface."""
        # Clean up existing layout if this is a refresh
        if self.layout():
            QtWidgets.QWidget().setLayout(self.layout())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(18)

        # --- Section 1: Header ---
        header_layout = QtWidgets.QHBoxLayout()
        is_connected = self.status.get('connected', False)

        # Large status icon
        main_icon = 'mdi6.database-check' if is_connected else 'mdi6.database-off'
        icon_color = "#38A169" if is_connected else "#E53E3E"

        icon_lbl = QtWidgets.QLabel()
        icon_lbl.setPixmap(qtawesome.icon(main_icon, color=icon_color).pixmap(54, 54))

        title_vbox = QtWidgets.QVBoxLayout()
        title_lbl = QtWidgets.QLabel(
            f"<span style='font-size: 18px; font-weight: bold;'>{self.status.get('engine')}</span>")
        subtitle = "TimescaleDB Optimized" if self.status.get(
            'is_timescale') else "Standard SQL Engine"
        subtitle_lbl = QtWidgets.QLabel(subtitle)
        subtitle_lbl.setStyleSheet("color: #718096;")

        title_vbox.addWidget(title_lbl)
        title_vbox.addWidget(subtitle_lbl)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(title_vbox)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Horizontal separator
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setStyleSheet("background-color: #E2E8F0;")
        layout.addWidget(line)

        # --- Section 2: Error Feedback ---
        error_msg = self.status.get('error')
        if error_msg:
            err_panel = QtWidgets.QLabel(f"<b>Connection Error:</b><br>{error_msg}")
            err_panel.setWordWrap(True)
            err_panel.setStyleSheet("""
                background-color: #FFF5F5; color: #C53030; padding: 12px; 
                border: 1px solid #FEB2B2; border-radius: 6px; font-family: monospace;
            """)
            layout.addWidget(err_panel)

        # --- Section 3: Status Grid ---
        grid = QtWidgets.QGridLayout()
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(1, 1)

        def add_status_row(row, label, key, icon_name):
            active = self.status.get(key, False)
            color = "#38A169" if active else "#E53E3E"

            ico = QtWidgets.QLabel()
            ico.setPixmap(qtawesome.icon(icon_name, color=color).pixmap(22, 22))

            txt_label = QtWidgets.QLabel(f"<b>{label}</b>")

            status_text = "Verified / Ready" if active else "Missing / Denied"
            val_lbl = QtWidgets.QLabel(status_text)
            val_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")

            grid.addWidget(ico, row, 0)
            grid.addWidget(txt_label, row, 1)
            grid.addWidget(val_lbl, row, 2)

        add_status_row(0, "Network Link", "connected", 'fa5s.network-wired')
        add_status_row(1, "Tables (Schema)", "tables_exist", 'fa5s.table')
        add_status_row(2, "Write Access", "can_write", 'fa5s.file-signature')

        layout.addLayout(grid)
        layout.addSpacing(10)

        # --- Section 4: Action Button ---
        self.init_btn = QtWidgets.QPushButton(" Initialize Database Schema")
        self.init_btn.setIcon(qtawesome.icon('fa5s.magic'))
        self.init_btn.setFixedHeight(42)

        # User Choice Logic: Enable only if tables are missing and write is allowed
        missing_tables = not self.status.get('tables_exist', False)
        can_write = self.status.get('can_write', False)

        if is_connected and missing_tables and can_write:
            self.init_btn.setEnabled(True)
            self.init_btn.setStyleSheet("""
                QPushButton { background-color: #3182CE; color: white; border-radius: 6px; font-weight: bold; }
                QPushButton:hover { background-color: #2B6CB0; }
            """)
        else:
            self.init_btn.setEnabled(False)
            self.init_btn.setToolTip(
                "Initialization unavailable: Connection issues, tables already exist, or read-only access.")

        self.init_btn.clicked.connect(self.run_manual_init)
        layout.addWidget(self.init_btn)

        # --- Section 5: Dialog Controls ---
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def run_manual_init(self):
        """Executes the setup_schema script upon explicit user confirmation."""
        msg = ("Do you want to create the database tables and metadata schema now?\n\n"
               "This will execute the 'setup_schema' script on the target server.")

        choice = QtWidgets.QMessageBox.question(
            self, "Confirm Schema Setup", msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if choice == QtWidgets.QMessageBox.Yes:
            try:
                # Explicitly call the write operation
                with self.db:
                    self.db.setup_schema()

                QtWidgets.QMessageBox.information(self, "Success",
                                                  "Database schema initialized successfully.")

                # Refresh data and UI to show the new green state
                self.refresh_db_status()
                self.setup_ui()

            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Setup Failed",
                                               f"Could not initialize schema:\n{str(e)}")


class DBQueryDialog(QtWidgets.QDialog):
    """
    Dialog to browse both Packet and Metadata inventory using Tabs.
    """
    items_chosen = QtCore.Signal(list)

    def __init__(self, db_instance, parent=None, select_mode=False):
        super().__init__(parent)
        self.db = db_instance
        self.select_mode = select_mode
        self.selected_data = None

        if self.select_mode:
            self.setWindowTitle("Select Stream from Inventory")
        else:
            self.setWindowTitle("Database Inventory Browser")

        self.resize(1200, 700)  # Etwas breiter wegen der zusätzlichen UUID Spalte
        self.setup_ui()
        self.refresh_data()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # --- Header with Info and Refresh ---
        header = QtWidgets.QHBoxLayout()
        title_vbox = QtWidgets.QVBoxLayout()
        title_label = QtWidgets.QLabel("<b>Database Inventory Overview</b>")
        title_label.setStyleSheet("font-size: 14px;")

        self.db_info_label = QtWidgets.QLabel("Connecting...")
        self.db_info_label.setStyleSheet("color: #444; font-size: 11px;")

        title_vbox.addWidget(title_label)
        title_vbox.addWidget(self.db_info_label)
        header.addLayout(title_vbox)
        header.addStretch()

        self.refresh_button = QtWidgets.QPushButton(" Refresh All")
        self.refresh_button.setIcon(qtawesome.icon('fa5s.sync-alt'))
        self.refresh_button.clicked.connect(self.refresh_data)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        # --- Tabs ---
        self.tabs = QtWidgets.QTabWidget()
        self.packet_table = self._create_table_widget(tabletype="datastream")
        self.tabs.addTab(self.packet_table, qtawesome.icon('fa5s.box'), "Packets")
        self.meta_table = self._create_table_widget(tabletype="metadata")
        self.tabs.addTab(self.meta_table, qtawesome.icon('fa5s.info-circle'),
                         "Metadata")
        layout.addWidget(self.tabs)

        # --- Footer ---
        footer = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Ready")
        footer.addWidget(self.status_label)
        footer.addStretch()

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    def _create_table_widget(self, tabletype: typing.Literal["datastream","metadata"]="datastream") -> QtWidgets.QTableWidget:
        """Helper to create a standardized table with the new header order."""
        #print(f"Creating table: {tabletype}")
        table = QtWidgets.QTableWidget()
        table.__tabletype = tabletype
        headers = ["Address", "Packet ID", "Device", "Host", "UUID", "Count",
                   "First Seen", "Last Seen"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        if table.__tabletype == "metadata":
            table.setColumnHidden(1, True) # Packet id
            table.setColumnHidden(2, True)  # device
            table.setColumnHidden(3, True)  # host

        if self.select_mode:
            table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            table.customContextMenuRequested.connect(self.show_context_menu)
            table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        return table

    def refresh_data(self):
        """Fetches data and updates connection info labels."""
        self.status_label.setText("Fetching data...")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)

        try:
            with self.db as connected_db:
                # 1. Update DB Meta Info
                connected_db.identify_and_setup()
                engine = connected_db.engine_type.upper()
                params = getattr(self.db, 'conn_params', {})
                source = f"{params.get('host', 'unknown')}:{params.get('port', '')}"

                self.db_info_label.setText(
                    f"Connected to: <b>{engine}</b> | Source: <i>{source}</i>")

                # 2. Fetch Stats with common keys for both tables
                common_keys = ["redvypr_address", "packetid", "device", "host", "uuid"]
                packet_stats = connected_db.get_unique_combination_stats(
                    keys=common_keys)
                meta_stats = connected_db.get_metadata_info(keys=common_keys)


            # 3. Fill tables
            self._fill_table(self.packet_table, packet_stats)
            self._fill_table(self.meta_table, meta_stats)

            self.status_label.setText(
                f"Updated: {len(packet_stats)} packet streams, {len(meta_stats)} metadata entries.")

        except Exception as e:
            self.db_info_label.setText("Connection failed.")
            QtWidgets.QMessageBox.critical(self, "Error", f"Fetch failed: {e}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _fill_table(self, table: QtWidgets.QTableWidget, stats: list):
        """Fills the table according to the new header index mapping."""
        table.setRowCount(0)
        table.setRowCount(len(stats))

        for row_idx, entry in enumerate(stats):
            # Mapping strictly following your header order
            items = [
                entry.get('redvypr_address', '-'),  # 0
                entry.get('packetid', '-'),  # 1
                entry.get('device', '-'),  # 2
                entry.get('host', '-'),  # 3
                entry.get('uuid', '-'),  # 4
                str(entry.get('count', 0)),  # 5
                entry.get('first_seen', 'N/A'),  # 6
                entry.get('last_seen', 'N/A')  # 7
            ]

            for col_idx, text in enumerate(items):
                item = QtWidgets.QTableWidgetItem(text)
                # Add id to be able to get the entry for later query of db
                if table.__tabletype == "metadata":
                    item.__ids__ = entry.get('ids', [])  # 7

                if col_idx == 5:  # Count column
                    item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                table.setItem(row_idx, col_idx, item)

        # Style & Resizing
        header = table.horizontalHeader()
        table.resizeColumnsToContents()
        header.setStretchLastSection(False)

        # Cap width for long strings
        for i in [0, 1, 4]:  # Address, Packet ID, UUID
            if table.columnWidth(i) > 250:
                table.setColumnWidth(i, 250)

        for i in range(table.columnCount()):
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.Interactive)

        table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

    def show_context_menu(self, position):
        table = self.sender()
        selected_rows = sorted(
            list(set(index.row() for index in table.selectedIndexes())))
        if not selected_rows:
            return

        if table.__tabletype == "datastream":
            menu = QtWidgets.QMenu()
            action_text = f"Add {len(selected_rows)} selected item(s) to Replay"
            select_action = menu.addAction(qtawesome.icon('fa5s.plus-circle'), action_text)
        else:
            menu = QtWidgets.QMenu()
            action_text = f"Get metadata from {len(selected_rows)} selected item(s) for Replay"
            select_action = menu.addAction(qtawesome.icon('fa5s.plus-circle'),
                                           action_text)

        action = menu.exec_(table.viewport().mapToGlobal(position))
        if action == select_action:
            self.emit_selected_items(table, selected_rows)

    def emit_selected_items(self, table, rows):
        """Extracts data with updated index mapping for Replay."""
        results = []
        if table.__tabletype == "datastream":
            for row in rows:
                results.append({
                    "address": table.item(row, 0).text(),
                    "packetid": table.item(row, 1).text(),
                    "uuid": table.item(row, 4).text(),
                    "tstart": table.item(row, 6).text(),
                    "tend": table.item(row, 7).text(),
                    "metadata":None
                })
        else: # Look at the metadata and interprete it
            with self.db as connected_db:
                for row in rows:
                    ids = table.item(row, 0).__ids__
                    metadatalist = connected_db.get_metadata_by_ids(ids)
                    print("Metadatalist",metadatalist)
                    results.append({
                        "address": table.item(row, 0).text(),
                        "packetid": table.item(row, 1).text(),
                        "uuid": table.item(row, 4).text(),
                        "tstart": table.item(row, 6).text(),
                        "tend": table.item(row, 7).text(),
                        "metadata": metadatalist
                    })
        if results:
            self.items_chosen.emit(results)
            self.status_label.setText(
                f"Sent {len(results)} items to Replay controller.")





class TimescaleStatusTableWidget(QtWidgets.QWidget):
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
        self._update_timescale_table(status_dict)

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

    def _update_timescale_table(self, status_dict: dict):
        """Update the SQLite table with data from status_db['columns_flat_active']."""
        status_dict = copy.deepcopy(status_dict)
        if not status_dict.get("status_db"):
            return

        db_entry = status_dict["status_db"]
        # Get columns_flat_active
        columns_flat_active = db_entry.get("columns_flat_active")
        # Iterate through each entry in status_db
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






