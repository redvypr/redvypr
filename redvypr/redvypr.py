import copy

import serial
import serial.tools
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
    deviceinfoWidget, redvypr_devicelist_widget, redvypr_deviceInitWidget, redvypr_deviceInfoWidget
from redvypr.utils import addrm_device_as_data_provider, get_data_receiving_devices, get_data_providing_devices
from redvypr.version import version
import redvypr.files as files
from redvypr.device import redvypr_device

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
logger.setLevel(logging.DEBUG)


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

def create_hostinfo():
    funcname = __name__ + '.create_hostinfo()'
    logger.debug(funcname)
    randstr = '{:03d}'.format(random.randrange(2 ** 8))
    redvyprid = datetime.datetime.now().strftime('%Y%m%d%H%M%S.%f-') + str(uuid.getnode()) + '-' + randstr
    hostinfo = {'hostname': 'redvypr', 'tstart': time.time(), 'addr': get_ip(), 'uuid': redvyprid, 'local': True}
    return hostinfo


def treat_datadict(data, devicename, hostinfo, numpacket, tpacket):
    """ Treats a datadict received from a device and adds additional information from redvypr as hostinfo, numpackets etc. 
    """
    # Add deviceinformation to the data package
    if ('device' not in data.keys()):
        data['device'] = str(devicename)
        data['host'] = hostinfo
    else:  # Check if we have a local data packet, i.e. a packet that comes from another redvypr instance with another UUID
        data['host']['local'] = data['host']['uuid'] == hostinfo['uuid']

    # Add the time to the datadict if its not already in
    if ('t' not in data.keys()):
        data['t'] = tpacket

    # Add the packetnumber to the datadict
    if ('numpacket' not in data.keys()):
        data['numpacket'] = numpacket


def distribute_data(devices, hostinfo, infoqueue, dt=0.01):
    """ The heart of redvypr, this functions distributes the queue data onto the subqueues.
    """
    funcname = __name__ + '.distribute_data()'
    dt_info = 1.0  # The time interval information will be sent
    dt_avg = 0  # Averaging of the distribution time needed
    navg = 0
    tinfo = time.time()
    tstop = time.time()
    dt_sleep = dt
    while True:
        time.sleep(dt_sleep)
        tstart = time.time()
        for devicedict in devices:
            device = devicedict['device']
            while True:
                try:
                    data = device.dataqueue.get(block=False)
                    if(type(data) is not dict): # If data is not a dictionary, convert it to one
                        data = {'data':data}
                    devicedict['numpacket'] += 1
                except Exception as e:
                    break

                # Add additional information, if not present yet
                treat_datadict(data, device.name, hostinfo, devicedict['numpacket'], tstart)
                # Do statistics
                try:
                    if devicedict['statistics']['inspect']:
                        devicedict['statistics'] = data_packets.do_data_statistics(data, devicedict['statistics'])
                        # Do a more detailed inspection for the datakey informations. This could be done less often if it turns out to be expensive
                        devicedict['statistics'] = data_packets.do_data_statistics_deep(data, devicedict['statistics'])
                except Exception as e:
                    logger.debug(funcname + ':Statistics:' + str(e))

                if True:
                    # Feed the data into the modules/functions/objects and
                    # let them treat the data
                    for dataout in devicedict['dataout']:
                        devicedict['numpacketout'] += 1
                        try:
                            dataout.put_nowait(data) # These are the datainqueues of the subscribing devices
                        except Exception as e:
                            logger.debug(funcname + ':dataout of :' + devicedict['device'].name + ' full: ' + str(e))
                    for guiqueue in devicedict['guiqueue']:  # Put data into the guiqueue, this queue does always exist
                        try:
                            guiqueue.put_nowait(data)
                        except Exception as e:
                            pass
                            # logger.debug(funcname + ':guiqueue of :' + devicedict['device'].name + ' full')

        # Calculate the sleeping time
        tstop = time.time()
        dt_dist = tstop - tstart  # The time for all the looping
        dt_avg += dt_dist
        navg += 1
        dt_sleep = max([0, dt - dt_dist])
        if ((tstop - tinfo) > dt_info):
            tinfo = tstop
            info_dict = {'dt_avg': dt_avg / navg}
            # print(info_dict)
            try:
                infoqueue.put_nowait(info_dict)
            except:
                pass


class redvypr(QtCore.QObject):
    """This is the redvypr heart. Here devices are added/threads
    are started and data is interchanged

    """
    device_path_changed = QtCore.pyqtSignal()  # Signal notifying if the device path was changed
    device_added = QtCore.pyqtSignal(list)  # Signal notifying if the device path was changed
    devices_connected = QtCore.pyqtSignal(str, str)  # Signal notifying if two devices were connected

    def __init__(self, parent=None, config=None, nogui=False):
        # super(redvypr, self).__init__(parent)
        super(redvypr, self).__init__()
        print(__platform__)
        funcname = __name__ + '.__init__()'
        logger.debug(funcname)
        self.hostinfo = create_hostinfo()
        self.config = {}  # Might be overwritten by parse_configuration()
        self.properties = {}  # Properties that are distributed with the device
        self.numdevice = 0
        self.devices = []  # List containing dictionaries with information about all attached devices
        self.device_paths = []  # A list of pathes to be searched for devices
        self.device_modules = []

        ## A timer to check the status of all threads
        self.devicethreadtimer = QtCore.QTimer()
        self.devicethreadtimer.start(500)

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
        self.devices, self.hostinfo, self.datadistinfoqueue, self.dt_datadist), daemon=True)
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

    def print_status(self):
        funcname = __name__ + '.print_status():'
        print(funcname + self.status())

    def status(self):
        """ Creates a statusstr of the devices
        """
        tstr = str(datetime.datetime.now())
        statusstr = "{:s}, {:s}, num devices {:d}".format(tstr, self.hostinfo['hostname'], len(self.devices))

        for sendict in self.devices:
            try:
                running = sendict['thread'].is_alive()
                runstr = 'running'
            except:
                running = False
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
            logger.warning(funcname + ':This shouldnt happen')

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

                self.add_device(devicemodulename=device['devicemodulename'], deviceconfig=device['deviceconfig'])

        # Connecting devices ['connections']
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
                    # print('provider',devicereceiver,sensprov)
                    # print('receiver',deviceprovider,sensreicv)
                    # print('provider',self.devices[indprovider])#,deviceprovider)
                    # print('receiver',self.devices[indreceiver])
                    # print(devicereceiver)
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

        if ('start' in config.keys()):
            logger.debug('Starting devices')
            if (config['start'] is not None):
                for start_device in config['start']:
                    for s in self.devices:
                        if (s['device'].name == start_device):
                            self.start_device_thread(s['device'])
        return True

    def check_devicename(self, devicename_orig):
        """
        Args:
            devicename_orig:
            
        Returns:
            
        """

        return devicename

    def populate_device_path(self):
        """Searches all device paths for modules and creates a list with the
        found devices in self.device_modules

        """
        funcname = 'populate_device_path()'
        logger.debug(funcname)
        self.device_modules = []  # Clear the list
        # Add all devices from additional folders
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
                hasdevice = False
                try:
                    module.Device
                    hasdevice = True
                except:
                    logger.debug(funcname + ' did not find Device class, will skip.')
                    pass

                if (hasdevice):
                    devdict = {'module': module, 'name': module_name, 'source': module.__file__}
                    self.device_modules.append(devdict)

        # Add all devices from the device module
        max_tries = 5000  # The maximum recursion of modules
        n_tries = 0
        testmodules = [redvyprdevices]
        device_modules = []
        while (len(testmodules) > 0) and (n_tries < max_tries):
            testmodule = testmodules[0]
            device_module_tmp = inspect.getmembers(testmodule, inspect.ismodule)
            for smod in device_module_tmp:
                devicemodule = getattr(testmodule, smod[0])
                # Check if the device is valid
                valid_module = self.valid_device(devicemodule)
                if (valid_module['valid']):  # If the module is valid add it to devices
                    devdict = {'module': devicemodule, 'name': smod[0], 'source': smod[1].__file__}
                    self.device_modules.append(devdict)
                else:  # Check recursive if devices are found
                    n_tries += 1
                    testmodules.append(devicemodule)

            testmodules.pop(0)

    def valid_device(self, devicemodule):
        """ Checks if the module is a valid redvypr module
        """
        funcname = 'valid_device()'
        logger.debug('Checking device {:s}'.format(str(devicemodule)))
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
                except Exception as e:
                    logger.debug(
                        funcname + ':No configuration template of device {:s}: {:s}'.format(str(devicemodule), str(e)))
                    config_template = {}

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
                    deviceconfig['config']['name']
                except:
                    deviceconfig['config']['name'] = devicemodulename + '_' + str(self.numdevice)

                try:
                    deviceconfig['config']['loglevel']
                except:
                    deviceconfig['config']['loglevel'] = 'INFO'

                # Check for multiprocess options in configuration
                if (thread == None):
                    try:
                        multiprocess = deviceconfig['config']['mp'].lower()
                    except:
                        multiprocess = 'thread'
                elif(thread):
                    multiprocess = 'thread'
                else:
                    multiprocess = 'multiprocess'


                if thread:  # Thread or multiprocess
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

                statistics = data_packets.create_data_statistic_dict()
                # Device do not necessarily have a statusqueue
                try:
                    name = deviceconfig['config'].pop('name')
                    loglevel = deviceconfig['config'].pop('loglevel')
                    device_uuid = devicemodulename + '_' + str(uuid.uuid1())
                    try:
                        devicemodule.Device
                        HASDEVICE = True
                    except:
                        HASDEVICE = False

                    if (HASDEVICE):  # Module has its own device
                        Device = devicemodule.Device
                        startfunction = None
                    else:
                        Device = redvypr_device
                        startfunction = devicemodule.start

                    # Config used at all?
                    config = deviceconfig['config']
                    print('Config', config)
                    print('loglevel', loglevel)
                    device = Device(name=name, uuid=device_uuid, config=config, redvypr=self, dataqueue=dataqueue,
                                    publish=publish,subscribe=subscribe,
                                    template=config_template, comqueue=comqueue, datainqueue=datainqueue,
                                    statusqueue=statusqueue, loglevel=loglevel, multiprocess=multiprocess,
                                    numdevice=self.numdevice, statistics=statistics,startfunction=startfunction)



                    self.numdevice += 1
                    # If the device has a logger
                    devicelogger = device.logger
                except Exception as e:
                    print('Exception new style', str(e))

                devicedict = {'device': device, 'thread': None, 'dataout': [], 'gui': [], 'guiqueue': [guiqueue],
                              'statistics': statistics, 'logger': devicelogger}

                # Add the modulename
                devicedict['devicemodulename'] = devicemodulename
                # Add some statistics
                devicedict['numpacket'] = 0
                devicedict['numpacketout'] = 0
                # The displaywcreate_idget, to be filled by redvyprWidget.add_device (optional)
                devicedict['devicedisplaywidget'] = None
                # device = devicedict['device']

                # Add a priori datakeys to the statistics, if the device supports it
                # TODO: Add this as a template parameter
                self.update_statistics_from_apriori_datakeys(device)

                # Check if the device wants a direct start after initialization
                try:
                    autostart = device.autostart
                except:
                    autostart = False

                # Add the device to the device list
                self.devices.append(devicedict)  # Add the device to the devicelist
                ind_device = len(self.devices) - 1

                if (autostart):
                    logger.debug(funcname + ': Starting device')
                    self.start_device_thread(device)

                devicelist = [devicedict, ind_device, devicemodule]

                logger.debug(funcname + ': Emitting device signal')
                self.device_added.emit(devicelist)
                device_found = True
                break

        if (device_found == False):
            logger.warning(funcname + ': Could not add device (not found): {:s}'.format(str(devicemodulename)))

        return devicelist

    def update_statistics_from_apriori_datakeys(self, device):
        """
        """
        funcname = self.__class__.__name__ + '.update_statistics_from_apriori_datakeys():'
        logger.debug(funcname)
        print('device', device)
        # Add a priori datakeys to the statistics, if the device supports it
        try:
            datakeys = device.get_apriori_datakeys()
            logger.debug(funcname + 'Adding datakeys received from .get_datakeys(): {:s}'.format(str(datakeys)))
        except Exception as e:
            logger.debug(funcname + 'Device does not have .get_apriori_datakeys(): {:s}'.format(str(e)))
            datakeys = []

        device.statistics['datakeys'] = list(set(datakeys))
        if (len(device.statistics['datakeys']) > 0):
            # Add also the datastreams
            for dkey in datakeys:
                dstream = self.construct_datastream_from_device_datakey(dkey, device)
                try:
                    info = device.get_apriori_datakey_info(dkey)
                    device.statistics['datastreams_info'][dstream] = info
                except Exception as e:
                    pass

                device.statistics['datastreams'].append(dstream)

            device.statistics['datastreams'] = list(set(device.statistics['datastreams']))

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
        device['thread'] = thread

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

    def construct_datastream_from_device_datakey(self, datakey, device):
        """
        Returns a full datastream from a redvypr device and datakey. Note that the datastream must no exist. 
        Args:
            datakey: str
                The datakey
            device: redvypr_device
                The redvypr device 
        
        
        Returns
        -------
        str
            A str of the datastream
            
        """
        devicename = self.get_devicename_from_device(device)
        datastream = datakey + '/' + devicename
        return datastream

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
        Returns the devicedict based on an devicestr, if not found returns None
        
        Args:
            devicestr (str): 
            
            
        Returns
        -------
        device : dict
            The redvypr devicedict corresponding to the devicestr.
            
        
        """
        deviceparsed = data_packets.parse_devicestring(devicestr, local_hostinfo=self.hostinfo)
        for d in self.devices:
            flag_name = d['device'].name == deviceparsed['devicename']
            flag_name = flag_name or deviceparsed['deviceexpand']

            flag_hostname = self.hostinfo['hostname'] == deviceparsed['hostname']
            flag_hostname = flag_hostname or deviceparsed['hostexpand']

            flag_addr = self.hostinfo['addr'] == deviceparsed['addr']
            flag_addr = flag_addr or deviceparsed['addrexpand']

            flag_UUID = self.hostinfo['uuid'] == deviceparsed['uuid']
            flag_UUID = flag_UUID or deviceparsed['uuidexpand']

            flag_local = deviceparsed['local']
            if (flag_name and flag_local) or (flag_name and flag_UUID) or (flag_name and flag_addr and flag_hostname):
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
        """
        funcname = self.__class__.__name__ + '.get_datastream_providing_device():'
        logger.debug(funcname)
        datastreamparsed = parse_devicestring(datastream, local_hostinfo=self.hostinfo)
        for dev in self.devices:
            datastreamlist.extend(dev['statistics']['datastreams'])

    def get_datastream_info(self, datastream):
        """ Gets additional information to the datastream, namely the data that is stored in the ?[datakey] dictionary entry
        """

        datastreams = self.get_datastreams()
        datastreaminfo = {}
        for dev in self.devices:
            datastreaminfo |= dev['statistics']['datastreams_info']

        for dstream in datastreaminfo.keys():
            if (data_packets.compare_datastreams(datastream, dstream)):
                return datastreaminfo[dstream]

        return None

    def get_datastreams(self, device=None, format='uuid'):
        """
        Gets datastreams from a device (or all devices if device == None).
        Args:
            device: (redvypr_device or str):
            format:
            
        Returns
        -------
        list
            A list containing the datastreams
        """
        funcname = self.__class__.__name__ + '.get_datastreams():'
        datastreamlist = []

        if (type(device) == str):
            datastreams_all = []
            for dev in self.devices:
                datastreams_all.extend(dev['statistics']['datastreams'])
            datastreams_all = list(set(datastreams_all))
            # Parse the devicestring
            deviceparsed = parse_devicestring(device, local_hostinfo=self.hostinfo)
            ##print('datastreams',datastreams_all)
            ##print('deviceparsed',deviceparsed)
            for stream in datastreams_all:
                datastream_parsed = parse_devicestring(stream, local_hostinfo=self.hostinfo)
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

    def rm_all_data_provider(self, device):
        """
        Remove all devices that provide data
        Args:
            device: The redvypr device
        """
        funcname = self.__class__.__name__ + '.rm_all_data_provider():'
        logger.debug(funcname)
        dataprovider = self.get_data_providing_devices(device)
        for provider in dataprovider:
            self.addrm_device_as_data_provider(provider, device, remove=True)

    def addrm_device_as_data_provider(self, deviceprovider, devicereceiver, remove=False):
        """ Adding/removing devices as dataprovider for the device devicereceiver
        Arguments:
        deviceprovider: The device (type Device) or devicename (type str Device.name)
        devicerreceiver: The device (type Device) or devicename (type str Device.name)
        remove: False for adding, True for removing
        """
        if (type(deviceprovider) == str):
            deviceprovider = self.get_device_from_str(deviceprovider)

        if (type(devicereceiver) == str):
            devicereceiver = self.get_device_from_str(devicereceiver)

        ret = addrm_device_as_data_provider(self.devices, deviceprovider, devicereceiver, remove=remove)
        # Emit a connection signal
        self.devices_connected.emit(deviceprovider.name, devicereceiver.name)
        return ret


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

    def __init__(self, width=None, height=None, config=None):
        """ Args: 
            width:
            height:
            config: Either a string containing a path of a yaml file, or a list with strings of yaml files
        """
        super(redvyprWidget, self).__init__()
        self.setGeometry(50, 50, 500, 300)

        # Lets create the heart of redvypr
        self.redvypr = redvypr()  # Configuration comes later after all widgets are initialized

        self.redvypr.device_path_changed.connect(self.__populate_devicepathlistWidget)
        self.redvypr.device_added.connect(self._add_device)
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
                dev['device'].name = name
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
        """This periodically called functions reads the guiqueue and calls
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
                            devicedict['gui'][i].update(data)
                        except Exception as e:
                            break

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

    def _add_device(self, devicelist):
        """ Function is called via the redvypr.add_device signal and is adding
        all the gui functionality to the device

        """
        funcname = __name__ + '.add_device()'
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
            deviceinitwidget_bare = redvypr_deviceInitWidget  # Use a standard widget

        try:
            deviceinitwidget = deviceinitwidget_bare(device)
        except Exception as e:
            logger.warning(funcname + ': Widget does not have a deviceinitwidget:' + str(e))
            deviceinitwidget = QtWidgets.QWidget()  # Use a standard widget

        try:
            logger.debug(funcname + ': Connect signal connected')
            deviceinitwidget.connect.connect(self.connect_device)
        except Exception as e:
            logger.debug('Widget does not have connect signal:' + str(e))


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

        devicewidget = QtWidgets.QWidget()
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

            # https://stackoverflow.com/questions/334655/passing-a-dictionary-to-a-function-as-keyword-parameters
            devicedisplaywidget_called = devicedisplaywidget(**initdict)

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
        self.open_connect_widget(device=None)

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
        self.__con_widget = redvyprConnectWidget(devices=self.redvypr.devices, device=device)
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

    def update_status(self):
        while True:
            try:
                data = self.datadistinfoqueue.get(block=False)
                self.dt_avg_datadist = data['dt_avg']
            except Exception as e:
                break
        self.__status_dtneeded.setText(' (needed {:0.5f}s)'.format(self.redvypr.dt_avg_datadist))

    def create_statuswidget(self):
        """Creates the statuswidget

        """
        self.redvypr.devicethreadtimer.timeout.connect(self.update_status)  # Add to the timer another update
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
        # Change the hostname
        self.__hostname_btn = QtWidgets.QPushButton('Change hostname')
        self.__hostname_btn.clicked.connect(self.__hostname_changed_click)

        layout.addRow(self.__hostname_label, self.__hostname_line)
        layout.addRow(self.__uuid_label, self.__uuid_line)
        layout.addRow(self.__ip_label, self.__ip_line)
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
        logger.debug(funcname + ' Closing ...')
        try:
            self.add_device_widget.close()
        except:
            pass

        for sendict in self.redvypr.devices:
            sendict['device'].thread_stop()

        time.sleep(1)
        for sendict in self.redvypr.devices:
            try:
                sendict['thread'].kill()
            except:
                pass

        # sys.exit()

    def closeEvent(self, event):
        self.close_application()


#        
#
# The main widget
#
#
class redvyprMainWidget(QtWidgets.QMainWindow):
    def __init__(self, width=None, height=None, config=None):
        super(redvyprMainWidget, self).__init__()
        # self.setGeometry(0, 0, width, height)

        self.setWindowTitle("redvypr")
        # Add the icon
        self.setWindowIcon(QtGui.QIcon(_icon_file))

        self.redvypr_widget = redvyprWidget(config=config)
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
        self.__deviceselect__ = redvypr_devicelist_widget(redvypr=self.redvypr_widget.redvypr, deviceonly=True)
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
# A splash screen
#
#

class SplashScreen(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(700, 350)
        self.setWindowFlag(QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.counter = 0
        self.n = 50
        # self.initUI()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.count)
        self.timer.start(100)

    def count(self):
        # set progressbar value
        # self.progressBar.setValue(self.counter)
        # stop progress if counter
        # is greater than n and
        # display main window app
        if self.counter >= self.n:
            self.timer.stop()
            self.close()
            time.sleep(1)
            ## Start the main application
            # self.main_window()
        self.counter += 1


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
            logger.info('Adding device {:s}'.format(d))
            dev = {'devicemodulename': d}
            hostconfig['devices'].append(dev)

        config_all.append(hostconfig)

    # Add hostname
    if (args.hostname is not None):
        hostconfig = {'hostname': args.hostname}
        config_all.append(hostconfig)

    logger.debug('Configuration:\n {:s}\n'.format(str(config_all)))
    # GUI oder command line?
    if (args.nogui):
        def handleIntSignal(signum, frame):
            '''Ask app to close if Ctrl+C is pressed.'''
            print('Received CTRL-C: Closing now')
            sys.exit()

        signal.signal(signal.SIGINT, handleIntSignal)
        app = QtCore.QCoreApplication(sys.argv)
        redvypr_obj = redvypr(config=config_all, nogui=True)
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
        ex = redvyprMainWidget(width=width, height=height, config=config_all)

        sys.exit(app.exec_())


if __name__ == '__main__':
    redvypr_main()
