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


The device infodata is a dictionary of this structure and is created by create_info_packet()::

  info_data = {'host': {'hostname': 'redvypr', 'tstart': 1677037052.8936212, 'addr': '192.168.178.26', 'uuid': '93328248922693-056', 'local': True}, 't': 1677037146.6887786, 'zmq_pub': 'tcp://192.168.178.26:18197', 'zmq_rep': 'tcp://192.168.178.26:18196', 'deviceinfo_all': {'iored_0': {'iored_0:redvypr@192.168.178.26::93328248922693-056': {'_redvypr': {'tag': {'93328248922693-056': 1}, 'device': 'iored_0', 'host': {'hostname': 'redvypr', 'tstart': 1677037052.8936212, 'addr': '192.168.178.26', 'uuid': '93328248922693-056', 'local': True}, 't': 1677037053.0344708, 'devicemodulename': 'iored', 'numpacket': 2}, 'datakeys': [], '_deviceinfo': {'subscribe': True, 'publish': True, 'devicemodulename': 'iored'}, '_keyinfo': {}}}, 'test_device_1': {'test_device_1:redvypr@192.168.178.26::93328248922693-056': {'_redvypr': {'tag': {'93328248922693-056': 1}, 'device': 'test_device_1', 'host': {'hostname': 'redvypr', 'tstart': 1677037052.8936212, 'addr': '192.168.178.26', 'uuid': '93328248922693-056', 'local': True}, 't': 1677037145.0688086, 'devicemodulename': 'test_device', 'numpacket': 144}, 'datakeys': ['data', 'count', 't'], '_deviceinfo': {'subscribe': False, 'publish': True, 'devicemodulename': 'test_device'}, '_keyinfo': {'data': {'unit': 'string', 'description': 'Some sentence sent'}, 'count': {'datatype': 'int', 'unit': 'count', 'description': 'Simple packetcount'}}}, 't2:redvypr@192.168.178.26::93328248922693-056': {'_redvypr': {'device': 't2', 'tag': {'93328248922693-056': 1}, 'host': {'hostname': 'redvypr', 'tstart': 1677037052.8936212, 'addr': '192.168.178.26', 'uuid': '93328248922693-056', 'local': True}, 't': 1677037145.0688086, 'devicemodulename': 'test_device', 'numpacket': 144}, 'datakeys': ['t', 'count'], '_deviceinfo': {}, '_keyinfo': {}}}}, 'hostinfo_opt': {'template_name': 'hostinfo_opt'}}


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
import uuid as uuid_module
import hashlib

import redvypr
from redvypr.device import redvypr_device
from redvypr.data_packets import check_for_command
import redvypr.data_packets as data_packets
import redvypr.files


description = 'Internet of Redvypr, device allows to easily connect to other redvypr devices '

config_template = {}
config_template['template_name']      = 'iored'
config_template['redvypr_device']     = {}
config_template['zmq_pub_port_start'] = 18196
config_template['zmq_pub_port_end']   = 20000
config_template['multicast_listen']   = {'type':'bool','default':True,'description':'Listening for multicast information'}
config_template['multicast_send']     = {'type':'bool','default':True,'description':'Sending information via multicast (using multicast_address and multicast_port)'}
config_template['multicast_address']  = "239.255.255.239"
config_template['multicast_dtbeacon'] = {'type':'int','default':-1,'description':'Time [s] a multicastinformation is sent, disable with negative number'}
config_template['multicast_port']     = 18196
config_template['redvypr_device']['max_devices']  = 1
config_template['redvypr_device']['publishes']  = True
config_template['redvypr_device']['subscribes'] = True
config_template['redvypr_device']['description'] = description

# Headers for network packets
info_header = {}
info_header['info']    = b'redvypr info'
info_header['infoshort'] = b'redvypr shortinfo'
info_header['getinfo'] = b'redvypr getinfo'
info_header['stop']    = b'redvypr stop'

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('iored')
logger.setLevel(logging.DEBUG)

_logo_file = redvypr.files.logo_file
_icon_file = redvypr.files.icon_file

def create_info_packet(device_info,url_pub,url_rep):
    """
    Creates a binary information packet that is used to by iored to send the information about the redvypr instance.
    Args:
        device_info:
        url_pub:
        url_rep:

    Returns:
         binary string containing the information
    """
    # Remove subdevices of the iored device, they are not interesting for the remote iored device
    deviceinfo_all = copy.deepcopy(device_info['deviceinfo_all'])
    uuid = device_info['hostinfo']['uuid']
    #https://stackoverflow.com/questions/5384914/how-do-i-delete-items-from-a-dictionary-while-iterating-over-it
    for subdevice in list(deviceinfo_all[device_info['devicename']].keys()):
        subdevaddr = data_packets.redvypr_address(subdevice)
        if subdevaddr.uuid != uuid: # Remove all remote devices from this iored device
            deviceinfo_all[device_info['devicename']].pop(subdevice)


    devtmp = yaml.dump(deviceinfo_all).encode('utf-8')
    hosttmp = yaml.dump(device_info['hostinfo_opt']).encode('utf-8')

    info_packet = {'host': device_info['hostinfo'], 't': time.time(), 'zmq_pub': url_pub, 'zmq_rep': url_rep,'tinfo':device_info['tinfo'],
                   'deviceinfo_all': deviceinfo_all, 'hostinfo_opt': device_info['hostinfo_opt'],'devicename':device_info['devicename']}

    #print('Device info',device_info)
    # print('--------------')
    print('Info packet', info_packet)
    # print('--------------')
    hostinfoy = yaml.dump(info_packet, explicit_end=True, explicit_start=True)
    hostinfoy = hostinfoy.encode('utf-8')
    datab = info_header['info'] + hostinfoy

    return datab

def create_info_packet_short(device_info,url_pub,url_rep):
    """
    Creates a binary information packet that is used by iored to send the information about the redvypr instance.
    Args:
        device_info:
        url_pub:
        url_rep:

    Returns:
         binary string containing the information
    """
    devtmp = yaml.dump(device_info['deviceinfo_all']).encode('utf-8')
    hosttmp = yaml.dump(device_info['hostinfo_opt']).encode('utf-8')
    info_packet = {'host': device_info['hostinfo'], 't': time.time(), 'zmq_pub': url_pub, 'zmq_rep': url_rep,
                   'tinfo':device_info['tinfo'],'devicename':device_info['devicename']}

    #print('Device info',device_info)
    ## print('--------------')
    #print('Multicast packet', info_packet)
    ## print('--------------')
    hostinfoy = yaml.dump(info_packet, explicit_end=True, explicit_start=True)
    hostinfoy = hostinfoy.encode('utf-8')
    datab = info_header['infoshort'] + hostinfoy

    return datab


def create_stop_packet(device_info,url_pub,url_rep):
    """
    Creates a binary information packet to inform that the device is stopped
    Args:
        device_info:
        url_pub:
        url_rep:

    Returns:
         binary string containing the information
    """
    info_packet = {'host': device_info['hostinfo'], 't': time.time(), 'zmq_pub': url_pub, 'zmq_rep': url_rep,
                   'devicename':device_info['devicename']}

    #print('Multicast packet', info_packet)
    # print('--------------')
    hostinfoy = yaml.dump(info_packet, explicit_end=True, explicit_start=True)
    hostinfoy = hostinfoy.encode('utf-8')
    datab = info_header['stop'] + hostinfoy

    return datab


def filter_deviceinfo(data):
    """
    Filters the deviceinfo_all data structure and removes devices that are not publishing
    Returns:
       data_filt dictionary with the devices filtered (at the moment if they publish)
    """
    data_filt = {}
    for dev in data.keys():
        for devfull in data[dev].keys():
            try:
                FLAG_PUBLISH = data[dev][devfull]['_deviceinfo']['publishes']
            except:
                FLAG_PUBLISH = False

            if(FLAG_PUBLISH):
                data_filt[dev] = data[dev]
                break

    return data_filt


def analyse_info_packet(datab):
    """
    Processes information packet from a redvypr instance.

    Args:
        datab: Binary data

    Returns:

    """
    funcname = __name__ + '.analyse_info_packet()'
    #print('Received multicast data', datab)
    redvypr_info = None
    trecv = time.time()
    if datab.startswith(info_header['info']): # info packet
        headerlen = len(info_header['info'])
        try:
            data = datab.decode('utf-8')
            redvypr_info = yaml.safe_load(data[headerlen:])
            redvypr_info['trecv'] = trecv
            return ['info',redvypr_info]
        except Exception as e:
            redvypr_info = ['info',None]

    elif datab.startswith(info_header['infoshort']): # info md5 packet
        headerlen = len(info_header['infoshort'])
        try:
            data = datab.decode('utf-8')
            redvypr_info = yaml.safe_load(data[headerlen:])
            redvypr_info['trecv'] = trecv
            return ['info',redvypr_info]
        except Exception as e:
            redvypr_info = ['info',None]

    elif datab.startswith(info_header['getinfo']):  # getinfo request
        try:
            headerlen = len(info_header['getinfo'])
            data = datab.decode('utf-8')
            redvypr_info = yaml.safe_load(data[headerlen:])
            redvypr_info['trecv'] = trecv
            return ['getinfo', redvypr_info]
        except Exception as e:
            redvypr_info = ['info', None]

    elif datab.startswith(info_header['stop']):  # Stop information
        try:
            headerlen = len(info_header['stop'])
            data = datab.decode('utf-8')
            redvypr_info = yaml.safe_load(data[headerlen:])
            redvypr_info['trecv'] = trecv
            return ['stop', redvypr_info]
        except Exception as e:
            redvypr_info = ['info', None]

    return [None,None]

def create_datapacket_from_deviceinfo(device_info,tlastseen=None):
    """

    Args:
        redvypr_info:

    Returns:
        Either a list of datapackets (datastream == None) or a single datapacket if a datastream equal to the argument "datastream" was found.

    """
    funcname = __name__ + '.create_datapacket_from_deviceinfo()'


    d = device_info
    dpacket = {}
    dpacket['_redvypr'] = d['_redvypr']
    if (tlastseen is not None):
        dpacket['_redvypr']['tlastseen'] = tlastseen

    #dpacket['_redvypr']['connected'] = None  # Used for zmq subscription
    if 'iored' in d['_redvypr']['devicemodulename']:
        subscribeable = False
        #dpacket['_redvypr']['connected'] = False
    else:
        subscribeable = True # Flag if the device can be subscribed via zmq, the iored device itself cannot
    #print('device info',d)
    if True:
        dpacket['_redvypr']['subscribeable'] = subscribeable # Extra boolean used for zmq subscription
        dpacket['_deviceinfo'] = d['_deviceinfo']
        dpacket['_keyinfo']  = d['_keyinfo']

        # Add datakeys with bogus data
        for k in d['datakeys']:
            dpacket[k] = None

        return dpacket


def connect_remote_host(remote_uuid,zmq_url_pub,zmq_url_rep,dataqueue,statusqueue,hostuuid,hostinfos,zmq_context):
    """
    Connects to a remote iored by starting a thread
    Args:
        remote_uuid:

    Returns:

    """
    remote_dict = {}
    config_zmq = {}
    config_zmq['zmq_pub'] = zmq_url_pub
    config_zmq['zmq_rep'] = zmq_url_rep
    comqueue = queue.Queue(maxsize=1000)
    statqueue = queue.Queue(maxsize=1000)
    remote_dict['comqueue'] = comqueue
    remote_dict['statqueue'] = statqueue
    remote_dict['thread'] = threading.Thread(target=start_zmq_sub, args=(dataqueue, comqueue, statqueue, config_zmq, remote_uuid,statusqueue,hostuuid,hostinfos,zmq_context),daemon=True)
    remote_dict['thread'].start()
    if(remote_dict['thread'].is_alive()):
        return remote_dict
    else:
        return None

def start_zmq_sub(dataqueue, comqueue, statusqueue_zmq, config, remote_uuid, statusqueue, hostuuid, hostinfos,zmq_context):
    """ zeromq thread for receiving data from a remote redvypr/iored host with a zmq.PUB socket. Thread is started
    by the main start thread.
    """
    funcname = __name__ + '.start_recv(): '
    raddr_iored_remote = data_packets.redvypr_address(local_hostinfo=hostinfos[remote_uuid]['host'],devicename=hostinfos[remote_uuid]['devicename'])
    addrstr_iored_remote = raddr_iored_remote.get_str('<device>:<host>@<addr>::<uuid>')
    datastreams_dict = {}
    status = {'sub':[],'uuid':remote_uuid,'type':'status'}
    zmq_url_pub = config['zmq_pub']
    zmq_url_rep = config['zmq_rep']
    status['zmq_pub'] = config['zmq_pub']
    status['zmq_rep'] = config['zmq_rep']
    timeout_ms = 1000
    #
    socket_req = zmq_context.socket(zmq.REQ)
    socket_req.setsockopt(zmq.RCVTIMEO, timeout_ms)  # milliseconds
    try:
        socket_req.connect(zmq_url_rep)
        print(funcname + 'Connected (zmq.REQ) to url {:s}'.format(zmq_url_rep))
    except Exception as e:
        print('Could not connect (zmq.REQ) to url {:s}'.format(zmq_url_rep))
        return None

    socket_req.send(info_header['getinfo'])
    try:
        recv = socket_req.recv()
        [packet_type, redvypr_info] = analyse_info_packet(recv) # Return data is [command, redvypr_info]
    except Exception as e:
        redvypr_info = None
        packet_type = None

    #print('Got data of type ', packet_type)
    #print('With information', redvypr_info)
    if (redvypr_info is not None):  # Processing the information and sending it to redvypr
        process_host_information(redvypr_info, hostuuid, hostinfos, statusqueue, dataqueue)
    else:
        status['status'] = 'notconnected'
        try:
            statusqueue_zmq.put_nowait(copy.deepcopy(status))
        except Exception as e:
            logger.exception(e)
        return

    #
    sub = zmq_context.socket(zmq.SUB)
    logger.debug(funcname + ':Start receiving data (zmq.SUB) from url {:s}'.format(zmq_url_pub))
    sub.setsockopt(zmq.RCVTIMEO, 200)
    sub.connect(zmq_url_pub)
    datapackets = 0
    bytes_read  = 0
    npackets    = 0 # Number packets received
    # Subscribe to the uuid, this is used for sending status updates, commands and messages from the redvypr host
    remote_uuidb = remote_uuid.encode('utf-8')
    print('Subscribing to',remote_uuidb)
    sub.setsockopt(zmq.SUBSCRIBE, remote_uuidb)
    #sub.setsockopt(zmq.SUBSCRIBE, b'') # Subscribe to all
    status['sub'].append(remote_uuid)
    status['status'] = 'connected'
    try:
        statusqueue_zmq.put_nowait(copy.deepcopy(status))
    except Exception as e:
        logger.exception(e)

    # Status of iored packet
    print('Sending status of redvypr iored connection')
    comdata = {}
    comdata['deviceaddr'] = addrstr_iored_remote
    comdata['devicestatus'] = { 'connected': True }  # This is the status of the iored device
    datapacket = data_packets.commandpacket(command='device_status', device_uuid='', thread_uuid='', devicename=None,
                                            host=None, comdata=comdata)
    try:
        statusqueue.put_nowait(datapacket)
    except Exception as e:
        logger.exception(e)


    while True:
        try:
            com = comqueue.get(block=False)
        except:
            com = None

        # Check if a command was sent from main thread
        if com is not None:
            if(com == 'stop'):
                logger.info(funcname + ' stopping zmq sockets {:s}, {:s}'.format(zmq_url_rep,zmq_url_pub))
                sub.close()
                socket_req.close()
                break

            elif com.startswith('sub'):
                substring = com.rsplit(' ')[1]
                logger.info(funcname + ' subscribing to {:s}'.format(substring))
                substringb = substring.encode('utf-8')
                sub.setsockopt(zmq.SUBSCRIBE, substringb)
                status['sub'].append(substring)
                try:
                    statusqueue_zmq.put_nowait(copy.deepcopy(status))
                except Exception as e:
                    logger.exception(e)
                comdata = {}
                comdata['deviceaddr']   = substring
                comdata['devicestatus'] = {'subscribed': True} # This is the status of the iored device, 'zmq_subscriptions': status['sub']}
                datapacket = data_packets.commandpacket(command='device_status', device_uuid='', thread_uuid='', devicename=None, host=None,comdata=comdata)
                #dataqueue.put(datapacket)
                statusqueue.put_nowait(datapacket)
                # datastreams_dict is dictionary from the device, changed in a thread, use only atomic operations
                try:
                    datastreams_dict[substring]
                except:
                    datastreams_dict[substring] = {}

                try:
                    datastreams_dict[substring]['status']
                except:
                    datastreams_dict[substring]['status'] = {}

                datastreams_dict[substring]['status']['zmq_url_pub'] = zmq_url_pub
                datastreams_dict[substring]['status']['zmq_url_rep'] = zmq_url_rep
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
                    datastreams_dict[unsubstring]['status']['zmq_url_pub'] = zmq_url_pub
                    datastreams_dict[unsubstring]['status']['zmq_url_rep'] = zmq_url_rep
                    datastreams_dict[unsubstring]['status']['subscribeable'] = True
                    datastreams_dict[unsubstring]['status']['subscribed'] = False
                except:
                    pass

                statusqueue_zmq.put(copy.deepcopy(status))
                comdata = {}
                comdata['deviceaddr'] = unsubstring
                comdata['devicestatus'] = { 'subscribed': False}
                datapacket = data_packets.commandpacket(command='device_status', device_uuid='', thread_uuid='',
                                                        devicename=None, host=None, comdata=comdata)
                # Send a device status packet to notify a device change
                statusqueue.put(datapacket)
                #dataqueue.put(datapacket)

        # Command finished, lets receive some data
        try:
            #datab = sub.recv(zmq.NOBLOCK)
            datab_all = sub.recv_multipart()
            #print('Got data',datab_all)
            FLAG_DATA = True
        except Exception as e:
            #logger.debug(funcname + ':' + str(e))
            FLAG_DATA = False

        if FLAG_DATA:
            device = datab_all[0]  # The device address
            t = datab_all[1] # The time the packet was sent
            datab = datab_all[2] # The message
            bytes_read += len(datab)
            # Check what data we are expecting and convert it accordingly
            if True:
                for databs in datab.split(b'...\n'): # Split the text into single subpackets
                    try:
                        data = yaml.safe_load(databs)
                        #print(datab)
                        #print('sub-------')
                        #print(data)
                        #print('sub-------')
                    except Exception as e:
                        logger.debug(funcname + ': Could not decode message {:s}'.format(str(datab)))
                        data = None

                    if((data is not None) and (type(data) == dict)):
                        # Check for command
                        command = check_for_command(data)
                        # logger.debug('Got a command: {:s}'.format(str(data)))
                        if command is not None:
                            print('Got a command from remote device, hande it in the device')
                            # TODO, this can be more fine grained if we want to allow commands to be received from remote
                            # redvypr to this redvy instance
                            statusqueue.put(data)
                        else:
                            dataqueue.put(data)
                            datapackets += 1

    print('Thread stopped, sending status of redvypr iored connection')
    comdata = {}
    comdata['deviceaddr'] = addrstr_iored_remote
    comdata['devicestatus'] = {'connected': False}  # This is the status of the iored device
    datapacket = data_packets.commandpacket(command='device_status', device_uuid='', thread_uuid='',
                                            devicename=None,
                                            host=None, comdata=comdata)
    statusqueue.put(datapacket)
    #dataqueue.put(datapacket)


def start_zmq_reply(config, device_info,url_pub,zmq_ports,thread_uuid,replyqueue,statusqueue,zmq_context):
    """ zeromq thread to reply for remote requests for information
    """
    timeout_ms = 1000
    funcname = __name__ + '.start_zmq_reply():'
    logzmqrep = logging.getLogger('iored_zmq_reply')
    logzmqrep.setLevel(logging.DEBUG)
    sock_zmq_rep = zmq_context.socket(zmq.REP)
    #sock_zmq_rep.setsockopt(zmq.RCVTIMEO, timeout_ms)  # milliseconds
    FLAG_BIND = False
    if True:
        for zmq_port in zmq_ports:
            print(zmq_port)
            url_rep = 'tcp://' + device_info['hostinfo']['addr'] + ':' + str(int(zmq_port))
            logzmqrep.info('Trying to connect zmq rep to {:s}'.format(url_rep))
            try:
                sock_zmq_rep.bind(url_rep)
                #print('Good', url_rep)
                FLAG_BIND = True
                break
            except Exception as e:
                continue

    if FLAG_BIND:
        replyqueue.put(url_rep)
    else:
        replyqueue.put(None)

    logzmqrep.info(':Start listening at url {:s}'.format(url_rep))
    # Before starting the loop send an status information about the info that will be sent over the network
    datab = create_info_packet(device_info, url_pub, url_rep)
    [packet_type, redvypr_info] = analyse_info_packet(datab)  # Return data is [command, redvypr_info]
    statusqueue.put({'type': 'own_info_packet', 'redvypr_info': redvypr_info, 'packet_type': packet_type})

    #
    # Start trying to get a zmq request
    #
    print('Starting loop')
    while True:
        data_zmq_req = sock_zmq_rep.recv()
        print('Got a request, answering', data_zmq_req)
        if data_zmq_req.startswith(info_header['getinfo']):  # getinfo request
            print(funcname + ' Getinfo request')
            datab = create_info_packet(device_info, url_pub, url_rep)
            print(funcname + ' Sending info packet')
            print('data', datab)
            print(funcname + ' Done sending info packet')
            sock_zmq_rep.send(datab)
            # Sending the updated host information also to the statusqueue
            [packet_type, redvypr_info] = analyse_info_packet(datab)  # Return data is [command, redvypr_info]
            statusqueue.put({'type':'own_info_packet','redvypr_info':redvypr_info,'packet_type':packet_type})
        elif data_zmq_req == 'ping'.encode('utf-8'):
            sock_zmq_rep.send('pong'.encode('utf-8'))
        elif data_zmq_req.startswith(thread_uuid.encode('utf-8')):  # if the uuid is sent (this is only known by this instance), stop the thread
            logzmqrep.info('Got the thread_uuid, stopping thread')
            sock_zmq_rep.send(b'stopping')
            sock_zmq_rep.close()
            return
        else:  # Mirror it back
            sock_zmq_rep.send(data_zmq_req)
    #
    # End trying to get a zmq request
    #


def do_multicast(config,sock_multicast_recv,sock_multicast_send,MULTICASTADDRESS, MULTICASTPORT,device_info,logstart,statusqueue,hostuuid,hostinfos,dataqueue,url,url_rep,MULTICASTFLAGS,zmq_context):
    #
    # Start Trying to receive data from multicast
    #
    if config['multicast_listen']:
        try:
            data_multicast_recv = sock_multicast_recv.recv(10240)  # This could be a potential problem as this is finite
        except Exception as e:
            if isinstance(e, BlockingIOError):
                data_multicast_recv = None
            else:
                print('-----Exception start-------')
                data_multicast_recv = None
                logger.exception(e)
                print('------Exception end------')

        if (data_multicast_recv is not None):
            print('Got multicast data',len(data_multicast_recv))
            if len(data_multicast_recv) == 0:
                logger.critical('Multicast socket error')
                print('received 0 bytes')
            # print('Got multicast data',data_multicast_recv)
            trecv = time.time()
            #print('Got multicast data',data_multicast_recv)
            [multicast_command, redvypr_info] = analyse_info_packet(data_multicast_recv)

            #print('Command',multicast_command,redvypr_info)
            #print('from uuid', redvypr_info['host']['uuid'])
            # Information request sent by another iored device
            if multicast_command == 'getinfo':
                print('Multicast getinfo command')
                try:
                    print('Getinfo request from {:s}::{:s}'.format(redvypr_info['host']['hostname'],
                                                                   redvypr_info['host']['uuid']))
                except Exception as e:
                    logstart.exception(e)

                if redvypr_info['host']['uuid'] == device_info['hostinfo']['uuid']:
                    print('request from myself, doing nothing')
                    pass
                else:
                    MULTICASTFLAGS['FLAG_MULTICAST_INFO'] = True
                    statusqueue.put_nowait({'type': 'getinfo', 'info': redvypr_info})
            elif multicast_command == 'stop':
                print('Multicast stop command')
                try:
                    print('Stop information from {:s}::{:s}'.format(redvypr_info['host']['hostname'],
                                                                   redvypr_info['host']['uuid']))
                except Exception as e:
                    logstart.exception(e)

                if redvypr_info['host']['uuid'] == device_info['hostinfo']['uuid']:
                    print('stop request from myself, doing nothing')
                    pass
                else:
                    statusqueue.put_nowait({'type': 'stop', 'info': redvypr_info})
            # Information packet sent by another iored device
            elif multicast_command == 'info':
                print('Multicast infopacket')
                try:
                    uuid = redvypr_info['host']['uuid']
                except:
                    uuid = None



                if uuid == hostuuid:
                    print('from me', uuid)
                    #print('Own multicast packet')
                    pass
                else:
                    print('from', uuid)
                    print('Info from {:s}::{:s} at address {:s}'.format(redvypr_info['host']['hostname'], redvypr_info['host']['uuid'], redvypr_info['zmq_rep']))
                    # Check if things have changed or if the uuid is existing at all
                    FLAG_QUERY = True
                    # Dont bother about these cases
                    if(redvypr_info['host']['uuid'] not in hostinfos.keys()):
                        #print('Host is not registered yet in hostinfos, querying')
                        FLAG_QUERY = True
                    else:
                        print('Host known')
                        if hostinfos[uuid]['tinfo'] == redvypr_info['tinfo']:
                            print('same creation time of info package, doing nothing')
                            FLAG_QUERY = False


                    if FLAG_QUERY:
                        try:
                            [packet_type, redvypr_info] = query_host(redvypr_info['zmq_rep'],zmq_context)
                        except Exception as e:
                            logger.exception(e)
                        #print('Got data of type ', packet_type)
                        #print('With information', redvypr_info)
                        if (redvypr_info is not None):  # Processing the information and sending it to redvypr
                            process_host_information(redvypr_info, hostuuid, hostinfos, statusqueue, dataqueue)

                        #print('End query')

                    #
                    # print('redvypr_info',redvypr_info)
                    #statusqueue.put_nowait({'type': 'info', 'info': redvypr_info})

            # print('Received multicast data!!', data_multicast_recv)

        #
        # END Trying to receive data from multicast
        #

    if config['multicast_send']:
        #
        # START Sending multicast data
        #
        if (config['multicast_dtbeacon'] > 0) or MULTICASTFLAGS['FLAG_MULTICAST_INFO']:
            if ((time.time() - MULTICASTFLAGS['tbeacon']) > config['multicast_dtbeacon']) or MULTICASTFLAGS['FLAG_MULTICAST_INFO']:
                MULTICASTFLAGS['FLAG_MULTICAST_INFO'] = False
                MULTICASTFLAGS['tbeacon'] = time.time()

                # print('datastreams',datastreams)
                # print('Deviceinfo all')
                # print('deviceinfo all', device_info['deviceinfo_all'])
                # print('----- Deviceinfo all done -----')
                # Create an information packet
                datab = create_info_packet_short(device_info, url, url_rep)
                print('Sending multicast info with length {:d}'.format(len(datab)), time.time())
                sock_multicast_send.sendto(datab, (MULTICASTADDRESS, MULTICASTPORT))

                # print('Sending zmq data')
                # sock_zmq_pub.send_multipart([b'123',b'Hallo!'])
        #
        # Create a getinfo command and broadcast it over multicast
        #
        if MULTICASTFLAGS['FLAG_MULTICAST_GETINFO']:
            MULTICASTFLAGS['FLAG_MULTICAST_GETINFO'] = False
            multicast_packet = {'host': device_info['hostinfo'], 't': time.time()}
            hostinfoy = yaml.dump(multicast_packet, explicit_end=True, explicit_start=True)
            hostinfoy = hostinfoy.encode('utf-8')
            datab = info_header['getinfo'] + hostinfoy
            print('Sending getinfo request info with length {:d}'.format(len(datab)), time.time())
            sock_multicast_send.sendto(datab, (MULTICASTADDRESS, MULTICASTPORT))

        if MULTICASTFLAGS['FLAG_MULTICAST_DEVICESTOP']: # Device is stopped
            datab = create_stop_packet(device_info, url, url_rep)
            sock_multicast_send.sendto(datab, (MULTICASTADDRESS, MULTICASTPORT))

        #
        # END Sending multicast data
        #


def query_host_thread(urls,timeout_ms=200,queryqueue=None):
    """
    A thread wrapper for query-host to be run as thread

    Args:
        url:
        timeout_ms:
        queryqueue:

    Returns:

    """
    for url in urls:
        redvypr_info = query_host(url,timeout_ms)
        queryqueue.put(redvypr_info)

def query_host(url,zmq_context,timeout_ms=5000):
    """
    Queries a host with url using a zmq req getinfo command
    Args:
        url: str: address of the host, zmq rep url like tcp://localhost:18196

    Returns: None if no connection could be made or no valid redvypr answer was given, otherwise info dictionary

    """
    funcname = 'query_host():'
    print(funcname + ' {:s}'.format(url))
    socket_req = zmq_context.socket(zmq.REQ)
    socket_req.setsockopt(zmq.RCVTIMEO, timeout_ms)  # milliseconds
    try:
        socket_req.connect(url)
    except Exception as e:
        print('Could not connect to url {:s}'.format(url))
        return [None,None]

    socket_req.send(info_header['getinfo'])
    try:
        recv = socket_req.recv()
        redvypr_data = analyse_info_packet(recv) # Return data is [command, redvypr_info]
        socket_req.close()
    except Exception as e:
        socket_req.close()
        print('query host exception',e)
        redvypr_data = [None,None]

    return redvypr_data


def process_host_information(redvypr_info, hostuuid, hostinfos, statusqueue, dataqueue):
    """
    Save the hostinformation in hostinfo dictionary and creates/sends datapackages to the redvypr main task.
    Args:
        redvypr_info:

    Returns:

    """
    funcname = __name__ + '.process_host_information()'
    print(funcname)

    try:
        uuid = redvypr_info['host']['uuid']
    except:
        uuid = None

    if (uuid == hostuuid):
        print('Own multicast/info packet')
    else:
        print('Info from {:s}::{:s}'.format(redvypr_info['host']['hostname'], redvypr_info['host']['uuid']))
        # Could be locked
        hostinfos[uuid] = copy.deepcopy(
            redvypr_info)  # Copy it to the hostinfo of the device. This should be thread safe
        # Send it to the statusqueue, the data is processed in the device.
        print(funcname + ' redvypr_info')
        print(redvypr_info)
        print(funcname + ' redvypr_info done')
        statusqueue.put({'type': 'info', 'info': redvypr_info})


def zmq_publish_data(sock_zmq_pub,data,address_style='<device>:<host>@<addr>::<uuid>'):
    """
    Publishes data via sock_zmq_pub
    Args:
        sock_zmq_pub: zmq publish socket
        data: redvypr data packet
        address_style: The style of the address that is used for subscription

    Returns: datapacket: the multipart list that is sent via the zmq_socket

    """
    datab = yaml.dump(data, explicit_end=False, explicit_start=False).encode('utf-8')
    # print('Got data from queue',data)
    #
    #addrstr = data_packets.get_address_from_data('', data, style=address_style)
    raddr = data_packets.redvypr_address(datapacket=data)
    addrstr = raddr.get_str(address_style)
    # datasend = addrstr[1:].encode('utf-8') + ' '.encode('utf-8') + datab
    tsend = 't{:.6f}'.format(time.time()).encode('utf-8')
    #datapacket = [addrstr[1:].encode('utf-8'), tsend, datab]
    datapacket = [addrstr[:].encode('utf-8'), tsend, datab]
    sock_zmq_pub.send_multipart(datapacket)
    #print('Sent data')
    #print(datapacket)
    #print('Sent data done')
    return datapacket




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
    zmq_context = zmq.Context() # The context is created here and not globally to allow multicprocessing
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
    hostinfos = {} # All known hostinfos as sent by create_info_packet are saved here, with the uuid as the key
    zmq_sub_threads = {} # Dictionary with all remote redvypr hosts subscribed

    if (config['multicast_listen'] or config['multicast_send']):
        #
        # The multicast send socket
        #
        MULTICASTADDRESS = config['multicast_address'] # "239.255.255.250" # The same as SSDP
        MULTICASTPORT = config['multicast_port']

        # Flags for multicast feature
        MULTICASTFLAGS = {}
        MULTICASTFLAGS['FLAG_MULTICAST_INFO'] = True
        MULTICASTFLAGS['FLAG_MULTICAST_GETINFO'] = True
        MULTICASTFLAGS['FLAG_MULTICAST_DEVICESTOP'] = False
        MULTICASTFLAGS['tbeacon'] = 0
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
    # Start the zeromq distribution and request/reply sockets by testing if a port is free and if yes start a thread
    #
    FLAG_ZMQ_BIND = 0 # Flags if zmq could bind to two ports
    # The socket to broadcasts the data
    sock_zmq_pub = zmq_context.socket(zmq.XPUB)
    sock_zmq_pub.setsockopt(zmq.RCVTIMEO, 0)  # milliseconds
    zmq_ports = range(config['zmq_pub_port_start'], config_template['zmq_pub_port_end'])
    for zmq_port in zmq_ports:
        url_pub = 'tcp://' + device_info['hostinfo']['addr'] + ':' + str(int(zmq_port))
        logstart.info('Trying to connect zmq pub to {:s}'.format(url_pub))
        try:
            sock_zmq_pub.bind(url_pub)
            FLAG_ZMQ_BIND += 1
            break
        except Exception as e:
            continue
        logstart.info(funcname + ':Start publishing data at url {:s}'.format(url_pub))

    zmq_ports2 = range(zmq_port + 1, config_template['zmq_pub_port_end'])
    # Test if we could bind to the sockets, if not stop thread
    if(FLAG_ZMQ_BIND < 1):
        logstart.warning('Could not bind to ZMQ sockets, exiting')
        return
    else:
        # Start thread
        logstart.debug('Start reply thread')
        rep_thread_uuid = str(uuid_module.uuid1())  # Old
        replyqueue = queue.Queue()
        # Note that the reply thread is directly reading the device_info, that is updated in this thread.
        rep_thread = threading.Thread(target=start_zmq_reply, args=(config, device_info, url_pub,zmq_ports2, rep_thread_uuid, replyqueue, statusqueue, zmq_context),daemon=True)
        rep_thread.start()
        url_rep = replyqueue.get()
        # Create a local request for communication
        sock_zmq_rep_local = zmq_context.socket(zmq.REQ)
        try:
            sock_zmq_rep_local.connect(url_rep)
            sock_zmq_rep_local.send('ping'.encode('utf-8'))
            datab = sock_zmq_rep_local.recv()
            print('print received',datab)
        except:
            url_rep == None

        if(url_rep == None):
            logstart.warning('Could not bind to ZMQ sockets, exiting')
            sock_zmq_pub.close()
            for s in sockets:
                s.close()
            return

    # Create an onformation packet for to update the deviceinformation
    datapacket = data_packets.datapacket(data = {'url_zmq_rep':url_rep,'url_zmq_sub':url_pub}, datakey = '_deviceinfo')
    dataqueue.put(datapacket)

    #
    # Infinite loop
    #
    while True:
        tstart = time.time()
        if(config['multicast_listen'] or config['multicast_send']):
            do_multicast(config,sock_multicast_recv, sock_multicast_send, MULTICASTADDRESS, MULTICASTPORT, device_info, logstart,
                     statusqueue, hostuuid, hostinfos, dataqueue, url_pub, url_rep, MULTICASTFLAGS,zmq_context)
        else:
            pass

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
                        print(funcname + ' Stop command, shutting down all sockets and threads')
                        # Send a multicastpacket
                        if config['multicast_send']:
                            MULTICASTFLAGS['FLAG_MULTICAST_DEVICESTOP'] = True
                            do_multicast(config, sock_multicast_recv, sock_multicast_send, MULTICASTADDRESS,
                                         MULTICASTPORT, device_info, logstart,
                                         statusqueue, hostuuid, hostinfos, dataqueue, url_pub, url_rep, MULTICASTFLAGS,
                                         zmq_context)

                        print('publishing stop packet')
                        stoppacket = data_packets.commandpacket('stopped',host=device_info['hostinfo'],devicename=device_info['devicename'])
                        zmq_publish_data(sock_zmq_pub, stoppacket, address_style='<uuid>') # Sending only uuid means to everyone who is connected
                        print('Done')
                        # Close all sockets
                        for s in sockets:
                            s.close()

                        # Stopping the reply thread by sending the uuid
                        print('Sending uuid',rep_thread_uuid.encode('utf-8'))
                        sock_zmq_rep_local.send(rep_thread_uuid.encode('utf-8'))
                        print('Waiting')
                        datab = sock_zmq_rep_local.recv()
                        print('Waiting done')
                        sock_zmq_rep_local.close()

                        for uuidkey in zmq_sub_threads.keys():
                            try:  # Send the command to the corresponding thread
                                zmq_sub_threads[uuidkey]['comqueue'].put('stop')
                            except Exception as e:
                                logstart.exception(e)

                        logstart.info(funcname + ': Stopped')
                        return

                    elif (command == 'query'): # a zmq query command
                        print('Query')
                        try:
                            [packet_type, redvypr_info] = query_host(data['url_query'],zmq_context)
                        except Exception as e:
                            logger.exception(e)
                        print('Got data of type ',packet_type)
                        print('With information',redvypr_info)
                        if(redvypr_info is not None): # Processing the information and sending it to redvypr
                            process_host_information(redvypr_info,hostuuid,hostinfos,statusqueue,dataqueue)

                        print('End query')

                    # Whenever the hostinfo_opt has been changed, publish it to all other devices
                    elif (command == 'hostinfo_opt'):
                        logstart.info(funcname + ': Got hostinfo update')
                        device_info['tinfo'] = time.time() # update the time information
                        device_info['hostinfo_opt'].update(data['hostinfo_opt'])
                        if True:
                            # Send the information over zmq_pub socket to all connected devices
                            datapacket = zmq_publish_data(sock_zmq_pub, data, address_style='<uuid>')
                            #print('Sent device update', datapacket)
                            #print('----------')
                            #print(data)
                            #print('----------')

                        # This is creating at the moment a race condition
                        MULTICASTFLAGS['FLAG_MULTICAST_INFO'] = True
                    # The command is sent from the device whenever the device status of any device of this redvypr
                    # instance changed: device added, removed, keys changed
                    elif (command == 'deviceinfo_all'):
                        FLAG_DEVICE_UPDATE = True
                        logstart.info(funcname + ': Got devices update')
                        print('Filtering')
                        try:
                            # remove devices that do not publish
                            device_info_all = filter_deviceinfo(data['deviceinfo_all'])
                        except Exception as e:
                            logger.exception(e)

                        device_info['tinfo'] = time.time()  # update the time information
                        device_info['deviceinfo_all'] = device_info_all

                        print('Filtering done')
                        try:
                            # Check if the iored device itself has been changed
                            try:
                                print('Devicename', devicename)
                                print('Devices changed',data['devices_changed'])
                                if devicename in data['devices_changed']: # Check if devices except myself have been changed
                                    print('That was myself, will not publish')
                                    data['devices_changed'].remove(devicename)
                                    FLAG_DEVICE_UPDATE = False
                            except:
                                pass
                            if FLAG_DEVICE_UPDATE:
                                logstart.info(funcname + ': deviceinfo_all update, will publish update')
                                # Send the information over zmq_pub socket to all connected devices
                                datapacket = zmq_publish_data(sock_zmq_pub, data, address_style='<uuid>')
                                #print('Sent device update',datapacket)
                                #print('----------')
                                #print(data)
                                #print('----------')
                        except Exception as e:
                            print('Dubidu')
                            logstart.exception(e)

                        # This is creating at the moment a race condition
                        MULTICASTFLAGS['FLAG_MULTICAST_INFO'] = True
                    elif (command == 'multicast_info'): # Multicast send infocommand
                        print('Setting flag Multicast info')
                        MULTICASTFLAGS['FLAG_MULTICAST_INFO'] = True
                    elif (command == 'multicast_getinfo'):  # Multicast command requesting info from other redvypr instances
                        MULTICASTFLAGS['FLAG_MULTICAST_GETINFO'] = True
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

                    # Connect command, either with a uuid or with a url. If its a url, first a query is done to test if
                    # there is a iored host listening on the other side
                    elif (command == 'connect'):
                        # Got an url, trying to connect first
                        if 'url_connect' in data.keys():
                            print('Trying to connect to {:s}'.format(data['url']))
                            print('Query')
                            try:
                                [packet_type, redvypr_info] = query_host(data['url'],zmq_context)
                            except Exception as e:
                                logger.exception(e)
                            print('Got data of type ', packet_type)
                            print('With information', redvypr_info)
                            if (redvypr_info is not None):  # Processing the information (i.e. adding to hostinfos) and sending it to redvypr
                                data['remote_uuid'] = redvypr_info['host']['uuid'] # Add the uuid to data for connection
                                process_host_information(redvypr_info, hostuuid, hostinfos, statusqueue, dataqueue)
                            else:
                                statusqueue.put(
                                    {'type': 'status', 'status': 'connect fail', 'url_rep': data['url']})

                        # Try to connect to uuid
                        try:
                            remote_uuid = data['remote_uuid']
                            logstart.info(
                                funcname + ': Connecting to uuid {:s}'.format(remote_uuid))

                            print('hostinfos', hostinfos.keys())
                            zmq_url_pub = hostinfos[remote_uuid]['zmq_pub']
                            zmq_url_rep = hostinfos[remote_uuid]['zmq_rep']

                            logstart.info(
                                funcname + ': at url {:s}'.format(zmq_url_pub))
                            try:  # Lets check if the thread is already running
                                FLAG_CONNECTED = zmq_sub_threads[remote_uuid]['thread'].is_alive()
                            except Exception as e:
                                FLAG_CONNECTED = False

                            # If not running, create a thread and subscribe to
                            if FLAG_CONNECTED == False:
                                logstart.debug(funcname + ' starting new thread for connecting')
                                connect_dict = connect_remote_host(remote_uuid, zmq_url_pub, zmq_url_rep, dataqueue, statusqueue, hostuuid, hostinfos,zmq_context)
                                if (connect_dict is not None):
                                    zmq_sub_threads[remote_uuid] = connect_dict
                            else:
                                logstart.info(funcname + ': url {:s} already connected'.format(zmq_url_pub))

                        except Exception as e:
                            statusqueue.put({'type': 'status', 'status': 'connect fail','zmq_url_pub':zmq_url_pub,'zmq_url_rep':zmq_url_rep})
                            logstart.exception(e)


                    elif (command == 'disconnect'):
                        # Got an url, trying to connect first
                        if 'url_connect' in data.keys():
                            print('Trying to disconnect to {:s}'.format(data['url']))
                            print('Nood implemented yet')
                        # Try to connect to uuid
                        try:
                            remote_uuid = data['remote_uuid']
                            logstart.info(
                                funcname + ': Disconnecting from uuid {:s}'.format(remote_uuid))

                            print('hostinfos', hostinfos.keys())
                            zmq_url_pub = hostinfos[remote_uuid]['zmq_pub']
                            zmq_url_rep = hostinfos[remote_uuid]['zmq_rep']


                            try:  # Lets check if the thread is already running
                                FLAG_CONNECTED = zmq_sub_threads[remote_uuid]['thread'].is_alive()
                            except Exception as e:
                                FLAG_CONNECTED = False

                            # If not running, create a thread and subscribe to
                            if FLAG_CONNECTED:
                                logstart.info(funcname + ': thread is alive, stopping it now')
                                try:
                                    zmq_sub_threads[remote_uuid]['comqueue'].put_nowait('stop')
                                except Exception as e:
                                    logstart.exception(e)

                        except Exception as e:
                            try:
                                statusqueue.put_nowait({'type': 'status', 'status': 'disconnect fail', 'zmq_url_pub': zmq_url_pub,
                                             'zmq_url_rep': zmq_url_rep})
                            except Exception as e:
                                logstart.exception(e)
                            logstart.exception(e)


                    elif (command == 'subscribe'):
                        try:
                            remote_uuid = data['remote_uuid']
                            substring = data['substring']
                            logstart.info(
                                funcname + ': Subscribing to uuid {:s}'.format(remote_uuid))
                            print('keys', hostinfos.keys())
                            zmq_url_pub = hostinfos[remote_uuid]['zmq_pub']
                            zmq_url_rep = hostinfos[remote_uuid]['zmq_rep']
                            logstart.info(
                                funcname + ': at url {:s}'.format(zmq_url_pub))
                            try: # Lets check if the thread is already running
                                zmq_sub_threads[remote_uuid]['comqueue']
                                FLAG_START_SUB_THREAD = False
                                try:
                                    zmq_sub_threads[remote_uuid]['comqueue'].put_nowait('sub ' + substring)
                                except Exception as e:
                                    logstart.exception(e)
                                    raise IOError('Could not send subscribe command')

                            except Exception as e:
                                zmq_sub_threads[remote_uuid] = {}
                                FLAG_START_SUB_THREAD = True

                            # If not running, create a thread and subscribe to
                            if FLAG_START_SUB_THREAD:
                                logstart.debug(funcname + ' Starting new thread')
                                connect_dict = connect_remote_host(remote_uuid, zmq_url_pub, zmq_url_rep, dataqueue,
                                                                   statusqueue, hostuuid, hostinfos,zmq_context)
                                if(connect_dict is not None):
                                    zmq_sub_threads[remote_uuid] = connect_dict

                                # Thread started, lets subscribe now
                                try:
                                    zmq_sub_threads[remote_uuid]['comqueue'].put_nowait('sub ' + substring)
                                except Exception as e:
                                    logstart.exception(e)

                        except Exception as e:
                            logstart.error(funcname + ' Could not subscribe because of')
                            logstart.exception(e)

                        # Start/update the thread zeromq sub thread

                else: # data packet, lets send it
                    zmq_publish_data(sock_zmq_pub,data)

        # Read the status of all sub threads and update the dictionary
        for uuid in zmq_sub_threads.keys():
            try:
                status = zmq_sub_threads[uuid]['statqueue'].get(block=False)
                #print('Got status',status)
                zmq_sub_threads[uuid]['sub'] = status['sub']
                # Put the subscription status into the statusqueue, this is used for the device to update
                try:
                    statusqueue.put_nowait({'subscribed':status['sub'],'uuid':uuid})
                except Exception as e:
                    logstart.exception(e)
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
    """
    iored device
    """

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
        self.__remote_info__ = {} # A dictionary of remote redvypr devices and information gathered, this is hidden because it is updated by get_remote_info

        #self.redvypr.hostconfig_changed_signal.connect(self.__update_hostinfo__)
        self.redvypr.hostconfig_changed_signal.connect(self.__hostinfo_changed__)
        self.redvypr.device_status_changed_signal.connect(self.__devicestatus_changed__)
        self.statusthread = threading.Thread(target=self.__process_statusdata__, daemon=True)
        self.statusthread.start()

    def start(self, device_info, config, dataqueue, datainqueue, statusqueue):
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
        device_info['tinfo'] = time.time()  # update the time information
        device_info['deviceinfo_all']   = self.redvypr.get_deviceinfo(publishes=True)
        device_info['devicename']       = self.name
        device_info['devicemodulename'] = self.devicemodulename
        device_info['deviceuuid']       = self.uuid
        device_info['hostinfo_opt']     = copy.deepcopy(self.redvypr.hostinfo_opt)
        start(device_info,copy.deepcopy(config), dataqueue, datainqueue, statusqueue)

    def __process_statusdata__(self):
        """
        Reads the statusqueue and processes the data, the data comes from the numoerous threads that receive data as
        start(), start_zmq_sub()
        Returns:

        """
        funcname = __name__ + '.__process_statusdata__():'
        FLAG_SEND_DEVICE_STATUS = False
        while True:
            print('Hallo')
            try:
                data = self.statusqueue.get()
                print('Got status data',data)
                try:
                    deviceinfo_all = None
                    print('Check for command')
                    [com,comdata] = check_for_command(data,add_data=True)
                    print('Check for command',com)
                    if(com == 'stopped'):
                        print('Device stopped command')
                        uuidstop = data['_redvypr']['host']['uuid']
                        self.__mark_host_as_removed__(uuidstop)
                    elif(com == 'device_status'):
                        print('Device status')
                        try:
                            devaddr = comdata['data']['deviceaddr']
                            devstatus = comdata['data']['devicestatus']
                        except Exception as e:
                            logger.exception(e)
                            devaddr = None
                            devstatus = None

                        print('devaddr/devstatus',devaddr,devstatus)
                        if (devaddr is not None):
                            try:  # Update the device
                                self.statistics['device_redvypr'][devaddr]['_redvypr'].update(devstatus)
                            except Exception as e:
                                logger.warning('Could not update status ' + str(e))
                                logger.exception(e)

                        FLAG_SEND_DEVICE_STATUS = True
                    elif com == 'deviceinfo_all':
                        deviceinfo_all = data['deviceinfo_all'] # deviceinfo_all will be updated further down

                    elif com == 'hostinfo_opt':
                        print('Got hostinfo opt command')
                        uuid = data['_redvypr']['host']['uuid']
                        hostinfo_opt   = data['hostinfo_opt']
                        # Update the remote_info
                        try:
                            self.__remote_info__[uuid]['hostinfo_opt'] = hostinfo_opt
                        except Exception as e:
                            logger.exception(e)

                        FLAG_SEND_DEVICE_STATUS = True # Set the flag to update the status of this device

                    if ('type' in data.keys()):
                        if data['type'] == 'stop': # Remote host has been stopped, remove it locally
                            uuidstop = data['info']['host']['uuid']
                            self.__mark_host_as_removed__(uuidstop)

                        elif data['type'] == 'own_info_packet':  # Information about the device info that is sent to other redvypr instances
                            #self.statistics['device_redvypr'][self.address_str]['redvypr_info_publish'] = data['redvypr_info']
                            self.__own_info_packet__ = data['redvypr_info']

                        elif (data['type'] == 'getinfo') or (data['type'] == 'info'):
                            print('remote host information')
                            raddr = data_packets.redvypr_address(local_hostinfo=data['info']['host'])
                            try:
                                self.__remote_info__[raddr.uuid]
                            except:
                                self.__remote_info__[raddr.uuid] = {}
                            try:
                                self.__remote_info__[raddr.uuid].update(data['info'])
                            except:
                                self.__remote_info__[raddr.uuid] = data['info']

                            # If deviceinfo_all in keys, update the statistics, this is done in a thread, atomic operations
                            # in dictionaries should be threadsafe
                            if 'deviceinfo_all' in data['info'].keys():
                                deviceinfo_all = data['info']['deviceinfo_all']

                    # a new deviceinfo_all
                    if deviceinfo_all is not None:
                        all_devices_tmp = []
                        print('Updating device statistics')
                        # Loop over the devicenames: i.e. iored_0, the devices have a dictionary with devices again that this
                        # device is hosting, this is at least one, the device itself, but can be more, for example if devices
                        # are forwarded
                        for hostdevice in deviceinfo_all.keys():
                            # The datakeys as full redvypr addrstrings: 'iored_0:test1@192.168.1.112::190135457042106-110'
                            for deviceaddress in deviceinfo_all[hostdevice].keys():
                                # print('devicekey', dkeyhost,dkey)
                                d = deviceinfo_all[hostdevice][deviceaddress]
                                # print('device', d)
                                daddr = data_packets.redvypr_address(deviceaddress)
                                if daddr.uuid == self.host_uuid:  # This should not happen but anyways
                                    # print('Own device, doing nothing')
                                    pass
                                # elif (d['_redvypr']['devicemodulename'] == 'iored'):
                                #    # print('ioreddevice, doing nothing')
                                #    pass
                                else:
                                    print('Remote device update')
                                    datapacket = create_datapacket_from_deviceinfo(d,tlastseen=time.time())
                                    all_devices_tmp.append(data_packets.get_devicename_from_data(d,uuid=True))
                                    print('datapacket',datapacket)
                                    # update the statistics, this is typically done in redvypr.distribute_data(),
                                    # after a packet was sent, here it is done within the device itself
                                    data_packets.do_data_statistics(datapacket, self.statistics)


                        print('Remove devices')
                        all_devices = self.statistics['device_redvypr'].keys()
                        print('len all_devices',len(all_devices))
                        print('len all_devices tmp', len(all_devices_tmp))
                        # Compare if devices need to be removed
                        devices_rem = []
                        for dold in all_devices:
                            #print('dold',dold)
                            daddr = data_packets.redvypr_address(dold)
                            print('daddr',daddr)
                            if daddr.uuid == self.host_uuid:  # This should not happen but anyways
                                print('Own device, doing nothing')
                                pass
                            elif(dold in all_devices_tmp): # Device is still existing
                                print('Device found, will not change')
                                pass
                            else:
                                print('Will remove device',dold)
                                devices_rem.append(dold)
                                # Check if the lastseen is already negative, if yes dont change, if no update
                                try:
                                    FLAG_ALREADY_REMOVED = self.statistics['device_redvypr'][dold]['_redvypr']['tlastseen'] < 0
                                except:
                                    FLAG_ALREADY_REMOVED = False

                                if FLAG_ALREADY_REMOVED == False:
                                    self.statistics['device_redvypr'][dold]['_redvypr']['tlastseen'] = -time.time()

                        # TODO, check if existing subscriptions match with the new deviceinfo_all, if yes send a subscribe command ...
                        #if 'devices_removed' in data['info'].keys():
                        #    for device_removed in data['info']['devices_removed']:
                        #        print('Removing device',device_removed)
                        FLAG_SEND_DEVICE_STATUS=True
                except Exception as e:
                    print('Exception', e)
                    logger.exception(e)

                # Check if an update should be sent, send a device_status command. That will trigger redvypr.distribute_data to
                # send a 'deviceinfo_all' to the datadistinfoqueue, which is in turn creating a device_changed signal
                # this is complicated but as this function runs in a thread this is thread safe ...
                if FLAG_SEND_DEVICE_STATUS:
                    try:
                        # Sending a device_status command without any further information, this is triggering an upate in distribute_data
                        comdata = {'origin':'__process_statusqueue__','device':self.name}
                        datapacket = data_packets.commandpacket(command='device_status', device_uuid='',
                                                                thread_uuid='',
                                                                devicename=None, host=None,comdata=comdata)
                        # print('Sending statuscommand',datapacket)
                        self.dataqueue.put_nowait(datapacket)
                    except Exception as e:
                        self.logger.exception(e)


            except Exception as e:
                self.logger.exception(e)
                #break

    def __mark_host_as_removed__(self, uuidremove):
        """
        Remove host with uuid from the statistics
        Args:
            uuidremove:

        Returns:

        """
        funcname = __name__ + '.__mark_host_as_removed__():'
        print('Stopping host {:s}'.format(uuidremove))
        all_devices = self.statistics['device_redvypr'].keys()
        #print('len all_devices', len(all_devices))
        FLAG_CHANGED = False
        # Compare if devices need to be removed
        #
        for dold in all_devices:
            #print('dold', dold)
            daddr = data_packets.redvypr_address(dold)
            #print('daddr', daddr)
            if daddr.uuid == uuidremove:  # If the uuids are the same
                FLAG_CHANGED = True
                print(funcname + 'Check if connected',self.statistics['device_redvypr'][dold]['_redvypr'])
                try:
                    connected = self.statistics['device_redvypr'][dold]['_redvypr']['connected']
                except:
                    self.statistics['device_redvypr'][dold]['_redvypr']['connected'] = False
                    connected = False
                if connected:
                    print(funcname + 'Disconnecting device {:s}'.format(str(daddr)))
                    self.zmq_disconnect(daddr.uuid)

                self.statistics['device_redvypr'][dold]['_redvypr']['tlastseen'] = -time.time()

        if FLAG_CHANGED:
            try:
                # Sending a device_status command without any further information
                # this is triggering an upate in distribute_data
                comdata = {'origin': '__mark_host_as_removed__', 'device': self.name}
                datapacket = data_packets.commandpacket(command='device_status', device_uuid='',
                                                        thread_uuid='',
                                                        devicename=None, host=None,comdata=comdata)
                # print('Sending statuscommand',datapacket)
                self.dataqueue.put_nowait(datapacket)
            except Exception as e:
                pass

    def __hostinfo_changed__(self):
        funcname = __name__ + '.__hostinfo_changed__():'
        self.logger.info(funcname)
        self.send_hostinfo_command()

    def __devicestatus_changed__(self):
        funcname = __name__ + '.__devicestatus_changed__():'
        self.logger.info(funcname)
        #devinfo_send = {'type': 'deviceinfo_all', 'deviceinfo_all': copy.deepcopy(deviceinfo_all),
        #                'devices_changed': list(set(devices_changed)),
        #                'devices_removed': devices_removed}
        deviceinfo_changed = copy.deepcopy(self.redvypr.__device_status_changed_data__)
        print('Deviceinfo changed',deviceinfo_changed)
        print('Deviceinfo changed done')
        # Check if the device change came from myself, if yes, dont bother, otherwise trigger an device change
        if 'device_status' in deviceinfo_changed['change'] and deviceinfo_changed['device_changed'] == self.name:
            print('The change was triggered by me, doing nothing')
        elif self.name in deviceinfo_changed['devices_changed']:
            print('Change came from me, will not send an deviceinfo_command to the thread')
        else:
            print('Sending deviceinfo command')
            self.send_deviceinfo_command()

    def send_hostinfo_command(self):
        """
        Sends a deviceinfoall command to the thread
        Returns:

        """
        funcname = __name__ + '.send_hostinfo_command():'
        self.logger.info(funcname)
        hostinfo = {'hostinfo_opt': copy.deepcopy(self.redvypr.hostinfo_opt)}
        print('hostinfo', hostinfo,time.time())
        self.thread_command('hostinfo_opt', hostinfo)

    def send_deviceinfo_command(self):
        """
        Sends a deviceinfoall command to the thread
        Returns:

        """
        funcname = __name__ + '.send_deviceinfo_command():'
        self.logger.info(funcname)
        deviceinfo_all = {'deviceinfo_all': self.redvypr.get_deviceinfo()}
        print('Deviceinfo all',deviceinfo_all)
        self.thread_command('deviceinfo_all',deviceinfo_all)

    # LEGACY, to be removed soon
    def get_remote_device_info_legacy(self,if_changed=False):
        """

        Args:
            if_changed:


        Returns:
           remote_info: Dictionary with discovered devices and their information
        """
        funcname = __name__ + '.get_remote_info():'
        data_all = []
        FLAG_CHANGED = False
        while True:
            try:
                data = self.statusqueue.get_nowait()
                data_all.append(data)
                try:
                    if ('type' in data.keys()):
                        FLAG_CHANGED = True
                        if (data['type'] == 'getinfo') or (data['type'] == 'info'):
                            raddr = data_packets.redvypr_address(local_hostinfo=data['info']['host'])
                            try:
                                self.__remote_info__[raddr.uuid]
                            except:
                                self.__remote_info__[raddr.uuid] = {}
                            try:
                                self.__remote_info__[raddr.uuid].update(data['info'])
                            except:

                                self.__remote_info__[raddr.uuid] = data['info']
                except Exception as e:
                    print('Exception',e)
                    logger.exception(e)
            except:
                break

        #print('data_all',data_all)
        # Return None if nothing has been changed and if_changed argument has been set
        if if_changed:
            if FLAG_CHANGED:
                return self.__remote_info__
            else:
                return None
        else:
            return self.__remote_info__

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
        print('All remote devices',all_remote_devices)
        sub_list = []
        for address_string in all_remote_devices:
            daddr = data_packets.redvypr_address(address_string)
            if(daddr.uuid == self.host_uuid): # Test if this is the local host, if yes, continue
                print('Thats this host')
                continue
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
                if FLAG_SUB_FITS == False:
                    address_string = ''

                sub_list.append([FLAG_SUB_FITS, remote_uuid, address_string, FLAG_SUBSCRIBED])

        return sub_list


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
            print('Testing',subaddr,subdev)
            if(subdev == self.address_str): # Do nothing if its me
                print('Thats me, doing nothing')
                continue
            else:
                sub_list = self.compare_zmq_subscription(subaddr)
                for s in sub_list:
                    FLAG_FIT        = s[0]
                    remote_uuid     = s[1]
                    address_string  = s[2]
                    FLAG_SUBSCRIBED = s[3]

                    print('test',FLAG_FIT,remote_uuid,address_string,FLAG_SUBSCRIBED)
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

    def zmq_connect(self, uuid):
        """
        Connects to a remote iored device, that means that a thread is started (start_zmq_sub) that is continously reading the zmq.sub
        socket of the remote device as well as a zmq.req socket to send requests to the device.
        self.get_devices_by_host()

        Args:
            uuid: uuid of the device

        Returns:

        """
        funcname = __name__ + 'zmq_connect()'
        self.logger.debug(funcname)
        self.thread_command('connect', {'remote_uuid': uuid})

    def zmq_disconnect(self, uuid):
        funcname = __name__ + 'zmq_disconnect()'
        self.logger.debug(funcname)
        self.thread_command('disconnect', {'remote_uuid': uuid})

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

    def query_host(self,url_query):
        """
        Querying a remote host
        Args:
            url_query:

        Returns:

        """
        self.thread_command('query', {'url_query': url_query})

    def connect_host(self, url_connect):
        """
        Connects to a remote host
        Args:
            url_connect:

        Returns:

        """
        self.thread_command('connect', {'url': url_connect})


class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self, device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        self.device = device
        self.deviceinfolabel = QtWidgets.QLabel('Discovered iored devices')
        self.deviceinfotree = QtWidgets.QTreeWidget()
        self.deviceinfotree.setHeaderLabels(['Address', 'Last seen'])
        self.deviceinfotree.itemDoubleClicked.connect(self.__open_remote_host_info__)

        self.devicelabel = QtWidgets.QLabel('Remote data publishing devices')
        self.devicetree = QtWidgets.QTreeWidget()
        self.devicetree.currentItemChanged.connect(self.__item_changed__)
        self.devicetree.itemDoubleClicked.connect(self.__open_remote_device_info__)
        self.reqbtn = QtWidgets.QPushButton('Get info')
        self.reqbtn.clicked.connect(self.__getinfo_command__)
        self.sendbtn = QtWidgets.QPushButton('Send Info')
        self.sendbtn.clicked.connect(self.__sendinfo_command__)
        self.querybtn = QtWidgets.QPushButton('Query Address')
        self.querybtn.clicked.connect(self.__query_command__)
        IP = redvypr.get_ip()
        self.queryaddr = QtWidgets.QLineEdit('tcp://{:s}:18197'.format(IP))

        #self.sendbtn.clicked.connect(self.__update_devicelist__)
        self.subbtn = QtWidgets.QPushButton('Subscribe')
        self.subbtn.clicked.connect(self.__subscribe_clicked__)
        self.subbtn.setEnabled(False)
        #layout.addWidget(self.deviceinfolabel, 0, 0)
        #layout.addWidget(self.deviceinfotree, 1, 0)
        layout.addWidget(self.devicelabel, 2, 0)
        layout.addWidget(self.devicetree,3,0,1,2)
        layout.addWidget(self.subbtn, 4, 0,1,2)
        layout.addWidget(self.reqbtn,5,0)
        layout.addWidget(self.sendbtn, 5, 1)
        layout.addWidget(self.queryaddr, 6, 0)
        layout.addWidget(self.querybtn, 6, 1)
        self.__update_devicelist__()

        ## A timer to gather all the data from the devices
        #self.updatetimer = QtCore.QTimer()
        #self.updatetimer.timeout.connect(self.__update_deviceinfolist__)
        #self.updatetimer.start(500)

        #self.device.redvypr.datastreams_changed_signal.connect(self.__update_devicelist__)
        self.device.redvypr.device_status_changed_signal.connect(self.__update_devicelist__)

    def __query_command__(self):
        funcname = __name__ + '__query_command__():'
        url_query = self.queryaddr.text()
        logger.info(funcname + 'Querying {:s}'.format(url_query))
        self.device.query_host(url_query)


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

            try:
                connected = new.connected
            except:
                connected = None

            # Check if its a device item
            try:
                tlastseen = new.tlastseen
            except:
                tlastseen = 0
            #if (new.parent() == None):
            if (new.subscribeable==False) or (new.parent() == None):
                print('Got device to connect')
                print('Connected',connected)
                if(connected == False):
                    self.subbtn.setText('Connect')
                    self.subbtn.setEnabled(True)
                else:
                    self.subbtn.setText('Disconnect')
                    self.subbtn.setEnabled(True)
            elif(new.subscribeable == False):
                self.subbtn.setText('Subscribe')
                self.subbtn.setEnabled(False)
            else:
                self.subbtn.setEnabled(True)
                if(subscribed):
                    self.subbtn.setText('Unsubscribe')
                else:
                    self.subbtn.setText('Subscribe')

            if tlastseen <0:
                self.subbtn.setEnabled(False)


    def __subscribe_clicked__(self):
        funcname = __name__ + '__subscribe_clicked__():'
        logger.debug(funcname)
        getSelected = self.devicetree.selectedItems()
        if getSelected:
            baseNode = getSelected[0]
            #if(baseNode.parent() == None):
            if baseNode.subscribeable == False:
                #uuid = baseNode._redvypr['host']['uuid']
                hostnameuuid = baseNode.hostnameuuid
                hostuuid = baseNode.hostuuid
                print('uuid',hostuuid)
                if (baseNode.connected == False):
                    print('Got device, connecting')
                    self.device.zmq_connect(hostuuid)
                else:
                    print('Got device, disconnecting')
                    self.device.zmq_disconnect(hostuuid)


            else:
                #devstr = baseNode.text(0)
                devstr = data_packets.get_deviceaddress_from_redvypr_meta(baseNode._redvypr,uuid=True)
                uuid = baseNode._redvypr['host']['uuid']
                if(self.subbtn.text() == 'Subscribe'):
                    print('Subscribing to',devstr)
                    self.device.zmq_subscribe(uuid,devstr)
                else:
                    print('Unsubscribing from',devstr)
                    self.device.zmq_unsubscribe(uuid,devstr)


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

    def __open_remote_device_info__(self, item):
        """
        Opening a widget that shows the information of the remote host
        Returns:

        """
        funcname = '__open_remote_device_info__'
        logger.debug(funcname)
        FLAG_DEVICE = False
        FLAG_HOST   = False
        try:
            item.devname
            FLAG_DEVICE=True
        except:
            print('Not a device, doing nothing')
            try:
                item.hostinfo
                FLAG_HOST = True
            except:
                return
        if FLAG_DEVICE:
            print('address',item.devname)
            devtxt = str(item.devinfo)

        if FLAG_HOST:
            print(item.hostinfo)
            devtxt = str(item.hostinfo)

        self.hostinfo_widget = QtWidgets.QPlainTextEdit()
        self.hostinfo_widget.insertPlainText(str(devtxt))
        self.hostinfo_widget.setWindowIcon(QtGui.QIcon(_icon_file))
        self.hostinfo_widget.setWindowTitle("redvypr iored remote host info")
        self.hostinfo_widget.show()


    def __open_remote_host_info__(self,item):
        """
        Opening a widget that shows the information of the remote host
        Returns:

        """
        funcname = '__open_device_info__'
        logger.debug(funcname)
        devtxt = self.devinfo[item.__devaddress__]
        self.hostinfo_widget = QtWidgets.QPlainTextEdit()
        self.hostinfo_widget.insertPlainText(str(devtxt))
        self.hostinfo_widget.setWindowIcon(QtGui.QIcon(_icon_file))
        self.hostinfo_widget.setWindowTitle("redvypr remote host info")
        self.hostinfo_widget.show()

    def __update_devicelist__(self):
        """
        Updates the qtreewidget with the devices found in self.device.redvypr
        Returns:

        """

        funcname = __name__ + '__update_devicelist__():'
        print('display widget update devicelist')
        self.devicetree.clear()
        self.devicetree.setColumnCount(2)
        self.devicetree.setHeaderLabels(['Address', 'Status'])
        root = self.devicetree.invisibleRootItem()
        # Devices sorted by the host  and saved in a dict with a hostnameuuid as a key
        devices = self.device.get_devices_by_host()
        #print('devices',devices)
        for hostnameuuid in devices.keys():
            raddr = data_packets.redvypr_address(hostnameuuid)
            hostuuid = hostnameuuid.split('::')[1]
            if (hostuuid == self.device.redvypr.hostinfo['uuid']): # Dont show own packets
                print('Own device')
                continue
            else:
                # TODO, sort out iored remote devices
                pass

            itm = QtWidgets.QTreeWidgetItem([hostnameuuid,''])
            itm.subscribeable = False
            itm.subscribed = False
            itm.hostnameuuid = hostnameuuid
            itm.hostuuid = hostuuid
            try:
                itm.hostinfo = self.device.__remote_info__[hostuuid]
            except:
                itm.hostinfo = {}

            try:
                hostinfo_opt = itm.hostinfo['hostinfo_opt']
            except:
                hostinfo_opt = {}

            root.addChild(itm)
            # Add deviceinfo parent
            itminfoparent = QtWidgets.QTreeWidgetItem(['Info', ''])
            itminfoparent.subscribeable = False
            itminfoparent.subscribed = False
            itminfoparent.hostnameuuid = hostnameuuid
            itminfoparent.hostuuid = hostuuid
            itm.addChild(itminfoparent)
            # Populate host information
            for k in hostinfo_opt.keys():
                keydata = str(hostinfo_opt[k])
                if(len(keydata)>0) and (k != 'template_name'):
                    itminfo = QtWidgets.QTreeWidgetItem([k, keydata])
                    itminfo.subscribeable = False
                    itminfo.subscribed = False
                    itminfo.hostnameuuid = hostnameuuid
                    itminfo.hostuuid = hostuuid
                    itminfoparent.addChild(itminfo)


            # Add devices parent
            itmdevparent = QtWidgets.QTreeWidgetItem(['Devices', ''])
            itmdevparent.subscribeable = False
            itmdevparent.subscribed = False
            itmdevparent.hostnameuuid = hostnameuuid
            itmdevparent.hostuuid = hostuuid
            itm.addChild(itmdevparent)
            # Populate devices
            for d in devices[hostnameuuid]:
                #print('Device d',d)
                substr = 'not subscribed'
                FLAG_SUBSCRIBED = None
                FLAG_CONNECTED = None
                try:
                    tlastseen = d['_redvypr']['tlastseen']
                except:
                    tlastseen = 0

                if('iored' in d['_redvypr']['devicemodulename']):
                    # iored devices are connected, not subscribed
                    #print('dfds',d['_redvypr'])
                    try:
                        try:
                            FLAG_CONNECTED = d['_redvypr']['connected']
                        except:
                            #d['_redvypr']['connected'] = False
                            FLAG_CONNECTED = False

                        itm.connected = FLAG_CONNECTED
                        if FLAG_CONNECTED:
                            substr = 'connected'
                            itm.setText(1, 'connected')
                        else:
                            substr = 'not connected'
                            itm.setText(1, 'not connected')

                    except Exception as e:
                        print('Subscribed?',e)
                        #FLAG_CONNECTED = False

                else:
                    try:
                        FLAG_SUBSCRIBED = d['_redvypr']['subscribed']
                        if FLAG_SUBSCRIBED:
                            substr = 'subscribed'
                    except Exception as e:
                        #print('Subscribed?',e)
                        FLAG_SUBSCRIBED = False

                try:
                    FLAG_SUBSCRIBEABLE = d['_redvypr']['subscribeable']
                except Exception as e:
                    # print('Subscribed?',e)
                    FLAG_SUBSCRIBEABLE = False


                devname = d['_redvypr']['device']
                #raddr = data_packets.redvypr_address(redvypr_meta=d['_redvypr'])
                itmdevice = QtWidgets.QTreeWidgetItem([devname,substr])
                itmdevice.subscribeable = FLAG_SUBSCRIBEABLE
                itmdevice.subscribed = FLAG_SUBSCRIBED
                itmdevice.connected = FLAG_CONNECTED
                itmdevice.hostnameuuid = hostnameuuid
                itmdevice.hostuuid = hostuuid
                itmdevice.devname = devname
                itmdevice.devinfo = d
                itmdevice.tlastseen = tlastseen
                #itmdevice.__devaddress__ = raddr.address_str
                itmdevice._redvypr = d['_redvypr']
                try:
                    itmdevice.subscribeable = d['_redvypr']['subscribeable']
                except:
                    itmdevice.subscribeable = False
                itmdevparent.addChild(itmdevice)

                if(tlastseen < 0):
                    itmdevice.setForeground(0, QtGui.QBrush(QtGui.QColor("red")))
                    td_lastseen = datetime.datetime.fromtimestamp(-tlastseen)
                    str_tlastseen = td_lastseen.strftime('%d.%m.%Y %H:%M:%S')
                    itmdevice.setText(1, 'stopped {:s}'.format(str_tlastseen))
                #else:
                #    itmdevice.setForeground(0, QtGui.QBrush(QtGui.QColor("black")))

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






