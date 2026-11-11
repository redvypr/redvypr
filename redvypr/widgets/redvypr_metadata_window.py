"""
The Metadata window: one entry point for the metadata of redvypr (design note
doc/source/design_items.rst, section "The Metadata window").

All metadata are entries ``address -> key = value, valid from ... until``.
Three kinds live at special addresses and have their own tabs:

* **Items** (``@i:'item' and d:'<type>' and di:'<id>'``): things such as
  loggers, boards, sensors, with their tree, calibrations and attachments;
* **Item types** (``@i:'itemtype' and d:'<type>'``): the fields of a type;
* **Calibrations** (key ``calibration``): calibration results of sensors.

**Generic** shows all other entries (e.g. units of channels, the setup of a
device), optionally the special ones as well. Item libraries (files and
directories holding items, item types and calibrations), git and the state
time are shared by all tabs and are in the bar at the top.
"""

import datetime
import logging
import os
import typing

from PyQt6 import QtCore, QtWidgets

from redvypr.widgets.load_progress import LoadProgress

logger = logging.getLogger('redvypr.widgets.metadata_window')

TABS = ('Generic', 'Items', 'Item types', 'Calibrations')


class RedvyprMetadataWindow(QtWidgets.QWidget):
    """Metadata of a redvypr instance: tabs Generic, Items, Item types, Calibrations."""

    def __init__(self, redvypr_instance, parent=None, tab: typing.Optional[str] = None):
        super().__init__(parent)
        self.redvypr = redvypr_instance
        self.setWindowTitle('Metadata')
        self.git_widget = None

        # --- bar: libraries, save, git, state time
        self.btn_libraries = QtWidgets.QToolButton()
        self.btn_libraries.setText('Libraries')
        self.btn_libraries.setToolTip('Item libraries: files and directories holding items, item types and '
                                      'calibrations')
        self.btn_libraries.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.libraries_menu = QtWidgets.QMenu(self)
        self.libraries_menu.aboutToShow.connect(self._fill_libraries_menu)
        self.btn_libraries.setMenu(self.libraries_menu)
        self.btn_save = QtWidgets.QPushButton('Save libraries')
        self.btn_save.setToolTip('Every item, item type and calibration into the library it came from, new ones '
                                 'into the first library of their kind')
        self.btn_save.clicked.connect(lambda: self.save_libraries())
        self.btn_git = QtWidgets.QPushButton('Git ...')
        self.btn_git.setToolTip('The item libraries in git: commit, pull, push, bundles')
        self.btn_git.clicked.connect(lambda: self.open_git())
        self.use_now = QtWidgets.QCheckBox('now')
        self.use_now.setChecked(True)
        self.at_time = QtWidgets.QDateTimeEdit()
        self.at_time.setDisplayFormat('yyyy-MM-dd HH:mm:ss UTC')
        self.at_time.setTimeZone(QtCore.QTimeZone.utc())
        self.at_time.setDateTime(QtCore.QDateTime.currentDateTimeUtc())
        self.at_time.setEnabled(False)
        self.use_now.toggled.connect(self._time_changed)
        self.at_time.dateTimeChanged.connect(lambda _dt: self._time_changed())
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(self.btn_libraries)
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_git)
        bar.addStretch(1)
        bar.addWidget(QtWidgets.QLabel('State at'))
        bar.addWidget(self.at_time)
        bar.addWidget(self.use_now)

        # --- tabs
        from redvypr.widgets.redvypr_metadata_table import RedvyprMetadataTable
        from redvypr.widgets.redvypr_items_widget import RedvyprItemsWidget
        from redvypr.widgets.redvypr_item_types_widget import RedvyprItemTypesWidget
        self.generic = RedvyprMetadataTable(redvypr_instance=self.redvypr, library_filter=True)
        self.btn_query = QtWidgets.QPushButton('Query ...')
        self.btn_query.setToolTip('The metadata of an address at a time or as a timeline')
        self.btn_query.clicked.connect(lambda: self.open_query())
        generic_tab = QtWidgets.QWidget()
        gl = QtWidgets.QVBoxLayout(generic_tab)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.addWidget(self.generic, 1)
        gq = QtWidgets.QHBoxLayout()
        gq.addStretch(1)
        gq.addWidget(self.btn_query)
        gl.addLayout(gq)
        self.items = RedvyprItemsWidget(redvypr_instance=self.redvypr, embedded=True)
        self.types = RedvyprItemTypesWidget(redvypr_instance=self.redvypr)
        self.types.types_changed.connect(self._types_changed)
        self.types.items_requested.connect(self.show_items_of_type)
        self.items.type_requested.connect(self.show_type)
        self.items.tree.itemSelectionChanged.connect(self._item_selected)
        self.calibrations = self._make_calibrations_tab()
        self.tabs = QtWidgets.QTabWidget()
        for widget, name in ((generic_tab, 'Generic'), (self.items, 'Items'), (self.types, 'Item types'),
                             (self.calibrations, 'Calibrations')):
            self.tabs.addTab(widget, name)
        self.tabs.currentChanged.connect(self._tab_changed)

        self.status = QtWidgets.QLabel('')
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.status)
        if tab:
            self.show_tab(tab)
        self.update_status()

    def _make_calibrations_tab(self):
        """The tab Calibrations (all calibrations of the metadata); see RedvyprCalibrationsWidget."""
        try:
            from redvypr.widgets.redvypr_calibrations_widget import RedvyprCalibrationsWidget
            w = RedvyprCalibrationsWidget(redvypr_instance=self.redvypr)
            w.item_requested.connect(self.show_item)
            return w
        except ImportError:
            w = QtWidgets.QLabel('Calibrations: not available')
            w.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            return w

    # --- tabs ---
    def show_tab(self, name: str):
        """Shows a tab by name ('Generic', 'Items', 'Item types', 'Calibrations')."""
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).lower() == name.lower():
                self.tabs.setCurrentIndex(i)
                return self.tabs.widget(i)
        raise ValueError(f'no tab {name!r}, one of {TABS}')

    def show_item(self, ref: str):
        """Shows an item in the tab Items."""
        self.show_tab('Items')
        self.items.refresh()
        it = self.redvypr.get_item(ref, at_time=self.time())
        self.items.current_ref = ref
        self.items.set_item(it)
        self._select_in_tree(ref)
        return it

    def show_type(self, name: str) -> bool:
        """Shows an item type in the tab Item types."""
        self.show_tab('Item types')
        return self.types.select_type(name)

    def show_items_of_type(self, name: str):
        """The tab Items with the items of a type (type filter)."""
        self.show_tab('Items')
        self.items.refresh()
        i = self.items.type_filter.findData(name)
        if i >= 0:
            self.items.type_filter.setCurrentIndex(i)
        return i >= 0

    def _select_in_tree(self, ref):
        from redvypr.widgets.redvypr_items_widget import ROLE_REF

        def walk(node):
            if node.data(0, ROLE_REF) == ref:
                return node
            for i in range(node.childCount()):
                found = walk(node.child(i))
                if found is not None:
                    return found
            return None
        for i in range(self.items.tree.topLevelItemCount()):
            node = walk(self.items.tree.topLevelItem(i))
            if node is not None:
                self.items.tree.blockSignals(True)
                self.items.tree.setCurrentItem(node)
                self.items.tree.blockSignals(False)
                return node
        return None

    def _tab_changed(self, index):
        w = self.tabs.widget(index)
        if hasattr(w, 'refresh'):
            try:
                w.refresh()
            except Exception:
                logger.debug('refresh of a tab failed', exc_info=True)
        if w is self.tabs.widget(0):
            self.generic.refresh_and_clear_filters()

    def _item_selected(self):
        ref = self.items.current_ref
        self.types.set_item(self.redvypr.get_item(ref, at_time=self.time()) if ref else None)

    def _types_changed(self):
        self.items.refresh()
        if self.items.current_ref:
            self.items.set_item(self.redvypr.get_item(self.items.current_ref, at_time=self.time()))

    # --- time ---
    def time(self) -> typing.Optional[datetime.datetime]:
        if self.use_now.isChecked():
            return None
        return datetime.datetime.fromtimestamp(self.at_time.dateTime().toMSecsSinceEpoch() / 1000,
                                               tz=datetime.timezone.utc)

    def set_time(self, at_time=None):
        """The state time of all tabs (None: now)."""
        if at_time is None:
            self.use_now.setChecked(True)
        else:
            self.at_time.setDateTime(QtCore.QDateTime.fromMSecsSinceEpoch(int(at_time.timestamp() * 1000),
                                                                         QtCore.QTimeZone.utc()))
            self.use_now.setChecked(False)

    def _time_changed(self):
        self.at_time.setEnabled(not self.use_now.isChecked())
        self.items.set_time(self.time())
        if hasattr(self.calibrations, 'set_time'):
            self.calibrations.set_time(self.time())

    # --- libraries ---
    def _fill_libraries_menu(self):
        m = self.libraries_menu
        m.clear()
        m.addAction('Load library file ...', lambda: self.load_library())
        m.addAction('Load library folder ...', lambda: self.load_library(folder=True))
        m.addAction('Save library as ...', lambda: self.items.save_library())
        m.addSeparator()
        libs = list(self.redvypr.metadata_libraries)
        if not libs:
            a = m.addAction('(no library loaded)')
            a.setEnabled(False)
        for lib in libs:
            a = m.addAction(os.path.basename(os.path.normpath(lib)) + ('/' if os.path.isdir(lib) else ''))
            a.setToolTip(lib)
            a.setEnabled(False)

    def load_library(self, path=None, folder=False):
        """Loads a library with a progress dialog that also covers building the tabs."""
        path = path or self.items.choose_library(folder)
        if not path:
            return
        name = os.path.basename(os.path.normpath(path))
        with LoadProgress(self, f'Loading {name}') as progress:
            n = self.items.load_library(path=path, progress=progress)
            if n is not None:
                progress('Building the tabs', 0, 0)
                self.refresh()
                self.items.set_status(f'{n} items loaded from {path} in {progress.elapsed:.1f} s')
        self.update_status(self.items.status.text())
        return n

    def save_libraries(self):
        try:
            saved = self.redvypr.save_metadata_libraries()
        except Exception as e:
            self.status.setText(f'not saved: {e}')
            return None
        self.update_status('saved: ' + ', '.join(f'{os.path.basename(os.path.normpath(p))} ({n})'
                                                 for p, n in saved.items()))
        return saved

    def open_git(self, prefer=None):
        from redvypr.widgets.redvypr_item_git_widget import RedvyprItemGitWidget
        if self.git_widget is None:
            self.git_widget = RedvyprItemGitWidget(redvypr_instance=self.redvypr, prefer=prefer)
            self.git_widget.libraries_changed.connect(self.refresh)
            self.git_widget.resize(900, 600)
        else:
            self.git_widget.refresh()
        self.git_widget.show()
        self.git_widget.raise_()
        return self.git_widget

    def open_query(self):
        from redvypr.widgets.redvypr_metadata_widget import MetadataWidget
        self.query_widget = MetadataWidget(redvypr=self.redvypr)
        self.query_widget.show()
        return self.query_widget

    # --- view ---
    def refresh(self):
        for w in (self.items, self.types, self.calibrations):
            if hasattr(w, 'refresh'):
                try:
                    w.refresh()
                except Exception:
                    logger.debug('refresh failed', exc_info=True)
        self.update_status()

    def update_status(self, prefix: str = ''):
        """Status line: the loaded libraries (and a message)."""
        libs = [os.path.basename(os.path.normpath(p)) + ('/' if os.path.isdir(p) else '')
                for p in self.redvypr.metadata_libraries]
        text = 'Libraries: ' + (', '.join(libs) if libs else 'none loaded')
        self.status.setText(f'{prefix} | {text}' if prefix else text)
