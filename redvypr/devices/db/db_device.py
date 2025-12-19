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
import redvypr
from redvypr.data_packets import check_for_command
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket
from .timescaledb import RedvyprTimescaleDb

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db.db_device')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Writes data into a database'
    gui_tablabel_display: str = 'database status'

class DeviceCustomConfig(pydantic.BaseModel):
    size_packetbuffer: int = 10
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress("data"))
    dbname: str = pydantic.Field(default="postgres")
    user: str = pydantic.Field(default="postgres")
    password: str = pydantic.Field(default="passworD")
    host: str = pydantic.Field(default="pi5server1")
    port: int = pydantic.Field(default=5433)

def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger_thread = logging.getLogger('redvypr.device.db_device.start')
    logger_thread.setLevel(logging.DEBUG)
    logger_thread.debug(funcname)
    print("Config",config)
    pconfig = DeviceCustomConfig(**config)
    print("Opening database")
    db = RedvyprTimescaleDb(dbname = pconfig.dbname,
                            user= pconfig.user,
                            password=pconfig.password,
                            host=pconfig.host,
                            port=pconfig.port)


    db.create_hypertable()

    while True:
        datapacket = datainqueue.get()
        [command, comdata] = check_for_command(datapacket, thread_uuid=device_info['thread_uuid'],
                                               add_data=True)
        if command is not None:
            logger.debug('Command is for me: {:s}'.format(str(command)))
            if command == 'stop':
                logger.info(funcname + 'received command:' + str(datapacket) + ' stopping now')
                logger.debug('Stop command')
                return
        else: # Only save real data
            print('Inserting datapacket',datapacket)
            db.insert_packet_data(datapacket)


def get_database_info(config):
    db = RedvyprTimescaleDb(dbname=config.dbname,
                            user=config.user,
                            password=config.password,
                            host=config.host,
                            port=config.port)

    info = db.get_database_info()
    return info
class DBConfigWidget(QtWidgets.QWidget):
    """
    A dedicated widget for configuring and testing
    database connection settings based on a Pydantic model.
    """

    def __init__(self, initial_config: DeviceCustomConfig, parent=None):
        super().__init__(parent)
        self.initial_config = initial_config
        self.input_fields: Dict[str, QtWidgets.QLineEdit] = {}
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

        # 2. Test Button
        self.test_button = QtWidgets.QPushButton("Test DB Connection")
        # Placeholder icon from qtawesome stub
        icon = qtawesome.icon('fa5s.database')
        self.test_button.setIcon(icon)
        self.test_button.clicked.connect(self.test_connection_clicked)
        main_layout.addWidget(self.test_button)

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

        initial_config = self.device.custom_config
        # 2. Create the new DBConfigWidget
        self.db_config_widget = DBConfigWidget(initial_config=initial_config)

        # 3. Add the DBConfigWidget to the main content area (self.layout)
        # We add it at the top of the 'self.widget' (main content area)
        self.layout.addWidget(self.db_config_widget)

        # Optional: Add a placeholder label for the main device content
        self.layout.addWidget(
            QtWidgets.QLabel("--- Device Live Data/Control Panel ---"))
        self.layout.addStretch(1)  # Push the DB widget to the top

    def start_clicked(self):
        self.device.custom_config = self.db_config_widget.get_config()
        super().start_clicked()