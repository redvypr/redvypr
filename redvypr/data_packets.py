import time
import logging
import sys

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('data_packets')
logger.setLevel(logging.DEBUG)


def create_data_statistic_dict():
    statdict = {}
    statdict['inspect']    = True
    statdict['numpackets'] = 0
    statdict['datakeys']   = []
    statdict['devicekeys'] = {}
    statdict['devices']    = []
    statdict['datastreams']= []
    return statdict

def do_data_statistics(data, statdict):
    """
    Fills in the statistics dictionary with the data packet information
    Args:
        data:
        statdict:
    """
    statdict['numpackets'] += 1
    # Create a unique list of datakeys
    statdict['datakeys'] = list(set(statdict['datakeys'] + list(data.keys())))
    # Create a unqiue list of devices, device can
    # be different from the transporting device,
    # i.e. network devices do not change the name
    # of the transporting dictionary
    devicename_stat  = get_devicename_from_data(data,uuid=True)
    try:
        statdict['devicekeys'][devicename_stat]
    except:
        statdict['devicekeys'][devicename_stat] = []
        
    statdict['devicekeys'][devicename_stat] = list(set(statdict['devicekeys'][devicename_stat] + list(data.keys())))
    statdict['devices'] = list(set(statdict['devices'] + [devicename_stat]))
    datastreams_stat = get_datastreams_from_data(data,uuid=True)
    statdict['datastreams'] = list(set(statdict['datastreams'] + datastreams_stat))
    return statdict


def parse_devicestring(devicestr,local_hostinfo=None):
    """
     Parses as redvypr datastring or devicestring
    
        devicestr: the devicestring
        local_uuid: if the devicestring is local, the local hostinfo is used to fill in hostname, addr and UUID etc. 
    """
    devstring_full = devicestr
    # Check first if we have a datastream
    if('/' in devstring_full):

        s = devstring_full.split('/')
        datakey   = s[0]
        devstring = s[1]
    else:
        datakey   = None
        devstring = devstring_full

    # First distinguish between the different realizations of the devicestring
    uuid       = None
    hostname   = None
    addr       = None
    devicename = None 
    local      = True # True if devicename is local
    # Check first if we have an UUID       
    if('::' in devstring): # UUID
        s         = devstring.split('::')
        devstring = s[0]
        uuid      = s[1]
        local     = False
        
    if(':' in devstring): # hostname
        s = devstring.split(':')
        devicename = s[0]
        rest       = s[1]
        local      = False
        if('@' in rest):
            hostname = rest.split('@')[0]
            addr     = rest.split('@')[1]
        else:
            hostname = rest
            addr     = '*' # If only the hostname is defined, addr is expected to be expanded
    else:
        devicename = devstring

    hostexpanded   = (hostname == '*')
    addrexpanded   = (addr == '*')
    deviceexpanded = (devicename == '*')
    uuidexpanded   = (uuid == '*')
    
    if(local and (local_hostinfo is not None)):
        if(hostname == None):
            hostname = local_hostinfo['hostname']
        addr     = local_hostinfo['addr']
        uuid     = local_hostinfo['uuid']
    

    # Fill a dictionary
    parsed_data = {}
    parsed_data['devicestr']    = devicestr
    parsed_data['hostname']     = hostname
    parsed_data['addr']         = addr
    parsed_data['devicename']   = devicename
    parsed_data['uuid']         = uuid
    parsed_data['datakey']      = datakey
    parsed_data['hostexpand']   = hostexpanded
    parsed_data['addrexpand']   = addrexpanded
    parsed_data['deviceexpand'] = deviceexpanded
    parsed_data['uuidexpand']   = uuidexpanded            
    parsed_data['local']        = local
    
    return parsed_data

def get_keys_from_data(data,rem_standard=True,rem_tnum=False,rem_props=False):
    """
    Returns the keys of a redvypr data dictionary without the standard
    keys (host','device','numpacket') as well as keys with an
    '@' in it.
    Args:
        data (dict): redvypr data dictionary 
        rem_standard (bool): Remove host, device
        rem_tnum (bool): Remove t, numpacket
        rem_props (bool): Remove property keys (i.e. keys starting with a '?'?
    
        data (dict): 
        rem_props (bool): 
    """
    keys = list(data.keys())
    if rem_tnum:
        keys.remove('t')
        keys.remove('numpacket')
    if rem_standard:        
        keys.remove('host')
        keys.remove('device')
    if rem_props:
        for k in keys:
            if('?' in k):
                keys.remove(k)
            
    return keys

def get_devicename_from_data(data,uuid=False):
    """ Returns a redvypr devicename string including the hostname, ip with the optional uuid.
    
    Args:
        data (dict): A redvypr data dictionary
        uuid (Optional[bool]): Default False. Returns the devicename with the uuid (True) or the hostname + IP-Address (False)
        
    Returns:
        str: The full devicename
    """
    if(uuid):
        devicename = data['device'] + ':' + data['host']['hostname'] + '@' + data['host']['addr'] + '::' + data['host']['uuid']
    else:
        devicename = data['device'] + ':' + data['host']['hostname'] + '@' + data['host']['addr']
    return devicename


def get_datastream_from_data(data,datakey,uuid=False):
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
    devicestr = get_devicename_from_data(data,uuid)
    if((datakey == None) or (datakey == '')):
        return devicestr
    else:
        if(datakey in data.keys()):
            datastream = datakey + '/' + devicestr
        else:
            None
        
    
def get_datastreams_from_data(data,uuid=False):
    """ Returns all datastreams of the datapacket
    
    Args:
        data (dict): A redvypr data dictionary
        uuid (Optional[bool]): Default False. Returns the devicename with the uuid (True) or the hostname + IP-Address (False)
        
    Returns:
        list: A list of all datastreams
    """
    datastreams = []
    datakeys = get_keys_from_data(data)
    devicename = get_devicename_from_data(data,uuid=True)
    for key in datakeys:
        datastream = key + '/' + devicename
        datastreams.append(datastream)
        
    return datastreams


def get_datastream(datakey,data=None,device=None,hostname=None,uuid=False,ip=False):
    """ Returns a datastream string based either on a data packet or on hostname 
    
    Args:
        datakey (str): The key for the datastream
        data (dict): A redvypr data dictionary
        hostname (str): The hostname
        uuid (Optional[bool]): Default False. Returns the devicename with the uuid (True) or the hostname + IP-Address (False)
        
    Returns:
        str: The full devicename
    """
    
    
    if((data == None) and (device == None)):
        raise TypeError('Either data or device need to be not None')
    
    if(data is not None):
        device = data['device']
        hostname = data['host']['hostname']
        addr = data['host']['addr']
        uuid = data['host']['uuid']
        
    datastream = datakey + '/' + device
        
    return datastream

def device_in_data(devicestring, data, get_devicename = False):
    """ Checks if the devicestring (or datastream) is in the datapacket. 
    
    Examples of devicestrings:
        - Devicename: rand1
        - Devicename with hostname: rand1:randredvypr
        - Devicename with ip and any hostname: rand1:*@192.168.178.33
        - Devicename with uuid: rand1::5c9295ee-6f8e-11ec-9f01-f7ad581789cc
        - Devicename with hostname, IP and uuid: rand1:redvypr1@192.168.178.33::5c9295ee-6f8e-11ec-9f01-f7ad581789cc
        
    Examples of datastreams:        
        - 'data' key: data/rand1:randredvypr
        - 't' key with with uuid: t/randdata::5c9295ee-6f8e-11ec-9f01-f7ad581789cc
        
        
    An example data packet with different devicestrings::

        from redvypr.data_packets import device_in_data
        
        data = {'t': 1648623649.1282434, 'data': 1.2414117419163326, '?data': {'unit': 'randomunit', 'type': 'f'}, 'device': 'testranddata', 'host': {'hostname': 'redvyprtest', 'tstart': 1648623606.2900488, 'addr': '192.168.132.74', 'uuid': '07b7a4de-aff7-11ec-9324-135f333bc2f6'}, 'numpacket': 212}
        devicestrings = ['testranddata']
        devicestrings.append('*')
        devicestrings.append('testranddata:redvyprtest')
        devicestrings.append('data/testranddata:redvyprtest')
        devicestrings.append('testranddata:someotherredvypr')
        devicestrings.append('testranddata:*@192.168.132.74')
        devicestrings.append('testranddata::07b7a4de-aff7-11ec-9324-135f333bc2f6')
        devicestrings.append('*::07b7a4de-aff7-11ec-9324-135f333bc2f6')
        devicestrings.append('*::someotheruuid')
        devicestrings.append('t/*')
        for devicestr in devicestrings:
            print('Devicestring',devicestr)
            result = device_in_data(devicestr,data)
            print(result)
            result = device_in_data(devicestr,data,get_devicename=True)
            print(result)
            print('-------')
    
    Args:
        devicestring (str): String or list of strings consisting the devicename and, optionally, the hostname/respectively IP-Adress
        data (dict): a redvypr data dictionary
        get_devicename(Optional[bool]): Default False: 
    Returns:
        bool or list: 
            - bool: True if devicestring agrees with data dictionary [get_devicename=False]
            - list: [bool,devicename,expanded]: First entry True is devicestring agrees with dictionary, second entry: the devicename string, third entry True if devicestring was expanded
    
    """

    # TODO: replace with parse_devicestring()
    if(type(devicestring) == str):
        devicestring = [devicestring]

    for devstring_full in devicestring:
        device_parsed = parse_devicestring(devstring_full) 
        datakey       = device_parsed['datakey']
        uuid          = device_parsed['uuid']
        devicename    = device_parsed['devicename']
        hostname      = device_parsed['hostname']
        addr          = device_parsed['addr']
        
        
        deviceflag  = (devicename  == data['device'])            or device_parsed['deviceexpand']
        hostflag    = (hostname    == data['host']['hostname'])  or device_parsed['hostexpand'] 
        addrflag    = (addr        == data['host']['addr'])      or device_parsed['addrexpand'] 
        uuidflag    = (uuid        == data['host']['uuid'])      or device_parsed['uuidexpand']
        localflag   = data['host']['local']                      and device_parsed['local']
        
        if(datakey is not None):
            if(datakey in data.keys()):
                flag_datakey = True
                key_str = datakey
            else: # If the key does not fit, return False immidiately
                flag_datakey = False 
                
                if(get_devicename):
                    return [False,None,False]
                else:
                    return False
                
        if(deviceflag and localflag):
            if(get_devicename):
                devicename = get_datastream_from_data(key_str,data,uuid=True)
                #devicename = key_str + data['device'] + ':' + data['host']['hostname'] + '@' + data['host']['addr']
                return [True,devicename,deviceexpanded or hostexpanded or addrexpanded]
            else:
                return True

        elif(deviceflag and hostflag and addrflag):
            if(get_devicename):
                devicename = get_datastream_from_data(key_str,data,uuid=True)
                #devicename = key_str + data['device'] + ':' + data['host']['hostname'] + '@' + data['host']['addr']
                return [True,devicename,deviceexpanded or hostexpanded or addrexpanded]
            else:
                return True
            
        elif(deviceflag and uuidflag):
            if(get_devicename):
                devicename = get_datastream_from_data(key_str,data,uuid=True)
                #devicename = key_str + data['device'] + '::' + data['host']['uuid']
                return [True,devicename,deviceexpanded or uuidexpanded]                    
            else:
                return True                

    if(get_devicename):
        return [False,None,False]
    else:
        return False
    
    
    
    

def datadict(data,datakey=None,tu=None):
    """ A datadictionary used as internal datastructure in redvypr
    """
    if(tu == None):
        tu = time.time()
    if(datakey == None):
        datakey = 'data'
        
    datadict = {'t':tu}
    datadict[datakey] = data
    return datadict
