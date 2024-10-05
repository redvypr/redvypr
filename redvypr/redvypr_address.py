"""
Redvypr addresses are the base to identify and address redvypr data packets.
"""

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

restr = r'''\[['"].+['"]\].*''' # Regex that searches for square brackets as start, followed by quotation strs, arbitraty string and again quotation and bracket
rtest = re.compile(restr)

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
    def __init__(self, addrstr=None, local_hostinfo=None, datakey=None, devicename=None, hostname=None, addr=None, uuid=None, publisher=None, compare=None, packetid=None):
        # Some definitions
        self.__regex_symbol_start = '{'
        self.__regex_symbol_end = '}'
        self.__add_entries_short = {'k': 'datakey', 'd': 'devicename', 'i': 'packetid', 'a': 'addr', 'u': 'uuid', 'h': 'hostname', 'p': 'publisher', 'c': 'compare'}
        self.__addr_entries_short_r = {'datakey': 'k', 'devicename': 'd' , 'packetid': 'i', 'addr': 'a', 'uuid': 'u' , 'hostname': 'h', 'publisher': 'p', 'compare': 'c'}
        self.__addr_entries = ['datakey', 'devicename', 'packetid', 'addr', 'uuid', 'hostname', 'publisher', 'compare']
        self.__addr_entries_expand = ['datakeyexpand', 'deviceexpand', 'packetidexpand', 'addrexpand', 'uuidexpand', 'hostexpand', 'publisherexpand', 'compareexpand']
        self.__delimiter_parts = '/'
        self.__delimiter_id = ':'

        # Try to convert redvypr_address to dict
        self._common_address_formats = ['/i/k', '/d/i/k','/k/','/d/','/i/','/p/','/p/d/','/p/d/i','/u/a/h/d/','/u/a/h/d/i', '/u/a/h/d/k/', '/u/a/h/d/k/i', '/a/h/d/', '/a/h/d/i', '/a/h/p/']
        if addrstr is not None: # Address from addrstr
            #print('addrstr',type(addrstr),type(self))
            if type(addrstr) == type(self): # If addrstr is redvypr_address, convert it to str
                self.address_str = addrstr.address_str
            #elif type(addrstr) == dict:  # Address from datapacket # This does not work with inherited classes like redvypr_address
            elif isinstance(addrstr, dict):  # Addressstr is a redvypr datapacket # This should work with dict and inherited classes like redvypr_address
                try:
                    publisher_packet = addrstr['_redvypr']['publisher']
                except:
                    publisher_packet = None

                try:
                    packetid = addrstr['_redvypr']['packetid']
                except:
                    packetid = None
                try:
                    devicename_packet = addrstr['_redvypr']['device']
                except:
                    devicename_packet = None

                if True:
                    try:
                        addr_packet = addrstr['_redvypr']['host']['addr']
                    except:
                        addr_packet = None

                try:
                    hostname_packet = addrstr['_redvypr']['host']['hostname']
                except:
                    hostname_packet = None
                try:
                    uuid_packet = addrstr['_redvypr']['host']['uuid']
                except:
                    uuid_packet = None

                self.address_str = self.create_addrstr(datakey=datakey,
                                                       packetid=packetid,
                                                       devicename=devicename_packet,
                                                       hostname=hostname_packet,
                                                       addr=addr_packet,
                                                       uuid=uuid_packet,
                                                       publisher=publisher_packet,
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
            #if any([addrstr, local_hostinfo, datakey, devicename, hostname, addr, uuid, publisher]):
            if any([packetid, publisher, local_hostinfo, datakey, devicename, hostname, addr, uuid, publisher]):
                #print('Replacing string with new stuff')
                (parsed_addrstr, parsed_addrstr_expand) = self.parse_addrstr(self.address_str)
                if packetid is not None:
                    parsed_addrstr['packetid'] = packetid
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
                # new
                if compare is not None:
                    parsed_addrstr['compare'] = compare
                # new
                if local_hostinfo is not None:
                    parsed_addrstr['local_hostinfo'] = local_hostinfo

                #self.address_str = self.create_addrstr(parsed_addrstr['datakey'], parsed_addrstr['devicename'], parsed_addrstr['hostname'], parsed_addrstr['addr'], parsed_addrstr['uuid'], parsed_addrstr['publisher'], local_hostinfo=local_hostinfo)
                self.address_str = self.create_addrstr(**parsed_addrstr)

        else:  # addrstr from single ingredients
            self.address_str = self.create_addrstr(datakey=datakey,
                                                   packetid=packetid,
                                                   devicename=devicename,
                                                   hostname=hostname,
                                                   addr=addr,
                                                   uuid=uuid,
                                                   publisher=publisher,
                                                   local_hostinfo=local_hostinfo,
                                                   compare=compare)
            # print('Address string',self.address_str)

        (parsed_addrstr,parsed_addrstr_expand) = self.parse_addrstr(self.address_str)
        self.parsed_addrstr = parsed_addrstr
        self.parsed_addrstr_expand = parsed_addrstr_expand

        # Add the attributes to the object
        for addr_id in self.__addr_entries:
            addr_entry = parsed_addrstr[addr_id]
            if addr_entry is None:
                addr_entry = '*'
            setattr(self,addr_id,addr_entry)
            expand_attribute = addr_id + 'expand'
            setattr(self, expand_attribute, parsed_addrstr_expand[addr_id])

        self.datakeyeval = parsed_addrstr_expand['datakeyeval']
        # Check if address has a regular expression
        self.datakeyregex = False
        if self.datakey.startswith(self.__regex_symbol_start) and self.datakey.endswith(self.__regex_symbol_end) and len(
            self.datakey) > 1:
            self.datakeyregex = True

    def get_datakeyentries(self):
        if self.parsed_addrstr_expand['datakeyentries'] is None:
            return [self.datakey]
        else:
            return self.parsed_addrstr_expand['datakeyentries']

    def get_common_address_formats(self):
        return self._common_address_formats
    def create_addrstr(self, datakey=None, packetid=None, devicename=None, hostname=None, addr=None, uuid=None, publisher=None, local_hostinfo=None, compare=None):
        """
            Creates an address string from given ingredients
            Args:
                datakey:
                packetid:
                devicename:
                hostname:
                addr:
                uuid:
                local_hostinfo:
                compare:

            Returns:

            """

        if local_hostinfo is not None:
            uuid = local_hostinfo['uuid']
            addr = local_hostinfo['addr']
            hostname = local_hostinfo['hostname']

        address_str = ''
        if compare is not None:
            address_str += self.__addr_entries_short_r['compare'] + self.__delimiter_id + compare + self.__delimiter_parts
        if uuid is not None:
            address_str += self.__addr_entries_short_r['uuid'] + self.__delimiter_id + uuid + self.__delimiter_parts
        if addr is not None:
            address_str += self.__addr_entries_short_r['addr'] + self.__delimiter_id + addr + self.__delimiter_parts
        if hostname is not None:
            address_str += self.__addr_entries_short_r['hostname'] + self.__delimiter_id + hostname + self.__delimiter_parts
        if publisher is not None:
            address_str += self.__addr_entries_short_r['publisher'] + self.__delimiter_id + publisher + self.__delimiter_parts
        if devicename is not None:
            address_str += self.__addr_entries_short_r['devicename'] + self.__delimiter_id + devicename + self.__delimiter_parts
        if packetid is not None:
            address_str += self.__addr_entries_short_r['packetid'] + self.__delimiter_id + packetid + self.__delimiter_parts
        if datakey is not None:
            address_str += self.__addr_entries_short_r['datakey'] + self.__delimiter_id + datakey + self.__delimiter_parts

        if len(address_str)>0:
            address_str = self.__delimiter_parts + address_str
        else:
            address_str += self.__addr_entries_short_r['datakey'] + self.__delimiter_id + '*' + self.__delimiter_parts

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
        parsed_addrstr_expand = {}
        # Use regex to account for quoted strings
        #https://stackoverflow.com/questions/2785755/how-to-split-but-ignore-separators-in-quoted-strings-in-python
        regex_str = '''{}(?=(?:[^'"]|'[^']*'|"[^"]*")*$)'''.format(self.__delimiter_parts)
        #print('Regex str',regex_str)
        addrsplit_re = re.compile(regex_str)
        addr_parts = addrsplit_re.split(addrstr)
        #print('addr_parts',addr_parts,len(addr_parts))
        for addr_part in addr_parts:
            #print('Part',addr_part)
            if len(addr_part) > 0:
                addr_part_sp = addr_part.split(self.__delimiter_id)
                #print('addr_part_sp',addr_part_sp)
                # Check if there is a single string, if so interprete as datakey entry
                if len(addr_part_sp) == 1 and len(addr_parts) == 1:
                    #print('Single entry, interpreting as datakey')
                    parsed_addrstr['datakey'] = addr_parts[0]
                elif len(addr_part_sp) >= 2:
                    addr_part_id = addr_part_sp[0]
                    addr_part_content = addr_part_sp[1]
                    #print('part',addr_part_id,addr_part_content)
                    # Try to add to parsed addrstr
                    try:
                        addr_part_id_decoded = self.__add_entries_short[addr_part_id]
                        parsed_addrstr[addr_part_id_decoded] = addr_part_content
                    except:
                        pass
                else:
                    raise ValueError('Format needs to be <ID>{}<content>, not: {}'.format(self.__delimiter_id,str(addr_part_sp)))

        #print(parsed_addrstr)
        # Check for expansion and fill not explicitly defined ids with *
        #for addr_id,addr_idexpand in zip(self.__addr_ids,self.__addr_idsexpand):
        for addr_id in self.__addr_entries:
            try:
                addr_content = parsed_addrstr[addr_id]
            except:
                addr_content = '*'
                parsed_addrstr[addr_id] = None

            # Check if an expansion (*) should be done
            if addr_content == '*':
                parsed_addrstr_expand[addr_id] = True
            else:
                parsed_addrstr_expand[addr_id] = False

        parsed_addrstr_expand['datakeyeval'] = False
        parsed_addrstr_expand['datakeyentries'] = None
        parsed_addrstr_expand['datakeyentries_str'] = None
        if parsed_addrstr['datakey'] is not None:
            if parsed_addrstr['datakey'].startswith('[') and parsed_addrstr['datakey'].endswith(']'):
                parsed_addrstr_expand['datakeyeval'] = True
                # Parse the entries
                #https://stackoverflow.com/questions/2403122/regular-expression-to-extract-text-between-square-brackets
                # and
                # https://stackoverflow.com/questions/7317043/regex-not-operator#7317087
                # TODO: regex string is not optimally working with quoted strings and square brackets ...
                regex_str = r'(?<=\[).+?(?=\])'
                #print('Parsed address string',parsed_addrstr['datakey'])
                datakeyentries_str = re.findall(regex_str, parsed_addrstr['datakey'])
                datakeyentries = [eval(x,None) for x in datakeyentries_str]
                parsed_addrstr_expand['datakeyentries_str'] = datakeyentries_str # The str values can be used to reconstruct the original str
                parsed_addrstr_expand['datakeyentries'] = datakeyentries

        #print(parsed_addrstr)
        return parsed_addrstr,parsed_addrstr_expand

    def get_fullstr(self):
        address_format = '/u/a/h/d/p/i/k/'
        return self.get_str(address_format)


    def get_expand_explicit_str(self, address_format = '/u/a/h/d/p/i/k/'):
        r"""
        Returns a string that searches explicitly for the expandsymbol.
        This is useful to match with addresses with the expandsymbel defined but
        not with addresses that have a real value in the address entry::

            r1 = RedvyprAddress('/d:test/k:*')
            r2 = RedvyprAddress('/d:test/k:somekey')
            r1.get_expand_explicit_str('/d/k') # yields '/d:test/k:{\\*}/'
            r1_exp = RedvyprAddress(r1.get_expand_explicit_str('/d/k'))
            print("r1: {}".format(r1)) # r1: RedvyprAddress('''/d:test/k:*''')
            print("r1_exp: {}".format(r1_exp)) # r1_exp: RedvyprAddress('''/d:test/k:{\*}/''')
            print("r2: {}".format(r2)) # r2: RedvyprAddress('''/d:test/k:somekey''')
            print("r2 in r1: {}".format(r2 in r1)) # r2 in r1: True
            print("r2 in r1_exp: {}".format(r2 in r1_exp)) # r2 in r1_exp: False

        :return:
        """
        address_str = self.__delimiter_parts
        addr_ids = address_format.split(self.__delimiter_parts)
        for a_id in addr_ids:
            if len(a_id) > 0:
                addr_id = self.__add_entries_short[a_id]
                addr_id_data = self.parsed_addrstr[addr_id]
                if (addr_id_data is None) or (addr_id_data == '*'):
                    addr_id_data = r'{\*}'
                address_str += a_id + self.__delimiter_id + addr_id_data + self.__delimiter_parts

        return address_str


    def get_str(self, address_format = '/u/a/h/d/p/i/k/'):
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
                addr_id = self.__add_entries_short[a_id]
                addr_id_data = self.parsed_addrstr[addr_id]
                if addr_id_data is not None:
                    address_str += a_id + self.__delimiter_id + addr_id_data + self.__delimiter_parts

        return address_str

    def compare_address_substrings(self, str1, str2):
        #if str1 == '' and str2 == '':
        #    return True
        #elif str1 == '' or str2 == '':
        #    return False
        if str1 is None:
            str1 = ''
        if str2 is None:
            str2 = ''
        ## Check if a direct comparison is wished
        flag_compare = False
        if str1.startswith('=='):
            str1 = str1[2:]
            flag_compare = True
        if str2.startswith('=='):
            str2 = str2[2:]
            flag_compare = True

        if (str1 == '*' or str2 == '*') and flag_compare == False:
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
        astr = "RedvyprAddress('''" + astr2 + "''')"
        return astr

    def __hash__(self):
        astr2 = self.address_str
        astr = "RedvyprAddress('''" + astr2 + "''')"
        return hash(astr)

    def __len__(self):
        return len(self.address_str)

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
        - it converts a string into a RedvyprAddress and checks if the addresses match
        """
        if isinstance(data, dict): # check if data is a dictionary or an inherited type like redvypr.data_packets.datapacket
            datapacket = data
            deviceflag = self.compare_address_substrings(self.devicename,datapacket['_redvypr']['device'])
            packetidflag = self.compare_address_substrings(self.packetid, datapacket['_redvypr']['packetid'])
            hostflag = self.compare_address_substrings(self.hostname, datapacket['_redvypr']['host']['hostname'])
            addrflag = self.compare_address_substrings(self.addr, datapacket['_redvypr']['host']['addr'])
            uuidflag = self.compare_address_substrings(self.uuid, datapacket['_redvypr']['host']['uuid'])
            pubflag = self.compare_address_substrings(self.publisher, datapacket['_redvypr']['publisher'])
            # Test the comparison
            compareflag = True
            if self.compare is not None:
                if self.compare != '*':
                    evalstr = 'data' + self.compare
                    #print('Evalstr',evalstr)
                    try:
                        compareflag = eval(evalstr)
                        #print('Compareflag',compareflag)
                    except:
                        logger.info('Eval did not work out',exc_info=True)
                        compareflag = False
            #self.compare
            #locpubflag = self.compare_address_substrings(self.uuid, datapacket['_redvypr']['host']['locpub'])
            # Loop over all datakeys in the packet
            if(len(self.datakey) > 0):
                if self.datakey == '*': # always valid
                    pass
                elif len(self.datakey)>1 and self.datakey.startswith(self.__regex_symbol_start) and self.datakey.endswith(self.__regex_symbol_end): # Regular expression
                    for k in datapacket.keys(): # Test every key
                        if self.compare_address_substrings(self.datakey,k):
                            break
                elif (self.datakey in datapacket.keys()): # Datakey (standard) in list of datakeys
                    pass
                elif rtest.match(self.datakey): # check if key is of the form ['TAR'][0] with a regular expression
                    try:
                        evalstr = 'datapacket' + self.datakey
                        data = eval(evalstr, None)
                        #print('data',data)
                    except:
                        #logger.debug('Eval comparison {}'.format(evalstr),exc_info=True)
                        return False

                else:  # If the key does not fit, return False
                    return False

            #if (deviceflag and uuidflag):
            #    return True
            #elif (deviceflag and hostflag and addrflag and uuidflag):
            #    return True
            #elif (deviceflag and uuidflag):
            #    return True

            matchflag3 = deviceflag and hostflag and addrflag and uuidflag and pubflag and compareflag and packetidflag

            return matchflag3

        elif(type(data) == RedvyprAddress):
            addr = data
            # If there is et least one eval address, compare the datakeyentries one by one
            # This is resulting in two list, that are compared element by element
            if self.datakeyeval or addr.datakeyeval:
                datakeyflag = self.get_datakeyentries() == addr.get_datakeyentries()
            else:
                datakeyflag = self.compare_address_substrings(self.datakey, addr.datakey)

            packetidflag = self.compare_address_substrings(self.packetid, addr.packetid)
            deviceflag = self.compare_address_substrings(self.devicename, addr.devicename)
            hostflag = self.compare_address_substrings(self.hostname, addr.hostname)
            addrflag = self.compare_address_substrings(self.addr, addr.addr)
            uuidflag = self.compare_address_substrings(self.uuid, addr.uuid)
            pubflag = self.compare_address_substrings(self.publisher, addr.publisher)
            matchflag3 = datakeyflag and packetidflag and deviceflag and hostflag and addrflag and uuidflag and pubflag

            return matchflag3  # 1 or matchflag2

        # string, convert to RedvyprAddress first
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
        * Serialization will always return just a str
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









