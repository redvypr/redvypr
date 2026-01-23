import copy
import datetime
import os.path
import zoneinfo
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import pyqtgraph
import yaml
import uuid
import pydantic
from pydantic import BaseModel
import typing
from typing import List, Any
from collections.abc import Iterable
import numpy
from pathlib import Path
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import check_for_command, commandpacket
from redvypr.device import RedvyprDevice
import redvypr.files as redvypr_files
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from .sensor_and_calibration_definitions import CalibrationFactory
from redvypr.device import RedvyprDeviceCustomConfig
from redvypr.devices.db.db_util_widgets import DBStatusDialog, TimescaleDbConfigWidget, DBConfigWidget
from redvypr.devices.db.db_engines import RedvyprTimescaleDb, DatabaseConfig, DatabaseSettings, TimescaleConfig, SqliteConfig, RedvyprDBFactory


_logo_file = redvypr_files.logo_file
_icon_file = redvypr_files.icon_file
description = 'Manager for sensors and calibrations'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.sencalmgr')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = False
    description: str = 'Manage calibrations and sensors'


class DeviceCustomConfig(RedvyprDeviceCustomConfig):
    calibration_lists: dict = pydantic.Field(default={'Calibrations':[]})


def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    return


class Device(RedvyprDevice):
    """
    Sensor and calibration manager
    """

    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)
        logger.debug(funcname)

        # Internal storage: { 'list_name': [cal_dict_1, cal_dict_2] }
        self.calibration_lists = self.custom_config.calibration_lists
        # Convert the dictionaries into calibratios
        for list_name, cal_list in self.calibration_lists.items():
            print(f"Processing {list_name}")
            new_list = []
            for cal in cal_list:
                cal_proc = CalibrationFactory.create(cal)
                new_list.append(cal_proc)

            # Replacing the old list
            self.calibration_lists[list_name] = new_list



    def import_calibration(self, list_name: str, file_path: str) -> bool:
        """
        Loads a YAML file and appends its content to the specified list.
        """
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File not found: {file_path}")
            return False

        try:
            with open(path, 'r') as file:
                # safe_load_all liest alle Dokumente (getrennt durch ---) nacheinander ein
                all_calibrations = yaml.safe_load_all(file)

                for calibration_data in all_calibrations:
                    if calibration_data is None:
                        continue  # Skips empty entries

                    if list_name not in self.calibration_lists:
                        self.calibration_lists[list_name] = []

                    calibration = CalibrationFactory.create(calibration_data)
                    self.calibration_lists[list_name].append(calibration)

                logger.info(f"Successfully imported '{path.name}' into list '{list_name}'.")
            return True

        except yaml.YAMLError as exc:
            logger.error(f"Error parsing YAML file: {exc}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during import: {e}")
            return False

    def delete_calibration_list(self, list_name: str):
        """
        Deletes an entire list of calibrations.
        """
        if list_name in self.calibration_lists:
            del self.calibration_lists[list_name]
            logger.info(f"Calibration list '{list_name}' deleted.")
        else:
            logger.warning(f"List '{list_name}' does not exist.")

    def clear_all_calibrations(self):
        """
        Removes all lists and data.
        """
        self.calibration_lists.clear()
        logger.debug("All calibration data cleared.")

    def get_calibrations(self, list_name: str) -> list:
        """
        Returns the calibrations for a specific list, or an empty list if not found.
        """
        return self.calibration_lists.get(list_name, [])

    def create_metadict_from_calibration_list(self, list_name: str) -> dict:
        """

        Parameters
        ----------
        list_name

        Returns
        -------
        Dictionary that can be sent processed with redvypr.set_metadata_from_dict
        """
        funcname = __name__ + '.create_metadatapacket_from_calibration_list():'
        logger.debug(funcname)
        calibrations = self.calibration_lists[list_name]

        calibration_dict_meta = {}
        for calibration in calibrations:
            raddress = calibration.create_redvypr_address()
            address_str = raddress.to_address_string()
            calibration_dict = calibration.model_dump()
            calibration_dict_meta[address_str] = {'calibration':calibration_dict}

        logger.debug(funcname + 'Metadata packet created')
        return calibration_dict_meta

    def create_calibration_list_from_metadata(self, list_name='metadata') -> dict:
        """

        Parameters
        ----------


        Returns
        -------

        """
        funcname = __name__ + '.create_metadatapacket_from_calibration_list():'
        logger.debug(funcname)

        metadata = self.redvypr.get_metadata()
        self.calibration_lists[list_name] = []
        for maddr,mdata in metadata.items():
            print(mdata)
            if 'calibration' in mdata.keys():
                print("Found calibration")
                calibration_data = mdata["calibration"]
                print(f"Calibration data:{calibration_data}")
                calibration = CalibrationFactory.create(calibration_data)
                self.calibration_lists[list_name].append(calibration)

        print(f"{self.calibration_lists=}")
        return self.calibration_lists[list_name]

    def set_metadata_from_calibration_list(self, list_name: str):
        metadict = self.create_metadict_from_calibration_list(list_name=list_name)
        self.redvypr.set_metadata_from_dict(metadata=metadict)

    def load_calibrations_from_db(self, databaseconfig=None, list_name=None) -> dict:
        print("Creating db from config", databaseconfig)
        db = RedvyprDBFactory.create(databaseconfig)
        return_dict = {'num_read':0,'num_added':0}
        with db:
            print("Opened")
            # 1. Setup (gentle approach)
            db.identify_and_setup()
            status = db.check_health()

            # Read metadata first
            metainfo = db.get_metadata_info()
            count_all = 0
            for m in metainfo:
                count_all += m['count']

            #print("Metadata stat", metainfo)
            #print("Count all", count_all)
            metadata = db.get_metadata(0, count_all)
            #print("Metadata", metadata)
            try:
                self.calibration_lists[list_name]
            except:
                self.calibration_lists[list_name] = []

            list_add = self.calibration_lists[list_name]
            for mdict in metadata:
                print("mdict",mdict)
                #maddr = mdict['address']
                mdata = mdict['metadata']
                if 'calibration' in mdata.keys():
                    return_dict['num_read'] += 1
                    cal_proc = CalibrationFactory.create(mdata['calibration'])
                    if cal_proc not in list_add:
                        list_add.append(cal_proc)
                        return_dict['num_added'] += 1
                    else:
                        print("Calibration already in list")


        return return_dict


    def save_calibrations_to_db(self, databaseconfig=None, list_name=None):
        print("Creating db from config",databaseconfig)
        db = RedvyprDBFactory.create(databaseconfig)
        with db:
            print("Opened")
            # 1. Setup (gentle approach)
            db.identify_and_setup()
            status = db.check_health()
            calibrations = self.calibration_lists[list_name]
            for calibration in calibrations:
                print(f"Creating metadata for {calibration=}")
                raddress = calibration.create_redvypr_address()
                address_str = raddress.to_address_string()
                calibration_dict = calibration.model_dump()
                uuid = hash(calibration)
                packetid = raddress.packetid
                try:
                    db.add_metadata(address=address_str,
                                    uuid=uuid,
                                    metadata_dict={'calibration': calibration_dict})
                except:
                    logger.warning("Could not add metadata", exc_info=True)



from enum import Enum
from typing import Literal


class DBAction(Enum):
    LOAD = "load"
    SAVE = "save"


class DBCalibrationLoadSaveWidget(QtWidgets.QWidget):
    """
    Wraps DBConfigWidget and adds a contextual Load or Save button.
    """
    # Signal, das gefeuert wird, wenn der Button geklickt wird
    action_triggered = QtCore.Signal(object)  # Emittiert die DatabaseConfig
    calibration_loaded = QtCore.Signal(dict)  #

    def __init__(self, initial_config: DatabaseConfig,
                 mode: Literal["load", "save"] = "load",
                 calibrations_list=None,
                 list_name=None, device=None, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.calibration_list = calibrations_list
        self.list_name = list_name
        self.device = device
        # Wir nutzen Komposition: Das Config-Widget wird ein Kind dieses Widgets
        self.config_widget = DBConfigWidget(initial_config)

        self.setup_ui()

    def setup_ui(self):
        self.layout = QtWidgets.QVBoxLayout(self)

        # 1. Das eingebettete Konfigurations-Widget hinzufügen
        self.layout.addWidget(self.config_widget)

        # 2. Action Button Bereich
        self.button_layout = QtWidgets.QHBoxLayout()
        self.button_layout.addStretch()  # Schiebt den Button nach rechts

        if self.mode == "load":
            self.action_btn = QtWidgets.QPushButton("Load Calibration")
            self.action_btn.setIcon(
                self.style().standardIcon(QtWidgets.QStyle.SP_DialogOpenButton))
            self.action_btn.clicked.connect(self.on_load_clicked)
        else:
            self.action_btn = QtWidgets.QPushButton("Save Calibration")
            self.action_btn.setIcon(
                self.style().standardIcon(QtWidgets.QStyle.SP_DialogSaveButton))

            self.action_btn.clicked.connect(self.on_save_clicked)


        self.button_layout.addWidget(self.action_btn)

        self.layout.addLayout(self.button_layout)

    def on_load_clicked(self):
        """Holt die aktuelle Konfiguration und schickt sie mit dem Signal raus."""
        current_config = self.config_widget.get_config()
        config = self.get_config()
        db = RedvyprDBFactory.create(config)
        config = self.get_config()
        ret_dict = self.device.load_calibrations_from_db(databaseconfig=config,
                                            list_name=self.list_name)

        self.calibration_loaded.emit(ret_dict)
    def on_save_clicked(self):
        """Holt die aktuelle Konfiguration und schickt sie mit dem Signal raus."""
        current_config = self.config_widget.get_config()
        config = self.get_config()
        self.device.save_calibrations_to_db(databaseconfig=config, list_name=self.list_name)



    # Proxy-Methoden, damit man von außen leichter an das Config-Widget kommt
    def get_config(self):
        return self.config_widget.get_config()

class CalibrationTable(QtWidgets.QTableWidget):
    # Signals
    calibrationDataChanged = QtCore.pyqtSignal(int)
    calibrationDeleted = QtCore.pyqtSignal(object)

    def __init__(self, calibration_lists, list_name, parent=None):
        super().__init__(parent)
        self.calibration_lists = calibration_lists
        self.list_name = list_name

        # Standard columns that are always visible
        self.default_columns = ['name', 'sn', 'sensortype', 'date']
        self.extra_columns = []
        self.all_possible_keys = []

        self.setup_ui()
        self.update_possible_keys()
        self.refresh_table()

        # Shortcuts
        self.copy_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+C"), self)
        self.copy_shortcut.activated.connect(self.copy_selection)
        self.paste_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+V"), self)
        self.paste_shortcut.activated.connect(self.paste_selection)

    @property
    def data_list(self):
        """
           This is solved this way,
           as it allows that the list is removed and recreated somewhere else
        """
        try:
            self.calibration_lists[self.list_name]
        except:
            self.calibration_lists[self.list_name] = []

        return self.calibration_lists[self.list_name]

    def setup_ui(self):
        # UI Policy and Selection
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)

        # Headers
        header = self.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)

        # Enable Sorting
        self.setSortingEnabled(True)

    def update_possible_keys(self):
        """Finds keys in the Pydantic models not present in default_columns."""
        keys = set()
        for item in self.data_list:
            if hasattr(item, "model_dump"):
                keys.update(item.model_dump().keys())
            else:
                keys.update(item.dict().keys())

        self.all_possible_keys = sorted([
            k for k in keys if k not in self.default_columns
        ])

    def refresh_table(self):
        """Rebuilds the table structure and data."""
        # Disable sorting while populating to prevent flickering/index shifts
        self.setSortingEnabled(False)
        self.clear()

        # Define Columns: # (Row Number), then Defaults, then Extras
        headers = ['#'] + [col.capitalize() for col in
                           self.default_columns] + self.extra_columns
        actual_keys = self.default_columns + self.extra_columns

        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(self.data_list))

        for row_idx, item in enumerate(self.data_list):
            # 1. Sequential Row Number (Column 0)
            # We use a custom QTableWidgetItem that sorts numerically
            num_item = QtWidgets.QTableWidgetItem()
            num_item.setData(QtCore.Qt.ItemDataRole.DisplayRole, row_idx + 1)
            num_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            # Make row number read-only and non-selectable for clarity
            num_item.setFlags(num_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.setItem(row_idx, 0, num_item)

            # 2. Data Columns
            for col_idx, key in enumerate(actual_keys, start=1):
                val = getattr(item, key, "-")
                table_item = QtWidgets.QTableWidgetItem(str(val))
                table_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                # Store the original Pydantic object reference in the first data cell of the row
                if col_idx == 1:
                    table_item.setData(QtCore.Qt.ItemDataRole.UserRole, item)

                self.setItem(row_idx, col_idx, table_item)

        self.setSortingEnabled(True)

    def get_selected_pydantic_objects(self) -> List[Any]:
        """Helper to get Pydantic objects from selected rows regardless of sorting."""
        objects = []
        selected_indexes = self.selectionModel().selectedRows()
        for index in selected_indexes:
            # We get the object from Column 1 where we stored it in UserRole
            obj = self.item(index.row(), 1).data(QtCore.Qt.ItemDataRole.UserRole)
            objects.append(obj)
        return objects

    def copy_selection(self):
        items = self.get_selected_pydantic_objects()
        if not items:
            return

        items_to_copy = []
        for original_item in items:
            if hasattr(original_item, "model_copy"):
                items_to_copy.append(original_item.model_copy())
            else:
                items_to_copy.append(copy.deepcopy(original_item))

        # Access clipboard in RedvyprDeviceWidget
        parent = self.parent_widget()
        if parent:
            parent._clipboard = items_to_copy
            QtWidgets.QToolTip.showText(
                QtGui.QCursor.pos(),
                f"Copied {len(items_to_copy)} calibration(s)"
            )

    def paste_selection(self):
        parent = self.parent_widget()
        if not parent or not parent._clipboard:
            return

        clipboard_data = parent._clipboard
        items_to_paste = clipboard_data if isinstance(clipboard_data, list) else [
            clipboard_data]

        for item in items_to_paste:
            if hasattr(item, "model_copy"):
                new_item = item.model_copy()
            else:
                new_item = copy.deepcopy(item)
            self.data_list.append(new_item)

        self.update_possible_keys()
        self.refresh_table()
        self.calibrationDataChanged.emit(len(self.data_list))
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(),
                                    f"Pasted {len(items_to_paste)} calibration(s)")

    def delete_selected_rows(self):
        items_to_delete = self.get_selected_pydantic_objects()
        if not items_to_delete:
            return

        reply = QtWidgets.QMessageBox.question(
            self, 'Confirm Deletion',
            f"Delete {len(items_to_delete)} selected calibration(s)?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )

        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            for item in items_to_delete:
                if item in self.data_list:
                    self.data_list.remove(item)
                    self.calibrationDeleted.emit(item)

            self.update_possible_keys()
            self.refresh_table()
            self.calibrationDataChanged.emit(len(self.data_list))

    def show_context_menu(self, position):
        menu = QtWidgets.QMenu(self)
        selected_rows = self.selectionModel().selectedRows()

        if selected_rows:
            del_act = menu.addAction(f"Delete Selected ({len(selected_rows)})")
            del_act.triggered.connect(lambda: self.delete_selected_rows())
            menu.addSeparator()

        col_menu = menu.addMenu("Toggle Extra Columns")
        for key in self.all_possible_keys:
            action = QtGui.QAction(key, col_menu, checkable=True,
                                   checked=(key in self.extra_columns))
            action.triggered.connect(
                lambda checked, k=key: self.toggle_column(k, checked))
            col_menu.addAction(action)
        menu.exec(self.viewport().mapToGlobal(position))

    def toggle_column(self, key, checked):
        if checked and key not in self.extra_columns:
            self.extra_columns.append(key)
        elif not checked and key in self.extra_columns:
            self.extra_columns.remove(key)
        self.refresh_table()

    def parent_widget(self) -> 'RedvyprDeviceWidget':
        curr = self.parent()
        # Find the widget that has the _clipboard attribute
        while curr:
            if hasattr(curr, '_clipboard'):
                return curr
            curr = curr.parent()
        return None


from PyQt6 import QtWidgets, QtCore, QtGui
import yaml


class CalibrationManageWidget(QtWidgets.QWidget):
    # Signals for communication with the main app
    dataImported = QtCore.pyqtSignal()

    def __init__(self, calibration_lists, device_reference, list_name, parent=None):
        super().__init__(parent)
        self.device = device_reference
        self.list_name = list_name
        self.calibration_lists = calibration_lists
        self.setup_ui()

    @property
    def data_list(self):
        """
           This is solved this way,
           as it allows that the list is removed and recreated somewhere else
        """
        try:
            self.calibration_lists[self.list_name]
        except:
            self.calibration_lists[self.list_name] = []

        return self.calibration_lists[self.list_name]

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # --- Toolbar for Load/Save/Clipboard ---
        toolbar = QtWidgets.QHBoxLayout()

        # 1. LOAD BUTTON with Menu
        self.btn_load = QtWidgets.QPushButton("Load")
        load_menu = QtWidgets.QMenu(self)
        load_menu.addAction("Import from YAML", self.import_from_yaml)
        load_menu.addAction("Load from Database", self.load_from_db)
        load_menu.addAction("Load from Metadata", self.load_from_metadata)
        self.btn_load.setMenu(load_menu)

        # 2. SAVE/APPLY BUTTON with Menu
        self.btn_save = QtWidgets.QPushButton("Save / Apply")
        save_menu = QtWidgets.QMenu(self)
        save_menu.addAction("Export to YAML", self.save_data)
        save_menu.addAction("Save to Database", self.save_to_db)
        save_menu.addSeparator()
        # Your new feature: Sending to redvypr system
        save_menu.addAction("Apply Metadata to System", self.apply_metadata_to_system)
        self.btn_save.setMenu(save_menu)

        # 3. CLIPBOARD BUTTONS
        self.btn_copy = QtWidgets.QPushButton("Copy")
        self.btn_copy.setToolTip("Copy selected rows (Ctrl+C)")
        self.btn_copy.clicked.connect(lambda: self.table.copy_selection())

        self.btn_paste = QtWidgets.QPushButton("Paste")
        self.btn_paste.setToolTip("Paste from clipboard (Ctrl+V)")
        self.btn_paste.clicked.connect(lambda: self.table.paste_selection())

        # Add widgets to toolbar
        toolbar.addWidget(self.btn_load)
        toolbar.addWidget(self.btn_save)
        toolbar.addSpacing(20)  # Visual separator
        toolbar.addWidget(self.btn_copy)
        toolbar.addWidget(self.btn_paste)
        toolbar.addStretch()

        layout.addLayout(toolbar)

        # 4. THE TABLE
        self.table = CalibrationTable(self.calibration_lists, self.list_name)
        layout.addWidget(self.table)

    def import_from_yaml(self):
        # Allow selecting multiple files
        file_paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Import YAML Files",
            "",
            "YAML Files (*.yaml *.yml);;All Files (*)"
        )

        if file_paths:
            imported_count = 0
            for path in file_paths:
                success = self.device.import_calibration(self.list_name, path)
                if success:
                    imported_count += 1

            if imported_count > 0:
                self.table.update_possible_keys()
                self.table.refresh_table()
                self.dataImported.emit()

                QtWidgets.QToolTip.showText(
                    QtGui.QCursor.pos(),
                    f"Successfully imported {imported_count} file(s)."
                )

    def save_data(self):
        """Export current list to a single YAML file."""
        if not self.data_list:
            QtWidgets.QMessageBox.warning(self, "Save", "List is empty.")
            return

        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export YAML", f"{self.list_name}.yaml", "YAML Files (*.yaml)"
        )

        if file_path:
            try:
                # Convert Pydantic models to dicts
                export_data = [
                    obj.model_dump() if hasattr(obj, 'model_dump') else obj.dict()
                    for obj in self.data_list
                ]
                with open(file_path, 'w') as f:
                    yaml.safe_dump(export_data, f, sort_keys=False)

                QtWidgets.QMessageBox.information(self, "Success", "Export successful.")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Export failed: {e}")

    def apply_metadata_to_system(self):
        """Uses the new device method to set metadata on the redvypr system."""
        if not self.data_list:
            QtWidgets.QMessageBox.warning(self, "Warning", "List is empty.")
            return

        try:
            # Call your newly added device methods
            self.device.set_metadata_from_calibration_list(self.list_name)

            QtWidgets.QMessageBox.information(
                self,
                "System Update",
                f"Successfully applied metadata for '{self.list_name}' to Redvypr."
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "System Error",
                                           f"Failed to apply metadata: {e}")

    def list_changed(self, load_info):
        print(f"List changed:{load_info}")
        self.table.update_possible_keys()
        self.table.refresh_table()
        self.dataImported.emit()

    def load_from_db(self):
        print(f"Loading {self.list_name} from DB...")
        initial_config = SqliteConfig()
        self.db_config_widget = DBCalibrationLoadSaveWidget(
            initial_config=initial_config, mode='load',
            device=self.device,
            calibrations_list=self.calibration_lists,
            list_name=self.list_name)

        self.db_config_widget.calibration_loaded.connect(self.list_changed)
        self.db_config_widget.show()



    def save_to_db(self):
        print(f"Saving {self.list_name} to DB...")
        initial_config = SqliteConfig()
        self.db_config_widget = DBCalibrationLoadSaveWidget(
            initial_config=initial_config, mode='save',
            device=self.device,
            calibrations_list=self.calibration_lists,
            list_name=self.list_name)


        self.db_config_widget.show()

    def load_from_metadata(self):
        print(f"Loading {self.list_name} from Metadata...")
        calibrations = self.device.create_calibration_list_from_metadata(list_name=self.list_name)
        imported_count = len(calibrations)
        print("calibrations")
        print(f"Loaded {imported_count} calibrations")
        if imported_count > 0:
            print(f"{self.list_name=}")
            print(f"{self.data_list=}")
            self.table.update_possible_keys()
            self.table.refresh_table()
            self.dataImported.emit()

            QtWidgets.QToolTip.showText(
                QtGui.QCursor.pos(),
                f"Successfully imported {imported_count} file(s)."
            )


class RedvyprDeviceWidget(QtWidgets.QWidget):
    def __init__(self, *args, device=None, redvypr=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.device = device
        self.redvypr = redvypr
        # Internal clipboard for Pydantic objects
        self._clipboard = None

        # Main Layout
        self.main_layout = QtWidgets.QVBoxLayout(self)

        # Toolbar for List Management
        self.toolbar = QtWidgets.QHBoxLayout()
        self.btn_add_list = QtWidgets.QPushButton("Create New List")
        self.btn_add_list.clicked.connect(self.create_list_dialog)
        self.toolbar.addWidget(self.btn_add_list)
        self.main_layout.addLayout(self.toolbar)

        # Tab Widget for different Calibration Lists
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.delete_list)
        self.main_layout.addWidget(self.tabs)

        for list_name in self.device.calibration_lists.keys():
            self.add_calibration_tab(list_name)

    def create_list_dialog(self):
        """Opens a dialog to name a new calibration list."""
        name, ok = QtWidgets.QInputDialog.getText(self, "New List", "Enter List Name:")
        if ok and name:
            self.add_calibration_tab(name)

    def add_calibration_tab(self, name: str):
        """Creates a new tab with a CalibrationTable."""
        # Ensure the list exists in the Device backend
        if name not in self.device.calibration_lists:
            self.device.calibration_lists[name] = []


        manage_widget = CalibrationManageWidget(
            self.device.calibration_lists,
            self.device,
            name
        )

        index = self.tabs.addTab(manage_widget, name)
        self.tabs.setCurrentIndex(index)

    def delete_list(self, index):
        """Removes the tab and the list from the device."""
        name = self.tabs.tabText(index)
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete the list '{name}' and all its calibrations?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            if name in self.device.calibration_lists:
                del self.device.calibration_lists[name]
            self.tabs.removeTab(index)
