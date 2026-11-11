"""Notes: persistent metadata entries found without the filters naming the run of their host."""

import datetime

import pytest
import yaml

import redvypr
from redvypr import metadata as md
from redvypr.redvypr import RedvyprConfig

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
T1 = datetime.datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
T2 = datetime.datetime(2026, 11, 12, 16, 0, tzinfo=UTC)

RUN1 = "sine @ d:'test_device' and i:'test_device' and u:'RUN1' and h:'laptop1'"
RUN2 = "sine @ d:'test_device' and i:'test_device' and u:'RUN2' and h:'laptop1'"
OTHER_HOST = "sine @ d:'test_device' and i:'test_device' and u:'RUN9' and h:'laptop2'"
OTHER_CHANNEL = "sine_rand @ d:'test_device' and i:'test_device' and u:'RUN2' and h:'laptop1'"


def storage_with(address, entries):
    s = {}
    for key, value, constraints, t in entries:
        md.add_metadata_to_entries(md.create_metadata_dict(address, {key: value}, constraints=constraints,
                                                           valid_from=t), s)
    return {'metadata': s}


def test_persistent_entry_is_found_without_the_run_filters():
    # written in run 1 with the full address; read with the address of run 2
    s = storage_with(RUN1, [('note', 'sensor cleaned', {'persistent': True}, T0),
                            ('unit', 'degC', None, T0)])
    at = T1
    got = md.get_metadata(s, address=RUN2, at_time=at)
    assert got == {RUN1: {'note': 'sensor cleaned'}}            # the note; the unit is of run 1 only
    assert md.get_metadata(s, address=RUN1, at_time=at) == {RUN1: {'note': 'sensor cleaned', 'unit': 'degC'}}
    # the name of the host stays a filter, the channel too
    assert md.get_metadata(s, address=OTHER_HOST, at_time=at) == {}
    assert md.get_metadata(s, address=OTHER_CHANNEL, at_time=at) == {}
    # a query without run filters finds both (as before)
    assert md.get_metadata(s, address="sine @ d:'test_device'", at_time=at) == {RUN1: {'note': 'sensor cleaned',
                                                                                    'unit': 'degC'}}
    # modes 'all' and 'merge'
    assert [e['key'] for e in md.get_metadata(s, address=RUN2, mode='all')] == ['note']
    assert md.get_metadata(s, address=RUN2, mode='merge', at_time=at) == {'note': 'sensor cleaned'}


def test_without_the_mark_the_run_filter_decides():
    s = storage_with(RUN1, [('unit', 'degC', None, T0)])
    assert md.get_metadata(s, address=RUN2, at_time=T1) == {}


def test_persistent_is_not_a_context_and_time_still_applies():
    assert 'persistent' in md.NON_CONTEXT_KEYS
    s = storage_with(RUN1, [('note', 'a', {'persistent': True}, T0), ('note', 'b', {'persistent': True}, T1)])
    # the same key: the new note ends the old one at its begin
    assert md.get_metadata(s, address=RUN2, at_time=datetime.datetime(2026, 11, 12, 10, 0, tzinfo=UTC)) == \
        {RUN1: {'note': 'a'}}
    assert md.get_metadata(s, address=RUN2, at_time=T2) == {RUN1: {'note': 'b'}}
    assert md.get_metadata(s, address=RUN2, at_time=datetime.datetime(2026, 11, 12, 7, 0, tzinfo=UTC)) == {}


def test_note_addresses_of_the_scopes():
    ds = RUN2
    assert md.note_address(ds, 'all') == '@'
    assert md.note_address(ds, 'host') == "@h:'laptop1'"
    assert md.note_address(ds, 'device') == "@d:'test_device' and h:'laptop1'"
    assert md.note_address(ds, 'channel') == "sine @ d:'test_device' and h:'laptop1'"
    assert md.note_address("temp @ di:'A1B2' and h:'logger'", 'device') == "@di:'A1B2' and h:'logger'"
    with pytest.raises(ValueError):
        md.note_address("@d:'x' and h:'y'", 'channel')              # no datakey
    with pytest.raises(ValueError):
        md.note_address('sine', 'device')                           # no host or device
    with pytest.raises(ValueError):
        md.note_address(ds, 'everything')
    # a note at the address of its scope applies to the stream of every run
    s = storage_with(md.note_address(RUN1, 'device'), [('location', 'lab', {'persistent': True}, T0)])
    assert md.get_metadata(s, address=RUN2, mode='merge', at_time=T1) == {'location': 'lab'}
    assert md.get_metadata(s, address=OTHER_HOST, mode='merge', at_time=T1) == {}
    # the host note applies to all devices of that host, not to another host
    s = storage_with(md.note_address(RUN1, 'host'), [('user', 'P. H.', {'persistent': True}, T0)])
    assert md.get_metadata(s, address=OTHER_CHANNEL, mode='merge', at_time=T1) == {'user': 'P. H.'}
    assert md.get_metadata(s, address=OTHER_HOST, mode='merge', at_time=T1) == {}


def test_add_note_and_it_survives_a_restart_from_the_configuration(tmp_path):
    r = redvypr.Redvypr(hostname='notes1')
    addr = md.note_address(f"sine @ d:'test_device' and u:'{r.hostinfo['uuid']}' and h:'notes1'", 'channel')
    r.add_note(addr, 'sensor cleaned', valid_from=T0)
    r.add_note(addr, 'raining', key='note_weather', valid_from=T0, valid_until=T1)
    entries = r._copy_metadata()[addr]
    assert {e['key']: e['constraints']['persistent'] for e in entries} == {'note': True, 'note_weather': True}
    cfg = str(tmp_path / 'cfg.yaml')
    r.save_config(fname=cfg)
    r2 = redvypr.Redvypr(hostname='notes1', config=RedvyprConfig(**yaml.safe_load(open(cfg, encoding='utf-8'))))
    assert r2.hostinfo['uuid'] != r.hostinfo['uuid']                # another run
    q = f"sine @ d:'test_device' and u:'{r2.hostinfo['uuid']}' and h:'notes1'"
    assert r2.get_metadata(address=q, mode='merge', at_time=datetime.datetime(2026, 11, 12, 10, tzinfo=UTC)) == \
        {'note': 'sensor cleaned', 'note_weather': 'raining'}
    assert r2.get_metadata(address=q, mode='merge', at_time=T2) == {'note': 'sensor cleaned'}      # weather ended


def test_note_dialog_and_metadata_window(tmp_path):
    from PyQt6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from redvypr.widgets.redvypr_note_dialog import NoteDialog
    from redvypr.widgets.redvypr_metadata_window import RedvyprMetadataWindow
    r = redvypr.Redvypr(hostname='notes2')
    d = NoteDialog(r, datastream=RUN1)
    assert d.address.text() == "@d:'test_device' and h:'laptop1'"              # default scope: device
    d.scope.setCurrentIndex(md.NOTE_SCOPES.index('channel'))
    assert d.address.text() == "sine @ d:'test_device' and h:'laptop1'"
    d.scope.setCurrentIndex(0)
    assert d.address.text() == '@'
    d.scope.setCurrentIndex(1)
    assert d.address.text() == "@h:'laptop1'"
    # checks
    assert 'empty' in d.problem()
    d.text.setPlainText('sensor cleaned')
    assert d.problem() is None
    d.use_until.setChecked(True)
    d.valid_until.setDateTime(d.valid_from.dateTime().addSecs(-60))
    assert 'later' in d.problem()
    d.valid_until.setDateTime(d.valid_from.dateTime().addSecs(3600))
    assert d.problem() is None and d.values()['valid_until'] > d.values()['valid_from']
    d.address.setText("sine @ d:'x' and h:'y'")
    d._manual_address = True
    d.scope.setCurrentIndex(3)
    assert d.address.text() == "sine @ d:'x' and h:'y'"                          # an edited address stays
    d.address.setText('')
    assert 'address' in d.problem()
    d.close()
    # the window adds the note (without the dialog: values given)
    w = RedvyprMetadataWindow(redvypr_instance=r)
    assert w.btn_note.text() == 'Add note ...'
    values = {'address': "@h:'notes2'", 'key': 'user', 'text': 'P. Holtermann',
              'valid_from': T0, 'valid_until': None}
    assert w.add_note(values) == values
    assert r.get_metadata(address="sine @ d:'t' and u:'other-run' and h:'notes2'", mode='merge', at_time=T1) == \
        {'user': 'P. Holtermann'}
    assert 'note added' in w.status.text()
    w.close()
