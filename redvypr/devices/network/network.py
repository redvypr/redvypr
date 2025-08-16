"""
network device
"""


import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import threading
import socket
#from apt_pkg import config
import yaml
import copy
import pydantic
import typing
from redvypr.device import RedvyprDevice
from redvypr.data_packets import check_for_command
import redvypr.redvypr_address as redvypr_address
import redvypr.packet_statistic as packet_statistic
from redvypr.widgets.pydanticConfigWidget import dictQTreeWidget
from redvypr.widgets.standard_device_widgets import displayDeviceWidget_standard

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.network_device')
logger.setLevel(logging.INFO)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Send and receive data using standard network protocols as TCP or UDP'
    gui_tablabel_display: str = 'Network Status'

class DeviceCustomConfig(pydantic.BaseModel):
    address: str = pydantic.Field(default='<IP>', description='The IP address, this can be also <IP> or <broadcast>')
    port: int = pydantic.Field(default=18196, description='The network port used')
    protocol: typing.Literal['tcp', 'udp'] = pydantic.Field(default='tcp', description= 'The network protocol used.')
    direction: typing.Literal['publish', 'receive'] = pydantic.Field(default='tcp', description='Publishing or receiving data.')
    datakey: str = pydantic.Field(default='all', description='Datakey to store data, this is used if serialize is raw or str')
    serialize: typing.Literal['yaml','str','raw'] = pydantic.Field(default='raw',description='Method to serialize (convert) original data into binary data.')
    queuesize: int = pydantic.Field(default=10000, description= 'Size of the queues for transfer between threads')
    dt_status: float = pydantic.Field(default=4.0,description= 'Send a status message every dt_status seconds')
    tcp_reconnect: bool = pydantic.Field(default=True, description = 'Reconnecting to TCP Port if connection was closed by host')
    tcp_numreconnect: int = pydantic.Field(default= 10, description='The number of reconnection attempts before giving up')


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

def raw_to_packet(datab, config, safe_load=True):
    """
    Packs the received raw data into a packet that can be sent via the dataqueue

    Args:
        datab:
        config:
        safe_load:

    Returns:
        packets: A list of datapackets to be sent via the dataqueue

    """
    funcname = __name__ + '.raw_to_packet()'
    t = time.time()
    packets = []
    datab_rest = b''
    #print('A data:',datab)
    #print('-------------------')
    if safe_load:
        loader = yaml.SafeLoader
    else:
        loader = yaml.CLoader
    if(config['serialize'] == 'yaml'):
        i0 = datab.find(b'---\n')
        i1 = datab.rfind(b'...\n')+4
        # Check here if we got some data
        datab_valid = datab[i0:i1]
        datab_rest = datab[i1:]
        for databs in datab_valid.split(b'...\n'): # Split the text into single subpackets
            try:
                data = yaml.load(databs,Loader=loader)
            except Exception as e:
                #print('data',databs)
                logger.info(funcname + ': Could not decode message:',exc_info=True)
                logger.debug(funcname + ': Could not decode message  with supposed format {:s} into something useful.'.format(config['datakey']))
                data = None
            if(data is not None):
                if(config['datakey'] == 'all'): # Forward the whole message
                    packets.append(data)
                else:
                    datan = {'t':t}
                    datan[config['datakey']] = data[config['datakey']]
                    packets.append(datan)

    elif (config['serialize'] == 'utf-8'):  # Put the "str" data into the packet with the key in "data"
        data = datab.decode('utf-8')
        datan = {'t':t}
        datan[config['datakey']] = data
        packets.append(datan)
    elif(config['serialize'] == 'raw'): # Put the "str" data into the packet with the key in "data"
        datan = {'t':t}
        datan[config['datakey']] = datab
        packets.append(datan)

    return {'packets':packets,'datab_rest':datab_rest}

def packet_to_raw(data_dict,config):
    """ Function that processes the data_dict to a serialized datastream sendable over network connections 
    """
    funcname = __name__ + 'send_data()'
    #
    if (config['datakey'] == 'all') and (config['serialize'] == 'yaml'):
        datab = yaml_dump(data_dict).encode('utf-8')
    elif (config['serialize'] == 'utf-8'):
        key = config['datakey']
        datab = str(data_dict[key]).encode('utf-8')
    elif (config['serialize'] == 'raw'):
        key = config['datakey']
        data = data_dict[key]
        if(isinstance(data, (bytes, bytearray))):
            datab = data
        else:
            datab = str(data).encode('utf-8')

    return datab


def handle_tcp_client_send(client, threadqueue, statusqueue, config):
    funcname =  __name__ + 'handle_tcp_client_send()'
    address = client[1]
    client = client[0]
    statusstr = 'Sending data to (TCP):' + str(address)
    nsent = 0
    dt_status = config['dt_status']
    tlast_status = time.time()
    #statusdict = {'tcp': {'send': {'address': {address: {'sent': nsent, 'status': 'open'}}}}}
    try:
        statusqueue.put_nowait(statusstr)
        #statusqueue.put_nowait(statusdict)
        logger.info(funcname + ':' + statusstr)
    except Exception as e:
        logger.warning(funcname + ':' + str(e))
    
    while True:
        data = threadqueue.get() # Blocking
        tread = time.time()
        #print('Read data from queue')
        try:
            logger.debug(funcname  + ':Sending data: {:s}'.format(str(data)))
            client.send(data)
            nsent += len(data)
        except Exception as e:
            statusstr = 'Connection to {:s} closed, stopping thread, sent {:d}bytes'.format(str(address),nsent)
            try:
                statusqueue.put_nowait(statusstr)
            except: # If the queue is full
                pass
            logger.info(funcname + ':' + statusstr)
            return

        if (tread - tlast_status) > dt_status:
            statusstr = 'Connection to {:s} open, sent {:d}bytes'.format(str(address), nsent)
            #statusdict = {'tcp': {'send': {'address': {address:{'sent':nsent,'status':'open'}}}}}
            try:
                statusqueue.put_nowait(statusstr)
                #statusqueue.put_nowait(statusdict)
            except:  # If the queue is full
                pass
            logger.debug(funcname + ':' + statusstr)
            tlast_status = time.time()



def start_tcp_send(dataqueue, datainqueue, statusqueue, config=None, device_info=None):
    """ TCP publishing, this thread waits for TCP connections connections. For each connection a new connection is created that is fed with a subthread (handle_tcp_send) is created that is receiving data with a new queue. 
    """
    funcname = __name__ + '.start_tcp_send()'
    logger.debug(funcname + ':Starting network thread')        
    npackets     = 0 # Number of packets
    bytes_read   = 0
    metadata_packet = None
    metadata_update = False
    threadqueues = []
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    logger.debug(funcname + ' Binding to {:s}:{:d}'.format(config['address'],config['port']))
    server.bind((config['address'],config['port']))
    server.listen(8)
    server.settimeout(0.05) # timeout for listening
    # Some variables for status
    # Some variables for status
    try:
        dt_status = config['dt_status']
    except:
        dt_status = 2  # Send a status message every dtstatus seconds

    # Adding dt_status to get first status asap
    tstatus = time.time() - dt_status + 0.1
    npackets = 0 # Number packets received via the datainqueue
    clients = []
    try:
        queuesize = config['queuesize']
    except:
        queuesize = 1000

    FLAG_RUN = True
    while FLAG_RUN:
        try:
            client, address = server.accept() # Here the timeout will let the loop run with 20 Hz
            taccept = time.time()
            threadqueue = queue.Queue(maxsize=queuesize)
            tcp_thread = threading.Thread(target=handle_tcp_client_send, args=([client,address],threadqueue,statusqueue,config), daemon=True)
            tcp_thread.start()
            clients.append(client)
            thread_queue_dict = {'thread': tcp_thread, 'queue': threadqueue, 'address': address, 'bytes_sent': 0, 'packets_published': 0,
             'taccept': taccept}
            threadqueues.append(thread_queue_dict)
            if metadata_packet is not None:
                metadata_send = copy.deepcopy(metadata_packet)
                devinfo_all = metadata_send.pop('deviceinfo_all')
                metadata_tmp = devinfo_all['metadata']
                metadata_send['_metadata'] = {}
                raddr_tmp = redvypr_address.RedvyprAddress(metadata_packet,datakey='REMOTE')
                raddr_tmp_str = raddr_tmp.get_fullstr()
                raddr_tmp_str = raddr_tmp_str
                metadata_send['_metadata'][raddr_tmp_str] = metadata_tmp
                datab = packet_to_raw(metadata_send, config)
                q = thread_queue_dict
                q['queue'].put(datab)
                q['bytes_sent'] += len(datab)
                q['packets_published'] += 1


        except socket.timeout:
            pass
        except:
            logger.info(funcname + ':thread start: ',exc_info=True)
        
        while(datainqueue.empty() == False):
            try:
                data_dict = datainqueue.get(block=False)
                [command, comdata] = check_for_command(data_dict, thread_uuid=device_info['thread_uuid'],
                                                                    add_data=True)
                packet_address = redvypr_address.RedvyprAddress(data_dict)
                if (command is not None):
                    logger.debug('Command is for me: {:s}'.format(str(command)))
                    if(command == 'stop'):
                        logger.info(funcname + 'received command:' + str(data_dict) + ' stopping now')
                        logger.debug('Stop command')
                        for client in clients:
                            client.close()
                        server.close()
                        FLAG_RUN = False
                        break

                    if (command == 'info'):
                        logger.debug('Metadata command')
                        if packet_address.packetid == 'metadata':
                            metadata_packet = data_dict
                            metadata_update = True

                npackets += 1
                # Call the send_data function to create a binary sendable datastream
                datab = packet_to_raw(data_dict,config)
                #print('sending data',datab)
                for q in threadqueues:
                    q['queue'].put(datab)
                    q['bytes_sent'] += len(datab)
                    q['packets_published'] += 1

            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))



        # Sending a status message
        if((time.time() - tstatus) > dt_status):
            statusdata = {'npackets':npackets}
            tstatus = time.time()
            # Do a cleanup of the threads that are dead
            for q in threadqueues:
                isalive = q['thread'].is_alive() # This can be False or None if the thread is dead already
                if(isalive == False):
                    threadqueues.remove(q)
                
            statusdata['tcp_clients'] = []
            #statusdata['config'] = copy.deepcopy(config)
            for q in threadqueues:
                taccept_str = datetime.datetime.fromtimestamp(q['taccept'])
                client = {'bytes':q['bytes_sent'],'address':q['address'][0],'port':q['address'][1],'packets':q['packets_published'],'t_accept':taccept_str}
                statusdata['tcp_clients'].append(client)
                
            try:
                statusqueue.put_nowait(statusdata)
            except: # If the queue is full
                pass                

            
        
        
            
def start_tcp_recv(dataqueue, datainqueue, statusqueue, config=None, device_info=None):
    """ TCP receiving
    """
    funcname = __name__ + '.start_tcp_recv():'
    logger.debug(funcname + ':Starting network thread')        
    sentences = 0
    bytes_read = 0
    reconnections = 0
    threadqueues = []
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    logger.debug(funcname + ': Connecting to '+ str(config))
    client.settimeout(1.0) # timeout for listening
    try:
        client.connect((config['address'],config['port']))
    except Exception as e:
        logger.warning(funcname + ': Could not connect to host. {:s}'.format(str(e)))
        return
    
    client.settimeout(0.05) # timeout for listening
    
    # Some variables for status
    try:
        dt_status = config['dt_status']
    except:
        dt_status = 2 # Send a status message every dtstatus seconds

    # Adding dt_status to get first status asap
    tstatus = time.time() - dt_status + 0.1
    # Reconnecting to TCP Port if connection was closed by host
    try:
        config['tcp_reconnect']
    except:
        config['tcp_reconnect'] = True
        
    # The number of reconnection attempts before giving up
    try:
        config['tcp_numreconnect']
    except:
        config['tcp_numreconnect'] = 10
        
    # 
    npackets = 0 # Number packets received via the datainqueue
    datab_all = b''
    while True:
        try:
            com = datainqueue.get(block=False)
            [command, comdata] = check_for_command(com, thread_uuid=device_info['thread_uuid'],
                                                   add_data=True)
            if (command is not None):
                logger.debug(funcname + 'Command is for me: {:s}'.format(str(command)))
                if (command == 'stop'):
                    logger.info(funcname + 'received command:' + str(command) + ' stopping now')
                    client.close()
                    #FLAG_RUN = False
                    break
        except:
            pass

        try:
            datab = client.recv(1000000)
            if(datab == b''): # Connection closed
                logger.warning(funcname + ': Connection closed by host')
                if(config['tcp_reconnect']): # Try to reconnect
                    logger.warning(funcname + ': Reconnecting')
                    i = 0
                    while i < config['tcp_numreconnect']: # a couple of times with a 1 second interval
                        i = i + 1
                        try:
                            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            client.settimeout(1.0) # timeout for listening
                            client.connect((config['address'],config['port']))
                            reconnections += 1
                        except:
                            logger.warning(funcname + ': Could not connect to host.')
                            
                    logger.info(funcname + ': Connected to '+ str(config))
                    client.settimeout(0.05) # timeout for listening
                else:
                    logger.warning(funcname + ': Stopping thread')
                    client.close()
                    break

            bytes_read += len(datab)
            # Check what data we are expecting and convert it accordingly
            datab_all += datab
            tmp = raw_to_packet(datab_all, config, safe_load=False)
            packets = tmp['packets']
            datab_all = tmp['datab_rest'] # Store the rest
            for p in packets:
                ## Check if there is a deviceinfo command
                #command = check_for_command(p)
                #p_address=redvypr_address.RedvyprAddress(p)
                #if (command == 'info'):
                #    logger.debug('Metadata command')
                #    if p_address.packetid == 'metadata':

                #print(funcname + ' publishing packet',p)
                dataqueue.put(p)
                npackets += 1

        except socket.timeout as e:
            pass
        except:
            logger.info(funcname + ':',exc_info=True)
            return

        # Sending a status message
        if((time.time() - tstatus) > dt_status):
            statusdata = {}
            statusdata['bytes_read'] = bytes_read
            statusdata['time'] = str(datetime.datetime.now())
            statusdata['reconnections'] = reconnections
            tstatus = time.time()
            #statusdata['clients'] = []
            statusdata['config'] = copy.deepcopy(config)
                
            try:
                statusqueue.put_nowait(statusdata)
            except: # If the queue is full
                pass

def start_udp_send(dataqueue, datainqueue, statusqueue, config=None, device_info=None):
    """ UDP publishing
    """
    funcname = __name__ + '.start_udp_send()'
    logger.debug(funcname + ':Starting network thread')        
    sentences = 0
    bytes_sent = 0

    # Some variables for status
    tstatus = time.time()
    dt_status = 5 # Send a status message every dtstatus seconds
    npackets = 0 # Number packets received via the datainqueue
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) # UDP
    if(config['address'] == '<broadcast>'):
        #client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,  1)  # https://stackoverflow.com/questions/13637121/so-reuseport-is-not-defined-on-windows-7
        # Enable broadcasting mode
        client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Optional: reuse port if supported (multiple processes on same port)
        try:
            client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            print("SO_REUSEPORT enabled")
        except (AttributeError, OSError):
            print("SO_REUSEPORT not available on this system")
        #udp_addr = ""
        udp_addr = "255.255.255.255"
    else:
        udp_addr = config['address']

    client.settimeout(0.01) # timeout for listening, do we need that here??
    FLAG_RUN=True
    while FLAG_RUN:
        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data_dict = datainqueue.get(block=False)
                command = check_for_command(data_dict, thread_uuid=device_info['thread_uuid'])

                if (command is not None):
                    logger.debug(funcname + 'Command is for me: {:s}'.format(str(command)))
                    if (command == 'stop'):
                        logger.info(funcname + 'received command:' + str(command) + ' stopping now')
                        client.close()
                        udpaddrstr = str((udp_addr, config['port']))
                        statusdata = '{} Stopping UDP send thread to {}'.format(str(datetime.datetime.now()),udpaddrstr)
                        try:
                            statusqueue.put_nowait(statusdata)
                        except:  # If the queue is full
                            pass

                        FLAG_RUN = False
                        break
                else:
                    npackets   += 1
                    # Call the send_data function to create a binary sendable datastream
                    datab       = packet_to_raw(data_dict,config)
                    bytes_sent += len(datab)
                    #print('Sending data',datab,udp_addr,config['port'])
                    client.sendto(datab, (udp_addr, config['port']))


            except:
                logger.debug(funcname + ':Error', exc_info=True)



        # Sending a status message
        if((time.time() - tstatus) > dt_status):
            statusdata = {'npackets':npackets}
            statusdata['bytes_sent'] = bytes_sent
            statusdata['udp_address'] = str((udp_addr, config['port']))
            tstatus = time.time()
            #statusdata['clients'] = []
            #statusdata['config'] = copy.deepcopy(config)
            statussend = {}
            statussend['udp_publish'] = statusdata

            try:
                statusqueue.put_nowait(statussend)
            except: # If the queue is full
                pass
            


        
        
def start_udp_recv(dataqueue, datainqueue, statusqueue, config=None, device_info = None):
    """ UDP receiving
    """
    funcname = __name__ + '.start_udp_recv():'
    logger.debug(funcname + ':Starting network thread (uuid: {:s})'.format(device_info['thread_uuid']))
    npackets = 0
    bytes_read = 0
    threadqueues = []
    tstatus = 0
    dt_status = 2 # Send a status message every dtstatus seconds
    
    #client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) # UDP
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
    if(config['address'] == '<broadcast>'):
        # Optional: reuse port if supported (multiple processes on same port)
        try:
            client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            print("SO_REUSEPORT enabled")
        except (AttributeError, OSError):
            print("SO_REUSEPORT not available on this system")

        #client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1) # https://stackoverflow.com/questions/13637121/so-reuseport-is-not-defined-on-windows-7
        client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # https://stackoverflow.com/questions/13637121/so-reuseport-is-not-defined-on-windows-7
        # Enable broadcasting mode
        client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1) # Not really necessary
        udp_addr = ""
    else:
        udp_addr = config['address']
    client.settimeout(0.05) # timeout for listening
    logger.debug(funcname + 'Will bind to {:s} on port {:d}'.format(udp_addr,config['port']))
    client.bind((udp_addr,config['port']))
    datab_all = b''
    while True:
        try:
            com = datainqueue.get(block=False)
            command = check_for_command(com,thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command: {:s}'.format(str(com)))
            if (command is not None):
                if (command == 'stop'):
                    logger.debug('Command is for me: {:s}'.format(str(command)))
                    client.close()
                    logger.info(funcname + 'received command:' + str(com) + ' stopping now')
                    statusdata = {}
                    statusdata['status'] = 'Stopping UDP redcv thread'
                    statusdata['time'] = str(datetime.datetime.now())
                    try:
                        statusqueue.put_nowait(statusdata)
                    except:  # If the queue is full
                        pass

                    break

        except:
            pass

        try:
            datab, addr = client.recvfrom(1000000)
            #print('Got data',datab,addr)
            bytes_read += len(datab)
            t = time.time()
            # Check what data we are expecting and convert it accordingly
            datab_all += datab
            tmp = raw_to_packet(datab_all, config, safe_load=False)
            packets = tmp['packets']
            datab_all = tmp['datab_rest']
            for p in packets:
                dataqueue.put(p)
                npackets += 1

            #print(config)
            #print('UDP Received',datab)
            #print('UDP sent as',datan)
        except socket.timeout as e:
            pass
        except Exception as e:
            logger.info(funcname + ': Error: ' + str(e))
            logger.info(funcname + ': Will stop now')
            return


        # Sending a status message
        if((time.time() - tstatus) > dt_status):
            statusdata = {}
            statusdata['bytes_read'] = bytes_read
            statusdata['npackets'] = npackets
            statusdata['time'] = str(datetime.datetime.now())            
            tstatus = time.time()
            #statusdata['clients'] = []
            statusdata['config'] = copy.deepcopy(config)
                
            try:
                statusqueue.put_nowait(statusdata)
            except: # If the queue is full
                pass


    logger.info(funcname + ' stopped')



def start(device_info, config, dataqueue, datainqueue, statusqueue):
    """

    Args:
        device_info:
        config:
        dataqueue:
        datainqueue:
        statusqueue:

    Returns:

    """
    funcname = __name__ + '.start():'
    logger.debug(funcname + config['protocol'])
    if (config['address'].lower() == '<ip>'):
        ip = get_ip()
        logger.debug(funcname + ' Converting <IP> to {:s}'.format(ip))
        config['address'] = ip

    if(config['direction'] == 'publish'):
        if(config['protocol'] == 'tcp'):
            logger.info(__name__ + ':Start to serve data on address (TCP):' + str(config))
            start_tcp_send(dataqueue,datainqueue,statusqueue,config=config,device_info=device_info)
        elif(config['protocol'] == 'udp'):
            logger.info(__name__ + ':Start to serve data on address (UDP)' + str(config))
            #start_udp_send(dataqueue,datainqueue,statusqueue,config=config)
            start_udp_send(dataqueue, datainqueue, statusqueue, config=config,
                           device_info=device_info)
    elif(config['direction'] == 'receive'):
        if(config['protocol'] == 'tcp'):
            logger.info('Start to receive data from address (TCP):' + str(config))
            start_tcp_recv(dataqueue,datainqueue,statusqueue,config=config,device_info=device_info)
        elif(config['protocol'] == 'udp'):
            logger.info('Start to receive data from address (UDP):' + str(config))
            start_udp_recv(dataqueue,datainqueue,statusqueue,config=config,device_info=device_info)

class Device(RedvyprDevice):
    network_status_changed = QtCore.pyqtSignal()  # Signal notifying that the network status changed
    def __init__(self, **kwargs):
        """
        """
        super(Device, self).__init__(**kwargs)
        self.check_and_fill_config() # Add standard stuff
        # Could be done with a blocking thread, but lets keep it simple
        self.network_status = {}
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.get_status)  # Add to the timer another update
        self.statustimer.start(1000)

    def get_metadata(self, address, mode='merge'):
        """
        Gets the metadata of the redvypr address
        :param address:
        :return:
        """
        funcname = __name__ + '.get_metadata({},{}):'.format(str(address), str(mode))
        self.logger.debug(funcname)
        # Split the metadata into a remote and a local part
        metadata_local = {'metadata':copy.deepcopy(self.statistics['metadata'])}
        metadata_remote = {}
        metadata_remote_query = {}
        # Loop over all keys, check for REMOTE__ and loop over entries
        for metadatakey in self.statistics['metadata']:
            metadatakey_raddr = redvypr_address.RedvyprAddress(metadatakey)
            if 'REMOTE' in metadatakey_raddr.key():
                mtmp = metadata_local['metadata'].pop(metadatakey)
                #print('Mtmp',mtmp)
                #print('Mtmp keys', mtmp.keys())
                #print('Mtmp metadatakey', metadatakey)
                raddr_tmp = metadatakey_raddr
                remote_address_str = raddr_tmp.get_fullstr()
                metadata_remote[remote_address_str] = {}
                metadata_remote[remote_address_str]['metadata'] = mtmp
                self.logger.debug(funcname + 'Remote query ...')
                metadata_remote_query_tmp = packet_statistic.get_metadata_deviceinfo_all(metadata_remote[remote_address_str], address, mode=mode, publisher_strict=False)
                #print('Remote query',metadata_remote_query)
                metadata_remote_query.update(metadata_remote_query_tmp)

        metadata = packet_statistic.get_metadata(metadata_local, address, mode=mode)
        #print('Metadata (local)', metadata)
        if len(metadata.keys()) > 0:
            metadata_remote_query.update(metadata)

        return metadata_remote_query

    def check_and_fill_config(self):
        """ Fills a config, if essential entries are missing
        """
        try:
            self.custom_config.address
        except:
            self.configaddress = get_ip()


        if(self.custom_config.address == None):
            self.custom_config.address = get_ip()
        elif(self.custom_config.address == ''):
            self.custom_config.address = get_ip()
        elif(self.custom_config.address == '<ip>'):
            self.custom_config.address = get_ip()
        elif(self.custom_config.address == '<IP>'):
            self.custom_config.address = get_ip()
            
        try:
            self.custom_config.port
        except:
            self.custom_config.port = 18196
            
        try:
            self.custom_config.protocol
        except:
            self.custom_config.protocol = 'tcp'
        
        try:    
            self.custom_config.direction
        except:
            self.custom_config.direction = 'publish' # publish/receive
            
        try:
            self.custom_config.datakey
        except: 
            self.custom_config.datakey = 'data' #

        try:
            self.custom_config.serialize
        except:
            self.custom_config.serialize = 'raw' # yaml/str/raw

    def status(self):
        funcname = 'status()'
        # print('Status')
        try:
            status = self.statusqueue.get_nowait()
        except:
            return

        #if type(status) == str:
        #    print('Status', status)
        #else:
        #    print('Statusdict', status)

        return status

    def get_status(self):
        funcname = 'get_status()'
        #print('Status')
        while True:
            try:
                status = self.statusqueue.get_nowait()
            except:
                return

            if type(status) == str:
                #print('Status str',status)
                pass
            else:
                #print('Statusdict',status)
                self.network_status.update(status)
                self.network_status_changed.emit()

        #return statusstr
            

    def __str__(self):
        sstr = 'network device'
        return sstr



class initDeviceWidget(QtWidgets.QWidget):
    #device_start = QtCore.pyqtSignal(Device)
    #device_stop = QtCore.pyqtSignal(Device)
    connect      = QtCore.pyqtSignal(RedvyprDevice) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QFormLayout(self)
        self.device   = device
        self.device.check_and_fill_config() # Add standard stuff
        self.inputtabs = QtWidgets.QTabWidget() # Create tabs for different connection types
        self.serialwidget = QtWidgets.QWidget()
        self.label    = QtWidgets.QLabel("Network device")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet("font-weight: bold; font-size: 16")
        self.subbtn = QtWidgets.QPushButton("Subscribe")
        self.subbtn.clicked.connect(self.subscribe_clicked)

        self.startbtn = QtWidgets.QPushButton("Open device")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)

        self.config_widgets = [] # Collecting all config widgets here, makinf it easier to grey them out
        # Address and port
        self.addressline = QtWidgets.QLineEdit()
        self.addressline.setStatusTip('The IP Address, for UDP Broadcast use "<broadcast>", use <IP> for local network IP')
        myip = get_ip()
        addresses = ["<broadcast>", "<IP>", myip ]
        completer = QtWidgets.QCompleter(addresses)
        self.addressline.setCompleter(completer)
        self.portline = QtWidgets.QLineEdit()
        
            
        # Data direction
        self._combo_inout = QtWidgets.QComboBox()
        self._combo_inout.addItem('Publish')        
        self._combo_inout.addItem('Receive')

        
        # Data direction
        self._combo_proto = QtWidgets.QComboBox()
        self._combo_proto.addItem('TCP')        
        self._combo_proto.addItem('UDP')

        # Publish options
        # Create an array of radio buttons
        self._data_pub_all  = QtWidgets.QRadioButton("Redvypr YAML datapacket")
        self._data_pub_all.setStatusTip('Sends/Expects the whole datapacket as a YAML string')


        self._data_pub_dict = QtWidgets.QRadioButton("Dictionary entries")
        self._data_pub_dict.setStatusTip('Sends entries and serialize them as choosen by the serialization box')

        self._data_pub_group = QtWidgets.QButtonGroup()
        self._data_pub_group.addButton(self._data_pub_all)
        self._data_pub_group.addButton(self._data_pub_dict)

        self._data_pub_dict.setChecked(False)
        self._data_pub_all.setChecked(True)
        
        # Serialize
        self._combo_ser = QtWidgets.QComboBox()
        self._combo_ser.addItem('utf-8')
        self._combo_ser.addItem('raw')
        self._combo_ser.addItem('yaml')





        
        
        # Data format to submit
        self.fdataentry  = QtWidgets.QLabel("Data keys publish")        
        self.dataentry   = QtWidgets.QLineEdit()
        self.dataentry.setText('data')


        # The layout of all widgets    
        layout.addRow(self.label)        
        layout.addRow(QtWidgets.QLabel("Address"),self.addressline)  
        layout.addRow(QtWidgets.QLabel("Port"),self.portline)
        layout.addRow(QtWidgets.QLabel("Data direction"),self._combo_inout)
        layout.addRow(QtWidgets.QLabel("Protocol"),self._combo_proto)
        self._serialize_label = QtWidgets.QLabel("Data publishing options")
        layout.addRow(self._serialize_label)
        layout.addRow(self._data_pub_all,self._data_pub_dict)
        layout.addRow(QtWidgets.QLabel("Serialize"),self._combo_ser)
        layout.addRow(self.fdataentry,self.dataentry)
        layout.addRow(self.subbtn)
        layout.addRow(self.startbtn)
        
        self.config_widgets.append(self.addressline)
        self.config_widgets.append(self.portline)
        self.config_widgets.append(self._combo_inout)
        self.config_widgets.append(self._combo_proto)        
        self.config_widgets.append(self._data_pub_all)
        self.config_widgets.append(self._data_pub_dict)
        self.config_widgets.append(self._combo_ser)
        self.config_widgets.append(self.dataentry)

        self.config_to_buttons()
        self.process_options()
        self.connect_signals_options(connect=True)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def subscribe_clicked(self):
        button = self.sender()
        self.connect.emit(self.device)
    def connect_signals_options(self,connect=True):
        if True:
            if(connect):
                self._combo_inout.currentIndexChanged.connect(self.process_options)
                self._combo_proto.currentIndexChanged.connect(self.process_options)
                self._data_pub_all.toggled.connect(self.process_options)
                self._combo_ser.currentIndexChanged.connect(self.process_options)
            else:
                try:
                    self._combo_inout.currentIndexChanged.disconnect()
                    self._combo_proto.currentIndexChanged.disconnect()
                    self._data_pub_all.toggled.disconnect()
                    self._combo_ser.currentIndexChanged.disconnect()
                except:
                    pass

        
    def config_to_buttons(self):
        """ Update the configuration widgets according to the config dictionary in the device module 
        """
        #print('Config to buttons',self.device.config)

        # Disconnect all signals
        self.connect_signals_options(connect=False)
        if (self.device.custom_config.protocol == 'tcp'):
            self._combo_proto.setCurrentIndex(0)
        else:
            self._combo_proto.setCurrentIndex(1)

        if(self.device.custom_config.address is not None):
            self.addressline.setText(self.device.custom_config.address)
        if(self.device.custom_config.port is not None):
            self.portline.setText(str(self.device.custom_config.port))
            
        if(self.device.custom_config.direction == 'publish'):
            self._combo_inout.setCurrentIndex(0)
        else:
            self._combo_inout.setCurrentIndex(1)

        for i in range(self._combo_ser.count()):
            self._combo_ser.setCurrentIndex(i)
            txt = self._combo_ser.currentText()
            #print('txt',i,txt)
            if(txt.lower() == self.device.custom_config.serialize.lower()):
                #print('break')
                break

        if(self.device.custom_config.datakey.lower() == 'all'):
            self._data_pub_all.setChecked(True)
        else:
            self._data_pub_dict.setChecked(True)


        self.dataentry.setText(self.device.custom_config.datakey)
        self.connect_signals_options(connect=True)
            
    def process_options(self):
        """ Reads all options and creates a configuration dictionary
        """
        funcname = __name__ + '.process_options()'
        config   = {}
        logger.debug(funcname)
        config = self.device.custom_config
        config.address = self.addressline.text()
        config.direction = self._combo_inout.currentText().lower()
        config.protocol = self._combo_proto.currentText().lower()
        if(self._data_pub_all.isChecked()): # sending/receiving YAML dictionaries
            self.dataentry.setEnabled(False)
            self._combo_ser.setEnabled(False)
            config.serialize = 'yaml'
            config.datakey = 'all'
        else:
            self.dataentry.setEnabled(True)
            self._combo_ser.setEnabled(True)
            config.serialize = self._combo_ser.currentText().lower()
            config.datakey   = self.dataentry.text()

        # Change the GUI according to send/receive
        if(self._combo_inout.currentText() == 'Publish'):
            self._serialize_label.setText("Data publishing options")
            self.fdataentry.setText("Data key to publish")
        else:
            self._serialize_label.setText("Data receiving options")
            self.fdataentry.setText("Data key to receive")


        # Check for invalid combinations
        if((config.address.lower()) == '<broadcast>' and config.protocol == 'tcp'):
            logger.warning(funcname + ': Broadcast works only with UDP')

        try:
            config.port = int(self.portline.text())
        except:
            logger.warning(funcname + ': Port is not an int')


        self.device.custom_config = config
        logger.debug(funcname + ': config: ' + str(config))


    def thread_status(self,status):
        self.update_buttons(status['threadalive'])
        
    def update_buttons(self):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """

            status = self.device.get_thread_status()
            thread_status = status['thread_running']
            # Running
            if(thread_status):
                self.startbtn.setText('Stop')
                self.startbtn.setChecked(True)
                #for w in self.config_widgets:
                #    w.setEnabled(False)
            # Not running
            else:
                self.startbtn.setText('Start')
                #for w in self.config_widgets:
                #    w.setEnabled(True)
                    
                # Check if an error occured and the startbutton 
                if(self.startbtn.isChecked()):
                    self.startbtn.setChecked(False)
                #self.conbtn.setEnabled(True)

    def start_clicked(self):
        funcname = __name__ + '.start_clicked()'
        button = self.sender()
        if button.isChecked():
            try:
                self.process_options()
            except:
                logger.warning(funcname + ': Invalid settings')
                self.startbtn.setChecked(False)
                return

            # Setting the configuration
            self.device.thread_start()
            button.setText("Starting")
        else:
            logger.debug('Stopping thread now')
            self.device.thread_stop()
            button.setText("Stopping")

class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self, device=None, tabwidget=None):
        super().__init__()
        self.device = device
        self.layout = QtWidgets.QGridLayout(self)
        self.tabwidget = tabwidget
        #self.statuswidget_network = QtWidgets.QWidget()
        #self.tabwidget.addTab(self.statuswidget_network,'Network devices connected')
        self.statusdictWidget = dictQTreeWidget(self.device.network_status, dataname = 'network status')
        self.device.network_status_changed.connect(self.update_status)
        self.layout.addWidget(self.statusdictWidget)

    def update_status(self):
        """

        """
        status = self.device.network_status
        self.statusdictWidget.reload_data(status)
