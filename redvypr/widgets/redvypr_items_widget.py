"""
Items window: the items (sensors, boards, ...) of the metadata as a tree by
'parent', a form of the selected item, its history, moving it to another
parent/slot and item library files. Design: doc/source/design_items.rst.
"""

import datetime
import json
import logging
import os
import types
import typing

import yaml
from PyQt6 import QtCore, QtGui, QtWidgets

import redvypr.items as ritems
import redvypr.item_types as ritem_types
from redvypr.metadata_sources import LoadCancelled
from redvypr.widgets.load_progress import LoadProgress

logger = logging.getLogger('redvypr.widgets.items')

ROLE_REF = QtCore.Qt.ItemDataRole.UserRole + 1
UTC = datetime.timezone.utc
# Fields not edited in the form (address, bookkeeping)
FORM_SKIP = ('itemtype', 'id', 'type_revision', 'attachments')
# Fields not edited in the form but in their own tab: taken over from the stored item when saving
MANAGED_FIELDS = ('attachments',)


LIBRARY_FILTER = ('Item library (*.yaml *.yml *.sqlite *.sqlite3 *.db);;YAML (*.yaml *.yml);;'
                  'SQLite (*.sqlite *.sqlite3 *.db);;All files (*)')


def now_utc():
    return datetime.datetime.now(UTC)


def _qdt(dt: datetime.datetime) -> QtCore.QDateTime:
    return QtCore.QDateTime.fromSecsSinceEpoch(int(dt.timestamp()), QtCore.QTimeZone.utc())


def _pydt(qdt: QtCore.QDateTime) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(qdt.toSecsSinceEpoch(), UTC)


def _base_type(annotation):
    """str, int, float, bool or None (anything else: edited as JSON/YAML text)."""
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            annotation = args[0]
    return annotation if annotation in (str, int, float, bool) else None


def value_to_text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json', exclude_none=True)
    return json.dumps(value, ensure_ascii=False, default=str)


def text_to_value(text: str, base):
    """Value of a form field: '' -> None; str/int/float/bool by type; else JSON or YAML."""
    text = text.strip()
    if text == '':
        return None
    if base is str:
        return text
    if base is int:
        return int(text)
    if base is float:
        return float(text)
    if base is bool:
        return text.lower() in ('1', 'true', 'yes', 'ja', 'on')
    try:
        return json.loads(text)
    except ValueError:
        return yaml.safe_load(text)


class NewItemDialog(QtWidgets.QDialog):
    """Type, id and validity of a new item (optionally a copy of another one)."""

    def __init__(self, parent=None, itemtype='', copy_of=None):
        super().__init__(parent)
        self.setWindowTitle('New item' if copy_of is None else f'Copy of {copy_of}')
        lay = QtWidgets.QFormLayout(self)
        self.itemtype = QtWidgets.QComboBox()
        self.itemtype.setEditable(True)
        self.itemtype.addItems(sorted(t for t in ritems.ITEM_TYPES if t != 'item') + ['item'])
        self.itemtype.setCurrentText(itemtype)
        self.item_id = QtWidgets.QLineEdit()
        self.item_id.setPlaceholderText('serial number or name, unique per type')
        self.valid_from = QtWidgets.QDateTimeEdit(_qdt(now_utc()))
        self.valid_from.setDisplayFormat('yyyy-MM-dd HH:mm:ss UTC')
        self.valid_from.setTimeZone(QtCore.QTimeZone.utc())
        self.with_uuid = QtWidgets.QCheckBox('create a globally unique uuid')
        lay.addRow('Type', self.itemtype)
        lay.addRow('Id', self.item_id)
        lay.addRow('Valid from', self.valid_from)
        lay.addRow('', self.with_uuid)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                             QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addRow(buttons)

    def values(self):
        return self.itemtype.currentText().strip(), self.item_id.text().strip(), _pydt(self.valid_from.dateTime())


def item_label(item: ritems.Item) -> str:
    """Reference of an item with its serial number and name, e.g. 'norlog_v02/6BD5... (sn 003)'."""
    extra = [f'sn {item.sn}'] if getattr(item, 'sn', None) and item.sn != item.id else []
    if item.name:
        extra.append(item.name)
    return f"{item.ref} ({', '.join(extra)})" if extra else item.ref


class MoveItemDialog(QtWidgets.QDialog):
    """New parent and slot of an item from a time on."""

    def __init__(self, parent, item: ritems.Item, candidates: typing.List[typing.Union[str, ritems.Item]],
                 all_items: typing.Optional[typing.List[ritems.Item]] = None):
        """all_items: the items at the time of interest, for the slots suggested by the parent."""
        super().__init__(parent)
        self._item = item
        self._all_items = list(all_items) if all_items is not None else [c for c in candidates
                                                                         if not isinstance(c, str)]
        self.setWindowTitle(f'Move {item.ref}')
        lay = QtWidgets.QFormLayout(self)
        self.parent_ref = QtWidgets.QComboBox()
        self.parent_ref.setEditable(True)
        self.parent_ref.addItem('(none)', '')
        for cand in candidates:
            ref = cand if isinstance(cand, str) else cand.ref
            if ref != item.ref:
                self.parent_ref.addItem(ref if isinstance(cand, str) else item_label(cand), ref)
        i = self.parent_ref.findData(item.parent or '')
        self.parent_ref.setCurrentIndex(max(i, 0))
        self.slot = QtWidgets.QComboBox()
        self.slot.setEditable(True)
        self.slot.lineEdit().setPlaceholderText('e.g. the channel name (ntc0) or a terminal')
        self.slot.setToolTip('Suggestions: the slots of the parent (and of its parents) that accept this item '
                             'type; other names can be typed')
        self.slot_hint = QtWidgets.QLabel('')
        self.slot_hint.setWordWrap(True)
        self._initial_slot = item.slot or ''
        self.parent_ref.currentIndexChanged.connect(lambda _i: self.update_slots())
        self.slot.currentIndexChanged.connect(self._slot_chosen)
        self.slot.editTextChanged.connect(lambda _t: self._slot_hint())
        self.update_slots(keep=self._initial_slot)
        self.valid_from = QtWidgets.QDateTimeEdit(_qdt(now_utc()))
        self.valid_from.setDisplayFormat('yyyy-MM-dd HH:mm:ss UTC')
        self.valid_from.setTimeZone(QtCore.QTimeZone.utc())
        lay.addRow('Parent', self.parent_ref)
        lay.addRow('Slot', self.slot)
        lay.addRow('', self.slot_hint)
        lay.addRow('From', self.valid_from)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                             QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addRow(buttons)

    def _parent(self) -> typing.Optional[str]:
        text = self.parent_ref.currentText().strip()
        i = self.parent_ref.currentIndex()
        # a chosen entry gives its reference (the text shows sn and name), else the typed reference
        ref = self.parent_ref.itemData(i) if i >= 0 and text == self.parent_ref.itemText(i) else text
        return None if ref in ('', '(none)', None) else ref

    def update_slots(self, keep: typing.Optional[str] = None):
        """Fills the slot suggestions from the parent; the typed/current slot is kept (keep: set it)."""
        current = self.slot.currentText().strip() if keep is None else keep
        options = ritems.slot_options(self._all_items, self._parent(), self._item.itemtype,
                                      exclude_ref=self._item.ref)
        self.slot.blockSignals(True)
        self.slot.clear()
        self.slot.addItem('', '')
        for o in options:
            text = o['slot'] + (f"  ({o['label']})" if o['label'] else '')
            if o['occupied_by']:
                text += f"  - occupied by {o['occupied_by']}"
            self.slot.addItem(text, o['slot'])
        self.slot.setEditText(current)
        self.slot.blockSignals(False)
        self._options = {o['slot']: o for o in options}
        self._slot_hint()

    def _slot_chosen(self, i):
        data = self.slot.itemData(i)
        if data:
            self.slot.setEditText(data)
        self._slot_hint()

    def _slot_hint(self):
        o = self._options.get(self.slot.currentText().strip())
        self.slot_hint.setText(f"Slot already used by {o['occupied_by']} (it is not removed)"
                               if o and o['occupied_by'] else '')

    def values(self):
        text = self.slot.currentText().strip()
        i = self.slot.currentIndex()
        slot = self.slot.itemData(i) if i >= 0 and text == self.slot.itemText(i) else text
        return self._parent(), (slot or None), _pydt(self.valid_from.dateTime())


class RedvyprItemsWidget(QtWidgets.QWidget):
    """
    The items of a redvypr instance. Left: tree by parent at a chosen time
    (default now), filter by type. Right: form of the selected item (saved as
    new values from a time on) and its history.
    """

    # the item type in the title was clicked (name of the type)
    type_requested = QtCore.pyqtSignal(str)

    def __init__(self, redvypr_instance, parent=None, embedded: bool = False):
        """embedded: part of the Metadata window, which has the libraries, git, types and the time."""
        super().__init__(parent)
        self.redvypr = redvypr_instance
        self.embedded = embedded
        self.setWindowTitle('Items')
        self.current_ref = None
        self._form_time = None          # state time of the item in the form
        self.form_fields = {}           # key -> (QLineEdit, base type)

        # --- left: filter, time, tree, buttons
        self.type_filter = QtWidgets.QComboBox()
        self.type_filter.currentIndexChanged.connect(self.refresh)
        self.flat = QtWidgets.QCheckBox('flat')
        self.flat.setToolTip('All items as a list, without the tree by parent')
        self.flat.toggled.connect(lambda _on: self.refresh())
        self.use_now = QtWidgets.QCheckBox('now')
        self.use_now.setChecked(True)
        self.at_time = QtWidgets.QDateTimeEdit(_qdt(now_utc()))
        self.at_time.setDisplayFormat('yyyy-MM-dd HH:mm:ss UTC')
        self.at_time.setTimeZone(QtCore.QTimeZone.utc())
        self.at_time.setEnabled(False)
        self.use_now.toggled.connect(lambda on: (self.at_time.setEnabled(not on), self.refresh()))
        self.at_time.dateTimeChanged.connect(lambda _dt: self.refresh())
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel('Type'))
        top.addWidget(self.type_filter, 1)
        top.addWidget(self.flat)
        self.at_time_label = QtWidgets.QLabel('State at')
        top.addWidget(self.at_time_label)
        top.addWidget(self.at_time)
        top.addWidget(self.use_now)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(['Item', 'SN', 'Name', 'Slot', 'Status'])
        self.tree.itemSelectionChanged.connect(self.selection_changed)

        self.btn_new = QtWidgets.QPushButton('New')
        self.btn_copy = QtWidgets.QPushButton('Copy')
        self.btn_move = QtWidgets.QPushButton('Move to ...')
        self.btn_delete = QtWidgets.QPushButton('Delete ...')
        self.btn_delete.setToolTip('Remove the selected item with its whole history (for mistakes; an item '
                                   'that is no longer used gets status "retired" instead)')
        self.btn_load = QtWidgets.QPushButton('Load library ...')
        self.btn_load_dir = QtWidgets.QPushButton('Load folder ...')
        self.btn_load_dir.setToolTip('Load a directory library (one file per item and calibration, '
                                     'marked by redvypr_library.yaml)')
        self.btn_load_dir.clicked.connect(lambda: self.load_library(folder=True))
        self.btn_save_lib = QtWidgets.QPushButton('Save libraries')
        self.btn_save_lib.setToolTip('Save every loaded library file: each item and calibration into the file '
                                     'it was loaded from, new ones into the first file of their kind')
        self.btn_save_as = QtWidgets.QPushButton('Save library as ...')
        self.btn_refresh = QtWidgets.QPushButton('Refresh')
        self.btn_types = QtWidgets.QPushButton('Types ...')
        self.btn_types.setToolTip('Editor of the item types (types defined as data, YAML file item_types)')
        self.btn_types.clicked.connect(lambda: self.open_types())
        self.types_widget = None
        self.btn_git = QtWidgets.QPushButton('Git ...')
        self.btn_git.setToolTip('Changes of the item files in git: commit, pull, push')
        self.btn_git.clicked.connect(lambda: self.open_git())
        self.git_widget = None
        self.btn_new.clicked.connect(lambda: self.new_item())
        self.btn_copy.clicked.connect(lambda: self.new_item(copy=True))
        self.btn_move.clicked.connect(self.move_item)
        self.btn_delete.clicked.connect(lambda: self.delete_item())
        self.btn_load.clicked.connect(self.load_library)
        self.btn_save_lib.clicked.connect(lambda: self.save_libraries())
        self.btn_save_as.clicked.connect(lambda: self.save_library())
        self.btn_refresh.clicked.connect(self.refresh)
        buttons = QtWidgets.QGridLayout()
        for i, b in enumerate((self.btn_new, self.btn_copy, self.btn_move, self.btn_delete,
                               self.btn_load, self.btn_load_dir, self.btn_save_lib, self.btn_save_as,
                               self.btn_refresh, self.btn_types, self.btn_git)):
            buttons.addWidget(b, i // 4, i % 4)

        left = QtWidgets.QWidget()
        llay = QtWidgets.QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)
        llay.addLayout(top)
        llay.addWidget(self.tree, 1)
        llay.addLayout(buttons)

        # --- right: form and history
        self.title = QtWidgets.QLabel('')
        self.title.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse |
                                           QtCore.Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.title.setOpenExternalLinks(False)
        self.title.linkActivated.connect(self._title_link)
        self.form_widget = QtWidgets.QWidget()
        self.form = QtWidgets.QFormLayout(self.form_widget)
        form_scroll = QtWidgets.QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setWidget(self.form_widget)
        self.new_key = QtWidgets.QLineEdit()
        self.new_key.setPlaceholderText('new field')
        self.btn_add_field = QtWidgets.QPushButton('Add field')
        self.btn_add_field.clicked.connect(self.add_field)
        addf = QtWidgets.QHBoxLayout()
        addf.addWidget(self.new_key, 1)
        addf.addWidget(self.btn_add_field)
        self.valid_from = QtWidgets.QDateTimeEdit(_qdt(now_utc()))
        self.valid_from.setDisplayFormat('yyyy-MM-dd HH:mm:ss UTC')
        self.valid_from.setTimeZone(QtCore.QTimeZone.utc())
        self.btn_save = QtWidgets.QPushButton('Save changes')
        self.btn_save.clicked.connect(self.save_item)
        save = QtWidgets.QHBoxLayout()
        save.addWidget(QtWidgets.QLabel('Valid from'))
        save.addWidget(self.valid_from)
        save.addWidget(self.btn_save, 1)
        self.history = QtWidgets.QTableWidget(0, 5)
        self.history.setHorizontalHeaderLabels(['Field', 'Value', 'Valid from', 'Valid until', 'Source'])
        self.history.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history.horizontalHeader().setStretchLastSection(True)

        right = QtWidgets.QWidget()
        rlay = QtWidgets.QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.addWidget(self.title)
        rlay.addWidget(form_scroll, 2)
        rlay.addLayout(addf)
        rlay.addLayout(save)
        # calibrations of the item (serial number and type)
        self.calibrations = QtWidgets.QTableWidget(0, 7)
        self.calibrations.setHorizontalHeaderLabels(['Date', 'Valid', 'Type', 'Channel', 'Coefficients',
                                                     'Unit', 'Sensor model'])
        self.calibrations.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.calibrations.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.calibrations.horizontalHeader().setStretchLastSection(True)
        self.calibrations.setToolTip('Calibrations with the serial number of the item and its type as sensor '
                                     'model (NA: any type); "valid": the one used at the state time')
        self.btn_import_cal = QtWidgets.QPushButton('Import calibration ...')
        self.btn_import_cal.setToolTip('Read calibrations (YAML of the sensor manager); a calibration without '
                                       'serial number takes that of the selected item; missing sensor items '
                                       'are created. "Save libraries" stores them (calibrations.yaml).')
        self.btn_remove_cal = QtWidgets.QPushButton('Remove calibration')
        self.btn_apply_cal = QtWidgets.QPushButton('Apply to datastream ...')
        self.btn_apply_cal.setToolTip('Which data this calibration converts: adds a calibration assignment (filter = '
                                      'address of the raw data) to the configuration of a generic_sensor device')
        self.btn_import_cal.clicked.connect(lambda: self.import_calibration())
        self.btn_remove_cal.clicked.connect(lambda: self.remove_calibration())
        self.btn_apply_cal.clicked.connect(lambda: self.apply_calibration_to_stream())
        cal_tab = QtWidgets.QWidget()
        cl = QtWidgets.QVBoxLayout(cal_tab)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.calibrations, 1)
        cb = QtWidgets.QHBoxLayout()
        cb.addWidget(self.btn_import_cal)
        cb.addWidget(self.btn_remove_cal)
        cb.addWidget(self.btn_apply_cal)
        cb.addStretch(1)
        cl.addLayout(cb)

        # attachments of the item (files in the attachment folder)
        self.attachments = QtWidgets.QTableWidget(0, 4)
        self.attachments.setHorizontalHeaderLabels(['File', 'Description', 'Size', 'Added'])
        self.attachments.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.attachments.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.attachments.horizontalHeader().setStretchLastSection(True)
        self.attachments.doubleClicked.connect(lambda _i: self.open_attachment())
        self.btn_add_att = QtWidgets.QPushButton('Add file ...')
        self.btn_open_att = QtWidgets.QPushButton('Open')
        self.btn_folder_att = QtWidgets.QPushButton('Open folder')
        self.btn_remove_att = QtWidgets.QPushButton('Remove')
        self.btn_add_att.clicked.connect(lambda: self.add_attachment())
        self.btn_open_att.clicked.connect(lambda: self.open_attachment())
        self.btn_folder_att.clicked.connect(lambda: self.open_attachment(folder=True))
        self.btn_remove_att.clicked.connect(lambda: self.remove_attachment())
        att_tab = QtWidgets.QWidget()
        al = QtWidgets.QVBoxLayout(att_tab)
        al.setContentsMargins(0, 0, 0, 0)
        self.att_folder = QtWidgets.QLabel('')
        self.att_folder.setStyleSheet('color: gray;')
        self.att_folder.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        al.addWidget(self.attachments, 1)
        ab = QtWidgets.QHBoxLayout()
        for b in (self.btn_add_att, self.btn_open_att, self.btn_folder_att, self.btn_remove_att):
            ab.addWidget(b)
        ab.addStretch(1)
        al.addLayout(ab)
        al.addWidget(self.att_folder)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.history, 'History')
        self.tabs.addTab(cal_tab, 'Calibrations')
        self.tabs.addTab(att_tab, 'Attachments')
        rlay.addWidget(self.tabs, 1)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        self.status = QtWidgets.QLabel('')
        self.status.setWordWrap(True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(splitter, 1)
        lay.addWidget(self.status)
        if embedded:
            # the Metadata window has these (libraries, git, types, time)
            lay.setContentsMargins(0, 0, 0, 0)
            for w in (self.btn_load, self.btn_load_dir, self.btn_save_lib, self.btn_save_as, self.btn_types,
                      self.btn_git, self.at_time_label, self.at_time, self.use_now):
                w.hide()

        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        try:
            self.redvypr.metadata_changed_signal.connect(lambda: self._refresh_timer.start(300))
        except Exception:
            pass
        self.set_item(None)
        self.refresh()

    # --- helpers ---
    def set_time(self, at_time=None):
        """The state time (None: now), set by the Metadata window."""
        if at_time is None:
            self.use_now.setChecked(True)
        else:
            self.at_time.setDateTime(_qdt(at_time))
            self.use_now.setChecked(False)

    def time(self):
        return None if self.use_now.isChecked() else _pydt(self.at_time.dateTime())

    def set_status(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet('color: red' if error else '')

    # --- tree ---
    def refresh(self):
        at = self.time()
        # item types defined as data in the metadata of the instance, definitions of unknown
        # types searched in the type directories
        try:
            if hasattr(self.redvypr, 'resolve_item_types'):
                self.redvypr.resolve_item_types()
            else:
                ritem_types.register_from_storage(self.redvypr._copy_metadata())
        except Exception:
            logger.warning('could not register the item types of the metadata', exc_info=True)
        all_items = self.redvypr.list_items(at_time=at)
        types = sorted({i.itemtype for i in all_items})
        current = self.type_filter.currentData()
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem('(all)', None)
        for t in types:
            self.type_filter.addItem(t, t)
        i = self.type_filter.findData(current)
        self.type_filter.setCurrentIndex(max(i, 0))
        self.type_filter.blockSignals(False)
        itemtype = self.type_filter.currentData()

        by_ref = {i.ref: i for i in all_items}
        self.tree.blockSignals(True)
        self.tree.clear()
        nodes = {}

        def node(item):
            if item.ref in nodes:
                return nodes[item.ref]
            sn = getattr(item, 'sn', None) or ''
            w = QtWidgets.QTreeWidgetItem([item.ref, str(sn), item.name or '', item.slot or '', item.status or ''])
            w.setData(0, ROLE_REF, item.ref)
            nodes[item.ref] = w
            return w

        if itemtype is None and not self.flat.isChecked():
            # tree by parent; items whose parent is unknown at this time are roots
            for item in all_items:
                w = node(item)
                parent = by_ref.get(item.parent) if item.parent else None
                if parent is not None and parent.ref != item.ref:
                    node(parent).addChild(w)
            for item in all_items:
                w = nodes[item.ref]
                if w.parent() is None:
                    self.tree.addTopLevelItem(w)
        else:
            # flat list (all or one type), sorted by type and id
            for item in sorted(all_items, key=lambda i: (i.itemtype, i.id)):
                if itemtype is None or item.itemtype == itemtype:
                    self.tree.addTopLevelItem(node(item))
        self.tree.expandAll()
        for c in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(c)
        if self.current_ref in nodes:
            self.tree.setCurrentItem(nodes[self.current_ref])
        self.tree.blockSignals(False)
        if self.current_ref and self.current_ref not in nodes:
            self.set_item(None)
        elif self.current_ref and at != self._form_time:
            # other state time: the form shows the item at that time
            self.set_item(self.redvypr.get_item(self.current_ref, at_time=at))
        elif self.current_ref:
            self.show_history(self.current_ref)

    def selection_changed(self):
        w = self.tree.currentItem()
        ref = w.data(0, ROLE_REF) if w is not None else None
        self.set_item(self.redvypr.get_item(ref, at_time=self.time()) if ref else None)
        if self.types_widget is not None:
            self.types_widget.set_item(self.redvypr.get_item(ref, at_time=self.time()) if ref else None)

    def _title_link(self, link: str):
        """A link in the title: 'type:<name>' shows the type (signal type_requested, or the type editor)."""
        if not link.startswith('type:'):
            return
        name = link[len('type:'):]
        if self.embedded:
            self.type_requested.emit(name)
        else:
            self.open_types().select_type(name)

    def open_types(self):
        """Opens the editor of the item types (the selected item for "From item")."""
        from redvypr.widgets.redvypr_item_types_widget import RedvyprItemTypesWidget
        item = self.redvypr.get_item(self.current_ref, at_time=self.time()) if self.current_ref else None
        if self.types_widget is None:
            self.types_widget = RedvyprItemTypesWidget(redvypr_instance=self.redvypr, item=item)
            self.types_widget.types_changed.connect(self._types_changed)
            self.types_widget.resize(1100, 650)
        else:
            self.types_widget.set_item(item)
            self.types_widget.refresh()
        self.types_widget.show()
        self.types_widget.raise_()
        return self.types_widget

    def open_git(self, prefer=None):
        """Opens the git window of the item libraries (status, commit, pull, push)."""
        from redvypr.widgets.redvypr_item_git_widget import RedvyprItemGitWidget
        if self.git_widget is None:
            self.git_widget = RedvyprItemGitWidget(redvypr_instance=self.redvypr, prefer=prefer)
            self.git_widget.libraries_changed.connect(self._types_changed)
            self.git_widget.resize(900, 600)
        else:
            self.git_widget.refresh()
        self.git_widget.show()
        self.git_widget.raise_()
        return self.git_widget

    def _types_changed(self):
        self.refresh()
        if self.current_ref:
            self.set_item(self.redvypr.get_item(self.current_ref, at_time=self.time()))

    # --- form ---
    def set_item(self, item: typing.Optional[ritems.Item]):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.form_fields = {}
        self.current_ref = item.ref if item is not None else None
        self._form_time = self.time()
        enabled = item is not None
        for w in (self.btn_save, self.btn_copy, self.btn_move, self.btn_add_field, self.new_key, self.valid_from):
            w.setEnabled(enabled)
        for w in (self.btn_remove_cal, self.btn_add_att, self.btn_open_att, self.btn_folder_att,
                  self.btn_remove_att):
            w.setEnabled(enabled)
        if item is None:
            self.title.setText('No item selected')
            self.history.setRowCount(0)
            self.calibrations.setRowCount(0)
            self.attachments.setRowCount(0)
            return
        cls = type(item)
        rev = f', revision {item.type_revision}' if item.type_revision else ''
        if getattr(cls, 'ORIGIN', 'python') == 'data':
            kind = 'type defined as data'
        elif cls is ritems.Item and item.itemtype != 'item':
            kind = 'type not defined: generic Item'
        else:
            kind = cls.__name__
        self.title.setText(f'<b>{item.ref}</b> (<a href="type:{item.itemtype}">{item.itemtype}</a>: '
                           f'{kind}{rev})<br>{item.address}')
        self.title.setToolTip('Click the type to see its definition')
        for key, finfo in cls.model_fields.items():
            if key in FORM_SKIP:
                continue
            extra = finfo.json_schema_extra if isinstance(finfo.json_schema_extra, dict) else {}
            self._add_row(key, getattr(item, key), _base_type(finfo.annotation), finfo.description,
                          unit=extra.get('unit'))
        for key, value in (item.model_extra or {}).items():
            self._add_row(key, value, None, 'additional field')
        self.valid_from.setDateTime(_qdt(now_utc()))
        self.show_history(item.ref)
        self.show_calibrations(item)
        self.show_attachments(item)

    def _add_row(self, key, value, base, tip=None, unit=None):
        edit = QtWidgets.QLineEdit(value_to_text(value))
        if tip:
            edit.setToolTip(tip + (f' [{unit}]' if unit else ''))
        if unit:
            edit.setPlaceholderText(f'number in {unit}, or {{value: ..., unit: {unit}, method: ...}}')
        elif base is None:
            edit.setPlaceholderText('JSON or YAML text, e.g. {value: 10002.7, unit: Ohm}')
        self.form.addRow(key, edit)
        self.form_fields[key] = (edit, base)

    def add_field(self):
        key = self.new_key.text().strip()
        if not key or key in self.form_fields or not key.isidentifier():
            self.set_status(f'field name {key!r}: a new identifier', error=True)
            return
        self._add_row(key, None, None, 'additional field')
        self.new_key.clear()

    def form_item(self) -> ritems.Item:
        """The item with the values of the form (raises on wrong values)."""
        itemtype, item_id = ritems.parse_ref(self.current_ref)
        data = {'itemtype': itemtype, 'id': item_id}
        old = self.redvypr.get_item(self.current_ref, at_time=self.time())
        if old is not None and old.type_revision:
            data['type_revision'] = old.type_revision
        for key in MANAGED_FIELDS:
            value = getattr(old, key, None) if old is not None else None
            if value:
                data[key] = [v.model_dump(mode='json') if hasattr(v, 'model_dump') else v for v in value]                     if isinstance(value, list) else value
        for key, (edit, base) in self.form_fields.items():
            try:
                value = text_to_value(edit.text(), base)
            except Exception as e:
                raise ValueError(f'{key}: {e}')
            if value is not None:
                data[key] = value
        return ritems.get_item_type(itemtype).model_validate(data)

    def save_item(self):
        if not self.current_ref:
            return
        try:
            item = self.form_item()
            changed = self.redvypr.add_item(item, valid_from=_pydt(self.valid_from.dateTime()))
        except Exception as e:
            self.set_status(f'{self.current_ref} not saved: {e}', error=True)
            return
        self.set_status(f'{self.current_ref} saved' if changed else f'{self.current_ref}: nothing changed')
        self.refresh()
        self.set_item(self.redvypr.get_item(item.ref, at_time=self.time()) or item)

    def show_history(self, ref):
        entries = self.redvypr.get_item_history(ref)
        self.history.setRowCount(len(entries))
        for row, e in enumerate(entries):
            c = e.get('constraints') or {}
            src = c.get('source')
            src = ', '.join(src) if isinstance(src, list) else (src or '')
            for col, text in enumerate((e['key'], value_to_text(e['value']), c.get('valid_from') or '',
                                        c.get('valid_until') or '', src)):
                self.history.setItem(row, col, QtWidgets.QTableWidgetItem(str(text)))
        self.history.resizeColumnsToContents()

    # --- calibrations ---
    def show_calibrations(self, item):
        from redvypr.devices.sensors.calibration import item_calibration as ic
        storage = self.redvypr._copy_metadata()
        try:
            cals = ic.calibrations_of_item(storage, item)
        except Exception:
            logger.warning('could not read the calibrations', exc_info=True)
            cals = []
        at = self.time()
        valid = ic.select_calibration(cals, ic.item_sn(item), '', at, itemtype=item.itemtype) if cals else None
        self.calibrations.setRowCount(len(cals))
        for row, c in enumerate(cals):
            date = getattr(c, 'date', None)
            texts = (date.isoformat(sep=' ', timespec='seconds') if hasattr(date, 'isoformat') else str(date or ''),
                     'yes' if c is valid else '', getattr(c, 'calibration_type', ''),
                     str(getattr(c, 'channel', '') or ''), ic.calibration_summary(c),
                     str(getattr(c, 'unit', '') or ''), str(getattr(c, 'sensor_model', '') or ''))
            for col, text in enumerate(texts):
                cell = QtWidgets.QTableWidgetItem(text)
                cell.setData(QtCore.Qt.ItemDataRole.UserRole, getattr(c, 'calibration_uuid', ''))
                cell.setToolTip(getattr(c, 'comment', None) or '')
                self.calibrations.setItem(row, col, cell)
        self.calibrations.resizeColumnsToContents()
        return cals

    def import_calibration(self, path=None):
        from redvypr.devices.sensors.calibration import item_calibration as ic
        if not path:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Import calibration', '',
                                                            'YAML (*.yaml *.yml);;All files (*)')
        if not path:
            return None
        item = self.redvypr.get_item(self.current_ref, at_time=self.time()) if self.current_ref else None
        try:
            cals = ic.read_calibration_file(path)
            report = ic.import_calibrations(self.redvypr, cals, item=item)
        except Exception as e:
            self.set_status(f'{os.path.basename(path)} not imported: {e}', error=True)
            return None
        created = [ref for _c, ref, new in report if new]
        missing = [c for c, ref, _new in report if ref is None]
        text = f'{len(report)} calibration(s) imported'
        if created:
            text += ', sensor items created: ' + ', '.join(created)
        if missing:
            text += f'; {len(missing)} without serial number or sensor type (not assigned)'
        self.set_status(text + '. "Save libraries" stores them.', error=bool(missing))
        self.refresh()
        if item is not None:
            self.set_item(self.redvypr.get_item(item.ref, at_time=self.time()))
        return report

    def assignment_devices(self) -> list:
        """The devices of this instance that apply calibration assignments (generic_sensor)."""
        out = []
        for devicedict in getattr(self.redvypr, 'devices', []) or []:
            device = devicedict.get('device') if isinstance(devicedict, dict) else None
            if device is not None and hasattr(device, 'assignments_to_metadata'):
                out.append(device)
        return out

    def apply_calibration_to_stream(self, device=None, assignment=None):
        """
        Adds a calibration assignment for the selected calibration (else its sensor: sn and type of the
        item) to a device (the only one, else asked); the dialog asks for the datastream. assignment: add
        it without the dialog. Returns the assignment, None if cancelled.
        """
        from redvypr.devices.sensors.calibration import item_calibration as ic
        from redvypr.devices.sensors.calibration.calibration_assignments_widget import AssignmentDialog
        item = self.redvypr.get_item(self.current_ref, at_time=self.time()) if self.current_ref else None
        if item is None:
            self.set_status('select an item first', error=True)
            return None
        if device is None:
            devices = self.assignment_devices()
            if not devices:
                self.set_status('no device that applies calibrations (generic_sensor) in this instance', error=True)
                return None
            device = devices[0]
            if len(devices) > 1:
                names = [d.name for d in devices]
                name, ok = QtWidgets.QInputDialog.getItem(self, 'Apply to datastream', 'Device', names, 0, False)
                if not ok:
                    return None
                device = devices[names.index(name)]
        if assignment is None:
            row = self.calibrations.currentRow()
            cell = self.calibrations.item(row, 0) if row >= 0 else None
            uuid = cell.data(QtCore.Qt.ItemDataRole.UserRole) if cell is not None else None
            # a selected calibration: exactly that one, else the calibration of the sensor valid at the data
            preset = {'uuid': uuid} if uuid else {'sn': ic.item_sn(item), 'type': item.itemtype}
            dlg = AssignmentDialog(self.redvypr, self, preset=preset)
            if not dlg.exec():
                return None
            assignment = dlg.assignment()
        items = [a for a in device.custom_config.calibration_assignments if a.address != assignment.address]
        device.custom_config.calibration_assignments = items + [assignment]
        device.update_subscriptions()
        if hasattr(device, 'config_changed_signal'):
            device.config_changed_signal.emit()
        self.set_status(f'assignment added to {device.name}: {assignment.address}. In the device: '
                        '"Calibration assignments" -> "Save to metadata".')
        return assignment

    def remove_calibration(self, calibration_uuid=None, confirm=None):
        from redvypr.devices.sensors.calibration import item_calibration as ic
        if calibration_uuid is None:
            row = self.calibrations.currentRow()
            cell = self.calibrations.item(row, 0) if row >= 0 else None
            calibration_uuid = cell.data(QtCore.Qt.ItemDataRole.UserRole) if cell is not None else None
        if not calibration_uuid:
            self.set_status('select a calibration first', error=True)
            return False
        text = f'Remove the calibration {calibration_uuid} from this redvypr instance? A library file loses it ' \
               'at the next "Save libraries".'
        if confirm is None:
            ok = QtWidgets.QMessageBox.question(self, 'Remove calibration', text) == \
                QtWidgets.QMessageBox.StandardButton.Yes
        else:
            ok = confirm(text)
        if not ok:
            return False
        n = ic.remove_calibration(self.redvypr, calibration_uuid)
        self.set_status(f'calibration removed ({n} address{"es" if n != 1 else ""})' if n else
                        'calibration not found', error=not n)
        if self.current_ref:
            self.set_item(self.redvypr.get_item(self.current_ref, at_time=self.time()))
        return bool(n)

    # --- attachments ---
    def attachments_folder(self) -> str:
        return self.redvypr.item_attachments_folder()

    def show_attachments(self, item):
        import redvypr.item_attachments as ia
        atts = ia.attachments_of(item)
        base = self.attachments_folder()
        self.att_folder.setText(f'Folder: {base}')
        self.attachments.setRowCount(len(atts))
        for row, a in enumerate(atts):
            size = a.file_size_bytes
            size_text = f'{size / 1e6:.1f} MB' if size >= 1e6 else f'{size / 1e3:.0f} kB'
            path = ia.attachment_path(base, item, a)
            for col, text in enumerate((a.file_name, a.description or '', size_text, (a.added or '')[:19])):
                cell = QtWidgets.QTableWidgetItem(text)
                cell.setData(QtCore.Qt.ItemDataRole.UserRole, a.attachment_uuid)
                cell.setToolTip(path if os.path.exists(path) else f'missing: {path}')
                if not os.path.exists(path):
                    cell.setForeground(QtGui.QColor('red'))
                self.attachments.setItem(row, col, cell)
        self.attachments.resizeColumnsToContents()
        return atts

    def _selected_attachment(self):
        row = self.attachments.currentRow()
        cell = self.attachments.item(row, 0) if row >= 0 else None
        return cell.data(QtCore.Qt.ItemDataRole.UserRole) if cell is not None else None

    def add_attachment(self, path=None, description=None):
        import redvypr.item_attachments as ia
        item = self.redvypr.get_item(self.current_ref, at_time=self.time()) if self.current_ref else None
        if item is None:
            return None
        if not path:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, f'Attach a file to {item.ref}', '',
                                                            'All files (*)')
            if not path:
                return None
            description, ok = QtWidgets.QInputDialog.getText(self, 'Attachment', 'Description (optional)')
            if not ok:
                return None
        try:
            att = ia.add_attachment(self.redvypr, item, path, self.attachments_folder(), description=description)
        except Exception as e:
            self.set_status(f'{os.path.basename(str(path))} not attached: {e}', error=True)
            return None
        self.set_status(f'{att.file_name} attached to {item.ref} ("Save libraries" stores the list)')
        self.set_item(self.redvypr.get_item(item.ref, at_time=self.time()))
        return att

    def open_attachment(self, folder=False, attachment_uuid=None):
        import redvypr.item_attachments as ia
        item = self.redvypr.get_item(self.current_ref, at_time=self.time()) if self.current_ref else None
        if item is None:
            return None
        base = self.attachments_folder()
        attachment_uuid = attachment_uuid or self._selected_attachment()
        att = next((a for a in ia.attachments_of(item) if a.attachment_uuid == attachment_uuid), None)
        if att is None:
            target = os.path.join(base, item.itemtype, item.id) if folder else None
        else:
            target = ia.attachment_dir(base, item, att.attachment_uuid) if folder else \
                ia.attachment_path(base, item, att)
        if not target or not os.path.exists(target):
            self.set_status(f'not found: {target or "select an attachment"}', error=True)
            return None
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(target))
        return target

    def remove_attachment(self, attachment_uuid=None, confirm=None):
        import redvypr.item_attachments as ia
        item = self.redvypr.get_item(self.current_ref, at_time=self.time()) if self.current_ref else None
        attachment_uuid = attachment_uuid or self._selected_attachment()
        if item is None or not attachment_uuid:
            self.set_status('select an attachment first', error=True)
            return False
        text = 'Remove the attachment and delete its file from the attachment folder?'
        if confirm is None:
            ok = QtWidgets.QMessageBox.question(self, 'Remove attachment', text) == \
                QtWidgets.QMessageBox.StandardButton.Yes
        else:
            ok = confirm(text)
        if not ok:
            return False
        done = ia.remove_attachment(self.redvypr, item, attachment_uuid, self.attachments_folder())
        self.set_item(self.redvypr.get_item(item.ref, at_time=self.time()))
        self.set_status('attachment removed' if done else 'attachment not found', error=not done)
        return done

    # --- actions ---
    def new_item(self, copy=False):
        source = self.redvypr.get_item(self.current_ref, at_time=self.time()) if (copy and self.current_ref) else None
        dlg = NewItemDialog(self, itemtype=source.itemtype if source else (self.type_filter.currentData() or ''),
                            copy_of=source.ref if source else None)
        if not dlg.exec():
            return False
        itemtype, item_id, valid_from = dlg.values()
        return self.create_item(itemtype, item_id, valid_from, source=source, with_uuid=dlg.with_uuid.isChecked())

    def create_item(self, itemtype, item_id, valid_from=None, source=None, with_uuid=False):
        try:
            ref = ritems.make_ref(itemtype, item_id)
            if self.redvypr.get_item(ref, at_time=valid_from, builtin=False) is not None:
                raise ValueError(f'{ref} exists already')
            data = {}
            if source is not None:
                data = source.model_dump(exclude_none=True)
                data.pop('uuid', None)
                data.pop('type_revision', None)
            data.update(itemtype=itemtype, id=item_id)
            if with_uuid:
                import uuid
                data['uuid'] = str(uuid.uuid4())
            item = ritems.get_item_type(itemtype).model_validate(data)
            self.redvypr.add_item(item, valid_from=valid_from)
        except Exception as e:
            self.set_status(f'item not created: {e}', error=True)
            return False
        self.current_ref = ref
        self.set_status(f'{ref} created')
        self.refresh()
        self.set_item(self.redvypr.get_item(ref, at_time=self.time()) or item)
        return True

    def delete_item(self, ref=None, confirm=None):
        """
        Removes an item (default the selected one) with its whole history after a question.
        confirm: callable(text) -> bool instead of the dialog (tests).
        """
        ref = ref or self.current_ref
        if not ref:
            return False
        children = sorted({it.ref for t in self._history_times(ref)
                           for it in self.redvypr.list_items(at_time=t) if it.parent == ref})
        text = (f'Delete {ref} with its whole history?\n\n'
                'It is removed from this redvypr instance; a library file it came from loses it '
                'at the next "Save libraries". Data files keep the metadata they were written with.\n'
                'An item that is no longer used should rather get status "retired".')
        if children:
            text += '\n\nThese items have it as parent (they stay, their parent then points nowhere):\n' + \
                    '\n'.join(children)
        if confirm is None:
            answer = QtWidgets.QMessageBox.question(
                self, 'Delete item', text,
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No)
            ok = answer == QtWidgets.QMessageBox.StandardButton.Yes
        else:
            ok = confirm(text)
        if not ok:
            return False
        try:
            n = self.redvypr.remove_item(ref)
        except Exception as e:
            self.set_status(f'{ref} not deleted: {e}', error=True)
            return False
        self.current_ref = None
        self.set_item(None)
        self.set_status(f'{ref} deleted ({n} address{"es" if n != 1 else ""})' if n else f'{ref} not found',
                        error=not n)
        self.refresh()
        return bool(n)

    def _history_times(self, ref):
        """Times at which items could have this one as parent: now and the starts of all parent entries."""
        times = [self.time()]
        for addr, entries in self.redvypr._copy_metadata().items():
            for e in entries or []:
                if isinstance(e, dict) and e.get('key') == 'parent' and e.get('value') == ref:
                    vf = (e.get('constraints') or {}).get('valid_from')
                    if vf is not None:
                        times.append(vf)
        return times

    def move_item(self):
        item = self.redvypr.get_item(self.current_ref, at_time=self.time()) if self.current_ref else None
        if item is None:
            return False
        all_items = self.redvypr.list_items(at_time=self.time())
        dlg = MoveItemDialog(self, item, all_items, all_items=all_items)
        if not dlg.exec():
            return False
        parent_ref, slot, valid_from = dlg.values()
        return self.move(item, parent_ref, slot, valid_from)

    def move(self, item, parent_ref, slot, valid_from):
        try:
            if parent_ref is not None:
                ritems.parse_ref(parent_ref)
            moved = item.model_copy(update={'parent': parent_ref, 'slot': slot})
            fields = {k: v for k, v in (('parent', parent_ref), ('slot', slot))}
            # a removed parent/slot ends its entry: write the whole item
            if parent_ref is None or slot is None:
                self.redvypr.add_item(moved, valid_from=valid_from)
            else:
                self.redvypr.add_item(moved, valid_from=valid_from, fields=fields)
        except Exception as e:
            self.set_status(f'{item.ref} not moved: {e}', error=True)
            return False
        self.set_status(f'{item.ref} moved to {parent_ref or "(none)"} / {slot or "-"}')
        self.refresh()
        self.set_item(self.redvypr.get_item(item.ref, at_time=self.time()))
        return True

    def choose_library(self, folder=False):
        """Asks for a library (file or, with folder, a directory); None if cancelled."""
        if folder:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Load library folder', '')
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Load item library', '', LIBRARY_FILTER)
        return path or None

    def load_library(self, path=None, folder=False, progress=None):
        """
        Loads a library (a file, or a directory with folder=True) with a progress dialog that
        appears if it takes longer than a moment (progress: an existing LoadProgress, e.g. of the
        Metadata window, which then also covers the work after the loading). Returns the number of
        addresses loaded, None if cancelled, failed or no library was chosen.
        """
        path = path or self.choose_library(folder)
        if not path:
            return None
        name = os.path.basename(os.path.normpath(path))
        own = progress is None
        progress = LoadProgress(self, f'Loading {name}') if own else progress
        self.set_status(f'loading {name} ...')
        try:
            n = self.redvypr.load_metadata_library(path, progress=progress)
            progress('Building the item tree', 0, 0)
            self.refresh()
            seconds = progress.elapsed
        except LoadCancelled:
            self.set_status(f'loading of {name} cancelled, nothing changed')
            return None
        except Exception as e:
            self.set_status(f'{path} not loaded: {e}', error=True)
            return None
        finally:
            if own:
                progress.close()
        self.set_status(f'{n} items loaded from {path} in {seconds:.1f} s')
        return n

    def save_library(self, path=None):
        if not path:
            default = self.redvypr.metadata_libraries[0] if self.redvypr.metadata_libraries else 'items.yaml'
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save item library', default, LIBRARY_FILTER)
        if not path:
            return
        try:
            n = self.redvypr.save_metadata_library(path)
        except Exception as e:
            self.set_status(f'{path} not saved: {e}', error=True)
            return
        self.set_status(f'{n} items saved in {path}')

    def save_libraries(self):
        """Saves every loaded library file; without one asks for a file name."""
        if not self.redvypr.metadata_libraries:
            return self.save_library()
        try:
            saved = self.redvypr.save_metadata_libraries()
        except Exception as e:
            self.set_status(f'libraries not saved: {e}', error=True)
            return
        self.set_status('saved: ' + ', '.join(f'{os.path.basename(p)} ({n})' for p, n in saved.items()))
