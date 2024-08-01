import re
import copy
import time
import logging
import sys
import yaml
import pydantic
import pydantic_core
import typing

from pydantic import BaseModel, Field, TypeAdapter
from pydantic_core import SchemaSerializer, core_schema

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr_address')
logger.setLevel(logging.DEBUG)

s = []
s.append('/uuid:fsfsd/p:*/d:*/ip:*/k:data')
s.append('/k:data/d:"/d:hallo"/')
s.append('/k:data/d:{.*Hallo/d:}/')


RedvyprAddressStr = typing.Annotated[
    str,
    pydantic.WithJsonSchema({'type': 'string'}, mode='serialization'),
    'RedvyprAddressStr'
]


class RedvyprAddress():
    """
    """
    address_str: str
    def __init__(self, addrstr=None, local_hostinfo=None, datakey=None, devicename=None, hostname=None, addr=None, uuid=None, publisher=None, redvypr_meta=None):
        # Some definitions
        self.__regex_symbol_start = '{'
        self.__regex_symbol_end = '}'
        self.__addr_id_links = {'k': 'datakey', 'd': 'devicename', 'a': 'addr', 'u': 'uuid', 'h': 'hostname','p': 'publisher'}
        self.__addr_id_links_r = {'datakey':'k', 'devicename': 'd' , 'addr': 'a', 'uuid': 'u' , 'hostname':'h', 'publisher':'p'}
        self.__addr_ids = ['datakey', 'devicename', 'hostname', 'addr', 'uuid','publisher']
        self.__addr_idsexpand = ['datakeyexpand', 'deviceexpand', 'hostexpand', 'addrexpand', 'uuidexpand','publisherexpand']
        self.__delimiter_parts = '/'
        self.__delimiter_id = ':'

        # Try to convert redvypr_address to dict
        self._common_address_formats = ['/d/k', '/k/','/d/','/p/','/p/d/','/u/a/h/d/', '/u/a/h/d/k/', '/a/h/d/', '/a/h/p/']
        if addrstr is not None: # Address from addrstr
            #print('addrstr',type(addrstr),type(self))
            if type(addrstr) == type(self): # If addrstr is redvypr_address, convert it to str
                self.address_str = addrstr.address_str
            #elif type(addrstr) == dict:  # Address from datapacket # This does not work with inherited classes like redvypr_address
            elif isinstance(addrstr, dict):  # Address from redvypr datapacket # This should work with dict and inherited classes like redvypr_address
                #print('Data packet',addrstr)
                if True:
                    try:
                        publisher_packet = addrstr['_redvypr']['locpub']
                    except:
                        publisher_packet = None
                if True:
                    try:
                        addr_packet = addrstr['_redvypr']['host']['addr']
                    except:
                        pass
                if True:
                    hostname_packet = addrstr['_redvypr']['host']['hostname']
                if True:
                    uuid_packet = addrstr['_redvypr']['host']['uuid']
                if True:
                    devicename_packet = addrstr['_redvypr']['device']

                self.address_str = self.create_addrstr(datakey, devicename_packet, hostname_packet, addr_packet, uuid_packet, publisher_packet,
                                                       local_hostinfo=local_hostinfo)

            elif addrstr == '*':
                self.address_str = self.create_addrstr()
            elif addrstr.startswith('RedvyprAddress(') and addrstr.endswith(')'):
                # string that can be evaluated
                redvypr_address_tmp = eval(addrstr)
                self.address_str = redvypr_address_tmp.address_str
            else:
                self.address_str = addrstr

            # Replace potentially given arguments
            if any([addrstr, local_hostinfo, datakey, devicename, hostname, addr, uuid, publisher]):
                parsed_addrstr = self.parse_addrstr(self.address_str)
                if addr is not None:
                    parsed_addrstr['addr'] = addr
                if datakey is not None:
                    parsed_addrstr['datakey'] = datakey
                if devicename is not None:
                    parsed_addrstr['devicename'] = devicename
                if hostname is not None:
                    parsed_addrstr['hostname'] = hostname
                if uuid is not None:
                    parsed_addrstr['uuid'] = uuid
                if publisher is not None:
                    parsed_addrstr['publisher'] = publisher

                self.address_str = self.create_addrstr(parsed_addrstr['datakey'], parsed_addrstr['devicename'], parsed_addrstr['hostname'], parsed_addrstr['addr'], parsed_addrstr['uuid'], parsed_addrstr['publisher'], local_hostinfo=local_hostinfo)

        else:  # addrstr from single ingredients
            self.address_str = self.create_addrstr(datakey, devicename, hostname, addr, uuid, publisher, local_hostinfo=local_hostinfo)
            # print('Address string',self.address_str)

        parsed_addrstr = self.parse_addrstr(self.address_str)
        self.parsed_addrstr = parsed_addrstr

        # Add the attributes to the object
        self.datakey = parsed_addrstr['datakey']
        self.datakeyexpand = parsed_addrstr['datakeyexpand']

        self.devicename = parsed_addrstr['devicename']
        self.deviceexpand = parsed_addrstr['deviceexpand']

        self.hostname = parsed_addrstr['hostname']
        self.hostexpand = parsed_addrstr['hostexpand']

        self.addr = parsed_addrstr['addr']
        self.addrexpand = parsed_addrstr['addrexpand']

        self.uuid = parsed_addrstr['uuid']
        self.uuidexpand = parsed_addrstr['uuidexpand']

        self.publisher = parsed_addrstr['publisher']

    def get_common_address_formats(self):
        return self._common_address_formats
    def create_addrstr(self, datakey=None, devicename=None, hostname=None, addr=None, uuid=None, publisher=None, local_hostinfo=None):
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

        if datakey is None:
            datakey = '*'
        if devicename is None:
            devicename = '*'
        if hostname is None:
            hostname = '*'
        if addr is None:
            addr = '*'
        if uuid is None:
            uuid = '*'
        if publisher is None:
            publisher = '*'

        if local_hostinfo is not None:
            uuid = local_hostinfo['uuid']
            addr = local_hostinfo['addr']
            hostname = local_hostinfo['hostname']

        address_str = self.__delimiter_parts
        address_str += self.__addr_id_links_r['uuid'] + self.__delimiter_id + uuid + self.__delimiter_parts
        address_str += self.__addr_id_links_r['addr'] + self.__delimiter_id + addr + self.__delimiter_parts
        address_str += self.__addr_id_links_r['hostname'] + self.__delimiter_id + hostname  + self.__delimiter_parts
        address_str += self.__addr_id_links_r['publisher'] + self.__delimiter_id + publisher + self.__delimiter_parts
        address_str += self.__addr_id_links_r['devicename'] + self.__delimiter_id + devicename  + self.__delimiter_parts
        address_str += self.__addr_id_links_r['datakey'] + self.__delimiter_id + datakey + self.__delimiter_parts

        return address_str

    def get_data(self, datapacket):
        """Returns the part of the data in the datapacket that fits
        with the address

        """
        if datapacket in self:
            if self.datakeyexpand == True: # Return the time
                return datapacket['_redvypr']['t']
            elif self.datakey.startswith(self.__regex_symbol_start) and self.datakey.endswith(self.__regex_symbol_end) and len(self.datakey) > 1:
                # Regular expression
                for k in datapacket.keys():
                    if self.compare_address_substrings(k,self.datakey):
                        return datapacket[k]
            else: # Just a datakey
                return datapacket[self.datakey]
        else:
            return None


    def parse_addrstr(self, addrstr):
        """ Parses a redvypr address string

        """


        # Create blank parsed_addrstr
        parsed_addrstr = {}

        ## Fill parsed_addrstr with data
        #addr_parts = addrstr.split(self.__delimiter_parts)
        # Use regex to account for quoted strings
        #https://stackoverflow.com/questions/2785755/how-to-split-but-ignore-separators-in-quoted-strings-in-python
        regex_str = '''{}(?=(?:[^'"]|'[^']*'|"[^"]*")*$)'''.format(self.__delimiter_parts)
        #print('Regex str',regex_str)
        addrsplit_re = re.compile(regex_str)
        addr_parts = addrsplit_re.split(addrstr)
        #print('fsdf',addr_parts)
        for addr_part in addr_parts:
            #print('Part',addr_part)
            if len(addr_part) > 0:
                addr_part_sp = addr_part.split(self.__delimiter_id)
                if len(addr_part_sp) >= 2:
                    addr_part_id = addr_part_sp[0]
                    addr_part_content = addr_part_sp[1]
                    #print('part',addr_part_id,addr_part_content)
                    # Try to add to parsed addrstr
                    try:
                        addr_part_id_decoded = self.__addr_id_links[addr_part_id]
                        parsed_addrstr[addr_part_id_decoded] = addr_part_content
                    except:
                        pass
                else:
                    raise ValueError('Format needs to be <ID>{}<content>, not: {}'.format(self.__delimiter_id,str(addr_part_sp)))

        # Check for expansion and fill not explictly defined ids with *
        for addr_id,addr_idexpand in zip(self.__addr_ids,self.__addr_idsexpand):
            try:
                addr_content = parsed_addrstr[addr_id]
            except:
                addr_content = parsed_addrstr[addr_id] = '*'

            if addr_content == '*':
                parsed_addrstr[addr_idexpand] = True
            else:
                parsed_addrstr[addr_idexpand] = False


        return parsed_addrstr


    def get_str(self, address_format = '/u/a/h/d/p/k/'):
        """

        Args:
            addr_ids:

        Returns:

        """
        funcname = __name__ + '.get_str():'
        address_str = self.__delimiter_parts
        addr_ids = address_format.split(self.__delimiter_parts)
        for a_id in addr_ids:
            if len(a_id)>0:
                addr_id = self.__addr_id_links[a_id]
                addr_id_data = self.parsed_addrstr[addr_id]
                address_str += a_id + self.__delimiter_id + addr_id_data + self.__delimiter_parts

        return address_str

    def compare_address_substrings(self, str1, str2):
        if str1 == '*' or str2 == '*':
            return True
        elif str1.startswith(self.__regex_symbol_start) and str1.endswith(self.__regex_symbol_end) and len(str1) > 1:
            if str2.startswith(self.__regex_symbol_start) and str2.endswith(self.__regex_symbol_end):
                return str1 == str2
            else:
                flag_re = re.fullmatch(str1[1:-1], str2) is not None
                return flag_re
        elif str2.startswith(self.__regex_symbol_start) and str2.endswith(self.__regex_symbol_end) and len(str2) > 1:
            flag_re = re.fullmatch(str2[1:-1], str1) is not None
            return flag_re
        else:
            flag_cmp = str1 == str2
            return flag_cmp

    def __repr__(self):
        #astr2 = self.get_str('<key>/<device>:<host>@<addr>')
        astr2 = self.address_str
        astr = "RedvyprAddress('" + astr2 + "')"
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
        if type(addr) == RedvyprAddress:
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
            deviceflag = self.compare_address_substrings(self.devicename,datapacket['_redvypr']['device'])
            hostflag   = self.compare_address_substrings(self.hostname, datapacket['_redvypr']['host']['hostname'])
            addrflag   = self.compare_address_substrings(self.addr, datapacket['_redvypr']['host']['addr'])
            uuidflag   = self.compare_address_substrings(self.uuid, datapacket['_redvypr']['host']['uuid'])
            try:
                pubstr = datapacket['_redvypr']['locpub']
            except:
                pubstr = ''

            pubflag = self.compare_address_substrings(self.publisher, pubstr)
            #locpubflag = self.compare_address_substrings(self.uuid, datapacket['_redvypr']['host']['locpub'])
            #print('deviceflag', deviceflag)
            #print('hostflag', deviceflag)
            #print('addrflag', addrflag)
            #print('uuidflag', uuidflag)
            #print('uuidexpand', self.uuid,self.uuidexpand)
            # Loop over all datakeys in the packet
            if(len(self.datakey) > 0):
                if self.datakey == '*': # always valid
                    pass
                elif len(self.datakey)>1 and self.datakey.startswith(self.__regex_symbol_start) and self.datakey.endswith(self.__regex_symbol_end): # Regular expression
                    for k in datapacket.keys(): # Test every key
                        if self.compare_address_substrings(self.datakey,k):
                            break
                elif (self.datakey in datapacket.keys()):
                    pass
                else:  # If the key does not fit, return False immediately
                    return False

            #if (deviceflag and uuidflag):
            #    return True
            #elif (deviceflag and hostflag and addrflag and uuidflag):
            #    return True
            #elif (deviceflag and uuidflag):
            #    return True

            matchflag3 = deviceflag and hostflag and addrflag and uuidflag and pubflag

            return matchflag3

        elif(type(data) == RedvyprAddress):
            addr = data
            datakeyflag = self.compare_address_substrings(self.datakey, addr.datakey)
            deviceflag  = self.compare_address_substrings(self.devicename, addr.devicename)
            hostflag    = self.compare_address_substrings(self.hostname, addr.hostname)
            addrflag    = self.compare_address_substrings(self.addr, addr.addr)
            uuidflag    = self.compare_address_substrings(self.uuid, addr.uuid)
            pubflag = self.compare_address_substrings(self.publisher, addr.publisher)
            #locpubflag = self.compare_address_substrings(self.local_publisher, addr.local_publisher)

            # print('Datakeyflag',datakeyflag)
            # print('Deviceflag',deviceflag)
            # print('Hostflag',hostflag)
            # print('addr',addrflag)
            # print('uuidflag',uuidflag)
            # print('localflag',localflag)

            # matchflag1  = datakeyflag and deviceflag and hostflag and addrflag
            # matchflag2 = datakeyflag  and deviceflag and uuidflag
            matchflag3 = datakeyflag and deviceflag and hostflag and addrflag and uuidflag and pubflag

            return matchflag3  # 1 or matchflag2

        elif type(data) == str:
            raddr = RedvyprAddress(str(data))
            contains = raddr in self
            return contains
        else:
            raise ValueError('Unknown data type')


    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: typing.Any,
        _handler: pydantic.GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        """
        Modified from here:
        https://docs.pydantic.dev/latest/concepts/types/#handling-third-party-types
        We return a pydantic_core.CoreSchema that behaves in the following ways:

        * strs will be parsed as `RedvyprAddress` instances
        * `RedvyprAddress` instances will be parsed as `RedvyprAddress` instances without any changes
        * Nothing else will pass validation
        * Serialization will always return just an str
        """

        def validate_from_str(value: str) -> RedvyprAddress:
            result = RedvyprAddress(value)
            return result

        from_str_schema = core_schema.chain_schema(
            [
                core_schema.str_schema(),
                core_schema.no_info_plain_validator_function(validate_from_str),
            ]
        )

        return core_schema.json_or_python_schema(
            json_schema=from_str_schema,
            python_schema=core_schema.union_schema(
                [
                    # check if it's an instance first before doing any further work
                    core_schema.is_instance_schema(RedvyprAddress),
                    from_str_schema,
                ]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda instance: instance.address_str
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: core_schema.CoreSchema, handler: pydantic.GetJsonSchemaHandler
    ) -> pydantic.json_schema.JsonSchemaValue:
        # Use the same schema that would be used for `str`
        return handler(core_schema.str_schema())






