import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import yaml
import copy

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('mergedata')
logger.setLevel(logging.DEBUG)

def start(datainqueue,dataqueue,comqueue,config):
    funcname = __name__ + '.start()'
    print(funcname,config)
    mergeddata = {}
    mergeddata['devicenames'] = config['devicenames']
    devices_updated = []
    publish_merged = False
    for i,d in enumerate(config['devicenames']):
        devices_updated.append(False)
        
    while True:
        try:
            com = comqueue.get(block=False)
            logger.info(funcname + 'received command:' + com)
            break
        except:
            pass

        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
                for i,d in enumerate(config['devicenames']):
                    if(data['device'] == d):
                        devices_updated[i] = True                        
                        for k in data.keys():
                            k_new = k + '_{:d}'.format(i)
                            mergeddata[k_new] = data[k]

                # Here the "modes" should be checked, at the moment we
                # have only the mode that data is published when all
                # devices have sent one package
                if(all(devices_updated)):
                    publish_merged = True
                    
                # Publishing the merged data
                if(publish_merged):
                    dataqueue.put(mergeddata)
                    mergeddata = {}
                    mergeddata['devicenames'] = config['devicenames']
                    publish_merged = False
                    for i in range(len(devices_updated)):
                        devices_updated[i] = False
                        
                    
            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))            

class Device():
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None,config = []):
        """
        """
        self.publish     = True # publishes data, a typical device is doing this
        self.subscribe   = True  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.config      = config # Please note that this is typically a placeholder, the config structure will be written by redvypr and the yaml
                
    def start(self):
        """ Starting the logger
        """
        funcname = self.name + ':' + __name__ +':'
        logger.debug(funcname + 'Starting now')
        # Check of devices have not been added
        devices = self.redvypr.get_devices() # Get all devices
        dataprovider = self.redvypr.get_data_providing_devices(self) # Get already connected publisher
        merge_devices = []
        for name in self.config['devicenames']: # Loop over all plots
            merge_devices.append(name)

        # Add the device if not already done so
        for name in merge_devices:
            logger.info(funcname + 'Connecting device {:s}'.format(name))
            ret = self.redvypr.addrm_device_as_data_provider(name,self,remove=False)
            if(ret == None):
                logger.info(funcname + 'Device was not found')
            elif(ret == False):
                logger.info(funcname + 'Device was already connected')
            elif(ret == True):
                logger.info(funcname + 'Device was successfully connected')                                                    
            
                
        # And now start
        start(self.datainqueue,self.dataqueue,self.comqueue,config=self.config)

    def status(self):
        """ 
        """ 
        statusstr = 'mergedata: ' + str(datetime.datetime.now())
        print(statusstr)
        return statusstr        
        
    def __str__(self):
        sstr = 'merge'
        return sstr







