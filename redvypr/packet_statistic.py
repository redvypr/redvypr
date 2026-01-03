import sys
import logging
import copy
from .redvypr_address import RedvyprAddress, redvypr_standard_address_filter
import redvypr.data_packets as data_packets
import time
import json
import deepdiff
import typing
from datetime import datetime

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.packet_statistics')
logger.setLevel(logging.INFO)

# A dictionary for the device_redvypr entry in the statistics
#device_redvypr_statdict = {'_redvypr': {},'datakeys':[],'datakeys_expanded': {},'packets_received':0,'packets_published':0,'packets_droped':0,'_metadata':{},'_deviceinfo':{},'_keyinfo':{}}
device_redvypr_statdict = {'_redvypr': {},'datakeys':[],'datakeys_expanded': {},'packets_received':0,'packets_published':0,'packets_droped':0,'_metadata':{}}

data_statistics_address_format = redvypr_standard_address_filter#["i","p","d","h","u","a"]


def treat_datadict(data, devicename, hostinfo, numpacket, tpacket, devicemodulename=''):
    """ Treats a datadict received from a device and adds additional information from redvypr as hostinfo, numpackets etc.
    """
    # Add deviceinformation to the data package
    if ('_redvypr' not in data.keys()):
        data['_redvypr'] = {}
    if ('tag' not in data['_redvypr'].keys()): # A tag of the uuid, counting the number of times the packet has been recirculated
        data['_redvypr']['tag'] = {}
    if ('device' not in data['_redvypr'].keys()):
        data['_redvypr']['device'] = str(devicename)
    elif data['_redvypr']['device'] is None:
        data['_redvypr']['device'] = str(devicename)
    #if ('publisher' not in data['_redvypr'].keys()):
    #    data['_redvypr']['publisher'] = str(devicename)
    if ('packetid' not in data['_redvypr'].keys()):
        data['_redvypr']['packetid'] = str(devicename)
    if ('host' not in data['_redvypr'].keys()):
        data['_redvypr']['host'] = hostinfo
    # for legacy and stability reason, allow hostname, TODO: remove at some point
    if "hostname" in data['_redvypr']['host'].keys():
        data['_redvypr']['host']['host'] = data['_redvypr']['host']['hostname']
    if (data['_redvypr']['host']['host'] is None) or (data['_redvypr']['host']['uuid'] is None):
        # Invalid host, replacing with local host
        data['_redvypr']['host'] = hostinfo
    # for legacy reason, allow hostname, TODO: remove at some point
    if ('hostname' in data['_redvypr'].keys()):
        data['_redvypr']['host'] = data['_redvypr']['hostname']

    # Tag the datapacket and add the local publishing device
    try:
        data['_redvypr']['tag'][hostinfo['uuid']] += 1
    except:
        data['_redvypr']['tag'][hostinfo['uuid']] = 1
        data['_redvypr']['localhost'] = hostinfo
        #data['_redvypr']['localuuid'] = hostinfo['uuid']
        data['_redvypr']['publisher'] = str(devicename)

    # Add the time to the datadict if its not already in
    if ('t' not in data['_redvypr'].keys()):
        data['_redvypr']['t'] = tpacket

    # Check if there was data sent (len(datakeys) > 0), if yes check if time is present, if not add it
    datakeys = get_keys_from_data(data)
    if (len(datakeys) > 0) and ('t' not in datakeys):
        data['t'] = tpacket

    # Add the devicemodulename to the redvypr
    if ('devicemodulename' not in data['_redvypr'].keys()):
        data['_redvypr']['devicemodulename'] = devicemodulename

    # Add the packetnumber to the datadict
    if ('numpacket' not in data['_redvypr'].keys()):
        data['_redvypr']['numpacket'] = numpacket

    return data

def create_data_statistic_dict():
    statdict = {}
    statdict['inspect'] = True
    statdict['packets_published'] = 0
    statdict['packets_received'] = 0
    statdict['datakeys'] = []
    #statdict['datakeys_expanded'] = {}
    statdict['devicekeys'] = {}
    statdict['devices'] = []
    statdict['devices_dict'] = {}
    statdict['datastreams'] = []
    statdict['datastreams_dict'] = {}
    statdict['datastreams_info'] = {}
    statdict['hostinfos'] = {}
    # New
    statdict['datakey_info'] = {}
    statdict['datastream_redvypr'] = {}
    statdict['device_redvypr'] = {}
    statdict['host_redvypr'] = {}
    statdict['metadata'] = {}
    statdict['packets'] = {}  # Packets from subscribed devices
    return statdict


def rem_device_from_statistics(deviceaddress, statdict):
    """
    Remove a deviceaddress from the statistic
    Args:
        deviceaddress:
        statdict:

    Returns:

    """
    keys_removed = []
    for k in statdict.keys():
        try:
            statdict[k].pop(deviceaddress)
            keys_removed.append(k)
        except:
            pass

    return keys_removed


def do_metadata(data, metadatadict, auto_add_packetfilter=True):
    funcname = __name__ + '.do_metadata():'
    status = {'metadata_changed': False}
    # Remove entries
    if '_metadata_remove' in data.keys():
        print("Removing data")
        for address_str, removedata in data['_metadata_remove'].items():
            raddress_str = RedvyprAddress(address_str)
            remove_keys = removedata['keys']
            constraint_entries = removedata['constraints']
            try:
                remove_mode = removedata['mode'] # Can be "exact" or "matches"
            except:
                remove_mode = "exact"

            # Check which addresses shall be treated
            if remove_mode == "exact":
                address_strings = [address_str]
            else:
                address_strings = []
                potential_address_strings = metadatadict['metadata'].keys()
                for addr_test in potential_address_strings:
                    raddr_test = RedvyprAddress(addr_test)
                    if raddress_str.matches(raddr_test):
                        address_strings.append(addr_test)

            print(f"Removing entries from addresses:{address_strings}")
            if constraint_entries is not None:
                if len(constraint_entries) == 0:
                    print("Removing constraints for", address_str)
                    try:
                        metadatadict['metadata'][address_str].pop('_constraints')
                        status['metadata_changed'] = True
                    except (KeyError, IndexError):
                        pass  # Expected
                    except Exception as e:
                        logger.debug(f"Unexpected error during removal: {e}")
                else:
                    for i in sorted(constraint_entries, reverse=True):
                        for address_str in address_strings:
                            try:
                                metadatadict['metadata'][address_str]['_constraints'].pop(i)
                                status['metadata_changed'] = True
                            except (KeyError, IndexError):
                                pass  # Expected
                            except Exception as e:
                                logger.debug(f"Unexpected error during removal: {e}")

                    # Remove constraints entry, if empty
                    for address_str in address_strings:
                        try:
                            lencon = len(metadatadict['metadata'][address_str]['_constraints'])
                            if lencon == 0:
                                metadatadict['metadata'][address_str].pop('_constraints')
                        except:
                            pass


            if remove_keys is not None:
                if len(remove_keys) == 0:
                    for address_str in address_strings:
                        try:
                            print("Removing key", address_str)
                            metadatadict['metadata'].pop(address_str)
                            status['metadata_changed'] = True
                        except (KeyError, IndexError):
                            pass  # Expected
                        except Exception as e:
                            logger.debug(f"Unexpected error during removal: {e}")

                else:
                    for address_str in address_strings:
                        for k in remove_keys:
                            try:
                                metadatadict['metadata'][address_str].pop(k)
                                status['metadata_changed'] = True
                            except (KeyError, IndexError):
                                pass  # Expected
                            except Exception as e:
                                logger.debug(f"Unexpected error during removal: {e}")

            # Remove whole entry if empty
            for address_str in address_strings:
                try:
                    lenkeys = len(metadatadict['metadata'][address_str].keys())
                    if lenkeys == 0:
                        metadatadict['metadata'].pop(address_str)
                except:
                    pass

    # Add entry
    if '_metadata' in data.keys():
        try:
            for address_str_work in data['_metadata'].keys():
                raddress = RedvyprAddress(address_str_work)
                raddress_data = RedvyprAddress(data)

                if auto_add_packetfilter:
                    uuid = None
                    device = None
                    packetid = None
                    # Add uuid
                    if (raddress.uuid is None) and (raddress_data.uuid is not None):
                        #print("Adding uuid")
                        uuid = raddress_data.uuid
                    # Add device
                    if (raddress.device is None) and (raddress_data.device is not None):
                        #print("Adding device")
                        device = raddress_data.device
                    # Add packetid
                    if (raddress.device is None) and (raddress_data.device is not None):
                        #print("Adding packetid")
                        packetid = raddress_data.packetid

                    raddress_final = RedvyprAddress(raddress, uuid=uuid, device=device, packetid=packetid)
                    address_str = raddress_final.to_address_string()
                    #print(f"Address string: {address_str_work=}")
                    #print(f"Address string: {address_str=}")
                else:
                    address_str = address_str_work

                new_metadata = data['_metadata'][address_str_work]

                # Ensure the address exists in our storage
                if address_str not in metadatadict['metadata']:
                    metadatadict['metadata'][address_str] = {}

                target = metadatadict['metadata'][address_str]

                # 1. Handle standard key-value pairs (everything except _constraints)
                for key, value in new_metadata.items():
                    if key == '_constraints':
                        continue

                    # Compare value before updating to set changed flag
                    if target.get(key) != value:
                        target[key] = value
                        status['metadata_changed'] = True
                        logger.debug(f"New metadata for {address_str=}:\n")
                        logger.debug(f"{key=}:{value=}")

                # 2. Handle _constraints list merging
                if '_constraints' in new_metadata:
                    if '_constraints' not in target:
                        target['_constraints'] = []

                    for new_rule in new_metadata['_constraints']:
                        # Use DeepHash to check if this specific rule already exists
                        new_rule_hash = deepdiff.DeepHash(new_rule)[new_rule]

                        is_duplicate = False
                        for existing_rule in target['_constraints']:
                            existing_hash = deepdiff.DeepHash(existing_rule)[existing_rule]
                            if new_rule_hash == existing_hash:
                                is_duplicate = True
                                break

                        if not is_duplicate:
                            target['_constraints'].append(new_rule)
                            status['metadata_changed'] = True
                            #print(f"Added new unique constraint to {address_str}")
                            logger.debug(f"New contrained metadata for {address_str=}:\n")
                            logger.debug(f"{new_rule=}")

        except Exception:
            logger.info(funcname + " Could not update metadata", exc_info=True)

    return status


def do_data_statistics(data, statdict, address_data = None):
    """
    Fills in the statistics dictionary with the data packet information
    :param data:
    :param statdict:
    :param address_data:
    :return: statdict
    """
    if address_data is None:
        raddr = RedvyprAddress(data)
    else:
        raddr = address_data

    #print("\n\nStatistics for data",data)
    #print("\n\nStatistics for address", raddr)
    uuid = raddr.uuid
    address_str = raddr.to_address_string(data_statistics_address_format)

    # Create a hostinfo information
    try:
        statdict['host_redvypr'][uuid].update(data['_redvypr']['host'])
    except:
        statdict['host_redvypr'][uuid] = data['_redvypr']['host']

    # Create device_redvypr, dictionary with all devices as keys
    try:
        statdict['device_redvypr'][address_str]['packets_published'] += 1
    except:  # Does not exist yet, create the entry
        statdict['device_redvypr'][address_str] = copy.deepcopy(device_redvypr_statdict)

    # Get datakeys from datapacket
    datakeys = get_keys_from_data(data)
    try:
        datakeys_new = list(set(statdict['device_redvypr'][address_str]['datakeys'] + datakeys))
    except Exception as e:
        logger.exception(e)
        datakeys_new = datakeys

    statdict['device_redvypr'][address_str]['_redvypr'].update(data['_redvypr'])
    statdict['device_redvypr'][address_str]['datakeys'] = datakeys_new

    # Deeper check, data types and expanded data types
    rdata = data_packets.Datapacket(data)
    datakeys_expanded = rdata.datakeys(expand=True)
    #print('Datakeys expanded',datakeys_expanded)
    statdict['device_redvypr'][address_str]['datakeys_expanded'].update(datakeys_expanded)


    #return statdict



def get_keys_from_data(data):
    """
    Returns the keys of a redvypr data packet without the potentially existing standard keys:
    -'_redvypr'
    -'_redvypr_command'
    -'_deviceinfo'
    -'_keyinfo'

    Args:
        data (dict): redvypr data dictionary
    Returns:
        list with the datakeys

    """
    keys = list(data.keys())
    for key_remove in data_packets.redvypr_data_keys:
        try:
            keys.remove(key_remove)
        except:
            pass

    return keys


#def get_metadata(statistics, address=None, mode='expanded'):
def get_metadata(statistics,
    address: None | str | RedvyprAddress = None,
    mode: typing.Literal["merge", "expanded"] = "expanded"):
    """
    Gets the metadata of the redvypr address
    :param statistics:
    :param address:
    :param mode: merge or expanded
    :return:
    """

    funcname = __name__ + '.get_metadata():'
    logger.debug(funcname)
    metadata_return = {}
    if address is None:
        raddress = RedvyprAddress("@") # Everything
    else:
        raddress = RedvyprAddress(address)

    if mode == 'merge':
        metadata_return[raddress.to_address_string()] = {}
    # Sort the datakeys by the number of the datakey indices.
    # This allows to have the longest entries latest such that the most
    # specific one is overwriting a less specific one
    #https://docs.python.org/3/howto/sorting.html Decorate-Sort-Undecorate
    decorated = [(len(RedvyprAddress(astr).get_datakeyentries()),astr) for astr in statistics['metadata'].keys()]
    decorated.sort()
    metadata_keys_sorted = [astr for nentries,astr in decorated]
    print('Metadaty_keys_sorted',metadata_keys_sorted)
    #for astr in statistics['metadata'].keys():
    for astr in metadata_keys_sorted:
        print("Astr",astr,mode,raddress)
        raddr = RedvyprAddress(astr)
        #print("Test address,",raddr,raddress)
        #print("Test address result,", raddr(raddress))
        print("Test matches", raddress.matches_filter(raddr, soft_missing=False), raddr.matches_filter(raddress, soft_missing=False))
        print("Test address result2,", RedvyprAddress(astr))
        print("\n")
        #try:
        #    retdata = raddr(raddress)
        #except:
        #    continue

        if raddr.matches(raddress):
            #print("Match of {}({}".format(raddr,raddress))
            if True:
                metadata = statistics['metadata'][astr]
                #print('Found metadata', metadata)
                if mode == 'merge': # Put everything into the addressstring key
                    metadata_return[raddress.to_address_string()].update(metadata)
                else:
                    #print("Expanded",astr)
                    try:
                        metadata_return[astr].update(metadata)
                    except:
                        metadata_return[astr] = metadata

                    #print("Expanded", metadata_return)

    return metadata_return


def get_metadata_in_range(
        statistics: dict,
        address: None | str | RedvyprAddress = None,
        t1: datetime | None = None,
        t2: datetime | None = None,
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




