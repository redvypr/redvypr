from PyQt6 import QtWidgets, QtCore
import time
import logging
import sys
import pydantic
import typing
import hashlib
import re
import uuid
import json
import numpy as np
from typing import Any, Dict, List, Optional, Iterator
from redvypr.redvypr_address import RedvyprAddress
from redvypr.widgets.redvyprAddressWidget import RedvyprMultipleAddressesWidget
from datetime import datetime, timezone

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db.db_config')
logger.setLevel(logging.DEBUG)


def get_calibration_uuid():
    #return 'CAL_' + str(uuid.uuid4())
    uuid_str = uuid.uuid4().hex
    short_uuid = "DBCFG_" + uuid_str
    return short_uuid


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



class DbTableConfig(pydantic.BaseModel):
    tablename: str = pydantic.Field(default="", description="The tablename")
    tabletype: typing.Literal["redvypr_datapacket", "data_flat", "redvypr_metadata"]\
        = pydantic.Field(
        default="redvypr_datapacket",
        description="The type of the database table. Options: "
                    "redvypr_datapacket: Full redvypr datapackets, "
                    "data_flat: data is extracted from one or multiple redvypr_address(es) and stored as a column entry,"
                    "redvypr_metadata: Metadata of the redvypr host "
    )
    addresses: List[str] = pydantic.Field(default_factory=list,description="The redvypr addresses that are saved in the table.")


class DbWriteConfig(pydantic.BaseModel):
    tables: Dict[str, DbTableConfig] = pydantic.Field(
        default_factory=dict,
        description=""" A dictionary of the tables, the key is the tablename"""
    )
    uuid: str = pydantic.Field(default_factory=get_calibration_uuid)
    name: str = pydantic.Field(default="")
    description: str = pydantic.Field(default="")



def json_safe_dumps_legacy(obj):
    """
    Convert complex Redvypr packets into JSON-safe text.
    Adds a '__dt__:' prefix to datetime objects to ensure safe restoration.
    """

    def default(o):
        # numpy arrays → convert to Python lists
        if isinstance(o, np.ndarray):
            return o.tolist()

        # numpy scalar values (e.g. np.int64, np.float64)
        if isinstance(o, (np.generic,)):
            return o.item()

        # Handle Python 'type' objects
        if isinstance(o, type):
            return str(o)

        # Handle datetime with specific prefix marker
        if isinstance(o, datetime):
            return f"__dt__:{o.isoformat()}"

        # Handle other unknown types
        return str(o)

    return json.dumps(obj, default=default, ensure_ascii=False)


def restore_datetimes_legacy(data):
    """
    Recursively traverses dictionaries and lists to find strings
    starting with '__dt__:' and converts them back to datetime objects.
    """
    if isinstance(data, dict):
        return {k: restore_datetimes(v) for k, v in data.items()}

    elif isinstance(data, list):
        return [restore_datetimes(item) for item in data]

    elif isinstance(data, str) and data.startswith("__dt__:"):
        try:
            # Strip prefix and convert to datetime
            iso_str = data.replace("__dt__:", "", 1)
            return datetime.fromisoformat(iso_str)
        except (ValueError, TypeError):
            # If conversion fails, return the string as is
            return data

    return data


def json_safe_loads_legacy(json_str):
    """
    Parses a JSON string and automatically restores datetime objects
    hidden in dictionaries or lists.
    """
    raw_data = json.loads(json_str)
    return restore_datetimes(raw_data)


# GUI
class TableDetailWidget(QtWidgets.QWidget):
    """Sub-widget for editing a specific table configuration."""

    # Signal emitted whenever data within this table changes
    data_changed = QtCore.pyqtSignal()

    def __init__(self, tablename: str, parent=None, redvypr=None):
        super().__init__(parent)
        self.redvypr=redvypr
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Table Type Selection
        form = QtWidgets.QFormLayout()
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItems([
            "redvypr_datapacket",
            "data_flat",
            "redvypr_metadata"
        ])
        form.addRow("Table Type:", self.type_combo)
        layout.addLayout(form)

        # Address List Management
        layout.addWidget(QtWidgets.QLabel("Registered Addresses:"))
        addr_layout = QtWidgets.QHBoxLayout()
        self.addr_list = QtWidgets.QListWidget()

        btn_layout = QtWidgets.QVBoxLayout()
        self.btn_add_man_addr = QtWidgets.QPushButton("+")
        self.btn_add_man_addr.setToolTip("Add Address Manually")
        self.btn_add_addr = QtWidgets.QPushButton("+ (List)")
        self.btn_add_addr.setToolTip("Add Address from list")
        self.btn_del_addr = QtWidgets.QPushButton("-")
        self.btn_del_addr.setToolTip("Remove Selected Address")

        btn_layout.addWidget(self.btn_add_addr)
        btn_layout.addWidget(self.btn_add_man_addr)
        btn_layout.addWidget(self.btn_del_addr)
        btn_layout.addStretch()

        addr_layout.addWidget(self.addr_list)
        addr_layout.addLayout(btn_layout)
        layout.addLayout(addr_layout)

    def _connect_signals(self):
        """Connect internal widgets to the data_changed signal."""
        # ComboBox change
        self.type_combo.currentIndexChanged.connect(self.data_changed)

        # Button actions
        self.btn_add_man_addr.clicked.connect(self._add_address_dialog)
        self.btn_add_addr.clicked.connect(self._add_address_widget)
        self.btn_del_addr.clicked.connect(self._remove_selected_address)

        # Monitor the list model for insertions/removals
        self.addr_list.model().rowsInserted.connect(lambda: self.data_changed.emit())
        self.addr_list.model().rowsRemoved.connect(lambda: self.data_changed.emit())

    def _add_address_widget(self):
        self._address_widget = RedvyprMultipleAddressesWidget(redvypr=self.redvypr)
        self._address_widget.apply.connect(self._addresses_added)
        self._address_widget.show()

    def _addresses_added(self,dict):
        print("dict",dict)
        for a in dict["addresses"]:
            self.addr_list.addItem(a.to_address_string())

    def _add_address_dialog(self):
        addr, ok = QtWidgets.QInputDialog.getText(self, "New Address",
                                                  "Enter Redvypr Address:")
        if ok and addr:
            self.addr_list.addItem(addr)

    def _remove_selected_address(self):
        row = self.addr_list.currentRow()
        if row >= 0:
            self.addr_list.takeItem(row)

    def set_table_config(self, table_cfg: Any):
        """Populates the table detail view from data."""
        # Block signals to prevent 'changed' triggers during loading
        self.blockSignals(True)
        data = table_cfg if isinstance(table_cfg, dict) else table_cfg.model_dump()

        idx = self.type_combo.findText(data.get("tabletype", ""))
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

        self.addr_list.clear()
        for addr in data.get("addresses", []):
            self.addr_list.addItem(addr)
        self.blockSignals(False)

    def get_table_config(self) -> dict:
        """Returns the specific table configuration as a dictionary."""
        return {
            "tabletype": self.type_combo.currentText(),
            "addresses": [self.addr_list.item(i).text() for i in
                          range(self.addr_list.count())]
        }


class DbConfigWidget(QtWidgets.QWidget):
    """Main Widget for Database Configuration."""

    # Signal emitted whenever any part of the configuration changes
    config_changed = QtCore.pyqtSignal()

    def __init__(self, initial_config: Any = None, parent=None, redvypr=None):
        super().__init__(parent)
        self.redvypr = redvypr
        self.setWindowTitle("Database Write Configuration")
        self._setup_ui()

        if initial_config:
            self.set_config_data(initial_config)

        self._connect_main_signals()

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)

        # --- Section 1: General Config ---
        gen_group = QtWidgets.QGroupBox("General Configuration")
        gen_layout = QtWidgets.QFormLayout(gen_group)

        self.name_edit = QtWidgets.QLineEdit()
        self.desc_edit = QtWidgets.QTextEdit()
        self.desc_edit.setMaximumHeight(60)

        uuid_layout = QtWidgets.QHBoxLayout()
        self.uuid_label = QtWidgets.QLabel(get_calibration_uuid())
        self.uuid_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        self.btn_new_uuid = QtWidgets.QPushButton("Regenerate")

        uuid_layout.addWidget(self.uuid_label)
        uuid_layout.addWidget(self.btn_new_uuid)
        uuid_layout.addStretch()

        gen_layout.addRow("Config Name:", self.name_edit)
        gen_layout.addRow("Description:", self.desc_edit)
        gen_layout.addRow("UUID:", uuid_layout)
        main_layout.addWidget(gen_group)

        # --- Section 2: Tables Management ---
        table_group = QtWidgets.QGroupBox("Tables Definition")
        table_layout = QtWidgets.QVBoxLayout(table_group)

        table_tools = QtWidgets.QHBoxLayout()
        self.btn_add_table = QtWidgets.QPushButton("Add Table")
        self.btn_remove_table = QtWidgets.QPushButton("Remove Selected Table")

        table_tools.addWidget(self.btn_add_table)
        table_tools.addWidget(self.btn_remove_table)
        table_tools.addStretch()
        table_layout.addLayout(table_tools)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.table_list = QtWidgets.QListWidget()
        self.table_detail_stack = QtWidgets.QStackedWidget()

        # Placeholder for index 0
        placeholder = QtWidgets.QLabel("Select a table to edit or add a new one")
        placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.table_detail_stack.addWidget(placeholder)

        self.splitter.addWidget(self.table_list)
        self.splitter.addWidget(self.table_detail_stack)
        self.splitter.setStretchFactor(1, 2)

        table_layout.addWidget(self.splitter)
        main_layout.addWidget(table_group)

    def _connect_main_signals(self):
        """Connect UI elements to the central config_changed signal."""
        # General inputs
        self.name_edit.textChanged.connect(self.config_changed)
        self.desc_edit.textChanged.connect(self.config_changed)
        self.btn_new_uuid.clicked.connect(self._regenerate_uuid)

        # Table list interactions
        self.btn_add_table.clicked.connect(self._add_table_dialog)
        self.btn_remove_table.clicked.connect(self._remove_selected_table)
        self.table_list.currentRowChanged.connect(self._table_selection_changed)

        # Monitor list model
        self.table_list.model().rowsInserted.connect(lambda: self.config_changed.emit())
        self.table_list.model().rowsRemoved.connect(lambda: self.config_changed.emit())

    def _regenerate_uuid(self):
        self.uuid_label.setText(get_calibration_uuid())
        self.config_changed.emit()

    def _table_selection_changed(self, index):
        self.table_detail_stack.setCurrentIndex(index + 1 if index >= 0 else 0)

    def _add_table_dialog(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New Table",
                                                  "Enter Table Name:")
        if ok and name:
            if any(self.table_list.item(i).text() == name for i in
                   range(self.table_list.count())):
                QtWidgets.QMessageBox.warning(self, "Error",
                                              "Table name already exists!")
                return
            self.add_table(name)

    def add_table(self, name: str, table_cfg: Any = None):
        """Adds a new table entry and connects its internal change signal."""
        self.table_list.addItem(name)
        detail_widget = TableDetailWidget(name,redvypr=self.redvypr)

        # Bubble up the signal from the sub-widget
        detail_widget.data_changed.connect(self.config_changed)

        if table_cfg:
            detail_widget.set_table_config(table_cfg)

        self.table_detail_stack.addWidget(detail_widget)
        self.table_list.setCurrentRow(self.table_list.count() - 1)

    def _remove_selected_table(self):
        row = self.table_list.currentRow()
        if row >= 0:
            self.table_list.takeItem(row)
            widget = self.table_detail_stack.widget(row + 1)
            self.table_detail_stack.removeWidget(widget)

    def set_config_data(self, config: Any):
        """Loads data and blocks change signals during the process."""
        self.blockSignals(True)
        data = config if isinstance(config, dict) else config.model_dump()

        self.name_edit.setText(data.get("name", ""))
        self.desc_edit.setText(data.get("description", ""))
        self.uuid_label.setText(data.get("uuid", get_calibration_uuid()))

        self.table_list.clear()
        while self.table_detail_stack.count() > 1:
            self.table_detail_stack.removeWidget(self.table_detail_stack.widget(1))

        tables = data.get("tables", {})
        for t_name, t_cfg in tables.items():
            self.add_table(t_name, t_cfg)
        self.blockSignals(False)

        if len(tables)>0:
            self._table_selection_changed(0)

    def get_config_data(self) -> dict:
        """Returns the current UI state as a dictionary."""
        tables = {}
        for i in range(self.table_list.count()):
            name = self.table_list.item(i).text()
            detail_widget = self.table_detail_stack.widget(i + 1)
            if detail_widget is not None:
                tables[name] = detail_widget.get_table_config()
                tables[name]["tablename"] = name

        return {
            "name": self.name_edit.text(),
            "description": self.desc_edit.toPlainText(),
            "uuid": self.uuid_label.text(),
            "tables": tables
        }

    def get_config(self) -> Any:
        """
        Returns the config as a Pydantic DbConfig object.
        Replace 'DbConfig' with your actual Pydantic class.
        """
        data = self.get_config_data()
        return DbWriteConfig(**data)
        #return data  # Fallback if model not imported









