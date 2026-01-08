import typing

import pydantic
import qtawesome
from PyQt6 import QtWidgets, QtCore, QtGui
from qtpy import QtWidgets
from .timescaledb import RedvyprTimescaleDb, DatabaseConfig, TimescaleConfig, SqliteConfig, RedvyprDBFactory

from qtpy import QtWidgets, QtCore
import typing


class DBConfigWidget(QtWidgets.QWidget):
    """
    A container widget that switches between TimescaleDbConfigWidget
    and SqliteConfigWidget based on the selected dbtype.
    """
    db_type_changed = QtCore.Signal(dict)
    db_config_changed = QtCore.Signal(dict)
    def __init__(self, initial_config: DatabaseConfig, parent=None):
        super().__init__(parent)
        self.current_config = initial_config
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # --- 1. Selection Header ---
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.addWidget(QtWidgets.QLabel("<b>Database Engine:</b>"))

        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItems(["timescaledb", "sqlite"])

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
        self.timescale_ui = TimescaleDbConfigWidget(
            initial_config=self.current_config if isinstance(self.current_config,
                                                             TimescaleConfig) else TimescaleConfig()
        )

        self.sqlite_ui = SqliteConfigWidget(
            initial_config=self.current_config if isinstance(self.current_config,
                                                             SqliteConfig) else SqliteConfig()
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
        if dbtype == "timescaledb":
            self.stack.setCurrentWidget(self.timescale_ui)
            config = self.timescale_ui.get_config()
        elif dbtype == "sqlite":
            self.stack.setCurrentWidget(self.sqlite_ui)
            config = self.sqlite_ui.get_config()

        print(f"DB type changed:{config}")
        self.db_type_changed.emit(config.model_dump())
    def get_config(self) -> DatabaseConfig:
        """Returns the specific Pydantic model from the active sub-widget."""
        if self.type_combo.currentText() == "timescaledb":
            return self.timescale_ui.get_config()
        else:
            return self.sqlite_ui.get_config()


class SqliteConfigWidget(QtWidgets.QWidget):
    db_config_changed = QtCore.Signal(dict)
    def __init__(self, initial_config: SqliteConfig, parent=None):
        super().__init__(parent)
        self.config = initial_config
        self.setup_ui()

    def setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        layout = QtWidgets.QFormLayout()

        self.path_edit = QtWidgets.QLineEdit(self.config.filepath)
        self.path_edit.textChanged.connect(self.config_changed)
        self.browse_btn = QtWidgets.QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.handle_browse)

        file_layout = QtWidgets.QHBoxLayout()
        file_layout.addWidget(self.path_edit)
        file_layout.addWidget(self.browse_btn)

        layout.addRow("Database File:", file_layout)

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
        main_layout.addLayout(layout)
        main_layout.addLayout(self.button_layout)

    def config_changed(self):
        config = self.get_config()
        print(f"Sqlite config changed:{config}")
        self.db_config_changed.emit(config.model_dump())

    def handle_browse(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Select SQLite Database", "",
            "DB Files (*.db *.sqlite);;All Files (*)"
        )
        if path:
            self.path_edit.setText(path)

    def get_config(self) -> SqliteConfig:
        return SqliteConfig(dbtype="sqlite", filepath=self.path_edit.text())


    def query_db_clicked(self):
        config = self.get_config()
        db = RedvyprDBFactory.create(config)
        self.query_widdget = DBQueryDialog(db_instance=db)
        self.query_widdget.show()

    def test_connection_clicked(self):
        # pconfig is an instance of TimescaleConfig
        pconfig = self.get_config()
        print("Testing connection")
        try:
            # Instantiate the correct class
            db = RedvyprDBFactory.create(pconfig)
            print("DB",db)

            # Pass the DB instance to the Dialog.
            # The dialog will handle 'with db:' internally to keep it alive.
            diag = DBStatusDialog(db, self)
            diag.exec_()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Connection Error",
                                           f"Failed: {str(e)}")

class TimescaleDbConfigWidget(QtWidgets.QWidget):
    """
    A dedicated widget for configuring and testing
    database connection settings based on a Pydantic model.
    """
    db_config_changed = QtCore.Signal(dict)
    def __init__(self, initial_config: TimescaleConfig, parent=None):
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

    def get_config(self) -> TimescaleConfig:
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
            return TimescaleConfig(**config_data)
        except pydantic.ValidationError as e:
            print(f"Configuration Validation Error: {e}")
            return self.initial_config

    def query_db_clicked(self):
        config = self.get_config()
        db = RedvyprDBFactory.create(config)
        self.query_widdget = DBQueryDialog(db_instance=db)
        self.query_widdget.show()

    def test_connection_clicked(self):
        # pconfig is an instance of TimescaleConfig
        pconfig = self.get_config()

        try:
            # Instantiate the correct class
            db = RedvyprDBFactory.create(pconfig)

            # Pass the DB instance to the Dialog.
            # The dialog will handle 'with db:' internally to keep it alive.
            diag = DBStatusDialog(db, self)
            diag.exec_()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Connection Error",
                                           f"Failed: {str(e)}")

    def query_db_clicked_legacy(self):
        config = self.get_config()
        db = RedvyprTimescaleDb(dbname=config.dbname,
                                user=config.user,
                                password=config.password,
                                host=config.host,
                                port=config.port)

        self.query_widdget = DBQueryDialog(db_instance=db)
        self.query_widdget.show()

    def test_connection_clicked_legacy(self):
        # pconfig is an instance of TimescaleConfig
        pconfig = self.get_config()

        try:
            # Factory: Select class based on Pydantic model 'dbtype'
            print("pconfig",pconfig)
            if pconfig.dbtype == "timescaledb":
                db_class = RedvyprTimescaleDb
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
            diag = DBStatusDialog(db, self)
            diag.exec_()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Connection Error",
                                           f"Failed: {str(e)}")



class DBStatusDialog(QtWidgets.QDialog):
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


class DBQueryDialog(QtWidgets.QDialog):
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
        self.packet_table = self._create_table_widget()
        self.tabs.addTab(self.packet_table, qtawesome.icon('fa5s.box'), "Packets")
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
        """Helper to create a standardized table with the new header order."""
        table = QtWidgets.QTableWidget()
        headers = ["Address", "Packet ID", "Device", "Host", "UUID", "Count",
                   "First Seen", "Last Seen"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

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

        menu = QtWidgets.QMenu()
        action_text = f"Add {len(selected_rows)} selected item(s) to Replay"
        select_action = menu.addAction(qtawesome.icon('fa5s.plus-circle'), action_text)

        action = menu.exec_(table.viewport().mapToGlobal(position))
        if action == select_action:
            self.emit_selected_items(table, selected_rows)

    def emit_selected_items(self, table, rows):
        """Extracts data with updated index mapping for Replay."""
        results = []
        for row in rows:
            results.append({
                "address": table.item(row, 0).text(),
                "packetid": table.item(row, 1).text(),
                "uuid": table.item(row, 4).text(),
                "tstart": table.item(row, 6).text(),
                "tend": table.item(row, 7).text()
            })

        if results:
            self.items_chosen.emit(results)
            self.status_label.setText(
                f"Sent {len(results)} items to Replay controller.")




class DBQueryDialog_legacy(QtWidgets.QDialog):
    """
    Dialog to browse both Packet and Metadata inventory using Tabs.
    """
    items_chosen = QtCore.Signal(list)
    def __init__(self, db_instance, parent=None, select_mode=False):
        super().__init__(parent)
        self.db = db_instance
        self.select_mode = select_mode # New flag
        self.selected_data = None # Storage for result
        if self.select_mode:
            self.setWindowTitle("Select Stream from Inventory")
        else:
            self.setWindowTitle("Database Inventory Browser")
        self.resize(1100, 700)

        self.setup_ui()
        self.refresh_data()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        ## --- Header with Refresh ---
        #header = QtWidgets.QHBoxLayout()
        #header.addWidget(QtWidgets.QLabel("Database Inventory Overview"))
        #header.addStretch()

        # --- Header with Info and Refresh ---
        header = QtWidgets.QHBoxLayout()

        # Titel und DB-Info Container
        title_vbox = QtWidgets.QVBoxLayout()
        title_label = QtWidgets.QLabel("<b>Database Inventory Overview</b>")
        title_label.setStyleSheet("font-size: 14px;")

        # Das neue Label für die DB-Details
        self.db_info_label = QtWidgets.QLabel("Connecting...")
        self.db_info_label.setStyleSheet("color: #666; font-size: 11px;")

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

    def get_selection(self):
        """Returns the address and time range of the selected row."""
        table = self.tabs.currentWidget()
        selected_items = table.selectedItems()
        if not selected_items:
            return None

        row = selected_items[0].row()
        # Mapping based on your table columns:
        # 0: Address, 5: First Seen, 6: Last Seen
        address = table.item(row, 0).text()
        first_seen = table.item(row, 5).text()
        last_seen = table.item(row, 6).text()

        return {
            "address": address,
            "tstart": first_seen,
            "tend": last_seen
        }

    def _create_table_widget(self) -> QtWidgets.QTableWidget:
        """Helper to create a standardized table."""
        table = QtWidgets.QTableWidget()
        headers = ["Address", "Packet ID", "UUID", "Device", "Host", "Count",
                   "First Seen", "Last Seen"]

        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        if self.select_mode:
            # Enable Custom Context Menu
            table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            table.customContextMenuRequested.connect(self.show_context_menu)
            table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        return table

    def refresh_data(self):
        """Fetches data and updates connection info."""
        self.status_label.setText("Fetching data...")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)

        try:
            with self.db as connected_db:
                # --- DB Info Label aktualisieren ---
                connected_db.identify_and_setup()
                engine = connected_db.engine_type.upper()

                # Wir versuchen an die Adresse/Datei zu kommen
                # Je nachdem, ob es SQLite (filepath) oder Postgres (host) ist
                if engine == "SQLITE":
                    # Falls du das Config-Objekt in der DB-Klasse speicherst:
                    source = getattr(self.db, 'filepath', 'local file')
                else:
                    host = self.db.conn_params['host']
                    port = self.db.conn_params['port']
                    source = f"{host}:{port}" if port else host

                self.db_info_label.setText(
                    f"Connected to: <b>{engine}</b> | Source: <i>{source}</i>")

                # --- Daten fetchen ---
                packet_stats = connected_db.get_unique_combination_stats(
                    keys=["redvypr_address", "packetid", "device", "host"]
                )
                meta_stats = connected_db.get_metadata_info(
                    keys=["redvypr_address", "uuid", "device", "host"]
                )

            self._fill_table(self.packet_table, packet_stats, "packetid")
            self._fill_table(self.meta_table, meta_stats, "uuid")

            self.status_label.setText(
                f"Updated: {len(packet_stats)} packet streams, {len(meta_stats)} metadata entries.")

        except Exception as e:
            self.db_info_label.setText("Connection failed.")
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

    def show_context_menu(self, position):
        """Creates and shows the right-click menu."""
        table = self.sender() # Get the table that was clicked
        selected_rows = self._get_unique_selected_rows(table)
        if not selected_rows:
            return

        menu = QtWidgets.QMenu()
        count = len(selected_rows)
        action_text = f"Add {count} selected item(s) to Replay" if self.select_mode else "Copy Selection"

        select_action = menu.addAction(qtawesome.icon('fa5s.plus-circle'), action_text)
        action = menu.exec_(table.viewport().mapToGlobal(position))

        if action == select_action:
            self.emit_selected_items(table, selected_rows)

    def _get_unique_selected_rows(self, table):
        """Gibt eine sortierte Liste der eindeutigen Zeilen-Indizes zurück."""
        return sorted(list(set(index.row() for index in table.selectedIndexes())))

    def emit_selected_items(self, table, rows):
        """Extrahiert Daten aus allen gewählten Zeilen und sendet sie als Liste."""
        results = []
        for row in rows:
            data = {
                "address": table.item(row, 0).text(),
                "id": table.item(row, 1).text(),
                "tstart": table.item(row, 5).text(),
                "tend": table.item(row, 6).text()
            }
            results.append(data)

        if results:
            self.items_chosen.emit(results)
            self.status_label.setText(f"Added {len(results)} items to settings.")




