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
logger = logging.getLogger('redvypr.device.sqlite3db')
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
            self.add_raddstr_column(column_name='raddstr')
            self.add_raddstr_column(column_name='packetid')
            self.add_raddstr_column(column_name='publisher')
            self.add_raddstr_column(column_name='host')
            self.add_raddstr_column(column_name='device')

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
                    data JSONB NOT NULL,
                    redvypr_address TEXT NOT NULL,
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
                print(f"❌ Error during Hypertable creation: {e}")

        # --- NEW METHOD TO ADD MISSING COLUMN ---
        def add_raddstr_column(self, table_name: str = 'redvypr_packets',
                               column_name: str = 'raddstr'):
            """
            Safely adds a missing column (raddstr) to the existing table using a DO block for idempotency.
            """
            # Note: The column is added as NULL-able to avoid issues with existing data.
            alter_sql = f"""
                DO $$
                BEGIN
                    -- Check if the column already exists in the information_schema
                    IF NOT EXISTS (
                        SELECT 1 
                        FROM information_schema.columns 
                        WHERE table_name = '{table_name}' AND column_name = '{column_name}'
                    ) THEN
                        -- If it does not exist, add the column as TEXT
                        ALTER TABLE {table_name} ADD COLUMN {column_name} TEXT;
                        RAISE NOTICE 'Column % was successfully added to table %.', '{column_name}', '{table_name}';
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
                            f"Checking for and adding column '{column_name}' to '{table_name}'...")
                        cur.execute(alter_sql)
                        conn.commit()
                        print("✅ Schema check/update complete.")
            except Exception as e:
                print(f"❌ Error adding column '{column_name}': {e}")
        # ----------------------------------------

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
               INSERT INTO {table_name} (timestamp, data, raddstr, host, publisher, device, packetid)
               VALUES (%s, %s, %s, %s, %s, %s, %s);
            """

            # Convert the Python dictionary to a JSON string for the JSONB column
            json_data = json_safe_dumps(data_dict)
            try:
                timestamp_value = data_dict['t']
                raddr = RedvyprAddress(data_dict)
                raddrstr = raddr.to_address_string()
                host = raddr.hostname
                device = raddr.device
                packetid = raddr.packetid
                publisher = raddr.publisher
            except Exception as e:
                print(f"❌ Data is not compatible for inserting: {e}")
                return
            if isinstance(timestamp_value, (int, float)):
                timestamp_utc = datetime.fromtimestamp(timestamp_value, tz=timezone.utc)
            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        data_insert = (timestamp_utc, json_data, raddrstr, host, publisher, device, packetid)
                        print("data insert",data_insert)
                        print("insert sql",insert_sql)
                        # Execute the INSERT command, passing parameters safely
                        cur.execute(insert_sql, data_insert)
                        conn.commit()
            except Exception as e:
                print(f"❌ Error inserting data: {e}")



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
