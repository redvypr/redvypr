import ast
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
import re
import pydantic
from pyqtconsole.console import PythonConsole
from pyqtconsole.highlighter import format
import platform
# Import redvypr specific stuff
import redvypr.data_packets as data_packets
import redvypr.redvypr_address as redvypr_address
import redvypr.packet_statistic as redvypr_packet_statistic
from redvypr.gui import redvypr_ip_widget, QPlainTextEditLogger, displayDeviceWidget_standard, \
    deviceControlWidget, datastreamWidget, redvypr_deviceInitWidget, redvypr_deviceInfoWidget, deviceTabWidget
import redvypr.gui as gui
from redvypr.config import configuration
import redvypr.config as redvyprconfig
from redvypr.version import version
import redvypr.files as files
from redvypr.device import redvypr_device, redvypr_device_scan, redvypr_device_parameter
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

_logo_file = files.logo_file
_icon_file = files.icon_file

# The maximum size the dataqueues have, this should be more than
# enough for a "normal" usage case
queuesize = 10000
# queuesize = 10

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr')
logger.setLevel(logging.INFO)

# Pydantic
class redvypr_config(pydantic.BaseModel):
    hostname: str = pydantic.Field(default='redvypr')
    description: str = pydantic.Field(default='')
    lon: float = pydantic.Field(default=-9999)
    lat: float = pydantic.Field(default=-9999)
    devices: dict = pydantic.Field(default={})



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
    hostinfo = {'hostname': hostname, 'tstart': time.time(), 'addr': get_ip(), 'uuid': redvyprid}
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
    packet_counter = 0 # Global counter of packets received by the redvypr instance
    tinfo = time.time()
    tstop = time.time()
    thread_start = time.time()
    dt_sleep = dt

    while True:
        try:
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

                        devicedict['statistics']['packets_published'] += 1 # The total number of packets published by the device
                        packets_processed += 1 # Counter for the statistics
                        packet_counter += 1 # Global counter of packets received by the redvypr instance
                        data_all.append([data,packet_counter])
                    except Exception as e:
                        break
                # Process read packets
                for data_list in data_all:
                    data = data_list[0]
                    numpacket = data_list[1]

                    #rdata = data_packets.redvypr_datapacket(data)
                    #print(rdata.datakeys())

                    # Add additional information, if not present yet
                    redvypr_packet_statistic.treat_datadict(data, device.name, hostinfo, numpacket, tread,devicedict['devicemodulename'])
                    # Get the devicename using an address
                    raddr = redvypr_address.redvypr_address(data)
                    devicename_stat = raddr.address_str
                    #devicename_stat = data_packets.get_devicename_from_data(data, uuid=True)
                    #
                    # Do statistics
                    try:
                        devicedict['statistics'] = redvypr_packet_statistic.do_data_statistics(data, devicedict['statistics'], address_data=raddr)
                    except Exception as e:
                        logger.debug(funcname + ':Statistics:',exc_info=True)

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

                            # Send an information about the change, that will trigger a pyqt signal in the main thread
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
                        # Send an information about the change, that will trigger a pyqt signal in the main thread
                        devinfo_send = {'type': 'deviceinfo_all', 'deviceinfo_all': copy.deepcopy(deviceinfo_all),
                                        'devices_changed': list(set(devices_changed)),
                                        'devices_removed': devices_removed, 'change': 'datastreams changed','device_changed':device.name}
                        infoqueue.put_nowait(devinfo_send)

                    #
                    # And finally: Distribute the data
                    #
                    # Loop over all devices and check if any subscription works
                    for devicedict_sub in devices:
                        devicesub = devicedict_sub['device']
                        if(devicesub == device): # Not to itself
                            continue

                        for addr in devicesub.subscribed_addresses: # Loop over all subscribed redvypr_addresses
                            # This is the main functionality for distribution, comparing a datapacket with a
                            # redvypr_address using "in"
                            if (data in addr) and (numtag < 2): # Check if data packet fits with addr and if its not recirculated again
                                try:
                                    #print('data to be sent',data)
                                    devicesub.datainqueue.put_nowait(data) # These are the datainqueues of the subscribing devices
                                    devicedict_sub['statistics']['packets_received'] += 1
                                    #print(devicedict_sub['statistics']['packets_received'])
                                    try:
                                        devicedict_sub['statistics']['packets'][devicename_stat]
                                    except:
                                        devicedict_sub['statistics']['packets'][devicename_stat] = {'received':0,'published':0}
                                    devicedict_sub['statistics']['packets'][devicename_stat]['received'] += 1
                                    #print('Sent data to',devicename_stat,devicedict_sub['packets_received'])
                                    break
                                except Exception as e:
                                    #logger.exception(e)
                                    thread_status = devicesub.get_thread_status()
                                    if thread_status['thread_running']:
                                        devicedict['statistics']['packets_dropped'] += 1
                                    logger.debug(funcname + ':dataout of :' + devicedict_sub['device'].name + ' full: ' + str(e), exc_info=True)

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
            # Time to sleep, remove processing time
            dt_sleep = max([0, dt - dt_dist])
            if ((tstop - tinfo) > dt_info):
                tinfo = tstop
                info_dict = {'type':'dt_avg','dt_avg': dt_avg / navg,'packets_processed': packets_processed,'packets_counter':packet_counter,'thread_start':thread_start}
                packets_processed = 0
                # print(info_dict)
                try:
                    infoqueue.put_nowait(info_dict)
                except:
                    pass
        except:
            logger.warning(funcname + 'Could not distribute packets:', exc_info=True)


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

    def __init__(self, parent=None, config=None, hostname='redvypr', metadata={}, nogui=False):
        # super(redvypr, self).__init__(parent)
        super(redvypr, self).__init__()
        print(__platform__)
        funcname = __name__ + '.__init__()'
        logger.debug(funcname)
        self.hostinfo = create_hostinfo(hostname=hostname)
        # TODO: replace with pydantic
        #print('Hostinfo opt',hostinfo_opt)
        try:
            metadata['description']
        except:
            metadata['description'] = ''

        try:
            metadata['location']
        except:
            metadata['location'] = ''

        try:
            metadata['lon']
        except:
            metadata['lon'] = -9999.0

        try:
            metadata['lat']
        except:
            metadata['lat'] = -9999.0

        self.metadata = configuration(template=metadata)

        self.config = {}  # Might be overwritten by parse_configuration()
        self.properties = {}  # Properties that are distributed with the device
        self.numdevice = 0
        self.devices = []  # List containing dictionaries with information about all attached devices
        self.device_paths = []  # A list of pathes to be searched for devices
        self.datastreams_dict = {} # Information about all datastreams, this is updated by distribute data
        self.deviceinfo_all   = {} # Information about all devices, this is updated by distribute data

        self.packets_counter = 0 # Counter for the total number of packets processed
        self.dt_datadist = 0.01  # The time interval of datadistribution
        self.dt_avg_datadist = 0.00  # The time interval of datadistribution
        self.datadistinfoqueue = queue.Queue(maxsize=1000)  # A queue to get informations from the datadistthread
        self.redvyprqueue = queue.Queue()  # A queue to send informations to the datadistthread
        # Lets start the distribution!
        self.datadistthread = threading.Thread(target=distribute_data, args=(
        self.devices, self.hostinfo, self.deviceinfo_all, self.datadistinfoqueue, self.redvyprqueue, self.dt_datadist), daemon=True)
        self.t_thread_start = time.time()
        self.datadistthread.start()
        logger.info(funcname + ':Searching for devices')
        self.redvypr_device_scan = redvypr_device_scan(device_path = self.device_paths, redvypr_devices=redvyprdevices, loglevel = logger.getEffectiveLevel())
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
            if True:
                logger.info('RESTARTING datadistribution thread ....')
                self.datadistthread.start()

            return

        while True:
            try: # Reading data coming from distribute_data thread
                data = self.datadistinfoqueue.get(block=False)
                #print('Got data',data)
                try:
                    if('dt_avg' in data['type']):
                        self.dt_avg_datadist   = data['dt_avg']
                        self.packets_processed = data['packets_processed']
                        self.packets_counter = data['packets_counter']
                        self.t_thread_start = data['thread_start']
                        self.status_update_signal.emit()
                    elif ('deviceinfo_all' in data['type']):
                        data.pop('type')  # Remove the type key
                        # Store the data of the changed devices
                        self.__device_status_changed_data__ = data

                        #print('datastreams changed', data)
                        self.device_status_changed_signal.emit()
                except:
                    logger.info(funcname + 'Error',exc_info=True)

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
            #info_dict['thread_running'] = running
            if(status['thread_running']):
                runstr = 'running'
            else:
                runstr = 'stopped'

            statusstr += '\n\t' + sendict['device'].name + ':' + runstr + ': data packets sent: {:d}' + ': data packets received: {:d}'.format(
                sendict['packets_published'],sendict['packets_received'])
            # statusstr += ': data packets received: {:d}'.format(sendict['numpacketout'])

        return statusstr

    def get_config(self):
        """
        Creates a configuration dictionary out of the current state.

        Returns:
            config: configuration dictionary

        """
        funcname = __name__ + '.get_config():'
        config = {}
        config['hostname']     = self.hostinfo['hostname']
        config['hostinfo_opt'] = copy.deepcopy(self.metadata)
        config['devicepath'] = []
        for p in self.device_paths:
            config['devicepath'].append(p)
        # Loglevel
        config['loglevel'] = logger.level
        # redvypr_version
        config['redvypr_version'] = version
        # time
        config['creation_time'] = str(datetime.datetime.utcnow())
        # Devices
        config['devices'] = []
        for devicedict in self.devices:
            device = devicedict['device']
            devsave = {}
            base_config_exclude = {'uuid','publishes','subscribes','description','numdevice','devicemodulename'}
            devsave['base_config'] = device.device_parameter.model_dump(exclude=base_config_exclude)
            devsave['devicemodulename'] = devicedict['devicemodulename']
            devsave['config'] = device.config.model_dump()
            # Treat subscriptions
            devsave['subscriptions'] = []
            for raddr in device.subscribed_addresses:
                devsave['subscriptions'].append(raddr.address_str)

            config['devices'].append(devsave)

        return config

    def parse_configuration(self, redvypr_config=None):
        """ Parses a dictionary with a configuration, if the file does not exists it will return with false, otherwise self.config will be updated

        Arguments:
            redvypr_config (str, dict or list of strs and dicts):
        Returns:
            True or False
        """
        funcname = "parse_configuration():"
        parsed_devices = []
        logger.debug(funcname)

        if (redvypr_config is not None):
            logger.debug(funcname + 'Configuration: ' + str(redvypr_config))
            if (type(redvypr_config) == str):
                redvypr_config = [redvypr_config]
        else:
            return False

        config = {} # This is a merged config of all configurations
        device_tmp = []
        for configraw in redvypr_config:
            if (type(configraw) == str):
                logger.debug(funcname + 'Opening yaml file: ' + str(configraw))
                if (os.path.exists(configraw)):
                    fconfig = open(configraw)
                    try:
                        config_tmp = yaml.load(fconfig, Loader=yaml.SafeLoader)
                    except:
                        logger.warning(funcname + 'Could not load yaml file with safe loader')
                        fconfig.close()
                        fconfig = open(configraw)
                        try:
                            config_tmp = yaml.load(fconfig, Loader=yaml.CLoader)
                            logger.debug('Config tmp {}'.format(config_tmp))
                        except:
                            logger.warning(funcname + ' Could not load yaml file with x loader')
                            continue
                else:
                    logger.warning(funcname + 'Yaml file: ' + str(configraw) + ' does not exist!')
                    continue
            elif(type(configraw) == dict):
                logger.debug(funcname + 'Opening dictionary')
                config_tmp = configraw
            else:
                logger.warning(funcname + 'Unknown type of configuration {:s}'.format(type(configraw)))
                continue

            # Merge the configuration into one big dictionary
            config.update(config_tmp)

            if 'devices' in config_tmp.keys():
                device_tmp.extend(config_tmp['devices'])

        if len(device_tmp)>0:
            config['devices'] = device_tmp

        # Apply the merged configuration
        if True:
            #self.config = config
            # global loglevel
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
                logger.info(funcname + 'Setting hostname to {:s}'.format(config['hostname']))
                self.hostinfo['hostname'] = config['hostname']
            except:
                pass

            try:
                logger.info(funcname + 'Setting optional hostinfomation: {:s}'.format(str(config['hostinfo_opt'])))
                c = redvyprconfig.dict_to_configDict(config['hostinfo_opt'])
                self.metadata.update(c)
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

            # Add the devices
            if (hasdevices):
                for device in config['devices']:
                    print('Device',device)
                    # Device specifig configuration
                    try:
                        device_config = device['config']
                    except:
                        device_config = {}

                    # The base configuration, same for all devices
                    try:
                        base_config = device['base_config']
                    except:
                        base_config = {}

                    # Check if the devicemodulename kind of fits
                    FLAG_DEVICEMODULENAME_EXACT = False
                    # Make an exact test first
                    for smod in self.redvypr_device_scan.redvypr_devices_flat:
                        #print('device:',smod['name'],device['devicemodulename'])
                        # The smod['name'] looks like 'redvypr.devices.network.zeromq_device'
                        # Check first if devicemodulename has a '.', if not, use split smod['name'] and use the last one
                        if '.' in device['devicemodulename']:
                            if (device['devicemodulename'] == smod['name']):
                                FLAG_DEVICEMODULENAME_EXACT = True
                                break
                        else:
                            smodname = smod['name'].split('.')[-1]
                            #print('smodname',smodname)
                            if (device['devicemodulename'] == smodname):
                                FLAG_DEVICEMODULENAME_EXACT = True
                                device['devicemodulename_orig'] = device['devicemodulename']
                                device['devicemodulename'] = smod['name']
                                break

                    # Make a test if the string is within the devicemodulename
                    if FLAG_DEVICEMODULENAME_EXACT == False:
                        for smod in self.redvypr_device_scan.redvypr_devices_flat:
                            if (device['devicemodulename'] in smod['name']): # This is a weaker test, can be potentially replaced by regex
                                device['devicemodulename_orig'] = device['devicemodulename']
                                device['devicemodulename'] = smod['name']

                    logger.info(funcname + 'Adding device {}'.format(device['devicemodulename']))
                    dev_added = self.add_device(devicemodulename=device['devicemodulename'], deviceconfig=device_config, device_parameter=base_config)
                    # Subscriptions
                    # Name
                    #
                    parsed_devices.append(dev_added)

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

    def add_device(self, devicemodulename=None, deviceconfig=None, device_parameter=None):
        """
        Function adds a device to redvypr

        Args:
            :param devicemodulename:
            :param deviceconfig: A dictionary with the configuration, this is filled by i.e. a yaml file with the configuration or if clicked in the gui just the name of the device
            :param device_parameter:

        Returns:
            devicelist: a list containing all devices of this redvypr instance


        """
        funcname = self.__class__.__name__ + '.add_device():'
        logger.debug(funcname + ':devicemodule: ' + str(devicemodulename) + ':deviceconfig: ' + str(deviceconfig))
        #logger.info(funcname + ':devicemodule: ' + str(devicemodulename) + ':deviceconfig: ' + str(deviceconfig))
        devicelist = []
        device_found = False
        # Loop over all modules and check of we find the name
        for smod in self.redvypr_device_scan.redvypr_devices_flat:
            if (devicemodulename == smod['name']):
                logger.debug('Trying to import device {:s}'.format(smod['name']))
                devicemodule = smod['module']
                # Try to get a pydantic base configuration, every device has
                pydantic_base_config = None
                try:
                    pydantic_base_config = devicemodule.device_base_config()
                    logger.debug(funcname + ':Found pydantic base configuation {:s}'.format(str(devicemodule)))
                    FLAG_HAS_PYDANTICBASE = True
                    FLAG_PYDANTIC = True
                    # Create or use a given device parameter object
                    if isinstance(device_parameter, redvypr_device_parameter):
                        pass
                    elif isinstance(device_parameter, dict):
                        print('Will update from config dictionary')
                        device_parameter_tmp = redvypr_device_parameter()
                        device_parameter = device_parameter_tmp.model_copy(update=device_parameter)
                    else:
                        print('Standard base_config')
                        device_parameter = redvypr_device_parameter()

                    device_parameter.devicemodulename = devicemodulename
                    device_parameter.numdevice = self.numdevice
                    print('Device parameter',device_parameter)
                    # Update the device parameter with the parameters of the device
                    device_parameter = device_parameter.model_copy(update=pydantic_base_config.model_dump())
                    print('Device parameter 2', device_parameter)



                except Exception as e:
                    logger.debug(
                        funcname + ':No pydantic base configuration template of device {:s}: {:s}'.format(str(devicemodule), str(e)))
                    #logger.exception(e)
                    FLAG_HAS_PYDANTICBASE = False
                    FLAG_PYDANTIC = False

                # Try to get a pydantic device specific configuration (the configuration only for the device)
                try:
                    pydantic_device_config = devicemodule.device_config()
                    try:
                        config = deviceconfig['config']
                        #print('Config',config)
                        pydantic_device_config = devicemodule.device_config.model_validate(config)
                    except:
                        logger.debug('No config found',exc_info=True)
                        pydantic_device_config = devicemodule.device_config()

                    logger.debug(funcname + ':Found pydantic configuration {:s}'.format(str(devicemodule)))
                    #redvypr_device_parameter.config = pydantic_device_config
                    FLAG_HAS_PYDANTIC = True
                except Exception as e:
                    logger.debug(
                        funcname + ':No pydantic configuration template of device {:s}: {:s}'.format(str(devicemodule),
                                                                                            str(e)))
                    #logger.exception(e)
                    FLAG_HAS_PYDANTIC = False

                # If no pydantic was found, do it the old style (to be removed soon)
                if FLAG_PYDANTIC == False:
                    logger.info('Adding old style configuration device')
                    # Try to get a configuration template (oldstyle)
                    try:
                        config_template = devicemodule.config_template
                        logger.debug(funcname + ':Found configuation template of device {:s}'.format(str(devicemodule)))
                        #templatedict = configtemplate_to_dict(config_template)
                        self.__fill_config__(device_parameter, config_template, deviceconfig)
                        FLAG_HAS_TEMPLATE = True
                    except Exception as e:
                        logger.debug(
                            funcname + ':No configuration template of device {:s}: {:s}'.format(str(devicemodule), str(e)))
                        logger.exception(e)
                        logger.debug(funcname + ' template=False')
                        FLAG_HAS_TEMPLATE = False


                if(device_parameter.maxdevices > 0):
                    ndevices = 0
                    for d in self.devices:
                        devname = d['device'].devicemodulename
                        if(devname == devicemodulename):
                            ndevices += 1

                    if ndevices >= device_parameter.maxdevices:
                        logger.warning(funcname + ' Could not add {:s}, maximum number of {:d} devices reached'.format(devicemodulename,maxdevices))
                        return


                # If the device does not have a name, add a standard but unique one
                devicenames = self.get_all_devicenames()
                #print('Devicenames',devicenames)
                #print('device_parameter',device_parameter)
                #print('devicemodulename', devicemodulename)
                #print('devicename 0',device_parameter.name,len(device_parameter.name))
                devicename_tmp = device_parameter.name
                if len(device_parameter.name) == 0:
                    devicename_tmp = devicemodulename.split('.')[-1]# + '_' + str(self.numdevice)
                    #print('Devicename_tmp',devicename_tmp)

                if devicename_tmp in devicenames:
                    logger.warning(funcname + ' Devicename {:s} exists already, will add {:d} to the name.'.format(devicename_tmp,self.numdevice))
                    devicename_tmp += '_' + str(self.numdevice)

                device_parameter.name = devicename_tmp

                # Check for multiprocess options in configuration
                if 'thread' in device_parameter.multiprocess:  # Thread or QThread
                    dataqueue = queue.Queue(maxsize=queuesize)
                    datainqueue = queue.Queue(maxsize=queuesize)
                    comqueue = queue.Queue(maxsize=queuesize)
                    statusqueue = queue.Queue(maxsize=queuesize)
                    guiqueue = queue.Queue(maxsize=queuesize)
                else: # multiprocess
                    dataqueue = multiprocessing.Queue(maxsize=queuesize)
                    datainqueue = multiprocessing.Queue(maxsize=queuesize)
                    comqueue = multiprocessing.Queue(maxsize=queuesize)
                    statusqueue = multiprocessing.Queue(maxsize=queuesize)
                    guiqueue = multiprocessing.Queue(maxsize=queuesize)

                # Create a dictionary for the statistics and general information about the device
                # This is used extensively in exchanging information about devices between redvypr instances and or other devices
                statistics = redvypr_packet_statistic.create_data_statistic_dict()
                # Device do not necessarily have a statusqueue
                try:
                    numdevices = len(self.devices)
                    # Could also create a UUID based on the hostinfo UUID str
                    device_parameter.uuid = '{:03d}--'.format(numdevices) + str(uuid.uuid1()) + '::' + self.hostinfo['uuid']
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
                    #print('Getting config')

                    #print('Done')


                    if FLAG_HAS_PYDANTIC:
                        logger.debug(funcname + ' Using pydantic config')
                        configu = pydantic_device_config
                        config_template = None
                    else: # Legacy configuration, TODO: Remove soon
                        # Merge the config with a potentially existing template to fill in default values
                        if FLAG_HAS_TEMPLATE:
                            config = deviceconfig['config']
                            # print('With template', config_template)
                            # print('With configuration', config)
                            # config = apply_config_to_dict(config,templatedict)
                            # config = copy.deepcopy(config)
                            # redvypr.config.dict_to_configDict(templatedict, process_template=True)
                            configu = configuration(template=config_template, config=config)
                        else:  # Make a configuration without a template directly from the config dict
                            # print('Without template')
                            configu = configuration(config)
                            config_template = None

                    logger.debug(funcname + 'Config for device')
                    logger.debug(funcname + 'Config: {:s}'.format(str(configu)))
                    # Set the loglevel
                    try:
                        level = deviceconfig['loglevel']
                    except Exception as e:
                        logger.info(funcname + 'Setting loglevel to standard')
                        # Set the loglevel
                        level = logger.getEffectiveLevel()

                    levelname = logging.getLevelName(level)
                    logger.debug(funcname + 'Setting the loglevel to {}'.format(levelname))
                    device_parameter.loglevel = levelname
                    # Check for an autostart
                    try:
                        device_parameter.autostart = deviceconfig['autostart']
                    except Exception as e:
                        device_parameter.autostart = False

                    # Creating the device
                    device = Device(device_parameter=device_parameter, config=configu, redvypr=self, dataqueue=dataqueue,
                                    template=config_template, comqueue=comqueue, datainqueue=datainqueue,
                                    statusqueue=statusqueue, statistics=statistics, startfunction=startfunction)

                    device.subscription_changed_signal.connect(self.process_subscription_changed)
                    self.numdevice += 1
                    # If the device has a logger
                    devicelogger = device.logger
                except Exception as e:
                    logger.warning(funcname + ' Could not add device because of:')
                    logger.exception(e)


                devicedict = {'device':device, 'dataout': [], 'gui': [], 'guiqueue': [guiqueue],
                              'statistics': statistics, 'logger': devicelogger,'comqueue':comqueue}

                # Add the modulename
                devicedict['devicemodulename'] = devicemodulename
                # Add some statistics (LEGACY)
                devicedict['packets_received'] = 0
                devicedict['packets_published'] = 0
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
                deviceinfo_packet = {'_redvypr':{},'_deviceinfo': {'subscribes': device_parameter.subscribes, 'publishes': device_parameter.publishes, 'devicemodulename': device_parameter.devicemodulename}}
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
                    logger.debug(funcname + ' No subscriptions found')

                    subscribe_addresses = []

                logger.debug(funcname + 'Subscribing to')
                for a in subscribe_addresses:
                    logger.debug(funcname + 'subscribing: {}'.format(a))
                    device.subscribe_address(a)

                logger.debug(funcname + ': Emitting device signal')
                self.device_added.emit(devicelist)
                device_found = True
                break

        if (device_found == False):
            logger.warning(funcname + ': Could not add device (not found): {:s}'.format(str(devicemodulename)))

        return devicelist

    def __fill_config__(self, device_parameter, config_template, deviceconfig, thread=None):
        """ Fills device_parameter with data from config_template
        """
        funcname = __name__ + '.fill_config():'
        try:
            device_parameter.max_devices = config_template['redvypr_device']['max_devices']
        except:
            pass
        # Try to get information about publish/subscribe capabilities described in the config_template
        try:
            device_parameter.publishes = config_template['redvypr_device']['publishes']
        except:
            pass
        try:
            device_parameter.subscribes = config_template['redvypr_device']['subscribes']
        except:
            pass

        try:
            deviceconfig['config']
        except:
            deviceconfig['config'] = {}

        try:
            device_parameter.name = deviceconfig['config']['name']
        except:
            pass

        try:
            level = deviceconfig['loglevel']
            if type(level) == int:
                levelname = logging.getLevelName(level)
            else:
                levelname = level

            device_parameter.loglevel = levelname
        except Exception as e:
            logger.debug(funcname + 'Loglevel not found', exc_info=True)


        try:
            device_parameter.autostart = deviceconfig['autostart']
        except:
            pass

        try:
            device_parameter.gui_dock = deviceconfig['gui_dock']
        except:
            logger.info('Hall',exc_info=True)
            pass

        if (thread == None):
            try:
                device_parameter.multiprocess = deviceconfig['mp'].lower()
            except:
                pass


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
                elif (sendict['device'].thread_running()):
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

    def get_all_devicenames(self):
        """
        Returns a list with the devicenames
        """
        devicenames = []
        for d in self.devices:
            devicenames.append(d['device'].name)

        return devicenames

    def get_hosts(self):
        """
        Returns: List with all redvypr hosts known to this redvypr host instance

        """
        hosts = []
        for d in self.devices:
            dev = d['device']
            hosts.extend(dev.get_hosts())

        hosts = list(set(hosts))
        hosts.sort()
        return hosts


    def get_device_objects(self, publishes = None, subscribes = True):
        """
        Returns a list of all devices of this redvypr instance. Returns all devices if neither "publishes" or "subscribes" is defined.
        Args:
            publishes: True/False or None
            subscribes: True/False

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

        return devicelist

    def get_devices(self, local=None, local_object=True):
        """
        Returns a list of all devices of this redvypr instance.
        Returns: List with devicenames

        """

        devicelist = []
        for d in self.devices:
            dev = d['device']
            if local_object:
                devicelist.append(dev.name)
            else:
                devaddrs = dev.get_deviceaddresses(local=local)
                for devaddr in devaddrs:
                    devicelist.append(devaddr.devicename)

        devicelist = list(set(devicelist))
        devicelist.sort()
        return devicelist

    def get_deviceaddresses(self, local = None, publishes = None, subscribes = None):
        """
        Returns a list of redvypr_addresses of all devices. If local == None all known devices are listed,
        also of all remote devices that are forwarded by a local host device (i.e. iored device).


        Args:
            local [bool/None]: None: all known devices are listed, False: Remote devices are listed, True: local devices are listed

        Returns:
            List of redvypr_address


        """
        raddrs = []
        for dev in self.devices:
            raddrs_tmp = dev['device'].get_deviceaddresses(local)
            raddrs.extend(raddrs_tmp)

        return raddrs

    def get_datakeys(self, local=None):
        """
        Returns a list of all datakeys this host is providing by all its devices
        Returns:
            List of datakeys (str)
        """
        datakeys = []
        for dev in self.devices:
            dkeys = dev['device'].get_datakeys()
            datakeys.extend(dkeys)

        datakeys = list(set(datakeys))
        datakeys.sort()
        return datakeys

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
                    logger.debug(funcname + 'Thread is not running, doing nothing')
                    pass
                elif (sendict['device'].thread_running()):
                    logger.debug(funcname + 'Sending stop command')
                    device.thread_stop()

                self.devices.remove(sendict)
                FLAG_REMOVED = True
                self.device_removed.emit()
                device_changed_dict = {'type':'device_removed','device':device.name,'uuid':device.uuid}
                self.redvyprqueue.put(device_changed_dict)
                break

        return FLAG_REMOVED














