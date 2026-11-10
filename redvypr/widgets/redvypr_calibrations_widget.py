"""
Tab "Calibrations" of the Metadata window: all calibrations of the metadata
with their sensor item, the one valid at the state time, and their library;
filter, import, remove; a double click shows the sensor in the tab Items.
"""

import datetime
import logging
import os

from PyQt6 import QtCore, QtGui, QtWidgets

logger = logging.getLogger('redvypr.widgets.calibrations')

COLUMNS = ['Sensor', 'SN', 'Sensor model', 'Type', 'Date', 'Valid', 'Coefficients', 'Unit', 'Library']
ROLE_UUID = QtCore.Qt.ItemDataRole.UserRole + 1
ROLE_REF = QtCore.Qt.ItemDataRole.UserRole + 2


class RedvyprCalibrationsWidget(QtWidgets.QWidget):
    """All calibrations of the metadata of a redvypr instance."""

    item_requested = QtCore.pyqtSignal(str)       # reference of a sensor item to show

    def __init__(self, redvypr_instance, parent=None):
        super().__init__(parent)
        self.redvypr = redvypr_instance
        self._time = None
        self._entries = []
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText('filter: serial number, sensor model, type, library')
        self.filter.textChanged.connect(lambda _t: self.apply_filter())
        self.only_unassigned = QtWidgets.QCheckBox('without sensor item')
        self.only_unassigned.setToolTip('Only calibrations whose serial number and sensor model match no item')
        self.only_unassigned.toggled.connect(lambda _on: self.apply_filter())
        self.only_valid = QtWidgets.QCheckBox('valid only')
        self.only_valid.setToolTip('Only the calibration valid at the state time of each sensor')
        self.only_valid.toggled.connect(lambda _on: self.apply_filter())
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.filter, 1)
        top.addWidget(self.only_valid)
        top.addWidget(self.only_unassigned)

        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _i: self.show_sensor())

        self.btn_import = QtWidgets.QPushButton('Import calibration ...')
        self.btn_import.setToolTip('Read calibrations (YAML of the sensor manager); missing sensor items are '
                                   'created. "Save libraries" stores them.')
        self.btn_remove = QtWidgets.QPushButton('Remove')
        self.btn_sensor = QtWidgets.QPushButton('Show sensor')
        self.btn_create = QtWidgets.QPushButton('Create sensor item')
        self.btn_create.setToolTip('An item for the selected calibration without one (type = its sensor model)')
        self.btn_refresh = QtWidgets.QPushButton('Refresh')
        self.btn_import.clicked.connect(lambda: self.import_calibration())
        self.btn_remove.clicked.connect(lambda: self.remove_selected())
        self.btn_sensor.clicked.connect(lambda: self.show_sensor())
        self.btn_create.clicked.connect(lambda: self.create_sensor_item())
        self.btn_refresh.clicked.connect(lambda: self.refresh())
        bl = QtWidgets.QHBoxLayout()
        for b in (self.btn_import, self.btn_remove, self.btn_sensor, self.btn_create, self.btn_refresh):
            bl.addWidget(b)
        bl.addStretch(1)
        self.status = QtWidgets.QLabel('')
        self.status.setWordWrap(True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addLayout(bl)
        lay.addWidget(self.status)
        self.refresh()

    def set_status(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet('color: red' if error else '')

    def set_time(self, at_time=None):
        """State time (None: now): which calibration of a sensor is valid."""
        self._time = at_time
        self.refresh()

    # --- view ---
    def refresh(self):
        from redvypr.devices.sensors.calibration import item_calibration as ic
        storage = self.redvypr._copy_metadata()
        try:
            self._entries = ic.calibration_entries(storage)
        except Exception:
            logger.warning('could not read the calibrations', exc_info=True)
            self._entries = []
        # valid: per sensor (sn, model) the latest with a date before the state time
        t = self._time or datetime.datetime.now(datetime.timezone.utc)
        latest = {}
        for ce in self._entries:
            c = ce.calibration
            d = ic._aware(getattr(c, 'date', None))
            if d is not None and d > t:
                continue
            key = (getattr(c, 'sn', None), getattr(c, 'sensor_model', None))
            if key not in latest or (d or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)) >= \
                    (ic._aware(getattr(latest[key].calibration, 'date', None)) or
                     datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)):
                latest[key] = ce
        valid = {id(ce) for ce in latest.values()}
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._entries))
        for row, ce in enumerate(self._entries):
            c = ce.calibration
            date = getattr(c, 'date', None)
            texts = (ce.sensor_ref or '—', str(getattr(c, 'sn', '') or ''), str(getattr(c, 'sensor_model', '') or ''),
                     str(getattr(c, 'calibration_type', '') or ''),
                     date.isoformat(sep=' ', timespec='seconds') if hasattr(date, 'isoformat') else str(date or ''),
                     'yes' if id(ce) in valid else '', ic.calibration_summary(c), str(getattr(c, 'unit', '') or ''),
                     ce.source or '(this instance)')
            for col, text in enumerate(texts):
                cell = QtWidgets.QTableWidgetItem(text)
                cell.setData(ROLE_UUID, getattr(c, 'calibration_uuid', ''))
                cell.setData(ROLE_REF, ce.sensor_ref or '')
                if col == 0 and ce.sensor_ref is None:
                    cell.setForeground(QtGui.QColor('#c08000'))
                    cell.setToolTip('no sensor item with this serial number and type: "Create sensor item"')
                self.table.setItem(row, col, cell)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.apply_filter()
        return self._entries

    def apply_filter(self):
        words = self.filter.text().lower().split()
        shown = 0
        for row in range(self.table.rowCount()):
            texts = [self.table.item(row, c).text().lower() for c in range(self.table.columnCount())]
            hide = bool(words) and not all(any(w in t for t in texts) for w in words)
            if self.only_unassigned.isChecked() and self.table.item(row, 0).data(ROLE_REF):
                hide = True
            if self.only_valid.isChecked() and texts[COLUMNS.index('Valid')] != 'yes':
                hide = True
            self.table.setRowHidden(row, hide)
            shown += 0 if hide else 1
        unassigned = sum(1 for ce in self._entries if ce.sensor_ref is None)
        self.set_status(f'{shown} of {len(self._entries)} calibration(s) shown' +
                        (f', {unassigned} without sensor item' if unassigned else ''))
        return shown

    def _selected(self):
        """(calibration uuid, sensor ref) of the selected row."""
        row = self.table.currentRow()
        cell = self.table.item(row, 0) if row >= 0 else None
        if cell is None:
            return None, None
        return cell.data(ROLE_UUID), cell.data(ROLE_REF) or None

    def _entry(self, uuid):
        return next((ce for ce in self._entries if getattr(ce.calibration, 'calibration_uuid', None) == uuid), None)

    # --- actions ---
    def show_sensor(self):
        _uuid, ref = self._selected()
        if not ref:
            self.set_status('the selected calibration has no sensor item', error=True)
            return None
        self.item_requested.emit(ref)
        return ref

    def import_calibration(self, path=None):
        from redvypr.devices.sensors.calibration import item_calibration as ic
        if not path:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Import calibration', '',
                                                            'YAML (*.yaml *.yml);;All files (*)')
        if not path:
            return None
        try:
            report = ic.import_calibrations(self.redvypr, ic.read_calibration_file(path))
        except Exception as e:
            self.set_status(f'{os.path.basename(path)} not imported: {e}', error=True)
            return None
        self.refresh()
        created = [ref for _c, ref, new in report if new]
        self.set_status(f'{len(report)} calibration(s) imported' +
                        (', sensor items created: ' + ', '.join(created) if created else '') +
                        '. "Save libraries" stores them.')
        return report

    def remove_selected(self, confirm=None):
        from redvypr.devices.sensors.calibration import item_calibration as ic
        uuid, _ref = self._selected()
        if not uuid:
            self.set_status('select a calibration first', error=True)
            return False
        text = 'Remove the selected calibration from this redvypr instance? A library loses it at the next ' \
               '"Save libraries".'
        ok = confirm(text) if confirm is not None else \
            QtWidgets.QMessageBox.question(self, 'Remove calibration', text) == \
            QtWidgets.QMessageBox.StandardButton.Yes
        if not ok:
            return False
        n = ic.remove_calibration(self.redvypr, uuid)
        self.refresh()
        return bool(n)

    def create_sensor_item(self):
        """An item for the selected calibration without one: type = sensor model, id = serial number."""
        from redvypr.devices.sensors.calibration import item_calibration as ic
        uuid, ref = self._selected()
        ce = self._entry(uuid) if uuid else None
        if ce is None:
            self.set_status('select a calibration first', error=True)
            return None
        if ref:
            self.set_status(f'it has the sensor item {ref} already')
            return ref
        c = ce.calibration
        model = getattr(c, 'sensor_model', None)
        if model in ic.NO_MODEL:
            model = ic.CALIBRATION_ITEMTYPES.get(getattr(c, 'calibration_type', None))
        if not model:
            self.set_status('the calibration names no sensor model: create the item in the tab Items', error=True)
            return None
        report = ic.import_calibrations(self.redvypr, [c])
        self.refresh()
        new_ref = report[0][1] if report else None
        self.set_status(f'sensor item {new_ref} created' if new_ref else 'no item created', error=not new_ref)
        return new_ref
