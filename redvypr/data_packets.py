import copy
import time
import logging
import sys
import re
import redvypr.config
import redvypr.redvypr_address as redvypr_address
import collections

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('data_packets')
logger.setLevel(logging.DEBUG)

regex_symbol_start = '{'
regex_symbol_end = '}'

#device_redvypr_statdict = {'_redvypr': {}, 'datakeys': [], '_deviceinfo': {},'_keyinfo': {},'packets_received':0,'packets_published':0,'packets_droped':0}

redvypr_data_keys = ['_redvypr','_redvypr_command','_deviceinfo','_keyinfo']

class redvypr_datapacket(dict):
    def __init__(self, *args, **kwargs):
        if len(args)>0:
            if type(args[0]) == dict:
                dict.__init__(self, *args,**kwargs)

        else:
            dict.__init__(self)

        if '_redvypr' not in self.keys():
            dataself = datapacket()
            self.update(dataself)


    def datakeys(self):
        """
        Returns the datakeys of the redvypr dictionary
        """
        keys = list(self.keys())
        for key_remove in redvypr_data_keys:
            try:
                keys.remove(key_remove)
            except:
                pass

        return keys

    def datastreams(self):
        """
        Returns the datastreams of the redvypr dictionary
        """
        keys = list(self.keys())
        datastreams = []
        for key_remove in redvypr_data_keys:
            try:
                keys.remove(key_remove)
            except:
                pass

        keys.sort()
        for k in keys:
            datastreams.append(redvypr.redvypr_address(self, datakey = k))

        return datastreams




def datapacket(data=None,datakey=None,tu=None,device=None,hostinfo=None):
    """ A datapacket dictionary used as internal datastructure in redvypr
    """
    if(tu == None):
        tu = time.time()
    if(datakey == None):
        datakey = 'data'
        
    datadict = {'_redvypr':{'t':tu}}

    if (device is not None):
        datadict['_redvypr']['device'] = device

    if (hostinfo is not None):
        datadict['_redvypr']['host'] = hostinfo

    if(data is not None):
        datadict[datakey] = data

    return datadict

def add_keyinfo2datapacket(datapacket,datakey,unit=None,description=None,infokey=None,info=None):
    """

    Args:
        datapacket:
        datakey:
        unit:
        description:
        infokey:
        info:

    Returns:

    """
    try:
        datapacket['_keyinfo']
    except:
        datapacket['_keyinfo'] = {}

    try:
        datapacket['_keyinfo'][datakey]
    except:
        datapacket['_keyinfo'][datakey] = {}

    if(unit is not None):
        datapacket['_keyinfo'][datakey]['unit'] = unit

    if (description is not None):
        datapacket['_keyinfo'][datakey]['description'] = description

    if (infokey is not None):
        datapacket['_keyinfo'][datakey][infokey] = info

    return datapacket



def commandpacket(command='stop',device_uuid='',thread_uuid='',devicename = None, host = None, comdata=None,devicemodulename=None):
    """

    Args:
        command: 'stop'
        device: The device the command was sent from
        device_uuid:
        thread_uuid:

    Returns:
         compacket: A redvypr dictionary with the command
    """
    compacket = datapacket({'command':command},datakey='_redvypr_command') # The command
    if devicename is not None:
        compacket['_redvypr']['device'] = devicename  # The device the command was sent from
    if host is not None:
        compacket['_redvypr']['host'] = host
    if devicemodulename is not None:
        compacket['_redvypr']['devicemodulename'] = devicemodulename  # The device the command was sent from
    compacket['_redvypr_command']['device_uuid'] = device_uuid  # The uuid of the device the command is for
    compacket['_redvypr_command']['thread_uuid'] = thread_uuid  # The uuid of the thread of device the command is for
    compacket['_redvypr_command']['data'] = comdata

    return compacket


def deviceinfopacket(deviceadress,statusdict):
    """
    deviceinfopacket for a device thread
    Returns:
         stauspacket: A redvypr statuspacket dictionary
    """
    comdata = {}
    comdata['deviceaddr'] = deviceadress
    comdata['devicestatus'] = statusdict  # This is the status of the device
    datapacket = commandpacket(command='device_status', device_uuid='', thread_uuid='', devicename=None,
                                            host=None, comdata=comdata)
    return datapacket


def statuspacket(deviceadress,statusdict):
    """
    statuspacket for a device thread
    Returns:
         statuspacket: A redvypr statuspacket dictionary
    """
    comdata = {}
    comdata['deviceaddr'] = deviceadress
    comdata['devicestatus'] = statusdict  # This is the status of the device
    datapacket = commandpacket(command='device_status', device_uuid='', thread_uuid='', devicename=None,
                                            host=None, comdata=comdata)
    return datapacket

def check_for_command(datapacket=None,uuid=None,thread_uuid=None,add_data=False):
    """

    Args:
        datapacket:
        uuid: if set, compare uuid of the command with given uuid, return command only of uuid match
        add_data: adds the command dictionary

    Returns:
        command: content of the field 'redvypr_device_command', typically a string
    """
    if '_redvypr_command' not in datapacket.keys():
        if(add_data):
            return [None,None]
        else:
            return None
    else:
        FLAG_COM1 = 'command' in datapacket['_redvypr_command'].keys()
        FLAG_COM2 = 'device_uuid' in datapacket['_redvypr_command'].keys()
        FLAG_COM3 = 'thread_uuid' in datapacket['_redvypr_command'].keys()
        command = None
        if (FLAG_COM1 and FLAG_COM2):
            if(uuid is not None):
                FLAG_UUID = datapacket['_redvypr_command']['device_uuid'] == uuid
            else:
                FLAG_UUID = True

            if (thread_uuid is not None):
                FLAG_TUUID = datapacket['_redvypr_command']['thread_uuid'] == thread_uuid
            else:
                FLAG_TUUID = True

            if(FLAG_UUID and FLAG_TUUID):
                command = datapacket['_redvypr_command']['command']

        if(add_data):
            return [command,datapacket['_redvypr_command']]
        else:
            return command



#__rdvpraddr__ = redvypr_address('tmp')
#addresstypes  = __rdvpraddr__.get_strtypes() # A list of all addresstypes

