import json

from PyQt6 import QtWidgets, QtCore, QtGui
import logging
import sys
import qtawesome
import redvypr.files as files
import redvypr.data_packets as data_packets
from redvypr.redvypr_address import RedvyprAddress
from redvypr.widgets.redvyprAddressWidget import RedvyprMultipleAddressesWidget

class DatastreamTableWidget(QtWidgets.QWidget):
    """Widget to manage datastreams in a table with add/remove functionality."""
    datastreams_changed = QtCore.Signal(list)  # Signal für Änderungen

    def __init__(self, datastreams=None, parent=None, redvypr=None, show_apply_button=True):
        super().__init__(parent)
        self.redvypr = redvypr
        self.datastreams = datastreams if datastreams is not None else []
        self.show_apply_button = show_apply_button
        self.setup_ui()

    def setup_ui(self):
        """Initialize the UI with table, buttons (with icons + text), and address widget."""
        self.layout = QtWidgets.QVBoxLayout(self)

        # --- Table for Datastreams ---
        self.datastream_table = QtWidgets.QTableWidget()
        self.datastream_table.setColumnCount(1)
        self.datastream_table.setHorizontalHeaderLabels(["Datastream Address"])
        self.datastream_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.datastream_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.layout.addWidget(self.datastream_table)

        # --- Buttons for Add/Remove (with icons + text) ---
        button_layout = QtWidgets.QHBoxLayout()

        # Add Button (Icon + Text: " Add") → Öffnet RedvyprMultipleAddressesWidget
        self.add_button = QtWidgets.QPushButton(" Add")
        self.add_button.setIcon(qtawesome.icon('fa5s.plus'))
        self.add_button.setToolTip("Add datastream from list")
        self.add_button.clicked.connect(self.add_datastream)
        button_layout.addWidget(self.add_button)

        # Add Manual Button (Icon + Text: " Add Manual") → Öffnet InputDialog
        self.add_manual_button = QtWidgets.QPushButton(" Add Manual")
        self.add_manual_button.setIcon(qtawesome.icon('fa5s.edit'))
        self.add_manual_button.setToolTip("Add datastream manually")
        self.add_manual_button.clicked.connect(self.add_manual_datastream)
        button_layout.addWidget(self.add_manual_button)

        # Remove Selected Button (Icon + Text: " Remove")
        self.remove_button = QtWidgets.QPushButton(" Remove")
        self.remove_button.setIcon(qtawesome.icon('fa5s.trash-alt'))
        self.remove_button.setToolTip("Remove selected datastreams")
        self.remove_button.clicked.connect(self.remove_datastreams)
        button_layout.addWidget(self.remove_button)

        # Clear All Button (Icon + Text: " Clear")
        self.clear_button = QtWidgets.QPushButton(" Clear")
        self.clear_button.setIcon(qtawesome.icon('fa5s.broom'))
        self.clear_button.setToolTip("Clear all datastreams")
        self.clear_button.clicked.connect(self.clear_datastreams)
        button_layout.addWidget(self.clear_button)

        # --- Optional: Apply Button (Icon + Text: " Apply") ---
        if self.show_apply_button:
            self.apply_button = QtWidgets.QPushButton(" Apply")
            self.apply_button.setIcon(qtawesome.icon('fa5s.check'))
            self.apply_button.setToolTip("Apply changes")
            self.apply_button.clicked.connect(self.apply_clicked)
            button_layout.addWidget(self.apply_button)

        self.layout.addLayout(button_layout)

        # Initialize table
        self.update_table()

    def update_table(self):
        """Update the table with current datastreams."""
        self.datastream_table.setRowCount(len(self.datastreams))
        for row, datastream in enumerate(self.datastreams):
            item = QtWidgets.QTableWidgetItem(str(datastream))
            item.setData(QtCore.Qt.UserRole, datastream)
            self.datastream_table.setItem(row, 0, item)
        self.datastream_table.resizeColumnsToContents()

    def add_datastream(self):
        """Open the address widget to select datastreams."""
        self.address_widget = RedvyprMultipleAddressesWidget(redvypr=self.redvypr)
        self.address_widget.apply.connect(self.on_address_applied)
        self.address_widget.show()

    def add_manual_datastream(self):
        """Open an input dialog to manually add a datastream."""
        text, ok = QtWidgets.QInputDialog.getText(
            self,
            "Add Manual Datastream",
            "Enter datastream address:"
        )
        if ok and text:
            # Hier könntest du die Eingabe validieren (z. B. mit RedvyprAddress)
            self.datastreams.append(text)
            self.update_table()
            self.emit_datastreams_changed()

    def on_address_applied(self, signal_dict):
        """Handle datastreams added from the address widget."""
        new_datastreams = signal_dict.get('datastreams_address', [])
        for ds in new_datastreams:
            if ds not in self.datastreams:
                self.datastreams.append(ds.to_address_string())
        self.update_table()
        self.emit_datastreams_changed()

    def remove_datastreams(self):
        """Remove selected datastreams from the table."""
        selected_rows = set(index.row() for index in self.datastream_table.selectedIndexes())
        for row in sorted(selected_rows, reverse=True):
            self.datastreams.pop(row)
        self.update_table()
        self.emit_datastreams_changed()

    def clear_datastreams(self):
        """Clear all datastreams from the table."""
        self.datastreams.clear()
        self.update_table()
        self.emit_datastreams_changed()

    def emit_datastreams_changed(self):
        """Emit the datastreams_changed signal with the current datastreams."""
        self.datastreams_changed.emit(self.datastreams.copy())

    def apply_clicked(self):
        """Emit the datastreams_changed signal with the current datastreams."""
        self.datastreams_changed.emit(self.datastreams.copy())
        self.close()

    def get_datastreams(self):
        """Return the list of current datastreams."""
        return self.datastreams.copy()

