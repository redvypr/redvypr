"""

redvypr configuration module

The module provides modified objects that allow to store extra attributes.
- dict
- list
- str, todo
- int, todo
- float, todo
- bool, todo
- None, todo



"""

import sys
import logging
import copy
import collections
import numbers
import math
from redvypr.utils import seq_iter

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.config')
logger.setLevel(logging.DEBUG)


template_types = []
template_types.append({'type': 'dict'})
template_types.append({'type': 'list'})
template_types.append({'type': 'str'})
template_types.append({'type': 'int'})
template_types.append({'type': 'float'})
template_types.append({'type': 'bool'})
template_types.append({'type': 'datastream'})
template_types.append({'type': 'color'})
#template_types.append({'type': 'ip'})



class configDict(collections.UserDict):
    """
    The class is a modified dictionary that allows to add attributes. If a deepcopy of the class is done, a standard
    dictionary will be returned.
    """
    def __reduce_ex__(self,protocol):

        return self.data.__reduce_ex__(protocol)

    def __reduce__(self):
        return self.data.__reduce__()


class configList(collections.UserList):
    """
    The class is a modified list that allows to add attributes. If a deepcopy of the class is done, a standard
    list will be returned.
    """

    #def __setitem__(self, key,value):
    #    self.data.__setitem__(key,value)
    def __reduce_ex__(self, protocol):

        return self.data.__reduce_ex__(protocol)

    def __reduce__(self):
        return self.data.__reduce__()


class configString(collections.UserString):
    """
    The class is a modified dictionary that allows to add attributes. If a deepcopy of the class is done, a standard
    dictionary will be returned.
    """
    def __reduce_ex__(self,protocol):

        return self.data.__reduce_ex__(protocol)

    def __reduce__(self):
        return self.data.__reduce__()



class configNumber(numbers.Integral):
    """Emulate numeric types based on "n" attribute, based on
    https://docs.python.org/3/reference/datamodel.html#basic-customization
    https://docs.python.org/3/reference/datamodel.html#emulating-numeric-types
    This is effectively a mutable container for a number, and can be
    subclassed to provide interesting properties that are related to
    the number.
    To use this class, subclass (if you like) or construct it
    directly, passing the numerical object you wish to make mutable to
    the initializer.
    The current immutable number is the 'n' attribute, and all the
    numeric type dunder methods just delegate to this current number.

    Note this is a fork of
    https://github.com/markrages/python_mutable_number that includes deepcopy functionality
    """

    # Basic customization
    def __init__(self, n=None): self.data=n
    def __repr__(self): return repr(self.data)
    def __str__(self): return str(self.data)
    # def __bytes__(self): unimplemented
    def __format__(self, format_spec): self.data.__format__(format_spec)

    def __lt__(self, other): return self.data < other
    def __le__(self, other): return self.data <= other
    def __ne__(self, other): return self.data != other
    def __eq__(self, other): return self.data == other
    def __gt__(self, other): return self.data > other
    def __ge__(self, other): return self.data >= other

    def __hash__(self): return hash(self.data)
    def __bool__(self): return bool(self.data)

    # math functions
    def __ceil__(self): return math.ceil(self.data)
    def __floor__(self): return math.floor(self.data)
    def __trunc__(self): return math.trunc(self.data)

    # Binary arithmetic operations
    def __add__(self, other): return self.data + other
    def __sub__(self, other): return self.data - other
    def __mul__(self, other): return self.data * other
    def __truediv__(self, other): return self.data / other
    def __floordiv__(self, other): return self.data // other
    def __mod__(self, other): return self.data % other
    def __divmod__(self, other): return divmod(self.data, other)
    def __pow__(self, other, modulo=None): return pow(self.data, other, modulo)
    def __lshift__(self, other): return self.data << other
    def __rshift__(self, other): return self.data >> other
    def __and__(self, other): return self.data & other
    def __xor__(self, other): return self.data ^ other
    def __or__(self, other): return self.data | other

    # Right binary operations
    def __radd__(self, other): return other + self.data
    def __rsub__(self, other): return other - self.data
    def __rmul__(self, other): return other * self.data
    def __rtruediv__(self, other): return other / self.data
    def __rfloordiv__(self, other): return other // self.data
    def __rmod__(self, other): return other % self.data
    def __rdivmod__(self, other): return divmod(other, self.data)
    def __rpow__(self, other): return pow(other, self.data)
    def __rlshift__(self, other): return other << self.data
    def __rrshift__(self, other): return other >> self.data
    def __rand__(self, other): return other & self.data
    def __rxor__(self, other): return other ^ self.data
    def __ror__(self, other): return other | self.data

    # In-place binary operations
    def __iadd__(self, other):
        self.data += other
        return self
    def __isub__(self, other):
        self.data -= other
        return self
    def __imul__(self, other):
        self.data *= other
        return self
    def __itruediv__(self, other):
        self.data /= other
        return self
    def __ifloordiv__(self, other):
        self.data //= other
        return self
    def __imod__(self, other):
        self.data %= other
        return self
    def __ipow__(self, other, modulo=None):
        self.data = pow(self.data, other, modulo)
        return self
    def __ilshift__(self, other):
        self.data <<= other
        return self
    def __irshift__(self, other):
        self.data >>= other
        return self
    def __iand__(self, other):
        self.data &= other
        return self
    def __ixor__(self, other):
        self.data ^= other
        return self
    def __ior__(self, other):
        self.data |= other
        return self

    # Unary arithmetic operations
    def __neg__(self): return -self.data
    def __pos__(self): return +self.data
    def __abs__(self): return abs(self.data)
    def __invert__(self): return ~self.data

    # Conversion functions
    def __complex__(self): return complex(self.data)
    def __int__(self): return int(self.data)
    def __float__(self): return float(self.data)
    def __round__(self, n=0): return round(self.data, n)

    def __index__(self): return self.data.__index__()

    # integer functions
    # https://docs.python.org/3/library/stdtypes.html#additional-methods-on-integer-types
    def bit_length(self): return self.data.bit_length()
    def to_bytes(self, length, byteorder, *args, signed=False):
        return self.data.to_bytes(length, byteorder, *args, signed=signed)
    def from_bytes(self, bytes, byteorder, *args, signed=False):
        return self.data.from_bytes(bytes, byteorder, *args, signed=signed)
    def conjugate(self): return self.data.conjugate()

    @property
    def denominator(self): return self.data.denominator
    @property
    def numerator(self): return self.data.numerator

    @property
    def imag(self): return self.data.imag
    @property
    def real(self): return self.data.real

    # float functions
    # https://docs.python.org/3/library/stdtypes.html#additional-methods-on-float
    def as_integer_ratio(self): return self.data.as_integer_ratio()
    def is_integer(self): return self.data.is_integer()
    def hex(self): return self.data.hex()

    @property
    def value(self): return self.data

    @value.setter
    def value(self, n): self.data = n

    def __reduce_ex__(self,protocol):
        return self.data.__reduce_ex__(protocol)

    def __reduce__(self):
        return self.data.__reduce__()


def data_to_configdata(data):
    """
    Converts a known class to a configClass, that can additionally store attributes
    Args:
        data:

    Returns:
        configClass: an class that behaves similar to the original data but can store attributes

    """
    funcname = __name__ + '.to_configdata():'
    typestr = str(type(data))
    if(type(data) == list):
        configData = configList(data)
        return configData
    elif (type(data) == dict):
        configData = configDict(data)
        return configData
    elif (type(data) == str):
        configData = configString(data)
        return configData
    elif (type(data) == int):
        configData = configNumber(data)
        return configData
    elif (type(data) == float):
        configData = configNumber(data)
        return configData
    elif (type(data) == bool):
        configData = configNumber(data)
        return configData
    elif (data == None):
        configData = configNumber(data)
        return configData
    # if they are already configClasses, return the same object
    elif (type(data) == configList):
        return data
    elif (type(data) == configDict):
        return data
    elif (type(data) == configString):
        return data
    elif (type(data) == configNumber):
        return data
    else:
        raise TypeError(funcname + 'Unknown data type {:s}'.format(typestr))


def deepcopy_config(data,standard_datatypes=True):
    """

    Args:
        data: the data to be copied
        standard_datatypes: True if the copied result has standard datatypes instead of configXYZ datatypes

    Returns:

    """
    data_copy = copy.deepcopy(data)
    if standard_datatypes == False:
        dict_to_configDict(data_copy)

    return data_copy

def valid_template(template):
    """
    Checks if the template is valid
    Args:
        template: dictionary

    Returns:
        boold: True if valid, False otherwise

    """
    funcname = __name__ + 'valid_template():'
    if(type(template) == dict):
        if('template_name' in template.keys()):
            return True
        else:
            logger.debug(funcname + 'key "template_name" missing')
    else:
        logger.debug(funcname + 'template not a dictionary')

    return False

def configdata_to_data(data):
    """
    Converts a configData class back into a standard Python class
    Args:
        data: configData, i.e. configList, configDict

    Returns:
        standard Python data

    """
    funcname = __name__ + '.configdata_to_data():'
    try: # Data is stored in data
        standard_data = data.data
        return standard_data
    except:
        pass

    try:  # Data is stored in n in the configNumber
        standard_data = data.n
        return standard_data
    except:
        pass

    raise TypeError(funcname + 'Could not return data for datatype {:s}'.format(str(type(data))))



def dict_to_configDict(data,process_template=False):
    """
    creates a config dictionary out of a configuration template, the values of the dictionary are
    configList/configNumber objects that can be accessed like classical values but have the capability to store
    attributes as well.

    """
    funcname = __name__ + 'dict_to_configDict():'
    def loop_over_index(c):
        #print('c',c,seq_iter(c))
        for index in seq_iter(c):
            #print('c1', c[index])
            default_value = data_to_configdata(c[index]) # Brute conversion of everything
            c[index] = default_value
            if process_template:
                c[index].template = copy.deepcopy(c[index])
            #print('c2', c[index])
            # Check first if we have a configuration dictionary with at least the type
            FLAG_CONFIG_DICT = False
            if (type(c[index]) == configDict) and process_template:
                print('Hallo')
                default_value = ''
                if ('default' in c[index].keys()):
                    default_value = c[index]['default']
                    default_type = default_value.__class__.__name__ # Defaults overrides type
                    FLAG_CONFIG_DICT = True
                if('type' in c[index].keys()):
                    default_type = c[index]['type']
                    FLAG_CONFIG_DICT = True
                    if(c[index]['type'] == 'list'): # Modifiable list
                        print('List')
                        if ('default' in c[index].keys()): # The default values are templates and need to be converted to dicts
                            default_value_tmp = c[index]['default']
                            default_value = configList()
                            if (type(default_value_tmp) == list) or (type(default_value_tmp) == configList):
                                print('Configlist',type(default_value_tmp))
                                for d in default_value_tmp:
                                    print('d',d)
                                    if(valid_template(d)):
                                        print('Valid',d)
                                        default_value.append(dict_to_configDict(d,process_template=process_template))
                                        default_value.template = copy.deepcopy(c[index])
                                    else:
                                        raise TypeError("The list entry should be a valid redvypr template")


                            else:
                                raise TypeError("The default value should be a list containing templates")
                        else:
                            default_value = configList()

                print('Default value',default_value,FLAG_CONFIG_DICT)
                if FLAG_CONFIG_DICT:
                    c[index] = data_to_configdata(default_value)

            # Iterate over a dictionary or list
            if ((seq_iter(c[index]) is not None) and (FLAG_CONFIG_DICT == False)):
                #print('Loop')
                loop_over_index(c[index])


    data_tmp = copy.deepcopy(data) # Copy the data first
    if(type(data_tmp) == dict):
        data_dict = configDict(data_tmp) #
    elif (type(data_tmp) == configDict):
        data_dict = data_tmp
    else:
        raise TypeError(funcname + 'data must be a dictionary and not {:s}'.format(str(type(data))))
    loop_over_index(data_dict)
    #print('Config:',config)
    return data_dict




def apply_config_to_configDict(userconfig,configdict):
    """
    Applies a user configuration to a dictionary created from a template
    Args:
        userconfig:
        configdict:

    Returns:
        configdict_applied: A with the userconfig modified configuration dictionary
    """
    funcname = __name__ + '.apply_config_to_configDict():'
    def loop_over_index(c,cuser):
        for index in seq_iter(cuser): # Loop over the user config
            #print('Hallo',index,getdata(c[index]))
            #print('c', c, index)
            indices = seq_iter(c)
            #print('c', c, index,indices)
            #print(index in indices)
            # Try to get the same index in the template
            try:
                ctemp = c[index]
            except:
                try:
                    ctemp = c.value[index]
                except: # Could not get data, forget the index and continue with next one
                    continue


            if (seq_iter(ctemp) is not None):
                #print('Hallo',cuser,index)
                try: # Check if the user data is existing as well
                    cuser[index]
                    if (seq_iter(cuser[index]) is not None):
                        loop_over_index(ctemp, cuser[index])
                except Exception as e:
                    logger.debug(funcname + ': cuser[index]: ' + str(e))
                    continue


            # Check if this is a configdata list, that can be modified
            elif(type(getdata(ctemp)) == list):
                try:
                    t = ctemp.template['type']
                except Exception as e:
                    t = ''

                if(t == 'list'): # modifiable list, fill the template list with the types
                    # First make the list equally long, the user list is either 0 or longer
                    numitems = len(getdata(cuser[index]))
                    dn = numitems - len(ctemp.value)
                    for i in range(dn):
                        ctemp.value.append(configdata(None))

                    # Fill the list with the right templates
                    for i in range(numitems):
                        try:
                            nameuser = getdata(cuser[index][i]['template_name'])
                        except:
                            nameuser = ''

                        FLAG_FOUND_VALID_OPTION = False
                        for o in ctemp.template['options']:
                            nameoption = o['template_name']
                            if(nameoption == nameuser):
                                ctemp.value[i] = configtemplate_to_dict(o)
                                FLAG_FOUND_VALID_OPTION = True
                                break

                        if(FLAG_FOUND_VALID_OPTION == False):
                            cuser[index][i] = None

                    # Loop again
                    loop_over_index(ctemp, cuser[index])

            else: # Apply the value
                try:
                    ctemp = c.value # If c is a configdata with a list (used for modifiable list)
                except:
                    ctemp = c

                try:  # Check if the user data is existing as well
                    ctemp[index].value = cuser[index]
                except: # Is this needed anymore? Everything should be configdata ...
                    try:  # Check if the user data is existing as well
                        ctemp[index] = cuser[index]
                    except:
                        pass
                    pass

    #print('Configdict before:', configdict)
    loop_over_index(configdict,userconfig)
    #print('Configdict after:', configdict)
    return configdict




class configuration(configDict):
    """
    The class is a modified dictionary with extra functionality for configuration.
    - history
    """
    def __init__(self,template,config={}):
        """
        Args:
            template:
            config:
        """
        template_config = template_to_configDict(template)
        super().__init__(template_config)



#
# Legacy, replaced by dict_to_configDict(process_template=True)
#
def template_to_configDict(template):
    """
    creates a config dictionary out of a configuration template, the values of the dictionary are
    configList/configNumber objects that can be accessed like classical values but have the capability to store
    attributes as well.

    """
    funcname = __name__ + 'template_to_config():'
    def loop_over_index(c):
        print('c',c,seq_iter(c))
        print(type(c))
        for index in seq_iter(c):
            print('c1', c[index])
            c[index] = data_to_configdata(c[index]) # Brute conversion of everything
            print('c2', c[index])
            # Check first if we have a configuration dictionary with at least the type
            FLAG_CONFIG_DICT = False
            if(type(c[index]) == dict):
                if ('default' in c[index].keys()):
                    default_value = c[index]['default']
                    default_type = default_value.__class__.__name__ # Defaults overrides type
                    FLAG_CONFIG_DICT = True
                if('type' in c[index].keys()):
                    default_type = c[index]['type']
                    default_value = ''
                    FLAG_CONFIG_DICT = True
                    if(c[index]['type'] == 'list'): # Modifiable list
                        #print('List')
                        if ('default' in c[index].keys()): # The default values are templates and need to be converted to dicts
                            default_value_tmp = c[index]['default']
                            default_value = []
                            if (type(default_value_tmp) == list):
                                for d in default_value_tmp:
                                    if(valid_template(d)):
                                        default_value.append(template_to_configDict(d))
                                    else:
                                        raise TypeError("The list entry should be a valid redvypr template")


                            else:
                                raise TypeError("The default value should be a list containing templates")
                        else:
                            default_value = []


            # Iterate over a dictionary or list
            if ((seq_iter(c[index]) is not None) and (FLAG_CONFIG_DICT == False)):
                #print('Loop')
                loop_over_index(c[index])
            else:
                # Check if we have some default values like type etc ...
                try:
                    confdata = data_to_configdata(default_value) # Configdata object
                    confdata.template = c[index]
                    c[index] = confdata
                except Exception as e:
                    #print('Exception',e)
                    confdata = data_to_configdata(c[index])
                    confdata.template = c[index]
                    c[index] = confdata


    config_tmp = copy.deepcopy(template) # Copy the template first
    if(type(config_tmp) == dict):
        config = configDict(template) #
    else:
        raise TypeError(funcname + 'template must be a dictionary and not {:s}'.format(str(type(template))))
    loop_over_index(config)
    #print('Config:',config)
    return config




