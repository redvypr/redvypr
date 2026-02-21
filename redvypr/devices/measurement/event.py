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
logger = logging.getLogger('redvypr.device.event')
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

    def create_address_string_from_event(self, event):
        address_str = f"@i:event__{event.uuid} and d:event_metadata"
        return address_str
    def add_event_to_metadata(self, event):
        funcname = __name__ + '.add_event_to_metadata()'
        print(f"{funcname}")
        #print(f"Measurement:{measurement}")
        address_str = self.create_address_string_from_event(event)
        meta_address = RedvyprAddress(address_str)
        meta_address_str = meta_address.to_address_string()
        metadata = event.model_dump()
        #print("Adding metadata",metadata)
        self.redvypr.set_metadata(meta_address_str, metadata=metadata)
        # Try to remove the measurement metadata entries in all datastreams
        self.redvypr.rem_metadata("@", metadata_keys=[meta_address_str], mode="matches")
        for addr_datastream, metadata_datastream in metadata["datastreams"].items():
            print(f"Adding metadata to datastream {addr_datastream}")
            #print("Metadata",metadata_datastream)
            #metadata_datastream_submit = {meta_address_str:metadata_datastream}
            # Do not send the whole metadata, but a link to the metadata
            metadata_datastream_submit = {meta_address_str:f'["datastreams"][{addr_datastream}]'}
            #print("Adding",metadata_datastream_submit)
            self.redvypr.set_metadata(addr_datastream,metadata=metadata_datastream_submit)

    def load_events_from_metadata(self):
        """
        Retrieves all event metadata from redvypr and reconstructs Event objects.
        Returns a list of validated event objects.
        """
        funcname = __name__ + '.load_events_from_metadata()'
        print(f"{funcname}")

        # 1. Define the search pattern based on your address string logic
        # We look for anything starting with 'event__' and containing 'event_metadata'
        search_pattern = "@d:event_metadata"

        # 2. Fetch all matching metadata from redvypr
        # This returns a dict: {address_string: metadata_dict}
        all_metadata = self.redvypr.get_metadata(search_pattern)

        events = []

        if not all_metadata:
            print("No events found in metadata.")
            return events

        for addr_str, metadata_content in all_metadata.items():
            try:
                # 3. Reconstruct the object via Pydantic
                # Since you saved it using model_dump(), model_validate() is the safest way back
                # Replace 'EventBaseConfig' with your actual Pydantic model class name
                event_obj = EventBaseConfig.model_validate(metadata_content)
                events.append(event_obj)
                print(f"Successfully loaded event: {event_obj.uuid}")

            except Exception as e:
                print(f"Error validating event metadata at {addr_str}: {e}")

        return events

    def rem_event_from_metadata(self, event):
        funcname = __name__ + '.rem_measurement_from_metadata()'
        print(f"{funcname}")
        address_str = self.create_address_string_from_event(event)
        # Delete the whole entry
        print(f"Deleting metadata entry for event:{address_str}")
        self.redvypr.rem_metadata(address_str, metadata_keys=[], constraint_entries=[])
        for addr_datastream, metadata_datastream in event.datastreams.items():
            self.redvypr.rem_metadata(addr_datastream, metadata_keys=[address_str])


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
        print("tstart",self.config.tstart)
        widget_config = {'autoloc': True, 'autoloc_address_lon': 'lon@', 'autoloc_address_lat': 'lat@'}
        widget_config['autotime_start'] = True
        widget_config['autotime_end'] = True
        widget_config['autotime_address_start'] = "t@"
        widget_config['autotime_address_end'] = "t@"
        self.widget_config = widget_config
        self.setup_ui()
        self.load_config_into_ui()
        # If new data from the device has arrived, process it also here in the widget
        self.device.new_data.connect(self.new_data)



        # Initialen Status setzen (falls 'Use' am Anfang aus ist)
        # Das triggert den Slot sofort einmal
        if self.config.tstart is None:
            self.time_controls["start"]['check_use'].setChecked(False)
            self.on_edittime_toggled(False, "start")
        else:
            self.time_controls["start"]['check_use'].setChecked(True)
            self.on_edittime_toggled(True, "start")

        if self.config.tend is None:
            self.time_controls["end"]['check_use'].setChecked(False)
            self.on_edittime_toggled(False, "end")
        else:
            self.time_controls["end"]['check_use'].setChecked(True)
            self.on_edittime_toggled(True, "end")

        # Call the autoloc_changed function
        self.autoloc_changed(self.widget_config['autoloc'])


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
            dt.setTimeSpec(QtCore.Qt.TimeSpec.UTC)
            dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss 'UTC'")
            dt.dateTimeChanged.connect(self.on_time_changed)

        t_form.addRow("Start:", self._create_time_control_widget(self.start_dt,"start"))
        t_form.addRow("End:", self._create_time_control_widget(self.end_dt,"end"))
        self.layout.addWidget(self.time_sec)

        # --- 3. LOCATION & COORDINATES (Collapsible) ---
        self.loc_sec, loc_content = self.create_section("Location & Coordinates",
                                                        checked=True)
        l_form = QtWidgets.QFormLayout(loc_content)
        self.edit_loc = QtWidgets.QLineEdit()
        self.spin_lon = QtWidgets.QDoubleSpinBox()
        self.spin_lat = QtWidgets.QDoubleSpinBox()
        widget_autolatlon = QtWidgets.QWidget()
        layout_autolatlon = QtWidgets.QHBoxLayout(widget_autolatlon)
        layout_autolatlon.setContentsMargins(0, 0, 0, 0)
        layout_autolatlon.setSpacing(4)


        self.autolatlon_from_device = QtWidgets.QCheckBox("Auto update location from device")
        self.autolatlon_from_device.setChecked(self.widget_config['autoloc'])
        self.autolatlon_from_device.toggled.connect(self.autoloc_changed)
        self.autolatlon_add_time = QtWidgets.QCheckBox(
            "Autoupdate time as well")
        self.autolatlon_add_time.setChecked(True)
        self.autolatlon_add_time.setEnabled(False)
        self.button_choose_latlonaddress = QtWidgets.QPushButton("Choose address longitude")
        self.button_choose_latlonaddress.clicked.connect(self.choose_latlondevice_clicked)
        self.edit_locdevice_lon = QtWidgets.QLineEdit()
        self.edit_locdevice_lon.setText(self.widget_config['autoloc_address_lon'])
        self.edit_locdevice_lat = QtWidgets.QLineEdit()
        self.edit_locdevice_lat.setText(self.widget_config['autoloc_address_lat'])
        for s in [self.spin_lon, self.spin_lat]:
            s.setRange(-180, 180)
            s.setDecimals(6)

        self.autloc_devices_enable = [self.button_choose_latlonaddress, self.edit_locdevice_lon,
         self.edit_locdevice_lat]
        layout_autolatlon.addWidget(self.autolatlon_from_device)
        layout_autolatlon.addWidget(self.button_choose_latlonaddress)
        layout_autolatlon.addWidget(self.autolatlon_add_time)

        l_form.addRow("Location Label:", self.edit_loc)
        l_form.addRow("Longitude:", self.spin_lon)
        l_form.addRow("Latitude:", self.spin_lat)
        l_form.addRow(widget_autolatlon)
        l_form.addRow("Datastream address longitude:", self.edit_locdevice_lon)
        l_form.addRow("Datastream address latitude:", self.edit_locdevice_lat)
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

    def _create_time_control_widget(self, dt_edit, name_prefix):
        """Modified to store references for autotime logic."""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Store references in a dictionary on the instance
        if not hasattr(self, 'time_controls'):
            self.time_controls = {}

        ctrls = {}
        ctrls['check_use'] = QtWidgets.QCheckBox("Use")
        ctrls['check_autotime'] = QtWidgets.QCheckBox("Auto update")
        ctrls['address_edit'] = QtWidgets.QLineEdit()
        # Default value for demo/standard
        ctrls['address_edit'].setText("time@")
        ctrls['address_choose'] = QtWidgets.QPushButton("Datastream")
        ctrls['address_choose'].clicked.connect(self._choose_autotimedevice_clicked)

        # UI Setup (wie gehabt)
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(0, 9999);
        spin.setFixedWidth(60);
        spin.setValue(10)
        unit_combo = QtWidgets.QComboBox()
        unit_combo.addItems(["s", "min", "h", "days"])
        btn_sub = QtWidgets.QPushButton("-");
        btn_add = QtWidgets.QPushButton("+")
        btn_now = QtWidgets.QPushButton("Now")

        dt_edit.__edit_widgets__ = [spin,unit_combo,btn_sub, btn_add, btn_now]
        # Layout hinzufügen
        layout.addWidget(ctrls['check_use'])
        layout.addWidget(spin)
        layout.addWidget(unit_combo)
        layout.addWidget(btn_sub)
        layout.addWidget(btn_add)
        layout.addWidget(dt_edit)
        layout.addWidget(btn_now)
        layout.addWidget(ctrls['check_autotime'])
        layout.addWidget(ctrls['address_edit'])
        layout.addWidget(ctrls['address_choose'])

        # Logic for autotime toggle
        ctrls['check_autotime'].toggled.connect(
            lambda state: self.on_autotime_toggled(state, dt_edit,
                                                   ctrls['address_edit']))

        # Store the set of controls for this specific date_edit (start or end)
        self.time_controls[name_prefix] = ctrls
        # Button signals...
        btn_now.clicked.connect(
            lambda: dt_edit.setDateTime(QtCore.QDateTime.currentDateTime()))

        ctrls['check_use'].toggled.connect(
            lambda state: self.on_edittime_toggled(state, name_prefix)
        )

        def adjust_time(multiplier):
            mapping = {"s": 1, "min": 60, "h": 3600, "days": 86400}
            delta_seconds = spin.value() * mapping[
                unit_combo.currentText()] * multiplier
            dt_edit.setDateTime(dt_edit.dateTime().addSecs(int(delta_seconds)))

        btn_now.clicked.connect(
            lambda: dt_edit.setDateTime(QtCore.QDateTime.currentDateTime()))
        btn_add.clicked.connect(lambda: adjust_time(1))
        btn_sub.clicked.connect(lambda: adjust_time(-1))

        return container

    def on_edittime_toggled(self, state, name_prefix):
        """
        Handles if time shall be changed

        """
        if hasattr(self, 'time_controls') and name_prefix in self.time_controls:
            ctrls = self.time_controls[name_prefix]

            # 1. Die im ctrls-Dictionary gespeicherten Widgets umschalten
            ctrls['check_autotime'].setEnabled(state)
            ctrls['address_edit'].setEnabled(state)
            ctrls['address_choose'].setEnabled(state)

            # 2. Falls du auch die Spinboxen und Buttons umschalten willst,
            # müssen wir diese im Widget-Tree finden.
            # Am einfachsten: Das Parent-Widget (Container) nutzen.
            # Da 'check_use' das Signal sendet, ist das Parent-Widget
            # der Container, den wir deaktivieren können:
            container = ctrls['check_use'].parentWidget()

            # Wir iterieren durch alle Kinder des Containers
            for i in range(container.layout().count()):
                widget = container.layout().itemAt(i).widget()
                if widget and widget != ctrls['check_use']:
                    widget.setEnabled(state)
    def on_autotime_toggled(self, state, dt_edit, address_edit):
        """Handles subscription when autotime is enabled."""
        dt_edit.setEnabled(not state)
        for w in dt_edit.__edit_widgets__:
            w.setEnabled(not state)
        if state:
            addr_str = address_edit.text()
            if addr_str:
                self.device.subscribe_address(RedvyprAddress(addr_str))
                self.device.thread_start()

    def on_time_changed(self):
        """Auto-fix: Ensures start_dt <= end_dt."""
        start = self.start_dt.dateTime()
        end = self.end_dt.dateTime()
        if start > end:
            self.start_dt.blockSignals(True)
            self.end_dt.blockSignals(True)
            if self.sender() == self.start_dt:
                self.end_dt.setDateTime(start.addSecs(60))
            else:
                self.start_dt.setDateTime(end.addSecs(-60))
            self.start_dt.blockSignals(False)
            self.end_dt.blockSignals(False)

    def _choose_autotimedevice_clicked(self):
        # Filter with an address that has lon or lat
        self._autotimedevice_choose = RedvyprAddressWidget(device=self.device,
                                                         redvypr=self.device.redvypr,
                                                         deviceonly=True)


        self._autotimedevice_choose.apply.connect(self._autotimedevice_chosen)
        self._autotimedevice_choose.show()

    def _autotimedevice_chosen(self, address_dict):
        addr = address_dict['datastream_address']
        addrstr = addr.to_address_string()


    def autoloc_changed(self, state):
        print("State",state)
        self.widget_config['autoloc'] = state
        self.autoloc_address_lon = RedvyprAddress(self.widget_config['autoloc_address_lon'])
        self.autoloc_address_lat = RedvyprAddress(
            self.widget_config['autoloc_address_lat'])

        # unsubscribe all
        self.device.unsubscribe_all()
        if state:
            self.spin_lon.setEnabled(False)
            self.spin_lat.setEnabled(False)
            for w in self.autloc_devices_enable:
                w.setEnabled(True)
            self.device.subscribe_address(self.autoloc_address_lon)
            self.device.subscribe_address(self.autoloc_address_lat)
            # Autoupdate time as well
            if self.autolatlon_add_time.isChecked():
                taddress = RedvyprAddress(self.autoloc_address_lon, datakey="t")
                taddressstr = taddress.to_address_string()
                self.time_controls["start"]['check_use'].setChecked(True)
                self.time_controls["start"]['address_edit'].setText(taddressstr)
                self.time_controls["start"]['check_autotime'].setChecked(True)
                self.time_controls["end"]['check_use'].setChecked(False)
                self.time_controls["end"]['check_autotime'].setChecked(False)
            self.device.thread_start()
        else:
            self.spin_lon.setEnabled(True)
            self.spin_lat.setEnabled(True)
            for w in self.autloc_devices_enable:
                w.setEnabled(False)
            self.device.thread_stop()


    def choose_latlondevice_clicked(self):
        # Filter with an address that has lon or lat
        filter_address = RedvyprAddress("@(lon?:) or (lat?:)")
        self._latlondevice_choose = RedvyprMultipleAddressesWidget(device=self.device,
                                                         redvypr=self.device.redvypr,
                                                         address_names = {'Longitude':'lon@','Latitude':'lat@'},
                                                         filter_datastream=[filter_address],
                                                         deviceonly=True)

        self._latlondevice_choose.apply.connect(self.latlondevice_chosen)
        self._latlondevice_choose.show()

    def latlondevice_chosen(self, address_dict):
        print("Got address dict",address_dict)
        lonaddr = address_dict['addresses_named']['Longitude']
        lataddr = address_dict['addresses_named']['Latitude']
        lonaddrstr = lonaddr#.to_address_string()
        lataddrstr = lataddr#.to_address_string()

        self.widget_config['autoloc_address_lon'] = lonaddrstr
        self.edit_locdevice_lon.setText(lonaddrstr)
        self.widget_config['autoloc_address_lat'] = lataddrstr
        self.edit_locdevice_lat.setText(lataddrstr)


        # Update of the config etc
        self.autoloc_changed(True)

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
        iso_start = self.start_dt.dateTime().toString(QtCore.Qt.ISODate)
        iso_end = self.end_dt.dateTime().toString(QtCore.Qt.ISODate)
        dt_start = datetime.datetime.fromisoformat(iso_start)
        dt_end = datetime.datetime.fromisoformat(iso_end)
        self.config.name = self.edit_name.text()
        self.config.eventtype = self.combo_type.currentText()
        self.config.num = self.edit_num.value()
        self.config.tstart = dt_start
        self.config.tend = dt_end
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
        #print(f"Got new data:{data=}")
        # Check if autolocation should be used
        if self.widget_config['autoloc']:
            if self.autoloc_address_lon.matches(data):
                try:
                    lon = self.autoloc_address_lon(data)
                    self.spin_lon.setValue(lon)
                except:
                    logger.info("Could not update lon",exc_info=True)
                try:
                    lat = self.autoloc_address_lat(data)
                    self.spin_lat.setValue(lat)
                except:
                    logger.info("Could not update lat", exc_info=True)

        # --- 2. Autotime Logic (New) ---
        if hasattr(self, 'time_controls'):
            for prefix, ctrls in self.time_controls.items():
                if ctrls['check_autotime'].isChecked():
                    addr_str = ctrls['address_edit'].text()
                    addr = RedvyprAddress(addr_str)

                    if addr.matches(data):
                        try:
                            val = addr(data)
                            # Convert to QDateTime if val is a timestamp or datetime
                            if isinstance(val, (int, float)):
                                dt = QtCore.QDateTime.fromSecsSinceEpoch(int(val), QtCore.Qt.TimeSpec.UTC)
                            elif isinstance(val, datetime.datetime):
                                # Add utz timezone if not present
                                if val.tzinfo is None:
                                    val = val.replace(tzinfo=datetime.timezone.utc)
                                    dt = QtCore.QDateTime(val)
                                    dt.setTimeSpec(QtCore.Qt.TimeSpec.UTC)
                                elif isinstance(val, datetime.datetime):
                                    dt = QtCore.QDateTime(val)
                            else:
                                continue

                            # Update start_dt or end_dt
                            target_dt_edit = self.start_dt if prefix == 'start' else self.end_dt
                            target_dt_edit.setDateTime(dt)
                        except Exception:
                            pass

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

        sync_btn = QtWidgets.QPushButton(" Sync to Metadata")
        sync_btn.setIcon(qtawesome.icon('fa5s.sync'))
        sync_btn.setToolTip("Upload all local events to Redvypr metadata")
        sync_btn.clicked.connect(self.sync_events_to_remote)

        load_btn = QtWidgets.QPushButton(" Load from Metadata")
        load_btn.setIcon(qtawesome.icon('fa5s.cloud-download-alt'))
        load_btn.setToolTip("Fetch all events from Redvypr metadata")
        load_btn.clicked.connect(self.load_events_from_remote)

        btn_lay.addWidget(sync_btn)
        btn_lay.addWidget(load_btn)
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

    def sync_events_to_remote(self):
        """Push all local events from custom_config to the Redvypr metadata store."""
        if not self.custom_config.events:
            QtWidgets.QMessageBox.information(self, "Sync", "No local events to sync.")
            return

        reply = QtWidgets.QMessageBox.question(
            self, "Sync Metadata",
            f"Do you want sync {len(self.custom_config.events)} events to metadata?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )

        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                for event in self.custom_config.events:
                    # Calling the method we defined in the Device class earlier
                    self.device.add_event_to_metadata(event)
                QtWidgets.QMessageBox.information(self, "Success",
                                                  "Metadata sync complete.")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Sync failed: {e}")

    def load_events_from_remote(self):
        """Fetch events from Redvypr metadata and merge them into the local list."""
        try:
            # Using the 'load' method from the Device class
            remote_events = self.device.load_events_from_metadata()

            if not remote_events:
                QtWidgets.QMessageBox.information(self, "Load",
                                                  "No events found in metadata")
                return

            # Avoid duplicates by checking UUIDs
            local_uuids = [e.uuid for e in self.custom_config.events]
            new_count = 0

            for r_event in remote_events:
                if r_event.uuid not in local_uuids:
                    self.custom_config.events.append(r_event)
                    new_count += 1
                else:
                    # Optional: Update existing local event with remote data
                    idx = local_uuids.index(r_event.uuid)
                    self.custom_config.events[idx] = r_event

            if new_count > 0 or remote_events:
                self.event_model.refresh()
                QtWidgets.QMessageBox.information(
                    self, "Load Complete",
                    f"Loaded {len(remote_events)} events ({new_count} were new)."
                )

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error",
                                           f"Failed to load metadata: {e}")

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




