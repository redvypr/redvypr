from datetime import timezone, datetime
from redvypr.redvypr_address import RedvyprAddress

from PyQt6 import QtWidgets, QtCore, QtGui


class RedvyprMetadataTable(QtWidgets.QWidget):
    """
    A self-contained custom PyQt6 Widget executing queries and registrations
    against a passed redvypr master instance object.

    This widget features sorting, checkbox-based column filtering, and a
    read-only address visualization field at the top.

    Parameters
     Meso-level structural parameters for PyQt initialization.
    redvypr_instance : object
        The master instance of the redvypr backend layout engine.
    redvypr_address : object or str, optional
        The active device or node address mapping reference. Default is None.
    parent : QWidget, optional
        The parent widget container within the Qt hierarchy. Default is None.

    Attributes
    ----------
    redvypr : object
        Stored reference to the master backend layout instance.
    redvypr_address : object or str
        Stored reference to the target device or node path.
    address_edit : QLineEdit
        A read-only text input field used to safely display and copy the target address.
    table_view : QTableView
        The main tabular layout rendering filtered or sorted metadata structures.
    base_model : RedvyprMetadataModel
        The underlying standard model serving raw data chunks from the backend.
    proxy_model : MultiValueFilterProxyModel
        The custom sorting and checkbox filtering proxy layout layer.
    btn_refresh : QPushButton
        Action button to reload backend items and clear active search filters.
    btn_add_row : QPushButton
        Action button to inject an editable blank row state inside the workspace.
    btn_save_row : QPushButton
        Action button committing newly validation-passed draft row entries.
    """

    def __init__(self, redvypr_instance, redvypr_address=None, parent=None):
        super().__init__(parent)
        self.redvypr = redvypr_instance
        self.redvypr_address = redvypr_address

        #if self.redvypr_address is None:
        #    self.redvypr_address = RedvyprAddress("@")

        if self.redvypr_address:
            raddr = RedvyprAddress(self.redvypr_address)
            self.redvypr_address_datakey_orig = raddr.datakey




        # Primary Structural Layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Initialize the read-only target address input display field
        self.address_edit_layout = QtWidgets.QHBoxLayout()

        self.address_edit = QtWidgets.QLineEdit()
        self.address_edit.setReadOnly(True)
        self.address_edit.setStyleSheet(
            "background-color: #f0f0f0; color: #555555; font-weight: bold; padding: 4px;"
        )
        self.address_edit_layout.addWidget(QtWidgets.QLabel("Target Address"))
        self.address_edit_layout.addWidget(self.address_edit)

        if self.redvypr_address and self.redvypr_address_datakey_orig is None:
            self.address_edit_checkbox = QtWidgets.QCheckBox("No datakeys")
            self.address_edit_layout.addWidget(self.address_edit_checkbox)
            self.address_edit_checkbox.toggled.connect(self.nodatakeys_toogled)

        # Populate and embed address field if explicitly provided
        if self.redvypr_address is not None:
            self.address_edit.setText(f"{str(self.redvypr_address)}")
            layout.addLayout(self.address_edit_layout)
        else:
            self.address_edit_layout.hide()

        # QTableView setup
        self.table_view = QtWidgets.QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)

        # Enable tabular sorting behavior
        self.table_view.setSortingEnabled(True)

        # Custom Context Menu for Filter Options on Header
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(100)
        header.setStretchLastSection(True)
        header.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.open_header_filter_menu)

        layout.addWidget(self.table_view)

        # Initialize Base Model
        self.base_model = RedvyprMetadataModel(self.redvypr)

        # Set up Proxy Model for Sorting & Filtering
        self.proxy_model = MultiValueFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.base_model)

        # Bind proxy framework layer to view instead of base model directly
        self.table_view.setModel(self.proxy_model)

        # Bottom control actions layout assembly
        button_layout = QtWidgets.QHBoxLayout()

        self.btn_refresh = QtWidgets.QPushButton("Refresh Table")
        self.btn_refresh.clicked.connect(self.refresh_and_clear_filters)

        self.btn_add_row = QtWidgets.QPushButton("Insert New Row")
        self.btn_add_row.clicked.connect(self.addNewRowTrack)

        self.btn_save_row = QtWidgets.QPushButton("Commit Selected Row")
        self.btn_save_row.clicked.connect(self.commitSelectedRowTrack)
        self.btn_save_row.setEnabled(False)

        button_layout.addWidget(self.btn_refresh)
        button_layout.addWidget(self.btn_add_row)
        button_layout.addWidget(self.btn_save_row)
        layout.addLayout(button_layout)

        # Bind selection event triggers across the model layout framework
        self.table_view.selectionModel().selectionChanged.connect(
            self.onSelectionChanged)

        # Initialize background data population routine
        self.base_model.reload_from_backend(redvypr_address=self.redvypr_address)

    def nodatakeys_toogled(self):
        flag_datakeys = self.address_edit_checkbox.isChecked()
        if flag_datakeys:
            self.redvypr_address.add_datakey('!')
            print("New address", self.redvypr_address)
        else:
            self.redvypr_address.delete_datakey()
            print("New address", self.redvypr_address)

        self.address_edit.setText(f"{str(self.redvypr_address)}")
        self.refresh_and_clear_filters()

    def refresh_and_clear_filters(self):
        """
        Reloads backend data mappings and purges all active proxy filtering configurations.
        """
        self.proxy_model._column_filters.clear()
        self.proxy_model.invalidateFilter()
        self.base_model.reload_from_backend(redvypr_address=self.redvypr_address)

    def open_header_filter_menu(self, position):
        """
        Generates a dynamic menu containing unique checkboxes for filtering column entries.

        Parameters
        ----------
        position : QPoint
            The relative cursor coordinate location where the right-click event originated.
        """
        header = self.table_view.horizontalHeader()
        column_idx = header.logicalIndexAt(position)

        if column_idx == -1:
            return

        # Extract all unique stringified cell values present across this column
        unique_values = set()
        for row in range(self.base_model.rowCount()):
            idx = self.base_model.index(row, column_idx)
            val = str(self.base_model.data(idx, QtCore.Qt.ItemDataRole.DisplayRole))
            unique_values.add(val)

        sorted_values = sorted(list(unique_values))

        # Generate Context Menu Container
        menu = QtWidgets.QMenu(self)
        menu.setTitle(
            f"Filter Column: {self.base_model.headerData(column_idx, QtCore.Qt.Orientation.Horizontal)}")

        # Append Meta Actions (Select All / Unselect All)
        action_select_all = menu.addAction("Select All")
        action_unselect = menu.addAction("Unselect All")
        menu.addSeparator()

        # Build dynamic checkboxes wrapped in QWidgetAction objects
        checkbox_actions = []
        currently_allowed = self.proxy_model._column_filters.get(column_idx, unique_values)

        for val in sorted_values:
            container = QtWidgets.QWidgetAction(menu)
            checkbox = QtWidgets.QCheckBox(val, menu)
            checkbox.setChecked(val in currently_allowed)
            container.setDefaultWidget(checkbox)
            menu.addAction(container)
            checkbox_actions.append((val, checkbox))

        # Inline handler function configurations
        def select_all_triggered():
            for _, cb in checkbox_actions: cb.setChecked(True)

        def unselect_all_triggered():
            for _, cb in checkbox_actions: cb.setChecked(False)

        action_select_all.triggered.connect(select_all_triggered)
        action_unselect.triggered.connect(unselect_all_triggered)

        # Show context menu at global coordinate mapping point
        result_action = menu.exec(header.mapToGlobal(position))

        # Inspect checkboxes check states upon operational closure
        allowed_results = [val for val, cb in checkbox_actions if cb.isChecked()]

        if len(allowed_results) == len(sorted_values):
            # All items match -> wipe out explicit filter rules to save computation overhead
            self.proxy_model.set_column_filter_values(column_idx, None)
        else:
            self.proxy_model.set_column_filter_values(column_idx, allowed_results)

    def addNewRowTrack(self):
        """
        Appends an uncommitted empty draft data sequence inside the local dataset model.

        Maps target workspace indexes through the proxy model to immediately set focus
        and open interactive grid editors for the newly inserted record.
        """
        new_row_idx = self.base_model.insert_empty_row(address=self.redvypr_address)

        # Map indices cleanly back through proxy layout boundaries
        base_index = self.base_model.index(new_row_idx, 1)
        proxy_index = self.proxy_model.mapFromSource(base_index)

        self.table_view.setCurrentIndex(proxy_index)
        self.table_view.edit(proxy_index)

    def onSelectionChanged(self, selected, deselected):
        """
        Slot triggered upon changing cell selections inside the table workspace view.

        Evaluates if the newly selected entity represents an uncommitted draft row item,
        and dynamically toggles the confirmation commit action button.

        Parameters
        ----------
        selected : QItemSelection
            The collection of index items selected during the action loop.
        deselected : QItemSelection
            The collection of index items discarded during the action loop.
        """
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            self.btn_save_row.setEnabled(False)
            return

        # Map proxy view selection indices back to source data structures
        proxy_index = indexes[0]
        base_index = self.proxy_model.mapToSource(proxy_index)
        current_row = base_index.row()

        # Enable commit operations exclusively for newly generated draft configurations
        is_draft = current_row >= len(self.base_model._raw_data)
        self.btn_save_row.setEnabled(is_draft)

    def commitSelectedRowTrack(self):
        """
        Commits the active draft configuration row entry back to the target metadata database.

        Triggers standard error visualization blocks upon verification failures or
        reinitializes local grid frameworks on backend storage authorization.
        """
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            return

        proxy_index = indexes[0]
        base_index = self.proxy_model.mapToSource(proxy_index)
        target_row = base_index.row()

        # Fire pipeline request downstream to the persistent layer
        success, message = self.base_model.commit_row_to_backend(target_row)

        if success:
            QtWidgets.QMessageBox.information(self, "Success",
                                              "Metadata successfully committed!")
            self.refresh_and_clear_filters()
        else:
            QtWidgets.QMessageBox.warning(self, "Validation Error",
                                          f"Failed saving entry:\n{message}")

class RedvyprMetadataTable_legacy(QtWidgets.QWidget):
    """
    A self-contained custom PyQt6 Widget executing queries and registrations
    against a passed redvypr master instance object. Now features sorting and
    checkbox-based column filtering.
    """

    def __init__(self, redvypr_instance, redvypr_address=None, parent=None):
        super().__init__(parent)
        self.redvypr = redvypr_instance
        self.redvypr_address = redvypr_address

        # Primary Structural Layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # QTableView setup
        self.table_view = QtWidgets.QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)

        # --- NEW: Enable Sorting ---
        self.table_view.setSortingEnabled(True)

        # --- NEW: Custom Context Menu for Filter Options on Header ---
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive)  # <--- HIER GEÄNDERT
        header.setMinimumSectionSize(100)
        header.setStretchLastSection(True)
        #header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.open_header_filter_menu)

        layout.addWidget(self.table_view)

        # Initialize Base Model
        self.base_model = RedvyprMetadataModel(self.redvypr)

        # --- NEW: Set up Proxy Model for Sorting & Filtering ---
        self.proxy_model = MultiValueFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.base_model)

        # Bind proxy to view instead of base model
        self.table_view.setModel(self.proxy_model)

        # Bottom controls setup
        button_layout = QtWidgets.QHBoxLayout()

        self.btn_refresh = QtWidgets.QPushButton("Refresh Table")
        self.btn_refresh.clicked.connect(self.refresh_and_clear_filters)

        self.btn_add_row = QtWidgets.QPushButton("Insert New Row")
        self.btn_add_row.clicked.connect(self.addNewRowTrack)

        self.btn_save_row = QtWidgets.QPushButton("Commit Selected Row")
        self.btn_save_row.clicked.connect(self.commitSelectedRowTrack)
        self.btn_save_row.setEnabled(False)

        button_layout.addWidget(self.btn_refresh)
        button_layout.addWidget(self.btn_add_row)
        button_layout.addWidget(self.btn_save_row)
        layout.addLayout(button_layout)

        # Selection event triggers (Mapping tracking indexes through proxy framework)
        self.table_view.selectionModel().selectionChanged.connect(
            self.onSelectionChanged)

        # Initialize initial fetch loop
        self.base_model.reload_from_backend(redvypr_address = self.redvypr_address)

    def refresh_and_clear_filters(self):
        """Reloads backend data and drops active proxy filtering configurations."""
        self.proxy_model._column_filters.clear()
        self.proxy_model.invalidateFilter()
        self.base_model.reload_from_backend(redvypr_address = self.redvypr_address)

    def open_header_filter_menu(self, position):
        """Generates a dynamic menu containing unique checkboxes for filtering column entries."""
        header = self.table_view.horizontalHeader()
        column_idx = header.logicalIndexAt(position)

        if column_idx == -1:
            return

        # Extract all unique values present in this column across current rows
        unique_values = set()
        for row in range(self.base_model.rowCount()):
            idx = self.base_model.index(row, column_idx)
            val = str(self.base_model.data(idx, QtCore.Qt.ItemDataRole.DisplayRole))
            unique_values.add(val)

        sorted_values = sorted(list(unique_values))

        # Generate Menu Container
        menu = QtWidgets.QMenu(self)
        menu.setTitle(
            f"Filter Column: {self.base_model.headerData(column_idx, QtCore.Qt.Orientation.Horizontal)}")

        # Meta Controls (Select All / Unselect All)
        action_select_all = menu.addAction("Select All")
        action_unselect = menu.addAction("Unselect All")
        menu.addSeparator()

        # Build individual value checkboxes inside WidgetActions
        checkbox_actions = []
        currently_allowed = self.proxy_model._column_filters.get(column_idx,
                                                                 unique_values)

        for val in sorted_values:
            container = QtWidgets.QWidgetAction(menu)
            checkbox = QtWidgets.QCheckBox(val, menu)
            checkbox.setChecked(val in currently_allowed)
            container.setDefaultWidget(checkbox)
            menu.addAction(container)
            checkbox_actions.append((val, checkbox))

        # Trigger logic loops
        def select_all_triggered():
            for _, cb in checkbox_actions: cb.setChecked(True)

        def unselect_all_triggered():
            for _, cb in checkbox_actions: cb.setChecked(False)

        action_select_all.triggered.connect(select_all_triggered)
        action_unselect.triggered.connect(unselect_all_triggered)

        # Render menu at the exact right-click point
        result_action = menu.exec(header.mapToGlobal(position))

        # Evaluate checkboxes state upon menu closure
        allowed_results = [val for val, cb in checkbox_actions if cb.isChecked()]

        if len(allowed_results) == len(sorted_values):
            # All active -> clear explicit filter overrides
            self.proxy_model.set_column_filter_values(column_idx, None)
        else:
            self.proxy_model.set_column_filter_values(column_idx, allowed_results)

    def addNewRowTrack(self):
        new_row_idx = self.base_model.insert_empty_row()

        # Map indices cleanly back through the proxy to ensure edit states focus correctly
        base_index = self.base_model.index(new_row_idx, 1)
        proxy_index = self.proxy_model.mapFromSource(base_index)

        self.table_view.setCurrentIndex(proxy_index)
        self.table_view.edit(proxy_index)

    def onSelectionChanged(self, selected, deselected):
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            self.btn_save_row.setEnabled(False)
            return

        # Map current proxy layout selection back to base model reference point
        proxy_index = indexes[0]
        base_index = self.proxy_model.mapToSource(proxy_index)
        current_row = base_index.row()

        is_draft = current_row >= len(self.base_model._raw_data)
        self.btn_save_row.setEnabled(is_draft)

    def commitSelectedRowTrack(self):
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            return

        proxy_index = indexes[0]
        base_index = self.proxy_model.mapToSource(proxy_index)
        target_row = base_index.row()

        success, message = self.base_model.commit_row_to_backend(target_row)

        if success:
            QtWidgets.QMessageBox.information(self, "Success",
                                              "Metadata successfully committed!")
            self.refresh_and_clear_filters()
        else:
            QtWidgets.QMessageBox.warning(self, "Validation Error",
                                          f"Failed saving entry:\n{message}")


class RedvyprMetadataModel(QtCore.QAbstractTableModel):
    """
    A dynamic table model that interfaces directly with a redvypr instance's
    metadata lists, supporting in-place editing for new row rows.
    """

    def __init__(self, redvypr_instance):
        super().__init__()
        self.redvypr = redvypr_instance
        self._raw_data = []
        self._headers = ["Source Address", "Key", "Value", "Data Type", "Valid From",
                         "Valid Until", "Constraints"]

        # Track temporary uncommitted rows being edited
        self._uncommitted_rows = {}

    def reload_from_backend(self, redvypr_address = None):
        """Fetches the latest state from the redvypr instance."""
        self.beginResetModel()
        try:
            if redvypr_address:
                #mode = "expanded"
                mode = "all"
            else:
                mode= "all"

            print(f"Metadata for address:{redvypr_address} with mode:{mode}")
            self._raw_data = self.redvypr.get_metadata(address=redvypr_address, mode=mode)
            print("Raw data:", self._raw_data)
            self._uncommitted_rows.clear()
        except Exception as e:
            print(f"Error loading metadata: {e}")
            self._raw_data = []
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._raw_data) + len(self._uncommitted_rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self._headers)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        # Determine if we are looking at real data or a temporary row
        if row < len(self._raw_data):
            row_data = self._raw_data[row]
            is_committed = True
        else:
            row_data = self._uncommitted_rows.get(row, {})
            is_committed = False

        constraints = row_data.get('constraints', {})

        if role in (
        QtCore.Qt.ItemDataRole.DisplayRole, QtCore.Qt.ItemDataRole.EditRole):
            if col == 0:
                return str(row_data.get('source_address', ''))
            elif col == 1:
                return str(row_data.get('key', ''))
            elif col == 2:
                return str(row_data.get('value', ''))
            elif col == 3:
                return str(row_data.get('data_type', 'string'))
            elif col == 4:
                return str(constraints.get('valid_from', ''))
            elif col == 5:
                return str(constraints.get('valid_until', ''))
            elif col == 6:
                clean_constraints = {k: v for k, v in constraints.items() if
                                     k not in ['valid_from', 'valid_until']}
                return str(clean_constraints) if clean_constraints else "-"

        # Visual styling: Color uncommitted rows differently to emphasize active editing
        if role == QtCore.Qt.ItemDataRole.BackgroundRole and not is_committed:
            return QtGui.QColor(240, 248, 255)  # Light AliceBlue background

        return None

    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if orientation == QtCore.Qt.Orientation.Horizontal and role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self._headers[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return QtCore.Qt.ItemFlag.NoItemFlags

        # Existing committed entries are Read-Only history (since mode='all' is an immutable trace log)
        # New appended rows are completely editable
        if index.row() >= len(self._raw_data):
            # Constraints field column is processed simplified or empty for basic entries
            if index.column() in [0, 1, 2, 3]:
                return QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEditable

        return QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable

    def setData(self, index, value, role=QtCore.Qt.ItemDataRole.EditRole):
        if index.isValid() and role == QtCore.Qt.ItemDataRole.EditRole:
            row = index.row()
            col = index.column()

            if row not in self._uncommitted_rows:
                self._uncommitted_rows[row] = {'source_address': '@', 'key': '',
                                               'value': '', 'data_type': 'string',
                                               'constraints': {}}

            target_row = self._uncommitted_rows[row]
            value_str = str(value).strip()

            if col == 0:
                target_row['source_address'] = value_str
            elif col == 1:
                target_row['key'] = value_str
            elif col == 2:
                target_row['value'] = value_str
            elif col == 3:
                if value_str.lower() in ['int', 'integer']:
                    target_row['data_type'] = 'int'
                elif value_str.lower() in ['float', 'double']:
                    target_row['data_type'] = 'float'
                else:
                    target_row['data_type'] = 'string'

            self.dataChanged.emit(index, index, [QtCore.Qt.ItemDataRole.DisplayRole])
            return True
        return False

    def insert_empty_row(self, address=None):
        """Appends a new empty workspace template row onto the UI grid."""
        next_row_index = self.rowCount()
        if address is None:
            address_insert = address
        else:
            address_insert = str(address)
        self.beginInsertRows(QtCore.QModelIndex(), next_row_index, next_row_index)
        self._uncommitted_rows[next_row_index] = {
            'source_address': address_insert,
            'key': 'new_key',
            'value': '',
            'data_type': 'string',
            'constraints': {}
        }
        self.endInsertRows()
        return next_row_index

    def commit_row_to_backend(self, row_index):
        """Converts data types and submits the chosen working row to add_metadata."""
        row_data = self._uncommitted_rows.get(row_index)
        if not row_data or not row_data['key'] or not row_data['value']:
            return False, "Key and Value fields cannot be left empty!"

        # Datatype conversion logic
        raw_val = row_data['value']
        dtype = row_data['data_type']

        try:
            if dtype == 'int':
                final_value = int(raw_val)
            elif dtype == 'float':
                final_value = float(raw_val)
            else:
                final_value = str(raw_val)
        except ValueError:
            return False, f"Value '{raw_val}' cannot be parsed into expected data type: {dtype}"

        try:
            # Route processing into your exact add_metadata framework definition
            self.redvypr.add_metadata(
                address=row_data['source_address'],
                metadata={row_data['key']: final_value},
                constraints=None,
                # Expand if explicit custom runtime metadata structures are requested
                valid_from=datetime.now(timezone.utc)
            )
            return True, "Success"
        except Exception as e:
            return False, str(e)


class MultiValueFilterProxyModel(QtCore.QSortFilterProxyModel):
    """
    A advanced proxy model that allows column-specific filtering based on a
    set of allowed values (managed via checkboxes in the header).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Dictionary mapping column_index -> set of allowed string values
        self._column_filters = {}

    def set_column_filter_values(self, column, allowed_values):
        """Sets the allowed values for a specific column. If None, filtering is disabled for it."""
        if allowed_values is None:
            self._column_filters.pop(column, None)
        else:
            self._column_filters[column] = set(allowed_values)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        # Iterate over all columns that have an active filter configured
        for col, allowed_set in self._column_filters.items():
            source_index = self.sourceModel().index(source_row, col, source_parent)
            cell_value = str(self.sourceModel().data(source_index,
                                                     QtCore.Qt.ItemDataRole.DisplayRole))

            if cell_value not in allowed_set:
                return False
        return True
