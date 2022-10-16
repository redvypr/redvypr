"""

redvypr device class



"""

import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import logging
import sys
import yaml
import copy
from redvypr.data_packets import compare_datastreams, parse_devicestring, commandpacket

logging.basicConfig(stream=sys.stderr)

class redvypr_device():
    def __init__(self,name='redvypr_device',uuid = '', redvypr=None,dataqueue=None,comqueue=None,datainqueue=None,statusqueue=None,config = {},publish=False,subscribe=False,loglevel = 'INFO',numdevice = -1,statistics=None):
        """
        """
        self.publish     = publish   # publishes data, a typical device is doing this
        self.subscribe   = subscribe  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.statusqueue = statusqueue
        self.config      = config 
        self.redvypr     = redvypr
        self.name        = name
        self.uuid        = uuid
        self.loglevel    = loglevel
        self.numdevice   = numdevice
        self.description = 'redvypr_device'
        self.statistics  = statistics
        self.mp          = 'thread'
        self.data_receiver = []
        self.data_provider = []

        # The queue that is used for the thread commmunication
        self.thread_communication = self.comqueue

        self.properties  = {}
        self.__apriori_datakeys__     = {'t','numpacket'}
        self.__apriori_datakey_info__ = {}
        self.subscribed_datastreams   = []
        
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(loglevel)
        
    def start(self):
        """
        """
        funcname = self.__class__.__name__ + '.start()'
        self.logger.debug(funcname)
        config=copy.deepcopy(self.config)
        #start(self.datainqueue,self.dataqueue,self.comqueue,self.statusqueue,config=config)


    def thread_stop(self):
        """
        Sends a stop command to the thread_communication queue
        Returns:

        """
        command = commandpacket(command='stop', uuid=self.uuid)
        self.command(command)

    def command(self,command):
        """
        Sends a command to the running thread, either via the comqueue or the datainqueue
        Args:
            command: The command to be sent to the device, typically created with datapacket.commandpacket

        Returns:

        """

        self.thread_communication.put(command)

    def __str__(self):
        return self.description
    
    def finalize_init(self):
        pass
    
    def subscribe_datastream(self,datastream):
        """
        
        Subscribes the device that provides the datastream
        
        Args:
            datastream:
        """
        funcname = self.__class__.__name__ + '.subscribe_datastream()'
        self.logger.debug(funcname)
        datastreams = self.redvypr.get_datastreams()
        for datastream_tmp in datastreams:
            if(compare_datastreams(datastream,datastream_tmp)):
                datastream_parsed = parse_devicestring(datastream_tmp)
                devicename = datastream_parsed['devicename']
                self.logger.debug(funcname + ': Found matching datastream from device {:s}'.format(devicename))
                self.subscribe_device(devicename)
                self.subscribed_datastreams.append({'datastream':datastream,'device':devicename})
                break
            
    def subscribe_device(self,device):
        """
        """
        funcname = self.__class__.__name__ + '.subscribe_device()'
        self.logger.debug(funcname)
        self.redvypr.addrm_device_as_data_provider(device,self,remove=False)
            
    def unsubscribe_datastream(self,datastream):
        """
        """
        funcname = self.__class__.__name__ + '.unsubscribe_datastream()'
        self.logger.debug(funcname)
        # TODO, think how to deal with datastreams instead of devices with datakeys 
        
        #dataprovider = self.get_data_providing_devices(device)
        #for provider in dataprovider:
        #    self.addrm_device_as_data_provider(provider,device,remove=True)
            
    def unsubscribe_device(self,device):
        """
        """
        funcname = self.__class__.__name__ + '.subscribe_device()'
        self.logger.debug(funcname)
        self.redvypr.addrm_device_as_data_provider(self,device,remove=True)
        
    def unsubscribe_all(self):
        """
        """
        funcname = self.__class__.__name__ + '.unsubscribe_all()'
        self.logger.debug(funcname)
        self.redvypr.rm_all_data_provider(self)
                    
        
    def set_apriori_datakeys(self,datakeys):
        """ Sets the apriori datakeys, useful if the user does already knows what the device will provide
        """
        for datakey in datakeys:
            self.__apriori_datakeys__.add(datakey)         
        
        self.redvypr.update_statistics_from_apriori_datakeys(self)
    
    def get_apriori_datakeys(self):
        """ Returns a list of datakey that the device has in their data dictionary
        datakeys = ['t','data','?data','temperature']
        """
        if(self.publish): 
            return list(self.__apriori_datakeys__)
        else:
            return []
    
    
    def set_apriori_datakey_info(self,datakey,unit='NA',datatype='d',size=None,latlon=None,location=None,comment=None,serialnumber=None,sensortype=None):
        """ 
        Sets the apriori datakey information, information should

                datakey:
                unit:
                datatype:
                size:
                latlon:
                location:
                comment:
                serialnumber:
                sensortype:
        """
        infodict = {'unit':unit,'datatype':datatype}
        if(size is not None):
            infocdict['size']         = size
        if(latlon is not None):
            infocdict['latlon']       = latlon
        if(location is not None):
            infocdict['location']     = location
        if(comment is not None):
            infocdict['comment']      = comment
        if(serialnumber is not None):
            infocdict['serialnumber'] = serialnumber
        if(sensortype is not None):
            infocdict['sensortyp']    = sensortype
            
        self.__apriori_datakey_info__[datakey] = infodict
        
        self.redvypr.update_statistics_from_apriori_datakeys(self)
    
    def get_apriori_datakey_info(self,datakey):
        """ Returns 
        """
        try:
            info = self.__apriori_datakey_info__[datakey]
        except:
            info = None
            
        return info

    def get_info(self):
        """
        Returns a dictionary with the essential info of the device
        Returns:

        """
        info_dict = {}
        info_dict['uuid'] = self.uuid
        info_dict['name'] = self.name

        return info_dict

    def print_info(self):
        """ Displays information about the device

        """
        print('get_info():')
        print('Name' + self.name)
        print('redvypr' + self.redvypr)  
        
    def __str__(self):
        return self.description     

