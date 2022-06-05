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


def send_data(data_dict,config):
    """ Function that processes the data_dict to a serialized datastream sendable over network connections 
    """
    funcname = __name__ + 'send_data()'

    # Choose the serialize function
    if(config['serialize'] == 'str'):
        serialize = str 
    elif(config['serialize'] == 'yaml'):
        serialize = yaml_dump # A dump with options
        
    # 
    if(config['data'][0] == 'all'):
        datab = serialize(data_dict).encode('utf-8')
    else:
        if(type(config['data']) == str):
            config['data'] = [config['data']]
            
        datab = b''
        for key in config['data']:
            datab += serialize(data_dict[key]).encode('utf-8')

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
            #logger.debug(funcname  + ':Sending data: {:s}'.format(str(data)))
            client.send(data)
        except Exception as e:
            statusstr = 'Connection to {:s} closed, stopping thread'.format(str(address))
            try:
                statusqueue.put_nowait(statusstr)
            except: # If the queue is full
                pass
            logger.info(funcname + ':' + statusstr)
            return
        

def start_tcp_send(dataqueue, datainqueue, comqueue, statusqueue, config=None):
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
            
    while True:
        try:
            com = comqueue.get(block=False)
            logger.info(funcname + 'received command:' + str(com) + ' stopping now')
            server.close()            
            break
        except:
            pass

        try:        
            client, address = server.accept() # Here the timeout will let the loop run with 20 Hz
            threadqueue = queue.Queue()
            tcp_thread = threading.Thread(target=handle_tcp_client_send, args=([client,address],threadqueue,statusqueue))
            tcp_thread.start()
            threadqueues.append({'thread':tcp_thread,'queue': threadqueue,'address':address,'bytes_sent':0,'packets_sent':0})
        except socket.timeout:
            pass
        except Exception as e:
            logger.info(funcname + ':thread start: ' + str(e))
        
        while(datainqueue.empty() == False):
            try:
                data_dict = datainqueue.get(block=False)
                npackets += 1
                # Call the send_data function to create a binary sendable datastream
                datab      = send_data(data_dict,config)
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

            
        
        
            
def start_tcp_recv(dataqueue, datainqueue, comqueue, statusqueue, config=None):
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
            com = comqueue.get(block=False)
            logger.debug('received command:' + str(com) + ' stopping now')
            client.close()            
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
                            
                    return
                    
                    logger.info(funcname + ': Connected to '+ str(config))
                    client.settimeout(0.05) # timeout for listening
                else:
                    logger.warning(funcname + ': Stopping thread')
                    client.close()
                    break
            
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

                    if(data is not None):
                        if(config['data'][0] == 'all'): # Forward the whole message
                            dataqueue.put(data)
                        else:
                            datan = {'t':t}
                            for k in config['data']: # List of keys
                                datan[k] = data[k]

                            dataqueue.put(datan)
            else: # Put the "str" data into the packet with the key in "data"
                data = datab.decode('utf-8')
                datan = {'t':t}
                datan['data'] = data
                dataqueue.put(datan)
            
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
        



def start_udp_send(dataqueue, datainqueue, comqueue, statusqueue, config=None):
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
    client.settimeout(0.01) # timeout for listening

    while True:
        try:
            com = comqueue.get(block=False)
            logger.info(funcname + 'received command:' + str(com) + ' stopping now')
            client.close()            
            break
        except:
            pass

        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data_dict = datainqueue.get(block=False)
                npackets += 1
                # Call the send_data function to create a binary sendable datastream
                datab      = send_data(data_dict,config)
                bytes_sent += len(datab)
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
            


        
        
def start_udp_recv(dataqueue, datainqueue, comqueue, statusqueue, config=None):
    """ UDP receiving
    """
    funcname = __name__ + '.start_udp_recv():'
    logger.debug(funcname + ':Starting network thread')        
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
            com = comqueue.get(block=False)
            client.close()            
            logger.info(funcname + 'received command:' + str(com) + ' stopping now')
            statusdata = {}
            statusdata['status'] = 'Stopping UDP redcv thread'
            statusdata['time'] = str(datetime.datetime.now())
            try:
                statusqueue.put_nowait(statusdata)
            except: # If the queue is full
                pass            

            break
        except:
            pass

        try:
            datab, addr = client.recvfrom(1000000)
            bytes_read += len(datab)
            t = time.time()
            # Check what data we are expecting and convert it accordingly
            if(config['serialize'] == 'yaml'):
                for databs in datab.split(b'...\n'): # Split the text into single subpackets                
                    try:
                        data = yaml.safe_load(databs)
                    except Exception as e:
                        logger.debug(funcname + ': Could not decode message {:s}'.format(str(data)))
                        logger.debug(funcname + ': Could not decode message  with supposed format {:s} into something useful.'.format(config['data']))
                    if(data is not None):                    
                        if(config['data'][0] == 'all'): # Forward the whole message
                            dataqueue.put(data)
                        else:
                            datan = {'t':t}
                            for k in config['data']: # List of keys
                                datan[k] = data[k]

                            dataqueue.put(datan)
                            npackets += 1
            else: # Put the "str" data into the packet with the key in "data"
                data = datab.decode('utf-8')
                datan = {'t':t}
                datan['data'] = data
                dataqueue.put(datan)
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

class Device():
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None,statusqueue=None):
        """
        """
        self.publish     = False # publishes data, a typical device is doing this
        self.subscribe   = False  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.statusqueue = statusqueue
        self.config = {}
        self.check_and_fill_config() # Add standard stuff
        
    def thread_status(self,status):
        """ Function that is called by redvypr, allowing to update the status of the device according to the thread 
        """
        self.threadalive = status['threadalive']

    def start(self):
        funcname = __name__ + '.start():'
        self.check_and_fill_config()
        logger.debug(funcname + self.config['protocol'])
        if(self.config['direction'] == 'publish'):
            if(self.config['protocol'] == 'tcp'):
                logger.info(__name__ + ':Start to serve data on address (TCP):' + str(self.config))
                start_tcp_send(self.dataqueue,self.datainqueue,self.comqueue,self.statusqueue,config=self.config)
            elif(self.config['protocol'] == 'udp'):
                logger.info(__name__ + ':Start to serve data on address (UDP broadcast)')
                start_udp_send(self.dataqueue,self.datainqueue,self.comqueue,self.statusqueue,config=self.config)                
        elif(self.config['direction'] == 'receive'):
            if(self.config['protocol'] == 'tcp'):
                logger.info('Start to receive data from address (TCP):' + str(self.config))
                start_tcp_recv(self.dataqueue,self.datainqueue,self.comqueue,self.statusqueue,config=self.config)
            elif(self.config['protocol'] == 'udp'):
                logger.info('Start to receive data from address (UDP):' + str(self.config))
                start_udp_recv(self.dataqueue,self.datainqueue,self.comqueue,self.statusqueue,config=self.config)
                
    
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
            self.config['data'] = ['all'] # "all" for the whole dictionary, comma separated "keys" for parts of the dictionary

        # Make a list out of a string
        if(self.config['data'] == 'all'):
            self.config['data'] = ['all']
            
        try:
            self.config['serialize']
        except:
            self.config['serialize'] = 'yaml' # yaml/str

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
    device_start = QtCore.pyqtSignal(Device)
    device_stop = QtCore.pyqtSignal(Device)        
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
        self._combo_inout.currentIndexChanged.connect(self.process_options)
        
        # Data direction
        self._combo_proto = QtWidgets.QComboBox()
        self._combo_proto.addItem('TCP')        
        self._combo_proto.addItem('UDP')
        self._combo_proto.currentIndexChanged.connect(self.process_options)
        
        
        # Publish options
        # Create an array of radio buttons
        self._data_pub_all  = QtWidgets.QRadioButton("Whole dictionary")
        self._data_pub_all.setStatusTip('Serializes the whole dictionary into a string using YAML')
        self._data_pub_all.setChecked(True)
        self._data_pub_dict = QtWidgets.QRadioButton("Dictionary entries")
        self._data_pub_dict.setStatusTip('Choose entries of the dictionary and serialize them as utf-8 string or yaml')
        
        self._data_pub_group = QtWidgets.QButtonGroup()
        self._data_pub_group.addButton(self._data_pub_all)
        self._data_pub_group.addButton(self._data_pub_dict)
        
        # Serialize
        self._combo_ser = QtWidgets.QComboBox()
        self._combo_ser.addItem('str')
        self._combo_ser.addItem('YAML')
        
        
        
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
        
    def config_to_buttons(self):
        """ Update the configuration widgets according to the config dictionary in the device module 
        """
        print('Config to buttons',self.device.config)
        if(self.device.config['address'] is not None):
            self.addressline.setText(self.device.config['address'])
        if(self.device.config['port'] is not None):
            self.portline.setText(str(self.device.config['port']))
            
        if(self.device.config['direction'] == 'publish'):
            self._combo_inout.setCurrentIndex(0)
        else:
            self._combo_inout.setCurrentIndex(1)
            
        if(self.device.config['protocol'] == 'tcp'):
            self._combo_proto.setCurrentIndex(0)
        else:
            self._combo_proto.setCurrentIndex(1)
            
        if(self.device.config['serialize'] == 'yaml'):
            self._combo_ser.setCurrentIndex(0)
        else:
            self._combo_ser.setCurrentIndex(1)
            
        if(self.device.config['data'][0] == ['all']):
            self._data_pub_all.setChecked(True)   
        else:
            self._data_pub_dict.setChecked(True)
            txt = ''
            for d in self.device.config['data']:
                txt += d + ','

            txt = txt[:-1]
            self.dataentry.setText(txt)
            
            
    def process_options(self):
        """ Reads all options and creates a configuration dictionary
        """
        funcname = __name__ + '.process_options()'
        config   = {}
        
        # Change the GUI according to send/receive
        if(self._combo_inout.currentText() == 'Publish'):
            self._serialize_label.setText("Data publishing options")
            self.dataentry.setEnabled(True)
        else:  
            self._serialize_label.setText("Data receiving options")
            #self._combo_ser.setCurrentIndex(0)
            self._data_pub_all.setChecked(True)
            self.dataentry.setEnabled(False)
         
        if(self._combo_inout.currentText() == 'Publish'):
            config['direction'] = 'publish'
            self.device.publish   = False
            self.device.subscribe = True
        else:
            config['direction'] = 'receive'
            self.device.publish   = True
            self.device.subscribe = False

        if(self._combo_proto.currentText() == 'TCP'):
            config['protocol'] = 'tcp'
        else:
            config['protocol'] = 'udp'
    
        config['address'] = self.addressline.text()
        # Check for invalid combinations
        if((config['address'].lower()) == '<broadcast>' and config['protocol'] == 'tcp'):
            logger.warning(funcname + ': Broadcast works only with UDP')
            config = None
            return config
        
        try:
            config['port'] = int(self.portline.text())
        except:
            logger.warning(funcname + ': Port is not an int')
            raise ValueError
        
        if(self._data_pub_all.isChecked()):
            config['data'] = ['all']
        else:
            config['data'] = self.dataentry.text().split(',')
        
        config['serialize'] = self._combo_ser.currentText().lower()
                    
        
        logger.debug(funcname + ': config: ' + str(config))    
        return config
    
    def thread_status(self,status):
        self.update_buttons(status['threadalive'])
        
    def update_buttons(self,thread_status):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """
            # Running
            if(thread_status):
                self.startbtn.setText('Stop')
                self.startbtn.setChecked(True)
                for w in self.config_widgets:
                    w.setEnabled(False)
            # Not running
            else:
                self.startbtn.setText('Start')
                for w in self.config_widgets:
                    w.setEnabled(True)
                    
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
            print('Starting network with config',config)
            self.device.config = config
            self.device_start.emit(self.device)
            print('Config',config)
            button.setText("Starting")
        else:
            self.device_stop.emit(self.device)
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
        
