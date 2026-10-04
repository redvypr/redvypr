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
}

# cbor_source_id_t
SOURCE_IDS = {0: "internal", 1: "i2c0", 2: "i2c1", 3: "uart0", 4: "uart1", 5: "spi0", 6: "spi1"}

# cbor_raw_type_t
RAW_TYPES = {0: "serial", 1: "nmea", 2: "ubx"}

CBOR_TAG_EPOCH = 1


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

    result = {"packet_type": PACKET_TAGS[item.tag]}
    for key, value in item.value.items():
        name = KEYS.get(key, f"key_{key}")
        result[name] = _convert_value(name, value)

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
