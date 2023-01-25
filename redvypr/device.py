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
from redvypr.data_packets import compare_datastreams, parse_addrstr, commandpacket, redvypr_address

logging.basicConfig(stream=sys.stderr)

class redvypr_device(QtCore.QObject):
    thread_started = QtCore.pyqtSignal(dict)  # Signal notifying that the thread started
    thread_stopped = QtCore.pyqtSignal(dict)  # Signal notifying that the thread started
    status_signal  = QtCore.pyqtSignal(dict)   # Signal with the status of the device
    subscription_changed_signal = QtCore.pyqtSignal()  # Signal notifying that a subscription changed

    def __init__(self,name='redvypr_device',uuid = '', redvypr=None,dataqueue=None,comqueue=None,datainqueue=None,statusqueue=None,template = {},config = {},publish=False,subscribe=False,multiprocess='tread',startfunction = None, loglevel = 'INFO',numdevice = -1,statistics=None,autostart=False):
        """
        """
        super(redvypr_device, self).__init__()
        self.publish     = publish    # publishes data, a typical sensor is doing this
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
        self.autostart   = autostart
        # Create a redvypr_address
        # self.address_str
        # self.address
        self.__update_address__()

        # Adding the start function (the function that is executed as a thread or multiprocess and is doing all the work!)
        if(startfunction is not None):
            self.start = startfunction

        # The queue that is used for the thread commmunication
        self.thread_communication = self.datainqueue

        self.subscribed_addresses = []
        
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(loglevel)

    def subscription_changed_global(self,devchange):
        """
        Function is called by redvypr after another device emitted the subscription_changed_signal

        Args:
            devchange: redvypr_device that emitted the subscription changed signal

        Returns:

        """
        print('Global subscription changed',self.name,devchange.name)

    def subscribe_address(self, address):
        """
        """
        funcname = self.__class__.__name__ + '.subscribe_address()'
        self.logger.debug(funcname + ' subscribing to device {:s}'.format(str(address)))
        print('Address',address,type(address))
        if(type(address) == str):
            raddr = redvypr_address(address)
        else:
            raddr = address

        FLAG_NEW = True
        # Test if the same address exists already
        for a in self.subscribed_addresses:
            if(a.addressstr == raddr.addressstr):
                FLAG_NEW = False
                break

        if(FLAG_NEW):
            self.subscribed_addresses.append(raddr)
            # TODO, emit signals
            self.subscription_changed_signal.emit()
            print(self.subscribed_addresses)

    def unsubscribe_address(self, address):
        """
        """
        funcname = self.__class__.__name__ + '.unsubscribe_address()'
        self.logger.debug(funcname + ' subscribing to device {:s}'.format(str(address)))
        print('Address', address, type(address))
        if (type(address) == str):
            raddr = redvypr_address(address)
        else:
            raddr = address

        try:
            self.subscribed_addresses.remove(raddr)
            self.subscription_changed_signal.emit()
        except Exception as e:
            self.logger.warning('Could not remove address {:s}: {:s}'.format(str(address),str(e)))

        # TODO, emit signals

    def change_name(self,name):
        """
        Changes the name of the device

        Args:
            name:

        Returns:

        """
        self.name = name
        self.__update_address__()
        # Clear the statistics
        self.statistics['numpackets'] = 0
        self.statistics['datakeys'] = []
        self.statistics['devicekeys'] = {}
        self.statistics['devices'] = []
        self.statistics['datastreams'] = []
        self.statistics['datastreams_dict'] = {}
        self.statistics['datastreams_info'] = {}

    def __update_address__(self):
        self.address_str = self.name + ':' + self.redvypr.hostinfo['hostname'] + '@' + self.redvypr.hostinfo[
            'addr'] + '::' + self.redvypr.hostinfo['uuid']
        self.address = redvypr_address(self.address_str)

    def address_string(self,strtype='<device>:<host>@<addr>::<uuid>'):
        """
        Returns the addressstring of the device
        Returns:

        """
        astr = self.redvypr_address().get_str(strtype = strtype)
        return astr

    def got_subscribed(self,dataprovider_address,datareceiver_address,):
        """
        Function is called by self.redvypr if this device is connected with another one. The intention is to notify device
        that a specific datastream/devce has been subscribed. This is a wrapper function and need to be reimplemented if needed.
        See i.e. iored as an example
        Args:
            dataprovider_address:
            datareceiver_address:

        Returns:

        """
        pass

    def got_unsubscribed(self, dataprovider_address, datareceiver_address):
        pass

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


    def __send_command__(self,command):
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

    def thread_command(self, command,data=None):
        """
        Sends a command to the device thread
        Args:
            command: string, i.e. "stop"
            data: dictionary with additional data, the data will be incorporated into the command dict by executing command.update8(ata)

        Returns:

        """
        funcname = __name__ + '.thread_command():'
        self.logger.debug(funcname)
        command = commandpacket(command=command, device_uuid=self.uuid, thread_uuid=self.thread_uuid,devicename=self.name,host=self.redvypr.hostinfo)
        if(data is not None):
            if type(data) == dict:
                command.update(data)
            else:
                raise TypeError('data needs to be a dictionary')

        print('Sending command')
        self.__send_command__(command)

    def thread_stop(self):
        """
        Sends a stop command to the thread_communication queue
        Returns:

        """
        funcname = __name__ + '.thread_stop():'
        self.logger.debug(funcname)
        command = commandpacket(command='stop', device_uuid=self.uuid,thread_uuid=self.thread_uuid)
        #print('Sending command',command)
        self.__send_command__(command)
        try:
            running2 = self.thread.is_alive()
        except:
            running2 = False
        info_dict = {}
        info_dict['uuid'] = self.uuid
        info_dict['thread_status'] = running2
        self.thread_stopped.emit(info_dict)

    def thread_start(self):
        """ Starts the device thread
        Args:


        """
        funcname = __name__ + '.start_thread():'

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
                        device_info = {'device':self.name,'uuid':self.uuid,'thread_uuid':thread_uuid,'hostinfo':self.redvypr.hostinfo}
                        config = copy.deepcopy(self.config) # The thread/multiprocess gets a copy
                        args = (device_info,config, self.dataqueue, self.datainqueue, self.statusqueue)
                        print('thread',self.mp)
                        if self.mp == 'thread':
                            self.logger.info(funcname + 'Starting as thread')
                            self.thread = threading.Thread(target=self.start, args=args, daemon=True)
                        else:
                            self.logger.info(funcname + 'Starting as process')
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
    
    def get_data_provider_info(self):
        """
        Returns information about the data providing devices
        Returns:

        """
        d = copy.deepcopy(self.statistics['device_redvypr'])
        return d

    def publishing_to(self):
        """

        Returns:
            List of devices this device is publishing to
        """
        devs = self.redvypr.get_data_receiving_devices(self)
        return devs

    def subscribed_to(self):
        """

        Returns:
            List of devices this device is subscribed to
        """
        devs = self.redvypr.get_data_providing_devices(self)
        return devs
            
    def unsubscribe_all(self):
        """
        """
        funcname = self.__class__.__name__ + '.unsubscribe_all()'
        self.logger.debug(funcname)
        self.subscribed_addresses = []
                    
        
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

