"""
Type editor of the Items window: item types defined as data (redvypr.item_types,
design note doc/source/design_items.rst, section "Item types as data").

Left: all known item types with their origin (Python, data, both) and file.
Right: the definition of the selected type: description, base, revision,
fields (name, kind, unit, description, default, choices), defaults and
renamed fields; the fields of a Python type it extends are shown read-only.
"Save" writes the definition into a YAML file (new values from "Valid from";
the history and the other contents of the file stay) and registers it.
"""

import datetime
import json
import logging
import os
import typing

import yaml
from PyQt6 import QtCore, QtWidgets

import redvypr.items as ritems
import redvypr.item_types as ritem_types


def _qdt(dt: datetime.datetime) -> QtCore.QDateTime:
    return QtCore.QDateTime.fromMSecsSinceEpoch(int(dt.timestamp() * 1000), QtCore.QTimeZone.utc())


def _pydt(qdt: QtCore.QDateTime) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(qdt.toMSecsSinceEpoch() / 1000, tz=datetime.timezone.utc)

logger = logging.getLogger('redvypr.widgets.item_types')

FIELD_COLUMNS = ['Field', 'Kind', 'Unit', 'Description', 'Default', 'Choices']
DEFAULT_TYPE_FILE = 'item_types.yaml'


def _text_to_value(text: str):
    """Value of a cell: '' -> None, else YAML (numbers, lists, dicts, text)."""
    text = text.strip()
    if text == '':
        return None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


def _value_to_text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _origin_text(name: str) -> str:
    origin = ritem_types.type_origin(name)
    if origin == 'data' and ritem_types._python_type(name) is not None:
        return 'Python + data'
    return {'python': 'Python', 'data': 'data'}.get(origin, origin)


class RedvyprItemTypesWidget(QtWidgets.QWidget):
    """Editor of the item types."""

    types_changed = QtCore.pyqtSignal()

    def __init__(self, redvypr_instance, parent=None, item: typing.Optional[ritems.Item] = None):
        super().__init__(parent)
        self.redvypr = redvypr_instance
        self.setWindowTitle('Item types')
        self.current = None             # name of the type in the form
        self._new = False               # form holds a new type (name editable)

        # --- left: list of types
        self.list = QtWidgets.QTreeWidget()
        self.list.setHeaderLabels(['Type', 'Origin', 'File'])
        self.list.setRootIsDecorated(False)
        self.list.itemSelectionChanged.connect(self.selection_changed)
        self.btn_new = QtWidgets.QPushButton('New')
        self.btn_copy = QtWidgets.QPushButton('Copy')
        self.btn_from_item = QtWidgets.QPushButton('From item')
        self.btn_from_item.setToolTip('Propose a type from the item selected in the Items window: its additional '
                                      'fields become fields of the type')
        self.btn_refresh = QtWidgets.QPushButton('Refresh')
        self.btn_new.clicked.connect(lambda: self.new_type())
        self.btn_copy.clicked.connect(lambda: self.copy_type())
        self.btn_from_item.clicked.connect(lambda: self.type_from_item(self._item))
        self.btn_refresh.clicked.connect(lambda: self.refresh())
        self._item = item
        self.btn_from_item.setEnabled(item is not None)
        left = QtWidgets.QWidget()
        llay = QtWidgets.QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)
        llay.addWidget(self.list, 1)
        bl = QtWidgets.QHBoxLayout()
        for b in (self.btn_new, self.btn_copy, self.btn_from_item, self.btn_refresh):
            bl.addWidget(b)
        llay.addLayout(bl)

        # --- right: definition
        self.title = QtWidgets.QLabel('')
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText('per model, in English, e.g. calypso_CMI1018')
        self.description = QtWidgets.QPlainTextEdit()
        self.description.setFixedHeight(60)
        self.base = QtWidgets.QComboBox()
        self.base.setEditable(True)
        self.revision = QtWidgets.QSpinBox()
        self.revision.setRange(1, 9999)
        self.revision.setToolTip('Count up when fields are renamed or change their meaning (see "Renamed")')
        self.inherited = QtWidgets.QLabel('')
        self.inherited.setWordWrap(True)
        self.inherited.setStyleSheet('color: gray;')

        self.fields = QtWidgets.QTableWidget(0, len(FIELD_COLUMNS))
        self.fields.setHorizontalHeaderLabels(FIELD_COLUMNS)
        self.fields.horizontalHeader().setSectionResizeMode(
            FIELD_COLUMNS.index('Description'), QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.fields.setToolTip('Default and choices as YAML (e.g. 0.5, [NMEA0183, RS485]); a quantity takes a '
                               'number in its unit')
        self.btn_add_field = QtWidgets.QPushButton('Add field')
        self.btn_del_field = QtWidgets.QPushButton('Remove field')
        self.btn_add_field.clicked.connect(lambda: self.add_field_row())
        self.btn_del_field.clicked.connect(lambda: self._remove_row(self.fields))

        self.defaults = QtWidgets.QTableWidget(0, 2)
        self.defaults.setHorizontalHeaderLabels(['Field', 'Value'])
        self.defaults.horizontalHeader().setStretchLastSection(True)
        self.defaults.setToolTip('Values every item of the type gets unless it has its own '
                                 '(e.g. manufacturer, mpn); values as YAML')
        self.btn_add_default = QtWidgets.QPushButton('Add default')
        self.btn_del_default = QtWidgets.QPushButton('Remove default')
        self.btn_add_default.clicked.connect(lambda: self._add_pair(self.defaults))
        self.btn_del_default.clicked.connect(lambda: self._remove_row(self.defaults))

        self.renamed = QtWidgets.QTableWidget(0, 2)
        self.renamed.setHorizontalHeaderLabels(['Old field', 'New field'])
        self.renamed.horizontalHeader().setStretchLastSection(True)
        self.renamed.setToolTip('Fields renamed in this revision: items of older revisions are migrated when read')
        self.btn_add_renamed = QtWidgets.QPushButton('Add rename')
        self.btn_del_renamed = QtWidgets.QPushButton('Remove rename')
        self.btn_add_renamed.clicked.connect(lambda: self._add_pair(self.renamed))
        self.btn_del_renamed.clicked.connect(lambda: self._remove_row(self.renamed))

        self.file = QtWidgets.QComboBox()
        self.file.setEditable(True)
        self.file.setToolTip('YAML file the definition is saved in (section item_types)')
        self.btn_browse = QtWidgets.QPushButton('...')
        self.btn_browse.clicked.connect(self.browse_file)
        self.valid_from = QtWidgets.QDateTimeEdit(_qdt(datetime.datetime.now(datetime.timezone.utc)))
        self.valid_from.setDisplayFormat('yyyy-MM-dd HH:mm:ss UTC')
        self.valid_from.setTimeZone(QtCore.QTimeZone.utc())
        self.btn_save = QtWidgets.QPushButton('Save type')
        self.btn_save.clicked.connect(lambda: self.save())
        self.status = QtWidgets.QLabel('')
        self.status.setWordWrap(True)

        form = QtWidgets.QFormLayout()
        form.addRow('Name', self.name)
        form.addRow('Description', self.description)
        form.addRow('Base', self.base)
        form.addRow('Revision', self.revision)
        form.addRow('Inherited', self.inherited)
        right = QtWidgets.QWidget()
        rlay = QtWidgets.QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.addWidget(self.title)
        rlay.addLayout(form)
        rlay.addWidget(QtWidgets.QLabel('Fields'))
        rlay.addWidget(self.fields, 3)
        fb = QtWidgets.QHBoxLayout()
        fb.addWidget(self.btn_add_field)
        fb.addWidget(self.btn_del_field)
        fb.addStretch(1)
        rlay.addLayout(fb)
        pairs = QtWidgets.QHBoxLayout()
        for label, table, add, rem in (('Defaults', self.defaults, self.btn_add_default, self.btn_del_default),
                                       ('Renamed', self.renamed, self.btn_add_renamed, self.btn_del_renamed)):
            box = QtWidgets.QVBoxLayout()
            box.addWidget(QtWidgets.QLabel(label))
            box.addWidget(table)
            hb = QtWidgets.QHBoxLayout()
            hb.addWidget(add)
            hb.addWidget(rem)
            box.addLayout(hb)
            pairs.addLayout(box)
        rlay.addLayout(pairs, 2)
        save = QtWidgets.QHBoxLayout()
        save.addWidget(QtWidgets.QLabel('File'))
        save.addWidget(self.file, 1)
        save.addWidget(self.btn_browse)
        save.addWidget(QtWidgets.QLabel('Valid from'))
        save.addWidget(self.valid_from)
        save.addWidget(self.btn_save)
        rlay.addLayout(save)
        rlay.addWidget(self.status)

        split = QtWidgets.QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(split)
        self.refresh()
        self.set_type(None)

    # --- helpers ---
    def set_status(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet('color: red' if error else '')

    def set_item(self, item: typing.Optional[ritems.Item]):
        """The item selected in the Items window (for "From item")."""
        self._item = item
        self.btn_from_item.setEnabled(item is not None)

    @staticmethod
    def _remove_row(table):
        rows = sorted({i.row() for i in table.selectedIndexes()}, reverse=True) or \
            ([table.rowCount() - 1] if table.rowCount() else [])
        for r in rows:
            table.removeRow(r)

    @staticmethod
    def _add_pair(table, a='', b=''):
        r = table.rowCount()
        table.insertRow(r)
        table.setItem(r, 0, QtWidgets.QTableWidgetItem(a))
        table.setItem(r, 1, QtWidgets.QTableWidgetItem(b))
        return r

    @staticmethod
    def _cell(table, r, c) -> str:
        w = table.cellWidget(r, c)
        if isinstance(w, QtWidgets.QComboBox):
            return w.currentText()
        it = table.item(r, c)
        return it.text() if it is not None else ''

    def add_field_row(self, name='', fd: typing.Optional[ritem_types.FieldDefinition] = None):
        fd = fd or ritem_types.FieldDefinition()
        r = self.fields.rowCount()
        self.fields.insertRow(r)
        self.fields.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
        kind = QtWidgets.QComboBox()
        kind.addItems(list(ritem_types.KINDS))
        kind.setCurrentText(fd.kind)
        self.fields.setCellWidget(r, 1, kind)
        for c, v in ((2, fd.unit), (3, fd.description), (4, _value_to_text(fd.default)),
                     (5, _value_to_text(fd.choices))):
            self.fields.setItem(r, c, QtWidgets.QTableWidgetItem(v or ''))
        return r

    # --- list ---
    def refresh(self):
        try:
            self.redvypr.resolve_item_types()
        except Exception:
            logger.debug('could not resolve the item types', exc_info=True)
        names = sorted(n for n in ritems.ITEM_TYPES if n != 'item')
        self.list.blockSignals(True)
        self.list.clear()
        for n in names:
            src = ritem_types.TYPE_SOURCES.get(n, '') if ritem_types.type_origin(n) == 'data' else ''
            w = QtWidgets.QTreeWidgetItem([n, _origin_text(n), os.path.basename(src) if src else ''])
            w.setToolTip(2, src)
            w.setData(0, QtCore.Qt.ItemDataRole.UserRole, n)
            self.list.addTopLevelItem(w)
            if n == self.current:
                self.list.setCurrentItem(w)
        self.list.blockSignals(False)
        for c in range(3):
            self.list.resizeColumnToContents(c)
        current_base = self.base.currentText()
        self.base.clear()
        self.base.addItem('')
        self.base.addItems(names)
        self.base.setCurrentText(current_base)
        current_file = self.file.currentText()
        self.file.clear()
        try:
            files = self.redvypr.item_type_files()
        except Exception:
            files = []
        if not files:
            files = [self._default_file()]
        self.file.addItems(files)
        if current_file:
            self.file.setCurrentText(current_file)

    def _default_file(self) -> str:
        libs = list(getattr(self.redvypr, 'item_libraries', []) or [])
        folder = os.path.dirname(os.path.abspath(libs[0])) if libs else os.getcwd()
        return os.path.join(folder, DEFAULT_TYPE_FILE)

    def selection_changed(self):
        w = self.list.currentItem()
        name = w.data(0, QtCore.Qt.ItemDataRole.UserRole) if w is not None else None
        self.set_type(name)

    # --- form ---
    def set_type(self, name: typing.Optional[str], defn: typing.Optional[ritem_types.TypeDefinition] = None,
                 new: bool = False):
        """Shows a type (its data definition, or an empty one for a Python type) or a new definition."""
        self.current = name
        self._new = new
        self.fields.setRowCount(0)
        self.defaults.setRowCount(0)
        self.renamed.setRowCount(0)
        enabled = name is not None or defn is not None
        for w in (self.name, self.description, self.base, self.revision, self.fields, self.defaults,
                  self.renamed, self.btn_save, self.btn_add_field, self.btn_del_field, self.btn_add_default,
                  self.btn_del_default, self.btn_add_renamed, self.btn_del_renamed, self.btn_copy):
            w.setEnabled(enabled)
        if not enabled:
            self.title.setText('No type selected')
            self.name.setText('')
            self.description.setPlainText('')
            self.inherited.setText('')
            return
        if defn is None:
            defn = ritem_types.definition_of(name) or ritem_types.TypeDefinition(name=name)
        self.name.setText(defn.name)
        self.name.setReadOnly(not new)
        self.description.setPlainText(defn.description or '')
        self.base.setCurrentText(defn.base or '')
        self.revision.setValue(defn.revision)
        for fname, fd in defn.fields.items():
            self.add_field_row(fname, fd)
        for k, v in defn.defaults.items():
            self._add_pair(self.defaults, k, _value_to_text(v))
        for k, v in defn.renamed.items():
            self._add_pair(self.renamed, k, v)
        py = ritem_types._python_type(defn.name)
        self.base.setEnabled(py is None)
        inherited_cls = py or (ritems.ITEM_TYPES.get(defn.base) if defn.base else None) or ritems.Item
        own = set(defn.fields)
        names = [k for k in ritem_types.python_fields(inherited_cls) if k not in own]
        self.inherited.setText(f'{inherited_cls.__name__ if py is not None else (defn.base or "Item")}: '
                               + ', '.join(names))
        src = ritem_types.TYPE_SOURCES.get(defn.name)
        if src:
            self.file.setCurrentText(os.path.abspath(src))
        origin = 'new type' if new else _origin_text(defn.name)
        note = ' (fields of the Python type stay; a definition extends it)' if py is not None else ''
        self.title.setText(f'<b>{defn.name}</b> ({origin}){note}')
        self.valid_from.setDateTime(_qdt(datetime.datetime.now(datetime.timezone.utc)))

    def form_definition(self) -> ritem_types.TypeDefinition:
        """The definition in the form (raises ValueError with a readable text)."""
        name = self.name.text().strip()
        if not name:
            raise ValueError('the type needs a name')
        fields = {}
        for r in range(self.fields.rowCount()):
            fname = self._cell(self.fields, r, 0).strip()
            if not fname:
                continue
            if not fname.isidentifier():
                raise ValueError(f'field name {fname!r}: letters, digits and _ only')
            if fname in fields:
                raise ValueError(f'field {fname!r} twice')
            choices = _text_to_value(self._cell(self.fields, r, 5))
            if choices is not None and not isinstance(choices, list):
                choices = [choices]
            fields[fname] = ritem_types.FieldDefinition(
                kind=self._cell(self.fields, r, 1) or 'str',
                unit=self._cell(self.fields, r, 2).strip() or None,
                description=self._cell(self.fields, r, 3).strip() or None,
                default=_text_to_value(self._cell(self.fields, r, 4)),
                choices=choices)
        defaults = {}
        for r in range(self.defaults.rowCount()):
            k = self._cell(self.defaults, r, 0).strip()
            if k:
                defaults[k] = _text_to_value(self._cell(self.defaults, r, 1))
        renamed = {}
        for r in range(self.renamed.rowCount()):
            old, new = self._cell(self.renamed, r, 0).strip(), self._cell(self.renamed, r, 1).strip()
            if old and new:
                renamed[old] = new
        base = self.base.currentText().strip() or None
        if base == name:
            base = None
        return ritem_types.TypeDefinition(
            name=name, description=self.description.toPlainText().strip() or None, base=base,
            revision=self.revision.value(), fields=fields, defaults=defaults, renamed=renamed)

    # --- actions ---
    def new_type(self):
        self.list.clearSelection()
        self.set_type(None, ritem_types.TypeDefinition(name=''), new=True)
        self.name.setFocus()
        self.set_status('new type: give a name (per model, in English) and the fields')

    def copy_type(self):
        try:
            defn = self.form_definition()
        except ValueError as e:
            self.set_status(str(e), error=True)
            return
        copy = defn.model_copy(update={'name': '', 'revision': 1, 'renamed': {}})
        self.set_type(None, copy, new=True)
        self.set_status(f'copy of {defn.name}: give the new name')

    def type_from_item(self, item: typing.Optional[ritems.Item]):
        if item is None:
            self.set_status('select an item in the Items window first', error=True)
            return
        defn = ritem_types.definition_from_item(item)
        existing = ritem_types.definition_of(item.itemtype)
        if existing is not None:
            # keep the existing definition, add the additional fields of the item
            fields = dict(existing.fields)
            for k, v in defn.fields.items():
                fields.setdefault(k, v)
            defaults = dict(defn.defaults)
            defaults.update(existing.defaults)
            defn = existing.model_copy(update={'fields': fields, 'defaults': defaults})
        self.set_type(item.itemtype, defn, new=item.itemtype not in ritems.ITEM_TYPES)
        self.name.setReadOnly(True)          # the type of the item
        self.set_status(f'proposed from {item.ref}: check kinds, units and descriptions, then save')

    def browse_file(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'File of the item type', self.file.currentText() or self._default_file(),
            'YAML (*.yaml *.yml)', options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
        if path:
            self.file.setCurrentText(path)

    def save(self, path: typing.Optional[str] = None) -> bool:
        try:
            defn = self.form_definition()
        except (ValueError, Exception) as e:
            self.set_status(f'not saved: {e}', error=True)
            return False
        path = path or self.file.currentText().strip()
        if not path:
            self.set_status('not saved: choose a file', error=True)
            return False
        if not path.lower().endswith(ritem_types.TYPE_FILE_SUFFIXES):
            self.set_status('not saved: the file must be a YAML file (.yaml)', error=True)
            return False
        if self._new and defn.name in ritems.ITEM_TYPES:
            self.set_status(f'not saved: the type {defn.name} exists already', error=True)
            return False
        vf = _pydt(self.valid_from.dateTime())
        try:
            self.redvypr.save_item_type(defn, path, valid_from=vf)
        except Exception as e:
            self.set_status(f'not saved: {e}', error=True)
            return False
        self.current = defn.name
        self._new = False
        self.refresh()
        self.set_type(defn.name)
        self.set_status(f'{defn.name} saved in {path}')
        self.types_changed.emit()
        return True
