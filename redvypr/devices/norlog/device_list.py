"""
Device list of the norlogs reachable from redvypr: one or more serial ports, and the members of
the Thread networks behind the gateway ports.

build_device_list() combines the state of one gateway (serial connection), the OpenThread
neighbor, child and router tables and the sources of received data packets into a list of
devices with connection type, role and link quality. build_devices() does this for all serial
ports (see choose_gateways() for the gateway of each Thread network) and merges a norlog that is
reachable both serially and over Thread into one entry.

Every entry has a 'key': the hardware ID of the norlog if known, otherwise 'port:<port>' (serial)
or 'rloc:<RLOC16>@<gateway port>' (Thread member whose info was not read yet). 'parent' is the
key of the gateway entry for Thread members ('' for serial entries), 'via' its serial port.

Entries keep 'next_hop' and 'path_cost' so a Thread topology map can be
drawn from the same data later.
"""

import re
import time

CONNECTION_SERIAL = "serial"
CONNECTION_THREAD = "thread"

ROLE_GATEWAY = "gateway"     # serial port, active gateway of its Thread network
ROLE_NODE = "node"           # serial port, not a gateway (role 'node', other gateway active, no network)
ROLE_MEMBER = "member"       # Thread member behind a gateway

# Role of a serial port (configuration)
PORT_ROLE_AUTO = "auto"         # may become gateway of its Thread network
PORT_ROLE_GATEWAY = "gateway"   # preferred gateway
PORT_ROLE_NODE = "node"         # only addressed directly, never the way into the Thread network
PORT_ROLES = (PORT_ROLE_AUTO, PORT_ROLE_GATEWAY, PORT_ROLE_NODE)

# State of a serial port
PORT_OPEN = "open"
PORT_CLOSED = "not opened"
PORT_ERROR = "error"            # could not be opened (used by another program?) or failed
PORT_GONE = "missing"           # configured, but not found (unplugged)

# Thread states in which a port can be the gateway of its network
_GATEWAY_STATES = ("leader", "router", "child")
_STATE_RANK = {"leader": 0, "router": 1, "child": 2}

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


def is_compact_info(info):
    """
    True for the compact CoAP 'info' of firmware >= 0.4.50 (the rest is in 'extinfo');
    older firmware and 'norlog info json' send everything (with 'firmware').
    """
    return bool(info) and 'firmware' not in info and 'device' not in info


def merge_info(ext, base):
    """
    Combine 'extinfo' and 'info' (firmware >= 0.4.50) into one info dict as older firmware
    sends it. Objects split over both parts (battery, gnss, thread) are merged one level
    deep; the values of base (read more often) win.
    """
    merged = dict(ext or {})
    for k, v in (base or {}).items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    return merged


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


def port_key(port):
    return f"port:{port}"


def rloc_key(rloc16, port):
    return f"rloc:{norm_rloc16(rloc16)}@{port}"


def network_id(status):
    """Thread network of a port: Extended PAN ID (else network name), '' without network."""
    status = status or {}
    if status.get("state") not in _GATEWAY_STATES:
        return ""
    return status.get("extpanid") or status.get("network_name") or ""


def choose_gateways(ports, previous=None):
    """
    The active gateway of each Thread network (design note doc/design_verbindungen.md).
    ports: list of dicts {name, role (PORT_ROLE_*), status (ot_cli.read_status), opened (order of
    opening, smaller = earlier)}; previous: {network: port name} of the last choice.
    Order: role 'gateway', then leader, router, child; on a tie the previous gateway, then the
    port opened first. Ports with role 'node' and ports without network are never chosen.
    Returns {network: port name}.
    """
    previous = previous or {}
    best = {}
    for p in ports:
        net = network_id(p.get("status"))
        if not net or p.get("role") == PORT_ROLE_NODE:
            continue
        rank = (0 if p.get("role") == PORT_ROLE_GATEWAY else 1,
                _STATE_RANK.get((p.get("status") or {}).get("state"), 9),
                0 if previous.get(net) == p["name"] else 1,
                p.get("opened", 0))
        if net not in best or rank < best[net][0]:
            best[net] = (rank, p["name"])
    return {net: name for net, (_rank, name) in best.items()}


def build_device_list(status, gateway_port="", serial_rx_age_s=None, data_sources=None, now=None,
                      infos=None, gateway_key=None, member_keys=None):
    """
    Args:
        status: dict from ot_cli.read_status() (may be empty)
        gateway_port: serial port of the gateway
        serial_rx_age_s: seconds since the last byte from the gateway
        data_sources: {source: {"last_seen": t, "packets": n, "mac": ...}} from '#NLD' lines
        infos: {key: info dict from 'norlog info json' / CoAP /info}
        gateway_key: key of the gateway (its hardware ID), default 'port:<gateway_port>'
        member_keys: {RLOC16: hardware ID} of the members whose info was read
    Returns:
        list of device dicts, gateway first, then members sorted by RLOC16
    """
    now = time.time() if now is None else now
    status = status or {}
    data_sources = data_sources or {}
    member_keys = {norm_rloc16(k): v for k, v in (member_keys or {}).items()}

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
    own_rloc = gateway["rloc16"]

    def is_own(ext, rloc):
        """Entry of the gateway itself (the router table of a leader lists it, also with
        Extended MAC 0000000000000000)."""
        return ext == own_ext or (own_rloc and norm_rloc16(rloc) == own_rloc) or not ext.strip("0")

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
        if not ext or is_own(ext, n.get("RLOC16")):
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
        if not ext or is_own(ext, r.get("RLOC16")):
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
    # The gateway outputs its own packets as sink too (firmware >= 0.4.33), and the RLOC16 of a
    # member changes with its role: match also by the hardware ID ('mac' of the packets)
    infos = infos or {}
    gateway_key = gateway_key or port_key(gateway_port)
    by_rloc = {e["rloc16"]: e for e in members.values() if e["rloc16"]}
    by_hwid = {}
    for e in members.values():
        hwid = member_keys.get(e["rloc16"])
        if hwid:
            by_hwid[hwid] = e
    gateway_hwid = gateway_key if not gateway_key.startswith("port:") else None
    for source, info in data_sources.items():
        age = now - info.get("last_seen", 0)
        rloc = norm_rloc16(source)
        mac = info.get("mac")
        if (own_rloc and rloc == own_rloc) or (mac and mac == gateway_hwid):
            e = gateway
        else:
            e = by_rloc.get(rloc) or (by_hwid.get(mac) if mac else None)
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

    # --- keys and device info (norlog info / CoAP /info) ----------------------
    gateway["key"] = gateway_key
    gateway["parent"] = ""
    gateway["via"] = ""
    for e in members.values():
        e["key"] = (member_keys.get(e["rloc16"]) or e.get("mac") or
                    (rloc_key(e["rloc16"], gateway_port) if e["rloc16"] else f"id:{e['id']}"))
        e["parent"] = gateway_key
        e["via"] = gateway_port
    _apply_info(gateway, infos.get(gateway_key))
    for e in members.values():
        _apply_info(e, infos.get(e["key"]))

    ordered = sorted(members.values(), key=lambda e: (e["rloc16"] or "~", e["id"]))
    return [gateway] + ordered


def port_entry(name, state=PORT_CLOSED, role=PORT_ROLE_AUTO, key=None, description="", error="", infos=None):
    """Entry of a serial port that is not open (or not a gateway): no Thread data."""
    key = key or port_key(name)
    e = {
        "id": name, "key": key, "parent": "", "via": "", "extaddr": "", "rloc16": "",
        "connection": CONNECTION_SERIAL, "port": name, "port_state": state, "port_role": role,
        "port_description": description, "port_error": error,
        "role": ROLE_NODE, "thread_role": "", "link": "serial", "quality": QUALITY_UNKNOWN,
        "age_s": None, "rssi_avg": None, "rssi_last": None, "lq_in": None, "lq_out": None,
        "path_cost": 0, "next_hop": None, "packets": 0, "last_data_s": None,
    }
    if not key.startswith("port:"):
        e["hwid"] = key
    _apply_info(e, (infos or {}).get(key))
    return e


def build_devices(ports, infos=None, now=None):
    """
    Device list of all serial ports.

    ports: list of dicts, one per serial port (found or configured), in display order:
        name, state (PORT_*), role (PORT_ROLE_*), description, error,
        key: hardware ID of the norlog at the port if known (else 'port:<name>'),
        active: True if it is the active gateway of its Thread network,
        status: ot_cli.read_status() of the port (open ports), rx_age_s,
        data_sources: '#NLD' sources received at this port,
        member_keys: {RLOC16: hardware ID} of the members seen through this port.
    Returns the list of entries: each serial port, the members of an active gateway right after
    it (with 'parent' = key of the gateway). A norlog that is a member of a gateway and at a serial
    port itself appears once, at its port; its Thread link values are kept in 'thread_link'.
    """
    infos = infos or {}
    serial = []
    members = []
    for p in ports:
        name = p["name"]
        key = p.get("key") or port_key(name)
        if p.get("state") != PORT_OPEN:
            serial.append(port_entry(name, p.get("state", PORT_CLOSED), p.get("role", PORT_ROLE_AUTO), key,
                                     p.get("description", ""), p.get("error", ""), infos))
            continue
        entries = build_device_list(p.get("status"), gateway_port=name, serial_rx_age_s=p.get("rx_age_s"),
                                    data_sources=p.get("data_sources") if p.get("active") else None,
                                    now=now, infos=infos, gateway_key=key, member_keys=p.get("member_keys"))
        gw = entries[0]
        gw.update(port_state=PORT_OPEN, port_role=p.get("role", PORT_ROLE_AUTO),
                  port_description=p.get("description", ""), port_error=p.get("error", ""),
                  network=network_id(p.get("status")))
        if not p.get("active"):
            gw["role"] = ROLE_NODE
        serial.append(gw)
        if p.get("active"):
            members.extend(entries[1:])

    # A member that is also at a serial port: one entry at the port
    by_ext = {e["extaddr"]: e for e in serial if e.get("extaddr")}
    by_key = {e["key"]: e for e in serial}
    out_members = []
    for m in members:
        twin = by_key.get(m["key"]) or by_ext.get(m.get("extaddr"))
        if twin is not None and twin is not m:
            twin["thread_link"] = {k: m.get(k) for k in ("rloc16", "link", "quality", "rssi_avg", "rssi_last",
                                                         "lq_in", "lq_out", "path_cost", "next_hop", "via")}
            twin["packets"] = max(twin.get("packets", 0), m.get("packets", 0))
            continue
        out_members.append(m)

    result = []
    for e in serial:
        result.append(e)
        result.extend(m for m in out_members if m["parent"] == e["key"])
    return result
