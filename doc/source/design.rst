Design
======

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


