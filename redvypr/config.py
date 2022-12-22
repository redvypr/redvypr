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
    def __init__(self, n=None): self.n=n
    def __repr__(self): return repr(self.n)
    def __str__(self): return str(self.n)
    # def __bytes__(self): unimplemented
    def __format__(self, format_spec): self.n.__format__(format_spec)

    def __lt__(self, other): return self.n < other
    def __le__(self, other): return self.n <= other
    def __ne__(self, other): return self.n != other
    def __eq__(self, other): return self.n == other
    def __gt__(self, other): return self.n > other
    def __ge__(self, other): return self.n >= other

    def __hash__(self): return hash(self.n)
    def __bool__(self): return bool(self.n)

    # math functions
    def __ceil__(self): return math.ceil(self.n)
    def __floor__(self): return math.floor(self.n)
    def __trunc__(self): return math.trunc(self.n)

    # Binary arithmetic operations
    def __add__(self, other): return self.n + other
    def __sub__(self, other): return self.n - other
    def __mul__(self, other): return self.n * other
    def __truediv__(self, other): return self.n / other
    def __floordiv__(self, other): return self.n // other
    def __mod__(self, other): return self.n % other
    def __divmod__(self, other): return divmod(self.n, other)
    def __pow__(self, other, modulo=None): return pow(self.n, other, modulo)
    def __lshift__(self, other): return self.n << other
    def __rshift__(self, other): return self.n >> other
    def __and__(self, other): return self.n & other
    def __xor__(self, other): return self.n ^ other
    def __or__(self, other): return self.n | other

    # Right binary operations
    def __radd__(self, other): return other + self.n
    def __rsub__(self, other): return other - self.n
    def __rmul__(self, other): return other * self.n
    def __rtruediv__(self, other): return other / self.n
    def __rfloordiv__(self, other): return other // self.n
    def __rmod__(self, other): return other % self.n
    def __rdivmod__(self, other): return divmod(other, self.n)
    def __rpow__(self, other): return pow(other, self.n)
    def __rlshift__(self, other): return other << self.n
    def __rrshift__(self, other): return other >> self.n
    def __rand__(self, other): return other & self.n
    def __rxor__(self, other): return other ^ self.n
    def __ror__(self, other): return other | self.n

    # In-place binary operations
    def __iadd__(self, other):
        self.n += other
        return self
    def __isub__(self, other):
        self.n -= other
        return self
    def __imul__(self, other):
        self.n *= other
        return self
    def __itruediv__(self, other):
        self.n /= other
        return self
    def __ifloordiv__(self, other):
        self.n //= other
        return self
    def __imod__(self, other):
        self.n %= other
        return self
    def __ipow__(self, other, modulo=None):
        self.n = pow(self.n, other, modulo)
        return self
    def __ilshift__(self, other):
        self.n <<= other
        return self
    def __irshift__(self, other):
        self.n >>= other
        return self
    def __iand__(self, other):
        self.n &= other
        return self
    def __ixor__(self, other):
        self.n ^= other
        return self
    def __ior__(self, other):
        self.n |= other
        return self

    # Unary arithmetic operations
    def __neg__(self): return -self.n
    def __pos__(self): return +self.n
    def __abs__(self): return abs(self.n)
    def __invert__(self): return ~self.n

    # Conversion functions
    def __complex__(self): return complex(self.n)
    def __int__(self): return int(self.n)
    def __float__(self): return float(self.n)
    def __round__(self, n=0): return round(self.n, n)

    def __index__(self): return self.n.__index__()

    # integer functions
    # https://docs.python.org/3/library/stdtypes.html#additional-methods-on-integer-types
    def bit_length(self): return self.n.bit_length()
    def to_bytes(self, length, byteorder, *args, signed=False):
        return self.n.to_bytes(length, byteorder, *args, signed=signed)
    def from_bytes(self, bytes, byteorder, *args, signed=False):
        return self.n.from_bytes(bytes, byteorder, *args, signed=signed)
    def conjugate(self): return self.n.conjugate()

    @property
    def denominator(self): return self.n.denominator
    @property
    def numerator(self): return self.n.numerator

    @property
    def imag(self): return self.n.imag
    @property
    def real(self): return self.n.real

    # float functions
    # https://docs.python.org/3/library/stdtypes.html#additional-methods-on-float
    def as_integer_ratio(self): return self.n.as_integer_ratio()
    def is_integer(self): return self.n.is_integer()
    def hex(self): return self.n.hex()

    @property
    def value(self): return self.n

    @value.setter
    def value(self, n): self.n = n

    def __reduce_ex__(self,protocol):
        return self.n.__reduce_ex__(protocol)

    def __reduce__(self):
        return self.n.__reduce__()


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

def template_to_config(template):
    """
    Dreates a config dictionary out of a configuration template, the values of the dictionary are
    configList/configNumber objects that can be accessed like classical values but have the capability to store
    attributes as well.

    """
    def loop_over_index(c):
        for index in seq_iter(c):
            c[index] = data_to_configdata(c[index]) # Brute conversion of everything
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
    loop_over_index(config)
    #print('Config:',config)
    return config




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
        pass



