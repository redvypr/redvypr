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
from typing import List, Dict, Any
import redvypr
from redvypr.data_packets import check_for_command
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket
from .timescaledb import RedvyprTimescaleDb

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db.db_writer')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = 'Writes data into a database'
    gui_tablabel_display: str = 'database status'

class DeviceCustomConfig(pydantic.BaseModel):
    size_packetbuffer: int = 10
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress("data"))
    dbname: str = pydantic.Field(default="postgres")
    user: str = pydantic.Field(default="postgres")
    password: str = pydantic.Field(default="password")
    host: str = pydantic.Field(default="pi5server1")
    port: int = pydantic.Field(default=5433)

def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger_thread = logging.getLogger('redvypr.device.db_writer.start')
    logger_thread.setLevel(logging.DEBUG)
    logger_thread.debug(funcname)
    dt_update = 1  # Update interval in seconds
    packet_inserted = 0
    packet_inserted_failure = 0
    t_update = time.time() - dt_update
    print("Config",config)
    print("device_info", device_info)

    pconfig = DeviceCustomConfig(**config)
    logger_thread.info("Opening database")
    try:
        db = RedvyprTimescaleDb(dbname = pconfig.dbname,
                                user= pconfig.user,
                                password=pconfig.password,
                                host=pconfig.host,
                                port=pconfig.port)

        with db:
            print("Opened")
            # 1. Setup (gentle approach)
            db.identify_and_setup()
            status = db.check_health()

            print(f"--- Database Health Check ---")
            print(f"Engine:  {status['engine']} (Timescale: {status['is_timescale']})")
            print(f"Tables:  {'✅ Found' if status['tables_exist'] else '❌ Missing'}")
            print(f"Write:   {'✅ Permitted' if status['can_write'] else '❌ Denied'}")
            print(f"-----------------------------")
            db_info = db.get_database_info()
            if status['tables_exist'] and status['can_write']:
                statistics = {}
                while True:
                    datapacket = datainqueue.get()
                    # print("Got data",datapacket)
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
                            metadata = datapacket["deviceinfo_all"]["metadata"]
                            print("Metadata", metadata)
                            # add_metadata(self, address: str, uuid: str, metadata_dict: dict,mode: str = "merge"):
                            for metadata_address_str, metadata_content in metadata.items():
                                print("Adding metadata", metadata_address_str)
                                metadata_address = RedvyprAddress(metadata_address_str)
                                try:
                                    uuid = metadata_address.uuid
                                except:
                                    print(
                                        "Could not get uuid from metadata, get from host")
                                    uuid = device_info["hostinfo"]["uuid"]

                                try:
                                    db.add_metadata(address=metadata_address_str, uuid=uuid,
                                                    metadata_dict=metadata_content)
                                except:
                                    logger_thread.info("Could not add metadata",exc_info=True)

                    else:  # Only save real data
                        # print('Inserting datapacket',datapacket)
                        addrstr = RedvyprAddress(datapacket).to_address_string()
                        try:
                            statistics[addrstr]
                        except:
                            statistics[addrstr] = {'packet_inserted': 0,
                                                   'packet_inserted_failure': 0}
                        try:
                            db.insert_packet(datapacket)
                            packet_inserted += 1
                            statistics[addrstr]['packet_inserted'] += 1
                        except:
                            logger_thread.info("Could not add data",exc_info=True)
                            packet_inserted_failure += 1
                            statistics[addrstr]['packet_inserted_failure'] += 1

                    if ((time.time() - t_update) > dt_update):
                        t_update = time.time()
                        # print("Updating")
                        data = {}
                        data['t'] = time.time()
                        data['packet_inserted'] = packet_inserted
                        data['packet_inserted_failure'] = packet_inserted_failure
                        data['statistics'] = statistics
                        statusqueue.put(data)

    except:
        logger_thread.exception("Could not connect to database")
        return





def get_database_info(config):
    db = RedvyprTimescaleDb(dbname=config.dbname,
                            user=config.user,
                            password=config.password,
                            host=config.host,
                            port=config.port)

    print("Opening with config",config)
    with db:
        print("Opened")
        # 1. Setup (gentle approach)
        db.identify_and_setup()
        status = db.check_health()

        print(f"--- Database Health Check ---")
        print(f"Engine:  {status['engine']} (Timescale: {status['is_timescale']})")
        print(f"Tables:  {'✅ Found' if status['tables_exist'] else '❌ Missing'}")
        print(f"Write:   {'✅ Permitted' if status['can_write'] else '❌ Denied'}")
        print(f"-----------------------------")

        stats = db.get_unique_combination_stats(keys=['uuid'])
        print("Stats",stats)

        info = db.get_database_info()
        return info


class DBQueryDialog(QtWidgets.QDialog):
    """
    Dialog to browse both Packet and Metadata inventory using Tabs.
    """

    def __init__(self, db_instance, parent=None):
        super().__init__(parent)
        self.db = db_instance
        self.setWindowTitle("Database Inventory Browser")
        self.resize(1100, 700)

        self.setup_ui()
        self.refresh_data()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # --- Header with Refresh ---
        header = QtWidgets.QHBoxLayout()
        header.addWidget(QtWidgets.QLabel("Database Inventory Overview"))
        header.addStretch()

        self.refresh_button = QtWidgets.QPushButton(" Refresh All")
        self.refresh_button.setIcon(qtawesome.icon('fa5s.sync-alt'))
        self.refresh_button.clicked.connect(self.refresh_data)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        # --- Tabs ---
        self.tabs = QtWidgets.QTabWidget()

        # Tab 1: Packets
        self.packet_table = self._create_table_widget()
        self.tabs.addTab(self.packet_table, qtawesome.icon('fa5s.box'), "Packets")

        # Tab 2: Metadata
        self.meta_table = self._create_table_widget()
        self.tabs.addTab(self.meta_table, qtawesome.icon('fa5s.info-circle'),
                         "Metadata")

        layout.addWidget(self.tabs)

        # --- Footer ---
        footer = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Ready")
        footer.addWidget(self.status_label)
        footer.addStretch()

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    def _create_table_widget(self) -> QtWidgets.QTableWidget:
        """Helper to create a standardized table."""
        table = QtWidgets.QTableWidget()
        headers = ["Address", "Packet ID / UUID", "Device", "Host", "Count",
                   "First Seen", "Last Seen"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        return table

    def refresh_data(self):
        """Fetches data for both tables."""
        self.status_label.setText("Fetching data...")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)

        try:
            with self.db as connected_db:
                # 1. Fetch Packet Stats
                packet_stats = connected_db.get_unique_combination_stats(
                    keys=["redvypr_address", "packetid", "device", "host"]
                )

                # 2. Fetch Metadata Stats (using the new info method)
                # We use uuid instead of packetid here for the second column
                meta_stats = connected_db.get_metadata_info(
                    keys=["redvypr_address", "uuid", "device", "host"]
                )

            self._fill_table(self.packet_table, packet_stats, "packetid")
            self._fill_table(self.meta_table, meta_stats, "uuid")

            self.status_label.setText(
                f"Updated: {len(packet_stats)} packet streams, {len(meta_stats)} metadata entries.")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Fetch failed: {e}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _fill_table(self, table: QtWidgets.QTableWidget, stats: list, id_key: str):
        """Generic logic to fill a table with stats."""
        table.setRowCount(0)
        table.setRowCount(len(stats))

        for row_idx, entry in enumerate(stats):
            # We map the dictionary keys to the columns
            items = [
                entry.get('redvypr_address', '-'),
                entry.get(id_key, '-'),  # Either packetid or uuid
                entry.get('device', '-'),
                entry.get('host', '-'),
                str(entry.get('count', 0)),
                entry.get('first_seen', 'N/A'),
                entry.get('last_seen', 'N/A')
            ]

            for col_idx, text in enumerate(items):
                item = QtWidgets.QTableWidgetItem(text)
                if col_idx == 4:  # Count column right-aligned
                    item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                table.setItem(row_idx, col_idx, item)

        #table.resizeColumnsToContents()
        #table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        # 1. Disable the forced stretch on the header to allow horizontal overflow
        header = table.horizontalHeader()
        header.setStretchLastSection(False)

        # 2. Initially resize columns to fit the data we just loaded
        table.resizeColumnsToContents()

        # 2. CAP the first column (Address) if it exceeds a reasonable limit
        # Adjust 300 to your preferred maximum width in pixels
        if table.columnWidth(0) > 300:
            table.setColumnWidth(0, 300)

        # 3. Set all columns to 'Interactive' so the user can resize them manually
        for i in range(table.columnCount()):
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.Interactive)

        # 4. Ensure the horizontal scrollbar is enabled
        table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        # Optional: Add a bit of padding to the columns for better readability
        for i in range(table.columnCount()):
            current_width = table.columnWidth(i)
            table.setColumnWidth(i, current_width + 20)


class DBConfigWidget(QtWidgets.QWidget):
    """
    A dedicated widget for configuring and testing
    database connection settings based on a Pydantic model.
    """

    def __init__(self, initial_config: DeviceCustomConfig, parent=None):
        super().__init__(parent)
        self.initial_config = initial_config
        self.input_fields: typing.Dict[str, QtWidgets.QLineEdit] = {}
        self.test_result_label: QtWidgets.QLabel = None
        self.setup_ui()

    def setup_ui(self):
        """Creates a form layout for the DB fields and adds the Test button/label."""

        # Main layout for the entire widget (Vertical arrangement)
        main_layout = QtWidgets.QVBoxLayout(self)

        # 1. Form for input fields
        form_layout = QtWidgets.QFormLayout()
        form_layout.setLabelAlignment(QtCore.Qt.AlignLeft)

        db_fields = ['dbname', 'user', 'password', 'host', 'port']

        for field_name in db_fields:
            field_value = getattr(self.initial_config, field_name)
            line_edit = QtWidgets.QLineEdit(str(field_value))

            if field_name == 'password':
                # --- NEW: Password field with toggle button ---
                line_edit.setEchoMode(QtWidgets.QLineEdit.Password)

                # Container for password field and button
                password_container = QtWidgets.QWidget()
                h_layout = QtWidgets.QHBoxLayout(password_container)
                h_layout.setContentsMargins(0, 0, 0, 0)
                h_layout.addWidget(line_edit)

                show_button = QtWidgets.QPushButton("Show")
                show_button.setCheckable(True)
                show_button.setToolTip("Toggle password visibility")
                # Connect the button's checked state to the toggle function
                show_button.clicked.connect(
                    lambda checked, le=line_edit: self.toggle_password_visibility(le,
                                                                                  checked))
                h_layout.addWidget(show_button)

                self.input_fields[field_name] = line_edit
                form_layout.addRow(f"{field_name.capitalize()}:", password_container)

            elif field_name == 'port':
                # Use QIntValidator from QtGui
                line_edit.setValidator(QtGui.QIntValidator(1, 65535, self))
                self.input_fields[field_name] = line_edit
                form_layout.addRow(f"{field_name.capitalize()}:", line_edit)
            else:
                self.input_fields[field_name] = line_edit
                form_layout.addRow(f"{field_name.capitalize()}:", line_edit)

        main_layout.addLayout(form_layout)

        # 2. Test/Query Buttons
        self.test_button = QtWidgets.QPushButton("Test DB Connection")
        # Placeholder icon from qtawesome stub
        icon = qtawesome.icon('mdi6.database-outline')
        self.test_button.setIcon(icon)
        self.query_button = QtWidgets.QPushButton("Query DB")
        icon = qtawesome.icon('mdi6.database-search-outline')
        self.query_button.setIcon(icon)
        self.button_layout = QtWidgets.QHBoxLayout()
        self.button_layout.addWidget(self.test_button)
        self.button_layout.addWidget(self.query_button)

        self.test_button.clicked.connect(self.test_connection_clicked)
        self.query_button.clicked.connect(self.query_db_clicked)
        main_layout.addLayout(self.button_layout)

        # 3. Result Label
        self.test_result_label = QtWidgets.QLabel("Ready to test DB connection.")
        self.test_result_label.setAlignment(QtCore.Qt.AlignCenter)
        self.test_result_label.setStyleSheet(
            "color: #4A5568; padding: 8px; border: 1px solid #E2E8F0; border-radius: 6px; background-color: #F7FAFC;")
        main_layout.addWidget(self.test_result_label)

    def toggle_password_visibility(self, line_edit: QtWidgets.QLineEdit, checked: bool):
        """Toggles the echo mode of the password field based on the button state."""
        if checked:
            line_edit.setEchoMode(QtWidgets.QLineEdit.Normal)
        else:
            line_edit.setEchoMode(QtWidgets.QLineEdit.Password)

    def get_config(self) -> DeviceCustomConfig:
        """
        Retrieves current values from QLineEdits and creates a new
        DeviceCustomConfig instance, ensuring proper type conversion.
        """

        # 1. Start with base configuration data (incl. default values for unexposed fields)
        config_data = self.initial_config.model_dump()

        # 2. Overwrite exposed DB fields with current UI values
        for field_name, line_edit in self.input_fields.items():
            value = line_edit.text()

            # Type conversion back to Pydantic model
            if field_name == 'port':
                try:
                    config_data[field_name] = int(value)
                except ValueError:
                    # Fallback to default value on invalid input
                    config_data[field_name] = self.initial_config.port
            else:
                config_data[field_name] = value

        # 3. Create and validate the new Pydantic instance
        try:
            return DeviceCustomConfig(**config_data)
        except pydantic.ValidationError as e:
            print(f"Configuration Validation Error: {e}")
            return self.initial_config

    def query_db_clicked(self):
        config = self.get_config()
        db = RedvyprTimescaleDb(dbname=config.dbname,
                                user=config.user,
                                password=config.password,
                                host=config.host,
                                port=config.port)

        self.query_widdget = DBQueryDialog(db_instance=db)
        self.query_widdget.show()

    def test_connection_clicked(self):
        """Tests the current configuration against a simulated database connection and displays results."""

        # Set status to 'testing'
        self.test_result_label.setText("Testing Connection...")
        self.test_result_label.setStyleSheet(
            "color: #D69E2E; font-weight: bold; background-color: #FEFCBF; border: 1px solid #D69E2E; border-radius: 6px;")

        # 1. Retrieve current configuration
        current_config = self.get_config()
        try:
            # 2. Simulate connection test
            result = get_database_info(current_config)
        except Exception as e:
            info = f"CONNECTION FAILED: {e}"
            style = "color: #C53030; font-weight: bold; background-color: #FEB2B2; border: 1px solid #C53030; border-radius: 6px;"
            self.test_result_label.setText(info)
            self.test_result_label.setStyleSheet(style)
            return


        # 3. Update UI
        if result:
            info = f"CONNECTION SUCCESSFUL! {result}"
            style = "color: #2F855A; font-weight: bold; background-color: #9AE6B4; border: 1px solid #2F855A; border-radius: 6px;"
        else:
            info = f"CONNECTION FAILED"
            style = "color: #C53030; font-weight: bold; background-color: #FEB2B2; border: 1px solid #C53030; border-radius: 6px;"

        self.test_result_label.setText(info)
        self.test_result_label.setStyleSheet(style)


class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.statistics = {}
        self._statistics_items = {}
        initial_config = self.device.custom_config
        # 2. Create the new DBConfigWidget
        self.db_config_widget = DBConfigWidget(initial_config=initial_config)
        self.statustable = QtWidgets.QTableWidget()
        self.statustable.setRowCount(1)
        self._statustableheader = ['Packets','Num stored','Num stored error']
        self.statustable.setColumnCount(len(self._statustableheader))
        self.statustable.setHorizontalHeaderLabels(self._statustableheader)
        item = QtWidgets.QTableWidgetItem("All")
        self.statustable.setItem(0, 0, item)
        self.statustable.resizeColumnsToContents()

        # 3. Add the DBConfigWidget to the main content area (self.layout)
        # We add it at the top of the 'self.widget' (main content area)
        self.layout.addWidget(self.db_config_widget)
        self.layout.addWidget(self.statustable)
        self.layout.addStretch(1)  # Push the DB widget to the top

        self.statustimer_db = QtCore.QTimer()
        self.statustimer_db.timeout.connect(self.update_status)


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
            #print("data", data)
        except:
            data = None

        if data is not None:
            try:
                item_inserted = QtWidgets.QTableWidgetItem(str(data['packet_inserted']))
                item_inserted_failure = QtWidgets.QTableWidgetItem(
                    str(data['packet_inserted_failure']))
                self.statistics.update(data['statistics'])
                #print("Statistics",self.statistics)
                self.statustable.setItem(0,1,item_inserted)
                self.statustable.setItem(0, 2, item_inserted_failure)
                for row,(k, i) in enumerate(self.statistics.items()):
                    #print("k",k)
                    #print("i", i)
                    k_mod = RedvyprAddress(k).to_address_string(["i","p","h","d"])
                    try:
                        item_inserted = self._statistics_items[k][1]
                        item_inserted_failure = self._statistics_items[k][2]
                        istr = str(i['packet_inserted'])
                        item_inserted.setText(istr)
                    except:
                        logger.info("Could not get data",exc_info=True)
                        item_addr = QtWidgets.QTableWidgetItem(k_mod)
                        item_inserted = QtWidgets.QTableWidgetItem(str(i['packet_inserted']))
                        item_inserted_failure = QtWidgets.QTableWidgetItem(
                            str(i['packet_inserted_failure']))
                        self._statistics_items[k] = (item_addr,item_inserted,item_inserted_failure)
                        nrows = self.statustable.rowCount()
                        self.statustable.setRowCount(nrows + 1)
                        self.statustable.setItem(nrows, 0, item_addr)
                        self.statustable.setItem(nrows, 1, item_inserted)
                        self.statustable.setItem(nrows, 2, item_inserted_failure)

                    #item = self._statistics_items[k]

                self.statustable.resizeColumnsToContents()
            except:
                logger.info("Could not update data",exc_info=True)

    # This is bad style, needs to be changed to thread_started signal and continous update of configuration
    def start_clicked(self):
        self.device.custom_config = self.db_config_widget.get_config()
        self.statustimer_db.start(500)
        super().start_clicked()