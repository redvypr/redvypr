import copy
import time
import logging
import sys
import re
import redvypr.config

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('data_packets')
logger.setLevel(logging.DEBUG)


# A dictionary for the device_redvypr entry in the statistics
device_redvypr_statdict = {'_redvypr': {}, 'datakeys': [], '_deviceinfo': {},'_keyinfo': {},'packets_received':0,'packets_sent':0}



def treat_datadict(data, devicename, hostinfo, numpacket, tpacket,devicemodulename=''):
    """ Treats a datadict received from a device and adds additional information from redvypr as hostinfo, numpackets etc.
    """
    # Add deviceinformation to the data package
    if ('_redvypr' not in data.keys()):
        data['_redvypr'] = {}
    if ('tag' not in data['_redvypr'].keys()): # A tag of the uuid, counting the number of times the packet has been recirculated
        data['_redvypr']['tag'] = {}
    if ('device' not in data['_redvypr'].keys()):
        data['_redvypr']['device'] = str(devicename)
    if ('host' not in data['_redvypr'].keys()):
        data['_redvypr']['host']   = hostinfo
    else:  # Check if we have a local data packet, i.e. a packet that comes from another redvypr instance with another UUID
        data['_redvypr']['host']['local'] = data['_redvypr']['host']['uuid'] == hostinfo['uuid']

    # Tag the datapacket
    try:
        data['_redvypr']['tag'][hostinfo['uuid']] += 1
    except:
        data['_redvypr']['tag'][hostinfo['uuid']] = 1

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

#
#
#
#
#
class redvypr_address():
    """ redvypr address


    addresses are equal if there .address_str are equal
    TODO: let addrstr be another redvypr address and replace parts if datakay etc. is given
    TODO: let given datakey, devicename etc. replace the potentially defined address

    """
    def __init__(self,addrstr=None,datapacket=None,local_hostinfo=None, datakey='',devicename='',hostname='',addr='',uuid='',redvypr_meta=None):
        """

        Args:
            addrstr:
            datapacket:
            local_hostinfo:
            datakey:
            devicename:
            hostname:
            addr:
            uuid:
            redvypr_meta:
        """
        FLAG_MODIFIABLE = False
        if addrstr is not None: # Address from addrstr
            #print('addrstr',type(addrstr),type(self))
            if type(addrstr) == type(self):
                print('redvypr address')
                self.address_str = addrstr.address_str
            else:
                self.address_str = addrstr
            FLAG_MODIFIABLE=True
        elif redvypr_meta is not None:  # Address from _redvypr meta information
            self.address_str = get_deviceaddress_from_redvypr_meta(redvypr_meta, uuid=True)
            FLAG_MODIFIABLE = True
        elif datapacket is not None:  # Address from datapacket
            if(len(datakey)>0):
                datakey_tmp = datakey
            else:
                datakey_tmp = None
            self.address_str = get_datastream_from_data(datapacket,datakey = datakey_tmp,uuid=True)
            FLAG_MODIFIABLE = True
        else: # addrsstr from single ingredients
            self.address_str = create_addrstr(datakey,devicename,hostname,addr,uuid,local_hostinfo=local_hostinfo)
            FLAG_MODIFIABLE = False
            #print('Address string',self.address_str)
        if (type(self.address_str) is not str):
            raise ValueError('Unsupported type of address str {:s}'.format(str(type(self.address_str))))



        if FLAG_MODIFIABLE:
            #modify_addrstr(addrstr, datakey='', devicename='', hostname='', addr='', uuid='', local_hostinfo=None):
            if (len(datakey) > 0) or (len(devicename) > 0) or (len(hostname) > 0) or (len(addr) > 0 ) or (len(uuid) > 0):
                self.__address_str_orig__ = self.address_str[:]
                self.address_str = modify_addrstr(self.address_str, datakey=datakey, devicename = devicename, hostname = hostname, addr=addr)


        self.parsed_addrstr = parse_addrstr(self.address_str, local_hostinfo=local_hostinfo)

        self.strtypes = ['<key>','<key>/<device>']
        self.strtypes.append('<key>/<device>:<host>')
        self.strtypes.append('<key>/<device>:<host>@<addr>')
        self.strtypes.append('<key>/<device>:<host>@<addr>::<uuid>')
        self.strtypes.append('<key>/<device>::<uuid>')
        self.strtypes.append('<device>:<host>')
        self.strtypes.append('<device>:<host>@<addr>')
        self.strtypes.append('<device>:<host>@<addr>::<uuid>')
        self.strtypes.append('<device>:<host>::<uuid>')
        self.strtypes.append('<device>')
        self.strtypes.append('<host>')
        self.strtypes.append('<addr>')
        self.strtypes.append('<uuid>')


        self.datakey      = self.parsed_addrstr['datakey']
        self.datakeyexpand = self.parsed_addrstr['datakeyexpand']

        self.devicename   = self.parsed_addrstr['devicename']
        self.deviceexpand = self.parsed_addrstr['deviceexpand']

        self.hostname     = self.parsed_addrstr['hostname']
        self.hostexpand = self.parsed_addrstr['hostexpand']

        self.addr         = self.parsed_addrstr['addr']
        self.addrexpand = self.parsed_addrstr['addrexpand']

        self.uuid         = self.parsed_addrstr['uuid']
        self.uuidexpand = self.parsed_addrstr['uuidexpand']

        self.local        = self.parsed_addrstr['local']

    def get_strtypes(self):
        """
        Returns a list of available datastream str types
        Returns:

        """
        return self.strtypes

    def get_str(self,strtype = 'full'):
        """

        Args:
            strtype:

        Returns:

        """
        funcname = __name__ + '.get_str():'
        try:
            if(strtype == 'full'):
                return self.address_str
            elif(strtype == '<key>'):
                return self.parsed_addrstr['datakey']
            elif (strtype == '<device>'):
                return self.parsed_addrstr['devicename']
            elif (strtype == '<host>'):
                return self.parsed_addrstr['hostname']
            elif (strtype == '<addr>'):
                return self.parsed_addrstr['addr']
            elif (strtype == '<uuid>'):
                return self.parsed_addrstr['uuid']
            elif (strtype == '<key>/<device>'):
                return self.parsed_addrstr['datakey'] + '/' + self.parsed_addrstr['devicename']
            elif (strtype == '<key>/<device>:<host>'):
                return self.parsed_addrstr['datakey'] + '/' + self.parsed_addrstr['devicename'] + ':' + self.parsed_addrstr['hostname']
            elif (strtype == '<key>/<device>:<host>@<addr>'):
                return self.parsed_addrstr['datakey'] + '/' + self.parsed_addrstr['devicename'] + ':' + self.parsed_addrstr[
                    'hostname'] + '@' + self.parsed_addrstr['addr']
            elif (strtype == '<key>/<device>:<host>@<addr>::<uuid>'):
                return self.parsed_addrstr['datakey'] + '/' + self.parsed_addrstr['devicename'] + ':' + self.parsed_addrstr[
                    'hostname'] + '@' + self.parsed_addrstr['addr'] + '::' + self.parsed_addrstr['uuid']
            elif (strtype == '<device>:<host>'):
                return self.parsed_addrstr['devicename'] + ':' + self.parsed_addrstr['hostname']
            elif (strtype == '<device>:<host>@<addr>'):
                return self.parsed_addrstr['devicename'] + ':' + self.parsed_addrstr['hostname'] + '@' + \
                       self.parsed_addrstr['addr']
            elif (strtype == '<device>:<host>::<uuid>'):
                return self.parsed_addrstr['devicename'] + ':' + self.parsed_addrstr['hostname'] + '::' + self.parsed_addrstr['uuid']
            elif (strtype == '<device>:<host>@<addr>::<uuid>'):
                return self.parsed_addrstr['devicename'] + ':' + self.parsed_addrstr['hostname'] + '@' + self.parsed_addrstr['addr'] + '::' + self.parsed_addrstr['uuid']
            elif (strtype == '<key>/<device>::<uuid>'):
                return self.parsed_addrstr['datakey'] + '/' + self.parsed_addrstr['devicename'] + '::' + self.parsed_addrstr['uuid']
        except Exception as e:
            logger.debug(funcname + ':{:s}'.format(str(e)))
            return 'NA'

        return 'NA2'

    def get_data(self,datapacket):
        """
        Returns the data in the datapacket that fits with the address.

        Args:
            datapacket: redvypr_datapacket

        Returns: list
            List with each element containing a tuple with the first element being the data and the second element the datakey.
        """
        data = []
        if self.datakeyexpand == False: # We have a defined datakey
            data.append((datapacket[self.datakey],self.datakey))

        else:
            keys = get_keys_from_data(datapacket)
            for k in keys:
                datatuple = (datapacket[k], k)
                data.append(datatuple)

        return data

    def __repr__(self):
        #astr2 = self.get_str('<key>/<device>:<host>@<addr>')
        astr2 = self.address_str
        astr = "redvypr_address('" + astr2 + "')"
        return astr

    def __eq__(self, addr):
        """
        Compares a second redvypr_address with this one by comparing the
        address_str, if they are equal the redvypr_addresses are defined as equal.
        If a string is given, the string is compared to self.address_str, otherwise
        False is returned
        Args:
            addr:

        Returns:

        """
        if type(addr) == redvypr_address:
            streq = self.address_str == addr.address_str
            return streq
        elif type(addr) == str:
            streq = self.address_str == addr
            return streq
        else:
            return False


    def __contains__(self, data):
        """ Depending on the type of data
        - it checks if address is in data, if data is a redvypr data structure (datapacket)
        - it checks if addresses match between self and data, if data is a redvypr_address
        - it converts a string or configString into a redvypr_address and checks if addresses match
        """
        if (type(data) == dict):
            datapacket = data
            deviceflag = (self.devicename == datapacket['_redvypr']['device']) or self.deviceexpand
            hostflag = (self.hostname == datapacket['_redvypr']['host']['hostname']) or self.hostexpand
            addrflag = (self.addr == datapacket['_redvypr']['host']['addr']) or self.addrexpand
            uuidflag = (self.uuid == datapacket['_redvypr']['host']['uuid']) or self.uuidexpand
            localflag = datapacket['_redvypr']['host']['local'] and self.local
            #print('deviceflag', deviceflag)
            #print('hostflag', deviceflag)
            #print('addrflag', addrflag)
            #print('uuidflag', uuidflag)
            #print('localflag', localflag)
            #print('uuidexpand', self.uuid,self.uuidexpand)
            if(len(self.datakey) > 0):
                if (self.datakey in datapacket.keys() or self.datakey == '*'):
                    pass
                else:  # If the key does not fit, return False immidiately
                    return False

            if (deviceflag and localflag and uuidflag):
                return True
            elif (deviceflag and hostflag and addrflag and uuidflag):
                return True
            elif (deviceflag and uuidflag):
                return True

            return False

        elif(type(data) == redvypr_address):
            addr = data
            print('Redvypr address')
            datakeyflag = (self.datakey == addr.datakey) or self.datakeyexpand or addr.datakeyexpand
            deviceflag = (self.devicename == addr.devicename) or self.deviceexpand or addr.deviceexpand
            hostflag = (self.hostname == addr.hostname) or self.hostexpand or addr.hostexpand
            addrflag = (self.addr == addr.addr) or self.addrexpand or addr.addrexpand
            uuidflag = (self.uuid == addr.uuid) or self.uuidexpand or addr.uuidexpand
            localflag = self.local and addr.local

            # print('Datakeyflag',datakeyflag)
            # print('Deviceflag',deviceflag)
            # print('Hostflag',hostflag)
            # print('addr',addrflag)
            # print('uuidflag',uuidflag)
            # print('localflag',localflag)

            # matchflag1  = datakeyflag and deviceflag and hostflag and addrflag
            # matchflag2 = datakeyflag  and deviceflag and uuidflag
            matchflag3 = datakeyflag and deviceflag and hostflag and addrflag and uuidflag

            return matchflag3  # 1 or matchflag2

        elif (type(data) == str) or (type(data) == redvypr.config.configString):
            raddr = redvypr_address(str(data))
            contains = raddr in self
            return contains
        else:
            raise ValueError('Unknown data type')

def create_data_statistic_dict():
    statdict = {}
    statdict['inspect']          = True
    statdict['packets_sent']     = 0
    statdict['packets_received'] = 0
    statdict['datakeys']         = []
    statdict['devicekeys']       = {}
    statdict['devices']          = []
    statdict['devices_dict']     = {}
    statdict['datastreams']      = []
    statdict['datastreams_dict'] = {}
    statdict['datastreams_info'] = {}
    statdict['hostinfos']        = {}
    # New
    statdict['datakey_info']       = {}
    statdict['datastream_redvypr'] = {}
    statdict['device_redvypr']     = {}
    statdict['host_redvypr']       = {}
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

def do_data_statistics(data, statdict):
    """
    Fills in the statistics dictionary with the data packet information
    Args:
        data:
        statdict:
    """
    statdict['packets_sent'] += 1
    uuid = data['_redvypr']['host']['uuid']
    # Create a unique list of datakeys
    statdict['datakeys'] = list(set(statdict['datakeys'] + list(data.keys())))
    # Create a unqiue list of devices, device can
    # be different from the transporting device,
    # i.e. network devices do not change the name
    # of the transporting dictionary
    devicename_stat = get_devicename_from_data(data,uuid=True)
    try:
        statdict['devicekeys'][devicename_stat]
    except:
        statdict['devicekeys'][devicename_stat] = []
        
    statdict['devicekeys'][devicename_stat] = list(set(statdict['devicekeys'][devicename_stat] + list(data.keys())))
    statdict['devices']                     = list(set(statdict['devices'] + [devicename_stat])) # This list collects all devices distributed by the actual device. This is helpful for brokers like iored or network.
    try:
        statdict['devices_dict'][devicename_stat]['host'].update(data['_redvypr']['host'])
    except:
        statdict['devices_dict'][devicename_stat] = {'host':data['_redvypr']['host']}

    [datastreams_stat,datastreams_dict]     = get_datastreams_from_data(data,uuid=True,add_dict=True)
    statdict['datastreams']                 = list(set(statdict['datastreams'] + datastreams_stat))
    statdict['datastreams_dict'].update(datastreams_dict)
    # Create a hostinfo information
    try:
        statdict['hostinfos'][uuid].update(data['_redvypr']['host'])
    except:
        statdict['hostinfos'][uuid] = data['_redvypr']['host']


    # new
    statdict['datastream_redvypr'].update(datastreams_dict)
    # Create a hostinfo information
    try:
        statdict['host_redvypr'][uuid].update(data['_redvypr']['host'])
    except:
        statdict['host_redvypr'][uuid] = data['_redvypr']['host']

    # Create device_redvypr
    try:
        statdict['device_redvypr'][devicename_stat]['packets_sent'] += 1
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

    ## Create status skeleton if not existing
    #try:
    #    statdict['device_redvypr'][devicename_stat]['_redvypr']['status']
    #except:
    #    statdict['device_redvypr'][devicename_stat]['_redvypr']['status'] = {}


    return statdict


def expand_address_string(addrstr):
    """ Expands an address string, i.e. it fills non existing entries with wildcards. 
    """
    devstring_full = addrstr

    devstring = devstring_full
    local = True
    # Check first if we have an UUID
    #'data/randdata_1:redvypr@192.168.178.26::04283d40-ef3c-11ec-ab8f-21d63600f1d0'
    FLAG_ANY_SEPARATORS = False
    if('::' in devstring): # UUID
        s         = devstring.split('::',1)
        devstring = s[0]
        uuid      = s[1]
        local     = False
        FLAG_ANY_SEPARATORS = True
    else:
        uuid      = '*'

    if ('@' in devstring):
        s = devstring.split('@',1)
        addr = s[1]
        devstring = s[0]
        FLAG_ANY_SEPARATORS = True
    else:
        addr = '*'

    if(':' in devstring): # hostname
        local     = False
        s = devstring.split(':',1)
        hostname  = s[1]
        devstring = s[0]
        FLAG_ANY_SEPARATORS = True
    else:
        hostname = '*'

    # Check first if we have a datastream string
    if ('/' in devstring):
        s = devstring.split('/',1)
        datakey    = s[0]
        devicename = s[1]
        FLAG_ANY_SEPARATORS = True
    else:
        devicename = devstring
        datakey   = '*'

    # Is a sole string a datakey or a devicename
    #if(FLAG_ANY_SEPARATORS == False) and (sole_devicename == False):
    if (FLAG_ANY_SEPARATORS == False):
        devicename = devstring
        datakey = '*'


    #if(local): # No UUID and addr
    #    uuid = 'local'

    address_string = datakey + '/' + devicename + ':' + hostname + '@' + addr + '::' + uuid
    return address_string


def modify_addrstr(addrstr,datakey='',devicename='',hostname='',addr='',uuid='',local_hostinfo=None):
    """
    Modifies address string with optionally given arguments. Note that missing parts are replaced by wildcards:
    modify_addrstr('test') becomes */test:*@*::*.

    Args:
        addrstr: Address string to be modified
        datakey:
        devicename:
        hostname:
        addr:
        uuid:
        local_hostinfo:

    Returns:
        Modified address string
    """

    parsed_str = parse_addrstr(addrstr,local_hostinfo=local_hostinfo)
    if len(datakey) > 0:
        parsed_str['datakey'] = datakey
    if len(devicename) > 0:
        parsed_str['devicename'] = devicename
    if len(hostname) > 0:
        parsed_str['hostname'] = hostname
    if len(addr) > 0:
        parsed_str['addr'] = addr
    if len(uuid) > 0:
        parsed_str['uuid'] = uuid

    addrstr_mod = create_addrstr(datakey=parsed_str['datakey'],devicename=parsed_str['devicename'],hostname=parsed_str['hostname'],addr=parsed_str['addr'],uuid=parsed_str['uuid'])
    return addrstr_mod



def create_addrstr(datakey='',devicename='',hostname='',addr='',uuid='',local_hostinfo=None):
    """
    Creates an address string from given ingredients
    Args:
        datakey:
        devicename:
        hostname:
        addr:
        uuid:
        local_hostinfo:

    Returns:

    """
    if local_hostinfo is not None:
        if len(uuid) == 0:
            uuid = local_hostinfo['uuid']
        if len(addr) == 0:
            addr = local_hostinfo['addr']
        if len(hostname) == 0:
            hostname = local_hostinfo['hostname']
    else:
        if len(uuid) == 0:
            uuid = '*'
        if len(addr) == 0:
            addr = '*'
        if len(hostname) == 0:
            hostname = '*'

    if len(datakey) > 0:
        datakey = datakey + '/'
    if len(devicename) > 0:
        devicename = devicename + ':'

    address_str = datakey + devicename + hostname + '@' + addr + '::' + uuid
    return address_str


def parse_addrstr(address_string,local_hostinfo=None):
    """
     Parses as redvypr address string and returns a dictionary with the parsed result
    
        address_string: the devicestring
        local_hostinfo: if the devicestring is local, the local hostinfo is used to fill in hostname, ip and UUID etc. 
    """
    devstring_full = expand_address_string(address_string)
    # Check first if we have a datastream
    datakeyexpanded = False
    s = devstring_full.split('/',1)
    datakey   = s[0]
    devstring = s[1]
    if(datakey == '*'):
        datakeyexpanded = True

    s         = devstring.split('::',1)
    devstring = s[0]
    uuid      = s[1]
    s = devstring.split(':',1)
    devicename = s[0]
    rest       = s[1]
    hostname = rest.split('@')[0]
    addr     = rest.split('@')[1]

    hostexpanded   = (hostname == '*')
    addrexpanded   = (addr == '*')
    deviceexpanded = (devicename == '*')
    uuidexpanded   = (uuid == '*')
    local = uuid == 'local'
    if(local and (local_hostinfo is not None)):
        hostname = local_hostinfo['hostname']
        addr     = local_hostinfo['addr']
        uuid     = local_hostinfo['uuid']
        uuidexpanded   = False
        addrexpanded   = False
        deviceexpanded = False

    # Fill a dictionary
    parsed_data = {}
    parsed_data['address_string']          = address_string
    parsed_data['address_string_expanded'] = devstring_full
    parsed_data['hostname']     = hostname
    parsed_data['addr']         = addr
    parsed_data['devicename']   = devicename
    parsed_data['uuid']         = uuid
    parsed_data['datakey']      = datakey
    parsed_data['hostexpand']   = hostexpanded
    parsed_data['datakeyexpand']= datakeyexpanded
    parsed_data['addrexpand']   = addrexpanded
    parsed_data['deviceexpand'] = deviceexpanded
    parsed_data['uuidexpand']   = uuidexpanded            
    parsed_data['local']        = local
    
    return parsed_data






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
    try:
        keys.remove('_redvypr')
    except:
        pass

    try:
        keys.remove('_redvypr_command')
    except:
        pass

    try:
        keys.remove('_deviceinfo')
    except:
        pass

    try:
        keys.remove('_keyinfo')
    except:
        pass

    return keys


def get_deviceaddress_from_redvypr_meta(_redvypr,uuid=False):
    return get_devicename_from_data({'_redvypr':_redvypr},uuid=uuid)

def get_devicename_from_data(data,uuid=False):
    """ Returns a redvypr devicename string including the hostname, ip with the optional uuid.
    
    Args:
        data (dict): A redvypr data dictionary
        uuid (Optional[bool]): Default False. Returns the devicename with the uuid (True) or the hostname + IP-Address (False)
        
    Returns:
        str: The full devicename
    """
    if(uuid):
        devicename = data['_redvypr']['device'] + ':' + data['_redvypr']['host']['hostname'] + '@' + data['_redvypr']['host']['addr'] + '::' + data['_redvypr']['host']['uuid']
    else:
        devicename = data['_redvypr']['device'] + ':' + data['_redvypr']['host']['hostname'] + '@' + data['_redvypr']['host']['addr']
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
        
    
def get_datastreams_from_data(data,uuid=False,add_dict=False):
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
    devicename = get_devicename_from_data(data,uuid=True)
    for key in datakeys:
        datastream = key + '/' + devicename
        datastreams.append(datastream)
        datastreams_dict[datastream] = {'host':data['_redvypr']['host']}

    if(add_dict):
        return [datastreams,datastreams_dict]
    else:
        return datastreams


def get_address_from_data(datakey,data=None,device=None,hostinfo=None,style='<datakey>/<device>'):
    """ Returns an address string based either on a data packet or on hostname
    
    Args:
        datakey (str): The key for the datastream
        data (dict): A redvypr data dictionary
        hostname (str): The hostname
        uuid (Optional[bool]): Default False. Returns the devicename with the uuid (True) or the hostname + IP-Address (False)
        
    Returns:
        str: The full datastream
    """


    
    
    if((data == None) and (device == None)):
        raise TypeError('Either data or device need to be not None')
    
    if(data is not None):
        device = data['_redvypr']['device']
        hostname = data['_redvypr']['host']['hostname']
        addr = data['_redvypr']['host']['addr']
        uuid = data['_redvypr']['host']['uuid']
    else:
        if(hostinfo == None):
            hostname = '*'
            uuid     = '*'
            addr     = '*'            
        else:
            hostname = hostinfo['hostname']
            uuid     = hostinfo['uuid']
            addr     = hostinfo['addr']

    raddr = redvypr_address(local_hostinfo=hostinfo, datakey=datakey, devicename=device)
    datastream = raddr.get_str(style)
    #if(style=='<datakey>/<device>'):
    #    datastream = datakey + '/' + device
    #elif (style=='full') or (style == '<device>:<host>@<addr>::<uuid>'):
    #    datastream = datakey + '/' + device + ':' + hostname + '@' + addr + '::' + uuid
    #else:
    #    raise ValueError('Unknown style')
        
    return datastream


def compare_datastreams(datastream1, datastream2, hostinfo=None):
    """ Checks if the two datastreams match
    
    Examples of datastreams::
            
        d1 = data/rand1:randredvypr
        d2 = 't/randdata::5c9295ee-6f8e-11ec-9f01-f7ad581789cc'
        d3 = '?data/randdata_1:redvypr@192.168.178.26::04283d40-ef3c-11ec-ab8f-21d63600f1d0'
        d4 = 'data/randdata_1:redvypr@192.168.178.26::04283d40-ef3c-11ec-ab8f-21d63600f1d0' 
        d5 = 'data/randdata_1:redvypr'
        d6 = 'data/randdata_1::04283d40-ef3c-11ec-ab8f-21d63600f1d0' 
        d7 = '*/randdata_1::04283d40-ef3c-11ec-ab8f-21d63600f1d0' 
        d8 = 'data/randdata_1:*'
        
    Args:
        datastream1 (str): redvypr datastream1 
        datastream2 (str): redvypr datastream2        

    Returns:
        bool: 
            True if datastreams match, False otherwise
    
    """

    # The easiest comparison    
    if(datastream1 == datastream2):
        return True

    if True:
        d1_parsed     = parse_addrstr(datastream1,hostinfo)
        d2_parsed     = parse_addrstr(datastream2,hostinfo)
         
        datakey       = d1_parsed['datakey']
        uuid          = d1_parsed['uuid']
        devicename    = d1_parsed['devicename']
        hostname      = d1_parsed['hostname']
        addr          = d1_parsed['addr']
        
        datakeyflag = (d1_parsed['datakey']     == d2_parsed['datakey'])    or d1_parsed['datakeyexpand'] or d2_parsed['datakeyexpand']
        deviceflag  = (d1_parsed['devicename']  == d2_parsed['devicename']) or d1_parsed['deviceexpand']  or d2_parsed['deviceexpand']
        hostflag    = (d1_parsed['hostname']    == d2_parsed['hostname'])   or d1_parsed['hostexpand']    or d2_parsed['hostexpand'] 
        addrflag    = (d1_parsed['addr']        == d2_parsed['addr'])       or d1_parsed['addrexpand']    or d2_parsed['addrexpand'] 
        uuidflag    = (d1_parsed['uuid']        == d2_parsed['uuid'])       or d1_parsed['uuidexpand']    or d2_parsed['uuidexpand']
        localflag   = d1_parsed['local'] and d2_parsed['local']
        
        #print('Datakeyflag',datakeyflag)
        #print('Deviceflag',deviceflag)
        #print('Hostflag',hostflag)
        #print('addr',addrflag)
        #print('uuidflag',uuidflag)
        #print('localflag',localflag)
        
        #matchflag1  = datakeyflag and deviceflag and hostflag and addrflag
        #matchflag2 = datakeyflag  and deviceflag and uuidflag
        matchflag3  = datakeyflag and deviceflag and hostflag and addrflag and uuidflag
        
        return matchflag3#1 or matchflag2
    
    
    
def get_data(datastream,datapacket):
    """
     Returns the data from the datapacket associated with the datastream
    
        datastream:
        datapacket:
        
        Returns: Content of the data     
    """
    
    datastream_parsed = parse_addrstr(datastream)
    data = datapacket[datastream_parsed['datakey']]
    return data



def addr_in_data(devicestring, datapacket, get_devicename = False):
    """ Checks if the redvypr addr is in the datapacket.
    
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

        from redvypr.data_packets import addr_in_data
        
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
            result = addr_in_data(devicestr,data)
            print(result)
            result = addr_in_data(devicestr,data,get_devicename=True)
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
        device_parsed = parse_addrstr(devstring_full) 
        datakey       = device_parsed['datakey']
        uuid          = device_parsed['uuid']
        devicename    = device_parsed['devicename']
        hostname      = device_parsed['hostname']
        addr          = device_parsed['addr']
        
        
        deviceflag  = (devicename  == datapacket['_redvypr']['device'])            or device_parsed['deviceexpand']
        hostflag    = (hostname    == datapacket['_redvypr']['host']['hostname'])  or device_parsed['hostexpand']
        addrflag    = (addr        == datapacket['_redvypr']['host']['addr'])      or device_parsed['addrexpand']
        uuidflag    = (uuid        == datapacket['_redvypr']['host']['uuid'])      or device_parsed['uuidexpand']
        localflag   = datapacket['_redvypr']['host']['local']                      and device_parsed['local']
        
        #if(datakey is not None):
        if (len(datakey) > 0):
            if(datakey in datapacket.keys()):
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
                devicename = get_datastream_from_data(key_str,datapacket,uuid=True)
                #devicename = key_str + data['device'] + ':' + data['host']['hostname'] + '@' + data['host']['addr']
                return [True,devicename,deviceexpanded or hostexpanded or addrexpanded]
            else:
                return True

        elif(deviceflag and hostflag and addrflag):
            if(get_devicename):
                devicename = get_datastream_from_data(key_str,datapacket,uuid=True)
                #devicename = key_str + data['device'] + ':' + data['host']['hostname'] + '@' + data['host']['addr']
                return [True,devicename,deviceexpanded or hostexpanded or addrexpanded]
            else:
                return True
            
        elif(deviceflag and uuidflag):
            if(get_devicename):
                devicename = get_datastream_from_data(key_str,datapacket,uuid=True)
                #devicename = key_str + data['device'] + '::' + data['host']['uuid']
                return [True,devicename,deviceexpanded or uuidexpanded]                    
            else:
                return True                

    if(get_devicename):
        return [False,None,False]
    else:
        return False





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



__rdvpraddr__ = redvypr_address('tmp')
addresstypes  = __rdvpraddr__.get_strtypes() # A list of all addresstypes

