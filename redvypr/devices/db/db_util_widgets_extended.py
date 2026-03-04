import typing
import os
from datetime import datetime
import pydantic
import qtawesome
from PyQt6 import QtWidgets, QtCore, QtGui
from qtpy import QtWidgets
import copy
from .db_engines_extended import TimescaleConfigExtended, SqliteConfigExtended, DatabaseConfigExtended, SqliteConfigExtended, RedvyprDBFactoryExtended, RedvyprSqliteDbExtended
from redvypr.widgets.redvypr_datastream_table_widget import DatastreamTableWidget
from qtpy import QtWidgets, QtCore
import typing



class DBConfigWidgetExtended(QtWidgets.QWidget):
    """
    A container widget that switches between TimescaleDbConfigWidget
    and SqliteConfigWidget based on the selected dbtype.
    """
    db_type_changed = QtCore.Signal(dict)
    db_config_changed = QtCore.Signal(dict)
    def __init__(self, initial_config: DatabaseConfigExtended, parent=None, redvypr=None):
        super().__init__(parent)
        self.redvypr = redvypr
        self.current_config = initial_config
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # --- 1. Selection Header ---
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.addWidget(QtWidgets.QLabel("<b>Database Engine:</b>"))

        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItems(["sqlite", "timescaledb"])

        # Set initial selection from config
        index = self.type_combo.findText(self.current_config.dbtype)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)

        header_layout.addWidget(self.type_combo)
        self.main_layout.addLayout(header_layout)

        # --- 2. The Stacked Area ---
        self.stack = QtWidgets.QStackedWidget()

        # Instantiate specific widgets
        # We pass dummy defaults if the initial type doesn't match
        self.timescale_ui = TimescaleDbConfigWidgetExtended(
            initial_config=self.current_config if isinstance(self.current_config,
                                                             TimescaleConfigExtended) else TimescaleConfigExtended()
        )

        self.sqlite_ui = SqliteConfigWidgetExtended(
            initial_config=self.current_config if isinstance(self.current_config,
                                                             SqliteConfigExtended) else SqliteConfigExtended(),
            redvypr=self.redvypr
        )
        self.sqlite_ui.db_config_changed.connect(self.db_widget_config_changed)
        self.stack.addWidget(self.timescale_ui)  # Index 0
        self.stack.addWidget(self.sqlite_ui)  # Index 1

        self.main_layout.addWidget(self.stack)

        # Connect signals
        self.type_combo.currentTextChanged.connect(self.switch_view)

        # Set initial view
        self.switch_view(self.current_config.dbtype)

    def db_widget_config_changed(self, db_config: dict):
        self.db_config_changed.emit(db_config)
    def switch_view(self, dbtype: str):
        """Swaps the visible configuration form."""
        if "timescaledb" in dbtype:
            self.stack.setCurrentWidget(self.timescale_ui)
            config = self.timescale_ui.get_config()
        elif "sqlite" in dbtype:
            self.stack.setCurrentWidget(self.sqlite_ui)
            config = self.sqlite_ui.get_config()

        print(f"DB type changed:{config}")
        self.db_type_changed.emit(config.model_dump())
    def get_config(self) -> DatabaseConfigExtended:
        """Returns the specific Pydantic model from the active sub-widget."""
        if self.type_combo.currentText() == "timescaledb":
            return self.timescale_ui.get_config()
        else:
            return self.sqlite_ui.get_config()


class DatastreamsTabsWidget(QtWidgets.QWidget):
    """
    A widget to manage multiple tables of datastreams using tabs.
    Emits `tables_changed` on all modifications (add/rename/remove/datastream changes).
    Apply: Closes the widget after changes.
    Cancel: Closes the widget without saving.
    """
    tables_changed = QtCore.Signal(dict)  # Emitted on ALL changes

    def __init__(self, tables=None, parent=None, redvypr=None):
        """
        Initialize the widget.

        Args:
            tables (dict, optional): Initial tables dictionary. Defaults to None.
            parent (QWidget, optional): Parent widget. Defaults to None.
            redvypr (object, optional): Redvypr instance for datastream management.
        """
        super().__init__(parent)
        self.redvypr = redvypr
        self.tables = tables.copy() if tables is not None else {}
        self.setup_ui()

    def setup_ui(self):
        """Set up the UI with tabs and buttons."""
        self.layout = QtWidgets.QVBoxLayout(self)

        # --- Tab Widget ---
        self.tab_widget = QtWidgets.QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.remove_tab)
        self.layout.addWidget(self.tab_widget)

        # --- Tab Management Buttons ---
        tab_button_layout = QtWidgets.QHBoxLayout()

        # Add Tab Button
        self.add_tab_button = QtWidgets.QPushButton(" Add Table")
        self.add_tab_button.setIcon(qtawesome.icon('fa5s.plus'))
        self.add_tab_button.setToolTip("Add a new table")
        self.add_tab_button.clicked.connect(lambda: self.add_tab())
        tab_button_layout.addWidget(self.add_tab_button)

        # Rename Tab Button
        self.rename_tab_button = QtWidgets.QPushButton(" Rename Table")
        self.rename_tab_button.setIcon(qtawesome.icon('fa5s.edit'))
        self.rename_tab_button.setToolTip("Rename the current table")
        self.rename_tab_button.clicked.connect(self.rename_tab)
        tab_button_layout.addWidget(self.rename_tab_button)

        self.layout.addLayout(tab_button_layout)

        # --- Apply/Cancel Buttons ---
        apply_cancel_layout = QtWidgets.QHBoxLayout()

        # Apply Button: Closes the widget after changes
        self.apply_button = QtWidgets.QPushButton(" Apply")
        self.apply_button.setIcon(qtawesome.icon('fa5s.check'))
        self.apply_button.setToolTip("Close and keep changes")
        self.apply_button.clicked.connect(self.on_apply)
        apply_cancel_layout.addWidget(self.apply_button)

        # Cancel Button: Closes without saving
        self.cancel_button = QtWidgets.QPushButton(" Cancel")
        self.cancel_button.setIcon(qtawesome.icon('fa5s.times'))
        self.cancel_button.setToolTip("Close without saving")
        self.cancel_button.clicked.connect(self.on_cancel)
        apply_cancel_layout.addWidget(self.cancel_button)

        self.layout.addLayout(apply_cancel_layout)

        # Initialize existing tabs
        for table_name, datastreams in self.tables.items():
            self.add_tab(table_name, datastreams)

    def on_apply(self):
        """Close the widget/dialog (changes are already saved via signals)."""
        self.close_widget_or_dialog()

    def on_cancel(self):
        """Close the widget/dialog without saving."""
        self.close_widget_or_dialog()

    def close_widget_or_dialog(self):
        """Close the widget or its parent dialog."""
        if self.parent():  # If embedded in a QDialog
            self.parent().close()
        else:
            self.close()

    def add_tab(self, name=None, datastreams=None):
        """
        Add a new tab with a DatastreamTableWidget.

        Args:
            name (str, optional): Table name. If None, prompts the user.
            datastreams (list, optional): Initial datastreams. Defaults to None.

        Returns:
            bool: True if successful, False otherwise.
        """
        if name is None:
            name, ok = QtWidgets.QInputDialog.getText(
                self, "New Table", "Enter table name:"
            )
            if not ok or not name:
                return False

        if datastreams is None:
            datastreams = []

        name = str(name).strip()


        # Check if tab exists in the UI
        tab_index = -1
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == name:
                tab_index = i
                break

        # If both are there already
        if name in self.tables and tab_index != -1:
            QtWidgets.QMessageBox.warning(
                self, "Error", f"Table '{name}' already exists!"
            )
            return False
        else:
            table_widget = DatastreamTableWidget(
                datastreams=datastreams,
                redvypr=self.redvypr,
                show_apply_button=False
            )
            table_widget.datastreams_changed.connect(
                lambda ds: self.on_datastreams_changed(name, ds)
            )

            self.tab_widget.addTab(table_widget, name)
            self.tables[name] = datastreams
            self.tables_changed.emit(self.tables)  # Emit on add
            return True

    def rename_tab(self):
        """Rename the current tab."""
        current_index = self.tab_widget.currentIndex()
        if current_index == -1:
            return

        old_name = self.tab_widget.tabText(current_index)
        new_name, ok = QtWidgets.QInputDialog.getText(
            self, "Rename Table", "Enter new name:", text=old_name
        )
        if not ok or not new_name or new_name == old_name:
            return

        if new_name in self.tables:
            QtWidgets.QMessageBox.warning(
                self, "Error", f"Table '{new_name}' already exists!"
            )
            return

        self.tables[new_name] = self.tables.pop(old_name)
        self.tab_widget.setTabText(current_index, new_name)
        self.tables_changed.emit(self.tables)  # Emit on rename

    def remove_tab(self, index):
        """Remove the tab at the given index."""
        name = self.tab_widget.tabText(index)
        self.tab_widget.removeTab(index)
        del self.tables[name]
        self.tables_changed.emit(self.tables)  # Emit on remove

    def on_datastreams_changed(self, table_name, datastreams):
        """Update internal tables dictionary and emit signal."""
        self.tables[table_name] = datastreams
        self.tables_changed.emit(self.tables)  # Emit on datastream changes

    def get_tables(self):
        """Return the current tables dictionary."""
        return self.tables.copy()





class SqliteExtendedConfigWidget(QtWidgets.QWidget):
    """Widget for extended SQLite configurations (rotation, etc.)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QtWidgets.QFormLayout()

        # --- Rotation Section ---
        rotation_group = QtWidgets.QGroupBox("File Rotation")
        rotation_layout = QtWidgets.QFormLayout()

        # Max Size (MB)
        self.size_spin = QtWidgets.QDoubleSpinBox()
        self.size_spin.setRange(0.1, 9999.0)
        self.size_spin.setSuffix(" MB")
        self.size_spin.setValue(100.0)
        rotation_layout.addRow("Max File Size:", self.size_spin)

        # Check Interval (Packets)
        self.interval_spin = QtWidgets.QSpinBox()
        self.interval_spin.setRange(1, 10000)
        self.interval_spin.setValue(100)
        self.interval_spin.setSuffix(" Packets")
        rotation_layout.addRow("Check Interval:", self.interval_spin)

        # Naming Format
        self.format_edit = QtWidgets.QLineEdit("{base_name}_{index}.db")
        rotation_layout.addRow("File Naming Format:", self.format_edit)

        rotation_group.setLayout(rotation_layout)
        layout.addRow(rotation_group)

        # --- Additional groups can be added here ---
        self.setLayout(layout)





class SqliteConfigWidgetExtended(QtWidgets.QWidget):
    db_config_changed = QtCore.Signal(dict)

    def __init__(self, initial_config: SqliteConfigExtended, parent=None, redvypr = None):
        super().__init__(parent)
        self.redvypr = redvypr
        self.config = initial_config
        self.extended_config_widget = SqliteExtendedConfigWidget()
        self.extended_config_dialog = QtWidgets.QDialog(self)
        self.extended_config_dialog.setWindowTitle("SQLite Extended Configuration")
        self.extended_config_dialog.setLayout(QtWidgets.QVBoxLayout())
        self.extended_config_dialog.layout().addWidget(self.extended_config_widget)
        self.extended_config_dialog.setModal(True)

        self.setup_ui()

    def setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        layout = QtWidgets.QFormLayout()
        layout.setVerticalSpacing(4)
        layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        # 1. Base File Path
        self.path_edit = QtWidgets.QLineEdit(self.config.filepath)
        self.path_edit.textChanged.connect(self.config_changed)
        self.browse_btn = QtWidgets.QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.handle_browse)

        file_layout = QtWidgets.QHBoxLayout()
        file_layout.addWidget(self.path_edit)
        file_layout.addWidget(self.browse_btn)
        layout.addRow("Database Name/Path:", file_layout)

        # 2. Rotation Toggle with Config Button
        rotation_layout = QtWidgets.QHBoxLayout()
        self.rotate_cb = QtWidgets.QCheckBox("Enable File Rotation (Limit Size)")
        self.rotate_cb.setChecked(self.config.max_file_size_mb is not None)
        self.rotate_cb.stateChanged.connect(self.toggle_rotation_ui)
        self.rotate_cb.stateChanged.connect(self.config_changed)

        self.config_btn = QtWidgets.QPushButton("Config")
        self.config_btn.clicked.connect(self.show_extended_config)
        self.config_btn.setEnabled(self.rotate_cb.isChecked())

        rotation_layout.addWidget(self.rotate_cb)
        rotation_layout.addWidget(self.config_btn)
        layout.addRow(rotation_layout)

        # 3. Live Preview Label
        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setStyleSheet("color: gray; font-style: italic; font-size: 11px;")
        self.preview_label.setWordWrap(True)
        self.preview_label.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        layout.addRow("Filename Preview:", self.preview_label)

        # --- New Checkboxes ---
        # Save Whole Packets
        self.save_whole_packets_cb = QtWidgets.QCheckBox("Save Whole Packets")
        self.save_whole_packets_cb.setChecked(getattr(self.config, "save_whole_packets", False))
        self.save_whole_packets_cb.setEnabled(False)
        self.save_whole_packets_cb.stateChanged.connect(self.config_changed)
        layout.addRow(self.save_whole_packets_cb)

        # Save Metadata
        self.save_metadata_cb = QtWidgets.QCheckBox("Save Metadata")
        self.save_metadata_cb.setChecked(getattr(self.config, "save_metadata", False))
        self.save_metadata_cb.setEnabled(False)
        self.save_metadata_cb.stateChanged.connect(self.config_changed)
        layout.addRow(self.save_metadata_cb)

        # Save Single Datastreams in Tables (mit Config-Button)
        datastream_layout = QtWidgets.QHBoxLayout()
        self.save_datastreams_cb = QtWidgets.QCheckBox("Save Single Datastreams in Tables")
        self.save_datastreams_cb.setChecked(getattr(self.config, "save_datastreams", False))
        self.save_datastreams_cb.stateChanged.connect(self.toggle_datastream_ui)
        self.save_datastreams_cb.stateChanged.connect(self.config_changed)

        self.datastream_config_btn = QtWidgets.QPushButton("Config")
        self.datastream_config_btn.clicked.connect(self.show_datastream_config)
        self.datastream_config_btn.setEnabled(self.save_datastreams_cb.isChecked())

        datastream_layout.addWidget(self.save_datastreams_cb)
        datastream_layout.addWidget(self.datastream_config_btn)
        layout.addRow(datastream_layout)

        # --- Test/Query Buttons ---
        self.test_button = QtWidgets.QPushButton("Test DB Connection")
        self.test_button.setIcon(qtawesome.icon('mdi6.database-outline'))

        self.query_button = QtWidgets.QPushButton("Query DB")
        self.query_button.setIcon(qtawesome.icon('mdi6.database-search-outline'))

        self.button_layout = QtWidgets.QHBoxLayout()
        self.button_layout.addWidget(self.test_button)
        self.button_layout.addWidget(self.query_button)

        self.test_button.clicked.connect(self.test_connection_clicked)
        self.query_button.clicked.connect(self.query_db_clicked)

        # UI Initialization
        self.toggle_rotation_ui()
        self.toggle_datastream_ui()
        self.update_preview()

        main_layout.addLayout(layout)
        main_layout.addLayout(self.button_layout)

    def show_extended_config(self):
        """Shows the extended configuration dialog (modal)."""
        self.extended_config_dialog.exec_()

    def show_datastream_config(self):
        """Shows the datastream configuration dialog (modal)."""
        # Platzhalter für das zukünftige Datastream-Konfig-Widget
        tables_local = copy.deepcopy(self.config.tables)
        self.datastreamsconfigwidget = DatastreamsTabsWidget(redvypr=self.redvypr, tables=tables_local)
        self.datastreamsconfigwidget.tables_changed.connect(self._update_datastreams_dict)
        self.datastreamsconfigwidget.show()

    def _update_datastreams_dict(self, datastreamsdict):
        print("Updating tables",datastreamsdict)
        self.config.tables = datastreamsdict
        self.config_changed()

    def toggle_rotation_ui(self):
        """Enables/disables the rotation Config button."""
        enabled = self.rotate_cb.isChecked()
        self.config_btn.setEnabled(enabled)
        self.preview_label.setVisible(enabled)

    def toggle_datastream_ui(self):
        """Enables/disables the datastream Config button."""
        enabled = self.save_datastreams_cb.isChecked()
        self.datastream_config_btn.setEnabled(enabled)

    def update_preview(self):
        """Updates the filename preview."""
        config = self.get_config()
        preview_path = RedvyprSqliteDbExtended.format_filename(
            base_name=config.filepath,
            file_format=config.file_format,
            file_index=1,
            max_file_size_mb=config.max_file_size_mb
        )
        self.preview_label.setText(os.path.basename(preview_path))

    def get_config(self) -> SqliteConfigExtended:
        """Returns the current configuration."""
        max_size = self.extended_config_widget.size_spin.value() if self.rotate_cb.isChecked() else None
        return SqliteConfigExtended(
            dbtype="sqlite_ext",
            filepath=self.path_edit.text(),
            max_file_size_mb=max_size,
            size_check_interval=self.extended_config_widget.interval_spin.value(),
            file_format=self.extended_config_widget.format_edit.text(),
            tables=self.config.tables,
            save_whole_packets=self.save_whole_packets_cb.isChecked(),
            save_metadata=self.save_metadata_cb.isChecked(),
            save_datastreams=self.save_datastreams_cb.isChecked(),
        )

    def config_changed(self):
        """Updates the preview and emits the config signal."""
        self.update_preview()
        config = self.get_config()
        self.db_config_changed.emit(config.model_dump())

    def handle_browse(self):
        """Opens the file dialog."""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Select SQLite Database", "",
            "DB Files (*.db *.sqlite);;All Files (*)"
        )
        if path:
            self.path_edit.setText(path)

    def query_db_clicked(self):
        """Opens the query dialog."""
        config = self.get_config()
        db = RedvyprDBFactoryExtended.create(config)
        self.query_widget = DBQueryDialogExtended(db_instance=db)
        self.query_widget.show()

    def test_connection_clicked(self):
        """Tests the database connection."""
        pconfig = self.get_config()
        try:
            db = RedvyprDBFactoryExtended.create(pconfig)
            diag = DBStatusDialogExtended(db, self)
            diag.exec_()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Connection Error", f"Failed: {str(e)}")




class TimescaleDbConfigWidgetExtended(QtWidgets.QWidget):
    """
    A dedicated widget for configuring and testing
    database connection settings based on a Pydantic model.
    """
    db_config_changed = QtCore.Signal(dict)
    def __init__(self, initial_config: TimescaleConfigExtended, parent=None):
        super().__init__(parent)
        self.initial_config = initial_config
        self.input_fields: typing.Dict[str, QtWidgets.QLineEdit] = {}
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

            line_edit.textChanged.connect(self.config_changed)
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

    def config_changed(self):
        config = self.get_config()
        print(f"TimescaleDb config changed:{config}")
        self.db_config_changed.emit(config.model_dump())

    def toggle_password_visibility(self, line_edit: QtWidgets.QLineEdit, checked: bool):
        """Toggles the echo mode of the password field based on the button state."""
        if checked:
            line_edit.setEchoMode(QtWidgets.QLineEdit.Normal)
        else:
            line_edit.setEchoMode(QtWidgets.QLineEdit.Password)

    def get_config(self) -> TimescaleConfigExtended:
        """
        Retrieves current values from QLineEdits and creates a new
        TimescaleConfig instance, ensuring proper type conversion.
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
            return TimescaleConfigExtended(**config_data)
        except pydantic.ValidationError as e:
            print(f"Configuration Validation Error: {e}")
            return self.initial_config

    def query_db_clicked(self):
        config = self.get_config()
        db = RedvyprDBFactoryExtended.create(config)
        self.query_widdget = DBQueryDialogExtended(db_instance=db)
        self.query_widdget.show()

    def test_connection_clicked(self):
        # pconfig is an instance of TimescaleConfig
        pconfig = self.get_config()

        try:
            # Instantiate the correct class
            db = RedvyprDBFactoryExtended.create(pconfig)

            # Pass the DB instance to the Dialog.
            # The dialog will handle 'with db:' internally to keep it alive.
            diag = DBStatusDialogExtended(db, self)
            diag.exec_()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Connection Error",
                                           f"Failed: {str(e)}")

    def query_db_clicked_legacy(self):
        config = self.get_config()
        db = RedvyprTimescaleDbExtended(dbname=config.dbname,
                                user=config.user,
                                password=config.password,
                                host=config.host,
                                port=config.port)

        self.query_widdget = DBQueryDialogExtended(db_instance=db)
        self.query_widdget.show()

    def test_connection_clicked_legacy(self):
        # pconfig is an instance of TimescaleConfig
        pconfig = self.get_config()

        try:
            # Factory: Select class based on Pydantic model 'dbtype'
            print("pconfig",pconfig)
            if pconfig.dbtype == "timescaledb":
                db_class = RedvyprTimescaleDbExtended
            elif pconfig.dbtype == "sqlite":  # For future expansion
                #db_class = RedvyprSqliteDb
                pass
            else:
                raise ValueError(f"Unsupported database type: {pconfig.dbtype}")

            # Instantiate the correct class
            db = db_class(
                dbname=pconfig.dbname,
                user=pconfig.user,
                password=pconfig.password,
                host=pconfig.host,
                port=pconfig.port
            )

            # Pass the DB instance to the Dialog.
            # The dialog will handle 'with db:' internally to keep it alive.
            diag = DBStatusDialogExtended(db, self)
            diag.exec_()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Connection Error",
                                           f"Failed: {str(e)}")



class DBStatusDialogExtended(QtWidgets.QDialog):
    """
    A Database Status and Management Dialog.
    Allows users to verify connection health and manually initialize the schema.
    """

    def __init__(self, db_instance, parent=None):
        super().__init__(parent)
        self.db = db_instance

        # Default state ensures dictionary is always subscriptable
        self.status = {
            'engine': 'Unknown',
            'connected': False,
            'tables_exist': False,
            'can_write': False,
            'is_timescale': False
        }

        # Step 1: Perform observational checks
        self.refresh_db_status()

        # Step 2: Configure Dialog window
        self.setWindowTitle(f"Database Status: {self.status.get('engine')}")
        self.setMinimumWidth(480)
        self.setup_ui()

    def refresh_db_status(self):
        """
        Connects to the database to identify engine type and health parameters.
        No structural changes (schema) are made here.
        """
        try:
            with self.db:
                # Discovers engine type and SQL placeholders
                self.db.identify_and_setup()

                # Queries system tables (information_schema) to check health
                health = self.db.check_health()
                if isinstance(health, dict):
                    self.status.update(health)
                    self.status['connected'] = True
        except Exception as e:
            self.status['connected'] = False
            self.status['error'] = str(e)
            self.status['engine'] = "Discovery Failed"

    def setup_ui(self):
        """Creates a modern, icon-driven interface."""
        # Clean up existing layout if this is a refresh
        if self.layout():
            QtWidgets.QWidget().setLayout(self.layout())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(18)

        # --- Section 1: Header ---
        header_layout = QtWidgets.QHBoxLayout()
        is_connected = self.status.get('connected', False)

        # Large status icon
        main_icon = 'mdi6.database-check' if is_connected else 'mdi6.database-off'
        icon_color = "#38A169" if is_connected else "#E53E3E"

        icon_lbl = QtWidgets.QLabel()
        icon_lbl.setPixmap(qtawesome.icon(main_icon, color=icon_color).pixmap(54, 54))

        title_vbox = QtWidgets.QVBoxLayout()
        title_lbl = QtWidgets.QLabel(
            f"<span style='font-size: 18px; font-weight: bold;'>{self.status.get('engine')}</span>")
        subtitle = "TimescaleDB Optimized" if self.status.get(
            'is_timescale') else "Standard SQL Engine"
        subtitle_lbl = QtWidgets.QLabel(subtitle)
        subtitle_lbl.setStyleSheet("color: #718096;")

        title_vbox.addWidget(title_lbl)
        title_vbox.addWidget(subtitle_lbl)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(title_vbox)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Horizontal separator
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setStyleSheet("background-color: #E2E8F0;")
        layout.addWidget(line)

        # --- Section 2: Error Feedback ---
        error_msg = self.status.get('error')
        if error_msg:
            err_panel = QtWidgets.QLabel(f"<b>Connection Error:</b><br>{error_msg}")
            err_panel.setWordWrap(True)
            err_panel.setStyleSheet("""
                background-color: #FFF5F5; color: #C53030; padding: 12px; 
                border: 1px solid #FEB2B2; border-radius: 6px; font-family: monospace;
            """)
            layout.addWidget(err_panel)

        # --- Section 3: Status Grid ---
        grid = QtWidgets.QGridLayout()
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(1, 1)

        def add_status_row(row, label, key, icon_name):
            active = self.status.get(key, False)
            color = "#38A169" if active else "#E53E3E"

            ico = QtWidgets.QLabel()
            ico.setPixmap(qtawesome.icon(icon_name, color=color).pixmap(22, 22))

            txt_label = QtWidgets.QLabel(f"<b>{label}</b>")

            status_text = "Verified / Ready" if active else "Missing / Denied"
            val_lbl = QtWidgets.QLabel(status_text)
            val_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")

            grid.addWidget(ico, row, 0)
            grid.addWidget(txt_label, row, 1)
            grid.addWidget(val_lbl, row, 2)

        add_status_row(0, "Network Link", "connected", 'fa5s.network-wired')
        add_status_row(1, "Tables (Schema)", "tables_exist", 'fa5s.table')
        add_status_row(2, "Write Access", "can_write", 'fa5s.file-signature')

        layout.addLayout(grid)
        layout.addSpacing(10)

        # --- Section 4: Action Button ---
        self.init_btn = QtWidgets.QPushButton(" Initialize Database Schema")
        self.init_btn.setIcon(qtawesome.icon('fa5s.magic'))
        self.init_btn.setFixedHeight(42)

        # User Choice Logic: Enable only if tables are missing and write is allowed
        missing_tables = not self.status.get('tables_exist', False)
        can_write = self.status.get('can_write', False)

        if is_connected and missing_tables and can_write:
            self.init_btn.setEnabled(True)
            self.init_btn.setStyleSheet("""
                QPushButton { background-color: #3182CE; color: white; border-radius: 6px; font-weight: bold; }
                QPushButton:hover { background-color: #2B6CB0; }
            """)
        else:
            self.init_btn.setEnabled(False)
            self.init_btn.setToolTip(
                "Initialization unavailable: Connection issues, tables already exist, or read-only access.")

        self.init_btn.clicked.connect(self.run_manual_init)
        layout.addWidget(self.init_btn)

        # --- Section 5: Dialog Controls ---
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def run_manual_init(self):
        """Executes the setup_schema script upon explicit user confirmation."""
        msg = ("Do you want to create the database tables and metadata schema now?\n\n"
               "This will execute the 'setup_schema' script on the target server.")

        choice = QtWidgets.QMessageBox.question(
            self, "Confirm Schema Setup", msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if choice == QtWidgets.QMessageBox.Yes:
            try:
                # Explicitly call the write operation
                with self.db:
                    self.db.setup_schema()

                QtWidgets.QMessageBox.information(self, "Success",
                                                  "Database schema initialized successfully.")

                # Refresh data and UI to show the new green state
                self.refresh_db_status()
                self.setup_ui()

            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Setup Failed",
                                               f"Could not initialize schema:\n{str(e)}")


class DBQueryDialogExtended(QtWidgets.QDialog):
    """
    Dialog to browse both Packet and Metadata inventory using Tabs.
    """
    items_chosen = QtCore.Signal(list)

    def __init__(self, db_instance, parent=None, select_mode=False):
        super().__init__(parent)
        self.db = db_instance
        self.select_mode = select_mode
        self.selected_data = None

        if self.select_mode:
            self.setWindowTitle("Select Stream from Inventory")
        else:
            self.setWindowTitle("Database Inventory Browser")

        self.resize(1200, 700)  # Etwas breiter wegen der zusätzlichen UUID Spalte
        self.setup_ui()
        self.refresh_data()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # --- Header with Info and Refresh ---
        header = QtWidgets.QHBoxLayout()
        title_vbox = QtWidgets.QVBoxLayout()
        title_label = QtWidgets.QLabel("<b>Database Inventory Overview</b>")
        title_label.setStyleSheet("font-size: 14px;")

        self.db_info_label = QtWidgets.QLabel("Connecting...")
        self.db_info_label.setStyleSheet("color: #444; font-size: 11px;")

        title_vbox.addWidget(title_label)
        title_vbox.addWidget(self.db_info_label)
        header.addLayout(title_vbox)
        header.addStretch()

        self.refresh_button = QtWidgets.QPushButton(" Refresh All")
        self.refresh_button.setIcon(qtawesome.icon('fa5s.sync-alt'))
        self.refresh_button.clicked.connect(self.refresh_data)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        # --- Tabs ---
        self.tabs = QtWidgets.QTabWidget()
        self.packet_table = self._create_table_widget(tabletype="datastream")
        self.tabs.addTab(self.packet_table, qtawesome.icon('fa5s.box'), "Packets")
        self.meta_table = self._create_table_widget(tabletype="metadata")
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

    def _create_table_widget(self, tabletype: typing.Literal["datastream","metadata"]="datastream") -> QtWidgets.QTableWidget:
        """Helper to create a standardized table with the new header order."""
        #print(f"Creating table: {tabletype}")
        table = QtWidgets.QTableWidget()
        table.__tabletype = tabletype
        headers = ["Address", "Packet ID", "Device", "Host", "UUID", "Count",
                   "First Seen", "Last Seen"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        if table.__tabletype == "metadata":
            table.setColumnHidden(1, True) # Packet id
            table.setColumnHidden(2, True)  # device
            table.setColumnHidden(3, True)  # host

        if self.select_mode:
            table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            table.customContextMenuRequested.connect(self.show_context_menu)
            table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        return table

    def refresh_data(self):
        """Fetches data and updates connection info labels."""
        self.status_label.setText("Fetching data...")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)

        try:
            with self.db as connected_db:
                # 1. Update DB Meta Info
                connected_db.identify_and_setup()
                engine = connected_db.engine_type.upper()

                # Dynamic source string based on engine
                if engine == "SQLITE":
                    source = getattr(self.db, 'filepath', 'local db')
                else:
                    params = getattr(self.db, 'conn_params', {})
                    source = f"{params.get('host', 'unknown')}:{params.get('port', '')}"

                self.db_info_label.setText(
                    f"Connected to: <b>{engine}</b> | Source: <i>{source}</i>")

                # 2. Fetch Stats with common keys for both tables
                common_keys = ["redvypr_address", "packetid", "device", "host", "uuid"]
                packet_stats = connected_db.get_unique_combination_stats(
                    keys=common_keys)
                meta_stats = connected_db.get_metadata_info(keys=common_keys)


            # 3. Fill tables
            self._fill_table(self.packet_table, packet_stats)
            self._fill_table(self.meta_table, meta_stats)

            self.status_label.setText(
                f"Updated: {len(packet_stats)} packet streams, {len(meta_stats)} metadata entries.")

        except Exception as e:
            self.db_info_label.setText("Connection failed.")
            QtWidgets.QMessageBox.critical(self, "Error", f"Fetch failed: {e}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _fill_table(self, table: QtWidgets.QTableWidget, stats: list):
        """Fills the table according to the new header index mapping."""
        table.setRowCount(0)
        table.setRowCount(len(stats))

        for row_idx, entry in enumerate(stats):
            # Mapping strictly following your header order
            items = [
                entry.get('redvypr_address', '-'),  # 0
                entry.get('packetid', '-'),  # 1
                entry.get('device', '-'),  # 2
                entry.get('host', '-'),  # 3
                entry.get('uuid', '-'),  # 4
                str(entry.get('count', 0)),  # 5
                entry.get('first_seen', 'N/A'),  # 6
                entry.get('last_seen', 'N/A')  # 7
            ]

            for col_idx, text in enumerate(items):
                item = QtWidgets.QTableWidgetItem(text)
                # Add id to be able to get the entry for later query of db
                if table.__tabletype == "metadata":
                    item.__ids__ = entry.get('ids', [])  # 7

                if col_idx == 5:  # Count column
                    item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                table.setItem(row_idx, col_idx, item)

        # Style & Resizing
        header = table.horizontalHeader()
        table.resizeColumnsToContents()
        header.setStretchLastSection(False)

        # Cap width for long strings
        for i in [0, 1, 4]:  # Address, Packet ID, UUID
            if table.columnWidth(i) > 250:
                table.setColumnWidth(i, 250)

        for i in range(table.columnCount()):
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.Interactive)

        table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

    def show_context_menu(self, position):
        table = self.sender()
        selected_rows = sorted(
            list(set(index.row() for index in table.selectedIndexes())))
        if not selected_rows:
            return

        if table.__tabletype == "datastream":
            menu = QtWidgets.QMenu()
            action_text = f"Add {len(selected_rows)} selected item(s) to Replay"
            select_action = menu.addAction(qtawesome.icon('fa5s.plus-circle'), action_text)
        else:
            menu = QtWidgets.QMenu()
            action_text = f"Get metadata from {len(selected_rows)} selected item(s) for Replay"
            select_action = menu.addAction(qtawesome.icon('fa5s.plus-circle'),
                                           action_text)

        action = menu.exec_(table.viewport().mapToGlobal(position))
        if action == select_action:
            self.emit_selected_items(table, selected_rows)

    def emit_selected_items(self, table, rows):
        """Extracts data with updated index mapping for Replay."""
        results = []
        if table.__tabletype == "datastream":
            for row in rows:
                results.append({
                    "address": table.item(row, 0).text(),
                    "packetid": table.item(row, 1).text(),
                    "uuid": table.item(row, 4).text(),
                    "tstart": table.item(row, 6).text(),
                    "tend": table.item(row, 7).text(),
                    "metadata":None
                })
        else: # Look at the metadata and interprete it
            with self.db as connected_db:
                for row in rows:
                    ids = table.item(row, 0).__ids__
                    metadatalist = connected_db.get_metadata_by_ids(ids)
                    print("Metadatalist",metadatalist)
                    results.append({
                        "address": table.item(row, 0).text(),
                        "packetid": table.item(row, 1).text(),
                        "uuid": table.item(row, 4).text(),
                        "tstart": table.item(row, 6).text(),
                        "tend": table.item(row, 7).text(),
                        "metadata": metadatalist
                    })
        if results:
            self.items_chosen.emit(results)
            self.status_label.setText(
                f"Sent {len(results)} items to Replay controller.")




