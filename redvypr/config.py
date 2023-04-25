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

Templates can be used to define the configuration
A template is a dict with the keys defining entries that can be configured.
Options are for lists and dicts datatypes that can be added, for int, float, str the values of the variable
.. code-block::

    config_template['list_options'] = {'type': 'list', 'options': ['int','float']}
    config_template['int_options'] = {'type': 'int', 'options': [4,5,6]}

As option also other templates can be used

.. code-block::

    template_option = {}
    template_option['template_name'] = 'option1'
    template_option['port'] = {'type': 'int'}

    config_template['template_name'] = 'test_template'
    config_template['list_options'] = {'type': 'list', 'options': ['int',template_option]}





"""

import sys
import logging
import copy
import collections
import numbers
import math
from redvypr.configdata import seq_iter

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.config')
logger.setLevel(logging.DEBUG)


template_types = []
template_types.append({'type': 'dict','default':{}})
template_types.append({'type': 'list','default':[]})
template_types.append({'type': 'str','default':''})
template_types.append({'type': 'int','default':0})
template_types.append({'type': 'float','default':0.0})
template_types.append({'type': 'bool','default':True})
template_types.append({'type': 'datastream','default':'*','subtype':'datastream'}) # subtypes are used to distinguish between general types and more specialized
template_types.append({'type': 'color','default':{'template_name':'colordict','r':0,'g':0,'b':0,'a':0},'subtype':'color'})
#template_types.append({'type': 'ip'})



template_types_dict = {}
for t in template_types:
    template_types_dict[t['type']] = t


__template_types__modifiable_list__ = []
__template_types__modifiable_list__.append(template_types_dict['int'])
__template_types__modifiable_list__.append(template_types_dict['float'])
__template_types__modifiable_list__.append(template_types_dict['str'])
__template_types__modifiable_list__.append(template_types_dict['bool'])

__template_types__modifiable_list_dict__ = {}
for t in __template_types__modifiable_list__:
    __template_types__modifiable_list_dict__[t['type']] = template_types_dict[t['type']]


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
    https://github.com/markrages/python_mutable_number
    that includes a deepcopy functionality, i.e. returns the original data type if a copy.deepcopy() is called.
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


def data_to_configdata(data,recursive = False):
    """
    Converts a known class to a configClass, that can additionally store attributes
    Args:
        data:

    Returns:
        configClass: an class that behaves similar to the original data but can store attributes

    """
    funcname = __name__ + '.to_configdata():'
    if recursive == False:
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
    else: # Call dict_to_configDict with data
        configdata = dict_to_configDict({'data':data})['data']
        return configdata


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
    funcname = __name__ + '.valid_template():'
    if(type(template) == dict):
        if('template_name' in template.keys()):
            return True
        else:
            logger.debug(funcname + 'key "template_name" missing')
    else:
        logger.debug(funcname + 'template not a dictionary {:s}'.format(str(type(template))))

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

    raise TypeError(funcname + 'Could not return data for datatype {:s}'.format(str(type(data))))



def dict_to_configDict(data,process_template=False,configdict=None):
    """
    creates a config dictionary out of a configuration template, the values of the dictionary are
    configList/configNumber objects that can be accessed like classical values but have the capability to store
    attributes as well.

    """
    funcname = __name__ + 'dict_to_configDict():'
    def loop_over_index(c):
        #print('c',c,seq_iter(c))
        for index in seq_iter(c):
            # Check first if we have a configuration dictionary entry
            FLAG_CONFIG_DICT = False
            if ((type(c[index]) == configDict) or (type(c[index]) == dict)) and process_template:
                if ('type' in c[index].keys()) or ('default' in c[index].keys()):
                    #print('Configdict')
                    FLAG_CONFIG_DICT = True
            #print('c1', c[index])
            origdata = copy.deepcopy(c[index])
            origtype = c[index].__class__.__name__
            default_value = data_to_configdata(c[index]) # Brute conversion of everything
            default_value.__parent__ = c
            c[index] = default_value
            #print('c2', c[index])
            # Check first if we have a configuration dictionary with at least the type
            if(FLAG_CONFIG_DICT == False): # standard entry
                if(process_template):
                    if(origtype in template_types_dict.keys()):
                        #print('Adding standard template to data')
                        c[index].template = copy.deepcopy(template_types_dict[origtype])
                        c[index].template['default'] = origdata
            else: # Configuration dictionary
                default_value = ''
                # The if can be removed soon
                if ('default' in c[index].keys()):
                    default_value = c[index]['default']
                    default_type = default_value.__class__.__name__  # Defaults overrides type
                    # Add the type, if its not existing
                    try:
                        c[index]['type']
                    except:
                        c[index]['type'] = default_type

                # loop over all keys of standard types and add potentially missing information
                if(c[index]['type'] in template_types_dict.keys()):
                    #print('Adding keys of standard type')
                    standard_template = copy.deepcopy(template_types_dict[c[index]['type']])
                    for k in standard_template.keys():
                        try:
                            c[index][k]
                            #print('c[index][k]',c[index][k])
                        except:
                            #print('Adding',standard_template[k])
                            c[index][k] = standard_template[k]#

                        if (k == 'default'):
                            if valid_template(c[index]['default']):
                                #print('Template', c[index]['default'])
                                dtmp = dict_to_configDict(c[index]['default'], process_template=process_template)
                                default_value = dtmp
                            else:
                                default_value = data_to_configdata(c[index]['default'],recursive=True)

                templatedata = copy.deepcopy(c[index])
                templatedata_orig = copy.deepcopy(c[index])
                default_type = c[index]['type']
                try:
                    modifiable = c[index]['modify']
                except Exception as e:
                    modifiable = False

                if (c[index]['type'] == 'list') and modifiable: # Modifiable list
                    # Check if options are in the template, if not not add standard types
                    try:
                        c[index]['options']
                        # Loop over the options and replace standard options with their dictionary types
                        for i,o in enumerate(c[index]['options']):
                            #print('Option to be checked', o)
                            # If the option is a str, try to find the correct template in the standard template
                            if (type(o) == str) or (type(o) == configString):
                                print('Converting to standard option',o)
                                try:
                                    c[index]['options'][i] = copy.deepcopy(__template_types__modifiable_list_dict__[o])
                                    print('Changed option', c[index]['options'][i])
                                    print('Hallo', c)
                                except Exception as e:
                                    print('Did not change because of',e)
                                    continue
                    except: # If no options are given, simply copy all options as a choice
                        c[index]['options'] = copy.deepcopy(__template_types__modifiable_list__)

                    templatedata['options'] = c[index]['options'] # Copy the modified options
                    if ('default' in c[index].keys()): # The default values are templates and need to be converted to dicts
                        default_value_tmp = c[index]['default']
                        default_value = configList()
                        default_value.__parent__ = c # Save the parent as attribute
                        #print('Default',default_value_tmp)
                        if (type(default_value_tmp) == list) or (type(default_value_tmp) == configList):
                            #print('Configlist',type(default_value_tmp))
                            for d in default_value_tmp:
                                #print('d',d)
                                if valid_template(d):
                                    #print('Template', d)
                                    dtmp = dict_to_configDict(d, process_template=process_template)
                                else:
                                    #print('Standard data', d)
                                    dtmp = data_to_configdata(d,recursive=True)

                                dtmp.template = copy.deepcopy(d)
                                dtmp.__parent__ = default_value # Save the parent as attribute
                                default_value.append(dtmp)
                                default_value.template = copy.deepcopy(c[index])
                        else:
                            raise TypeError("The default value should be a list containing templates")
                    else:
                        default_value = configList()
                        default_value.template = copy.deepcopy(c[index])

                #print('Default value',default_value,FLAG_CONFIG_DICT,type(default_value))
                c[index] = data_to_configdata(default_value)
                # Test if an template was already added above, otherwise add one
                try:
                    c[index].template
                except:
                    #print('Adding template', origdata)
                    c[index].template = templatedata
                    c[index].__template_orig__ = templatedata_orig


            # Iterate over a dictionary or list
            if ((seq_iter(c[index]) is not None) and (FLAG_CONFIG_DICT == False)):
                #print('Loop')
                loop_over_index(c[index])

    # Create a copy of the input dictionary and work with that
    if(configdict == None):
        data_tmp = copy.deepcopy(data) # Copy the data first
        if(type(data_tmp) == dict):
            data_dict = configDict(data_tmp) #
        elif (type(data_tmp) == configDict):
            data_dict = data_tmp
        else:
            raise TypeError(funcname + 'data must be a dictionary and not {:s}'.format(str(type(data))))
    else: # Modify the original data
        data_dict = configdict

    # Start the iterative processing now
    data_dict.__parent__ = None
    loop_over_index(data_dict)
    #print('Config:',config)
    #print('Data dict',data_dict,type(data_dict))
    return data_dict









def apply_config_to_configDict(userconfig,configdict):
    """
    Applies a user configuration to a dictionary created from a template
    Args:
        userconfig: The configuration dictionary
        configdict: The dictionary the configuration will be applied to

    Returns:
        configdict_applied: A with the userconfig modified configuration dictionary
    """
    funcname = __name__ + '.apply_config_to_configDict():'
    logger.debug(funcname)
    def loop_over_index(c,cuser):
        for index in seq_iter(cuser): # Loop over the user config
            #print('c', c, index)
            indices = seq_iter(c)
            #print('c', c, index,indices)
            #print(index in indices)
            # Try to get the same data at the index in the template
            try:
                ctemp = c[index]
            except:
                continue

            try:
                modifiable = ctemp.template['modify']
            except Exception as e:
                modifiable = False

            if (seq_iter(ctemp) is not None) and (modifiable == False):
                #print('Hallo',cuser,index)
                try: # Check if the user data is existing as well
                    cuser[index]
                    if (seq_iter(cuser[index]) is not None):
                        loop_over_index(ctemp, cuser[index])
                except Exception as e:
                    logger.debug(funcname + ': cuser[index]: ' + str(e))
                    continue

            # Check if this is a configdata list, that can be modified
            elif(type(ctemp) == configList):
                try:
                    t = ctemp.template['type']
                except Exception as e:
                    t = ''

                #print('List',t,modifiable)
                if (t == 'list') and modifiable: # modifiable list
                    # First make the list equally long, the user list is either 0 or longer
                    numitems = len(cuser[index])
                    dn = numitems - len(ctemp)
                    for i in range(dn):
                        ctemp.append(None)

                    # Fill the list with the right templates
                    for i in range(numitems):
                        try:
                            nameuser = cuser[index][i]['template_name']
                        except:
                            nameuser = cuser[index][i].__class__.__name__

                        FLAG_FOUND_VALID_OPTION = False
                        #print('Template options',ctemp.template)
                        #print('Nameuser',nameuser)
                        for o in ctemp.template['options']:
                            #print('Option',o)
                            # If the option is a str, try to find the correct template in the standard template
                            if(type(o) == str) or (type(o) == configString):
                                #print('Converting to standard option')
                                try:
                                    o = copy.deepcopy(__template_types__modifiable_list_dict__[o])
                                except:
                                    continue

                            try: # Check if this is a template
                                nameoption = o['template_name']
                                FLAG_TEMPLATE=True
                            except: # or a standard template
                                nameoption = o['type']
                                FLAG_TEMPLATE = False

                            #print('Nameoption',nameoption,FLAG_TEMPLATE)
                            if(nameoption == nameuser) and FLAG_TEMPLATE:
                                #print('Converting the template')
                                ctemp[i] = dict_to_configDict(o,process_template=True)
                                #print('ctemp',ctemp[i])
                                FLAG_FOUND_VALID_OPTION = True
                                break
                            elif nameoption == nameuser:
                                ctemp[i] = o['default']
                                FLAG_FOUND_VALID_OPTION = True
                                break

                        if(FLAG_FOUND_VALID_OPTION == False):
                            cuser[index][i] = None

                    # Loop again
                    loop_over_index(ctemp, cuser[index])

            else: # Apply the value
                ctemp = c
                # TODO, here a type check would be useful
                try:  # Check if the user data is existing as well
                    ctemp[index].data = cuser[index]
                except Exception as e: # Is this needed anymore? Everything should be configdata ...
                    print('Exception exception',e)
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
    def __init__(self,template={},config=None):
        """
        Args:
            template:
            config:
        """
        super().__init__(template)
        #self.config_orig = config
        #self.data = dict_to_configDict(template, process_template=True)
        tmp = dict_to_configDict(template, process_template=True,configdict=self)

        #print('Applying')
        if(config is not None):
            test = apply_config_to_configDict(config,self)
            #print('test',test)
















