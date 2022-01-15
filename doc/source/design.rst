Design
======


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






  

