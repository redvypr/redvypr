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


Conversion into units
---------------------

The calibrations (sensor manager: ``CalibrationNTC``, ``CalibrationPoly``,
...) convert with ``raw2data()`` from ``unit_input`` into ``unit``. With
items a value of a channel is converted in two stages that belong to
different things:

==========================  ===========================  ==============================
Stage                       Belongs to                   Source
==========================  ===========================  ==============================
1. measuring circuit:       the board / the setup        setup profile of the channel:
   x = R/R_ref -> R = x*R1                               ``scale_ref`` (item parameter,
                                                         e.g. ``R1`` of the board) or
                                                         ``scale`` (number)
2. sensor: R -> T           the sensor                   calibration with ``sn`` = id of
                                                         the sensor item, ``raw2data()``
==========================  ===========================  ==============================

The sensor calibration does not contain R_ref: moving the sensor changes
stage 1, not stage 2. A sensor without measuring circuit (heat flux sensor in
V) has no stage 1 (scale 1).

For a value of a channel at time t:

1. ``get_items(address, t)``: sensor, board, setup profile;
2. input = raw * scale of the channel (``scale_ref`` of the profile channel
   resolved with the items, else its ``scale``, else 1);
3. calibration: of all calibrations with ``sn`` = id of the sensor, the
   latest with a date before t (if several channels: the one whose
   ``channel`` datakey is the datakey of the data, ``ntc0_raw`` -> ``ntc0``);
4. value = ``calibration.raw2data(input)`` with the unit of the calibration.

Calibrations stay objects of their own (sensor manager, metadata at
``@i:calibration``, files), chosen by date, not fields of the sensor item: a
sensor has several calibrations over the years.

Templates in code: device modules can register **built-in items**
(``redvypr.items.register_builtin_item()``), e.g. the built-in setup profiles
of the norlog. ``get_item()`` returns them if the storage has no item of that
reference; an item in the storage wins.

Where it runs: when the data are evaluated (from a database: always with the
current items and calibrations, also for older data; the raw data stay
unchanged) and live in a processing device (later). Both use the same
function ``apply_calibration()``; for a time series ``calibrate_series()``
splits the data where items, assignments or calibrations change.

For the norlog NTCs the conversion can then be done in redvypr instead of on
the device: from the value ``ntc0`` (= x) with R1 of the board and the
calibration of the sensor; both may run side by side for a comparison.

**Implemented** (2026-11-08): ``redvypr/devices/sensors/calibration/item_calibration.py``
with ``apply_calibration()``, ``calibrate_series()``, ``get_data_calibrated()``
(for a ``DbReader``), ``select_calibration()``, ``calibrations_from_metadata()``;
``redvypr.items.register_builtin_item()``; the norlog module registers its
built-in profiles as built-in ``setup`` items. Tests in
``test/test_item_calibration.py``. Not yet: the live processing device and a
choice "converted with items" in the plots.


Performance: item index (planned)
---------------------------------

Status 2026-11-08: direct lookups and defaults implemented (below); the
index itself is a concept (no performance problem yet).

The present implementation is simple: ``get_items()`` lists all items at
the time (``list_items()``) to build the tree, and every item is read with a
normal metadata query, which tests every stored address. The cost grows with
items x addresses. Measured (per device a logger, a board and four NTCs, each
NTC moved three times, plus other metadata):

=====  =================  =====================
Items  Addresses (total)  one ``get_items()``
=====  =================  =====================
60     260                17 ms
300    1300               290 ms
600    2600               1050 ms
=====  =================  =====================

``calibrate_series()`` does this once per part of the series.

That an item only names its parent is not the problem: the other direction is
built once as an index instead of being searched in every query.

**Item index** per state of the metadata:

* one pass over the storage: the item addresses are parsed once; every item
  reads only the entries at its own address (``storage[address]``), no
  search over all addresses;
* children index with times: ``parent -> [(child, valid_from, valid_until)]``
  from the ``parent`` entries; the children at time t without touching all
  items;
* source index: ``deviceid``/``sensorid``/``device`` -> item, with times;
* ``get_items()`` then needs the device, its subtree and the slot: the cost
  depends on the size of that one tree, not on the number of all items
  (expected well below 1 ms per query, also with thousands of items).

**Defaults for items (implemented):** an entry at ``@i:'item' and
d:'ntc_sensor'`` (e.g. ``manufacturer``) applies to all items of that type,
one at ``@i:'item'`` to all items. ``get_item()`` reads these two forms and
its own address directly (``item_keys()``: one pass over the address
strings, whose parsing is cached, finds the item addresses in any spelling):
all items, then the type, then the item itself; the more specific wins. An
item exists only if its own address has entries at the time. Other patterns
(e.g. addresses with content filters that happen to match items) do not apply
to items.

With these direct lookups (no search over all addresses per item) the same
measurement gives 1.5 ms (60 items), 6.4 ms (300) and 14 ms (600 items, 2600
addresses): linear in the number of items, because ``get_items()`` still
reads all items at the time. The index below removes that as well.

**Built, not stored:** the index is derived data and lives in memory only.
It is built at the first use after reading and dropped when the metadata
change: in redvypr after ``metadata_changed``, in the ``DbReader`` together
with the merged metadata (cached 2 s), in ``calibrate_series()`` once for the
whole series. Storing it is not done: it would duplicate the metadata (two
truths, e.g. after a change of the item library in git or with another
database) and it depends on the combination of sources (instance, libraries,
database with precedence). Building it costs about one pass over the item
entries, i.e. about as much as reading the metadata.

Only for very large stocks in a shared database (Timescale, tens of thousands
of items) the relations could be kept as a table of the database (parent,
child, from, until) with a database index and queried there; only if
building the index in memory turns out to be too slow.

The measurement above becomes a test with a time limit when the index is
implemented.


Storage and exchange
--------------------

* The items live in the metadata storage like all metadata; they are saved
  with the configuration and written into the databases, so every data file
  carries the items valid for its data.
* In addition an **item library file** (YAML, simple or storage format of
  ``save_config``) with only the entries of ``@i:'item'``, for a git
  repository shared by several computers. Load and save from the GUI;
  loading the same file again adds nothing (merge rules of the storage).
  The library can also be an **SQLite file** (suffix ``.sqlite``,
  ``.sqlite3``, ``.db``, e.g. ``inventory.sqlite``): the item addresses in
  the table ``redvypr_metadata`` (the format of the databases written by
  redvypr, so a database reader sees them too); saving replaces only the
  item addresses, other metadata and tables of the file stay.
* **Several library files** can be loaded at once, e.g. a git repository
  ``inventory_redvypr`` with ``inventory_norlog.yaml`` (items) and
  ``calibrations.yaml``. A library holds items and calibrations (the
  entries with the key ``calibration``, e.g. of the sensor manager; YAML
  sections ``items`` and ``calibrations``). Every address belongs to the
  file it was loaded from (source ``library:<file name>``) and is saved
  back into it; a new one goes into the first file already holding its
  kind (item or calibration), else into the first file. "Save library
  as ..." writes a new file with the entries that belong to no file.
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
3. **Done** (``redvypr/widgets/redvypr_items_widget.py``, button "Items" in the
   main window, ``test/test_items_widget.py``): Items widget with tree by
   parent and state time, type filter, form (own simple form: text fields,
   JSON/YAML for structured values, additional fields), history with source,
   new/copy (optional uuid), move to parent/slot, load/save library file.
   Assigning items from the address widget and the ADC tab follow with step 4.
4. **Done** (``redvypr/items.py``: ``param_value()``, ``resolve_param()``;
   ``devices/norlog/norlog_items.py``: ``norlog_v02``, ``norlog_v021``,
   ``breakout_v01`` with ``R1``, ``ntc_sensor``, ``hf_sensor``; profile
   channels name the parameter, ``ChannelCal.scale_ref = ('board', 'R1')``).
   The norlog calibration is applied on the device, so the scale is a number
   there: the ADC tab shows the items of every channel (sensor, board) and
   warns if the R_ref of an NTC calibration on the device differs from R1 of
   the board; the calibration dialog takes R_ref from the board (new
   calibration) or offers it with a button. Calibrations applied in redvypr:
   see "Conversion into units".
5. **Done** (``redvypr.items.SetupItem``, ``setup_of()``; norlog:
   ``adc_setups.to_item()``/``from_item()``/``update_from_items()``, button
   "Save as profile ..." in the ADC tab; the gateway sends the profiles of a
   norlog as device metadata ``setup`` = {sensor: name} at ``@di:<hwid>``):
   setup profiles as ``setup`` items, translation of terminal slots. The
   built-in profiles stay in the code as fallback; an item of the same name
   wins. The profile item carries ``channels`` (with ``slot``, ``cal``,
   ``unit``, ``scale``, ``scale_ref``, ``hint``) and the norlog fields
   ``sensor`` and ``sequence`` as additional fields.
6. **Done** (``sensor_and_calibration_definitions.py``,
   ``sensor_calibration_manager.py``, ``test/test_sensor_items.py``):
   ``BaseSensor`` derives from ``Item`` (itemtype = ``sensortype``, id =
   ``sn``), ``BaseSensor``, ``HeatflowClassicSensor`` and ``TarSensor`` are
   registered item types. The manager writes sensors with a serial number as
   items (``sensor_metadict()``) and reads items and sensors of older
   versions (``sensors_from_metadata()``); a sensor without serial number is
   still written in the old format.


Open points
-----------

* Decided 2026-11-08: ids unique per item type with optional ``uuid``; the
  tree is kept in redvypr only (devices do not store their boards).
* Several redvypr instances changing the same item: the merge rules keep both
  values with their times; the later ``valid_from`` wins.
* Calibrations applied in redvypr: R_ref is not a field of the calibration
  but stage 1 of the conversion (setup profile of the channel), see
  "Conversion into units". Open: live processing device, plots.
* Slot names: free strings; conventions per device type (channel names or
  connector pins) are documented with the item types.
