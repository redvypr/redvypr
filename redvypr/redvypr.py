import copy
import os
import time
import datetime
import logging
import queue
import sys
import yaml
import pkg_resources
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np
import inspect
import threading
import multiprocessing
import socket
import argparse
import importlib.util
import glob
import pathlib
import signal
import uuid
import random
from pyqtconsole.console import PythonConsole
from pyqtconsole.highlighter import format
import platform
# Import redvypr specific stuff

import redvypr.devices as redvyprdevices
import redvypr.data_packets as data_packets
from redvypr.gui import redvypr_ip_widget, redvyprConnectWidget, QPlainTextEditLogger, displayDeviceWidget_standard, \
    deviceinfoWidget, datastreamWidget, redvypr_deviceInitWidget, redvypr_deviceInfoWidget
import redvypr.gui as gui
from redvypr.utils import addrm_device_as_data_provider, get_data_receiving_devices, get_data_providing_devices#, configtemplate_to_dict, apply_config_to_dict
from redvypr.config import configuration
from redvypr.version import version
import redvypr.files as files
from redvypr.device import redvypr_device
import faulthandler
faulthandler.enable()

# Platform information str
__platform__ = "redvypr (REaltime Data Vi(Y)ewer and PRocessor (in Python))\n"
__platform__ += "\n\n"
__platform__ += "Version: {:s}\n".format(str(version))
__platform__ += "Python: {:s}\n".format(sys.version)
__platform__ += "Platform system: {:s}\n".format(platform.system())
__platform__ += "Platform release: {:s}\n".format(platform.release())
__platform__ += "Platform version: {:s}\n".format(platform.version())

# Windows icon fix
# https://stackoverflow.com/questions/1551605/how-to-set-applications-taskbar-icon-in-windows-7/1552105#1552105
import ctypes

myappid = u'redvypr.redvypr.version'  # arbitrary string
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except:
    pass

_logo_file = files.logo_file
_icon_file = files.icon_file

# The maximum size the dataqueues have, this should be more than
# enough for a "normal" usage case
queuesize = 10000
# queuesize = 10

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr')
logger.setLevel(logging.INFO)


# https://stackoverflow.com/questions/166506/finding-local-ip-addresses-using-pythons-stdlib
def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


# The hostinfo, to distinguish between different redvypr instances
# redvyprid = str(uuid.uuid1()) # Old

def create_hostinfo(hostname='redvypr'):
    funcname = __name__ + '.create_hostinfo()'
    logger.debug(funcname)
    randstr = '{:03d}'.format(random.randrange(2 ** 8))
    #redvyprid = datetime.datetime.now().strftime('%Y%m%d%H%M%S.%f-') + str(uuid.getnode()) + '-' + randstr
    redvyprid = str(uuid.getnode()) + '-' + randstr
    hostinfo = {'hostname': hostname, 'tstart': time.time(), 'addr': get_ip(), 'uuid': redvyprid, 'local': True}
    return hostinfo




def distribute_data(devices, hostinfo, deviceinfo_all, infoqueue, dt=0.01):
    """ The heart of redvypr, this functions distributes the queue data onto the subqueues.
    """
    funcname = __name__ + '.distribute_data()'
    datastreams_all = {}
    datastreams_all_old = {}
    dt_info = 1.0  # The time interval information will be sent
    dt_avg = 0  # Averaging of the distribution time needed
    navg = 0
    tinfo = time.time()
    tstop = time.time()
    dt_sleep = dt


    while True:
        time.sleep(dt_sleep)
        tstart = time.time()
        FLAG_device_status_changed = False
        devices_changed = []
        for devicedict in devices:
            device = devicedict['device']
            data_all = []
            tread = time.time()
            # Read all packets in a bunch
            while True:
                try:
                    data = device.dataqueue.get(block=False)
                    if(type(data) is not dict): # If data is not a dictionary, convert it to one
                        data = {'data':data}

                    devicedict['numpacket'] += 1
                    data_all.append(data)
                except Exception as e:
                    break
            # Process read packets
            for data in data_all:
                #
                # Add additional information, if not present yet
                data_packets.treat_datadict(data, device.name, hostinfo, devicedict['numpacket'], tread,devicedict['devicemodulename'])
                #
                # Do statistics
                try:
                    if devicedict['statistics']['inspect']:
                        devicedict['statistics'] = data_packets.do_data_statistics(data, devicedict['statistics'])
                except Exception as e:
                    logger.exception(e)
                    logger.debug(funcname + ':Statistics:' + str(e))

                #
                # Check for a command packet
                #
                [command, comdata] = data_packets.check_for_command(data, add_data=True)
                if (command == 'device_status'):  # status update
                    try:
                        devaddr   = comdata['data']['deviceaddr']
                        devstatus = comdata['data']['devicestatus']
                    except:
                        devaddr = None
                        devstatus = None
                        pass
                    devices_changed.append(device.name)
                    try: # Update the device
                        devicedict['statistics']['device_redvypr'][devaddr]['_redvypr'].update(devstatus)
                    except Exception as e:
                        logger.warning('Could not update status ' + str(e))
                        logger.exception(e)

                    FLAG_device_status_changed = True

                #
                # Create a dictionary of all datastreams
                #
                datastreams_all.update(devicedict['statistics']['datastream_redvypr'])
                try:
                    deviceinfo_all[device.name].update(devicedict['statistics']['device_redvypr'])
                except:
                    deviceinfo_all[device.name] = devicedict['statistics']['device_redvypr']

                if (list(datastreams_all.keys()) != list(datastreams_all_old.keys())):
                    #print('Datastreams changed', len(datastreams_all.keys()))
                    datastreams_all_old.update(datastreams_all)
                    devices_changed.append(device.name)
                    FLAG_device_status_changed = True
                #
                # And finally: Distribute the data
                #
                for devicedict_sub in devices:
                    devicesub = devicedict_sub['device']
                    if(devicesub == device):
                        continue

                    for addr in devicesub.subscribed_addresses:
                        if data in addr: # Check if data packet fits with addr
                            devicedict['numpacketout'] += 1
                            try:
                                devicesub.datainqueue.put_nowait(data) # These are the datainqueues of the subscribing devices
                                break
                            except Exception as e:
                                logger.debug(funcname + ':dataout of :' + devicedict['device'].name + ' full: ' + str(e))

                # The gui of the device
                for guiqueue in devicedict['guiqueue']:  # Put data into the guiqueue, this queue does always exist
                    try:
                        guiqueue.put_nowait(data)
                    except Exception as e:
                        pass
                        # logger.debug(funcname + ':guiqueue of :' + devicedict['device'].name + ' full')

        if FLAG_device_status_changed:
            infoqueue.put_nowait(copy.copy(datastreams_all))
            devall = copy.copy(deviceinfo_all)
            devall['type'] = 'deviceinfo_all'
            infoqueue.put_nowait(devall)
            # Send a command to all devices with the notification that something changed
            for devicedict in devices:
                dev = devicedict['device']
                dev.thread_command('deviceinfo_all', {'deviceinfo_all':deviceinfo_all,'devices_changed':list(set(devices_changed))})

        # Calculate the sleeping time
        tstop = time.time()
        dt_dist = tstop - tstart  # The time for all the looping
        dt_avg += dt_dist
        navg += 1
        dt_sleep = max([0, dt - dt_dist])
        if ((tstop - tinfo) > dt_info):
            tinfo = tstop
            info_dict = {'type':'dt_avg','dt_avg': dt_avg / navg}
            # print(info_dict)
            try:
                infoqueue.put_nowait(info_dict)
            except:
                pass


class redvypr(QtCore.QObject):
    """This is the redvypr heart. Here devices are added/threads
    are started and data is interchanged

    """
    device_path_changed        = QtCore.pyqtSignal()  # Signal notifying if the device path was changed
    device_added               = QtCore.pyqtSignal(list)  # Signal notifying if the device path was changed
    devices_connected          = QtCore.pyqtSignal(str, str)  # Signal notifying if two devices were connected
    devices_disconnected       = QtCore.pyqtSignal(str, str)  # Signal notifying if two devices were connected
    status_update_signal       = QtCore.pyqtSignal()  # Signal notifying if the status of redvypr has been changed
    device_status_changed_signal = QtCore.pyqtSignal()  # Signal notifying if datastreams have been added

    def __init__(self, parent=None, config=None, hostname='redvypr',hostinfo_opt = {}, nogui=False):
        # super(redvypr, self).__init__(parent)
        super(redvypr, self).__init__()
        print(__platform__)
        funcname = __name__ + '.__init__()'
        logger.debug(funcname)
        self.hostinfo = create_hostinfo(hostname=hostname)
        config_template = {'template_name':'hostinfo_opt','name':'hostinfo_opt'}
        self.hostinfo_opt = configuration(config=hostinfo_opt,template=config_template) # Optional host information
        self.config = {}  # Might be overwritten by parse_configuration()
        self.properties = {}  # Properties that are distributed with the device
        self.numdevice = 0
        self.devices = []  # List containing dictionaries with information about all attached devices
        self.device_paths = []  # A list of pathes to be searched for devices
        self.device_modules = []
        self.datastreams_dict = {} # Information about all datastreams, this is updated by distribute data
        self.deviceinfo_all   = {} # Information about all devices, this is updated by distribute data

        ## A timer to check the status of all threads
        self.devicethreadtimer = QtCore.QTimer()
        self.devicethreadtimer.start(250)
        self.devicethreadtimer.timeout.connect(self.update_status)  # Add to the timer another update

        ## A timer to print the status in the nogui environment
        if (nogui):
            self.statustimer = QtCore.QTimer()
            self.statustimer.timeout.connect(self.print_status)
            self.statustimer.start(5000)

        self.dt_datadist = 0.01  # The time interval of datadistribution
        self.dt_avg_datadist = 0.00  # The time interval of datadistribution
        self.datadistinfoqueue = queue.Queue(maxsize=1000)  # A queue to get informations from the datadistribution
        # Lets start the distribution!
        self.datadistthread = threading.Thread(target=distribute_data, args=(
        self.devices, self.hostinfo, self.deviceinfo_all, self.datadistinfoqueue, self.dt_datadist), daemon=True)
        self.datadistthread.start()
        logger.info(funcname + ':Searching for devices')
        self.populate_device_path()
        logger.info(funcname + ':Done searching for devices')

        # Configurating redvypr
        if (config is not None):
            logger.debug(funcname + ':Configuration: ' + str(config))
            if (type(config) == str):
                config = [config]

            for c in config:
                logger.debug(funcname + ':Parsing configuration: ' + str(c))
                self.parse_configuration(c)

    def get_deviceinfo(self,publish=None,subscribe=None):
        """

        Args:
            publish:
            subscribe:

        Returns:
            A dictionary containing the deviceinfo of all devices seen by this redvypr instance
        """
        if (publish == None) and (subscribe == None):
            return copy.deepcopy(self.deviceinfo_all)
        else:
            dinfo = {}
            for d in self.devices:
                dev = d['device']
                FLAG_publish   =   (publish == dev.publish) or (publish == None)
                FLAG_subscribe = (subscribe == dev.subscribe) or (subscribe == None)
                if FLAG_publish and FLAG_subscribe:
                    dinfo[dev.name] = copy.deepcopy(dev.statistics['device_redvypr'])

            return dinfo

    def update_status(self):
        while True:
            try: # Reading data coming from distribute_data thread
                data = self.datadistinfoqueue.get(block=False)
                #print('Got data',data)
                if('dt_avg' in data['type']):
                    self.dt_avg_datadist = data['dt_avg']
                    self.status_update_signal.emit()
                elif ('deviceinfo_all' in data['type']):
                    data.pop('type')  # Remove the type key
                    #print('datastreams changed', data)
                    self.device_status_changed_signal.emit()

            except Exception as e:
                #logger.exception(e)
                break

    def print_status(self):
        funcname = __name__ + '.print_status():'
        logger.debug(funcname + self.status())

    def status(self):
        """ Creates a statusstr of the devices
        """
        tstr = str(datetime.datetime.now())
        statusstr = "{:s}, {:s}, num devices {:d}".format(tstr, self.hostinfo['hostname'], len(self.devices))

        for sendict in self.devices:
            status = sendict['device'].get_thread_status()
            #info_dict['uuid'] = self.uuid
            #info_dict['thread_uuid'] = self.thread_uuid
            #info_dict['thread_status'] = running
            if(status['thread_status']):
                runstr = 'running'
            else:
                runstr = 'stopped'

            statusstr += '\n\t' + sendict['device'].name + ':' + runstr + ': data packets: {:d}'.format(
                sendict['numpacket'])
            # statusstr += ': data packets received: {:d}'.format(sendict['numpacketout'])

        return statusstr

    def get_config(self):
        """
        Creates a configuration dictionary out of the current state.

        Returns:
            config: configuration dictionary

        """
        config = {}

        config['hostname'] = self.hostinfo['hostname']
        config['devicepath'] = []
        for p in self.device_paths:
            config['devicepath'].append(p)
        # Loglevel
        config['loglevel'] = logger.level
        # Devices
        config['devices'] = []
        for devicedict in self.devices:
            device = devicedict['device']
            devsave = {'deviceconfig':{}}
            devsave['deviceconfig']['name']     = device.name
            devsave['deviceconfig']['loglevel'] = device.loglevel
            devsave['deviceconfig']['autostart']= device.autostart
            devsave['devicemodulename']         = devicedict['devicemodulename']
            devconfig = device.config
            devsave['deviceconfig']['config'] = copy.deepcopy(devconfig)
            config['devices'].append(devsave)

        # Connections
        config['connections'] = []
        for devicedict in self.devices:
            device = devicedict['device']
            sensprov = get_data_providing_devices(self.devices, device)
            for prov in sensprov:
                condict = {'publish':prov['device'].name,'receive':device.name}
                config['connections'].append(condict)
            #sensreicv = get_data_receiving_devices(self.devices, device)
            #print('Provider',sensprov)
            #print('Receiver', sensreicv)

        return config

    def parse_configuration(self, configfile=None):
        """ Parses a dictionary with a configuration, if the file does not exists it will return with false, otherwise self.config will be updated

        Arguments:
            configfile (str or dict):
        Returns:
            True or False
        """
        funcname = "parse_configuration()"
        parsed_devices = []
        logger.debug(funcname)
        if (type(configfile) == str):
            logger.info(funcname + ':Opening yaml file: ' + str(configfile))
            if (os.path.exists(configfile)):
                fconfig = open(configfile)
                config = yaml.load(fconfig, Loader=yaml.loader.SafeLoader)
            else:
                logger.warning(funcname + ':Yaml file: ' + str(configfile) + ' does not exist!')
                return False
        elif(type(configfile) == dict):
            logger.info(funcname + ':Opening dictionary')
            config = configfile
        else:
            logger.warning(funcname + ':This should not happen')

        self.config = config
        if ('loglevel' in config.keys()):
            logger.setLevel(config['loglevel'])
        # Add device path if found
        if ('devicepath' in config.keys()):
            devpath = config['devicepath']

            if (type(devpath) == str):
                devpath = [devpath]

            for p in devpath:
                if (p not in self.device_paths):
                    self.device_paths.append(p)

            self.populate_device_path()
            self.device_path_changed.emit()  # Notify about the changes

        # Adding the devices found in the config ['devices']
        # Check if we have a list or something
        try:
            iter(config['devices'])
            hasdevices = True
        except:
            hasdevices = False
        if (hasdevices):
            for device in config['devices']:
                try:
                    device['deviceconfig']
                except:
                    device['deviceconfig'] = {}

                dev_added = self.add_device(devicemodulename=device['devicemodulename'], deviceconfig=device['deviceconfig'])
                parsed_devices.append(dev_added)

        # Connecting devices ['connections']
        # TODO, this needs to be changed to subscritpions
        # TODO
        # TODO
        try:
            iter(config['connections'])
            hascons = True
        except:
            hascons = False
        if (hascons):
            logger.debug('Connecting devices')
            for con in config['connections']:
                logger.debug('Connecting devices:' + str(con))
                devicenameprovider = con['publish']
                devicenamereceiver = con['receive']
                indprovider = -1
                indreceiver = -1
                for i, s in enumerate(self.devices):
                    if s['device'].name == devicenameprovider:
                        deviceprovider = s['device']
                        indprovider = i
                    if s['device'].name == devicenamereceiver:
                        devicereceiver = s['device']
                        indreceiver = i

                if ((indprovider > -1) and (indreceiver > -1)):
                    self.addrm_device_as_data_provider(deviceprovider, devicereceiver, remove=False)
                    sensprov = get_data_providing_devices(self.devices, devicereceiver)
                    sensreicv = get_data_receiving_devices(self.devices, deviceprovider)
                else:
                    logger.warning(
                        funcname + ':Could not create connection for devices: {:s} and {:s}'.format(devicenameprovider,
                                                                                                    devicenamereceiver))

        # Add the hostname
        try:
            logger.info(funcname + ': Setting hostname to {:s}'.format(config['hostname']))
            self.hostinfo['hostname'] = config['hostname']
        except:
            pass

        # Autostart the device, if wanted
        #for dev in parsed_devices:
        #    device = dev[0]['device']
        #    if(device.autostart):
        #        device.thread_start()

        return True

    def __populate_device_path_packages(self,package_names = ['vypr','vyper']):
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

        funcname = '__populate_device_path_packages()'
        logger.debug(funcname)
        for d in pkg_resources.working_set:
            FLAG_POTENTIAL_MODULE = False
            #print(d.key)
            for name in package_names:
                if name in d.key:
                    FLAG_POTENTIAL_MODULE = True
                    #print('maybe',d.key)
            if d.key == 'redvypr':
                #print('its me')
                FLAG_POTENTIAL_MODULE = False

            if(FLAG_POTENTIAL_MODULE):
                print('Found package',d.location, d.project_name, d.version, d.key)
                libstr2 = d.key.replace('-','_')

                try:
                    testmodule = importlib.import_module(libstr2)
                    device_module_tmp = inspect.getmembers(testmodule, inspect.ismodule)
                    for smod in device_module_tmp:
                        devicemodule = getattr(testmodule, smod[0])
                        # Check if the device is valid
                        valid_module = self.valid_device(devicemodule)
                        if (valid_module['valid']):  # If the module is valid add it to devices
                            devdict = {'module': devicemodule, 'name': smod[0], 'source': smod[1].__file__}
                            # Test if the module is already there, otherwise append
                            FLAG_MOD_APPEND = True
                            for m in self.device_modules:
                                if m['module'] == devicemodule:
                                    FLAG_MOD_APPEND = False
                                    break
                            if (FLAG_MOD_APPEND):
                                logger.debug(funcname + ' Found device package {:s}'.format(libstr2))
                                self.device_modules.append(devdict)
                except Exception as e:
                    logger.info(funcname + ' Could not import module: ' + str(e))

    def populate_device_path(self):
        """
        Updates self.device_modules with dictionaries of type
        devdict = {'module': module, 'name': module_name, 'source': module.__file__}
        with module the imported module with module_name at the location __file__.
        Returns:
            None

        """
        funcname = 'populate_device_path()'
        logger.debug(funcname)
        self.device_modules = []  # Clear the list
        #
        # Add all devices from additionally folders
        #
        # https://docs.python.org/3/library/importlib.html#checking-if-a-module-can-be-imported
        for dpath in self.device_paths:
            python_files = glob.glob(dpath + "/*.py")
            logger.debug(funcname + ' will search in path for files: {:s}'.format(dpath))
            for pfile in python_files:
                logger.debug(funcname + ' opening {:s}'.format(pfile))
                module_name = pathlib.Path(pfile).stem
                spec = importlib.util.spec_from_file_location(module_name, pfile)
                module = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(module)
                except Exception as e:
                    logger.warning(funcname + ' could not import module: {:s} \nError: {:s}'.format(pfile, str(e)))

                module_members = inspect.getmembers(module, inspect.isclass)
                valid_module = self.valid_device(module)
                if (valid_module['valid']):  # If the module is valid add it to devices
                    devdict = {'module': module, 'name': module_name, 'source': module.__file__}
                    # Test if the module is already there, otherwise append
                    FLAG_MOD_APPEND = True
                    for m in self.device_modules:
                        if(m['module'] == module):
                            FLAG_MOD_APPEND = False
                            break
                    if (FLAG_MOD_APPEND):
                        self.device_modules.append(devdict)

        #
        # Add all devices from the redvypr internal device module
        #
        max_tries = 5000  # The maximum recursion of modules
        n_tries = 0
        testmodules = [redvyprdevices]
        valid_device_modules = [] #
        other_modules = [] # The rest
        while (len(testmodules) > 0) and (n_tries < max_tries):
            testmodule = testmodules[0]
            device_module_tmp = inspect.getmembers(testmodule, inspect.ismodule)
            for smod in device_module_tmp:
                devicemodule = getattr(testmodule, smod[0])
                if(devicemodule in other_modules):
                    #logger.debug(funcname + ': Module has been tested already ...')
                    continue
                # Check if the device is valid
                valid_module = self.valid_device(devicemodule)
                if (valid_module['valid']):  # If the module is valid add it to devices
                    devdict = {'module': devicemodule, 'name': smod[0], 'source': smod[1].__file__}
                    # Test if the module is already there, otherwise append
                    FLAG_MOD_APPEND = True
                    for m in self.device_modules:
                        if(m['module'] == devicemodule):
                            FLAG_MOD_APPEND=False
                            break
                    if(FLAG_MOD_APPEND):
                        self.device_modules.append(devdict)

                    valid_device_modules.append(devicemodule)
                else:  # Check recursive if devices are found
                    n_tries += 1
                    testmodules.append(devicemodule)
                    other_modules.append(devicemodule)

            testmodules.pop(0)

        self.__populate_device_path_packages()

    def valid_device(self, devicemodule):
        """ Checks if the module is a valid redvypr module
        """
        funcname = 'valid_device(): '
        logger.debug(funcname + 'Checking device {:s}'.format(str(devicemodule)))
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

    def device_loglevel(self, device, loglevel=None):
        """ Returns the loglevel of the device
        """
        loglevel = 'NA'
        for d in self.devices:
            if d['devices'] == device:
                if (d['logger'] is not None):
                    loglevel = d['logger'].getEffectiveLevel()
                    break

        return loglevel

    def add_device(self, devicemodulename=None, deviceconfig={}, thread=None):
        """
        Function adds a device to redvypr

        Configuration of the device can have options:
        template and config:
        template:
        config:

        Args:
            devicemodulename:
            deviceconfig: A dictionary with the configuration, this is filled by i.e. a yaml file with the configuration or if clicked in the gui just the name of the device
            thread:

        Returns:
            devicelist: a list containing all devices of this redvypr instance

        """

        funcname = self.__class__.__name__ + '.add_device():'
        logger.debug(funcname + ':devicemodule: ' + str(devicemodulename) + ':deviceconfig: ' + str(deviceconfig))
        devicelist = []
        device_found = False
        # Loop over all modules and check of we find the name
        for smod in self.device_modules:
            if (devicemodulename == smod['name']):
                logger.debug('Trying to import device {:s}'.format(smod['name']))
                devicemodule = smod['module']
                # Try to get a configuration template
                try:
                    config_template = devicemodule.config_template
                    logger.debug(funcname + ':Found configuation template of device {:s}'.format(str(devicemodule)))
                    #templatedict = configtemplate_to_dict(config_template)
                    FLAG_HAS_TEMPLATE = True
                except Exception as e:
                    logger.debug(
                        funcname + ':No configuration template of device {:s}: {:s}'.format(str(devicemodule), str(e)))
                    FLAG_HAS_TEMPLATE = False

                # Try to get information about publish/subscribe capabilities described in the config_template
                try:
                    publish = config_template['redvypr_device']['publish']
                except:
                    publish = False
                try:
                    subscribe = config_template['redvypr_device']['subscribe']
                except:
                    subscribe = False

                try:
                    deviceconfig['config']
                except:
                    deviceconfig['config'] = {}
                # If the device does not have a name, add a standard but unique one
                try:
                    deviceconfig['name']
                except:
                    deviceconfig['name'] = devicemodulename + '_' + str(self.numdevice)

                try:
                    deviceconfig['loglevel']
                except:
                    deviceconfig['loglevel'] = 'INFO'

                try:
                    autostart = deviceconfig['autostart']
                except:
                    autostart = False

                # Check for multiprocess options in configuration
                if (thread == None):
                    try:
                        multiprocess = deviceconfig['mp'].lower()
                    except:
                        multiprocess = 'thread'
                elif(thread):
                    multiprocess = 'thread'
                else:
                    multiprocess = 'multiprocess'

                if multiprocess == 'thread':  # Thread or multiprocess
                    dataqueue = queue.Queue(maxsize=queuesize)
                    datainqueue = queue.Queue(maxsize=queuesize)
                    comqueue = queue.Queue(maxsize=queuesize)
                    statusqueue = queue.Queue(maxsize=queuesize)
                    guiqueue = queue.Queue(maxsize=queuesize)
                else:
                    dataqueue = multiprocessing.Queue(maxsize=queuesize)
                    datainqueue = multiprocessing.Queue(maxsize=queuesize)
                    comqueue = multiprocessing.Queue(maxsize=queuesize)
                    statusqueue = multiprocessing.Queue(maxsize=queuesize)
                    guiqueue = multiprocessing.Queue(maxsize=queuesize)

                # Create a dictionary for the statistics and general information about the device
                # This is used extensively in exchanging information about devices between redvypr instances and or other devices
                statistics = data_packets.create_data_statistic_dict()
                # Device do not necessarily have a statusqueue
                try:
                    name = deviceconfig['name']
                    loglevel = deviceconfig['loglevel']

                    numdevices = len(self.devices)
                    # Could also create a UUID based on the hostinfo UUID str
                    device_uuid = '{:03d}--'.format(numdevices) + str(uuid.uuid1()) + '::' + self.hostinfo['uuid']
                    try:
                        devicemodule.Device
                        HASDEVICE = True
                    except:
                        HASDEVICE = False

                    if (HASDEVICE):  # Module has its own device
                        Device = devicemodule.Device
                        # Check if a startfunction is implemented
                        try:
                            Device.start
                            startfunction = None
                            logger.debug(
                                funcname + ' Device has a start function')
                        except:
                            logger.debug(
                                funcname + ' Device does not have a start function, will add the standard function')
                            startfunction = devicemodule.start
                    else:
                        Device = redvypr_device
                        startfunction = devicemodule.start

                    # Config used at all?
                    print('Getting config')
                    config = deviceconfig['config']
                    print('Done')
                    # Merge the config with a potentially existing template to fill in default values
                    if FLAG_HAS_TEMPLATE:
                        print('With template', config_template)
                        print('With configuration', config)
                        #config = apply_config_to_dict(config,templatedict)
                        #config = copy.deepcopy(config)
                        #redvypr.config.dict_to_configDict(templatedict, process_template=True)
                        configu = configuration(template=config_template,config=config)
                    else: # Make a configuration without a template directly from the config dict
                        print('Without template')
                        configu = configuration(config)
                        config_template = None

                    print('Config', configu)
                    print('Config type', type(configu))
                    print('loglevel', loglevel)
                    device = Device(name=name, uuid=device_uuid, config=configu, redvypr=self, dataqueue=dataqueue,
                                    publish=publish,subscribe=subscribe,autostart=autostart,
                                    template=config_template, comqueue=comqueue, datainqueue=datainqueue,
                                    statusqueue=statusqueue, loglevel=loglevel, multiprocess=multiprocess,
                                    numdevice=self.numdevice, statistics=statistics,startfunction=startfunction,devicemodulename=devicemodulename)

                    # Update the statistics of the device itself
                    #statistics['device_redvypr'][device.address_str] = copy.deepcopy(data_packets.device_redvypr_statdict)
                    #statistics['device_redvypr'][device.address_str]['_redvypr']['host'] = self.hostinfo
                    #statistics['device_redvypr'][device.address_str]['_deviceinfo'] = {'subscribe':subscribe,'publish':publish,'devicemodulename':devicemodulename}
                    device.subscription_changed_signal.connect(self.process_subscription_changed)
                    self.numdevice += 1
                    # If the device has a logger
                    devicelogger = device.logger
                except Exception as e:
                    logger.warning(funcname + ' Could not add device because of:')
                    logger.exception(e)


                devicedict = {'device': device, 'thread': None, 'dataout': [], 'gui': [], 'guiqueue': [guiqueue],
                              'statistics': statistics, 'logger': devicelogger,'comqueue':comqueue}

                # Add the modulename
                devicedict['devicemodulename'] = devicemodulename
                # Add some statistics
                devicedict['numpacket'] = 0
                devicedict['numpacketout'] = 0
                # The displaywcreate_idget, to be filled by redvyprWidget.add_device (optional)
                devicedict['devicedisplaywidget'] = None
                # device = devicedict['device']

                # Check if the device wants a direct start after initialization
                try:
                    autostart = device.autostart
                except:
                    autostart = False

                # Add the device to the device list
                self.devices.append(devicedict)  # Add the device to the devicelist
                ind_device = len(self.devices) - 1

                if (autostart):
                    logger.info(funcname + ': Starting device')
                    self.start_device_thread(device)

                devicelist = [devicedict, ind_device, devicemodule]

                logger.debug(funcname + ': Emitting device signal')
                self.device_added.emit(devicelist)
                device_found = True
                break

        if (device_found == False):
            logger.warning(funcname + ': Could not add device (not found): {:s}'.format(str(devicemodulename)))

        return devicelist


    def start_device_thread(self, device):
        """ Functions starts the device thread that is the core of each device
        Args:
           device: Device is either a Device class defined in the device module or a dictionary containing the device class (when called from infodevicewidget in redvypr.py)

        """
        funcname = __name__ + '.start_device_thread():'
        if (type(device) == dict):  # If called from devicewidget
            device = device['device']

        # logger.debug(funcname + 'Starting device: ' + str(device.name))
        logger.debug(funcname + 'Starting device: ' + str(device.name))
        thread = device.thread_start()

    def stop_device_thread(self, device):
        """Functions stops a thread, to process the data (i.e. reading from a device, writing to a file)
        Args:
           device: Device is either a Device class defined in the device module or a dictionary containing the device class (when called from infodevicewidget in redvypr.py)

        """
        funcname = __name__ + '.stop_device_thread()'
        command = data_packets.commandpacket(command='stop', uuid=device.uuid)
        if (type(device) == dict):  # If called from devicewidget
            device = device['device']
        logger.debug(funcname + ':Stopping device: ' + device.name)
        thread_status = device.thread_stop()

        for sendict in self.devices:
            if (sendict['device'] == device):
                if (sendict['thread'] == None):
                    return
                elif (sendict['thread'].is_alive()):
                    try:
                        device.thread_stop()
                        return
                    except:
                        pass
                    try:
                        if (device.datainqueuestop):
                            datainqueuestop = True
                    except:
                        datainqueuestop = False

                    if (datainqueuestop):
                        logger.debug(funcname + ':Stopping device with datainqueue: ' + device.name)
                        device.datainqueue.put({'command': 'stop'})
                    else:
                        logger.debug(funcname + ':Stopping device with comqueue: ' + device.name)
                        device.comqueue.put('stop')

                else:
                    logger.warning(funcname + ': Could not stop thread.')

    def send_command(self, device, command):  # Legacy ?!!?!, used device.command instead ...
        """ Sends a command to a device by putting it into the command queue
        """
        funcname = self.__class__.__name__ + '.send_command():'
        dev = self.get_device_from_str(device)
        print(funcname, device, command, dev)
        logger.debug(funcname + 'Sending command')
        dev.comqueue.put(command)

    def adddevicepath(self, folder):
        """Adds a path to the devicepathlist
        """
        if folder:
            if (folder not in self.device_paths):
                self.device_paths.append(folder)
                self.device_path_changed.emit()  # Notify about the changes

    def remdevicepath(self, folder):
        if (folder not in self.device_paths):
            self.device_paths.remove(folder)
            self.device_path_changed.emit()  # Notify about the changes

    def process_subscription_changed(self):
        """
        Process the subscription changed signals of the devices
        Returns:

        """
        devsender = self.sender()
        print('Subscribtion changed',devsender.name)
        for d in self.devices:
            dev = d['device']
            if dev == devsender:
                continue
            dev.subscription_changed_global(devsender)

    def get_all_subscriptions(self):
        """

        Returns:
            List containing two lists of equal length, the first with all subscriptions, the second the device address

        """
        all_subscriptions = []
        all_devices = []
        for d in self.devices:
            dev = d['device']
            nsub = len(dev.subscribed_addresses)
            all_subscriptions.extend(dev.subscribed_addresses)
            all_devices.extend([dev.address_str]*nsub)

        return [all_subscriptions,all_devices]


    def get_devicename_from_device(self, device):
        """
        Creates a redvypr devicename from device and the hostinfo.
        Args:
            device:
        
        Returns
        -------
        device : str
            The devicestring
            
        """
        devicename = device.name + ':' + self.hostinfo['hostname'] + '@' + self.hostinfo['addr'] + '::' + self.hostinfo[
            'uuid']
        return devicename


    def get_device_from_str(self, devicestr):
        """ Returns the deviced based on an inputstr, if not found returns None
        """
        devicedict = self.get_devicedict_from_str(devicestr)
        if (devicedict == None):
            return None
        else:
            return devicedict['device']

    def get_devicedict_from_str(self, devicestr):
        """
        Returns the devicedict (as found in the list self.devices) based on an devicestr, if not found returns None. If
        the devicestr is from a remote redvypr instance (uuid differ) the devicedict of the forwarding device is returned.
        
        Args:
            devicestr (str): 
            
            
        Returns
        -------
        device : dict
            The redvypr devicedict corresponding to the devicestr.
            
        
        """
        #deviceparsed = data_packets.parse_addrstr(devicestr, local_hostinfo=self.hostinfo)
        deviceaddr = data_packets.redvypr_address(devicestr)
        # Check local devices first
        for d in self.devices:
            dev = d['device']
            daddr = dev.address
            if deviceaddr == daddr:
                return d

        # Check forwarded devices
        for d in self.devices:
            dev = d['device']
            daddr = dev.address
            for dforward in dev.statistics['devices']:
                if deviceaddr == daddr:
                    return d

        return None

    def get_devices(self):
        """
        Returns a list of the devices

        Returns
        -------
        devicelist : TYPE
            DESCRIPTION.


        """
        devicelist = []
        for d in self.devices:
            devicelist.append(d['device'].name)

        return devicelist

    def get_forwarded_devicenames(self, device=None):
        """

        Args:
            device: redvypr_device

        Returns:
           List with the devicenames of the forwarded devicenames
        """
        try:
            devicenames = device.statistics['devices']
        except:
            devicenames = []

        return devicenames

    def get_data_providing_devicenames(self, device=None, forwarded_devices=True):
        """
        Returns a list of the devices that provide data to device. This is either the subscribed devices itself or a device that forwards data packets (i.e. network device)

        Args:
            device: bool
                None: Returns all data providing devices. 
                Device:  Returns all data providing devices of device 
            forwarded_devices: bool
                A device might forward data packets from other devices. These devices can be listed as well, note that the device needs to have data packets received already to have them in their statistic.

        Returns
        -------
        list
            A list containing the names of the data providing devices

        """
        funcname = self.__class__.__name__ + '.get_data_providing_devices():'
        logger.debug(funcname)
        flag_device_itself = False
        for devdict in self.devices:
            if (devdict['device'] == device):
                flag_device_itself = True
                break

        if (device == None):
            flag_device_itself = True

        if (flag_device_itself == False):
            raise ValueError('Device not in redvypr')
        else:
            devicenamelist = []
            if (device == None):
                for dev in self.devices:
                    devname = dev['device'].name
                    if (dev['device'].publish):
                        devicenamelist.append(devname)
                        print('Devname test', devname)
                        devicenamelist_forward = self.get_forwarded_devicenames(dev['device'])
                        print('Devname forward', devicenamelist_forward)
                        devicenamelist.extend(devicenamelist_forward)

            else:
                devicelist = get_data_providing_devices(self.devices, device)
                for dev in devicelist:
                    devicenamelist.append(dev.name)

                devicenamelist_forward = self.get_forwarded_devicenames(dev['device'])
                devicenamelist.extend(devicenamelist_forward)

            print('Devicelist 1', devicenamelist)
            devicenamelist = list(set(devicenamelist))

            return devicenamelist

    def get_data_providing_devices(self, device=None):
        """
        Returns LOCAL devices that provide data, note that if forwarded devices are needed, use get_data_providing_devicenames!
        Args:
            device: redvypr_device or None, if none return all data providing devices
            
        Returns
        -------
        list
            A list containing redvypr_devices
        """
        devicelist = []
        devicedicts = self.get_data_providing_devicedicts(device)
        for d in devicedicts:
            devicelist.append(d['device'])
        return devicelist

    def get_data_providing_devicedicts(self, device=None):
        """
        Returns LOCAL devices that provide data, note that if forwarded devices are needed, use get_data_providing_devicenames!
        Args:
            device: redvypr_device or None, if none return all data providing devices
            
        Returns
        -------
        list
            A list containing redvypr dictionary containing the device and additional infrastructure::
                redvypr.get_data_providing_devices()[0].keys()
                dict_keys(['device', 'thread', 'dataout', 'gui', 'guiqueue', 'statistics', 'numpacket', 'numpacketout', 'devicedisplaywidget', 'logger', 'displaywidget', 'initwidget', 'widget', 'infowidget'])
        """
        if (device == None):
            devicedicts = []
            for dev in self.devices:
                if (dev['device'].publish):
                    devicedicts.append(dev)
        else:
            devicedicts = get_data_providing_devices(self.devices, device)

        return devicedicts

    def get_datastream_providing_device(self, datastream):
        """ Gets the device that provides that datastream
        Not fully implemented!!!
        """
        funcname = self.__class__.__name__ + '.get_datastream_providing_device():'
        logger.debug(funcname)
        datastreamparsed = data_packets.parse_addrstr(datastream, local_hostinfo=self.hostinfo)
        devicename = datastreamparsed['devicename']
        #for dev in self.devices:
        #    datastreamlist.extend(dev['statistics']['datastreams'])

    def get_datastream_info(self, datastream):
        """ Gets additional information to the datastream
        """

        datastreams = self.get_datastreams()
        datastreaminfo = {}
        for dev in self.devices:
            datastreaminfo |= dev['statistics']['datastreams_info']

        for dstream in datastreaminfo.keys():
            if (data_packets.compare_datastreams(datastream, dstream)):
                return datastreaminfo[dstream]

        return None

    def get_datastreams(self, device=None, format='uuid',local=False,add_lastseen=False):
        """
        Gets datastreams from a device (or all devices if device == None).
        Args:
            device: (redvypr_device or str):
            format:
            local: If True: Return only datastreams that are local. This is important if datastreams from other redvypr instances are subscribed.
            add_lastseen:
            
        Returns
        -------
        list if add_lastseen == False
            A list containing the datastreams
        dict: if add_lastseen == True
            A dictionary with all datastreams as keys and the unix time as content specifying the last time the datastream has been received
        """
        funcname = self.__class__.__name__ + '.get_datastreams():'
        datastreamlist = []

        if (type(device) == str):
            datastreams_all = []
            for dev in self.devices:
                datastreams_all.extend(dev['statistics']['datastreams'])
            datastreams_all = list(set(datastreams_all))
            # Parse the devicestring
            deviceparsed = data_packets.parse_addrstr(device, local_hostinfo=self.hostinfo)
            ##print('datastreams',datastreams_all)
            ##print('deviceparsed',deviceparsed)
            for stream in datastreams_all:
                datastream_parsed = data_packets.parse_addrstr(stream, local_hostinfo=self.hostinfo)
                ##print('datastream parsed',datastream_parsed)
                flag_name = datastream_parsed['devicename'] == deviceparsed['devicename']
                flag_name = flag_name or deviceparsed['deviceexpand']

                flag_hostname = datastream_parsed['hostname'] == deviceparsed['hostname']
                flag_hostname = flag_hostname or deviceparsed['hostexpand']

                flag_addr = datastream_parsed['addr'] == deviceparsed['addr']
                flag_addr = flag_addr or deviceparsed['addrexpand']

                flag_uuid = datastream_parsed['uuid'] == deviceparsed['uuid']
                flag_uuid = flag_uuid or deviceparsed['uuidexpand']

                flag_local = datastream_parsed['local'] == deviceparsed['local']

                ##print('name',flag_name,'hostname',flag_hostname,'addr',flag_addr,'uuid',flag_uuid)
                if (flag_name and flag_local) or (flag_name and flag_uuid) or (
                        flag_name and flag_addr and flag_hostname):
                    datastreamlist.append(stream)

            datastreamlist = list(set(datastreamlist))

        elif (device == None):
            for dev in self.devices:
                datastreamlist.extend(dev['statistics']['datastreams'])
            datastreamlist = list(set(datastreamlist))

        else:
            datastreamlist = device.statistics['datastreams']
            datastreamlist = list(set(datastreamlist))


        if local:
            for d in reversed(datastreamlist):
                if self.hostinfo['uuid'] in d: # Check if the uuid is in
                    pass
                else:
                    datastreamlist.remove(d)

        return datastreamlist

    def get_datakeys(self, device):
        """
        Get the datakeys for the device. 
        
        
        Args:
            device (redvypr device or str):
            
        Returns:
        --------
        list
            A list of the device datakeys
         
        """
        funcname = self.__class__.__name__ + '.get_datakeys():'
        logger.debug(funcname)
        datakeys = []
        datastreams = self.get_datastreams(device)  # Get datastreams of device
        for stream in datastreams:
            key = stream.split('/')[0]
            datakeys.append(key)

        datakeys = list(set(datakeys))

        return datakeys

    def get_data_receiving_devices(self, device):
        """

        Args:
            device:

        Returns:
            List of devices the device is provding data
        """

        funcname = self.__class__.__name__ + '.get_data_receiving_devices():'
        logger.debug(funcname)
        return get_data_receiving_devices(self.devices, device)

    def get_known_devices(self):
        """ List all known devices that can be loaded by redvypr
        
        Returns:
        --------
        list
            A list of known devices
        """
        funcname = self.__class__.__name__ + '.get_known_devices():'
        logger.debug(funcname)
        devices = []
        for d in self.device_modules:
            devices.append(d['name'])

        return devices




#
#
# ########################
# Here the gui part starts
# ########################
#
#
#


#
#
#
# redvyprwidget
#
#
#

class redvyprWidget(QtWidgets.QWidget):
    """This is the main widget of redvypr. 

    """

    def __init__(self, width=None, height=None, config=None,hostname='redvypr'):
        """ Args: 
            width:
            height:
            config: Either a string containing a path of a yaml file, or a list with strings of yaml files
        """
        super(redvyprWidget, self).__init__()
        self.setGeometry(50, 50, 500, 300)

        # Lets create the heart of redvypr
        self.redvypr = redvypr(hostname=hostname)  # Configuration comes later after all widgets are initialized

        self.redvypr.device_path_changed.connect(self.__populate_devicepathlistWidget)
        self.redvypr.device_added.connect(self._add_device_gui)
        # Fill the layout
        self.devicetabs = QtWidgets.QTabWidget()
        self.devicetabs.setMovable(True)
        self.devicetabs.setTabsClosable(True)
        self.devicetabs.tabCloseRequested.connect(self.closeTab)

        # The configuration of the redvypr
        self.create_devicepathwidget()
        self.create_statuswidget()
        # self.devicetabs.addTab(self.__devicepathwidget,'Status')
        self.devicetabs.addTab(self.__statuswidget, 'Status')

        # A widget containing all connections
        self.create_devicewidgetsummary()  # Creates self.devicesummarywidget
        self.devicetabs.addTab(self.devicesummarywidget, 'Devices')  # Add device summary widget
        # A logwidget
        self.logwidget = QtWidgets.QPlainTextEdit()
        self.logwidget.setReadOnly(True)
        self.logwidget_handler = QPlainTextEditLogger()
        self.logwidget_handler.add_widget(self.logwidget)
        self.devicetabs.addTab(self.logwidget, 'Log')  # Add a logwidget
        # Connect the logwidget to the logging
        # logger.addHandler(self.logwidget_handler)
        # self.logwidget.append("Hallo!")

        # A timer to gather all the data from the devices
        self.devicereadtimer = QtCore.QTimer()
        self.devicereadtimer.timeout.connect(self.readguiqueue)
        self.devicereadtimer.start(100)
        # self.devicereadtimer.start(500)

        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.addWidget(self.devicetabs)
        if ((width is not None) and (height is not None)):
            self.resize(int(width), int(height))

        if True:
            # Configurating redvypr
            if (config is not None):
                if (type(config) == str):
                    config = [config]

                for c in config:
                    self.redvypr.parse_configuration(c)

                if ('hostname' in self.redvypr.config.keys()):
                    self.hostname_changed(self.redvypr.config['hostname'])
        self.__populate_devicepathlistWidget()

    def open_ipwidget(self):
        self.ipwidget = redvypr_ip_widget()

    def open_console(self):
        """ Opens a pyqtconsole console widget
            
        """
        if True:
            width = 800
            height = 500
            # Console
            self.console = PythonConsole(formats={
                'keyword': format('darkBlue', 'bold')
            })
            self.console.setWindowIcon(QtGui.QIcon(_icon_file))
            self.console.setWindowTitle("redvypr console")
            self.console.push_local_ns('redvypr_widget', self)
            self.console.push_local_ns('redvypr', self.redvypr)
            self.console.resize(width, height)
            self.console.show()

            self.console.eval_queued()

        # self.devicetabs.addTab(self.console,'Console')

    def renamedevice(self, oldname, name):
        """ Renames a devices
        """
        funcname = 'renamedevice()'
        for dev in self.redvypr.devices:
            devname = dev['device'].name
            if (devname == name):  # Found a device with that name already, lets do nothging
                logger.debug(funcname + ': Name already in use. Will not rename')
                return False

        for dev in self.redvypr.devices:
            devname = dev['device'].name
            if (devname == oldname):  # Found the device, lets rename it
                dev['device'].change_name(name)
                widget = dev['widget']
                # Create a new infowidget
                dev['infowidget'].close()
                dev['infowidget'] = deviceinfoWidget(dev, self)
                # Note: commented for the moment to be replaced by the signals of the device itself
                # dev['infowidget'].device_start.connect(self.redvypr.start_device_thread)
                # dev['infowidget'].device_stop.connect(self.redvypr.stop_device_thread)
                dev['infowidget'].connect.connect(self.connect_device)
                for i in range(self.devicetabs.count()):
                    if (self.devicetabs.widget(i) == widget):
                        self.devicetabs.setTabText(i, name)
                        break

                break

        self.update_devicewidgetsummary()
        return True

    def create_devicewidgetsummary(self):
        """ Creates the device summary widget
        """
        self.devicesummarywidget = QtWidgets.QWidget()
        self.devicesummarywidget_layout = QtWidgets.QVBoxLayout(self.devicesummarywidget)

    def update_devicewidgetsummary(self):
        """ Updates the device summary widget
        """
        # Remove all
        for i in reversed(range(self.devicesummarywidget_layout.count())):
            item = self.devicesummarywidget_layout.itemAt(i)
            self.devicesummarywidget_layout.removeItem(item)

        # and refill it
        for i, devicedict in enumerate(self.redvypr.devices):
            self.devicesummarywidget_layout.addWidget(devicedict['infowidget'])

        self.devicesummarywidget_layout.addStretch()

    def readguiqueue(self):
        """This periodically called function reads the guiqueue and calls
        the widgets of the devices update function (if they exist)

        """
        # Update devices
        for devicedict in self.redvypr.devices:
            device = devicedict['device']
            if True:
                # Feed the data into the modules/functions/objects and
                # let them treat the data
                for i, guiqueue in enumerate(devicedict['guiqueue']):
                    while True:
                        try:
                            data = guiqueue.get(block=False)
                        except Exception as e:
                            # print('Exception gui',e)
                            break
                        try:
                            devicedict['gui'][i].update(data)
                        except Exception as e:
                            break
                            #logger.exception(e)


    def load_config(self):
        """ Loads a configuration file
        """
        funcname = self.__class__.__name__ + '.load_config()'
        logger.debug(funcname)
        conffile, _ = QtWidgets.QFileDialog.getOpenFileName(self, "QFileDialog.getOpenFileName()", "",
                                                            "Yaml Files (*.yaml);;All Files (*)")
        if conffile:
            self.redvypr.parse_configuration(conffile)

    def save_config(self):
        """ Saves a configuration file
        """
        funcname = self.__class__.__name__ + '.save_config():'
        logger.debug(funcname)
        data_save = self.redvypr.get_config()
        print('data_save',data_save)
        if True:
            tstr = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
            fname_suggestion = 'config_' + self.redvypr.hostinfo['hostname'] + '_' +tstr + '.yaml'

            fname_full, _ = QtWidgets.QFileDialog.getSaveFileName(self, "QFileDialog.getSaveFileName()", fname_suggestion,
                                                                  "Yaml Files (*.yaml);;All Files (*)")
            if fname_full:
                print('Saving to file {:s}'.format(fname_full))
                with open(fname_full, 'w') as fyaml:
                    yaml.dump(data_save, fyaml)

    def open_add_device_widget(self):
        """Opens a widget for the user to choose to add a device
        TODO: make an own widget out of this

        """
        self.add_device_widget = QtWidgets.QWidget()
        # Set icon    
        self.add_device_widget.setWindowIcon(QtGui.QIcon(_icon_file))
        layout = QtWidgets.QFormLayout(self.add_device_widget)
        self.__devices_list = QtWidgets.QListWidget()
        self.__devices_list.itemClicked.connect(self.__device_name)
        self.__devices_list.currentItemChanged.connect(self.__device_name)
        self.__devices_list.itemDoubleClicked.connect(self.add_device_click)
        self.__devices_info = QtWidgets.QWidget()
        self.__devices_addbtn = QtWidgets.QPushButton('Add')
        self.__devices_addbtn.clicked.connect(self.add_device_click)
        self.__devices_devnamelabel = QtWidgets.QLabel('Devicename')
        self.__devices_devname = QtWidgets.QLineEdit()
        self.__mp_label = QtWidgets.QLabel('Multiprocessing options')
        self.__mp_thread = QtWidgets.QRadioButton('Thread')
        self.__mp_multi = QtWidgets.QRadioButton('Multiprocessing')
        self.__mp_multi.setChecked(True)
        self.__mp_group = QtWidgets.QButtonGroup()
        self.__mp_group.addButton(self.__mp_thread)
        self.__mp_group.addButton(self.__mp_multi)

        layout.addRow(self.__devices_info)
        layout.addRow(self.__devices_list)
        layout.addRow(self.__mp_label)
        layout.addRow(self.__mp_thread, self.__mp_multi)
        layout.addRow(self.__devices_devnamelabel, self.__devices_devname)
        layout.addRow(self.__devices_addbtn)
        # Searches for devices 
        self.redvypr.populate_device_path()
        # Create the info widget
        infolayout = QtWidgets.QFormLayout(self.__devices_info)
        self.__devices_info_sourcelabel1 = QtWidgets.QLabel('Source:')
        self.__devices_info_sourcelabel2 = QtWidgets.QLabel('')
        self.__devices_info_sourcelabel3 = QtWidgets.QLabel('Path:')
        self.__devices_info_sourcelabel4 = QtWidgets.QLabel('')
        self.__devices_info_sourcelabel5 = QtWidgets.QLabel('Description:')
        self.__devices_info_sourcelabel6 = QtWidgets.QLabel('')
        infolayout.addRow(self.__devices_info_sourcelabel1, self.__devices_info_sourcelabel2)
        infolayout.addRow(self.__devices_info_sourcelabel3, self.__devices_info_sourcelabel4)
        infolayout.addRow(self.__devices_info_sourcelabel5)
        infolayout.addRow(self.__devices_info_sourcelabel6)

        # Populate the device list
        itms = []
        known_devices = self.redvypr.get_known_devices()
        for d in known_devices:
            itm = QtWidgets.QListWidgetItem(d)
            itms.append(itm)
            self.__devices_list.addItem(itm)

        self.__devices_list.setMinimumWidth(self.__devices_list.sizeHintForColumn(0))
        # Set the first item as current and create a device name
        self.__devices_list.setCurrentItem(itms[0])
        self.__device_name()
        self.add_device_widget.show()

    def __device_info(self):
        """ Populates the self.__devices_info widget with the info of the module
        """
        ind = int(self.__devices_list.currentRow())
        infotxt = self.redvypr.device_modules[ind]['name']
        self.__devices_info_sourcelabel2.setText(infotxt)
        infotxt2 = self.redvypr.device_modules[ind]['source']
        self.__devices_info_sourcelabel4.setText(infotxt2)
        try:
            desctxt = self.redvypr.device_modules[ind]['module'].description
        except Exception as e:
            desctxt = ''

        self.__devices_info_sourcelabel6.setText(desctxt)

    def __device_name(self):
        devicemodulename = self.__devices_list.currentItem().text()
        devicename = devicemodulename + '_{:d}'.format(self.redvypr.numdevice + 1)
        self.__devices_devname.setText(devicename)
        self.__device_info()

    def add_device_click(self):
        """
        """
        devicemodulename = self.__devices_list.currentItem().text()
        thread = self.__mp_thread.isChecked()
        config = {'name': str(self.__devices_devname.text()),'loglevel':logger.level}
        deviceconfig = {'config':config}
        print('Adding device, config',deviceconfig)
        self.redvypr.add_device(devicemodulename=devicemodulename, thread=thread, deviceconfig=deviceconfig)
        # Update the name
        self.__device_name()

    def _add_device_gui(self, devicelist):
        """ Function is called via the redvypr.add_device signal and is adding
        all the gui functionality to the device

        """
        funcname = __name__ + '._add_device_gui()'
        logger.debug(funcname)
        devicedict = devicelist[0]
        ind_devices = devicelist[1]
        devicemodule = devicelist[2]

        # First create the device and then do the widget stuff here
        device = devicedict['device']
        #
        # Now add all the widgets to the device
        #
        # Create the init widget
        try:
            deviceinitwidget_bare = devicemodule.initDeviceWidget
        except Exception as e:
            logger.debug(funcname + ': Widget does not have a deviceinitwidget using standard one:' + str(e))
            #logger.exception(e)
            deviceinitwidget_bare = redvypr_deviceInitWidget  # Use a standard widget

        try:
            deviceinitwidget = deviceinitwidget_bare(device)
        except Exception as e:
            logger.warning(funcname + ': Could not add deviceinitwidget because of:')
            logger.exception(e)
            deviceinitwidget = QtWidgets.QWidget()  # Use a standard widget

        try:
            logger.debug(funcname + ': Connect signal connected')
            deviceinitwidget.connect.connect(self.connect_device)
        except Exception as e:
            logger.debug('Widget does not have connect signal:' + str(e))

        device.deviceinitwidget = deviceinitwidget
        # Add the info widget
        deviceinfowidget = redvypr_deviceInfoWidget(device)

        #
        # Check if we have a widget to display the data
        # Create the displaywidget
        #
        try:
            devicedisplaywidget = devicemodule.displayDeviceWidget
        except Exception as e:
            logger.debug(funcname + ': No displaywidget found for {:s}'.format(str(devicemodule)))
            ## Using the standard display widget
            # devicedisplaywidget = displayDeviceWidget_standard
            devicedisplaywidget = None

        # The widget shown in the tab
        devicewidget = QtWidgets.QWidget()
        devicewidget.device = device # Add the device to the devicewidget
        devicelayout = QtWidgets.QVBoxLayout(devicewidget)
        devicetab = QtWidgets.QTabWidget()
        devicetab.setMovable(True)
        devicelayout.addWidget(devicetab)

        # Add init widget
        devicetab.addTab(deviceinitwidget, 'Init')
        devicetab.addTab(deviceinfowidget, 'Info')
        # Devices can have their specific display objects, if one is
        # found, initialize it, otherwise just the init Widget
        if (devicedisplaywidget is not None):
            initargs = inspect.signature(devicedisplaywidget.__init__)
            initdict = {}
            if ('device' in initargs.parameters.keys()):
                initdict['device'] = device

            if ('tabwidget' in initargs.parameters.keys()):
                initdict['tabwidget'] = devicetab

            if ('deviceinitwidget' in initargs.parameters.keys()):
                initdict['deviceinitwidget'] = deviceinitwidget

            # https://stackoverflow.com/questions/334655/passing-a-dictionary-to-a-function-as-keyword-parameters
            devicedisplaywidget_called = devicedisplaywidget(**initdict)
            # Add the widget to the device
            device.devicedisplaywidget = devicedisplaywidget_called
            # Test if the widget has a tabname
            try:
                tabname = devicedisplaywidget_called.tabname
            except:
                tabname = 'Display data'

            # Check if the widget has included itself, otherwise add the displaytab
            if (devicetab.indexOf(devicedisplaywidget_called)) < 0:
                devicetab.addTab(devicedisplaywidget_called, tabname)
                # Append the widget to the processing queue
            self.redvypr.devices[ind_devices]['gui'].append(devicedisplaywidget_called)
            self.redvypr.devices[ind_devices]['displaywidget'] = self.redvypr.devices[ind_devices]['gui'][0]
            self.redvypr.devices[ind_devices]['initwidget'] = deviceinitwidget
        else:
            self.redvypr.devices[ind_devices]['initwidget'] = deviceinitwidget
            self.redvypr.devices[ind_devices]['displaywidget'] = None

        self.redvypr.devices[ind_devices]['widget'] = devicewidget  # This is the displaywidget
        # Create the infowidget (for the overview of all devices)
        self.redvypr.devices[ind_devices]['infowidget'] = deviceinfoWidget(self.redvypr.devices[ind_devices], self)
        self.redvypr.devices[ind_devices]['infowidget'].connect.connect(self.connect_device)

        #
        # Add the devicelistentry to the widget, this gives the full information to the device
        #
        # 22.11.2022 TODO, this needs to be replaced by functional arguments instead of properties
        self.redvypr.devices[ind_devices]['initwidget'].redvyprdevicelistentry = self.redvypr.devices[ind_devices]
        self.redvypr.devices[ind_devices]['initwidget'].redvypr = self.redvypr
        if(len(self.redvypr.devices[ind_devices]['gui']) > 0):
            self.redvypr.devices[ind_devices]['gui'][0].redvyprdevicelistentry = self.redvypr.devices[ind_devices]
            self.redvypr.devices[ind_devices]['gui'][0].redvypr = self.redvypr


        self.devicetabs.addTab(devicewidget, device.name)
        self.devicetabs.setCurrentWidget(devicewidget)

        # All set, now call finalizing functions
        # Finalize the initialization by calling a helper function (if exist)
        try:
            deviceinitwidget.finalize_init()
        except Exception as e:
            logger.debug(funcname + ':finalize_init():' + str(e))

            # Update the summary
        self.update_devicewidgetsummary()

    def connect_device_gui(self):
        """ Wrapper for the gui
        """
        # Get the current tab
        curtab = self.devicetabs.currentWidget()
        try:
            device = curtab.device
        except:
            device = None
        self.open_connect_widget(device=device)

    def connect_device(self, device):
        """ Handles the connect signal from devices, called when the connection between the device shall be changed
        """
        logger.debug('Connect clicked')
        if (type(device) == dict):
            device = device['device']
        self.open_connect_widget(device=device)

    def open_connect_widget(self, device=None):
        funcname = __name__ + '.open_connect_widget()'
        logger.debug(funcname + ':' + str(device))
        #self.__con_widget = redvyprConnectWidget(devices=self.redvypr.devices, device=device)
        self.__con_widget = gui.redvyprConnectWidget2(redvypr=self.redvypr, device=device)
        self.__con_widget.show()

    def __hostname_changed_click(self):
        hostname, ok = QtWidgets.QInputDialog.getText(self, 'redvypr hostname', 'Enter new hostname:')
        if ok:
            self.hostname_changed(hostname)

    def hostname_changed(self, hostname):
        if True:
            self.__hostname_line.setText(hostname)
            self.redvypr.config['hostname'] = hostname
            self.redvypr.hostinfo['hostname'] = hostname

    def __update_status_widget__(self):
        """
        Updates the status information
        Returns:

        """
        self.__status_dtneeded.setText(' (needed {:0.5f}s)'.format(self.redvypr.dt_avg_datadist))

    def create_statuswidget(self):
        """Creates the statuswidget

        """
        self.redvypr.status_update_signal.connect(self.__update_status_widget__)
        self.__statuswidget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(self.__statuswidget)
        # dt
        self.__status_dt = QtWidgets.QLabel('Distribution time: {:0.5f}s'.format(self.redvypr.dt_datadist))
        self.__status_dtneeded = QtWidgets.QLabel(' (needed {:0.5f}s)'.format(self.redvypr.dt_avg_datadist))

        layout.addRow(self.__status_dt, self.__status_dtneeded)

        # Hostname
        self.__hostname_label = QtWidgets.QLabel('Hostname:')
        self.__hostname_line = QtWidgets.QLabel('')
        self.__hostname_line.setAlignment(QtCore.Qt.AlignRight)
        self.__hostname_line.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.__hostname_line.setText(self.redvypr.hostinfo['hostname'])
        # UUID
        self.__uuid_label = QtWidgets.QLabel('UUID:')
        self.__uuid_line = QtWidgets.QLabel('')
        self.__uuid_line.setAlignment(QtCore.Qt.AlignRight)
        self.__uuid_line.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.__uuid_line.setText(self.redvypr.hostinfo['uuid'])
        # IP
        self.__ip_label = QtWidgets.QLabel('IP:')
        self.__ip_line = QtWidgets.QLabel('')
        self.__ip_line.setAlignment(QtCore.Qt.AlignRight)
        self.__ip_line.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.__ip_line.setText(self.redvypr.hostinfo['addr'])
        # Optional hostinformation
        self.__hostinfo_opt = gui.configWidget(self.redvypr.hostinfo_opt,loadsavebutton=False,redvypr_instance=self.redvypr)

        # Change the hostname
        self.__hostname_btn = QtWidgets.QPushButton('Change hostname')
        self.__hostname_btn.clicked.connect(self.__hostname_changed_click)

        layout.addRow(self.__hostname_label, self.__hostname_line)
        layout.addRow(self.__uuid_label, self.__uuid_line)
        layout.addRow(self.__ip_label, self.__ip_line)
        layout.addRow(self.__hostinfo_opt)
        layout.addRow(self.__hostname_btn)

        self.__statuswidget_pathbtn = QtWidgets.QPushButton('Edit device path')
        self.__statuswidget_pathbtn.clicked.connect(self.show_devicepathwidget)
        layout.addRow(self.__statuswidget_pathbtn)

        logo = QtGui.QPixmap(_logo_file)
        logolabel = QtWidgets.QLabel()
        logolabel.setPixmap(logo)
        # layout.addRow(logolabel)

    def show_devicepathwidget(self):
        """A widget to show the pathes to search for additional devices

        """
        self.__devicepathwidget.show()

    def create_devicepathwidget(self):
        """A widget to show the pathes to search for additional devices

        """
        self.__devicepathwidget = QtWidgets.QWidget()
        self.__devicepathlab = QtWidgets.QLabel('Devicepathes')  # Button to add a path
        self.__deviceaddpathbtn = QtWidgets.QPushButton('Add')  # Button to add a path
        self.__deviceaddpathbtn.clicked.connect(self.adddevicepath)
        self.__devicerempathbtn = QtWidgets.QPushButton('Remove')  # Button to remove a path
        self.__devicerempathbtn.clicked.connect(self.remdevicepath)
        layout = QtWidgets.QFormLayout(self.__devicepathwidget)
        self.__devicepathlist = QtWidgets.QListWidget()
        layout.addRow(self.__devicepathlab)
        layout.addRow(self.__devicepathlist)
        layout.addRow(self.__deviceaddpathbtn, self.__devicerempathbtn)
        self.__populate_devicepathlistWidget()

    def __populate_devicepathlistWidget(self):
        self.__devicepathlist.clear()
        for d in self.redvypr.device_paths:
            itm = QtWidgets.QListWidgetItem(d)
            self.__devicepathlist.addItem(itm)

    def __property_widget(self, device=None):
        """

        Returns:

        """
        w = QtWidgets.QWidget()
        if (device == None):
            props = self.properties
        else:
            props = device.properties

    def adddevicepath(self):
        """Adds a path to the devicepathlist
        """
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Devicepath', '')
        if folder:
            self.redvypr.adddevicepath(folder)

    def remdevicepath(self):
        """Removes the selected device pathes
        """
        ind = self.__devicepathlist.currentRow()
        rempath = self.__devicepathlist.item(ind).text()
        # Remove from the main widget and redraw the whole list (is done by the signal emitted by redvypr)
        self.redvypr.remdevicepath(rempath)

    def closeTab(self, currentIndex):
        """ Closing a device tab and stopping the device
        """
        logger.debug('Closing the tab now')
        currentWidget = self.devicetabs.widget(currentIndex)
        # Search for the corresponding device
        for sendict in self.redvypr.devices:
            if (sendict['widget'] == currentWidget):
                device = sendict['device']
                if (sendict['thread'] == None):
                    pass
                elif (sendict['thread'].is_alive()):
                    device.comqueue.put('stop')

                    # Close the widgets (init/display)
                currentWidget.close()
                # Info
                sendict['infowidget'].close()
                self.redvypr.devices.remove(sendict)
                self.devicetabs.removeTab(currentIndex)
                break

        self.update_devicewidgetsummary()

    def close_application(self):
        funcname = __name__ + '.close_application():'
        print(funcname + ' Closing ...')
        try:
            self.add_device_widget.close()
        except:
            pass

        for sendict in self.redvypr.devices:
            print(funcname + ' Stopping {:s}'.format(sendict['device'].name))
            sendict['device'].thread_stop()

        time.sleep(1)
        for sendict in self.redvypr.devices:
            try:
                sendict['thread'].kill()
            except:
                pass

        print('All stopped, sys.exit()')
        #sys.exit()
        os._exit(1)

    def closeEvent(self, event):
        self.close_application()


#        
#
# The main widget
#
#
class redvyprMainWidget(QtWidgets.QMainWindow):
    def __init__(self, width=None, height=None, config=None,hostname='redvypr'):
        super(redvyprMainWidget, self).__init__()
        # self.setGeometry(0, 0, width, height)

        self.setWindowTitle("redvypr")
        # Add the icon
        self.setWindowIcon(QtGui.QIcon(_icon_file))

        self.redvypr_widget = redvyprWidget(config=config,hostname=hostname)
        self.setCentralWidget(self.redvypr_widget)
        quitAction = QtWidgets.QAction("&Quit", self)
        quitAction.setShortcut("Ctrl+Q")
        quitAction.setStatusTip('Close the program')
        quitAction.triggered.connect(self.close_application)

        loadcfgAction = QtWidgets.QAction("&Load", self)
        loadcfgAction.setShortcut("Ctrl+O")
        loadcfgAction.setStatusTip('Load a configuration file')
        loadcfgAction.triggered.connect(self.load_config)

        savecfgAction = QtWidgets.QAction("&Save", self)
        savecfgAction.setShortcut("Ctrl+S")
        savecfgAction.setStatusTip('Saves a configuration file')
        savecfgAction.triggered.connect(self.save_config)

        pathAction = QtWidgets.QAction("&Devicepath", self)
        pathAction.setShortcut("Ctrl+L")
        pathAction.setStatusTip('Edit the device path')
        pathAction.triggered.connect(self.redvypr_widget.show_devicepathwidget)

        deviceAction = QtWidgets.QAction("&Add device", self)
        deviceAction.setShortcut("Ctrl+A")
        deviceAction.setStatusTip('Add a device')
        deviceAction.triggered.connect(self.open_add_device_widget)

        devcurAction = QtWidgets.QAction("&Go to device tab", self)
        devcurAction.setShortcut("Ctrl+D")
        devcurAction.setStatusTip('Go to the device tab')
        devcurAction.triggered.connect(self.gotodevicetab)

        conAction = QtWidgets.QAction("&Connect devices", self)
        conAction.setShortcut("Ctrl+C")
        conAction.setStatusTip('Connect the input/output datastreams of the devices')
        conAction.triggered.connect(self.connect_device_gui)

        self.statusBar()

        mainMenu = self.menuBar()
        fileMenu = mainMenu.addMenu('&File')
        fileMenu.addAction(loadcfgAction)
        fileMenu.addAction(savecfgAction)
        fileMenu.addAction(pathAction)
        fileMenu.addAction(quitAction)

        deviceMenu = mainMenu.addMenu('&Devices')
        deviceMenu.addAction(devcurAction)
        deviceMenu.addAction(deviceAction)
        deviceMenu.addAction(conAction)

        # Help and About menu
        toolMenu = mainMenu.addMenu('&Tools')
        toolAction = QtWidgets.QAction("&Choose Device/Datakey ", self)
        toolAction.setStatusTip('Opens a window to choose an available device and/or datakeys')
        toolAction.triggered.connect(self.show_deviceselect)
        consoleAction = QtWidgets.QAction("&Open console", self)
        consoleAction.triggered.connect(self.open_console)
        consoleAction.setShortcut("Ctrl+N")
        IPAction = QtWidgets.QAction("&Network interfaces", self)
        IPAction.triggered.connect(self.open_ipwidget)
        toolMenu.addAction(toolAction)
        toolMenu.addAction(IPAction)
        toolMenu.addAction(consoleAction)

        # Help and About menu
        helpAction = QtWidgets.QAction("&About", self)
        helpAction.setStatusTip('Information about the software version')
        helpAction.triggered.connect(self.about)

        helpMenu = mainMenu.addMenu('&Help')
        helpMenu.addAction(helpAction)

        self.resize(width, height)
        self.show()

    def open_console(self):
        self.redvypr_widget.open_console()

    def open_ipwidget(self):
        self.redvypr_widget.open_ipwidget()

    def gotodevicetab(self):
        self.redvypr_widget.devicetabs.setCurrentWidget(self.redvypr_widget.devicesummarywidget)

    def connect_device_gui(self):
        self.redvypr_widget.connect_device_gui()

    def about(self):
        """
Opens an "about" widget showing basic information.
        """
        self._about_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self._about_widget)
        label1 = QtWidgets.QTextEdit()
        label1.setReadOnly(True)
        label1.setText(__platform__)
        font = label1.document().defaultFont()
        fontMetrics = QtGui.QFontMetrics(font)
        textSize = fontMetrics.size(0, label1.toPlainText())
        w = textSize.width() + 10
        h = textSize.height() + 20
        label1.setMinimumSize(w, h)
        label1.setMaximumSize(w, h)
        label1.resize(w, h)
        label1.setReadOnly(True)

        layout.addWidget(label1)
        icon = QtGui.QPixmap(_logo_file)
        iconlabel = QtWidgets.QLabel()
        iconlabel.setPixmap(icon)
        layout.addWidget(iconlabel)
        self._about_widget.show()

    def show_deviceselect(self):
        self.__deviceselect__ = gui.datastreamWidget(redvypr=self.redvypr_widget.redvypr, deviceonly=True)
        self.__deviceselect__.show()

    def open_add_device_widget(self):
        self.redvypr_widget.open_add_device_widget()

    def load_config(self):
        self.redvypr_widget.load_config()

    def save_config(self):
        self.redvypr_widget.save_config()

    def close_application(self):
        self.redvypr_widget.close_application()

        sys.exit()

    def closeEvent(self, event):
        self.close_application()


#
#
# Main function called from os
#
#
#
def redvypr_main():
    redvypr_help = 'redvypr'
    config_help = 'Using a yaml config file'
    config_help_nogui = 'start redvypr without a gui'
    config_help_path = 'add path to search for redvypr modules'
    config_help_hostname = 'hostname of redvypr, overwrites the hostname in a possible configuration '
    config_help_add = 'add device, can be called multiple times'
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action='count')
    parser.add_argument('--config', '-c', help=config_help)
    parser.add_argument('--nogui', '-ng', help=config_help_nogui, action='store_true')
    parser.add_argument('--add_path', '-p', help=config_help_path)
    parser.add_argument('--hostname', '-hn', help=config_help_hostname)
    parser.add_argument('--add_device', '-a', help=config_help_add, action='append')
    parser.set_defaults(nogui=False)
    args = parser.parse_args()

    logging_level = logging.INFO
    if (args.verbose == None):
        logging_level = logging.INFO
    elif (args.verbose >= 1):
        print('Debug logging level')
        logging_level = logging.DEBUG

    logger.setLevel(logging_level)

    # Check if we have a redvypr.yaml, TODO, add also default path
    config_all = []
    if (os.path.exists('redvypr.yaml')):
        config_all.append('redvypr.yaml')

    # Adding device module pathes
    if (args.add_path is not None):
        # print('devicepath',args.add_path)
        modpath = os.path.abspath(args.add_path)
        # print('devicepath',args.add_path,modpath)
        configp = {'devicepath': modpath}
        # print('Modpath',modpath)
        config_all.append(configp)

    # Add the configuration
    config = args.config
    if (config is not None):
        config_all.append(config)

        # Add device
    if (args.add_device is not None):
        hostconfig = {'devices': []}
        print('devices', args.add_device)
        for d in args.add_device:
            autostart = False
            multiprocess = 'thread'
            if(',' in d):
                options = d.split(',')[1]
                d = d.split(',')[0]
                if('s' in options):
                    autostart = True
                if('p' in options):
                    multiprocess = 'multiprocess'

            dev = {'devicemodulename': d, 'deviceconfig':{'autostart':autostart,'loglevel':logging_level,'mp':multiprocess}}

            hostconfig['devices'].append(dev)
            logger.info('Adding device {:s}, autostart: {:s},'.format(d,str(autostart)))

        config_all.append(hostconfig)

    # Add hostname
    if (args.hostname is not None):
        hostname = args.hostname
    else:
        hostname = 'redvypr'

    logger.debug('Configuration:\n {:s}\n'.format(str(config_all)))
    QtCore.QLocale.setDefault(QtCore.QLocale(QtCore.QLocale.English, QtCore.QLocale.UnitedStates))
    # GUI oder command line?
    if (args.nogui):
        def handleIntSignal(signum, frame):
            '''Ask app to close if Ctrl+C is pressed.'''
            print('Received CTRL-C: Closing now')
            sys.exit()

        signal.signal(signal.SIGINT, handleIntSignal)
        app = QtCore.QCoreApplication(sys.argv)
        redvypr_obj = redvypr(config=config_all, hostname=hostname,nogui=True)
        sys.exit(app.exec_())
    else:
        app = QtWidgets.QApplication(sys.argv)
        screen = app.primaryScreen()
        # print('Screen: %s' % screen.name())
        size = screen.size()
        # print('Size: %d x %d' % (size.width(), size.height()))
        rect = screen.availableGeometry()
        width = int(rect.width() * 4 / 5)
        height = int(rect.height() * 2 / 3)

        logger.debug(
            'Available screen size: {:d} x {:d} using {:d} x {:d}'.format(rect.width(), rect.height(), width, height))
        ex = redvyprMainWidget(width=width, height=height, config=config_all,hostname=hostname)

        sys.exit(app.exec_())


if __name__ == '__main__':
    redvypr_main()







