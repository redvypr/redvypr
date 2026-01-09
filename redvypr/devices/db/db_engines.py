import json
import os
import sqlite3
import logging
import sys
import pydantic
import typing
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Iterator
import psycopg
from abc import ABC, abstractmethod
from typing import Iterator, Optional, Any, Dict
from redvypr.redvypr_address import RedvyprAddress

import numpy as np

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.timescaledb')
logger.setLevel(logging.DEBUG)



# --- Setup Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RedvyprDB")

def json_safe_dumps(obj):
    """
    Convert complex Redvypr packets into JSON-safe text.
    Adds a '__dt__:' prefix to datetime objects to ensure safe restoration.
    """

    def default(o):
        # numpy arrays → convert to Python lists
        if isinstance(o, np.ndarray):
            return o.tolist()

        # numpy scalar values (e.g. np.int64, np.float64)
        if isinstance(o, (np.generic,)):
            return o.item()

        # Handle Python 'type' objects
        if isinstance(o, type):
            return str(o)

        # Handle datetime with specific prefix marker
        if isinstance(o, datetime):
            return f"__dt__:{o.isoformat()}"

        # Handle other unknown types
        return str(o)

    return json.dumps(obj, default=default, ensure_ascii=False)


def restore_datetimes(data):
    """
    Recursively traverses dictionaries and lists to find strings
    starting with '__dt__:' and converts them back to datetime objects.
    """
    if isinstance(data, dict):
        return {k: restore_datetimes(v) for k, v in data.items()}

    elif isinstance(data, list):
        return [restore_datetimes(item) for item in data]

    elif isinstance(data, str) and data.startswith("__dt__:"):
        try:
            # Strip prefix and convert to datetime
            iso_str = data.replace("__dt__:", "", 1)
            return datetime.fromisoformat(iso_str)
        except (ValueError, TypeError):
            # If conversion fails, return the string as is
            return data

    return data


def json_safe_loads(json_str):
    """
    Parses a JSON string and automatically restores datetime objects
    hidden in dictionaries or lists.
    """
    raw_data = json.loads(json_str)
    return restore_datetimes(raw_data)

def json_safe_dumps_legacy(obj):
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



class TimescaleConfig(pydantic.BaseModel):
    dbtype: typing.Literal["timescaledb"] = "timescaledb"
    dbname: str = "postgres"
    user: str = "postgres"
    password: str = "password"
    host: str = "pi5server1"
    port: int = 5433

class SqliteConfig(pydantic.BaseModel):
    dbtype: typing.Literal["sqlite"] = "sqlite"
    filepath: str = "data.db"

# Das 'Union' erlaubt entweder das eine oder das andere Modell
DatabaseConfig = typing.Union[TimescaleConfig, SqliteConfig]
class DatabaseSettings(pydantic.RootModel):
    root: typing.Annotated[
        DatabaseConfig,
        pydantic.Field(discriminator="dbtype")
    ]


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
    def get_packets_range(self, start_index: int, count: int,
                          filters: List[Dict[str, str]] = None,
                          time_range: Dict[str, Any] = None) -> List[Dict]:
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

        # 1. Versuch: SQLite Probe
        cur = self._connection.cursor()  # Kein 'with' hier!
        try:
            cur.execute("SELECT sqlite_version();")
            # Wenn wir hier ankommen, ist es SQLite
            self.engine_type = "sqlite"
            self.placeholder = "?"
            logger.info("✅ Database identified as SQLite")
            return  # Erfolg!
        except Exception:
            try:
                self._connection.rollback()
            except:
                pass
        finally:
            cur.close()  # Cursor sicher schließen

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
        except Exception as e:
            print(f"Exception test timescaledb:{e}")
            self._connection.rollback()

        self.engine_type = "unknown"

    def get_database_info_legacy(self, table_name: str = 'redvypr_packets') -> Optional[
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

    def get_database_info(self, table_name: str = 'redvypr_packets') -> Optional[
        Dict[str, Any]]:
        """Retrieves row count and time range from a table safely."""
        if not self._connection:
            return None

        sql = f"SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM {table_name}"

        # Cursor manuell erstellen (kein 'with'!)
        cur = self._connection.cursor()
        try:
            cur.execute(sql)
            result = cur.fetchone()

            if result and result[0] > 0:
                def format_ts(val):
                    if val is None:
                        return None
                    # Prüfen, ob es bereits ein datetime-Objekt ist (Postgres)
                    if hasattr(val, 'isoformat'):
                        return val.isoformat()
                    # Ansonsten als String behandeln (SQLite)
                    return str(val)

                return {
                    "measurement_count": result[0],
                    "min_time": format_ts(result[1]),
                    "max_time": format_ts(result[2])
                }

        except Exception as e:
            logger.error(f"Failed to get info for {table_name}: {e}")
            try:
                self._connection.rollback()
            except:
                pass
        finally:
            cur.close()  # Cursor sicher schließen für SQLite Kompatibilität

        return None

    def check_health(self) -> Dict[str, Any]:

        # 1. Sicherstellen, dass wir eine Verbindung haben
        if not self._connection:
            self.connect()

        # 2. Falls Engine noch unbekannt, Identifizierung erzwingen
        if self.engine_type == "unknown":
            logger.info("Engine type unknown during health check, probing now...")
            print("Checking identity")
            self.identify_and_setup()

        health = {
            "engine": self.engine_type,
            "is_timescale": self.is_timescale,
            "tables_exist": False,
            "can_write": False
        }

        if not self._connection:
            return health

        print("Enginge type",self.engine_type)
        # Cursor manuell öffnen für maximale Kompatibilität
        cur = self._connection.cursor()
        try:
            # 1. Tabellen-Existenz prüfen
            if self.engine_type == "sqlite":
                # SQLite Syntax
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='redvypr_packets';"
                )
                health["tables_exist"] = cur.fetchone() is not None
            else:
                # PostgreSQL Syntax (Wichtig: Spalte * oder 1 nach SELECT)
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'redvypr_packets');"
                )
                res = cur.fetchone()
                health["tables_exist"] = bool(res[0]) if res else False

            # 2. Schreibrechte prüfen
            try:
                # 'TEMPORARY' ist in beiden Welten gültig
                cur.execute("CREATE TEMPORARY TABLE _health_test (id INTEGER);")
                cur.execute("DROP TABLE _health_test;")
                health["can_write"] = True
                self._connection.commit()
            except Exception:
                health["can_write"] = False
                self._connection.rollback()

        except Exception as e:
            # Hier kam dein "near FROM" Fehler her
            logger.error(f"❌ Health check failed: {e}")
        finally:
            cur.close()

        return health

    def check_health_legacy2(self) -> Dict[str, Any]:
        """
        Prüft den Datenbank-Typ, die Existenz der Tabellen und Schreibrechte.
        Diese Version ist robust gegenüber verschiedenen Python-Versionen und DB-Engines.
        """
        health = {
            "engine": self.engine_type,
            "is_timescale": self.is_timescale,
            "tables_exist": False,
            "can_write": False
        }

        if not self._connection:
            return health

        # Sicherstellen, dass keine alte Transaktion den Check blockiert
        try:
            self._connection.rollback()
        except Exception:
            pass

        cur = self._connection.cursor()
        try:
            # 1. Existenz der Haupttabelle prüfen
            if self.engine_type == "sqlite":
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='redvypr_packets';"
                )
                res = cur.fetchone()
                health["tables_exist"] = bool(res)
            else:  # PostgreSQL / TimescaleDB
                cur.execute(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'redvypr_packets');"
                )
                res = cur.fetchone()
                health["tables_exist"] = bool(res[0]) if res else False

            # 2. Schreibrechte prüfen (Temporäre Tabelle erstellen)
            try:
                # In SQLite heißt es TEMP oder TEMPORARY, beides funktioniert.
                cur.execute("CREATE TEMPORARY TABLE _health_write_test (id int);")
                cur.execute("DROP TABLE _health_write_test;")
                health["can_write"] = True
                self._connection.commit()  # Test-Aktion abschließen
            except Exception:
                health["can_write"] = False
                try:
                    self._connection.rollback()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
        finally:
            # Wichtig: Cursor immer explizit schließen für SQLite-Kompatibilität < 3.12
            cur.close()

        return health

    def check_health_legacy(self) -> Dict[str, Any]:
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

    @abstractmethod
    def get_metadata_by_ids(self, record_ids: List[int]) -> List[Dict[str, Any]]:
        """
        Retrieve multiple metadata records using a list of unique integer IDs.

        This method uses the SQL 'IN' clause to fetch all requested records in a
        single database round-trip. It is optimized for scenarios where a group
        of specific packets needs to be inspected in detail.

        :param record_ids: A list of unique technical identifiers (Primary Keys).
        :type record_ids: list[int]

        :return: A list of dictionaries, each containing the full record data.
                 Returns an empty list if no IDs match or the input list is empty.
                 The dictionaries include:

                 - **id**: The integer record ID.
                 - **redvypr_address**: The associated address.
                 - **uuid**: The record UUID.
                 - **metadata**: The parsed JSON content of the metadata.
                 - **created_at**: The ISO-formatted timestamp.

        :rtype: list[dict[str, Any]]

        .. seealso:: :meth:`get_unique_combination_stats` for obtaining the ID lists.
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

    @abstractmethod
    def get_packet_count(self,
                         filters: Optional[List[Dict[str, str]]] = None,
                         time_range: Optional[Dict[str, Any]] = None,
                         table_name: str = 'redvypr_packets') -> int:
        """
        Calculates the total number of records matching specific criteria.

        This method is essential for initializing progress bars, determining loop
        boundaries for paginated data retrieval, and performing high-level
        database audits without fetching actual data payloads.

        :param filters: A list of dictionaries representing filter groups.
            Each dictionary in the list is treated as an **AND** group, while the
            list itself combines these groups via **OR**.
            Example: ``[{"host": "A"}, {"device": "B"}]`` translates to
            *(host == 'A' OR device == 'B')*.
        :type filters: List[Dict[str, str]], optional

        :param time_range: A dictionary defining the temporal boundaries.
            Expected keys are ``tstart`` and ``tend``, containing
            ``datetime.datetime`` objects.
        :type time_range: Dict[str, Any], optional

        :param table_name: The name of the database table to query.
            Defaults to 'redvypr_packets'.
        :type table_name: str

        :return: The total count of matching records.
        :rtype: int

        .. rubric:: Example

        .. code-block:: python

            # Count all 'telemetry' packets from a specific host in a time window
            filters = [{"host": "gate_01", "packetid": "telemetry"}]
            time_range = {
                "tstart": datetime(2025, 1, 1, tzinfo=timezone.utc),
                "tend": datetime(2025, 1, 2, tzinfo=timezone.utc)
            }

            total = db.get_packet_count(filters=filters, time_range=time_range)
            print(f"Found {total} matching packets.")

        .. note::
            For SQL-based implementations, this method should utilize optimized
            ``COUNT(*)`` queries and leverage database indexes on the
            filtered columns to ensure high performance even with large datasets.
        """
        pass



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
                id SERIAL PRIMARY KEY,
                redvypr_address TEXT NOT NULL,
                uuid TEXT NOT NULL,
                packetid TEXT,
                device TEXT,
                host TEXT,
                metadata JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (redvypr_address, uuid)
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
            host = raddr.host
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
            #print("data dict",data_dict)
            #json.dumps(data_dict)

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
            host = raddr.host
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
                    address, uuid, packetid, device, host, json_safe_dumps(metadata_dict)
                ))
            self._connection.commit()
            logger.info(f"✅ Metadata for {address} stored.")
        except Exception as e:
            logger.error(f"❌ Metadata storage failed: {e}")
            if self._connection:
                self._connection.rollback()

    def get_packets_range(self, start_index: int, count: int,
                          filters: List[Dict[str, str]] = None,
                          time_range: Dict[str, Any] = None) -> List[Dict]:

        where_clauses = []
        params = []

        # 1. Zeitfenster (tstart, tend)
        if time_range:
            if "tstart" in time_range:
                where_clauses.append(f"timestamp >= {self.placeholder}")
                params.append(time_range["tstart"])
            if "tend" in time_range:
                where_clauses.append(f"timestamp <= {self.placeholder}")
                params.append(time_range["tend"])

        # 2. Kombinations-Filter (Liste von Dicts)
        if filters:
            sub_clauses = []
            for group in filters:
                # Erstellt für jedes Dict eine AND-Kette: (host='A' AND device='B')
                group_conditions = []
                for key, value in group.items():
                    group_conditions.append(f"{key} = {self.placeholder}")
                    params.append(value)
                sub_clauses.append(f"({' AND '.join(group_conditions)})")

            # Verbindet die Gruppen mit OR
            where_clauses.append(f"({' OR '.join(sub_clauses)})")

        where_stmt = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Das eigentliche SQL
        sql = f"""
            SELECT id, timestamp, data 
            FROM redvypr_packets 
            {where_stmt} 
            ORDER BY timestamp ASC 
            LIMIT {self.placeholder} OFFSET {self.placeholder}
        """

        params.extend([count, start_index])

        try:
            with self._connection.cursor() as cur:
                cur.execute(sql, params)
                return [{"id": r[0], "timestamp": r[1], "data": restore_datetimes(r[2])} for r in
                        cur.fetchall()]
        except Exception as e:
            logger.error(f"❌ Filtered range retrieval failed: {e}")
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
                        "data": restore_datetimes(row[2])  # Automatically a dict thanks to JSONB
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
        PostgreSQL Implementation of statistics retrieval including ID list.
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
        #print("time col",time_col)
        # Added array_agg(id) to collect all IDs for the group
        sql = f"""
                SELECT {col_string}, 
                       COUNT(*) as packet_count, 
                       MIN({time_col}) as first_seen, 
                       MAX({time_col}) as last_seen,
                       array_agg(id ORDER BY {time_col} ASC) as ids
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
                    # The first N elements are our safe_keys
                    d = dict(zip(safe_keys, r[:len(safe_keys)]))

                    # Column mapping from the end of the result row:
                    # r[-4] = count
                    # r[-3] = first_seen
                    # r[-2] = last_seen
                    # r[-1] = ids (list)

                    d["count"] = r[-4]
                    d["first_seen"] = r[-3].isoformat() if hasattr(r[-3],
                                                                   'isoformat') else r[
                        -3]
                    d["last_seen"] = r[-2].isoformat() if hasattr(r[-2],
                                                                  'isoformat') else r[
                        -2]
                    d["ids"] = r[
                        -1]  # psycopg2 automatically converts this to a Python list

                    results.append(d)
                return results
        except Exception as e:
            logger.error(f"❌ Detailed stats failed: {e}")
            if self._connection:
                self._connection.rollback()
            return []

    def get_unique_combination_stats_legacy(self, keys: List[str],
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

    def get_metadata_by_ids(self, record_ids: List[int]) -> List[Dict[str, Any]]:
        if not record_ids:
            return []

        # Create placeholders for the IN clause: e.g., (%s, %s, %s)
        placeholders = ", ".join([self.placeholder] * len(record_ids))

        sql = f"""
            SELECT id, redvypr_address, uuid, metadata, created_at, packetid, device, host
            FROM redvypr_metadata 
            WHERE id IN ({placeholders})
            ORDER BY created_at DESC
        """
        try:
            with self._connection.cursor() as cur:
                cur.execute(sql, tuple(record_ids))
                rows = cur.fetchall()

                return [
                    {
                        "id": r[0],
                        "redvypr_address": r[1],
                        "uuid": r[2],
                        "metadata": r[3],
                        "created_at": r[4].isoformat() if hasattr(r[4],
                                                                  'isoformat') else r[
                            4],
                        "packetid": r[5],
                        "device": r[6],
                        "host": r[7]
                    } for r in rows
                ]
        except Exception as e:
            logger.error(f"❌ Bulk metadata retrieval failed: {e}")
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



    def get_packet_count(self, filters: List[Dict[str, str]] = None,
                         time_range: Dict[str, Any] = None,
                         table_name: str = 'redvypr_packets') -> int:
        """
        Returns the number of packets matching specific filters and time ranges.
        """
        where_clauses = []
        params = []

        # 1. Time Range
        if time_range:
            if "tstart" in time_range:
                where_clauses.append(f"timestamp >= {self.placeholder}")
                params.append(time_range["tstart"])
            if "tend" in time_range:
                where_clauses.append(f"timestamp <= {self.placeholder}")
                params.append(time_range["tend"])

        # 2. Key Combination Filters
        if filters:
            sub_clauses = []
            for group in filters:
                group_conditions = [f"{k} = {self.placeholder}" for k in group.keys()]
                params.extend(group.values())
                sub_clauses.append(f"({' AND '.join(group_conditions)})")
            where_clauses.append(f"({' OR '.join(sub_clauses)})")

        where_stmt = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        sql = f"SELECT COUNT(*) FROM {table_name} {where_stmt}"

        try:
            with self._connection.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()[0]
        except Exception as e:
            logger.error(f"❌ Failed to get packet count: {e}")
            return 0







class RedvyprDBFactory:
    """
    Factory to create database instances directly from a DatabaseConfig.
    """

    @staticmethod
    def create(db_config: DatabaseConfig) -> AbstractDatabase:
        """
        Returns a concrete AbstractDatabase implementation.
        """
        # Handling TimescaleDB
        if isinstance(db_config, TimescaleConfig):
            return RedvyprTimescaleDb(
                dbname=db_config.dbname,
                user=db_config.user,
                password=db_config.password,
                host=db_config.host,
                port=db_config.port
            )

        # Handling SQLite
        elif isinstance(db_config, SqliteConfig):
            return RedvyprSqliteDb(
                filepath=db_config.filepath
            )

        # Fallback for dict-based configs (e.g. if loaded from JSON without Pydantic parsing)
        elif isinstance(db_config, dict):
            dbtype = db_config.get("dbtype")
            if dbtype == "timescaledb":
                return RedvyprTimescaleDb(
                    **{k: v for k, v in db_config.items() if k != "dbtype"})
            elif dbtype == "sqlite":
                return RedvyprSqliteDb(filepath=db_config.get("filepath"))

        raise ValueError(f"Unsupported database configuration type: {type(db_config)}")


class RedvyprSqliteDb(AbstractDatabase):
    """
    Vollständige SQLite Implementierung, die alle abstrakten Methoden
    der AbstractDatabase erfüllt.
    """

    def __init__(self, filepath: str = "data.db"):
        super().__init__()
        self.filepath = filepath
        self.placeholder = "?"
        self.engine_type = "sqlite"

    def connect(self):
        if not self._connection:
            try:
                self._connection = sqlite3.connect(
                    self.filepath,
                    detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                    check_same_thread=False
                )
                self._connection.row_factory = sqlite3.Row
                logger.info(f"✅ Connected to SQLite: {self.filepath}")
            except Exception as e:
                logger.error(f"❌ SQLite connection failed: {e}")
                raise
        return self._connection

    # --- Erforderliche Implementierungen der abstrakten Methoden ---

    def setup_schema(self, table_name: str = 'redvypr_packets'):
        cur = self._connection.cursor()
        try:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    redvypr_address TEXT NOT NULL,
                    packetid TEXT NOT NULL,
                    publisher TEXT NOT NULL,
                    device TEXT NOT NULL,
                    host TEXT NOT NULL,
                    numpacket TEXT NOT NULL,
                    uuid TEXT NOT NULL,
                    timestamp_packet DATETIME NOT NULL,
                    data TEXT NOT NULL
                );
            """)
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_ts_{table_name} ON {table_name} (timestamp);")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS redvypr_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, -- Eindeutiger Integer-Index
                    redvypr_address TEXT NOT NULL,
                    uuid TEXT NOT NULL,
                    packetid TEXT,
                    device TEXT,
                    host TEXT,
                    metadata TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    -- Stellt sicher, dass die Kombi aus Adresse und UUID trotzdem einzigartig bleibt:
                    UNIQUE (redvypr_address, uuid) 
                );
            """)
            self._connection.commit()
        finally:
            cur.close()

    def insert_packet(self, data_dict: Dict[str, Any],
                      table_name: str = 'redvypr_packets'):
        sql = f"INSERT INTO {table_name} (timestamp, data, redvypr_address, host, publisher, device, packetid, numpacket, timestamp_packet, uuid) VALUES (?,?,?,?,?,?,?,?,?,?)"
        cur = self._connection.cursor()
        try:
            raddr = RedvyprAddress(data_dict)
            ts_utc = datetime.fromtimestamp(data_dict['t'], tz=timezone.utc)
            ts_pkt_utc = datetime.fromtimestamp(data_dict['_redvypr']['t'],
                                                tz=timezone.utc)

            data_dict_json = json_safe_dumps(data_dict)
            cur.execute(sql, (
                ts_utc, data_dict_json, raddr.to_address_string(),
                raddr.host, raddr.publisher, raddr.device, raddr.packetid,
                data_dict['_redvypr']['numpacket'], ts_pkt_utc, raddr.uuid
            ))
            self._connection.commit()
        finally:
            cur.close()

    def add_metadata(self, address: str, uuid: str, metadata_dict: dict,
                     mode: str = "merge"):
        # SQLite Upsert
        cur = self._connection.cursor()
        try:
            # Einfaches Upsert (overwrite), Merge-Logik könnte hier bei Bedarf ergänzt werden
            sql = """
                INSERT INTO redvypr_metadata (redvypr_address, uuid, metadata)
                VALUES (?, ?, ?)
                ON CONFLICT(redvypr_address, uuid) DO UPDATE SET
                    metadata = excluded.metadata,
                    created_at = CURRENT_TIMESTAMP;
            """
            cur.execute(sql, (address, uuid, json_safe_dumps(metadata_dict)))
            self._connection.commit()
        finally:
            cur.close()

    def get_latest_packet(self, table_name: str = 'redvypr_packets') -> Optional[
        Dict[str, Any]]:
        cur = self._connection.cursor()
        try:
            cur.execute(
                f"SELECT id, timestamp, data FROM {table_name} ORDER BY timestamp DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                return {"id": row[0], "timestamp": row[1], "data": json_safe_loads(row[2])}
            return None
        finally:
            cur.close()

    def get_metadata(self, start_index: int = 0, count: int = 100) -> List[
        Dict[str, Any]]:
        cur = self._connection.cursor()
        try:
            cur.execute(
                "SELECT redvypr_address, uuid, metadata FROM redvypr_metadata LIMIT ? OFFSET ?",
                (count, start_index))
            return [{"address": r[0], "uuid": r[1], "metadata": json_safe_loads(r[2])} for r
                    in cur.fetchall()]
        finally:
            cur.close()

    def get_metadata_by_ids(self, record_ids: List[int]) -> List[Dict[str, Any]]:
        """
        SQLite implementation of bulk metadata retrieval.
        Fixed: Removed context manager from cursor.
        """
        if not record_ids:
            return []

        placeholders = ", ".join([self.placeholder] * len(record_ids))

        sql = f"""
            SELECT id, redvypr_address, uuid, metadata, created_at, packetid, device, host
            FROM redvypr_metadata 
            WHERE id IN ({placeholders})
            ORDER BY created_at DESC
        """

        cur = None
        try:
            # In SQLite, the connection is the context manager, not the cursor
            cur = self._connection.cursor()
            cur.execute(sql, tuple(record_ids))
            rows = cur.fetchall()

            results = []
            for r in rows:
                try:
                    # SQLite stores JSON as string
                    meta_dict = json.loads(r[3]) if isinstance(r[3], str) else r[3]
                except (json.JSONDecodeError, TypeError):
                    meta_dict = r[3]

                results.append({
                    "id": r[0],
                    "redvypr_address": r[1],
                    "uuid": r[2],
                    "metadata": meta_dict,
                    "created_at": r[4].isoformat() if hasattr(r[4], 'isoformat') else r[
                        4],
                    "packetid": r[5],
                    "device": r[6],
                    "host": r[7]
                })
            return results
        except Exception as e:
            logger.error(f"❌ SQLite bulk metadata retrieval failed: {e}")
            return []
        finally:
            if cur:
                cur.close()



    def get_packets_range(self, start_index: int, count: int, filters=None,
                          time_range=None) -> List[Dict]:
        where_clauses, params = [], []
        if time_range:
            if "tstart" in time_range:
                where_clauses.append("timestamp >= ?");
                params.append(time_range["tstart"])
            if "tend" in time_range:
                where_clauses.append("timestamp <= ?");
                params.append(time_range["tend"])

        where_stmt = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        sql = f"SELECT id, timestamp, data FROM redvypr_packets {where_stmt} ORDER BY timestamp ASC LIMIT ? OFFSET ?"
        params.extend([count, start_index])

        cur = self._connection.cursor()
        try:
            cur.execute(sql, params)
            data_return = []
            for r in cur.fetchall():
                ts_str = r[1]
                # Python 3.11+ Weg:
                try:
                    tdatetime = datetime.fromisoformat(ts_str)
                except ValueError:
                    # Fallback für ältere Versionen oder leicht abweichende Formate
                    # ersetzt Z durch +00:00 für Kompatibilität mit < 3.11
                    tdatetime = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))

                data_return.append({"id": r[0], "timestamp": tdatetime, "data": json_safe_loads(r[2])})
            return data_return
        finally:
            cur.close()

    def get_packet_count(self, filters=None, time_range=None,
                         table_name='redvypr_packets') -> int:
        where_clauses, params = [], []
        if time_range:
            if "tstart" in time_range: where_clauses.append(
                "timestamp >= ?"); params.append(time_range["tstart"])
            if "tend" in time_range: where_clauses.append(
                "timestamp <= ?"); params.append(time_range["tend"])

        where_stmt = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        cur = self._connection.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table_name} {where_stmt}", params)
            res = cur.fetchone()
            return res[0] if res else 0
        finally:
            cur.close()

    def get_unique_combination_stats(self, keys: List[str], filters=None,
                                            table_name='redvypr_packets',
                                            time_col='timestamp') -> List[
        Dict[str, Any]]:
        col_string = ", ".join(keys)

        # In SQLite we use group_concat(column)
        sql = f"""
            SELECT 
                {col_string}, 
                COUNT(*) as count, 
                MIN({time_col}) as first_seen, 
                MAX({time_col}) as last_seen,
                group_concat(id) as ids
            FROM {table_name} 
            GROUP BY {col_string}
        """

        cur = self._connection.cursor()
        try:
            cur.execute(sql)
            results = []
            for r in cur.fetchall():
                d = dict(zip(keys, r[:len(keys)]))

                # Since group_concat returns a string "1,2,3",
                # we need to split it into a Python list and convert to int
                raw_ids = r[-1]
                id_list = [int(i) for i in raw_ids.split(",")] if raw_ids else []

                d.update({
                    "count": r[-4],
                    "first_seen": r[-3],
                    "last_seen": r[-2],
                    "ids": id_list
                })
                results.append(d)
            return results
        finally:
            cur.close()



    def get_unique_combination_stats_legacy(self, keys: List[str], filters=None,
                                     table_name='redvypr_packets',
                                     time_col='timestamp') -> List[Dict[str, Any]]:
        # Basis-Implementierung für die UI-Statistik
        col_string = ", ".join(keys)
        sql = f"SELECT {col_string}, COUNT(*) as count, MIN({time_col}), MAX({time_col}) FROM {table_name} GROUP BY {col_string}"
        cur = self._connection.cursor()
        try:
            cur.execute(sql)
            results = []
            for r in cur.fetchall():
                d = dict(zip(keys, r[:len(keys)]))
                d.update({"count": r[-3], "first_seen": r[-2], "last_seen": r[-1]})
                results.append(d)
            return results
        finally:
            cur.close()