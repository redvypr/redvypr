import datetime
from PyQt6 import QtWidgets, QtCore, QtGui
import logging
import sys
from redvypr.device import RedvyprDeviceCustomConfig, RedvyprDevice
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetStartonly, RedvyprdevicewidgetSimple
from redvypr.widgets.redvyprMetadataWidget import MetadataWidget
from redvypr.widgets.redvyprAddressWidget import RedvyprAddressWidget, RedvyprMultipleAddressesWidget
from redvypr.data_packets import check_for_command
import pydantic
import typing
import qtawesome
import uuid
from redvypr.redvypr_address import RedvyprAddress

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('measurement')
logger.setLevel(logging.INFO)

redvypr_devicemodule = True


class Person(pydantic.BaseModel):
    first_name: str = pydantic.Field(default="")
    last_name: str = pydantic.Field(default="")
    email: typing.Optional[str] = None
    phone: typing.Optional[str] = None
    role: typing.Optional[str] = pydantic.Field(
        default=None,
        description="e.g., 'Lead Scientist', 'Field Technician'"
    )

    @property
    def full_name(self) -> str:
        """Returns the combined first and last name."""
        return f"{self.first_name} {self.last_name}"


class MeasurementDatastreamConfig(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='allow')
    version: str = 'v1.0'
    name: str = ''
    tstart: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    tend: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    location: typing.Optional[str] = pydantic.Field(default=None)
    lon: typing.Optional[float] = pydantic.Field(default=None)
    lat: typing.Optional[float] = pydantic.Field(default=None)
    contacts: typing.List[Person] = pydantic.Field(default_factory=list)
    description: str = 'A measurement config for a scpecific datastream'


class MeasurementConfig(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='allow')
    version: str = 'v1.0'
    name: str = ''
    uuid: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    #datastreams: typing.List[RedvyprAddress] = pydantic.Field(default_factory=list)
    datastreams: typing.Dict[str,MeasurementDatastreamConfig] = pydantic.Field(default_factory=dict)
    tstart: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    tend: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    location: typing.Optional[str] = pydantic.Field(default=None)
    lon: typing.Optional[float] = pydantic.Field(default=None)
    lat: typing.Optional[float] = pydantic.Field(default=None)
    contacts: typing.List[Person] = pydantic.Field(default_factory=list)
    description: str = 'A measurement config of several devices'


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = False
    description: str = 'A device to define measurements'


class DeviceCustomConfig(RedvyprDeviceCustomConfig):
    contacts: typing.List[Person] = pydantic.Field(default_factory=list)
    measurements: typing.List[MeasurementConfig] = pydantic.Field(default_factory=list)


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

    def create_address_string_from_measurement(self, measurement):
        address_str = f"@i:measurement__{measurement.uuid} and d:measurement_metadata"
        return address_str
    def add_measurement_to_metadata(self, measurement):
        funcname = __name__ + '.add_measurement_to_metadata()'
        print(f"{funcname}")
        print(f"Measurement:{measurement}")
        address_str = self.create_address_string_from_measurement(measurement)
        meta_address = RedvyprAddress(address_str)
        meta_address_str = meta_address.to_address_string()
        metadata = measurement.model_dump()
        print("Adding metadata",metadata)
        self.redvypr.set_metadata(meta_address_str, metadata=metadata)
        # Try to remove the measurement metadata entries in all datastreams
        self.redvypr.rem_metadata("@", metadata_keys=[meta_address_str], mode="matches")
        for addr_datastream, metadata_datastream in metadata["datastreams"].items():
            print(f"Adding metadata to datastream {addr_datastream}")
            print("Metadata",metadata_datastream)
            metadata_datastream_submit = {meta_address_str:metadata_datastream}
            print("Adding",metadata_datastream_submit)
            self.redvypr.set_metadata(addr_datastream,metadata=metadata_datastream_submit)

    def rem_measurement_from_metadata(self, measurement):
        funcname = __name__ + '.rem_measurement_from_metadata()'
        print(f"{funcname}")
        address_str = self.create_address_string_from_measurement(measurement)
        # Delete the whole entry
        print(f"Deleting metadata entry for measurement:{address_str}")
        self.redvypr.rem_metadata(address_str, metadata_keys=[], constraint_entries=[])
        for addr_datastream, metadata_datastream in measurement.datastreams.items():
            self.redvypr.rem_metadata(addr_datastream, metadata_keys=[address_str])

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


class ContactEditWidget(QtWidgets.QWidget):
    """Widget to edit a Person object inside a Tab."""
    # Signals to communicate with the main device widget
    data_changed = QtCore.Signal(object)  # Sends the Person object
    request_close = QtCore.Signal()  # Signals that editing is finished

    def __init__(self, person: typing.Optional[Person] = None, parent=None):
        super().__init__(parent)
        self.original_name = person.full_name if person else "New Contact"
        if person is None:
            person = Person()

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.first_name_edit = QtWidgets.QLineEdit(person.first_name if person else "")
        self.last_name_edit = QtWidgets.QLineEdit(person.last_name if person else "")
        self.role_edit = QtWidgets.QLineEdit(person.role or "")
        self.email_edit = QtWidgets.QLineEdit(person.email or "")

        form.addRow("First Name:", self.first_name_edit)
        form.addRow("Last Name:", self.last_name_edit)
        form.addRow("Role:", self.role_edit)
        form.addRow("Email:", self.email_edit)
        layout.addLayout(form)

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self.apply_btn = QtWidgets.QPushButton(" Save & Close")
        self.apply_btn.setIcon(qtawesome.icon('fa5s.save', color='green'))
        self.apply_btn.clicked.connect(self.emit_data)

        btn_layout.addStretch()
        btn_layout.addWidget(self.apply_btn)
        layout.addLayout(btn_layout)
        layout.addStretch()

    def emit_data(self):
        try:
            person = Person(
                first_name=self.first_name_edit.text().strip(),
                last_name=self.last_name_edit.text().strip(),
                role=self.role_edit.text().strip() or None,
                email=self.email_edit.text().strip() or None
            )
            self.data_changed.emit(person)
            self.request_close.emit()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Validation Error", str(e))

#
#
#
# Measurement config
#
#
#



class MeasurementConfigEditor(QtWidgets.QWidget):
    """
    Recursive Editor for MeasurementConfig and MeasurementDatastreamConfig.
    - If is_subconfig=False: Full editor with Datastream list.
    - If is_subconfig=True: Metadata-only editor (recycled UI).
    """
    config_updated = QtCore.Signal(object)
    request_close = QtCore.Signal()

    def __init__(self, config: typing.Union[
        'MeasurementConfig', 'MeasurementDatastreamConfig'],
                 parent=None, device=None, is_subconfig=False):
        super().__init__(parent)
        self.device = device
        self.is_subconfig = is_subconfig

        # Work on a copy to allow discarding changes
        self.config = config.model_copy()

        self.setup_ui()
        self.load_config_into_ui()

    def create_section(self, title: str, checked: bool = False):
        """Helper to create a checkable QGroupBox that hides content."""
        group = QtWidgets.QGroupBox(title)
        group.setCheckable(True)
        group.setChecked(checked)

        group_layout = QtWidgets.QVBoxLayout(group)
        group_layout.setContentsMargins(5, 15, 5, 5)
        group_layout.setSpacing(0)

        content_widget = QtWidgets.QWidget()
        content_widget.setVisible(checked)
        group_layout.addWidget(content_widget)

        group.toggled.connect(content_widget.setVisible)
        return group, content_widget

    def setup_ui(self):
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # --- LEFT SIDE: Datastreams (Only for Main Config) ---
        self.ds_container = QtWidgets.QWidget()
        ds_layout = QtWidgets.QVBoxLayout(self.ds_container)
        self.ds_group = QtWidgets.QGroupBox("Datastreams")
        ds_group_layout = QtWidgets.QVBoxLayout(self.ds_group)

        self.ds_list = QtWidgets.QListWidget()
        self.ds_list.setToolTip("Right-click an item to edit specific metadata")
        # Context Menu Setup
        self.ds_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ds_list.customContextMenuRequested.connect(self.on_ds_context_menu)

        ds_group_layout.addWidget(self.ds_list)

        ds_btns = QtWidgets.QHBoxLayout()
        self.add_ds_btn = QtWidgets.QPushButton(" Add")
        self.add_ds_btn.setIcon(qtawesome.icon('fa5s.plus'))
        self.choose_ds_btn = QtWidgets.QPushButton(" Choose")
        self.choose_ds_btn.setIcon(qtawesome.icon('fa5s.search-plus'))
        self.remove_ds_btn = QtWidgets.QPushButton(" Remove")
        self.remove_ds_btn.setIcon(qtawesome.icon('fa5s.trash-alt'))

        ds_btns.addWidget(self.add_ds_btn)
        ds_btns.addWidget(self.choose_ds_btn)
        ds_btns.addWidget(self.remove_ds_btn)
        ds_group_layout.addLayout(ds_btns)
        ds_layout.addWidget(self.ds_group)

        # Hide left side if we are editing a sub-datastream
        if self.is_subconfig:
            self.ds_container.hide()

        # --- RIGHT SIDE: Details (Scrollable) ---
        self.meta_scroll = QtWidgets.QScrollArea()
        self.meta_scroll.setWidgetResizable(True)
        self.meta_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.meta_content = QtWidgets.QWidget()
        self.meta_layout = QtWidgets.QVBoxLayout(self.meta_content)
        self.meta_layout.setSpacing(2)

        # 1. Identification
        self.id_group, id_content = self.create_section("Identification", checked=True)
        id_form = QtWidgets.QFormLayout(id_content)
        self.name_edit = QtWidgets.QLineEdit()
        id_form.addRow("Name:", self.name_edit)

        # UUID only exists in main MeasurementConfig
        if not self.is_subconfig:
            self.uuid_edit = QtWidgets.QLineEdit()
            self.uuid_edit.setEnabled(False)
            id_form.addRow("UUID:", self.uuid_edit)

        self.meta_layout.addWidget(self.id_group)

        # 2. General Info
        self.basic_group, basic_content = self.create_section("General Information",
                                                              checked=True)
        basic_form = QtWidgets.QFormLayout(basic_content)
        self.version_label = QtWidgets.QLabel(f"<b>{self.config.version}</b>")
        self.location_edit = QtWidgets.QLineEdit()
        self.description_edit = QtWidgets.QPlainTextEdit()
        self.description_edit.setMaximumHeight(80)

        basic_form.addRow("Version:", self.version_label)
        basic_form.addRow("Location:", self.location_edit)
        basic_form.addRow("Description:", self.description_edit)
        self.meta_layout.addWidget(self.basic_group)

        # 3. Time Range
        self.time_group, time_content = self.create_section("Time Range", checked=False)
        time_form = QtWidgets.QFormLayout(time_content)
        self.start_dt = QtWidgets.QDateTimeEdit(calendarPopup=True)
        self.end_dt = QtWidgets.QDateTimeEdit(calendarPopup=True)
        self.start_dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        time_form.addRow("Start:", self.start_dt)
        time_form.addRow("End:", self.end_dt)
        self.meta_layout.addWidget(self.time_group)

        # 4. Coordinates
        self.coord_group, coord_content = self.create_section("Coordinates",
                                                              checked=False)
        coord_form = QtWidgets.QFormLayout(coord_content)
        self.lon_spin = QtWidgets.QDoubleSpinBox()
        self.lat_spin = QtWidgets.QDoubleSpinBox()
        for s in [self.lon_spin, self.lat_spin]:
            s.setRange(-180, 180)
            s.setDecimals(6)
            s.setSpecialValueText("Not set")
        coord_form.addRow("Lon:", self.lon_spin)
        coord_form.addRow("Lat:", self.lat_spin)
        self.meta_layout.addWidget(self.coord_group)

        # 5. Contacts
        self.contacts_group, contact_content = self.create_section("Contacts",
                                                                   checked=False)
        contact_lay = QtWidgets.QVBoxLayout(contact_content)
        self.contact_table = QtWidgets.QTableWidget(0, 3)
        self.contact_table.setHorizontalHeaderLabels(["Name", "Role", "Email"])
        self.contact_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        contact_lay.addWidget(self.contact_table)

        c_btns = QtWidgets.QHBoxLayout()
        self.add_contact_btn = QtWidgets.QPushButton(" Add")
        self.remove_contact_btn = QtWidgets.QPushButton(" Remove")
        c_btns.addWidget(self.add_contact_btn)
        c_btns.addWidget(self.remove_contact_btn)
        contact_lay.addLayout(c_btns)
        self.meta_layout.addWidget(self.contacts_group)

        # 6. Extra Attributes
        self.extra_group, extra_content = self.create_section("Extra Attributes",
                                                              checked=False)
        extra_lay = QtWidgets.QVBoxLayout(extra_content)
        self.extra_table = QtWidgets.QTableWidget(0, 2)
        self.extra_table.setHorizontalHeaderLabels(["Key", "Value"])
        self.extra_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        extra_lay.addWidget(self.extra_table)

        ex_btns = QtWidgets.QHBoxLayout()
        self.add_extra_btn = QtWidgets.QPushButton(" Add")
        self.remove_extra_btn = QtWidgets.QPushButton(" Remove")
        ex_btns.addWidget(self.add_extra_btn)
        ex_btns.addWidget(self.remove_extra_btn)
        extra_lay.addLayout(ex_btns)
        self.meta_layout.addWidget(self.extra_group)

        self.meta_layout.addStretch()

        # Assembly
        self.meta_scroll.setWidget(self.meta_content)
        self.splitter.addWidget(self.ds_container)
        self.splitter.addWidget(self.meta_scroll)
        self.splitter.setStretchFactor(1, 2)
        self.main_layout.addWidget(self.splitter)

        # Bottom Buttons
        bottom_btns = QtWidgets.QHBoxLayout()
        self.discard_btn = QtWidgets.QPushButton(" Discard")
        self.save_btn = QtWidgets.QPushButton(
            " Save Changes" if self.is_subconfig else " Save Measurement")
        self.save_btn.setStyleSheet(
            "background-color: #2c3e50; color: white; font-weight: bold; padding: 8px;")
        bottom_btns.addStretch()
        bottom_btns.addWidget(self.discard_btn)
        bottom_btns.addWidget(self.save_btn)
        self.main_layout.addLayout(bottom_btns)

        # Signals
        self.add_ds_btn.clicked.connect(self.on_add_datastream)
        self.choose_ds_btn.clicked.connect(self.on_choose_datastream)
        self.remove_ds_btn.clicked.connect(self.on_remove_datastream)
        self.add_contact_btn.clicked.connect(self.on_add_contact)
        self.remove_contact_btn.clicked.connect(self.on_remove_contact)
        self.add_extra_btn.clicked.connect(self.on_add_extra_attribute)
        self.remove_extra_btn.clicked.connect(self.on_remove_extra_attribute)
        self.save_btn.clicked.connect(self.save_and_emit)
        self.discard_btn.clicked.connect(self.request_close.emit)

    def load_config_into_ui(self):
        self.name_edit.setText(self.config.name or "")
        if not self.is_subconfig:
            self.uuid_edit.setText(self.config.uuid or "")

        self.location_edit.setText(self.config.location or "")
        self.description_edit.setPlainText(self.config.description or "")

        if self.config.tstart: self.start_dt.setDateTime(self.config.tstart)
        if self.config.tend: self.end_dt.setDateTime(self.config.tend)

        self.lon_spin.setValue(
            self.config.lon if self.config.lon is not None else self.lon_spin.minimum())
        self.lat_spin.setValue(
            self.config.lat if self.config.lat is not None else self.lat_spin.minimum())

        self.refresh_contact_table()
        self.refresh_extra_table()
        if not self.is_subconfig:
            self.refresh_datastream_list()

    def refresh_datastream_list(self):
        self.ds_list.clear()
        for address, sub_cfg in self.config.datastreams.items():
            item = QtWidgets.QListWidgetItem(address)
            # Visual hint if datastream has custom location/description
            if sub_cfg.location or (
                    sub_cfg.description and "specific" not in sub_cfg.description):
                item.setIcon(qtawesome.icon('fa5s.info-circle', color='orange'))
            self.ds_list.addItem(item)

    def on_ds_context_menu(self, pos):
        item = self.ds_list.itemAt(pos)
        if not item: return

        menu = QtWidgets.QMenu()
        edit_meta = menu.addAction(qtawesome.icon('fa5s.edit'),
                                   "Edit Datastream Metadata...")
        action = menu.exec_(self.ds_list.mapToGlobal(pos))

        if action == edit_meta:
            self.open_sub_editor(item.text())

    def open_sub_editor(self, address: str):
        sub_cfg = self.config.datastreams[address]

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Metadata: {address}")
        dialog.setMinimumSize(700, 500)
        lay = QtWidgets.QVBoxLayout(dialog)

        sub_editor = MeasurementConfigEditor(config=sub_cfg, device=self.device,
                                             is_subconfig=True)
        lay.addWidget(sub_editor)

        def update_local_dict(updated_cfg):
            self.config.datastreams[address] = updated_cfg
            self.refresh_datastream_list()

        sub_editor.config_updated.connect(update_local_dict)
        sub_editor.request_close.connect(dialog.accept)
        dialog.exec_()

    def on_add_datastream(self):
        text, ok = QtWidgets.QInputDialog.getText(self, "Add Datastream",
                                                  "Address String:")
        if ok and text.strip():
            addr = text.strip()
            if addr not in self.config.datastreams:
                self.config.datastreams[addr] = MeasurementDatastreamConfig(name=addr)
                self.refresh_datastream_list()

    def on_choose_datastream(self):
        if self.device and hasattr(self.device, 'redvypr'):
            self.choose_ds_widget = RedvyprMultipleAddressesWidget(
                redvypr=self.device.redvypr)
            self.choose_ds_widget.apply.connect(self.add_datastreams_from_widget)
            self.choose_ds_widget.show()
        else:
            QtWidgets.QMessageBox.warning(self, "Warning",
                                          "No active device connection available.")


    def add_datastreams_from_widget(self, datastreams):
        for address in datastreams.get('addresses', []):
            print(f"Address:{address}")
            print(type(address))
            address_str = address.to_address_string()
            if address_str not in self.config.datastreams:
                self.config.datastreams[address_str] = MeasurementDatastreamConfig(name=address_str)

        self.refresh_datastream_list()


    def on_remove_datastream(self):
        item = self.ds_list.currentItem()
        if item:
            self.config.datastreams.pop(item.text())
            self.refresh_datastream_list()

    # --- Standard Table Helpers (Contacts/Extras) ---

    def refresh_contact_table(self):
        self.contact_table.setRowCount(0)
        for p in self.config.contacts:
            r = self.contact_table.rowCount()
            self.contact_table.insertRow(r)
            self.contact_table.setItem(r, 0, QtWidgets.QTableWidgetItem(p.full_name))
            self.contact_table.setItem(r, 1, QtWidgets.QTableWidgetItem(p.role or ""))
            self.contact_table.setItem(r, 2, QtWidgets.QTableWidgetItem(p.email or ""))

    def on_add_contact(self):
        dialog = ContactEditWidget(parent=self)
        dialog.contact_applied.connect(
            lambda p: [self.config.contacts.append(p), self.refresh_contact_table()])
        dialog.exec_()

    def on_remove_contact(self):
        row = self.contact_table.currentRow()
        if row >= 0:
            self.config.contacts.pop(row)
            self.refresh_contact_table()

    def refresh_extra_table(self):
        self.extra_table.setRowCount(0)
        extras = self.config.model_extra or {}
        for k, v in extras.items():
            r = self.extra_table.rowCount()
            self.extra_table.insertRow(r)
            self.extra_table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(k)))
            self.extra_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(v)))

    def on_add_extra_attribute(self):
        r = self.extra_table.rowCount()
        self.extra_table.insertRow(r)
        self.extra_table.setItem(r, 0, QtWidgets.QTableWidgetItem("key"))

    def on_remove_extra_attribute(self):
        row = self.extra_table.currentRow()
        if row >= 0: self.extra_table.removeRow(row)

    def save_and_emit(self):
        try:
            self.config.name = self.name_edit.text()
            self.config.location = self.location_edit.text()
            self.config.description = self.description_edit.toPlainText()
            self.config.tstart = self.start_dt.dateTime().toPyDateTime()
            self.config.tend = self.end_dt.dateTime().toPyDateTime()
            self.config.lon = self.lon_spin.value() if self.lon_spin.value() != self.lon_spin.minimum() else None
            self.config.lat = self.lat_spin.value() if self.lat_spin.value() != self.lat_spin.minimum() else None

            # Handle Extra Fields
            all_data = self.config.model_dump()
            for r in range(self.extra_table.rowCount()):
                k = self.extra_table.item(r, 0).text() if self.extra_table.item(r,
                                                                                0) else None
                v = self.extra_table.item(r, 1).text() if self.extra_table.item(r,
                                                                                1) else ""
                if k: all_data[k] = v

            ModelClass = MeasurementDatastreamConfig if self.is_subconfig else MeasurementConfig
            self.config = ModelClass.model_validate(all_data)

            self.config_updated.emit(self.config)
            self.request_close.emit()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))





class MeasurementConfigEditor_legacy(QtWidgets.QWidget):
    """
    Complete Editor for MeasurementConfig.
    Features:
    - Splitter layout (Datastreams left, Metadata right)
    - Collapsible sections that hide content when unchecked
    - Support for dynamic Extra Attributes via Pydantic model_extra
    - UUID generation and Name-to-Tab synchronization support
    """
    config_updated = QtCore.Signal(object)
    request_close = QtCore.Signal()

    def __init__(self, config: 'MeasurementConfig', parent=None, device=None):
        super().__init__(parent)
        self.device = device
        # Work on a copy to allow discarding changes
        self.config = config.model_copy()

        self.setup_ui()
        self.load_config_into_ui()

    def create_section(self, title: str, checked: bool = False):
        """Helper to create a checkable QGroupBox that hides content and collapses spacing."""
        group = QtWidgets.QGroupBox(title)
        group.setCheckable(True)
        group.setChecked(checked)

        group_layout = QtWidgets.QVBoxLayout(group)
        group_layout.setContentsMargins(5, 15, 5, 5)
        group_layout.setSpacing(0)

        content_widget = QtWidgets.QWidget()
        content_widget.setVisible(checked)
        group_layout.addWidget(content_widget)

        # Toggle visibility to collapse the section entirely
        group.toggled.connect(content_widget.setVisible)

        return group, content_widget

    def setup_ui(self):
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # --- LEFT SIDE: Datastreams ---
        self.ds_container = QtWidgets.QWidget()
        ds_layout = QtWidgets.QVBoxLayout(self.ds_container)
        self.ds_group = QtWidgets.QGroupBox("Datastreams")
        ds_group_layout = QtWidgets.QVBoxLayout(self.ds_group)
        self.ds_list = QtWidgets.QListWidget()
        ds_group_layout.addWidget(self.ds_list)

        ds_btns = QtWidgets.QHBoxLayout()
        self.add_ds_btn = QtWidgets.QPushButton(" Add")
        self.add_ds_btn.setIcon(qtawesome.icon('fa5s.plus'))

        self.choose_ds_btn = QtWidgets.QPushButton(" Choose")
        self.choose_ds_btn.setIcon(qtawesome.icon('fa5s.search-plus'))

        self.remove_ds_btn = QtWidgets.QPushButton(" Remove")
        self.remove_ds_btn.setIcon(qtawesome.icon('fa5s.trash-alt'))

        ds_btns.addWidget(self.add_ds_btn)
        ds_btns.addWidget(self.choose_ds_btn)
        ds_btns.addWidget(self.remove_ds_btn)
        ds_group_layout.addLayout(ds_btns)
        ds_layout.addWidget(self.ds_group)

        # --- RIGHT SIDE: Details (Scrollable) ---
        self.meta_scroll = QtWidgets.QScrollArea()
        self.meta_scroll.setWidgetResizable(True)
        self.meta_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.meta_content = QtWidgets.QWidget()
        self.meta_layout = QtWidgets.QVBoxLayout(self.meta_content)
        self.meta_layout.setSpacing(2)

        # 1. Identification (Checked)
        self.id_group, id_content = self.create_section("Identification", checked=True)
        id_form = QtWidgets.QFormLayout(id_content)
        self.name_edit = QtWidgets.QLineEdit()
        self.uuid_edit = QtWidgets.QLineEdit()
        self.uuid_edit.setEnabled(False)
        #self.regen_uuid_btn = QtWidgets.QPushButton(icon=qtawesome.icon('fa5s.sync'))

        uuid_lay = QtWidgets.QHBoxLayout()
        uuid_lay.addWidget(self.uuid_edit)
        #uuid_lay.addWidget(self.regen_uuid_btn)

        id_form.addRow("Measurement Name:", self.name_edit)
        id_form.addRow("UUID:", uuid_lay)
        self.meta_layout.addWidget(self.id_group)

        # 2. General Information (Checked)
        self.basic_group, basic_content = self.create_section("General Information",
                                                              checked=True)
        basic_form = QtWidgets.QFormLayout(basic_content)
        self.version_label = QtWidgets.QLabel(f"<b>{self.config.version}</b>")
        self.location_edit = QtWidgets.QLineEdit()
        self.description_edit = QtWidgets.QPlainTextEdit()
        self.description_edit.setMaximumHeight(80)

        basic_form.addRow("Config Version:", self.version_label)
        basic_form.addRow("Location:", self.location_edit)
        basic_form.addRow("Description:", self.description_edit)
        self.meta_layout.addWidget(self.basic_group)

        # 3. Time Range (Unchecked)
        self.time_group, time_content = self.create_section("Time Range", checked=False)
        time_form = QtWidgets.QFormLayout(time_content)
        self.start_dt = QtWidgets.QDateTimeEdit(calendarPopup=True)
        self.end_dt = QtWidgets.QDateTimeEdit(calendarPopup=True)
        self.start_dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        time_form.addRow("Start Time:", self.start_dt)
        time_form.addRow("End Time:", self.end_dt)
        self.meta_layout.addWidget(self.time_group)

        # 4. Coordinates (Unchecked)
        self.coord_group, coord_content = self.create_section("Fixed Coordinates",
                                                              checked=False)
        coord_form = QtWidgets.QFormLayout(coord_content)
        self.lon_spin = QtWidgets.QDoubleSpinBox()
        self.lat_spin = QtWidgets.QDoubleSpinBox()
        for s in [self.lon_spin, self.lat_spin]:
            s.setRange(-180, 180)
            s.setDecimals(6)
            s.setSpecialValueText("Not set")
        coord_form.addRow("Longitude:", self.lon_spin)
        coord_form.addRow("Latitude:", self.lat_spin)
        self.meta_layout.addWidget(self.coord_group)

        # 5. Contacts (Unchecked)
        self.contacts_group, contact_content = self.create_section("Involved Contacts",
                                                                   checked=False)
        contact_lay = QtWidgets.QVBoxLayout(contact_content)
        self.contact_table = QtWidgets.QTableWidget(0, 3)
        self.contact_table.setHorizontalHeaderLabels(["Name", "Role", "Email"])
        self.contact_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        contact_lay.addWidget(self.contact_table)

        c_btns = QtWidgets.QHBoxLayout()
        self.add_contact_btn = QtWidgets.QPushButton(" Add Contact")
        self.remove_contact_btn = QtWidgets.QPushButton(" Remove Contact")
        c_btns.addWidget(self.add_contact_btn)
        c_btns.addWidget(self.remove_contact_btn)
        contact_lay.addLayout(c_btns)
        self.meta_layout.addWidget(self.contacts_group)

        # 6. Extra Attributes (Unchecked)
        self.extra_group, extra_content = self.create_section("Extra Attributes",
                                                              checked=False)
        extra_lay = QtWidgets.QVBoxLayout(extra_content)
        self.extra_table = QtWidgets.QTableWidget(0, 2)
        self.extra_table.setHorizontalHeaderLabels(["Key", "Value (Text)"])
        self.extra_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        extra_lay.addWidget(self.extra_table)

        ex_btns = QtWidgets.QHBoxLayout()
        self.add_extra_btn = QtWidgets.QPushButton(" Add Attribute")
        self.remove_extra_btn = QtWidgets.QPushButton(" Remove Attribute")
        ex_btns.addWidget(self.add_extra_btn)
        ex_btns.addWidget(self.remove_extra_btn)
        extra_lay.addLayout(ex_btns)
        self.meta_layout.addWidget(self.extra_group)

        self.meta_layout.addStretch()

        # Assembly
        self.meta_scroll.setWidget(self.meta_content)
        self.splitter.addWidget(self.ds_container)
        self.splitter.addWidget(self.meta_scroll)
        self.splitter.setStretchFactor(1, 2)
        self.main_layout.addWidget(self.splitter)

        # Bottom Buttons
        bottom_btns = QtWidgets.QHBoxLayout()
        self.discard_btn = QtWidgets.QPushButton(" Discard")
        self.save_btn = QtWidgets.QPushButton(" Save Configuration")
        self.save_btn.setStyleSheet(
            "background-color: #2c3e50; color: white; font-weight: bold; padding: 10px;")
        bottom_btns.addStretch()
        bottom_btns.addWidget(self.discard_btn)
        bottom_btns.addWidget(self.save_btn)
        self.main_layout.addLayout(bottom_btns)

        # Signal Connections
        #self.regen_uuid_btn.clicked.connect(self.generate_new_uuid)
        self.add_ds_btn.clicked.connect(self.on_add_datastream)
        self.choose_ds_btn.clicked.connect(self.on_choose_datastream)
        self.remove_ds_btn.clicked.connect(self.on_remove_datastream)
        self.add_contact_btn.clicked.connect(self.on_add_contact)
        self.remove_contact_btn.clicked.connect(self.on_remove_contact)
        self.add_extra_btn.clicked.connect(self.on_add_extra_attribute)
        self.remove_extra_btn.clicked.connect(self.on_remove_extra_attribute)
        self.save_btn.clicked.connect(self.save_and_emit)
        self.discard_btn.clicked.connect(self.request_close.emit)

    def load_config_into_ui(self):
        """Populates UI elements from the internal config object."""
        self.name_edit.setText(self.config.name or "")
        self.uuid_edit.setText(self.config.uuid or "")
        self.location_edit.setText(self.config.location or "")
        self.description_edit.setPlainText(self.config.description or "")

        if self.config.tstart: self.start_dt.setDateTime(self.config.tstart)
        if self.config.tend: self.end_dt.setDateTime(self.config.tend)

        self.lon_spin.setValue(
            self.config.lon if self.config.lon is not None else self.lon_spin.minimum())
        self.lat_spin.setValue(
            self.config.lat if self.config.lat is not None else self.lat_spin.minimum())

        self.refresh_contact_table()
        self.refresh_datastream_list()
        self.refresh_extra_table()

    def generate_new_uuid(self):
        self.uuid_edit.setText(str(uuid.uuid4()))

    def refresh_contact_table(self):
        self.contact_table.setRowCount(0)
        for person in self.config.contacts:
            row = self.contact_table.rowCount()
            self.contact_table.insertRow(row)
            self.contact_table.setItem(row, 0,
                                       QtWidgets.QTableWidgetItem(person.full_name))
            self.contact_table.setItem(row, 1,
                                       QtWidgets.QTableWidgetItem(person.role or "-"))
            self.contact_table.setItem(row, 2,
                                       QtWidgets.QTableWidgetItem(person.email or "-"))

    def refresh_datastream_list(self):
        self.ds_list.clear()
        for ds in self.config.datastreams:
            self.ds_list.addItem(str(ds))

    def refresh_extra_table(self):
        self.extra_table.setRowCount(0)
        extras = self.config.model_extra or {}
        for key, value in extras.items():
            row = self.extra_table.rowCount()
            self.extra_table.insertRow(row)
            self.extra_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(key)))
            self.extra_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(value)))

    def on_add_datastream(self):
        text, ok = QtWidgets.QInputDialog.getText(self, "Add Address",
                                                  "Address String:")
        if ok and text:
            # Note: Ensure RedvyprAddress is imported correctly
            self.config.datastreams.append(RedvyprAddress(address=text))
            self.refresh_datastream_list()

    def on_choose_datastream(self):
        if self.device and hasattr(self.device, 'redvypr'):
            self.choose_ds_widget = RedvyprMultipleAddressesWidget(
                redvypr=self.device.redvypr)
            self.choose_ds_widget.apply.connect(self.add_datastreams_from_widget)
            self.choose_ds_widget.show()
        else:
            QtWidgets.QMessageBox.warning(self, "Warning",
                                          "No active device connection available.")

    def add_datastreams_from_widget(self, datastreams):
        for address in datastreams.get('addresses', []):
            self.config.datastreams.append(RedvyprAddress(address))
        self.refresh_datastream_list()

    def on_remove_datastream(self):
        row = self.ds_list.currentRow()
        if row >= 0:
            self.config.datastreams.pop(row)
            self.refresh_datastream_list()

    def on_add_contact(self):
        dialog = ContactEditWidget(parent=self)
        dialog.contact_applied.connect(self.add_person_to_list)
        dialog.exec_()

    def add_person_to_list(self, person):
        self.config.contacts.append(person)
        self.refresh_contact_table()

    def on_remove_contact(self):
        row = self.contact_table.currentRow()
        if row >= 0:
            self.config.contacts.pop(row)
            self.refresh_contact_table()

    def on_add_extra_attribute(self):
        row = self.extra_table.rowCount()
        self.extra_table.insertRow(row)
        self.extra_table.setItem(row, 0, QtWidgets.QTableWidgetItem("new_key"))
        self.extra_table.setItem(row, 1, QtWidgets.QTableWidgetItem(""))

    def on_remove_extra_attribute(self):
        row = self.extra_table.currentRow()
        if row >= 0:
            self.extra_table.removeRow(row)

    def save_and_emit(self):
        """Validates input, updates local config, and notifies the parent."""
        try:
            # 1. Update Standard Fields
            self.config.name = self.name_edit.text().strip()
            self.config.uuid = self.uuid_edit.text().strip()
            self.config.location = self.location_edit.text().strip()
            self.config.description = self.description_edit.toPlainText().strip()
            self.config.tstart = self.start_dt.dateTime().toPyDateTime()
            self.config.tend = self.end_dt.dateTime().toPyDateTime()

            self.config.lon = self.lon_spin.value() if self.lon_spin.value() != self.lon_spin.minimum() else None
            self.config.lat = self.lat_spin.value() if self.lat_spin.value() != self.lat_spin.minimum() else None

            # 2. Update Extra Fields
            all_data = self.config.model_dump()
            for row in range(self.extra_table.rowCount()):
                key_item = self.extra_table.item(row, 0)
                val_item = self.extra_table.item(row, 1)
                if key_item:
                    k = key_item.text().strip()
                    v = val_item.text() if val_item else ""
                    if k: all_data[k] = v

            # 3. Re-validate to sync Extra fields
            self.config = MeasurementConfig.model_validate(all_data)

            # 4. Notify parent (will update Tab text and Dashboard list)
            self.config_updated.emit(self.config)
            self.request_close.emit()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Validation Error",
                                           f"Could not save: {e}")


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
        # Tracking map: { "meas_UUID" or "contact_Name": tab_index }
        self.opened_tabs = {}

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
        self.setup_measurement_dashboard()  # Permanent Tab 0
        self.setup_contact_dashboard()  # Permanent Tab 1

        self.refresh_dashboard_lists()

    def setup_measurement_dashboard(self):
        """Creates the main Measurement Management tab (Tab 0)."""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)

        m_group = QtWidgets.QGroupBox("Measurement Management")
        m_lay = QtWidgets.QVBoxLayout(m_group)

        self.meas_list = QtWidgets.QListWidget()
        self.meas_list.doubleClicked.connect(lambda: self.open_meas_tab(new=False))

        btn_lay = QtWidgets.QHBoxLayout()
        add_m_btn = QtWidgets.QPushButton(" Add Measurement")
        add_m_btn.setIcon(qtawesome.icon('fa5s.plus-circle'))
        add_m_btn.clicked.connect(lambda: self.open_meas_tab(new=True))

        rem_m_btn = QtWidgets.QPushButton(" Remove Selected")
        rem_m_btn.setIcon(qtawesome.icon('fa5s.trash-alt'))
        rem_m_btn.clicked.connect(self.remove_measurement)

        btn_lay.addWidget(add_m_btn)
        btn_lay.addWidget(rem_m_btn)

        m_lay.addWidget(self.meas_list)
        m_lay.addLayout(btn_lay)
        layout.addWidget(m_group)

        self.tabs.addTab(container, qtawesome.icon('fa5s.layer-group'), "Measurements")

    def setup_contact_dashboard(self):
        """Creates the permanent Contact Management tab (Tab 1)."""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)

        c_group = QtWidgets.QGroupBox("Contact Directory")
        c_lay = QtWidgets.QVBoxLayout(c_group)

        self.contact_list = QtWidgets.QListWidget()
        self.contact_list.doubleClicked.connect(
            lambda: self.open_contact_tab(new=False))

        btn_lay = QtWidgets.QHBoxLayout()
        add_c_btn = QtWidgets.QPushButton(" Add Contact")
        add_c_btn.setIcon(qtawesome.icon('fa5s.user-plus'))
        add_c_btn.clicked.connect(lambda: self.open_contact_tab(new=True))

        rem_c_btn = QtWidgets.QPushButton(" Remove Selected")
        rem_c_btn.setIcon(qtawesome.icon('fa5s.user-minus'))
        rem_c_btn.clicked.connect(self.remove_contact)

        btn_lay.addWidget(add_c_btn)
        btn_lay.addWidget(rem_c_btn)

        c_lay.addWidget(self.contact_list)
        c_lay.addLayout(btn_lay)
        layout.addWidget(c_group)

        self.tabs.addTab(container, qtawesome.icon('fa5s.address-book'), "Contacts")

    # --- Measurement Logic ---

    def open_meas_tab(self, new=False):
        if new:
            name, ok = QtWidgets.QInputDialog.getText(
                self, "New Measurement", "Enter name for the measurement:",
                QtWidgets.QLineEdit.Normal, "New Measurement"
            )
            if not ok or not name.strip():
                return
            config = MeasurementConfig(name=name.strip())
        else:
            row = self.meas_list.currentRow()
            if row < 0: return
            config = self.custom_config.measurements[row]

        identifier = f"meas_{config.uuid}"
        if identifier in self.opened_tabs:
            self.tabs.setCurrentIndex(self.opened_tabs[identifier])
            return

        editor = MeasurementConfigEditor(config=config, device=self.device)
        editor.config_updated.connect(lambda c: self.sync_measurement(c, is_new=new))
        editor.request_close.connect(lambda: self.close_tab_by_widget(editor))

        idx = self.tabs.addTab(editor, qtawesome.icon('fa5s.edit'),
                               config.name or "Unnamed")
        self.opened_tabs[identifier] = idx
        self.tabs.setCurrentIndex(idx)

    def sync_measurement(self, config_obj, is_new):
        if is_new:
            self.custom_config.measurements.append(config_obj)
        else:
            for i, m in enumerate(self.custom_config.measurements):
                if m.uuid == config_obj.uuid:
                    self.custom_config.measurements[i] = config_obj
                    break

        identifier = f"meas_{config_obj.uuid}"
        if identifier in self.opened_tabs:
            self.tabs.setTabText(self.opened_tabs[identifier], config_obj.name)

        self.refresh_dashboard_lists()
        self.device.add_measurement_to_metadata(config_obj)

    def remove_measurement(self):
        row = self.meas_list.currentRow()
        if row < 0: return

        config = self.custom_config.measurements[row]
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Deletion", f"Delete measurement '{config.name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.close_tab_by_identifier(f"meas_{config.uuid}")
            measurement_remove = self.custom_config.measurements.pop(row)
            self.refresh_dashboard_lists()
            self.device.rem_measurement_from_metadata(measurement_remove)

    # --- Contact Logic ---

    def open_contact_tab(self, new=False):
        if new:
            person = Person(full_name="New Contact")
        else:
            row = self.contact_list.currentRow()
            if row < 0: return
            person = self.custom_config.contacts[row]

        identifier = f"contact_{person.full_name}"
        if identifier in self.opened_tabs:
            self.tabs.setCurrentIndex(self.opened_tabs[identifier])
            return

        editor = ContactEditWidget(person=person)
        editor.data_changed.connect(lambda p: self.sync_contact(p, is_new=new))
        editor.request_close.connect(lambda: self.close_tab_by_widget(editor))

        idx = self.tabs.addTab(editor, qtawesome.icon('fa5s.user-edit'),
                               person.full_name)
        self.opened_tabs[identifier] = idx
        self.tabs.setCurrentIndex(idx)

    def sync_contact(self, person_obj, is_new):
        if is_new:
            self.custom_config.contacts.append(person_obj)
        else:
            for i, c in enumerate(self.custom_config.contacts):
                if c.full_name == person_obj.full_name:
                    self.custom_config.contacts[i] = person_obj
                    break
        self.refresh_dashboard_lists()

    def remove_contact(self):
        row = self.contact_list.currentRow()
        if row < 0: return

        person = self.custom_config.contacts[row]
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Deletion", f"Remove contact '{person.full_name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.close_tab_by_identifier(f"contact_{person.full_name}")
            self.custom_config.contacts.pop(row)
            self.refresh_dashboard_lists()

    # --- UI Helpers ---

    def refresh_dashboard_lists(self):
        self.contact_list.clear()
        for p in self.custom_config.contacts:
            self.contact_list.addItem(p.full_name)

        self.meas_list.clear()
        for m in self.custom_config.measurements:
            self.meas_list.addItem(m.name or "Unnamed")

    def close_tab(self, index):
        if index < 2: return  # Protect Measurements (0) and Contacts (1) tabs

        widget = self.tabs.widget(index)
        to_delete = [k for k, v in self.opened_tabs.items() if v == index]
        for k in to_delete:
            del self.opened_tabs[k]

        for k in self.opened_tabs:
            if self.opened_tabs[k] > index:
                self.opened_tabs[k] -= 1

        self.tabs.removeTab(index)
        widget.deleteLater()

    def close_tab_by_identifier(self, identifier):
        if identifier in self.opened_tabs:
            self.close_tab(self.opened_tabs[identifier])

    def close_tab_by_widget(self, widget):
        idx = self.tabs.indexOf(widget)
        if idx != -1:
            # Check which widget we should jump to
            target_index = 0
            if isinstance(widget, ContactEditWidget):
                target_index = 1

            self.close_tab(idx)
            self.tabs.setCurrentIndex(target_index)


