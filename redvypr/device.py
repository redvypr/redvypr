"""

redvypr device class



"""

import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import logging
import sys
import yaml
import copy
import uuid
import multiprocessing
import threading
import importlib
import glob
import pathlib
import inspect
import pkg_resources
import redvypr
from redvypr.data_packets import compare_datastreams, parse_addrstr, commandpacket, redvypr_address, do_data_statistics
import redvypr.config as redvyprConfig



logging.basicConfig(stream=sys.stderr)


class redvypr_device_scan():
    """
    Searches for redvypr devices
    """
    def __init__(self, device_path = [],scan=True,redvypr_devices = None):
        """

        Args:
            device_path:
            scan: Flag if a scanning shall be performed at initialization
        """
        self.logger = logging.getLogger('redvypr_device_scan')
        self.logger.setLevel(logging.DEBUG)
        self.device_paths = device_path
        #self.redvypr = redvypr
        self.device_modules_path = []
        self.device_modules = []
        self.redvypr_devices = {'redvypr_modules': {},'redvypr':{},'files':{}}
        self.redvypr_devices_flat = []
        self.__modules_scanned__ = []
        self.__modules_scanned__.append(redvypr) # Do not scan redvypr itself

        # Start scanning
        if(scan):
            print('scanning redvypr')
            if redvypr_devices is not None:
                self.scan_redvypr(redvypr_devices)
            self.scan_modules()
            self.scan_devicepath()


    def print_modules(self):
        for m in self.device_modules:
            print(m)


    def scan_devicepath(self):
        funcname = 'search_in_path()'
        self.logger.debug(funcname)
        self.device_modules = []  # Clear the list
        #
        # Add all devices from additionally folders
        #
        # https://docs.python.org/3/library/importlib.html#checking-if-a-module-can-be-imported
        for dpath in self.device_paths:
            python_files = glob.glob(dpath + "/*.py")
            self.logger.debug(funcname + ' will search in path for files: {:s}'.format(dpath))
            for pfile in python_files:
                self.logger.debug(funcname + ' opening {:s}'.format(pfile))
                module_name = pathlib.Path(pfile).stem
                spec = importlib.util.spec_from_file_location(module_name, pfile)
                module = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(module)
                except Exception as e:
                    self.logger.warning(funcname + ' could not import module: {:s} \nError: {:s}'.format(pfile, str(e)))

                module_members = inspect.getmembers(module, inspect.isclass)
                valid_module = self.valid_device(module)
                if (valid_module['valid']):  # If the module is valid add it to devices
                    devdict = {'module': module, 'name': module_name, 'file': module.__file__,'type':'file'}
                    # Test if the module is already there, otherwise append
                    if (module in self.__modules_scanned__):
                        # logger.debug(funcname + ': Module has been tested already ...')
                        continue
                    else:
                        try:
                            self.redvypr_devices['files'][pfile] = {'__devices__': [devdict]}
                        except Exception as e:
                            self.logger.exception(e)

                        self.redvypr_devices_flat.append(devdict)
                        self.__modules_scanned__.append(module)



    def scan_module_recursive(self,testmodule, module_dict):
        funcname = 'scan_module_recursive():'
        # print(funcname,testmodule)
        # Check if the device is valid
        valid_module = self.valid_device(testmodule)
        if (valid_module['valid']):  # If the module is valid add it to devices
            # print('Members',inspect.getmembers(testmodule, inspect.ismodule))
            devdict = {'module': testmodule, 'name': testmodule.__name__, 'file': testmodule.__file__,'type':'module'}
            # module_dict[testmodule.__name__] = devdict
            try:
                module_dict['__devices__'].append(devdict)
            except:
                module_dict['__devices__'] = [devdict]

            self.redvypr_devices_flat.append(devdict)
        # Always append as scanned
        self.__modules_scanned__.append(testmodule)

        device_module_tmp = inspect.getmembers(testmodule, inspect.ismodule)
        if len(device_module_tmp) > 0:
            for smod in device_module_tmp:
                testmodule2 = getattr(testmodule, smod[0])
                if (testmodule2 in self.__modules_scanned__):
                    # logger.debug(funcname + ': Module has been tested already ...')
                    continue
                else:
                    try:
                        module_dict[testmodule.__name__]
                    except:
                        module_dict[testmodule.__name__] = {}
                    self.scan_module_recursive(testmodule2, module_dict[testmodule.__name__])
                    # Cleanup modules without devices
                    if len(module_dict[testmodule.__name__].keys()) == 0:
                        module_dict.pop(testmodule.__name__)

    def scan_redvypr(self,redvyprdevices):
        funcname = 'scan_redvypr():'
        self.logger.debug(funcname)
        if True:
            try:
                device_module_all = inspect.getmembers(redvyprdevices)
                self.scan_module_recursive(redvyprdevices,self.redvypr_devices['redvypr'])

            except Exception as e:
                self.logger.exception(e)
                #self.logger.info(funcname + ' Could not import module: ' + str(e))# If the module is valid add it to devices


    def scan_modules(self,package_names = ['vypr','vyper']):
        """
        Searches for installed packages containing redvypr devices. Packages do typically start with redvypr_package_name
        and add them to the device path
        Updates self.device_modules with dictionaries of type
        devdict = {'module': module, 'name': module_name, 'source': module.__file__}
        with module the imported module with module_name at the location __file__.

        Args:
            package_names: a list of package names that will be inspected
        Returns:

        """

        funcname = 'scan_modules():'
        self.logger.debug(funcname)

        # Loop over all modules and search for devices
        for d in pkg_resources.working_set:
            FLAG_POTENTIAL_MODULE = False
            #print('Package', d.location, d.project_name, d.version, d.key)
            #print(d.key)
            for name in package_names:
                if name in d.key:
                    FLAG_POTENTIAL_MODULE = True

            # Dont import the redvypr module itself
            if d.key == 'redvypr':
                #print('its me')
                FLAG_POTENTIAL_MODULE = False

            if(FLAG_POTENTIAL_MODULE):
                #print('Found package',d.location, d.project_name, d.version, d.key)
                libstr2 = d.key.replace('-','_')  # Need to replace - with _, because - is not allowed in python

                try:
                    testmodule = importlib.import_module(libstr2)
                    device_module_all = inspect.getmembers(testmodule)
                    self.scan_module_recursive(testmodule,self.redvypr_devices['redvypr_modules'])
                    # Clean empty dictionaries

                except Exception as e:
                    self.logger.info(funcname + ' Could not import module: ' + str(e))  # If the module is valid add it to devices


    def valid_device(self, devicemodule):
        """ Checks if the module is a valid redvypr module
        """
        funcname = 'valid_device(): '
        #self.logger.debug(funcname + 'Checking device {:s}'.format(str(devicemodule)))
        try:
            devicemodule.Device
            hasdevice = True
        except:
            hasdevice = False

        try:
            devicemodule.start
            hasstart = True
        except:
            hasstart = False

        if (hasstart == False):
            try:
                devicemodule.Device.start
                hasstart = True
            except:
                hasstart = False

        try:
            devicemodule.displayDeviceWidget
            hasdisplaywidget = True
        except:
            hasdisplaywidget = False

        try:
            devicemodule.initDeviceWidget
            hasinitwidget = True
        except:
            hasinitwidget = False

        devicecheck = {}
        devicecheck['valid'] = hasstart
        devicecheck['Device'] = hasdevice
        devicecheck['start'] = hasstart
        devicecheck['initgui'] = hasinitwidget
        devicecheck['displaygui'] = hasdisplaywidget

        return devicecheck


class redvypr_device(QtCore.QObject):
    thread_started = QtCore.pyqtSignal(dict)  # Signal notifying that the thread started
    thread_stopped = QtCore.pyqtSignal(dict)  # Signal notifying that the thread started
    status_signal  = QtCore.pyqtSignal(dict)   # Signal with the status of the device
    subscription_changed_signal = QtCore.pyqtSignal()  # Signal notifying that a subscription changed

    def __init__(self,name='redvypr_device',uuid = '', redvypr=None,dataqueue=None,comqueue=None,datainqueue=None,statusqueue=None,template = {},config = {},publishes=False,subscribes=False,multiprocess='tread',startfunction = None, loglevel = 'INFO',numdevice = -1,statistics=None,autostart=False,devicemodulename=''):
        """
        """
        super(redvypr_device, self).__init__()
        self.publishes   = publishes    # publishes data, a typical sensor is doing this
        self.subscribes  = subscribes   # subscribes other devices data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.statusqueue = statusqueue
        self.template    = template
        self.config      = config
        self.redvypr     = redvypr
        self.name        = name
        self.devicemodulename = devicemodulename
        self.uuid        = uuid
        try:
            self.host_uuid = redvypr.hostinfo['uuid']
        except:
            self.host_uuid = ''
        self.thread_uuid = ''
        self.host        = redvypr.hostinfo
        self.loglevel    = loglevel
        self.numdevice   = numdevice
        self.description = 'redvypr_device'
        self.statistics  = statistics
        self.mp          = multiprocess
        self.autostart   = autostart
        self.thread      = None
        # Create a redvypr_address
        # self.address_str
        # self.address
        self.__update_address__()

        # Add myself to the statistics
        datapacket = {'_redvypr':{}}
        datapacket['_redvypr']['device'] = self.name
        datapacket['_redvypr']['devicemodulename'] = self.devicemodulename
        datapacket['_redvypr']['host']=self.host
        do_data_statistics(datapacket,self.statistics)

        # Adding the start function (the function that is executed as a thread or multiprocess and is doing all the work!)
        if(startfunction is not None):
            self.start = startfunction

        # The queue that is used for the thread commmunication
        self.thread_communication = self.datainqueue

        self.subscribed_addresses = []
        
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(loglevel)

    def subscription_changed_global(self,devchange):
        """
        Function is called by redvypr after another device emitted the subscription_changed_signal

        Args:
            devchange: redvypr_device that emitted the subscription changed signal

        Returns:

        """
        pass
        #print('Global subscription changed',self.name,devchange.name)

    def address_from_datakey(self,datakey):
        """
        Returns a datastream string from the datakey and self.address
        Args:
            key:

        Returns:
            str: datastream strong
        """
        addr = redvypr_address(datakey = datakey,devicename=self.name,local_hostinfo=self.redvypr.hostinfo)
        return addr

    def subscribe_address(self, address,force=False):
        """
        Subscribes to address
        Args:
            address:
            force:

        Returns:

        """
        funcname = self.__class__.__name__ + '.subscribe_address()'
        self.logger.debug(funcname + ' subscribing to device {:s}'.format(str(address)))
        #print('Address',address,type(address))
        if type(address) == str or (type(address) == redvyprConfig.configString):
            raddr = redvypr_address(str(address))
        else:
            raddr = address

        FLAG_NEW = True
        # Test if the same address exists already
        for a in self.subscribed_addresses:
            if(a.address_str == raddr.address_str):
                FLAG_NEW = False
                break

        if(FLAG_NEW):
            self.subscribed_addresses.append(raddr)
            self.subscription_changed_signal.emit()
            print(self.subscribed_addresses)
            return True
        else:
            if force: # Resend the subscription signal
                self.subscription_changed_signal.emit()
            return False

    def unsubscribe_address(self, address):
        """
        """
        funcname = self.__class__.__name__ + '.unsubscribe_address()'
        self.logger.debug(funcname + ' unsubscribing from device {:s}'.format(str(address)))
        print('Address', address, type(address))
        if (type(address) == str):
            raddr = redvypr_address(address)
        else:
            raddr = address

        try:
            self.subscribed_addresses.remove(raddr)
            self.subscription_changed_signal.emit()
        except Exception as e:
            self.logger.warning('Could not remove address {:s}: {:s}'.format(str(address),str(e)))


    def change_name(self,name):
        """
        Changes the name of the device

        Args:
            name:

        Returns:

        """
        self.name = name
        self.__update_address__()
        # Clear the statistics
        self.statistics['numpackets'] = 0
        self.statistics['datakeys'] = []
        self.statistics['devicekeys'] = {}
        self.statistics['devices'] = []
        self.statistics['datastreams'] = []
        self.statistics['datastreams_dict'] = {}
        self.statistics['datastreams_info'] = {}
        self.logger.warning('This chnages only the device name but will not restart the thread.')

    def __update_address__(self):
        self.address_str = self.name + ':' + self.redvypr.hostinfo['hostname'] + '@' + self.redvypr.hostinfo[
            'addr'] + '::' + self.redvypr.hostinfo['uuid']
        self.address = redvypr_address(self.address_str)

    def address_string(self,strtype='<device>:<host>@<addr>::<uuid>'):
        """
        Returns the address string of the device
        Returns:

        """
        astr = self.address.get_str(strtype = strtype)
        return astr

    def got_subscribed(self,dataprovider_address,datareceiver_address,):
        """
        Function is called by self.redvypr if this device is connected with another one. The intention is to notify device
        that a specific datastream/devce has been subscribed. This is a wrapper function and need to be reimplemented if needed.
        See i.e. iored as an example
        Args:
            dataprovider_address:
            datareceiver_address:

        Returns:

        """
        pass

    def got_unsubscribed(self, dataprovider_address, datareceiver_address):
        """

        Args:
            dataprovider_address:
            datareceiver_address:

        Returns:

        """
        pass

    def get_thread_status(self):
        """

        Returns:

        """
        try:
            running = self.thread.is_alive()
        except:
            running = False

        info_dict = {}
        info_dict['uuid'] = self.uuid
        info_dict['thread_uuid'] = self.thread_uuid
        info_dict['thread_status'] = running

        return info_dict


    def __send_command__(self,command):
        """
        Sends a command to the running thread, either via the comqueue or the datainqueue
        Args:
            command: The command to be sent to the device, typically created with datapacket.commandpacket

        Returns:

        """

        self.thread_communication.put(command)


    def kill_process(self):
        funcname = __name__ + '.kill_process():'
        self.logger.debug(funcname)
        if(self.mp == 'multiprocess'):
            self.logger.debug(funcname + ': Terminating now')
            self.thread.kill()

    def thread_command(self, command,data=None):
        """
        Sends a command to the device thread
        Args:
            command: string, i.e. "stop"
            data: dictionary with additional data, the data will be incorporated into the command dict by executing command.update8(ata)

        Returns:

        """
        funcname = __name__ + '.thread_command():'
        self.logger.debug(funcname)
        command = commandpacket(command=command, device_uuid=self.uuid, thread_uuid=self.thread_uuid,devicename=self.name,host=self.redvypr.hostinfo,devicemodulename=self.devicemodulename)
        # TODO, this should be done by commandpacket
        if(data is not None):
            if type(data) == dict:
                command.update(data)
            else:
                raise TypeError('data needs to be a dictionary')

        try:
            running = self.thread.is_alive()
        except:
            running = False

        if(running):
            #print('Sending command',command)
            self.__send_command__(command)
        else:
            self.logger.warning(funcname + ' thread is not running, doing nothing')

    def thread_stop(self):
        """
        Sends a stop command to the thread_communication queue
        Returns:

        """
        funcname = __name__ + '.thread_stop():'
        self.logger.debug(funcname)
        command = commandpacket(command='stop', device_uuid=self.uuid,thread_uuid=self.thread_uuid)
        #print('Sending command',command)
        try:
            running = self.thread.is_alive()
        except:
            running = False

        if(running):
            self.__send_command__(command)
            try:
                running2 = self.thread.is_alive()
            except:
                running2 = False
            info_dict = {}
            info_dict['uuid'] = self.uuid
            info_dict['thread_status'] = running2
            self.thread_stopped.emit(info_dict)
        else:
            self.logger.warning(funcname + ' thread is not running, doing nothing')

    def thread_start(self):
        """ Starts the device thread, it calls the self.start function with the arguments

        start(self, device_info, config, dataqueue, datainqueue, statusqueue)

        config is a deepcopy of self.config: config = copy.deepcopy(self.config). The deepcopy converts the
        configuration dictionary into an ordinary dictionary "forgetting" additional information and making the
        configuration hashable as it is needed for a multiprocess.

        Args:


        """
        funcname = __name__ + '.start_thread():'

        #logger.debug(funcname + 'Starting device: ' + str(device.name))
        self.logger.debug(funcname + 'Starting device: ' + str(self.name))
        sendict = {}#self.__sendict__
        # Find the right thread to start
        if True:
            if True:
                try:
                    running = self.thread.is_alive()
                except:
                    running = False

                if(running):
                    self.logger.warning(funcname + ':thread/process is already running, doing nothing')
                else:
                    try:
                        # The arguments for the start function
                        thread_uuid = 'thread_' + str(uuid.uuid1())
                        device_info = {'device':self.name,'uuid':self.uuid,'thread_uuid':thread_uuid,'hostinfo':self.redvypr.hostinfo}
                        config = copy.deepcopy(self.config) # The thread/multiprocess gets a copy
                        args = (device_info,config, self.dataqueue, self.datainqueue, self.statusqueue)
                        if self.mp == 'thread':
                            self.logger.info(funcname + 'Starting as thread')
                            self.thread = threading.Thread(target=self.start, args=args, daemon=True)
                        else:
                            self.logger.info(funcname + 'Starting as process')
                            self.thread = multiprocessing.Process(target=self.start, args=args)
                            #self.logger.info(funcname + 'started {:s} as process with PID {:d}'.format(self.name, self.thread.pid))

                        self.thread.start()
                        sendict['thread'] = self.thread
                        self.logger.info(funcname + 'started {:s}'.format(self.name))
                        # Update the device and the devicewidgets about the thread status
                        running2 = sendict['thread'].is_alive()
                        try: # If the device has a thread_status function
                            self.thread_status({'threadalive':running2})
                        except:
                            pass

                        self.thread_uuid = thread_uuid

                        info_dict                  = {}
                        info_dict['uuid']          = self.uuid
                        info_dict['thread_uuid']   = thread_uuid
                        info_dict['thread_status'] = running2
                        self.thread_started.emit(info_dict)  # Notify about the started thread

                        return self.thread

                    except Exception as e:
                        self.logger.warning(funcname + 'Could not start thread, reason: {:s}'.format(str(e)))
                        return None

    def __str__(self):
        return self.description
    
    def finalize_init(self):
        """
        Dummy function, can be defined by the user. Function is called after the device is added to redvypr.

        Returns:

        """
        pass

    def get_deviceaddresses(self,local=None):
        """
        Returns a list with redvypr_addresses of all devices that publish data via this device. This is in many cases
        the device itself but can also forwarded devices (i.e. iored) or because the device publishes data with different
        devicenames::
           dataqueue.put({'count': i}) # Devicename as the device itself
           dataqueue.put({'count': i+10,'_redvypr':{'device':'test2'}}) # Devicename is 'test2'

        Args:
            local: None, True or False

        Returns: List of redvypr_addresses

        """
        addr_str = list(self.statistics['device_redvypr'].keys())
        addr_list = []
        for a in addr_str:
            raddr = redvypr_address(a)
            if local is None:
                addr_list.append(raddr)
            else: # Check if we have a local or remote address
                raddr_local = raddr.uuid == self.host_uuid
                if local == raddr_local:
                    addr_list.append(raddr)

        return addr_list

    def get_datastreams(self,local=None):

        devaddrs = self.get_deviceaddresses(local)
        datastreams = []
        for devaddr in devaddrs:
            dkeys = self.statistics['device_redvypr'][devaddr.address_str]['datakeys']
            for dkey in dkeys:
                raddr = redvypr_address(devaddr,datakey=dkey)
                dstr = raddr.get_str()
                datastreams.append(dstr)


        return datastreams

    def get_device_info(self):
        """
        Returns a deepcopy that is saved in self.statistics['device_redvypr'] containing information about all devices
        that have been sent by this device.
        Note: name was def get_data_provider_info(self):

        Returns: dictionary with the device addresses as keys

        """
        d = copy.deepcopy(self.statistics['device_redvypr'])
        return d



    def publishing_to(self):
        """

        Returns:
            List of devices this device is publishing to
        """
        self.logger.warning('needs to be refurbished')
        devs = self.redvypr.get_data_receiving_devices(self)
        return devs

    def get_subscribed_devices(self):
        """
        Returns all redvypr.devices this device is subscribed to.

        Returns:

        """
        funcname = __name__ + '.get_subscribed_devices()'
        devs = self.redvypr.get_devices()
        devs_subscribed = []
        for subaddr in self.subscribed_addresses:
            for dev in reversed(devs):
                if (subaddr in dev.address) and (dev is not self):
                    devs_subscribed.append(dev)
                    devs.remove(dev)

        return devs_subscribed

    def get_subscribed_deviceaddresses(self):
        """
        List of redvypr devices addresses this device has subscribed. This is different from self.subcribed_addresses as it
        returns the existing devices, in self.subscribed_addresses also regular expressions can exist.

        Returns: List of redvypr addresses

        """
        funcname = __name__ + '.get_subscribed_deviceaddresses()'
        subaddresses = []
        raddresses = self.redvypr.get_deviceaddresses()

        #print('raddresses', raddresses)
        #print('subscribed addresses',self.subscribed_addresses)
        for subaddr in self.subscribed_addresses:
            for addr in reversed(raddresses):
                if subaddr in addr:
                    subaddresses.append(addr)
                    raddresses.remove(addr)

        #print('subaddresses', subaddresses)
        return subaddresses
            
    def unsubscribe_all(self):
        """
        """
        funcname = self.__class__.__name__ + '.unsubscribe_all()'
        self.logger.debug(funcname)
        self.subscribed_addresses = []
                    
        
    def get_info(self):
        """
        Returns a dictionary with the essential info of the device
        Returns:

        """
        info_dict = {}
        info_dict['uuid'] = self.uuid
        info_dict['name'] = self.name

        return info_dict

    def print_info(self):
        """ Displays information about the device

        """
        print('get_info():')
        print('Name' + self.name)
        print('redvypr' + self.redvypr)  
        
    def __str__(self):
        return 'redvypr_device (' + self.devicemodulename + ') ' + self.address_string()

