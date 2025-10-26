import sys
import logging
import copy
from .redvypr_address import RedvyprAddress, redvypr_standard_address_filter
import redvypr.data_packets as data_packets
import time
import json
import deepdiff

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
    elif (data['_redvypr']['host']['hostname'] is None) or (data['_redvypr']['host']['uuid'] is None):
        # Invalid host, replacing with local host
        data['_redvypr']['host'] = hostinfo

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


def do_data_statistics(data, statdict, address_data = None):
    """
    Fills in the statistics dictionary with the data packet information
    :param data:
    :param statdict:
    :param address_data:
    :return: statdict, status
    """
    status = {'metadata_changed':False}
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

    # Metadata of the datapacket
    try:
        for address_str_metadata in data['_metadata'].keys():
            metadata = data['_metadata'][address_str_metadata]
            deephash = deepdiff.DeepHash(metadata)[metadata]
            try:
                metadata_orig = statdict['metadata'][address_str_metadata]
            except:
                statdict['metadata'][address_str_metadata] = {}
                metadata_orig = statdict['metadata'][address_str_metadata]

            deephash_orig = deepdiff.DeepHash(metadata_orig)[metadata_orig]
            # Check if there is a difference, if yes, update
            if deephash != deephash_orig:
                #print('Updating metadata')
                statdict['metadata'][address_str_metadata].update(metadata)
                status['metadata_changed'] = True
            else:
                #print('Same metadata, doing nothing')
                pass
    except:
        pass

    return statdict, status



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

def get_metadata_deviceinfo_all(statistics, address, publisher_strict=True,  mode='merge'):
    """
    Gets the metadata from a deviceinfo_all dict retreived with
    redvypr.get_deviceinfo()

    :param statistics:
    :param address:
    :param publisher_strict:
    :param mode:
    :return:
    """
    funcname = __name__ + '.get_metadata_deviceinfo_all():'
    logger.debug(funcname + '{}'.format(address))
    metadata = {}
    raddress = RedvyprAddress(address)
    if publisher_strict:
        publisher_key = raddress.publisher
        #print('Publisher key',publisher_key)
        try:
            #mdata_device = statistics['metadata'][publisher_key]
            mdata_device = {'metadata': statistics['metadata'][publisher_key]}
            mdata = get_metadata(mdata_device, address, mode)
            metadata.update(mdata)
        except:
            logger.debug('Could not find publisher for address {}'.format(raddress),exc_info=True)
    else:
        #print('Statistics keys',statistics.keys())
        for dev in statistics['metadata'].keys():
            mdata_device = {'metadata': statistics['metadata'][dev]}
            mdata = get_metadata(mdata_device, address, mode)
            metadata.update(mdata)

    return metadata

def get_metadata(statistics, address, mode='merge'):
    """
    Gets the metadata of the redvypr address
    :param statistics:
    :param address:
    :param mode: merge or dict
    :return:
    """

    funcname = __name__ + '.get_metadata():'
    logger.debug(funcname)
    if mode == 'merge':
        metadata_return = {}
    else:
        metadata_return = {}
    raddress = RedvyprAddress(address)

    # Sort the datakeys by the number of the datakey indices.
    # This allows to have the longest entries latest such that the most
    # specific one is overwriting a less specific one
    #https://docs.python.org/3/howto/sorting.html Decorate-Sort-Undecorate
    decorated = [(len(RedvyprAddress(astr).get_datakeyentries()),astr) for astr in statistics['metadata'].keys()]
    decorated.sort()
    metadata_keys_sorted = [astr for nentries,astr in decorated]
    #print('Metadaty_keys_sorted',metadata_keys_sorted)
    #for astr in statistics['metadata'].keys():
    for astr in metadata_keys_sorted:
        raddr = RedvyprAddress(astr)
        try:
            retdata = raddr(raddress)
        except:
            continue
        if True:
            #print("Match of {}({}".format(raddr,raddress))
            if True:
                metadata = statistics['metadata'][astr]
                #print('Metadata', metadata)
                if mode == 'merge':
                    metadata_return.update(metadata)
                else:
                    metadata_return[astr] = metadata

    return metadata_return

