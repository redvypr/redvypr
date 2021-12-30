Redvypr devices
===============



   
Structure of the redvypr device modules
---------------------------------------


Sensors are python modules in the subfolder `sensors`.

A sensor needs to be able to initialized with a data queue and a command queue::

        dataqueue        = queue.Queue()
        datainqueue      = queue.Queue()
        comqueue         = queue.Queue()        
        sensor           = sensormodule.Sensor(dataqueue = dataqueue,comqueue = comqueue)
        
        
The basis functionality each sensor needs to have is::

		class Sensor():
		    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None):
		        """
		        """
		        self.publish     = True # publishes data, a typical sensor is doing this
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
		        sstr = 'serial sensor'
		        return sstr

The dataqueue is used by the sensor to push data do dsdv, the command queue is mainly used to stop the sensor from collecting data.

Sensor data is gathered by creating a thread with the function::

        sensorthread = threading.Thread(target=sensor.start, args=(), daemon=True)
        sensorthread.start()
        sensordict = {'sensor':sensor,'thread':sensorthread,'procqueues':[]}


Optional features
^^^^^^^^^^^^^^^^^

Description variable in the module (see i.e. randdata.py)::
  
        description = 'Description of the module'






  

