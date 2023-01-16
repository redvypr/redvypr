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
from redvypr.data_packets import check_for_command, commandpacket, get_address_from_data, redvypr_address



zmq_context = zmq.Context()
description = 'Internet of Redvypr, device allows to easily connect to other redvypr devices '

config_template = {}
config_template['template_name']  = 'iored'
config_template['redvypr_device'] = {}
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
            redvypr_info = yaml.safe_load(data[headerlen:])
            return ['info',redvypr_info]
        except Exception as e:
            redvypr_info = ['info',None]

    elif datab.startswith(multicast_header['getinfo']):  # Search for info request
        try:
            headerlen = len(multicast_header['getinfo'])
            data = datab.decode('utf-8')
            redvypr_info = yaml.safe_load(data[headerlen:])
            return ['getinfo', redvypr_info]
        except Exception as e:
            redvypr_info = ['info', None]

    return [None,None]

def create_datapackets_from_multicast_info(redvypr_info,datastream = None):
    """

    Args:
        redvypr_info:

    Returns:
        Either a list of datapackets (datastream == None) or a single datapacket if a datastream equal to the argument "datastream" was found.

    """
    funcname = __name__ + '.create_datapackets_from_multicast_info()'
    datapackets = []
    print('hallo',redvypr_info)
    for d in redvypr_info['datastreams_dict']:
        if (datastream == None) or (d == datastream):
            print('------------')
            print('d',d)
            dpacket = {}
            addr = redvypr_address(d)
            dpacket['t']      = redvypr_info['t']
            dpacket['device'] = addr.devicename
            dpacket['host']   = redvypr_info['host']
            dpacket['host']['local'] = False
            print('dpacket', dpacket)
            print('------------')
            if(datastream == None):
                datapackets.append(dpacket)
            else: # Return the single datapacket
                return dpacket

    return datapackets



#https://stackoverflow.com/questions/166506/finding-local-ip-addresses-using-pythons-stdlib
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

def yaml_dump(data):
    #return yaml.dump(data,default_flow_style=False)
    return yaml.dump(data,explicit_end=True,explicit_start=True)

def rawcopy(data):
    """
    Functions that simply returns the input data, used as the basic field conversion function
    """
    return data


def start_recv(dataqueue, datainqueue, statusqueue, config=None,device_info=None):
    """ zeromq receiving data
    """
    funcname = __name__ + '.start_recv()'

    sub = zmq_context.socket(zmq.SUB)
    url = 'tcp://' + config['address'] + ':' + str(config['port'])
    logger.debug(funcname + ':Start receiving data from url {:s}'.format(url))
    sub.setsockopt(zmq.RCVTIMEO, 200)
    sub.connect(url)
    # subscribe to topic '', TODO, do so
    sub.setsockopt(zmq.SUBSCRIBE, b'')

    datapackets = 0
    bytes_read  = 0

    # Some variables for status
    tstatus = time.time()
    try:
        dtstatus = config['dtstatus']
    except:
        dtstatus = 2 # Send a status message every dtstatus seconds
        
    #
    npackets = 0 # Number packets received
    while True:
        try:
            data = datainqueue.get(block=False)
        except:
            data = None

        if(data is not None):
            command = check_for_command(data,thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command {:s}'.format(str(data)))
            if (command is not None):
                logger.debug(funcname + ': received command:' + str(command) + ', stopping now')
                sub.close()
                logger.debug(funcname + ': zeromq port closed.')
                return

        try:
            #datab = sub.recv(zmq.NOBLOCK)
            datab = sub.recv()
            #print('Got data',datab)
        except Exception as e:
            #logger.debug(funcname + ':' + str(e))
            datab = b''


        if(len(datab)>0):
            t = time.time()
            bytes_read += len(datab)
            # Check what data we are expecting and convert it accordingly
            if(config['serialize'] == 'yaml'):
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

            else: # Put the "str" data into the packet with the key in "data"
                key = config['data']
                data = datab.decode('utf-8')
                datan = {'t':t}
                datan[key] = data
                try:
                    dataqueue.put(datan)
                except Exception as e:
                    print('Exception',e)

                datapackets += 1



        # Sending a status message
        if((time.time() - tstatus) > dtstatus):
            statusdata = {}
            statusdata['bytes_read']  = bytes_read
            statusdata['datapackets'] = datapackets
            statusdata['time'] = str(datetime.datetime.now())
            tstatus = time.time()
            #statusdata['clients'] = []
            statusdata['config'] = copy.deepcopy(config)
                
            try:
                statusqueue.put_nowait(statusdata)
            except: # If the queue is full
                pass



def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    receivers_subscribed    = [] # List of external receivers subscribed to own datastreams
    subscribed_to_publisher = [] # List of external publisher we have subscribed to
    dt_sleep  = 0.05
    queuesize = 100 # The queuesize for the subthreads
    sockets   = []
    datastreams_uuid = {} # A local list of datastreams, prohibing sending known datastreams again and again
    #
    # The multicast send socket
    #
    MULTICASTADDRESS = "239.255.255.250" # The same as SSDP
    MULTICASTPORT = 18196
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
    zmq_ports = range(18196,19000)
    for zmq_port in zmq_ports:
        url = 'tcp://' + device_info['hostinfo']['addr'] + ':' + str(int(zmq_port))
        print('Trying to connect zmq pub to {:s}'.format(url))
        try:
            sock_zmq_pub.bind(url)
        except Exception as e:
            pass
        logger.info(funcname + ':Start publishing data at url {:s}'.format(url))
        break


    sockets.append(sock_zmq_pub)
    # Zeromq receive
    #sock_zmq_sub = zmq_context.socket(zmq.SUB)
    #logger.debug(funcname + ':Start receiving data from url {:s}'.format(url))
    #sock_zmq_sub.setsockopt(zmq.RCVTIMEO, 0) # milliseconds
    #sock_zmq_sub.connect(url)
    ## subscribe to topic '', TODO, do so
    #sock_zmq_sub.setsockopt(zmq.SUBSCRIBE, b'')
    #sockets.append(sock_zmq_sub)

    if False:
        queue_send_beacon = queue.Queue(maxsize=queuesize)
        send_beacon = threading.Thread(target=start_send_beacon, args=(dataqueue, queue_send_beacon, statusqueue, config, device_info))
        send_beacon.start()

        queue_recv_beacon = queue.Queue(maxsize=queuesize)
        recv_beacon = threading.Thread(target=start_recv_beacon,
                                       args=(dataqueue, queue_recv_beacon, statusqueue, config, device_info))
        recv_beacon.start()

    # Infinite loop
    while True:
        tstart = time.time()


        # Trying to receive data from multicast
        try:
            data_multicast_recv = sock_multicast_recv.recv(10240) # This could be a potential problem as this is finite
            #print('Got multicast data',data_multicast_recv)
            print('Got multicast data')
            [multicast_command,redvypr_info] = process_multicast_packet(data_multicast_recv)
            #print('Command',multicast_command,redvypr_info)
            print('from uuid',redvypr_info['host']['uuid'])
            if multicast_command == 'getinfo':
                try:
                    print('Getinfo request from {:s}::{:s}'.format(redvypr_info['host']['hostname'], redvypr_info['host']['uuid']))
                except Exception as e:
                    logger.exception(e)

                FLAG_MULTICAST_INFO = True
            elif multicast_command == 'info':
                try:
                    uuid = redvypr_info['host']['uuid']
                    try:
                        datastreams_uuid[uuid] = [] # Create a list for the uuid
                    except:
                        pass
                except:
                    uuid = None

                if(uuid == device_info['hostinfo']['uuid']):
                    print('Own packet')
                else:
                    print('Info from {:s}::{:s}'.format(redvypr_info['host']['hostname'],redvypr_info['host']['uuid']))
                    print('redvypr_info',redvypr_info)
                    if 'datastreams_dict' in redvypr_info.keys():
                        for  d in redvypr_info['datastreams_dict']:
                            daddr = redvypr_address(d)
                            if d in datastreams_uuid[uuid]:
                                pass
                            elif daddr.uuid == device_info['hostinfo']['uuid']:
                                print('Self')
                            else:
                                print('New datastream')
                                datastreams_uuid[uuid].append(d)
                                datapacket = create_datapackets_from_multicast_info(redvypr_info,datastream = d)
                                # Send the packet, distribute_data() will call do_data_statistics() and will add them to the available datastreams
                                # This will again create on return a signal that the datastreams have been changed
                                dataqueue.put_nowait(datapacket)

            #print('Received multicast data!!', data_multicast_recv)
        except:
            pass

        #
        # Sending multicast data
        #
        if (dtbeacon > 0) or FLAG_MULTICAST_INFO:
            if ((time.time() - tbeacon) > dtbeacon) or FLAG_MULTICAST_INFO:
                FLAG_MULTICAST_INFO = False
                print('Sending multicast info',time.time())
                multicast_packet = {'host': device_info['hostinfo'], 't': time.time(), 'zmq_pub': url,
                                    'datastreams_dict': device_info['datastreams_dict']}
                hostinfoy = yaml.dump(multicast_packet, explicit_end=True, explicit_start=True)
                hostinfoy = hostinfoy.encode('utf-8')
                datab = multicast_header['info'] + hostinfoy
                sock_multicast_send.sendto(datab, (MULTICASTADDRESS, MULTICASTPORT))

                # print('Sending zmq data')
                # sock_zmq_pub.send_multipart([b'123',b'Hallo!'])
        if FLAG_MULTICAST_GETINFO:
            FLAG_MULTICAST_GETINFO = False
            print('Sending multicast getinfo request')
            multicast_packet = {'host': device_info['hostinfo'], 't': time.time()}
            hostinfoy = yaml.dump(multicast_packet, explicit_end=True, explicit_start=True)
            hostinfoy = hostinfoy.encode('utf-8')
            datab = multicast_header['getinfo'] + hostinfoy
            sock_multicast_send.sendto(datab, (MULTICASTADDRESS, MULTICASTPORT))

        #
        # Sending multicast data done
        #

        # Try to receive subscription filter data from the xpub socket
        try:
            data_pub = sock_zmq_pub.recv_multipart()
            receivers_subscribed.append(data_pub)
            print('Received a subscription', data_pub,receivers_subscribed)
        except Exception as e:
            #print('e',e)
            pass

        if False: # This is bogus, each zeromq publishes needs to have an own recevier.
            # Trying to receive data from zmq socket
            try:
                data_zeromq_recv = sock_zmq_sub.recv()
                print('Received zeromq data!!', data_zeromq_recv)
            except:
                pass

        while datainqueue.empty() == False:
            try:
                data = datainqueue.get(block=False)
            except:
                data = None

            if data is not None:
                command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
                # logger.debug('Got a command: {:s}'.format(str(data)))
                if command is not None:
                    logger.debug('Command is for me: {:s}'.format(str(command)))
                    #queue_send_beacon.put_nowait(data)
                    #queue_recv_beacon.put_nowait(data)
                    if(command == 'stop'):
                        # Close all sockets
                        for s in sockets:
                            s.close()

                        logger.info(funcname + ': Stopped')
                        return
                    elif (command == 'datastreams'):
                        logger.info(funcname + ': Got datastreams update')
                        print('datastreams!')
                        print('datastreams!')
                        print('datastreams!')
                        print('datastreams!')
                        print('datastreams!',data)
                        device_info['datastreams_dict'].update(data['datastreams_dict'])
                        FLAG_MULTICAST_INFO = True # Send the information over multicast
                    elif (command == 'multicast_info'): # Multicast send infocommand
                        FLAG_MULTICAST_INFO = True
                    elif (command == 'multicast_getinfo'):  # Multicast command requesting info from other redvypr instances
                        FLAG_MULTICAST_GETINFO = True
                    elif (command == 'subscribe'):
                        logger.info(funcname + ': Subscribing to device {:s}'.format(data['device']))

                else: # data packet, lets send it
                    datab = yaml.dump(data,explicit_end=False,explicit_start=False).encode('utf-8')
                    #print('Got data',data)
                    addrstr = get_address_from_data('',data,style='full')
                    #datasend = addrstr[1:].encode('utf-8') + ' '.encode('utf-8') + datab
                    tsend = 't{:.6f}'.format(time.time()).encode('utf-8')
                    sock_zmq_pub.send_multipart([addrstr[1:].encode('utf-8'), tsend,datab])

        tend = time.time()
        dt_usage = tend - tstart
        dt_realsleep = dt_sleep - dt_usage
        time.sleep(dt_realsleep)



class Device(redvypr_device):
    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)

        self.logger.info(funcname + ' subscribing to devices')
        for d in self.redvypr.devices:
            dev = d['device']
            self.subscribe_device(dev)

        self.forwarded_devices_subscribed = {}

        self.redvypr.datastreams_changed_signal.connect(self.__update_datastreams__)
        self.redvypr.device_added.connect(self.__update_subscription__)

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
        device_info['datastreams_dict'] = copy.deepcopy(self.redvypr.datastreams_dict)
        device_info['hostinfo_opt'] = copy.deepcopy(self.redvypr.hostinfo_opt)
        start(device_info,config, dataqueue, datainqueue, statusqueue)

    def subscribe_forwarded_device(self, address_string):
        """
        Subscribes a forwarded device in the
        Args:
            address_string:

        Returns:

        """
        pass

    def got_subscription(self, dataprovider_address, datareceiver_address):
        print('Hallo got subscription',dataprovider_address, datareceiver_address)

    def __update_subscription__(self,devicelist):
        """
        Update the device subscriptions
        Args:
            devicelist:

        Returns:

        """
        funcname = __name__ + '__update_subscription__()'

        self.logger.info(funcname + ' updating subscription')
        for d in self.redvypr.devices:
            dev = d['device']
            try:
                self.subscribe_device(dev)
            except Exception as e:
                pass


    def __update_datastreams__(self):
        """
        Whenever new signals arrived the datastreamlist needs to be updated
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

    def sort_devicelist_by_host(self,devices):
        """
        Sorts the forwarded devicelist by remote host and returns a dictionary
        Returns:
           Dictionary with the hostnames as keys and redvypr_addresses as list entries
        """
        devicedict = {}
        for d in devices:
            daddr = redvypr_address(d)
            hostname = daddr.hostname + '::' + daddr.uuid
            try:
                devicedict[hostname]
            except:
                devicedict[hostname] = []

            devicedict[hostname].append(daddr)

        return devicedict

class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self, device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        self.device = device
        self.devicetree = QtWidgets.QTreeWidget()

        self.reqbtn = QtWidgets.QPushButton('Get info')
        self.reqbtn.clicked.connect(self.__getinfo_command__)
        self.sendbtn = QtWidgets.QPushButton('Send Info')
        self.sendbtn.clicked.connect(self.__sendinfo_command__)
        self.subbtn = QtWidgets.QPushButton('Subscribe')
        self.subbtn.clicked.connect(self.__subscribe_clicked__)
        layout.addWidget(self.devicetree,0,0,1,2)
        layout.addWidget(self.subbtn, 1, 0,1,2)
        layout.addWidget(self.reqbtn,2,0)
        layout.addWidget(self.sendbtn, 2, 1)
        self.__update_devicelist__()
        self.device.redvypr.datastreams_changed_signal.connect(self.__update_devicelist__)

    def __subscribe_clicked__(self):
        funcname = __name__ + '__subscribe_clicked__():'
        logger.debug(funcname)
        getSelected = self.devicetree.selectedItems()
        if getSelected:
            baseNode = getSelected[0]
            devstr = baseNode.text(0)
            print('Subscribing to',devstr)
            self.device.thread_command('subscribe', {'device': devstr})

    def __getinfo_command__(self):
        funcname = __name__ + '__getinfo_command__():'
        logger.debug(funcname)
        self.device.thread_command('multicast_getinfo',{})

    def __sendinfo_command__(self):
        funcname = __name__ + '__sendinfo_command__():'
        logger.debug(funcname)
        self.device.thread_command('multicast_info', {})

    def __subscribe_command__(self,device):
        """
        Command to the start thread to subscribe a certain device
        Returns:

        """
        funcname = __name__ + '__subscribe_command__():'
        logger.debug(funcname)
        self.device.thread_command('subscribe', {'device':device})

    def __unsubscribe_command__(self, device):
        """
        Command to the start thread to subscribe a certain device
        Returns:

        """
        funcname = __name__ + '__unsubscribe_command__():'
        logger.debug(funcname)
        self.device.thread_command('unsubscribe', {'device': device})

    def __update_devicelist__(self):
        """
        Updates the qtreewidget with the devices found in self.device.redvypr
        Returns:

        """

        funcname = __name__ + '__update_devicelist__():'
        print('display widget update devicelist')
        self.devicetree.clear()
        self.devicetree.setColumnCount(1)
        root = self.devicetree.invisibleRootItem()
        devdict = self.device.sort_devicelist_by_host(self.device.statistics['devices'])
        print('devdict',devdict)
        for host in devdict.keys():
            itm = QtWidgets.QTreeWidgetItem([host])
            root.addChild(itm)
            for d in devdict[host]:
                devname = d.devicename
                itmdevice = QtWidgets.QTreeWidgetItem([devname])
                itm.addChild(itmdevice)

    def update(self, data):
        """

        Args:
            data:

        Returns:

        """
        pass




