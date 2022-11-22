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
from redvypr.data_packets import device_in_data, get_keys_from_data, parse_devicestring
from redvypr.gui import redvypr_devicelist_widget
import redvypr.files as files
from redvypr.utils import configtemplate_to_dict
from redvypr.device import redvypr_device
from redvypr.data_packets import do_data_statistics, create_data_statistic_dict,check_for_command

_logo_file = files.logo_file
_icon_file = files.icon_file
pyqtgraph.setConfigOption('background', 'w')
pyqtgraph.setConfigOption('foreground', 'k')

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('plot_widgets')
logger.setLevel(logging.DEBUG)



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
# numeric display widget
#
#
#
class redvypr_numdisp_widget(QtWidgets.QFrame):
    """ Widget is plotting realtimedata on a display
    """
    def __init__(self,config=None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QFrame, self).__init__()
        #self.setStyleSheet("border : 1px solid lightgray;background-color : lightgray")
        #self.setStyleSheet("background-color : red")
        self.description = 'Device that plots the received data'
        self.config_template = {}
        self.config_template['backgroundcolor'] = {'type':'str','default':'lightgray'}
        self.config_template['bordercolor'] = {'type': 'str', 'default': 'lightgray'}
        self.config_template['fontsize']    = {'type': 'int', 'default': 50}
        self.config_template['device']      = {'type': 'str', 'default': 'NA'}  # TODO, make a datastream
        self.config_template['datastream']  = {'type': 'datastream', 'default': 'NA'}  # TODO, make a datastream
        self.config_template['showtime']    = {'type': 'bool', 'default': True}
        self.config_template['devicelabel'] = {'type': 'bool', 'default': True,'description':'Display the devicelabel'}
        self.config_template['useprops']    = {'type': 'bool', 'default': True,
                                               'description': 'Use the properties to display units etc.'}
        self.config_template['dataformat']  = {'type': 'str', 'default': 'f','description':'The format the data is shown, this will be interpreted as "{:dataformat}".format(data)'}
        self.config_template['description'] = self.description
        if(config == None): # Create a config from the template
            config = configtemplate_to_dict(self.config_template)
            self.config = config
            #config = copy.deepcopy(config)

        print('widget config',config)
        try:
            config['backgroundcolor']
        except:
            config['backgroundcolor'] = 'lightgray'

        try:
            config['bordercolor']
        except:
            config['bordercolor'] = 'black'

        try:
            config['fontsize']
        except:
            config['fontsize'] = 50

        try:
            config['showtime']
        except:
            config['showtime'] = True
            
        try:
            config['dataformat']
        except:
            config['dataformat'] = "+2.5f"

        try:
            config['devicelabel']
        except:
            config['devicelabel'] = True
            
        # Using the properties key in the data
        try:
            config['useprops']
        except:
            config['useprops'] = True

        config = copy.deepcopy(config)
        self.config = config
        self.setStyleSheet("background-color : {:s};border : 1px solid {:s};".format(config['backgroundcolor'],config['bordercolor']))
        self.layout = QtWidgets.QGridLayout(self)
        if True:
            logger.debug(funcname + ': Adding plot' + str(config))
            # Title
            try:
                title = config['title']
            except:
                title = ""

            if(len(title)>0):
                self.titledisp = QtWidgets.QLabel(title)
                self.titledisp.setStyleSheet("font-weight: bold;border : 1px solid {:s};".format(config['backgroundcolor']))
                self.titledisp.setAlignment(QtCore.Qt.AlignCenter)
                self.layout.addWidget(self.titledisp,0,0,1,2)

            if(self.config['devicelabel']):
                self.devicedisp = QtWidgets.QLabel(self.config['device'])
                self.devicedisp.setStyleSheet("border : 1px solid {:s};".format(config['backgroundcolor']))
                self.devicedisp.setAlignment(QtCore.Qt.AlignCenter)
                self.layout.addWidget(self.devicedisp,1,0,1,2)
                
            if(self.config['showtime']):
                self.timedisp = QtWidgets.QLabel(self.get_timestr(0))
                self.timedisp.setStyleSheet("border : 1px solid {:s};".format(config['backgroundcolor']))
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
                self.unitdisp.setStyleSheet("border : 1px solid {:s};".format(config['backgroundcolor']))
                self.layout.addWidget(self.unitdisp,3,1)

            
            self.numdisp = QtWidgets.QLabel("#")
            self.numdisp.setStyleSheet("border : 1px solid {:s};font-weight: bold; font-size: {:d}pt".format(config['backgroundcolor'],config['fontsize']))
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
        print(funcname + ': got data', data)
        print('config', self.config)
        devicename = data['device']
        datastream = self.config['datastream']
        parsed_stream = parse_devicestring(datastream)
        datakey = parsed_stream['datakey']
        print('datastram', datastream)
        print('datakey', datakey)
        print('in data',device_in_data(datastream, data))
        if(device_in_data(datastream,data)):
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
                except Exception as e:
                    pass

                
                self.unitdisp.setText(self.unit)
                #self.resize_font(self.unitdisp)                






    
