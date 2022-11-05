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
import uuid
import multiprocessing
import threading
from redvypr.data_packets import compare_datastreams, parse_devicestring, commandpacket

logging.basicConfig(stream=sys.stderr)

class redvypr_device(QtCore.QObject):
    thread_started = QtCore.pyqtSignal(dict)  # Signal notifying that the thread started
    thread_stopped = QtCore.pyqtSignal(dict)  # Signal notifying that the thread started
    status_signal = QtCore.pyqtSignal(dict)  # Signal with the status of the device
    connection_changed = QtCore.pyqtSignal()  # Signal notifying that a connection with another device has changed

    def __init__(self,name='redvypr_device',uuid = '', redvypr=None,dataqueue=None,comqueue=None,datainqueue=None,statusqueue=None,template = {},config = {},publish=False,subscribe=False,multiprocess='tread',startfunction = None, loglevel = 'INFO',numdevice = -1,statistics=None):
        """
        """
        super(redvypr_device, self).__init__()
        self.publish     = publish   # publishes data, a typical device is doing this
        self.subscribe   = subscribe  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.statusqueue = statusqueue
        self.template    = template
        self.config      = config
        self.redvypr     = redvypr
        self.name        = name
        self.uuid        = uuid
        self.thread_uuid = ''
        self.loglevel    = loglevel
        self.numdevice   = numdevice
        self.description = 'redvypr_device'
        self.statistics  = statistics
        self.mp          = multiprocess
        self.data_receiver = []
        self.data_provider = []

        # Adding the start function (the function that is executed as a thread or multiprocess and is doing all the work!)
        if(startfunction is not None):
            self.start = startfunction

        # The queue that is used for the thread commmunication
        self.thread_communication = self.datainqueue

        self.properties  = {}
        self.__apriori_datakeys__     = {'t','numpacket'}
        self.__apriori_datakey_info__ = {}
        self.subscribed_datastreams   = []
        
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(loglevel)


    def get_thread_status(self):
        """

        Returns:

        """
        try:
            running = self.thread.is_alive()
        except:
            running = False

        info_dict = {}
        info_dict['uuid'] = self.uuid
        info_dict['thread_uuid'] = self.thread_uuid
        info_dict['thread_status'] = running

        return info_dict


    def command(self,command):
        """
        Sends a command to the running thread, either via the comqueue or the datainqueue
        Args:
            command: The command to be sent to the device, typically created with datapacket.commandpacket

        Returns:

        """

        self.thread_communication.put(command)


    def kill_process(self):
        funcname = __name__ + '.kill_process():'
        self.logger.debug(funcname)
        if(self.mp == 'multiprocess'):
            self.logger.debug(funcname + ': Terminating now')
            self.thread.kill()


    def thread_stop(self):
        """
        Sends a stop command to the thread_communication queue
        Returns:

        """
        funcname = __name__ + '.thread_stop():'
        self.logger.debug(funcname)
        command = commandpacket(command='stop', device_uuid=self.uuid,thread_uuid=self.thread_uuid)
        print('Sending command',command)
        self.command(command)
        try:
            running2 = self.thread.is_alive()
        except:
            running2 = False
        info_dict = {}
        info_dict['uuid'] = self.uuid
        info_dict['thread_status'] = running2
        self.thread_stopped.emit(info_dict)

    #@property
    def thread_start(self):
        """ Starts the device thread
        Args:


        """
        funcname = __name__ + '.start_thread():'
        print('Thread start')
        #logger.debug(funcname + 'Starting device: ' + str(device.name))
        self.logger.debug(funcname + 'Starting device: ' + str(self.name))
        sendict = {}
        # Find the right thread to start
        if True:
            if True:
                try:
                    running = self.thread.is_alive()
                except:
                    running = False

                if(running):
                    self.logger.info(funcname + ':thread/process is already running, doing nothing')
                else:
                    try:
                        # The arguments for the start function
                        thread_uuid = 'thread_' + str(uuid.uuid1())
                        device_info = {'uuid':self.uuid,'thread_uuid':thread_uuid}
                        args = (device_info,self.config, self.dataqueue, self.datainqueue, self.statusqueue)
                        if self.mp == 'thread':
                            self.thread = threading.Thread(target=self.start, args=args, daemon=True)
                        else:
                            self.thread = multiprocessing.Process(target=self.start, args=args)
                            #self.logger.info(funcname + 'started {:s} as process with PID {:d}'.format(self.name, self.thread.pid))

                        self.thread.start()
                        sendict['thread'] = self.thread
                        self.logger.info(funcname + 'started {:s}'.format(self.name))
                        # Update the device and the devicewidgets about the thread status
                        running2 = sendict['thread'].is_alive()
                        try: # If the device has a thread_status function
                            self.thread_status({'threadalive':running2})
                        except:
                            pass

                        self.thread_uuid = thread_uuid

                        info_dict                  = {}
                        info_dict['uuid']          = self.uuid
                        info_dict['thread_uuid']   = thread_uuid
                        info_dict['thread_status'] = running2
                        self.thread_started.emit(info_dict)  # Notify about the started thread

                        return self.thread

                    except Exception as e:
                        self.logger.warning(funcname + 'Could not start thread, reason: {:s}'.format(str(e)))
                        return None

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

