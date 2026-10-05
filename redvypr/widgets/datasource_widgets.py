"""
Widgets for the data sources of redvypr (databases to read from, see redvypr.datasource):
editing a data source and selecting datastreams of it.

The widgets work with a registry: Redvypr (its data sources are saved with the
configuration) or a redvypr.datasource.DatasourceRegistry (e.g. of a plot without redvypr).
"""

import datetime
import logging
import pathlib

from PyQt6 import QtWidgets, QtCore, QtGui

from redvypr.datasource import DataSourceConfig, DataSourceError

logger = logging.getLogger('redvypr.widgets.datasource_widgets')


def _time_str(t):
    if t is None:
        return ''
    try:
        return datetime.datetime.fromtimestamp(float(t), datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError, OSError):
        return str(t)


class DataSourceEditDialog(QtWidgets.QDialog):
    """Edit a data source: name, SQLite file or TimescaleDB connection."""

    def __init__(self, config: DataSourceConfig = None, parent=None, names_used=()):
        super().__init__(parent)
        self.setWindowTitle('Data source')
        self._names_used = set(names_used)
        config = config or DataSourceConfig()
        layout = QtWidgets.QFormLayout(self)
        self.name = QtWidgets.QLineEdit(config.name)
        self.dbtype = QtWidgets.QComboBox()
        self.dbtype.addItems(['sqlite', 'timescaledb'])
        self.dbtype.setCurrentText(config.dbtype)
        self.filepath = QtWidgets.QLineEdit(config.filepath)
        browse = QtWidgets.QPushButton('Browse ...')
        browse.clicked.connect(self._browse)
        filerow = QtWidgets.QHBoxLayout()
        filerow.addWidget(self.filepath)
        filerow.addWidget(browse)
        self.host = QtWidgets.QLineEdit(config.host)
        self.port = QtWidgets.QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(config.port)
        self.dbname = QtWidgets.QLineEdit(config.dbname)
        self.user = QtWidgets.QLineEdit(config.user)
        self.password = QtWidgets.QLineEdit(config.password)
        self.password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.description = QtWidgets.QLineEdit(config.description)
        layout.addRow('Name', self.name)
        layout.addRow('Type', self.dbtype)
        layout.addRow('File', filerow)
        self._ts_widgets = [self.host, self.port, self.dbname, self.user, self.password]
        for label, w in zip(('Host', 'Port', 'Database', 'User', 'Password'), self._ts_widgets):
            layout.addRow(label, w)
        layout.addRow('Description', self.description)
        self._filewidgets = [self.filepath, browse]
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                             QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.dbtype.currentTextChanged.connect(self._type_changed)
        self._type_changed()

    def _type_changed(self):
        sqlite = self.dbtype.currentText() == 'sqlite'
        for w in self._filewidgets:
            w.setEnabled(sqlite)
        for w in self._ts_widgets:
            w.setEnabled(not sqlite)

    def _browse(self):
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'SQLite database', self.filepath.text(),
                                                         'SQLite (*.sqlite *.db *.sqlite3);;All files (*)')
        if fname:
            self.filepath.setText(fname)
            if not self.name.text().strip() or self.name.text() == DataSourceConfig().name:
                self.name.setText(pathlib.Path(fname).stem)

    def _accept(self):
        name = self.name.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, 'Data source', 'Please enter a name.')
            return
        if name in self._names_used:
            QtWidgets.QMessageBox.warning(self, 'Data source', f'A data source "{name}" exists already.')
            return
        self.accept()

    def get_config(self) -> DataSourceConfig:
        return DataSourceConfig(name=self.name.text().strip(), dbtype=self.dbtype.currentText(),
                                filepath=self.filepath.text().strip(), host=self.host.text().strip(),
                                port=self.port.value(), dbname=self.dbname.text().strip(),
                                user=self.user.text().strip(), password=self.password.text(),
                                description=self.description.text())


class DatastreamSelectDialog(QtWidgets.QDialog):
    """
    Choose a data source of the registry (add, edit, remove data sources) and select
    datastreams of it. selected() gives (data source name, [Datastream]).
    """
    COLUMNS = ['Address', 'Values', 'From (UTC)', 'To (UTC)', 'Type', 'Table']

    def __init__(self, registry, parent=None, title='Datastreams of a database', numeric_only=True,
                 add_button_text='Add', extra_widget=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1000, 600)
        self.registry = registry
        self.numeric_only = numeric_only
        self._streams = []
        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel('Data source'))
        self.source = QtWidgets.QComboBox()
        self.source.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        row.addWidget(self.source, 1)
        for text, slot in (('New ...', self._new), ('Edit ...', self._edit), ('Remove', self._remove),
                           ('Reload', self._reload)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        layout.addLayout(row)
        self.status = QtWidgets.QLabel('')
        layout.addWidget(self.status)
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText('Filter (text in the address, e.g. board_temp or 9AB6)')
        self.filter.textChanged.connect(self._fill_table)
        layout.addWidget(self.filter)
        self.table = QtWidgets.QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.table, 1)
        if extra_widget is not None:
            layout.addWidget(extra_widget)
        buttons = QtWidgets.QDialogButtonBox()
        self.add_button = buttons.addButton(add_button_text, QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.source.currentIndexChanged.connect(self._source_changed)
        self._fill_sources()

    # --- data sources ---
    def _fill_sources(self, select=None):
        current = select or self.source.currentData()
        self.source.blockSignals(True)
        self.source.clear()
        for d in self.registry.datasources:
            self.source.addItem(d.summary(), d.name)
        i = self.source.findData(current) if current else -1
        self.source.setCurrentIndex(i if i >= 0 else 0 if self.source.count() else -1)
        self.source.blockSignals(False)
        self._source_changed()

    def _new(self):
        dialog = DataSourceEditDialog(parent=self, names_used=[d.name for d in self.registry.datasources])
        if dialog.exec():
            config = self.registry.add_datasource(dialog.get_config())
            self._fill_sources(select=config.name)

    def _edit(self):
        name = self.source.currentData()
        config = self.registry.get_datasource(name) if name else None
        if config is None:
            return
        others = [d.name for d in self.registry.datasources if d.name != name]
        dialog = DataSourceEditDialog(config, parent=self, names_used=others)
        if dialog.exec():
            new = dialog.get_config()
            if new.name != name:
                self.registry.remove_datasource(name)
            self.registry.add_datasource(new)
            self._fill_sources(select=new.name)

    def _remove(self):
        name = self.source.currentData()
        if name and QtWidgets.QMessageBox.question(
                self, 'Remove data source', f'Remove the data source "{name}" from redvypr? '
                                            f'(The database itself is not changed.)') == \
                QtWidgets.QMessageBox.StandardButton.Yes:
            self.registry.remove_datasource(name)
            self._fill_sources()

    def _reload(self):
        self._source_changed(refresh=True)

    def _source_changed(self, *_args, refresh=False):
        self._streams = []
        name = self.source.currentData()
        if name:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            try:
                reader = self.registry.get_datasource_reader(name, refresh=refresh)
                self._streams = reader.datastreams(refresh=refresh)
                n_num = sum(s.numeric for s in self._streams)
                self.status.setText(f'{len(self._streams)} datastreams ({n_num} numeric)')
            except (DataSourceError, Exception) as e:
                logger.info(f'could not read data source {name}', exc_info=True)
                self.status.setText(f'Could not read the data source: {e}')
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
        else:
            self.status.setText('No data source, add one with "New ..."')
        self._fill_table()

    def _fill_table(self):
        text = self.filter.text().strip().lower()
        streams = [s for s in self._streams if not text or text in s.address.lower()]
        self.table.setRowCount(len(streams))
        for i, s in enumerate(streams):
            values = [s.address, '' if s.num is None else str(s.num), _time_str(s.t_first),
                      _time_str(s.t_last), s.datatype or '', s.table]
            for j, v in enumerate(values):
                item = QtWidgets.QTableWidgetItem(v)
                if j == 1:
                    item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
                if self.numeric_only and not s.numeric:
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
                    item.setToolTip('not numeric, cannot be plotted')
                item.setData(QtCore.Qt.ItemDataRole.UserRole, s)
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)

    def selected(self):
        """(name of the data source, [selected Datastream])"""
        rows = sorted({i.row() for i in self.table.selectedItems()})
        streams = [self.table.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole) for r in rows]
        return self.source.currentData(), streams
