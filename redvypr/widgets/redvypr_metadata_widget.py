import datetime
from PyQt6 import QtWidgets, QtCore, QtGui
import logging

from redvypr.widgets.dict_qtree_widget import EditableDictQTreeWidget
from redvypr.widgets.redvypr_address_widget import RedvyprAddressWidget
from datetime import datetime, timedelta

# Importiere hier deine zuvor erstellte Funktion
# from redvypr.metadata_api import add_metadata2datapacket

logger = logging.getLogger(__name__)


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


