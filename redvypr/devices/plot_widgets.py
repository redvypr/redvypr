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

import redvypr.data_packets
from redvypr.data_packets import addr_in_data, get_keys_from_data, parse_addrstr
from redvypr.gui import redvypr_devicelist_widget
import redvypr.files as files
from redvypr.utils import configtemplate_to_dict, configdata, getdata
from redvypr.device import redvypr_device
from redvypr.data_packets import do_data_statistics, create_data_statistic_dict,check_for_command
from copy import deepcopy as dc

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
description_graph = 'Device that plots the received data'
config_template_graph_line = {}
config_template_graph_line['template_name'] = 'Line'
config_template_graph_line['buffersize'] = {'type': 'int', 'default': 2000,
                                           'description': 'The size of the buffer holding the data of the line'}
config_template_graph_line['name'] = {'type': 'str', 'default': '',
                                     'description': 'The name of the line, this is shown in the legend'}
config_template_graph_line['x'] = {'type': 'datastream', 'default': 'NA',
                                  'description': 'The x-data of the plot'}
config_template_graph_line['y'] = {'type': 'datastream', 'default': 'NA',
                                  'description': 'The y-data of the plot'}
config_template_graph_line['color'] = {'type': 'color', 'default': 'r',
                                      'description': 'The color of the plot'}
config_template_graph_line['linewidth'] = {'type': 'int', 'default': 1,
                                          'description': 'The linewidth of the line'}
config_template_graph = {}
config_template_graph['template_name'] = 'Realtime graph'
config_template_graph['type'] = {'type': 'str', 'default': 'graph', 'modify': False}
config_template_graph['backgroundcolor'] = {'type': 'color', 'default': 'lightgray'}
config_template_graph['bordercolor'] = {'type': 'color', 'default': 'lightgray'}

config_template_graph['useprops'] = {'type': 'bool', 'default': True,
    'description': 'Use the properties to display units etc.'}
config_template_graph['datetick'] = {'type': 'bool', 'default': True,
    'description': 'x-axis is a date axis'}

config_template_graph['title'] = {'type': 'str', 'default': ''}
config_template_graph['xlabel'] = {'type': 'str', 'default': ''}
config_template_graph['ylabel'] = {'type': 'str', 'default': ''}
l1 = copy.deepcopy(config_template_graph_line)
l2 = copy.deepcopy(config_template_graph_line)
config_template_graph['lines'] = {'type': 'list', 'default': [l1], 'dynamic': True,
                                 'options': [config_template_graph_line]}
#config_template_graph['description'] = description_graph

class redvypr_graph_widget(QtWidgets.QFrame):
    """ Widget is plotting realtimedata using the pyqtgraph functionality
    This widget can be configured with a configuration dictionary 
    """
    def __init__(self,config=None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QFrame, self).__init__()
        self.description = description_graph
        self.config_template = config_template_graph

        if(config == None): # Create a config from the template
            config = configtemplate_to_dict(self.config_template)
            config = copy.deepcopy(config)
            self.config = config

        logger.debug('plot widget config {:s}'.format(str(config)))

        try:
            backcolor = config['backgroundcolor']
        except:
            backcolor = 'lightgray'
            
        try:
            bordercolor = config['bordercolor']
        except:
            bordercolor = 'black'
            
        try:
            config['useprops']
        except:
            config['useprops'] = True
            
        self.setStyleSheet("background-color : {:s};border : 1px solid {:s};".format(backcolor,bordercolor))
        self.layout = QtWidgets.QVBoxLayout(self)
        self.config = config
        self.create_widgets()
        self.apply_config()


    def create_widgets(self):


        """
        Creates the configuration

        Returns:

        """
        funcname = __name__ + '.create_widgets()'
        config = self.config
        print('Hallo!, Creating widgets')
        i = 0
        if True:
            logger.debug(funcname + ': Adding plot' + str(config))
            try:
                title = getdata(config['title'])
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
                


            plot_dict = {'widget': plot, 'lines': []}

                
                
        self.plot_dict = plot_dict

    def apply_config(self):
        funcname = __name__ + '.apply_config()'
        print('Hallo!, Apply config!')
        print('config:', self.config)
        plot = self.plot_dict['widget']
        # Title
        title = getdata(self.config['title'])
        plot.setTitle(title)
        # Label
        # If a xlabel is defined
        try:
            plot.setLabel('left', getdata(self.config['ylabel']))
        except:
            pass

        # If a ylabel is defined
        try:
            plot.setLabel('bottom', getdata(self.config['xlabel']))
        except:
            pass

        plot_dict = self.plot_dict
        config = self.config
        # Add lines with the actual data to the graph
        for iline, line in enumerate(getdata(config['lines'])):
            print('Line',line)
            logger.debug(funcname + ':Adding a line to the plot:' + str(line))
            try:
                buffersize = getdata(line['buffersize'])
            except:
                buffersize = self.buffersizestd

            xdata = np.zeros(buffersize) * np.NaN
            ydata = np.zeros(buffersize) * np.NaN
            try:
                name = getdata(line['name'])
            except:
                name = 'line {:d}'.format(iline)

            lineplot = pyqtgraph.PlotDataItem(name=name)

            try:
                x = getdata(line['x'])
            except:
                x = "t"

            try:
                y = getdata(line['y'])
            except:
                y = "numpacket"

            try:
                linewidth = getdata(line['linewidth'])
            except:
                linewidth = 1

            try:
                colors = getdata(line['color'])
                color = QtGui.QColor(colors[0], colors[1], colors[2])
            except Exception as e:
                logger.debug('No color found:' + str(e))
                color = QtGui.QColor(255, 10, 10)

            # Configuration of the line plot
            lineconfig = {'x': x, 'y': y, 'linewidth': linewidth, 'color': color}
            # Add the line and the configuration to the lines list
            line_dict = {'line': lineplot, 'config': lineconfig, 'x': xdata, 'y': ydata}

            plot_dict['lines'].append(line_dict)
            plot.addItem(lineplot)
            # Configuration


        # Update the line configuration
        for iline, line in enumerate(getdata(self.config['lines'])):
            try:
                print('Line',line,iline)
                lineconfig = self.plot_dict['lines'][iline]['config']
                x = getdata(line['x'])
                y = getdata(line['y'])
                xaddr = redvypr.data_packets.redvypr_address(x)
                yaddr = redvypr.data_packets.redvypr_address(y)
                lineconfig['x'] = x
                lineconfig['y'] = y
                lineconfig['xaddr'] = xaddr
                lineconfig['yaddr'] = yaddr

                print('Set pen')
                linewidget = getdata(self.plot_dict['lines'][iline])['line']  # The line to plot
                print('Set pen 1')
                color = getdata(getdata(self.config['lines'])[iline]['color'])
                print('Set pen 2')
                linewidth = getdata(getdata(self.config['lines'])[iline]['linewidth'])
                print('Set pen 3')
                pen = pyqtgraph.mkPen(color, width=linewidth)
                linewidget.setPen(pen)
            except Exception as e:
                logger.debug('Exception config lines: {:s}'.format(str(e)))



        print('Apply')
        
    def clear_buffer(self):
        """ Clears the buffer of all lines
        """
        # Check if the device is to be plotted
        
        for ind,line_dict in enumerate(self.plot_dict['lines']): # Loop over all lines of the device to plot
            line      = line_dict['line'] # The line to plot
            config    = line_dict['config'] # The line to plot
            line_dict['x'][:] = np.NaN
            line_dict['y'][:] = np.NaN
        
    def update_plot(self,data):
        """ Updates the plot based on the given data
        """
        print('Hallo',data)
        funcname = self.__class__.__name__ + '.update_plot():'
        tnow = time.time()
        print(funcname + 'got data',data,tnow)
        # Always update
        update = True
        #try:
        if True:
            # Loop over all plot axes
            if True:
                plot_dict = self.plot_dict
                # Check if the device is to be plotted
                for line_dict in plot_dict['lines']:  # Loop over all lines of the devices to plot
                    print('line dict',line_dict)
                    xaddr = line_dict['config']['xaddr']
                    yaddr = line_dict['config']['yaddr']
                    print('adresses:',xaddr,yaddr)
                    if(data in xaddr) and (data in yaddr):
                        pw        = plot_dict['widget'] # The plot widget
                        line      = line_dict['line'] # The line to plot
                        config    = line_dict['config'] # The line to plot
                        xdata     = line_dict['x'] # The line to plot
                        ydata         = line_dict['y'] # The line to plot
                        # data can be a single float or a list
                        newx = data[xaddr.datakey]
                        newy = data[yaddr.datakey]
                        if(type(newx) is not list):
                            newx = [newx]
                            newy = [newy]

                        for inew in range(len(newx)): # TODO this can be optimized using indices instead of a loop
                            xdata         = np.roll(xdata,-1)
                            ydata         = np.roll(ydata,-1)
                            xdata[-1]    = float(newx[inew])
                            ydata[-1]    = float(newy[inew])
                            line_dict['x']  = xdata
                            line_dict['y']  = ydata

                        if('useprops' in self.config.keys()):
                            if(self.config['useprops']):
                                propkey = '?' + yaddr.datakey
                                try:
                                    unitstr ='[' + data[propkey]['unit'] + ']'
                                    pw.setLabel('left', unitstr)
                                except:
                                    pass



            if(update):
                for line_dict in plot_dict['lines']:  # Loop over all lines of the devices to plot
                    line      = line_dict['line'] # The line to plot
                    config    = line_dict['config'] # The line to plot
                    x         = line_dict['x'] # The line to plot
                    y         = line_dict['y'] # The line to plot
                    line.setData(x=x,y=y)
                    #pw.setXRange(min(x[:ind]),max(x[:ind]))

        #except Exception as e:
        #    #print(funcname + 'Exception:' + str(e))
        #    logger.debug(funcname + 'Exception:' + str(e))



#
#                
#
# numeric display widget
#
#
#
description_numdisp = 'Device that plots the received data'
rdvpraddr = redvypr.data_packets.redvypr_address('tmp')
config_template_numdisp = {}
config_template_numdisp['name'] = 'Numeric display'
config_template_numdisp['type'] = {'type': 'str', 'default': 'numdisp', 'modify': False}
config_template_numdisp['backgroundcolor'] = {'type': 'color', 'default': 'lightgray'}
config_template_numdisp['bordercolor'] = {'type': 'color', 'default': 'lightgray'}
config_template_numdisp['fontsize'] = {'type': 'int', 'default': 20}
config_template_numdisp['datastream'] = {'type': 'datastream', 'default': 'NA'}
config_template_numdisp['timeformat'] = {'type': 'str', 'default': '%d-%b-%Y %H:%M:%S'}
config_template_numdisp['datastreamlabel'] = {'type': 'str', 'options': rdvpraddr.get_strtypes(),
                                           'default': '<key>/<device>', 'description': 'Display the datastreamlabel'}
config_template_numdisp['useprops'] = {'type': 'bool', 'default': True,
                                    'description': 'Use the properties to display units etc.'}
config_template_numdisp['dataformat'] = {'type': 'str', 'default': 'f',
                                      'description': 'The format the data is shown, this will be interpreted as "{:dataformat}".format(data)'}
config_template_numdisp['title'] = {'type': 'str', 'default': ''}
config_template_numdisp['description'] = description_numdisp

class redvypr_numdisp_widget(QtWidgets.QFrame):
    """ Widget is plotting realtimedata on a display
    """
    def __init__(self,config=None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QFrame, self).__init__()
        self.redvypr_addrtmp = redvypr.data_packets.redvypr_address('tmp')
        #self.setStyleSheet("border : 1px solid lightgray;background-color : lightgray")
        #self.setStyleSheet("backgrounNAd-color : red")
        self.description = description_numdisp
        self.config_template = config_template_numdisp

        if(config == None): # Create a config from the template
            config = configtemplate_to_dict(self.config_template)
            config = copy.deepcopy(config)
            self.config = config


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
            config['timeformat']
        except:
            config['timeformat'] = self.config_template['timeformat']['default']
            
        try:
            config['dataformat']
        except:
            config['dataformat'] = "+2.5f"

        try:
            config['datastreamlabel']
        except:
            config['datastreamlabel'] = True
            
        # Using the properties key in the data
        try:
            config['useprops']
        except:
            config['useprops'] = True

        # Title
        try:
            title = config['title']
        except:
            title = ""

        # Unit
        try:
            unit = config['unit']
        except:
            unit = ""

        self.unit = unit


        self.titledisp = QtWidgets.QLabel(getdata(title))
        self.titledisp.hide()

        self.devicedisp = QtWidgets.QLabel(getdata(self.config['datastream']))
        self.devicedisp.hide()

        self.timedisp = QtWidgets.QLabel(self.get_timestr(0,format=config['timeformat']))
        self.timedisp.hide()

        self.unitdisp = QtWidgets.QLabel(getdata(unit))
        self.unitdisp.hide()


        self.setStyleSheet("background-color : {:s};border : 1px solid {:s};".format(dc(config['backgroundcolor']),dc(config['bordercolor'])))
        self.layout = QtWidgets.QGridLayout(self)
        if True:
            logger.debug(funcname + ': Adding plot' + str(config))
            self.apply_config()

            self.numdisp = QtWidgets.QLabel("#")
            self.numdisp.setStyleSheet("border : 1px solid {:s};font-weight: bold; font-size: {:d}pt".format(dc(config['backgroundcolor']),dc(config['fontsize'])))
            #
            self.layout.addWidget(self.numdisp,3,0)


    def apply_config(self):
        """
        Applies the config to the widgets
        Returns:

        """
        funcname = __name__ + '.apply_config():'
        logger.debug(funcname)
        title = getdata(self.config['title'])
        if (len(title) > 0): # Show title
            self.titledisp.setText(title)
            self.titledisp.setStyleSheet("font-weight: bold;border : 1px solid {:s};".format(getdata(self.config['backgroundcolor'])))
            self.titledisp.setAlignment(QtCore.Qt.AlignCenter)
            self.layout.addWidget(self.titledisp, 0, 0, 1, 2)
            self.titledisp.show()
        else: # Do not show title
            try:
                self.layout.removeWidget(self.titledisp)
                self.titledisp.hide()
            except Exception as e:
                print('problem',e)
                pass

        if (getdata(self.config['datastreamlabel'])): # TODO, let the user choose the datastream display options (UUID, key, key + address ...)
            self.redvypr_addrconv = redvypr.data_packets.redvypr_address(getdata(self.config['datastream']))
            dstrlabel = getdata(self.config['datastreamlabel'])
            print('dffdsf',dstrlabel)
            dstr = self.redvypr_addrconv.get_str(dstrlabel)
            print('Hallohallo',dstr)
            print('parsed',self.redvypr_addrconv.parsed_addrstr)
            self.devicedisp.setText(dstr)
            self.devicedisp.setStyleSheet("border : 1px solid {:s};".format(getdata(self.config['backgroundcolor'])))
            self.devicedisp.setAlignment(QtCore.Qt.AlignCenter)
            self.layout.addWidget(self.devicedisp, 1, 0, 1, 2)
            self.devicedisp.show()
        else:
            self.layout.removeWidget(self.devicedisp)
            self.devicedisp.hide()

        timefmt = getdata(self.config['timeformat'])
        if(len(timefmt)>0):
            self.timedisp.setStyleSheet("border : 1px solid {:s};".format(getdata(self.config['backgroundcolor'])))
            self.timedisp.setText(self.get_timestr(0, format=timefmt))
            self.timedisp.setAlignment(QtCore.Qt.AlignCenter)
            self.layout.addWidget(self.timedisp, 2, 0, 1, 2)
            self.timedisp.show()
        else:
            self.layout.removeWidget(self.timedisp)
            self.timedisp.hide()

        if(len(self.unit)>0):
            self.unitdisp.setStyleSheet("border : 1px solid {:s};".format(getdata(self.config['backgroundcolor'])))
            self.layout.addWidget(self.unitdisp, 3, 1)
            self.unitdisp.show()
        else:
            self.layout.removeWidget(self.unitdisp)
            self.unitdisp.hide()




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
        logger.debug(funcname)
        tnow = time.time()
        print(funcname + ': got data', data)
        print('config', self.config)
        datastream = getdata(self.config['datastream'])
        dataformat = getdata(self.config['dataformat'])
        parsed_stream = parse_addrstr(datastream)
        datakey = parsed_stream['datakey']
        print('datastram', datastream)
        print('datakey', datakey)
        print('in data',addr_in_data(datastream, data))
        if(addr_in_data(datastream,data)):
            # data can be a single float or a list
            newdata = data[datakey]
            newt    = data['t']
            if(type(newdata) == list):
                newdata = newdata[0]
                newt = newt[0]

            datastr = "{0:{dformat}}".format(newdata,dformat=dataformat)
            self.numdisp.setText(datastr)

            timefmt = getdata(self.config['timeformat'])
            if(len(timefmt)>0):
                self.timedisp.setText(self.get_timestr(newt,format=timefmt))
            
            if(getdata(self.config['useprops'])):
                # Get the propertykey 
                propkey = '?' + datakey 
                try:
                    props = data[propkey]
                except:
                    props = None
                    
            if(props is not None):
                try:
                    unitstr = str(getdata(data[propkey]['unit']))
                    self.unit = unitstr
                except Exception as e:
                    pass

                
                self.unitdisp.setText(self.unit)
                #self.resize_font(self.unitdisp)                






    
