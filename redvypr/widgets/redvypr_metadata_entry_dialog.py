"""
Dialog for metadata of a datastream (Metadata window, tab Generic, "Add metadata ...").

Scope: all data, the host, the device or the channel of a datastream, e.g. the location or the user
of a host from a time on; the address is made by redvypr.metadata.scope_address(). An entry marked
"persistent" (redvypr.metadata) is found without the filters naming the run and the address of its
host, so it applies to the data after a restart too. Like all metadata it is kept in the
configuration and the databases.
"""

import datetime
import typing

from PyQt6 import QtCore, QtWidgets

from redvypr.redvypr_address import RedvyprAddress
import redvypr.metadata as redvypr_metadata

SCOPE_TEXTS = {'all': 'All data', 'host': 'This host', 'device': 'This device', 'channel': 'This channel'}


def _qdt(dt: datetime.datetime) -> QtCore.QDateTime:
    return QtCore.QDateTime.fromMSecsSinceEpoch(int(dt.timestamp() * 1000), QtCore.QTimeZone.utc())


def _pydt(qdt: QtCore.QDateTime) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(qdt.toMSecsSinceEpoch() / 1000, tz=datetime.timezone.utc)


class MetadataEntryDialog(QtWidgets.QDialog):
    """Datastream, scope, key, value, validity and persistence of a metadata entry."""

    def __init__(self, redvypr_instance=None, parent=None, datastream: typing.Optional[str] = None):
        super().__init__(parent)
        self.redvypr = redvypr_instance
        self.setWindowTitle('Add metadata')
        self._manual_address = False
        self.datastream = QtWidgets.QLineEdit(datastream or '')
        self.datastream.setPlaceholderText("a datastream, e.g. sine @ d:'test_device' and h:'laptop1'")
        self.btn_choose = QtWidgets.QPushButton('Choose ...')
        self.btn_choose.setEnabled(redvypr_instance is not None)
        self.btn_choose.clicked.connect(self.choose_datastream)
        self.scope = QtWidgets.QComboBox()
        for scope in redvypr_metadata.ADDRESS_SCOPES:
            self.scope.addItem(SCOPE_TEXTS[scope], scope)
        self.scope.setCurrentIndex(redvypr_metadata.ADDRESS_SCOPES.index('host'))
        self.scope.setToolTip('The metadata apply to all data, to all data of the host, to all channels of the '
                              'device or to the channel of the datastream')
        self.address = QtWidgets.QLineEdit()
        self.address.setToolTip('Address of the metadata, made from the datastream and the scope (without the '
                                'parts that change with every start); can be edited')
        self.address.textEdited.connect(lambda _t: setattr(self, '_manual_address', True))
        self.key = QtWidgets.QLineEdit()
        self.key.setPlaceholderText('e.g. location, user, comment')
        self.key.setToolTip('A new value of the same key ends the previous one at its begin (like every metadata '
                            'value): use other keys (comment_service, comment_weather, ...) for values that '
                            'stand beside each other')
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setPlaceholderText('the value (text)')
        self.persistent = QtWidgets.QCheckBox('persistent')
        self.persistent.setChecked(True)
        self.persistent.setToolTip('Found without the filters naming the run and the address of the host that '
                                   'wrote it (uuid, addr): it applies to the data after a restart too. The '
                                   'host name, the device and the channel stay filters.')
        self.valid_from = QtWidgets.QDateTimeEdit(_qdt(datetime.datetime.now(datetime.timezone.utc)))
        self.valid_from.setDisplayFormat('yyyy-MM-dd HH:mm:ss UTC')
        self.valid_from.setTimeZone(QtCore.QTimeZone.utc())
        self.use_until = QtWidgets.QCheckBox('until')
        self.valid_until = QtWidgets.QDateTimeEdit(_qdt(datetime.datetime.now(datetime.timezone.utc)))
        self.valid_until.setDisplayFormat('yyyy-MM-dd HH:mm:ss UTC')
        self.valid_until.setTimeZone(QtCore.QTimeZone.utc())
        self.valid_until.setEnabled(False)
        self.use_until.toggled.connect(self.valid_until.setEnabled)
        self.status = QtWidgets.QLabel('')
        self.status.setStyleSheet('color: red')
        self.status.setWordWrap(True)

        lay = QtWidgets.QFormLayout(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.datastream, 1)
        row.addWidget(self.btn_choose)
        lay.addRow('Datastream', row)
        lay.addRow('Scope', self.scope)
        lay.addRow('Address', self.address)
        lay.addRow('Key', self.key)
        lay.addRow('Value', self.text)
        lay.addRow('', self.persistent)
        lay.addRow('Valid from', self.valid_from)
        until = QtWidgets.QHBoxLayout()
        until.addWidget(self.use_until)
        until.addWidget(self.valid_until, 1)
        lay.addRow('', until)
        lay.addRow(self.status)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                                  QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept_if_valid)
        self.buttons.rejected.connect(self.reject)
        lay.addRow(self.buttons)
        self.datastream.textChanged.connect(lambda _t: self.update_address())
        self.scope.currentIndexChanged.connect(lambda _i: self.update_address())
        self.update_address()

    # --- address ---
    def choose_datastream(self):
        from redvypr.widgets.redvypr_address_widget import RedvyprAddressWidget
        self._chooser = RedvyprAddressWidget(redvypr=self.redvypr)
        self._chooser.apply.connect(self._datastream_chosen)
        self._chooser.show()

    def _datastream_chosen(self, address_dict):
        if 'address_str' in address_dict:
            self.datastream.setText(address_dict['address_str'])

    def update_address(self):
        """The address from the datastream and the scope (unless the address was edited)."""
        if self._manual_address:
            return
        scope = self.scope.currentData()
        text = self.datastream.text().strip()
        try:
            self.address.setText(redvypr_metadata.scope_address(text, scope) if (text or scope == 'all') else '')
            self.status.setText('')
        except Exception as e:
            self.address.setText('')
            self.status.setText(str(e))

    # --- result ---
    def values(self) -> dict:
        """address, key, value, valid_from, valid_until (None) and persistent of the entry."""
        return {'address': self.address.text().strip(), 'key': self.key.text().strip(),
                'value': self.text.toPlainText().strip(), 'valid_from': _pydt(self.valid_from.dateTime()),
                'valid_until': _pydt(self.valid_until.dateTime()) if self.use_until.isChecked() else None,
                'persistent': self.persistent.isChecked()}

    def problem(self) -> typing.Optional[str]:
        """What is wrong with the values, None if they are fine."""
        v = self.values()
        if not v['address']:
            return 'the metadata need an address: choose a datastream and a scope'
        try:
            RedvyprAddress(v['address'])
        except Exception as e:
            return f'address: {e}'
        if not v['key'] or "'" in v['key'] or '"' in v['key']:
            return 'the key must not be empty or contain quotes'
        if not v['value']:
            return 'the value is empty'
        if v['valid_until'] is not None and v['valid_until'] <= v['valid_from']:
            return '"until" must be later than "valid from"'
        return None

    def _accept_if_valid(self):
        p = self.problem()
        if p:
            self.status.setText(p)
            return
        self.accept()
