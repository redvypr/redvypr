import json
import os
import sqlite3
import logging
import sys
from datetime import datetime, timezone

import numpy as np

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.sqlite3db')
logger.setLevel(logging.DEBUG)



class RedvyprDbSqlite3:
    def __init__(self, db_file: str = "redvypr_data.db"):
        """Open a persistent connection to the SQLite database."""
        self.db_file = db_file
        self.file_status = 'open'

        # Check if the database file already exists
        db_exists = os.path.exists(db_file)

        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()

        # If it's a new file, initialize the tables
        if not db_exists:
            self.init_db()

    def init_db(self):
        """Create the table if it doesn’t exist."""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS redvypr_packets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                data JSON NOT NULL
            )
        """)
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_redvypr_timestamp
            ON redvypr_packets (timestamp)
        """)
        self.conn.commit()

    def insert_packet(self, packet: dict, timestamp: str | None = None):
        """Insert a Redvypr packet with the current or provided timestamp."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        try:
            jsonstr = json_safe_dumps(packet)
            #print("Jsonstr",jsonstr)
        except:
            logger.info("Could not serialize data",exc_info=True)
            #print(packet)
            raise ValueError("Bad")

        self.cursor.execute("""
            INSERT INTO redvypr_packets (timestamp, data)
            VALUES (?, json(?))
        """, (timestamp, jsonstr))

    def commit(self):
        """Manually commit — e.g. after multiple inserts."""
        self.conn.commit()

    def get_all_packets(self):
        """Fetch all stored packets."""
        self.cursor.execute("SELECT id, timestamp, data FROM redvypr_packets ORDER BY timestamp DESC")
        return [
            {"id": row[0], "timestamp": row[1], "data": json.loads(row[2])}
            for row in self.cursor.fetchall()
        ]

    def get_stats(self):
        """Return the number of packets, earliest timestamp, and latest timestamp."""
        self.cursor.execute("""
            SELECT COUNT(*), MIN(timestamp), MAX(timestamp)
            FROM redvypr_packets
        """)
        count, min_ts, max_ts = self.cursor.fetchone()
        return {
            "count": count or 0,
            "min_timestamp": min_ts,
            "max_timestamp": max_ts
        }

    def query_by_device(self, device_id: str):
        """Example query: filter packets by device_id inside the JSON."""
        self.cursor.execute("""
            SELECT id, timestamp, data
            FROM redvypr_packets
            WHERE json_extract(data, '$.device_id') = ?
            ORDER BY timestamp DESC
        """, (device_id,))
        return [
            {"id": row[0], "timestamp": row[1], "data": json.loads(row[2])}
            for row in self.cursor.fetchall()
        ]

    def get_packet_by_index(self, index: int):
        """
        Return the packet at the given index (0-based) ordered by insertion (id ASC).

        Example:
            get_packet_by_index(0) -> first inserted packet
            get_packet_by_index(9) -> tenth inserted packet
        """
        self.cursor.execute("""
            SELECT id, timestamp, data
            FROM redvypr_packets
            ORDER BY id ASC
            LIMIT 1 OFFSET ?
        """, (index,))
        row = self.cursor.fetchone()
        if not row:
            return None
        return {"id": row[0], "timestamp": row[1], "data": json.loads(row[2])}

    def close(self):
        """Close the database connection cleanly."""
        self.file_status = 'closed'
        self.conn.commit()
        self.conn.close()


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
