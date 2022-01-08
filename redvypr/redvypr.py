import serial
import serial.tools
import os
import time
import datetime
import logging
import queue
import sys
import yaml
import pkg_resources
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np
import inspect
import threading
import multiprocessing
import redvypr.devices as redvyprdevices
import redvypr.standard_device_widgets as standard_device_widgets
import socket
import argparse
import importlib.util
import glob
import pathlib
import signal
import uuid




# Get the version
_version_file = pkg_resources.resource_filename('redvypr','VERSION')
with open(_version_file) as _version_f:
   version = _version_f.read().strip()

_version_f.close()

# The maximum size the dataqueues have, this should be more than
# enough for a "normal" usage case
queuesize = 10000
#queuesize = 10

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr')
logger.setLevel(logging.DEBUG)

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

# The hostinfo, to distinguish between different redvypr instances
hostinfo = {'name':'redvypr','tstart':time.time(),'addr':get_ip(),'uuid':str(uuid.uuid1())}

def distribute_data(devices,infoqueue,dt=0.01):
    """ The heart of redvypr, this functions distributes the queue data onto the subqueues.
    """
    funcname = __name__ + 'distribute_data()'
    dt_info = 1.0 # The time interval information will be sent
    dt_avg = 0 # Averaging of the distribution time needed
    navg = 0    
    tinfo = time.time()    
    tstop = time.time()
    dt_sleep = dt
    while True:
        time.sleep(dt_sleep)
        tstart = time.time()
        for devicedict in devices:
            device = devicedict['device']
            #print('device',devicedict)
            while True:
                try:
                    data = device.dataqueue.get(block=False)
                    devicedict['numdata'] += 1
                        
                except Exception as e:
                    break

                # Add deviceinformation to the data package
                if('device' not in data.keys()):
                    data['device']   = str(device.name)
                    data['host']     = hostinfo

                try:
                    if devicedict['statistics']['inspect']:
                        devicedict['statistics']['numpackets'] += 1
                        # Create a unique list of datakeys
                        devicedict['statistics']['datakeys'] = list(set(devicedict['statistics']['datakeys'] + list(data.keys())))
                        # Create a unqiue list of devices, device can
                        # be different from the transporting device,
                        # i.e. network devices do not change the name
                        # of the transporting dictionary
                        devicedict['statistics']['devices'] = list(set(devicedict['statistics']['devices'] + [data['device']]))
                except Exception as e:
                    print('e')

                if True:
                    # Feed the data into the modules/functions/objects and
                    # let them treat the data
                    for dataout in devicedict['dataout']:
                        devicedict['numdataout'] += 1
                        try:
                            dataout.put_nowait(data)
                        except Exception as e:
                            logger.debug(funcname + ':dataout of :' + devicedict['device'].name + ' full')
                    for guiqueue in devicedict['guiqueue']: # Put data into the guiqueue, this queue does always exist
                        #print('putting into guiqueue',data)
                        try:                        
                            guiqueue.put_nowait(data)
                        except Exception as e:
                            logger.debug(funcname + ':guiqueue of :' + devicedict['device'].name + ' full')

        # Calculate the sleeping time
        tstop = time.time()        
        dt_dist = tstop - tstart # The time for all the looping
        dt_avg += dt_dist
        navg += 1
        dt_sleep = max([0,dt - dt_dist])
        if((tstop - tinfo) > dt_info):
            tinfo = tstop
            info_dict = {'dt_avg':dt_avg/navg}
            #print(info_dict)
            infoqueue.put_nowait(info_dict)
            
            



def addrm_device_as_data_provider(devices,deviceprovider,devicereceiver,remove=False):
    """ Adds or remove deviceprovider as a datasource to devicereceiver
    Arguments:
    devices: list of dictionary including device and dataout lists
    deviceprovider: Device object 
    devicerecevier: Device object
    Returns: None if device could not been found, True for success, False if device was already connected
    """
    print('addrm_device_as_data_provider():')
    # Find the device first in self.devices and save the index
    inddeviceprovider = -1
    inddevicereceiver = -1    
    for i,s in enumerate(devices):
        if(s['device'] == deviceprovider):
            inddeviceprovider = i
        if(s['device'] == devicereceiver):
            inddevicereceiver = i     

    if(inddeviceprovider < 0 or inddevicereceiver < 0):
        logger.debug('addrm_device_as_data_provider(): Could not find devices, doing nothing')
        return None

    datainqueue       = devices[inddevicereceiver]['device'].datainqueue
    datareceivernames = devices[inddevicereceiver]['device'].data_receiver
    dataoutlist       = devices[inddeviceprovider]['dataout']
    
    if(remove):
        if(datainqueue in dataoutlist):
            logger.debug('addrm_device_as_data_provider():removed device')
            dataoutlist.remove(datainqueue)
            # Remove the receiver name from the list
            devices[inddevicereceiver]['device'].data_receiver.remove(devices[inddeviceprovider]['device'].name)
            devices[inddeviceprovider]['device'].data_provider.remove(devices[inddevicereceiver]['device'].name)
            return True
        else:
            return False
    else:
        if(datainqueue in dataoutlist):
            return False
        else:
            logger.debug('addrm_device_as_data_provider():added device')
            dataoutlist.append(datainqueue)
            # Add the receiver and provider names to the device
            devices[inddevicereceiver]['device'].data_receiver.append(devices[inddeviceprovider]['device'].name)
            devices[inddeviceprovider]['device'].data_provider.append(devices[inddevicereceiver]['device'].name)
            return True


def get_data_receiving_devices(devices,device):
    """ Returns a list of devices that are receiving data from device
    """
    funcname = __name__ + 'get_data_receiving_devices():'
    devicesin = []
    # Find the device first in self.devices and save the index
    inddevice = -1
    for i,s in enumerate(devices):
        if(s['device'] == device):
            inddevice = i

    if(inddevice < 0):
        return None

    # Look if the devices are connected as input to the choosen device
    #  device -> data -> s in self.devices
    try:
        dataout = device.dataqueue
    except Exception as e:
        logger.debug(funcname + 'Device has no dataqueue for data output')
        return devicesin
    
    for dataout in devices[inddevice]['dataout']: # Loop through all dataoutqueues
        for s in devices:
            sen = s['device']
            datain = sen.datainqueue
            if True:
                if(dataout == datain):
                    devicesin.append(s)
            
    return devicesin

def get_data_providing_devices(devices,device):
    """ Returns a list of devices that are providing their data to device, i.e. device.datain is in the 'dataout' list of the device
    devices = list of dictionaries 
    """
    # Find the device first in self.devices and save the index
    inddevice = -1
    for i,s in enumerate(devices):
        if(s['device'] == device):
            inddevice = i

    if(inddevice < 0):
        return None
    
    devicesout = []
    # Look if the devices are connected as input to the chosen device
    # s in self.devices-> data -> device
    datain = device.datainqueue
    for s in devices:
        sen = s['device']
        try:
            for dataout in s['dataout']:
                if(dataout == datain):
                    devicesout.append(s)
        except Exception as e:
            print('dataqueue',s,device,str(e))
            
    return devicesout



class redvypr(QtCore.QObject):
    """This is the redvypr heart. Here devices are added/threads
    are started and data is interchanged

    """
    device_path_changed = QtCore.pyqtSignal() # Signal notifying if the device path was changed
    device_added        = QtCore.pyqtSignal(list) # Signal notifying if the device path was changed    
    def __init__(self,parent=None,config=None,nogui=False):
        #super(redvypr, self).__init__(parent)
        super(redvypr, self).__init__()
        funcname = __name__ + '.__init__()'                                
        logger.debug(funcname)
        self.config = {} # Might be overwritten by parse_configuration()
        self.numdevice = 0
        self.devices        = [] # List containing dictionaries with information about all attached devices
        self.device_paths   = [] # A list of pathes to be searched for devices
        self.device_modules = []        
        
        ## A timer to check the status of all threads
        self.devicethreadtimer = QtCore.QTimer()
        self.devicethreadtimer.timeout.connect(self.update_devices_thread_status)
        self.devicethreadtimer.start(500)


        ## A timer to print the status in the nogui environment
        if(nogui):
            self.statustimer = QtCore.QTimer()
            self.statustimer.timeout.connect(self.print_status)
            self.statustimer.start(5000)        
        

        self.dt_datadist = 0.01 # The time interval of datadistribution
        self.dt_avg_datadist = 0.00 # The time interval of datadistribution        
        self.datadistinfoqueue = queue.Queue(maxsize=1000) # A queue to get informations from the datadistribution
        self.datadistthread = threading.Thread(target=distribute_data, args=(self.devices,self.datadistinfoqueue,self.dt_datadist), daemon=True)
        self.datadistthread.start()
        self.populate_device_path()

        # Configurating redvypr
        if(config is not None):
            logger.debug(funcname + ':Configuration: ' + str(config))            
            if(type(config) == str):
                config = [config]

            for c in config:
                logger.debug(funcname + ':Parsing configuration: ' + str(c))                            
                self.parse_configuration(c)        

    def print_status(self):
        funcname = __name__ + '.print_status():'
        print(funcname + self.status())

    def status(self):
        """ Creates a statusstr of the devices
        """
        tstr = str(datetime.datetime.now())
        statusstr = "{:s}, {:s}, num devices {:d}".format(tstr, hostinfo['name'], len(self.devices))
        
        for sendict in self.devices:
            try:
                running = sendict['thread'].is_alive()
                runstr = 'running'
            except:
                running = False
                runstr = 'stopped'    

            statusstr += '\n\t' + sendict['device'].name + ':' + runstr + ': data packets: {:d}'.format(sendict['numdata'])
            #statusstr += ': data packets published: {:d}'.format(sendict['numdataout'])

        return statusstr


    def update_devices_thread_status(self):
        """ This function is called regularly to check the status of the threads
        """
        # Check the datadistribution statistics
        datainfo = []
        while True:
            try:
                data = self.datadistinfoqueue.get(block=False)
                datainfo.append(data)
                self.dt_avg_datadist = data['dt_avg']

            except Exception as e:
                break

        # Check the devicethreadstatusses
        for sendict in self.devices:
            # Update the device and the devicewidgets about the thread status
            if(sendict['thread'] is not None):
                running2 = sendict['thread'].is_alive()
                try: # If the device has a thread_status function
                    device.thread_status({'threadalive':running2})
                except:
                    pass

                # Tell it deviceinfos
                try: # GUI?
                    sendict['infowidget'].thread_status({'threadalive':running2})
                except Exception as e:
                    pass                    
                # Go tell it to the widgets
                try: # If the device has a thread_status function
                    sendict['initwidget'].thread_status({'threadalive':running2})
                except Exception as e:
                    pass
                    #print('Start thread exception:' + str(e))


                for guiwidget in sendict['gui']:
                        try: # If the device has a thread_status function
                            guiwidget.thread_status({'threadalive':running2})
                        except Exception as e:
                            pass
                            #print('Start thread exception:' + str(e))



    def parse_configuration(self,configfile=None):
        """ Parses a dictionary with a configuration
        """
        funcname = "parse_configuration()"
        logger.debug(funcname)
        if(type(configfile) == str):
            logger.debug(funcname + ':Opening yaml file: ' + str(configfile))
            if(os.path.exists(configfile)):
                fconfig = open(configfile)
                config = yaml.load(fconfig, Loader=yaml.loader.SafeLoader)
            else:
                logger.debug(funcname + ':Yaml file: ' + str(configfile) +  ' does not exist!')                
        elif(type(configfile) == dict):
            logger.debug(funcname + ':Opening dictionary')
            config = configfile
        else:
            logger.debug(funcname + ':This shouldnt happen')


        self.config = config
        # Add device path if found
        if('devicepath' in config.keys()):
            devpath = config['devicepath']

            if(type(devpath) == str):
                devpath = [devpath]

            for p in devpath:
                if(p not in self.device_paths):
                    self.device_paths.append(p)

            self.populate_device_path()
            self.device_path_changed.emit() # Notify about the changes


            
        # Adding the devices found in the config ['devices']
        if('devices' in config.keys()):
            for device in config['devices']:
                logger.info('Adding device:' +device['deviceconfig']['name'])
                # TODO, check if the name has been already given
                self.add_device(devicemodulename=device['devicemodulename'],deviceconfig=device['deviceconfig'])

        # Connecting devices ['connections']
        if('connections' in config.keys()):        
            logger.debug('Connecting devices')
            for con in config['connections']:
                logger.debug('Connecting devices:' + str(con))
                devicenameprovider = con['publish']    
                devicenamereceiver = con['receive']
                indprovider = -1
                indreceiver = -1
                for i,s in enumerate(self.devices):
                    if s['device'].name == devicenameprovider:
                       deviceprovider = s['device']
                       indprovider = i 
                    if s['device'].name == devicenamereceiver:
                       devicereceiver = s['device']
                       indreceiver = i 

                if((indprovider > -1) and (indreceiver > -1)):
                    addrm_device_as_data_provider(self.devices,deviceprovider,devicereceiver,remove=False)
                    sensprov = get_data_providing_devices(self.devices,devicereceiver)
                    sensreicv = get_data_receiving_devices(self.devices,deviceprovider)
                    #print('provider',devicereceiver,sensprov)            
                    #print('receiver',deviceprovider,sensreicv)            
                    #print('provider',self.devices[indprovider])#,deviceprovider)
                    #print('receiver',self.devices[indreceiver])
                    #print(devicereceiver)
                else:
                    logger.warning(funcname + ':Could not create connection for devices: {:s} and {:s}'.format(devicenameprovider,devicenamereceiver))

        # Add the hostname
        try:
            logger.info(funcname + ': Setting hostname to {:s}'.format(config['hostname']))
            hostinfo['name'] = config['hostname']
        except:
            pass
        
        if('start' in config.keys()):
            logger.debug('Starting devices')
            if(config['start'] is not None):
                for start_device in config['start']:
                    for s in self.devices:
                        if(s['device'].name == start_device):
                            self.start_device_thread(s['device'])


    def populate_device_path(self):
        """Searches all device paths for modules and creates a list with the
        found devices self.device_modules

        """
        funcname = 'populate_device_path()'
        logger.debug(funcname)
        self.device_modules = [] # Clear the list
        # Add all devices from additional folders
        for dpath in self.device_paths:
            python_files = glob.glob(dpath + "/*.py")
            for pfile in python_files:
                module_name = pathlib.Path(pfile).stem
                spec = importlib.util.spec_from_file_location(module_name, pfile)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module_members = inspect.getmembers(module,inspect.isclass)
                hasdevice = False
                try:
                    module.Device
                    hasdevice = True      
                except:
                    pass

                if(hasdevice):
                    devdict = {'module':module,'name':module_name,'source':pfile}
                    self.device_modules.append(devdict)

        # Add all devices from the device module
        device_modules = inspect.getmembers(redvyprdevices,inspect.ismodule)                
        for smod in device_modules:
            devicemodule     = getattr(redvyprdevices, smod[0])
            devdict = {'module':devicemodule,'name':smod[0],'source':'devices'}
            self.device_modules.append(devdict)                                    


    def add_device(self,devicemodulename=None, deviceconfig = None, thread=False):
        """ Function adds a device
        """
        funcname = __name__ + '.add_device()' 
        logger.debug(funcname + ':devicemodule: ' + str(devicemodulename) + ':deviceconfig: ' + str(deviceconfig))
        devicelist = []
        device_found = False
        # Loop over all modules and check of we find the name
        for smod in self.device_modules:
           if(devicemodulename == smod['name']):
              print(smod)
              devicemodule     = smod['module']
              #devicemodule     = getattr(redvyprdevices, devicemodulename)
              thread = True
              [devicedict,ind_devices] = self.create_devicedict(devicemodule,thread=thread,deviceconfig=deviceconfig)
              device = devicedict['device']
              # If the device does not have a name, add a standard but unique one
              try:
                  device.name
              except:
                  device.name = devicemodulename +'_' + str(self.numdevice)

              # Add the redvypr object to the device itself
              device.redvypr = self
              # Link the statistics directly into the device as well    
              device.statistics = devicedict['statistics']
              # Check if the device wants a direct start after initialization
              try:
                  autostart = device.autostart
              except:
                  autostart = False


              # Do the loglevel use "standard" to take the loglevel of the redvypr instance
              try:
                  loglevel_device = device.loglevel.upper()
              except: # Use the standard loglevel of redvypr
                  loglevel_device = "standard"

              # If we have standard 
              if(loglevel_device == "standard"):
                  loglevel_device = logger.level

              # If the device has a logger
              try:
                  device.logger.setLevel(loglevel_device)
              except Exception as e:
                  logger.debug(funcname + ': NA logger device loglevel {:s}'.format(str(e)))

              # If the module has a logger            
              try:
                  devicemodule.logger.setLevel(loglevel_device)
              except Exception as e:            
                  logger.debug(funcname + ': NA logger module loglevel {:s}'.format(str(e)))


              if(autostart):
                  logger.debug(funcname + ': Starting device')
                  self.start_device_thread(device)

              devicelist = [devicedict,ind_devices,devicemodule]
              self.device_added.emit(devicelist)
              device_found = True
              break

        if(device_found == False):
           logger.warning(funcname + ': Could not add device (not found): {:s}',format(devicemodulename))
           
        return devicelist




    def create_devicedict(self,devicemodule,devicename = None,thread=False,deviceconfig=None):
        """Adds a device of type devicemodulename

        """

        if thread: # Thread or multiprocess
            dataqueue        = queue.Queue(maxsize=queuesize)
            datainqueue      = queue.Queue(maxsize=queuesize)            
            comqueue         = queue.Queue(maxsize=queuesize)
            statusqueue      = queue.Queue(maxsize=queuesize)
            #dataoutqueue     = queue.Queue(maxsize=queuesize)
            guiqueue         = queue.Queue(maxsize=queuesize)                                
        else:
            dataqueue        = multiprocessing.Queue(maxsize=queuesize)
            datainqueue      = multiprocessing.Queue(maxsize=queuesize)            
            comqueue         = multiprocessing.Queue(maxsize=queuesize)
            statusqueue      = multiprocessing.Queue(maxsize=queuesize)
            #dataoutqueue     = multiprocessing.Queue(maxsize=queuesize)
            guiqueue         = multiprocessing.Queue(maxsize=queuesize)                                            
        
        # Device do not necessarily have a statusqueue
        try:
            device               = devicemodule.Device(dataqueue= dataqueue,comqueue = comqueue,datainqueue = datainqueue,statusqueue = statusqueue)
        except:
            device               = devicemodule.Device(dataqueue,comqueue,datainqueue)
        # Add an unique number
        device.numdevice     = self.numdevice
        self.numdevice      += 1        
        if thread: # Thread or multiprocess        
            device.mp = 'thread'
        else:
            device.mp = 'multiprocessing'

        # Add lists of receiving and providing devicenames
        device.data_receiver = []
        device.data_provider = []        
        
        statistics = {'inspect':True,'numpackets':0,'datakeys':[],'devices':[]} # A dictionary for gathering useful information about the packages
        devicedict = {'device':device,'thread':None,'dataout':[],'gui':[],'guiqueue':[guiqueue],'statistics':statistics}
        # Add some statistics
        devicedict['numdata'] = 0
        devicedict['numdataout'] = 0        
        # The displaywidget, to be filled by redvyprWidget.add_device (optional)
        devicedict['devicedisplaywidget'] = None
        
        # Setting the configuration of the device. Each key entry in
        # the dict is directly set as an attribute in the device class
        if(deviceconfig is not None):
            logger.info('Setting configuration of device: ' + str(device) + ' #' + str(device.numdevice))
            for key in deviceconfig:
                confvalue = deviceconfig[key]                
                logger.info(key + ':'+ str(confvalue))
                setattr(device,key,confvalue)
            
                
        self.devices.append(devicedict)
        
        return [devicedict,len(self.devices)-1]

    def start_device_thread(self,device):
        """Functions starts a thread, to process the data (i.e. reading from a device, writing to a file)
        Args:
           device: Device is either a Device class defined in the device module or a dictionary containing the device class (when called from infodevicewidget in redvypr.py)

        """
        funcname = __name__ + '.start_device_thread()'
        if(type(device) == dict): # If called from devicewidget
            device = device['device']        
        logger.debug(funcname + ':Starting device: ' + device.name)
        # Find the right thread to start
        for sendict in self.devices:
            if(sendict['device'] == device):
                try:
                    running = sendict['thread'].is_alive()
                except:
                    running = False

                if(running):
                    logger.info(funcname + 'thread/process is already running, doing nothing')
                    
                else:
                    if device.mp == 'thread':
                        devicethread     = threading.Thread(target=device.start, args=(), daemon=True)
                        sendict['thread']= devicethread
                        sendict['thread'].start()
                    else:
                        deviceprocess    = multiprocessing.Process(target=device.start, args=())
                        sendict['thread']= deviceprocess
                        sendict['thread'].start()
                        print('PID',deviceprocess.pid)
                    print('started')
                    
                    # Update the device and the devicewidgets about the thread status
                    running2 = sendict['thread'].is_alive()
                    try: # If the device has a thread_status function
                        device.thread_status({'threadalive':running2})
                    except:
                        pass
                    
                    try: # If the device has a thread_status function
                        sendict['initwidget'].thread_status({'threadalive':running2})
                    except Exception as e:
                        pass
                    
                    for guiwidget in sendict['gui']:
                        try: # If the device has a thread_status function
                            guiwidget.thread_status({'threadalive':running2})
                        except Exception as e:
                            pass
                            #print('Start thread exception:' + str(e))
                    

    def stop_device_thread(self,device):
        """Functions stops a thread, to process the data (i.e. reading from a device, writing to a file)
        Args:
           device: Device is either a Device class defined in the device module or a dictionary containing the device class (when called from infodevicewidget in redvypr.py)

        """        
        funcname = __name__ + '.stop_device_thread()'
        if(type(device) == dict): # If called from devicewidget
            device = device['device']                
        logger.debug(funcname + ':Stopping device: ' + device.name)
        for sendict in self.devices:
            if(sendict['device'] == device):
                if(sendict['thread'] == None):
                    return
                elif(sendict['thread'].is_alive()):
                    try:
                        if(device.datainqueuestop):
                            datainqueuestop = True
                    except:
                        datainqueuestop = False
                    
                    if(datainqueuestop):
                        logger.debug(funcname + ':Stopping device with datainqueue: ' + device.name)
                        device.datainqueue.put({'command':'stop'})
                    else:
                        logger.debug(funcname + ':Stopping device with comqueue: ' + device.name)
                        device.comqueue.put('stop')
                                
                else:
                    print('Stop exception')
                    
                # This is probably still an alive thread, since it is usually checked in time intervals within the thread
                try:    
                    device.thread_status({'threadalive': sendict['thread'].is_alive()})
                except:
                    pass
                

    def adddevicepath(self,folder):
        """Adds a path to the devicepathlist
        """
        if folder:
            if(folder not in self.device_paths):
                self.device_paths.append(folder)
                self.device_path_changed.emit() # Notify about the changes                



    def remdevicepath(self,folder):
        if(folder not in self.device_paths):
            self.device_paths.remove(folder)
            self.device_path_changed.emit() # Notify about the changes


    def get_device_from_str(self,devicestr):
        """ Returns the deviced based on an inputstr, if not found returns None
        """
        devicedict = self.get_devicedict_from_str(devicestr)
        if(devicedict == None):
            return None
        else:
            return devicedict['device']
            

    def get_devicedict_from_str(self,devicestr):
        """ Returns the devicedict based on an inputstr, if not found returns None
        """
        for d in self.devices:
            if d['device'].name == devicestr:
                return d

        return None    
    
    def get_devices(self):
        """ Returns a list of the devices
        """
        devicelist = []
        for d in self.devices:
            devicelist.append(d['device'].name)

        return devicelist

    def get_data_providing_devices(self,device):
        return get_data_providing_devices(self.devices,device)

    def get_data_receiving_devices(self,device):
        return get_data_receiving_devices(self.devices,device)

    def addrm_device_as_data_provider(self,deviceprovider,devicereceiver,remove=False):
        """ Adding/removing devices as dataprovider for the device devicereceiver
        Arguments:
        deviceprovider: The device (type Device) or devicename (type str Device.name)
        devicerreceiver: The device (type Device) or devicename (type str Device.name)
        remove: False for adding, True for removing
        """
        if(type(deviceprovider) == str):
            deviceprovider = self.get_device_from_str(deviceprovider)

        if(type(devicereceiver) == str):
            devicereceiver = self.get_device_from_str(devicereceiver)

        ret = addrm_device_as_data_provider(self.devices,deviceprovider,devicereceiver,remove=remove)
        return ret


        




#
#
# ########################
# Here the gui part starts
# ########################
#
#
#
    

class redvyprConnectWidget(QtWidgets.QWidget):
    """A widget that lets the user connect the input and output queues of
the devives with each other

    """
    def __init__(self,devices=None,device=None):
        super(redvyprConnectWidget, self).__init__()
        if(len(devices) > 0):    
            if(device == None): # Take the first one
                device = devices[0]['device']

        self.devices = devices
        layout = QtWidgets.QVBoxLayout(self)
        lab = QtWidgets.QLabel('Connect datastreams to device:')

        lablayout = QtWidgets.QHBoxLayout()
        lablayout.addStretch()
        lablayout.addWidget(lab)
        lablayout.addStretch()


        self.device_label = QtWidgets.QLabel('Device')
        devlablayout = QtWidgets.QHBoxLayout()
        devlablayout.addStretch()
        devlablayout.addWidget(self.device_label)
        devlablayout.addStretch()                        
        font = QtGui.QFont('Arial', 20)
        font.setBold(True)
        self.device_label.setFont(font)
        layout.addLayout(lablayout)
        layout.addLayout(devlablayout)

        conwidget  = QtWidgets.QWidget(self)
        conlayout = QtWidgets.QHBoxLayout(conwidget)
        self.devices_listallout= QtWidgets.QListWidget() # All dataproviding devices
        self.devices_listallin = QtWidgets.QListWidget() # All datareceiving devices
        self.devices_listin    = QtWidgets.QListWidget() # All connected datareceiving devices
        self.devices_listout   = QtWidgets.QListWidget() # All connected dataproviding devices
        self.devices_listcon   = QtWidgets.QListWidget() # The devices a connection is to be defined
        self.devices_listcon.itemClicked.connect(self.itemcon_clicked)
        self.devices_listcon.itemDoubleClicked.connect(self.itemcon_dclicked)                

        self.__commitbtn  = QtWidgets.QPushButton('Commit')
        self.__commitbtn.clicked.connect(self.commit_clicked)

        self.arroutleft = QtWidgets.QToolButton()
        self.arroutleft.setArrowType(QtCore.Qt.LeftArrow)
        self.arroutleft.clicked.connect(self.addrm_out)
        self.arroutright = QtWidgets.QToolButton()
        self.arroutright.setArrowType(QtCore.Qt.RightArrow)
        self.arroutright.clicked.connect(self.addrm_out)        
        self.arrinleft = QtWidgets.QToolButton()
        self.arrinleft.setArrowType(QtCore.Qt.LeftArrow)
        self.arrinleft.clicked.connect(self.addrm_in)                
        self.arrinright = QtWidgets.QToolButton()
        self.arrinright.setArrowType(QtCore.Qt.RightArrow)
        self.arrinright.clicked.connect(self.addrm_in)                        
        arroutlayout = QtWidgets.QVBoxLayout()
        arroutlayout.addWidget(self.arroutleft)
        arroutlayout.addWidget(self.arroutright)
        arrinlayout = QtWidgets.QVBoxLayout()
        arrinlayout.addWidget(self.arrinleft)
        arrinlayout.addWidget(self.arrinright)                

        # Subscribe devices all
        devicesoutlayout = QtWidgets.QVBoxLayout()
        devicesoutlayout.addWidget(QtWidgets.QLabel('Subscribable devices'))
        devicesoutlayout.addWidget(self.devices_listallout)
        conlayout.addLayout(devicesoutlayout)
        conlayout.addLayout(arroutlayout)
        # Subscribed devices of the choosen device
        devicessubscribedlayout = QtWidgets.QVBoxLayout()
        devicessubscribedlayout.addWidget(QtWidgets.QLabel('Subscribed devices'))        
        devicessubscribedlayout.addWidget(self.devices_listout)
        conlayout.addLayout(devicessubscribedlayout)
        # The device to choose
        convlayout = QtWidgets.QVBoxLayout()
        convlayout.addWidget(QtWidgets.QLabel('Device'))        
        convlayout.addWidget(self.devices_listcon)     
        #conlayout.addWidget(self.devices_listcon)
        conlayout.addLayout(convlayout)
        # Published devices
        devicespublishedlayout = QtWidgets.QVBoxLayout()
        devicespublishedlayout.addWidget(QtWidgets.QLabel('Publishing to devices'))        
        devicespublishedlayout.addWidget(self.devices_listin)
        conlayout.addLayout(devicespublishedlayout)
        conlayout.addLayout(arrinlayout)
        # All devices data can be published to
        devicespublishablelayout = QtWidgets.QVBoxLayout()
        devicespublishablelayout.addWidget(QtWidgets.QLabel('Data receivable devices'))        
        devicespublishablelayout.addWidget(self.devices_listallin)
        conlayout.addLayout(devicespublishablelayout)
        
        layout.addWidget(conwidget)
        layout.addWidget(self.__commitbtn)


        if(len(devices) > 0):    
            self.update_list(device)
        
        
    def addrm_out(self):
        """ Connecting publishing devices with device
        """
        funcname = 'addrm_in'
        logger.debug(funcname)        
        button = self.sender()
        if(button == self.arroutleft):
            #print('remove')
            ind = self.devices_listout.currentRow()
            self.devices_listout.takeItem(ind)
            
        if(button == self.arroutright):
            #print('add')
            itmadd = self.devices_listallout.currentItem()
            sen = itmadd.device
            itm = QtWidgets.QListWidgetItem(sen.name)
            itm.device = sen
            self.devices_listout.addItem(itm)            
            #print('add',itmadd.device)
            #self.devices_listout.addItem(itmadd.text())
            
    def addrm_in(self):
        """ Connecting receiving devices with dataqueue of this device
        """
        funcname = 'addrm_in'
        logger.debug(funcname)
        button = self.sender()
        if(button == self.arrinright):
            logger.debug(funcname + ': remove')
            ind = self.devices_listin.currentRow()
            self.devices_listin.takeItem(ind)
            
        elif(button == self.arrinleft):
            logger.debug(funcname + ': add')            
            itmadd = self.devices_listallin.currentItem()
            sen = itmadd.device
            itm = QtWidgets.QListWidgetItem(sen.name)
            itm.device = sen
            self.devices_listin.addItem(itm)
            

    def commit_clicked(self):
        """ Apply changes to the publishing/receiving devices
        """
        funcname = 'commit_clicked'
        logger.debug(funcname)
        outdevices = []
        # Add device as receiver for publishing devices
        for inditm in range(self.devices_listout.count()):
            itm = self.devices_listout.item(inditm)
            sen = itm.device
            outdevices.append(sen)
            logger.debug(funcname + ':' + 'add as publisher:' + str(sen))            
            addrm_device_as_data_provider(self.devices,sen,self.device,remove=False)

        # Check if there are devices to be removed
        data_provider = get_data_providing_devices(self.devices,self.device)
        for sen in data_provider:
            device = sen['device']
            if(device in outdevices):
                pass
            else:
                logger.debug(funcname + ': Removing device {:s} as a data publisher for {:s} '.format(self.device.name,device.name))
                addrm_device_as_data_provider(self.devices,device,self.device,remove=True)
                

        # Add device as publisher for receiving devices
        indevices = []        
        for inditm in range(self.devices_listin.count()):
            itm = self.devices_listin.item(inditm)
            sen = itm.device
            indevices.append(sen)
            logger.debug(funcname + ':' + 'add as receiver:' + str(sen))            
            addrm_device_as_data_provider(self.devices,self.device,sen,remove=False)

        # Check if there are devices to be removed
        data_receiver = get_data_receiving_devices(self.devices,self.device)
        for sen in data_receiver:
            device = sen['device']
            if(device in indevices):
                pass
            else:
                logger.debug(funcname + ': Removing device {:s} as a data receiver from {:s} '.format(self.device.name,device.name))                
                addrm_device_as_data_provider(self.devices,self.device,device,remove=True)            
            
            
    def update_list(self,device):
        """ Update the list
        """
        
        funcname = __name__ + '.update_list()'
        logger.debug(funcname + ':update_list:' + str(device))                        
        self.devices_listallin.clear()
        self.devices_listallout.clear()        
        self.devices_listin.clear()
        self.devices_listout.clear()
        self.devices_listcon.clear()
        self.device = device
        self.device_label.setText(device.name)
        
        if(len(self.devices) > 0):
            #self.devices_listcon.addItem(str(device))
            data_provider = get_data_providing_devices(self.devices,device)
            data_receiver = get_data_receiving_devices(self.devices,device)
            if(data_provider is not None):
                for s in data_provider:
                    sen = s['device']
                    itm = QtWidgets.QListWidgetItem(sen.name)
                    itm.device = sen            
                    self.devices_listout.addItem(itm)

            if(data_receiver is not None):                    
                for s in data_receiver:
                    sen = s['device']
                    itm = QtWidgets.QListWidgetItem(sen.name)
                    itm.device = sen
                    self.devices_listin.addItem(itm)


            # connecting devices
            for s in self.devices:
                sen = s['device']
                itm = QtWidgets.QListWidgetItem(sen.name)
                itm.device = sen            
                self.devices_listcon.addItem(itm)
                if(sen == device):
                    self.devices_listcon.setCurrentItem(itm)

            # data receiving devices
            if(device.publish):
                self.devices_listin.setEnabled(True)
                self.devices_listallin.setEnabled(True)
                for s in self.devices:
                    sen = s['device']
                    if(sen.subscribe == False):
                        continue
                    if(device == sen): # Dont list the device itself
                        continue                    
                           
                    itm = QtWidgets.QListWidgetItem(sen.name)
                    itm.device = sen            
                    self.devices_listallin.addItem(itm)
                
            else:
                self.devices_listin.setEnabled(False)                
                self.devices_listallin.setEnabled(False)
                
            # data providing devices
            if(device.subscribe):
                self.devices_listout.setEnabled(True)
                self.devices_listallout.setEnabled(True)
                for s in self.devices:
                    sen = s['device']
                    if(sen.publish == False):
                        continue
                    if(device == sen): # Dont list the device itself
                        continue
                    
                    itm = QtWidgets.QListWidgetItem(sen.name)
                    itm.device = sen            
                    self.devices_listallout.addItem(itm)
            else:
                self.devices_listout.setEnabled(False)                
                self.devices_listallout.setEnabled(False)                    
                    
            
    def disconnect_clicked(self):
        print('Disconnect')

    def itemcon_clicked(self,item):
        # Update the connection list 
        self.update_list(item.device)

    def itemcon_dclicked(self,item):
        if(item.isSelected()):
            item.setSelected(False)


#
# The main widget
#
class redvyprMainWidget(QtWidgets.QMainWindow):
    def __init__(self,width=None,height=None,config=None):
        super(redvyprMainWidget, self).__init__()
        self.setGeometry(50, 50, 500, 300)
        self.setWindowTitle("redvypr")
        #self.setWindowIcon(QtGui.QIcon('pythonlogo.png'))
        self.redvypr = redvyprWidget(config=config)
        self.setCentralWidget(self.redvypr)
        quitAction = QtWidgets.QAction("&Quit", self)
        quitAction.setShortcut("Ctrl+Q")
        quitAction.setStatusTip('Close the program')
        quitAction.triggered.connect(self.close_application)

        loadcfgAction = QtWidgets.QAction("&Load", self)
        loadcfgAction.setShortcut("Ctrl+O")
        loadcfgAction.setStatusTip('Load a configuration file')
        loadcfgAction.triggered.connect(self.load_config)

        pathAction = QtWidgets.QAction("&Devicepath", self)
        pathAction.setShortcut("Ctrl+L")
        pathAction.setStatusTip('Edit the device path')
        pathAction.triggered.connect(self.redvypr.show_devicepathwidget)                

        deviceAction = QtWidgets.QAction("&Add device", self)
        deviceAction.setShortcut("Ctrl+A")
        deviceAction.setStatusTip('Add a device')
        deviceAction.triggered.connect(self.open_add_device_widget)

        devcurAction = QtWidgets.QAction("&Go to device tab", self)
        devcurAction.setShortcut("Ctrl+D")
        devcurAction.setStatusTip('Go to the device tab')
        devcurAction.triggered.connect(self.gotodevicetab)        

        conAction = QtWidgets.QAction("&Connect devices", self)
        conAction.setShortcut("Ctrl+C")
        conAction.setStatusTip('Connect the input/output datastreams of the devices')
        conAction.triggered.connect(self.connect_device_gui)

        self.statusBar()

        mainMenu = self.menuBar()
        fileMenu = mainMenu.addMenu('&File')
        fileMenu.addAction(loadcfgAction)
        fileMenu.addAction(pathAction)
        fileMenu.addAction(quitAction)

        deviceMenu = mainMenu.addMenu('&Devices')
        deviceMenu.addAction(devcurAction)        
        deviceMenu.addAction(deviceAction)
        deviceMenu.addAction(conAction) 
        
        
        # Help and About menu
        helpAction = QtWidgets.QAction("&About", self)
        helpAction.setStatusTip('Information about the software version')
        helpAction.triggered.connect(self.about)
        
        helpMenu = mainMenu.addMenu('&Help')
        helpMenu.addAction(helpAction)

        self.show()

    def gotodevicetab(self):
        self.redvypr.devicetabs.setCurrentWidget(self.redvypr.devicesummarywidget)


    def connect_device_gui(self):
        self.redvypr.connect_device_gui()

    def about(self):
        self._about_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self._about_widget)
        label = QtWidgets.QLabel("Python based Realtime Data Viewer and Processor (redvypr)")
        label1 = QtWidgets.QLabel("Version: {:s}".format(str(version)))
        layout.addWidget(label)
        layout.addWidget(label1)
        self._about_widget.show()

    def open_add_device_widget(self):
        self.redvypr.open_add_device_widget()

    def load_config(self):
        self.redvypr.load_config()

    def close_application(self):
        self.redvypr.close_application()
            
        sys.exit()
        
    def closeEvent(self,event):
        self.close_application()


class deviceinfoWidget(QtWidgets.QWidget):
    """ A widget to display the general info of a device
    """
    device_start = QtCore.pyqtSignal(dict) # Signal requesting a start of the device (starting the thread)
    device_stop  = QtCore.pyqtSignal(dict) # Signal requesting a stop of device
    connect      = QtCore.pyqtSignal(dict) # Signal requesting a change of the connection

    def __init__(self,devicedict,redvyprwidget):
        super(deviceinfoWidget, self).__init__()
        self.devicedict = devicedict
        self.redvyprwidget = redvyprwidget
        self.devicetab = self.redvyprwidget.devicetabs # The parent tab with all devices listed
        self.namelabel = QtWidgets.QLabel(devicedict['device'].name)
        label = self.namelabel
        fsize         = label.fontMetrics().size(0, label.text())
        label.setFont(QtGui.QFont('Arial', fsize.height()+4))        
        #self.numlabel = QtWidgets.QLabel(str(devicedict['device'].numdevice))
        #label = self.numlabel
        #fsize         = label.fontMetrics().size(0, label.text())
        #label.setFont(QtGui.QFont('Arial', fsize.height()+4))                
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout2 = QtWidgets.QGridLayout()
        self.viewbtn = QtWidgets.QPushButton("View")
        self.viewbtn.clicked.connect(self.viewclicked)
        self.viewbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)        
        self.conbtn = QtWidgets.QPushButton("Connections")
        self.conbtn.clicked.connect(self.conclicked)
        self.conbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)
        self.rembtn = QtWidgets.QPushButton("Remove")
        self.rembtn.clicked.connect(self.remdevice)
        self.rembtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)        
        self.renbtn = QtWidgets.QPushButton("Rename")
        self.renbtn.clicked.connect(self.rendevice)
        self.renbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)        
        self.startbtn = QtWidgets.QPushButton("Start")
        self.startbtn.setCheckable(True)
        self.startbtn.clicked.connect(self.startstopclicked)
        self.startbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)
        self.infobtn = QtWidgets.QPushButton("Info")
        self.infobtn.clicked.connect(self.get_info)
        self.infobtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)                
        self.layout2.addWidget(QtWidgets.QLabel('Name' + ' Device #' + str(devicedict['device'].numdevice)),0,0)        
        self.layout2.addWidget(self.namelabel,1,0)
        self.layout.addLayout(self.layout2)
        self.layout.addStretch()
        self.layout.addWidget(self.viewbtn)
        self.layout.addWidget(self.infobtn)         
        self.layout.addWidget(self.renbtn)
        self.layout.addWidget(self.conbtn)
        self.layout.addWidget(self.rembtn)
        self.layout.addWidget(self.startbtn)

    def get_info(self):        
        self.infowidget       = QtWidgets.QPlainTextEdit()
        self.infowidget.setReadOnly(True)
        sortstat ={}
        for i in sorted(self.devicedict['statistics']):
            sortstat[i]=self.devicedict['statistics'][i]

        sortstat['datakeys'] = sorted(sortstat['datakeys'])
        statstr = yaml.dump(sortstat)
        self.infowidget.insertPlainText(statstr + '\n')
        self.infowidget.show()
        
        
    def viewclicked(self):
        self.redvyprwidget.devicetabs.setCurrentWidget(self.devicedict['widget'])        

    def conclicked(self):
        self.connect.emit(self.devicedict)

    def startstopclicked(self):
        funcname = __name__ + '.startstopclicked()'
        logger.debug(funcname)
        if(self.startbtn.text() == 'Stop'):
            self.device_stop.emit(self.devicedict)
        else:
            self.device_start.emit(self.devicedict)

    def thread_status(self,statusdict):
        """ Function regularly called by redvypr to update the thread status
        """
        status = statusdict['threadalive']
        if(status):
            self.startbtn.setText('Stop')
            self.startbtn.setChecked(True)            
        else:
            self.startbtn.setText('Start')
            self.startbtn.setChecked(False)                        

    def remdevice(self):
        """ Removing the device
        """
        ret = QtWidgets.QMessageBox.question(self,'', "Are you sure to remove the device?", QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ret == QtWidgets.QMessageBox.Yes:
            widget = self.devicedict['widget']
            for i in range(self.devicetab.count()):
                if(self.devicetab.widget(i) == widget):
                    self.redvyprwidget.closeTab(i)

    def rendevice(self):
        """ Renaming a device
        """
        oldname = self.devicedict['device'].name
        name, okPressed = QtWidgets.QInputDialog.getText(self, "Enter new name","Device name:", QtWidgets.QLineEdit.Normal, oldname)
        if okPressed and name != '':
            renamed = self.redvyprwidget.renamedevice(oldname,name)

#
#
#
# A logging handler for qplaintext
#
#
#
class QPlainTextEditLogger(logging.Handler):
    def __init__(self):
        super(QPlainTextEditLogger, self).__init__()

    def add_widget(self,widget):        
        self.widget = widget

    def emit(self, record):
        msg = self.format(record)
        self.widget.appendPlainText(msg)

    def write(self, m):
        pass            


#
#
#
# redvyprwidget
#
#
#

class redvyprWidget(QtWidgets.QWidget):
    """This is the main widget of redvypr. 

    """
    def __init__(self,width=None,height=None,config=None):
        """ Args: 
            config: Either a string containing a path of a yaml file, or a list with strings of yaml files
        """
        super(redvyprWidget, self).__init__()
        self.setGeometry(50, 50, 500, 300)
        # Lets create the heart of redvypr
        self.redvypr = redvypr() # Configuration comes later after all widgets are initialized
        
        self.redvypr.device_path_changed.connect(self.__populate_devicepathlistWidget)
        self.redvypr.device_added.connect(self._add_device)
        # Fill the layout
        self.devicetabs = QtWidgets.QTabWidget()
        self.devicetabs.setTabsClosable(True)
        self.devicetabs.tabCloseRequested.connect(self.closeTab)

        # The configuration of the redvypr
        self.create_devicepathwidget()
        self.create_statuswidget()
        #self.devicetabs.addTab(self.__devicepathwidget,'Status')
        self.devicetabs.addTab(self.__statuswidget,'Status')


        # A widget containing all connections
        self.create_devicewidgetsummary() # Creates self.devicesummarywidget
        self.devicetabs.addTab(self.devicesummarywidget,'Devices') # Add device summary widget
        # A logwidget
        self.logwidget = QtWidgets.QPlainTextEdit()
        self.logwidget.setReadOnly(True)
        self.logwidget_handler = QPlainTextEditLogger()
        self.logwidget_handler.add_widget(self.logwidget)
        self.devicetabs.addTab(self.logwidget,'Log') # Add a logwidget
        # Connect the logwidget to the logging
        logger.addHandler(self.logwidget_handler)
        #self.logwidget.append("Hallo!")

        # A timer to gather all the data from the devices
        self.devicereadtimer = QtCore.QTimer()
        self.devicereadtimer.timeout.connect(self.readguiqueue)
        self.devicereadtimer.start(100)
        #self.devicereadtimer.start(500)
        

        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.addWidget(self.devicetabs)
        if((width is not None) and (height is not None)):
            self.resize(int(width), int(height))
            
        if True:    
            # Configurating redvypr
            if(config is not None):
                if(type(config) == str):
                    config = [config]

                for c in config:
                    self.redvypr.parse_configuration(c)


        self.__populate_devicepathlistWidget()

    def renamedevice(self,oldname,name):
        """ Renames a devices
        """
        funcname = 'renamedevice()'
        for dev in self.redvypr.devices:
            devname = dev['device'].name
            if(devname == name): # Found a device with that name already, lets do nothging
                logger.debug(funcname + ': Name already in use. Will not rename')
                return False
            
        for dev in self.redvypr.devices:
            devname = dev['device'].name
            if(devname == oldname): # Found the device, lets rename it
                dev['device'].name = name
                widget = dev['widget']
                # Create a new infowidget
                dev['infowidget'].close()
                dev['infowidget'] = deviceinfoWidget(dev,self)
                dev['infowidget'].device_start.connect(self.redvypr.start_device_thread)
                dev['infowidget'].device_stop.connect(self.redvypr.stop_device_thread)
                dev['infowidget'].connect.connect(self.connect_device)                
                for i in range(self.devicetabs.count()):
                    if(self.devicetabs.widget(i) == widget):
                        self.devicetabs.setTabText(i,name)
                        break

                break
                
        self.update_devicewidgetsummary()
        return True
    
    def create_devicewidgetsummary(self):
        """ Creates the device summary widget
        """
        self.devicesummarywidget = QtWidgets.QWidget()
        self.devicesummarywidget_layout = QtWidgets.QVBoxLayout(self.devicesummarywidget)

    def update_devicewidgetsummary(self):            
        """ Updates the device summary widget
        """
        # Remove all
        for i in reversed(range(self.devicesummarywidget_layout.count())):
            item = self.devicesummarywidget_layout.itemAt(i)
            self.devicesummarywidget_layout.removeItem(item)

        # and refill it
        for i,devicedict in enumerate(self.redvypr.devices):
            self.devicesummarywidget_layout.addWidget(devicedict['infowidget'])

        self.devicesummarywidget_layout.addStretch()

    def readguiqueue(self):
        """This periodically called functions reads the guiqueue and calls
        the widgets of the devices update function (if they exist)

        """
        # Update devices
        for devicedict in self.redvypr.devices:
            device = devicedict['device']
            if True:
                # Feed the data into the modules/functions/objects and
                # let them treat the data
                for i,guiqueue in enumerate(devicedict['guiqueue']):
                    while True:
                        try:                    
                            data = guiqueue.get(block=False)
                            devicedict['gui'][i].update(data)
                        except Exception as e:
                            break


    def load_config(self):
        """ Loads a configuration file
        """
        funcname = __name__ + '.load_config()'                        
        logger.debug(funcname)
        conffile, _ = QtWidgets.QFileDialog.getOpenFileName(self,"QFileDialog.getOpenFileName()", "","Yaml Files (*.yaml);;All Files (*)")
        if conffile:
            self.redvypr.parse_configuration(conffile)



    def open_add_device_widget(self):
        """Opens a widget for the user to choose to add a device

        """
        self.add_device_widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(self.add_device_widget)
        self.__devices_list    = QtWidgets.QListWidget()
        self.__devices_list.itemClicked.connect(self.__device_name)
        self.__devices_info    = QtWidgets.QWidget()
        self.__devices_addbtn  = QtWidgets.QPushButton('Add')
        self.__devices_addbtn.clicked.connect(self.add_device_click)
        self.__devices_devnamelabel = QtWidgets.QLabel('Devicename')
        self.__devices_devname = QtWidgets.QLineEdit()
        self.__mp_label  = QtWidgets.QLabel('Multiprocessing options')
        self.__mp_thread = QtWidgets.QRadioButton('Thread')
        self.__mp_multi  = QtWidgets.QRadioButton('Multiprocessing')
        self.__mp_multi.setChecked(True)        
        self.__mp_group  = QtWidgets.QButtonGroup()
        self.__mp_group.addButton(self.__mp_thread)
        self.__mp_group.addButton(self.__mp_multi)
        layout.addRow(self.__devices_list,self.__devices_info)
        layout.addRow(self.__mp_label)
        layout.addRow(self.__mp_thread,self.__mp_multi)
        layout.addRow(self.__devices_devnamelabel,self.__devices_devname)                                
        layout.addRow(self.__devices_addbtn)
        # Searches for devices 
        self.redvypr.populate_device_path()
        # Create the info widget
        infolayout = QtWidgets.QFormLayout(self.__devices_info)        
        self.__devices_info_sourcelabel1 = QtWidgets.QLabel('Source:')
        self.__devices_info_sourcelabel2 = QtWidgets.QLabel('')
        self.__devices_info_sourcelabel3 = QtWidgets.QLabel('Path:')
        self.__devices_info_sourcelabel4 = QtWidgets.QLabel('')
        self.__devices_info_sourcelabel5 = QtWidgets.QLabel('Description:')
        self.__devices_info_sourcelabel6 = QtWidgets.QLabel('')                
        infolayout.addRow(self.__devices_info_sourcelabel1,self.__devices_info_sourcelabel2)
        infolayout.addRow(self.__devices_info_sourcelabel3,self.__devices_info_sourcelabel4)
        infolayout.addRow(self.__devices_info_sourcelabel5)
        infolayout.addRow(self.__devices_info_sourcelabel6)        

        # Populate the device list
        itms = []
        for d in self.redvypr.device_modules:
            itm = QtWidgets.QListWidgetItem(d['name'])
            itms.append(itm)
            self.__devices_list.addItem(itm)
            
        # set the first item as current and create a device name
        self.__devices_list.setCurrentItem(itms[0])
        self.__device_name()
        self.add_device_widget.show()

    def __device_info(self):
        """ Populates the self.__devices_info widget with the info of the module
        """
        ind = int(self.__devices_list.currentRow())
        infotxt = self.redvypr.device_modules[ind]['name']
        self.__devices_info_sourcelabel2.setText(infotxt)
        infotxt2 = self.redvypr.device_modules[ind]['source']
        self.__devices_info_sourcelabel4.setText(infotxt2)
        try:
            desctxt = self.relf.redvypr.device_modules[ind]['module'].description
        except:
            desctxt = ''

        self.__devices_info_sourcelabel6.setText(desctxt)        
        
    def __device_name(self):
        devicemodulename = self.__devices_list.currentItem().text()
        devicename = devicemodulename + '_{:d}'.format(self.redvypr.numdevice)
        self.__devices_devname.setText(devicename)
        self.__device_info()
        
    def add_device_click(self):
        """
        """
        devicemodulename = self.__devices_list.currentItem().text()
        thread = self.__mp_thread.isChecked()
        deviceconfig = {'name':str(self.__devices_devname.text())}
        self.redvypr.add_device(devicemodulename=devicemodulename,thread=thread,deviceconfig=deviceconfig)
        # Update the name
        self.__device_name()

    def _add_device(self,devicelist):
        """Function is called via the redvypr.add_device signal and is adding
        all the gui functionality to the device

        """
        funcname = __name__ + '.add_device()' 
        logger.debug(funcname)
        devicedict   = devicelist[0]
        ind_devices  = devicelist[1]
        devicemodule = devicelist[2]

        # First create the device and then do the widget stuff here
        device = devicedict['device']
        #
        # Now add all the widgets to the device
        #
        # Create the init widget
        try:
            deviceinitwidget = devicemodule.initDeviceWidget(device)
            deviceinitwidget.device_start.connect(self.redvypr.start_device_thread)
            deviceinitwidget.device_stop.connect(self.redvypr.stop_device_thread)
        except Exception as e:
            logger.debug(funcname + ': Widget does not have a deviceinitwidget or start/stop signals:' + str(e))
            deviceinitwidget = QtWidgets.QWidget() # Use a standard widget
            
        try:
            logger.debug(funcname + ': Connect signal connected')
            deviceinitwidget.connect.connect(self.connect_device)
        except Exception as e:
            logger.debug('Widget does not have connect signal:' + str(e))


        #
        # Check if we have a widget to display the data
        # Create the displaywidget
        #
        try:
            devicedisplaywidget = devicemodule.displayDeviceWidget
        except Exception as e:
            logger.debug(funcname + ': No displaywidget found for {:s}'.format(str(devicemodule)))
            # Using the standard display widget
            devicedisplaywidget = standard_device_widgets.displayDeviceWidget_standard

        devicewidget = QtWidgets.QWidget()
        devicelayout = QtWidgets.QVBoxLayout(devicewidget)
        devicetab = QtWidgets.QTabWidget()
        devicelayout.addWidget(devicetab)
        
        devicetab.addTab(deviceinitwidget,'Init') 
        # Devices can have their specific display objects, if one is
        # found, initialize it, otherwise just the init Widget
        if(devicedisplaywidget is not None):
            initargs = inspect.signature(devicedisplaywidget.__init__)
            initdict = {}
            if('device' in initargs.parameters.keys()):
                initdict['device'] = device

            if('tabwidget' in initargs.parameters.keys()):
                initdict['tabwidget'] = devicetab
                
            # https://stackoverflow.com/questions/334655/passing-a-dictionary-to-a-function-as-keyword-parameters
            devicedisplaywidget_called = devicedisplaywidget(**initdict)
                
            # Test if the widget has a tabname
            try:
                tabname = devicedisplaywidget_called.tabname
            except:
                tabname = 'Display data'
                
            devicetab.addTab(devicedisplaywidget_called,tabname)            
            # Append the widget to the processing queue
            self.redvypr.devices[ind_devices]['gui'].append(devicedisplaywidget_called)
            self.redvypr.devices[ind_devices]['initwidget'] = deviceinitwidget
        else:
            self.redvypr.devices[ind_devices]['initwidget'] = deviceinitwidget
                               
        
        self.redvypr.devices[ind_devices]['widget'] = devicewidget # This is the displaywidget
        # Create the infowidget (for the overview of all devices)
        self.redvypr.devices[ind_devices]['infowidget'] = deviceinfoWidget(self.redvypr.devices[ind_devices],self)
        self.redvypr.devices[ind_devices]['infowidget'].device_start.connect(self.redvypr.start_device_thread)
        self.redvypr.devices[ind_devices]['infowidget'].device_stop.connect(self.redvypr.stop_device_thread)
        self.redvypr.devices[ind_devices]['infowidget'].connect.connect(self.connect_device)
        
        #
        # Add the devicelistentry to the widget, this gives the full information to the device
        #
        self.redvypr.devices[ind_devices]['initwidget'].redvyprdevicelistentry = self.redvypr.devices[ind_devices]
        self.redvypr.devices[ind_devices]['gui'][0].redvyprdevicelistentry     = self.redvypr.devices[ind_devices]
        self.redvypr.devices[ind_devices]['initwidget'].redvypr = self.redvypr
        self.redvypr.devices[ind_devices]['gui'][0].redvypr     = self.redvypr
            
        self.devicetabs.addTab(devicewidget,device.name)
        self.devicetabs.setCurrentWidget(devicewidget)

        # All set, now call finalizing functions
        # Finalize the initialization by calling a helper function (if exist)
        try:
            deviceinitwidget.finalize_init()
        except Exception as e:
            logger.debug(funcname + ':finalize_init():' + str(e))        

        # Update the summary
        self.update_devicewidgetsummary()        

    def connect_device_gui(self):
        """ Wrapper for the gui
        """
        self.open_connect_widget(device = None)

    def connect_device(self,device):
        """ Handles the connect signal from devices, called when the connection between the device shall be changed
        """
        logger.debug('Connect clicked')
        if(type(device) == dict):
            device = device['device']
        self.open_connect_widget(device = device)

    def open_connect_widget(self,device=None):
        funcname = __name__ + '.open_connect_widget()'                
        logger.debug(funcname + ':' + str(device))
        self.__con_widget = redvyprConnectWidget(devices=self.redvypr.devices,device=device)        
        self.__con_widget.show()
        
        
    def __hostname_changed(self):
        hostname, ok = QtWidgets.QInputDialog.getText(self, 'redvypr hostname', 'Enter new hostname:')
        if ok:
            self.__hostname_line.setText(hostname)
            self.redvypr.config['hostname'] = hostname
            hostinfo['name'] = hostname


    def update_status(self):
        self.__status_dtneeded.setText(' (needed {:0.5f}s)'.format(self.redvypr.dt_avg_datadist))                

    def create_statuswidget(self):
        """Creates the statuswidget

        """
        self.redvypr.devicethreadtimer.timeout.connect(self.update_status) # Add to the timer another update
        self.__statuswidget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(self.__statuswidget)
        # dt
        self.__status_dt = QtWidgets.QLabel('Distribution time: {:0.5f}s'.format(self.redvypr.dt_datadist))
        self.__status_dtneeded = QtWidgets.QLabel(' (needed {:0.5f}s)'.format(self.redvypr.dt_avg_datadist))        

        layout.addRow(self.__status_dt,self.__status_dtneeded)

        # Hostname
        self.__hostname_label = QtWidgets.QLabel('Hostname:')
        self.__hostname_line  = QtWidgets.QLabel('')
        self.__hostname_line.setAlignment(QtCore.Qt.AlignRight)
        self.__hostname_line.setText(hostinfo['name'])
        self.__hostname_btn = QtWidgets.QPushButton('Change hostname')
        self.__hostname_btn.clicked.connect(self.__hostname_changed)

        layout.addRow(self.__hostname_label,self.__hostname_line)
        layout.addRow(self.__hostname_btn)

        self.__statuswidget_pathbtn = QtWidgets.QPushButton('Edit device path')
        self.__statuswidget_pathbtn.clicked.connect(self.show_devicepathwidget)
        layout.addRow(self.__statuswidget_pathbtn)


    def show_devicepathwidget(self):
        """A widget to show the pathes to search for additional devices

        """
        self.__devicepathwidget.show()
    def create_devicepathwidget(self):
        """A widget to show the pathes to search for additional devices

        """
        self.__devicepathwidget = QtWidgets.QWidget()
        self.__devicepathlab = QtWidgets.QLabel('Devicepathes') # Button to add a path        
        self.__deviceaddpathbtn = QtWidgets.QPushButton('Add') # Button to add a path
        self.__deviceaddpathbtn.clicked.connect(self.adddevicepath)
        self.__devicerempathbtn = QtWidgets.QPushButton('Remove') # Button to remove a path
        self.__devicerempathbtn.clicked.connect(self.remdevicepath)
        layout = QtWidgets.QFormLayout(self.__devicepathwidget)
        self.__devicepathlist = QtWidgets.QListWidget()
        layout.addRow(self.__devicepathlab)        
        layout.addRow(self.__devicepathlist)
        layout.addRow(self.__deviceaddpathbtn,self.__devicerempathbtn)
        self.__populate_devicepathlistWidget()

    def __populate_devicepathlistWidget(self):
        self.__devicepathlist.clear()
        for d in self.redvypr.device_paths:
            itm = QtWidgets.QListWidgetItem(d)
            self.__devicepathlist.addItem(itm)

    def adddevicepath(self):
        """Adds a path to the devicepathlist
        """
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Devicepath', '')
        if folder:
            self.redvypr.adddevicepath(folder)

    def remdevicepath(self):
        """Removes the selected device pathes
        """
        ind = self.__devicepathlist.currentRow()
        rempath = self.__devicepathlist.item(ind).text()
        # Remove from the main widget and redraw the whole list (is done by the signal emitted by redvypr)
        self.redvypr.remdevicepath(rempath)


    def closeTab (self, currentIndex):
        """ Closing a device tab and stopping the device
        """
        logger.debug('Closing the tab now')
        currentWidget = self.devicetabs.widget(currentIndex)
        # Search for the corresponding device
        for sendict in self.redvypr.devices:
            if(sendict['widget'] == currentWidget):
                device = sendict['device']
                if(sendict['thread'] == None):
                    pass
                elif(sendict['thread'].is_alive()):
                    device.comqueue.put('stop')                

                # Close the widgets (init/display)
                currentWidget.close()
                # Info
                sendict['infowidget'].close()
                self.redvypr.devices.remove(sendict)
                self.devicetabs.removeTab(currentIndex)
                break
                
        self.update_devicewidgetsummary()
        
    def close_application(self):
        print('Closing!')
        try:
            self.add_device_widget.close()
        except:
            pass

        for sendict in self.redvypr.devices:
            self.redvypr.stop_device_thread(sendict['device'])

        time.sleep(1)
        for sendict in self.redvypr.devices:        
            try:
                sendict['thread'].kill()
            except:
                pass
            
        #sys.exit()        
        
    def closeEvent(self,event):
        self.close_application()
                

#
#
# Main function called from os
#
#
#

def redvypr_main():
    print("Python based REaltime Data VYewer and PlotteR  (REDVYPR)")
    
    redvypr_help      = 'redvypr'
    config_help       = 'Using a yaml config file'
    config_help_nogui = 'start redvypr without a gui'
    config_help_path  = 'add path to search for redvypr modules'
    config_help_hostname  = 'hostname of redvypr, overwrites the hostname in a possible configuration '            
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action='count')
    parser.add_argument('--config', '-c',help=config_help)
    parser.add_argument('--nogui', '-ng',help=config_help_nogui,action='store_true')
    parser.add_argument('--add_path', '-p',help=config_help_path)
    parser.add_argument('--hostname', '-hn',help=config_help_hostname)        
    parser.set_defaults(nogui=False)
    args = parser.parse_args()

    logging_level = logging.INFO
    if(args.verbose == None):
        logging_level = logging.INFO      
    elif(args.verbose >= 1):
        print('Debug logging level')
        logging_level = logging.DEBUG
        

    logger.setLevel(logging_level)
    
    # Check if we have a redvypr.yaml, TODO, add also default path
    config_all = []
    if(os.path.exists('redvypr.yaml')):
        config_all.append('redvypr.yaml')

    # Add the configuration
    config = args.config
    if(config is not None):
        config_all.append(config)    

    # Add hostname
    if(args.hostname is not None):
        hostconfig = {'hostname':args.hostname}
        config_all.append(hostconfig)
        
    print('Config',config_all)
    print('Flag nogui',args.nogui)

    # Adding device module pathes
    if(args.add_path is not None):
        print('devicepath',args.add_path)        
        modpath = os.path.abspath(args.add_path)
        print('devicepath',args.add_path,modpath)
        configp = {'devicepath':modpath}
        print('Modpath',modpath)
        if(config == None):
            config = []

        config.append(configp)
        
    # GUI oder command line?
    if(args.nogui):
        def handleIntSignal(signum, frame):
            '''Ask app to close if Ctrl+C is pressed.'''
            print('Received CTRL-C: Closing now')
            sys.exit()
            
        signal.signal(signal.SIGINT, handleIntSignal)        
        app = QtCore.QCoreApplication(sys.argv)
        redvypr_obj = redvypr(config=config_all,nogui=True)
        sys.exit(app.exec_())
    else:
        app = QtWidgets.QApplication(sys.argv)
        screen = app.primaryScreen()
        print('Screen: %s' % screen.name())
        size = screen.size()
        print('Size: %d x %d' % (size.width(), size.height()))
        rect = screen.availableGeometry()
        print('Available: %d x %d' % (rect.width(), rect.height()))
        ex = redvyprMainWidget(width=rect.width()/2,height=rect.height()*2/3,config=config_all)
        sys.exit(app.exec_())


if __name__ == '__main__':
    redvypr_main()
    



