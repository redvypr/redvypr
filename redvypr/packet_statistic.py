import sys
import logging
import copy
from .redvypr_address import RedvyprAddress, redvypr_standard_address_filter
import redvypr.data_packets as data_packets

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.base.packet_statistics')
logger.setLevel(logging.INFO)

# A dictionary for the device_redvypr entry in the statistics
device_redvypr_statdict = {'_redvypr': {},
                           'datakeys':[],
                           'datakeys_expanded': {},
                           'packets_received':0,
                           'packets_published':0,
                           'packets_dropped':0,
                           '_metadata':{}}

data_statistics_address_format = redvypr_standard_address_filter#["i","p","d","h","u","a"]

STRUCTURE_CACHE = {} # Global variable for redvypr datapacket dictionaries


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
    statdict['packets_dropped'] = 0
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


def do_data_statistics(data, statdict, address_data = None):
    """
    Fills in the statistics dictionary with the data packet information.

    Extracts routing information, increments packet publication counts,
    and maintains flat representations of all encountered sub-keys and
    addressable datastreams. Uses a global structure cache to optimize
    the parsing of complex nested layouts.

    Parameters
    ----------
    data : dict
        The incoming raw telemetry data packet containing a '_redvypr'
        metadata sub-dictionary.
    statdict : dict
        The persistent statistics storage registry tracking host and
        device communication metrics. **This object is mutated in-place.**
    address_data : RedvyprAddress, optional
        Pre-calculated routing address. If None, a new `RedvyprAddress`
        instance will be compiled dynamically from `data`. Default is None.

    Returns
    -------
    None
        The function modifies `statdict` directly in place and does not
        return a value.

    Notes
    -----
    This processing engine leverages a global `STRUCTURE_CACHE` registry.
    By hashing the skeletal backbone of nested structures via
    `Datapacket.get_structure_hash`, it bypasses recursive extraction pipelines
    and heavy class instantiations for previously registered data patterns.
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
    # Calculate hash first
    struct_hash = data_packets.Datapacket.get_structure_hash(data)
    if struct_hash in STRUCTURE_CACHE: # doing nothing
        datakeys_expanded = STRUCTURE_CACHE[struct_hash]['datakeys_expanded']
        #datastreams_expanded = STRUCTURE_CACHE[struct_hash]['datastreams_expanded']
    else:
        # update cache
        rdata = data_packets.Datapacket(data)
        datakeys_expanded = rdata.datakeys(expand=True)
        #datastreams_expanded = rdata.datastreams(expand=True, return_type = "address_type") # Get datastreams with datatype
        STRUCTURE_CACHE[struct_hash] = {'datakeys_expanded':datakeys_expanded}
        #print("Packet first seen")
        #print("datastreams_expanded",datastreams_expanded)
        #print("datakeys_expanded", datakeys_expanded)
        #print("Packet first seen end")

    statdict['device_redvypr'][address_str]['datakeys_expanded'].update(datakeys_expanded)
    #statdict['device_redvypr'][address_str]['datastreams_expanded'] = datastreams_expanded


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




