import copy
import time
import logging
import sys
import re
import numpy as np
import redvypr
import redvypr.redvypr_address as redvypr_address
import collections
import pydantic
import typing

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('data_packets')
logger.setLevel(logging.DEBUG)

regex_symbol_start = '{'
regex_symbol_end = '}'

#device_redvypr_statdict = {'_redvypr': {}, 'datakeys': [], '_deviceinfo': {},'_keyinfo': {},'packets_received':0,'packets_published':0,'packets_droped':0}
redvypr_data_keys = ['_redvypr','_redvypr_command','_deviceinfo','_keyinfo','_metadata']

# Defintions for common metadata types
class RedvyprMetadata(pydantic.BaseModel):
    address: typing.Dict[redvypr_address.RedvyprAddress, typing.Any] = {}
class RedvyprDeviceMetadata(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")
    location: str = ''
    comment: str = ''

class RedvyprDatastreamMetadata(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")
    unit: str = ''
    comment: str = ''

class RedvyprMetadataGeneral(pydantic.BaseModel):
    address: typing.Dict[str, typing.Any] = {}

class Datapacket(dict):
    def __init__(self, *args, **kwargs):
        if len(args)>0:
            if isinstance(args[0],dict):
                dict.__init__(self, *args,**kwargs)

        else:
            dict.__init__(self)

        if '_redvypr' not in self.keys():
            dataself = create_datadict()
            self.update(dataself)

        self.address = redvypr_address.RedvyprAddress(self)

    def __getitem__(self, key):
        # Check if the key is a string but is an "eval" operator
        if isinstance(key,str):
            if key.startswith('[') and key.endswith(']'):
                evalstr = 'self' + key
                #data = self
                data = eval(evalstr, None)
                return data
            else:
                return super().__getitem__(key)
        # Check if the key is a RedvyprAddress
        elif isinstance(key, redvypr_address.RedvyprAddress):
            datakey = key.datakey
            if datakey.startswith('[') and datakey.endswith(']'):
                evalstr = 'self' + datakey
                #data = self
                data = eval(evalstr, None)
                return data
            else:
                return super().__getitem__(datakey)
        else:
            return super().__getitem__(key)

    def __setitem__(self, key, value):
        # Check if the key is a string but is an "eval" operator
        if isinstance(key, str):
            if key.startswith('[') and key.endswith(']'):
                evalstr = 'self' + key + '=value'
                # data = self
                exec(evalstr, None)
            else:
                return super().__setitem__(key, value)
        # Check if the key is a RedvyprAddress
        elif isinstance(key, redvypr_address.RedvyprAddress):
            datakey = key.datakey
            if datakey.startswith('[') and datakey.endswith(']'):
                evalstr = 'self' + datakey  + '=value'
                exec(evalstr, None)
            else:
                return super().__setitem__(datakey, value)
        else:
            return super().__setitem__(key, value)

    def __expand_datakeys_recursive__(self, data, keys, level=0, parent_key='f', key_list = [], key_dict = {}, max_level=1000):
        for k in keys:
            #print('k',k)
            data_k = data[k]
            # Check if k is a list or a dict
            if isinstance(k, int):
                strformat = "[{}]".format(k)
                key_dict.append(None)
            else:
                strformat = "['{}']".format(k)
                key_dict[k] = None
            if level < max_level:
                if isinstance(data_k, list):
                    data_k_keys = range(0, len(data_k))
                    parent_key_new = parent_key + strformat
                    key_dict[k] = []
                    self.__expand_datakeys_recursive__(data_k, data_k_keys, level=level + 1, parent_key=parent_key_new, key_list=key_list, key_dict = key_dict[k], max_level=max_level)
                elif isinstance(data_k, dict):
                    data_k_keys = data_k.keys()
                    parent_key_new = parent_key + strformat
                    key_dict[k] = {}
                    self.__expand_datakeys_recursive__(data_k, data_k_keys, level=level + 1, parent_key=parent_key_new, key_list=key_list, key_dict = key_dict[k], max_level=max_level)
                elif isinstance(data_k, np.ndarray):
                    #logger.warning('Found an numpy array, this is not implemented yet')
                    # Add index type of address if necessary only
                    if level > 0:
                        expanded_key = parent_key + strformat
                        key_list.append(expanded_key)
                        key_dict[k] = (expanded_key, type(data[k]))
                    else:
                        key_list.append(k)
                        key_dict[k] = (k, type(data[k]))

                else: # This is not an iterative element anymore, lets use it
                    # Add index type of address if necessary only
                    if level > 0:
                        expanded_key = parent_key + strformat
                        key_list.append(expanded_key)
                        key_dict[k] = (expanded_key,type(data[k]))
                    else:
                        key_list.append(k)
                        key_dict[k] = (k,type(data[k]))
            else:
                # Add index type of address if necessary only
                if level > 0:
                    expanded_key = parent_key + strformat
                    key_list.append(expanded_key)
                else:
                    key_list.append(k)

    def datakeys(self, expand=False, return_type='dict'):
        """
        Returns the datakeys of the redvypr dictionary
        :param expand: True/False or level [int], if true return expanded datakeys with a level depth of 100
        :param return_type: 'dict,'list','both'
        :return:
        """
        keys = list(self.keys())
        for key_remove in redvypr_data_keys:
            try:
                keys.remove(key_remove)
            except:
                pass

        # Check if the datakey needs to be expanded
        if expand == False:
            return keys
        else:
            keys_expand = []
            keys_dict_expand = {}
            if isinstance(expand, bool):
                max_level = 100
            else:
                max_level = expand

            self.__expand_datakeys_recursive__(self, keys, level=0, parent_key='', key_list=keys_expand, key_dict=keys_dict_expand, max_level=max_level)

            if return_type=='list':
                return keys_expand
            elif return_type=='dict':
                return keys_dict_expand
            else:
                return (keys_expand, keys_dict_expand)

    def datastreams(self, expand=True):
        datakeys = self.datakeys(expand=expand,return_type='list')
        daddresses = []
        for d in datakeys:
            daddr = redvypr_address.RedvyprAddress(self.address,datakey=d)
            daddresses.append(daddr)

        return daddresses


    def legacy_datastreams_legacy(self):
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
            datastreams.append(redvypr_address.RedvyprAddress(self, datakey=k))

        return datastreams

    def get_addressstr(self,addrformat='/i/k/'):
        return self.address.get_str(addrformat)




def create_datadict(data=None, datakey=None, packetid=None, tu=None, device=None, publisher=None, hostinfo=None):
    """ Creates a datadict dictionary used as internal datastructure in redvypr
    """
    if(tu == None):
        tu = time.time()

    datadict = {'_redvypr':{'t':tu}}
    datadict['_redvypr']['device'] = device
    if (packetid is None):
            datadict['_redvypr']['packetid'] = device

    datadict['_redvypr']['packetid'] = packetid
    datadict['_redvypr']['publisher'] = publisher
    if (hostinfo is not None):
        if hostinfo == 'random':
            redvypr.create_hostinfo('random')
        else:
            datadict['_redvypr']['host'] = hostinfo
    else:
        datadict['_redvypr']['host'] = redvypr.hostinfo_blank

    if(data is not None):
        if (datakey == None):
            datakey = 'data'
        datadict[datakey] = data

    return datadict


def add_metadata2datapacket(datapacket, address=None, datakey=None, metakey=None, metadata=None, metadict=None):
    """

    Args:add_metad
        datapacket:
        datakey:
        metakey:
        metadata:

    Returns:

    """
    if True:
        #print('Datapacket',datapacket)
        if address is not None:
            raddress = redvypr_address.RedvyprAddress(address)
        if datakey is not None:
            try: # Try first to create a RedvyprAddress from the datapacket itself
                raddress = redvypr_address.RedvyprAddress(datapacket, datakey=datakey)
            except:
                logger.info('Could not create address',exc_info=True)
                raddress = redvypr_address.RedvyprAddress(datakey=datakey)

        address_str = raddress.address_str
        try:
            datapacket['_metadata']
        except:
            datapacket['_metadata'] = {}

        try:
            datapacket['_metadata'][address_str]
        except:
            datapacket['_metadata'][address_str] = {}

        if (metadata is not None):
            datapacket['_metadata'][address_str][metakey] = metadata

        # If a dictionary with metakeys is given
        if (metadict is not None):
            datapacket['_metadata'][address_str].update(metadict)

    #print('Metadata datapacket',datapacket)
    #print('---done----')
    return datapacket



def commandpacket(command='stop',device_uuid='',thread_uuid='',packetid=None,devicename=None,publisher=None,host=None,comdata=None,devicemodulename=None):
    """

    Args:
        command: 'stop'
        device: The device the command was sent from
        device_uuid:
        thread_uuid:

    Returns:
         compacket: A redvypr dictionary with the command
    """
    compacket = create_datadict({'command':command}, datakey='_redvypr_command') # The command
    if packetid is not None:
        compacket['_redvypr']['packetid'] = packetid  # The device the command was sent from
    if devicename is not None:
        compacket['_redvypr']['device'] = devicename  # The device the command was sent from
    if publisher is not None:
        compacket['_redvypr']['publisher'] = publisher
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
    flags = {}
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
        flags['com'] = FLAG_COM1
        if FLAG_COM1:

            if(uuid is not None):
                FLAG_UUID = datapacket['_redvypr_command']['device_uuid'] == uuid
            else:
                FLAG_UUID = True

            if (thread_uuid is not None):
                FLAG_TUUID = datapacket['_redvypr_command']['thread_uuid'] == thread_uuid
            else:
                FLAG_TUUID = True

            flags['device_uuid'] = FLAG_UUID
            flags['thread_uuid'] = FLAG_TUUID
            command = datapacket['_redvypr_command']['command']

        if(add_data):
            return [command,{'command_data':datapacket['_redvypr_command'],'flags':flags}]
        else:
            return command


#__rdvpraddr__ = redvypr_address('tmp')
#addresstypes  = __rdvpraddr__.get_strtypes() # A list of all addresstypes

