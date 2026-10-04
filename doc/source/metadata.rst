Metadata
========

Metadata describe data: the unit of a value, a description, the location of a
sensor, its serial number or the calibration in use. In redvypr metadata are
not part of every datapacket. They are kept in a central storage of the redvypr
instance and are attached to :ref:`redvypr addresses <design_addressing>`. Every
datastream that matches an address gets the metadata of that address.

The storage is part of ``deviceinfo_all`` and is distributed to all devices and
to connected redvypr instances. It is saved with the configuration, including
its history (see :ref:`metadata_config`).

The functions are in :mod:`redvypr.metadata`; the ``Redvypr`` object has the
methods ``add_metadata()``, ``get_metadata()`` and ``rem_metadata()``.


Adding and reading metadata
---------------------------

::

    import redvypr

    r = redvypr.Redvypr(hostname='lab')
    r.add_metadata('temp@d:ctd_01', {'unit': 'degC', 'description': 'Water temperature'})

    print(r.get_metadata('temp@d:ctd_01', mode='merge'))
    print(r.get_metadata('temp@d:ctd_01', mode='expanded'))

gives::

    {'unit': 'degC', 'description': 'Water temperature'}
    {"temp @ d:'ctd_01'": {'unit': 'degC', 'description': 'Water temperature'}}

``get_metadata()`` returns the metadata of all stored addresses that match the
query address. The modes are

``merge``
    one dictionary with all keys; more specific addresses (deeper datakeys)
    override less specific ones
``expanded``
    one dictionary per stored address
``all``
    the complete list of stored entries with their constraints (history),
    without filtering by time

A query with a datakey also finds metadata of an address without a datakey: an
entry at ``@d:ctd_01`` (e.g. the location) applies to all datakeys of ``ctd_01``.

Which stored addresses match a query:

* The entries of the query must not contradict the stored address:
  ``temp@d:ctd_02`` does not get the metadata of ``@d:ctd_01``.
* If the query names its source (``d`` device, ``di`` deviceid, ``si``
  sensorid or ``s`` sensor), every source entry of the stored address must be
  in the query with the same value. ``temp@d:ctd_01`` does not get the metadata
  of ``@di:A1B2C3``: it cannot be known that ``ctd_01`` is this device. Query
  with the deviceid (``temp@d:ctd_01 and di:A1B2C3``) to get both. The addresses
  offered by the datastream widget contain all source entries of a datastream.
* A query without a source (``@``, ``temp@``) gets the metadata of all sources.


Entries, validity and history
-----------------------------

Every metadata value is stored as an entry::

    {'key': 'unit', 'value': 'degC',
     'constraints': {'valid_from': '2026-01-01T00:00:00+00:00',
                     'valid_until': None,           # open: valid until changed
                     'hostinfo': {...},             # who set it
                     'site': 'lab'}}                # optional context, see below

An entry describes the **period** in which a value was valid. ``valid_from`` and
``valid_until`` are UTC times (``datetime``, ISO string with ``Z`` or
``+00:00``, or unix time). ``valid_until`` is exclusive: at the time of a change
the new value is valid. Without ``valid_from`` an entry set with
``add_metadata()`` is valid from the start of the redvypr instance; an entry from
a datapacket from the time of the packet.

Changing a value ends the old entry and keeps it as history::

    import datetime
    UTC = datetime.timezone.utc

    r.add_metadata('pres@d:ctd_01', {'unit': 'dbar'}, valid_from=datetime.datetime(2026, 1, 1, tzinfo=UTC))
    r.add_metadata('pres@d:ctd_01', {'unit': 'hPa'}, valid_from=datetime.datetime(2026, 6, 1, tzinfo=UTC))

    print(r.get_metadata('pres@d:ctd_01', mode='merge'))
    print(r.get_metadata('pres@d:ctd_01', mode='merge', at_time=datetime.datetime(2026, 3, 1, tzinfo=UTC)))
    for e in r.get_metadata('pres@d:ctd_01', mode='all'):
        print(e['key'], e['value'], e['constraints']['valid_from'], e['constraints'].get('valid_until'))

gives::

    {'unit': 'hPa'}
    {'unit': 'dbar'}
    unit dbar 2026-01-01T00:00:00+00:00 2026-06-01T00:00:00+00:00
    unit hPa 2026-06-01T00:00:00+00:00 None


Same metadata again: no new entry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Entries with the same key, value and context are the same metadata,
independent of their validity and of the host that set them. Setting them again
does not add an entry, so devices can send their metadata with every packet and
redvypr can be restarted without the storage growing::

    for i in range(3):
        r.add_metadata('pres@d:ctd_01', {'unit': 'hPa'})
    print(len(r.get_metadata('pres@d:ctd_01', mode='all')))   # still 2: dbar and hPa

The rules in detail (key and context equal):

=================================================  ===============================================
New entry                                          Result
=================================================  ===============================================
same value, periods overlap or touch               merged into the existing entry; its begin moves
                                                   back or its end forward if needed
same value, only ``valid_until`` differs           the existing entry is updated
same value after a gap (A -> B -> A)               new entry (history)
other value                                        the open entry ends at the begin of the new one
other value, older than an existing entry          the new entry ends at the begin of the later one
=================================================  ===============================================

The storage only grows when a value really changes, and a change is only
announced to the devices (``metadata_changed``) if the storage changed. Only
the entries of the same address are compared, not the whole storage.


Context
~~~~~~~

All constraints except ``valid_from``, ``valid_until`` and ``hostinfo`` are the
context of an entry. Entries of different contexts exist side by side; a query
selects them with ``context``::

    r.add_metadata('cond@d:ctd_01', {'calibration': 'cal_lab_2026'}, constraints={'site': 'lab'})
    r.add_metadata('cond@d:ctd_01', {'calibration': 'cal_field_2026'}, constraints={'site': 'field'})

    print(r.get_metadata('cond@d:ctd_01', mode='merge', context={'site': 'field'}))
    print(r.get_metadata('cond@d:ctd_01', mode='merge', context={'site': 'lab'}))

gives::

    {'calibration': 'cal_field_2026'}
    {'calibration': 'cal_lab_2026'}

A query without ``context`` gets the entries of all contexts; for the same key
the one stored last wins.


Removing metadata
~~~~~~~~~~~~~~~~~

``rem_metadata()`` deletes entries physically, including their history::

    r.rem_metadata('cond@d:ctd_01', metadata_keys=['calibration'])
    print(r.get_metadata('cond@d:ctd_01', mode='merge'))       # {}

Without ``metadata_keys`` all entries of the address are removed. With
``mode='matches'`` all stored addresses matching the given address are
affected.


Metadata sent by devices
------------------------

A device sends metadata inside its datapackets, in the field ``_metadata``.
redvypr takes them out when it distributes the packet.
:func:`redvypr.metadata.add_metadata2datapacket` adds them to a packet::

    import redvypr.metadata
    from redvypr.redvypr_datadict import create_redvypr_dict

    data = create_redvypr_dict(device='ctd_07', deviceid='A1B2C3', sensorid='SN-0007', packetid='info')
    data['temp'] = 12.3
    # metadata of the device, valid for all its datastreams
    redvypr.metadata.add_metadata2datapacket(data, address='@di:A1B2C3',
                                             metadict={'location': 'Kiel', 'sn': 'SN-0007'})
    # metadata of one datakey
    redvypr.metadata.add_metadata2datapacket(data, address='temp@di:A1B2C3', metadict={'unit': 'degC'})
    dataqueue.put(data)

Without ``valid_from`` the entries are valid from the time of the packet
(``data['_redvypr']['t']``). Sending the same metadata with every packet is
possible (see above), but sending them once and again on a change keeps the
packets small.

Several addresses at once, e.g. in a separate packet, are created with
:func:`redvypr.metadata.create_metadatapacket`::

    packet = redvypr.metadata.create_metadatapacket({'temp@d:ctd_01': {'unit': 'degC'},
                                                     'pres@d:ctd_01': {'unit': 'dbar'}},
                                                    device_info=device_info)
    dataqueue.put(packet)


Which address is stored
~~~~~~~~~~~~~~~~~~~~~~~

redvypr completes the address of metadata from a packet with information of the
packet, so that the metadata belong to the right source:

* An address that names its source itself, with ``d`` (device), ``di``
  (deviceid) or ``si`` (sensorid), only gets the UUID of the host. It is valid
  for **all** packets of this source, whatever their packetid. In the example
  above ``@di:A1B2C3`` is stored as ``@di:'A1B2C3' and u:'<uuid>'``: the location
  also applies to the packets ``i:raw`` or ``i:data`` of the same device, and it
  stays valid if the device name changes (e.g. after setting a new serial
  number).
* An address with only a datakey (e.g. ``add_metadata2datapacket(data,
  datakey='sine', ...)``) gets device, packetid and UUID of the packet:
  ``sine @ d:'ctd_07' and i:'raw' and u:'<uuid>'``.

For devices with a constant hardware ID it is therefore recommended to put it
into ``deviceid`` of the packets (``create_redvypr_dict(deviceid=...)``) and to
attach the metadata to ``@di:<id>``. The device name can then be readable and
may change.


.. _metadata_config:

Metadata in the configuration file
----------------------------------

``Redvypr.save_config()`` saves the stored entries with their history and
constraints under ``metadata``; they are loaded again at startup with this
configuration and by ``load_config(fname, use_metadata=True)``. Loading the same
file twice does not add entries.

Metadata can also be written by hand in a simple form, one dictionary of
key/value pairs per address. They are valid from the start of redvypr::

    metadata:
      "temp@d:ctd_01":
        unit: degC
        description: Water temperature
      "@di:A1B2C3":
        location: Kiel

Both forms can be mixed. ``Redvypr.set_metadata_from_dict()`` accepts the same
dictionary at runtime.


Queries with time ranges
------------------------

``at_time`` returns the metadata valid at one time. ``time_range=(start,
end)`` considers all entries valid at some point within the range; since
``merge`` and ``expanded`` return one value per key, the last of them is
returned. For the complete history within a range use ``mode='all'`` and filter
the entries by their ``valid_from``/``valid_until``.


Performance
-----------

Adding metadata only looks at the entries of one address and takes about 1 ms,
independent of the size of the storage. A query tests the stored addresses
against the query address; the parsed addresses are cached and addresses of
other sources are skipped early, so a query of one datastream takes about 0.4 ms
for 10, 2 ms for 1000 and 7 ms for 5000 stored addresses.
``Redvypr.get_metadata()`` copies only the metadata (not the whole
``deviceinfo_all``). Widgets that ask for metadata periodically (e.g. the unit
of a plot line) should do so in intervals of seconds, not for every packet.
