import json
import datetime
from PyQt6 import QtWidgets, QtCore, QtGui
import logging
import sys
import qtawesome

import redvypr.files as files
import redvypr.data_packets as data_packets
import redvypr.metadata
from redvypr.redvypr_address import RedvyprAddress
from redvypr.widgets.pydanticConfigWidget import dictQTreeWidget
from redvypr.widgets.redvyprAddressWidget import RedvyprAddressWidgetSimple, \
    datastreamQTreeWidget, RedvyprAddressWidget, RedvyprAddressEditWidget
from datetime import datetime, timedelta, timezone

# Importiere hier deine zuvor erstellte Funktion
# from redvypr.metadata_api import add_metadata2datapacket

logger = logging.getLogger(__name__)


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

    def reload_from_backend(self):
        """Fetches the latest state from the redvypr instance."""
        self.beginResetModel()
        try:
            self._raw_data = self.redvypr.get_metadata(mode="all")
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

    def insert_empty_row(self):
        """Appends a new empty workspace template row onto the UI grid."""
        next_row_index = self.rowCount()
        self.beginInsertRows(QtCore.QModelIndex(), next_row_index, next_row_index)
        self._uncommitted_rows[next_row_index] = {
            'source_address': '@',
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


class RedvyprMetadataTable(QtWidgets.QWidget):
    """
    A self-contained custom PyQt6 Widget executing queries and registrations
    against a passed redvypr master instance object. Now features sorting and
    checkbox-based column filtering.
    """

    def __init__(self, redvypr_instance, parent=None):
        super().__init__(parent)
        self.redvypr = redvypr_instance

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
        self.base_model.reload_from_backend()

    def refresh_and_clear_filters(self):
        """Reloads backend data and drops active proxy filtering configurations."""
        self.proxy_model._column_filters.clear()
        self.proxy_model.invalidateFilter()
        self.base_model.reload_from_backend()

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


class RedvyprMetadataTable_legacy(QtWidgets.QWidget):
    """
    A self-contained custom PyQt6 Widget executing queries and registrations
    against a passed redvypr master instance object.
    """

    def __init__(self, redvypr_instance, parent=None):
        super().__init__(parent)
        self.redvypr = redvypr_instance

        # Primary Structural Layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # QTableView setup
        self.table_view = QtWidgets.QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table_view)

        # Initialize and bind our custom editing data provider
        self.model = RedvyprMetadataModel(self.redvypr)
        self.table_view.setModel(self.model)

        # Bottom controls setup
        button_layout = QtWidgets.QHBoxLayout()

        self.btn_refresh = QtWidgets.QPushButton("Refresh Table")
        self.btn_refresh.clicked.connect(self.model.reload_from_backend)

        self.btn_add_row = QtWidgets.QPushButton("Insert New Row")
        self.btn_add_row.clicked.connect(self.addNewRowTrack)

        self.btn_save_row = QtWidgets.QPushButton("Commit Selected Row")
        self.btn_save_row.clicked.connect(self.commitSelectedRowTrack)
        self.btn_save_row.setEnabled(
            False)  # Activated only when rows under construction are highlighted

        button_layout.addWidget(self.btn_refresh)
        button_layout.addWidget(self.btn_add_row)
        button_layout.addWidget(self.btn_save_row)
        layout.addLayout(button_layout)

        # Selection event triggers to contextualize button interactions
        self.table_view.selectionModel().selectionChanged.connect(
            self.onSelectionChanged)

        # Initialize initial fetch loop
        self.model.reload_from_backend()

    def addNewRowTrack(self):
        new_row_idx = self.model.insert_empty_row()
        # Automatically focus view highlight directly on the new key identifier field
        target_focus_index = self.model.index(new_row_idx, 1)
        self.table_view.setCurrentIndex(target_focus_index)
        self.table_view.edit(target_focus_index)

    def onSelectionChanged(self, selected, deselected):
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            self.btn_save_row.setEnabled(False)
            return

        current_row = indexes[0].row()
        # Enable save option only if selecting a dynamically inserted draft tracking row
        is_draft = current_row >= len(self.model._raw_data)
        self.btn_save_row.setEnabled(is_draft)

    def commitSelectedRowTrack(self):
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            return

        target_row = indexes[0].row()
        success, message = self.model.commit_row_to_backend(target_row)

        if success:
            QtWidgets.QMessageBox.information(self, "Success",
                                              "Metadata successfully committed to backend stream!")
            self.model.reload_from_backend()
        else:
            QtWidgets.QMessageBox.warning(self, "Validation Error",
                                          f"Failed saving metadata entry:\n{message}")


# Legacy to be replaced by an updated variant
class MetadataWidget(QtWidgets.QWidget):
    def __init__(self, redvypr=None):
        super().__init__()
        self.redvypr = redvypr
        self.layout = QtWidgets.QHBoxLayout(self)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        self.metaeshowwidget = QtWidgets.QWidget()
        self.metaeshowwidget_layout = QtWidgets.QVBoxLayout(self.metaeshowwidget)
        self.metaeshowwidget_layout_update = QtWidgets.QVBoxLayout()
        self.placeholder = QtWidgets.QLabel(
            "Select an address and click 'Get metadata' to display details.")
        self.placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.metaeshowwidget_layout_update.addWidget(self.placeholder)

        self.metaeditwidget = QtWidgets.QWidget()

        self.splitter.addWidget(self.metaeditwidget)
        self.splitter.addWidget(self.metaeshowwidget)
        self.layout.addWidget(self.splitter)

        layout = QtWidgets.QGridLayout(self.metaeditwidget)

        # --- Get Metadata Section ---
        self.address_get = QtWidgets.QLineEdit()
        self.apply_get_button = QtWidgets.QPushButton("Get metadata")
        self.apply_get_button.clicked.connect(self.get_metadata_clicked)
        self.choose_address_button = QtWidgets.QPushButton("Choose address")
        self.choose_address_button.clicked.connect(self.choose_address_clicked)

        # --- Get Metadata Time Constraint Section ---
        self.time_constrain_checkbox_get = QtWidgets.QCheckBox("Add time constraint")

        self.time_constrain_checkbox_show_timeline = QtWidgets.QCheckBox(
            "Show timeline")
        self.time_constrain_checkbox_show_timeline.setChecked(False)
        self.time_constrain_checkbox_show_timeline.toggled.connect(
            self.get_metadata_clicked)

        self.t1_label_get = QtWidgets.QLabel("Start (t1)")
        self.t1_edit_get = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime())
        self.t1_edit_get.setCalendarPopup(True)

        self.t2_label_get = QtWidgets.QLabel("End (t2)")
        self.t2_edit_get = QtWidgets.QDateTimeEdit(
            QtCore.QDateTime.currentDateTime().addDays(7))
        self.t2_edit_get.setCalendarPopup(True)
        self.time_constrain_checkbox_get.toggled.connect(self.toggle_time_inputs_get)
        self.toggle_time_inputs_get(False)

        # Mode explicit/merge
        self.radio_expanded = QtWidgets.QRadioButton("Mode: Expanded")
        self.radio_merge = QtWidgets.QRadioButton("Mode: Merge")
        self.radio_expanded.setChecked(True)
        self.radio_merge.toggled.connect(self.get_metadata_clicked)

        self.metadata_group = QtWidgets.QButtonGroup(self)
        self.metadata_group.addButton(self.radio_expanded)
        self.metadata_group.addButton(self.radio_merge)

        self.metaeshowwidget_layout_get = QtWidgets.QGridLayout()
        self.metaeshowwidget_layout_get.addWidget(self.address_get, 0, 0)
        self.metaeshowwidget_layout_get.addWidget(self.choose_address_button, 0, 1)
        self.metaeshowwidget_layout_get.addWidget(self.apply_get_button, 0, 2)
        self.metaeshowwidget_layout_get.addWidget(self.radio_merge, 1, 0)
        self.metaeshowwidget_layout_get.addWidget(self.radio_expanded, 1, 1)
        self.metaeshowwidget_layout_get.addWidget(self.time_constrain_checkbox_get, 2,
                                                  0)
        self.metaeshowwidget_layout_get.addWidget(
            self.time_constrain_checkbox_show_timeline, 2, 1)
        self.metaeshowwidget_layout_get.addWidget(self.t1_label_get, 3, 0)
        self.metaeshowwidget_layout_get.addWidget(self.t1_edit_get, 3, 1, 1, 2)
        self.metaeshowwidget_layout_get.addWidget(self.t2_label_get, 4, 0)
        self.metaeshowwidget_layout_get.addWidget(self.t2_edit_get, 4, 1, 1, 2)

        self.metaeshowwidget_layout.addLayout(self.metaeshowwidget_layout_get, 0)
        self.metaeshowwidget_layout.addLayout(self.metaeshowwidget_layout_update, 1)

        # --- Add Metadata Section ---
        self.address_new_label = QtWidgets.QLabel("Address")
        self.address_new = QtWidgets.QLineEdit()

        self.metadatakey_new_label = QtWidgets.QLabel("Key")
        self.metadatakey_new = QtWidgets.QLineEdit()
        self.metadataentry_new_label = QtWidgets.QLabel("Entry")
        self.metadataentry_new = QtWidgets.QLineEdit()

        # --- Time Constraint Section ---
        self.time_constrain_checkbox = QtWidgets.QCheckBox("Add time constraint")
        self.time_constrain_checkbox.toggled.connect(self.toggle_time_inputs)

        self.t1_label = QtWidgets.QLabel("Start (t1)")
        self.t1_edit = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime())
        self.t1_edit.setCalendarPopup(True)

        self.t2_label = QtWidgets.QLabel("End (t2)")
        self.t2_edit = QtWidgets.QDateTimeEdit(
            QtCore.QDateTime.currentDateTime().addDays(7))
        self.t2_edit.setCalendarPopup(True)

        self.toggle_time_inputs(False)

        self.apply_button = QtWidgets.QPushButton("Add metadata")
        self.apply_button.clicked.connect(self.add_metadata_clicked)

        # --- Layout Assembly ---
        layout.addWidget(QtWidgets.QLabel("<b>Set Metadata:</b>"), 1, 0)
        layout.addWidget(self.address_new_label, 2, 0)
        layout.addWidget(self.address_new, 2, 1)
        layout.addWidget(self.metadatakey_new_label, 3, 0)
        layout.addWidget(self.metadatakey_new, 3, 1)
        layout.addWidget(self.metadataentry_new_label, 4, 0)
        layout.addWidget(self.metadataentry_new, 4, 1)

        layout.addWidget(self.time_constrain_checkbox, 5, 0, 1, 2)
        layout.addWidget(self.t1_label, 6, 0)
        layout.addWidget(self.t1_edit, 6, 1)
        layout.addWidget(self.t2_label, 7, 0)
        layout.addWidget(self.t2_edit, 7, 1)

        layout.addWidget(self.apply_button, 8, 0, 1, 2)
        layout.addItem(
            QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Policy.Minimum,
                                  QtWidgets.QSizePolicy.Policy.Expanding), 9, 0)

        self.get_metadata_clicked()

    def choose_address_clicked(self):
        self.addresswidget = RedvyprAddressWidget(redvypr=self.redvypr)
        self.addresswidget.apply.connect(self.address_choosen)
        self.addresswidget.show()

    def address_choosen(self, address_dict):
        # Setzt die ausgewählte Adresse direkt in die Eingabefelder ein
        if "address_str" in address_dict:
            self.address_get.setText(address_dict["address_str"])
            self.address_new.setText(address_dict["address_str"])

    def toggle_time_inputs_get(self, checked):
        self.t1_label_get.setEnabled(checked)
        self.t1_edit_get.setEnabled(checked)
        self.t2_label_get.setEnabled(checked)
        self.t2_edit_get.setEnabled(checked)

    def toggle_time_inputs(self, checked):
        self.t1_label.setEnabled(checked)
        self.t1_edit.setEnabled(checked)
        self.t2_label.setEnabled(checked)
        self.t2_edit.setEnabled(checked)

    def get_metadata_clicked(self):
        address = self.address_get.text()
        mode = "expanded" if self.radio_expanded.isChecked() else "merge"

        if self.time_constrain_checkbox_get.isChecked():
            t1 = self.t1_edit_get.dateTime().toPython()
            t2 = self.t2_edit_get.dateTime().toPython()
            metadata_new = self.redvypr.get_metadata_in_range(address=address,
                                                                       t1=t1, t2=t2,
                                                                       mode=mode)
        else:
            metadata_new = self.redvypr.get_metadata(address, mode=mode)

        # Bereinige vorherige Widgets im Layout
        for i in reversed(range(self.metaeshowwidget_layout_update.count())):
            widget = self.metaeshowwidget_layout_update.itemAt(i).widget()
            if widget is not None:
                widget.setParent(None)

        if not metadata_new:
            self.metaeshowwidget_layout_update.addWidget(
                QtWidgets.QLabel("No metadata found for this selection."))
            return

        if self.time_constrain_checkbox_show_timeline.isChecked():
            self.timeconstraints = ConstraintTimeline()
            self.timeconstraints.set_data(metadata=metadata_new)
            self.metaeshowwidget_layout_update.addWidget(self.timeconstraints)

        self.metadata_widget = EditableDictQTreeWidget(data=metadata_new,
                                                       dataname=f'Metadata for {address}',
                                                       mode=mode)
        self.metadata_widget.deleteRequested.connect(self.delete_entry)
        self.metadata_widget.expandAll()
        self.metaeshowwidget_layout_update.addWidget(self.metadata_widget)

    def delete_entry(self, address, delete_dict):
        # Sendet die Löschanweisung an die Backend-Pipeline ('_metadata_remove')
        # Das Backend (`do_metadata`) erwartet die Struktur über ein Datenpaket
        packet = {
            '_metadata_remove': {
                address: {
                    'keys': delete_dict.get('keys', []),
                    'mode': 'exact'
                }
            }
        }
        print(f"Sending delete packet to backend: {packet}")
        # Aufruf deiner zentralen Verarbeitungsinstanz (z. B. über do_metadata)
        self.redvypr.process_metadata_packet(packet)
        self.get_metadata_clicked()

    def add_metadata_clicked(self):
        address_text = self.address_new.text()
        if not address_text:
            return

        key = self.metadatakey_new.text()
        entry = self.metadataentry_new.text()
        # Constraints für die neue Struktur aufbauen
        if self.time_constrain_checkbox.isChecked():
            valid_from = self.t1_edit.dateTime().toPython().isoformat()
            valid_until = self.t2_edit.dateTime().toPython().isoformat()
        else:
            valid_from = None
            valid_until = None

        # Nutzt das neue einheitliche add_metadata2datapacket Format

        metadata = {key:entry}
        print(f"Sending new structured metadata packet to backend: {metadata} for address:{address_text}")
        # Nutzt dieselbe Pipeline wie do_metadata(datapacket, master_storage) im Backend
        self.redvypr.add_metadata(address_text,metadata,valid_until=valid_until,valid_from=valid_from)

        # UI zurücksetzen und aktualisieren
        self.metadatakey_new.clear()
        self.metadataentry_new.clear()
        self.get_metadata_clicked()


class ConstraintTimeline(QtWidgets.QWidget):
    constraintClicked = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setMouseTracking(True)
        self.t1 = None
        self.t2 = None
        self.metadata = {}
        self.rects = []
        self.row_height = 30
        self.address_label_width = 120
        self.bar_color = QtGui.QColor("#4da6ff")
        self.bg_color = QtGui.QColor("#f8f8f8")

    def set_data(self, metadata, t1=None, t2=None):
        self.metadata = metadata
        if t1 is None or t2 is None:
            self.t1, self.t2 = self.calculate_bounds(metadata)
        else:
            self.t1, self.t2 = t1, t2

        if not self.t1:
            self.t1 = datetime.now()
            self.t2 = self.t1 + timedelta(days=1)

        self.update_geometry()
        self.update()

    def update_geometry(self):
        total_rows = 0
        for addr in self.metadata:
            # In der neuen Struktur ist self.metadata[addr] eine Liste von Einträgen
            entries = self.metadata[addr] if isinstance(self.metadata[addr],
                                                        list) else []
            total_rows += max(1, len(entries))

        new_height = total_rows * (self.row_height + 5) + 40
        self.setMinimumHeight(new_height)

    def time_to_x(self, t_target):
        if not self.t1 or not self.t2 or t_target is None:
            return self.address_label_width
        total_range = (self.t2 - self.t1).total_seconds()
        if total_range <= 0: return self.address_label_width
        elapsed = (t_target - self.t1).total_seconds()
        ratio = elapsed / total_range
        available_width = self.width() - self.address_label_width - 20
        return self.address_label_width + int(ratio * available_width)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        self.rects = []

        painter.setBrush(self.bg_color)
        painter.drawRect(self.rect())

        if not self.t1 or not self.t2: return

        current_y = 20
        for address, entries in self.metadata.items():
            if not isinstance(entries, list): continue

            # Adresse zeichnen
            painter.setPen(QtCore.Qt.GlobalColor.black)
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(5, current_y, self.address_label_width - 10,
                             self.row_height,
                             QtCore.Qt.AlignmentFlag.AlignVCenter, address)

            font.setBold(False)
            painter.setFont(font)

            # Iteriere über die neuen strukturierten Einträge der Adresse
            for entry in entries:
                constraints = entry.get('constraints', {})
                r_start, r_end = self.extract_times(constraints)

                x_start = max(self.address_label_width,
                              self.time_to_x(r_start or self.t1))
                x_end = min(self.width() - 10, self.time_to_x(r_end or self.t2))

                if x_end > x_start:
                    rect = QtCore.QRect(x_start, current_y, x_end - x_start,
                                        self.row_height - 4)
                    self.rects.append((rect, entry))  # Speichert den kompletten Eintrag

                    painter.setBrush(self.bar_color)
                    painter.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.white, 1))
                    painter.drawRoundedRect(rect, 4, 4)

                    label = f"{entry.get('key')}: {entry.get('value')}"
                    painter.setPen(QtCore.Qt.GlobalColor.black)
                    painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, label)

                current_y += self.row_height

            painter.setPen(QtGui.QColor("#d0d0d0"))
            painter.drawLine(0, current_y, self.width(), current_y)
            current_y += 10

    def mouseMoveEvent(self, event):
        for rect, entry in self.rects:
            if rect.contains(event.pos()):
                constraints = entry.get('constraints', {})
                cond_str = f"Valid From: {constraints.get('valid_from', 'None')}\nValid Until: {constraints.get('valid_until', 'None')}"
                QtWidgets.QToolTip.showText(event.globalPos(),
                                            f"Key: {entry['key']}\nValue: {entry['value']}\n\nConstraints:\n{cond_str}",
                                            self)
                return
        QtWidgets.QToolTip.hideText()

    def mousePressEvent(self, event):
        for rect, entry in self.rects:
            if rect.contains(event.pos()):
                self.constraintClicked.emit(entry)
                break

    def calculate_bounds(self, metadata):
        all_times = []
        for entries in metadata.values():
            if not isinstance(entries, list): continue
            for entry in entries:
                s, e = self.extract_times(entry.get('constraints', {}))
                if s: all_times.append(s)
                if e: all_times.append(e)
        return (min(all_times), max(all_times)) if all_times else (None, None)

    def extract_times(self, constraints):
        # Extrahiert Zeiten aus der flachen, neuen Constraints-Struktur ('valid_from' / 'valid_until')
        r_start, r_end = None, None

        v_from = constraints.get('valid_from')
        if v_from:
            r_start = datetime.fromisoformat(v_from) if isinstance(v_from,
                                                                   str) else v_from

        v_until = constraints.get('valid_until')
        if v_until:
            r_end = datetime.fromisoformat(v_until) if isinstance(v_until,
                                                                  str) else v_until

        return r_start, r_end







class EditableDictQTreeWidget(dictQTreeWidget):
    # Signal, das (Adresse, Key/Index-Liste, Constraint-Index-Liste) sendet
    deleteRequested = QtCore.Signal(str, dict)

    def __init__(self, data={}, dataname='data', show_datatype=True, address="", mode="expanded"):
        super().__init__(data, dataname, show_datatype)
        self.mode = mode
        self.address = address  # Wir merken uns, zu welcher Adresse die Daten gehören
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, pos):
        item = self.itemAt(pos)
        if not item or item == self.dataitem:
            return

        menu = QtWidgets.QMenu(self)
        if self.mode == "expanded":
            delete_action = menu.addAction("Delete entry")

            # delete icon
            delete_action.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_TrashIcon))

            action = menu.exec(self.mapToGlobal(pos))

            if action == delete_action:
                self.handle_delete(item)

        else:
            delete_action = menu.addAction('Delete entry (disabled in "merge" mode)')

            # delete icon
            delete_action.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_TrashIcon))
            delete_action.setEnabled(False)
            action = menu.exec(self.mapToGlobal(pos))

    def handle_delete(self, item):
        # Wir müssen herausfinden, was gelöscht werden soll
        key_or_index = item.__dataindex__
        #parentdata = item.__parentdata__
        data = item.__data__
        parent_item = item.__parent__
        print("Data",data)
        print("Parent",self.dataitem, )

        # Check if we are at the root and want to delete an address
        address = None
        keys_to_remove = None
        constraints_to_remove = None
        if parent_item == self.dataitem:
            address = key_or_index
            keys_to_remove = []
            constraints_to_remove = []
            print("Removing address",address)
        else:
            # Spezialfall: Wir löschen ein Constraint aus der Liste
            if parent_item and parent_item.__dataindex__ == '_constraints':
                constraints_to_remove = [int(key_or_index)]
                address_item = parent_item.__parent__
                address = address_item.__dataindex__
            elif item.__dataindex__ == '_constraints':
                print("Removing all constraints")
                constraints_to_remove = []
                address_item = parent_item
                address = address_item.__dataindex__
            else:
                # Normaler Key-Value Pair
                keys_to_remove = [str(key_or_index)]
                address_item = parent_item
                address = address_item.__dataindex__

            if address_item is not self.dataitem:
                print("Cannot delete items (not base item)")

        # Confirmation dialog
        res = QtWidgets.QMessageBox.question(
            self, "Confirm Deletion",
            f"Are you sure you want to delete '{key_or_index}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if res == QtWidgets.QMessageBox.Yes:
            delete_dict = {'constraints':constraints_to_remove,'keys':keys_to_remove}
            print("Removing",address, delete_dict)
            self.deleteRequested.emit(address, delete_dict)

