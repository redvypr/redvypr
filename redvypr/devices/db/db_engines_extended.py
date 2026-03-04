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
from typing import Any, Dict, List, Optional, Iterator
import psycopg
import hashlib
import re
from abc import ABC, abstractmethod
from typing import Iterator, Optional, Any, Dict
from redvypr.redvypr_address import RedvyprAddress
from .db_engines import SqliteConfig, TimescaleConfig, RedvyprDBFactory, AbstractDatabase, RedvyprSqliteDb, RedvyprTimescaleDb

import numpy as np

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db_engines_extended')
logger.setLevel(logging.DEBUG)




def sanitize_name_for_db(address: str) -> str:
    """
    Converts a Redvypr address into a SQL-compatible column name.
    - Normalizes special characters to underscores
    - Lowercases
    - Removes duplicate underscores
    - Ensures valid starting character
    - Truncates prefix to 30 chars
    - Appends 8-char SHA1 hash of normalized original
    Result is PostgreSQL/TimescaleDB safe (<63 bytes).
    """

    replacements = {
        "@": "_at_",
        ":": "_",
        "[": "_",
        "]": "_",
        " ": "_",
        "/": "_",
        "~": "_",
        "^": "_",
        "$": "_",
        ".": "_",
        "'": "_",
        '"': "_",
        "(": "_",
        ")": "_",
        "-": "_",
        "+": "_pl_",
    }

    name = address

    # Replace special characters
    for old, new in replacements.items():
        name = name.replace(old, new)

    # Lowercase
    name = name.lower()

    # Replace any remaining invalid characters with underscore
    name = re.sub(r"[^a-z0-9_]", "_", name)

    # Remove duplicate underscores
    name = re.sub(r"_+", "_", name)

    # Strip leading/trailing underscores
    name = name.strip("_")

    # Ensure it doesn't start with digit
    if name and name[0].isdigit():
        name = f"d_{name}"

    # Compute hash of normalized name
    hash_suffix = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]

    if len(name) > 30:
        # Take prefix (30 chars max)
        prefix = name[:30]

        # Combine
        final_name = f"{prefix}__{hash_suffix}"

        return final_name
    else:
        return name


class TimescaleConfigExtended(TimescaleConfig):
    dbtype: typing.Literal["timescale_ext"] = pydantic.Field(
        default="timescale_ext",
        description="The type of the database engine."
    )
    tables: Dict[str, List[str]] = pydantic.Field(
        default_factory=dict,
        description="""
            A dictionary mapping table names to lists of Redvypr addresses.
            Example:
            {
                "sensor_data": ["data[0]@i:test", "u['temp']@d:cam"],
                "metadata": ["host@u:uuid", "device@d:name"]
            }
            """
    )

class SqliteConfigExtended(SqliteConfig):
    dbtype: typing.Literal["sqlite_ext"] = pydantic.Field(
        default="sqlite_ext",
        description="The type of the database engine."
    )
    save_whole_packets: bool = pydantic.Field(default=True,
                                              description="Flag if the whole data packets shall be saved (the subscribed ones!)")
    save_metadata: bool = pydantic.Field(default=True,
                                              description="Flag if the metadata shall be saved")
    tables: Dict[str, List[str]] = pydantic.Field(
        default_factory=dict,
        description="""
            A dictionary mapping table names to lists of Redvypr addresses.
            Example:
            {
                "sensor_data": ["data[0]@i:test", "u['temp']@d:cam"],
                "metadata": ["host@u:uuid", "device@d:name"]
            }
            """
    )

# Das 'Union' erlaubt entweder das eine oder das andere Modell
DatabaseConfigExtended = typing.Union[TimescaleConfigExtended, SqliteConfigExtended]
class DatabaseSettingsExtended(pydantic.RootModel):
    root: typing.Annotated[
        DatabaseConfigExtended,
        pydantic.Field(discriminator="dbtype")
    ]

class RedvyprDBFactoryExtended:
    """
    Factory to create database instances directly from a DatabaseConfig.
    """

    @staticmethod
    def create(db_config: DatabaseConfigExtended) -> AbstractDatabase:
        """
        Returns a concrete AbstractDatabase implementation.
        """
        # A flat instance (the most children like at the top)
        if isinstance(db_config, SqliteConfigExtended):
            print(f"db config for sqlite extended:{db_config}")
            return RedvyprSqliteDbExtended(
                base_name=db_config.filepath,
                max_file_size_mb=db_config.max_file_size_mb,
                size_check_interval=db_config.size_check_interval,
                file_format=db_config.file_format,
                tables=db_config.tables
            )

        # Handling TimescaleDB
        elif isinstance(db_config, TimescaleConfig):
            return RedvyprTimescaleDb(
                dbname=db_config.dbname,
                user=db_config.user,
                password=db_config.password,
                host=db_config.host,
                port=db_config.port
            )

        # Handling SQLite
        elif isinstance(db_config, SqliteConfig):
            print(f"db config for sqlite:{db_config}")
            return RedvyprSqliteDb(
                base_name=db_config.filepath,
                max_file_size_mb=db_config.max_file_size_mb,
                size_check_interval=db_config.size_check_interval,
                file_format=db_config.file_format
            )

        # Fallback for dict-based configs (e.g. if loaded from JSON without Pydantic parsing)
        elif isinstance(db_config, dict):
            dbtype = db_config.get("dbtype")
            if dbtype == "timescaledb":
                print("timescaledb from dict")
                return RedvyprTimescaleDb(
                    **{k: v for k, v in db_config.items() if k != "dbtype"})
            elif dbtype == "sqlite":
                print("Sqlite from dict")
                return RedvyprSqliteDb(filepath=db_config.get("filepath"))
            elif dbtype == "sqlite_ext":
                print("Sqlite extended from dict")
                return RedvyprSqliteDbExtended(filepath=db_config.get("filepath"))

        raise ValueError(f"Unsupported database configuration type: {type(db_config)}")

class RedvyprSqliteDbExtended(RedvyprSqliteDb):
    """
    Extended SQLite database for flat tables with Redvypr addresses as columns.
    Supports reversible mapping between sanitized column names and original Redvypr addresses.
    """

    def __init__(self, *args, tables=None, **kwargs):
        """
        Initializes the database and creates flat tables based on the provided `tables` dictionary.

        Args:
            *args: Positional arguments for the parent class.
            tables: A dictionary where keys are table names and values are lists of Redvypr addresses.
                   Example: {"sensor_data": ["temp@d:thermo", "humidity@d:hygro"]}
            **kwargs: Keyword arguments for the parent class.
        """
        super().__init__(*args, **kwargs)
        if tables is None:
            self.tables = {}
        else:
            self.tables = tables

        self.tables_redvypr_address = {}
        for tablename in self.tables.keys():
            self.tables_redvypr_address[tablename] = []
            for a in self.tables[tablename]:
                self.tables_redvypr_address[tablename].append(RedvyprAddress(a))

        self._flat_tables = set()  # Tracks created flat tables



    def setup_schema(self, table_name: str = 'redvypr_packets'):
        print("Setup schema extended ...")
        super().setup_schema(table_name=table_name)
        if len(self.tables) > 0:
            print("Creating table/column mappings")
            self._ensure_table_mapping_table()
            self._ensure_column_mapping_table()
            # Initialize all tables from the `tables` dictionary
            for table_name, address_strings in self.tables.items():
                print(f"Creating flat table:{table_name}")
                # Convert address strings to RedvyprAddress objects
                addresses = [RedvyprAddress(addr) for addr in address_strings]
                self.create_flat_table(table_name, addresses)


    def _ensure_table_mapping_table(self) -> None:
        """Ensures the table mapping table exists."""
        cur = self._connection.cursor()
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS redvypr_flat_table_mapping (
                    original_table_name TEXT NOT NULL,
                    sanitized_table_name TEXT NOT NULL,
                    table_type TEXT NOT NULL,  -- z. B. 'flat', 'raw', 'agg'
                    description TEXT,          -- Optional: Beschreibung der Tabelle
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (original_table_name, sanitized_table_name),
                    UNIQUE (sanitized_table_name)  -- Verhindert doppelte sanitized Namen
                );
            """)
            logger.info("Table mapping table created/verified.")
        except sqlite3.Error as e:
            logger.error(f"Error creating table mapping table: {e}")
        finally:
            cur.close()

    def _ensure_column_mapping_table(self) -> None:
        """Ensures the column mapping table exists."""
        cur = self._connection.cursor()
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS redvypr_flat_column_mapping (
                    table_name TEXT NOT NULL,
                    sanitized_table_name TEXT NOT NULL,
                    sanitized_name TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    PRIMARY KEY (table_name, sanitized_name),
                    UNIQUE (table_name, original_name)
                );
            """)
        except sqlite3.Error as e:
            logger.error(f"Error creating mapping table: {e}")
        finally:
            cur.close()

    def sanitize_table_name(self, table_name: str) -> str:
        sanitized_table_name_tmp = self.sanitize_name(table_name)
        sanitized_table_name = f"rf_{sanitized_table_name_tmp}"  # add redvypr flat (rf_)
        return sanitized_table_name

    def sanitize_name(self, address: str) -> str:
        """
        Converts a Redvypr address into a SQL-compatible column name.
        Replaces special characters with underscores and truncates to 64 characters.
        """
        return sanitize_name_for_db(address)

    def reverse_sanitized_name(self, sanitized_name: str, table_name: str) -> Optional[str]:
        """
        Reverses a sanitized column name to its original Redvypr address.

        Args:
            sanitized_name: The sanitized column name (e.g., "data_0_at_i_test").
            table_name: The name of the table.

        Returns:
            The original Redvypr address, or None if not found.
        """
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT original_name
                FROM redvypr_flat_column_mapping
                WHERE table_name = ? AND sanitized_name = ?;
            """, (table_name, sanitized_name))
            row = cur.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            logger.error(f"Error reversing sanitized name: {e}")
            return None
        finally:
            cur.close()

    def get_sanitized_name(self, original_name: str, table_name: str) -> Optional[str]:
        """
        Retrieves the sanitized column name for a given original Redvypr address.

        Args:
            original_name: The original Redvypr address (e.g., "data[0]@i:test").
            table_name: The name of the table.

        Returns:
            The sanitized column name, or None if not found.
        """
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT sanitized_name
                FROM redvypr_flat_column_mapping
                WHERE table_name = ? AND original_name = ?;
            """, (table_name, original_name))
            row = cur.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            logger.error(f"Error getting sanitized name: {e}")
            return None
        finally:
            cur.close()

    def _add_table_mapping(
            self,
            original_table_name: str,
            sanitized_table_name: str,
            table_type: str = "flat",
            description: Optional[str] = None
    ) -> bool:
        """
        Adds a mapping between an original table name and its sanitized table name.

        Args:
            original_table_name: The original table name (e.g., "sensor_data").
            sanitized_table_name: The sanitized table name (e.g., "rf_sensor_data").
            table_type: The type of the table (e.g., "flat", "raw", "agg").
            description: Optional description of the table.

        Returns:
            True if the mapping was added successfully, False otherwise.
        """
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT OR REPLACE INTO redvypr_flat_table_mapping
                (original_table_name, sanitized_table_name, table_type, description)
                VALUES (?, ?, ?, ?);
            """, (original_table_name, sanitized_table_name, table_type, description))
            conn.commit()
            logger.info(
                f"Added table mapping: {original_table_name} -> {sanitized_table_name}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Error adding table mapping: {e}")
            conn.rollback()
            return False
        finally:
            cur.close()

    def _add_column_mapping(self, table_name: str, sanitized_table_name: str, original_name: str, sanitized_name: str) -> bool:
        """
        Adds a mapping between an original Redvypr address and its sanitized column name.

        Args:
            table_name: The name of the table.
            original_name: The original Redvypr address.
            sanitized_name: The sanitized column name.

        Returns:
            True if the mapping was added successfully, False otherwise.
        """
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT OR REPLACE INTO redvypr_flat_column_mapping
                (table_name, sanitized_table_name, sanitized_name, original_name)
                VALUES (?, ?, ?, ?);
            """, (table_name, sanitized_table_name, sanitized_name, original_name))
            conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error adding mapping: {e}")
            conn.rollback()
            return False
        finally:
            cur.close()

    def infer_sqlite_type(self, value: Any) -> str:
        """Infers the SQLite type from a Python value."""
        if value is None:
            return "TEXT"
        elif isinstance(value, bool):
            return "INTEGER"
        elif isinstance(value, int):
            return "INTEGER"
        elif isinstance(value, float):
            return "REAL"
        elif isinstance(value, str):
            return "TEXT"
        elif isinstance(value, (list, dict)):
            return "TEXT"
        else:
            return "TEXT"


    def create_flat_table(self, table_name: str,
                          addresses: List[RedvyprAddress]) -> bool:
        """
        Creates a flat table with columns for each Redvypr address.
        Updates the `tables` dictionary and adds mappings for sanitized names.

        Args:
            table_name: Name of the table to create.
            addresses: List of RedvyprAddress objects defining the columns.

        Returns:
            True if the table was successfully created/updated, False otherwise.
        """
        if not table_name or not addresses:
            logger.error("Invalid parameters: table_name or addresses is empty.")
            return False


        sanitized_table_name = self.sanitize_table_name(table_name)
        print(f"Creating flat table for:{table_name}:{sanitized_table_name}")
        # Add the table to the tracking set
        if sanitized_table_name not in self._flat_tables:
            self._flat_tables.add(sanitized_table_name)

        # Initialize the table entry in the `tables` dict if it doesn't exist
        if table_name not in self.tables:
            self.tables[table_name] = []

        conn = self.connect()
        cur = conn.cursor()

        # Add the table mapping
        self._add_table_mapping(
            original_table_name=table_name,
            sanitized_table_name=sanitized_table_name,
            table_type="flat",
            description=f"Flat table for {table_name}."
        )

        try:
            # Create the table if it doesn't exist
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {sanitized_table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    UNIQUE(timestamp)
                );
            """)

            # Process each Redvypr address
            for addr in addresses:
                original_column_name = addr.to_address_string()

                # Add the original name to the `tables` dict if not already present
                if original_column_name not in self.tables[table_name]:
                    self.tables[table_name].append(original_column_name)

                sanitized_column_name = self.sanitize_name(original_column_name)

                # Add the mapping to the database
                self._add_column_mapping(table_name, sanitized_table_name, original_column_name, sanitized_column_name)

                # Check if the column exists, and add it if missing
                cur.execute(f"PRAGMA table_info({table_name});")
                existing_columns = {row[1] for row in cur.fetchall()}
                if sanitized_column_name not in existing_columns:
                    # Default to TEXT; type will be inferred during insertion
                    cur.execute(
                        f"ALTER TABLE {sanitized_table_name} ADD COLUMN {sanitized_column_name} TEXT;")
                    logger.info(f"Added column {sanitized_column_name} to table {sanitized_table_name}.")

            conn.commit()
            return True

        except sqlite3.Error as e:
            logger.error(f"Error creating table {table_name} ({sanitized_table_name}): {e}")
            conn.rollback()
            return False

        finally:
            cur.close()

    def insert_packet(self, data_dict: Dict[str, Any],
                      table_name: str = 'redvypr_packets'):
        # Standard packet writing
        super().insert_packet(data_dict=data_dict, table_name=table_name)
        # Check if we can save something into flat tables
        for tablename in self.tables.keys():
            print(f"Inserting packet into table:{tablename}")
            for ind_ra,ra in enumerate(self.tables_redvypr_address[tablename]):
                print(f"ra:{ra=}")
                a = self.tables[tablename][ind_ra]
                data_save = ra(data_dict, strict=False) # Returns None if it fails
                print("data save",data_save)
                t_save = data_dict["t"]
                if data_save:
                    print("Found data and will save it into tablename")
                    self.insert_packet_flat(table_name = tablename, address = a, timestamp = t_save, data = data_save, packet = data_dict)

    def insert_packet_flat(
            self,
            table_name: str,
            address: str,
            timestamp: float,
            data: Any,
            packet: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Inserts a single data value into a flat table for a specific Redvypr address and timestamp.
        Automatically adds new columns and mappings as needed.

        Args:
            table_name: Name of the flat table (e.g., "rf_sensor_data").
            address: The original Redvypr address (e.g., "temp@d:thermo").
            timestamp: The timestamp for the data point (as float or datetime).
            data: The data value to insert.
            packet: Optional full packet (unused in this simplified version).

        Returns:
            True if the data was successfully inserted, False otherwise.
        """
        print(f"Inserting data into:{table_name}")
        if not table_name or not address:
            logger.error("Invalid parameters: table_name or address is empty.")
            return False

        # Sanitize the table name (prepend 'rf_' if not already present)
        sanitized_table_name = self.sanitize_table_name(table_name)

        if sanitized_table_name not in self._flat_tables:
            logger.error(
                f"Table {sanitized_table_name} for {table_name} does not exist. Create it first with create_flat_table().")
            return False

        # Sanitize the column name from the Redvypr address
        print("Sanitizing address:",address)
        sanitized_column_name = self.sanitize_name(address)
        print("Sanitized address:", sanitized_column_name)

        # Get or create the mapping for the column
        existing_sanitized = self.get_sanitized_name(address, table_name)
        if not existing_sanitized:
            self._add_column_mapping(table_name, address, sanitized_column_name)

        # Convert timestamp to datetime if necessary
        if isinstance(timestamp, (int, float)):
            timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc)

        # Connect to the database
        conn = self.connect()
        cur = conn.cursor()

        try:
            # Check if the column exists, and add it if missing
            cur.execute(f"PRAGMA table_info({sanitized_table_name});")
            existing_columns = {row[1] for row in cur.fetchall()}
            if sanitized_column_name not in existing_columns:
                col_type = self.infer_sqlite_type(data)
                cur.execute(
                    f"ALTER TABLE {sanitized_table_name} ADD COLUMN {sanitized_column_name} {col_type};"
                )
                logger.info(
                    f"Added column {sanitized_column_name} ({col_type}) to table {sanitized_table_name}.")

            # Insert or update the data
            sql = f"""
                INSERT INTO {sanitized_table_name} (timestamp, {sanitized_column_name})
                VALUES (?, ?)
                ON CONFLICT(timestamp) DO UPDATE SET
                    {sanitized_column_name} = excluded.{sanitized_column_name};
            """
            cur.execute(sql, (timestamp, data))
            conn.commit()
            logger.info(
                f"Inserted data for {address} at {timestamp} into {sanitized_table_name}.")
            return True

        except sqlite3.Error as e:
            logger.error(f"Error inserting data into {sanitized_table_name}: {e}")
            conn.rollback()
            return False

        finally:
            cur.close()

    def get_flat_table_columns(self, table_name: str) -> List[Dict[str, str]]:
        """
        Returns a list of all columns in the flat table, including original names.

        Args:
            table_name: Name of the flat table.

        Returns:
            List of dictionaries with column names, types, and original names.
        """
        if table_name not in self._flat_tables:
            logger.error(f"Table {table_name} does not exist.")
            return []

        conn = self.connect()
        cur = conn.cursor()

        try:
            # Get column info from SQLite
            cur.execute(f"PRAGMA table_info({table_name});")
            columns = []
            for row in cur.fetchall():
                sanitized_name = row[1]  # Column name
                col_type = row[2]        # Column type

                # Get the original name from the mapping table
                original_name = self.reverse_sanitized_name(sanitized_name, table_name)

                columns.append({
                    "sanitized_name": sanitized_name,
                    "original_name": original_name,
                    "type": col_type,
                })
            return columns
        except sqlite3.Error as e:
            logger.error(f"Error fetching columns from {table_name}: {e}")
            return []
        finally:
            cur.close()

    def get_all_mappings(self, table_name: str) -> List[Dict[str, str]]:
        """
        Returns all mappings for a given table.

        Args:
            table_name: Name of the table.

        Returns:
            List of dictionaries with original and sanitized names.
        """
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT original_name, sanitized_name
                FROM redvypr_flat_column_mapping
                WHERE table_name = ?;
            """, (table_name,))
            return [{"original_name": row[0], "sanitized_name": row[1]} for row in cur.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error fetching mappings: {e}")
            return []
        finally:
            cur.close()



