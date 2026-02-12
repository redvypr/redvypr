import datetime
from PyQt6 import QtWidgets, QtCore, QtGui
import logging
import sys
from redvypr.device import RedvyprDeviceCustomConfig, RedvyprDevice
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetStartonly, RedvyprdevicewidgetSimple
from redvypr.widgets.redvyprMetadataWidget import MetadataWidget
from redvypr.widgets.redvyprAddressWidget import RedvyprAddressWidget, RedvyprMultipleAddressesWidget
from redvypr.data_packets import check_for_command
from .event_definitions import EventBaseConfig, DatastreamBaseConfig
import pydantic
import typing
import qtawesome
import uuid
import re
from redvypr.redvypr_address import RedvyprAddress

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('event')
logger.setLevel(logging.INFO)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = 'A device to create/edit/delete events like measurements, stations or notes, which are saved as metadata objects'


class DeviceCustomConfig(RedvyprDeviceCustomConfig):
    events: typing.List[EventBaseConfig] = pydantic.Field(default_factory=list)


def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    # print('Config',config)
    pdconfig = DeviceCustomConfig.model_validate(config)
    while True:
        try:
            data = datainqueue.get()
        except:
            data = None
        if (data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command: {:s}'.format(str(data)))
            if (command == 'stop'):
                logger.debug('Command is for me: {:s}'.format(str(command)))
                break

        dataqueue.put(data)


class Device(RedvyprDevice):
    """
    A measurement device
    """
    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '.__init__()'
        super(Device, self).__init__(**kwargs)
        self.calfiles_processed = []


class EventTableModel(QtCore.QAbstractTableModel):
    # Map für interne Feldnamen zu Anzeigenamen
    COLUMN_MAP = {
        "num": "Num",
        "eventtype": "Type",
        "name": "Name",
        "tstart": "Start Time",
        "tend": "End Time",
        "location": "Location",
        "uuid": "UUID",
        "lon": "Longitude",
        "lat": "Latitude"
    }

    def __init__(self, events: typing.List[EventBaseConfig]):
        super().__init__()
        self.event_list = events
        self._all_columns = list(self.COLUMN_MAP.keys())

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self.event_list)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self._all_columns)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != QtCore.Qt.ItemDataRole.DisplayRole:
            return None

        event = self.event_list[index.row()]
        col_key = self._all_columns[index.column()]

        val = getattr(event, col_key, None)

        if isinstance(val, datetime.datetime):
            return val.strftime('%Y-%m-%d %H:%M')
        if val is None:
            return ""
        return str(val)

    def headerData(self, section, orientation, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole and orientation == QtCore.Qt.Orientation.Horizontal:
            return self.COLUMN_MAP[self._all_columns[section]]
        return None

    def refresh(self):
        self.layoutChanged.emit()

#
#
#
#
#


class EventConfigEditor(QtWidgets.QWidget):
    config_updated = QtCore.pyqtSignal(object)
    request_close = QtCore.pyqtSignal()

    def __init__(self, config: EventBaseConfig, parent=None, device=None):
        super().__init__(parent)
        self.device = device
        # Work on a copy to allow discarding changes
        self.config = config.model_copy()
        self.widget_config = {'autoloc':True,'autoloc_address_lon':'lon@','autoloc_address_lat':'lat@'}
        self.setup_ui()
        self.load_config_into_ui()
        # If new data from the device has arrived, process it also here in the widget
        self.device.new_data.connect(self.new_data)

    def setup_ui(self):
        self.main_layout = QtWidgets.QVBoxLayout(self)

        # Scroll Area for better usability on small screens
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        content = QtWidgets.QWidget()
        self.layout = QtWidgets.QVBoxLayout(content)

        # --- 1. BASIC DATA (Always Visible) ---
        base_group = QtWidgets.QGroupBox("Basic Event Metadata")
        base_form = QtWidgets.QFormLayout(base_group)

        self.edit_name = QtWidgets.QLineEdit()
        self.combo_type = QtWidgets.QComboBox()
        self.combo_type.setEditable(True)
        # Assuming EventBaseConfig has this list defined
        if hasattr(EventBaseConfig, 'default_event_types'):
            self.combo_type.addItems(EventBaseConfig.default_event_types)

        self.edit_num = QtWidgets.QSpinBox()
        self.edit_num.setRange(0, 99999)

        base_form.addRow("Event Name:", self.edit_name)
        base_form.addRow("Event Type:", self.combo_type)
        base_form.addRow("Event Number:", self.edit_num)
        self.layout.addWidget(base_group)

        # --- 2. TIME & DURATION (Collapsible) ---
        self.time_sec, time_content = self.create_section("Time & Duration",
                                                          checked=True)
        t_form = QtWidgets.QFormLayout(time_content)
        self.start_dt = QtWidgets.QDateTimeEdit(calendarPopup=True)
        self.end_dt = QtWidgets.QDateTimeEdit(calendarPopup=True)
        for dt in [self.start_dt, self.end_dt]:
            dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        t_form.addRow("Start:", self.start_dt)
        t_form.addRow("End:", self.end_dt)
        self.layout.addWidget(self.time_sec)

        # --- 3. LOCATION & COORDINATES (Collapsible) ---
        self.loc_sec, loc_content = self.create_section("Location & Coordinates",
                                                        checked=True)
        l_form = QtWidgets.QFormLayout(loc_content)
        self.edit_loc = QtWidgets.QLineEdit()
        self.spin_lon = QtWidgets.QDoubleSpinBox()
        self.spin_lat = QtWidgets.QDoubleSpinBox()
        self.latlon_from_device = QtWidgets.QCheckBox("Position from device")
        self.latlon_from_device.toggled.connect(self.autoloc_changed)
        self.latlon_from_device.setChecked(self.widget_config['autoloc'])
        self.button_choose_lonaddress = QtWidgets.QPushButton("Choose address longitude")
        self.button_choose_lonaddress.clicked.connect(self.choose_latlondevice_clicked)
        self.button_choose_lataddress = QtWidgets.QPushButton("Choose address latitude")
        self.button_choose_lataddress.clicked.connect(self.choose_latlondevice_clicked)
        self.edit_locdevice_lon = QtWidgets.QLineEdit()
        self.edit_locdevice_lon.setText(self.widget_config['autoloc_address_lon'])
        self.edit_locdevice_lat = QtWidgets.QLineEdit()
        self.edit_locdevice_lat.setText(self.widget_config['autoloc_address_lat'])
        for s in [self.spin_lon, self.spin_lat]:
            s.setRange(-180, 180)
            s.setDecimals(6)
        l_form.addRow("Location Label:", self.edit_loc)
        l_form.addRow("Longitude:", self.spin_lon)
        l_form.addRow("Latitude:", self.spin_lat)
        # Positions from a device
        l_form.addRow(self.latlon_from_device)
        l_form.addRow(self.button_choose_lonaddress)
        l_form.addRow("Autolocation address longitude:", self.edit_locdevice_lon)
        l_form.addRow(self.button_choose_lataddress)
        l_form.addRow("Autolocation address latitude:", self.edit_locdevice_lat)
        self.layout.addWidget(self.loc_sec)

        # --- 4. DATASTREAMS (Collapsible) ---
        self.ds_sec, ds_content = self.create_section("Associated Datastreams",
                                                      checked=False)
        ds_lay = QtWidgets.QVBoxLayout(ds_content)
        self.ds_list = QtWidgets.QListWidget()
        ds_lay.addWidget(self.ds_list)
        # Add Datastream management buttons here if needed
        self.layout.addWidget(self.ds_sec)

        # --- 5. CONTACTS (Collapsible) ---
        self.contact_sec, contact_content = self.create_section("Contacts / Personnel",
                                                                checked=False)
        # Add Contact Table/List here
        self.layout.addWidget(self.contact_sec)

        self.layout.addStretch()
        scroll.setWidget(content)
        self.main_layout.addWidget(scroll)

        # --- BOTTOM BUTTONS ---
        btn_lay = QtWidgets.QHBoxLayout()

        # Apply & Next: Saves and keeps the editor open with incremented values
        self.save_next_btn = QtWidgets.QPushButton("Apply & Next")
        self.save_next_btn.setIcon(qtawesome.icon('fa5s.redo-alt'))
        self.save_next_btn.setToolTip(
            "Save current event, increment number, and keep editor open.")
        self.save_next_btn.clicked.connect(
            lambda: self.save_to_config(close_after=False))

        # Standard Save: Saves and closes the tab
        self.save_btn = QtWidgets.QPushButton("Apply & Save Event")
        self.save_btn.setIcon(qtawesome.icon('fa5s.check'))
        self.save_btn.setStyleSheet("font-weight: bold;")
        self.save_btn.clicked.connect(lambda: self.save_to_config(close_after=True))

        btn_lay.addStretch()
        btn_lay.addWidget(self.save_next_btn)
        btn_lay.addWidget(self.save_btn)
        self.main_layout.addLayout(btn_lay)

    def autoloc_changed(self, state):
        print("State",state)
        self.widget_config['autoloc'] = state
        self.autoloc_address_lon = RedvyprAddress(self.widget_config['autoloc_address_lon'])
        self.autoloc_address_lat = RedvyprAddress(
            self.widget_config['autoloc_address_lat'])

        # unsubscribe all
        self.device.unsubscribe_all()
        if state:
            self.device.subscribe_address(self.autoloc_address_lon)
            self.device.subscribe_address(self.autoloc_address_lat)


    def choose_latlondevice_clicked(self):
        if self.sender() == self.button_choose_lonaddress:
            latlon = 'lon'
        else:
            latlon = 'lat'
        # Filter with an address that has lon or lat
        filter_address = RedvyprAddress("@(lon?:) or (lat?:)")
        self._latlondevice_choose = RedvyprAddressWidget(device=self.device,
                                                         redvypr=self.device.redvypr,
                                                         filter_datastream=[filter_address],
                                                         deviceonly=True)

        self._latlondevice_choose.__latlon__ = latlon

        self._latlondevice_choose.apply.connect(self.latlondevice_chosen)
        self._latlondevice_choose.show()

    def latlondevice_chosen(self, address_dict):
        latlon = self.sender().__latlon__
        addr = address_dict['datastream_address']
        addrstr = addr.to_address_string()

        if latlon == 'lon':
            self.widget_config['autoloc_address_lon'] = addrstr
            self.edit_locdevice_lon.setText(addrstr)
        else:
            self.widget_config['autoloc_address_lat'] = addrstr
            self.edit_locdevice_lat.setText(addrstr)

    def create_section(self, title: str, checked: bool = False):
        """Helper to create a collapsible QGroupBox."""
        group = QtWidgets.QGroupBox(title)
        group.setCheckable(True)
        group.setChecked(checked)
        group_layout = QtWidgets.QVBoxLayout(group)
        content_widget = QtWidgets.QWidget()
        content_widget.setVisible(checked)
        group_layout.addWidget(content_widget)
        group.toggled.connect(content_widget.setVisible)
        return group, content_widget

    def load_config_into_ui(self):
        """Load Pydantic model values into the UI widgets."""
        self.edit_name.setText(self.config.name)
        self.combo_type.setCurrentText(self.config.eventtype)
        self.edit_num.setValue(self.config.num)

        if self.config.tstart:
            self.start_dt.setDateTime(self.config.tstart)
        if self.config.tend:
            self.end_dt.setDateTime(self.config.tend)

        self.edit_loc.setText(self.config.location or "")
        self.spin_lon.setValue(self.config.lon or 0.0)
        self.spin_lat.setValue(self.config.lat or 0.0)

    def save_to_config(self, close_after: bool = True):
        """Extract UI data, validate via Pydantic, and emit updated config."""
        # Update local model copy from UI
        self.config.name = self.edit_name.text()
        self.config.eventtype = self.combo_type.currentText()
        self.config.num = self.edit_num.value()
        self.config.tstart = self.start_dt.dateTime().toPyDateTime()
        self.config.tend = self.end_dt.dateTime().toPyDateTime()
        self.config.location = self.edit_loc.text()
        self.config.lon = self.spin_lon.value()
        self.config.lat = self.spin_lat.value()

        try:
            # Full validation check
            validated_config = EventBaseConfig.model_validate(self.config.model_dump())
            self.config_updated.emit(validated_config)

            if close_after:
                self.request_close.emit()
            else:
                self._prepare_next_event()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Validation Error", str(e))

    def _prepare_next_event(self):
        """Increments numbering and generates a new UUID for the next entry."""
        # 1. Increment Number
        new_num = self.edit_num.value() + 1
        self.edit_num.setValue(new_num)
        self.config.num = new_num

        # 2. Generate New UUID (Crucial so it doesn't overwrite the previous one)
        self.config.uuid = str(uuid.uuid4())

        # 3. Auto-increment Name (e.g., 'Measurement 01' -> 'Measurement 02')
        current_name = self.edit_name.text()
        new_name = current_name

        # If no digits were found at the end, just keep it or append
        if new_name == current_name:
            # Optional: self.edit_name.setText(f"{current_name} {new_num}")
            pass
        else:
            self.edit_name.setText(new_name)

        # 4. UI Focus for rapid entry
        self.edit_name.setFocus()
        self.edit_name.selectAll()

    def new_data(self, data):
        print(f"Got new data:{data=}")
        # Check if autolocation should be used
        if self.widget_config['autoloc']:
            if self.autoloc_address_lon.matches(data):
                lon = self.autoloc_address_lon(data)
                lat = self.autoloc_address_lat(data)
                self.spin_lon.setValue(lon)
                self.spin_lat.setValue(lat)
                print(f"Lon:{lon} Lat:{lat}")
#
#
#
# Redvypr device
#
#
#
class RedvyprDeviceWidget(RedvyprdevicewidgetStartonly):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Access the central configuration
        self.custom_config = self.device.custom_config

        # Clean up existing UI from the inherited class
        self.statustimer.stop()
        if self.layout is not None:
            while self.layout.count():
                item = self.layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        # Initialize Main Tab Widget
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.layout.addWidget(self.tabs)

        # Setup Permanent Dashboard Tabs
        self.setup_event_list_dashboard()  # Permanent Tab 0

        #self.redvypr.metadata_changed_signal.connect(self.check_for_remote_measurements)


    def setup_event_list_dashboard(self):
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)

        m_group = QtWidgets.QGroupBox("Event Management")
        m_lay = QtWidgets.QVBoxLayout(m_group)

        # Tabelle und Model initialisieren
        self.event_table = QtWidgets.QTableView()
        # Wir nutzen die Liste direkt aus der custom_config
        self.event_model = EventTableModel(self.custom_config.events)
        self.event_table.setModel(self.event_model)

        # Header-Kontextmenü für Spalten-Sichtbarkeit
        header = self.event_table.horizontalHeader()
        header.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_column_menu)
        # Also in the table
        self.event_table.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.event_table.customContextMenuRequested.connect(
            self.show_table_context_menu)

        # Standardmäßig einige Spalten verstecken (z.B. UUID)
        self.hide_column_by_name("uuid")

        # UI Optimierung
        self.event_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.event_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.event_table.setAlternatingRowColors(True)

        self.event_table.doubleClicked.connect(
            lambda: self.open_event_widget(new=False))

        btn_lay = QtWidgets.QHBoxLayout()
        add_m_btn = QtWidgets.QPushButton(" Add Event")
        add_m_btn.setIcon(qtawesome.icon('fa5s.plus-circle'))
        add_m_btn.clicked.connect(lambda: self.open_event_widget(new=True))

        rem_m_btn = QtWidgets.QPushButton(" Remove Selected")
        rem_m_btn.setIcon(qtawesome.icon('fa5s.trash-alt'))
        rem_m_btn.clicked.connect(self.remove_measurement)

        btn_lay.addWidget(add_m_btn)
        btn_lay.addWidget(rem_m_btn)

        m_lay.addWidget(self.event_table)
        m_lay.addLayout(btn_lay)
        layout.addWidget(m_group)

        self.tabs.addTab(container, qtawesome.icon('fa5s.layer-group'), "Events")

    def show_table_context_menu(self, pos):
        self.show_column_menu(pos)
    def show_column_menu(self, pos):
        """Erzeugt ein Menü zum Ein/Ausblenden von Spalten."""
        menu = QtWidgets.QMenu(self)
        model = self.event_model

        for i, col_key in enumerate(model._all_columns):
            action = QtGui.QAction(model.COLUMN_MAP[col_key], menu)
            action.setCheckable(True)
            # Prüfen, ob die Spalte aktuell sichtbar ist
            action.setChecked(not self.event_table.isColumnHidden(i))

            # Lambda mit i=i fixiert den aktuellen Wert von i in der Schleife
            action.toggled.connect(
                lambda checked, idx=i: self.event_table.setColumnHidden(idx,
                                                                        not checked))
            menu.addAction(action)

        menu.exec(self.event_table.horizontalHeader().mapToGlobal(pos))

    def hide_column_by_name(self, name):
        """Hilfsfunktion zum Verstecken über den Feldnamen."""
        if name in self.event_model._all_columns:
            idx = self.event_model._all_columns.index(name)
            self.event_table.setColumnHidden(idx, True)

    def remove_measurement(self):
        indices = self.event_table.selectionModel().selectedRows()
        if not indices:
            return

        # Von hinten löschen, damit die Indices stabil bleiben
        for index in sorted(indices, reverse=True):
            del self.custom_config.events[index.row()]

        self.event_model.refresh()

    def setup_event_list_dashboard_legacy(self):
        """Creates the main Measurement Management tab (Tab 0)."""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)

        m_group = QtWidgets.QGroupBox("Event Management")
        m_lay = QtWidgets.QVBoxLayout(m_group)

        self.event_table = None #Here a speicalised tableview please
        self.event_table.doubleClicked.connect(lambda: self.open_event_widget(new=False))

        btn_lay = QtWidgets.QHBoxLayout()
        add_m_btn = QtWidgets.QPushButton(" Add Event")
        add_m_btn.setIcon(qtawesome.icon('fa5s.plus-circle'))
        add_m_btn.clicked.connect(lambda: self.open_event_widget(new=True))

        rem_m_btn = QtWidgets.QPushButton(" Remove Selected")
        rem_m_btn.setIcon(qtawesome.icon('fa5s.trash-alt'))
        rem_m_btn.clicked.connect(self.remove_measurement)

        btn_lay.addWidget(add_m_btn)
        btn_lay.addWidget(rem_m_btn)

        m_lay.addWidget(self.event_table)
        m_lay.addLayout(btn_lay)
        layout.addWidget(m_group)

        self.tabs.addTab(container, qtawesome.icon('fa5s.layer-group'), "Events")

    # --- Measurement Logic ---

    def open_event_widget(self, new=False):
        """Öffnet den EventConfigEditor in einem neuen Tab."""
        if new:
            # Erstelle ein neues Event-Objekt mit Standardwerten
            # Wir berechnen die nächste Nummer basierend auf der Liste
            next_num = max([e.num for e in self.custom_config.events],
                           default=0) + 1
            event_to_edit = EventBaseConfig(
                name=f"New Event {next_num}",
                num=next_num,
                tcreated=datetime.datetime.now(datetime.timezone.utc)
            )
        else:
            # Bestehendes Event aus der Auswahl holen
            index = self.event_table.currentIndex()
            if not index.isValid():
                QtWidgets.QMessageBox.information(self, "Selection",
                                                  "Please select an event to edit.")
                return
            event_to_edit = self.custom_config.events[index.row()]

        # Den Editor instanziieren (wir nutzen die Klasse von vorhin)
        editor = EventConfigEditor(config=event_to_edit, device=self.device)

        # Signale verbinden
        editor.config_updated.connect(
            lambda cfg: self.on_event_config_updated(cfg, is_new=new))
        editor.request_close.connect(lambda: self.close_active_editor_tab(editor))

        # Icon und Titel festlegen
        icon = qtawesome.icon('fa5s.plus-circle' if new else 'fa5s.edit')
        title = "New Event" if new else f"Edit: {event_to_edit.name}"

        # Tab hinzufügen und darauf fokussieren
        new_tab_index = self.tabs.addTab(editor, icon, title)
        self.tabs.setCurrentIndex(new_tab_index)

    def on_event_config_updated(self, updated_config, is_new=False):
        """Wird aufgerufen, wenn der Editor 'Save' signalisiert."""
        if is_new:
            # Zur Liste hinzufügen
            self.custom_config.events.append(updated_config)
        else:
            # Das Objekt in der Liste finden und ersetzen (oder Update via Index)
            # Da Pydantic-Modelle kopiert wurden, suchen wir hier am besten über die UUID
            for i, ev in enumerate(self.custom_config.events):
                if ev.uuid == updated_config.uuid:
                    self.custom_config.events[i] = updated_config
                    break

        # Tabelle im Haupt-Tab aktualisieren
        self.event_model.refresh()

    def close_active_editor_tab(self, widget):
        """Schließt den Tab, der das spezifische Widget enthält."""
        index = self.tabs.indexOf(widget)
        if index != -1:
            self.tabs.removeTab(index)
            widget.deleteLater()

    def close_tab(self, index):
        """Handler für das 'X' am Tab-Header."""
        # Tab 0 (Event Liste) sollte permanent bleiben
        if index == 0:
            return

        widget = self.tabs.widget(index)
        if widget:
            self.tabs.removeTab(index)
            widget.deleteLater()




