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


zmq_context = zmq.Context()



logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('zeromq_device')
logger.setLevel(logging.DEBUG)

description = 'Connects to zeromq datastreams'

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


def start_send(dataqueue, datainqueue, comqueue, statusqueue, config=None):
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

            
        
        
            
def start_recv(dataqueue, datainqueue, statusqueue, config=None):
    """ zeromq receiving data
    """
    funcname = __name__ + '.start_recv()'

    sub = zmq_context.socket(zmq.SUB)
    url = 'tcp://' + config['address'] + ':' + str(config['port'])
    logger.debug(funcname + ':Start receiving data from url {:s}'.format(url))
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
            com = datainqueue.get(block=False)
            logger.debug('received command:' + str(com) + ' stopping now')
            client.close()            
            break
        except:
            pass

        try:
            datab = sub.recv(zmq.NOBLOCK)
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
                dataqueue.put(datan)
                datapackets += 1

        except Exception as e:
            pass
            #logger.info(funcname + ':' + str(e))
            #return

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
        


class Device(redvypr_device):
    def __init__(self,**kwargs):
        """
        """
        super(Device, self).__init__(**kwargs)
        self.publish     = True
        self.subscribe   = False
        self.description = 'zeromq'
        self.config = {}
        self.check_and_fill_config() # Add standard stuff
        
    def thread_status(self,status):
        """ Function that is called by redvypr, allowing to update the status of the device according to the thread 
        """
        self.threadalive = status['threadalive']

    def start(self):
        funcname = __name__ + '.start():'
        self.check_and_fill_config()
        logger.debug(funcname)
        if(self.config['direction'] == 'publish'):
            logger.info(__name__ + ':Start to serve data on address:' + str(self.config))
            start_send(self.dataqueue,self.datainqueue,self.statusqueue,config=self.config)
        elif(self.config['direction'] == 'receive'):
            logger.info('Start to receive data from address:' + str(self.config))
            start_recv(self.dataqueue,self.datainqueue,self.statusqueue,config=self.config)

    
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
            self.config['direction']
        except:
            self.config['direction'] = 'publish' # publish/receive
            
        try:
            self.config['data']
        except: 
            self.config['data'] = 'data' # "all" for the whole dictionary, comma separated "keys" for parts of the dictionary

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
        sstr = 'zeromq device'
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
        self.label    = QtWidgets.QLabel("Zeromq device")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet("font-weight: bold; font-size: 16")
        self.startbtn = QtWidgets.QPushButton("Open device")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)
        self.config_widgets = [] # Collecting all config widgets here, makinf it easier to grey them out
        # Address and port
        self.addressline = QtWidgets.QLineEdit()
        self.addressline.setStatusTip('The IP Address, use <IP> for local network IP')
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
        
        # Create an array of radio buttons for yaml/key choice
        self._data_yaml  = QtWidgets.QRadioButton("redvypr YAML message")
        self._data_yaml.setStatusTip('redvypr YAML message')
        self._data_yaml.setChecked(True)
        self._data_dict = QtWidgets.QRadioButton("Data ist stored in key")
        self._data_dict.setStatusTip('Choose entries of the dictionary and serialize them as utf-8 string or yaml')
        
        self._data_pub_group = QtWidgets.QButtonGroup()
        self._data_pub_group.addButton(self._data_yaml)
        self._data_pub_group.addButton(self._data_dict)
        
        # Data format to submit
        self.fdataentry  = QtWidgets.QLabel("Key for storage of received data")
        self.dataentry   = QtWidgets.QLineEdit()
        self.dataentry.setText('data')
        # The layout of all widgets
        layout.addRow(self.label)
        layout.addRow(QtWidgets.QLabel("Address"), self.addressline)
        layout.addRow(QtWidgets.QLabel("Port"),self.portline)
        layout.addRow(QtWidgets.QLabel("Data direction"),self._combo_inout)
        self._serialize_label = QtWidgets.QLabel("Data publishing options")
        layout.addRow(self._serialize_label)
        layout.addRow(self._data_yaml,self._data_dict)
        layout.addRow(self.fdataentry,self.dataentry)
        layout.addRow(self.startbtn)
        
        self.config_widgets.append(self.addressline)
        self.config_widgets.append(self.portline)
        self.config_widgets.append(self._combo_inout)
        self.config_widgets.append(self._data_yaml)
        self.config_widgets.append(self._data_dict)
        self.config_widgets.append(self.dataentry)

        self.config_to_buttons()
        self.process_options()
        
    def config_to_buttons(self):
        """ Update the configuration widgets according to the config dictionary in the device module 
        """
        funcname = __name__ + '.config_to_buttons()'
        logger.debug(funcname)
        if(self.device.config['address'] is not None):
            self.addressline.setText(self.device.config['address'])
        if (self.device.config['port'] is not None):
            self.portline.setText(str(self.device.config['port']))

        if(self.device.config['serialize'] == 'yaml'):
                self._data_yaml.setChecked(True)

        if(self.device.config['direction'] == 'publish'):
            self._combo_inout.setCurrentIndex(0)
        else:
            self._combo_inout.setCurrentIndex(1)
            
        if True:
            self._data_dict.setChecked(True)
            txt = self.device.config['data']
            self.dataentry.setText(txt)
            
            
    def process_options(self):
        """ Reads all options and creates a configuration dictionary
        """
        funcname = __name__ + '.process_options()'
        config   = {}
        
        # Change the GUI according to send/receive
        if(self._combo_inout.currentText() == 'Publish'):
            self._serialize_label.setText("Data publishing options")
            self.dataentry.setEnabled(False)
        else:  
            self._serialize_label.setText("Data receiving options")
            #self._combo_ser.setCurrentIndex(0)
            #self._data_yaml.setChecked(True)
            self.dataentry.setEnabled(True)

        if(self._data_yaml.isChecked()):
            config['serialize'] = 'yaml'
        else:
            config['serialize'] = 'str'
         
        if(self._combo_inout.currentText() == 'Publish'):
            config['direction'] = 'publish'
            self.device.publish   = False
            self.device.subscribe = True
        else:
            config['direction'] = 'receive'
            self.device.publish   = True
            self.device.subscribe = False

        config['address'] = self.addressline.text()
        try:
            config['port'] = int(self.portline.text())
        except:
            logger.warning(funcname + ': Port is not an int')
            raise ValueError
        
        config['data'] = self.dataentry.text()

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
            self.device.config = config
            self.device_start.emit(self.device)
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
        
