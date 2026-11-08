.. _design_items:

Design note: items (sensors, boards, parts) in the metadata
===========================================================

Status 2026-11-08, not implemented yet. Goal: information about physical
things (a logger, an add-on board, a sensor, a cable, a housing) is kept in
the redvypr metadata, with history. The state of a measurement setup at any
time (which sensor was on which channel) is derived from these metadata, not
stored a second time. Generic for all redvypr devices; the norlog ADC is the
first user (NTC calibration with the measured reference resistor of an add-on
board).


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
* **norlog setup profiles** (``devices/norlog/adc_setups.py``): templates of
  an ADC sequence with channel calibration presets, defined in code; the
  device reports the name of its profile (``setup``).
* **Widgets**: ``RedvyprMetadataTable`` (generic table of metadata entries)
  and ``pydantic_config_widget`` (forms generated from pydantic models).


Items
-----

An item is a thing information is kept about. Its properties are the
metadata entries at its address, every field with its own validity period.

Address
~~~~~~~

::

    @i:'item' and d:'<itemtype>' and si:'<id>'

e.g. ``@i:'item' and d:'breakout_v01' and si:'BO-003'``. ``i:'item'`` keeps
items apart from data sources (a device called like an item type gets no item
metadata) and allows to list all items with the query ``@i:'item'``. The
item reference used elsewhere is the short form ``<itemtype>/<id>``
(``breakout_v01/BO-003``). The id is the serial number of a physical item or
the name of a template (see setup profiles).

Ids are **unique per item type** (``d`` together with ``si``):
``ntc_sensor/0042`` and ``fp07/0042`` are different items. This fits the
serial numbers of manufacturers, which are mostly unique per product only.
In addition every item may have an optional globally unique ``uuid`` (field
of ``Item``, created on request in the GUI, e.g. for a label or QR code).
References use ``<itemtype>/<id>``; a lookup by ``uuid`` is possible as
well.

One key per field
~~~~~~~~~~~~~~~~~

Every field of an item is its own metadata key, not one key with the whole
model as today in the sensor manager. A new value of one field (R1 measured
again) ends only that entry; the other fields keep their history. The item at
time t is ``get_metadata(item_address, mode='merge', at_time=t)``, validated
into its model.

Values with a unit are stored as a small quantity dictionary::

    R1: {value: 10002.7, unit: Ohm, uncertainty: 0.5, method: "4-wire", date: 2026-11-10}

Item types
~~~~~~~~~~

An item type is a pydantic model with ``model_config = ConfigDict(extra='allow')``:

* ``Item`` (generic): ``itemtype``, ``id``, ``uuid`` (optional), ``name``, ``description``,
  ``manufacturer``, ``mpn``, ``batch``, ``order`` (supplier, number, date),
  ``parent``, ``slot``, ``status``, ``attachments``, ``comment``. Works for
  any device without code; unknown fields are kept.
* Specific types derive from ``Item`` and add fields with validation, e.g.
  ``norlog_v02`` (``deviceid`` = hardware ID), ``breakout_v01`` with ``R1`` (quantity),
  ``ntc_sensor`` with ``r25``, ``beta``, ``dissipation_constant``.

Types register in a registry (like ``SensorFactory``); devices bring their own
types (the norlog module brings ``norlog_v02``, ``breakout_v01``, ``setup``).
The GUI uses the specific model if the type is known, otherwise ``Item``.

Revisions of item types
~~~~~~~~~~~~~~~~~~~~~~~

Item types change: later a further parameter of a sensor type is wanted, a
field is renamed or gets another unit. Every item type therefore has a
**revision** (``ClassVar`` of the model, an integer counted up with every
change of the type), and every item stores the revision of the type it was
written with (key ``type_revision``).

* A new optional field needs no migration: older items simply do not have the
  key (default ``None``); the revision is counted up anyway, so it is
  documented which items were written before the field existed.
* A renamed field or a changed meaning gets a **migration function** of the
  type (``migrate(entries, from_revision)``); items of an older revision are
  migrated when read, and written with the new revision when they are saved
  the next time (new entries from that time on, the history stays).
* An item of a revision newer than the code knows is shown and kept
  unchanged (``extra='allow'``), with a warning; it is not written back.

Not to be confused with the hardware revision of a thing (breakout v01
rev B): that is a normal field (``hw_revision``) of the item, or a new item
type if the boards differ in function.


The tree: parent and slot
-------------------------

Every item says itself where it sits:

* ``parent``: item reference of the item it is mounted on or connected to,
* ``slot``: where on the parent (free string).

Children are not stored in the parent; they are found with the query "all
items with ``parent`` = X". A rebuild is one new ``parent``/``slot`` entry at
the moved item; the old entry ends, so the history shows where the item was
when.

The tree is kept **in redvypr only**: a rebuild is entered in the Items
window (or another redvypr GUI), with the time of the rebuild. The devices do
not store or detect their add-on boards. Later extensions, if boards are often
swapped without a PC: the device stores the id of its board like ``setup``
(e.g. ``board=BO-003``, reported in ``extinfo`` and the configuration
packet, so redvypr can check or create the ``parent`` entry), or detects it
with an id chip on the board. Example::

    norlog_v02/N-012          deviceid: 0xA1B2...
     +- breakout_v01/BO-003   parent: norlog_v02/N-012   R1: 10002.7 Ohm
         +- ntc_sensor/0042   parent: breakout_v01/BO-003, slot: ntc0
         +- hf_sensor/HF-17   parent: breakout_v01/BO-003, slot: hf0

The slot is free: the channel name (``ntc0``) is the simplest case and needs
nothing else. Who wants the terminals uses them (``J2.3-4``) and a setup
profile that translates them into channels (below).

Connection to the data source
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The root of a tree is the item of the device that sends the data. It names
the data source with the fields ``deviceid``, ``sensorid`` or ``device`` of
``Item``, named like the standard address entries of its packets (``di``,
``si``, ``d``). For a norlog ``deviceid`` is its hardware ID (``hwid``).
Thus redvypr finds the tree of ``ntc0 @ i:'adc_brd' and di:'0xA1B2...'``.


Setup profiles as items
-----------------------

A setup profile is an item of type ``setup`` with its name as id. It is a
template, not a physical thing, and optional::

    setup/hf_ntc_v01
        board_type: breakout_v01
        sequence: "on=1,sps=5,filter=sinc3,...;hf0,0,1,128,..."
        channels:
          ntc0: {slot: J2.3-4, cal: ntc, unit: degC, scale: 10000}
          hf0:  {slot: J2.1-2, cal: poly, unit: W/m2}

The device reports the name of its profile (norlog: ``setup`` in
``extinfo`` and in the configuration packet 50010, with history on the SD
card); redvypr looks up the item ``setup/<name>``. The profiles of
``adc_setups.py`` become items of a library file; new profiles can then be
made and shared without a change of the code. The ADC tab keeps "Load
profile", now from the items.


Resolving a channel
-------------------

The items of a datastream at time t, e.g. ``ntc0`` of norlog 0xA1B2...:

1. the device item whose ``deviceid``/``sensorid``/``device`` matches the
   source of the address, valid at t;
2. its children and their children (``parent``), valid at t;
3. the item whose ``slot`` equals the datakey (``ntc0``; ``ntc0_raw`` is tried
   as ``ntc0`` too) is the sensor of the
   channel; its parent is the board;
4. if none: the setup profile of the device at t translates the slot of the
   items (``J2.3-4``) into the channel;
5. exception: a key ``items`` (role -> item reference) at the data address
   itself overrides the tree. For devices without a tree, e.g. a serial device
   with one sensor (``temp@d:'ctd_01'``: ``items: {sensor: sbe3/1234}``).

A new function returns the result::

    redvypr.metadata.get_items(storage, address, at_time) -> {role: item model}

with the roles ``device``, ``board``, ``sensor`` (and further parents).
``Redvypr`` and ``DbReader`` get a method of the same name, so live data and
stored data are resolved the same way. Nothing of this is stored a second
time; the state at any time follows from the history of the entries.


Calibrations with item parameters
---------------------------------

A calibration may take a parameter from an item instead of a fixed number::

    calibration ntc, sn 0042: coeffs [...], scale: {item: board, key: R1}

When the calibration is applied to ``adc_brd.ntc0`` at time t, ``scale`` is
taken from the board of that channel at time t. The sensor calibration
(R -> T) stays with the sensor; the board parameter (x -> R) with the board.
Moving the sensor to another board is a new ``parent``, not a new
calibration; data before the move are still evaluated with the old board.

Calibrations stay where they are (sensor manager, files); they are found by
the id of the sensor item.


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


Metadata from several sources
-----------------------------

Metadata come from several places: the running instance (configuration,
devices, connected instances), the item library file(s), and every database
(SQLite files, Timescale), which holds the metadata known when the data were
written. Today a ``DbReader`` uses only the metadata of its own database, so
a later correction (R1 measured in December with ``valid_from`` = production
of the board) never reaches the data of November.

Rules:

1. **One main source per kind of information.** Items, tree and profiles: the
   item library (or, for a team, one central database chosen instead).
   Information a device reports itself (firmware, ``setup``, hwid): the
   device, via its packets. Free metadata of a measurement (location,
   comment): the configuration. Databases are never the main source; they
   keep what was known at the time of the measurement.
2. **Merge, do not replace.** Data are evaluated with the snapshot of their
   database plus the current library and instance. The merge rules of the
   storage already join equal entries and fit later corrections with their
   own validity into the history.
3. **Precedence for real conflicts** (same address, key and context,
   overlapping time, other value): for items library > instance > database;
   for metadata reported by a device the device wins. Configurable.
4. **Provenance.** Every entry gets ``source`` (e.g.
   ``library:items.yaml@<git commit>``, ``db:nov.sqlite``,
   ``device:norlog_0xA1B2``). It is not part of the context (added to
   ``NON_CONTEXT_KEYS`` like ``hostinfo``), so equal entries of different
   sources are still merged; the sources of a merged entry are kept as a
   list.
5. **Conflicts are shown** in the Items and metadata windows with both values
   and their sources; they are resolved in the main source.
6. **Databases are not changed afterwards.** A data file keeps its snapshot;
   an export with the merged metadata gives a self-contained file if needed.

Implementation: a **metadata view over several sources** (instance, library
files, one or more databases) that applies these rules;
``DbReader.get_metadata()``, ``get_items()`` and the calibration read through
it instead of only their own database.


GUI
---

* **Items** (in the redvypr main window, next to the metadata table): tree of
  the items by ``parent`` (with a time slider or date to see an earlier
  state), list and filter by type, form of the selected item from its model
  (``pydantic_config_widget``), history per field (``mode='all'``), "new
  value from date", "move to" (new parent/slot from date), attachments, new
  item from a type or as copy, import/export of the library file.
* **Datastream**: context menu of a datastream in the address widget shows
  the resolved items and allows the exception ``items``.
* **norlog ADC tab**: per channel the resolved sensor and board; profile
  selection from the ``setup`` items.
* **Calibration**: shows the items and the parameters used for a channel.


Migration
---------

* ``BaseSensor`` of the sensor manager becomes an item type
  (``sensortype`` = ``itemtype``), its address changes to the item address,
  one key per field. Reading the old addresses (``@i:sensor and sn==...``,
  one key ``sensor``) stays possible and converts them. ``BaseSensor`` is
  used only inside the sensor and calibration manager
  (``sensor_and_calibration_definitions.py``,
  ``sensor_calibration_manager.py``), so the change stays local.
  **Decided 2026-11-08:** this way (option 1); the alternatives (keeping both
  systems side by side, or items referring to ``BaseSensor`` entries) were
  rejected because sensors would then be kept in two places.
* norlog: the profiles of ``adc_setups.py`` become ``setup`` items in a
  library file shipped with redvypr; the code keeps them as fallback until
  then.


Steps
-----

1. **Done** (``redvypr/items.py``, ``test/test_items.py``, methods of ``Redvypr``
   and ``DbReader.get_items()``; setup profiles still missing in the
   resolution): ``Item`` model with type revisions and migrations, registry, item
   address, writing/reading items (one key per field), ``parent``/``slot``,
   ``get_items()`` with the tree and the exception ``items``; tests.
2. **Done** (``redvypr/metadata_sources.py``, ``test/test_metadata_sources.py``;
   item libraries in the configuration ``item_libraries``, loaded into the
   instance; ``DbReader`` merges its database with the instance): Metadata view over several sources with ``source``, precedence and
   conflicts; ``DbReader`` reads through it.
3. Items widget: tree, form, history, move, library file.
4. Calibration parameter from an item (``scale`` of the NTC calibration);
   norlog item types (``norlog_v02``, ``breakout_v01``),
   resolved items in the ADC tab.
5. Setup profiles as ``setup`` items, translation of terminal slots.
6. Migration of ``BaseSensor``.


Open points
-----------

* Decided 2026-11-08: ids unique per item type with optional ``uuid``; the
  tree is kept in redvypr only (devices do not store their boards).
* Several redvypr instances changing the same item: the merge rules keep both
  values with their times; the later ``valid_from`` wins.
* Slot names: free strings; conventions per device type (channel names or
  connector pins) are documented with the item types.
