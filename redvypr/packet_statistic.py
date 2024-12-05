import sys
import logging
import copy
from .redvypr_address import RedvyprAddress
import redvypr.data_packets as data_packets
import time
import json
import deepdiff

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr_packet_statistics')
logger.setLevel(logging.INFO)

# A dictionary for the device_redvypr entry in the statistics
device_redvypr_statdict = {'_redvypr': {},'datakeys':[],'datakeys_expanded': {},'packets_received':0,'packets_published':0,'packets_droped':0,'_metadata':{},'_deviceinfo':{},'_keyinfo':{}}



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

    uuid = raddr.uuid
    address_str = raddr.address_str
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
    # Get datakeys from info (potentially)
    try:
        datakeys_info = get_keys_from_data(data['_keyinfo'])
    except Exception as e:
        datakeys_info = []

    try:
        datakeys_new = list(set(statdict['device_redvypr'][address_str]['datakeys'] + datakeys + datakeys_info))
    except Exception as e:
        logger.exception(e)
        datakeys_new = datakeys

    statdict['device_redvypr'][address_str]['_redvypr'].update(data['_redvypr'])
    statdict['device_redvypr'][address_str]['datakeys'] = datakeys_new

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

    # TODO (0.9.2++): On the long term it shall be replaced by _metadata
    try:
        statdict['device_redvypr'][address_str]['_deviceinfo'].update(data['_deviceinfo'])
    except:
        pass

    # TODO (0.9.2++): On the long term it shall be replaced by _metadata
    try:
        statdict['device_redvypr'][address_str]['_keyinfo'].update(data['_keyinfo'])
    except:
        pass

    # Deeper check, data types and expanded data types
    rdata = data_packets.Datapacket(data)
    datakeys_expanded = rdata.datakeys(expand=True)
    #print('Datakeys expanded',datakeys_expanded)
    statdict['device_redvypr'][address_str]['datakeys_expanded'].update(datakeys_expanded)

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
        print('Statistics keys',statistics.keys())
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
        if raddress.datakeyeval == False:
            if raddr in raddress:
                metadata = statistics['metadata'][astr]
                #print('Metadata', metadata)
                if mode == 'merge':
                    metadata_return.update(metadata)
                else:
                    metadata_return[astr] = metadata
        # loop over all datakeys and check for a hit
        else:
            dkeys1 = raddr.get_datakeyentries()
            dkeys2 = raddress.get_datakeyentries()
            dkeys2_fit = dkeys2[:len(dkeys1)]
            datakey_construct_new = ''
            for dentry in dkeys2_fit:
                datakey_construct_new = datakey_construct_new + '[' + json.dumps(dentry) + ']'

            raddress_construct = RedvyprAddress(address, datakey=datakey_construct_new)
            #print('Constructed address {}'.format(raddress_construct))
            if raddr in raddress_construct:
                metadata = statistics['metadata'][astr]
                #print('Metadata', metadata)
                if mode == 'merge':
                    metadata_return.update(metadata)
                else:
                    metadata_return[astr] = metadata

    return metadata_return

    #for astr in statistics['device_redvypr'].keys():
    #    raddr = RedvyprAddress(astr)
    #    if '_metadata' in statistics['device_redvypr'][astr].keys():
    #        for astr2 in statistics['device_redvypr'][astr]['_metadata'].keys():
    #            raddr2 = RedvyprAddress(astr2)
    #            # Check if a eval address is present (or not), if yes, check for all components
    #            if raddress.parsed_addrstr_expand['datakeyeval'] == False:
    #                if raddr2 in raddress:
    #                    metadata.update(statistics['device_redvypr'][astr]['_metadata'][astr2])
    #            else:
    #                print('Datakeyeval')
    #                #if self.expandlevel == 0:
    #                #    datakey_construct_new = data_new_key
    #                #else:
    #                #    datakey_construct_new = datakey_construct + '[' + json.dumps(data_new_key) + ']'
    #                datakey_construct_new = '['
    #                for dentry in raddress.parsed_addrstr_expand['datakeyentries_str']:
    #                    datakey_construct_new = datakey_construct_new + '[' + json.dumps(dentry) + ']'
    #                    raddr_construct = RedvyprAddress(address, datakey=datakey_construct_new)
    #                    print('hallo',raddr_construct)
    #                    pass



    return metadata

# Legacy
def get_devicename_from_data(data, uuid=False):
    """ Returns a redvypr devicename string including the hostname, ip with the optional uuid.

    Args:
        data (dict): A redvypr data dictionary
        uuid (Optional[bool]): Default False. Returns the devicename with the uuid (True) or the hostname + IP-Address (False)

    Returns:
        str: The full devicename
    """
    if (uuid):
        devicename = data['_redvypr']['device'] + ':' + data['_redvypr']['host']['hostname'] + '@' + \
                     data['_redvypr']['host']['addr'] + '::' + data['_redvypr']['host']['uuid']
    else:
        devicename = data['_redvypr']['device'] + ':' + data['_redvypr']['host']['hostname'] + '@' + \
                     data['_redvypr']['host']['addr']
    return devicename

# legacy
def get_datastream_from_data(data, datakey, uuid=False):
    """ Returns a redvypr datastream string including the hostname, ip with the optional uuid.

    Args:
        datakey (str): The datakey,
        data (dict): A redvypr data dictionary
        uuid (Optional[bool]): Default False. Returns the devicename with the uuid (True) or the hostname + IP-Address (False)

    Returns:
        str:
            - The full datastream
            - devicename string if datakey is None or ''
            - None if datakey is not in data dict
    """
    devicestr = get_devicename_from_data(data, uuid)
    if ((datakey == None) or (datakey == '')):
        return devicestr
    else:
        if (datakey in data.keys()):
            datastream = datakey + '/' + devicestr
            return datastream
        else:
            return None

# legacy
def get_datastreams_from_data(data, uuid=False, add_dict=False):
    """ Returns all datastreams of the datapacket

    Args:
        data (dict): A redvypr data dictionary
        uuid (Optional[bool]): Default False. Returns the devicename with the uuid (True) or the hostname + IP-Address (False)
        add_dict (Optional[bool]): Default False. Returns the devicename with the uuid (True) or the hostname + IP-Address (False)

    Returns:
        list: A list of all datastreams
    """
    t = time.time()
    datastreams = []
    datastreams_dict = {}
    datakeys = get_keys_from_data(data)
    devicename = get_devicename_from_data(data, uuid=True)
    for key in datakeys:
        datastream = key + '/' + devicename
        datastreams.append(datastream)
        datastreams_dict[datastream] = {'host': data['_redvypr']['host']}

    if (add_dict):
        return [datastreams, datastreams_dict]
    else:
        return datastreams
