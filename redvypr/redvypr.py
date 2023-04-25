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
import redvypr.data_packets as data_packets
from redvypr.gui import redvypr_ip_widget, QPlainTextEditLogger, displayDeviceWidget_standard, \
    deviceinfoWidget, datastreamWidget, redvypr_deviceInitWidget, redvypr_deviceInfoWidget
import redvypr.gui as gui
from redvypr.config import configuration
import redvypr.config as redvyprconfig
from redvypr.version import version
import redvypr.files as files
from redvypr.device import redvypr_device, redvypr_device_scan
import redvypr.devices as redvyprdevices
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




def distribute_data(devices, hostinfo, deviceinfo_all, infoqueue, redvyprqueue, dt=0.01):
    """ The heart of redvypr, this functions distributes the queue data onto the subqueues.
    """
    funcname = __name__ + '.distribute_data()'
    datastreams_all = {}
    datastreams_all_old = {}
    dt_info = 5.0  # The time interval information will be sent
    dt_avg = 0  # Averaging of the distribution time needed
    navg = 0
    packets_processed = 0 # For statistics, count packets
    tinfo = time.time()
    tstop = time.time()
    dt_sleep = dt


    while True:
        time.sleep(dt_sleep)
        tstart = time.time()
        FLAG_device_status_changed = False
        devices_changed = []
        devices_removed = []
        # Read data from the main thread
        try:
            redvyprdata = redvyprqueue.get(block=False) # Data from the main thread
        except Exception as e:
            redvyprdata = None
        # Process data from the main thread
        if(redvyprdata is not None):
            if(redvyprdata['type'] == 'device_removed'):
                print('Device removed',redvyprdata)
                FLAG_device_status_changed = True
                devices_removed.append(redvyprdata['device'])
                devinfo_rem = deviceinfo_all.pop(redvyprdata['device'])
                #print('Devices len distribute data', len(devices))
                devinfo_send = {'type':'deviceinfo_all', 'deviceinfo_all': copy.deepcopy(deviceinfo_all), 'devices_changed': list(set(devices_changed)),
                'devices_removed': devices_removed,'change':'devrem','device_changed':redvyprdata['device']}
                infoqueue.put_nowait(devinfo_send)


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

                    devicedict['packets_sent'] += 1
                    packets_processed += 1
                    data_all.append(data)
                except Exception as e:
                    break
            # Process read packets
            for data in data_all:
                #
                # Add additional information, if not present yet
                data_packets.treat_datadict(data, device.name, hostinfo, devicedict['packets_sent'], tread,devicedict['devicemodulename'])
                # Get the devicename
                devicename_stat = data_packets.get_devicename_from_data(data, uuid=True)
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
                numtag = data['_redvypr']['tag'][hostinfo['uuid']]
                if numtag < 2:  # Check if data packet fits with addr and its not recirculated again
                    [command, comdata] = data_packets.check_for_command(data, add_data=True)
                    if (command == 'device_status'):  # status update
                        #print('device status command',device.name)
                        #print('comdata',comdata)
                        #print('data', data)
                        try:
                            devaddr   = comdata['data']['deviceaddr']
                            devstatus = comdata['data']['devicestatus']
                        except:
                            devaddr = None
                            devstatus = None

                        devices_changed.append(device.name) # LEGACY ...
                        if(devaddr is not None):
                            try: # Update the device
                                devicedict['statistics']['device_redvypr'][devaddr]['_redvypr'].update(devstatus)
                            except Exception as e:
                                logger.warning('Could not update status ' + str(e))
                                logger.exception(e)

                        # Send an information about the change, that will trigger an pyqt signal in the main thread
                        devinfo_send = {'type': 'deviceinfo_all', 'deviceinfo_all': copy.deepcopy(deviceinfo_all),
                                        'devices_changed': list(set(devices_changed)), 'device_changed':device.name,
                                        'devices_removed': devices_removed, 'change': 'device_status command','comdata':comdata}
                        infoqueue.put_nowait(devinfo_send)

                #
                # Create a dictionary of all datastreams
                #
                datastreams_all.update(devicedict['statistics']['datastream_redvypr'])
                try:
                    deviceinfo_all[device.name].update(devicedict['statistics']['device_redvypr'])
                except:
                    deviceinfo_all[device.name] = devicedict['statistics']['device_redvypr']

                #
                # Compare if datastreams changed
                #
                if (list(datastreams_all.keys()) != list(datastreams_all_old.keys())):
                    #print('Datastreams changed', len(datastreams_all.keys()))
                    datastreams_all_old.update(datastreams_all)
                    devices_changed.append(device.name)
                    # Send an information about the change, that will trigger an pyqt signal in the main thread
                    devinfo_send = {'type': 'deviceinfo_all', 'deviceinfo_all': copy.deepcopy(deviceinfo_all),
                                    'devices_changed': list(set(devices_changed)),
                                    'devices_removed': devices_removed, 'change': 'datastreams changed','device_changed':device.name}
                    infoqueue.put_nowait(devinfo_send)

                #
                # And finally: Distribute the data
                #
                for devicedict_sub in devices:
                    devicesub = devicedict_sub['device']
                    if(devicesub == device): # Not to itself
                        continue

                    for addr in devicesub.subscribed_addresses: # Loop over all subscribed redvypr_addresses
                        # This is the main functionality for sitribution, comparing a datapacket with a
                        # redvypr_address using "in"
                        if (data in addr) and (numtag < 2): # Check if data packet fits with addr and if its not recirculated again
                            try:
                                devicesub.datainqueue.put_nowait(data) # These are the datainqueues of the subscribing devices
                                devicedict['packets_received'] += 1
                                devicedict['statistics']['device_redvypr'][devicename_stat]['packets_received'] += 1
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

        #if FLAG_device_status_changed:
            #infoqueue.put_nowait(copy.copy(datastreams_all))
            #devinfo_send = {'type':'deviceinfo_all', 'deviceinfo_all': copy.deepcopy(deviceinfo_all), 'devices_changed': list(set(devices_changed)),
            # 'devices_removed': devices_removed,''}
            #infoqueue.put_nowait(devinfo_send)

        # Calculate the sleeping time
        tstop = time.time()
        dt_dist = tstop - tstart  # The time for all the looping
        dt_avg += dt_dist
        navg += 1
        dt_sleep = max([0, dt - dt_dist])
        if ((tstop - tinfo) > dt_info):
            tinfo = tstop
            info_dict = {'type':'dt_avg','dt_avg': dt_avg / navg,'packets_processed': packets_processed}
            packets_processed = 0
            # print(info_dict)
            try:
                infoqueue.put_nowait(info_dict)
            except:
                pass


class redvypr(QtCore.QObject):
    """This is the redvypr heart. Here devices are added/threads
    are started and data is interchanged

    """
    device_path_changed          = QtCore.pyqtSignal()  # Signal notifying if the device path was changed
    device_added                 = QtCore.pyqtSignal(list)  # Signal notifying that a device was added
    device_removed               = QtCore.pyqtSignal()  # Signal notifying that a device was removed
    devices_connected            = QtCore.pyqtSignal(str, str)  # Signal notifying if two devices were connected
    devices_disconnected         = QtCore.pyqtSignal(str, str)  # Signal notifying if two devices were connected
    status_update_signal         = QtCore.pyqtSignal()  # Signal notifying if the status of redvypr has been changed
    device_status_changed_signal = QtCore.pyqtSignal()  # Signal notifying if datastreams have been added
    hostconfig_changed_signal    = QtCore.pyqtSignal()  # Signal notifying if the configuration of the host changed (hostname, hostinfo_opt)

    def __init__(self, parent=None, config=None, hostname='redvypr',hostinfo_opt = {}, nogui=False):
        # super(redvypr, self).__init__(parent)
        super(redvypr, self).__init__()
        print(__platform__)
        funcname = __name__ + '.__init__()'
        logger.debug(funcname)
        self.hostinfo = create_hostinfo(hostname=hostname)
        print('Hostinfo opt',hostinfo_opt)
        try:
            hostinfo_opt['description']
        except:
            hostinfo_opt['description'] = ''

        try:
            hostinfo_opt['location']
        except:
            hostinfo_opt['location'] = ''

        try:
            hostinfo_opt['lon']
        except:
            hostinfo_opt['lon'] = -9999.0

        try:
            hostinfo_opt['lat']
        except:
            hostinfo_opt['lat'] = -9999.0

        self.hostinfo_opt = configuration(template=hostinfo_opt)

        self.config = {}  # Might be overwritten by parse_configuration()
        self.properties = {}  # Properties that are distributed with the device
        self.numdevice = 0
        self.devices = []  # List containing dictionaries with information about all attached devices
        self.device_paths = []  # A list of pathes to be searched for devices
        self.datastreams_dict = {} # Information about all datastreams, this is updated by distribute data
        self.deviceinfo_all   = {} # Information about all devices, this is updated by distribute data



        self.dt_datadist = 0.01  # The time interval of datadistribution
        self.dt_avg_datadist = 0.00  # The time interval of datadistribution
        self.datadistinfoqueue = queue.Queue(maxsize=1000)  # A queue to get informations from the datadistthread
        self.redvyprqueue = queue.Queue()  # A queue to send informations to the datadistthread
        # Lets start the distribution!
        self.datadistthread = threading.Thread(target=distribute_data, args=(
        self.devices, self.hostinfo, self.deviceinfo_all, self.datadistinfoqueue, self.redvyprqueue, self.dt_datadist), daemon=True)
        self.datadistthread.start()
        logger.info(funcname + ':Searching for devices')
        self.redvypr_device_scan = redvypr_device_scan(device_path = self.device_paths,redvypr_devices=redvyprdevices)
        logger.info(funcname + ':Done searching for devices')

        # Parsing configuration
        self.parse_configuration(config)

        ## A timer to check the status of all threads
        self.devicethreadtimer = QtCore.QTimer()
        self.devicethreadtimer.timeout.connect(self.update_status)  # Add to the timer another update
        self.devicethreadtimer.start(250)


        ## A timer to print the status in the nogui environment
        if (nogui):
            self.statustimer = QtCore.QTimer()
            self.statustimer.timeout.connect(self.print_status)
            self.statustimer.start(5000)

    def get_deviceinfo(self,publishes=None,subscribes=None):
        """

        Args:
            publishes:
            subscribes:

        Returns:
            A dictionary containing the deviceinfo of all devices seen by this redvypr instance
        """
        if (publishes == None) and (subscribes == None):
            return copy.deepcopy(self.deviceinfo_all)
        else:
            dinfo = {}
            for d in self.devices:
                dev = d['device']
                FLAG_publishes   =   (publishes == dev.publishes) or (publishes == None)
                FLAG_subscribes  = (subscribes == dev.subscribes) or (subscribes == None)
                if FLAG_publishes and FLAG_subscribes:
                    dinfo[dev.name] = copy.deepcopy(dev.statistics['device_redvypr'])

            return dinfo

    def update_status(self):
        funcname = __name__ + '.update_status():'
        # Check if the distribution thread is running, if not warn the user
        if self.datadistthread.is_alive() == False:
            logger.warning('Datadistribution thread is not running! This is bad, consider restarting redvypr.')
            self.status_update_signal.emit()
            return

        while True:
            try: # Reading data coming from distribute_data thread
                data = self.datadistinfoqueue.get(block=False)
                #print('Got data',data)
                if('dt_avg' in data['type']):
                    self.dt_avg_datadist   = data['dt_avg']
                    self.packets_processed = data['packets_processed']
                    self.status_update_signal.emit()
                elif ('deviceinfo_all' in data['type']):
                    data.pop('type')  # Remove the type key
                    # Store the data of the changed devices
                    self.__device_status_changed_data__ = data

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

            statusstr += '\n\t' + sendict['device'].name + ':' + runstr + ': data packets sent: {:d}' + ': data packets received: {:d}'.format(
                sendict['packets_sent'],sendict['packets_received'])
            # statusstr += ': data packets received: {:d}'.format(sendict['numpacketout'])

        return statusstr

    def get_config(self):
        """
        Creates a configuration dictionary out of the current state.

        Returns:
            config: configuration dictionary

        """
        config = {}

        config['hostname']     = self.hostinfo['hostname']
        config['hostinfo_opt'] = copy.deepcopy(self.hostinfo_opt)
        config['devicepath']   = []
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
            devsave['deviceconfig']['autostart'] = device.autostart

            devsave['devicemodulename']         = devicedict['devicemodulename']
            devconfig = device.config
            devsave['deviceconfig']['config'] = copy.deepcopy(devconfig)
            # Treat subscriptions
            devsave['deviceconfig']['subscriptions'] = []
            for raddr in device.subscribed_addresses:
                devsave['deviceconfig']['subscriptions'].append(raddr.address_str)

            config['devices'].append(devsave)


        return config

    def parse_configuration(self, redvypr_config=None):
        """ Parses a dictionary with a configuration, if the file does not exists it will return with false, otherwise self.config will be updated

        Arguments:
            redvypr_config (str, dict or list of strs and dicts):
        Returns:
            True or False
        """
        funcname = "parse_configuration()"
        parsed_devices = []
        logger.debug(funcname)

        if (redvypr_config is not None):
            logger.debug(funcname + ':Configuration: ' + str(redvypr_config))
            if (type(redvypr_config) == str):
                redvypr_config = [redvypr_config]
        else:
            return False

        config = {} # This is a merged config of all configurations
        for configraw in redvypr_config:
            if (type(configraw) == str):
                logger.info(funcname + ':Opening yaml file: ' + str(configraw))
                if (os.path.exists(configraw)):
                    fconfig = open(configraw)
                    config_tmp = yaml.load(fconfig, Loader=yaml.loader.SafeLoader)
                else:
                    logger.warning(funcname + ':Yaml file: ' + str(configraw) + ' does not exist!')
                    continue
            elif(type(configraw) == dict):
                logger.info(funcname + ':Opening dictionary')
                config_tmp = configraw
            else:
                logger.warning(funcname + ': Unknown type of configuration {:s}'.format(type(configraw)))
                continue

            # Merge the configuration into one big dictionary
            config.update(config_tmp)

        # Apply the merged configuration
        if True:
            #self.config = config
            if ('loglevel' in config.keys()):
                logger.setLevel(config['loglevel'])
            # Add device path if found
            if ('devicepath' in config.keys()):
                devpath = config['devicepath']

                if (type(devpath) == str):
                    devpath = [devpath]

                FLAG_NEW_DEVPATH=False
                for p in devpath:
                    if (p not in self.device_paths):
                        self.device_paths.append(p)
                        FLAG_NEW_DEVPATH = True

                if FLAG_NEW_DEVPATH:
                    self.redvypr_device_scan.scan_devicepath()
                    self.device_path_changed.emit()  # Notify about the changes

            # Check for hostinformation
            # Add the hostname
            try:
                logger.info(funcname + ': Setting hostname to {:s}'.format(config['hostname']))
                self.hostinfo['hostname'] = config['hostname']
            except:
                pass

            try:
                logger.info(funcname + ': Setting optional hostinfomation: {:s}'.format(str(config['hostinfo_opt'])))
                c = redvyprconfig.dict_to_configDict(config['hostinfo_opt'])
                self.hostinfo_opt.update(c)
            except Exception as e:
                #logger.exception(e)
                pass


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

                    # Check if the devicemodulename kind of fits
                    FLAG_MOD_DEVICEMODULENAME = True
                    for smod in self.redvypr_device_scan.redvypr_devices_flat:
                        if (device['devicemodulename'] == smod['name']):
                            FLAG_MOD_DEVICEMODULENAME = False

                    if FLAG_MOD_DEVICEMODULENAME:
                        for smod in self.redvypr_device_scan.redvypr_devices_flat:
                            if (device['devicemodulename'] in smod['name']): # This is a weaker test, can be potentially replaced by regex
                                device['devicemodulename_orig'] = device['devicemodulename']
                                device['devicemodulename'] = smod['name']

                    dev_added = self.add_device(devicemodulename=device['devicemodulename'], deviceconfig=device['deviceconfig'])

                    # Subscriptions
                    # Name
                    #
                    parsed_devices.append(dev_added)


            # Autostart the device, if wanted
            #for dev in parsed_devices:
            #    device = dev[0]['device']
            #    if(device.autostart):
            #        device.thread_start()

            # Emit a signal that the configuration has been changed
        self.hostconfig_changed_signal.emit()
        return True


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
        for smod in self.redvypr_device_scan.redvypr_devices_flat:
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

                # Try to get information about the maximum number of devices
                try:
                    max_devices = config_template['redvypr_device']['max_devices']
                except:
                    max_devices = -1

                if(max_devices > 0):
                    ndevices = 0
                    for d in self.devices:
                        devname = d['device'].devicemodulename
                        if(devname == devicemodulename):
                            ndevices += 1

                    if ndevices >= max_devices:
                        logger.warning(funcname + ' Could not add {:s}, maximum number of {:d} devices reached'.format(devicemodulename,max_devices))
                        return

                # Try to get information about publish/subscribe capabilities described in the config_template
                try:
                    publishes = config_template['redvypr_device']['publishes']
                except:
                    publishes = False
                try:
                    subscribes = config_template['redvypr_device']['subscribes']
                except:
                    subscribes = False

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
                                    publishes=publishes,subscribes=subscribes,autostart=autostart,
                                    template=config_template, comqueue=comqueue, datainqueue=datainqueue,
                                    statusqueue=statusqueue, loglevel=loglevel, multiprocess=multiprocess,
                                    numdevice=self.numdevice, statistics=statistics,startfunction=startfunction,devicemodulename=devicemodulename)

                    device.subscription_changed_signal.connect(self.process_subscription_changed)
                    self.numdevice += 1
                    # If the device has a logger
                    devicelogger = device.logger
                except Exception as e:
                    logger.warning(funcname + ' Could not add device because of:')
                    logger.exception(e)


                devicedict = {'device': device, 'dataout': [], 'gui': [], 'guiqueue': [guiqueue],
                              'statistics': statistics, 'logger': devicelogger,'comqueue':comqueue}

                # Add the modulename
                devicedict['devicemodulename'] = devicemodulename
                # Add some statistics (LEGACY)
                devicedict['packets_received'] = 0
                devicedict['packets_sent'] = 0
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

                # Update the statistics of the device itself
                deviceinfo_packet = {'_redvypr':{},'_deviceinfo': {'subscribes': subscribes, 'publishes': publishes, 'devicemodulename': devicemodulename}}
                device.dataqueue.put(deviceinfo_packet)
                # Send a device_status packet to notify that a new device was added (deviceinfo_all) is updated
                datapacket = data_packets.commandpacket(command='device_status')
                device.dataqueue.put(datapacket)
                if (autostart):
                    logger.info(funcname + ': Starting device')
                    self.start_device_thread(device)

                devicelist = [devicedict, ind_device, devicemodule]

                #
                # Subscribe to devices
                #
                try:
                    subscribe_addresses =  deviceconfig['subscriptions']
                except:
                    subscribe_addresses = []

                print('Subscribing to ...')
                for a in subscribe_addresses:
                    print('subscribing',a)
                    device.subscribe_address(a)

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
                if (sendict['device'].thread == None):
                    return
                elif (sendict['device'].thread.is_alive()):
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

                    device.thread_stop()

                else:
                    logger.warning(funcname + ': Could not stop thread.')

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


    def get_devices(self, publishes = None, subscribes = None):
        """
        Returns a list of all devices of this redvypr instance. Returns all devices if "publishes" or "subscribes" is None.
        Otherwise according to the publishes/subscribes flags
        Args:
            publishes: True/False or None.
            subscribes: True/False or None

        Returns: List with redvypr_devices

        """

        devicelist = []
        for d in self.devices:
            dev = d['device']
            if publishes == True:
                if(dev.publishes):
                    devicelist.append(dev)
                    continue
            elif publishes is None:
                devicelist.append(dev)
                continue

            if (subscribes):
                if (dev.subscribes):
                    devicelist.append(dev)
                    continue
            elif subscribes is None:
                devicelist.append(dev)
                continue


        return devicelist

    def get_deviceaddresses(self, local = None, publishes = None, subscribes = None):
        """
        Returns a list of redvypr_addresses of all devices. If local == None all known devices are listed,
        also of all remote devices that are forwarded by a local host device (i.e. iored device).


        Args:
            local [bool/None]: None: all known devices are listed, False: Remote devices are listed, True: local devices are listed

        Returns: List of redvypr_addresses


        """
        raddrs = []
        for dev in self.devices:
            raddrs_tmp = dev['device'].get_deviceaddresses(local)
            raddrs.extend(raddrs_tmp)

        return raddrs

    def get_datastreams(self,local=None):
        """

        Args:
            local:

        Returns:

        """
        datastreams = []
        for dev in self.devices:
            raddrs_tmp = dev['device'].get_datastreams()
            datastreams.extend(raddrs_tmp)

        return datastreams


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
        for d in self.redvypr_device_scan.redvypr_devices_flat:
            devices.append(d['name'])

        return devices

    def rem_device(self,device):
        """
        Removes a device, after the removal a signal for device change is sent
        Args:
            device: redvypr_device

        Returns:

        """
        funcname = self.__class__.__name__ + '.rem_device():'
        logger.debug(funcname)
        FLAG_REMOVED = False
        for sendict in self.devices:
            if(sendict['device'] == device):
                print('Sendict',sendict)
                if (sendict['device'].thread == None):
                    logger.debug(funcname + 'Thread is not runnung, doing nothing')
                    pass
                elif (sendict['device'].thread.is_alive()):
                    logger.debug(funcname + 'Sending stop command')
                    device.thread_stop()

                self.devices.remove(sendict)
                FLAG_REMOVED = True
                self.device_removed.emit()
                device_changed_dict = {'type':'device_removed','device':device.name,'uuid':device.uuid}
                self.redvyprqueue.put(device_changed_dict)
                break

        return FLAG_REMOVED





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

    def __init__(self, width=None, height=None, config=None,hostname='redvypr',hostinfo_opt={}):
        """ Args: 
            width:
            height:
            config: Either a string containing a path of a yaml file, or a list with strings of yaml files
        """
        super(redvyprWidget, self).__init__()
        self.setGeometry(50, 50, 500, 300)

        # Lets create the heart of redvypr
        self.redvypr = redvypr(hostname=hostname,hostinfo_opt=hostinfo_opt)  # Configuration comes later after all widgets are initialized

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
        if False:
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

        self.redvypr.parse_configuration(config)
        # Update hostinformation widgets
        self.__update_hostinfo_widget__()
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
        self.add_device_widget = gui.redvyprDeviceWidget(redvypr=self.redvypr)
        self.add_device_widget.show()

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

        # Connect the connect signal with connect_device()
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
        self.__con_widget = gui.redvyprSubscribeWidget(redvypr=self.redvypr, device=device)
        self.__con_widget.show()

    def __hostname_changed_click(self):
        hostname, ok = QtWidgets.QInputDialog.getText(self, 'redvypr hostname', 'Enter new hostname:')
        if ok:
            self.redvypr.hostinfo['hostname'] = hostname
            self.__hostname_line.setText(hostname)

    def __update_hostinfo_widget__(self):
        """
        Updates the hostinformation
        Returns:

        """
        funcname = __name__ + '.__update_hostinfo_widget__()'
        print(funcname)


    def __update_status_widget__(self):
        """
        Updates the status information
        Returns:

        """
        if self.redvypr.datadistthread.is_alive() == False:
            self.__status_dt.setText(
                'Datadistribution thread is not running! This is bad, consider restarting redvypr.')
            self.__status_dt.setStyleSheet("QLabel { background-color : white; color : red; }")
            self.__status_dtneeded.setText('')
        else:
            npackets = self.redvypr.packets_processed
            if(npackets > 0):
                packets_pstr = npackets / self.redvypr.dt_avg_datadist
            else:
                packets_pstr = 0.0
            self.__status_dtneeded.setText(' (needed {:0.5f}s, {:6.1f} packets/s)'.format(self.redvypr.dt_avg_datadist,packets_pstr))

    def create_statuswidget(self):
        """Creates the statuswidget

        """
        self.redvypr.status_update_signal.connect(self.__update_status_widget__)
        self.redvypr.hostconfig_changed_signal.connect(self.__update_hostinfo_widget__)
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

        # Location
        try:
            location = self.redvypr.hostinfo_opt['location'].data
        except:
            location = ''

        self.__loc_label = QtWidgets.QLabel('Location:')
        self.__loc_text = QtWidgets.QLineEdit(location)
        self.__loc_text.textold = self.__loc_text.text() # the old text to check again
        self.__loc_text.editingFinished.connect(self.__hostinfo_opt_changed_text)

        # Description
        try:
            description = self.redvypr.hostinfo_opt['description'].data
        except:
            description = ''

        self.__desc_label = QtWidgets.QLabel('Description:')
        self.__desc_text = QtWidgets.QLineEdit(description)
        self.__desc_text.textold = self.__desc_text.text()  # the old text to check again
        self.__desc_text.editingFinished.connect(self.__hostinfo_opt_changed_text)

        # Lon
        try:
            lon = self.redvypr.hostinfo_opt['lon'].data
        except:
            lon = -9999.0

        # Lon/Lat
        try:
            lat = self.redvypr.hostinfo_opt['lat'].data
        except:
            lat = -9999.0


        self.__lon_label = QtWidgets.QLabel('Longitude:')
        self.__lat_label = QtWidgets.QLabel('Latitude:')
        self.__lon_text = QtWidgets.QDoubleSpinBox()
        self.__lon_text.setMinimum(-9999)
        self.__lon_text.setMaximum(360)
        self.__lon_text.setSingleStep(0.00001)
        self.__lon_text.setDecimals(5)
        self.__lon_text.setValue(lon)
        self.__lon_text.oldvalue = self.__lon_text.value()
        self.__lon_text.editingFinished.connect(self.__hostinfo_opt_changed_text)

        self.__lat_text = QtWidgets.QDoubleSpinBox()
        self.__lat_text.setMinimum(-9999)
        self.__lat_text.setMaximum(90)
        self.__lat_text.setSingleStep(0.00001)
        self.__lat_text.setDecimals(5)
        self.__lat_text.setValue(lat)
        self.__lat_text.oldvalue = self.__lat_text.value()
        self.__lat_text.editingFinished.connect(self.__hostinfo_opt_changed_text)

        # Change the hostname
        self.__hostinfo_opt_btn = QtWidgets.QPushButton('Edit optional information')
        self.__hostinfo_opt_btn.clicked.connect(self.__hostinfo_opt_changed_click)



        self.__statuswidget_pathbtn = QtWidgets.QPushButton('Edit device path')
        self.__statuswidget_pathbtn.clicked.connect(self.show_devicepathwidget)

        layout.addRow(self.__hostname_label, self.__hostname_line)
        layout.addRow(self.__uuid_label, self.__uuid_line)
        layout.addRow(self.__ip_label, self.__ip_line)
        layout.addRow(self.__desc_label, self.__desc_text)
        layout.addRow(self.__loc_label, self.__loc_text)
        layout.addRow(self.__lon_label,self.__lon_text)
        layout.addRow(self.__lat_label, self.__lat_text)
        layout.addRow(self.__hostinfo_opt_btn)
        layout.addRow(self.__statuswidget_pathbtn)

        logo = QtGui.QPixmap(_logo_file)
        logolabel = QtWidgets.QLabel()
        logolabel.setPixmap(logo)
        # layout.addRow(logolabel)

    def __hostinfo_opt_changed_text(self):
        """
        Called when the textedit was done, updates the hostinformation,
        Returns:

        """
        funcname = __name__ + '.__hostinfo_opt_changed_text()'
        print(funcname)
        FLAG_CHANGE = False
        # Location text
        if self.__loc_text.textold == self.__loc_text.text():
            print('Not really a change of the text')
        else:
            self.__loc_text.textold = self.__loc_text.text()
            self.redvypr.hostinfo_opt['location'].data = self.__loc_text.text()
            FLAG_CHANGE = True

        # Location text
        if self.__desc_text.textold == self.__desc_text.text():
            print('Not really a change of the description text')
        else:
            self.__desc_text.textold = self.__desc_text.text()
            self.redvypr.hostinfo_opt['description'].data = self.__desc_text.text()
            FLAG_CHANGE = True

        # Longitude
        if self.__lon_text.oldvalue == self.__lon_text.value():
            print('Not really a change of the longitude')
        else:
            self.__lon_text.oldvalue = self.__lon_text.value()
            self.redvypr.hostinfo_opt['lon'].data = self.__lon_text.value()
            FLAG_CHANGE = True

        # Latitude
        if self.__lat_text.oldvalue == self.__lat_text.value():
            print('Not really a change of the latitude')
        else:
            self.__lat_text.oldvalue = self.__lat_text.value()
            self.redvypr.hostinfo_opt['lat'].data = self.__lat_text.value()
            FLAG_CHANGE = True

        if FLAG_CHANGE:
            print('Things have changed, lets send a signal')
            try:
                self.__hostinfo_opt_edit.reload_config()
            except:
                pass
            self.redvypr.hostconfig_changed_signal.emit()

    def __hostinfo_opt_changed_click(self):
        """
        Opens a widget that allow to change the optional hostinformation
        Returns:

        """
        # Optional hostinformation
        self.__hostinfo_opt_edit = gui.configWidget(self.redvypr.hostinfo_opt, loadsavebutton=False,
                                               redvypr_instance=self.redvypr)

        self.__hostinfo_opt_edit.show()

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
        """ Closing a device tab and removing the device
        """
        funcname = __name__ + '.closeTab()'
        logger.debug('Closing the tab now')
        currentWidget = self.devicetabs.widget(currentIndex)
        # Search for the corresponding device
        for sendict in self.redvypr.devices:
            if (sendict['widget'] == currentWidget):
                device = sendict['device']
                self.redvypr.rem_device(device)
                # Close the widgets (init/display)
                currentWidget.close()
                # Info
                sendict['infowidget'].close()

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
                sendict['device'].thread.kill()
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
    def __init__(self, width=None, height=None, config=None,hostname='redvypr',hostinfo_opt={}):
        super(redvyprMainWidget, self).__init__()
        # self.setGeometry(0, 0, width, height)


        #self.setWindowTitle("redvypr")
        self.setWindowTitle(hostname)
        # Add the icon
        self.setWindowIcon(QtGui.QIcon(_icon_file))

        self.redvypr_widget = redvyprWidget(config=config,hostname=hostname,hostinfo_opt=hostinfo_opt)
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
    config_help_add = 'add device, can be called multiple times, options/configuration by commas separated, -a test_device,[s],[mp/th],name:test_1,delay_s:0.4'
    config_optional = 'optional information about the redvypr instance, multiple calls possible or separated by ",". Given as a key:data pair: --hostinfo location:lab --hostinfo lat:10.2,lon:30.4. The data is tried to be converted to an int, if that is not working as a float, if that is neither working at is passed as string'
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action='count')
    parser.add_argument('--config', '-c', help=config_help)
    parser.add_argument('--nogui', '-ng', help=config_help_nogui, action='store_true')
    parser.add_argument('--add_path', '-p', help=config_help_path)
    parser.add_argument('--hostname', '-hn', help=config_help_hostname)
    parser.add_argument('--hostinfo', '-o', help=config_optional, action='append')
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
    config_all = [] # Make a config all, the list can have several dictionaries that will be all processed by the redvypr initialization
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
        print('devices!', args.add_device)
        for d in args.add_device:
            deviceconfig = {'autostart':False,'loglevel':logging_level,'mp':'thread','config':{},'subscriptions':[]}
            if(',' in d):
                devicemodulename = d.split(',')[0]
                options = d.split(',')[1:]
                for option in options:
                    print('Option',option)
                    if(option == 's'):
                        deviceconfig['autostart'] = True
                    elif (option == 'mp' or option == 'multiprocess') and (':' not in option):
                        deviceconfig['mp'] = 'multiprocess'
                    elif (option == 'th' or option == 'thread') and (':' not in option):
                        deviceconfig['mp'] = 'thread'
                    elif (':' in option):
                        key = option.split(':')[0]
                        data = option.split(':')[1]
                        try:
                            data = int(data)
                        except:
                            try:
                                data = float(data)
                            except:
                                pass

                        if(key == 'name'):
                            deviceconfig[key] = data
                        elif (key == 'loglevel') or (key == 'll'):
                            try:
                                loglevel_tmp = data
                                loglevel_device = getattr(logging, loglevel_tmp.upper())
                            except Exception as e:
                                print(e)
                                loglevel_tmp = 'INFO'
                                loglevel_device = getattr(logging, loglevel_tmp.upper())

                            print('Setting device {:s} to loglevel {:s}'.format(devicemodulename,loglevel_tmp))
                            deviceconfig['loglevel'] = loglevel_device
                        elif (key == 'subscribe'):
                            print('Subscribe',data)
                            deviceconfig['subscriptions'].append(data)
                        else:
                            deviceconfig['config'][key] = data
            else:
                devicemodulename = d
            dev = {'devicemodulename': devicemodulename, 'deviceconfig':deviceconfig}
            print('dev',dev)
            hostconfig['devices'].append(dev)
            logger.info('Adding device {:s}, autostart: {:s},'.format(d,str(deviceconfig['autostart'])))

        config_all.append(hostconfig)

    # Add hostname
    if (args.hostname is not None):
        hostname = args.hostname
    else:
        hostname = 'redvypr'

    # Add hostname
    if (args.hostinfo is not None):
        hostinfo = args.hostinfo
    else:
        hostinfo = []

    # Add optional hostinformations
    hostinfo_opt = {}
    for i in hostinfo:
        for info in i.split(','):
            print('Info',info)
            if(':' in info):
                key = info.split(':')[0]
                data = info.split(':')[1]
                try:
                    data = int(data)
                except:
                    try:
                        data = float(data)
                    except:
                        pass

                hostinfo_opt[key] = data
            else:
                logger.warning('Not a key:data pair in hostinfo, skipping {:sf}'.format(info))

    #config_all.append({'hostinfo_opt':hostinfo_opt})
    print('Hostinfo', hostinfo)
    print('Hostinfo opt', hostinfo_opt)

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
        redvypr_obj = redvypr(config=config_all, hostinfo_opt=hostinfo_opt,hostname=hostname,nogui=True)
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
        ex = redvyprMainWidget(width=width, height=height, config=config_all,hostname=hostname,hostinfo_opt=hostinfo_opt)

        sys.exit(app.exec_())


if __name__ == '__main__':
    redvypr_main()







