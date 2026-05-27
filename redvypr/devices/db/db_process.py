from qtpy import QtWidgets, QtCore, QtGui
import logging
from PyQt6 import QtWidgets, QtCore, QtGui
import qtawesome
import time
import logging
import sys
import pydantic
import redvypr
import typing
import copy
from collections import defaultdict
import datetime
from PyQt6 import QtWidgets, QtCore
from redvypr.data_packets import check_for_command
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket
from .db_engine_sqlite import SqliteConfig, DbSqlite, DataQuery
import redvypr.devices.fileio.netcdfwriter as ncwriter

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db.db_process')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = 'Processes redvypr database(s) data'
    gui_tablabel_display: str = 'db process'

class DeviceCustomConfig(pydantic.BaseModel):
    size_packetbuffer: int = 100
    read_metadata: bool = pydantic.Field(default=True, description="Read metadata from the database and publish it")
    packet_filter: typing.List[RedvyprAddress] = pydantic.Field(default=[])
    tstart: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    tend: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    speedup: float = pydantic.Field(default=1.0,
                                    description='Speedup factor of the data in realtime mode')
    constant_dt: float = pydantic.Field(default=.1,
                                    description='Constant time between to packets in constant mode')
    replay_mode: typing.Literal["realtime","constant"] = pydantic.Field(default="realtime")






class DbReader:
    def __init__(self, backends: typing.List[typing.Any] = None):
        """
        Aggregates multiple redvypr database backends (SQLite or TimescaleDB)
        into a seamless, unified timeseries view.

        Parameters
        ----------
        backends : list, optional
            A list of initialized database backend objects providing 'get_data'
            and 'get_data_tables' methods.
        """
        self.backends = []
        self.backend_tables = []
        if backends:
            for b in backends:
                self.add_backend(b)

    def add_backend(self, backend: typing.Any):
        """
        Add a new database instance (SQLite or TimescaleDB) to the reader pipeline.

        Parameters
        ----------
        backend : Any
            The database instance to append.
        """
        backend_tables = backend.get_data_tables(tabletype='all')
        self.backends.append(backend)
        self.backend_tables.append(backend_tables)
        data_tables = self.get_data_tables()
        self.data_tables = data_tables

    def get_data_tables(self, tabletype: typing.Literal[
        'all', 'raw', 'flat'] = 'all') -> dict:
        """
        Get registered data tables filtered by their architectural type,
        merging metadata statistics dynamically across all registered database backends.

        Parameters
        ----------
        tabletype : {'all', 'raw', 'flat'}, default 'all'
            The structural type of the tables to retrieve.

        Returns
        -------
        dict
            A structured dictionary of merged tables, global stats, and containing metrics.
        """
        global_tables = {}

        for backend_tables in self.backend_tables:
            try:
                for tablename, info in backend_tables.items():
                    if tablename not in global_tables:
                        # Initialize structure with the first backend's data
                        global_tables[tablename] = {
                            'tablename_db': info.get('tablename_db'),
                            'tabletype': info.get('tabletype'),
                            'num_entries': info.get('num_entries', 0),
                            't_first': info.get('t_first'),
                            't_last': info.get('t_last'),
                            't_packet_first': info.get('t_packet_first'),
                            't_packet_last': info.get('t_packet_last'),
                            'addresses': {}
                        }
                    else:
                        # Aggregate rows and expand time boundaries (MIN/MAX)
                        tgt = global_tables[tablename]
                        tgt['num_entries'] += info.get('num_entries', 0)

                        tgt['t_first'] = min(
                            filter(None, [tgt['t_first'], info.get('t_first')]),
                            default=None)
                        tgt['t_last'] = max(
                            filter(None, [tgt['t_last'], info.get('t_last')]),
                            default=None)
                        tgt['t_packet_first'] = min(filter(None, [tgt['t_packet_first'],
                                                                  info.get(
                                                                      't_packet_first')]),
                                                    default=None)
                        tgt['t_packet_last'] = max(filter(None, [tgt['t_packet_last'],
                                                                 info.get(
                                                                     't_packet_last')]),
                                                   default=None)

                    # Merge address metrics inside the current table
                    tgt_addresses = global_tables[tablename]['addresses']
                    for addr, addr_info in info.get('addresses', {}).items():
                        if addr not in tgt_addresses:
                            tgt_addresses[addr] = {
                                'address_db': addr_info.get('address_db'),
                                'num_entries': addr_info.get('num_entries', 0),
                                't_first': addr_info.get('t_first'),
                                't_last': addr_info.get('t_last'),
                                't_packet_first': addr_info.get('t_packet_first'),
                                't_packet_last': addr_info.get('t_packet_last')
                            }
                        else:
                            t_addr = tgt_addresses[addr]
                            t_addr['num_entries'] += addr_info.get('num_entries', 0)
                            t_addr['t_first'] = min(filter(None, [t_addr['t_first'],
                                                                  addr_info.get(
                                                                      't_first')]),
                                                    default=None)
                            t_addr['t_last'] = max(filter(None, [t_addr['t_last'],
                                                                 addr_info.get(
                                                                     't_last')]),
                                                   default=None)
                            t_addr['t_packet_first'] = min(filter(None, [
                                t_addr['t_packet_first'],
                                addr_info.get('t_packet_first')]), default=None)
                            t_addr['t_packet_last'] = max(filter(None, [
                                t_addr['t_packet_last'],
                                addr_info.get('t_packet_last')]), default=None)

            except Exception as e:
                logger.warning(
                    f"⚠️ Failed to query data tables from backend {backend}: {e}")

        return global_tables

    def map_index(self, tablename: str, global_limit: typing.Optional[int] = None,
                  global_offset: typing.Optional[int] = None) -> typing.List[
        typing.Optional[typing.Tuple[int, typing.Optional[int]]]]:
        """
        Calculates local offsets and limits for each backend based on pre-loaded metadata.

        Parameters
        ----------
        tablename : str
            The logical name of the table (e.g., 'redvypr_datapackets').
        global_limit : int, optional
            The total rows requested across the aggregated pipeline.
        global_offset : int, optional
            The total rows to skip across the aggregated pipeline.

        Returns
        -------
        list of (tuple or None)
            A list corresponding strictly to self.backends.
            Each item is either (local_offset, local_limit) or None if skipped.
        """
        offset_remaining = global_offset if global_offset is not None else 0
        limit_remaining = global_limit if global_limit is not None else float('inf')

        index_map = []

        # zip erlaubt uns, die Backends parallel zu den bereits geladenen Tabellen-Infos zu prüfen
        for backend, backend_tables in zip(self.backends, self.backend_tables):

            # 1. Hole die Zeilenanzahl aus den gecachten Tabellen-Metadaten
            table_info = backend_tables.get(tablename, {}) if backend_tables else {}
            num_entries = table_info.get('num_entries', 0)

            # Fall A: Keine Einträge oder das globale Limit ist bereits aufgebraucht
            if num_entries == 0 or limit_remaining <= 0:
                index_map.append(None)
                continue

            # Fall B: Der globale Offset ist größer als alle Einträge in dieser Datei zusammen
            if offset_remaining >= num_entries:
                offset_remaining -= num_entries
                index_map.append(None)
                continue

            # Fall C: Der Offset fällt in diese Datei, oder wurde bereits vollständig abgearbeitet
            local_offset = offset_remaining
            offset_remaining = 0  # Offset ist für alle folgenden Dateien verbraucht

            # Berechne, wie viele Zeilen in dieser Datei nach dem Offset noch übrig sind
            available_rows = num_entries - local_offset
            local_limit = min(limit_remaining, available_rows)

            # Reduziere das global verbleibende Limit
            if limit_remaining != float('inf'):
                limit_remaining -= local_limit

            # Verwandle unendliche Limits (kein Limit übergeben) zurück in ein sauberes None für das Backend
            backend_limit = int(local_limit) if local_limit != float('inf') else None

            index_map.append((int(local_offset), backend_limit))

        return index_map

    def get_data(
            self,
            tablename: str,
            addresses: typing.Union[str, typing.List[str]],
            query: typing.Optional[typing.Any] = None
    ) -> dict:
        """
        Retrieves, merges, deduplicates, and chronologically sorts datasets
        across all registered database backends.

        Parameters
        ----------
        tablename : str
            The logical name of the table to query.
        addresses : str or list of str
            The address string or list of address strings to query.
        query : DataQuery, optional
            A DataQuery object defining time windows, limits, offsets, and order.

        Returns
        -------
        dict
            An address-mapped dictionary containing unified timeline arrays.
            Format:
            {
                "address_string": {
                    "t": [...],
                    "t_packet": [...],
                    "numpacket": [...],
                    "data": [...]
                }
            }
        """
        # 1. Collect timeline chunks from all accessible backends
        raw_chunks = defaultdict(list)

        for backend in self.backends:
            try:
                data = backend.get_data(tablename=tablename, addresses=addresses,
                                        query=query)
                for addr, timeline in data.items():
                    if timeline and timeline.get(
                            "t"):  # Only process chunks containing actual data
                        raw_chunks[addr].append(timeline)
            except Exception as e:
                logger.warning(f"⚠️ Failed to query data from backend {backend}: {e}")

        # 2. Merge, sort and deduplicate timelines per metric address
        aggregated_result = {}

        for addr, chunks in raw_chunks.items():
            combined_rows = []
            for chunk in chunks:
                combined_rows.extend(
                    zip(chunk["t"], chunk["t_packet"], chunk["numpacket"],
                        chunk["data"])
                )

            if not combined_rows:
                continue

            # Interlace data by sorting chronologically via system timestamp 't' (Index 0)
            combined_rows.sort(key=lambda x: x[0])

            # Deduplication pass: Strip overlapping records across partition/backend boundaries
            deduplicated_rows = []
            seen_timestamps = set()
            for row in combined_rows:
                timestamp_t = row[0]
                if timestamp_t not in seen_timestamps:
                    seen_timestamps.add(timestamp_t)
                    deduplicated_rows.append(row)

            # Unzip rows back into parallel, single-type lists
            unzipped = list(zip(*deduplicated_rows))

            aggregated_result[addr] = {
                "t": list(unzipped[0]),
                "t_packet": list(unzipped[1]),
                "numpacket": list(unzipped[2]),
                "data": list(unzipped[3])
            }

        return aggregated_result

    def get_redvypr_datapackets(
            self,
            tablename: str,
            query: typing.Optional[typing.Any] = None
    ) -> dict:
        """
        Retrieves, merges, deduplicates, and chronologically sorts full datapacket
        datasets across all registered database backends using 't_packet' and 'numpacket'.
        """
        # 1. Alle Chunks aus den verfügbaren Backends einsammeln
        raw_chunks = []

        g_limit = None
        g_offset = None
        if query and hasattr(query, 'limit'):
            g_limit = query.limit
            g_offset = query.offset
            index_map = self.map_index(tablename=tablename, global_limit=g_limit, global_offset=g_offset)


        # 2. Den exakten Index-Plan für alle Backends berechnen
        index_map = self.map_index(tablename=tablename, global_limit=g_limit,
                                   global_offset=g_offset)

        for i,backend in enumerate(self.backends):
            try:
                if hasattr(backend, "get_redvypr_datapackets"):
                    query_local = None
                    if query is not None:
                        if index_map[i] is None:
                            continue
                        if query and hasattr(query, 'limit'):
                            query_local = copy.copy(query)
                            local_limit = index_map[i][1]
                            local_offset = index_map[i][0]
                            query_local.limit = local_limit
                            query_local.offset = local_offset

                    data = backend.get_redvypr_datapackets(tablename=tablename,
                                                           query=query_local)
                    # Wir prüfen hier auf 't_packet', da 't' ja -1 sein kann
                    if data and data.get("t_packet"):
                        raw_chunks.append(data)
            except Exception as e:
                logger.warning(
                    f"⚠️ Failed to query datapackets from backend {backend}: {e}")

        if not raw_chunks:
            return {}

        # 2. Spaltennamen exakt definieren (Reihenfolge muss zum Backend-SELECT passen!)
        # Indices:
        # 0: numconfig, 1: numpacket, 2: t_packet, 3: t, ...
        columns = [
            "numconfig", "numpacket", "t_packet", "t", "redvypr_address",
            "packetid", "publisher", "device", "host", "uuid", "data"
        ]

        # Zeilenweise zusammensetzen
        combined_rows = []
        for chunk in raw_chunks:
            zipped_chunk = zip(*(chunk[col] for col in columns))
            combined_rows.extend(zipped_chunk)

        if not combined_rows:
            return {}

        # 3. Chronologisch sortieren nach Paket-Zeitstempel 't_packet' (Index 2)
        reverse_order = (query.order.upper() == "DESC") if query and hasattr(query,
                                                                             "order") else False
        combined_rows.sort(key=lambda x: x[1], reverse=reverse_order)

        # 4. Deduplizierung über die von dir definierten eindeutigen Merkmale:
        # Index 1: numpacket
        # Index 2: t_packet
        deduplicated_rows = []
        seen_records = set()

        for row in combined_rows:
            record_key = (row[1], row[2])  # (numpacket, t_packet)
            if record_key not in seen_records:
                seen_records.add(record_key)
                deduplicated_rows.append(row)

        # 5. Wieder zurück in parallele Listen entpacken (Unzip)
        unzipped = list(zip(*deduplicated_rows))

        # Resultat-Dictionary aufbauen
        aggregated_result = {}
        for i, col in enumerate(columns):
            aggregated_result[col] = list(unzipped[i])

        return aggregated_result


# A dedicated worker thread for the export to keep the GUI responsive
class ExportWorker(QtCore.QThread):
    # Signals to communicate with the main GUI thread
    progress_changed = QtCore.pyqtSignal(int)
    log_message = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, db_reader, tablename, ncdev, num_entries, slice_size=5):
        super().__init__()
        self.db_reader = db_reader
        self.tablename = tablename
        self.ncdev = ncdev
        self.num_entries = num_entries
        self.slice_size = slice_size
        self._is_running = True

    def run(self):
        numread = 0
        numsent = 0

        # Prevent infinite loops if 0 packets are returned from the database
        while self._is_running and numread < self.num_entries:
            # Calculate progress percentage
            progress = int((numread / self.num_entries) * 100)
            self.progress_changed.emit(progress)

            self.log_message.emit(f"Reading packets starting at offset {numread}...")

            # Put your original DataQuery and database reading logic here:
            try:
                slice_query = DataQuery(offset=numread, limit=self.slice_size, order='ASC')
                data_table = self.db_reader.get_redvypr_datapackets(tablename=self.tablename, query=slice_query)
                data_packets = data_table['data']
                if not data_packets: break # No more data available

                numread += len(data_packets)

                for p in data_packets:
                    if numsent % 100 == 0:
                        print(f"Sent {numsent}")
                    if not self._is_running:
                        break

                    # Push data into the queue safely
                    while self._is_running:
                        try:
                            self.ncdev.datainqueue.put_nowait(p)
                            numsent += 1
                            break
                        except:
                            #logger.info("Could not write data",exc_info=True)
                            #self.log_message.emit("Queue full, waiting...")
                            time.sleep(0.1)

                    #time.sleep(0.05)

            except Exception as e:
                self.log_message.emit(f"Error during export: {str(e)}")
                break

        # Ensure it tops out at 100% when successfully completed
        if self._is_running:
            self.progress_changed.emit(100)
        self.finished.emit()

    def stop(self):
        self._is_running = False


class DbExportWidget(QtWidgets.QWidget):
    def __init__(self, db_reader, redvypr, tablename, table_data, parent=None):
        super().__init__(parent)
        self.redvypr = redvypr
        self.tablename = tablename
        self.db_reader = db_reader
        self.table_data = table_data
        self.ncdev = None
        self.worker = None



        # Set up UI layout
        self.init_ui()

        # Initialize NetCDF Device in the background
        self.create_netcdfwriter_device()

    def init_ui(self):
        # Main layout
        layout = QtWidgets.QVBoxLayout(self)

        # Title Info
        layout.addWidget(QtWidgets.QLabel(f"<b>Exporting Table:</b> {self.tablename}"))

        # Input layout for entries count
        input_layout = QtWidgets.QHBoxLayout()
        input_layout.addWidget(QtWidgets.QLabel("Number of entries to export:"))

        self.num_entries_spin = QtWidgets.QSpinBox()

        # Extract max entries from table_data dynamically
        max_entries = self.table_data.get(self.tablename, {}).get("num_entries", 1000)

        # Configure the spinbox limits and defaults
        self.num_entries_spin.setRange(0, max_entries)
        self.num_entries_spin.setValue(
            max_entries)

        input_layout.addWidget(self.num_entries_spin)
        layout.addLayout(input_layout)

        # Progress Bar
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Log Output terminal widget
        self.log_output = QtWidgets.QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(120)
        layout.addWidget(self.log_output)

        # Interaction Buttons
        button_layout = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Start Export")
        self.start_btn.clicked.connect(self.start_export)

        self.stop_btn = QtWidgets.QPushButton("Cancel")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_export)

        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        layout.addLayout(button_layout)

    def create_netcdfwriter_device(self):
        ncfilename = self.tablename
        datafolder = "./"
        nccfg = ncwriter.netcdfwriter.DeviceCustomConfig(dt_newfile=0,
                                                         zlib=True,
                                                         size_newfile=0,
                                                         fileprefix=ncfilename,
                                                         filepostfix='',
                                                         filedateformat='',
                                                         filecountformat='',
                                                         datafolder=datafolder)
        devname = 'netcdfwriter'
        devicemodulename = self.redvypr.get_devicemodulename_from_str(devname)
        print("Devname", devname, devicemodulename)
        dev = self.redvypr.add_device(devicemodulename=devicemodulename,
                                      custom_config=nccfg)
        self.ncdev = dev
        print('dataqueue', self.ncdev.dataqueue)
        self.ncdev.thread_start()

    def start_export(self):
        #self.create_netcdfwriter_device()
        # Toggle component states for processing phase
        self.start_btn.setEnabled(False)
        self.num_entries_spin.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_output.append("=== Export started ===")

        # Instantiate Thread worker and bridge signals
        self.worker = ExportWorker(
            db_reader=self.db_reader,
            tablename=self.tablename,
            ncdev=self.ncdev,
            num_entries=self.num_entries_spin.value(),
            slice_size=500
        )

        self.worker.progress_changed.connect(self.progress_bar.setValue)
        self.worker.log_message.connect(self.log_output.append)
        self.worker.finished.connect(self.export_finished)

        # Fire up the thread
        self.worker.start()

    def stop_export(self):
        if self.worker and self.worker.isRunning():
            self.log_output.append("Canceling export sequence...")
            self.worker.stop()

    def export_finished(self):
        self.log_output.append("=== Export sequence finalized ===")
        self.start_btn.setEnabled(True)
        self.num_entries_spin.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.worker = None



class DbExportWidget_legacy(QtWidgets.QWidget):
    def __init__(self, db_reader: 'DbReader',
                 redvypr,
                 tablename,
                 table_data,
                 parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.redvypr = redvypr
        self.tablename = tablename
        self.db_reader = db_reader
        self.table_data = table_data
        self.create_netcdfwriter_device()
        self.write_data_to_nc()

    def create_netcdfwriter_device(self):
        ncfilename = self.tablename
        datafolder = "./"
        nccfg = ncwriter.netcdfwriter.DeviceCustomConfig(dt_newfile=0,
                                                         zlib=True,
                                                         size_newfile=0,
                                                         fileprefix=ncfilename,
                                                         filepostfix='',
                                                         filedateformat='',
                                                         filecountformat='',
                                                         datafolder=datafolder)
        devname = 'netcdfwriter'
        devicemodulename = self.redvypr.get_devicemodulename_from_str(devname)
        print("Devname",devname,devicemodulename)
        dev = self.redvypr.add_device(devicemodulename=devicemodulename,custom_config=nccfg)
        self.ncdev = dev
        print('dataqueue',self.ncdev.dataqueue)
        self.ncdev.thread_start()

    def write_data_to_nc(self):
        # Read the whole dataset and write it
        print("Table data",self.table_data[self.tablename])
        numentries = self.table_data[self.tablename]["num_entries"]
        numentries = 50
        numread = 0
        slice_sice = 5
        while numread <= numentries:
            print(f"{numentries=}, {numread=}")
            slice_query = DataQuery(offset=numread, limit=slice_sice, order='ASC')
            print("Get packets")
            data_table = self.db_reader.get_redvypr_datapackets(tablename=self.tablename,
                                                                  query=slice_query)

            data_packets = data_table['data']
            print("Packets", len(data_packets))
            numread += len(data_packets)
            for p in data_packets:
                print("Sending",p)
                #return
                try:
                    self.ncdev.datainqueue.put_nowait(p)
                except:
                    print("Queue full, waiting")
                    time.sleep(0.2)

                time.sleep(0.1)
        print("Done")




class DbReaderWidget(QtWidgets.QWidget):
    def __init__(self, db_reader: 'DbReader', redvypr=None, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.db_reader = db_reader
        self.current_tables_data = {}
        self.redvypr = redvypr

        self.init_ui()
        self.load_initial_data()

    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)

        # --- Layout-Umbau mit verschachtelten Splittern ---
        # Haupt-Splitter verläuft vertikal (Oben vs. Unten)
        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        main_layout.addWidget(self.main_splitter)

        # Oberer Splitter verläuft horizontal (Backends links, Tabellen rechts)
        self.top_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self.top_splitter)

        # --- 1. Tabelle: Backends (Files) mit Buttons ---
        self.backends_group = QtWidgets.QGroupBox("Registered Backends (Files)")
        backends_layout = QtWidgets.QVBoxLayout(self.backends_group)

        self.backends_table = QtWidgets.QTableWidget()
        self.backends_table.setColumnCount(2)
        self.backends_table.setHorizontalHeaderLabels(["Index", "Backend Object"])
        self.backends_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.backends_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.backends_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)

        self.backends_table.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.backends_table.customContextMenuRequested.connect(
            self.show_backend_context_menu)

        backends_layout.addWidget(self.backends_table)

        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_add_backend = QtWidgets.QPushButton("Add Backend...")
        self.btn_remove_backend = QtWidgets.QPushButton("Remove Selected")

        self.btn_add_backend.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_DialogOpenButton))
        self.btn_remove_backend.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_DialogDiscardButton))

        self.btn_add_backend.clicked.connect(self.on_add_backend_clicked)
        self.btn_remove_backend.clicked.connect(self.on_remove_backend_clicked)

        btn_layout.addWidget(self.btn_add_backend)
        btn_layout.addWidget(self.btn_remove_backend)
        backends_layout.addLayout(btn_layout)

        # In den oberen horizontalen Splitter packen
        self.top_splitter.addWidget(self.backends_group)

        # --- 2. Tabelle: Tables ---
        self.tables_group = QtWidgets.QGroupBox("Database Tables")
        tables_layout = QtWidgets.QVBoxLayout(self.tables_group)
        self.tables_table = QtWidgets.QTableWidget()
        self.tables_table.setColumnCount(3)
        self.tables_table.setHorizontalHeaderLabels(
            ["Table Name", "Type", "Total Entries"])
        self.tables_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tables_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tables_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tables_table.itemSelectionChanged.connect(self.on_table_selected)
        tables_layout.addWidget(self.tables_table)

        # Ebenfalls in den oberen horizontalen Splitter packen
        self.top_splitter.addWidget(self.tables_group)

        # --- 3. Tabelle: Data (Addresses & Stats) UNTEN ---
        self.data_group = QtWidgets.QGroupBox("Table Data / Addresses")
        data_layout = QtWidgets.QVBoxLayout(self.data_group)
        self.data_table = QtWidgets.QTableWidget()
        self.data_table.setColumnCount(7)
        self.data_table.setHorizontalHeaderLabels([
            "Address / Context", "Entries", "First Time (t)", "Last Time (t)",
            "Packet First", "Packet Last", "Action"
        ])
        self.data_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        data_layout.addWidget(self.data_table)

        # In den vertikalen Haupt-Splitter (unten) packen
        self.main_splitter.addWidget(self.data_group)

        # Initiale Größenverteilung der Splitter (50% oben, 50% unten)
        self.main_splitter.setSizes([300, 300])

        self.setWindowTitle("redvypr Database Reader Explorer")
        self.resize(1200, 600)

    def load_initial_data(self):
        """Aktualisiert die Backend-Liste und lädt danach die Tabellendaten neu."""
        self.backends_table.setRowCount(len(self.db_reader.backends))
        for row, backend in enumerate(self.db_reader.backends):
            self.backends_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(row)))
            self.backends_table.setItem(row, 1,
                                        QtWidgets.QTableWidgetItem(str(backend)))

        self.refresh_tables_and_data()

    def refresh_tables_and_data(self):
        """Holt die Tabellen-Metadaten neu aus dem db_reader und aktualisiert die UI."""
        selected_ranges = self.tables_table.selectedRanges()
        selected_tablename = None
        if selected_ranges:
            row = selected_ranges[0].topRow()
            item = self.tables_table.item(row, 0)
            if item:
                selected_tablename = item.text()

        self.current_tables_data = self.db_reader.get_data_tables(tabletype='all')

        self.tables_table.setRowCount(len(self.current_tables_data))
        restore_row = -1

        for row, (tablename, info) in enumerate(self.current_tables_data.items()):
            self.tables_table.setItem(row, 0, QtWidgets.QTableWidgetItem(tablename))
            self.tables_table.setItem(row, 1, QtWidgets.QTableWidgetItem(
                str(info.get('tabletype', 'N/A'))))
            self.tables_table.setItem(row, 2, QtWidgets.QTableWidgetItem(
                str(info.get('num_entries', 0))))

            if tablename == selected_tablename:
                restore_row = row

        if restore_row != -1:
            self.tables_table.selectRow(restore_row)
        else:
            self.data_table.setRowCount(0)

    def show_backend_context_menu(self, pos: QtCore.QPoint):
        """Erzeugt das Rechtsklick-Kontextmenü für die Backend-Tabelle."""
        item = self.backends_table.itemAt(pos)
        menu = QtWidgets.QMenu(self)

        add_action = menu.addAction("Add New Backend...")
        add_action.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_DialogOpenButton))
        add_action.triggered.connect(self.on_add_backend_clicked)

        if item is not None:
            menu.addSeparator()
            remove_action = menu.addAction("Remove Selected Backend")
            remove_action.setIcon(self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_DialogDiscardButton))
            remove_action.triggered.connect(self.on_remove_backend_clicked)

        menu.exec(self.backends_table.mapToGlobal(pos))

    def on_add_backend_clicked(self):
        """Wird aufgerufen, wenn ein neues Backend hinzugefügt werden soll."""
        file_paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select SQLite Database Backend", "",
            "Database Files (*.db *.sql *.sqlite *.sqlite3);;All Files (*)"
        )

        if file_paths:
            for file_path in file_paths:
                logger.info(f"Opening file {file_path}")
                try:
                    c = SqliteConfig(filepath=file_path)
                    db_sql_reader = DbSqlite(c, mode='read')
                    self.db_reader.add_backend(db_sql_reader)

                except Exception as e:
                    QtWidgets.QMessageBox.critical(self, "Error",
                                                   f"Could not add backend:\n{e}")

            logger.info(f"Loading data statistics of backends")
            self.load_initial_data()

    def on_remove_backend_clicked(self):
        """Entfernt das ausgewählte Backend aus dem db_reader Pipeline."""
        selected_ranges = self.backends_table.selectedRanges()
        if not selected_ranges:
            QtWidgets.QMessageBox.information(self, "No Selection",
                                              "Please select a backend to remove.")
            return

        row = selected_ranges[0].topRow()

        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Removal",
            f"Are you sure you want to remove backend at index {row} from the reader pipeline?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )

        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            if 0 <= row < len(self.db_reader.backends):
                self.db_reader.backends.pop(row)
                self.load_initial_data()

    # --- Optimierte Zeitstempel-Formatierung ---
    def format_timestamp(self, ts) -> str:
        """Konvertiert Unix-Timestamps (int/float) verlässlich in lesbare Datetimes."""
        if ts is None or ts == "" or ts == 0:
            return "N/A"
        try:
            # Falls der Timestamp als String reinkommt, versuchen wir ihn zu casten
            if isinstance(ts, str):
                ts = float(ts)

            if isinstance(ts, (int, float)):
                return  datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            return str(ts)
        except Exception:
            return str(ts)

    def on_table_selected(self):
        """Wird ausgelöst, wenn eine Tabelle im mittleren Panel ausgewählt wird."""
        selected_ranges = self.tables_table.selectedRanges()
        if not selected_ranges:
            self.data_table.setRowCount(0)
            return

        row = selected_ranges[0].topRow()
        tablename_item = self.tables_table.item(row, 0)
        tabletype_item = self.tables_table.item(row, 1)
        if not tablename_item: return

        tablename = tablename_item.text()
        tabletype = tabletype_item.text() if tabletype_item else ""
        table_info = self.current_tables_data.get(tablename, {})
        print("Table info",table_info)
        self.data_table.setRowCount(0)

        # Bedingung angepasst: Wir prüfen sowohl den Namen als auch den Typ 'raw' / 'redvypr_datapacket'
        if tabletype == "redvypr_datapacket":
            self.data_table.setRowCount(1)
            self.data_table.setItem(0, 0,
                                    QtWidgets.QTableWidgetItem("Global Packet Summary"))
            self.data_table.setItem(0, 1, QtWidgets.QTableWidgetItem(
                str(table_info.get('num_entries', 0))))
            self.data_table.setItem(0, 2, QtWidgets.QTableWidgetItem(
                self.format_timestamp(table_info.get('t_first'))))
            self.data_table.setItem(0, 3, QtWidgets.QTableWidgetItem(
                self.format_timestamp(table_info.get('t_last'))))
            self.data_table.setItem(0, 4, QtWidgets.QTableWidgetItem(
                self.format_timestamp(table_info.get('t_packet_first'))))
            self.data_table.setItem(0, 5, QtWidgets.QTableWidgetItem(
                self.format_timestamp(table_info.get('t_packet_last'))))

            # Plot item
            btn_plot = QtWidgets.QPushButton("Export to netCDF")
            btn_plot.setIcon(qtawesome.icon('fa5s.chart-bar'))
            btn_plot.clicked.connect(
                lambda checked, t=tablename:self.export_data_clicked(t))
            self.data_table.setCellWidget(0, 6, btn_plot)

        else:
            # Flat-Tabellen mit multiplen Adressen/Signalen
            addresses = table_info.get('addresses', {})
            self.data_table.setRowCount(len(addresses))
            for idx, (addr_name, addr_info) in enumerate(addresses.items()):
                self.data_table.setItem(idx, 0,
                                        QtWidgets.QTableWidgetItem(str(addr_name)))
                self.data_table.setItem(idx, 1, QtWidgets.QTableWidgetItem(
                    str(addr_info.get('num_entries', 0))))
                self.data_table.setItem(idx, 2, QtWidgets.QTableWidgetItem(
                    self.format_timestamp(addr_info.get('t_first'))))
                self.data_table.setItem(idx, 3, QtWidgets.QTableWidgetItem(
                    self.format_timestamp(addr_info.get('t_last'))))
                self.data_table.setItem(idx, 4, QtWidgets.QTableWidgetItem(
                    self.format_timestamp(addr_info.get('t_packet_first'))))
                self.data_table.setItem(idx, 5, QtWidgets.QTableWidgetItem(
                    self.format_timestamp(addr_info.get('t_packet_last'))))

                # Plot item
                btn_plot = QtWidgets.QPushButton("Plot")
                btn_plot.setIcon(qtawesome.icon('fa5s.chart-bar'))
                btn_plot.clicked.connect(
                    lambda checked, t=tablename, a=addr_name: self.plot_address_data_clicked(t,a))
                self.data_table.setCellWidget(idx, 6, btn_plot)

        self.data_table.resizeColumnsToContents()

    def plot_address_data_clicked(self,tablename, address):
        print("Plot clicked",tablename,address)
        data = self.db_reader.get_data(tablename=tablename,addresses=address)
        print("data",data)

    def export_data_clicked(self, tablename):
        print("Export clicked", tablename)
        table_data = self.current_tables_data
        self.export_widget = DbExportWidget(db_reader=self.db_reader, tablename=tablename, redvypr=self.redvypr, table_data=table_data)
        self.export_widget.show()
        #data = self.db_reader.get_data(tablename=tablename, addresses=address)
        #print("data", data)



def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    return


class Device(RedvyprDevice):
    """
    db_reader device
    """

    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)

    def thread_start(self, config=None):
        """
        Starts export devices, to save the data
        Parameters
        ----------
        config

        Returns
        -------

        """
        print("Starting thread now")
        super().thread_start(config)


class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.statistics = {}
        self._statistics_items = {}
        initial_config = self.device.custom_config

        self.db_reader = DbReader()
        self.reader_widget = DbReaderWidget(db_reader=self.db_reader, redvypr = self.device.redvypr)

        self.layout.addWidget(self.reader_widget)
        self.layout.addStretch(1)  # Push the DB widget to the top


