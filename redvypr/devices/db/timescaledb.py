import json
import os
import sqlite3
import logging
import sys
from datetime import datetime, timezone
import psycopg
from typing import Iterator, Optional, Any, Dict
from contextlib import contextmanager
from redvypr.redvypr_address import RedvyprAddress

import numpy as np

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.timescaledb')
logger.setLevel(logging.DEBUG)



class RedvyprTimescaleDb:
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
