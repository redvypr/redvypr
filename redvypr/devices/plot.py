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
import pyqtgraph
from redvypr.data_packets import redvypr_isin_data

pyqtgraph.setConfigOption('background', 'w')
pyqtgraph.setConfigOption('foreground', 'k')

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('plot')
logger.setLevel(logging.DEBUG)


def start(datainqueue,dataqueue,comqueue):
    funcname = __name__ + '.start()'        
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
        """ Starting the logger
        """
        funcname = self.name + ':' + __name__ +':'
        logger.debug(funcname + 'Starting now')
        # Check of devices have not been added
        devices = self.redvypr.get_devices() # Get all devices
        dataprovider = self.redvypr.get_data_providing_devices(self) # Get already connected publisher
        plot_devices = []
        for plot in self.config: # Loop over all plots
            if(plot['type'].lower() == 'numdisp'):
                name = plot['device']
                plot_devices.append(name)

            elif(plot['type'].lower() == 'graph'):
                for l in plot['lines']: # Loop over all lines in a plot
                    name = l['device']
                    plot_devices.append(name)                    

        # Add the device if not already done so
        for name in plot_devices:
            logger.info(funcname + 'Connecting device {:s}'.format(name))
            ret = self.redvypr.addrm_device_as_data_provider(name,self,remove=False)
            if(ret == None):
                logger.info(funcname + 'Device was not found')
            elif(ret == False):
                logger.info(funcname + 'Device was already connected')
            elif(ret == True):
                logger.info(funcname + 'Device was successfully connected')                                                    
            
                
        # And now start
        start(self.datainqueue,self.dataqueue,self.comqueue)
        
    def __str__(self):
        sstr = 'plot'
        return sstr



class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device) # Signal requesting a start of the device (starting the thread)
    device_stop  = QtCore.pyqtSignal(Device) # Signal requesting a stop of device
    connect      = QtCore.pyqtSignal(Device) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QFormLayout(self)

        self.device   = device
        self.label    = QtWidgets.QLabel("Datadisplay setup")
        self.conbtn = QtWidgets.QPushButton("Connect logger to devices")
        self.conbtn.clicked.connect(self.con_clicked)        
        self.startbtn = QtWidgets.QPushButton("Start logging")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)
        self.addbtn = QtWidgets.QPushButton("Add")
        self.addbtn.clicked.connect(self.add_clicked)
        self.addtype = QtWidgets.QComboBox()
        self.addtype.addItem('Graph')
        self.addtype.addItem('Numeric Display')
        # The location stuff
        self.locwidget = QtWidgets.QWidget()        
        loclayout = QtWidgets.QGridLayout(self.locwidget)
        labx  = QtWidgets.QLabel('Loc x')
        laby  = QtWidgets.QLabel('Loc y')
        labsx  = QtWidgets.QLabel('Size x')
        labsy  = QtWidgets.QLabel('Size y')                
        self.locx  = QtWidgets.QSpinBox()
        self.locy  = QtWidgets.QSpinBox()
        self.sizex = QtWidgets.QSpinBox()
        self.sizex.setValue(1)
        self.sizey = QtWidgets.QSpinBox()
        self.sizey.setValue(1)
        loclayout.addWidget(labx,0,0)        
        loclayout.addWidget(self.locx,1,0)
        loclayout.addWidget(laby,0,1)                
        loclayout.addWidget(self.locy,1,1)
        loclayout.addWidget(labsx,0,2)                                
        loclayout.addWidget(self.sizex,1,2)
        loclayout.addWidget(labsy,0,3)                                
        loclayout.addWidget(self.sizey,1,3)                
        # Location stuff done
        
        self.config = [] # A list of plots

        layout.addRow(self.label)        
        layout.addRow(self.conbtn)
        layout.addRow(self.locwidget)        
        layout.addRow(self.addtype,self.addbtn)
        layout.addRow(self.startbtn)        
        

        # Configuration of plots
        self.configwidget  = QtWidgets.QWidget()
        self.configlayout        = QtWidgets.QGridLayout(self.configwidget) # The layout
        layout.addRow(self.configwidget)
        #

    def finalize_init(self):
        """ This function is called after the configuration is parsed
        """        
        self.add_allwidgets()
        

    def add_clicked(self):
        """ Add a new plot
        """
        if(self.addtype.currentText() == 'Graph'):
            self.add_graph()
        elif(self.addtype.currentText() == 'Numeric Display'):
            print('Adding a numeric display')
            self.add_numdisp()            

    def add_numdisp(self):
        """ Add a new numeric display
        """
        print('Adding numeric display',self.device)
        locx = self.locx.value()
        locy = self.locy.value()
        sizex = self.sizex.value()
        sizey = self.sizey.value()                
        plotdict_bare = {}
        plotdict_bare['type'] = 'numdisp'        
        plotdict_bare['title'] = ''
        plotdict_bare['location'] = [locy,locx,sizey,sizex]
        plotdict_bare['unit'] = '[auto]' # Add auto
        plotdict_bare['data'] = 'data'
        plotdict_bare['device'] = 'testranddata'        
        # Check if we have already a plot here
        flag_add_plot = True
        for config in self.device.config:
            xsame = plotdict_bare['location'][0] == config['location'][0]
            ysame = plotdict_bare['location'][1] == config['location'][1]
            if xsame and ysame:
                logger.info('Already plot at the location')
                flag_add_plot = False
                break

        if(flag_add_plot):
            self.device.config.append(plotdict_bare)
            self.add_allwidgets()            


    def add_graph(self):
        """ Add a new graph
        """            
        print('Add new graph')
        print('Device',self.device)
        print(self.redvyprdevicelistentry)
        locx = self.locx.value()
        locy = self.locy.value()
        sizex = self.sizex.value()
        sizey = self.sizey.value()        
        plotdict_bare = {}
        plotdict_bare['type'] = 'graph'        
        plotdict_bare['title'] = 'New Plot'
        plotdict_bare['location'] = [locy,locx,sizey,sizex]
        plotdict_bare['xlabel'] = 'x label'
        plotdict_bare['ylabel'] = 'y label'
        plotdict_bare['datetick'] = True
        plotdict_bare['lines'] = []
        line_bare = {}
        line_bare['device'] = 'add devicename here'
        line_bare['name'] = 'line 1'
        line_bare['x'] = 't'
        line_bare['y'] = 'data'
        line_bare['linewidth'] = 2
        line_bare['color'] = [255,0,0]
        line_bare['buffersize'] = 5000
        plotdict_bare['lines'].append(line_bare)
        # Check if we have already a plot here
        flag_add_plot = True
        for config in self.device.config:
            xsame = plotdict_bare['location'][0] == config['location'][0]
            ysame = plotdict_bare['location'][1] == config['location'][1]
            if xsame and ysame:
                logger.info('Already plot at the location')
                flag_add_plot = False
                break

        if(flag_add_plot):
            self.device.config.append(plotdict_bare)
            self.add_allwidgets()



    def add_allwidgets(self):
        """
        """
        if True:
            # Adding/Updating the plotwidgets in the display widget
            self.redvyprdevicelistentry['gui'][0].update_widgets()
            # Adding/Updating the config widgets in the init widget
            for i,config in enumerate(self.device.config):
                try:
                    config['location']
                except:
                    config['location'] = [i,0]

                location = config['location']
                if(len(location) == 2):
                    location.append(1)
                    location.append(1)                    
                # Add the configurationwidget to the initwidget
                if(config['type'].lower() == 'graph'):
                    configtree = configTreePlotWidget(config=config)
                elif(config['type'].lower() == 'numdisp'):
                    configtree = configTreeNumDispWidget(config=config)
                else:
                    return None

                configwidget = QtWidgets.QWidget()
                tmplayout = QtWidgets.QGridLayout(configwidget)
                tmplayout.addWidget(configtree,0,0,1,2)
                configupdate = QtWidgets.QPushButton('Update')
                configupdate.config = config # Add the configuration dictionary to the button
                configupdate.configtree = configtree # A modified config with updates
                configupdate.clicked.connect(self.update_clicked)
                removebtn = QtWidgets.QPushButton('Remove')
                removebtn.clicked.connect(self.rem_clicked)
                tmplayout.addWidget(removebtn,1,1)                
                tmplayout.addWidget(configupdate,1,0)
                self.configlayout.addWidget(configwidget,location[0],location[1],location[2],location[3])        

    def rem_clicked(self):
        print('Removing')
        
    def update_clicked(self):
        """
        """
        funcname = __name__ + 'update_clicked():'
        button = self.sender()
        # serialise and deserialise the configuration
        confignew = copy.deepcopy(button.configtree.config)
        print('Updating new config',confignew)
        #button.config = confignew
        #print('Hallonewnew',button.config)
        if True:
            for i,dc in enumerate(self.device.config):
                if(dc == button.config):
                    logger.debug('Found config')
                    self.device.config[i] = confignew
                    button.config = confignew
                    break
                
            # Lets update the display widget
            self.redvyprdevicelistentry['gui'][0].update_widgets()

    def con_clicked(self):
        button = self.sender()
        self.connect.emit(self.device)        
            
    def start_clicked(self):
        funcname = __name__ + '.start_clicked():'
        button = self.sender()
        if button.isChecked():
            logger.debug(funcname + "button pressed")                
            self.device_start.emit(self.device)
            button.setText("Stop logging")
            self.conbtn.setEnabled(False)
        else:
            logger.debug(funcname + "button released")                            
            self.device_stop.emit(self.device)
            button.setText("Start logging")
            self.conbtn.setEnabled(True)
            
            
    def thread_status(self,status):
        """ This function is called by redvypr whenever the thread is started/stopped
        """   
        self.update_buttons(status['threadalive'])

       
    def update_buttons(self,thread_status):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """
            if(thread_status):
                self.startbtn.setText('Stop logging')
                self.startbtn.setChecked(True)
                #self.conbtn.setEnabled(False)
            else:
                self.startbtn.setText('Start logging')
                #self.conbtn.setEnabled(True)




class displayDeviceWidget(QtWidgets.QWidget):
    """ Widget is plotting realtimedata using the pyqtgraph functionality
    This widget can be configured with a configuration dictionary 
    """
    def __init__(self,dt_update = 0.5,device=None,buffersize=100):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout        = QtWidgets.QGridLayout(self)
        self.device = device
        self.buffersizestd = buffersize
        self.plots = []
        self.databuf = [] # A buffer of data

            
        config = {'dt_update':dt_update,'last_update':time.time()}
        self.config = config

    def update_widgets(self):
        """ Compares self.config and widgets and add/removes plots if necessary
        """
        funcname = __name__ + '.update_widgets():'
        logger.debug(funcname)
        # Remove all plots (thats brute but easy to bookeep
        for plot in self.plots:
            plot.close()
            
        # Add axes to the widget
        for i,config in enumerate(self.device.config):

            if(config['type'] == 'graph'):
                logger.debug(funcname + ': Adding graph' + str(config))                
                plot = plotWidget(config)
                location = config['location']            

                if(len(location) == 2):
                    self.layout.addWidget(plot,location[0],location[1])
                else:
                    self.layout.addWidget(plot,location[0],location[1],location[2],location[3])
                    
                self.plots.append(plot)
            elif(config['type'] == 'numdisp'):
                logger.debug(funcname + ': Adding numeric display' + str(config))
                plot = numdispWidget(config)
                location = config['location']            
                self.layout.addWidget(plot,location[0],location[1])
                self.plots.append(plot)                

                
    def config_widget(self):
        """
        """
        self.configwidget = QtWidgets.QWidget(self)
        self.configwidget.show()
        
    def thread_status(self,status):
        """ This function is regularly called by redvypr whenever the thread is started/stopped
        """
        pass        
        #self.update_buttons(status['threadalive'])
        
    def update_line_styles(self):
        for plot_dict in self.plot_dicts:
            for line_dict in plot_dict['lines']:
                config = line_dict['config'] 
        
    def update(self,data):
        funcname = __name__ + '.update():'
        tnow = time.time()
        self.databuf.append(data)
        #print('got data',data)
        #print('statistics',self.device.statistics)
        devicename = data['device']
        # Only plot the data in intervals of dt_update length, this prevents high CPU loads for fast devices
        update = (tnow - self.config['last_update']) > self.config['dt_update']
        #print('update update',update)
        if(update):
            self.config['last_update'] = tnow
            
            try:
                for data in self.databuf:
                    for plot in self.plots:
                        plot.update_plot(data)

                self.databuf = []
    
            except Exception as e:
                logger.debug(funcname + 'Exception:' + str(e))

#
#                
#
# Plot widget
#
#
#
class plotWidget(QtWidgets.QWidget):
    """ Widget is plotting realtimedata using the pyqtgraph functionality
    This widget can be configured with a configuration dictionary 
    """
    def __init__(self,config):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout = QtWidgets.QVBoxLayout(self)
        self.config = config
        if True:
            logger.debug(funcname + ': Adding plot' + str(config))
            try:
                title = config['title']
            except:
                title = "Plot {:d}".format(i)
            
            plot = pyqtgraph.PlotWidget(title=title)

            self.layout.addWidget(plot)
                
            # Add time as date
            try:
                datetick = config['datetick']
            except:
                datetick = False
                
            if(datetick):
                axis = pyqtgraph.DateAxisItem(orientation='bottom')
                plot.setAxisItems({"bottom": axis})
                
            # If a xlabel is defined                
            try:
                plot.setLabel('left', config['ylabel'] )
            except:
                pass
            
            # If a ylabel is defined                
            try:
                plot.setLabel('bottom', config['xlabel'] )
            except:
                pass
                        
            plot_dict = {'widget':plot,'lines':{}}
            # Add a lines with the actual data to the graph
            for iline, line in enumerate(config['lines']):
                logger.debug(funcname + ':Adding a line to the plot:' + str(line))
                try:
                    buffersize = line['buffersize']
                except:
                    buffersize = self.buffersizestd
                    
                xdata = np.zeros(buffersize) * np.NaN
                ydata = np.zeros(buffersize) * np.NaN
                try:
                    name = line['name']
                except:
                    name = "Line {:d}".format(iline)
                lineplot = pyqtgraph.PlotDataItem( name = name)
                
                try:
                    device = line['device']
                except:
                    logger.warning(funcname + ': Could not find a device to plot, omitting entry:' + str(line))
                    continue
                    
                
                try:    
                    plot_dict['lines'][device]
                except Exception as e:
                    plot_dict['lines'][device] = []
                    
                try:
                    x = line['x']
                except:
                    x = ""
                    
                try:
                    y = line['y']
                except:
                    y = ""
                    
                try:
                    linewidth = line['linewidth']
                except:
                    linewidth = 1
                    
                try:
                    colors = line['color']
                    color = QtGui.QColor(colors[0],colors[1],colors[2])
                except Exception as e:
                    logger.debug('No color found:' + str(e))
                    color = QtGui.QColor(255,10,10)
                    
                # Configuration of the line plot
                lineconfig = {'device':device,'x':x,'y':y,'linewidth':linewidth,'color':color}
                #lineconfig = {'device':testranddata,'x':'t','y':'data','linewidth':2,'color':QtGui.QColor(255,0,0)}
                # Add the line and the configuration to the lines list
                line_dict = {'line':lineplot,'config':lineconfig,'x':xdata,'y':ydata}
                # The lines are sorted according to the devicenames, each device has a list of lines attached to it
                plot_dict['lines'][lineconfig['device']].append(line_dict)
                plot.addItem(lineplot)
                # Configuration 
                
                
        self.plot_dict = plot_dict
        
    def update_plot(self,data):
        """ Updates the plot based on the given data
        """
        #print('Hallo',data)
        funcname = __name__ + '.update()'
        tnow = time.time()
        #print('got data',data)
        # Always update
        update = True
        try:
            # Loop over all plot axes
            if True:
                plot_dict = self.plot_dict
                # Check if the device is to be plotted
                for devicename_plot in plot_dict['lines'].keys(): # Loop over all lines of the devices to plot
                    if(redvypr_isin_data(devicename_plot,data)):
                        pw        = plot_dict['widget'] # The plot widget
                        for ind,line_dict in enumerate(plot_dict['lines'][devicename_plot]): # Loop over all lines of the device to plot
                            line      = line_dict['line'] # The line to plot
                            config    = line_dict['config'] # The line to plot
                            x         = line_dict['x'] # The line to plot
                            y         = line_dict['y'] # The line to plot   
                            x         = np.roll(x,-1)       
                            y         = np.roll(y,-1)
                            x[-1]    = float(data[config['x']])
                            y[-1]    = float(data[config['y']])                
                            line_dict['x']  = x
                            line_dict['y']  = y
            if(update):
                #print('Hallo!')
                if True:
                    for devicename in plot_dict['lines'].keys():
                        if True:
                            for line_dict in plot_dict['lines'][devicename]:
                                line      = line_dict['line'] # The line to plot
                                config    = line_dict['config'] # The line to plot
                                x         = line_dict['x'] # The line to plot
                                y         = line_dict['y'] # The line to plot  
                                line.setData(x=x,y=y,pen = pyqtgraph.mkPen(config['color'], width=config['linewidth']))
                                
                                #pw.setXRange(min(x[:ind]),max(x[:ind]))        
    
        except Exception as e:
            #print(funcname + 'Exception:' + str(e))
            logger.debug(funcname + 'Exception:' + str(e))


#
#
#
#
#
class configTreePlotWidget(QtWidgets.QTreeWidget):
    """ Qtreewidget that display and modifies the configuration of the plotWidget display
    """
    def __init__(self, config = {},editable=True):
        super().__init__()
            
        self.config      = copy.deepcopy(config) # Make a copy of the dictionary
        #self.config      = config 
        
        # make only the first column editable        
        self.setEditTriggers(self.NoEditTriggers)
        #self.header().setVisible(False)
        self.create_qtree(self.config,editable=True)

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
        logger.debug(funcname + 'Changed {:s} {:d} to {:s}'.format(item.text(0),column,item.text(1)))
        # Parse the string given by the changed item using yaml (this makes the types correct again)
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
            logger.warning(funcname + ':bad:' + str(e))

        # Change the dictionary 
        try:
            key = item._ncconfig_key
            if(type(item._ncconfig_[key]) == configdata):
               item._ncconfig_[key].value = newdata # The newdata, parsed with yaml               
            else:
               item._ncconfig_[key] = newdata # The newdata, parsed with yaml

        except Exception as e:
            logger.debug(funcname + '{:s}'.format(str(e)))



    def create_qtree(self,config,editable=True):
        """Creates a new qtree from the configuration and replaces the data in
        the dictionary with a configdata obejct, that save the data
        but also the qtreeitem, making it possible to have a synced
        config dictionary from/with a qtreewidgetitem. TODO: Worth to
        replace with a qviewitem?

        """
        funcname = __name__ + ':create_qtree():'
        logger.debug(funcname)
        if True:
            self.clear()
            parent = self.invisibleRootItem()

            self.setColumnCount(2)
            
        
        for key in sorted(config.keys()):
            if(key == 'lines'):
                child = QtWidgets.QTreeWidgetItem([key,''])                
                parent.addChild(child)
                lineparent = child
                for iline,line in enumerate(config['lines']):
                    for linekey in sorted(line.keys()):
                        value = config['lines'][iline][linekey]
                        data = configdata(value)
                        config['lines'][iline][linekey] = data

                        child = QtWidgets.QTreeWidgetItem([linekey,str(value)])
                        data.qitem          = child
                        child._ncconfig_    = config['lines'][iline]
                        child._ncconfig_key = linekey
                        if(editable):
                            child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)                        
                        lineparent.addChild(child)
                    
            else:
                value = config[key]
                data = configdata(value)
                config[key] = data                
                child = QtWidgets.QTreeWidgetItem([key,str(value)])
                child._ncconfig_    = config
                child._ncconfig_key = key                
                parent.addChild(child)
                if(editable):
                    child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)
                groupparent = child


        # Connect edit triggers
        self.itemDoubleClicked.connect(self.checkEdit)
        self.itemChanged.connect(self.item_changed) # If an item is changed
        self.currentItemChanged.connect(self.current_item_changed) # If an item is changed







#
#                
#
# numeric display widget
#
#
#
class numdispWidget(QtWidgets.QFrame):
    """ Widget is plotting realtimedata on a display
    """
    def __init__(self,config):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        #self.setStyleSheet("border : 1px solid lightgray;background-color : lightgray")
        #self.setStyleSheet("background-color : red")
        self.config = config
        try:
            backcolor = config['background']
        except:
            backcolor = 'lightgray'

        try:
            bordercolor = config['background']
        except:
            bordercolor = 'black'

        try:
            fontsize = config['fontsize']
        except:
            fontsize = 50

        try:
            self.config['dataformat']
        except:
            self.config['dataformat'] = "+2.5f"

        try:
            self.config['devicelabel']
        except:
            self.config['devicelabel'] = False

        self.setStyleSheet("background-color : {:s};border : 1px solid {:s};".format(backcolor,bordercolor))
        self.layout = QtWidgets.QGridLayout(self)
        self.config = config
        if True:
            logger.debug(funcname + ': Adding plot' + str(config))
            # Title
            try:
                title = config['title']
            except:
                title = ""

            if(len(title)>0):
                self.titledisp = QtWidgets.QLabel(title)
                self.titledisp.setStyleSheet("font-weight: bold;border : 1px solid {:s};".format(backcolor))
                self.titledisp.setAlignment(QtCore.Qt.AlignCenter)
                self.layout.addWidget(self.titledisp,0,0,1,2)

            if(self.config['devicelabel']):
                self.devicedisp = QtWidgets.QLabel(self.config['device'])
                self.devicedisp.setStyleSheet("border : 1px solid {:s};".format(backcolor))
                self.devicedisp.setAlignment(QtCore.Qt.AlignCenter)
                self.layout.addWidget(self.devicedisp,1,0,1,2)

            # Unit
            try:
                unit = config['unit']
            except:
                unit = ""

            self.unit = unit                
            if(len(unit)>0):
                self.unitdisp = QtWidgets.QLabel(unit)
                self.unitdisp.setStyleSheet("border : 1px solid {:s};".format(backcolor))            
                self.layout.addWidget(self.unitdisp,2,1)

            
            self.numdisp = QtWidgets.QLabel("#")
            self.numdisp.setStyleSheet("border : 1px solid {:s};font-weight: bold; font-size: {:d}pt".format(backcolor,fontsize))            
            #
            if(len(unit)>0):            
                self.layout.addWidget(self.numdisp,2,0)
            else:
                self.layout.addWidget(self.numdisp,2,0,1,2)

                
    def update_plot(self,data):
        """ Updates the plot based on the given data
        """
        funcname = __name__ + '.update()'
        tnow = time.time()
        #print('got data',data)
        devicename = data['device']
        datakey = self.config['data']
        if(redvypr_isin_data(self.config['device'],data)):
            dataformat = self.config['dataformat']
            datastr = "{0:{dformat}}".format(data[datakey],dformat=dataformat)
            self.numdisp.setText(datastr)
            #self.resize_font(self.numdisp)
            if(self.unit == '[auto]'):
                unitkey = datakey + '_unit'
                try:
                    unitstr = str(data[unitkey])
                except:
                    unitstr = 'NA'
                    
                self.unitdisp.setText(unitstr)
                #self.resize_font(self.unitdisp)                

    def resize_font(self,label):
        # Does not work!
        fsize         = label.fontMetrics().size(0, label.text())
        lsize = label.size()
        font = QtGui.QFont('Arial')
        font.setPixelSize(label.height())
        #label.setFont(QtGui.QFont('Arial', fsize.height()))
        label.setFont(font)
        #label.resize(lsize)        



#
#
#
#
#
class configTreeNumDispWidget(QtWidgets.QTreeWidget):
    """ Qtreewidget that display and modifies the configuration of the plotWidget display
    """
    def __init__(self, config = {},editable=True):
        super().__init__()
            
        self.config      = copy.deepcopy(config) # Make a copy of the dictionary
        #self.config      = config 
        
        # make only the first column editable        
        self.setEditTriggers(self.NoEditTriggers)
        #self.header().setVisible(False)
        self.create_qtree(self.config,editable=True)

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
        logger.debug(funcname + 'Changed {:s} {:d} to {:s}'.format(item.text(0),column,item.text(1)))
        # Parse the string given by the changed item using yaml (this makes the types correct again)
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
            print('ohno',e)            

        # Change the dictionary 
        try:
            key = item._ncconfig_key
            if(type(item._ncconfig_[key]) == configdata):
               item._ncconfig_[key].value = newdata # The newdata, parsed with yaml               
            else:
               item._ncconfig_[key] = newdata # The newdata, parsed with yaml

        except Exception as e:
            logger.debug(funcname + '{:s}'.format(str(e)))



    def create_qtree(self,config,editable=True):
        """Creates a new qtree from the configuration and replaces the data in
        the dictionary with a configdata obejct, that save the data
        but also the qtreeitem, making it possible to have a synced
        config dictionary from/with a qtreewidgetitem. TODO: Worth to
        replace with a qviewitem?

        """
        funcname = __name__ + ':create_qtree():'
        logger.debug(funcname)
        if True:
            self.clear()
            parent = self.invisibleRootItem()

            self.setColumnCount(2)
            
        
        for key in sorted(config.keys()):
            if True:
                value = config[key]
                data = configdata(value)
                config[key] = data                
                child = QtWidgets.QTreeWidgetItem([key,str(value)])
                child._ncconfig_    = config
                child._ncconfig_key = key                
                parent.addChild(child)
                if(editable):
                    child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)
                groupparent = child


        # Connect edit triggers
        self.itemDoubleClicked.connect(self.checkEdit)
        self.itemChanged.connect(self.item_changed) # If an item is changed
        self.currentItemChanged.connect(self.current_item_changed) # If an item is changed            
                                
    

            



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



