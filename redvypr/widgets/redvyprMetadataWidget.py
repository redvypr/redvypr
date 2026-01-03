import json

from PyQt6 import QtWidgets, QtCore, QtGui
import logging
import sys
import qtawesome
import redvypr.files as files
import redvypr.data_packets as data_packets
from redvypr.redvypr_address import RedvyprAddress
from redvypr.widgets.pydanticConfigWidget import dictQTreeWidget
from redvypr.widgets.redvyprAddressWidget import RedvyprAddressWidgetSimple, datastreamQTreeWidget, RedvyprAddressWidget, RedvyprAddressEditWidget
from datetime import datetime, timedelta


class MetadataWidget(QtWidgets.QWidget):
    def __init__(self, redvypr=None):
        super().__init__()
        self.redvypr = redvypr
        self.layout = QtWidgets.QHBoxLayout(self)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        self.metaeshowwidget = QtWidgets.QWidget()
        self.metaeshowwidget_layout = QtWidgets.QVBoxLayout(self.metaeshowwidget)
        self.metaeshowwidget_layout_update = QtWidgets.QVBoxLayout()
        self.placeholder = QtWidgets.QLabel(
            "Select an address and click 'Get metadata' to display details.")
        self.placeholder.setAlignment(QtCore.Qt.AlignCenter)
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

        self.time_constrain_checkbox_show_timeline = QtWidgets.QCheckBox("Show timeline")
        self.time_constrain_checkbox_show_timeline.setChecked(False)
        self.time_constrain_checkbox_show_timeline.toggled.connect(self.get_metadata_clicked)

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
        # Standardwert setzen
        self.radio_expanded.setChecked(True)
        self.radio_merge.toggled.connect(self.get_metadata_clicked)
        # Create group
        self.metadata_group = QtWidgets.QButtonGroup(self)
        self.metadata_group.addButton(self.radio_expanded)
        self.metadata_group.addButton(self.radio_merge)

        self.metaeshowwidget_layout_get = QtWidgets.QGridLayout()
        self.metaeshowwidget_layout_get.addWidget(self.address_get, 0, 0)
        self.metaeshowwidget_layout_get.addWidget(self.choose_address_button, 0, 1)
        self.metaeshowwidget_layout_get.addWidget(self.apply_get_button, 0, 2)
        self.metaeshowwidget_layout_get.addWidget(self.radio_merge, 1, 0)
        self.metaeshowwidget_layout_get.addWidget(self.radio_expanded, 1, 1)
        self.metaeshowwidget_layout_get.addWidget(self.time_constrain_checkbox_get, 2, 0)
        self.metaeshowwidget_layout_get.addWidget(self.time_constrain_checkbox_show_timeline, 2, 1)
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

        # Initially disable time inputs
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
        layout.addItem(QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum,
                                             QtWidgets.QSizePolicy.Expanding), 9, 0)

        # Fill the table with all metadata
        self.get_metadata_clicked()
    def choose_address_clicked(self):
        self.addresswidget = RedvyprAddressWidget(redvypr=self.redvypr)
        self.addresswidget.apply.connect(self.address_choosen)
        self.addresswidget.show()

    def address_choosen(self, address_dict):
        print("Got address",address_dict)
    def toggle_time_inputs_get(self, checked):
        """ Enables/Disables time inputs based on checkbox state """
        self.t1_label_get.setEnabled(checked)
        self.t1_edit_get.setEnabled(checked)
        self.t2_label_get.setEnabled(checked)
        self.t2_edit_get.setEnabled(checked)
    def toggle_time_inputs(self, checked):
        """ Enables/Disables time inputs based on checkbox state """
        self.t1_label.setEnabled(checked)
        self.t1_edit.setEnabled(checked)
        self.t2_label.setEnabled(checked)
        self.t2_edit.setEnabled(checked)

    def get_metadata_clicked(self):
        address = self.address_get.text()
        if self.radio_expanded.isChecked():
            mode="expanded"
        else:
            mode="merge"
        print(f"Getting metadata for {address=} with {mode=}")
        if self.time_constrain_checkbox_get.isChecked():
            # Extract Python datetime from QDateTime
            t1 = self.t1_edit_get.dateTime().toPython()
            t2 = self.t2_edit_get.dateTime().toPython()

            print(f"Getting time-constrained metadata: [{t1} to {t2}]")
            metadata_new = self.redvypr.get_metadata_in_range(address=address,
                                                       t1=t1, t2=t2, mode=mode)
        else:
            metadata_new = self.redvypr.get_metadata(address, mode=mode)

        print(f"Metadata new:{metadata_new}")
        # Clear previous widget if exists
        for i in reversed(range(self.metaeshowwidget_layout_update.count())):
            self.metaeshowwidget_layout_update.itemAt(i).widget().setParent(None)

        if self.time_constrain_checkbox_show_timeline.isChecked():
            self.timeconstraints = ConstraintTimeline()
            self.timeconstraints.set_data(metadata=metadata_new)
            self.metaeshowwidget_layout_update.addWidget(self.timeconstraints)

        self.metadata_widget = EditableDictQTreeWidget(data=metadata_new,
                                               dataname=f'Metadata for {address}', mode=mode)

        self.metadata_widget.deleteRequested.connect(self.delete_entry)
        self.metadata_widget.expandAll()
        self.metaeshowwidget_layout_update.addWidget(self.metadata_widget)



    def delete_entry(self,address,delete_dict):
        print("Deleting entries",address)
        constraints = delete_dict['constraints']
        keys = delete_dict['keys']
        print("Deleting keys", keys)
        print("Deleting constraints", constraints)
        self.redvypr.rem_metadata(address,keys,constraints)
        # Update qtree
        self.get_metadata_clicked()
    def add_metadata_clicked(self):
        address_text = self.address_new.text()
        raddress = RedvyprAddress(address_text)
        key = self.metadatakey_new.text()
        entry = self.metadataentry_new.text()
        metadata = {key: entry}

        if self.time_constrain_checkbox.isChecked():
            # Extract Python datetime from QDateTime
            t1 = self.t1_edit.dateTime().toPython()
            t2 = self.t2_edit.dateTime().toPython()

            print(f"Adding time-constrained metadata: {metadata} [{t1} to {t2}]")
            self.redvypr.add_metadata_time_constrained(raddress, metadata=metadata,
                                                       t1=t1, t2=t2)
        else:
            print(f"Adding global metadata: {metadata}")
            self.redvypr.set_metadata(raddress, metadata=metadata)

    def get_constraint_time_bounds(self, constraints):
        """
        Extracts the absolute min and max timestamps from metadata constraints.
        Returns (min_time, max_time). If no constraints exist, returns (None, None).
        """
        constrain_times = []

        for rule in constraints:
            for cond in rule.get('conditions', []):
                if cond.get('field') == 't':
                    val = cond.get('value')
                    try:
                        # Parse ISO string to datetime object
                        dt = datetime.fromisoformat(val)
                        # Convert to Unix timestamp (float)
                        constrain_times.append(dt)
                    except (ValueError, TypeError):
                        continue

        if not constrain_times:
            return None, None

        return min(constrain_times), max(constrain_times)



class ConstraintTimeline(QtWidgets.QWidget):
    # Signal, wenn ein Constraint angeklickt wird
    constraintClicked = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setMouseTracking(True)  # Wichtig für Tooltips ohne Mausklick

        self.t1 = None
        self.t2 = None
        self.metadata = {}
        self.rects = []  # Speicher für Interaktionen: (QRect, rule_dict)

        self.row_height = 30  # Höhe eines einzelnen Balkens
        self.address_label_width = 120
        self.bar_color = QtGui.QColor("#4da6ff")
        self.bg_color = QtGui.QColor("#f8f8f8")

    def set_data(self, metadata, t1=None, t2=None):
        self.metadata = metadata
        if t1 is None or t2 is None:
            self.t1, self.t2 = self.calculate_bounds(metadata)
        else:
            self.t1, self.t2 = t1, t2

        # Falls immer noch None (keine Daten), Fallback
        if not self.t1:
            self.t1 = datetime.now()
            self.t2 = self.t1 + timedelta(days=1)

        self.update_geometry()
        self.update()

    def update_geometry(self):
        # Berechnet die benötigte Höhe: Jede Adresse + ihre Anzahl an Constraints
        total_rows = 0
        for addr in self.metadata:
            constraints = self.metadata[addr].get('_constraints', [])
            total_rows += max(1, len(constraints))

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
        self.rects = []  # Zurücksetzen für neue Klick-Erkennung

        painter.setBrush(self.bg_color)
        painter.drawRect(self.rect())

        if not self.t1 or not self.t2: return

        current_y = 20
        for address, content in self.metadata.items():
            constraints = content.get('_constraints', [])

            # Adresse links zeichnen
            painter.setPen(QtCore.Qt.black)
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(5, current_y, self.address_label_width - 10,
                             self.row_height,
                             QtCore.Qt.AlignVCenter, address)

            font.setBold(False)
            painter.setFont(font)

            # Constraints untereinander zeichnen
            for rule in constraints:
                r_start, r_end = self.extract_times(rule)
                x_start = max(self.address_label_width,
                              self.time_to_x(r_start or self.t1))
                x_end = min(self.width() - 10, self.time_to_x(r_end or self.t2))

                if x_end > x_start:
                    rect = QtCore.QRect(x_start, current_y, x_end - x_start,
                                        self.row_height - 4)
                    self.rects.append((rect, rule))  # Für Klick/Tooltip merken

                    painter.setBrush(self.bar_color)
                    painter.setPen(QtGui.QPen(QtCore.Qt.white, 1))
                    painter.drawRoundedRect(rect, 4, 4)

                    label = str(rule.get('values', ''))
                    painter.setPen(QtCore.Qt.black)
                    painter.drawText(rect, QtCore.Qt.AlignCenter, label)

                current_y += self.row_height  # Jedes Constraint eine neue Zeile

            # Trennlinie nach jeder Adresse
            painter.setPen(QtGui.QColor("#d0d0d0"))
            painter.drawLine(0, current_y, self.width(), current_y)
            current_y += 10

    def mouseMoveEvent(self, event):
        # Tooltip anzeigen, wenn über ein Rechteck gehovert wird
        for rect, rule in self.rects:
            if rect.contains(event.pos()):
                # Schöner formatierten Tooltip bauen
                cond_str = "\n".join([f"{c['field']} {c['op']} {c['value']}" for c in
                                      rule['conditions']])
                val_str = str(rule['values'])
                QtWidgets.QToolTip.showText(event.globalPos(),
                                            f"Conditions:\n{cond_str}\n\nValues:\n{val_str}",
                                            self)
                return
        QtWidgets.QToolTip.hideText()

    def mousePressEvent(self, event):
        # Klick-Erkennung
        for rect, rule in self.rects:
            if rect.contains(event.pos()):
                print(f"Constraint clicked: {rule}")
                self.constraintClicked.emit(rule)
                break

    def calculate_bounds(self, metadata):
        all_times = []
        for addr_content in metadata.values():
            if not isinstance(addr_content, dict): continue
            for rule in addr_content.get('_constraints', []):
                s, e = self.extract_times(rule)
                if s: all_times.append(s)
                if e: all_times.append(e)
        return (min(all_times), max(all_times)) if all_times else (None, None)

    def extract_times(self, rule):
        r_start, r_end = None, None
        for cond in rule.get('conditions', []):
            if cond['field'] == 't':
                dt = datetime.fromisoformat(cond['value']) if isinstance(cond['value'],
                                                                         str) else cond[
                    'value']
                if cond['op'] in ['>', '>=']:
                    r_start = dt
                elif cond['op'] in ['<', '<=']:
                    r_end = dt
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

