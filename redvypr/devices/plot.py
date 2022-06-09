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
from redvypr.data_packets import device_in_data, get_keys_from_data
from redvypr.gui import redvypr_devicelist_widget
import redvypr.files as files

_logo_file = files.logo_file
_icon_file = files.icon_file
pyqtgraph.setConfigOption('background', 'w')
pyqtgraph.setConfigOption('foreground', 'k')

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('plot')
logger.setLevel(logging.DEBUG)

def get_bare_graph_config():
    """ Returns a valid bare configuration for a graph plot
    """
    plotdict_bare = {}
    plotdict_bare['type'] = 'graph'        
    plotdict_bare['title'] = 'Graph title'
    plotdict_bare['name'] = 'Graph'
    plotdict_bare['location'] = [0,0,0,0]
    plotdict_bare['xlabel'] = 'x label'
    plotdict_bare['ylabel'] = 'y label'
    plotdict_bare['datetick'] = True
    plotdict_bare['lines'] = []
    plotdict_bare['lines'].append(get_bare_graph_line_config())
    #plotdict_bare['lines'].append(get_bare_graph_line_config())
    return plotdict_bare


def get_bare_graph_line_config():
    line_bare = {}
    line_bare['device'] = 'add devicename here'
    line_bare['name'] = 'this is a line'
    line_bare['x'] = 't'
    line_bare['y'] = 'data'
    line_bare['linewidth'] = 2
    line_bare['color'] = [255,0,0]
    line_bare['buffersize'] = 5000
    return line_bare


def start(datainqueue,dataqueue,comqueue):
    funcname = __name__ + '.start()'
    while True:
        try:
            com = comqueue.get(block=False)
            logger.info(funcname + ': Stopping now')
            break
        except:
            pass


        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
                dataqueue.put(data) # This has to be done, otherwise the gui does not get any data ...
            except Exception as e:
                logger.debug(funcname + ': Exception:' + str(e))
                
    logger.info(funcname + ': Stopped')            

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

    def finalize_init(self):
        """This function is called after the configuration has been read and
        parsed

        """
        self.connect_devices()
        
    def connect_devices(self):
        """ Connects devices, if they are not already connected
        """
        funcname = self.__class__.__name__ + '.connect_devices():'                                
        logger.debug(funcname)
        # Check of devices have not been added
        devices = self.redvypr.get_devices() # Get all devices
        plot_devices = []
        for plot in self.config: # Loop over all plots
            if(str(plot['type']).lower() == 'numdisp'):
                name = plot['device']
                plot_devices.append(name)

            elif(str(plot['type']).lower() == 'graph'):
                for l in plot['lines']: # Loop over all lines in a plot
                    name = l['device']
                    plot_devices.append(name)                    
                    
        # Add the device if not already done so
        if True:
            for name in plot_devices:
                logger.info(funcname + 'Connecting device {:s}'.format(name))
                ret = self.redvypr.addrm_device_as_data_provider(name,self,remove=False)
                if(ret == None):
                    logger.info(funcname + 'Device was not found')
                elif(ret == False):
                    logger.info(funcname + 'Device was already connected')
                elif(ret == True):
                    logger.info(funcname + 'Device was successfully connected')                                                            
    def start(self):
        """ Starting the plot
        """
        funcname = self.name + ':' + __name__ +':'
        logger.debug(funcname + 'Starting now')

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
        layout        = QtWidgets.QGridLayout(self)

        self.device   = device
        #self.label    = QtWidgets.QLabel("Datadisplay setup")
        self.conbtn = QtWidgets.QPushButton("Connect logger to devices")
        self.conbtn.clicked.connect(self.con_clicked)        
        self.startbtn = QtWidgets.QPushButton("Start plotting")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)
        self.addbtn = QtWidgets.QPushButton("Add")
        self.addbtn.clicked.connect(self.add_clicked)
        self.addbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)

        self.addtype = QtWidgets.QComboBox()
        self.addtype.addItem('Graph')
        self.addtype.addItem('Numeric Display')
        self.addtype.currentIndexChanged.connect(self.update_plotname)
        # The location stuff
        self.locwidget = QtWidgets.QWidget()        
        loclayout = QtWidgets.QGridLayout(self.locwidget)
        labx  = QtWidgets.QLabel('Location x')
        laby  = QtWidgets.QLabel('Location y')
        labsx  = QtWidgets.QLabel('Size x')
        labsy  = QtWidgets.QLabel('Size y')                
        self.locx  = QtWidgets.QSpinBox()
        self.locx.valueChanged.connect(self.update_plotname)
        self.locy  = QtWidgets.QSpinBox()
        self.locy.valueChanged.connect(self.update_plotname)
        self.sizex = QtWidgets.QSpinBox()
        self.sizex.setValue(1)
        self.sizey = QtWidgets.QSpinBox()
        self.sizey.setValue(1)
        self.addname = QtWidgets.QLineEdit()
        # Make the lineedit less wide
        # https://forum.qt.io/topic/37280/solved-how-to-change-initial-size-of-qlineedit/5
        self.addname.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred);
        self.addname.setMinimumWidth(200)
        self.update_plotname()
        
        loclayout.addWidget(labx,0,0)        
        loclayout.addWidget(self.locx,0,1)
        loclayout.addWidget(laby,1,0)                
        loclayout.addWidget(self.locy,1,1)
        loclayout.addWidget(labsx,2,0)                                
        loclayout.addWidget(self.sizex,2,1)
        loclayout.addWidget(labsy,3,0)                                
        loclayout.addWidget(self.sizey,3,1)  
        
        loclayout.addWidget(QtWidgets.QLabel('Plot type'),4,0)
        loclayout.addWidget(self.addtype,4,1)
        
        loclayout.addWidget(QtWidgets.QLabel('Plot name'),5,0)
        loclayout.addWidget(self.addname,5,1)
        loclayout.addWidget(self.addbtn,0,2,-1,1)                                              
        # Location stuff done
        
        self.config = [] # A list of plots

        #layout.addWidget(self.label,0,0,1,2)        
        layout.addWidget(self.conbtn,1,0)
        layout.addWidget(self.startbtn,1,1)
        layout.addWidget(self.locwidget,3,0,1,2)        
        
        
        # Configuration of plots
        self.configwidget  = QtWidgets.QWidget()
        backcolor = 'lightgray'
        #self.configwidget.setStyleSheet("border-style: outset;border-width: 2px;border-color: black")        
        #self.configwidget.setStyleSheet("border-style: outset;border-width: 2px;border-color: black")
        self.configwidget.setStyleSheet("background-color : {:s}".format(backcolor))                

        self.configlayout  = QtWidgets.QGridLayout(self.configwidget) # The layout
        layout.addWidget(self.configwidget,5,0,3,2)
        #
        
    def update_plotname(self):
        """ Updates the plot name  
        """
        x = self.locx.value()
        y = self.locy.value()
        plottype = self.addtype.currentText()
        name = '{:s} {:d}x{:d}'.format(plottype,x,y)
        self.addname.setText(name)

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
        plotdict_bare['title'] = self.addname.text()
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
        print('test',self.redvyprdevicelistentry)
        locx = self.locx.value()
        locy = self.locy.value()
        sizex = self.sizex.value()
        sizey = self.sizey.value()
        # Get a configuration and modify it
        plotdict_bare = get_bare_graph_config()        
        plotdict_bare['title'] = self.addname.text()
        plotdict_bare['name'] = self.addname.text()
        plotdict_bare['location'] = [locy,locx,sizey,sizex]
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
        """ Adds all plots defined in the list self.device.config
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
                # Add a button wich is opening the configuration widget
                button = QtWidgets.QPushButton(config['type'])
                button.setStatusTip('Click on icon for setup')

                #backcolor = 'lightgray'
                backcolor = 'white'
                bordercolor = 'black'        
                button.setStyleSheet("background-color : {:s};border : 1px solid {:s};".format(backcolor,bordercolor))        
                button.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)
                button.clicked.connect(self.config_clicked)
                if(config['type'].lower() == 'graph'):
                    configtree = configPlotWidget(config=config,device = self.device, redvypr = self.redvypr)
                elif(config['type'].lower() == 'numdisp'):
                    configtree = configTreeNumDispWidget(config=config)                 
                else:
                    return None
                
                configtree.redvypr = self.device.redvypr 
                configtree.device = self.device
                button.configwidget = QtWidgets.QWidget()
                tmplayout = QtWidgets.QGridLayout(button.configwidget)
                tmplayout.addWidget(configtree,0,0)
                configupdate = QtWidgets.QPushButton('Update')
                configupdate.config = config # Add the configuration dictionary to the button
                configupdate.configtree = configtree # A modified config with updates
                configupdate.clicked.connect(self.update_clicked)
                tmplayout.addWidget(configupdate,2,0)

                configwidget = QtWidgets.QWidget()
                button.configwidget.setWindowIcon(QtGui.QIcon(_icon_file))        
                button.configwidget.setWindowTitle('redvypr plot setup')
                tmplayout = QtWidgets.QGridLayout(configwidget)
                tmplayout.addWidget(button,0,0,1,2)
                
                self.configlayout.addWidget(configwidget,location[0],location[1],location[2],location[3])

    def config_clicked(self):
        """ Open the configurationwidget of the clicked button
        """
        self.sender().configwidget.show()

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
            
            # Reconnecting the devices    
            self.device.connect_devices()
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
            button.setText("Stop plotting")
            self.conbtn.setEnabled(False)
        else:
            logger.debug(funcname + "button released")                            
            self.device_stop.emit(self.device)
            button.setText("Start plotting")
            self.conbtn.setEnabled(True)
            
            
    def thread_status(self,status):
        """ This function is called by redvypr whenever the thread is started/stopped
        """   
        self.update_buttons(status['threadalive'])

       
    def update_buttons(self,thread_status):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """
            if(thread_status):
                self.startbtn.setText('Stop plotting')
                self.startbtn.setChecked(True)
                #self.conbtn.setEnabled(False)
            else:
                self.startbtn.setText('Start plotting')
                #self.conbtn.setEnabled(True)




class displayDeviceWidget(QtWidgets.QWidget):
    """ Widget is a wrapper for several plotting widgets (numdisp, graph) 
    This widget can be configured with a configuration dictionary 
    """
    def __init__(self,dt_update = 0.25,device=None,buffersize=100):
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
        """ Compares self.device.config and widgets and add/removes plots if necessary
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
class plotWidget(QtWidgets.QFrame):
    """ Widget is plotting realtimedata using the pyqtgraph functionality
    This widget can be configured with a configuration dictionary 
    """
    def __init__(self,config):
        funcname = __name__ + '.init()'
        super(QtWidgets.QFrame, self).__init__()
        try:
            backcolor = config['background']
        except:
            backcolor = 'lightgray'
            
        try:
            bordercolor = config['background']
        except:
            bordercolor = 'black'
            
        try:
            config['useprops']
        except:
            config['useprops'] = True
            
        self.setStyleSheet("background-color : {:s};border : 1px solid {:s};".format(backcolor,bordercolor))        
        self.layout = QtWidgets.QVBoxLayout(self)
        self.config = config
        i = 0
        if True:
            logger.debug(funcname + ': Adding plot' + str(config))
            try:
                title = config['title']
            except:
                title = "Plot {:d}".format(i)
                
            try:
                name = config['name']
            except:
                name = "Plot {:d}".format(i)
            
            plot = pyqtgraph.PlotWidget(title=title,name=name)
            plot.register(name=name)
            # Add a legend
            plot.addLegend()

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
                    name = line['device']
                    
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
        
    def clear_buffer(self):
        """ Clears the buffer of all lines
        """
        # Check if the device is to be plotted
        
        devicenames  = self.plot_dict['lines'].keys()
        for devicename in devicenames:
            for ind,line_dict in enumerate(self.plot_dict['lines'][devicename]): # Loop over all lines of the device to plot
                line      = line_dict['line'] # The line to plot
                config    = line_dict['config'] # The line to plot
                line_dict['x'][:] = np.NaN 
                line_dict['y'][:] = np.NaN 
        
    def update_plot(self,data):
        """ Updates the plot based on the given data
        """
        #print('Hallo',data)
        funcname = self.__class__.__name__ + '.update_plot():'
        tnow = time.time()
        print(funcname + 'got data',data)
        # Always update
        update = True
        try:
            # Loop over all plot axes
            if True:
                plot_dict = self.plot_dict
                # Check if the device is to be plotted
                for devicename_plot in plot_dict['lines'].keys(): # Loop over all lines of the devices to plot
                    if(device_in_data(devicename_plot,data)):
                        pw        = plot_dict['widget'] # The plot widget
                        for ind,line_dict in enumerate(plot_dict['lines'][devicename_plot]): # Loop over all lines of the device to plot
                            line      = line_dict['line'] # The line to plot
                            config    = line_dict['config'] # The line to plot
                            x         = line_dict['x'] # The line to plot
                            y         = line_dict['y'] # The line to plot
                            # data can be a single float or a list
                            newx = data[config['x']]
                            newy = data[config['y']]
                            if(type(newx) is not list):
                                newx = [newx]
                                newy = [newy]
                            
                            for inew in range(len(newx)): # TODO this can be optimized using indices instead of a loop
                                x         = np.roll(x,-1)       
                                y         = np.roll(y,-1)
                                x[-1]    = float(newx[inew])
                                y[-1]    = float(newy[inew])
                                line_dict['x']  = x
                                line_dict['y']  = y
                            if(ind==0): # Use the first line for the ylabel
                                if('useprops' in self.config.keys()):
                                    if(self.config['useprops']):
                                        propkey = '?' + config['y']
                                        try:
                                            unitstr ='[' + data[propkey]['unit'] + ']'
                                            pw.setLabel('left', unitstr)
                                        except:
                                            pass
                                            
                                        
                                        
            if(update):
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
class configPlotWidget(QtWidgets.QWidget):
    def __init__(self, config = {}, editable=True, device = None, redvypr = None):
        super().__init__()
        self.device      = device
        self.redvypr     = redvypr
        self.config      = copy.deepcopy(config) # Make a copy of the dictionary
        self.layout      = QtWidgets.QVBoxLayout(self)
        self.tree        = configTreePlotWidget(config,editable=editable,device=device,redvypr=redvypr)
        self.tree.config_changed.connect(self.config_changed)
        self.tree.line_touched.connect(self._line_touched)
        
        self.linebtn     = QtWidgets.QPushButton('Add line')
        self.linebtn.clicked.connect(self.process_linebutton)
        
        self.clearbtn     = QtWidgets.QPushButton('Clear data')
        self.clearbtn.clicked.connect(self.process_clearbutton)
        

        self.layout.addWidget(self.tree)
        self.layout.addWidget(self.linebtn)
        self.layout.addWidget(self.clearbtn)
        
    def process_clearbutton(self):
        """ Clears the databuffer of the lines 
        """
        #clear_buffer
        devicedict = self.redvypr.get_devicedict_from_str(self.device.name)
        print('Config',self.config)
        for p in devicedict['displaywidget'].plots:
            if(type(p) == plotWidget):
                print('Found a plot widget')
                print('Config widget',p.config)
                if True: # Here we need to check if its the right plot
                    p.clear_buffer()
        
    
    def process_linebutton(self):
        if(self.linebtn.text()   == 'Add line'):
            self.tree.add_line()
        elif(self.linebtn.text() == 'Remove line'):
            self.linebtn.setText('Add line')
            self.tree.rem_line(self.lineindex)
            
    def _line_touched(self,index):
        self.linebtn.setText('Remove line')
        self.lineindex = index
        
    def config_changed(self,config):
        #print('Config changed',config)
        self.config = copy.deepcopy(self.tree.config) # Make a copy of the dictionary
#
#
#
#
class configTreePlotWidget(QtWidgets.QTreeWidget):
    """ Qtreewidget that display and modifies the configuration of the plotWidget display
    """
    config_changed = QtCore.pyqtSignal(dict) # Signal requesting a start of the device (starting the thread)
    line_touched = QtCore.pyqtSignal(int) # Signal stating that a line was touched, useful for line removal
    def __init__(self, config = {},editable=True,device = None, redvypr = None):
        super().__init__()
        self.device  = device
        self.redvypr = redvypr
        self.config  = copy.deepcopy(config) # Make a copy of the dictionary
        self.config  = config
        self.editable= editable
        # make only the first column editable        
        self.setEditTriggers(self.NoEditTriggers)
        self.itemDoubleClicked.connect(self.edititem)
        self.header().setVisible(False)
        self.create_qtree(self.config,editable = self.editable)
        self.resizeColumnToContents(0)
        self.itemExpanded.connect(self._proc_expanded)
        self.itemDoubleClicked.connect(self.checkEdit)
        self.itemChanged.connect(self.item_changed) # If an item is changed
        self.currentItemChanged.connect(self.current_item_changed) # If an item is changed
         
    def _proc_expanded(self):
        self.resizeColumnToContents(0)        
          
    def checkEdit(self, item, column):
        """ Helper function that only allows to edit column 1
        """
        funcname = __name__ + '.checkEdit():'
        logger.debug(funcname)
        if column == 1:
            self.edititem(item, column)
            
    def add_line(self):
        """ Adds a new bare line to the config
        
        """
        lineconfig = get_bare_graph_line_config()
        self.config['lines'].append(lineconfig)
        config      = copy.deepcopy(self.config) # Make a copy of the dictionary
        self.config = config
        self.create_qtree(config, editable = self.editable)
        print('Config (add line)',self.config)
        
    def rem_line(self,index):
        """ Removes a line at position index
        
        """
        self.config['lines'].pop(index)
        config      = copy.deepcopy(self.config) # Make a copy of the dictionary
        self.config = config
        self.create_qtree(config, editable = self.editable)
        print('Config (rem line)',self.config)
            

    def current_item_changed(self,current,previous):
        """ Save the data in the currently changed item, this is used to
        restore if newly entered data is not valid
        """
        try:
            self.backup_data = current.text(1)
        except:
            self.backup_data = None
            
        if(current.text(0) == 'line'):
            index = int(current.text(1))
            self.line_touched.emit(index)
            

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


        self.resizeColumnToContents(0)
        self.config_changed.emit(self.config)
                                      
    def create_qtree(self,config,editable=True):
        """Creates a new qtree from the configuration and replaces the data in
        the dictionary with a configdata object, that save the data
        but also the qtreeitem, making it possible to have a synced
        config dictionary from/with a qtreewidgetitem. TODO: Worth to
        replace with a qviewitem?

        """

        funcname = __name__ + ':create_qtree():'
        logger.debug(funcname)
        self.blockSignals(True)
        if True:
            self.clear()
            parent = self.invisibleRootItem()

            self.setColumnCount(2)

        #parent.setEditTriggers(QtGui.QAbstractItemView.DoubleClicked)        
        for key in sorted(config.keys()):
            if(key == 'lines'):
                linesparent = QtWidgets.QTreeWidgetItem([key,''])                
                parent.addChild(linesparent)
                for iline,line in enumerate(config['lines']):
                    lineparent = QtWidgets.QTreeWidgetItem(['line',str(iline)])                
                    linesparent.addChild(lineparent)
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
                            # Check for autocomplete
                            if(linekey == 'device'):
                                pass

                                
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
        self.blockSignals(False)
        self.config_changed.emit(config)

    def edititem(self,item,colno):
        funcname = __name__ + 'edititem()'
        #print('Hallo!',item,colno)
        logger.debug(funcname + str(item.text(0)) + ' ' + str(item.text(1)))
        self.item_change = item # Save item that is to be changed
        if(item.text(0) == 'device'):
            
            # Let the user choose all devices and take care that the devices has been connected
            self.devicechoose = redvypr_devicelist_widget(self.redvypr, device = None, deviceonly=True, subscribed_only=False) # Open a device choosing widget
            self.devicechoose.device_name_changed.connect(self.itemtextchange)
            self.devicechoose.show()
            
        if((item.text(0) == 'x') or (item.text(0) == 'y')):
            # Get the devicename first
            parent = item.parent()
            devicename = ''
            device_datakey = None
            print('Childcount',parent.childCount())
            for i in range(parent.childCount()):
                child = parent.child(i)
                keystring = child.text(0)
                print('keystring',keystring)
                if(keystring == 'device'):
                    devicestr_datakey = child.text(1)
                    print('Devicename',devicestr_datakey)
                    break
            
            if(devicestr_datakey is not None): 
                print('Opening devicelist widget')       
                self.devicechoose = redvypr_devicelist_widget(self.redvypr, device = devicestr_datakey,devicename_highlight = devicestr_datakey,deviceonly=False,devicelock = True, subscribed_only=False) # Open a device choosing widget
                #self.devicechoose = redvypr_devicelist_widget(self.redvypr, device = self.device,deviceonly=False,devicelock = True) # Open a device choosing widget
                self.devicechoose.datakey_name_changed.connect(self.itemchanged)
                self.devicechoose.show()

            
    def itemtextchange(self,itemtext):
        """ Changes the current item text self.item_change, which is defined in self.item_changed. This is a wrapper function to work with signals that return text only
        """
        self.item_change.setText(1,itemtext)





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
        super(QtWidgets.QFrame, self).__init__()
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
            self.config['showtime']
        except:
            self.config['showtime'] = True
            
        try:
            self.config['dataformat']
        except:
            self.config['dataformat'] = "+2.5f"

        try:
            self.config['devicelabel']
        except:
            self.config['devicelabel'] = True
            
        # Using the properties key in the data
        try:
            self.config['useprops']
        except:
            self.config['useprops'] = True

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
                
            if(self.config['showtime']):
                self.timedisp = QtWidgets.QLabel(self.get_timestr(0))
                self.timedisp.setStyleSheet("border : 1px solid {:s};".format(backcolor))
                self.timedisp.setAlignment(QtCore.Qt.AlignCenter)
                self.layout.addWidget(self.timedisp,2,0,1,2)

            # Unit
            try:
                unit = config['unit']
            except:
                unit = ""

            self.unit = unit                
            #if((len(unit)>0) or (self.config['useprops'])):
            if True:
                self.unitdisp = QtWidgets.QLabel(unit)
                self.unitdisp.setStyleSheet("border : 1px solid {:s};".format(backcolor))            
                self.layout.addWidget(self.unitdisp,3,1)

            
            self.numdisp = QtWidgets.QLabel("#")
            self.numdisp.setStyleSheet("border : 1px solid {:s};font-weight: bold; font-size: {:d}pt".format(backcolor,fontsize))            
            #
            self.layout.addWidget(self.numdisp,3,0)

    def get_timestr(self,unixtime,format=None):
        """ Returns a time string
        """
        if(format == None):
            tstr = datetime.datetime.fromtimestamp(unixtime).isoformat(timespec='milliseconds')
        else:
            tstr = datetime.datetime.fromtimestamp(unixtime).strftime(format)
        return tstr
                
    def update_plot(self,data):
        """ Updates the plot based on the given data
        """
        funcname = __name__ + '.update()'
        tnow = time.time()
        #print('got data',data)
        devicename = data['device']
        datakey = self.config['data']
        if(device_in_data(self.config['device'],data)):
            dataformat = self.config['dataformat']
            # data can be a single float or a list
            newdata = data[datakey]
            newt    = data['t']
            if(type(newdata) == list):
                newdata = newdata[0]
                newt = newt[0]

            datastr = "{0:{dformat}}".format(newdata,dformat=dataformat)
            self.numdisp.setText(datastr)
            
            if(self.config['showtime']):
                self.timedisp.setText(self.get_timestr(newt))
            
            if(self.config['useprops']):
                # Get the propertykey 
                propkey = '?' + datakey 
                try:
                    props = data[propkey]
                except:
                    props = None
                    
            if(props is not None):
                try:
                    unitstr = str(data[propkey]['unit'])
                    self.unit = unitstr
                except Eception as e:
                    pass

                
                self.unitdisp.setText(self.unit)
                #self.resize_font(self.unitdisp)                





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
        self.header().setVisible(False)
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
            #print('ohno',e)            

        # Change the dictionary 
        try:
            key = item._ncconfig_key
            if(type(item._ncconfig_[key]) == configdata):
               item._ncconfig_[key].value = newdata # The newdata, parsed with yaml               
            else:
               item._ncconfig_[key] = newdata # The newdata, parsed with yaml

        except Exception as e:
            logger.debug(funcname + '{:s}'.format(str(e)))

        self.resizeColumnToContents(0)                            

    def create_qtree(self,config,editable=True):
        """Creates a new qtree from the configuration and replaces the data in
        the dictionary with a configdata obejct, that save the data
        but also the qtreeitem, making it possible to have a synced
        config dictionary from/with a qtreewidgetitem. TODO: Worth to
        replace with a qviewitem?

        """
        funcname = __name__ + '.create_qtree():'
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
        self.resizeColumnToContents(0)                            
    

            



#
# Custom object to store optional data as i.e. qitem, but does not
# pickle it, used to get original data again
#
class configdata():
    """ This is a class that stores the original data and potentially
    additional information, if it is pickled it is only returning
    self.value but not potential additional information

    """
    def __init__(self, value):
        self.value = value
    def __reduce__(self):
        return (type(self.value), (self.value, ))



