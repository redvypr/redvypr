import typing
import datetime
import time
import logging
from redvypr.redvypr_address import RedvyprAddress

logger = logging.getLogger('redvypr.metadata')

# Constraint keys that describe the validity period or the origin of an entry.
# All other constraint keys are its context (e.g. 'site'): entries with the same
# key, value and context describe the same metadata.
TIME_KEYS = ('valid_from', 'valid_until')
NON_CONTEXT_KEYS = TIME_KEYS + ('hostinfo',)

# Address entries naming the source of a datastream
SOURCE_KEYS = ('device', 'deviceid', 'sensorid', 'sensor')

# Parsed stored addresses (address string -> (RedvyprAddress, specificity, source)),
# get_metadata() does not parse every stored address again for every query
_ADDRESS_CACHE = {}
_ADDRESS_CACHE_MAX = 100000


def to_datetime(t):
    """
    Time of a constraint as timezone aware UTC datetime (None stays None).
    Accepts datetime (naive = UTC), ISO strings (also with 'Z') and unix time.
    """
    if t is None:
        return None
    if isinstance(t, datetime.datetime):
        dt = t
    elif isinstance(t, (int, float)):
        return datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    else:
        dt = datetime.datetime.fromisoformat(str(t).strip().replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def to_isotime(t):
    """Canonical ISO string (UTC) of a constraint time, None stays None."""
    dt = to_datetime(t)
    return None if dt is None else dt.isoformat()


def get_context(constraints):
    """The context of an entry: its constraints without validity period and hostinfo."""
    return {k: v for k, v in (constraints or {}).items() if k not in NON_CONTEXT_KEYS}


def get_source(raddress):
    """The source entries (device, deviceid, sensorid, sensor) an address names."""
    source = {}
    for k in SOURCE_KEYS:
        try:
            v = getattr(raddress, k)
        except Exception:
            v = None
        if v is not None:
            source[k] = v
    return source


def _parsed_address(address_str):
    """Cached (RedvyprAddress, number of datakey entries, source) of a stored address."""
    try:
        return _ADDRESS_CACHE[address_str]
    except KeyError:
        pass
    raddr = RedvyprAddress(address_str)
    parsed = (raddr, len(raddr.get_datakeyentries()), get_source(raddr))
    if len(_ADDRESS_CACHE) >= _ADDRESS_CACHE_MAX:
        _ADDRESS_CACHE.clear()
    _ADDRESS_CACHE[address_str] = parsed
    return parsed


def create_metadata_dict(
        address: str | RedvyprAddress,
        metadata: dict,
        hostinfo: dict | None = None,
        constraints: dict | None = None,
        valid_from: datetime.datetime | str | None = None,
        valid_until: datetime.datetime | str | None = None
) -> dict:
    """
    Adds metadata to a specific address with optional context or time constraints.

    Parameters
    ----------
    address : str or RedvyprAddress
        The target network address or pattern to attach the metadata to.
    metadata : dict
        A dictionary of key-value pairs representing the metadata to add.
    hostinfo : dict, optional
        A dictionary of the redvypr hostinfo
    constraints : dict, optional
        Logical context conditions (e.g., ``{'protocol': 'HTTP'}``) that must
        be met for this metadata to be considered active.
    valid_from : datetime.datetime or str, optional
        The UTC starting timestamp for the metadata validity. If None, it
        defaults to the host instance startup time (`self.hostinfo.tstart`).
        If input is datetime object without timezone, UTC is expected and attached.
    valid_until : datetime.datetime or str, optional
        The UTC ending timestamp for the metadata validity. If None, the
        metadata remains valid indefinitely until explicitly overwritten or removed.
        If input is datetime object without timezone, UTC is expected and attached.

    Returns
    -------
    metadata dictionary

    Notes
    -----
    This method creates a metadata dictionary into a standardized list of
    independent key-value-constraint objects and returns the dictionary
    """
    funcname = f"{__name__}.create_metadata_dict():"
    logger.debug(funcname)

    address_str = str(RedvyprAddress(address))

    # 1. Build unified constraints dictionary
    final_constraints = {}
    if constraints:
        final_constraints.update(constraints)

    # Helper for ISO timestamps (canonical UTC form, naive = UTC)
    format_time = to_isotime


    # Set up timeline bounds
    if valid_from is not None:
        final_constraints['valid_from'] = format_time(valid_from)
    else:
        if hostinfo:
            tstart = hostinfo["tstart"]
        else:
            tstart = time.time()

        dt_utc = datetime.datetime.fromtimestamp(tstart, datetime.timezone.utc)
        final_constraints['valid_from'] = dt_utc.isoformat()

    if valid_until is not None:
        final_constraints['valid_until'] = format_time(valid_until)

    # Attach audit telemetry
    final_constraints['hostinfo'] = hostinfo

    # 2. Package into standardized flat list structure. Every entry gets its own
    # constraints dict: a later change of one key sets 'valid_until' in the
    # constraints of that entry only (a shared dict expired all keys of the call).
    metadata_list = []
    for key, value in metadata.items():
        metadata_list.append({
            'key': key,
            'value': value,
            'constraints': dict(final_constraints)
        })

    metadata_dict = {
        address_str: metadata_list
    }

    return metadata_dict


def add_metadata_to_entries(
        metadata: dict,
        metadata_entries: dict,
        packetfilter_address: str | dict | None = None
) -> dict:
    """
    Merges incoming metadata updates into a target metadata storage structure.

    An entry describes the period in which a value was valid. Entries with the
    same key, value and context (constraints without valid_from, valid_until and
    hostinfo) are the same metadata:

    - same value, periods overlapping or touching: merged into one entry (no
      new entry, the begin moves back / the end moves forward if needed); sending
      the same metadata again (or after a restart) does not add anything
    - same value after a gap (A -> B -> A): new entry (history)
    - other value: the open entry of the same context ends at the begin of the new
      one (valid_until), or the new one ends at the begin of a later entry
    - entries of another context are not touched

    Only the entries of the same address are looked at.

    Parameters
    ----------
    metadata : dict
        The incoming dictionary containing new metadata address blocks and entries.
        Dictionary is created with `create_metadata_dict()`
    metadata_entries : dict
        The target storage dictionary (e.g., `metadata_dict['metadata']`) to modify.
    packetfilter_address : str or dict, optional
        A fallback or context packet/address used to dynamically inherit missing
        routing metrics (UUID, device, packetid) via RedvyprAddress merging. An
        address that names its source itself (device, deviceid or sensorid) only
        gets the UUID: it is valid for all packets of that source.

    Returns
    -------
    status : dict
        A dictionary containing processing flags:
        - ``status['metadata_changed']`` (bool): True if entries were added or modified.
    """
    funcname = f"{__name__}.add_metadata_to_entries():"
    status = {'metadata_changed': False}

    try:
        raddress_data = RedvyprAddress(packetfilter_address) if packetfilter_address else None
        for address_str_work, incoming_entries in metadata.items():

            # Apply dynamic address / packet filtering path matching
            if raddress_data is not None:
                raddress = RedvyprAddress(address_str_work)
                uuid = raddress_data.uuid if (raddress.uuid is None) else None
                if raddress.device is None and raddress.deviceid is None and raddress.sensorid is None:
                    device = raddress_data.device
                    packetid = raddress_data.packetid if (raddress.packetid is None) else None
                else:
                    # The address names its source: valid for all its packets
                    device = None
                    packetid = None
                raddress_final = RedvyprAddress(
                    raddress, uuid=uuid, device=device, packetid=packetid
                )
                address_str = raddress_final.to_address_string()
            else:
                address_str = address_str_work

            stored_list = metadata_entries.setdefault(address_str, [])
            for new_entry in incoming_entries:
                if _merge_entry(stored_list, new_entry):
                    status['metadata_changed'] = True
                    logger.debug(f"{funcname} {new_entry['key']}={new_entry['value']!r} for {address_str}")

            if not stored_list:
                metadata_entries.pop(address_str, None)

    except Exception:
        logger.warning(f"{funcname} Could not update metadata", exc_info=True)

    return status


def _merge_entry(stored_list, new_entry):
    """
    Merge one entry into the entries of an address (rules see
    add_metadata_to_entries()). Returns True if the stored entries changed.
    """
    key = new_entry['key']
    value = new_entry['value']
    new_constraints = dict(new_entry.get('constraints') or {})
    context = get_context(new_constraints)
    new_from = to_datetime(new_constraints.get('valid_from'))
    if new_from is None:
        new_from = datetime.datetime.now(datetime.timezone.utc)
    new_until = to_datetime(new_constraints.get('valid_until'))

    same = [e for e in stored_list
            if e['key'] == key and get_context(e.get('constraints')) == context]

    # 1. Same value with an overlapping or touching period: one entry
    for e in same:
        if e['value'] != value:
            continue
        c = e['constraints']
        e_from, e_until = to_datetime(c.get('valid_from')), to_datetime(c.get('valid_until'))
        if (e_from is None or new_until is None or e_from <= new_until) and \
                (e_until is None or e_until >= new_from):
            changed = False
            if e_from is not None and new_from < e_from:
                c['valid_from'] = new_from.isoformat()
                changed = True
            if e_until is not None and (new_until is None or new_until > e_until):
                if new_until is None:
                    c.pop('valid_until', None)
                else:
                    c['valid_until'] = new_until.isoformat()
                changed = True
            return changed

    # 2. Other value: the open entry before ends now, a later entry ends the new one
    for e in same:
        if e['value'] == value:
            continue
        c = e['constraints']
        e_from, e_until = to_datetime(c.get('valid_from')), to_datetime(c.get('valid_until'))
        if e_from is None or e_from <= new_from:
            if e_until is None or e_until > new_from:
                c['valid_until'] = new_from.isoformat()
        elif new_until is None or new_until > e_from:
            new_until = e_from      # inserted before a later value

    new_constraints['valid_from'] = new_from.isoformat()
    if new_until is None:
        new_constraints.pop('valid_until', None)
    else:
        new_constraints['valid_until'] = new_until.isoformat()
    stored = dict(new_entry)
    stored['constraints'] = new_constraints
    stored_list.append(stored)
    return True


def do_metadata(
        data: dict,
        metadata_dict: dict,
        auto_add_packetfilter: bool = True
) -> dict:
    """
    Processes incoming metadata commands to alter or append to the central storage.

    Handles hard physical deletions via ``_metadata_remove`` and delegates
    chronological updates, constraint deduplication, and appending to
    ``add_metadata_to_entries()`` via the ``_metadata`` command payload.

    Parameters
    ----------
    data : dict
        The incoming data packet containing instructions (``_metadata`` or
        ``_metadata_remove``).
    metadata_dict : dict
        The global central storage dictionary holding the master 'metadata' structure.
    auto_add_packetfilter : bool, default True
        If True, enriches and normalizes the target address string using
        available packet metadata (UUID, device, packet ID).

    Returns
    -------
    status : dict
        A dictionary containing processing flags:
        - ``status['metadata_changed']`` (bool): True if the global master state was modified.

    See Also
    --------
    add_metadata_to_entries : The underlying utility handling the append/historize logic.
    get_metadata : Read and filter the data structured by this function.
    """
    funcname = f"{__name__}.do_metadata():"
    status = {'metadata_changed': False}
    #print("Doing metadata")
    if 'metadata' not in metadata_dict:
        metadata_dict['metadata'] = {}

    # ==========================================
    # 1. REMOVE ENTRIES (HARD PHYSICAL DELETION)
    # ==========================================
    if '_metadata_remove' in data.keys():
        for address_str, removedata in data['_metadata_remove'].items():
            raddress_str = RedvyprAddress(address_str)
            remove_keys = removedata.get('keys', [])
            remove_mode = removedata.get('mode', 'exact')

            if remove_mode == "exact":
                address_strings = [address_str]
            else:
                address_strings = [
                    addr_test for addr_test in metadata_dict['metadata'].keys()
                    if raddress_str.matches(RedvyprAddress(addr_test))
                ]

            for addr in address_strings:
                if addr not in metadata_dict['metadata']:
                    continue

                if len(remove_keys) == 0:
                    metadata_dict['metadata'].pop(addr)
                    status['metadata_changed'] = True
                    logger.info(f"{funcname} Completely removed address from metadata storage: {addr}")
                else:
                    original_len = len(metadata_dict['metadata'][addr])

                    metadata_dict['metadata'][addr] = [
                        entry for entry in metadata_dict['metadata'][addr]
                        if entry['key'] not in remove_keys
                    ]

                    if len(metadata_dict['metadata'][addr]) != original_len:
                        status['metadata_changed'] = True
                        logger.info(f"{funcname} Hard-removed keys {remove_keys} from {addr}")

                    if len(metadata_dict['metadata'][addr]) == 0:
                        metadata_dict['metadata'].pop(addr)

    # ==========================================
    # 2. ADD ENTRIES (HISTORIZATION & APPENDING)
    # ==========================================
    if '_metadata' in data.keys():
        logger.debug("Adding metadata")
        # Delegate execution to the utility function
        filter_address = RedvyprAddress(data) if auto_add_packetfilter else None

        add_status = add_metadata_to_entries(
            metadata=data['_metadata'],
            metadata_entries=metadata_dict['metadata'],
            packetfilter_address=filter_address
        )

        #logger.debug("Adding metadata done")

        # Merge change status
        if add_status.get('metadata_changed'):
            status['metadata_changed'] = True

    return status


def get_metadata(
        statistics: dict,
        address: None | str | RedvyprAddress = None,
        mode: typing.Literal["merge", "expanded", "all"] = "expanded",
        context: dict | None = None,
        at_time: datetime.datetime | str | None = None,
        time_range: tuple[
                        datetime.datetime | str, datetime.datetime | str] | None = None
) -> dict | list:
    """
    Retrieves and filters active metadata for a given address based on
    chronological and logical context constraints.

    Parameters
    ----------
    statistics : dict
        The global central storage dictionary containing master data under 'metadata'.
    address : str or RedvyprAddress, optional
        The query address filter. If None, defaults to "@" (matches everything).
    mode : {'expanded', 'merge', 'all'}, default 'expanded'
        Determines the output schema format.
        'all' returns the complete historical list of matching entries (ignores time).
        'expanded'/'merge' filter by time and return a transformed dictionary.
    context : dict, optional
        A dictionary of key-value pairs representing the current runtime context.
    at_time : datetime.datetime or str, optional
        A specific UTC timestamp to query the metadata state for ("time travel").
        Mutually exclusive with 'time_range'. Ignored if mode='all'.
    time_range : tuple of (start, end), optional
        A time window (start_time, end_time) to fetch historical data. Matches any
        entry that was valid at some point during this window. Ignored if mode='all'.

    Returns
    -------
    metadata_return : dict or list
        A transformed dictionary or the full raw history list (if mode='all').
    """
    funcname = f"{__name__}.get_metadata():"
    logger.debug(funcname)

    # Validierung nur nötig, wenn wir überhaupt nach Zeit filtern
    if mode != 'all' and at_time and time_range:
        raise ValueError(
            "Parameters 'at_time' and 'time_range' are mutually exclusive.")

    metadata_return = {} if mode != 'all' else []

    if address is None:
        raddress = RedvyprAddress("@")
    else:
        raddress = RedvyprAddress(address)
    # A query naming its source (e.g. d:ctd_01) gets only metadata of addresses whose
    # source entries it names too: '@di:A1B2C3' must not apply to 'temp@d:ctd_01' just
    # because neither address contradicts the other. A query without a source
    # ('@', 'temp@') gets all matching metadata.
    query_source = get_source(raddress)

    if mode == 'merge':
        metadata_return[raddress.to_address_string()] = {}

    # 1. Sort by specificity using DSU (parsed addresses are cached)
    decorated = [
        (_parsed_address(astr)[1], astr)
        for astr in list(statistics.get('metadata', {}).keys())
    ]
    decorated.sort()
    metadata_keys_sorted = [astr for nentries, astr in decorated]

    # 2. Normalize the evaluation time or range (nur wenn mode != 'all')
    target_time = None
    range_start = None
    range_end = None

    if mode != 'all':
        # Compared as datetimes ('Z' and '+00:00', naive = UTC)
        if time_range:
            range_start = to_datetime(time_range[0])
            range_end = to_datetime(time_range[1])
        else:
            if at_time is None:
                target_time = datetime.datetime.now(datetime.timezone.utc)
            else:
                target_time = to_datetime(at_time)

    # 3. Iterate sorted structural matches
    for astr in metadata_keys_sorted:
        raddr, _, stored_source = _parsed_address(astr)
        if query_source and any(query_source.get(k) != v for k, v in stored_source.items()):
            continue
        if raddress.matches(raddr):
            stored_list = statistics['metadata'].get(astr)

            if not isinstance(stored_list, list):
                continue

            resolved_dict = {}

            for entry in stored_list:
                constraints = entry.get('constraints', {})

                # --- A. TIME DIMENSION FILTER (wird bei 'all' übersprungen) ---
                if mode != 'all':
                    valid_from = to_datetime(constraints.get('valid_from'))
                    valid_until = to_datetime(constraints.get('valid_until'))

                    if time_range:
                        if valid_from and valid_from > range_end:
                            continue
                        if valid_until and valid_until < range_start:
                            continue
                    else:
                        # valid_until is the begin of the next value (exclusive)
                        if valid_from and target_time < valid_from:
                            continue
                        if valid_until and target_time >= valid_until:
                            continue

                # --- B. LOGICAL CONTEXT FILTER ---
                context_mismatch = False
                if context:
                    for c_key, c_value in context.items():
                        if c_key in constraints and constraints[c_key] != c_value:
                            context_mismatch = True
                            break

                if context_mismatch:
                    continue

                # --- C. OUTPUT ROUTING BASED ON MODE ---
                if mode == 'all':
                    enriched_entry = entry.copy()
                    enriched_entry['source_address'] = astr
                    metadata_return.append(enriched_entry)
                else:
                    # 'resolved_dict' wird nur für merge/expanded befüllt
                    resolved_dict[entry['key']] = entry['value']

            # Wenn wir im 'all'-Modus sind, springen wir direkt zum nächsten Adress-Eintrag.
            # Das verhindert, dass wir unnötig leere 'resolved_dict' prüfen oder befüllen.
            if mode == 'all':
                continue

            if not resolved_dict:
                continue

            # 4. Route output configuration for 'merge' and 'expanded'
            if mode == 'merge':
                metadata_return[raddress.to_address_string()].update(resolved_dict)
            else:
                if astr not in metadata_return:
                    metadata_return[astr] = {}
                metadata_return[astr].update(resolved_dict)

    if mode == 'merge':
        return metadata_return[raddress.to_address_string()]
    else:
        return metadata_return


def normalize_metadata(metadata, hostinfo=None):
    """
    Metadata of a configuration in the storage format {address: [entries]}.

    Accepts the storage format (as saved by Redvypr.save_config(), with history
    and constraints) and the simple format {address: {key: value}} (e.g. written
    by hand or by older redvypr versions); simple values get the default
    constraints of create_metadata_dict().
    """
    result = {}
    for addr, md in (metadata or {}).items():
        if isinstance(md, list):
            entries = [dict(e) for e in md if isinstance(e, dict) and 'key' in e and 'value' in e]
            result.setdefault(addr, []).extend(entries)
        elif isinstance(md, dict):
            for addr_tmp, entries in create_metadata_dict(addr, md, hostinfo=hostinfo).items():
                result.setdefault(addr_tmp, []).extend(entries)
        else:
            raise ValueError(f"metadata of {addr!r} must be a list of entries or a dict, not {type(md).__name__}")
    return result


def create_metadatapacket(metadict=None, hostinfo=None, device_info=None):
    if device_info:
        hostinfo = device_info["hostinfo"]
    datapacket = {}
    datapacket['_metadata'] = {}
    for addr,metadata in metadict.items():
        if isinstance(addr,str):
            try:
                RedvyprAddress(addr) # Test if this is a valid RedvyprAddress
            except:
                raise ValueError(f"key {str(addr)} of metadict dictionary must be valid RedvyprAddress string")

            # create_metadata_dict() returns {address: [entries]}, the format of '_metadata'
            metadata_address = create_metadata_dict(addr, metadata, hostinfo=hostinfo)
            datapacket['_metadata'].update(metadata_address)
        else:
            raise ValueError(
                f"key {str(addr)} of metadict dictionary must be valid RedvyprAddress string")

    return datapacket


def add_metadata2datapacket(
        datapacket,
        address=None,
        datakey=None,
        metakey=None,
        metadata=None,
        metadict=None,
        hostinfo=None,
        device_info=None,
        constraints=None
):
    """
    Adds or updates metadata inside a Redvypr datapacket using the advanced
    list-of-dicts format required by add_metadata_to_entries().
    """
    # 1. Hostinfo aus Device-Info extrahieren, falls übergeben
    if device_info and "hostinfo" in device_info:
        hostinfo = device_info["hostinfo"]

    # 2. RedvyprAddress ermitteln und normalisieren
    raddress = None
    if address is not None:
        raddress = RedvyprAddress(address)
    elif datakey is not None:
        try:
            # Versuche Adresse aus dem Datapacket selbst abzuleiten
            raddress = RedvyprAddress(datapacket, datakey=datakey)
        except Exception:
            logger.info('Could not create address from datapacket', exc_info=True)
            raddress = RedvyprAddress(datakey=datakey)

    if raddress is None:
        raise ValueError("You must provide either a valid 'address' or 'datakey'.")

    address_str = raddress.to_address_string()

    # 3. Sicherstellen, dass die Basisstruktur im Datapacket existiert
    if '_metadata' not in datapacket:
        datapacket['_metadata'] = {}
    if address_str not in datapacket['_metadata']:
        datapacket['_metadata'][address_str] = []

    # 4. Standard-Constraints vorbereiten (z.B. für Historisierung)
    constraints = dict(constraints) if constraints else {}
    if hostinfo:
        constraints['hostinfo'] = hostinfo
    # Valid from the time of the packet: a changed value ends the old one there.
    # Sending the same metadata again does not add an entry (add_metadata_to_entries).
    if constraints.get('valid_from') is None:
        try:
            constraints['valid_from'] = to_isotime(float(datapacket['_redvypr']['t']))
        except (KeyError, TypeError, ValueError):
            constraints['valid_from'] = to_isotime(time.time())
    else:
        constraints['valid_from'] = to_isotime(constraints['valid_from'])
    if constraints.get('valid_until') is not None:
        constraints['valid_until'] = to_isotime(constraints['valid_until'])

    # 5. Daten standardisiert in die Liste pushen
    # Fall A: Einzelner Metadaten-Eintrag (metakey + metadata)
    if metakey is not None and metadata is not None:
        entry = {
            'key': metakey,
            'value': metadata,
            'constraints': constraints.copy()
        }
        datapacket['_metadata'][address_str].append(entry)

    # Fall B: Ein ganzes Dictionary mit Metadaten wurde übergeben
    if metadict is not None:
        for k, v in metadict.items():
            entry = {
                'key': k,
                'value': v,
                'constraints': constraints.copy()
            }
            datapacket['_metadata'][address_str].append(entry)

    return datapacket

