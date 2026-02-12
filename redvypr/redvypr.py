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
from PyQt6 import QtWidgets, QtCore, QtGui
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
import typing
from pyqtconsole.console import PythonConsole
from pyqtconsole.highlighter import format
import platform

import redvypr
# Import redvypr specific stuff
import redvypr.data_packets as data_packets
import redvypr.redvypr_address as redvypr_address
from redvypr.redvypr_address import RedvyprAddress
import redvypr.packet_statistic as redvypr_packet_statistic
from redvypr.version import version
import redvypr.files as files
from redvypr.device import RedvyprDeviceConfig, RedvyprDeviceBaseConfig, RedvyprDevice, RedvyprDeviceScan, RedvyprDeviceParameter, queuesize
import redvypr.devices as redvyprdevices
import faulthandler

logfile = None

if sys.stderr is not None:
    #normal mode
    faulthandler.enable()
else:
    # no-console, log to file
    log_path = os.path.join(os.path.dirname(sys.executable), "faulthandler.log")
    logfile = open(log_path, "w")
    faulthandler.enable(file=logfile)

# Collect all logger
logger_all = [data_packets.logger, redvypr_address.logger, redvypr_packet_statistic.logger]

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

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr')
logger.setLevel(logging.INFO)


# Pydantic

class RedvyprConfig(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")
    hostname: typing.Optional[str] = pydantic.Field(default=None)
    metadata: typing.Optional[dict] = pydantic.Field(default=None)
    #devices: list = pydantic.Field(default=[])
    #devices: typing.List[RedvyprDeviceConfig] = pydantic.Field(default=[])
    devices: typing.List[typing.Annotated[typing.Union[RedvyprDeviceConfig], pydantic.Field(discriminator='config_type')]] = pydantic.Field(default=[])
    devicepaths: list = pydantic.Field(default=[])
    loglevel: typing.Literal['INFO','DEBUG','WARNING'] = pydantic.Field(default='INFO')
    gui_home_icon: str = 'redvypr'



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

hostinfo_blank = {'host':None, 'tstart': 0,'addr':None, 'uuid':None}

def create_hostinfo(hostname='redvypr'):
    funcname = __name__ + '.create_hostinfo()'
    logger.debug(funcname)
    randstr = '{:03d}'.format(random.randrange(2 ** 8))
    redvyprid = str(uuid.getnode()) + '-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S.%f') + '-' + randstr
    #redvyprid = str(uuid.getnode()) + '-' + randstr
    hostinfo = {'host': hostname, 'tstart': time.time(), 'addr': get_ip(), 'uuid': redvyprid}
    return hostinfo

def send_packets_to_devices(devicedict, devices, data_packets_fan_out, logger_dist, hostinfo):
    funcname = __name__ + '.send_packets_to_devices()'
    device = devicedict['device']
    for devicedict_sub in devices:
        devicesub = devicedict_sub['device']
        if (devicesub == device):  # Not to itself
            continue

        for data_packet in data_packets_fan_out:
            raddr = redvypr_address.RedvyprAddress(data_packet)
            devicename_stat = str(raddr)
            for addr in devicesub.subscribed_addresses:  # Loop over all subscribed redvypr_addresses
                try:
                    numtag_packet = data_packet['_redvypr']['tag'][hostinfo['uuid']]
                except:
                    numtag_packet = 0
                # This is the main functionality for distribution, comparing a datapacket with a
                # print('Testing packet',redvypr_address.RedvyprAddress(data_packet),numtag_packet,(data_packet in addr))
                if addr.matches_filter(data_packet) and (
                        numtag_packet < 2):  # Check if data packet fits with addr and if its not recirculated again
                    try:
                        # print(funcname + 'data to be sent',data)
                        devicesub.datainqueue.put_nowait(
                            data_packet)  # These are the datainqueues of the subscribing devices
                        devicedict_sub['statistics']['packets_received'] += 1
                        # print(devicedict_sub['statistics']['packets_received'])
                        try:
                            devicedict_sub['statistics']['packets'][devicename_stat]
                        except:
                            devicedict_sub['statistics']['packets'][devicename_stat] = {
                                'received': 0, 'published': 0}
                        devicedict_sub['statistics']['packets'][devicename_stat][
                            'received'] += 1
                        # print('Sent data to',devicename_stat,devicedict_sub['packets_received'])
                        break
                    except:
                        thread_status = devicesub.get_thread_status()
                        if thread_status['thread_running']:
                            devicedict['statistics']['packets_dropped'] += 1
                        logger_dist.warning(funcname + ':dataout of :' + devicedict_sub[
                            'device'].name, exc_info=True)

def distribute_data(devices, hostinfo, deviceinfo_all, infoqueue, redvyprqueue, redvyprreplyqueue, dt=0.01):
    """ The heart of redvypr, this functions distributes the queue data onto the subqueues.
    """
    funcname = __name__ + '.distribute_data()'
    logger_dist = logging.getLogger('redvypr.distribute_data')
    logger_dist.setLevel(logging.DEBUG)
    dt_info = 5.0  # The time interval information will be sent
    dt_avg = 0  # Averaging of the distribution time needed
    navg = 0
    packets_processed = 0 # For statistics, count packets
    packet_counter = 0 # Global counter of packets received by the redvypr instance
    tinfo = time.time()
    tstop = time.time()
    thread_start = time.time()
    dt_sleep = dt

    # Create a bogus main redvypr device
    devicedict_main = {}
    devicedict_main['statistics'] = redvypr.packet_statistic.device_redvypr_statdict
    devicedict_main['device'] = None
    while True:
        try:
            time.sleep(dt_sleep)
            tstart = time.time()
            FLAG_device_status_changed = False
            devices_changed = []
            devices_removed = []
            # Read data from the main thread
            try:
                tread = time.time()
                redvyprdata = redvyprqueue.get(block=False) # Data from the main thread
            except queue.Empty:
                redvyprdata = None
                #logger_dist.info("Error processing data",exc_info=True)
            except:
                logger_dist.info("Error processing data",exc_info=True)
                redvyprdata = None


            # Process data from the main thread
            if redvyprdata is not None:
                print("Got data from redvyprqueue",redvyprdata)
                if "_metadata" in redvyprdata.keys() or "_metadata_remove" in redvyprdata.keys():
                    print("Adding/remove metadata from redvyrqueue")
                    try:
                        status_statistics = redvypr_packet_statistic.do_metadata(
                            redvyprdata, deviceinfo_all)
                        #print("Deviceinfo all",deviceinfo_all)
                        print("Status statistics",status_statistics)
                    except:
                        print("Problem")
                        logger_dist.info(funcname + ':Metadata:', exc_info=True)

                    # Update metadata
                    if status_statistics['metadata_changed']:
                        # Send a deviceinfo update with the changed metadata
                        compacket = data_packets.commandpacket('info',
                                                               host=hostinfo,
                                                               devicename='distribute_data',
                                                               packetid='metadata')
                        compacket['deviceinfo_all'] = copy.deepcopy(deviceinfo_all)
                        redvypr_packet_statistic.treat_datadict(compacket, '',
                                                                hostinfo, 0, tread,
                                                                'distribute_data')
                        infoqueue.put_nowait(compacket)
                        print("send to devices new metadata ...")
                        send_packets_to_devices(devicedict_main, devices, data_packets_fan_out=[compacket],
                                        logger_dist=logger_dist, hostinfo=hostinfo)
                    # Send the packet back to notify function that it was processed
                    redvyprreplyqueue.put_nowait(redvyprdata)

                elif "type" in redvyprdata.keys():
                    if(redvyprdata['type'] == 'device_removed'):
                        logger_dist.debug(funcname + 'Device removed {}'.format(redvyprdata))
                        FLAG_device_status_changed = True
                        devices_removed.append(redvyprdata['device'])
                        devinfo_rem = deviceinfo_all['device_redvypr'].pop(redvyprdata['device'])
                        devinfo_send = {'type':'deviceinfo_all', 'deviceinfo_all': copy.deepcopy(deviceinfo_all), 'devices_changed': list(set(devices_changed)),
                        'devices_removed': devices_removed,'change':'devrem','device_changed':redvyprdata['device']}
                        infoqueue.put_nowait(devinfo_send)
                        # Send a deviceinfo update with the changed metadata
                        compacket = data_packets.commandpacket('info', host=hostinfo, devicename='distribute_data', packetid='device_removed',
                                                               publisher='')
                        compacket['deviceinfo_all'] = copy.deepcopy(deviceinfo_all)
                        compacket['devices_removed'] = devices_removed
                        redvypr_packet_statistic.treat_datadict(compacket, 'distribute_data', hostinfo, 0, tread,
                                                                'distribute_data')
                        data_packets_fan_out.append(compacket)

            # Loop over all devices and process data
            for devicedict in devices:
                #print("devicedict", devicedict)
                #print("\n\n")
                #print("devicedict statistics", devicedict['statistics'])
                #print("\n\n")
                device = devicedict['device']
                data_all = []
                tread = time.time()
                # Read all packets in a bunch
                while True:
                    try:
                        data = device.dataqueue.get(block=False)
                        if not (isinstance(data, dict)): # If data is not a dictionary, convert it to one
                            data = {'data':data}


                        devicedict['statistics']['packets_published'] += 1  # The total number of packets published by the device
                        packets_processed += 1 # Counter for the statistics
                        packet_counter += 1 # Global counter of packets received by the redvypr instance
                        data_all.append([data,packet_counter])
                    except queue.Empty:
                        break
                    except:
                        logger_dist.info("Error processing data",exc_info=True)
                        return
                        break
                # Process read packets
                for data_list in data_all:
                    data_packets_fan_out = []
                    data = data_list[0]
                    numpacket = data_list[1]
                    # Add additional information, if not present yet
                    redvypr_packet_statistic.treat_datadict(data, device.name, hostinfo, numpacket, tread,devicedict['devicemodulename'])
                    # Get the devicename
                    raddr = redvypr_address.RedvyprAddress(data)
                    devicename_stat = str(raddr)
                    numtag = data['_redvypr']['tag'][hostinfo['uuid']]
                    #print("Processing",data)
                    if numtag < 2:  # Check if data packet fits with addr and its not recirculated again
                        #
                        # Check for a command packet
                        #
                        [command, comdata] = data_packets.check_for_command(data,
                                                                            add_data=True)

                        status_statistics = {'metadata_changed': False}
                        # Do statistics if it's not a command
                        if command is None:
                            #print("Standard data packet")
                            try:
                                redvypr_packet_statistic.do_data_statistics(
                                    data, devicedict['statistics'], address_data=raddr)
                                # print('Statistic status',status_statistics)
                            except:
                                logger_dist.debug(funcname + ':Statistics:', exc_info=True)
                            try:
                                status_statistics = redvypr_packet_statistic.do_metadata(
                                    data, deviceinfo_all)
                                #print(funcname + 'Metadata done')
                            except:
                                logger_dist.debug(funcname + ':Metadata:', exc_info=True)
                        elif (command == 'info'):  # info command, typically a deviceinfo_all packet
                            metadata_remote = data['deviceinfo_all']['metadata']
                            # Updating the metadata
                            for remote_device_name,remote_device_metadata in metadata_remote.items():
                                # Change the publisher to the local device and the uuid if its not existing
                                for addr_metadata, metadata_tmp in remote_device_metadata.items():
                                    raddr_metadata = redvypr_address.RedvyprAddress(addr_metadata,publisher=raddr.publisher)
                                    if raddr_metadata.uuid is None:
                                        raddr_metadata.add_filter(key="uuid",op="eq",value=raddr.uuid)
                                    rstr_tmp = raddr_metadata.to_address_string()
                                    deviceinfo_all['metadata'][rstr_tmp] = metadata_tmp

                            status_statistics['metadata_changed'] = True
                        elif (command == 'reply'):  # status update
                            device.distribute_data_replyqueue.put_nowait(data)
                        elif (command == 'device'):  # A command for the device
                            command = 'device.' + comdata
                            print('Got a command',command)
                        elif (command == 'device_status'):  # status update
                            try:
                                devaddr = comdata['data']['deviceaddr']
                                devstatus = comdata['data']['devicestatus']
                            except:
                                devaddr = None
                                devstatus = None

                            devices_changed.append(device.name) # LEGACY ...
                            if(devaddr is not None):
                                try: # Update the device
                                    devicedict['statistics']['device_redvypr'][devaddr]['_redvypr'].update(devstatus)
                                except:
                                    logger_dist.warning('Could not update status ',exc_info=True)

                            # Send an information about the change, that will trigger a pyqt signal in the main thread
                            devinfo_send = {'type': 'deviceinfo_all', 'deviceinfo_all': copy.deepcopy(deviceinfo_all),
                                            'devices_changed': list(set(devices_changed)), 'device_changed':device.name,
                                            'devices_removed': devices_removed, 'change': 'device_status command','comdata':comdata}
                            infoqueue.put_nowait(devinfo_send)

                    #
                    # Collect the individual dictionaries into one global deviceinfo
                    #
                    try:
                        deviceinfo_all['device_redvypr'][device.name].update(devicedict['statistics']['device_redvypr'])
                    except:
                        deviceinfo_all['device_redvypr'][device.name] = devicedict['statistics']['device_redvypr']

                    # Update metadata
                    if status_statistics['metadata_changed']:
                        # Send a deviceinfo update with the changed metadata
                        compacket = data_packets.commandpacket('info',host=hostinfo, devicename='distribute_data', packetid='metadata')
                        compacket['deviceinfo_all'] = copy.deepcopy(deviceinfo_all)
                        redvypr_packet_statistic.treat_datadict(compacket, '', hostinfo, 0, tread,
                                                                'distribute_data')
                        infoqueue.put_nowait(compacket)
                        data_packets_fan_out.append(compacket)


                    #print('Data ready to send',data)
                    #
                    # And finally: Distribute the data
                    #
                    data_packets_fan_out.append(data)
                    # And now send it to all devices
                    send_packets_to_devices(devicedict, devices, data_packets_fan_out, logger_dist, hostinfo=hostinfo)
                    # Send it into the local dataqueue
                    try:
                        device.dataqueue_local.put_nowait(data)
                    except Exception as e:
                        pass
                    # Fan out the datapacket into the guiqueues of the device
                    for (guiqueue, widget) in devicedict['guiqueues']:  # Put data into the guiqueue, this queue does always exist
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
            # Time to sleep, remove processing time
            dt_sleep = max([dt/4, dt - dt_dist])
            #print("dt_sleep",dt_sleep)
            if ((tstop - tinfo) > dt_info):
                tinfo = tstop
                info_dict = {'type':'dt_avg','dt_avg': dt_avg / navg,'packets_processed': packets_processed,'packets_counter':packet_counter,'thread_start':thread_start}
                #print("sending info",info_dict)
                packets_processed = 0
                # print(info_dict)
                try:
                    infoqueue.put_nowait(info_dict)
                except:
                    pass
        except:
            logger_dist.warning(funcname + 'Could not distribute packets:', exc_info=True)


class Redvypr(QtCore.QObject):
    """This is the redvypr heart. Here devices are added/threads
    are started and data is interchanged.

    """
    device_path_changed = QtCore.pyqtSignal()  # Signal notifying if the device path was changed
    device_added = QtCore.pyqtSignal(list)  # Signal notifying that a device was added
    device_removed = QtCore.pyqtSignal()  # Signal notifying that a device was removed
    devices_connected = QtCore.pyqtSignal(str, str)  # Signal notifying if two devices were connected
    devices_disconnected = QtCore.pyqtSignal(str, str)  # Signal notifying if two devices were connected
    status_update_signal = QtCore.pyqtSignal()  # Signal notifying if the status of redvypr has been changed
    metadata_changed_signal = QtCore.pyqtSignal()  # Signal notifying if the status of redvypr has been changed
    device_status_changed_signal = QtCore.pyqtSignal()  # Signal notifying if datastreams have been added
    hostconfig_changed_signal = QtCore.pyqtSignal()  # Signal notifying if the configuration of the host changed (hostname, hostinfo_opt)

    def __init__(self,config=None,hostname=None,nogui=False,loglevel=None,redvypr_device_scan=None):
        """

        Parameters
        ----------
        config:
            Configuration
        hostname: str
            The hostname of the redvypr instance
        nogui: bool
            No gui if True
        loglevel: logging.loglevel
            The loglevel
        redvypr_device_scan: RedvyprDeviceScan
            External RedvyprDeviceScan object to allow fine grained devices
        """
        super(Redvypr, self).__init__()
        if loglevel is not None:
            logger.setLevel(loglevel)
            logger.debug('Setting loglevel to global: "{}"'.format(loglevel))
        self.__platform__ = __platform__
        funcname = __name__ + '.__init__()'
        logger.debug(funcname)

        if config is None:
            logger.debug(funcname + 'Creating config')
            config = RedvyprConfig(hostname=hostname)
            logger.debug(funcname + 'Config {}'.format(config))

        # print(__platform__)
        # Overwrite hostname with argument
        if hostname is not None:
            config.hostname = hostname

        # global loglevel
        #print('Loglevel',loglevel)
        if loglevel is not None:
            logger.setLevel(loglevel)
            logger.debug('Setting loglevel to global: "{}"'.format(loglevel))
        else: # config loglevel
            try:
                logger.setLevel(config.loglevel)
            except:
                logger.debug('Could not set loglevel to: "{}"'.format(config.loglevel))

        self.hostinfo = create_hostinfo(hostname=config.hostname)
        self.metadata = config.metadata

        self.config = config # This is the initial version
        self.properties = {}  # Properties that are distributed with the device
        self.numdevice = 0
        self.devices = []  # List containing dictionaries with information about all attached devices
        self.device_paths = []  # A list of pathes to be searched for devices
        self.datastreams_dict = {} # Information about all datastreams, this is updated by distribute data
        self.deviceinfo_all = {'device_redvypr':{},'metadata':{}} # Information about all devices, this is updated by distribute data

        self.packets_counter = 0 # Counter for the total number of packets processed
        self.dt_datadist = 0.01  # The time interval of datadistribution
        self.dt_avg_datadist = 0.00  # The time interval of datadistribution
        self.datadistinfoqueue = queue.Queue(maxsize=1000)  # A queue to get informations from the datadistthread
        self.redvyprqueue = queue.Queue()  # A queue to send informations to the datadistthread
        self.redvyprreplyqueue = queue.Queue()  # A queue to send informations to the datadistthread
        # Lets start the distribution!
        self.datadistthread = threading.Thread(target=distribute_data, args=(
        self.devices, self.hostinfo, self.deviceinfo_all, self.datadistinfoqueue, self.redvyprqueue, self.redvyprreplyqueue, self.dt_datadist), daemon=True)
        self.t_thread_start = time.time()
        self.datadistthread.start()

        if redvypr_device_scan is None:
            logger.debug(funcname + ':Searching for devices')
            loglevel_device_scan = logger.getEffectiveLevel()
            #print('Loglevel device scan',loglevel_device_scan,logging.getLevelName(loglevel_device_scan))
            self.redvypr_device_scan = RedvyprDeviceScan(device_path = self.device_paths, redvypr_devices=redvyprdevices, loglevel=loglevel_device_scan)
        else:
            self.redvypr_device_scan = redvypr_device_scan

        logger.debug(funcname + ':Done searching for devices')
        # And now add the devices
        self.add_devices_from_config(config=self.config)
        # A timer to check the status of all threads
        self.devicethreadtimer = QtCore.QTimer()
        self.devicethreadtimer.timeout.connect(self.update_status)  # Add to the timer another update
        self.devicethreadtimer.start(250)
        print('LOGLEVEL',loglevel)
        if loglevel is None:
            loglevel = 'INFO'
        self.set_loglevel(loggername='redvypr',loglevel=loglevel)
        # A timer to print the status in the nogui environment
        if (nogui):
            self.statustimer = QtCore.QTimer()
            self.statustimer.timeout.connect(self.print_status)
            self.statustimer.start(5000)

    def apply_config(self, config, use_metadata=True,
                    use_loglevel=False, use_devices=True):
        """
        Applies a redvypr config from a filename
        Returns
        -------

        """
        redvypr_config = merge_configuration(config)
        if use_devices:
            self.add_devices_from_config(redvypr_config, rename_if_exists=False)
        if use_metadata:
            print("Using metadata",redvypr_config.metadata)
            self.set_metadata_from_dict(redvypr_config.metadata)

    def get_config(self):
        """
        Creates a configuration dictionary out of the current state.

        Returns:
            config: configuration dictionary

        """
        funcname = __name__ + '.get_config():'
        logger.debug(funcname)
        # Devices
        devices = []
        for devicedict in self.devices:
            device = devicedict['device']
            device_config_tmp = device.get_config()
            devices.append(device_config_tmp)

        loglevel_tmp = logging.getLevelName(logger.getEffectiveLevel())
        config = RedvyprConfig(hostname=self.hostinfo['host'], metadata=self.metadata,
                               devicepaths=self.device_paths, loglevel=loglevel_tmp,
                               redvyp_version=version, date_created=str(datetime.datetime.utcnow()),
                               devices=devices)

        return config

    def load_config(self, fname, use_metadata=False,
                    use_loglevel=False, use_devices=True):
        funcname = __name__ + '.load_config():'
        logger.debug(funcname)
        self.apply_config(config=[fname], use_metadata=use_metadata, use_loglevel=use_loglevel, use_devices=use_devices)

    def save_config(self, fname=None, autostart=False, add_metadata=False, set_loglevel:typing.Optional[typing.Literal["DEBUG","INFO","WARNING"]]=None):
        config = self.get_config()
        data_save = config.model_dump()
        print('Data save',data_save)
        if not(fname):
            tstr = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
            fname = 'config_' + self.hostinfo[
                'host'] + '_' + tstr + '.yaml'
        if set_loglevel:
            data_save['loglevel'] = set_loglevel

            for d in data_save['devices']:
                d['base_config']['autostart'] = autostart
                if set_loglevel:
                    d['base_config']['loglevel'] = set_loglevel

        if add_metadata:
            metadata = self.get_metadata()
            data_save['metadata'] = metadata

        if fname:
            logger.debug('Saving to file {:s}'.format(fname))
            with open(fname, 'w') as fyaml:
                yaml.dump(data_save, fyaml)



    def get_devicemodulename_from_str(self, devicename):
        """
        Tries to find a devicemodulename from devicename
        :param devicename:
        :return:
        """
        devicemodulename = None
        funcname = __name__ + '.get_devicemodulename_from_str():'
        logger.debug(funcname)
        #print('Devicename',devicename)
        # Make an exact test first
        for smod in self.redvypr_device_scan.redvypr_devices_flat:
            #print('device:',smod['name'],devicename)
            # The smod['name'] looks like 'redvypr.devices.network.zeromq_device'
            # Check first if devicemodulename has a '.', if not, use split smod['name'] and use the last one
            FLAG_DEVICEMODULENAME_EXACT = False
            if '.' in devicename:
                if (devicename == smod['name']):
                    logger.debug(funcname + ' Found exact fit {}'.format(devicename))
                    FLAG_DEVICEMODULENAME_EXACT = True
                    devicemodulename = smod['name']
                    break
            else:
                smodname = smod['name'].split('.')[-1]
                # print('smodname',smodname)
                if (devicename == smodname):
                    logger.debug(funcname + ' Found exact fit of last entry {}'.format(devicename))
                    FLAG_DEVICEMODULENAME_EXACT = True
                    # device.devicemodulename_orig = device.devicemodulename
                    devicemodulename = smod['name']
                    break

        # Make a test if the string is within the devicemodulename
        if FLAG_DEVICEMODULENAME_EXACT == False:
            logger.debug(funcname + ' Could not add exact fit, searching for substrings')
            for smod in self.redvypr_device_scan.redvypr_devices_flat:
                if (devicename in smod['name']):  # This is a weaker test, can be potentially replaced by regex
                    # device.devicemodulename_orig = device.devicemodulename
                    devicemodulename = smod['name']
                    break

        return devicemodulename

    def add_devices_from_config(self, config, rename_if_exists=True):
        funcname = "add_devices_from_config():"
        logger.debug(funcname)
        # Apply the configuration
        if config is not None:
            #print('Config parameter', config, type(config))
            #print('Devicepaths', type(config), type(config.hostname), config.devicepaths)
            # Add device path if found
            devpath = config.devicepaths
            if (type(devpath) == str):
                devpath = [devpath]

            FLAG_NEW_DEVPATH = False
            for p in devpath:
                if (p not in self.device_paths):
                    self.device_paths.append(p)
                    FLAG_NEW_DEVPATH = True

            if FLAG_NEW_DEVPATH:
                self.redvypr_device_scan.scan_devicepath()
                self.device_path_changed.emit()  # Notify about the changes

            # Adding the devices found in the config ['devices']
            # Check if we have a list or something
            #print('devices',config.devices,iter(config.devices))
            try:
                iter(config.devices)
                hasdevices = True
            except:
                hasdevices = False

            # Add the devices
            if (hasdevices):
                for device in config.devices:
                    logger.debug(funcname + 'Adding device {}'.format(device))
                    #print('Devicemodulename:',device.devicemodulename)
                    devicename = device.devicemodulename
                    devicemodulename = self.get_devicemodulename_from_str(devicename)
                    if devicemodulename is not None:
                        device.devicemodulename = devicemodulename
                        logger.info(funcname + 'Adding device {}'.format(device.devicemodulename))
                        #print('-------')
                        #print('Device',device)
                        #print('-------')
                        subscriptions = device.subscriptions
                        try:
                            dev_added = self.add_device(devicemodulename=device.devicemodulename,
                                                        custom_config=device.custom_config,
                                                        base_config=device.base_config,
                                                        subscriptions=subscriptions,
                                                        rename_if_name_exists=rename_if_exists)
                        except:
                            logger.warning('Could not add device',exc_info=True)

                    else:
                        logger.warning(funcname + ' Could not find devicemodulename {}'.format(devicemodulename))

        # Emit a signal that the configuration has been changed
        self.hostconfig_changed_signal.emit()

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
                FLAG_publishes = (publishes == dev.publishes) or (publishes == None)
                FLAG_subscribes = (subscribes == dev.subscribes) or (subscribes == None)
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
                raddress = redvypr_address.RedvyprAddress(data)
                #print('Got data with address',raddress)
                try:
                    if "type" in data.keys():
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
                    elif raddress.packetid == 'metadata':
                        logger.debug(funcname + "Got metadata, emitting signal")
                        metadata_new = data["deviceinfo_all"]["metadata"]
                        self.metadata_changed_signal.emit()


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
        statusstr = "{:s}, {:s}, num devices {:d}".format(tstr, self.hostinfo['host'], len(self.devices))

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

    def add_device(self, devicemodulename=None, custom_config=None, base_config=None, subscriptions=[],
                   rename_if_name_exists=True):
        """
        Function adds a device to redvypr

        Args:
            :param devicemodulename:
            :param custom_config: A dictionary with the configuration, this is filled by i.e. a yaml file with the configuration or if clicked in the gui just the name of the device
            :param device_parameter:

        Returns:
            device: the device added


        """
        funcname = self.__class__.__name__ + '.add_device():'
        logger.debug(funcname + ':devicemodule: ' + str(devicemodulename) + ':deviceconfig: ' + str(custom_config))
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
                    pydantic_base_config = devicemodule.DeviceBaseConfig()
                    logger.debug(funcname + ':Found pydantic base configuation {:s}'.format(str(devicemodule)))
                    FLAG_HAS_PYDANTICBASE = True
                    FLAG_PYDANTIC = True
                    # Create or use a given device parameter object
                    #print('type base config',type(base_config))
                    if isinstance(base_config, RedvyprDeviceParameter):
                        #print('Got a device parameter config')
                        device_parameter = base_config
                    elif isinstance(base_config, RedvyprDeviceBaseConfig):
                        #print('Got a base config',base_config)
                        device_parameter = RedvyprDeviceParameter(**base_config.model_dump())
                        #print('parameter',device_parameter)
                    elif isinstance(base_config, dict):
                        #print('Will update from config dictionary')
                        device_parameter_tmp = RedvyprDeviceParameter()
                        device_parameter = device_parameter_tmp.model_copy(update=base_config)
                    else:
                        #print('Standard base_config')
                        device_parameter = RedvyprDeviceParameter()

                    device_parameter.devicemodulename = devicemodulename
                    device_parameter.numdevice = self.numdevice
                    #print('Device parameter',device_parameter)
                    # Update the device parameter with the parameters of the device
                    device_parameter = device_parameter.model_copy(update=pydantic_base_config.model_dump())
                    #print('Device parameter 2', device_parameter)

                except Exception as e:
                    logger.debug(
                        funcname + ':No pydantic base configuration template of device {:s}: {:s}'.format(str(devicemodule), str(e)))
                    # Standard base config with parameter
                    if base_config is not None:
                        device_parameter = RedvyprDeviceParameter(**base_config.model_dump())
                        device_parameter.devicemodulename=devicemodulename
                        device_parameter.numdevice=self.numdevice
                        #print('Device parameter ...',device_parameter)
                    #logger.exception(e)
                    FLAG_HAS_PYDANTICBASE = False
                    FLAG_PYDANTIC = False

                # Try to get a pydantic device specific configuration (the configuration only for the device)
                try:
                    pydantic_device_config = devicemodule.DeviceCustomConfig()
                    #print('Device config of module',pydantic_device_config,type(pydantic_device_config))
                    #print('deviceconfig', custom_config, type(custom_config))

                    try:
                        #print('Custom_Config',custom_config)
                        if custom_config is not None:
                            #print('Dump',custom_config.model_dump())
                            pydantic_custom_config = devicemodule.DeviceCustomConfig.model_validate(custom_config.model_dump())
                        else:
                            pydantic_custom_config = devicemodule.DeviceCustomConfig()
                    except:
                        logger.debug('No config found',exc_info=True)
                        pydantic_custom_config = devicemodule.DeviceCustomConfig()

                    logger.debug(funcname + ':Found pydantic configuration {:s}'.format(str(devicemodule)))
                    #redvypr_device_parameter.config = pydantic_device_config
                    FLAG_HAS_PYDANTIC = True
                except Exception as e:
                    logger.debug(
                        funcname + ':No pydantic configuration template of device {:s}: {:s}'.format(str(devicemodule),
                                                                                            str(e)))
                    #logger.exception(e)
                    FLAG_HAS_PYDANTIC = False
                    pydantic_custom_config = None

                if(device_parameter.maxdevices > 0):
                    ndevices = 0
                    for d in self.devices:
                        devname = d['device'].devicemodulename
                        if(devname == devicemodulename):
                            ndevices += 1

                    if ndevices >= device_parameter.maxdevices:
                        logger.warning(funcname + ' Could not add {:s}, maximum number of {:d} devices reached'.format(devicemodulename,device_parameter.maxdevices))
                        return

                # If the device does not have a name, add a standard but unique one
                devicenames = self.get_all_devicenames()
                #print('Devicenames',devicenames)
                #print('device_parameter',device_parameter)
                #print('devicemodulename', devicemodulename)
                #print('devicename 0',device_parameter.name,len(device_parameter.name))
                devicename_tmp = device_parameter.name
                #print('Devicename_tmp', devicename_tmp)
                if len(device_parameter.name) == 0:
                    logger.debug(funcname + 'using standard name')
                    devicename_tmp = devicemodulename.split('.')[-1]# + '_' + str(self.numdevice)
                    #print('Devicename_tmp',devicename_tmp)

                # Check if the devicename exists already
                if devicename_tmp in devicenames:
                    if rename_if_name_exists:
                        logger.warning(funcname + ' Devicename {:s} exists already, will add {:d} to the name.'.format(devicename_tmp,self.numdevice))
                        devicename_tmp += '_' + str(self.numdevice)
                    else:
                        raise ValueError('Device {} exists already'.format(devicename_tmp))

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

                # guiqueues list
                guiqueues = [[guiqueue, None]]
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
                        # TODO: This seems to be bogus, double check
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
                        Device = RedvyprDevice
                        startfunction = devicemodule.start

                    # Config used at all?
                    #print('Getting config')

                    #print('Done')


                    if FLAG_HAS_PYDANTIC:
                        logger.debug(funcname + ' Using pydantic config')

                    logger.debug(funcname + 'Custom config for device')
                    logger.debug(funcname + 'Config: {:s}'.format(str(pydantic_custom_config)))
                    # Set the loglevel
                    try:
                        level = custom_config['loglevel']
                    except Exception as e:
                        logger.info(funcname + 'Setting loglevel to standard')
                        # Set the loglevel
                        level = logger.getEffectiveLevel()

                    levelname = logging.getLevelName(level)
                    logger.debug(funcname + 'Setting the loglevel to {}'.format(levelname))
                    device_parameter.loglevel = levelname
                    # Creating the device
                    #print('Deviceparameter',device_parameter)
                    device = Device(device_parameter=device_parameter, custom_config=pydantic_custom_config,
                                    redvypr=self, dataqueue=dataqueue,
                                    comqueue=comqueue, datainqueue=datainqueue,
                                    statusqueue=statusqueue, guiqueues=guiqueues,
                                    statistics=statistics, startfunction=startfunction)

                    # Subscribe to info packets from redvypr itself
                    device.subscribe_address(redvypr_address.metadata_address)
                    device.subscription_changed_signal.connect(self.process_subscription_changed)
                    self.numdevice += 1
                    # If the device has a logger
                    devicelogger = device.logger
                except Exception as e:
                    logger.warning(funcname + ' Could not add device because of:')
                    logger.exception(e)


                devicedict = {'device':device, 'guiqueues': guiqueues,
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
                #print('Autostart autostart',autostart)
                if (autostart):
                    logger.info(funcname + ': Starting device')
                    self.start_device_thread(device)

                devicelist = [devicedict, ind_device, devicemodule]

                #
                # Subscribe to devices
                #
                try:
                    subscribe_addresses = subscriptions
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

        return device

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
                #print('scanning')
                #self.redvypr_device_scan.logger.setLevel(logging.DEBUG)
                self.redvypr_device_scan.scan_devicepath()
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
        logger.debug('Subscribtion changed {}'.format(devsender.name))
        for d in self.devices:
            dev = d['device']
            if dev == devsender:
                continue
            dev.subscription_changed_global(devsender)

    def set_loglevel(self,loglevel='INFO', loggername='redvypr', propagate_down=True):
        """
        Sets the loglevel of the logger and to the children if propate_down==True

        Parameters
        ----------
        loggername
        loglevel
        propagate_down

        Returns
        -------

        """
        try:
            logger_tmp = logging.getLogger(loggername)
        except:
            raise ValueError('Could not find logger')

        logger_tmp.setLevel(loglevel)
        if propagate_down:
            for logger_child in logger_tmp.getChildren():
                self.set_loglevel(loglevel,logger_child.name,propagate_down)

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


    def get_device_objects(self, publishes=None, subscribes=True):
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

    def get_packetids(self):
        """
        Returns a list of all packetids this host has been seen
        Returns:
            List of packetids (str)
        """
        packetids = []
        for dev in self.devices:
            dkeys = dev['device'].get_packetids()
            packetids.extend(dkeys)

        packetids = list(set(packetids))
        packetids.sort()
        return packetids

    def get_metadata(self, address: None | str | RedvyprAddress = None,
                    mode: typing.Literal["merge", "expanded"] = "expanded"):
        funcname = __name__ + 'get_metadata():'
        logger.debug(funcname)
        deviceinfo_all = self.get_deviceinfo()
        #print("Deviceonfi all new",deviceinfo_all)
        #print("Mode redvypr",mode)
        metadata = redvypr_packet_statistic.get_metadata(deviceinfo_all, address=address, mode=mode)
        return metadata

    def get_metadata_in_range(
            self,
            address: str | RedvyprAddress,
            t1: datetime.datetime,
            t2: datetime.datetime,
            mode: typing.Literal["merge", "expanded"] = "expanded"
    ):
        """
        Returns all metadata and constraints that were active at any point
        between t1 and t2.
        """
        # 1. Get raw hierarchical metadata
        raw_data = self.get_metadata(address, mode=mode)

        results = {}

        for addr, content in raw_data.items():
            # Keep static metadata
            addr_result = {k: v for k, v in content.items() if k != '_constraints'}
            addr_result['_constraints'] = []

            constraints = content.get('_constraints', [])

            for rule in constraints:
                # Extract time boundaries from the rule
                r_start = None
                r_end = None
                for cond in rule['conditions']:
                    if cond['field'] == 't':
                        val = cond['value']
                        dt_val = datetime.datetime.fromisoformat(val) if isinstance(val,
                                                                                    str) else val

                        if cond['op'] in ['>', '>=']: r_start = dt_val
                        if cond['op'] in ['<', '<=']: r_end = dt_val

                #print(f"Comparing Rule {r_start} > Query {t2}:{r_start and t2 and r_start > t2}")
                #print(f"Comparing Rule {r_end} < Query {t1}:{r_end and t1 and r_end < t1}")
                # Logic for overlap:
                # A rule is relevant if its start is before our end AND its end is after our start
                is_relevant = True
                if r_start and t2 and r_start > t2:
                    is_relevant = False
                if r_end and t1 and r_end < t1:
                    is_relevant = False

                #print("Is relevant",is_relevant)
                if is_relevant:
                    addr_result['_constraints'].append(rule)

            results[addr] = addr_result

        return results

    def get_metadata_commandpacket(self, device=''):
        funcname = __name__ + 'get_metadata_commandpacket():'
        logger.debug(funcname)
        deviceinfo_all = self.get_deviceinfo()
        compacket = data_packets.commandpacket('info', host=self.hostinfo, devicename=device, packetid='metadata')
        compacket['deviceinfo_all'] = copy.deepcopy(deviceinfo_all)
        tread = time.time()
        redvypr_packet_statistic.treat_datadict(compacket, '', self.hostinfo, 0, tread,
                                                'distribute_data')
        return compacket

    def set_metadata(self, address: str | RedvyprAddress, metadata: dict):
        """
        Sets the metadata of address.
        :param address:
        :param metadata:
        :return:
        """
        funcname = __name__ + '.set_metadata():'
        logger.debug(funcname)
        address_str = str(redvypr.RedvyprAddress(address))
        datapacket = redvypr.data_packets.commandpacket(command='reply') # Arbitrary
        datapacket['_metadata'] = {}
        datapacket['_metadata'][address_str] = metadata
        self.redvyprqueue.put(datapacket)
        # Wait for the response
        data = self.redvyprreplyqueue.get()
        logger.debug(funcname + 'Metadata sent')

    def set_metadata_from_dict(self, metadata: dict):
        """
        Sets the metadata of address.
        :param metadata: metadata dict, keys must be valid RedvyprAddress strings and data must be dictionaries
        :return:
        """
        funcname = __name__ + '.set_metadata_from_dict():'
        logger.debug(funcname)
        datapacket = redvypr.data_packets.commandpacket(command='reply')  # Arbitrary
        datapacket['_metadata'] = {}

        for address,metadata_address in metadata.items():
            try:
                address_str = str(redvypr.RedvyprAddress(address))
            except:
                raise ValueError("The keys of the metadata dictionary must be a valid RedvyprAddress string")

            if isinstance(metadata_address,dict):
                datapacket['_metadata'][address_str] = metadata_address
            else:
                raise ValueError(
                    "The data of the metadata dictionary must be a dictionary")
        self.redvyprqueue.put(datapacket)
        # Wait for the response
        data = self.redvyprreplyqueue.get()
        logger.debug(funcname + 'Metadata sent')

    def add_metadata_time_constrained(
            self,
            address: str | RedvyprAddress,
            metadata: dict,
            t1: datetime.datetime | str | None = None,
            t2: datetime.datetime | str | None = None
    ):
        """
        Adds metadata that is only valid within the time range [t1, t2].
        :param address: Target address.
        :param metadata: The dictionary of metadata to apply if conditions are met.
        :param t1: Start timestamp (inclusive). If None, valid from the beginning of time.
        :param t2: End timestamp (inclusive). If None, valid until the end of time.
        """
        funcname = f"{__name__}.add_metadata_time_constrained():"
        logger.debug(funcname)

        # Ensure we have a consistent string representation of the address
        address_str = str(redvypr.RedvyprAddress(address))

        conditions = []

        # Helper to convert datetime objects to ISO strings if necessary
        def format_time(t):
            return t.isoformat() if hasattr(t, 'isoformat') else t

        # Add start time condition
        if t1 is not None:
            conditions.append({
                'field': 't',
                'op': '>=',
                'value': format_time(t1)
            })

        # Add end time condition
        if t2 is not None:
            conditions.append({
                'field': 't',
                'op': '<=',
                'value': format_time(t2)
            })

        # Create the command packet
        datapacket = redvypr.data_packets.commandpacket(command='reply')

        # Using a specific key '_metadata_add_constraint' to tell the backend
        # to append this to the existing list instead of overwriting.
        constrain = {'conditions': conditions,
                'values': metadata
            }
        metadata_conditions = {'_constraints': [constrain]}

        datapacket['_metadata'] = {}
        datapacket['_metadata'][address_str] = metadata_conditions

        # Example of sending the packet
        # self.send(datapacket)
        print(f"Sent time-constrained metadata for {address_str}")
        self.redvyprqueue.put(datapacket)
        # Wait for the response
        data = self.redvyprreplyqueue.get()
        logger.debug(funcname + 'Metadata sent')

    def rem_metadata(self, address: str | RedvyprAddress, metadata_keys: list | None = None, constraint_entries: list | None = None, mode="exact"):
        """

        Parameters
        ----------
        address
        metadata_keys
        constraint_entries
        mode: "exact" or "matches"

        Returns
        -------

        """
        funcname = __name__ + '.rem_metadata():'
        logger.debug(funcname)
        address_str = str(redvypr.RedvyprAddress(address))
        datapacket = redvypr.data_packets.commandpacket(command='reply') # Arbitrary
        datapacket['_metadata_remove'] = {}
        datapacket['_metadata_remove'][address_str] = {'keys':metadata_keys,'constraints':constraint_entries,'mode':mode}
        self.redvyprqueue.put(datapacket)
        # Wait for the response
        data = self.redvyprreplyqueue.get()
        logger.debug(funcname + 'Metadata remove sent')


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
        logger.debug(funcname +'Removing device:{}'.format(device.name))
        FLAG_REMOVED = False
        # Search for the device in sendict
        for sendict in self.devices:
            if(sendict['device'] == device):
                #print('Sendict',sendict)
                if (sendict['device'].thread == None):
                    logger.debug(funcname + 'Thread is not running, doing nothing')
                    pass
                elif (sendict['device'].thread_running()):
                    logger.debug(funcname + 'Sending stop command')
                    device.thread_stop()

                device.stop_and_cleanup()
                self.devices.remove(sendict)
                FLAG_REMOVED = True
                self.device_removed.emit()
                device_changed_dict = {'type':'device_removed','device':device.name,'uuid':device.uuid}
                self.redvyprqueue.put(device_changed_dict)
                break

        return FLAG_REMOVED


def load_config_file(fname):
    funcname = __name__ + '.load_config_file()'
    if (os.path.exists(fname)):
        fconfig = open(fname)
        try:
            config_tmp = yaml.load(fconfig, Loader=yaml.SafeLoader)
        except:
            logger.warning(funcname + 'Could not load yaml file with safe loader')
            fconfig.close()
            fconfig = open(fconfig)
            try:
                config_tmp = yaml.load(fconfig, Loader=yaml.CLoader)
                logger.debug('Config tmp {}'.format(config_tmp))
            except:
                logger.warning(funcname + ' Could not load yaml file with x loader')
                return None

        config_tmp = redvypr.RedvyprConfig(**config_tmp)
        return config_tmp
    else:
        logger.warning(funcname + 'Yaml file: ' + str(fname) + ' does not exist!')
        return None


def merge_configuration(redvypr_config=None):
    """
    Merges a list of configurations
    :param redvypr_config:
    :return:
    """
    funcname = "merge_configuration():"
    parsed_devices = []
    logger.debug(funcname)

    if (redvypr_config is not None):
        logger.debug(funcname + 'Configuration: ' + str(redvypr_config))
        if (type(redvypr_config) == str):
            redvypr_config = [redvypr_config]
    else:
        return False

    config_tmp = redvypr.RedvyprConfig()
    devices_all = []
    devicepath_all = []
    for iconf, configraw in enumerate(redvypr_config):
        #print('Configraw',configraw)
        #print('iconf', iconf,type(configraw))
        if isinstance(configraw, redvypr.RedvyprConfig):
            logger.info(funcname + ' Found redvypr config')
            config_tmp = configraw
        elif (type(configraw) == str):
            logger.info(funcname + 'Opening yaml file: ' + str(configraw))
            config_tmp = load_config_file(configraw)
            if not(config_tmp): # If None, dont care
                continue
        elif (type(configraw) == dict):
            logger.debug(funcname + 'Opening dictionary')
            config_tmp = redvypr.RedvyprConfig(**configraw)
        else:
            logger.warning(funcname + 'Unknown type of configuration {:s}'.format(type(configraw)))
            continue

        # Merge the configuration into one big dictionary
        devices_all.extend(config_tmp.devices)
        devicepath_all.extend(config_tmp.devicepaths)
        #print('Config tmp', config_tmp)
        # config = config.model_copy(update=config_tmp)
    config_tmp2 = redvypr.RedvyprConfig(devices=devices_all, devicepaths=devicepath_all)
    config = config_tmp2.model_copy(update=config_tmp.model_dump(exclude=['devices', 'devicepaths']))
    #print('Config', config)
    return config
