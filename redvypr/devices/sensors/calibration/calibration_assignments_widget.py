"""
Widgets for the calibration assignments (calibration_assignments.py): which data a calibration converts.

* :class:`AssignmentDialog`: filter (redvypr address of the raw data), sensor (sn, type) or calibration
  (uuid), name of the result, unit of the raw data.
* :class:`CalibrationAssignmentsWidget`: the assignments of a device (generic_sensor): add, edit,
  remove, write the configuration into the metadata ("Save to metadata") and read the state of a
  date from the metadata ("Load from metadata").
"""

import datetime
import logging
import typing

import pydantic
from PyQt6 import QtCore, QtWidgets

from redvypr.redvypr_address import RedvyprAddress
from redvypr.devices.sensors.calibration import calibration_assignments as cass

logger = logging.getLogger('redvypr.calibration_assignments_widget')


def _qdt(dt: datetime.datetime) -> QtCore.QDateTime:
    return QtCore.QDateTime.fromMSecsSinceEpoch(int(dt.timestamp() * 1000), QtCore.QTimeZone.utc())


def _pydt(qdt: QtCore.QDateTime) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(qdt.toMSecsSinceEpoch() / 1000, tz=datetime.timezone.utc)


class AssignmentDialog(QtWidgets.QDialog):
    """Filter, calibration (sn or uuid), result and raw unit of an assignment."""

    def __init__(self, redvypr_instance=None, parent=None,
                 assignment: typing.Optional[cass.CalibrationAssignment] = None, preset: typing.Optional[dict] = None):
        """assignment: edit it; preset: values (sn, type, uuid, ...) for a new one."""
        super().__init__(parent)
        self.redvypr = redvypr_instance
        self.setWindowTitle('Calibration assignment')
        values = dict(preset or {})
        if assignment is not None:
            values = dict(assignment.value(), filter=assignment.address)
        self.filter = QtWidgets.QLineEdit(str(values.get('filter') or ''))
        self.filter.setPlaceholderText("raw data, e.g. hf0 @ i:'adc' and di:'<hwid>'")
        self.filter.setToolTip('Redvypr address of the data the calibration converts: the packet filters and '
                               'the datakey of the raw value')
        self.btn_choose = QtWidgets.QPushButton('Choose ...')
        self.btn_choose.setEnabled(redvypr_instance is not None)
        self.btn_choose.clicked.connect(self.choose_datastream)
        self.sn = QtWidgets.QLineEdit(str(values.get('sn') or ''))
        self.sn.setToolTip('Serial number of the sensor: its calibration valid at the time of the data is used')
        self.type = QtWidgets.QLineEdit(str(values.get('type') or ''))
        self.type.setPlaceholderText('item type of the sensor, e.g. hf_sensor (optional)')
        self.uuid = QtWidgets.QLineEdit(str(values.get('uuid') or ''))
        self.uuid.setPlaceholderText('calibration_uuid: exactly this calibration (instead of the sn)')
        self.result = QtWidgets.QLineEdit(str(values.get('result') or ''))
        self.result.setPlaceholderText('datakey of the result (empty: replaces the raw data)')
        self.result.setToolTip('The datakey the converted data are written to; {datakey} is the raw datakey')
        self.raw_unit = QtWidgets.QLineEdit(str(values.get('raw_unit') or ''))
        self.raw_unit.setPlaceholderText('unit of the raw data, e.g. V (optional)')
        self.raw_unit.setToolTip('Converted to the input unit of the calibration (V -> mV)')
        self.status = QtWidgets.QLabel('')
        self.status.setStyleSheet('color: red')
        self.status.setWordWrap(True)
        lay = QtWidgets.QFormLayout(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.filter, 1)
        row.addWidget(self.btn_choose)
        lay.addRow('Filter', row)
        lay.addRow('Sensor sn', self.sn)
        lay.addRow('Sensor type', self.type)
        lay.addRow('or calibration', self.uuid)
        lay.addRow('Result', self.result)
        lay.addRow('Raw unit', self.raw_unit)
        lay.addRow(self.status)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                                  QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept_if_valid)
        self.buttons.rejected.connect(self.reject)
        lay.addRow(self.buttons)

    def choose_datastream(self):
        from redvypr.widgets.redvypr_address_widget import RedvyprAddressWidget
        self._chooser = RedvyprAddressWidget(redvypr=self.redvypr)
        self._chooser.apply.connect(self._datastream_chosen)
        self._chooser.show()

    def _datastream_chosen(self, address_dict):
        if 'address_str' in address_dict:
            self.filter.setText(address_dict['address_str'])

    def assignment(self) -> cass.CalibrationAssignment:
        """The assignment of the form (raises ValueError with a readable text)."""
        text = self.filter.text().strip()
        if not text:
            raise ValueError('the assignment needs a filter: the address of the raw data')
        try:
            RedvyprAddress(text)
        except Exception as e:
            raise ValueError(f'filter: {e}')
        try:
            return cass.CalibrationAssignment(
                filter=text, sn=self.sn.text().strip() or None, type=self.type.text().strip() or None,
                uuid=self.uuid.text().strip() or None, result=self.result.text().strip() or None,
                raw_unit=self.raw_unit.text().strip() or None)
        except pydantic.ValidationError as e:
            msg = e.errors()[0].get('msg', str(e))
            raise ValueError(msg.removeprefix('Value error, '))

    def problem(self) -> typing.Optional[str]:
        try:
            self.assignment()
        except ValueError as e:
            return str(e)
        return None

    def _accept_if_valid(self):
        p = self.problem()
        if p:
            self.status.setText(p)
            return
        self.accept()


class CalibrationAssignmentsWidget(QtWidgets.QWidget):
    """
    The calibration assignments of a device (needs ``custom_config.calibration_assignments``,
    ``update_subscriptions()``, ``assignments_to_metadata()`` and ``assignments_from_metadata()``).
    """
    COLUMNS = ['Filter', 'Calibration', 'Type', 'Result', 'Raw unit']

    def __init__(self, device, parent=None):
        super().__init__(parent)
        self.device = device
        self.setWindowTitle('Calibration assignments')
        self.table = QtWidgets.QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _i: self.edit())
        self.table.setToolTip('Which data a calibration converts. The configuration of the device holds them; '
                              '"Save to metadata" keeps them with their history in the metadata (libraries)')
        self.btn_add = QtWidgets.QPushButton('Add ...')
        self.btn_edit = QtWidgets.QPushButton('Edit ...')
        self.btn_remove = QtWidgets.QPushButton('Remove')
        self.btn_save = QtWidgets.QPushButton('Save to metadata ...')
        self.btn_save.setToolTip('Writes these assignments into the metadata as the state from a time on: new '
                                 'or changed ones start, ones of this device that are not listed end')
        self.btn_load = QtWidgets.QPushButton('Load from metadata ...')
        self.btn_load.setToolTip('Replaces these assignments by the state of this device at a date')
        self.btn_add.clicked.connect(lambda: self.add())
        self.btn_edit.clicked.connect(lambda: self.edit())
        self.btn_remove.clicked.connect(lambda: self.remove())
        self.btn_save.clicked.connect(lambda: self.save_to_metadata())
        self.btn_load.clicked.connect(lambda: self.load_from_metadata())
        self.status = QtWidgets.QLabel('')
        self.status.setWordWrap(True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        for b in (self.btn_add, self.btn_edit, self.btn_remove):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_load)
        lay.addLayout(row)
        lay.addWidget(self.status)
        self.refresh()

    # --- list ---
    def assignments(self) -> list:
        return list(self.device.custom_config.calibration_assignments)

    def set_assignments(self, assignments):
        self.device.custom_config.calibration_assignments = list(assignments)
        try:
            self.device.update_subscriptions()
            if hasattr(self.device, 'config_changed_signal'):
                self.device.config_changed_signal.emit()
        except Exception:
            logger.warning('could not update the device', exc_info=True)
        self.refresh()

    def refresh(self):
        items = self.assignments()
        self.table.setRowCount(len(items))
        for row, a in enumerate(items):
            what = a.uuid if a.uuid and not a.sn else (f'sn {a.sn}' + (f' (uuid {a.uuid})' if a.uuid else ''))
            for col, text in enumerate((a.address, what, a.type or '', a.result or '', a.raw_unit or '')):
                self.table.setItem(row, col, QtWidgets.QTableWidgetItem(text))
        self.table.resizeColumnsToContents()

    def set_status(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet('color: red' if error else '')

    def _redvypr(self):
        return getattr(self.device, 'redvypr', None)

    # --- actions ---
    def add(self, assignment: typing.Optional[cass.CalibrationAssignment] = None, preset: typing.Optional[dict] = None):
        """Adds an assignment (without the dialog if given); returns it, None if cancelled."""
        if assignment is None:
            dlg = AssignmentDialog(self._redvypr(), self, preset=preset)
            if not dlg.exec():
                return None
            assignment = dlg.assignment()
        # one calibration per filter: a new one replaces the old one with the same filter
        items = [a for a in self.assignments() if a.address != assignment.address] + [assignment]
        self.set_assignments(items)
        self.set_status(f'assignment added: {assignment.address}')
        return assignment

    def _current_row(self) -> int:
        return self.table.currentRow()

    def edit(self, assignment: typing.Optional[cass.CalibrationAssignment] = None):
        row = self._current_row()
        items = self.assignments()
        if row < 0 or row >= len(items):
            self.set_status('select an assignment first', error=True)
            return None
        if assignment is None:
            dlg = AssignmentDialog(self._redvypr(), self, assignment=items[row])
            if not dlg.exec():
                return None
            assignment = dlg.assignment()
        items[row] = assignment
        seen, out = set(), []
        for a in items:              # the edited filter may equal another one
            if a.address in seen:
                out = [x for x in out if x.address != a.address]
            seen.add(a.address)
            out.append(a)
        self.set_assignments(out)
        return assignment

    def remove(self):
        row = self._current_row()
        items = self.assignments()
        if row < 0 or row >= len(items):
            self.set_status('select an assignment first', error=True)
            return False
        gone = items.pop(row)
        self.set_assignments(items)
        self.set_status(f'assignment removed: {gone.address}')
        return True

    def _ask_time(self, title, label) -> typing.Optional[datetime.datetime]:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(title)
        lay = QtWidgets.QFormLayout(dlg)
        edit = QtWidgets.QDateTimeEdit(_qdt(datetime.datetime.now(datetime.timezone.utc)))
        edit.setDisplayFormat('yyyy-MM-dd HH:mm:ss UTC')
        edit.setTimeZone(QtCore.QTimeZone.utc())
        lay.addRow(label, edit)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                             QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addRow(buttons)
        return _pydt(edit.dateTime()) if dlg.exec() else None

    def save_to_metadata(self, valid_from: typing.Optional[datetime.datetime] = None, ask: bool = True):
        """Writes the assignments into the metadata from valid_from on (asks for the time unless ask is False)."""
        if valid_from is None and ask:
            valid_from = self._ask_time('Save to metadata', 'Valid from')
            if valid_from is None:
                return None
        try:
            changed = self.device.assignments_to_metadata(valid_from=valid_from)
        except Exception as e:
            self.set_status(f'not saved: {e}', error=True)
            return None
        self.set_status(f'{len(changed)} address(es) changed in the metadata' if changed
                        else 'nothing changed in the metadata. "Save libraries" stores the metadata of a library.')
        return changed

    def load_from_metadata(self, at_time: typing.Optional[datetime.datetime] = None, ask: bool = True):
        """Replaces the assignments by the state of this device at a time (asks for the time unless ask is False)."""
        if at_time is None and ask:
            at_time = self._ask_time('Load from metadata', 'State at')
            if at_time is None:
                return None
        try:
            assignments = self.device.assignments_from_metadata(at_time=at_time)
        except Exception as e:
            self.set_status(f'not loaded: {e}', error=True)
            return None
        self.refresh()
        self.set_status(f'{len(assignments)} assignment(s) loaded from the metadata')
        return assignments
