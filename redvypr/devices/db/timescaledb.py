import json
import os
import sqlite3
import logging
import sys
from datetime import datetime, timezone
import psycopg
from abc import ABC, abstractmethod
from typing import Iterator, Optional, Any, Dict
from contextlib import contextmanager
from redvypr.redvypr_address import RedvyprAddress

import numpy as np

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.timescaledb')
logger.setLevel(logging.DEBUG)

from abc import ABC, abstractmethod
import logging
from typing import Any, Dict, List, Optional

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import json
import logging
import psycopg
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Iterator

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RedvyprDB")


class AbstractDatabase(ABC):
    """
    Abstract Base Class for Redvypr Database Connectors.
    Implements the Context Manager Protocol and shared SQL logic.
    """

    def __init__(self):
        self.engine_type = "unknown"
        self.placeholder = "%s"
        self.is_timescale = False
        self._connection = None

    @abstractmethod
    def connect(self):
        """Establish the physical connection to the database."""
        pass

    def __enter__(self):
        """Allows usage: with DatabaseInstance as db:"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ensures the connection is closed when exiting the 'with' block."""
        self.disconnect()

    def disconnect(self):
        """Closes the connection safely."""
        if self._connection:
            try:
                self._connection.close()
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
            finally:
                self._connection = None

    @abstractmethod
    def setup_schema(self):
        """Creates necessary tables and extensions."""
        pass

    @abstractmethod
    def insert_packet(self, data_dict: Dict[str, Any],
                      table_name: str = 'redvypr_packets'):
        """Inserts a single data packet into the database."""
        pass

    @abstractmethod
    def add_metadata(self, address: str, uuid: str, metadata_dict: dict,
                     mode: str = "merge"):
        """Upserts metadata for a specific device/session."""
        pass

    @abstractmethod
    def get_latest_packet(self, table_name: str = 'redvypr_packets') -> Optional[
        Dict[str, Any]]:
        """Returns the most recent packet."""
        pass

    @abstractmethod
    def get_packets_range(self, start_index: int, count: int) -> List[Dict[str, Any]]:
        """Returns a list of packets for a given range."""
        pass

    @abstractmethod
    def get_unique_combination_stats(self, keys: List[str],
                                     filters: Dict[str, str] = None,
                                     table_name: str = 'redvypr_packets') -> List[
        Dict[str, Any]]:
        """
        Groups database records by a custom list of identity columns and returns aggregated
        packet counts along with the time range for each combination.

        This method allows for dynamic "drilling down" into your data. For example, you can
        get a list of all active hosts, or a breakdown of which devices are publishing
        to specific addresses, including when they were first and last active.

        Args:
            keys (List[str]): The columns used for grouping the results.
                Allowed keys: 'redvypr_address', 'packetid', 'device', 'host', 'publisher', 'uuid'.
                The order of keys in the list defines the structure of the returned dictionaries.

            filters (Dict[str, str], optional): A dictionary to narrow down the search
                before grouping.
                - Exact Match: {"host": "pi-lab-01"}
                - Pattern Match: {"redvypr_address": "sensor/%"} (matches any address starting with 'sensor/')
                - Any string containing '%' or '_' will trigger a SQL 'LIKE' search.

            table_name (str): The name of the table to query. Defaults to 'redvypr_packets'.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries. Each dictionary contains:
                - The requested 'keys' (e.g., 'host': 'pi-01').
                - 'count' (int): The number of packets found in this group.
                - 'first_seen' (str): ISO timestamp of the oldest packet in this group.
                - 'last_seen' (str): ISO timestamp of the newest packet in this group.
                The list is sorted by 'last_seen' in descending order (newest activity first).

        Example Usage:
            # 1. Get a list of all unique hosts with their packet counts and activity range:
            db.get_unique_combination_stats(keys=["host"])
            # Result: [
            #   {"host": "pi-01", "count": 120, "first_seen": "2024-01-01T10:00:00", "last_seen": "2024-01-02T15:30:00"},
            #   {"host": "server-01", "count": 500, "first_seen": "2023-12-01T08:00:00", "last_seen": "2023-12-05T12:00:00"}
            # ]

            # 2. Find specific devices on a host to check if they are still online:
            db.get_unique_combination_stats(keys=["host", "device"], filters={"host": "pi-01"})
            # Result: [
            #   {"host": "pi-01", "device": "DHT22", "count": 100, "first_seen": "...", "last_seen": "..."},
            #   {"host": "pi-01", "device": "SHT31", "count": 20, "first_seen": "...", "last_seen": "..."}
            # ]
        """
        pass

    def identify_and_setup(self):
        """Probes the database to identify engine type and set placeholders."""
        if not self._connection:
            return

        # 1. Probe for SQLite
        try:
            with self._connection.cursor() as cur:
                cur.execute("SELECT sqlite_version();")
                self.engine_type = "sqlite"
                self.placeholder = "?"
                return
        except Exception:
            self._connection.rollback()  # Wichtig: Transaktion nach Fehler heilen

        # 2. Probe for PostgreSQL
        try:
            with self._connection.cursor() as cur:
                cur.execute("SELECT version();")
                version_str = cur.fetchone()[0].lower()
                if "postgresql" in version_str:
                    self.engine_type = "postgresql"
                    self.placeholder = "%s"

                    # Check for TimescaleDB
                    try:
                        cur.execute(
                            "SELECT 1 FROM pg_extension WHERE extname = 'timescaledb';")
                        self.is_timescale = bool(cur.fetchone())
                    except Exception:
                        self._connection.rollback()

                    self._connection.commit()  # Alles okay, Transaktion abschließen
                    return
        except Exception:
            self._connection.rollback()

        self.engine_type = "unknown"

    def get_database_info(self, table_name: str = 'redvypr_packets') -> Optional[
        Dict[str, Any]]:
        """Retrieves row count and time range from a table."""
        sql = f"SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM {table_name}"
        try:
            with self._connection.cursor() as cur:
                cur.execute(sql)
                result = cur.fetchone()
                if result and result[0] > 0:
                    return {
                        "measurement_count": result[0],
                        "min_time": result[1].isoformat() if hasattr(result[1],
                                                                     'isoformat') else str(
                            result[1]),
                        "max_time": result[2].isoformat() if hasattr(result[2],
                                                                     'isoformat') else str(
                            result[2])
                    }
        except Exception as e:
            logger.error(f"Failed to get info for {table_name}: {e}")
        return None

    def check_health(self) -> Dict[str, Any]:
        """
        Checks engine type, table existence, and write permissions.
        """
        health = {
            "engine": self.engine_type,
            "is_timescale": self.is_timescale,
            "tables_exist": False,
            "can_write": False
        }

        if not self._connection:
            return health

        self._connection.rollback()

        try:
            with self._connection.cursor() as cur:
                # 1. Check if main tables exist
                if self.engine_type == "sqlite":
                    cur.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='redvypr_packets';")
                else:  # Postgres / MariaDB
                    cur.execute(
                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'redvypr_packets');")

                health["tables_exist"] = bool(cur.fetchone()[0])

                # 2. Check for Write Permissions (Try to create a temporary test table)
                try:
                    cur.execute("CREATE TEMPORARY TABLE _write_test (id int);")
                    cur.execute("DROP TABLE _write_test;")
                    health["can_write"] = True
                except Exception:
                    health["can_write"] = False
                    self._connection.rollback()  # Reset transaction after failed write test

        except Exception as e:
            logger.error(f"Health check failed: {e}")

        return health


class RedvyprTimescaleDb(AbstractDatabase):
    """
    Concrete implementation for TimescaleDB using the elegant API.
    """

    def __init__(self, dbname: str, user: str, password: str,
                 host: str = 'localhost', port: str = '5432'):
        super().__init__()
        self.conn_params = {
            'dbname': dbname, 'user': user, 'password': password,
            'host': host, 'port': port
        }

    def connect(self):
        """Implementation of the abstract connect method."""
        print("Connecting")
        if not self._connection:
            try:
                self._connection = psycopg.connect(**self.conn_params)
                print("Could connect to database")
            except psycopg.Error as e:
                logger.error(f"❌ Connection failed: {e}")
                raise
        return self._connection

    def setup_schema(self, table_name: str = 'redvypr_packets'):
        """Initializes tables and metadata."""
        sql_statements = [
            "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;",
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id SERIAL,
                timestamp TIMESTAMPTZ NOT NULL,
                redvypr_address TEXT NOT NULL,
                packetid TEXT NOT NULL,
                publisher TEXT NOT NULL,
                device TEXT NOT NULL,
                host TEXT NOT NULL,
                numpacket TEXT NOT NULL,
                uuid TEXT NOT NULL,
                timestamp_packet TIMESTAMPTZ NOT NULL,
                data JSONB NOT NULL,
                PRIMARY KEY (id, timestamp)
            );
            """,
            f"SELECT create_hypertable('{table_name}', 'timestamp', if_not_exists => TRUE);",
            """
            CREATE TABLE IF NOT EXISTS redvypr_metadata (
                redvypr_address TEXT NOT NULL,
                uuid TEXT NOT NULL,
                metadata JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (redvypr_address, uuid)
            );
            """
        ]
        try:
            with self._connection.cursor() as cur:
                for statement in sql_statements:
                    cur.execute(statement)
            self._connection.commit()
            logger.info("✅ Schema verified and tables ready.")
        except Exception as e:
            logger.error(f"❌ Schema setup failed: {e}")

    def insert_packet(self, data_dict: Dict[str, Any],
                      table_name: str = 'redvypr_packets'):
        """Inserts a single packet using internal data extraction logic."""
        sql = f"""
            INSERT INTO {table_name} (timestamp, data, redvypr_address, host, publisher, device, packetid, numpacket, timestamp_packet, uuid)
            VALUES ({self.placeholder}, {self.placeholder}, {self.placeholder}, {self.placeholder}, {self.placeholder}, 
                    {self.placeholder}, {self.placeholder}, {self.placeholder}, {self.placeholder}, {self.placeholder});
        """
        try:
            # Assuming data_dict structure: 't' for timestamp, '_redvypr' for metadata
            ts_utc = datetime.fromtimestamp(data_dict['t'], tz=timezone.utc)
            ts_pkt_utc = datetime.fromtimestamp(data_dict['_redvypr']['t'],
                                                tz=timezone.utc)

            # Here you would normally use your RedvyprAddress helper class
            # For this example, we assume it's pre-parsed or manual:
            raddr_data = RedvyprAddress(data_dict)
            numpacket = data_dict['_redvypr']['numpacket']
            raddr = RedvyprAddress(data_dict)
            raddrstr = raddr.to_address_string()
            host = raddr.hostname
            uuid = raddr.uuid
            device = raddr.device
            packetid = raddr.packetid
            publisher = raddr.publisher

            values = (
                ts_utc, json_safe_dumps(data_dict), raddrstr,
                host, publisher, device, packetid,
                numpacket, ts_pkt_utc, uuid)

            with self._connection.cursor() as cur:
                cur.execute(sql, values)
            self._connection.commit()
        except:
            logger.warning(f"❌ Insert failed",exc_info=True)
            print("data dict",data_dict)
            json.dumps(data_dict)

    def add_metadata(self, address: str, uuid: str, metadata_dict: dict,
                     mode: str = "merge"):
        """Upsert metadata with merge or overwrite logic."""
        conflict_action = "metadata = redvypr_metadata.metadata || EXCLUDED.metadata" if mode == "merge" else "metadata = EXCLUDED.metadata"

        sql = f"""
            INSERT INTO redvypr_metadata (redvypr_address, uuid, metadata)
            VALUES ({self.placeholder}, {self.placeholder}, {self.placeholder})
            ON CONFLICT (redvypr_address, uuid) DO UPDATE SET {conflict_action};
        """
        try:
            with self._connection.cursor() as cur:
                cur.execute(sql, (address, uuid, json.dumps(metadata_dict)))
            self._connection.commit()
        except Exception as e:
            logger.error(f"❌ Metadata storage failed: {e}")

    def get_packets_range(self, start_index: int, count: int) -> List[Dict]:
        """Returns a list of packet dictionaries."""
        sql = f"SELECT id, timestamp, data FROM redvypr_packets ORDER BY id ASC LIMIT {self.placeholder} OFFSET {self.placeholder}"
        try:
            with self._connection.cursor() as cur:
                cur.execute(sql, (count, start_index))
                return [{"id": r[0], "timestamp": r[1], "data": r[2]} for r in
                        cur.fetchall()]
        except Exception as e:
            logger.error(f"❌ Range retrieval failed: {e}")
            return []

    def get_latest_packet(self, table_name: str = 'redvypr_packets') -> Optional[
        Dict[str, Any]]:
        """
        Fetches the most recent packet from the database.
        Returns None if the table is empty.
        """
        # We sort by 'timestamp' (TimescaleDB primary dimension) or 'id'
        sql = f"SELECT id, timestamp, data FROM {table_name} ORDER BY timestamp DESC LIMIT 1"

        try:
            with self._connection.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()

                if row:
                    return {
                        "id": row[0],
                        "timestamp": row[1],
                        "data": row[2]  # Automatically a dict thanks to JSONB
                    }
        except Exception as e:
            logger.error(f"❌ Failed to fetch latest packet: {e}")
            if self._connection:
                self._connection.rollback()
        return None

    def get_unique_combination_stats(self, keys: List[str],
                                     filters: Dict[str, str] = None,
                                     table_name: str = 'redvypr_packets') -> List[
        Dict[str, Any]]:
        """
                                PostgreSQL Implementation of statistics retrieval.

                                .. SeeAlso:: :meth:`.AbstractDatabase.get_unique_combination_stats`
        """
        valid_columns = ["redvypr_address", "packetid", "device", "host", "publisher",
                         "uuid"]
        safe_keys = [k for k in keys if k in valid_columns]

        if not safe_keys:
            return []

        col_string = ", ".join(safe_keys)
        where_clauses = []
        params = []

        if filters:
            for key, value in filters.items():
                if key in valid_columns:
                    op = "LIKE" if isinstance(value, str) and "%" in value else "="
                    where_clauses.append(f"{key} {op} {self.placeholder}")
                    params.append(value)

        where_stmt = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Wir fügen MIN und MAX für den Zeitstempel hinzu
        sql = f"""
            SELECT {col_string}, 
                   COUNT(*) as packet_count, 
                   MIN(timestamp) as first_seen, 
                   MAX(timestamp) as last_seen
            FROM {table_name} 
            {where_stmt} 
            GROUP BY {col_string} 
            ORDER BY last_seen DESC
        """

        try:
            with self._connection.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

                results = []
                for r in rows:
                    # Die ersten N Elemente sind unsere Keys
                    d = dict(zip(safe_keys, r[:len(safe_keys)]))
                    # Die letzten 3 Elemente sind count, min, max
                    d["count"] = r[-3]
                    d["first_seen"] = r[-2].isoformat() if hasattr(r[-2],
                                                                   'isoformat') else r[
                        -2]
                    d["last_seen"] = r[-1].isoformat() if hasattr(r[-1],
                                                                  'isoformat') else r[
                        -1]
                    results.append(d)
                return results
        except Exception as e:
            logger.error(f"❌ Detailed stats failed: {e}")
            if self._connection: self._connection.rollback()
            return []

    def get_unique_combination_stats_legacy(self, keys: List[str],
                                     filters: Dict[str, str] = None,
                                     table_name: str = 'redvypr_packets') -> List[
        Dict[str, Any]]:

        """
                        PostgreSQL Implementation of statistics retrieval.

                        .. SeeAlso:: :meth:`.AbstractDatabase.get_unique_combination_stats`
        """

        # Security: Only allow valid columns to prevent SQL injection
        valid_columns = ["redvypr_address", "packetid", "device", "host", "publisher",
                         "uuid"]
        safe_keys = [k for k in keys if k in valid_columns]

        if not safe_keys:
            logger.error("No valid keys provided for grouping.")
            return []

        col_string = ", ".join(safe_keys)
        where_clauses = []
        params = []

        if filters:
            for key, value in filters.items():
                if key in valid_columns:
                    op = "LIKE" if isinstance(value, str) and "%" in value else "="
                    where_clauses.append(f"{key} {op} {self.placeholder}")
                    params.append(value)

        where_stmt = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        sql = f"""
            SELECT {col_string}, COUNT(*) as packet_count 
            FROM {table_name} 
            {where_stmt} 
            GROUP BY {col_string} 
            ORDER BY packet_count DESC
        """

        try:
            with self._connection.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [{**dict(zip(safe_keys, r[:-1])), "count": r[-1]} for r in rows]
        except Exception as e:
            logger.error(f"❌ Custom stats failed: {e}")
            if self._connection: self._connection.rollback()
            return []


class RedvyprTimescaleDb_legacy:
        """
        Class for managing the connection and interaction with a TimescaleDB instance.
        """

        def __init__(self, dbname: str, user: str, password: str,
                     host: str = 'localhost', port: str = '5432'):
            """Initializes the connection parameters."""
            self.conn_params = {
                'dbname': dbname,
                'user': user,
                'password': password,
                'host': host,
                'port': port
            }
            self.conn_str = f"dbname={dbname} user={user} password={password} host={host} port={port}"
            print("Conn parameter",self.conn_params)
            #self.add_custom_column(table_name='redvypr_packets',column_name='redvypr_address')
            #self.add_custom_column(table_name='redvypr_packets',column_name='packetid')
            #self.add_custom_column(table_name='redvypr_packets',column_name='publisher')
            #self.add_custom_column(table_name='redvypr_packets',column_name='host')
            #self.add_custom_column(table_name='redvypr_packets',column_name='device')
            #self.add_custom_column(table_name='redvypr_packets', column_name='uuid')
            #self.add_custom_column(table_name='redvypr_packets',column_name='numpacket')
            #self.add_custom_column(table_name='redvypr_packets', column_name='timestamp_packet', column_type='TIMESTAMPTZ')
            self.create_metadata_table()

        @contextmanager
        def _get_connection(self) -> Iterator[psycopg.Connection]:
            """Establishes a secure connection to the database and ensures it is automatically closed."""
            conn = None
            try:
                # Connect to the PostgreSQL/TimescaleDB database
                conn = psycopg.connect(**self.conn_params)
                yield conn
            except psycopg.Error as e:
                print(f"❌ Database Connection Error: {e}")
                raise  # Re-raise exception for proper error handling
            finally:
                if conn:
                    conn.close()

        def create_hypertable(self, table_name: str = 'redvypr_packets',
                              time_column: str = 'timestamp'):
            """
            Creates the standard table and converts it into a TimescaleDB Hypertable.
            """

            # SQL statements for creation (CREATE) and conversion (create_hypertable)
            sql_statements = [
                # 1. Enable the TimescaleDB extension
                "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;",

                # 2. Create the standard table using TIMESTAMPTZ and JSONB
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id SERIAL,
                    {time_column} TIMESTAMPTZ NOT NULL,
                    redvypr_address TEXT NOT NULL,
                    packetid TEXT NOT NULL,
                    publisher TEXT NOT NULL,
                    device TEXT NOT NULL,
                    host TEXT NOT NULL,
                    numpacket TEXT NOT NULL,
                    uuid TEXT NOT NULL,
                    timestamp_packet TIMESTAMPTZ NOT NULL,
                    data JSONB NOT NULL,
                    -- Primary Key must include the time column for partitioning
                    PRIMARY KEY (id, {time_column})
                );
                """,

                # 3. Convert to Hypertable, chunking by time_column (e.g., daily)
                f"""
                SELECT create_hypertable(
                    '{table_name}', 
                    by_range('{time_column}', INTERVAL '1 day'), 
                    if_not_exists => TRUE
                );
                """
            ]

            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        print(f"Starting creation of Hypertable '{table_name}'...")
                        for statement in sql_statements:
                            cur.execute(statement)
                        conn.commit()
                        print(
                            f"✅ Hypertable '{table_name}' successfully created and configured.")
            except Exception as e:
                raise ConnectionError("Could not connect to the TimescaleDB instance.")
                #print(f"❌ Error during Hypertable creation: {e}")

        def create_metadata_table(self):
            """Creates a metadata-table."""
            sql = """
            CREATE TABLE IF NOT EXISTS redvypr_metadata (
                redvypr_address TEXT NOT NULL,
                uuid TEXT NOT NULL,
                metadata JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (redvypr_address, uuid)
            );
            """
            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql)
                    conn.commit()
            except Exception as e:
                print(f"❌ Error: {e}")

        def add_custom_column(self, table_name: str, column_name: str,
                              column_type: str = 'TEXT'):
            """
            Safely adds a missing column with a specific data type (e.g., TIMESTAMPTZ or TEXT)
            to the existing table using a DO block for idempotency.
            """
            alter_sql = f"""
                DO $$
                BEGIN
                    -- Check if the column already exists
                    IF NOT EXISTS (
                        SELECT 1 
                        FROM information_schema.columns 
                        WHERE table_name = '{table_name}' AND column_name = '{column_name}'
                    ) THEN
                        -- Dynamically inject the column name and type
                        EXECUTE 'ALTER TABLE {table_name} ADD COLUMN {column_name} ' || '{column_type}';
                        RAISE NOTICE 'Column % (%) was successfully added to table %.', '{column_name}', '{column_type}', '{table_name}';
                    ELSE
                        RAISE NOTICE 'Column % already exists in table %.', '{column_name}', '{table_name}';
                    END IF;
                END
                $$;
            """
            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        print(
                            f"Checking for column '{column_name}' ({column_type}) in '{table_name}'...")
                        cur.execute(alter_sql)
                        conn.commit()
                        print(f"✅ Schema check for '{column_name}' complete.")
            except Exception as e:
                print(f"❌ Error adding column '{column_name}': {e}")


        def get_database_info(self, table_name: str = 'redvypr_packets') -> \
        Optional[Dict[str, Any]]:
            """
            Retrieves the total number of measurements (rows) and the time range stored
            in the specified table.

            Returns a dictionary with 'measurement_count', 'min_time', and 'max_time'
            (ISO formatted strings) or None in case of an error or empty table.
            """

            info_sql = f"""
                SELECT
                    COUNT(timestamp) AS measurement_count,
                    MIN(timestamp) AS min_time,
                    MAX(timestamp) AS max_time
                FROM
                    {table_name};
            """

            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(info_sql)

                        # fetchone() returns a single row as a tuple (count, min_time, max_time)
                        result = cur.fetchone()

                        # Check if the result is valid and the count (result[0]) is not None
                        if result and result[0] is not None:
                            # Convert datetime objects to ISO strings for cleaner output
                            info = {
                                "measurement_count": result[0],
                                "min_time": result[1].isoformat() if result[
                                    1] else None,
                                "max_time": result[2].isoformat() if result[
                                    2] else None
                            }
                            return info

                        return None

            except Exception as e:
                print(f"❌ Error fetching database information: {e}")
                return None
        # -------------------------------------

        def check_db_capabilities(self) -> Dict[str, Any]:
            """
            Checks if the connected database is a TimescaleDB and if the user
            has permissions to create tables.
            """
            status = {
                "is_timescale": False,
                "can_create_tables": False,
                "extension_version": None,
                "error": None
            }

            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        # 1. Check for TimescaleDB extension
                        cur.execute("""
                            SELECT extname, extversion 
                            FROM pg_extension 
                            WHERE extname = 'timescaledb';
                        """)
                        ts_ext = cur.fetchone()
                        if ts_ext:
                            status["is_timescale"] = True
                            status["extension_version"] = ts_ext[1]

                        # 2. Check for CREATE permissions on the current schema (usually 'public')
                        cur.execute("""
                            SELECT has_schema_privilege(current_user, current_schema(), 'CREATE');
                        """)
                        status["can_create_tables"] = cur.fetchone()[0]

                return status
            except Exception as e:
                status["error"] = str(e)
                return status

        def insert_packet_data(self, data_dict: Dict[str, Any],
                               table_name: str = 'redvypr_packets'):
            """
            Inserts a single record into the Hypertable.

            Args:
                data_dict: A Python dictionary to be stored as JSONB.
            """
            #insert_sql = f"""
            #    INSERT INTO {table_name} (timestamp, data, raddstr)
            #    VALUES (%s, %s, %s);
            #"""
            insert_sql = f"""
               INSERT INTO {table_name} (timestamp, data, redvypr_address, host, publisher, device, packetid, numpacket, timestamp_packet, uuid)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """

            # Convert the Python dictionary to a JSON string for the JSONB column
            json_data = json_safe_dumps(data_dict)
            try:
                timestamp_value = data_dict['t']
                timestamp_packet_value = data_dict['_redvypr']['t']
                numpacket = data_dict['_redvypr']['numpacket']
                raddr = RedvyprAddress(data_dict)
                raddrstr = raddr.to_address_string()
                host = raddr.hostname
                uuid = raddr.uuid
                device = raddr.device
                packetid = raddr.packetid
                publisher = raddr.publisher
            except Exception as e:
                print(f"❌ Data is not compatible for inserting: {e}")
                return
            if isinstance(timestamp_value, (int, float)):
                timestamp_utc = datetime.fromtimestamp(timestamp_value, tz=timezone.utc)
            if isinstance(timestamp_packet_value, (int, float)):
                timestamp_packet_utc = datetime.fromtimestamp(timestamp_packet_value, tz=timezone.utc)
            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        data_insert = (timestamp_utc, json_data, raddrstr, host, publisher, device, packetid, numpacket, timestamp_packet_utc, uuid)
                        #print("data insert",data_insert)
                        #print("insert sql",insert_sql)
                        # Execute the INSERT command, passing parameters safely
                        cur.execute(insert_sql, data_insert)
                        conn.commit()
            except Exception as e:
                print(f"❌ Error inserting data: {e}")

        def add_metadata(self, address: str, uuid: str, metadata_dict: dict,
                         mode: str = "merge"):
            """
            Stores metadata for a specific address and UUID.

            Args:
                address (str): The Redvypr address.
                uuid (str): The unique identifier for the configuration session.
                metadata_dict (dict): Dictionary containing the metadata.
                mode (str): 'merge' to combine with existing JSON, 'explicit' to overwrite.
            """
            if mode == "merge":
                # Uses the PostgreSQL || operator to merge existing JSONB data with new data
                sql = """
                INSERT INTO redvypr_metadata (redvypr_address, uuid, metadata, created_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (redvypr_address, uuid) 
                DO UPDATE SET 
                    metadata = redvypr_metadata.metadata || EXCLUDED.metadata;
                """
            else:  # explicit mode
                # Overwrites the existing JSONB data completely
                sql = """
                INSERT INTO redvypr_metadata (redvypr_address, uuid, metadata, created_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (redvypr_address, uuid) 
                DO UPDATE SET 
                    metadata = EXCLUDED.metadata;
                """

            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Convert the dict to a safe JSON string
                        json_data = json_safe_dumps(metadata_dict)
                        cur.execute(sql, (address, uuid, json_data))
                    conn.commit()
                    # print(f"✅ Metadata for {address} (UUID: {uuid}) stored successfully.")
            except Exception as e:
                print(f"❌ Error adding metadata for {address}: {e}")

        def get_metadata(self, address: str, uuid: str = None):
            """
            Retrieves metadata for a specific address and optionally a specific UUID.

            Args:
                address (str): The Redvypr address.
                uuid (str, optional): The unique identifier. If None, the most recent entry
                                      for the address is returned based on created_at.

            Returns:
                dict: The metadata dictionary, or None if no entry was found.
            """
            # Determine the correct placeholder for the SQL query
            placeholder = "?" if self.db_type == "sqlite" else "%s"

            if uuid:
                # Fetch a specific configuration session
                sql = f"""
                SELECT metadata FROM redvypr_metadata 
                WHERE redvypr_address = {placeholder} AND uuid = {placeholder}
                """
                params = (address, uuid)
            else:
                # Fallback: Fetch the latest known metadata for this address
                sql = f"""
                SELECT metadata FROM redvypr_metadata 
                WHERE redvypr_address = {placeholder} 
                ORDER BY created_at DESC LIMIT 1
                """
                params = (address,)

            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                        row = cur.fetchone()

                        if row:
                            raw_data = row[0]
                            # If the DB returns a string (SQLite), parse it into a dict
                            if isinstance(raw_data, str):
                                import json
                                return json.loads(raw_data)
                            # PostgreSQL/psycopg2 usually returns a dict directly for JSONB
                            return raw_data

                        return None
            except Exception as e:
                print(f"❌ Error retrieving metadata for {address}: {e}")
                return None

        def get_packets_range(self, start_index: int, count: int):
            """
            Returns a list of packets starting from start_index.

            Example:
                get_packets_range(0, 10) -> returns the first 10 packets.
                get_packets_range(20, 5) -> returns packets 21 to 25.

            Args:
                start_index (int): The 0-based offset (e.g., 0 for the very first packet).
                count (int): How many packets to retrieve.

            Returns:
                list[dict]: A list of dictionaries, each structured as follows:
                {
                     "id": int,              # The primary key/sequence ID
                     "timestamp": datetime,   # TIMESTAMPTZ object from DB
                     "data": dict            # The JSONB payload as a Python dictionary
                }
                Returns an empty list if no packets are found or an error occurs.
            """
            sql = """
                SELECT id, timestamp, data
                FROM redvypr_packets
                ORDER BY id ASC
                LIMIT %s OFFSET %s
            """

            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, (count, start_index))
                        rows = cur.fetchall()

                        packets = []
                        for row in rows:
                            packets.append({
                                "id": row[0],
                                "timestamp": row[1],
                                "data": row[2]  # JSONB is already a dict
                            })
                        return packets
            except Exception as e:
                print(f"❌ Error retrieving packet range: {e}")
                return []



def json_safe_dumps(obj):
    """Convert complex Redvypr packets into JSON-safe text."""
    def default(o):
        # numpy arrays → convert to Python lists
        if isinstance(o, np.ndarray):
            return o.tolist()
        # numpy scalar values (e.g. np.int64, np.float64)
        if isinstance(o, (np.generic,)):
            return o.item()
        # Handle Python 'type' objects (e.g., <class 'float'>)
        if isinstance(o, type):
            return str(o)
        # Handle datetime
        if isinstance(o, datetime):
            return o.isoformat()
        # Handle other unknown types
        return str(o)
    return json.dumps(obj, default=default, ensure_ascii=False)
