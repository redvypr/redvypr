import time

def get_keys(data):
    """Returns the keys of a redvypr data dictionary without the standard
    keys ('t', 'host','device','numpacket') as well as keys with an
    '@' in it.

    """
    keys = list(data.keys())
    keys.remove('t')
    keys.remove('host')
    keys.remove('device')
    keys.remove('numpacket')
    for k in keys:
        if('@' in k):
            keys.remove(k)
            
    return keys

def get_devicename(data,uuid=False):
    """ Returns a devicename including the hostname, ip or uuid.
    
    Args:
        data (dict): A redvypr data dictionary
        uuid (Optional[bool]): Default False. Returns the devicename with the uuid (True) or the hostname + IP-Address (False)
        
    Returns:
        str: The full devicename
    """
    if(uuid):
        devicename = data['device'] + '::' + data['host']['uuid']
    else:
        devicename = data['device'] + ':' + data['host']['name'] + '@' + data['host']['addr']
    return devicename


def get_datastream(datakey,data=None,device=None,hostname=None,uuid=False,ip=False):
    """ Returns a datastream string based either on a  data packet or on hostname 
    
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
        hostname = data['host']['name']
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
        
    Examples of datastreams:        
        - 'data' key: data/rand1:randredvypr
        - 't' key with with uuid: t/randdata::5c9295ee-6f8e-11ec-9f01-f7ad581789cc
        
        
    An example data packet with different devicestrings::

        from redvypr.data_packets import device_in_data
        
        data = {'t': 1648623649.1282434, 'data': 1.2414117419163326, '?data': {'unit': 'randomunit', 'type': 'f'}, 'device': 'testranddata', 'host': {'name': 'redvyprtest', 'tstart': 1648623606.2900488, 'addr': '192.168.132.74', 'uuid': '07b7a4de-aff7-11ec-9324-135f333bc2f6'}, 'numpacket': 212}
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
    if(type(devicestring) == str):
        devicestring = [devicestring]

    for devstring_full in devicestring:
        # Check first if we have a datastream
        if('/' in devstring_full):

            s = devstring_full.split('/')
            datakey   = s[0]
            devstring = s[1]
            if(datakey in data.keys()):
                flag_datakey = True
                key_str = datakey + '/' # This will be an addon to the devicename
            else: # If the key does not fit, return False immidiately
                flag_datakey = False 
                
                if(get_devicename):
                    return [False,None,False]
                else:
                    return False

        else:
            key_str = ''
            devstring = devstring_full
            
        # First distinguish between the different realizations of the devicestring
        UUID = None
        if('::' in devstring): # UUID
            s = devstring.split('::')
            devicename = s[0]
            UUID = s[1]
        elif(':' in devstring): # hostname
            s = devstring.split(':')
            devicename = s[0]
            rest       = s[1]
            if('@' in rest):
                hostname = rest.split('@')[0]
                addr     = rest.split('@')[1]
            else:
                hostname = rest
                addr     = data['host']['addr'] 
        else:
            devicename = devstring
            hostname   = data['host']['name'] # Take the hostname from the data as it is not defined
            addr       = data['host']['addr'] 
            
        if(UUID==None): # Return the IP address
            hostexpanded = (hostname == '*')
            if(hostexpanded):
                hostname = data['host']['name']
                
            addrexpanded = (addr == '*')
            if(addrexpanded):
                addr = data['host']['addr']
                
            deviceexpanded  = (devicename == '*')
            
            deviceflag = (devicename == data['device'])        or deviceexpanded
            hostflag   = (hostname   == data['host']['name'])  or hostexpanded 
            addrflag    = (addr       == data['host']['addr']) or addrexpanded 
            if(deviceflag and hostflag and addrflag):
                if(get_devicename):
                    devicename = key_str + data['device'] + ':' + data['host']['name'] + '@' + data['host']['addr']
                    return [True,devicename,deviceexpanded or hostexpanded or addrexpanded]
                else:
                    return True
        else:
            deviceexpanded = (devicename == '*')
            deviceflag     = (devicename == data['device'])        or deviceexpanded
            uuidexpanded   = (UUID == '*')
            uuidflag       = (UUID == data['host']['uuid'])        or uuidexpanded
            if(deviceflag and uuidflag):
                if(get_devicename):
                    devicename = key_str + data['device'] + '::' + data['host']['uuid']
                    return [True,devicename,deviceexpanded or uuidexpanded]                    
                else:
                    return True                

    if(get_devicename):
        return [False,None,False]
    else:
        return False
    
    
def device_in_data_old(devicestring, data, get_devicename = False):
    """ Checks if the devicestring is in the datapacket.
    Arguments:
        :param str devicestr: The person sending the message
        :devicestring: String or list of strings consisting the devicename and, optionally, the hostname/respectively IP-Adress
        Examples : Devicename: rand1, Devicename with hostname: rand1@randredvypr, Devicename with ip: rand1@192.168.178.33, Devicename with uuid: rand1@5c9295ee-6f8e-11ec-9f01-f7ad581789cc
        :data: a redvypr data dictionary
    Returns:
    
    """
    if(type(devicestring) == str):
        devicestring = [devicestring]

    for devstring in devicestring:

        if('@' in devstring): # Return the IP address
            devicename = devstring.split('@')[0]
            hostname   = devstring.split('@')[1]
            hostexpanded = (hostname == '*')
            if(hostexpanded):
                hostname = data['host']['name']
                
            expanded   = (devicename == '*')
            deviceflag = (devicename == data['device']) or expanded
            hostflag = (hostname == data['host']['name']) or (hostname == data['host']['addr'])
            if(deviceflag and hostflag):
                devicename = data['device'] + '@' + hostname                
                if(get_devicename):
                    return [True,devicename,expanded or hostexpanded]
                else:
                    return True
        elif(':' in devstring): # Return the IP address
            pass
        else:
            expanded   = (devstring == '*')
            if((devstring == data['device']) or expanded):
                if(get_devicename):
                    return [True,data['device'],expanded]                    
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
