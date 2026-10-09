"""
Decoding of norlog CBOR data packets.

The packet format is defined by the norlog firmware (src/cbor_packager.h):
every packet is a CBOR tag (packet type) wrapping a map with integer keys.
Keys and tags below must be kept in sync with the firmware.
"""

import datetime

from .cbor_mini import CBORTag, loads, loads_all

# Packet type tags (CBOR_TAG_*_PACKET)
PACKET_TAGS = {
    50001: "battery",
    50002: "adc",
    50003: "gnss",
    50004: "raw",
    50005: "ntc",
    50006: "board_temp",
    50007: "mag",           # magnetometer (firmware >= 0.4.12)
    50008: "wind",          # NMEA MWV of a wind meter at UART1 (firmware >= 0.4.13)
    50009: "adcseq",        # measurement sequence of an ADC (firmware >= 0.4.15), see decode_packet()
    50010: "adcseq_cfg",    # its configuration as text
}

# Map keys (cbor_key_t)
KEYS = {
    0: "packet_num",
    1: "uptime_ms",
    2: "rtc_time",
    3: "gps_time",
    4: "mac",
    5: "source_id",
    6: "set",
    7: "packet_num_sensor",
    8: "boot",
    9: "sensor",            # name of the sensor (firmware sensors.h), e.g. "adc_brd"
    10: "batt_mv",
    11: "batt_soc",
    12: "batt_charging",
    20: "adc_ch",
    21: "adc_raw",
    22: "adc_volts",
    30: "gnss_fix",
    31: "gnss_sats",
    32: "lat",
    33: "lon",
    34: "alt",
    40: "raw_type",
    41: "raw_data",
    50: "ntc_raw",
    51: "ntc_ohm",
    52: "ntc_temp",
    60: "board_temp_c",
    61: "nrf_temp_c",       # chip temperature of the nRF52840 (firmware >= 0.4.7)
    70: "mag_x",            # magnetometer raw (SET/RESET corrected), firmware >= 0.4.12
    71: "mag_y",
    72: "mag_z",
    73: "magc_x",           # calibrated A*(raw-b), only with a calibration on the device
    74: "magc_y",
    75: "magc_z",
    76: "mag_heading",      # atan2(y, x) of the calibrated (or raw) field, only meaningful when level
    80: "wind_dir",         # wind direction [deg] (NMEA MWV, UART1)
    81: "wind_speed",       # wind speed [m/s]
    82: "wind_ref",         # 0 relative (R), 1 true (T)
    83: "wind_valid",       # status A
    90: "cfg_id",           # ADC sequence: number of the configuration
    91: "seq_names",        # [names of the steps]
    92: "seq_raw",          # [raw values, 24 bit]
    93: "seq_values",       # [values: V, U_in/U_ref or degC]
    94: "seq_units",        # [units of the values]
    95: "seq_err",          # bit i: step i failed
    96: "seq_ovr",          # bit i: step i overranged
    97: "cfg",              # configuration as text
}

# Units of the values (metadata of the converted data)
UNITS = {
    "uptime_ms": "ms",
    "rtc_time": "s",
    "gps_time": "s",
    "batt_mv": "mV",
    "batt_soc": "%",
    "adc_volts": "V",
    "lat": "degN",
    "lon": "degE",
    "alt": "m",
    "ntc_ohm": "Ohm",
    "ntc_temp": "degC",
    "board_temp_c": "degC",
    "nrf_temp_c": "degC",
    "mag_x": "uT",
    "mag_y": "uT",
    "mag_z": "uT",
    "magc_x": "uT",
    "magc_y": "uT",
    "magc_z": "uT",
    "mag_heading": "deg",
    "wind_dir": "deg",
    "wind_speed": "m/s",
}

# cbor_source_id_t
SOURCE_IDS = {0: "internal", 1: "i2c0", 2: "i2c1", 3: "uart0", 4: "uart1", 5: "spi0", 6: "spi1"}

# cbor_raw_type_t
RAW_TYPES = {0: "serial", 1: "nmea", 2: "ubx"}

CBOR_TAG_EPOCH = 1


class Packet(dict):
    """A decoded packet; .units holds the units of fields that are not in UNITS (ADC sequences)."""
    units = None


def units_of(pkt):
    """Units of the fields of a decoded packet: UNITS plus the units the packet carries itself."""
    units = {k: UNITS[k] for k in pkt if k in UNITS}
    units.update(getattr(pkt, "units", None) or {})
    return units


# Field names of an ADC sequence that would collide with the header get the prefix "ch_"
_RESERVED = set(KEYS.values()) | {"packet_type", "source", "t", "rtc_time_iso", "gps_time_iso"}


def _flatten_adcseq(result):
    """
    ADC sequence: one field per step named like the step (value) plus <name>_raw;
    the packet type is the sensor name (e.g. 'adc_brd'), so several ADCs stay apart.
    """
    names = result.pop("seq_names", None) or []
    raw = result.pop("seq_raw", None) or []
    values = result.pop("seq_values", None) or []
    units = result.pop("seq_units", None) or []
    result.units = {}
    for i, name in enumerate(names):
        key = name if name not in _RESERVED else f"ch_{name}"
        if i < len(values):
            result[key] = values[i]
        if i < len(raw):
            result[f"{key}_raw"] = raw[i]
        if i < len(units) and units[i]:
            result.units[key] = units[i]
    if result.get("sensor"):
        result["packet_type"] = result["sensor"]


def _convert_value(key_name, value):
    """Unwrap epoch tags and give a few fields a friendlier representation."""
    if isinstance(value, CBORTag) and value.tag == CBOR_TAG_EPOCH:
        value = value.value
    if key_name == "mac" and isinstance(value, int):
        return f"{value:016X}"
    if key_name == "source_id":
        return SOURCE_IDS.get(value, value)
    if key_name == "raw_type":
        return RAW_TYPES.get(value, value)
    return value


def decode_packet(item):
    """
    Convert one decoded CBOR item into a flat dict.

    Returns a dict with 'packet_type' plus the named fields, or None if the
    item is not a norlog packet.
    """
    if not isinstance(item, CBORTag) or item.tag not in PACKET_TAGS:
        return None
    if not isinstance(item.value, dict):
        return None

    result = Packet(packet_type=PACKET_TAGS[item.tag])
    for key, value in item.value.items():
        name = KEYS.get(key, f"key_{key}")
        result[name] = _convert_value(name, value)

    if item.tag == 50009:
        _flatten_adcseq(result)
    elif item.tag == 50010 and result.get("sensor"):
        result["packet_type"] = f"{result['sensor']}_cfg"

    # Convenience: ISO time strings for the epoch timestamps
    for tkey in ("rtc_time", "gps_time"):
        if isinstance(result.get(tkey), (int, float)) and result[tkey] > 0:
            result[tkey + "_iso"] = datetime.datetime.fromtimestamp(
                result[tkey], tz=datetime.timezone.utc).isoformat()
    return result


def decode_bytes(data: bytes):
    """Decode a single norlog packet from raw CBOR bytes."""
    return decode_packet(loads(data))


def decode_file(data: bytes):
    """Decode all packets of a norlog SD-card log file (concatenated CBOR)."""
    packets = []
    for item in loads_all(data):
        pkt = decode_packet(item)
        if pkt is not None:
            packets.append(pkt)
    return packets
