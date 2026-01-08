import copy
import numpy as np
import datetime
import pytz
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import qtawesome
import time
import logging
import sys
import pydantic
import typing
import redvypr
from redvypr.data_packets import check_for_command
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket
from .db_util_widgets import DBStatusDialog, TimescaleDbConfigWidget, DBConfigWidget, DBQueryDialog
from .timescaledb import RedvyprTimescaleDb, DatabaseConfig, DatabaseSettings, TimescaleConfig, SqliteConfig, RedvyprDBFactory

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db.db_reader')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = 'Reads data into a database'
    gui_tablabel_display: str = 'db reader'

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
    database: DatabaseConfig = pydantic.Field(default_factory=TimescaleConfig, discriminator='dbtype')

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


from qtpy import QtWidgets, QtCore, QtGui
from datetime import datetime


class ReplaySettingsDialog(QtWidgets.QDialog):
    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.config = current_config
        self.setWindowTitle("Replay & Filter Settings")
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
            # 1. Adresse zur Liste hinzufügen (Duplikate vermeiden)
            addr_str = item["address"]
            existing = [self.address_list.item(i).text() for i in
                        range(self.address_list.count())]
            if addr_str not in existing:
                self.address_list.addItem(addr_str)

            # 2. Collect time data
            try:
                # fromisoformat handles strings of the format "2026-01-01T16:13:38.566638+00:00"
                t_start = datetime.fromisoformat(item["tstart"])
                t_end = datetime.fromisoformat(item["tend"])

                all_starts.append(t_start)
                all_ends.append(t_end)
            except:
                continue

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
        self.device.thread_started.connect(self.thread_start_signal)
        initial_config = self.device.custom_config
        # 1. Create Settings Button
        self.settings_button = QtWidgets.QPushButton(" Replay Settings")
        self.settings_button.setIcon(qtawesome.icon('fa5s.cog'))
        self.settings_button.clicked.connect(self.open_settings)

        # 2. Create the new DBConfigWidget
        self.db_config_widget = DBConfigWidget(
            initial_config=initial_config.database)
        self.db_config_widget.db_type_changed.connect(self.update_config_from_widgets)
        self.db_config_widget.db_config_changed.connect(self.update_config_from_widgets)
        self.statustable = QtWidgets.QTableWidget()
        self.statustable.setRowCount(1)
        self._statustableheader = ['Packets','Packets read','Packets published']
        self.statustable.setColumnCount(len(self._statustableheader))
        self.statustable.setHorizontalHeaderLabels(self._statustableheader)
        item = QtWidgets.QTableWidgetItem("All")
        self.statustable.setItem(0, 0, item)
        self.statustable.resizeColumnsToContents()

        # 3. Add the DBConfigWidget to the main content area (self.layout)
        # We add it at the top of the 'self.widget' (main content area)
        self.layout.addWidget(self.db_config_widget)
        # Insert settings widget
        self.layout.addWidget(self.settings_button)
        self.layout.addWidget(self.statustable)
        self.layout.addStretch(1)  # Push the DB widget to the top

        self.statustimer_db = QtCore.QTimer()
        self.statustimer_db.timeout.connect(self.update_status)

    def update_config_from_widgets(self, config_new):
        print(f"Got new config from widgets:{config_new}")
        db_config = DatabaseSettings(config_new).root
        print(f"Got new config from widgets:{db_config}")
        self.device.custom_config.database = db_config


    def open_settings(self):
        # Always get latest config from the sub-widget (connection params)
        # combined with our internal custom_config
        current_cfg = self.device.custom_config

        dialog = ReplaySettingsDialog(current_cfg, self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_config = dialog.get_updated_config()
            self.device.custom_config = new_config
            QtWidgets.QStatusBar().showMessage("Settings updated.", 2000)


    def update_status(self):
        status = self.device.get_thread_status()
        thread_status = status['thread_running']
        # Running
        if (thread_status):
            pass
        # Not running
        else:
            #print("Thread not running anymore, stopping timer")
            self.statustimer_db.stop()

        try:
            data = self.device.statusqueue.get(block=False)
            #print(" Got status data", data)
        except:
            data = None

        if data is not None:
            try:
                item_read = QtWidgets.QTableWidgetItem(str(data['packets_read']))
                item_published = QtWidgets.QTableWidgetItem(
                    str(data['packets_published']))
                self.statistics.update(data['statistics'])
                #print("Statistics",self.statistics)
                self.statustable.setItem(0,1,item_read)
                self.statustable.setItem(0, 2, item_published)
                for row,(k, i) in enumerate(self.statistics.items()):
                    #print("k",k)
                    #print("i", i)
                    k_mod = RedvyprAddress(k).to_address_string(["i","p","h","d"])
                    try:
                        item_read = self._statistics_items[k][1]
                        item_published = self._statistics_items[k][2]
                        istr = str(i['packets_read'])
                        item_read.setText(istr)
                        istr = str(i['packets_published'])
                        item_published.setText(istr)
                    except:
                        logger.info("Could not get data",exc_info=True)
                        item_addr = QtWidgets.QTableWidgetItem(k_mod)
                        item_read = QtWidgets.QTableWidgetItem(str(i['packets_read']))
                        item_published = QtWidgets.QTableWidgetItem(
                            str(i['packets_published']))
                        self._statistics_items[k] = (item_addr,item_read,item_published)
                        nrows = self.statustable.rowCount()
                        self.statustable.setRowCount(nrows + 1)
                        self.statustable.setItem(nrows, 0, item_addr)
                        self.statustable.setItem(nrows, 1, item_read)
                        self.statustable.setItem(nrows, 2, item_published)

                    #item = self._statistics_items[k]

                self.statustable.resizeColumnsToContents()
            except:
                logger.info("Could not update data",exc_info=True)

    def thread_start_signal(self):
        print("Thread started, starting statustimer")
        self.statustimer_db.start(500)


