import sys
import logging
import copy

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.utils')
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

    def __reduce__(self):
        """
        The function returns only self.value and omits any additional information.

        Returns:

        """
        return (type(self.value), (self.value, ))

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



def addrm_device_as_data_provider(devices,deviceprovider,devicereceiver,remove=False):
    """ Adds or remove deviceprovider as a datasource to devicereceiver
    Arguments:
    devices: list of dictionary including device and dataout lists
    deviceprovider: Device object 
    devicerecevier: Device object
    Returns: None if device could not been found, True for success, False if device was already connected
    """
    funcname = "addrm_device_as_data_provider():"
    logger.debug(funcname)
    # Find the device first in self.devices and save the index
    inddeviceprovider = -1
    inddevicereceiver = -1    
    for i,s in enumerate(devices):
        if(s['device'] == deviceprovider):
            inddeviceprovider = i
        if(s['device'] == devicereceiver):
            inddevicereceiver = i     

    if(inddeviceprovider < 0 or inddevicereceiver < 0):
        logger.debug(funcname + ': Could not find devices, doing nothing')
        return None

    datainqueue       = devices[inddevicereceiver]['device'].datainqueue
    datareceivernames = devices[inddevicereceiver]['device'].data_receiver
    dataoutlist       = devices[inddeviceprovider]['dataout']
    logger.debug(funcname + ':Data receiver {:s}'.format(devices[inddevicereceiver]['device'].name))
    if(remove):
        if(datainqueue in dataoutlist):
            logger.debug(funcname + ': Removed device {:s} as data provider'.format(devices[inddeviceprovider]['device'].name))
            dataoutlist.remove(datainqueue)
            # Remove the receiver name from the list
            devices[inddevicereceiver]['device'].data_receiver.remove(devices[inddeviceprovider]['device'].name)
            devices[inddeviceprovider]['device'].data_provider.remove(devices[inddevicereceiver]['device'].name)
            # Emit device connection change signal
            devices[inddevicereceiver]['device'].connection_changed.emit()
            devices[inddeviceprovider]['device'].connection_changed.emit()
            return True
        else:
            return False
    else:
        if(datainqueue in dataoutlist):
            return False
        else:
            logger.debug('addrm_device_as_data_provider(): Added device {:s} as data provider'.format(devices[inddeviceprovider]['device'].name))
            dataoutlist.append(datainqueue)
            # Add the receiver and provider names to the device
            devices[inddevicereceiver]['device'].data_receiver.append(devices[inddeviceprovider]['device'].name)
            devices[inddeviceprovider]['device'].data_provider.append(devices[inddevicereceiver]['device'].name)
            # Emit device connection change signal
            devices[inddevicereceiver]['device'].connection_changed.emit()
            devices[inddeviceprovider]['device'].connection_changed.emit()
            return True


def get_data_receiving_devices(devices,device):
    """ Returns a list of devices that are receiving data from device
    """
    funcname = __name__ + 'get_data_receiving_devices():'
    devicesin = []
    # Find the device first in self.devices and save the index
    inddevice = -1
    for i,s in enumerate(devices):
        if(s['device'] == device):
            inddevice = i

    if(inddevice < 0):
        return None

    # Look if the devices are connected as input to the choosen device
    #  device -> data -> s in self.devices
    try:
        dataout = device.dataqueue
    except Exception as e:
        logger.debug(funcname + 'Device has no dataqueue for data output')
        return devicesin
    
    for dataout in devices[inddevice]['dataout']: # Loop through all dataoutqueues
        for s in devices:
            sen = s['device']
            datain = sen.datainqueue
            if True:
                if(dataout == datain):
                    devicesin.append(s)
            
    return devicesin

def get_data_providing_devices(devices,device):
    """
     Returns a list of devices that are providing their data to device, i.e. device.datain is in the 'dataout' list of the device
    devices = list of dictionaries 
    
        devices: List of dictionaries as in redvypr.devices
        device: redvypr Device, see exampledevice.py
        
    Returns
        -------
        list
            A list containing the device
    """
    devicesout = []
    # Find the device first in self.devices and save the index
    inddevice = -1
    for i,s in enumerate(devices):
        if(s['device'] == device):
            inddevice = i

    if(inddevice < 0):
        raise ValueError('Device not in redvypr')
        
    # Look if the devices are connected as input to the chosen device
    # s in self.devices-> data -> device
    datain = device.datainqueue
    for s in devices:
        sen = s['device']
        try:
            for dataout in s['dataout']:
                if(dataout == datain):
                    devicesout.append(s)
        except Exception as e:
            print('dataqueue',s,device,str(e))
            
    return devicesout



def __seq_iter__(obj):
    if isinstance(obj, dict):
        return obj
    elif isinstance(obj, list):
        return range(0,len(obj))
    else:
        return None



def configtemplate_to_dict(template):
    """
    creates a dictionary out of of a configuration dictionary, the values of the dictionary are configdata objects that store the template information as well
    a deepcopy of the dict will result in an ordinary dictionary.
    """
    def loop_over_index(c):
        for index in __seq_iter__(c):
            # Check first if we have a configuration dictionary with at least the type
            FLAG_CONFIG_DICT = False
            if(type(c[index]) == dict):
                if ('default' in c[index].keys()):
                    default_value = c[index]['default']
                    default_type = default_value.__class__.__name__ # Defaults overrides type
                    FLAG_CONFIG_DICT = True
                elif('type' in c[index].keys()):
                    default_type = c[index]['type']
                    default_value = ''
                    FLAG_CONFIG_DICT = True

            if ((__seq_iter__(c[index]) is not None) and (FLAG_CONFIG_DICT == False)):
                loop_over_index(c[index])
            else:
                # Check if we have some default values like type etc ...
                try:
                    confdata = configdata(default_value)
                    confdata.template = c[index]
                    c[index] = confdata
                except Exception as e:
                    print('Exception',e)
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

    def loop_over_index(c,cuser):
        for index in __seq_iter__(c):
            if (__seq_iter__(c[index]) is not None):
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


