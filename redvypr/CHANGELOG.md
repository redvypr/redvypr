# Changelog

redvypr changelog

---

## [unreleased] -

### Added
- Progress while loading item libraries: a dialog with the file being read and its count, the
  following steps and a Cancel button appears if loading takes longer than 0.3 s (Metadata
  window, Items window, Git window for pull, bundle import and new repository); cancelling changes
  nothing. `progress(text, done, total)` of `Redvypr.load_item_library()`, `reload_item_library()`
  (reads first, then replaces the old entries), `item_git_pull()`, `item_git_import_bundle()`,
  `item_git_clone_bundle()`; `metadata_sources.LoadCancelled`; `widgets.load_progress.LoadProgress`.
  The status line shows the loading time.
- Heat flux sensor type named `hf_sensor` (calibration type `hf_sensor`, classes `HfSensor`,
  `HfCalibration`, `HfCalibData`; the generation "classic" is the field `hw_revision`).
- Metadata window (button "Metadata" in the main window, Tools menu "Metadata ..."; replaces
  "Edit Metadata" and "Items"): bar with libraries, "Save libraries", "Git ..." and the state time
  for all tabs; tabs Generic (metadata table without items, item types and calibrations unless
  asked; "Query ..."), Items, Item types and Calibrations (new: all calibrations with their sensor
  item, the valid one, the library; filter, import, remove, create sensor item, show sensor).
  `item_calibration.calibration_entries()`. Tools menu "Query metadata ..." for the query tool.
  Cross links: the type in the title of an item opens it in the tab Item types, "Show items" in the
  type editor shows the items of the type, a calibration shows its sensor.
- Sensors and calibrations (design note section "Sensors, calibrations and the sensor manager",
  step 1): sensor types of the sensor manager named per model in English (`hf_sensor`,
  `tar_sensor`, `base_sensor`), field `sensortype` removed (the `SensorFactory` uses `itemtype`,
  a key `sensortype` of a sensor file is read as item type), older sensor format (`@i:sensor`)
  dropped, `date_produced` optional; norlog type `hf_sensor` removed. Calibrations are found by
  serial number and type (`sensor_model` = item type, `NA`: any). `get_items()` gives the
  ancestors of the sensor (`FoundItems.ancestors`), `items.param_from()` searches a circuit
  parameter (e.g. `R1`) along them, so an NTC inside a heat flux sensor takes R1 of the breakout.
  Step 2: Items window with tabs "History", "Calibrations" (calibrations of the item by serial
  number and type, the valid one marked, "Import calibration ..." creating missing sensor items,
  "Remove calibration"; new calibrations saved into `calibrations.yaml` next to the first library)
  and "Attachments" (files in `attachments/<itemtype>/<id>/<uuid>/`, configuration
  `item_attachments_path`; module `redvypr.item_attachments`).
  Step 3: sensor manager with a fixed tab "Sensors (items)" (sensors of the metadata, open the
  Items window, import sensor files into the metadata), no new sensor lists; applying a
  calibration list creates missing sensor items, loading from the metadata fixed.
  `HfCalibration.raw2data()` (mV x `calibration_HF_SI`, W m-2); profile channels
  name their raw unit (`raw_unit`, hf0/hf1: V), converted into the input unit of the calibration
  by SI prefix (`item_calibration.unit_factor()`).
- git for the item libraries (`redvypr.item_git`): status, commit, pull and push of the item files
  (`Redvypr.item_git_paths()`, `item_git_status()`, `item_git_commit()`, `item_git_pull()`,
  `item_git_push()`), with the git program if installed, else dulwich (pure Python); a pull needs
  committed files, stops at conflicts without changes and loads the libraries again
  (`reload_item_library()`); a push is refused if the remote is ahead; with dulwich the HTTPS
  access token is kept in the system key store (`keyring`). New dependencies `dulwich` and
  `keyring` and `merge3` (dulwich merges changes at different places of one file), so
  `pip install redvypr` works without git. Library files are written only if their text changed
  (line ends not counted). Items window "Git ...": repositories of the item files with their
  changes, commit, refresh, fetch, pull (libraries loaded again), push, dialog for user name and
  access token. Bundles for computers without network: "Export bundle ..." (one file with the
  commits, `<bundle>.txt` with server, branch, commit and the libraries in load order), "New
  from bundle ..." (a repository on the field computer, origin = the server, libraries loaded
  in the same order), "Import bundle ..." (like a pull); `GitBackend.create_bundle()`,
  `import_bundle()`, `item_git.clone_bundle()`, `Redvypr.item_git_export_bundle()`,
  `item_git_import_bundle()`, `item_git_clone_bundle()`, `metadata_sources.find_libraries()`.
- Directory libraries: an item library can be a directory with one YAML file per item, item type
  and calibration (`items/<type>/<id>.yaml`, `item_types/<name>.yaml`,
  `calibrations/<sensor model>/<sn>/<date>_<uuid8>.yaml`, marker `redvypr_library.yaml`); saving
  writes only changed files and removes those of addresses that are gone; Items window "Load
  folder ...". Types of a library are searched in the YAML files next to it and its directory
  `item_types` (no longer in all subdirectories). YAML read and written with libyaml if available.
- Item types as data (`redvypr.item_types`, design note section "Item types as data"): a type
  defined in the metadata at `@i:'itemtype' and d:'<type>'` / in the section `item_types` of a
  library file (short form `<type>: {description, base, revision, fields, defaults, renamed}`)
  becomes a pydantic model registered like a Python type; field kinds str, int, float, bool,
  quantity (fixed unit), ref, list, dict with unit, description, default, choices; a definition
  of a Python type extends it. The Items form shows the field descriptions and units. Item type
  `breakout_v01` renamed `breakout_board_v01` (types named per model in English). Definitions
  of unknown types of loaded items are searched in the directory of the library and in the
  configuration `item_type_paths` (YAML files with a section `item_types`, with subdirectories,
  read again only after a change; `item_types.resolve_types()`, `Redvypr.resolve_item_types()`).
  Type editor (Items window, "Types ..."): list of the types with origin and file, form of a
  definition (fields table with kind, unit, description, default, choices; defaults; renamed;
  inherited fields shown), new type, copy, proposal from the selected item, saved into a YAML file
  with history (`Redvypr.save_item_type()`, `item_types.write_definition()`).
- Items in the metadata (design note doc/source/design_items.rst, step 1): new module
  `redvypr.items` for physical things (loggers, boards, sensors, ...) and templates. An item lives
  at `@i:'item' and d:'<itemtype>' and di:'<id>'`, one metadata key per field with its own validity
  period (general fields e.g. name, sn, description, location, manufacturer, mpn, order, parent,
  slot); pydantic item types with registry, type revision and migration; tree by `parent`/`slot`;
  `get_items(address, at_time)` finds the device, board and sensor of a datastream (or uses a key
  `items` at the data address). Methods `Redvypr.add_item()`, `get_item()`, `list_items()`,
  `get_items()`, `get_item_history()` and `DbReader.get_items()`. Tests in test_items.py.
- Metadata from several sources (step 2): new module `redvypr.metadata_sources`. Entries carry
  their origin in the constraint `source` (not part of the context; equal entries of different
  sources are joined, their sources kept as list). `merge_storages()` joins instance, item
  libraries and databases with a precedence per kind of source (items: library > instance > db)
  and reports conflicts. `DbReader.get_metadata()`/`get_items()` use the metadata of the database
  merged with the running instance (set by the `DatasourceRegistry`), so later corrections reach
  old data; `DbReader.metadata_conflicts()`. Item library files (YAML or SQLite, e.g. an
  `inventory.sqlite`, by the suffix .sqlite/.sqlite3/.db: table `redvypr_metadata`, only the item
  addresses are replaced): configuration `item_libraries`, `Redvypr.load_item_library()`,
  `save_item_library()`. Several library files at once (e.g. `inventory_norlog.yaml`,
  `calibrations.yaml`): a library holds items and calibrations (entries with the key
  `calibration`, YAML sections `items` and `calibrations`); every address is saved back into
  the file it was loaded from, new ones into the first file holding their kind
  (`assign_library_entries()`, `Redvypr.save_item_libraries()`, Items window "Save libraries"
  and "Save library as ...").
- Items window (step 3, button "Items" in the main window and Tools menu "Items (inventory)"):
  tree of the items by parent at a chosen time, type filter, form of the selected item saved as
  new values from a time on, additional fields, history with validity and source, new item or copy
  (optional uuid), move to another parent/slot, delete an item with its history after a question
  (for mistakes; `Redvypr.remove_item()`, the library loses it at the next save), load and save
  item library files.
- norlog items (step 4): item types `norlog_v02`, `norlog_v021`, `breakout_board_v01` (with the measured
  reference resistor `R1`), `ntc_sensor`, `hf_sensor`. The ADC tab shows the sensor and board of
  every channel from the items and warns if the R_ref of an NTC calibration on the device differs
  from R1 of the board; the calibration dialog takes R_ref from the board. Setup profile channels
  name the parameter (`ChannelCal.scale_ref`). `redvypr.items.resolve_param()`.
- Setup profiles as items (step 5): item type `setup` (`redvypr.items.SetupItem`) with the
  channels of a profile and the slot of their item (e.g. a terminal `J2.3-4`); `get_items()`
  translates such slots with the profile the device names (metadata `setup`). norlog: the gateway
  sends the profiles of a norlog as device metadata, profiles from `setup` items win over the
  built-in ones, ADC tab "Save as profile ..." stores the table as `setup` item. The built-in
  profile `hf_ntc_v01` names the terminals of its channels.
- Conversion into units with items (design note, section "Conversion into units"): new module
  `devices/sensors/calibration/item_calibration.py`. Stage 1 (measuring circuit): input = raw *
  scale of the setup profile channel (`scale_ref` resolved with the items, e.g. R1 of the board,
  else the nominal `scale`); stage 2 (sensor): the latest calibration of the sensor item (by `sn`
  and date, channel if several) with `raw2data()`. `apply_calibration()`, `calibrate_series()`
  (split where items or calibrations change), `get_data_calibrated()` for a `DbReader`.
  Built-in items (`redvypr.items.register_builtin_item()`): the norlog module registers its
  built-in setup profiles.
- Item defaults: entries at `@i:'item'` apply to all items, at `@i:'item' and d:'<type>'` to all
  items of a type (the item itself wins). Items are read by direct lookups of these addresses and
  their own (`redvypr.items.item_keys()`, any spelling of the address) instead of a search over all
  metadata addresses per item: `get_items()` with 600 items and 2600 addresses 14 ms instead of 1 s.

### Changed
- Sensor and calibration manager (items step 6): `BaseSensor` derives from `redvypr.items.Item`
  (itemtype = sensortype, id = sn); `BaseSensor`, `HfSensor` and `TarSensor` are item
  types (Items window, tree, history per field). Sensors with a serial number are written to the
  metadata as items (one key per field) instead of one key `sensor` at
  `@i:sensor and sn==...`; sensors stored that way by older versions are still read.
- norlog gateway: setup profiles of the ADC sequence (firmware >= 0.4.51, design note
  doc/design_aufbau_profile.md of the firmware). New module `adc_setups` with the profiles as
  templates (sequence and kind of calibration per channel), first `hf_ntc_v01` for the breakout v01
  with two heat flux sensors and two NTCs. The sequence text knows `setup=<name>`. ADC tab: "Setup"
  with "Load profile" (fills the table, then "Write to device"); after reading it shows the setup of
  the device, whether the sequence differs from its profile and which channels lack a (matching)
  calibration; the calibration dialog of a new calibration is preset from the profile (kind, unit,
  R_ref). Device list: column "Setup" from `extinfo.setup`, read again after writing a sequence.
- norlog gateway: several serial ports in one gateway device (design note doc/design_verbindungen.md of
  the firmware). The device list is a tree: the serial ports at the top (also while the device is
  stopped: the ports found, "All serial ports" also those that do not look like a norlog), the members
  of a Thread network below their gateway. Right click on a port: "Connect" / "Disconnect", role
  auto (may become the gateway of its network) / gateway (preferred) / node (never the way into the
  network), remove it from the configuration. The ports are stored in `ports` (found again by their
  USB serial number under another COM number; ports that are not connected are never opened); an
  older `comport` becomes the first port with role gateway. Each Thread network (Extended PAN ID) gets
  one active gateway (role gateway, then leader, router, child; no flapping on a tie); it is the sink
  of the live data, a former gateway gets `norlog sink off`. A packet received twice (mac, boot,
  packet_num) is published once. Console and tab "Thread network" (form network, make leader, read
  dataset, status) work on a chosen port; flash, battery model and USB settings of the settings window
  go to the port of the device.
- norlog gateway: devices are named by their hardware ID (before their first info `port:<port>` or
  `rloc:<RLOC16>@<gateway port>`) instead of "gateway" / RLOC16. Members are addressed over their
  Mesh-Local EID (firmware >= 0.4.49, `thread.mleid` of the info), which stays the same when the
  RLOC16 changes; without it over the RLOC address. New module `ports` (port search, matching with the
  configuration, open port); `device_list.build_devices()` and `choose_gateways()`.
- norlog: new module `links` with `SerialLink` (shell of the norlog at a serial port) and `ThreadLink`
  (CoAP to a member through the shell of a gateway), first step of several serial ports per gateway
  device (design note doc/design_verbindungen.md of the firmware). The gateway thread reaches every
  norlog through a link (`_Gateway.link(target)` instead of `target_address`); the `*_local` /
  `*_remote` pairs of `ot_cli` are methods of the links. No change of the behaviour.
- norlog gateway: compact CoAP 'info' of firmware >= 0.4.50 plus 'extinfo' (firmware, serial number,
  temperatures, radio, ...), read only every extinfo_interval_s (default 60 s, also on "Read device
  info") and merged into one info dict. 'info' packets carry the extinfo values only when they were
  read again. Older firmware still sends everything in 'info'.
- norlog: CoAP answers of 'norlog coap local' (firmware >= 0.4.48) are read: binary payload as
  base64 with CRC-32 (a garbled line is detected and read again). Not used for requests yet.
- norlog gateway, button "SD card" in the tab "Datafiles" and in the "Files" tab of the device settings, also
  right click on a device in "Datafiles": "Archive log files on the card" (moves /log to
  /archive/<name>_<date_time> on the card, logging continues), "Delete log files on the card", "Format the card"
  (firmware >= 0.4.44, also over Thread). `ot_cli`: `sd_op_local()`, `sd_op_remote()`, `sd_status_local()`,
  `sd_status_remote()`. Progress ("N file(s) deleted ...") in the status line; gives up only after 120 s
  without progress instead of a fixed 90 s (deleting hundreds of files takes a while). With firmware
  >= 0.4.46 the shell command on the gateway runs in the background and `norlog sd json` is polled.
- norlog gateway: tab "Datafiles" (after "Live data"): the archive of the SD card log files, one folder per
  hardware ID. Left the devices and their files ("List card": state on the card, "Download": what is new, also
  only the selected files), right an overview of the packets of the selected devices/files (one row per packet
  type and value: count, time range, lost packets, boots, redvypr address). Downloaded data is converted
  automatically into `<archive>/<hwid>/<hwid>.sqlite` (only new or grown files, `convert.json`) and added as
  data source of redvypr; "Rebuild database" in the tree menu. Right click in the overview: "Plot data" (database
  lines in a new XY-Plot) or "Add to <plot>" (also plots of the live data), "Publish packets" of the selected
  types and files with their measurement time, "Copy redvypr address". New module `norlog_datafiles`
  (`summarize()`, `summary_rows()`, `convert_device()`, `iter_packets()`); `norlog_convert.convert(boot_offsets=)`
- norlog gateway: "Subscribe" button per device in the device table: the subscriptions window for this device
  only. Subscriptions window: checkbox "All" ticks or unticks all packet types
- norlog gateway, tab "Live data": columns "CBOR type" (packet type of the CBOR tag, e.g. `adcseq (50009)`)
  and "Redvypr address"; checkbox "One row per value" splits the packets into their values (`live_split`).
  Right click on rows: "Plot data" makes a new XY-Plot device with the numeric values of the selected rows
  (x = measurement time `t` of the same packets), "Add to <plot>" adds them to a plot made here before
  (`live_plots`); "Copy redvypr address"
- norlog gateway: right click on the header of the device table shows or hides columns
  (`devices_hidden_columns`)
- norlog gateway: install a new norlog_loader without SWD (firmware >= 0.4.42). Firmware tab of the device
  settings, group "Loader (slot1, without SWD)": the signed loader image goes to `/fw/loader.bin` on the SD
  card of the gateway or a member, the app writes it to slot1 and verifies it (`norlog fw loader`,
  `POST fw?op=loader`), no reboot. `ot_cli`: `fw_status_local()`, `fw_loader_local()`, `fw_loader_remote()`;
  config `loader_image`
- norlog gateway: live data over Thread (firmware >= 0.4.32). "Subscriptions" button: make the gateway a sink
  (`norlog sink on [<types>]`) and tick per device which packet types it sends (`norlog pub <types> [targets]`,
  over CoAP for the members); stored on the devices and in the configuration (`live_sink`, `live_sink_types`,
  `live_pub` per hardware ID) and set again at the start (`live_apply`). "Live data" button: window with the
  last packet per device and type, lost packets (gaps in `packet_num_type`) and a log of the incoming packets
  The gateway is a sink by default (`live_sink`), so its own packets come as live data too (firmware >= 0.4.33)
- `ot_cli`: `pub_status()`, `pub_set()`, `sink_set()`, `pub_text()`, `sink_text()`, `PACKET_TYPES`
- norlog gateway: "Save data" with options (gear button): the channels are ordinary redvypr writer devices
  (for now `sqlite_writer`, shown in the device list) that subscribe to the packets of the gateway
  (`@p:<gateway>`, optionally only some packet IDs) into the table `redvypr_raw` (full packets, no flat
  table); "Save data" starts and stops them, the first one is added automatically (`save_data`,
  `save_channels` = device names)
- db: table setting `uid_keys` (redvypr_datapacket with `skip_duplicates`): keys of the packet that identify it
  together with its source (deviceid or device); packets that have all of them are compared by these only.
  norlog raw tables use `['boot', 'packet_num']`, so a packet received live and converted from the SD card is
  stored once, independent of its time
- norlog: time basis of firmware >= 0.4.35: packet time `t` = (`uptime_ms` + `offset_ms`) / 1000 with
  `t_source` 'node' (live data, archive, converter, log index); `rtc_time` of older logs is still used.
  `norlog_cbor.packet_time()`; time packet `time` (tag 50011, keys 100-108 incl. `gps_pps` of firmware 0.4.36,
  `time_event_name`), pub type `time`
- norlog gateway: "Set clock" sends the uncertainty of the time (round trip of the request) with firmware
  >= 0.4.35 (`ot_cli.time_set(unc_ms=...)`)
### Changed
- norlog gateway: magnetometer calibration: tooltip on the duration/rate, the device stores at most 600 values
  (firmware >= 0.4.45)
- norlog gateway: the redvypr address of the live data uses the hardware ID (`<key> @ di:<hwid> and
  i:<type>`) instead of the device name, the same as the data files
- norlog gateway: "Publish the downloaded packets" removed (`archive_publish` is not used anymore); instead
  "Publish packets" of selected types in the tab "Datafiles". The "Data" tab of the device settings has
  "Show in Datafiles"
- norlog gateway: tab "Live data" directly after "Devices"; the info text box below the device table
  is removed (the info stays in the table and in the device settings)
- norlog gateway: device table: RSSI, LQ, path cost, seen, packets and firmware moved to the right end
- norlog_convert / "Convert to SQLite": the packets go into `redvypr_raw` (full packets, as "Save data"); the
  data_flat table only with `flat=True` / `--flat` / "Flat table for plots" (default on in the GUI, needed by
  the redvypr data sources)
- norlog gateway: simpler "Subscriptions" window: one table for all devices including the gateway, ticks =
  packet types that come live (`norlog pub`), received packets and age per device, yellow = not applied yet,
  grey = not read; targets and all/none in the right-click menu. The gateway is always the sink for all
  types; without an entry it sends all its own packets (firmware >= 0.4.34). `live_sink_types` is unused
- norlog gateway: the "Data" tab (last `#NLD` packet per node) is replaced by the "Live data" tab with the
  "Subscriptions" button
- norlog gateway: live data of the gateway itself and of a member whose RLOC16 changed are counted at that
  device (matched by RLOC16 or hardware ID) instead of an extra "data only" device
- norlog: CBOR key 7 is decoded as `packet_num_type` (packet number per packet type, firmware 0.4.31),
  was `packet_num_sensor`; same key, so old log files still decode. New databases get the column
  `packet_num_type`, existing ones keep `packet_num_sensor`
- db writer status (sqlite, timescale): the lower table is "Written per table and address" with the table
  type; packet tables (redvypr_datapacket) show no flat column ("–"), only data_flat tables have one per address
### Fixed
- `RedvyprMetadataTable` without an address failed (a layout was hidden), so "Edit Metadata" did
  not open; it no longer prints all metadata to the console when loading.
- `HfCalibration` without `calibration_uuid` failed (uuid5 with a text namespace);
  its `sensor_model` is the item type `hf_sensor` (the series stays the field `series`).
- `ot_cli`: single-value answers (`ot state`, `channel`, `rloc16`, ...) only accept a line of the expected
  form; a log line of the firmware split into the response no longer shows up as Thread role of the gateway
- db writer config widget: field "UID keys" per table; before, applying the configuration in the GUI
  dropped `uid_keys`

## [0.9.23] - 2026-10-31

### Added
- Data sources (`redvypr.datasource`): databases of the SQLite and TimescaleDB writers, configured once in redvypr
  (`datasources` in the configuration, `Redvypr.add_datasource()`) and used by name. A reader lists the datastreams
  of the data_flat tables and gives the values of all datastreams matching an address, merged in time; long ranges
  are thinned out in the database (minimum and maximum per time bucket); units and other metadata from the database
- XY plot: lines from a database ("Add line from database ...", source `database` or `database+live`): loaded in a
  thread for the range shown, thinned out for long ranges, reloaded after zooming and panning, "A" loads everything;
  the data table of a selection gets all values of the range from the database
- Widgets to add/edit data sources and select datastreams (`redvypr.widgets.datasource_widgets`)
- norlog_convert: units of the values and hardware ID/serial number of the norlog as metadata in the database;
  the "Convert to SQLite" button adds the database as data source of redvypr
- norlog gateway: hardware ID column in the device table; "Make gateway leader" (leader weight 72, `state leader`)
  and "Gateway prefers leader role" (weight again after a restart, leader again at most every 10 minutes);
  leader weight and partition ID in the Thread status
- norlog gateway: "Import autoexec.txt ..." in the network parameters (counterpart of the export): network name,
  channel, PAN IDs, network key and the dataset for provisioning
- norlog gateway: "Provision node via UART" also without a running gateway (directly on the node port)
- norlog gateway: transmit power at the antenna per device in the settings ("Radio"), gateway over the shell,
  members over CoAP /radio; stored on the device (firmware >= 0.4.5)
- norlog gateway: state of the front end pins (TX_EN, RX_EN, MODE) in the settings, "PA stuck?" in the quality
  column if TX_EN hangs HIGH (firmware >= 0.4.6); fixed: the gateway as leader was listed twice
- norlog: chip temperature of the nRF52840 (`nrf_temp_c`, CBOR key 61, firmware >= 0.4.7) as column of the device
  table and in the settings; the board temperature (ADC) is marked if it differs by more than 15 C (ADC resets)
- norlog gateway: column "Clock" (was "RTC", it showed the system clock of the device): offset to this PC from the
  info time with ms (firmware >= 0.4.8) and the middle of the request, tolerance from the request time; RTC offset
  to the system clock in the tooltip and the settings
- norlog gateway: column "GNSS" (fix and satellites, colored; details in the tooltip) and GNSS in the settings
  (firmware >= 0.4.10)
- norlog gateway: GNSS position (firmware >= 0.4.11) in the tooltip and the settings; right click in the device
  table: copy the position (with/without altitude), the cell or the tooltip
- norlog gateway: magnetometer calibration (hard and soft iron, firmware >= 0.4.12) in the settings, tab
  "Magnetometer": recording on the device over UART or Thread with live points and coverage of 26 directions,
  ellipsoid fit (fallback sphere fit) in `devices/norlog/mag_calibration.py`, apply to / delete on the device,
  points as CSV; magnetometer packets (tag 50007, keys 70-76) decoded with units
- norlog: wind packets of a NMEA sensor at UART1 (tag 50008, keys 80-83, firmware >= 0.4.13) decoded with units
- norlog: ADC measurement sequences (tag 50009, firmware >= 0.4.15) decoded into one field per step (value, unit
  from the packet) plus `<name>_raw`, packet type = sensor name (e.g. `adc_brd`); configuration packets
  (tag 50010) as `<sensor>_cfg`; key 9 `sensor`; `norlog_cbor.units_of()`
- norlog gateway: settings tab "ADC" for the measurement sequence of `adc_brd`/`adc_hfm` (firmware >= 0.4.15),
  over UART and Thread: table of the steps (inputs, gain, reference, IDAC, delay) with the last values, data rate,
  filter, interval, on/off; read, write (checked before), measure once; configuration text; hints on the inputs
  of the norlog rev02; `devices/norlog/adc_sequence.py` (parser/writer of the configuration text),
  `ot_cli.adc_get/adc_set/adc_measure`
- norlog gateway, tab "ADC" (firmware >= 0.4.16): column "Bias" (VBIAS at AIN0-5 for floating sensors) and
  "Calibrated"; dialog "Calibration ..." for the polynomial calibration of a channel on the device (coefficients,
  linear from a sensitivity, fit to reference points, delete); `devices/norlog/poly_calibration.py`,
  `ot_cli.cal_get_one/adc_calibrations`; calibrated values of ADC sequences decoded as `<name>_cal` with unit
- norlog gateway, calibration dialog (firmware >= 0.4.17): kind NTC, the same model as
  `CalibrationNTC` (1/T = polynomial of ln R, R = x * R_ref), fit from R/R_ref and temperatures; load
  redvypr calibration files (ntc, polynom, linearfactor, heatflow) and save as redvypr calibration;
  `poly_calibration.fit_ntc/from_redvypr/to_redvypr`
- norlog ADC tab: data rates of the ADS124S08 corrected (50, 60, 100, 200, 400, 800, 1000, 2000, 4000 SPS
  instead of 45, 90, 175, 330, 600, 1000, 2000), matching firmware >= 0.4.18
- norlog gateway: settings tab "NMEA" for a sensor at UART1 (e.g. wind meter): receive on/off, baud rate
  (auto or fixed), raw packets on the SD card (written over the shell or CoAP `POST wind`, firmware >= 0.4.21),
  status with sentences, last wind and last sentence, optional refresh every 2 s; `ot_cli.nmea_get/nmea_set`
- norlog settings, tab "Data": "List files" compares the card with the archive without downloading (boot, start
  time, sizes, what is left to load); select files (checkboxes, "All" with new data, "None", "Marked rows") and
  the order ("oldest first"/"newest first"); during the download the current file is highlighted with its
  percentage, finished files are marked, the status shows file i of n, rate and time left;
  `norlog_archive.plan()` and `sync(stems=, newest_first=)`
- norlog data download: the file list compares sizes only (CRC only at the end of files that grew, before
  appending), much faster with many files; optional "verify (CRC)" compares the archived files completely
  with the card, files found different are loaded again (old copy kept); the list can be cancelled
- norlog data download: the catalog of the card (96 bytes per data file) is loaded incrementally (last
  record and what is new, the rest checked by one CRC) instead of completely for every list, with progress;
  columns "No." (file number from the name) and "Boot" (from the catalog)
- norlog data download more robust: blocks from the gateway's own card are checked (strict base64, length)
  and read again if garbled (e.g. a log line inside the answer); after a CRC mismatch the differing 4 KB
  pieces are read again instead of aborting; a file that still fails is marked "FAILED" and the download
  continues with the next files (stops after 3 failures in a row); with firmware >= 0.4.23 every block read from the gateway
  carries its CRC32 and is checked at once
### Changed
- norlog gateway: without a configured port the first serial port that no other device of redvypr uses
  is preset (ports in numeric order, COM3 before COM16); a port from the configuration stays
- Main window: after opening it is fitted into the free area of the screen and centered (it could reach
  under the Windows taskbar); the tabs of the norlog gateway scroll, they no longer force a minimum height of
  about 790 px on the main window
- Database writers: index on the time `t` of data_flat tables
- Fixed: norlog metadata of a hardware ID of digits only did not match (`@di:` without quotes became a number)

## [0.9.22] - 2026-10-05

### Added
- Documentation of the metadata system (`doc/source/metadata.rst`), `redvypr.metadata` in the API reference
- `Redvypr.set_metadata_from_dict()` (was called, but missing), `metadata.normalize_metadata()`
- norlog gateway: "Data" tab: download the SD card log files into an archive folder (only what is new,
  CRC verified, resumable) and optionally publish the packets with their measurement time; "Set clock" per device
- Database writers: option `skip_duplicates` per table (packets with the same source, packetid, time and content
  are written once); columns `deviceid`, `sensorid` and indexes on time and device
- SQLite writer: `storage` 'file' (directly into the file, WAL) besides 'memory', `append_to_file` to continue one
  database file
### Changed
- Metadata entries describe the period in which a value was valid: the same key, value and context again (other
  `valid_from`, restart, sent with every packet) does not add an entry; overlapping periods are merged, a new value
  ends the old one; entries of different contexts do not end each other
- Metadata from datapackets are valid from the time of the packet; an address naming its source (`d`, `di`, `si`) is
  no longer bound to device and packetid of the packet
- `get_metadata()`: a query naming its source only gets metadata of addresses with the same source entries; parsed
  addresses are cached (1000 addresses: 2 ms instead of 320 ms per query); times compared as datetimes
- `save_config()` saves the metadata entries with history; loading accepts them and the simple form
  `{address: {key: value}}` (before nothing was loaded and `load_config(use_metadata=True)` failed)
- Fixed: shared constraints of `create_metadata_dict()`, nested `create_metadatapacket()`, metadata of other redvypr
  instances lost (and the other packets of that distribution round)
- norlog gateway: no full resend of the metadata after a serial number change
- Database writers: packets are written in batches (`batch_size`, `dt_commit`) instead of one transaction per row;
  the address string is cached per source (SQLite: 10000 instead of 1000 packets/s)
- SQLite `get_redvypr_datapackets()`: failed with `json_safe_loads` not defined; returns deviceid and sensorid
- `RedvyprAddress` reimplemented: the filter is parsed once into a filter tree (no Python AST evaluation per packet),
  datakeys are resolved as key/index paths; same syntax and results (incl. comparisons on the packet content like
  `@ data > 2`, `dt()`, lists, `?:`, regular expressions). 20-100 times faster (address of a packet 221 -> 5 us,
  matches 254 -> 2 us), norlog gateway -> writer 550 -> 11000 packets/s. The previous version is kept as
  `redvypr_address_legacy` for comparison (`test/test_redvypr_address_legacy_compat.py`)
- `RedvyprAddress` fixed: address strings with lists, `?:` and regular expressions are re-parseable, parentheses
  (`@d:a and (d:b or d:c)`) are kept; an error in one condition (e.g. comparing a list) only affects that condition
- `RedvyprAddress`: removed `r:` root keys, `extract()`, `to_address_string_pure_python()`
- Devices without `DeviceBaseConfig` / custom config (`test_device_bare`, `test_device_receive`) could not be
  added or started

## [0.9.21] - 2026-10-04

### Added
- norlog gateway device (`devices/norlog`): console of the norlog shell, Thread network (form, status, provisioning),
  device list with link quality, periodic device info, settings window per norlog (properties sn/desc/loc, battery
  model, USB mode, TX power), file browser for the SD cards, firmware update over UART and over Thread
- norlog device info as redvypr packets: one device per norlog (`device` = `norlog_<sn>`, `deviceid` = hardware ID,
  `sensorid` = serial number, `packetid` = `info`) with metadata (properties, units) at `@di:<hwid>`
- norlog gateway option `publish_raw_data` (default off): publish also console, command results and Thread status;
  otherwise they go only to the device window (statusqueue)
- `create_redvypr_dict()`: arguments `sensorid`, `deviceid` and `sensor`, always set in the header (None if unknown)
- XYplot: x-axis mode `last_N_points`; new lines get the first color not used by another line
- "from files" functionality in devices, pause in `rawdatareplay.py`
### Changed
- `redvypr_standard_address_filter` (key of the packet statistics) contains `di`, `s` and `si`: devices with the same
  name but different deviceid/sensorid were merged; the datastream widget shows deviceid and sensorid
- `create_redvypr_dict()`: `raddress` no longer replaces the header (the time was lost), a `RedvyprAddress` object
  works like a string, the host dict is copied, `tu=None` leaves the time to redvypr
- XYplot: no blank plot every `dt_update_metadata` with units, x/y buffers stay the same length, error bands
  (factor = relative error), PyQt6 data table, buffer trimmed in steps, works without a redvypr device
- bug fixes in SubscribeWidget, TAR time variable and serial_single info

## [0.9.20] - 2026-08-22

### Added
- new field `datakeys_info` in `packet_statistics.do_data_statistics` that uses `data_packets.Datapacket.datakeys_info()`
### Changed
- bug fixes in autostart option in save config
- improved console logging for serial, serial_single, rawdatawriter and sqlite_writer
- `get_datakey_info`,`get_datakey_info_from_dict`,`datakeys_info`  in `redvypr.config`
- Renamed `Datapacket` into `RedvyprDatadict` and `data_packets.py` into `redvypr_datadict.py`
- Much cleaner RedvyprAddress init, allowing keywords to be set only by `RedvyprAddress.META_INFO`
- renamed filenames in widgets folder to follow PEP standard
- implemented redvypr_datadict cache in `RedvyprAddress`
- Made `RedvyprDeviceTreeWidget` more generic to use the filterkeys directly from `RedvyprAddress.META_CONFIG`
- Allows `RedvyprAddress` bracket style: `['e']@` is the same as `e@`

 
---

## [0.9.19] - 2026-06-14

### Added
- Datapacket.expand_data(self, expansion_level=1, address_format='k,i,h,d,p'): Helper function to get individual data entries
- datapath in redvypr.config
- added staticmethod `data_packets.Datapacket.datastreams_from_datakeys`
- added staticmethod `data_packets.Datapacket.get_structure_hash(data)`
- added `'device_config': device_config,` with `device_config = self.get_config().model_dump()` to `device_info` dict for the start parameter of a device thread
- db_writer_extended allowing to save single redvypr addresses in flat tables
- "subscribe","unsubscribe","unsubscribe_all" commands can be sent from the thread
  -  ```
        compacket = commandpacket("unsubscribe_all")
        dataqueue.put(compacket)
        compacket = commandpacket("subscribe",comdata=addresses_subscribe)
        dataqueue.put(compacket)
     ```
### Changed
- improved metadata handling a lot
- improved data statistics, better self consistency of packet inspection, cached inspection to improve performance. Not every packets gets a deep instpection anymore, only if the structure hash has changed
- improved `sqlite_writer`: New db setup, better performance on slow sd cards
- improved `netcdfwriter`: Cleaned layout, fixed metadata for the new api
- improved `serial_single`: Better configuration
- improved `RedvyprAddressWidget`: Expansion is not done for time series, as this can be long but can be forced by checkbox
- `test_device` with config gui to change data to be sent
- `XYPlotDevice` changed to `new_data` signal
- replaced `pkg_resources` with a modern alternative
- bug and layout in `redvyprSubscribeWidget`
- `RedvyprMultipleAddressesWidget` with new functionality of `self.address_names`, a dictionary of names that are assigned with `RedvyprAddress`
- `new_data([datapacket])` signal properly implemented in `redvypr.device`
  - first usage in device `devices.event.event.EventConfigEditor`
  - Plan is to replace the `gui_widget.update_data(data)` functions with signal functionality

---

## [0.9.18] - 2026-02-12

### Added
- Added new_data signal in `redvypr.device`, making it easier to get own or subscribed data from device, not working yet
- Metadata from splash screen is now added.
- Remove mode to `redvypr.rem_metadata()`: Keys can be removed from all address entries that match, useful with "@" address.
- First draft of measurement device able to add measurement metadata info to instance.
- Metadata changed signal implemented `metadata_changed_signal` in `Redvypr`
- `RedvyprAddress` can now have the datakey `!`, which means that the datakey must be strictly empty
- `RedvyprAddress` can compare datetimes `RedvyprAddress("@calibration_date <= dt(2026-01-14T16:15:15)")`
- `RedvyprAddress` understands quoted strings (does not treat them), see also new test addresses in `test_redvypr_address` 
- `data_packets.create_datadict` new parameter `random_host="somehostname"` to create a test packet
- Added maximum size and automatic new file creation to `RedvyprSqliteDb`
- Added `sensor_calibration_manager` and `sensor_and_calibration_definitions` that allow to pair sensor definitions with calibration definitions
- Added `__version__` to `__init__.py`
- Added `test_redvypr_address_benchmark.py`

### Changed
- Improved the first page of redvypr, which is now with a timer that starts redvypr after 10 seconds.
- Bugfixes and improvements in `redvyprAddressWidget`.
- Bugfixes and improvements in `distribute_data`, metata is now properly distributed
- Improved database structure of `db` device with id as primary key for all tables (including metadata)
- Renamed timescaledb.py in db_engines.py to account for more database connections
- Improved status gui of db_writer

---

## [0.9.17] - 2026-01-04

### Added
- Measurement device with measurement metadata support.

---

## [0.9.16] - 2026-01-02

### Changed
- Renamed `hostname` to `host` and `hostname_localhost` to `host_local` in `redvypr_address`.
- Major improvements for metadata and database functionality:
  - Support for TimescaleDB and SQLite3.
  - GUI to show databases and choose read options.

### Fixed
- DB works now with TimescaleDB and SQLite3.
- DB API cleanup, added configuration widget for SQLite.

---

## [0.9.15] - 2025-12-27

### Added
- Simplified metadata (global, not device-specific) and improved metadata widget.
- SQLite3 raw data file format support.
- TimescaleDB support.

### Changed
- Metadata info improved.
- Metadata info implemented.
- Abstract base class for TimescaleDB implemented.
- Metadata into TimescaleDB table included.

### Fixed
- First metadata refurbished version, which is unresponsive compared to the main branch.

---

## [0.9.14] - 2025-10-31

### Changed
- Updated `RedvyprAddress` syntax.
- Improved calibration device.
- Updated NetCDF writer.
- Minor bug fixes.

---

## [0.9.13] - 2025-04-18

### Added
- Added `TablePlotDevice`.
- Improved data filter.

---

## [0.9.12] - 2025-04-18

### Changed
- Cleanup of address widgets.
- Improved data filter device.

---

## [0.9.11] - 2024-08-22

### Changed
- Migrated to PyQt6.

---

## [0.9.10] - 2024-12-06

### Fixed
- Calibration updated to work again.

---

## [0.9.9] - 2024-11-02

### Changed
- Cleanup of `pydanticConfigWidget` and implementation of `NoneType` and `Optional`.
- Improved generic sensor to allow entries to `packetid` from `rawdatapacket`.

---

## [0.9.8] - 2024-10-28

### Added
- Added `figlet` and ASCII art.

---

## [0.9.7] - 2024-10-28

### Fixed
- Bug fixes in XLSXWriter and CSVWriter.
- Bug in `distribute_data` (rearranged for loops).
- Improved `datastreamsWidget`.

### Added
- Added `clear_datainqueue_before_start` flag in device base config.

---

## [0.9.6] - 2024-10-27

### Fixed
- Bug in `generic_sensor`.
- Removed debug print statements.

---

## [0.9.5] - 2024-10-27

### Added
- Added `redvypr_device_scan` option to `redvypr` and GUI widgets for fine-tuning available devices.

### Changed
- Cleanup of debugging statements.

---

## [0.9.4] - 2024-10-19

### Added
- Implemented `explicit_format` and `address_str_explicit` in `RedvyprAddress()`.
- Improved requirements.

---

## [0.9.3] - 2024-08-22

### Removed
- Removed `utils` and `utils/csv2dict`.

---

## [0.9.2] - 2024-10-05

### Added
- Implemented expansion level in `redvypr_addressWidget`.
- First draft of `PcolorPlot`.
- Added empty string feature in `RedvyprAddress('/k:')`.
- Added `get_expand_explicit_str` for `RedvyprAddress`.
- Added `distribute_data_replyqueue` for centralized metadata updates.
- Added infrastructure to send command packets to all devices.

### Changed
- Improved datakey comparison.
- Changed metadata design.
- Added `==` to `RedvyprAddress` for direct comparison.

---

## [0.9.1] - 2024-09-10

### Added
- Added `manual_input` device.
- Added `redvypr.get_packetids()` and `RedvyprDevice.get_packetids()`.
- Added support for regular expressions in `redvypr_addressWidget`.

### Changed
- `RedvyprAddress` no longer expands missing address entries with `*`.
- Implemented `__setitem__` for `Datapacket` object.
- `Datapacket` now has its own `RedvyprAddress`.
- `RedvyprAddress` is hashable and can be used as dictionary entries.
- Less verbose output.

### Fixed
- Bug in `redvypr_addressWidget` with packetid.
- Bug in `network_device` when loading config.

---

## [0.9.0] - 2024-08-22

### Fixed
- Fixed autostart bug.
- Fixed autocalibration in calibration device.
- Fixed parameter bug in `initdevicewidget`.

---

## [0.8.9] - 2024-06-19

### Changed
- Renamed `devicedisplaywidget.update` to `.update_data`.
- Cleaned `devicedict` and refactored `gui` and `guiqueue` into `guiqueues`.

---

## [0.8.8] - 2024-06-19

### Added
- Implemented `datastreamsWidget`.
- Added polynomial fit to `calibration.py`.

### Changed
- Improved `Device.get_metadata_datakey` to handle "eval" `RedvyprAddresses`.
- Cleanup of `XYPlotWidget`.

### Fixed
- Bugs in `RedvyprAddress` with `packetid`.

---

## [0.8.7] - 2024-06-19

### Added
- Introduced `packetid` in `datapackets`.
- `Datapackets` now work with `Datapacket[RedvyprAddress]`.

### Fixed
- Bug fixes in serial device.

---

## [0.8.6] - 2024-06-19

### Changed
- Strongly improved `generic_sensor` and sensor definitions.
- `RedvyprAddress` works as a Pydantic datatype.

---

## [0.8.5] - 2024-05-25

### Fixed
- Bug fixes in serial.

---

## [0.8.4] - 2024-05-24

### Added
- Improved `serial_widget`.
- Added `generic_sensor`.

### Changed
- Improved `configwidget`.

---

## [0.8.3] - 2024-04-16

### Added
- `XYPlot` working.
- Added `last_N_points` feature in `XYPlot`.

### Fixed
- Bug fixes in `redvypr_device` save config.

---

## [0.8.2] - 2024-02-22

### Added
- Added QtAwesome icons for devices.

---

## [0.8.1] - 2024-02-21

### Changed
- Renamed API classes to CapWord style according to PEP8.
- Cleanup of configuration.

---

## [0.8.0] - 2024-02-21

### Changed
- Complete rewrite of configuration for full Pydantic version.

---

## [0.7.9] - 2024-02-19

### Changed
- Complete split of `redvypr`, `redvypr_widget`, and `redvypr_main`.

---

## [0.7.8] - 2024-02-19

### Changed
- Cleanup of configuration.
- GUI windows can now be hidden/docked.

---

## [0.7.7] - 2024-02-19

### Added
- Added `datapacket` object for datakey expansion.

---

## [0.7.6] - 2024-02-19

### Added
- `datadistribution` thread restarts if it crashes.

---

## [0.7.5] - 2024-02-19

### Added
- Added calibration and `csvsensors`.

---

## [0.7.4] - 2024-04-10

### Added
- `xlsxlogger` working.
- Re-implemented `nmeaparser`.

---

## [0.7.3] - 2024-04-10

### Changed
- Major rework of `csvlogger`.
- Draft implementation of `xlsxlogger`.

---

## [0.7.2] - 2024-03-24

### Added
- Added `redvypr_devicelist_widget`.

---

## [0.7.1] - 2024-01-07

### Added
- Added Pydantic `device_parameter`.
- Added `add_device`, GUI, and loglevel.

---

## [0.7.0] - 2024-01-07

### Changed
- Replaced `threading.Thread` with `QThread`.
- Replaced `redvypr.configure` with Pydantic for configuration.

---

## [0.6.9] - 2023-12-29

### Added
- Added `finalize_init` for `displaywidget`.
- Implemented `redvypr_device.unsubscribe_all`.
- Improved `datastreamWidget`.

---

## [0.6.8] - 2023-11-22

### Added
- Added `dt_update` to line plot.
- Added `lpd` (last publishing device) to `treat_datapacket()`.

### Changed
- Cleanup of configuration and `rawdatareplay`.

---

## [0.6.7] - 2023-11-11

### Fixed
- Fixed `numpacket` in `distribute_data`.
- `rawdatareplay` now works with indices.

---

## [0.6.6] - 2023-10-25

### Fixed
- Fixed `numpacket` in `distribute_data`.

---

## [0.6.5] - 2023-10-21

### Added
- Improved `rawdatareplay` packet reader for thread-based file inspection.

---

## [0.6.4] - 2023-10-21

### Added
- Added `last publishing device` (lpd) to `treat_datapacket()`.
- Improved `rawdatareplay` packet reader.

---

## [0.6.3] - 2023-10-18

### Changed
- Major cleanup of config utilities and `rawdatareplay`.

---

## [0.6.2] - 2023-09-29

### Changed
- Changed regular expression from non-ASCII `§` to `{}`.

---

## [0.6.0] - 2023-09-21

### Added
- Added regular expressions to `redvypr_address`.
- Command-line arguments can now be more elaborate Python data structures.

---

## [0.5.5] - 2023-04-26

### Fixed
- Fixed nasty bug in `redvypr.py`.

---

## [0.5.4] - 2023-04-25

### Added
- Added `multiprocessing.freeze_support()` for Windows and PyInstaller compatibility.
- Added `sine_rand` datakey to `test_device`.

---

## [0.5.3] - 2023-04-25

### Added
- Added `redvypr.rem_device()` and cleaned `redvyprWidget.closeTab()`.
- Added connection to main thread via `redvypr.redvyprqueue`.
- Added maximum device threshold: `config_template['redvypr_device']['max_devices'] = 1`.

### Changed
- Changed device publish/subscribe flags to `devices.publishes/subscribes`.
- Cleanup of API.
- Rewrote device scan with `redvypr_device_scan` object.

---

## [0.5.2] - 2023-04-05

### Added
- Added subscriptions as a config key for devices.
- Improved configuration parsing.
- Added REP/REQ information exchange in `iored`.

---

## [0.5.1] - 2023-02-11

### Added
- Added tag in `_redvypr` data packet to prevent infinite recirculation.
- Improved `iored`.

---

## [0.5.0] - 2023-02-06

### Changed
- Redesigned `distribute_data` to check for subscriptions.
- Rewrote devices to work with the new design.

---

## [0.4.999] - 2023-01-24

### Added
- Added `iored` device.
- Added configuration class for device configuration.

### Changed
- Removed config folder.
- Created example folder with configuration.

---

## [0.4.10] - 2023-01-17

### Changed
- Improved `rawdatalogger`.

---

## [0.4.9] - 2023-01-17

### Changed
- Moved autostart option in YAML config to `deviceconfig`.

---

## [0.4.8] - 2023-01-17

### Added
- Added autostart option in devices widget.

### Changed
- Moved loglevel/name from `config` to `deviceconfig`.

---

## [0.4.7] - 2023-01-17

### Changed
- `nogui` works again.
- Template configuration is merged with user configuration in `add_device`.
- Updated `network_device` with new API.

---

## [0.4.6] - 2023-01-17

### Added
- Added process kill option.
- Configuration can now be saved.

### Changed
- Cleanup of old interface.
- Configuration now supports template dictionaries.

---

## [0.4.5] - 2023-01-17

### Changed
- Redesign of API.
- `redvypr_device` object as standard device.

---

## [0.4.4] - 2023-01-17

### Added
- Added `rawdatalogger`, `rawdatareplay`, and `csvlogger`.

---

## [0.4.3] - 2023-01-17

### Added
- Added `pyqtconsole`.
- Improved plot GUI.
- Reworked datastream/devicename nomenclature.
- Added `get_datastreams`, `get_datakeys`, and `get_known_devices`.
- Added local flag in `hostinfo`.

---

## [0.4.2] - 2023-01-17

### Changed
- Improved calibration.
- Added save config feature in `redvypr`.

---

## [0.4.1] - 2023-01-17

### Added
- Added `get_datastream`.

---

## [0.4.0] - 2023-01-17

### Changed
- Migrated to `redvypr.net`.
- Added GUI functionality to change loglevel.
- Cleanup of `network_device`.
- Added `ce_sensors` datalogger.
- Added recursive device import.

---

## [0.3.12] - 2022-01-12

### Added
- Added new icon/logo v0.3.1.
- Started calibration device.

---

## [0.3.11] - 2022-01-11

### Added
- Added TCP reconnection feature for NetCDF.

---

## [0.3.10] - 2022-01-10

### Fixed
- Fixed `textlogger` bug.

---

## [0.3.9] - 2022-01-09

### Added
- Improved `textlogger` with `dt_filename`.

---

## [0.3.8] - 2022-01-08

### Changed
- Small changes for stability.

---

## [0.3.7] - 2022-01-07

### Changed
- Changed NMEA parser to `pynmea2`.
- Improved NMEA parsing stability.

---

## [0.3.6] - 2022-01-06

### Added
- Created `files.py` and `gui.py`.

---

## [0.3.5] - 2022-01-05

### Added
- Added list option in packet data.

---

## [0.3.4] - 2022-01-04

### Added
- Added `props` option in plotting routines.

---

## [0.3.3] - 2022-01-03

### Added
- Added `redvypr_devicelist_widget`.

---

## [0.3.2] - 2022-01-02

### Added
- Added automatic group creation for NetCDF.

---

## [0.3.1] - 2022-01-01

### Added
- Added hostname command-line option.
- Added `randdata` counter.

---

## [0.3.0] - 2021-12-29

### Added
- Initial GitHub release (v0.3.0).
- Project initialization.


# Notes
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).