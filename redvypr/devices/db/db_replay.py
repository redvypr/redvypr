import datetime
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
from collections import defaultdict
logger = logging.getLogger(__name__)
from redvypr.data_packets import check_for_command
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket
from .db_engine_sqlite import SqliteConfig, DbSqlite

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db.db_replay')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = 'Replays data from redvypr style database(s)'
    gui_tablabel_display: str = 'DB Replay'

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
        self.backends = backends if backends is not None else []

    def add_backend(self, backend: typing.Any):
        """
        Add a new database instance (SQLite or TimescaleDB) to the reader pipeline.

        Parameters
        ----------
        backend : Any
            The database instance to append.
        """
        self.backends.append(backend)

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

        for backend in self.backends:
            try:
                backend_tables = backend.get_data_tables(tabletype=tabletype)
                if not backend_tables:
                    continue

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


class DbReaderWidget(QtWidgets.QWidget):
    def __init__(self, db_reader: 'DbReader', parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.db_reader = db_reader
        self.current_tables_data = {}

        self.init_ui()
        self.load_initial_data()

    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        # --- 1. Tabelle: Backends (Files) mit Buttons ---
        self.backends_group = QtWidgets.QGroupBox("Registered Backends (Files)")
        backends_layout = QtWidgets.QVBoxLayout(self.backends_group)

        # Die Tabelle selbst
        self.backends_table = QtWidgets.QTableWidget()
        self.backends_table.setColumnCount(2)
        self.backends_table.setHorizontalHeaderLabels(["Index", "Backend Object"])
        self.backends_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.backends_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.backends_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)

        # Kontextmenü für Rechtsklick aktivieren
        self.backends_table.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.backends_table.customContextMenuRequested.connect(
            self.show_backend_context_menu)

        backends_layout.addWidget(self.backends_table)

        # Button-Leiste für Backends
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_add_backend = QtWidgets.QPushButton("Add Backend...")
        self.btn_remove_backend = QtWidgets.QPushButton("Remove Selected")

        # Icons hinzufügen (Standard-System-Icons von Qt nutzen)
        # Verwendet garantiert existierende PyQt6 Standard-Symbole
        self.btn_add_backend.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_DialogOpenButton))
        self.btn_remove_backend.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_DialogDiscardButton))


        # Signale verbinden
        self.btn_add_backend.clicked.connect(self.on_add_backend_clicked)
        self.btn_remove_backend.clicked.connect(self.on_remove_backend_clicked)

        btn_layout.addWidget(self.btn_add_backend)
        btn_layout.addWidget(self.btn_remove_backend)
        backends_layout.addLayout(btn_layout)

        self.splitter.addWidget(self.backends_group)

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
        self.splitter.addWidget(self.tables_group)

        # --- 3. Tabelle: Data (Addresses & Stats) ---
        self.data_group = QtWidgets.QGroupBox("Table Data / Addresses")
        data_layout = QtWidgets.QVBoxLayout(self.data_group)
        self.data_table = QtWidgets.QTableWidget()
        self.data_table.setColumnCount(6)
        self.data_table.setHorizontalHeaderLabels([
            "Address / Context", "Entries", "First Time (t)", "Last Time (t)",
            "Packet First", "Packet Last"
        ])
        self.data_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        data_layout.addWidget(self.data_table)
        self.splitter.addWidget(self.data_group)

        self.setWindowTitle("redvypr Database Reader Explorer")
        self.resize(1200, 600)

    def load_initial_data(self):
        """Aktualisiert die Backend-Liste und lädt danach die Tabellendaten neu."""
        # 1. Backends-Tabelle füllen
        self.backends_table.setRowCount(len(self.db_reader.backends))
        for row, backend in enumerate(self.db_reader.backends):
            self.backends_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(row)))
            self.backends_table.setItem(row, 1,
                                        QtWidgets.QTableWidgetItem(str(backend)))

        # 2. Globale Tabellenstruktur abfragen
        self.refresh_tables_and_data()

    def refresh_tables_and_data(self):
        """Holt die Tabellen-Metadaten neu aus dem db_reader und aktualisiert die UI."""
        # Aktuell ausgewählte Tabelle merken, um den Fokus nach dem Refresh nicht zu verlieren
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

        # Vorherige Auswahl wiederherstellen oder Data-Tabelle leeren
        if restore_row != -1:
            self.tables_table.selectRow(restore_row)
        else:
            self.data_table.setRowCount(0)

    # --- Backend-Aktionen (Buttons & Menüs) ---

    def show_backend_context_menu(self, pos: QtCore.QPoint):
        """Erzeugt das Rechtsklick-Kontextmenü für die Backend-Tabelle."""
        item = self.backends_table.itemAt(pos)
        menu = QtWidgets.QMenu(self)

        # Aktion: Hinzufügen (immer verfügbar)
        add_action = menu.addAction("Add New Backend...")
        add_action.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_DialogOpenButton))
        add_action.triggered.connect(self.on_add_backend_clicked)

        # Aktion: Entfernen (nur wenn auf eine gültige Zeile geklickt wurde)
        if item is not None:
            menu.addSeparator()
            remove_action = menu.addAction("Remove Selected Backend")
            remove_action.setIcon(self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_DialogDiscardButton))
            remove_action.triggered.connect(self.on_remove_backend_clicked)

        menu.exec(self.backends_table.mapToGlobal(pos))

    def on_add_backend_clicked(self):
        """Wird aufgerufen, wenn ein neues Backend hinzugefügt werden soll."""
        # Z.B. ein QFileDialog für SQLite-Dateien:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select SQLite Database Backend", "",
            "Database Files (*.db *.sql *.sqlite *.sqlite3);;All Files (*)"
        )

        if file_path:
            try:
                c = SqliteConfig(filepath=file_path)
                db_sql_reader = DbSqlite(c, mode='read')
                self.db_reader.add_backend(db_sql_reader)

                # GUI aktualisieren
                self.load_initial_data()

            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error",
                                               f"Could not add backend:\n{e}")

    def on_remove_backend_clicked(self):
        """Entfernt das ausgewählte Backend aus dem db_reader Pipeline."""
        selected_ranges = self.backends_table.selectedRanges()
        if not selected_ranges:
            QtWidgets.QMessageBox.information(self, "No Selection",
                                              "Please select a backend to remove.")
            return

        row = selected_ranges[0].topRow()

        # Sicherheitsabfrage
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Removal",
            f"Are you sure you want to remove backend at index {row} from the reader pipeline?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )

        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            # Aus der Liste im DbReader löschen
            if 0 <= row < len(self.db_reader.backends):
                self.db_reader.backends.pop(row)

                # GUI komplett neu laden (Backends und gemergte Tabellen-Stats)
                self.load_initial_data()

    # --- Daten-Visualisierungs-Methoden (unverändert) ---

    def format_timestamp(self, ts) -> str:
        if ts is None: return "None"
        try:
            if isinstance(ts, (int, float)):
                return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            return str(ts)
        except Exception:
            return str(ts)

    def on_table_selected(self):
        selected_ranges = self.tables_table.selectedRanges()
        if not selected_ranges:
            self.data_table.setRowCount(0)
            return

        row = selected_ranges[0].topRow()
        tablename_item = self.tables_table.item(row, 0)
        if not tablename_item: return

        tablename = tablename_item.text()
        table_info = self.current_tables_data.get(tablename, {})

        self.data_table.setRowCount(0)

        if tablename == "redvypr_datapacket":
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
        else:
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

        self.data_table.resizeColumnsToContents()




def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger_thread = logging.getLogger('redvypr.device.db_reader.start')
    logger_thread.setLevel(logging.DEBUG)
    logger_thread.debug(funcname)
    dt_update = 1  # Update interval in seconds
    packets_read = 0
    packets_published = 0
    t_update = time.time() - dt_update
    print("Config",config)
    print("device_info", device_info)

    device_config = DeviceCustomConfig(**config)
    dbconfig = device_config.database
    logger_thread.info("Opening database")
    # Get the filters from the redvypr addresses
    packet_filters = None
    packet_time_range = None
    if len(device_config.packet_filter):
        packet_filters = []
        filter_keys = ["host","device","packetid","uuid"]
        for addr in device_config.packet_filter:
            filter_dict = {}
            for filter_key in filter_keys:
                if getattr(addr,filter_key):
                    print("Setting filter")
                    filter_dict[filter_key] = getattr(addr,filter_key)

            if len(filter_dict.keys()):
                packet_filters.append(filter_dict)

        packet_time_range = {
            "tstart": device_config.tstart,
            "tend": device_config.tend
        }

    print(f"Packet filters:{packet_filters}")
    print(f"Packet time range:{packet_time_range}")
    try:
        db = RedvyprDBFactory.create(dbconfig)
        #db = RedvyprTimescaleDb(dbname = dbconfig.dbname,
        #                        user= dbconfig.user,
        #                        password=dbconfig.password,
        #                        host=dbconfig.host,
        #                        port=dbconfig.port)

        with db:
            # 1. Setup (gentle approach)
            db.identify_and_setup()
            status = db.check_health()

            print(f"--- Database Health Check ---")
            print(f"Engine:  {status['engine']} (Timescale: {status['is_timescale']})")
            print(f"Tables:  {'✅ Found' if status['tables_exist'] else '❌ Missing'}")
            print(f"Write:   {'✅ Permitted' if status['can_write'] else '❌ Denied'}")
            print(f"-----------------------------")



            if device_config.read_metadata:
                logger_thread.info("Reading db-metadata")
                # Read metadata first
                metainfo = db.get_metadata_info()
                count_all = 0
                for m in metainfo:
                    count_all += m['count']

                print("Metadata stat",metainfo)
                print("Count all", count_all)
                metadata = db.get_metadata(0,count_all)
                print("Metadata",metadata)
                metadata_packet = redvypr.data_packets.create_datadict(device='db_reader',
                                                            packetid='metadata')
                if len(metadata) > 0:
                    for m in metadata:
                        print("2", m['metadata'])
                        print("1",m['address'])
                        redvypr.data_packets.add_metadata2datapacket(metadata_packet,
                                                                     address=m['address'],
                                                                     metadict=m['metadata'])
                    dataqueue.put(metadata_packet)
                else:
                    logger_thread.info("No metadata found")

            db_info = db.get_database_info()
            if db_info is None:
                logger.info("No valid data information returned from database, exiting")
                return
            statistics = {}
            packets_read_buffer = []
            print(f"Number of total measurements in db:{db_info["measurement_count"]}")
            if packet_filters is None:
                ntotal = db_info["measurement_count"]
            else:
                ntotal = db.get_packet_count(filters=packet_filters,
                                                     time_range=packet_time_range)

            print(f"Number of measurements (with filter):{ntotal}")
            nchunk = device_config.size_packetbuffer
            ind_read = 0
            t_packet_old = 0  # Time of the last sent packet
            t_packet = 0  # Time of the last sent packet
            t_thread_sent = 0  # Time of the last sent packet
            t_thread_now = 0  # Time of the last sent packet
            data_send = None

            while True:
                try:
                    datapacket = datainqueue.get(block=False)
                except:
                    datapacket = None
                    time.sleep(0.5)
                # print("Got data",datapacket)
                if datapacket is not None:
                    [command, comdata] = check_for_command(datapacket,
                                                           thread_uuid=device_info[
                                                               'thread_uuid'],
                                                           add_data=True)
                    if command is not None:
                        paddr = RedvyprAddress(datapacket)
                        packetid = paddr.packetid
                        publisher = paddr.publisher
                        device = paddr.device
                        logger.debug(
                            'Command is for me: {:s}. Packetid: {}, device: {}, publisher: {}'.format(
                                str(command), packetid, device, publisher))
                        if command == 'stop':
                            logger.info(funcname + 'received command:' + str(
                                datapacket) + ' stopping now')
                            logger.debug('Stop command')
                            return
                        elif command == 'info' and packetid == 'metadata':
                            print("Info command", datapacket.keys())
                else:
                    # Check if we have to fill the packetbuffer again
                    if len(packets_read_buffer) < int(nchunk / 10):
                        print("Reading packets")
                        if (ind_read + nchunk) < ntotal:
                            nread = nchunk
                        elif ind_read < (ntotal - 1):
                            nread = ntotal - ind_read
                        else:
                            print("All read")
                            return

                        print("Reading #{} packets from {}".format(nread, ind_read))
                        if packet_filters is None:
                            data = db.get_packets_range(ind_read, nread)
                        else:
                            data = db.get_packets_range(
                                start_index=ind_read,
                                count=nread,
                                filters=packet_filters,
                                time_range=packet_time_range
                            )
                        packets_read += len(data)
                        ind_read += nread
                        packets_read_buffer.extend(data)

                    if len(packets_read_buffer) > 1:
                        # t_packet_old = 0  # Time of the last sent packet
                        # t_packet = 0  # Time of the last sent packet
                        # t_thread_sent = 0  # Time of the last sent packet
                        # t_thread_now = 0  # Time of the last sent packet
                        if data_send is None:
                            data_send = packets_read_buffer.pop(0)
                            # print("Data send",data_send)
                            id_send = data_send["id"]
                            t_packet = data_send["timestamp"]
                            t_packet_unix = t_packet.timestamp()
                            packet_send = data_send["data"]

                        t_thread_now = time.time()
                        dt_packet = t_packet_unix - t_packet_old
                        dt_thread = t_thread_now - t_thread_sent
                        # print("dt", dt_packet, dt_thread)
                        if dt_thread >= dt_packet:
                            #print("Sending", id_send, t_packet)
                            packets_published += 1
                            t_thread_sent = t_thread_now
                            t_packet_old = t_packet_unix
                            dataqueue.put(packet_send)
                            data_send = None
                            # Update statistics
                            raddr_packet = RedvyprAddress(packet_send).to_address_string()
                            try:
                                statistics[raddr_packet]
                            except:
                                statistics[raddr_packet] = {'packets_read':0, 'packets_published':0}

                            statistics[raddr_packet]['packets_read'] += 1
                            statistics[raddr_packet]['packets_published'] += 1
                            #print(f"statistics:{statistics}")

                if ((time.time() - t_update) > dt_update):
                    t_update = time.time()
                    print("Updating", packets_read, packets_published)
                    data = {}
                    data['t'] = time.time()
                    data['packets_read'] = packets_read
                    data['packets_published'] = packets_published
                    data['statistics'] = statistics
                    statusqueue.put(data)
    except:
        logger_thread.exception("Could not connect to database")
        return
    finally:
        logger_thread.info("Thread shutting down, connection cleaned up.")

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


class ReplaySettingsDialog(QtWidgets.QDialog):
    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.config = current_config
        self.setWindowTitle("Replay/Export & Filter Settings")
        self.setMinimumWidth(500)
        self.setup_ui()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        self.browse_db_btn = QtWidgets.QPushButton(" Choose Datastreams/Times from DB")
        icon = qtawesome.icon('mdi6.database-search-outline')
        self.browse_db_btn.setIcon(icon)
        #self.browse_db_btn.setMinimumHeight(40)
        #self.browse_db_btn.setStyleSheet("background-color: #ebf8ff; font-weight: bold; border: 1px solid #bee3f8;")
        self.browse_db_btn.clicked.connect(self.on_browse_db)
        layout.addWidget(self.browse_db_btn)
        # --- 1. Address Filter List ---
        self.filter_group = QtWidgets.QGroupBox("Packet Filter (Addresses)")
        self.filter_group.setCheckable(True)  # Adds checkbox to title
        self.filter_group.setChecked(len(self.config.packet_filter) > 0)
        filter_layout = QtWidgets.QVBoxLayout(self.filter_group)

        self.address_list = QtWidgets.QListWidget()
        for addr in self.config.packet_filter:
            self.address_list.addItem(addr.to_address_string())

        btn_layout = QtWidgets.QHBoxLayout()
        self.add_addr_btn = QtWidgets.QPushButton("Add Address")
        self.remove_addr_btn = QtWidgets.QPushButton("Remove Selected")
        btn_layout.addWidget(self.add_addr_btn)
        btn_layout.addWidget(self.remove_addr_btn)

        filter_layout.addWidget(self.address_list)
        filter_layout.addLayout(btn_layout)
        layout.addWidget(self.filter_group)

        # --- 2. Time Range ---
        self.time_group = QtWidgets.QGroupBox("Time Range (Optional)")
        self.time_group.setCheckable(True)
        self.time_group.setChecked(False)
        time_layout = QtWidgets.QFormLayout(self.time_group)

        datetime_format = "yyyy-MM-dd HH:mm:ss"
        self.tstart_edit = QtWidgets.QDateTimeEdit(calendarPopup=True)
        self.tstart_edit.setDisplayFormat(datetime_format)
        self.tstart_edit.setDateTime(
            self.config.tstart if self.config.tstart else QtCore.QDateTime.currentDateTime().addDays(
                -1))

        self.tend_edit = QtWidgets.QDateTimeEdit(calendarPopup=True)
        self.tend_edit.setDisplayFormat(datetime_format)
        self.tend_edit.setDateTime(
            self.config.tend if self.config.tend else QtCore.QDateTime.currentDateTime())

        time_layout.addRow("Start Time:", self.tstart_edit)
        time_layout.addRow("End Time:", self.tend_edit)
        layout.addWidget(self.time_group)

        # --- 3. Mode & Speed ---
        mode_group = QtWidgets.QGroupBox("Replay Mode")
        mode_layout = QtWidgets.QFormLayout(mode_group)

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["realtime", "constant"])
        self.mode_combo.setCurrentText(self.config.replay_mode)

        self.speedup_spin = QtWidgets.QDoubleSpinBox()
        self.speedup_spin.setRange(0.1, 100.0)
        self.speedup_spin.setValue(self.config.speedup)

        self.dt_spin = QtWidgets.QDoubleSpinBox()
        self.dt_spin.setRange(0.001, 10.0)
        self.dt_spin.setSingleStep(0.1)
        self.dt_spin.setValue(self.config.constant_dt)

        mode_layout.addRow("Mode:", self.mode_combo)
        mode_layout.addRow("Speedup (Realtime):", self.speedup_spin)
        mode_layout.addRow("Constant Interval (s):", self.dt_spin)
        layout.addWidget(mode_group)

        # --- Buttons ---
        self.add_addr_btn.clicked.connect(self.add_address)
        self.remove_addr_btn.clicked.connect(self.remove_address)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def on_browse_db(self):
        """Opens the DB Inventory and imports selection."""
        dbconfig = self.config.database
        try:
            self.db = RedvyprDBFactory.create(dbconfig)
            #self.db = RedvyprTimescaleDb(dbname=dbconfig.dbname,
            #                        user=dbconfig.user,
            #                        password=dbconfig.password,
            #                        host=dbconfig.host,
            #                        port=dbconfig.port)

            with self.db:
                # 1. Setup (gentle approach)
                self.db.identify_and_setup()
                status = self.db.check_health()

                self.browser = DBQueryDialog(self.db, parent=self, select_mode=True)
                self.browser.items_chosen.connect(self.handle_incoming_items)
                self.browser.show()

        except Exception as e:
            print(f"Could not open databse: {e}")

    def handle_incoming_items(self, items_list: list):
        """Slot für das Signal 'items_chosen(list)'."""
        if not items_list:
            return

        all_starts = []
        all_ends = []
        fmt = "%Y-%m-%d %H:%M:%S"

        for item in items_list:
            #print("Processing item",item)
            metadata = item["metadata"]
            if metadata is None:
                print("Got a standard address")
                # 1. Adresse zur Liste hinzufügen (Duplikate vermeiden)
                addr_str = item["address"]
                existing = [self.address_list.item(i).text() for i in
                            range(self.address_list.count())]
                if addr_str not in existing:
                    self.address_list.addItem(addr_str)

                # 2. Collect time data
                try:
                    # fromisoformat handles strings of the format "2026-01-01T16:13:38.566638+00:00"
                    t_start = datetime.datetime.fromisoformat(item["tstart"])
                    t_end = datetime.datetime.fromisoformat(item["tend"])

                    all_starts.append(t_start)
                    all_ends.append(t_end)
                except:
                    continue
            else:
                print("Got a metadata entry")
                for m in metadata:
                    print(f"Metadata:{m}")
                    m_work = m["metadata"]
                    d_streams = m_work["datastreams"]
                    # Adding datastreams
                    for d_addr,d_meta in d_streams.items():
                        addr_str = d_addr
                        existing = [self.address_list.item(i).text() for i in
                                    range(self.address_list.count())]
                        if addr_str not in existing:
                            self.address_list.addItem(addr_str)
                    t_start = m_work["tstart"]
                    t_end = m_work["tend"]
                    if t_start:
                        all_starts.append(t_start)
                    if t_end:
                        all_ends.append(t_end)
                    meas_name = m_work["name"]
                    print(f"datastreams:{d_streams.keys()}")
                    print(f"t_start:{t_start}")
                    print(f"t_end:{t_end}")
                    print(f"name:{meas_name}")
                    #for ds,ds_key in m["datastreams"].items:
                    #    print("Datastream:{ds}")

        # 3. Optional: Zeit-Editor auf das Gesamt-Intervall aller gewählten Items setzen
        if all_starts and all_ends:
            #print("All starts",all_starts)
            #print("All ends", all_ends)
            min_start = min(all_starts)
            max_end = max(all_ends)

            self.tstart_edit.setDateTime(QtCore.QDateTime(min_start))
            self.tend_edit.setDateTime(QtCore.QDateTime(max_end))

    def add_address(self):
        text, ok = QtWidgets.QInputDialog.getText(self, "Add Address",
                                                  "Redvypr Address:")
        if ok and text:
            self.address_list.addItem(text)

    def remove_address(self):
        for item in self.address_list.selectedItems():
            self.address_list.takeItem(self.address_list.row(item))

    def get_updated_config(self):
        # Update the pydantic model with data from UI
        # 1. Handle Addresses
        if self.filter_group.isChecked():
            self.config.packet_filter = [
                RedvyprAddress(self.address_list.item(i).text())
                for i in range(self.address_list.count())
            ]
        else:
            # If disabled, maybe default to "all"
            self.config.packet_filter = []

        # 2. Handle Time Range
        if self.time_group.isChecked():
            self.config.tstart = self.tstart_edit.dateTime().toPyDateTime()
            self.config.tend = self.tend_edit.dateTime().toPyDateTime()
        else:
            # If disabled, set to None so the DB query doesn't use a WHERE clause for time
            self.config.tstart = None
            self.config.tend = None

        # 3. Handle Replay Params
        self.config.replay_mode = self.mode_combo.currentText()
        self.config.speedup = self.speedup_spin.value()
        self.config.constant_dt = self.dt_spin.value()

        return self.config



class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.statistics = {}
        self._statistics_items = {}
        initial_config = self.device.custom_config

        self.db_reader = DbReader()
        self.reader_widget = DbReaderWidget(db_reader=self.db_reader)

        self.layout.addWidget(self.reader_widget)
        self.layout.addStretch(1)  # Push the DB widget to the top


