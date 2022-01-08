import time

def redvypr_isin_data(devicestring,data):
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
            hostflag = (hostname in data['host']['name']) or (hostname in data['host']['addr'])
            if((devicename in data['device']) and hostflag):
                return True        
        else:
            if(devstring in data['device']):
                return True

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
