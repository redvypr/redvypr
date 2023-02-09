"""

Internet of Redvypr (iored) device

Multicast
---------
The device provides a multicast based information of the datastreams provided by the redvypr host.
It does also listens to multicasts from other redvypr hosts. If a info is received it is sent as a blank datapcket.
The distribute_data/do_statistics functionality will add the remote device and host to the available datastreams and will
create a datastream_changed signal. That signal is connected by iored and the display widget for an update of datastreams
sent over multicast and displayed in the gui.

Zeromq pub/sub
--------------

The data that is published is a multipart packet::

    [b'test_device_0:redvypr@192.168.236.188::93328248922693-217', b't1675787270.261712', b'_redvypr:\n  device: test_device_0\n  devicemodulename: test_device\n  host:\n    addr: 192.168.236.188\n    hostname: redvypr\n    local: true\n    tstart: 1675787257.351031\n    uuid: 93328248922693-217\n  numpacket: 4\n  t: 1675787257.50375\ndata: Hello World!\nt: 1675787257.50375\n']

The first part is the address of the device "test_device_0:redvypr@192.168.236.188::93328248922693-217", the format is "'<device>:<host>@<addr>::<uuid>'"
The second part the unix time as a string: "t1675787270.261712"
The third part the data packet as a yaml string

How subscriptions work:

iored compares all subscriptions of this host with all online iored/redvyprs. If there is a match, the host will be subscribed.


"""


import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import threading
#from apt_pkg import config
import yaml
import copy
import zmq
import socket
import struct
from redvypr.device import redvypr_device
from redvypr.data_packets import check_for_command
import redvypr.data_packets as data_packets



zmq_context = zmq.Context()
description = 'Internet of Redvypr, device allows to easily connect to other redvypr devices '

config_template = {}
config_template['template_name']  = 'iored'
config_template['redvypr_device'] = {}
config_template['multicast_address']  = "239.255.255.239"
config_template['multicast_port']     = 18196
config_template['zmq_pub_port_start'] = 18196
config_template['zmq_pub_port_end']   = 19000
config_template['redvypr_device']['publish']   = True
config_template['redvypr_device']['subscribe'] = True
config_template['redvypr_device']['description'] = description

multicast_header = {}
multicast_header['info']    = b'redvypr info'
multicast_header['getinfo'] = b'redvypr getinfo'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('iored')
logger.setLevel(logging.DEBUG)


def process_multicast_packet(datab):
    """
    Processes multicast information from a redvypr instance.

    Args:
        datab: Binary data

    Returns:

    """
    funcname = __name__ + '.process_multicast_packet()'
    #print('Received multicast data', datab)
    redvypr_info = None
    if datab.startswith(multicast_header['info']): # Search for info packet
        try:
            headerlen = len(multicast_header['info'])
            data = datab.decode('utf-8')
            # TODO We could put here a load command if the data is not yaml conform
            redvypr_info = yaml.safe_load(data[headerlen:])
            return ['info',redvypr_info]
        except Exception as e:
            redvypr_info = ['info',None]

    elif datab.startswith(multicast_header['getinfo']):  # Search for getinfo request
        try:
            headerlen = len(multicast_header['getinfo'])
            data = datab.decode('utf-8')
            redvypr_info = yaml.safe_load(data[headerlen:])
            return ['getinfo', redvypr_info]
        except Exception as e:
            redvypr_info = ['info', None]

    return [None,None]

def create_datapacket_from_deviceinfo(device_info):
    """

    Args:
        redvypr_info:

    Returns:
        Either a list of datapackets (datastream == None) or a single datapacket if a datastream equal to the argument "datastream" was found.

    """
    funcname = __name__ + '.create_datapackets_from_deviceinfo()'
    d = device_info
    if True:
        dpacket = {}
        dpacket['_redvypr']  = d['_redvypr']
        dpacket['_redvypr']['subscribeable'] = True
        dpacket['_redvypr']['subscribed'] = False
        dpacket['_info'] = d['_info']
        dpacket['_keyinfo']  = d['_keyinfo']
        return dpacket






def start_zmq_sub(dataqueue, comqueue, statusqueue, config, remote_uuid):
    """ zeromq receiving data
    """
    funcname = __name__ + '.start_recv()'
    datastreams_dict = {}
    status = {'sub':[],'uuid':remote_uuid}
    sub = zmq_context.socket(zmq.SUB)
    url = config['zmq_sub']
    logger.debug(funcname + ':Start receiving data from url {:s}'.format(url))
    sub.setsockopt(zmq.RCVTIMEO, 200)
    sub.connect(url)
    datapackets = 0
    bytes_read  = 0
    npackets    = 0 # Number packets received
    while True:
        try:
            com = comqueue.get(block=False)
        except:
            com = None

        if com is not None:
            if(com == 'stop'):
                logger.info(funcname + ' stopping zmq socket to {:s}'.format(url))
                sub.close()
                break

            elif com.startswith('sub'):
                substring = com.rsplit(' ')[1]
                logger.info(funcname + ' subscribing to {:s}'.format(substring))
                substringb = substring.encode('utf-8')
                sub.setsockopt(zmq.SUBSCRIBE, substringb)
                status['sub'].append(substring)
                statusqueue.put(copy.deepcopy(status))
                comdata = {}
                comdata['deviceaddr']   = substring
                comdata['devicestatus'] = {'subscribed': True} # TODO, this is the status of the iored deveice, 'zmq_subscriptions': status['sub']}
                datapacket = data_packets.commandpacket(command='device_status', device_uuid='', thread_uuid='', devicename=None, host=None,comdata=comdata)
                dataqueue.put(datapacket)
                # datastreams_dict is dictionary from the device, changed in a thread, use only atomic operations
                try:
                    datastreams_dict[substring]
                except:
                    datastreams_dict[substring] = {}

                try:
                    datastreams_dict[substring]['status']
                except:
                    datastreams_dict[substring]['status'] = {}

                datastreams_dict[substring]['status']['zmq_url'] = url
                datastreams_dict[substring]['status']['subscribeable'] = True
                datastreams_dict[substring]['status']['subscribed'] = True


            elif com.startswith('unsub'):
                unsubstring = com.rsplit(' ')[1]
                logger.info(funcname + ' unsubscribing {:s}'.format(unsubstring))
                unsubstringb = unsubstring.encode('utf-8')
                sub.setsockopt(zmq.UNSUBSCRIBE, unsubstringb)
                try:
                    status['sub'].remove(unsubstring)
                except:
                    pass

                # datastreams_dict is dictionary from the device, changed in a thread, use only atomic operations
                try:
                    datastreams_dict[unsubstring]['status']['zmq_url'] = url
                    datastreams_dict[substring]['status']['subscribeable'] = True
                    datastreams_dict[unsubstring]['status']['subscribed'] = False
                except:
                    pass

                statusqueue.put(copy.deepcopy(status))
                comdata = {}
                comdata['deviceaddr'] = substring
                comdata['devicestatus'] = { 'subscribed': False}
                datapacket = data_packets.commandpacket(command='device_status', device_uuid='', thread_uuid='',
                                                        devicename=None, host=None, comdata=comdata)
                dataqueue.put(datapacket)
                #dataqueue.put(datapacket)


        try:
            #datab = sub.recv(zmq.NOBLOCK)
            datab_all = sub.recv_multipart()
            #print('Got data',datab_all)
            FLAG_DATA = True
        except Exception as e:
            #logger.debug(funcname + ':' + str(e))
            FLAG_DATA = False

        if FLAG_DATA:
            device = datab_all[0]  # The message
            t = datab_all[1] # The message
            datab = datab_all[2] # The message
            bytes_read += len(datab)
            # Check what data we are expecting and convert it accordingly
            if True:
                for databs in datab.split(b'...\n'): # Split the text into single subpackets
                    try:
                        data = yaml.safe_load(databs)
                        #print(datab)
                        #print(data)
                    except Exception as e:
                        logger.debug(funcname + ': Could not decode message {:s}'.format(str(datab)))
                        logger.debug(funcname + ': Could not decode message  with supposed format {:s} into something useful.'.format(str(config['data'])))
                        data = None

                    if((data is not None) and (type(data) == dict)):
                        dataqueue.put(data)
                        datapackets += 1



def start(device_info, config, dataqueue, datainqueue, statusqueue):
    """
    
    Args:
        device_info: 
        config: 
        dataqueue: 
        datainqueue: 
        statusqueue: 
        datastreams_dict: Dictionary with information about datastreams

    Returns:

    """
    logstart = logging.getLogger('iored_start')
    logstart.setLevel(logging.DEBUG)

    funcname = __name__ + '.start():'
    hostuuid = device_info['hostinfo']['uuid']
    devicename = device_info['devicename']
    logger.debug(funcname)
    receivers_subscribed    = [] # List of external receivers subscribed to own datastreams
    
    dt_sleep  = 0.05
    queuesize = 100 # The queuesize for the subthreads
    sockets   = [] # List of all sockets that need to be closed when thread is stopped
    hostinfos = {}
    zmq_sub_threads = {} # Dictionary with all remote redvypr hosts subscribed
    #
    # The multicast send socket
    #




    MULTICASTADDRESS = config['multicast_address'] # "239.255.255.250" # The same as SSDP
    MULTICASTPORT = config['multicast_port']
    tbeacon = 0
    dtbeacon = -1
    FLAG_MULTICAST_INFO = True
    FLAG_MULTICAST_GETINFO = True
    # socket.IP_MULTICAST_TTL
    # ---------------------------------
    # for all packets sent, after two hops on the network the packet will not
    # be re-sent/broadcast (see https://www.tldp.org/HOWTO/Multicast-HOWTO-6.html)
    MULTICAST_TTL = 2
    sock_multicast_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock_multicast_send.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)
    sockets.append(sock_multicast_send)
    FLAG_RUN = True
    # Multicast receive
    sock_multicast_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock_multicast_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if sys.platform == 'win32': # had to add this on 07.02.2023, win10/anaconda python 3.9.16
        sock_multicast_recv.bind(('', MULTICASTPORT))
    else:
        sock_multicast_recv.bind((MULTICASTADDRESS, MULTICASTPORT))

    mreq = struct.pack("4sl", socket.inet_aton(MULTICASTADDRESS), socket.INADDR_ANY)
    sock_multicast_recv.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock_multicast_recv.settimeout(0)  # timeout for listening
    sockets.append(sock_multicast_recv)

    #
    # Start the zeromq distribution
    #
    sock_zmq_pub = zmq_context.socket(zmq.XPUB)
    sock_zmq_pub.setsockopt(zmq.RCVTIMEO, 0)  # milliseconds
    zmq_ports = range(config['zmq_pub_port_start'],config_template['zmq_pub_port_end'])
    for zmq_port in zmq_ports:
        url = 'tcp://' + device_info['hostinfo']['addr'] + ':' + str(int(zmq_port))
        print('Trying to connect zmq pub to {:s}'.format(url))
        try:
            sock_zmq_pub.bind(url)
        except Exception as e:
            pass
        logstart.info(funcname + ':Start publishing data at url {:s}'.format(url))
        break

    sockets.append(sock_zmq_pub)

    #
    # Infinite loop
    #
    while True:
        tstart = time.time()
        #
        # Start Trying to receive data from multicast
        #
        try:
            data_multicast_recv = sock_multicast_recv.recv(10240) # This could be a potential problem as this is finite
        except:
            data_multicast_recv = None

        if(data_multicast_recv is not None):
            #print('Got multicast data',data_multicast_recv)
            print('Got multicast data')
            [multicast_command,redvypr_info] = process_multicast_packet(data_multicast_recv)
            #print('Command',multicast_command,redvypr_info)
            print('from uuid',redvypr_info['host']['uuid'])
            if multicast_command == 'getinfo':
                try:
                    print('Getinfo request from {:s}::{:s}'.format(redvypr_info['host']['hostname'], redvypr_info['host']['uuid']))
                except Exception as e:
                    logstart.exception(e)

                if redvypr_info['host']['uuid'] == device_info['hostinfo']['uuid']:
                    print('request from myself, doing nothing')
                    pass
                else:
                    FLAG_MULTICAST_INFO = True
            elif multicast_command == 'info':
                try:
                    uuid = redvypr_info['host']['uuid']
                except:
                    uuid = None

                if(uuid == hostuuid):
                    print('Own multicast packet')
                else:
                    print('Info from {:s}::{:s}'.format(redvypr_info['host']['hostname'],redvypr_info['host']['uuid']))
                    # Could be locked
                    hostinfos[uuid] = copy.deepcopy(redvypr_info) # Copy it to the hostinfo of the device. This should be thread safe
                    #
                    #print('redvypr_info',redvypr_info)
                    if 'deviceinfo_all' in redvypr_info.keys():
                        for dkeyhost in redvypr_info['deviceinfo_all'].keys():  # This is the host device
                            for dkey in redvypr_info['deviceinfo_all'][dkeyhost].keys():  # This is the device, typically only one, the hostdevice itself
                                #print('devicekey', dkeyhost,dkey)
                                d = redvypr_info['deviceinfo_all'][dkeyhost][dkey]
                                #print('device', d)
                                daddr = data_packets.redvypr_address(dkey)
                                if daddr.uuid == hostuuid: # This should not happen but anyways
                                    #print('Own device, doing nothing')
                                    pass
                                elif(d['_redvypr']['devicemodulename'] == 'iored'):
                                    #print('ioreddevice, doing nothing')
                                    pass
                                else:
                                    #print('Remote device')
                                    datapacket = create_datapacket_from_deviceinfo(d)
                                    # Send the packet, distribute_data() will call do_data_statistics() and will add them to the available datastreams
                                    # This will again create on return a signal that the datastreams have been changed
                                    #print('Sending datapacket to inform redvypr about available devices',datapacket)
                                    dataqueue.put_nowait(datapacket)

                        try:
                            datapacket = data_packets.commandpacket(command='device_status', device_uuid='', thread_uuid='', devicename=None, host=None)
                            #print('Sending statuscommand',datapacket)
                            dataqueue.put_nowait(datapacket)
                        except Exception as e:
                            pass
            #print('Received multicast data!!', data_multicast_recv)

        #
        # END Trying to receive data from multicast
        #
        #
        # START Sending multicast data
        #
        if (dtbeacon > 0) or FLAG_MULTICAST_INFO:
            if ((time.time() - tbeacon) > dtbeacon) or FLAG_MULTICAST_INFO:
                FLAG_MULTICAST_INFO = False
                #print('Sending multicast info',time.time())
                # print('datastreams',datastreams)
                #print('Deviceinfo all')
                #print('deviceinfo all', device_info['deviceinfo_all'])
                #print('----- Deviceinfo all done -----')
                multicast_packet = {'host': device_info['hostinfo'], 't': time.time(), 'zmq_pub': url,
                                    'deviceinfo_all': device_info['deviceinfo_all']}
                #print('--------------')
                #print('Multicast packet',multicast_packet)
                #print('--------------')
                hostinfoy = yaml.dump(multicast_packet, explicit_end=True, explicit_start=True)
                hostinfoy = hostinfoy.encode('utf-8')
                datab = multicast_header['info'] + hostinfoy
                sock_multicast_send.sendto(datab, (MULTICASTADDRESS, MULTICASTPORT))

                # print('Sending zmq data')
                # sock_zmq_pub.send_multipart([b'123',b'Hallo!'])
        if FLAG_MULTICAST_GETINFO:
            FLAG_MULTICAST_GETINFO = False
            #print('Sending multicast getinfo request')
            multicast_packet = {'host': device_info['hostinfo'], 't': time.time()}
            hostinfoy = yaml.dump(multicast_packet, explicit_end=True, explicit_start=True)
            hostinfoy = hostinfoy.encode('utf-8')
            datab = multicast_header['getinfo'] + hostinfoy
            sock_multicast_send.sendto(datab, (MULTICASTADDRESS, MULTICASTPORT))

        #
        # END Sending multicast data
        #

        #
        # START Try to receive subscription filter data from the xpub socket
        #
        try:
            data_pub = sock_zmq_pub.recv_multipart()
            receivers_subscribed.append(data_pub)
            #print('Received a subscription', data_pub,receivers_subscribed)
        except Exception as e:
            #print('e',e)
            pass
        #
        # END Try to receive subscription filter data from the xpub socket
        #


        #
        # Receive data packets and check if they are either a command or a data packet to send
        #
        while datainqueue.empty() == False:
            try:
                data = datainqueue.get(block=False)
            except:
                data = None

            if data is not None:
                command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
                #logger.debug('Got a command: {:s}'.format(str(data)))
                if command is not None:
                    logstart.debug('Command is for me: {:s}'.format(str(command)))
                    #queue_send_beacon.put_nowait(data)
                    #queue_recv_beacon.put_nowait(data)
                    if(command == 'stop'):
                        # Close all sockets
                        for s in sockets:
                            s.close()

                        for uuidkey in zmq_sub_threads.keys():
                            try:  # Send the command to the corresponding thread
                                zmq_sub_threads[uuidkey]['comqueue'].put('stop')
                            except Exception as e:
                                logstart.exception(e)

                        logstart.info(funcname + ': Stopped')
                        return
                    elif (command == 'deviceinfo_all'):
                        logstart.info(funcname + ': Got devices update')
                        device_info['deviceinfo_all'].update(data['deviceinfo_all'])
                        try:
                            if devicename in data['devices_changed']: # Check if devices except myself have been changed
                                #print('That was myself, will remove')
                                data['devices_changed'].remove(devicename)
                            if(len(data['devices_changed']) > 0):
                                FLAG_MULTICAST_INFO = True  # Send the information over multicast
                        except Exception as e:
                            logstart.debug(e)
                    elif (command == 'multicast_info'): # Multicast send infocommand
                        FLAG_MULTICAST_INFO = True
                    elif (command == 'multicast_getinfo'):  # Multicast command requesting info from other redvypr instances
                        FLAG_MULTICAST_GETINFO = True
                    elif (command == 'unsubscribe'):
                        remote_uuid = data['remote_uuid']
                        substring = data['substring']
                        zmq_url = hostinfos[remote_uuid]['zmq_pub']
                        logstart.info(
                            funcname + ': Unsubscribing from uuid {:s} at url {:s}'.format(remote_uuid, zmq_url))
                        try:  # Send the command to the corresponding thread
                            zmq_sub_threads[remote_uuid]['comqueue'].put('unsub ' + substring)
                        except Exception as e:
                            logstart.exception(e)

                    elif (command == 'subscribe'):
                        try:
                            remote_uuid = data['remote_uuid']
                            substring = data['substring']
                            zmq_url = hostinfos[remote_uuid]['zmq_pub']
                            logstart.info(
                                funcname + ': Subscribing to uuid {:s} at url {:s}'.format(remote_uuid, zmq_url))
                            try: # Lets check if the thread is already running
                                zmq_sub_threads[remote_uuid]['comqueue'].put('sub ' + substring)
                                FLAG_START_SUB_THREAD = False
                            except Exception as e:
                                zmq_sub_threads[remote_uuid] = {}
                                FLAG_START_SUB_THREAD = True

                            # If not running, create a thread and subscribe to
                            if FLAG_START_SUB_THREAD:
                                logstart.debug(funcname + ' Starting new thread')
                                config_zmq = {}
                                config_zmq['zmq_sub'] = zmq_url
                                comqueue = queue.Queue(maxsize=1000)
                                statqueue = queue.Queue(maxsize=1000)
                                zmq_sub_threads[remote_uuid]['comqueue']  = comqueue
                                zmq_sub_threads[remote_uuid]['statqueue'] = statqueue
                                zmq_sub_threads[remote_uuid]['thread']    = threading.Thread(target=start_zmq_sub, args=(dataqueue, comqueue, statqueue, config_zmq,remote_uuid))
                                zmq_sub_threads[remote_uuid]['thread'].start()
                                # Thread started, lets subscribe now
                                zmq_sub_threads[remote_uuid]['comqueue'].put('sub ' + substring)

                        except Exception as e:
                            logstart.error(funcname + ' Could not subscribe because of')
                            logstart.exception(e)

                        # Start/update the thread zeromq sub thread

                else: # data packet, lets send it
                    datab = yaml.dump(data,explicit_end=False,explicit_start=False).encode('utf-8')
                    #print('Got data from queue',data)
                    #
                    addrstr = data_packets.get_address_from_data('',data,style='<device>:<host>@<addr>::<uuid>')
                    #datasend = addrstr[1:].encode('utf-8') + ' '.encode('utf-8') + datab
                    tsend = 't{:.6f}'.format(time.time()).encode('utf-8')
                    datapacket = [addrstr[1:].encode('utf-8'), tsend, datab]
                    sock_zmq_pub.send_multipart(datapacket)


        # Read the status of all sub threads and update the dictionary
        for uuid in zmq_sub_threads.keys():
            try:
                status = zmq_sub_threads[uuid]['statqueue'].get(block=False)
                #print('Got status',status)
                zmq_sub_threads[uuid]['sub'] = status['sub']
                # Put the subscription status into the statusqueue, this is used for the device to update
                statusqueue.put({'subscribed':status['sub'],'uuid':uuid})
                #print('Got status threads', zmq_sub_threads)
            except Exception as e:
                #logstart.exception(e)
                pass

        tend = time.time()
        dt_usage = tend - tstart
        dt_realsleep = dt_sleep - dt_usage
        dt_realsleep = max([0, dt_realsleep]) # Check if the sleep is negative
        time.sleep(dt_realsleep)



class Device(redvypr_device):
    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)

        self.__zmq_sub_threads__ = {} # Dictionary with uuid of the remote hosts collecting information of the subscribed threads

        self.logger.info(funcname + ' subscribing to devices')
        self.autosubscribe = True # Automatically subscribe to remote devices if a local device subscription fits
        # Subscribe all
        self.subscribe_address('*')
        self.zmq_subscribed_to = {} # Dictionary with remote_uuid as key that hold all subscribed strings


    def start(self,device_info,config, dataqueue, datainqueue, statusqueue):
        """
        Custom start function
        Args:
            device_info:
            config:
            dataqueue:
            datainqueue:
            statusqueue:

        Returns:

        """
        funcname = __name__ + '.start()'
        # Deviceinfoall is used to announce all devices
        device_info['deviceinfo_all']   = self.redvypr.get_deviceinfo(publish=True)
        device_info['devicename']       = self.name
        device_info['devicemodulename'] = self.devicemodulename
        device_info['deviceuuid']       = self.uuid
        device_info['hostinfo_opt']     = copy.deepcopy(self.redvypr.hostinfo_opt)
        start(device_info,copy.deepcopy(config), dataqueue, datainqueue, statusqueue)

    def compare_zmq_subscription(self, subscription):
        """
        Compares if a redvypr_address is already subscribed or needs to be subscribed because a remote device is fitting
        the address
        Args:
            subscription: redvypr address

        Returns:
             list: [FLAG_FIT, uuid, address string, FLAG_SUBSCRIBED]
        """
        # The dictionary keys of self.statistics['device_redvypr'] are the same as the zmq multipart identifier
        all_remote_devices = self.statistics['device_redvypr'].keys()
        FLAG_SUB_FITS = False
        remote_uuid = None
        for address_string in all_remote_devices:
            daddr = data_packets.redvypr_address(address_string)
            FLAG_SUB_FITS = daddr in subscription
            #print('Comparing',address_string,subscription.get_str())
            if FLAG_SUB_FITS: # Comparing two redvpr_addresses
                remote_uuid      = daddr.uuid
                remote_device    = daddr.devicename
                remote_substring = address_string
                try:
                    self.zmq_subscribed_to[remote_uuid]
                except:
                    self.zmq_subscribed_to[remote_uuid] = []

                # Test if the device has already been subscribed
                FLAG_SUBSCRIBED = remote_substring in self.zmq_subscribed_to[remote_uuid]
                break

        if FLAG_SUB_FITS == False:
            address_string = ''


        return [FLAG_SUB_FITS,remote_uuid,address_string,FLAG_SUBSCRIBED]


    def test_zmq_unsubscribe(self):
        """
        Tests if zmq subscriptions are not neccesary anymore

        Returns:
            list:

        """
        all_subscriptions = self.redvypr.get_all_subscriptions()
        # Test if zmq subscriptions have to be removed
        unsubscribe_addresses = []
        for remote_uuid in self.zmq_subscribed_to.keys():
            for substring_zmq in self.zmq_subscribed_to[remote_uuid]: # loop over all subscribe strings
                subaddr_zmq = data_packets.redvypr_address(substring_zmq)
                FLAG_REMOVE = True
                for subaddr, subdev in zip(all_subscriptions[0], all_subscriptions[1]):
                    # Omit own host
                    #print('subdev',subdev)
                    if (subdev == self.address_str):
                        #print('Its me doing nothing unsub ... ')
                        continue
                    else:
                        if subaddr in subaddr_zmq:
                            FLAG_REMOVE = False
                            break

                if FLAG_REMOVE:
                    unsubscribe_addresses.append([remote_uuid,substring_zmq])

        return unsubscribe_addresses

    def test_zmq_subscribe(self):
        """
        Tests if new zmq subscriptions have to be made.

        Returns:
            list with addresses that would need to be subscribed
            each list entry consists of another list with [remote_uuid,address_string]
        """
        all_subscriptions = self.redvypr.get_all_subscriptions()
        subscribe_addresses = []
        for subaddr, subdev in zip(all_subscriptions[0], all_subscriptions[1]):
            if(subdev == self.address_str): # Do nothing if its me
                continue
            else:
                [FLAG_FIT, remote_uuid, address_string, FLAG_SUBSCRIBED] = self.compare_zmq_subscription(subaddr)
            if (FLAG_FIT):  # Match of subscription with remote device
                if FLAG_SUBSCRIBED == False:
                    subscribe_addresses.append([remote_uuid,address_string])

        return subscribe_addresses

    def subscription_changed_global(self, devchange):
        """
        Function is called by redvypr after another device emitted the subscription_changed_signal

        Args:
            devchange: redvypr_device that emitted the subscription changed signal

        Returns:
            None
        """
        self.logger.info('Global subscription changed {:s} {:s}'.format(self.name,devchange.name))
        unsubscribe_addresses = self.test_zmq_unsubscribe()
        print('Unsubscribe addresses', unsubscribe_addresses)
        for unsub_addr in unsubscribe_addresses:
            remote_uuid = unsub_addr[0]
            address_string = unsub_addr[1]
            if self.autosubscribe:
                self.zmq_unsubscribe(remote_uuid, address_string)

        # Test for new subscriptions
        subscribe_addresses = self.test_zmq_subscribe()
        print('Subscribe addresses', subscribe_addresses)
        for sub_addr in subscribe_addresses:
            remote_uuid    = sub_addr[0]
            address_string = sub_addr[1]
            if self.autosubscribe:
                self.zmq_subscribe(remote_uuid, address_string)

    def subscribe_all_remote(self):
        """
        Subscribes to all remote iored:redvypr devices
        Returns:

        """
        self.autosubscribe = False
        all_remote_devices = self.statistics['device_redvypr'].keys()
        for address_string in all_remote_devices:
            daddr = data_packets.redvypr_address(address_string)
            if(daddr.uuid == self.host_uuid): # Only take remote uuids
                continue
            self.logger.info('Subscribing to {:s}'.format(daddr.uuid))
            self.zmq_subscribe(daddr.uuid,'')

    def unsubscribe_all_remote(self):
        """
        unsubscribes from all remote iored:redvypr devices
        Returns:

        """

        all_remote_devices = self.statistics['device_redvypr'].keys()
        for address_string in all_remote_devices:
            daddr = data_packets.redvypr_address(address_string)
            if(daddr.uuid == self.host_uuid): # Only take remote uuids
                continue
            self.logger.info('Unsubscribing from {:s}'.format(daddr.uuid))
            self.zmq_unsubscribe(daddr.uuid,'')

        self.autosubscribe = True

    def zmq_subscribe(self,uuid,substring):
        """
        Subscribe command to a remote iored device with address.
        Args:
            address: address string that needs to have the form '<device>:<host>@<addr>::<uuid>'
            remote_uuid = data['remote_uuid']
            substring = data['substring']
            zmq_url = hostinfos[remote_uuid]['zmq_pub']

        Returns:

        """
        funcname = __name__ + 'zmq_subscribe()'
        self.logger.debug(funcname)
        if True:
            self.thread_command('subscribe', {'remote_uuid': uuid, 'substring': substring})
            try:
                self.zmq_subscribed_to[uuid].append(substring)
            except:
                self.zmq_subscribed_to[uuid] = [substring]

    def zmq_unsubscribe(self, uuid, substring):
        """
        Unsubscribe address from a remote iored device.

        Args:
            address:

        Returns:

        """
        funcname = __name__ + 'zmq_unsubscribe()'
        self.logger.debug(funcname)
        if True:
            #self.zmq_subscribed_addresses.remove(address)
            #self.thread_command('unsubscribe', {'device': address})
            self.thread_command('unsubscribe', {'remote_uuid': uuid, 'substring': substring})
            try:
                self.zmq_subscribed_to[uuid].remove(substring)
            except Exception as e:
                self.logger.exception(e)


    def __update_datastreams__(self):
        """
        Whenever the datastreamlist of the redvypr hosts changes, iored sends an update with a multicast message,
        this function is called by a redvypr signal and sends a update datastream command to the iored thread.

        Returns:

        """
        funcname = __name__ + '.__update_datastreams__():'
        # check if the thread is running
        try:
            running = self.thread.is_alive()
        except:
            running = False

        print('loglevel', self.logger.level)
        if(running):
            datastreams_dict = {'datastreams_dict':copy.copy(self.redvypr.datastreams_dict)}
            print('Sending command')
            self.thread_command('datastreams', datastreams_dict)
        else:
            print('not running')
            self.logger.info(funcname + ' Thread is not running, doing nothing')
            self.logger.debug(funcname + ' Thread is not running, doing nothing')

    def get_devices_by_host(self):
        """
        Sorts the forwarded devicelist by remote host and returns a dictionary
        Returns:
           Dictionary with the hostnames as keys with a device_redvypr entry
        """
        devicedict = {}
        for d in self.statistics['device_redvypr'].keys():
            hostuuid = self.statistics['device_redvypr'][d]['_redvypr']['host']['uuid']
            hostname = self.statistics['device_redvypr'][d]['_redvypr']['host']['hostname']
            hostnameuuid = hostname + '::' + hostuuid
            try:
                devicedict[hostnameuuid]
            except:
                devicedict[hostnameuuid] = []

            devicedict[hostnameuuid].append(self.statistics['device_redvypr'][d])

        return devicedict



class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self, device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        self.device = device
        self.devicetree = QtWidgets.QTreeWidget()
        self.devicetree.currentItemChanged.connect(self.__item_changed__)
        self.reqbtn = QtWidgets.QPushButton('Get info')
        self.reqbtn.clicked.connect(self.__getinfo_command__)
        self.sendbtn = QtWidgets.QPushButton('Send Info')
        self.sendbtn.clicked.connect(self.__sendinfo_command__)
        #self.sendbtn.clicked.connect(self.__update_devicelist__)
        self.subbtn = QtWidgets.QPushButton('Subscribe')
        self.subbtn.clicked.connect(self.__subscribe_clicked__)
        self.subbtn.setEnabled(False)
        layout.addWidget(self.devicetree,0,0,1,2)
        layout.addWidget(self.subbtn, 1, 0,1,2)
        layout.addWidget(self.reqbtn,2,0)
        layout.addWidget(self.sendbtn, 2, 1)
        self.__update_devicelist__()

        #self.device.redvypr.datastreams_changed_signal.connect(self.__update_devicelist__)
        self.device.redvypr.device_status_changed_signal.connect(self.__update_devicelist__)

    def __item_changed__(self,new,old):
        if(new is not None):
            print('Item changed',new,old)
            try:
                print('Item changed', new.subscribeable, new.subscribed)
            except:
                print('Problem')
            try:
                subscribed = new.subscribed
            except:
                subscribed = False

            if(new.subscribeable == False):
                self.subbtn.setEnabled(False)
            else:
                self.subbtn.setEnabled(True)
                if(subscribed):
                    self.subbtn.setText('Unsubscribe')
                else:
                    self.subbtn.setText('Subscribe')


    def __subscribe_clicked__(self):
        funcname = __name__ + '__subscribe_clicked__():'
        logger.debug(funcname)
        getSelected = self.devicetree.selectedItems()
        if getSelected:
            baseNode = getSelected[0]
            if(baseNode.parent() == None):
                pass
            else:
                #devstr = baseNode.text(0)
                devstr = data_packets.get_deviceaddress_from_redvypr_meta(baseNode._redvypr,uuid=True)
                if(self.subbtn.text() == 'Subscribe'):
                    print('Subscribing to',devstr)
                    self.device.zmq_subscribe(devstr)
                else:
                    print('Unsubscribing from',devstr)
                    self.device.zmq_unsubscribe(devstr)


                #time.sleep(1)
                #self.__update_devicelist__()

    def __getinfo_command__(self):
        funcname = __name__ + '__getinfo_command__():'
        logger.debug(funcname)
        self.device.thread_command('multicast_getinfo',{})

    def __sendinfo_command__(self):
        funcname = __name__ + '__sendinfo_command__():'
        logger.debug(funcname)
        #print('Status update')
        #datapacket = data_packets.commandpacket(command='status', device_uuid='', thread_uuid='', devicename=None, host=None)
        #datapacket['_redvypr']['status'] = {'subscribed': True, 'zmq_subscriptions':'Hallo'}
        #self.device.dataqueue.put(datapacket)
        #print('End status update')
        self.device.thread_command('multicast_info', {})

    def __iored_device_changed__(self):
        print('IORED devices changed')

    def __update_devicelist__(self):
        """
        Updates the qtreewidget with the devices found in self.device.redvypr
        Returns:

        """

        funcname = __name__ + '__update_devicelist__():'
        print('display widget update devicelist')
        self.devicetree.clear()
        self.devicetree.setColumnCount(2)
        root = self.devicetree.invisibleRootItem()
        #devices = self.device.statistics['device_redvypr']
        devices = self.device.get_devices_by_host()
        #print('devices',devices)
        for hostnameuuid in devices.keys():
            hostuuid = hostnameuuid.split('::')[1]
            if(hostuuid == self.device.redvypr.hostinfo['uuid']): # Dont show own packets
                #print('Own device')
                continue
            itm = QtWidgets.QTreeWidgetItem([hostnameuuid,''])
            itm.subscribeable = False
            itm.subscribed = False
            root.addChild(itm)
            for d in devices[hostnameuuid]:
                #print('Device d',d)
                substr = 'not connected'
                try:
                    FLAG_SUBSCRIBED = d['_redvypr']['subscribed']
                    if FLAG_SUBSCRIBED:
                        substr = 'subscribed'
                except Exception as e:
                    #print('Subscribed?',e)
                    FLAG_SUBSCRIBED = False

                devname = d['_redvypr']['device']
                itmdevice = QtWidgets.QTreeWidgetItem([devname,substr])
                itmdevice.subscribed = FLAG_SUBSCRIBED
                itmdevice.hostnameuuid = hostnameuuid
                itmdevice._redvypr = d['_redvypr']
                try:
                    itmdevice.subscribeable = d['_redvypr']['subscribeable']
                except:
                    itmdevice.subscribeable = False
                itm.addChild(itmdevice)

        self.devicetree.expandAll()
        self.devicetree.resizeColumnToContents(0)

    def update(self, data):
        """

        Args:
            data:

        Returns:

        """
        # If this is a local package
        if(data['host']['uuid'] == self.device.redvypr.hostinfo['uuid']):
            self.__update_devicelist__()
        print('Update',data)
        pass




