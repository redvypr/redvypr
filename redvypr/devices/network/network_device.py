"""

network device

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
import socket
#from apt_pkg import config
import yaml
import copy
from redvypr.device import redvypr_device
from redvypr.data_packets import check_for_command

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('network_device')
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

def raw_to_packet(datab,config):
    """
    Packs the received raw data into a packet that can be sent via the dataqueue

    Args:
        datab:
        config:

    Returns:
        packets: A list of datapackets to be sent via the dataqueue

    """
    funcname = __name__ + '.raw_to_packet()'
    t = time.time()
    packets = []
    if(config['serialize'] == 'yaml'):
        for databs in datab.split(b'...\n'): # Split the text into single subpackets
            try:
                data = yaml.safe_load(databs)
            except Exception as e:
                logger.debug(funcname + ': Could not decode message {:s}'.format(str(data)))
                logger.debug(funcname + ': Could not decode message  with supposed format {:s} into something useful.'.format(config['data']))
            if(data is not None):
                if(config['data'] == 'all'): # Forward the whole message
                    packets.append(data)
                else:
                    datan = {'t':t}
                    datan[config['data']] = data[k]
                    packets.append(datan)

    elif (config['serialize'] == 'utf-8'):  # Put the "str" data into the packet with the key in "data"
        data = datab.decode('utf-8')
        datan = {'t':t}
        datan[config['data']] = data
        packets.append(datan)
    elif(config['serialize'] == 'raw'): # Put the "str" data into the packet with the key in "data"
        datan = {'t':t}
        datan[config['data']] = datab
        packets.append(datan)

    return packets

def packet_to_raw(data_dict,config):
    """ Function that processes the data_dict to a serialized datastream sendable over network connections 
    """
    funcname = __name__ + 'send_data()'
    #
    if (config['data'] == 'all') and (config['serialize'] == 'yaml'):
        datab = yaml_dump(data_dict).encode('utf-8')
    elif (config['serialize'] == 'utf-8'):
        key = config['data']
        datab = str(data_dict[key]).encode('utf-8')
    elif (config['serialize'] == 'raw'):
        key = config['data']
        data = data_dict[key]
        if(isinstance(data, (bytes, bytearray))):
            datab = data
        else:
            datab = str(data).encode('utf-8')

    return datab


def handle_tcp_client_send(client,threadqueue,statusqueue):
    funcname =  __name__ + 'handle_tcp_client_send()'
    address = client[1]
    client = client[0]
    statusstr = 'Sending data to (TCP):' + str(address)
    try:
        statusqueue.put_nowait(statusstr)
        logger.info(funcname + ':' + statusstr)
    except Exception as e:
        logger.warning(funcname + ':' + str(e))
    
    while True:
        data = threadqueue.get()
        #print('Read data from queue')
        try:
            logger.debug(funcname  + ':Sending data: {:s}'.format(str(data)))
            client.send(data)
        except Exception as e:
            statusstr = 'Connection to {:s} closed, stopping thread'.format(str(address))
            try:
                statusqueue.put_nowait(statusstr)
            except: # If the queue is full
                pass
            logger.info(funcname + ':' + statusstr)
            return

def start_tcp_send(dataqueue, datainqueue, statusqueue, config=None, device_info=None):
    """ TCP publishing, this thread waits for TCP connections connections. For each connection a new connection is created that is fed with a subthread (handle_tcp_send) is created that is receiving data with a new queue. 
    """
    funcname = __name__ + '.start_tcp_send()'
    logger.debug(funcname + ':Starting network thread')        
    npackets     = 0 # Number of packets
    bytes_read   = 0
    threadqueues = []
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((config['address'],config['port']))
    server.listen(8)
    server.settimeout(0.05) # timeout for listening
    # Some variables for status
    tstatus = time.time()
    dtstatus = 5 # Send a status message every dtstatus seconds
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
            threadqueue = queue.Queue(maxsize=queuesize)
            tcp_thread = threading.Thread(target=handle_tcp_client_send, args=([client,address],threadqueue,statusqueue), daemon=True)
            tcp_thread.start()
            clients.append(client)
            threadqueues.append({'thread':tcp_thread,'queue': threadqueue,'address':address,'bytes_sent':0,'packets_sent':0})
        except socket.timeout:
            pass
        except Exception as e:
            logger.info(funcname + ':thread start: ' + str(e))
        
        while(datainqueue.empty() == False):
            try:
                data_dict = datainqueue.get(block=False)
                command = check_for_command(data_dict, thread_uuid=device_info['thread_uuid'])
                if (command is not None):
                    logger.debug('Command is for me: {:s}'.format(str(command)))
                    for client in clients:
                        client.close()
                    server.close()
                    logger.info(funcname + 'received command:' + str(data_dict) + ' stopping now')
                    FLAG_RUN = False
                    break

                npackets += 1
                # Call the send_data function to create a binary sendable datastream
                datab      = packet_to_raw(data_dict,config)
                #print('sending data',datab)
                for q in threadqueues:
                    q['queue'].put(datab)
                    q['bytes_sent'] += len(datab)
                    q['packets_sent'] += 1

            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))



        # Sending a status message
        if((time.time() - tstatus) > dtstatus):
            statusdata = {'npackets':npackets}
            tstatus = time.time()
            # Do a cleanup of the threads that are dead
            for q in threadqueues:
                isalive = q['thread'].is_alive() # This can be False or None if the thread is dead already
                if(isalive == False):
                    threadqueues.remove(q)
                
            statusdata['clients'] = []
            statusdata['config'] = copy.deepcopy(config)
            for q in threadqueues:
                client = {'bytes':q['bytes_sent'],'address':q['address'][0],'port':q['address'][1],'packets':q['packets_sent']}
                statusdata['clients'].append(client)
                
            try:
                statusqueue.put_nowait(statusdata)
            except: # If the queue is full
                pass                

            
        
        
            
def start_tcp_recv(dataqueue, datainqueue, statusqueue, config=None, device_info=None):
    """ TCP receiving
    """
    funcname = __name__ + '.start_tcp_recv()'
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
    tstatus = time.time()
    try:
        dtstatus = config['dtstatus']
    except:
        dtstatus = 2 # Send a status message every dtstatus seconds
        
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
    while True:
        try:
            com = datainqueue.get(block=False)
            command = check_for_command(com, thread_uuid=device_info['thread_uuid'])
            print(funcname + ': Got command',com)
            if (command is not None):
                logger.debug('Command is for me: {:s}'.format(str(command)))
                client.close()
                logger.info(funcname + 'received command:' + str(com) + ' stopping now')
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
            packets = raw_to_packet(datab, config)
            for p in packets:
                dataqueue.put(p)
                npackets += 1

        except socket.timeout as e:
            pass
        except Exception as e:
            logger.info(funcname + ':' + str(e))
            return

        # Sending a status message
        if((time.time() - tstatus) > dtstatus):
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
    dtstatus = 5 # Send a status message every dtstatus seconds
    npackets = 0 # Number packets received via the datainqueue
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) # UDP
    if(config['address'] == '<broadcast>'):        
        client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        # Enable broadcasting mode
        client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    client.settimeout(0.01) # timeout for listening, do we need that here??
    FLAG_RUN=True
    while FLAG_RUN:
        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data_dict = datainqueue.get(block=False)
                command = check_for_command(data_dict, thread_uuid=device_info['thread_uuid'])
                if (command is not None):
                    logger.debug('Command is for me: {:s}'.format(str(command)))
                    client.close()
                    logger.info(funcname + 'received command:' + str(data_dict) + ' stopping now')
                    statusdata = {}
                    statusdata['status'] = 'Stopping UDP redcv thread'
                    statusdata['time'] = str(datetime.datetime.now())
                    try:
                        statusqueue.put_nowait(statusdata)
                    except:  # If the queue is full
                        pass

                    FLAG_RUN=False
                    break
                else:
                    npackets   += 1
                    # Call the send_data function to create a binary sendable datastream
                    datab       = packet_to_raw(data_dict,config)
                    bytes_sent += len(datab)
                    #print('Sending data',datab)
                    client.sendto(datab, (config['address'], config['port']))

            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))



        # Sending a status message
        if((time.time() - tstatus) > dtstatus):
            statusdata = {'npackets':npackets}
            statusdata['bytes_sent'] = bytes_sent
            tstatus = time.time()
            #statusdata['clients'] = []
            statusdata['config'] = copy.deepcopy(config)
                
            try:
                statusqueue.put_nowait(statusdata)
            except: # If the queue is full
                pass
            


        
        
def start_udp_recv(dataqueue, datainqueue, statusqueue, config=None, device_info = None):
    """ UDP receiving
    """
    funcname = __name__ + '.start_udp_recv():'
    logger.debug(funcname + ':Starting network thread (uuid: {:s})'.format(device_info['thread_uuid']))
    npackets     = 0
    bytes_read   = 0
    threadqueues = []
    tstatus      = 0
    dtstatus     = 2 # Send a status message every dtstatus seconds
    
    #client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) # UDP
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
    if(config['address'] == '<broadcast>'):
        client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        # Enable broadcasting mode
        client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    client.settimeout(0.05) # timeout for listening
    client.bind((config['address'],config['port']))
    while True:
        try:
            com = datainqueue.get(block=False)
            command = check_for_command(com,thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command: {:s}'.format(str(com)))
            if (command is not None):
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
            packets = raw_to_packet(datab, config)
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
        if((time.time() - tstatus) > dtstatus):
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

class Device(redvypr_device):
    def __init__(self, **kwargs):
        """
        """
        super(Device, self).__init__(**kwargs)
        self.publish = True
        self.subscribe = True
        self.description = 'network device'
        self.thread_communication = self.datainqueue  # Change the commandqueue to the datainqueue
        self.check_and_fill_config() # Add standard stuff
        
    def start(self, device_info, config, dataqueue, datainqueue, statusqueue):
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
        self.check_and_fill_config()
        logger.debug(funcname + self.config['protocol'])
        if(self.config['direction'] == 'publish'):
            if(self.config['protocol'] == 'tcp'):
                logger.info(__name__ + ':Start to serve data on address (TCP):' + str(self.config))
                start_tcp_send(self.dataqueue,self.datainqueue,self.statusqueue,config=self.config,device_info=device_info)
            elif(self.config['protocol'] == 'udp'):
                logger.info(__name__ + ':Start to serve data on address (UDP broadcast)')
                #start_udp_send(self.dataqueue,self.datainqueue,self.statusqueue,config=self.config)
                start_udp_send(self.dataqueue, self.datainqueue, self.statusqueue, config=self.config,
                               device_info=device_info)
        elif(self.config['direction'] == 'receive'):
            if(self.config['protocol'] == 'tcp'):
                logger.info('Start to receive data from address (TCP):' + str(self.config))
                start_tcp_recv(self.dataqueue,self.datainqueue,self.statusqueue,config=self.config,device_info=device_info)
            elif(self.config['protocol'] == 'udp'):
                logger.info('Start to receive data from address (UDP):' + str(self.config))
                start_udp_recv(self.dataqueue,self.datainqueue,self.statusqueue,config=self.config,device_info=device_info)
                
    
    def check_and_fill_config(self):
        """ Fills a config, if essential entries are missing
        """
        try:
            self.config['address']
        except:
            self.config['address'] = get_ip()


        if(self.config['address'] == None):
            self.config['address'] = get_ip()
        elif(self.config['address'] == ''):
            self.config['address'] = get_ip()
        elif(self.config['address'] == '<ip>'):
            self.config['address'] = get_ip()
        elif(self.config['address'] == '<IP>'):
            self.config['address'] = get_ip()                        
            
        try:
            self.config['port']
        except:
            self.config['port']=18196
            
        try:
            self.config['protocol']
        except:
            self.config['protocol'] = 'tcp'
        
        try:    
            self.config['direction']
        except:
            self.config['direction'] = 'publish' # publish/receive
            
        try:
            self.config['data']
        except: 
            self.config['data'] = 'data' #

        try:
            self.config['serialize']
        except:
            self.config['serialize'] = 'raw' # yaml/str/raw

    def status(self):
        funcname = 'status()'
        #print('Status')
        status = self.statusqueue.get_nowait()
        #print(statusstr)
        statusstr = yaml.dump(status)
        return statusstr
            

    def __str__(self):
        sstr = 'network device'
        return sstr



class initDeviceWidget(QtWidgets.QWidget):
    #device_start = QtCore.pyqtSignal(Device)
    #device_stop = QtCore.pyqtSignal(Device)
    connect      = QtCore.pyqtSignal(redvypr_device) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
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
        self._data_pub_all.setChecked(True)

        self._data_pub_dict = QtWidgets.QRadioButton("Dictionary entries")
        self._data_pub_dict.setStatusTip('Sends entries and serialize them as choosen by the serialization box')

        self._data_pub_group = QtWidgets.QButtonGroup()
        self._data_pub_group.addButton(self._data_pub_all)
        self._data_pub_group.addButton(self._data_pub_dict)
        
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
        if (self.device.config['protocol'] == 'tcp'):
            self._combo_proto.setCurrentIndex(0)
        else:
            self._combo_proto.setCurrentIndex(1)

        if(self.device.config['address'] is not None):
            self.addressline.setText(self.device.config['address'])
        if(self.device.config['port'] is not None):
            self.portline.setText(str(self.device.config['port']))
            
        if(self.device.config['direction'] == 'publish'):
            self._combo_inout.setCurrentIndex(0)
        else:
            self._combo_inout.setCurrentIndex(1)

        for i in range(self._combo_ser.count()):
            self._combo_ser.setCurrentIndex(i)
            txt = self._combo_ser.currentText()
            print('txt',i,txt)
            if(txt.lower() == self.device.config['serialize'].lower()):
                print('break')
                break

        if(self.device.config['serialize'].lower() == 'all'):
            self._data_pub_all.setChecked(True)
        else:
            self._data_pub_dict.setChecked(True)


        self.dataentry.setText(self.device.config['data'])
        self.connect_signals_options(connect=True)
            
    def process_options(self):
        """ Reads all options and creates a configuration dictionary
        """
        funcname = __name__ + '.process_options()'
        config   = {}
        print('Process options')

        config['address']   = self.addressline.text()
        config['direction'] = self._combo_inout.currentText().lower()
        config['protocol']  = self._combo_proto.currentText().lower()
        if(self._data_pub_all.isChecked()): # sending/receiving YAML dictionaries
            self.dataentry.setEnabled(False)
            self._combo_ser.setEnabled(False)
            config['serialize'] = 'yaml'
            config['data']      = 'all'
        else:
            self.dataentry.setEnabled(True)
            self._combo_ser.setEnabled(True)
            config['serialize'] = self._combo_ser.currentText().lower()
            config['data']      = self.dataentry.text()

        # Change the GUI according to send/receive
        if(self._combo_inout.currentText() == 'Publish'):
            self._serialize_label.setText("Data publishing options")
            self.fdataentry.setText("Data key to publish")
        else:
            self._serialize_label.setText("Data receiving options")
            self.fdataentry.setText("Data key to receive")


        # Check for invalid combinations
        if((config['address'].lower()) == '<broadcast>' and config['protocol'] == 'tcp'):
            logger.warning(funcname + ': Broadcast works only with UDP')

        try:
            config['port'] = int(self.portline.text())
        except:
            logger.warning(funcname + ': Port is not an int')


        self.device.config = config
        logger.debug(funcname + ': config: ' + str(config))
        return config

    def thread_status(self,status):
        self.update_buttons(status['threadalive'])
        
    def update_buttons(self):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """

            status = self.device.get_thread_status()
            thread_status = status['thread_status']
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
                config = self.process_options()
            except:
                logger.warning(funcname + ': Invalid settings')
                self.startbtn.setChecked(False)
                return

            if(config == None):
                self.startbtn.setChecked(False)
                return
            
            # Setting the configuration
            #print('Starting network with config',config)
            self.device.config = config
            self.device.thread_start()
            button.setText("Starting")
        else:
            logger.debug('Stopping thread now')
            self.device.thread_stop()
            button.setText("Stopping")




# class displayDeviceWidget(QtWidgets.QWidget):
#     def __init__(self):
#         super(QtWidgets.QWidget, self).__init__()
#         layout        = QtWidgets.QVBoxLayout(self)
#         hlayout        = QtWidgets.QHBoxLayout(self)
#         self.bytes_read = QtWidgets.QLabel('Bytes read: ')
#         self.lines_read = QtWidgets.QLabel('Lines read: ')
#         self.text     = QtWidgets.QPlainTextEdit(self)
#         self.text.setReadOnly(True)
#         self.text.setMaximumBlockCount(10000)
#         hlayoutv.addWidget(self.bytes_read)
#         hlayout.addWidget(self.lines_read)
#         layout.addLayout(hlayout)
#         layout.addWidget(self.text)
#
#     def update(self,data):
#         #print('data',data)
#         bstr = "Bytes read: {:d}".format(data['bytes_read'])
#         lstr = "Lines read: {:d}".format(data['nmea_sentences_read'])
#         self.bytes_read.setText(bstr)
#         self.lines_read.setText(lstr)
#         self.text.insertPlainText(str(data['nmea']))
        
