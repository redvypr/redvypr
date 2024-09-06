Design
======


Dataflow and addressing
-----------------------

Each redvypr instance has a hostinfo dictionary the is created with ``create_hostinfo(hostname=...)``::

    import redvypr
    hostinfo = redvypr.create_hostinfo(hostname='someredvypr')
    r = redvypr.Redvypr(hostname='otherredvypr')
    print('Hostinfo',hostinfo)
    print('Hostinfo redvypr',r.hostinfo)

gives as result::

   Hostinfo {'hostname': 'someredvypr', 'tstart': 1723380212.3953316, 'addr': '192.168.178.157', 'uuid': '118902019882015-126'}
   Hostinfo redvypr {'hostname': 'otherredvypr', 'tstart': 1723380212.3956072, 'addr': '192.168.178.157', 'uuid': '118902019882015-250'}
Devices added to redvypr have a unique `name`, if more than one device of the same kind is added, redvypr automatically changes the name if necessary::

   import redvypr
   r = redvypr.Redvypr(hostname='otherredvypr')
   # Add the first device
   r.add_device('redvypr.devices.test.test_device')
   # Add the second device of the same kind
   r.add_device('redvypr.devices.test.test_device')
   print('Device 0 name',r.devices[0]['device'].name)
   print('Device 1 name',r.devices[1]['device'].name)
yields::

   Device 0 name test_device
   Device 1 name test_device_1
This information is the base to identify a datapacket. In the following a number is published by a device, typically in the `start()` function::


   import redvypr
   import time
   r = redvypr.Redvypr(hostname='otherredvypr')
   # Add a data sending device
   r1 = r.add_device('redvypr.devices.test.test_device_bare')
   # Add a receiving device
   r2 = r.add_device('redvypr.devices.test.test_device_receive')
   r2.subscribe_address('*')
   # Clean the queue first
   print('Cleaning the queue')
   while True:
      time.sleep(0.2)
      try:
          data = r2.datainqueue.get(block=False)
          print('Got data (mostly information)',data)
      except:
          break

   print('Sending some important data')
   r1.dataqueue.put(3.1415)
   print('Wait for the data to be received by the second device')
   data = r2.datainqueue.get(block=True)
   print('Got data from r1\n',data)
The last statement shows a dictionary of the form::

   Got data from r1
   {'data': 3.1415, '_redvypr': {'tag': {'118902019882015-047': 1}, 'device': 'test_device_bare',
    'packetid': 'test_device_bare', 'host': {'hostname': 'otherredvypr', 'tstart': 1723435291.4256065,
     'addr': '192.168.178.157', 'uuid': '118902019882015-047'},
     'localhost': {'hostname': 'otherredvypr', 'tstart': 1723435291.4256065, 'addr': '192.168.178.157',
     'uuid': '118902019882015-047'}, 'publisher': 'test_device_bare', 't': 1723435292.030152,
     'devicemodulename': 'redvypr.devices.test.test_device_bare', 'numpacket': 5},
     't': 1723435292.030152}
Out of a simple number a dictionary was created, which are called datapackets. Creating and dealing with datapackets
is one of the major tasks of redvypr.
A redvypr packet can be received and sent by another redvypr instance::

   import redvypr
   import time
   r = redvypr.Redvypr(hostname='veryotherredvypr')
   # Add a data sending device
   r1 = r.add_device('redvypr.devices.test.test_device_bare')
   # Add a receiving device
   r2 = r.add_device('redvypr.devices.test.test_device_receive')
   r2.subscribe_address('*')
   # Clean the queue first
   print('Cleaning the queue')
   while True:
       time.sleep(0.2)
       try:
           data = r2.datainqueue.get(block=False)
           print('Got data (mostly information)',data)
       except:
           break

   print('Sending some important data')
   data = {'data': 3.1415, '_redvypr': {'tag': {'118902019882015-047': 1}, 'device': 'test_device_bare',
    'packetid': 'test_device_bare', 'host': {'hostname': 'otherredvypr', 'tstart': 1723435291.4256065,
     'addr': '192.168.178.157', 'uuid': '118902019882015-047'},
     'localhost': {'hostname': 'otherredvypr', 'tstart': 1723435291.4256065, 'addr': '192.168.178.157',
     'uuid': '118902019882015-047'}, 'publisher': 'test_device_bare', 't': 1723435292.030152,
     'devicemodulename': 'redvypr.devices.test.test_device_bare', 'numpacket': 5}, 't': 1723435292.030152}
   r1.dataqueue.put(data)
   print('Wait for the data to be received by the second device')
   data = r2.datainqueue.get(block=True)
   print('Got data from r1\n',data)


The result is a very similar datapacket, with a new entry called `localhost`::

   {'data': 3.1415, '_redvypr': {'tag': {'118902019882015-047': 1, '118902019882015-197': 1},
   'device': 'test_device_bare', 'packetid': 'test_device_bare',
   'host': {'hostname': 'otherredvypr', 'tstart': 1723435291.4256065, 'addr': '192.168.178.157',
   'uuid': '118902019882015-047'},
   'localhost': {'hostname': 'veryotherredvypr', 'tstart': 1723437492.1021655, 'addr': '192.168.178.157',
   'uuid': '118902019882015-197'}, 'publisher': 'test_device_bare', 't': 1723435292.030152,
   'devicemodulename': 'redvypr.devices.test.test_device_bare', 'numpacket': 5},
   't': 1723435292.030152}
Addressing the data within Python is easy if the data packet isfor example in the variable called `data`::

   pi = data['data']
RedvyprAddress
--------------
But how to address a certain data packet from a certain redvypr instance? This is done with a RedvyprAddress::

   from redvypr.redvypr_address import RedvyprAddress
   raddr = RedvyprAddress('*')


They allow to filter datapackets based on for example the redvypr host, the sending device, available datakeys or the packetid.
The `address entries` for filtering datapackets are formatted by a slash ``/`` the entryname a ``:`` and the value, for example
for the hostname::

  raddr1 = RedvyprAddress('/h:someredvypr')
  raddr2 = RedvyprAddress('/h:someotherredvypr')
Now a datapacket can be checked using the ``in`` keyword::

  print('data in raddr1',data in raddr1)
  print('data in raddr2',data in raddr2)

gives::

  data in raddr1 True
  data in raddr2 False


Below a table of all address entries.

.. table:: Truth table for "not"
   :widths: auto

   ===================  =============  =======
   Address entry short  Address entry  Example
   ===================  =============  =======
   k                    datakey        /k:data
   h                    hostname       /h:redvypr
   i                    packetid       /i:GPS_01
   a                    address        /a:192.168.178.1
   d                    device         /d:serial
   p                    publisher      /p:network_device
   ===================  =============  =======

Address entries can be combined. If an entry is not specified it is implicitly assumed that anything is allowed.
This can also be specified with the wildcard (\*) symbol. A good example is a RedvyprAddress that has not all entries defined,
for example the datakey only::

   r = RedvyprAddress('/k:data')
   rstr_full = r.get_str()
   print(rstr_full)

gives::

   '/u:*/a:*/h:*/d:*/p:*/i:*/k:data/'

Here all missing address entries are replaced by the wildcard symbol.

Regular Expressions
___________________
Sometimes the filtering of datapackets is based on a pattern and not on a specific expression.
For example the packetids of datapackets could be ``GPS_device1``, ``GPS_device2`` and ``GPS_device10``.
To address all GPS devices RedvyprAddresses supports `regular expressions <https://docs.python.org/3/library/re.html#module-re>`_.


Redvypr datapackets
-------------------

Misc notes
----------

- host
- device
- datapacket created by a device
- datakey
- datastream

address can to a host, device or a datakey




YAML configuration
------------------

redvypr can be configured by one or several yaml configuration files. The structure of the yaml file is

.. code-block::

    - deviceconfig:
    name: nclogger

   
Structure of the redvypr device modules
---------------------------------------


Devices are python modules in the subfolder `devices`.

A device needs to be able to initialized with a data queue and a command queue::

        dataqueue        = queue.Queue()
        datainqueue      = queue.Queue()
        comqueue         = queue.Queue()        
        device           = devicemodule.Device(dataqueue = dataqueue,comqueue = comqueue)
        
        
The basis functionality each device needs to have is::

		class Device():
		    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None):
		        """
		        """
		        self.publish     = True # publishes data, a typical device is doing this
		        self.subscribe   = False  # subscribing data, a typical datalogger is doing this
		        self.datainqueue = datainqueue
		        self.dataqueue   = dataqueue        
		        self.comqueue    = comqueue
		        
		    def thread_status(self,status):
			""" Function that is called by redvypr, allowing to update the status of the widget according to the thread 
			"""
			pass
			
		    def start(self):
		        start(self.dataqueue,self.comqueue,self.serial_name,self.baud)
		        
		
		    def __str__(self):
		        sstr = 'serial device'
		        return sstr

The dataqueue is used by the device to push data do dsdv, the command queue is mainly used to stop the device from collecting data.

Device data is gathered by creating a thread with the function::

        devicethread = threading.Thread(target=device.start, args=(), daemon=True)
        devicethread.start()
        devicedict = {'device':device,'thread':devicethread,'procqueues':[]}


Overview of device properties
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
After initialization each device has a number of attributes::
        device.name  
        device.data_receiver
        device.data_provider
        device.statistics
        device.mp
	device.numdevice
	device.redvypr
	device.thread_status	

Optional features
^^^^^^^^^^^^^^^^^

Description variable in the module (see i.e. randdata.py)::
  
        description = 'Description of the module'
        

Data packets
------------
Datapackets sent and received from devices are realized as Python dictionaries.
A device is sending data by putting data into the dataqueue. If the data put is not a dictionary, redvypr will convert it into a redvypr data dictionary.

If a device wants
to send data it simply has to create a dictionary with a key::

   data = {}
   data['data'] = 10

A useful information that is recommended to be added by the device itself is the time::

   data['t'] = time.time()
         
If the time key is not existent, redvypr adds it automatically after it received the package.
         
For many applications it might be as well of interest what kind of data is sent.
This is realized by a dictionary with the datakey preceded by an "?"::

   data['?data'] = {'unit': V, 'type','f','description':'Voltage of an OP-Amp'}

Datakeys
^^^^^^^^

Datakeys can have all characters that are supported by Python as dictionary keys
except a number of keys that are used by redvypr to distinguish between datakeys, redvypr hostnames,
IP adresses and UUIDs, these **non usable** characters are: "**@**", "**:**", "**/**", "**?**".
redvypr uses as well a number of standard keys that cannot be used as they are added automatically:

- _redvypr: Information added/modified by redvypr about the datapacket and optionally about the datakeys
  - t: The time the packet was seen the first time by a distribute data
  - host: Information about the host of the device
  - device: The devicename
  - device_info: Information about the device, i.e. if it is subscribeable etc.
  - numpacket: The packetnumber of that device, this is counted in distribute data
- _redvypr_command: A command sent from one device to the host or another device
- _info: Additional, optional, information about the datapacket, static information
- _keyinfo: Additional, optional, information about the datakeys


Datakey info
------------

The type of data that is stored in a datakey can be described with the "_keyinfo" key, which is a dictionary with
information for each datakey::

    data['_keyinfo'] = {'adc_raw':{'unit':'V','description':'Voltage output of ADC'}}

Each key in _keyinfo represents the key in the datapacket.

Datapacket filtering and naming conventions
-------------------------------------------

A device receives datapackets from other subscribed devices with their "datain"-queue.
To distinguish which datapacket the device needs to process it is necessary
to define a nomenclature to uniquely the device and datakey to be processed.

:py:mod:`redvypr.data_packets`

Datastream
^^^^^^^^^^
The data a device sends continously with the same datakey over time is called a **datastream**.
To define a datastream the redvypr hostname/IP/UUID + the devicename + the key need to be specified. 
The key is separated by a "/" from the device. The device by a ":" from the hostname or by a "::"
from the UUID. The "@" is used to separate the IP. Some examples:

- lon/gps
- t/randdata:redvypr@192.168.155.1
- data/randdata:redvypr@192.168.155.1
- data/randdata:*
- data/randata::65d7a34e-aaba-11ec-9324-135f333bc2f6
- data/randdata:redvypr@192.168.155.1::65d7a34e-aaba-11ec-9324-135f333bc2f6


