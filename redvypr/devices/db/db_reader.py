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
from .db_writer import TimescaleDbConfigWidget
from .timescaledb import RedvyprTimescaleDb, DatabaseConfig, TimescaleConfig, SqliteConfig

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
    size_packetbuffer: int = 10
    packet_filter: typing.List[RedvyprAddress] = pydantic.Field(default=[RedvyprAddress("@")])
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
    try:
        db = RedvyprTimescaleDb(dbname = dbconfig.dbname,
                                user= dbconfig.user,
                                password=dbconfig.password,
                                host=dbconfig.host,
                                port=dbconfig.port)

        with db:
            # 1. Setup (gentle approach)
            db.identify_and_setup()
            status = db.check_health()

            print(f"--- Database Health Check ---")
            print(f"Engine:  {status['engine']} (Timescale: {status['is_timescale']})")
            print(f"Tables:  {'✅ Found' if status['tables_exist'] else '❌ Missing'}")
            print(f"Write:   {'✅ Permitted' if status['can_write'] else '❌ Denied'}")
            print(f"-----------------------------")

            db_info = db.get_database_info()
            statistics = {}
            packets_read_buffer = []
            print("Number of measurements", db_info["measurement_count"])
            ntotal = db_info["measurement_count"]
            nchunk = 100
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
                        data = db.get_packets_range(ind_read, nread)
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
                            print("Sending", id_send, t_packet)
                            packets_published += 1
                            t_thread_sent = t_thread_now
                            t_packet_old = t_packet_unix
                            dataqueue.put(packet_send)
                            data_send = None

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

        # --- 1. Address Filter List ---
        filter_group = QtWidgets.QGroupBox("Packet Filter (Addresses)")
        filter_layout = QtWidgets.QVBoxLayout(filter_group)

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
        layout.addWidget(filter_group)

        # --- 2. Time Range ---
        time_group = QtWidgets.QGroupBox("Time Range (Optional)")
        time_layout = QtWidgets.QFormLayout(time_group)

        self.tstart_edit = QtWidgets.QDateTimeEdit(calendarPopup=True)
        self.tstart_edit.setDateTime(
            self.config.tstart if self.config.tstart else QtCore.QDateTime.currentDateTime().addDays(
                -1))

        self.tend_edit = QtWidgets.QDateTimeEdit(calendarPopup=True)
        self.tend_edit.setDateTime(
            self.config.tend if self.config.tend else QtCore.QDateTime.currentDateTime())

        time_layout.addRow("Start Time:", self.tstart_edit)
        time_layout.addRow("End Time:", self.tend_edit)
        layout.addWidget(time_group)

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
        self.config.packet_filter = [RedvyprAddress(self.address_list.item(i).text())
                                     for i in range(self.address_list.count())]
        self.config.tstart = self.tstart_edit.dateTime().toPyDateTime()
        self.config.tend = self.tend_edit.dateTime().toPyDateTime()
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
        # 1. Create Settings Button
        self.settings_button = QtWidgets.QPushButton(" Replay Settings")
        self.settings_button.setIcon(qtawesome.icon('fa5s.cog'))
        self.settings_button.clicked.connect(self.open_settings)

        # 2. Create the new DBConfigWidget
        self.db_config_widget = TimescaleDbConfigWidget(initial_config=initial_config.database)
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
            print(" Got status data", data)
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

    # This is bad style, needs to be changed to thread_started signal and continous update of configuration
    def start_clicked(self):
        # Ensure we sync the connection params (host, user, etc.) from the sub-widget
        # before starting the thread
        db_params = self.db_config_widget.get_config()
        current_cfg = self.device.custom_config

        # Merge them
        current_cfg.database.host = db_params.host
        current_cfg.database.user = db_params.user
        current_cfg.database.password = db_params.password
        current_cfg.database.dbname = db_params.dbname
        current_cfg.database.port = db_params.port

        self.device.custom_config = current_cfg

        self.statustimer_db.start(500)
        super().start_clicked()

