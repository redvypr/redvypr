import sys
import logging
import copy
from .redvypr_address import RedvyprAddress
import redvypr.data_packets as data_packets
import time

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr_packet_statistics')
logger.setLevel(logging.DEBUG)

# A dictionary for the device_redvypr entry in the statistics
device_redvypr_statdict = {'_redvypr': {}, 'datakeys': [], '_deviceinfo': {},'_keyinfo': {},'packets_received':0,'packets_published':0,'packets_droped':0}



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
    Args:
        data:
        statdict:
    """
    if address_data is None:
        raddr = RedvyprAddress(data)
    else:
        raddr = address_data

    uuid = raddr.uuid
    devicename_stat = raddr.address_str

    # Create a hostinfo information
    try:
        statdict['host_redvypr'][uuid].update(data['_redvypr']['host'])
    except:
        statdict['host_redvypr'][uuid] = data['_redvypr']['host']

    # Create device_redvypr, dictionary with all devices as keys
    try:
        statdict['device_redvypr'][devicename_stat]['packets_published'] += 1
    except:  # Does not exist yet, create the entry
        statdict['device_redvypr'][devicename_stat] = copy.deepcopy(device_redvypr_statdict)

    # Get datakeys from datapacket
    datakeys = get_keys_from_data(data)
    # Get datakeys from info (potentially)
    try:
        datakeys_info = get_keys_from_data(data['_keyinfo'])
    except Exception as e:
        datakeys_info = []

    try:
        datakeys_new = list(set(statdict['device_redvypr'][devicename_stat]['datakeys'] + datakeys + datakeys_info))
    except Exception as e:
        logger.exception(e)
        datakeys_new = datakeys

    statdict['device_redvypr'][devicename_stat]['_redvypr'].update(data['_redvypr'])
    statdict['device_redvypr'][devicename_stat]['datakeys'] = datakeys_new

    try:
        statdict['device_redvypr'][devicename_stat]['_deviceinfo'].update(data['_deviceinfo'])
    except:
        pass

    try:
        statdict['device_redvypr'][devicename_stat]['_keyinfo'].update(data['_keyinfo'])
    except:
        pass

    return statdict



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
