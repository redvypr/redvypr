import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import logging
import sys
import yaml

description = 'An bare example device'

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('exampledevice')
logger.setLevel(logging.DEBUG)


def start(datainqueue,dataqueue,comqueue):
    """ This is the function that reads and processes data from the sensor
    """
    funcname = __name__ + '.start()'        
    while True:
        try:
            com = comqueue.get(block=False)
            logger.debug('received command:' + str(com))
            break
        except:
            pass


        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
                dataqueue.put(data)

            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))            

class Device():
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None,config = []):
        """
        """
        self.publish     = False # publishes data, a typical device is doing this
        self.subscribe   = True  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.config      = config # Please note that this is typically a placeholder, the config structure will be written by redvypr and the yaml
                
    def start(self):
        """ This function is called by redvypr as a thread or multiprocessing
        """ 
        start(self.datainqueue,self.dataqueue,self.comqueue)

    def status(self):
        """ This is optional bare, but an example how a device can give a text status
        """ 
        statusstr = 'exampledevice_bare: ' + str(datetime.datetime.now())
        print(statusstr)
        return statusstr
        
    def __str__(self):
        sstr = 'bare example device'
        return sstr




            

