import typing
import datetime
import time
import deepdiff
from redvypr.data_packets import logger
from redvypr.redvypr_address import RedvyprAddress
from redvypr.packet_statistic import logger


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

    # Helper for ISO timestamps
    def format_time(t):
        if hasattr(t, 'isoformat'):
            # Falls das übergebene Objekt "naiv" ist (keine TZ hat), verpassen wir ihm UTC
            if t.tzinfo is None:
                t = t.replace(tzinfo=datetime.timezone.utc)
            return t.isoformat()
        return t


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

    # 2. Package into standardized flat list structure
    metadata_list = []
    for key, value in metadata.items():
        metadata_list.append({
            'key': key,
            'value': value,
            'constraints': final_constraints
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

    Handles RedVypr address filtration based on a reference packet address,
    performs deep constraint hash comparisons to prevent exact duplicates,
    and automatically historizes existing keys if their value changes by setting
    the 'valid_until' boundary.

    Parameters
    ----------
    metadata : dict
        The incoming dictionary containing new metadata address blocks and entries.
    metadata_entries : dict
        The target storage dictionary (e.g., `metadata_dict['metadata']`) to modify.
    packetfilter_address : str or dict, optional
        A fallback or context packet/address used to dynamically inherit missing
        routing metrics (UUID, device, packetid) via RedvyprAddress merging.

    Returns
    -------
    status : dict
        A dictionary containing processing flags:
        - ``status['metadata_changed']`` (bool): True if entries were added or modified.
    """
    funcname = f"{__name__}.add_metadata_to_entries():"
    status = {'metadata_changed': False}
    #print(f"\nMetadata entries:{metadata_entries}")

    try:
        for address_str_work, incoming_entries in metadata.items():

            # Apply dynamic address / packet filtering path matching
            if packetfilter_address:
                raddress = RedvyprAddress(address_str_work)
                raddress_data = RedvyprAddress(packetfilter_address)

                uuid = raddress_data.uuid if (raddress.uuid is None) else None
                device = raddress_data.device if (raddress.device is None) else None
                packetid = raddress_data.packetid if (
                            raddress.packetid is None) else None

                raddress_final = RedvyprAddress(
                    raddress, uuid=uuid, device=device, packetid=packetid
                )
                address_str = raddress_final.to_address_string()
            else:
                address_str = address_str_work

            # Ensure address slice exists in central storage
            if address_str not in metadata_entries:
                metadata_entries[address_str] = []

            stored_list = metadata_entries[address_str]
            #print(f"Testing:{address_str_work} ({address_str})")
            for new_entry in incoming_entries:
                new_key = new_entry['key']
                new_value = new_entry['value']
                new_constraints = new_entry['constraints']
                new_valid_from = new_constraints.get('valid_from')

                is_duplicate = False

                for existing_entry in stored_list:
                    #print(f"Testing:{existing_entry['key']=},{new_key=},{existing_entry['value']=},{new_value=}")
                    # Case A: Same key, same value -> Check constraints for duplication
                    if existing_entry['key'] == new_key and existing_entry[
                        'value'] == new_value:
                        existing_hash = \
                        deepdiff.DeepHash(existing_entry['constraints'])[
                            existing_entry['constraints']
                        ]
                        incoming_hash = deepdiff.DeepHash(new_constraints)[
                            new_constraints
                        ]
                        if existing_hash == incoming_hash:
                            is_duplicate = True
                            break

                    # Case B: Same key, different value -> Set chronological expiration
                    if existing_entry['key'] == new_key and existing_entry[
                        'value'] != new_value:
                        if existing_entry['constraints'].get('valid_until') is None:
                            existing_entry['constraints'][
                                'valid_until'] = new_valid_from
                            status['metadata_changed'] = True
                            #print("Change:True!\n")

                # Append entry if it represents a unique mutation/state
                if not is_duplicate:
                    stored_list.append(new_entry)
                    status['metadata_changed'] = True
                    logger.debug(
                        f"Added entry: {new_key}={new_value} for {address_str}")

    except Exception:
        logger.warning(f"{funcname} Could not update metadata", exc_info=True)

    return status


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
                    print(f"Completely removed address from metadata storage: {addr}")
                else:
                    original_len = len(metadata_dict['metadata'][addr])

                    metadata_dict['metadata'][addr] = [
                        entry for entry in metadata_dict['metadata'][addr]
                        if entry['key'] not in remove_keys
                    ]

                    if len(metadata_dict['metadata'][addr]) != original_len:
                        status['metadata_changed'] = True
                        print(f"Hard-removed keys {remove_keys} from {addr}")

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

    if mode == 'merge':
        metadata_return[raddress.to_address_string()] = {}

    # 1. Sort by specificity using DSU
    decorated = [
        (len(RedvyprAddress(astr).get_datakeyentries()), astr)
        for astr in statistics.get('metadata', {}).keys()
    ]
    decorated.sort()
    metadata_keys_sorted = [astr for nentries, astr in decorated]

    # 2. Normalize the evaluation time or range (nur wenn mode != 'all')
    target_time = None
    range_start = None
    range_end = None

    if mode != 'all':
        if time_range:
            range_start = time_range[0].isoformat() if hasattr(time_range[0], 'isoformat') else time_range[0]
            range_end = time_range[1].isoformat() if hasattr(time_range[1], 'isoformat') else time_range[1]
        else:
            if at_time is None:
                target_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
            else:
                target_time = at_time.isoformat() if hasattr(at_time, 'isoformat') else at_time

    # 3. Iterate sorted structural matches
    for astr in metadata_keys_sorted:
        raddr = RedvyprAddress(astr)

        if raddress.matches(raddr):
            stored_list = statistics['metadata'][astr]

            if not isinstance(stored_list, list):
                continue

            resolved_dict = {}

            for entry in stored_list:
                constraints = entry.get('constraints', {})

                # --- A. TIME DIMENSION FILTER (wird bei 'all' übersprungen) ---
                if mode != 'all':
                    valid_from = constraints.get('valid_from')
                    valid_until = constraints.get('valid_until')

                    if time_range:
                        if valid_from and valid_from > range_end:
                            continue
                        if valid_until and valid_until < range_start:
                            continue
                    else:
                        if valid_from and target_time < valid_from:
                            continue
                        if valid_until and target_time > valid_until:
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

def get_metadata_legacy(
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
        Determines the output schema format. 'all' returns the matching raw list entries.
    context : dict, optional
        A dictionary of key-value pairs representing the current runtime context.
    at_time : datetime.datetime or str, optional
        A specific UTC timestamp to query the metadata state for ("time travel").
        Mutually exclusive with 'time_range'.
    time_range : tuple of (start, end), optional
        A time window (start_time, end_time) to fetch historical data. Matches any
        entry that was valid at some point during this window.

    Returns
    -------
    metadata_return : dict or list
        A transformed dictionary or a raw list (if mode='all') containing valid matches.
    """
    funcname = f"{__name__}.get_metadata():"
    logger.debug(funcname)

    if at_time and time_range:
        raise ValueError(
            "Parameters 'at_time' and 'time_range' are mutually exclusive.")

    metadata_return = {} if mode != 'all' else []

    if address is None:
        raddress = RedvyprAddress("@")
    else:
        raddress = RedvyprAddress(address)

    if mode == 'merge':
        metadata_return[raddress.to_address_string()] = {}

    # 1. Sort by specificity using DSU
    decorated = [
        (len(RedvyprAddress(astr).get_datakeyentries()), astr)
        for astr in statistics.get('metadata', {}).keys()
    ]
    decorated.sort()
    metadata_keys_sorted = [astr for nentries, astr in decorated]

    # 2. Normalize the evaluation time or range
    target_time = None
    range_start = None
    range_end = None

    if time_range:
        range_start = time_range[0].isoformat() if hasattr(time_range[0],
                                                           'isoformat') else time_range[
            0]
        range_end = time_range[1].isoformat() if hasattr(time_range[1],
                                                         'isoformat') else time_range[1]
    else:
        if at_time is None:
            target_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        else:
            target_time = at_time.isoformat() if hasattr(at_time,
                                                         'isoformat') else at_time

    # 3. Iterate sorted structural matches
    for astr in metadata_keys_sorted:
        raddr = RedvyprAddress(astr)

        if raddress.matches(raddr):
            stored_list = statistics['metadata'][astr]

            if not isinstance(stored_list, list):
                continue

            resolved_dict = {}

            for entry in stored_list:
                constraints = entry.get('constraints', {})
                valid_from = constraints.get('valid_from')
                valid_until = constraints.get('valid_until')

                # --- A. TIME DIMENSION FILTER ---
                if time_range:
                    # Check overlap: entry start <= range end AND entry end >= range start
                    # (Assuming None means infinity)
                    if valid_from and valid_from > range_end:
                        continue
                    if valid_until and valid_until < range_start:
                        continue
                else:
                    # Classic Single-Point-in-Time Filter
                    if valid_from and target_time < valid_from:
                        continue
                    if valid_until and target_time > valid_until:
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
                    # Append the whole entry (including key, value, constraints)
                    # and attach its structural origin for traceability
                    enriched_entry = entry.copy()
                    enriched_entry['source_address'] = astr
                    metadata_return.append(enriched_entry)
                else:
                    # Entry passed all filters -> Add to active key-value view
                    resolved_dict[entry['key']] = entry['value']

            if mode == 'all' or not resolved_dict:
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



def get_metadata_in_range_legacy(
        statistics: dict,
        address: None | str | RedvyprAddress = None,
        t1: datetime.datetime | None = None,
        t2: datetime.datetime | None = None,
        mode: typing.Literal["merge", "expanded"] = "expanded",
        constraint_mode: typing.Literal["merge", "expanded"] = "expanded"
):
    """
    Retrieves metadata within a time range.
    :param mode: Controls the spatial hierarchy (Address merging).
    :param constraint_mode: Controls the temporal hierarchy (Constraint merging).
    """
    # 1. Get the base metadata (Spatial Merge/Expanded)
    # Using your existing hierarchical logic
    def _is_rule_active_in_range(rule, t1, t2):
        """ Helper to check time overlap """
        if not t1 and not t2: return True  # No range specified, show all

        r_start = None
        r_end = None
        for cond in rule.get('conditions', []):
            if cond['field'] == 't':
                if cond['op'] in ['>', '>=']:
                    r_start = datetime.fromisoformat(cond['value']) if isinstance(
                        cond['value'], str) else cond['value']
                if cond['op'] in ['<', '<=']:
                    r_end = datetime.fromisoformat(cond['value']) if isinstance(
                        cond['value'], str) else cond['value']

        # Overlap logic: (RuleStart <= QueryEnd) AND (RuleEnd >= QueryStart)
        if r_start and t2 and r_start > t2: return False
        if r_end and t1 and r_end < t1: return False
        return True

    base_data = get_metadata(statistics, address, mode=mode)

    results = {}

    for addr_str, content in base_data.items():
        final_content = content.copy()
        constraints = final_content.pop('_constraints', [])

        # Filter constraints that overlap with [t1, t2]
        active_rules = []
        for rule in constraints:
            if _is_rule_active_in_range(rule, t1, t2):
                active_rules.append(rule)

        if constraint_mode == 'merge':
            # TEMPORAL MERGE: Flatten rules into the main dictionary
            # Note: Later rules in the list overwrite earlier ones (Priority)
            for rule in active_rules:
                final_content.update(rule.get('values', {}))
        else:
            # TEMPORAL EXPANDED: Keep the rules as a list
            final_content['_constraints'] = active_rules

        results[addr_str] = final_content

    return results


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

            metadata_address = create_metadata_dict(addr, metadata, hostinfo=hostinfo)
            datapacket['_metadata'][addr] = metadata_address
        else:
            raise ValueError(
                f"key {str(addr)} of metadict dictionary must be valid RedvyprAddress string")

    return datapacket


import datetime


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
    if constraints is None:
        constraints = {}
    if hostinfo:
        constraints['hostinfo'] = hostinfo

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

