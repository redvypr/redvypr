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
                                     table_name: str = 'redvypr_packets',
                                     time_col: str = 'timestamp') -> List[
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

    @abstractmethod
    def get_metadata(self, start_index: int = 0, count: int = 100) -> List[
        Dict[str, Any]]:
        """
        Retrieves metadata records. Every DB must implement this.
        """
        pass

    def get_metadata_info(self, keys: List[str] = None) -> List[Dict[str, Any]]:
        """
        Returns an overview of stored metadata.
        Uses 'created_at' as the time dimension.
        """
        if keys is None:
            keys = ["redvypr_address", "uuid", "packetid", "device", "host"]

        return self.get_unique_combination_stats(
            keys=keys,
            table_name='redvypr_metadata',
            time_col='created_at'
        )



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
                packetid TEXT,
                device TEXT,
                host TEXT,
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
        """
        Upsert metadata with explicit columns and merge/overwrite logic for JSON content.
        """
        # 1. Extrahiere die Identitäts-Informationen aus der Adresse
        # Wir nutzen hier dein RedvyprAddress-Tool, um konsistent zu bleiben

        # Wir erstellen ein temporäres Objekt um die Felder sauber zu extrahieren
        # Falls du die Felder direkt als Argumente hättest, wäre es einfacher,
        # aber so bleibt die API sauber.
        try:
            raddr = RedvyprAddress.from_address_string(address, uuid=uuid)
            packetid = raddr.packetid
            device = raddr.device
            host = raddr.hostname
        except Exception:
            # Fallback falls die Adresse nicht geparst werden kann
            packetid, device, host = None, None, None

        # 2. Definiere das Verhalten bei Konflikten
        if mode == "merge":
            # JSON wird gemerged (|| Operator), Identitätsfelder werden aktualisiert
            update_logic = """
                metadata = redvypr_metadata.metadata || EXCLUDED.metadata,
                packetid = EXCLUDED.packetid,
                device = EXCLUDED.device,
                host = EXCLUDED.host
            """
        else:
            # Alles wird überschrieben
            update_logic = """
                metadata = EXCLUDED.metadata,
                packetid = EXCLUDED.packetid,
                device = EXCLUDED.device,
                host = EXCLUDED.host
            """

        sql = f"""
            INSERT INTO redvypr_metadata (
                redvypr_address, uuid, packetid, device, host, metadata
            )
            VALUES (
                {self.placeholder}, {self.placeholder}, {self.placeholder}, 
                {self.placeholder}, {self.placeholder}, {self.placeholder}
            )
            ON CONFLICT (redvypr_address, uuid) DO UPDATE SET {update_logic};
        """

        try:
            with self._connection.cursor() as cur:
                cur.execute(sql, (
                    address, uuid, packetid, device, host, json.dumps(metadata_dict)
                ))
            self._connection.commit()
            logger.info(f"✅ Metadata for {address} stored.")
        except Exception as e:
            logger.error(f"❌ Metadata storage failed: {e}")
            if self._connection:
                self._connection.rollback()

    def add_metadata_legacy(self, address: str, uuid: str, metadata_dict: dict,
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
                                     table_name: str = 'redvypr_packets',
                                     time_col: str = 'timestamp') -> List[
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

        # The sql query
        sql = f"""
                    SELECT {col_string}, 
                           COUNT(*) as packet_count, 
                           MIN({time_col}) as first_seen, 
                           MAX({time_col}) as last_seen
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

    def get_metadata(self, start_index: int = 0, count: int = 100) -> List[
        Dict[str, Any]]:
        """
        Retrieves metadata records with pagination.

        Args:
            start_index (int): Offset (where to start).
            count (int): Limit (how many entries to fetch).
        """
        sql = f"""
            SELECT redvypr_address, uuid, metadata, created_at 
            FROM redvypr_metadata 
            ORDER BY created_at DESC 
            LIMIT {self.placeholder} OFFSET {self.placeholder}
        """
        try:
            with self._connection.cursor() as cur:
                cur.execute(sql, (count, start_index))
                rows = cur.fetchall()
                return [
                    {
                        "redvypr_address": r[0],
                        "uuid": r[1],
                        "metadata": r[2],  # JSONB is automatically a dict
                        "created_at": r[3].isoformat() if hasattr(r[3],
                                                                  'isoformat') else r[3]
                    } for r in rows
                ]
        except Exception as e:
            logger.error(f"❌ Metadata retrieval failed: {e}")
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
