# Changelog

redvypr changelog

---

## [unreleased] 

### Added
- nothing yet
### Changed
- nothing yet

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