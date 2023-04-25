import sys
import logging
import copy

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.configdata')
logger.setLevel(logging.DEBUG)


#
# Custom object to store optional data as i.e. qitem, but does not
# pickle it, used to get original data again
#
class configdata():
    """ This is a class that stores the original data and potentially
    additional information, if it is pickled it is only returning
    self.value but not potential additional information
    
    The usage is to store configurations and additional complex data as whole Qt Widgets associated but if the configdata is pickled or copied it will return only the original data
    For example::
        d  = configdata('some text')
        d.moredata = 'more text or even a whole Qt Widget'
        e = copy.deepcopy(d)
        print(e) 
    """
    def __init__(self, value):
        self.value = value

    def __reduce_ex__(self,protocol):
        """
        The function returns the reduce_ex of the self.value object

        Returns:

        """
        return self.value.__reduce_ex__(protocol)

    def __reduce__(self):
        """
        The function returns self.value and omits any additional information.

        Returns:

        """
        return self.value.__reduce__()
        # Legacy
        #if self.value == None:
        #    return (type(self.value), ())

        #return (type(self.value), (self.value,))

    def __str__(self):
        rstr = 'configdata: {:s}'.format(str(self.value))
        return rstr

    def __repr__(self):
        rstr = 'configdata: {:s}'.format(str(self.value))
        return rstr


def getdata(data):
    """
    Returns the data of an object, if its an configdata object, it returns data.value, otherwise data
    Args:
        data:

    Returns:

    """
    try:
        return data.value
    except:
        return data


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



def seq_iter(obj):
    """
    To treat dictsionaries and lists equally this functions returns either the keys of dictionararies or the indices of a list.
    This allows a
    index = seq_iter(data)
    for index in data:
        data[index]

    with index being a key or an int.

    Args:
        obj:

    Returns:
        list of indicies

    """
    try: # Test if we have an UserDict or UserList or configDict or configList or configuration
        obj_test = obj.data
    except:
        obj_test = obj

    if isinstance(obj_test, dict):
        return obj
    elif isinstance(obj_test, list):
        return range(0,len(obj))
    else:
        return None



def configtemplate_to_dict(template):
    """
    creates a dictionary out of a configuration dictionary, the values of the dictionary are configdata objects that store the template information as well.
    A deepcopy of the dict will result in an ordinary dictionary.
    """
    def loop_over_index(c):
        for index in seq_iter(c):
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
                                        default_value.append(configtemplate_to_dict(d))
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
                    confdata = configdata(default_value) # Configdata object
                    confdata.template = c[index]
                    c[index] = confdata
                except Exception as e:
                    #print('Exception',e)
                    confdata = configdata(c[index])
                    confdata.template = c[index]
                    c[index] = confdata

    config = copy.deepcopy(template) # Copy the template first
    loop_over_index(config)
    #print('Config:',config)
    return config


def apply_config_to_dict(userconfig,configdict):
    """
    Applies a user configuration to a dictionary created from a template
    Args:
        userconfig:
        configdict:

    Returns:
        configdict: A with the userconfig modified configuration dictionary
    """
    funcname = __name__ + '.apply_config_to_dict():'
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


# Legacy, hopefully to be deleted soon
def apply_config_to_dict_static(userconfig,configdict):
    """
    Applies a user configuration to a dictionary created from a template
    Args:
        userconfig:
        configdict:

    Returns:
        configdict: A with the userconfig modified configuration dictionary
    """

    def loop_over_index(c,cuser):
        for index in seq_iter(c):
            if (seq_iter(c[index]) is not None):
                try: # Check if the user data is existing as well
                    cuser[index]
                except:
                    continue

                loop_over_index(c[index],cuser[index])
            else:
                try:  # Check if the user data is existing as well
                    c[index].value = cuser[index]
                except:
                    try:  # Check if the user data is existing as well
                        c[index] = cuser[index]
                    except:
                        pass
                    pass

    print('Configdict before:', configdict)
    loop_over_index(configdict,userconfig)
    print('Configdict after:', configdict)
    return configdict


