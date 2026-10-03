"""
Device list of a norlog network as seen from the gateway.

Combines the gateway's own state (serial connection), the OpenThread
neighbor, child and router tables and the sources of received data packets
into one list of devices with connection type, role and link quality.

Entries keep 'next_hop' and 'path_cost' so a Thread topology map can be
drawn from the same data later.
"""

import re
import time

CONNECTION_SERIAL = "serial"
CONNECTION_THREAD = "thread"

ROLE_GATEWAY = "gateway"
ROLE_MEMBER = "member"

# Quality levels (best first)
QUALITY_GOOD = "good"
QUALITY_FAIR = "fair"
QUALITY_POOR = "poor"
QUALITY_NONE = "none"
QUALITY_UNKNOWN = "n/a"

_RLOC16_RE = re.compile(r"^(0x)?([0-9a-fA-F]{4})$")

# Data packets older than this are not shown as "data only" devices anymore
DATA_SOURCE_TIMEOUT_S = 600

# The serial link counts as good if the gateway sent something recently
SERIAL_GOOD_S = 30


def norm_rloc16(value):
    """'c801', '0xC801' -> '0xc801'; anything else is returned unchanged."""
    if value is None:
        return ""
    m = _RLOC16_RE.match(str(value).strip())
    return f"0x{m.group(2).lower()}" if m else str(value).strip()


def _int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def quality_from_lq(lq):
    """OpenThread link quality 0..3 (from the link margin)."""
    return {3: QUALITY_GOOD, 2: QUALITY_FAIR, 1: QUALITY_POOR, 0: QUALITY_NONE}.get(lq, QUALITY_UNKNOWN)


def quality_from_rssi(rssi):
    """Rough classification of an average RSSI in dBm."""
    if rssi is None or rssi >= 127 or rssi <= -127:     # 127 = not available in OpenThread
        return QUALITY_UNKNOWN
    if rssi >= -70:
        return QUALITY_GOOD
    if rssi >= -85:
        return QUALITY_FAIR
    return QUALITY_POOR


def quality_from_path_cost(cost):
    """
    Route quality of a multi-hop router. Thread link costs per hop:
    LQ 3 -> 1, LQ 2 -> 2, LQ 1 -> 4; 16 means unreachable.
    """
    if cost is None:
        return QUALITY_UNKNOWN
    if cost >= 16:
        return QUALITY_NONE
    if cost <= 3:
        return QUALITY_GOOD
    if cost <= 6:
        return QUALITY_FAIR
    return QUALITY_POOR


_ORDER = [QUALITY_GOOD, QUALITY_FAIR, QUALITY_POOR, QUALITY_NONE]


def worst(*qualities):
    known = [q for q in qualities if q in _ORDER]
    return max(known, key=_ORDER.index) if known else QUALITY_UNKNOWN


def _apply_info(entry, info):
    """Copy the main fields of a norlog info (norlog info json / CoAP /info) into an entry."""
    if not info:
        return
    entry["info"] = info
    if "error" in info:
        # The last good values (if any) are kept next to the error of the last read
        entry["info_error"] = info["error"]
        if len(info) == 1:
            return
    entry["firmware"] = info.get("image") or info.get("firmware", "")
    if info.get("sn"):
        entry["sn"] = info["sn"]
    batt = info.get("battery") or {}
    entry["battery_mv"] = batt.get("mv")
    entry["battery_soc"] = batt.get("soc")
    entry["battery_charging"] = batt.get("charging")
    entry["battery_current_ma"] = batt.get("current_ma")
    entry["board_temp_c"] = info.get("board_temp_c")
    if info.get("hwid"):
        entry["hwid"] = info["hwid"]


def build_device_list(status, gateway_port="", serial_rx_age_s=None, data_sources=None, now=None,
                      infos=None):
    """
    Args:
        status: dict from ot_cli.read_status() (may be empty)
        gateway_port: serial port of the gateway
        serial_rx_age_s: seconds since the last byte from the gateway
        data_sources: {source: {"last_seen": t, "packets": n, "mac": ...}} from '#NLD' lines
        infos: {"gateway" or RLOC16: info dict from 'norlog info json' / CoAP /info}
    Returns:
        list of device dicts, gateway first, then members sorted by RLOC16
    """
    now = time.time() if now is None else now
    status = status or {}
    data_sources = data_sources or {}

    # --- gateway (serial) -------------------------------------------------
    if serial_rx_age_s is None:
        serial_q = QUALITY_UNKNOWN
    elif serial_rx_age_s <= SERIAL_GOOD_S:
        serial_q = QUALITY_GOOD
    else:
        serial_q = QUALITY_POOR
    own_ext = status.get("extaddr", "")
    gateway = {
        "id": own_ext or gateway_port or "gateway",
        "extaddr": own_ext,
        "rloc16": norm_rloc16(status.get("rloc16", "")),
        "connection": CONNECTION_SERIAL,
        "port": gateway_port,
        "role": ROLE_GATEWAY,
        "thread_role": status.get("state", ""),
        "link": "serial",
        "quality": serial_q,
        "age_s": serial_rx_age_s,
        "rssi_avg": None, "rssi_last": None, "lq_in": None, "lq_out": None,
        "path_cost": 0, "next_hop": None,
        "packets": 0, "last_data_s": None,
    }

    members = {}

    def entry(ext, rloc):
        key = ext or rloc
        if key not in members:
            members[key] = {
                "id": key, "extaddr": ext, "rloc16": rloc,
                "connection": CONNECTION_THREAD, "port": "",
                "role": ROLE_MEMBER, "thread_role": "", "link": "",
                "quality": QUALITY_UNKNOWN, "age_s": None,
                "rssi_avg": None, "rssi_last": None, "lq_in": None, "lq_out": None,
                "path_cost": None, "next_hop": None,
                "packets": 0, "last_data_s": None,
            }
        return members[key]

    # --- direct neighbors (RSSI) --------------------------------------------
    for n in status.get("neighbors", []):
        ext = n.get("Extended MAC", "")
        if not ext or ext == own_ext:
            continue
        e = entry(ext, norm_rloc16(n.get("RLOC16")))
        e["thread_role"] = "router" if n.get("Role", "").strip() == "R" else "child"
        e["link"] = "direct"
        e["rssi_avg"] = _int(n.get("Avg RSSI"))
        e["rssi_last"] = _int(n.get("Last RSSI"))
        e["age_s"] = _int(n.get("Age"))

    # --- children (link quality towards the gateway) ------------------------
    for c in status.get("children", []):
        ext = c.get("Extended MAC", "")
        if not ext:
            continue
        e = entry(ext, norm_rloc16(c.get("RLOC16")))
        e["thread_role"] = "child"
        e["link"] = "direct"
        e["lq_in"] = _int(c.get("LQ In"))
        if e["age_s"] is None:
            e["age_s"] = _int(c.get("Age"))
        e["path_cost"] = 1
        e["next_hop"] = gateway["rloc16"]

    # --- routers (direct and multi-hop) -----------------------------------
    rloc_by_router_id = {}
    for r in status.get("routers", []):
        rid = _int(r.get("ID"))
        if rid is not None:
            rloc_by_router_id[rid] = norm_rloc16(r.get("RLOC16"))
    leader_id = status.get("leader_router_id")
    for r in status.get("routers", []):
        ext = r.get("Extended MAC", "")
        if not ext or ext == own_ext:
            continue
        e = entry(ext, norm_rloc16(r.get("RLOC16")))
        e["thread_role"] = "leader" if _int(r.get("ID")) == leader_id else "router"
        e["path_cost"] = _int(r.get("Path Cost"))
        if _int(r.get("Link")) == 1:
            # Direct radio link to the gateway: edge gateway <-> router
            e["link"] = "direct"
            e["lq_in"] = _int(r.get("LQ In"))
            e["lq_out"] = _int(r.get("LQ Out"))
            e["next_hop"] = gateway["rloc16"]
        else:
            # Reached via another router; LQ values of the table are meaningless here
            if not e["link"]:
                e["link"] = "multi-hop"
            nh = _int(r.get("Next Hop"))
            e["next_hop"] = rloc_by_router_id.get(nh) if nh not in (None, 63) else None
        if e["age_s"] is None:
            e["age_s"] = _int(r.get("Age"))

    # --- data sources ('#NLD <source> ...') -------------------------------
    by_rloc = {e["rloc16"]: e for e in members.values() if e["rloc16"]}
    for source, info in data_sources.items():
        age = now - info.get("last_seen", 0)
        rloc = norm_rloc16(source)
        e = by_rloc.get(rloc)
        if e is None:
            if age > DATA_SOURCE_TIMEOUT_S:
                continue
            e = entry("", rloc)
            e["link"] = "data only"
            by_rloc[rloc] = e
        e["packets"] = info.get("packets", 0)
        e["last_data_s"] = age
        if info.get("mac"):
            e["mac"] = info["mac"]

    # --- quality ------------------------------------------------------------
    for e in members.values():
        if e["link"] == "multi-hop":
            # No direct radio link: rate the route by its path cost
            e["quality"] = quality_from_path_cost(e["path_cost"])
        elif e["link"] == "data only":
            e["quality"] = QUALITY_UNKNOWN
        else:
            q = [quality_from_rssi(e["rssi_avg"]), quality_from_lq(e["lq_in"])]
            if e["lq_out"] is not None:
                q.append(quality_from_lq(e["lq_out"]))
            e["quality"] = worst(*q)

    # --- device info (norlog info / CoAP /info), keyed 'gateway' or RLOC16 ---
    infos = infos or {}
    _apply_info(gateway, infos.get("gateway"))
    for e in members.values():
        _apply_info(e, infos.get(e["rloc16"]))

    ordered = sorted(members.values(), key=lambda e: (e["rloc16"] or "~", e["id"]))
    return [gateway] + ordered
