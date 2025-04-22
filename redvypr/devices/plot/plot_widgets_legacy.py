import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import yaml
import copy
import pyqtgraph

import redvypr.data_packets
import redvypr.gui
import redvypr.files as files
#from redvypr.configdata import configtemplate_to_dict, configdata, getdata
from copy import deepcopy as dc

_logo_file = files.logo_file
_icon_file = files.icon_file
pyqtgraph.setConfigOption('background', 'w')
pyqtgraph.setConfigOption('foreground', 'k')

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.plot_widgets')
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)



#
#                
#
# Plot widget
#
#
#

config_template_grid_loc = {}
config_template_grid_loc['template_name'] = 'gridloc'
config_template_grid_loc['x'] = {'type': 'int', 'default': 0}
config_template_grid_loc['y'] = {'type': 'int', 'default': 0}
config_template_grid_loc['width'] = {'type': 'int', 'default': 1}
config_template_grid_loc['height'] = {'type': 'int', 'default': 1}

description_graph = 'Device that plots the received data'
config_template_graph_line = {}
config_template_graph_line['template_name'] = 'Line'
config_template_graph_line['buffersize'] = {'type': 'int', 'default': 2000,
                                           'description': 'The size of the buffer holding the data of the line'}
config_template_graph_line['name'] = {'type': 'str', 'default': '$y',
                                     'description': 'The name of the line, this is shown in the legend'}
config_template_graph_line['x'] = {'type': 'datastream', 'default': '$t(y)',
                                  'description': 'The x-data of the plot'}
config_template_graph_line['y'] = {'type': 'datastream', 'default': '',
                                  'description': 'The y-data of the plot'}
config_template_graph_line['color'] = {'type': 'color', 'description': 'The color of the plot'}
config_template_graph_line['linewidth'] = {'type': 'int', 'default': 1,
                                          'description': 'The linewidth of the line'}
config_template_graph = {}
config_template_graph['template_name'] = 'Realtime graph'
config_template_graph['location']    = config_template_grid_loc
config_template_graph['type']        = {'type': 'str', 'default': 'graph', 'modify': False}
config_template_graph['dt_update']   = {'type': 'float', 'default': 0.25, 'modify': True,'description':'update time of plot'}
config_template_graph['interactive'] = {'type': 'str', 'default': 'mouse', 'modify': True,'description':'Interactive modes'}
config_template_graph['backgroundcolor'] = {'type': 'color', 'default': 'lightgray'}
config_template_graph['bordercolor'] = {'type': 'color', 'default': 'lightgray'}

config_template_graph['useprops'] = {'type': 'bool', 'default': True,
    'description': 'Use the properties to display units etc.'}

config_template_graph['showunits'] = {'type': 'bool', 'default': True,
    'description': 'Add the unit of the y-data to the legend, queried from the datakey.'}
config_template_graph['datetick'] = {'type': 'bool', 'default': True,
    'description': 'x-axis is a date axis'}

config_template_graph['title'] = {'type': 'str', 'default': ''}
config_template_graph['xlabel'] = {'type': 'str', 'default': ''}
config_template_graph['ylabel'] = {'type': 'str', 'default': ''}
config_template_graph['lines'] = {'type': 'list', 'default': [config_template_graph_line], 'modify': True,
                                 'options': [config_template_graph_line]}
#config_template_graph['description'] = description_graph



class redvypr_graph_widget(QtWidgets.QFrame):
    """ Widget is plotting realtimedata using the pyqtgraph functionality
    This widget can be configured with a configuration dictionary 
    """
    def __init__(self,config=None, redvypr_device = None , loglevel = logging.DEBUG):
        funcname = __name__ + '.init():'
        super(QtWidgets.QFrame, self).__init__()
        self.device = redvypr_device
        self.logger = logging.getLogger('plot_graph_widget')
        self.logger.setLevel(loglevel)
        self.description = description_graph
        self.config_template = config_template_graph

        if(config == None): # Create a config from the template
            self.config = redvypr.config.configuration(self.config_template)
        else:
            self.config = redvypr.config.configuration(self.config_template,config=config)

        #self.logger.debug('plot widget config {:s}'.format(str(self.config)))
        backcolor = str(self.config['backgroundcolor'])
        bordercolor = str(self.config['bordercolor'])
        #logger.debug(funcname + 'backcolor {:s}'.format(str(backcolor)))
        style = "background-color : {:s};border : 1px solid {:s};".format(backcolor, bordercolor)
        #logger.debug(funcname + 'Style: {:s}'.format(str(style)))
        self.setStyleSheet(style)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.create_widgets()
        self.apply_config()


    def create_widgets(self):


        """
        Creates the configuration

        Returns:

        """
        funcname = __name__ + '.create_widgets()'
        config = self.config
        logger.debug(funcname)
        i = 0
        if True:
            logger.debug(funcname + ': Adding plot ')# + str(config))
            try:
                title = config['title'].data
            except:
                title = "Plot {:d}".format(i)
                
            try:
                name = config['name'].data
            except:
                name = "Plot {:d}".format(i)

            # https://stackoverflow.com/questions/44402399/how-to-disable-the-default-context-menu-of-pyqtgraph
            plot = pyqtgraph.PlotWidget(title=title,name=name)
            menu = plot.plotItem.vb.menu.addMenu('Redvypr config')
            action = menu.addAction('Line config')
            action.triggered.connect(self.pyqtgraphRedvyprAction)

            #plot = redvyprPlotWidget(title=title,name=name)
            plot.register(name=name)
            # Add a legend
            legend = plot.addLegend()
            if config['interactive'].lower() == 'mouse':
                self.logger.debug('Adding interactive mouse (vertical line)')
                plot.scene().sigMouseMoved.connect(self.mouseMoved)
                plot.scene().sigMouseClicked.connect(self.mouseClicked)
                self.vb = plot.plotItem.vb
                # Add a vertical line
                color = QtGui.QColor(200,100,100)
                linewidth = 2
                pen = pyqtgraph.mkPen(color, width=linewidth)
                self.vLineMouse = pyqtgraph.InfiniteLine(angle=90, movable=False, pen=pen)
                #print('Set pen 3')
                plot.addItem(self.vLineMouse, ignoreBounds=True)

            self.layout.addWidget(plot)
                
            config.plot = plot
            config.legend = legend
            #plot_dict = {'widget': plot, 'lines': []}

                
                
        #self.plot_dict = plot_dict


    def pyqtgraphRedvyprAction(self,hallo):
        """

        """
        funcname = __name__ + '.pyqtgraphRedvyprAction()'
        logger.debug(funcname)
        self.configWidget = redvypr.gui.configWidget(self.config)
        self.configWidget.setWindowIcon(QtGui.QIcon(_icon_file))
        self.configWidget.config_changed_flag.connect(self.apply_config)
        self.configWidget.show()


    def mouseMoved(self,evt):
        """Function if mouse has been moved
        """
        pos = (evt.x(),evt.y())
        mousePoint = self.vb.mapSceneToView(evt)
        #print('mouse moved',mousePoint.x())
        self.vLineMouse.setPos(mousePoint.x())
        #for vline in self.vlines:
        #    vline.setPos(mousePoint.x())

    def mouseClicked(self,evt):
        #col =
        #col = pg.mkPen(0.5,width=3)
        #colsymbol = pg.mkPen(color=QtGui.QColor(150,150,150),width=4)
        #print('Clicked: ' + str(evt.scenePos()))
        pass

    def set_title(self,title):
        """
        Sets the title of the plot
        """
        funcname = __name__ + '.set_title()'
        logger.debug(funcname)
        self.config['title'].data = title
        self.config.plot.setTitle(title)

    def set_line(self, index, y, name='$y', x='$t(y)', color=[255, 0, 0], linewidth=1, bufsize=2000):
        """
        Sets the line at index to the parameters
        """

        self.add_line(y, name, x, color, linewidth, bufsize, index = index)

    def add_line(self,y,name='$y',x='$t(y)', color=[255,0,0], linewidth=1, bufsize=2000, index = None):
        """
        Adds a line to the plot
        """
        funcname = __name__ + '.add_line()'
        logger.debug(funcname)
        if index is None:
            rconfig = redvypr.config.configuration(config_template_graph_line)
            self.config['lines'].data.append(rconfig)
            index = len(self.config['lines']) - 1

        config_line = {}
        self.config['lines'][index]['buffersize'].data = bufsize
        self.config['lines'][index]['linewidth'].data = linewidth
        qcolor_tmp = redvypr.gui.get_QColor(color)
        self.config['lines'][index]['color']['r'].data = qcolor_tmp.red()
        self.config['lines'][index]['color']['g'].data = qcolor_tmp.green()
        self.config['lines'][index]['color']['b'].data = qcolor_tmp.blue()
        self.config['lines'][index]['x'].data = x
        self.config['lines'][index]['y'].data = y
        self.config['lines'][index]['name'].data = name

        self.apply_config()

        #config_template_graph_line = {}
        #config_template_graph_line['template_name'] = 'Line'
        #config_template_graph_line['buffersize'] = {'type': 'int', 'default': 2000,
        #                                            'description': 'The size of the buffer holding the data of the line'}
        #config_template_graph_line['name'] = {'type': 'str', 'default': '$y',
        #                                      'description': 'The name of the line, this is shown in the legend'}
        #config_template_graph_line['x'] = {'type': 'datastream', 'default': '$t(y)',
        #                                   'description': 'The x-data of the plot'}
        #config_template_graph_line['y'] = {'type': 'datastream', 'default': '',
        #                                   'description': 'The y-data of the plot'}
        #config_template_graph_line['color'] = {'type': 'color', 'description': 'The color of the plot'}
        #config_template_graph_line['linewidth'] = {'type': 'int', 'default': 1,
        #                                           'description': 'The linewidth of the line'}

    def apply_config(self):
        """
        Function is called by the initialization or after the configuration was changed

        Returns:

        """
        funcname = __name__ + '.apply_config()'
        logger.debug(funcname)
        plot = self.config.plot
        # Title
        title = self.config['title'].data
        plot.setTitle(title)

        try:
            datetick = self.config['datetick'].data
        except:
            datetick = False

        if datetick:
            logger.debug(funcname + 'Datetick')
            axis = pyqtgraph.DateAxisItem(orientation='bottom',utcOffset=0)
            plot.setAxisItems({"bottom": axis})
        else:
            logger.debug(funcname + ' No Datetick')
            axis = pyqtgraph.AxisItem(orientation='bottom')
            plot.setAxisItems({"bottom": axis})


        # Label
        # If a xlabel is defined
        try:
            plot.setLabel('left', self.config['ylabel'].data)
        except:
            pass

        # If a ylabel is defined
        try:
            plot.setLabel('bottom', self.config['xlabel'].data)
        except:
            pass

        # Add lines with the actual data to the graph
        for iline, line in enumerate(self.config['lines']):
            #print('Line',line)
            #FLAG_HAVE_LINE = False

            # check if we have already a lineplot, if yes, dont bother
            try:
                line.lineplot
                continue
            except:
                pass

            logger.debug(funcname + ': Adding a line to the plot:')# + str(line))
            buffersize = line['buffersize'].data
            tdata = np.zeros(buffersize) * np.NaN
            xdata = np.zeros(buffersize) * np.NaN
            ydata = np.zeros(buffersize) * np.NaN

            try:
                name = line['name'].data
            except:
                name = 'line {:d}'.format(iline)

            lineplot = pyqtgraph.PlotDataItem(name=name)
            line.lineplot = lineplot # Add the line as an attribute to the configuration
            try:
                x = line['x'].data
            except:
                pass

            try:
                y = line['y'].data
            except:
                pass

            try:
                linewidth = line['linewidth'].data
            except:
                linewidth = 1

            try:
                color = redvypr.gui.get_QColor(line['color'])
            except Exception as e:
                logger.debug('Definition of color not usable:')
                logger.exception(e)
                color = QtGui.QColor(255, 10, 10)

            # Configuration of the line plot
            lineconfig = {'x': x, 'y': y, 'linewidth': linewidth, 'color': color}
            # Add the line and the configuration to the lines list
            line_dict = {'line': lineplot, 'config': lineconfig, 'xdata': xdata, 'ydata': ydata, 'tdata':tdata,'tlastupdate':0}
            line.line_dict = line_dict
            plot.addItem(lineplot)
            # Configuration


        # Update the line configuration
        self.config.legend.clear()
        for iline, line in enumerate(self.config['lines']):
            try:
                logger.debug(funcname + ': Updating line {:d}'.format(iline))
                #print('Line',line,iline)

                lineconfig = line.line_dict['config']
                #print('Lineconfig',lineconfig)
                # The data buffer
                tdata = line.line_dict['tdata']
                xdata = line.line_dict['xdata']
                ydata = line.line_dict['ydata']
                if(len(xdata) != line['buffersize']):
                    buffersize = line['buffersize']
                    print('Updating the buffersize')
                    line.line_dict['tdata'] = np.zeros(buffersize) * np.NaN
                    line.line_dict['xdata'] = np.zeros(buffersize) * np.NaN
                    line.line_dict['ydata'] = np.zeros(buffersize) * np.NaN


                x = line['x'].data
                y = line['y'].data
                yaddr = redvypr.data_packets.redvypr_address(y)
                if(x == '$t(y)'):
                    logger.debug(funcname + ' Using time variable of y')
                    xtmp = redvypr.data_packets.modify_addrstr(yaddr.address_str,datakey='t')
                    #print('xtmp',xtmp)
                    xaddr = redvypr.data_packets.redvypraddress(xtmp)
                else:
                    xaddr = redvypr.data_packets.redvypraddress(x)

                # These attributes are used in plot.Device.connect_devices to actually subscribe to the fitting devices
                line['x'].xaddr = xaddr
                line['y'].yaddr = yaddr
                lineconfig['x'] = x
                lineconfig['y'] = y
                lineconfig['xaddr'] = xaddr
                lineconfig['yaddr'] = yaddr

                #print('Set pen')
                lineplot = line.line_dict['line']  # The line to plot
                #print('Set pen 1')
                color = redvypr.gui.get_QColor(self.config['lines'][iline]['color'])
                #print('COLOR!!!!',color)
                #print('Set pen 2')
                linewidth = self.config['lines'][iline]['linewidth'].data
                #print('Set pen 3')
                pen = pyqtgraph.mkPen(color, width=linewidth)
                lineplot.setPen(pen)
                name = self.config['lines'][iline]['name'].data
                if(name.lower() == '$y'):
                    logger.debug(funcname + ' Replacing with y')
                    name = y

                logger.debug(funcname + ' Setting the name')
                self.config.legend.addItem(lineplot,name)
                lineplot.setData(name=name)
            except Exception as e:
                logger.exception(e)
                logger.debug('Exception config lines: {:s}'.format(str(e)))


        logger.debug(funcname  + ' done.')

        
    def clear_buffer(self):
        """ Clears the buffer of all lines
        """
        # Check if the device is to be plotted
        
        for iline, line in enumerate(self.config['lines']):
            line_dict = line.line_dict
            line      = line_dict['line'] # The line to plot
            config    = line_dict['config'] # The line to plot
            line_dict['tdata'][:] = np.NaN
            line_dict['xdata'][:] = np.NaN
            line_dict['ydata'][:] = np.NaN
            # Set the data
            x = line_dict['xdata']  # The line to plot
            y = line_dict['ydata']  # The line to plot
            line.setData(x=x, y=y)

    def get_data(self, xlim):
        """
        Gets the data of the buffer in the limits of xlim
        """
        funcname = __name__ + '.get_data():'
        tdata = []
        xdata = []
        ydata = []
        for iline, line in enumerate(self.config['lines']):
            line_dict = line.line_dict
            line = line_dict['line']  # The line to plot
            config = line_dict['config']  # The line to plot
            t = line_dict['tdata']  # The line to plot
            x = line_dict['xdata']  # The line to plot
            y = line_dict['ydata']  # The line to plot
            ind = (x > xlim[0]) & (x < xlim[1])
            tdata_tmp = t[ind]
            xdata_tmp = x[ind]
            ydata_tmp = y[ind]
            tdata.append(tdata_tmp)
            xdata.append(xdata_tmp)
            ydata.append(ydata_tmp)
            logger.debug(funcname + ' Got data of length {:d}'.format(len(tdata_tmp)))
            #print('get_data',datetime.datetime.utcfromtimestamp(tdata_tmp[0]),datetime.datetime.utcfromtimestamp(xdata_tmp[0]))


        return {'x':xdata,'y':ydata,'t':tdata}


        
    def update_plot(self, data):
        """ Updates the plot based on the given data
        """
        funcname = self.__class__.__name__ + '.update_plot():'
        tnow = time.time()
        #print(funcname + 'got data',data,tnow)


        #try:
        if True:
            # Loop over all plot axes
            if True:
                # Check if the device is to be plotted
                for iline, line in enumerate(self.config['lines']):
                    line_dict = line.line_dict
                    #print('line dict',line_dict)
                    xaddr = line_dict['config']['xaddr']
                    yaddr = line_dict['config']['yaddr']
                    #print('adresses:',xaddr.get_str(),yaddr.get_str())
                    #print('device',data['_redvypr']['device'])
                    #print('data in',(data in xaddr),(data in yaddr))
                    if (data in xaddr) and (data in yaddr):
                        pw        = self.config.plot # The plot widget
                        line      = line_dict['line'] # The line to plot
                        config    = line_dict['config'] # The line to plot
                        tdata     = line_dict['tdata']  # The line to plot
                        xdata     = line_dict['xdata'] # The line to plot
                        ydata     = line_dict['ydata'] # The line to plot
                        # data can be a single float or a list, if its a list add it item by item
                        newt = data['_redvypr']['t'] # Add also the time of the packet
                        newx = data[xaddr.datakey]
                        newy = data[yaddr.datakey]
                        if(type(newx) is not list):
                            newx = [newx]
                        if (type(newy) is not list):
                            newy = [newy]

                        if(len(newx) != len(newy)):
                            logger.warning('lengths of x and y data different (x:{:d}, y:{:d})'.format(len(newx),len(newy)))
                            return

                        for inew in range(len(newx)): # TODO this can be optimized using indices instead of a loop
                            tdata        = np.roll(tdata, -1)
                            xdata        = np.roll(xdata,-1)
                            ydata        = np.roll(ydata,-1)
                            tdata[-1]    = float(newt)
                            xdata[-1]    = float(newx[inew])
                            ydata[-1]    = float(newy[inew])
                            line_dict['tdata']  = tdata
                            line_dict['xdata']  = xdata
                            line_dict['ydata']  = ydata

                        # Show the unit in the legend, if wished by the user and we have access to the device that can give us the metainformation
                        if (self.config['showunits']) and (self.device is not None):
                            try:
                                line.datakeys # datakeys found, doing nothing
                            except:
                                line.datakeys = self.device.get_datakeyinfo(yaddr)
                                logger.debug(funcname + ' Datakeyinfo {:s}'.format(str(line.datakeys)))
                                unit = None
                                for k in line.datakeys.keys():
                                    #print('key',k,yaddr,k in yaddr)
                                    if k in yaddr:
                                        print('fsfsd')
                                        try:
                                            unit = line.datakeys[k]['unit']
                                            break
                                        except:
                                            unit = None

                                if unit is not None:
                                    name = line.name()
                                    name_new = name + ' [{:s}]'.format(unit)
                                    self.config['lines'][iline]['name'].data = name_new
                                    self.apply_config()

            # Update the lines plot
            for iline, line in enumerate(self.config['lines']):
                line_dict = line.line_dict
                tlastupdate = line_dict['tlastupdate']  # The time the plot was last updated
                # Check if an update of the plot shall be done, or if only the buffer is updated
                dt = tnow - tlastupdate
                if dt > self.config['dt_update']:
                    update = True
                    line_dict['tlastupdate'] = tnow
                    #print('update')
                else:
                    update = False
                    #print('no update')

                if (update):  # We could check here if data was changed above the for given line
                    line      = line_dict['line'] # The line to plot
                    config    = line_dict['config'] # The line to plot
                    x         = line_dict['xdata'] # The line to plot
                    y         = line_dict['ydata'] # The line to plot
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
#rdvpraddr = redvypr.data_packets.redvypr_address('tmp')
config_template_numdisp = {}
config_template_numdisp['template_name'] = 'Numeric display'
config_template_numdisp['type'] = {'type': 'str', 'default': 'numdisp', 'modify': False}
config_template_numdisp['location'] = config_template_grid_loc
config_template_numdisp['backgroundcolor'] = {'type': 'color', 'default': 'lightgray'}
config_template_numdisp['bordercolor'] = {'type': 'color', 'default': 'lightgray'}
config_template_numdisp['fontsize'] = {'type': 'int', 'default': 20}
config_template_numdisp['datastream'] = {'type': 'datastream', 'default': 'NA'}
config_template_numdisp['timeformat'] = {'type': 'str', 'default': '%d-%b-%Y %H:%M:%S'}
config_template_numdisp['unit'] = {'type': 'str', 'default': ''}
config_template_numdisp['datastreamlabel'] = {'type': 'str', 'options': ['tmp1','tmp2'],
                                           'default': '/d:/k:', 'description': 'Display the datastreamlabel'}
config_template_numdisp['useprops'] = {'type': 'bool', 'default': True,
                                    'description': 'Use the properties to display units etc.'}
config_template_numdisp['dataformat'] = {'type': 'str', 'default': 'f',
                                      'description': 'The format the data is shown, this will be interpreted as "{:dataformat}".format(data)'}
config_template_numdisp['title'] = {'type': 'str', 'default': 'test'}
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

        print('Creating configuration')
        if(config == None): # Create a config from the template
            self.config = redvypr.config.configuration(self.config_template)
        else:
            self.config = redvypr.config.configuration(self.config_template,config=config)

        print('widget config',self.config)

        print('tpye',type(self.config['title'].data))
        self.titledisp = QtWidgets.QLabel(self.config['title'].data)
        self.titledisp.hide()

        self.devicedisp = QtWidgets.QLabel(self.config['datastream'].data)
        self.devicedisp.hide()

        self.timedisp = QtWidgets.QLabel(self.get_timestr(0,format=self.config['timeformat'].data))
        self.timedisp.hide()

        self.unitdisp = QtWidgets.QLabel(self.config['unit'].data)
        self.unitdisp.hide()


        self.setStyleSheet("background-color : {:s};border : 1px solid {:s};".format(self.config['backgroundcolor'].data,self.config['bordercolor'].data))
        self.layout = QtWidgets.QGridLayout(self)
        if True:
            logger.debug(funcname + ': Adding plot' + str(self.config))
            self.apply_config()

            self.numdisp = QtWidgets.QLabel("#")
            self.numdisp.setStyleSheet("border : 1px solid {:s};font-weight: bold; font-size: {:d}pt".format(self.config['backgroundcolor'].data,self.config['fontsize'].data))
            #
            self.layout.addWidget(self.numdisp,3,0)


    def apply_config(self):
        """
        Applies the config to the widgets
        Returns:

        """
        funcname = __name__ + '.apply_config():'
        logger.debug(funcname)
        title = self.config['title'].data
        if (len(title) > 0): # Show title
            self.titledisp.setText(title)
            self.titledisp.setStyleSheet("font-weight: bold;border : 1px solid {:s};".format(self.config['backgroundcolor'].data))
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
            self.redvypr_addrconv = redvypr.data_packets.redvypraddress(self.config['datastream'].data)
            dstrlabel = self.config['datastreamlabel'].data
            dstr = self.redvypr_addrconv.get_str(dstrlabel)
            self.devicedisp.setText(dstr)
            self.devicedisp.setStyleSheet("border : 1px solid {:s};".format(self.config['backgroundcolor'].data))
            self.devicedisp.setAlignment(QtCore.Qt.AlignCenter)
            self.layout.addWidget(self.devicedisp, 1, 0, 1, 2)
            self.devicedisp.show()
        else:
            self.layout.removeWidget(self.devicedisp)
            self.devicedisp.hide()

        timefmt = self.config['timeformat'].data
        if(len(timefmt)>0):
            self.timedisp.setStyleSheet("border : 1px solid {:s};".format(self.config['backgroundcolor'].data))
            self.timedisp.setText(self.get_timestr(0, format=timefmt))
            self.timedisp.setAlignment(QtCore.Qt.AlignCenter)
            self.layout.addWidget(self.timedisp, 2, 0, 1, 2)
            self.timedisp.show()
        else:
            self.layout.removeWidget(self.timedisp)
            self.timedisp.hide()

        if(len(self.config['unit'].data)>0):
            self.unitdisp.setStyleSheet("border : 1px solid {:s};".format(self.config['backgroundcolor'].data))
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
        #print(funcname + ': got data', data)
        dataformat = self.config['dataformat'].data
        FLAG_DATA = data in self.redvypr_addrconv
        datakey = self.redvypr_addrconv.datakey
        #print('datakey',datakey,'FLAG_DATA',FLAG_DATA)
        if(FLAG_DATA):
            # data can be a single float or a list
            newdata = data[datakey]
            newt    = data['t']
            if(type(newdata) == list):
                newdata = newdata[0]
                newt = newt[0]

            datastr = "{0:{dformat}}".format(newdata,dformat=dataformat)
            self.numdisp.setText(datastr)

            timefmt = self.config['timeformat'].data
            if(len(timefmt)>0):
                self.timedisp.setText(self.get_timestr(newt,format=timefmt))
            
            if(self.config['useprops'].data):
                # Get the propertykey 
                propkey = '?' + datakey 
                try:
                    props = data[propkey]
                except:
                    props = None
                    
            if(props is not None):
                self.unitdisp.setText(str(data[propkey]['unit'].data))
                #self.resize_font(self.unitdisp)                






    
