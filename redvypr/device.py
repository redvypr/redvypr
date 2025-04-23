"""

redvypr device class



"""

import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
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
import pydantic
import typing
import re
from redvypr.data_packets import commandpacket, create_datadict
from redvypr.packet_statistic import do_data_statistics
from redvypr.redvypr_address import RedvyprAddress, metadata_address

logging.basicConfig(stream=sys.stderr)


# The maximum size the dataqueues have, this should be more than
# enough for a "normal" usage case
queuesize = 10000
# queuesize = 10

class DeviceMetadata(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")
    description: str = pydantic.Field(default='')
    lon: float = pydantic.Field(default=-9999)
    lat: float = pydantic.Field(default=-9999)

class RedvyprDeviceCustomConfig(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")
    config_type: typing.Literal['custom'] = pydantic.Field(default='custom')

class RedvyprDeviceBaseConfig(pydantic.BaseModel):
    """
    This is the base config of any redvypr device.
    """
    name: str = pydantic.Field(default='')
    multiprocess: typing.Literal['qthread','multiprocess'] = pydantic.Field(default='qthread')  # str = pydantic.Field(default='qthread')
    loglevel: str = pydantic.Field(default='')
    autostart: bool = False
    clear_datainqueue_before_thread_starts: bool = pydantic.Field(default=False, description='Clears the datainqueue before the thread is started.')
    devicemodulename: str = pydantic.Field(default='')
    description: str = ''
    gui_tablabel_init: str = 'Init'
    gui_tablabel_display: str = 'Display'
    gui_dock: typing.Literal['Tab','Window','Hide'] = pydantic.Field(default='Tab')
    gui_icon: str = 'mdi.network-outline'

class RedvyprDeviceConfig(pydantic.BaseModel):
    """
    Device configuration that is used for saving and loading files
    """
    base_config: RedvyprDeviceBaseConfig = pydantic.Field(default=RedvyprDeviceBaseConfig())
    devicemodulename: str = pydantic.Field(default='', description='')
    custom_config: typing.Optional[RedvyprDeviceCustomConfig] = pydantic.Field(default=None, description='')
    subscriptions: list = pydantic.Field(default=[])
    datakeytags: list = pydantic.Field(default=['mac','sn','id'],description='datakeys for which will be looked at at each packet and a statistic will be done')
    metadata: typing.Optional[DeviceMetadata] = pydantic.Field(default=None, description='')
    config_type: typing.Literal['device'] = pydantic.Field(default='device')

class RedvyprDeviceParameter(RedvyprDeviceBaseConfig):
    """
    This is the base config with extra parameter that dont need to be saved
    """
    uuid: str = pydantic.Field(default='')
    #template: dict = pydantic.Field(default={}) # Candidate for removal
    #config: dict = pydantic.Field(default={})  # Candidate for removal
    publishes: bool = True
    subscribes: bool = True
    numdevice: int = pydantic.Field(default=-1)
    # Not as parameter, but necessary for initialization
    maxdevices: int = pydantic.Field(default=-1)

class deviceQThread(QtCore.QThread):
    def __init__(self, startfunction, start_arguments):
        QtCore.QThread.__init__(self)
        self.startfunction = startfunction
        self.start_arguments = start_arguments

    def __del__(self):
        self.wait()

    def run(self):
        #print('Arguments',self.start_arguments)
        self.startfunction(*self.start_arguments)


def device_start_standard(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start():'
    logger = logging.getLogger('redvypr.redvypr.device_start():')
    while True:
        data = datainqueue.get()
        if data is not None:
            command = redvypr.data_packets.check_for_command(data, thread_uuid=device_info['thread_uuid'])
            #logger.debug('Got a command: {:s}'.format(str(data)))
            if command == 'stop':
                logger.debug('Command is for me: {:s}'.format(str(command)))
                break

            dataqueue.put(data)



logging.basicConfig(stream=sys.stderr)


class RedvyprDeviceScan():
    """
    Searches for redvypr devices
    """
    def __init__(self, device_path = [],
                 scan=True,
                 scan_redvypr=True,
                 scan_modules=True,
                 scan_devicepath=True,
                 redvypr_devices=None,
                 loglevel = logging.INFO):
        """

        Parameters
        ----------
        device_path
        scan: bool
            Does a scan after initialization.
        scan_redvypr: bool
            Scans redvypr_devices (if scan is set)
        scan_modules: bool
            Scans modules (if scan is set)
        scan_devicepath: bool
            Scans possible devices in devicepaths (if scan is set)
        redvypr_devices: python redvypr modules
            Scans modules for redvypr compatible devices
        loglevel: logging.loglevel
            The loglevel
        """
        self.logger = logging.getLogger('redvypr.redvypr_device_scan')
        self.logger.setLevel(loglevel)
        self.device_paths = device_path
        self.redvypr_devices = redvypr_devices
        #self.redvypr = redvypr
        self.device_modules_path = []
        self.device_modules = []
        self.redvypr_devices = {'redvypr_modules': {},'redvypr':{},'files':{}}
        self.redvypr_devices_flat = []
        self.__modules_scanned__ = []
        self.__modules_scanned__.append(redvypr) # Do not scan redvypr itself

        # Start scanning
        if scan:
            if scan_redvypr:
                if redvypr_devices is not None:
                    if isinstance(redvypr_devices,list):
                        for redvypr_device in redvypr_devices:
                            self.scan_redvypr(redvypr_device)
                    else:
                        self.scan_redvypr(redvypr_devices)

            if scan_modules:
                self.scan_modules()
            if scan_devicepath:
                self.scan_devicepath()


    def print_modules(self):
        for m in self.device_modules:
            print(m)


    def scan_devicepath(self):
        funcname = 'search_in_path():'
        self.logger.debug(funcname)
        self.device_modules = []  # Clear the list
        #
        # Add all devices from additionally folders
        #
        # https://docs.python.org/3/library/importlib.html#checking-if-a-module-can-be-imported
        for dpath in self.device_paths:
            python_files = glob.glob(dpath + "/*.py")
            self.logger.debug(funcname + 'Will search in path for files: {:s}'.format(dpath))
            for pfile in python_files:
                self.logger.debug(funcname + 'Opening {:s}'.format(pfile))
                module_name = pathlib.Path(pfile).stem
                spec = importlib.util.spec_from_file_location(module_name, pfile)
                module = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(module)
                except:
                    self.logger.warning(funcname + 'Could not import module: {:s}\n--------------------------------------------\n'.format(pfile))
                    self.logger.warning('Because',exc_info=True)
                    self.logger.warning(funcname + '\n--------------------------------------------\n')

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
                        self.logger.debug(funcname + 'Found device: {}'.format(module_name))
                else:
                    self.logger.debug(funcname + 'Not a valid device')

    def scan_module_recursive(self,testmodule, module_dict):
        funcname = 'scan_module_recursive():'
        self.logger.debug(funcname + ' Scanning: {}'.format(testmodule))
        #print(funcname,testmodule)
        # Check if the device is valid
        valid_module = self.valid_device(testmodule)
        #print('Valid dictionary',valid_module)
        if (valid_module['valid']):  # If the module is valid add it to devices
            # print('Members',inspect.getmembers(testmodule, inspect.ismodule))
            devdict = {'module': testmodule, 'name': testmodule.__name__, 'file': testmodule.__file__,'type':'module'}
            # module_dict[testmodule.__name__] = devdict
            try:
                module_dict['__devices__'].append(devdict)
            except:
                module_dict['__devices__'] = [devdict]

            self.redvypr_devices_flat.append(devdict)
            self.logger.debug(funcname + ' Found valid module {:s}'.format(str(testmodule)))
        # Always append as scanned
        self.__modules_scanned__.append(testmodule)

        # Checks if the module has a variable called redvypr_devicemodule
        if (valid_module['hasredvyprdevicemodule']):  # If the module is valid add it to devices
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

    def scan_redvypr(self, redvyprdevices):
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
                FLAG_POTENTIAL_MODULE = False

            if(FLAG_POTENTIAL_MODULE):
                #print('Found potential package',d.location, d.project_name, d.version, d.key)
                libstr2 = d.key.replace('-','_')  # Need to replace - with _, because - is not allowed in python
                try:
                    testmodule = importlib.import_module(libstr2)
                    device_module_all = inspect.getmembers(testmodule)
                    #print('Scan recursive start')
                    self.scan_module_recursive(testmodule,self.redvypr_devices['redvypr_modules'])
                    # Clean empty dictionaries

                except Exception as e:
                    #self.logger.info(funcname + ' Could not import module: ' + str(e))  # If the module is valid add it to devices
                    self.logger.debug('Could not import module', exc_info=True)


    def valid_device(self, devicemodule):
        """ Checks if the module is a valid redvypr module
        """
        funcname = 'valid_device(): '
        #self.logger.debug(funcname + 'Checking device {:s}'.format(str(devicemodule)))
        try:
            devicemodule.config_template
            hastemplate = True
        except:
            hastemplate = False

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

        try:
            devicemodule.redvypr_devicemodule
            hasredvyprdevicemodule = True
        except:
            hasredvyprdevicemodule = False

        devicecheck = {}
        devicecheck['valid'] = hasstart and hasredvyprdevicemodule
        devicecheck['hasdevice'] = hasdevice
        devicecheck['hasredvyprdevicemodule'] = hasredvyprdevicemodule
        devicecheck['hastemplate'] = hastemplate
        devicecheck['start'] = hasstart
        devicecheck['initgui'] = hasinitwidget
        devicecheck['displaygui'] = hasdisplaywidget

        return devicecheck


# TODO: properly implement status signal with status dict similar to thread_started/stopped
class RedvyprDevice(QtCore.QObject):
    thread_started = QtCore.pyqtSignal(dict)  # Signal notifying that the thread started
    thread_stopped = QtCore.pyqtSignal(dict)  # Signal notifying that the thread started
    status_signal  = QtCore.pyqtSignal(dict)   # Signal with the status of the device
    subscription_changed_signal = QtCore.pyqtSignal()  # Signal notifying that a subscription changed
    config_changed_signal = QtCore.pyqtSignal()  # Signal notifying that the configuration of the device has changed

    def __init__(self, device_parameter = None, redvypr=None, dataqueue=None, comqueue=None, datainqueue=None,
                 statusqueue=None, guiqueues=None, custom_config=None, statistics=None, startfunction=None):
        """
        """
        super(RedvyprDevice, self).__init__()
        self.publishes = device_parameter.publishes    # publishes data, a typical sensor is doing this
        self.subscribes = device_parameter.subscribes   # subscribes other devices data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue = dataqueue
        self.comqueue = comqueue
        self.statusqueue = statusqueue
        self.custom_config = custom_config
        self.distribute_data_replyqueue = queue.Queue(maxsize=500)
        self.redvypr = redvypr
        self.name = device_parameter.name
        self.devicemodulename = device_parameter.devicemodulename
        self.uuid = device_parameter.uuid
        self.guiqueues = guiqueues
        try:
            self.host_uuid = redvypr.hostinfo['uuid']
        except:
            self.host_uuid = ''
        self.thread_uuid = ''
        self.host = redvypr.hostinfo
        self.loglevel = device_parameter.loglevel
        self.numdevice = device_parameter.numdevice
        self.description = 'redvypr_device'
        self.statistics = statistics
        self.mp = device_parameter.multiprocess
        self.autostart = device_parameter.autostart
        self.thread = None
        self.device_parameter = device_parameter
        # Create a redvypr_address
        # self.address_str
        # self.address
        self.__update_address__()

        # Add myself a-priori to the statistics
        datapacket = create_datadict(device=self.name,
                                     #packetid=self.name,
                                     publisher=self.name,
                                     hostinfo=self.host)
        datapacket['_redvypr']['devicemodulename'] = self.devicemodulename
        do_data_statistics(datapacket, self.statistics)

        # Adding the start function (the function that is executed as a thread or multiprocess and is doing all the work!)
        if(startfunction is not None):
            self.start = startfunction

        # The queue that is used for the thread commmunication
        self.thread_communication = self.datainqueue

        self.subscribed_addresses = []
        
        self.logger = logging.getLogger('redvypr.' + self.name)
        self.logger.setLevel(device_parameter.loglevel)
        # Some placeholder attribute, that will be filled by redvypr_main_widget, if the gui is used
        self.deviceinitwidget = None
        self.devicedisplaywidget = None
        self.redvyprdevicewidget = None
        # Timer to ping the status of thread
        self.__stoptimer__ = QtCore.QTimer()
        self.__stoptimer__.timeout.connect(self.__check_thread_status)  # Add to the timer another update

    def add_guiqueue(self, widget=None):
        """
        Adds a guiqueue to the guiqueues list. The queue can be used internally to process and display the data that is
        sent, additionally also a widget can be added. The widget needs to provide a function .update_data.
        :param widget:
        :return: (Queue, widget)
        """
        if 'thread' in self.device_parameter.multiprocess:  # Thread or QThread
            guiqueue = queue.Queue(maxsize=queuesize)
        else: # multiprocess
            guiqueue = multiprocessing.Queue(maxsize=queuesize)

        newqueue = (guiqueue,widget)
        self.guiqueues.append(newqueue)
        return newqueue

    def __update_address__(self):
        # self.address_str = self.name + ':' + self.redvypr.hostinfo['hostname'] + '@' + self.redvypr.hostinfo[
        #    'addr'] + '::' + self.redvypr.hostinfo['uuid']
        # self.address = redvypr_address(self.address_str)
        self.address = RedvyprAddress(devicename=self.name, local_hostinfo=self.redvypr.hostinfo, publisher=self.name)
        self.address_str = self.address.get_str(address_format='/u/a/h/p/d/')

    def config_changed(self):
        """
        Function should be called when the configuration of the device has changed
        :return:
        """
        self.config_changed_signal.emit()
        # TODO: Status changed to be emmited as well

    def subscription_changed_global(self, devchange):
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
        addr = RedvyprAddress(datakey = datakey, devicename=self.name, local_hostinfo=self.redvypr.hostinfo)
        return addr

    def subscribe_address(self, address, force=False):
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
        if type(address) == str:
            raddr = RedvyprAddress(str(address))
        elif type(address) == RedvyprAddress:
            raddr = address
        else:
            raise TypeError('address needs to be a str or a redvypr_address')

        if len(raddr.address_str) == 0:
            raise ValueError('Address length is 0')

        FLAG_NEW = True
        # Test if the same address exists already
        for a in self.subscribed_addresses:
            if(a.address_str == raddr.address_str):
                FLAG_NEW = False
                break

        if(FLAG_NEW):
            self.subscribed_addresses.append(raddr)
            self.subscription_changed_signal.emit()
            #print(self.subscribed_addresses)
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
        #print('Address', address, type(address))
        if type(address) == str:
            raddr = RedvyprAddress(address)
        else:
            raddr = address

        try:
            self.subscribed_addresses.remove(raddr)
            self.subscription_changed_signal.emit()
        except Exception as e:
            self.logger.warning('Could not remove address {:s}: {:s}'.format(str(address),str(e)))

    def unsubscribe_all(self, exclude_metadata=True):
        """
        """
        funcname = self.__class__.__name__ + '.unsubscribe_all():'
        self.logger.debug(funcname + ' unsubscribing all')
        while len(self.subscribed_addresses) > 0:
            try:
                self.subscribed_addresses.pop(0)
            except Exception as e:
                self.logger.warning(funcname + 'Could not remove address')

        # Add the metadata again
        if exclude_metadata:
            self.subscribed_addresses.append(RedvyprAddress(metadata_address))

        self.subscription_changed_signal.emit()


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
        self.logger.warning('This changes only the device name but will not restart the thread.')

    def address_string(self, address_format='/u/a/h/p/d'):
        """
        Returns the address string of the device
        Returns:

        """
        astr = self.address.get_str(address_format = address_format)
        return astr

    def got_subscribed(self, dataprovider_address, datareceiver_address):
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


    def isRunning(self):
        info_dict = self.get_thread_status()
        return info_dict['thread_running']

    def get_thread_status(self):
        """

        Returns:

        """
        running = False
        running = self.thread_running()
        info_dict = {}
        info_dict['uuid'] = self.uuid
        info_dict['thread_uuid'] = self.thread_uuid
        info_dict['thread_running'] = running

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
        self.logger.debug(funcname + 'Type {}'.format(type(self.thread)))
        if self.thread is not None:
            if isinstance(self.thread, deviceQThread):
                self.logger.debug(funcname + ': Terminating now')
                self.thread.terminate()
            #elif(self.mp == 'multiprocess'):
            elif isinstance(self.thread, deviceQThread):
                self.logger.debug(funcname + ': Terminating now')
                self.thread.kill()
            elif isinstance(self.thread, threading.Thread):
                self.logger.debug(funcname + ': Cannot terminate a threading.Thread')
            else:
                self.logger.warning(funcname + ' Thread type no known')
        else:
            self.logger.warning(funcname + ' Device is not running')

    def thread_running(self):
        try: # thread/mulitprocess
            running = self.thread.is_alive()
        except:  # QThread
            try:
                running = self.thread.isRunning()
            except:
                running = False

        return running

    def thread_command(self, command, data=None):
        """
        Sends a command to the device thread
        Args:
            command: string, i.e. "stop"
            data: dictionary with additional data, the data will be incorporated into the command dict by executing command.update(data)

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

        if(self.thread_running()):
            #print('Sending command',command)
            self.__send_command__(command)
        else:
            self.logger.warning(funcname + ' thread is not running, doing nothing')

    def __check_thread_status(self):
        """
        Regular thread status thread to test of thread is already stopped. Emit signal if stopped
        :return:
        """
        self.__stop_checks -= 1
        running2 = self.thread_running()
        info_dict = {}
        info_dict['uuid'] = self.uuid
        info_dict['thread_running'] = running2
        # Thread is not running anymore, stop timer and sent signal
        if info_dict['thread_running'] == False:
            self.__stoptimer__.stop()
            self.thread_stopped.emit(info_dict)
        if self.__stop_checks < 0:
            self.logger.warning('Could not stop device, giving up')
            self.__stoptimer__.stop()

    def thread_stop(self):
        """
        Sends a stop command to the thread_communication queue
        Returns:

        """
        funcname = __name__ + '.thread_stop():'
        self.logger.debug(funcname)
        command = commandpacket(command='stop', device_uuid=self.uuid,thread_uuid=self.thread_uuid)
        #print('Sending command',command)
        running = self.thread_running()
        if(running):
            self.__stoptimer__.stop()
            self.__stop_checks = 10 # Number of checks of stopped
            self.__send_command__(command)
            # Start a timer and check if the thread was stopped
            self.__stoptimer__.start(250)
        else:
            self.logger.warning(funcname + ' thread is not running, doing nothing')

    def thread_start(self, config=None):
        """ Starts the device thread, it calls the self.start function with the arguments

        start(self, device_info, config, dataqueue, datainqueue, statusqueue)

        config is a deepcopy of self.config: config = copy.deepcopy(self.config). The deepcopy converts the
        configuration dictionary into an ordinary dictionary "forgetting" additional information and making the
        configuration hashable as it is needed for a multiprocess.

        Args:
            config [default=None]: confuguration dictionary, if none a deepcopy of self.config is used, otherwise config


        """
        funcname = __name__ + '.thread_start():'

        #logger.debug(funcname + 'Starting device: ' + str(device.name))
        self.logger.debug(funcname + 'Starting device: ' + str(self.name))
        sendict = {}#self.__sendict__
        # Find the right thread to start
        if True:
            if True:
                running = self.thread_running()
                if running:
                    self.logger.warning(funcname + ':thread/process is already running, doing nothing')
                else:
                    try:
                        # The arguments for the start function
                        thread_uuid = 'thread_' + str(uuid.uuid1())
                        device_info = {'device':self.name,'uuid':self.uuid,'thread_uuid':thread_uuid,'hostinfo':self.redvypr.hostinfo,'address_str':self.address_str}
                        if config is None:
                            self.logger.debug('Using internal configuration')
                            self.logger.debug('Pydantic configuration')
                            try:
                                config = self.custom_config.model_dump()
                            except:
                                self.logger.debug(funcname + 'Could not dump model: {}'.format(self.custom_config), exc_info=True)
                                raise ValueError('Could not dump custom model config')
                        else:
                            self.logger.debug('Using external configuration')

                        if self.device_parameter.clear_datainqueue_before_thread_starts:
                            while self.datainqueue.empty() == False:
                                try:
                                    data = self.datainqueue.get(block=False)
                                except:
                                    break
                        args = (device_info, config, self.dataqueue, self.datainqueue, self.statusqueue)
                        if self.mp == 'qthread':
                            self.thread = deviceQThread(startfunction=self.start,start_arguments=args)
                        #elif self.mp == 'thread':
                        #    self.logger.info(funcname + 'Starting as thread')
                        #    self.thread = threading.Thread(target=self.start, args=args, daemon=True)
                        else:
                            self.logger.info(funcname + 'Starting as process')
                            self.thread = multiprocessing.Process(target=self.start, args=args)

                            #self.logger.info(funcname + 'started {:s} as process with PID {:d}'.format(self.name, self.thread.pid))

                        self.thread.start()

                        sendict['thread'] = self.thread
                        self.logger.info(funcname + 'started {:s}'.format(self.name))
                        # Update the device and the devicewidgets about the thread status
                        running2 = self.thread_running()


                        try: # If the device has a thread_status function
                            self.thread_status({'threadalive':running2})
                        except:
                            pass

                        self.thread_uuid = thread_uuid
                        # Sending metadata
                        compacket = self.redvypr.get_metadata_commandpacket()
                        for addr in self.subscribed_addresses:
                            if compacket in addr:
                                self.datainqueue.put(compacket)

                        info_dict = {}
                        info_dict['uuid'] = self.uuid
                        info_dict['thread_uuid'] = thread_uuid
                        info_dict['thread_running'] = running2
                        self.thread_started.emit(info_dict)  # Notify about the started thread

                        return self.thread

                    except Exception:
                        self.logger.warning(funcname + 'Could not start thread.',exc_info=True)

                        return None

    def __str__(self):
        return self.description
    
    def finalize_init(self):
        """
        Dummy function, can be defined by the user. Function is called after the device is added to redvypr.

        Returns:

        """
        pass


    def get_hosts(self):
        """
        Returns:
            List of redvypr host instances this device has been seen
        """
        hosts = []
        devs = self.get_deviceaddresses()
        for d in devs:
            hosts.append(d.hostname)

        hosts = list(set(hosts))
        hosts.sort()
        return hosts


    def get_deviceaddresses(self, local=None):
        """
        Returns a list with RedvyprAddresses of all data devices that publish data via this device. This is in many cases
        the device itself but can also forwarded devices (i.e. iored) or because the device publishes data with different

        Args:
            local: True for local devices only, False for remote devices only, None for both

        Returns:
            List of redvypr_address

        """
        addr_str = list(self.statistics['device_redvypr'].keys())
        addr_list = []
        for a in addr_str:
            raddr = RedvyprAddress(a)
            if local is None:
                addr_list.append(raddr)
            else: # Check if we have a local or remote address
                raddr_local = raddr.uuid == self.host_uuid
                if local == raddr_local:
                    addr_list.append(raddr)

        return addr_list

    def get_datakeys(self, local=None):
        """
        Returns a list of all datakeys this device is providing
        Returns:
            List of datakeys (str)
        """
        devaddrs = self.get_deviceaddresses(local)
        datakeys = []
        for devaddr in devaddrs:
            dkeys = self.statistics['device_redvypr'][devaddr.address_str]['datakeys']
            datakeys.extend(dkeys)

        # Sort the datakeys and make them unique
        datakeys = list(set(datakeys))
        datakeys.sort()
        return datakeys

    def get_datastreams(self,local=None):
        """
        Returns a list of all datastreams this device is providing
        Returns:
            List of datastreams (str)
        """
        devaddrs = self.get_deviceaddresses(local)
        datastreams = []
        for devaddr in devaddrs:
            dkeys = self.statistics['device_redvypr'][devaddr.address_str]['datakeys']
            for dkey in dkeys:
                raddr = RedvyprAddress(devaddr, datakey=dkey)
                dstr = raddr.get_str()
                datastreams.append(dstr)


        return datastreams

    def get_packetids(self):
        """
        Returns a list of all packetids this device has seen
        Returns:
            List of packetids (str)
        """
        devaddrs = self.get_deviceaddresses()
        packetids = []
        for devaddr in devaddrs:
            if len(devaddr.packetid)>0:
                packetids.append(devaddr.packetid)

        # Sort the datakeys and make them unique
        packetids = list(set(packetids))
        packetids.sort()
        return packetids

    def get_device_info(self, address=None):
        """
        Returns a deepcopy that is saved in self.statistics['device_redvypr'] containing information about all devices
        that have been published through this device.
        Note: name was def get_data_provider_info(self):

        Returns:
            Dictionary with the device address (str) as key

        """
        if address is None:
            d = copy.deepcopy(self.statistics['device_redvypr'])
            return d
        else:
            if type(address) == str:
                raddr = RedvyprAddress(address)
                dtmp = copy.deepcopy(self.statistics['device_redvypr'])
                for a in dtmp.keys():
                    if a in raddr:
                        d = dtmp[a]
                        return d


    def publishing_to(self):
        """

        Returns:
            List of redvypr_device this device is publishing to
        """
        funcname = __name__ + '.publishing_to()'
        #self.logger.debug(funcname)
        devs = self.redvypr.get_device_objects()
        devs_publishing_to = []
        for dev in reversed(devs):
            for subaddr in dev.subscribed_addresses:
                daddr = RedvyprAddress(subaddr)
                if (self.address in daddr) and (dev is not self):
                    devs_publishing_to.append(dev)
                    break

        return devs_publishing_to

    def get_subscribed_datastreams(self):
        """

        Returns:
            All datastreams of the subscribed devices

        """
        funcname = __name__ + '.get_subscribed_datastreams()'
        datastreams = []
        devs = self.redvypr.get_device_objects()
        for subaddr in self.subscribed_addresses:
            for dev in reversed(devs):
                datastreams_dev = dev.get_datastreams()
                for d in datastreams_dev:
                    daddr = RedvyprAddress(d)
                    if (subaddr in daddr) and (dev is not self):
                        datastreams.append(d)

        return datastreams

    def get_subscribed_devices(self):
        """
        Returns all redvypr_device this device is subscribed to.

        Returns:
             List with redvypr_device

        """
        funcname = __name__ + '.get_subscribed_devices()'
        #self.logger.debug(funcname)
        devs = self.redvypr.get_device_objects()
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
        returns the existing devices that provide data to this device, in self.subscribed_addresses also regular expressions can exist.

        Returns:
            List of redvypr_address

        """
        funcname = __name__ + '.get_subscribed_deviceaddresses()'
        subaddresses = []
        raddresses = self.redvypr.get_deviceaddresses()

        #print(' A raddresses', raddresses)
        #print(' B subscribed addresses',self.subscribed_addresses)
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

    def get_metadata_datakey(self, address, all_entries=True):
        """
        Returns the metadata of the redvypr address
        """
        funcname = self.__class__.__name__ + '.get_metadata_datakey():'
        self.logger.debug(funcname)
        if isinstance(address,str):
            daddr = redvypr.RedvyprAddress(address)
        else:
            daddr = address

        # d = copy.deepcopy(self.statistics['device_redvypr'])
        devinfo_all = copy.deepcopy(self.redvypr.deviceinfo_all)
        # print('Datastream',datastream,daddr)
        datakeyinfo = {}
        for hostdevice in devinfo_all:
            d = devinfo_all[hostdevice]
            for device in d:
                # Check first if an ordinary datakey is given, or an eval string to access subunits
                if daddr.datakeyeval == False: # Standard datakey
                    for dkey in d[device]['_keyinfo'].keys():
                        dstreamaddr_info = redvypr.RedvyprAddress(device, datakey=dkey)
                        # print('dstreamddr_info',dstreamaddr_info)
                        if daddr in dstreamaddr_info:
                            try:
                                datakeyinfo[dstreamaddr_info.get_str()].update(d[device]['_keyinfo'][dkey])
                            except:
                                datakeyinfo[dstreamaddr_info.get_str()] = d[device]['_keyinfo'][dkey]
                else: # Eval string, here things have to be done manually.
                    self.logger.debug(funcname + 'Found an eval string, searching for matching patterns')
                    # Split the evalstring into pieces separated by [] brackets and remove them subsequently until something was found
                    datakey_pieces = re.findall(r"\[.*?\]", daddr.datakey)
                    datakey_pieces_cumsum = []
                    for ipiece,piece in enumerate(datakey_pieces):
                        dtmp = ''
                        for ipiece2 in range(0,ipiece+1):
                            dtmp += datakey_pieces[ipiece2]

                        datakey_pieces_cumsum.append(dtmp)

                    datakey_pieces_cumsum.reverse()
                    #print('datakey pieces', datakey_pieces)
                    #print('datakey pieces cumsum', datakey_pieces_cumsum)
                    #for dkey in d[device]['_keyinfo'].keys():
                    if True:
                        #print('Daddr',daddr,daddr.datakey)
                        #print('key',dkey,daddr in dstreamaddr_info)
                        #print('Keyinfo',d[device]['_keyinfo'])
                        for keyeval in datakey_pieces_cumsum:
                            evalstr = '''d[device]['_keyinfo']''' + keyeval
                            #print('Evalstr',evalstr)
                            #print(d[device]['_keyinfo'])
                            try:
                                keyinfo = eval(evalstr,None)
                                dstreamaddr_info = redvypr.RedvyprAddress(device, datakey=keyeval)
                                #print('dstreamddr_info', dstreamaddr_info)
                                #print('Found something',keyinfo)
                                try:
                                    datakeyinfo[dstreamaddr_info.get_str()].update(keyinfo)
                                except:
                                    datakeyinfo[dstreamaddr_info.get_str()] = keyinfo
                                break
                            except:
                                #self.logger.info('Eval did not work',exc_info=True)
                                keyinfo = None

                        #print('Keyinfo',keyinfo)

        # Either return the first entry or all
        if all_entries == False:
            k = list(datakeyinfo.keys())
            if len(k) == 0:
                datakeyinfo = None
            else:
                datakeyinfo = datakeyinfo[k[0]]

            #print('Returning for address', address)
            #print('Returning datakeyinfo',datakeyinfo)
            return datakeyinfo
        else:
            return datakeyinfo

    def get_datakeyinfo_legacy(self,datastream):
        """
        Returns the datakeyinfo for the datastream

        Args:
            datastream:
            first_match:

        Returns:

        """
        funcname = self.__class__.__name__ + '.get_datakeyinfo()'
        self.logger.debug(funcname)
        daddr = redvypr.RedvyprAddress(datastream)
        #d = copy.deepcopy(self.statistics['device_redvypr'])
        devinfo_all = copy.deepcopy(self.redvypr.deviceinfo_all)
        #print('Datastream',datastream,daddr)
        datakeyinfo = {}
        for hostdevice in devinfo_all:
            d = devinfo_all[hostdevice]
            for device in d:
                for dkey in d[device]['_keyinfo'].keys():
                    dstreamaddr_info = redvypr.RedvyprAddress(device, datakey = dkey)
                    #print('dstreamddr_info',dstreamaddr_info)
                    if daddr in dstreamaddr_info:
                        try:
                            datakeyinfo[dstreamaddr_info.get_str()].update(d[device]['_keyinfo'][dkey])
                        except:
                            datakeyinfo[dstreamaddr_info.get_str()] = d[device]['_keyinfo'][dkey]

        return datakeyinfo

    def get_datastream_keyinfo_legacy(self, datastream):
        """
        Returns the datakeyinfo for the datastream

        Args:
            datastream:
            first_match:

        Returns:

        """
        funcname = self.__class__.__name__ + '.get_datastream_keyinfo()'
        self.logger.debug(funcname)
        daddr = redvypr.RedvyprAddress(datastream)
        d = copy.deepcopy(self.statistics['device_redvypr'])
        # print('Datastream',datastream,daddr)
        for device in d:
            for dkey in d[device]['_keyinfo'].keys():
                dstreamaddr_info = redvypr.RedvyprAddress(device, datakey=dkey)
                # print('dstreamddr_info',dstreamaddr_info)
                if daddr in dstreamaddr_info:
                    return d[device]['_keyinfo'][dkey]

        return None

    def get_config(self):
        """
        Returns a RedvyprDeviceConfig of the device
        """
        funcname = __name__ + '.get_config():'
        self.logger.debug(funcname)
        # Treat subscriptions
        subscriptions = []
        for raddr in self.subscribed_addresses:
            subscriptions.append(raddr.address_str)
        base_config = RedvyprDeviceBaseConfig(**self.device_parameter.model_dump())
        try:
            custom_config_dict = self.custom_config.model_dump()
        except:
            self.logger.debug(funcname + 'Could not create a dump of custom config', exc_info=True)
            custom_config_dict = None
        config = RedvyprDeviceConfig(base_config=base_config, custom_config=custom_config_dict,
                                     devicemodulename=self.devicemodulename, subscriptions=subscriptions)

        self.logger.debug(funcname + 'Config: {}'.format(config))
        return config

    def get_status(self):
        statusstr = 'Status'
        return statusstr

    def get_info(self):
        """
        Returns a dictionary with the essential info of the device
        Returns:

        """
        info_dict = {}
        info_dict['uuid'] = self.uuid
        info_dict['name'] = self.name

        return info_dict


    def get_metadata(self, address, mode='merge', local_statistics_only=False):
        """
        Gets the metadata of the redvypr address

        Parameters
        ----------
        address: RedvyprAddress
        mode:
        local_statistics_only: If true use the local statistics of the datastreams only, otherwise ue the global statistics of redvypr

        Returns
        -------

        """

        funcname = __name__ + '.get_metadata({},{}):'.format(str(address),str(mode))
        self.logger.debug(funcname)
        if local_statistics_only:
            metadata = redvypr.packet_statistic.get_metadata(self.statistics,address,mode=mode)
        else:
            metadata = self.redvypr.get_metadata(self.statistics,address,mode=mode)

        return metadata

    def set_metadata(self, address, metadata):
        """
        Sets the metadata of address.
        :param address:
        :param metadata:
        :return:
        """
        funcname = __name__ + '.set_metadata():'
        self.logger.debug(funcname)
        address_str = RedvyprAddress(address).address_str
        datapacket = redvypr.data_packets.commandpacket(command='reply')
        datapacket['_metadata'] = {}
        datapacket['_metadata'][address_str] = metadata
        self.dataqueue.put(datapacket)
        data = self.distribute_data_replyqueue.get()
        self.logger.debug(funcname + 'Metadata sent')

    def set_metadata_entry(self, address, metadata_key='unit', metadata_entry=None):
        """
        Convenience function to set one entry of the metadata of a redvypr address
        :param address:
        :param metadata_key:
        :param metadata_entry:
        :return:
        """
        funcname = __name__ + '.set_metadata_entry():'
        self.logger.debug(funcname)
        metadata = {}
        metadata[metadata_key:metadata_entry]
        self.set_metadata(address,metadata)

    def print_info(self):
        """ Displays information about the device

        """
        print('get_info():')
        print('Name' + self.name)
        print('redvypr' + self.redvypr)

    def __str__(self):
        return 'redvypr_device (' + self.devicemodulename + ') ' + self.address_string()

