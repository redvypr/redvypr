"""
.. _netCDF: https://www.unidata.ucar.edu/software/netcdf/
.. _netCDFtype:http://www-c4.ucsd.edu/netCDF/netcdf-guide/guide_9.html#SEC56

The netCDF logger device allows to write data to a `netCDF`_ file, a common data format used in the geophysical community. 


Configuration options for a netCDF logger:

.. code-block::

    - deviceconfig:
    name: nclogger
    config:
      filename: 'randdata_test.nc'
      zlib: True
      nsync: 100 # The number of datasets after which the nc file is synced 
      dt_newfile: 3600 # Number of seconds after a new file is created.
      groups: # Groups are used to save variables of different devices
        - name: hflow # Name of the group as it appears in the netCDF file
          devices: # List of devices the groups saves data to
            - testranddata
          variables: # keys of the data dictionaries the logger looks for data
            - name: randdata # The variable name as it appears in the netCDF file
              key: data # The key, as it appears in the data dictionary of the device
              type: float # byte, char, short, long, float, double, the datatype of the data entry, see also table here `netCDFtype`_
              attributes: # Add attributes to the variable
                - name: 'serialnumber'
                  key: sn # The 'key' key is used to dynamically add the data of data[key]
                - name: 'experiment'
                  value: 'testexperiment' # The value key is used to statically write the attribute
                  

  devicemodulename: netcdflogger


"""
import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys, os
import netCDF4
import copy
import pkg_resources
import yaml
from redvypr.data_packets import device_in_data, get_devicename_from_data, get_keys_from_data
from redvypr.version import version


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('netcdflogger')
logger.setLevel(logging.DEBUG)


description = 'Logs data into a netCDF file.'

# A standard config of the netCDF logger
standard_config = {}
standard_config['dt_newfile'] = -1 # Seconds after which a newfile will be opened
standard_config['groups'] = []
standard_config['zlib'] = True
standard_config['file_timestamp']=True
#standard_config['file_counter']  =True
standard_config['filename']='netcdfdata.nc'
standard_config['attributes'] = [{'name':'description','value':'Description of the dataset'},{'name':'history','value':'Created by redvypr netcdflogger ({:s})'.format(version)}]

standard_group = {'name':'newgroup','variables':[],'devices':[]}

standard_variable = {'name':'newvariable','attributes':[]}
standard_variable['attributes'].append({'name':'units','value':'Unit of the variable'})
standard_variable['attributes'].append({'name':'long_name','value':'Long description'})
standard_variable['type'] = 'float'
standard_variable['key'] = 'key'

standard_attribute = {'name':'newattribute','value':'attvalue','key':'attribute key'}

def create_ncfile(config,update=False,nc=None):
    """ Creates a netcdf file
    Args:
       config (dict): The configuration dictionary, see the Device class documentation for the structure of the dict
    """
    funcname = __name__ + '.create_ncfile()'
    if(update):
        logger.debug(funcname + ':Modifying file')
    else:
        logger.debug(funcname + ':Creating file')
    # Create the file
    tfile = time.time()
    filename = config['filename']
    confignc = copy.deepcopy(config) # Make a real copy of the config
    # Test if we have a newfile option, add a timestring into the filename
    try:
       config['file_timestamp']
    except:
       config['file_timestamp'] = True
    if(config['file_timestamp']):
       tstr = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
       (filebase,fileext)=os.path.splitext(filename)
       filename = filebase + '_' + tstr + fileext
       if(update):
            filename = config['ncfilename']
           

    if(update):
        pass # Use the ncfile in nc
    else:
        try:
            nc = netCDF4.Dataset(filename,'w')
            logger.debug(funcname + ': Opened file: {:s}'.format(filename))            
        except Exception as e:
            logger.warning(funcname + ': Error opening file:' + str(filename) + ':' + str(e))
            return

    # Create the groups
    for igroup,group in enumerate(confignc['groups']):
        if('*' in group['name']): # Check if we have a expansion, if yes, skip that
            logger.debug(funcname + ': Skipping group {:s}'.format(group['name']))
        else:
            if(group['name'] not in nc.groups.keys()): # Check if the nc file has already the group
                logger.debug(funcname + ': Creating group {:s}'.format(group['name']))                
                ncg = nc.createGroup(group['name'])
                group['__nc__'] = ncg # Save the group in the config dictionary
                # Create unix time as the unlimited dimension, here the time of the redvypr host is saved
                tdim = ncg.createDimension('tu',size=None)
                tvar = ncg.createVariable('tu',np.float,('tu'),zlib=config['zlib'])
                tvar.units = 'seconds since 1970-01-01 00:00:00' # Unix time                                
                nvar = ncg.createVariable('numpacket',np.int,('tu'),zlib=config['zlib'])                
                
            else:
                logger.debug(funcname + ': Group {:s} exists already'.format(group['name']))
                ncg = nc.groups[group['name']]
                group['__nc__'] = ncg # Save the group in the config dictionary                

            print('Hallo0',group['variables'])
            for ikey,key in enumerate(group['variables']):
                print('Hallo',key)
                if('name' in key.keys()):
                    if(key['name'] not in ncg.variables.keys()):                    
                        logger.debug(funcname + ': Creating variable {:s}'.format(key['name']))                    
                        ncvar = ncg.createVariable(key['name'],key['type'],('tu'),zlib=config['zlib'])
                        key['nwritten'] = 0
                        config['groups'][igroup]['variables'][ikey]['nwritten'] = key['nwritten'] # Put it also in the original config
                        try:
                            ncvar.units = key['units']
                        except:
                            pass
                    else:
                        logger.debug(funcname + ': Variable {:s} exists already'.format(key['name']))                                                
                else:
                    logger.warning(funcname + ': Variable does not have a name key, will not create it')
                    

    # This could be replaced by configdata object
    confignc['__nc__'] = nc
    confignc['ncfilename'] = filename
    config['ncfilename'] = filename    
    return [nc,confignc,config] # Give back the modified dictionary with the nc references and the original one

def start(datainqueue,dataqueue,comqueue,statusqueue,dataoutqueues=[],
          config=None):
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Opening writing:')
    dt_status = 5 # Send every 5 seconds a status packet
    
    # Keys: list of the keys used in the data dictionary
    # 'name': name of the variable created in netCDF
    # 'key': name of the keys in the dictionary
    # 'type': datatype of the data [optional, default numpy.float]
    
    try:
        config['nsync']
    except:
        config['nsync'] = 1000
        
    [nc,config,configstatus] = create_ncfile(config)
    configstatus2 = {'status':'{:s}: Created new file: '.format(str(datetime.datetime.now())) + config['ncfilename'] + '\n'}    
    # Send a status about the newly created file
    try:
        statusqueue.put_nowait(configstatus)
        statusqueue.put_nowait(configstatus2)        
    except Exception as e:
        pass

    tfile   = time.time() # Save the time the file was created
    tstatus = time.time() # Save the time for status
    packets_written = 0
    while True:
        try:
            com = comqueue.get(block=False)
            logger.debug(funcname + ': received:' + str(com))
            # Closing all open files
            try:
                logger.info(funcname + ':Closing ncfile')
                nc.close()
                fsize = os.path.getsize(config['ncfilename'])
                configstatus3 = {'status':'{:s}: Closed file: {:s}. Size: {:d} bytes'.format(str(datetime.datetime.now()),config['ncfilename'],fsize) + '\n{:s}: Stopping netCDF logger.\n'.format(str(datetime.datetime.now()))}
                statusqueue.put_nowait(configstatus3)                
            except Exception as e:
                logger.debug(funcname + ': could not close netcdfile')
                
            logger.info(funcname + ':Stopping now')
            break
        except Exception as e:
            #logger.warning(funcname + ': Error stopping thread:' + str(e))
            pass


        time.sleep(0.05)
        # Check if a newfile needs to be created
        tcheck = time.time()
        newfile = False
        try:
            dt = tcheck - tfile
            if((config['dt_newfile'] > 0) and (config['dt_newfile'] <= dt)):
                logger.info(funcname + ': Will create a new file')
                newfile = True
                tfile = tcheck
        except:
            pass


        # Send some status every tstatus seconds
        dt = tcheck - tstatus
        if(dt_status <= dt):
            tstatus = tcheck
            try:                
                statusqueue.put_nowait(configstatus)
            except Exception as e:
                pass



        if(newfile):
            nc.close()
            fsize = os.path.getsize(config['ncfilename'])
            configstatus3 = {'status':'{:s}: Closed file: {:s}. Size: {:d} bytes'.format(str(datetime.datetime.now()),config['ncfilename'],fsize) + '\n'}                            
            [nc,config,configstatus] = create_ncfile(configstatus) # The original config is with the netcdf object, so a backup is created as configstatus
            logger.info(funcname + ': Created new file: ' + config['ncfilename'])
            configstatus2 = {'status':'{:s}: Created new file: '.format(str(datetime.datetime.now())) + config['ncfilename'] + '\n'}                
            try:
                statusqueue.put_nowait(configstatus3)
                statusqueue.put_nowait(configstatus2)                
                statusqueue.put_nowait(configstatus)
            except Exception as e:
                pass            
        # First read all the data
        data_all = []
        while(datainqueue.empty() == False):
            data_all.append(datainqueue.get(block=False))
            if(len(data_all) > 100):
                if(datainqueue.empty() == False):
                    logger.warning(funcname + ': Could not empty datainqueue (overflow ...)')
                break

        for data in data_all:
            try:
                # Check if the devices are in the group
                for igroup,group in enumerate(config['groups']):
                    # Check first if we have an automatic group, that needs to be expanded
                    if('*' in group['name']):
                        # Found an expansion, here a "real" group will be created based on the data packet.
                        groupname = data['host']['name']
                        devicename_exp = get_devicename_from_data(data) # This will be the groupname
                        # Check if the group is already existing
                        flag_group_exists = False
                        for group_test in config['groups']:
                            if(group_test['name'] == devicename_exp):
                                flag_group_exists = True
                                #logger.debug(funcname + 'Group exists, saving it')
                        if(flag_group_exists == False): # Does not exist, create new group entry (the '*' entry will be kept as well)
                            logger.debug(funcname + ':Found expansion {:s} for device: {:s}'.format(group['name'],devicename_exp))
                            logger.debug(funcname + ': Will create group:' + devicename_exp)
                            newgroup     = {'name':devicename_exp,'devices':[],'variables':[]}
                            newgroup['devices'].append(devicename_exp)
                            # Create variables based on the data packet
                            newvariables = get_keys_from_data(data)
                            
                            for nvar in newvariables:
                                # Check if data can be converted to a float
                                if(type(data[nvar]) == list):
                                    if(len(data[nvar])>0):
                                        testdata = data[nvar][0]
                                    else:
                                        testdata= 'somestring'
                                else:
                                    testdata = data[nvar]
                                 
                                if(type(testdata)==str):
                                    continue   
                                try:
                                    float(testdata)
                                except:
                                    continue
                                
                                logger.debug(funcname + ': Will add variable:' + nvar)
                                newvar = {'name':nvar,'key':nvar,'type':float}

                                newgroup['variables'].append(newvar)
                                
                            configstatus['groups'].append(newgroup)
                            print('newgroup ...',newgroup)
                            # Update the nc file with the new group
                            [nc,config,configstatus] = create_ncfile(configstatus,update=True,nc=nc) # The original config is with the netcdf object, so a backup is created as configstatus
                    else:
                        flag_saved_data = False
                        [flag_data_save,devicename,expanded] = device_in_data(group['devices'],data,get_devicename=True) # Check i
                        if((flag_data_save) or (len(group['devices']) == 0)): # If devices is empty take all
                            # Check if the devicename was expanded, if yes variables need to be created automically
                            if(expanded):
                                pass

                            ind = len(group['__nc__'].variables['tu'])
                            # Get the data with the given keys
                            for ikey,key in enumerate(group['variables']):
                                # Check if the structure has the key
                                flag_saved_data = True                            
                                if(key['key'] in data):
                                    # Check if its a single variable or a list
                                    if(type(data[key['key']]) == list):
                                        indsave = [ind + i for i in range(len(data[key['key']]))]
                                    else:
                                        indsave = ind                                                     
                                    variable = group['__nc__'].variables[key['name']]
                                    variable[indsave] = data[key['key']]
                                    key['nwritten'] += 1
                                    configstatus['groups'][igroup]['variables'][ikey]['nwritten'] = key['nwritten']
                                    # Check if we set attributes as well
                                    if('attributes' in key.keys()):
                                        for attribute in key['attributes']:
                                            if(('key' in attribute.keys()) and ('name' in attribute.keys())): # Does the attribute has a key, then use it as a key in the data packet
                                                setattr(variable,attribute['name'],data[attribute['key']])
                                            elif(('value' in attribute.keys()) and ('name' in attribute.keys())): # This can also be done in create netcdf as it is static
                                                setattr(variable,attribute['name'],attribute['value'])
                                            else:
                                                pass

                            # If any data was saved, save time and numpacket as well
                            if flag_saved_data:
                                group['__nc__'].variables['tu'][indsave]        = data['t']
                                group['__nc__'].variables['numpacket'][indsave] = data['numpacket']
                                packets_written += 1
                                # Check if we want to sync
                                if(packets_written%config['nsync'] == 0):
                                    logger.debug(funcname + ': Syncing nc file (ndatasets {})'.format(packets_written))
                                    nc.sync()


            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))
                
    logger.info(funcname + 'stopped')

class Device():
    """This is a netCDF4 logger. It reads the dictionary packets from
    redvypr and saves them into a netCDF file. 
    """
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None,statusqueue=None):
        """
        """
        self.publish     = False # publishes data, a typical device is doing this
        self.subscribe   = True  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.statusqueue = statusqueue        
        self.statusstr = ''
        self.statusfile = {}        
        self.config = copy.deepcopy(standard_config)
        
    def start(self):
        config = self.config
        self.check_config(config)
        start(self.datainqueue,self.dataqueue,self.comqueue,self.statusqueue,config=config)

    def check_config(self,config):
        """ Checks the configuration for missing things
        """
        pass

    def status(self):
        """ Function that reads the statusqueue and returns the read data
        """
        funcname = __name__ + '.status()'
        #logger.debug(funcname)
        try:
            self.statusdata = self.statusqueue.get_nowait()
        except:
            return None

        if('status' in self.statusdata.keys()):
            self.statusstr = self.statusdata['status']
        elif('filename' in self.statusdata.keys()):
            self.statusfile = copy.deepcopy(self.statusdata)

        return self.statusstr        
        
    def __str__(self):
        sstr = 'netcdflogger'
        return sstr

#
#
#
# The gui stuff
#
#
#
class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device)
    device_stop = QtCore.pyqtSignal(Device)        
    def __init__(self,device=None):
        funcname = __name__ + ':initDeviceWidget()'
        super(QtWidgets.QWidget, self).__init__()
        try:        
            layout        = QtWidgets.QGridLayout(self)
            label = QtWidgets.QLabel('netCDF logger')
            self.startbtn = QtWidgets.QPushButton("Start logging")
            self.startbtn.clicked.connect(self.start_clicked)
            self.startbtn.setCheckable(True)                    
            self.additem = QtWidgets.QPushButton('Add') # General purpose add button (groups, variables)
            self.additem.setEnabled(False)
            self.remitem = QtWidgets.QPushButton('Rem') # General purpose remove button (groups, variables)
            self.remitem.setEnabled(False)                                    
            self.getcfg = QtWidgets.QPushButton('Get configuration') # Button to get the configuration
            self.layout   = layout
            self.device   = device
            self.config_widgets = [] # A list of widgets used for configuration
            self.config = self.device.config
            logger.debug(funcname)
            layout.addWidget(label,0,0,1,3)
            self.layout.addWidget(self.additem,2,0)
            self.layout.addWidget(self.remitem,2,1)            
            self.layout.addWidget(self.getcfg,2,2)
            self.layout.addWidget(self.startbtn,3,0,1,3)                                            
            self.create_nctree(self.config)
            self.nctree.currentItemChanged.connect(self.selection_changed) # signal connect
            self.layout.addWidget(self.nctree,1,0,1,3)
            self.config_widgets.append(self.nctree)

            
            self.additem.clicked.connect(self.add_item)
            self.remitem.clicked.connect(self.rem_item)            
            self.getcfg.clicked.connect(self.get_config)

            self.selected_item = None
        except Exception as e:
            logger.debug(funcname + ':'+str(e))
            

    def finalize_init(self):
        """This is called after the device is added and configured using a
        configuration file

        """
        pass
        #self.nctree.close()
        #self.create_nctree(self.config)

    def selection_changed(self,new,old):
        """ Function that handles a changed selection of the nctree
        """
        funcname = __name__ + 'selection_changed():'
        try:
            oldtext = old.text(0)
        except:
            oldtext = 'None'
        try:
            newtext = new.text(0)
        except:
            newtext = 'None'
            
        #logger.debug(funcname + 'changed from ' + str(oldtext)  + ' to ' + str(newtext))
        self.selected_item = new
        # Get the parent topic
        try:
            parenttext = new.parent().text(0)
        except:
            parenttext = ''
            
        if('attributes' in parenttext.lower()):
            self.remitem.setEnabled(True)
            self.remitem.setText('Remove attribute')            
        elif('variables' in parenttext.lower()):
            self.remitem.setEnabled(True)
            self.remitem.setText('Remove variable')
        elif('groups' in parenttext.lower()):
            self.remitem.setEnabled(True)
            self.remitem.setText('Remove group')
        elif('devices' in parenttext.lower()):
            self.remitem.setEnabled(True)
            self.remitem.setText('Remove device')            
        else:
            self.remitem.setEnabled(False)
            self.remitem.setText('Rem')                        

        # check if we have a variable
        try:
            itemtext = new.text(0)
        except:
            itemtext = ''
            
        if('variables' in itemtext.lower()):
            self.additem.setEnabled(True)
            self.additem.setText('Add variable')
        elif('groups' in itemtext.lower()):
            self.additem.setEnabled(True)
            self.additem.setText('Add group')
        elif('attributes' in itemtext.lower()):
            self.additem.setEnabled(True)
            self.additem.setText('Add attribute')
        elif('devices' in itemtext.lower()):
            self.additem.setEnabled(True)
            self.additem.setText('Add device')                        
        else:
            self.additem.setEnabled(False)
            self.additem.setText('Add')            

    def create_nctree(self,config):
        self.nctree = ncViewTree(config)

    def add_item(self):
        funcname = __name__ + '.add_item():'
        groupname = 'newgroup'
        logger.debug(funcname)
        if('Add variable' in self.additem.text()):
            logger.debug(funcname + 'Add variable')
            varname = 'newvar'
            self.nctree.add_variable(self.selected_item,varname)
        elif('Add group' in self.additem.text()):
            logger.debug(funcname + ' Add group')            
            self.nctree.add_group(self.selected_item)
        elif('Add attribute' in self.additem.text()):
            logger.debug(funcname + ' Add attribute')            
            self.nctree.add_attribute(self.selected_item,'newattribute','')
        elif('add device' in self.additem.text().lower()):
            logger.debug(funcname + ' Add device')            
            self.nctree.add_device(self.selected_item)            
        else:
            logger.warning(funcname + ': This shouldnt happen.')

    def rem_item(self):
        funcname = __name__ + '.rem_item():'
        logger.debug(funcname)
        if('remove variable' in self.remitem.text().lower()):
            logger.debug(funcname + 'Remove variable')
            self.nctree.rem_variable(self.selected_item)
        elif('remove group' in self.remitem.text().lower()):
            groupname = self.selected_item.text(0)
            logger.debug(funcname + 'Remove group {:s}'.format(groupname))
            self.nctree.rem_group(self.selected_item)
        elif('remove attribute' in self.remitem.text().lower()):
            attrname = self.selected_item.text(0)
            logger.debug(funcname + 'Remove attribute {:s}'.format(attrname))
            self.nctree.rem_attribute(self.selected_item)
        elif('remove device' in self.remitem.text().lower()):
            attrname = self.selected_item.text(0)
            logger.debug(funcname + 'Remove device {:s}'.format(attrname))
            self.nctree.rem_device(self.selected_item)                        
        
    def thread_status(self,status):
        self.update_buttons(status['threadalive'])

    def update_buttons(self,thread_status):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """
        # Running
        if(thread_status):
            self.startbtn.setText('Stop')
            self.startbtn.setChecked(True)
            for w in self.config_widgets:
                w.setEnabled(False)
        # Not running
        else:
            self.startbtn.setText('Start')
            for w in self.config_widgets:
                w.setEnabled(True)

            # Check if an error occured and the startbutton 
            if(self.startbtn.isChecked()):
                self.startbtn.setChecked(False)

    def get_config(self):
        config = self.nctree.get_config()
        self.configtext = QtWidgets.QPlainTextEdit()
        self.configtext.setReadOnly(True)
        config_full = {}
        config_full['devicemodulename'] = 'netcdflogger'
        config_full['loglevel'] = 'info'
        deviceconfig = {'name':'ncloggername','config':config}
        config_full['deviceconfig'] = deviceconfig
        yamlstr = yaml.dump(config_full)
        self.configtext.insertPlainText(yamlstr)
        self.configtext.show()


    def start_clicked(self):
        funcname = __name__ + '.start_clicked()'
        button = self.sender()
        config_gui = self.nctree.get_config()
        if button.isChecked():
            # Setting the configuration
            logger.debug(funcname + ': Starting logger with config: ' + str(config_gui))
            self.device.config = config_gui
            self.device_start.emit(self.device)
            button.setText("Starting")
        else:
            self.device_stop.emit(self.device)
            button.setText("Stopping")        
        

        

#
#
# displayDeviceWidget
#
#
class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device = None):
        super(QtWidgets.QWidget, self).__init__()
        layout          = QtWidgets.QVBoxLayout(self)
        hlayout         = QtWidgets.QHBoxLayout()        
        layout.addLayout(hlayout)
        self.layout     = layout
        self.text       = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)
        layout.addWidget(self.text)        
        # A timer that is regularly calling the device.status function
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_status)
        self.statustimer.start(2000)
        self.device = device
        self.oldstatusstr = ''

        self.nctree = None
        
    def update(self,data):
        pass
        #self.byteslab.setText("Bytes written: {:d}".format(data['bytes_written']))
        #self.packetslab.setText("Packets written: {:d}".format(data['packets_written']))
        #self.text.insertPlainText(str(data['data']) + '\n')

    def update_status(self):
        """
        """
        funcname = __name__ + '.update_status():'
        if True:
            while True:
                statusdata = self.device.status() # A string showing the status
                if((statusdata == None) or (len(statusdata) == 0)):
                    break

                statusfile = self.device.statusfile
                if(self.nctree is not None):
                    #logger.debug(funcname + 'update tree')
                    try:
                        self.nctree.update(statusfile)
                    except: # This is a lazy version of creating a whole new tree if the update fails
                        logger.debug(funcname + ' Update failed, creating a new tree')                        
                        self.layout.removeWidget(self.nctree)
                        self.nctree.close()
                        self.nctree = ncViewTree(statusfile,editable=False)
                        self.layout.addWidget(self.nctree)                        
                        
                else:
                    self.nctree = ncViewTree(statusfile,editable=False)
                    self.layout.addWidget(self.nctree)

                if(statusdata is not self.oldstatusstr):
                    self.oldstatusstr = statusdata
                    self.text.insertPlainText(statusdata)


#
# Custom object to store optional data as i.e. qitem, but does not
# pickle it, used to get original data again
#
class configdata():
    """This is a class that stores the original data and potentially
    additional information, if it is pickled it is only returning
    self.value but not potential additional information

    """
    def __init__(self, value):
        self.value = value
    def __reduce__(self):
        return (type(self.value), (self.value, ))    
        
        
class ncViewTree(QtWidgets.QTreeWidget):
    """ Qtreewidget that display and modifies a netcdf file
    """
    def __init__(self, config = {},editable=True):
        super().__init__()
        if(config == {}): # Create a standard configuration
            config = standard_config
            
        self.config      = copy.deepcopy(config) # Make a copy of the dictionary
        self.create_qtree(self.config,editable=editable)
        
        # make only the first column editable        
        self.setEditTriggers(self.NoEditTriggers)
        #self.header().setVisible(False)

    def checkEdit(self, item, column):
        """ Helper function that only allows to edit column 1
        """
        funcname = __name__ + '.checkEdit():'
        if column == 1:
            self.editItem(item, column)

    def current_item_changed(self,current,previous):
        """ Save the data in the currently changed item, this is used to
        restore if newly entered data is not valid
        """
        self.backup_data = current.text(1)
        
    def item_changed(self,item,column):
        """ Updates the dictionary with the changed data
        """
        funcname = __name__ + '.item_changed():'
        #logger.debug(funcname + 'Changed {:s} {:d} to {:s}'.format(item.text(0),column,item.text(1)))
        # Parse the string given by the changed item using yaml
        try:
            pstring = "a: {:s}".format(item.text(1))
            yparse = yaml.safe_load(pstring)
            newdata = yparse['a']
        except Exception as e: # Could not parse, use the old, valid data as a backup
            logger.debug(funcname + '{:s}'.format(str(e)))            
            pstring = "a: {:s}".format(self.backup_data)
            yparse = yaml.safe_load(pstring)
            newdata = yparse['a']
            item.setText(1,self.backup_data)


        # Change the dictionary 
        try:
            key = item._ncconfig_key
            if(type(item._ncconfig_[key]) == configdata):
               item._ncconfig_[key].value = newdata # The newdata, parsed with yaml               
            else:
               item._ncconfig_[key] = newdata # The newdata, parsed with yaml
               
        except Exception as e:
            logger.debug(funcname + '{:s}'.format(str(e)))

        # If its an attribute, change the attributes parent name as well
        try:
            parenttext = item.parent().parent().text(0).lower()
        except:
            parenttext = ''
        if(('attributes' in parenttext) and ('name' in item.text(0).lower())):
            # Change the attributes name
            item.parent().setText(0,item.text(1))

        if(('groups' in parenttext) and ('name' in item.text(0).lower())):
            # Change the groups name
            item.parent().setText(0,item.text(1))            

        
    def add_group(self,item,groupname=None):
        """Adds a new group, if its None, use the locally marked group, not TESTED

        """
        funcname = __name__ + '.add_group():'
        vardict = copy.deepcopy(standard_group)
        # Add the new variable to the config dictionary an re-create the whole tree
        logger.debug(funcname + 'adding group {:s}'.format(str(vardict)))
        item._ncconfig_.append(vardict)
        self.clear()
        config = copy.deepcopy(self.config) # The deepcopy is neccessary to replace configdata objects with the original again
        self.create_qtree(config)
            
            
    def rem_group(self,item):
        """Removes a group, if its None, use the locally marked group, not TESTED

        """
        item.parent()._ncconfig_.remove(item._ncconfig_) # Remove the dictionary from the variables list
        item.parent().removeChild(item)
        #if(groupname is not None):
        #    self.config['groups'].pop(groupname)
        #    self.clear()
        #    self.create_qtree(self.config)                               
            
            
    def add_variable(self,item,name):
        """Adds a variable in the group

        """
        funcname = __name__ + '.add_variable():'        
        vardict = copy.deepcopy(standard_variable)

        # Add the new variable to the config dictionary an re-create the whole tree
        logger.debug(funcname)
        item._ncconfig_.append(vardict)
        self.clear()
        config = copy.deepcopy(self.config) # The deepcopy is neccessary to replace configdata objects with the original again
        self.create_qtree(config)

    def rem_variable(self,item):
        """ Removes a variable
        """
        funcname = __name__ + '.rem_variable():'
        item.parent()._ncconfig_.remove(item._ncconfig_) # Remove the dictionary from the variables list
        item.parent().removeChild(item)
        
    def add_attribute(self,item,name,value):
        """Adds an attribute to the selected item

        """
        funcname = __name__ + '.add_atribute()'
        logger.debug(funcname)
        add_attr = True

        if(add_attr):
            value = 'value of attribute (does not change dynamically)'
            key = 'key of attribute (updates dynamically)'
            parent = QtWidgets.QTreeWidgetItem([name,''])
            item.addChild(parent)
            # Add name, value and key childs
            child = QtWidgets.QTreeWidgetItem(['name','name of attribute'])
            child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)
            parent.addChild(child)            
            child = QtWidgets.QTreeWidgetItem(['value',value])
            child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)
            parent.addChild(child)
            child = QtWidgets.QTreeWidgetItem(['key',key])
            child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)
            parent.addChild(child)                                    

            attrdict = copy.deepcopy(standard_attribute)
            item._ncconfig_.append(attrdict)
            parent.setExpanded(True)

    def rem_attribute(self,item):
        """Adds an attribute to the selected item

        """
        funcname = __name__ + '.rem_atribute():'
        logger.debug(funcname)
        item.parent()._ncconfig_.remove(item._ncconfig_) # Remove the dictionary from the attributes list
        item.parent().removeChild(item)
        # Remove

    def add_device(self,item,devicename='newdevicename'):
        """Adds a new device

        """
        funcname = __name__ + '.add_device():'
        #vardict = copy.deepcopy(standard_group)
        # Add the new variable to the config dictionary an re-create the whole tree
        logger.debug(funcname)
        item._ncconfig_['devices'].append(devicename)
        self.clear()
        config = copy.deepcopy(self.config) # The deepcopy is neccessary to replace configdata objects with the original again
        self.create_qtree(config)
        
        
    def rem_device(self,item):
        """Removes a device

        """
        funcname = __name__ + '.rem_device():'
        logger.debug(funcname)
        key = item.parent()._ncconfig_key
        item.parent()._ncconfig_[key].remove(item._ncconfig_) # Remove the dictionary from the attributes list
        item.parent().removeChild(item)        
        
        
    def get_config(self):
        """ Returns a configuration dictionary out of the qtree
        """
        funcname = __name__ + 'get_config():'
        logger.debug(funcname)

        # Making a copy, the configdata objects are reduced to the
        # original data. This i made possible with the _reduce_ magic
        # in the objects definition
        config = copy.deepcopy(self.config)
        return config

        
    def create_qtree(self,config,editable=True):
        """Creates a new qtree from the configuration and replaces the data in
        the dictionary with a configdata obejct, that save the data
        but also the qtreeitem, making it possible to have a synced
        config dictionary from/with a qtreewidgetitem. TODO: Worth to
        replace with a qviewitem?

        """
        funcname = __name__ + ':create_qtree():'
        logger.debug(funcname)
        # Disconnect signals, otherwise they might be called while creating tree
        try:
            self.itemDoubleClicked.disconnect(self.checkEdit)
            self.itemChanged.disconnect(self.item_changed) # If an item is changed
            self.currentItemChanged.disconnect(self.current_item_changed) # If an item is changed
        except:
            pass
    
        try:
            self.clear()
            parent = self.invisibleRootItem()

            self.setColumnCount(2)                                    
            if('ncfilename' in config.keys()): 
                filename = config['ncfilename'] # This is the modified filename with timestamp etc.
            elif('filename' in config.keys()): 
                filename = config['filename']
            else:
                filename = 'netcdffilename.nc'

            child = QtWidgets.QTreeWidgetItem(['filename',filename])
            child._ncconfig_ = config
            child.setToolTip(0,'The filename of the netCDF file')
            parent.addChild(child)
            parent = child

            for key in sorted(config.keys()):
                if(key == 'ncfilename'): # Already used
                    continue
                elif(key == 'groups'):
                    child = QtWidgets.QTreeWidgetItem(['groups',''])
                    child._ncconfig_ = config['groups']
                    parent.addChild(child)
                    groupparent = child
                elif(key == 'attributes'):
                    attrparent = QtWidgets.QTreeWidgetItem(['attributes',''])
                    parent.addChild(attrparent)
                    attrparent._ncconfig_ = config['attributes']                    
                    for iatt,attr in enumerate(config['attributes']):
                        name = config['attributes'][iatt]['name']
                        attrchild = QtWidgets.QTreeWidgetItem([name,''])
                        attrparent.addChild(attrchild)
                        attrchild._ncconfig_ = config['attributes'][iatt]
                        for attkey in sorted(config['attributes'][iatt].keys()):
                            data = configdata(config['attributes'][iatt][attkey])
                            child = QtWidgets.QTreeWidgetItem([attkey,str(data.value)])
                            if(attkey == 'name'):
                                child.setToolTip(0,'The name of the attribute')
                            elif(attkey == 'value'):
                                child.setToolTip(0,'The value of the attribute')
                            elif(attkey == 'key'):
                                child.setToolTip(0,'The key of the datapacket the attribute is updated dynamically. For instance a serial number the users does not know in advance')

                            if(editable):
                                child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)
                            child._ncconfig_    = config['attributes'][iatt]
                            child._ncconfig_key = attkey
                            attrchild.addChild(child)              
                else:
                    data = configdata(config[key])
                    child = QtWidgets.QTreeWidgetItem([key,str(data.value)])
                    if(editable):
                        child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)                    
                    child._ncconfig_ = config
                    child._ncconfig_key = key                                                      
                    data.qitem = child
                    parent.addChild(child)

            # Loop through all groups
            if('groups' in config.keys()):
                logger.debug(funcname + 'adding group')
                for igroup,group in enumerate(config['groups']):
                    data = configdata(group['name'])
                    child = QtWidgets.QTreeWidgetItem([data.value,''])
                    child._ncconfig_ = config['groups'][igroup]
                    data.qitem = child
                    groupparent.addChild(child)
                    parent = child
                    for key in sorted(group.keys()):
                        # the devices used for saving
                        if(key == 'devices'):
                            data = configdata(group[key])                            
                            devparent = QtWidgets.QTreeWidgetItem([key,''])
                            devparent._ncconfig_ = config['groups'][igroup]
                            devparent._ncconfig_key = key                            
                            data.qitem = devparent
                            parent.addChild(devparent)
                            for i,device in enumerate(sorted(group[key])):
                                data = configdata(group[key])
                                devitem = QtWidgets.QTreeWidgetItem([str(i),device])
                                devitem._ncconfig_ = device                                
                                if(editable):
                                    devitem.setFlags(devitem.flags() | QtCore.Qt.ItemIsEditable)          
                                data.qitem = devitem
                                devparent.addChild(devitem)
                                
                        # the variables saved in the netcdf
                        elif(key == 'variables'):
                            data = configdata(group[key])                                                        
                            keyparent = QtWidgets.QTreeWidgetItem(['variables',''])
                            data.qitem = keyparent                            
                            parent.addChild(keyparent)
                            keyparent._ncconfig_ = group[key]
                            for ikey,keydict in enumerate(group['variables']):
                                varname = group[key][ikey]['name']
                                keyparent2 = QtWidgets.QTreeWidgetItem([varname,''])
                                keyparent2._ncconfig_ = group[key][ikey]
                                # Save the keyparent and the item in the self.config dictionary
                                keyparent.addChild(keyparent2)
                                for key2 in sorted(keydict.keys()):
                                    if(key2 == 'attributes'):
                                        attrparent = QtWidgets.QTreeWidgetItem(['attributes',''])
                                        keyparent2.addChild(attrparent)
                                        for iatt,attr in enumerate(group[key][ikey]['attributes']):
                                            name = attr['name']
                                            attrchild = QtWidgets.QTreeWidgetItem([name,''])
                                            attrparent.addChild(attrchild)
                                            attrchild._ncconfig_ = group[key][ikey]['attributes']
                                            for attkey in sorted(attr.keys()):
                                                data = configdata(attr[attkey])
                                                child = QtWidgets.QTreeWidgetItem([attkey,str(data.value)])
                                                if(editable):
                                                    child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)
                                                child._ncconfig_ = attr
                                                child._ncconfig_key = attkey                                  
                                                attrchild.addChild(child)
                                                if(attkey == 'name'):
                                                    child.setToolTip(0,'The name of the attribute')
                                                elif(attkey == 'value'):
                                                    child.setToolTip(0,'The value of the attribute')
                                                elif(attkey == 'key'):
                                                    child.setToolTip(0,'The key of the datapacket the attribute is updated dynamically. For instance a serial number the users does not know in advance')                                                

                                        
                                    else:
                                        data = configdata(keydict[key2])
                                        keyitem = QtWidgets.QTreeWidgetItem([key2,str(data.value)])
                                        keyitem._ncconfig_ = keydict
                                        keyitem._ncconfig_key = key2
                                        if(editable):
                                            keyitem.setFlags(keyitem.flags() | QtCore.Qt.ItemIsEditable)
                                        data.qitem = keyitem
                                        config['groups'][igroup]['variables'][ikey][key2] = data # Replace the original item
                                        keyparent2.addChild(keyitem)
                                    
                                    
                        else:
                            data = configdata(group[key])
                            child = QtWidgets.QTreeWidgetItem([key,str(group[key])])
                            child._ncconfig_ = group
                            child._ncconfig_key = key
                            if(editable):
                                child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)
                            data.qitem = child
                            config['groups'][igroup][key] = data # Replace the original item
                            parent.addChild(child)

            self.expandAll()
            self.resizeColumnToContents(0)
            self.config = config
            # Connect edit triggers
            self.itemDoubleClicked.connect(self.checkEdit)
            self.itemChanged.connect(self.item_changed) # If an item is changed
            self.currentItemChanged.connect(self.current_item_changed) # If an item is changed            
        except Exception as e:
            logger.debug(funcname + ':' + str(e))

    
    def update(self,config):
        """
        """
        funcname = __name__ + '.update():'
        # Check if the filename has changed
        if(config['ncfilename'] == self.config['ncfilename']):
            for igroup,group in enumerate(config['groups']):
                for key in sorted(group.keys()):
                    # Update the keyitems
                    if(key == 'variables'):
                        for ikey,keydict in enumerate(group['variables']):
                            for key2 in sorted(keydict.keys()):
                                if(key2 == 'nwritten'):
                                    # update the nwritten key only
                                    #[ikey]
                                    itm = self.config['groups'][igroup]['variables'][ikey][key2]
                                    try:
                                       keyitem = self.config['groups'][igroup]['variables'][ikey][key2].qitem
                                       keyitem.setData(1,0,keydict['nwritten'])
                                    except Exception as e:
                                       logger.debug(funcname + str(e))
                                       logger.debug(funcname + ' group: {:s} key: {:s}'.format(group,key2))

        else:
            logger.debug(funcname + 'New file')
            self.create_qtree(copy.deepcopy(config))

        


        
# Adopted from
# https://stackoverflow.com/questions/21805047/qtreewidget-to-mirror-python-dictionary
class __ncViewTree_old(QtWidgets.QTreeWidget):
    def __init__(self, value):
        super().__init__()
        def fill_item(item, value):
            def new_item(parent, text, val=None):
                child = QtWidgets.QTreeWidgetItem([text])
                fill_item(child, val)
                parent.addChild(child)
                child.setExpanded(True)
            if value is None: return
            elif isinstance(value, dict):
                for key, val in sorted(value.items()):
                    new_item(item, str(key), val)
            elif isinstance(value, (list, tuple)):
                for val in value:
                    text = (str(val) if not isinstance(val, (dict, list, tuple))
                            else '[%s]' % type(val).__name__)
                    new_item(item, text, val) 
            else:
                new_item(item, str(value))

        fill_item(self.invisibleRootItem(), value)            


        
