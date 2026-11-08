.. _design_items:

Design note: items (sensors, boards, parts) in the metadata
===========================================================

Status 2026-11-08, not implemented yet. Goal: information about physical
things (a sensor, an add-on board, a cable, a part on a board) is kept in the
redvypr metadata, with history, and data streams refer to the things they were
measured with. Generic for all redvypr devices; the norlog ADC is the first
user (NTC calibration with the measured reference resistor of an add-on board).


Existing pieces
---------------

* **Metadata storage** (:doc:`metadata`): entries per address with
  ``valid_from``/``valid_until`` (open end = valid until changed), history,
  context. Kept in ``deviceinfo_all['metadata']``, distributed to the devices
  and to connected redvypr instances, saved with the configuration (with
  history) and written into the databases by the SQLite/Timescale writers
  (table ``redvypr_metadata``); ``DbReader.get_metadata()`` reads them at the
  time of the data. Metadata added with ``Redvypr.add_metadata()`` keep their
  address as given (no UUID of the host), so they are portable between
  instances. Metadata from datapackets with ``d``/``di``/``si`` in the address
  get the UUID of the host.
* **Sensor and calibration manager**
  (``devices/sensors/calibration``): pydantic models ``BaseSensor``
  (``sensortype`` discriminator, ``sn``, ``attachments``,
  ``calibration_uuids``) and calibrations, stored as one metadata key
  (``sensor`` or ``calibration``) holding the whole model, at addresses like
  ``@i:sensor and sn=='...' and sensortype=='...'``.
* **Widgets**: ``RedvyprMetadataTable`` (generic table of metadata entries)
  and ``pydantic_config_widget`` (forms generated from pydantic models).


Three kinds of information
--------------------------

============  ==================================================  ======================
Kind          Example                                             Changes
============  ==================================================  ======================
Item          breakout BO-003: R1 measured 10002.7 Ohm, MPN,      rarely; history kept
              batch, order; NTC 0042: type, batch
Assignment    norlog X, channel ``adc_brd.ntc0``: board BO-003,   on every rebuild
              sensor ntc/0042, from 2026-11-10
Calibration   NTC 0042: Steinhart-Hart coefficients (R -> T)      after a calibration
============  ==================================================  ======================

All three are metadata; they are tied together by item references.


Items
-----

Address
~~~~~~~

An item is addressed with the standard source entries, marked as item by
the packetid::

    @i:'item' and d:'<itemtype>' and si:'<serial number>'

e.g. ``@i:'item' and d:'breakout_v01' and si:'BO-003'``. ``i:'item'`` keeps
items apart from data sources (a device called like an item type gets no item
metadata) and allows to list all items with the query ``@i:'item'``. The
item reference used elsewhere is the short form ``<itemtype>/<sn>``
(``breakout_v01/BO-003``).

One key per field
~~~~~~~~~~~~~~~~~

Every field of an item is its own metadata key, not one key with the whole
model as today in the sensor manager. A new value of one field (R1 measured
again) ends only that entry; the other fields keep their history. The item at
time t is ``get_metadata(item_address, mode='merge', at_time=t)``, validated
into its model.

Values with a unit are stored as a small quantity dictionary::

    R1: {value: 10002.7, unit: Ohm, uncertainty: 0.5, method: "4-wire, Keithley 2000", date: 2026-11-10}

Item types
~~~~~~~~~~

An item type is a pydantic model with ``model_config = ConfigDict(extra='allow')``:

* ``Item`` (generic): ``itemtype``, ``sn``, ``name``, ``description``,
  ``manufacturer``, ``mpn``, ``batch``, ``order`` (supplier, number, date),
  ``parent`` (item reference, e.g. the board a part sits on), ``attachments``,
  ``comment``. Works for any device without code; unknown fields are kept.
* Specific types derive from ``Item`` and add fields with validation, e.g.
  ``breakout_v01`` with ``R1`` (quantity) and its channels, ``ntc_sensor``
  with ``r25``, ``beta``, ``dissipation_constant``.

Types register in a registry (like ``SensorFactory``); devices bring their own
types (the norlog module brings ``breakout_v01``). The GUI uses the specific
model if the type is known, otherwise ``Item``.


Assignments
-----------

A data address refers to items with the key ``items``, a dictionary role ->
item reference::

    "ntc0 @ i:'adc_brd' and di:'<hwid>'":
        items: {sensor: ntc_sensor/0042, board: breakout_v01/BO-003}

valid from the time of the rebuild, open end. Roles are free strings; usual
ones are ``sensor``, ``board``, ``cable``. An address without datakey assigns
items to all datakeys of a source (``@di:'<hwid>'``: the norlog is in housing
H-07). Items may refer to items with ``parent``.

Resolution
~~~~~~~~~~

A new function resolves the items of a data address at a time::

    redvypr.metadata.get_items(storage, address, at_time) -> {role: item model}

It reads ``items`` of the address (merged, at ``at_time``) and the metadata of
each referenced item at the same time. ``Redvypr`` and ``DbReader`` get a
method of the same name, so live data and stored data are resolved the same
way.


Calibrations with item parameters
---------------------------------

A calibration may take a parameter from an item instead of a fixed number::

    calibration ntc, sn 0042: coeffs [...], scale: {item: board, key: R1}

When the calibration is applied to ``adc_brd.ntc0`` at time t, ``scale`` is
taken from the item in role ``board`` of that address at time t. The sensor
calibration (R -> T) stays with the sensor; the board parameter
(x -> R) with the board. Moving the sensor to another board needs a new
assignment, not a new calibration; data before the move are still evaluated
with the old board.

Calibrations stay where they are (sensor manager, files); they are found by
the ``sn`` of the item in role ``sensor``.


Storage and exchange
--------------------

* The items live in the metadata storage like all metadata; they are saved
  with the configuration and written into the databases, so every data file
  carries the items valid for its data.
* In addition an **item library file** (YAML, simple or storage format of
  ``save_config``) with only the entries of ``@i:'item'``, for a git
  repository shared by several computers. Load and save from the GUI;
  loading the same file again adds nothing (merge rules of the storage).
* Removing an item deletes its history; normally an item gets
  ``status: retired`` instead.


GUI
---

* **Items** (in the redvypr main window, next to the metadata table): list of
  all items (type, sn, name, status), filter by type, form of the selected
  item from its model (``pydantic_config_widget``), history per field
  (``mode='all'``), "new value from date", attachments, new item from a type
  or as copy, import/export of the library file.
* **Assign items** (context menu of a datastream in the address widget):
  roles and items of the address, from date. Devices can show the same dialog
  where it fits, e.g. the norlog ADC tab per channel.
* **Calibration**: shows the items and the parameters used for a channel.


Migration of the sensor manager
-------------------------------

``BaseSensor`` becomes an item type (``sensortype`` = ``itemtype``), its
address changes to the item address, one key per field. Reading the old
addresses (``@i:sensor and sn==...``, one key ``sensor``) stays possible and
converts them. To be decided with the author of the sensor manager.


Steps
-----

1. ``Item`` model, registry, item address and functions to write/read items
   (one key per field), ``get_items()``; tests.
2. Items widget with form, history and library file.
3. Assignment dialog in the address widget; ``items`` key.
4. Calibration parameter from an item (``scale`` of the NTC calibration);
   norlog: ``breakout_v01`` type, assignment in the ADC tab.
5. Migration of ``BaseSensor``.


Open points
-----------

* Serial numbers: unique per item type (``si`` together with ``d``), or
  globally unique (e.g. inventory numbers)?
* Should an assignment also be stored in the device (norlog: board serial
  number next to ``setup``), so that it is known without a PC?
* Several redvypr instances changing the same item: the merge rules keep both
  values with their times; the later ``valid_from`` wins.
