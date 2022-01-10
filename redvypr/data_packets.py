import time

def redvypr_get_keys(data):
    """Returns the keys of a redvypr data dictionar without the standard
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

def redvypr_get_devicename(data):
    """ Returns a devicename including the hostname, ip or uuid.
    """
    devicename = data['device'] + '@' + data['host']['name']
    return devicename

def redvypr_isin_data(devicestring, data, get_devicename = False):
    """ Checks if the devicestring is in the datapacket.
    Arguments:
    devicestring: String or list of strings consisting the devicename and, optionally, the hostname/respectively IP-Adress
    Examples : Devicename: rand1, Devicename with hostname: rand1@randredvypr, Devicename with ip: rand1@192.168.178.33, Devicename with uuid: rand1@5c9295ee-6f8e-11ec-9f01-f7ad581789cc
    data: a redvypr data dictionary
    """
    if(type(devicestring) == str):
        devicestring = [devicestring]

    for devstring in devicestring:
        if('@' in devstring):
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
        else:
            expanded   = (devstring == '*')
            if((devstring in data['device']) or expanded):
                if(get_devicename):
                    return [True,data['device'],expanded]                    
                else:
                    return True                

    if(get_devicename):
        return [False,None,False]
    else:
        return False



def redvypr_datadict(data,datakey=None,tu=None):
    """ A datadictionary used as internal datastructure in redvypr
    """
    if(tu == None):
        tu = time.time()
    if(datakey == None):
        datakey = 'data'
        
    datadict = {'t':tu}
    datadict[datakey] = data
    return datadict
