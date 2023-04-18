"""

zeromq device

Configuration options for a network device:

.. code-block::

- devicemodulename: network_device  
  deviceconfig:
    name: tcpserial1 # The name, must be unique
    config:
       address: <ip> # Address IP, localhost. <broadcast> for UDP broadcast in local network. <ip> for local ip
       port: 10001 # Port
       serialize: str # yaml,str default yaml
       protocol: tcp # tcp, udp default tcp
       direction: publish # publish, receive default receive
       data: nmea # dictionary keys, default all
       tcp_reconnect: True # Try to reconnect to host if connection was closed
       tcp_numreconnect: 10 # The number of reconnection attempts
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
from redvypr.device import redvypr_device
from redvypr.data_packets import check_for_command



zmq_context = zmq.Context()
description = 'Send or reveives data via a zeromq PUB/SUB socket'

config_template = {}
config_template['name']      = 'zeromq'
config_template['address']   = {'type': 'str','default':'127.0.0.1'}
config_template['port']      = {'type': 'int','default':18196,'range':[0,65535]}
config_template['direction'] = {'type': 'str', 'options': ['receive', 'publish'],'default':'receive'}
config_template['data']      = {'type': 'str','default':'data'}
config_template['serialize'] = {'type': 'str', 'options': ['yaml', 'str'],'default':'yaml'}
config_template['redvypr_device'] = {}
config_template['redvypr_device']['publishes']   = True
config_template['redvypr_device']['subscribes'] = False
config_template['redvypr_device']['description'] = description


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('zeromq_device')
logger.setLevel(logging.DEBUG)



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


def start_send(dataqueue, datainqueue, statusqueue, config=None):
    """ zeromq publishing.
    """
    funcname = __name__ + '.start_send()'
    logger.debug(funcname + ':Starting zeromq send thread')
    npackets     = 0 # Number of packets
    bytes_read   = 0

    pub = zmq_context.socket(zmq.PUB)
    url = 'tcp://' + config['address'] + ':' + str(config['port'])
    logger.debug(funcname + ':Start receiving data from url {:s}'.format(url))
    pub.connect(url)

    # Some variables for status
    tstatus    = time.time()
    dtstatus   = 5 # Send a status message every dtstatus seconds
    npackets   = 0  # Number packets received via the datainqueue
    bytes_sent = 0  # Number packets received via the datainqueue

    if(config['serialize'] == 'str'):
        serialize = str
    elif (config['serialize'] == 'yaml'):
        serialize = yaml_dump #
    elif (config['serialize'] == 'raw'):
        serialize = rawcopy  #
    else:
        serialize = yaml_dump #
            
    while True:
        if True:
            data = datainqueue.get()
            command = check_for_command(data)
            if(command is not None):
                logger.debug('Got a command', command)
                break

        npackets += 1
        # Call the send_data function to create a binary sendable datastream

        #
        if (config['data'][0] == 'all'):
            datab = serialize(data_dict).encode('utf-8')
        else:
            if (type(config['data']) == str):
                config['data'] = [config['data']]

            datab = b''
            for key in config['data']:
                datab += serialize(data_dict[key]).encode('utf-8')
        datab      = send_data(data,config)
        pub.send(datab)
        bytes_sent += len(datab)

        # Sending a status message
        if((time.time() - tstatus) > dtstatus):
            statusdata = {'npackets':npackets}
            statusdata['bytes_sent'] = bytes_sent
            tstatus = time.time()
            try:
                statusqueue.put_nowait(statusdata)
            except: # If the queue is full
                pass


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
    if (config['direction'] == 'publish'):
        logger.info(__name__ + ':Start to serve data on address:' + str(config))
        # start_send(self.dataqueue,self.datainqueue,self.statusqueue,config=self.config)
    elif (config['direction'] == 'receive'):
        logger.info('Start to receive data from address:' + str(config))
        start_recv(dataqueue, datainqueue, statusqueue, config=config, device_info=device_info)
        



