# Changelog

redvypr changelog

---

## [unreleased] -

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