import datetime
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import yaml
import copy
import pydantic
from pydantic.color import Color as pydColor
import typing
import pyqtgraph
import redvypr.data_packets
import redvypr.gui
import redvypr.files as files
from redvypr.redvypr_address import RedvyprAddress

_logo_file = files.logo_file
_icon_file = files.icon_file
pyqtgraph.setConfigOption('background', 'w')
pyqtgraph.setConfigOption('foreground', 'k')

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('plot_widgets')
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)

colors = ['red','blue','green','gray','yellow','purple']

class dataBufferLine(pydantic.BaseModel,extra=pydantic.Extra.allow):
    tdata: list = pydantic.Field(default=[])
    xdata: list = pydantic.Field(default=[])
    ydata: list = pydantic.Field(default=[])
    errordata: list = pydantic.Field(default=[])
class configLine(pydantic.BaseModel,extra=pydantic.Extra.allow):
    buffersize: int = pydantic.Field(default=20000,description='The size of the buffer holding the data of the line')
    numplot: int = pydantic.Field(default=2000, description='The number of data points to be plotted maximally')
    name: str = pydantic.Field(default='$y', description='The name of the line, this is shown in the legend, use $y to use the realtimedata address')
    x_addr: str = pydantic.Field(default='$t(y)', description='The realtimedata address of the x-axis, use $t(y) to automatically choose the time corresponding to the y-data')
    y_addr: str = pydantic.Field(default='', description='The realtimedata address of the x-axis')
    error_addr: str = pydantic.Field(default='', description='The realtimedata address for an optional error band around the line')
    color: pydColor = pydantic.Field(default=pydColor('red'), description='The color of the line')
    linewidth: float = pydantic.Field(default=1.0, description='The linewidth')
    databuffer: dataBufferLine = pydantic.Field(default=dataBufferLine(), description='The databuffer', editable=False)

class configXYplot(pydantic.BaseModel):
    location: list  = pydantic.Field(default=[])
    type: str = 'XYplot'
    dt_update: float = pydantic.Field(default=0.25,description='Update time of the plot [s]')
    interactive: str = pydantic.Field(default='mouse',description='Interactive modes')
    backgroundcolor: pydColor = pydantic.Field(default=pydColor('lightgray'),description='Backgroundcolor')
    bordercolor: pydColor = pydantic.Field(default=pydColor('lightgray'), description='Bordercolor')
    show_legend: bool = pydantic.Field(default=True, description='Show legend (True) or hide (False)')
    show_units: bool = pydantic.Field(default=True, description='Add the unit of the y-data to the legend, queried from the datakey')
    datetick_x: bool = pydantic.Field(default=True, description='x-axis is a date axis')
    datetick_y: bool = pydantic.Field(default=True, description='y-axis is a date axis')
    title: str = pydantic.Field(default='', description='')
    xlabel: str = pydantic.Field(default='', description='')
    ylabel: str = pydantic.Field(default='', description='')
    lines: typing.Optional[typing.List[configLine]] = pydantic.Field(default=[configLine()])


# config_template_graph['description'] = description_graph


class XYplot(QtWidgets.QFrame):
    """ Widget is plotting realtimedata using the pyqtgraph functionality

    """

    def __init__(self, config=None, redvypr_device=None, add_line=True, loglevel=logging.DEBUG):
        """

        """
        funcname = __name__ + '.init():'
        super(QtWidgets.QFrame, self).__init__()
        self.device = redvypr_device
        self.logger = logging.getLogger('XYplot')
        self.logger.setLevel(loglevel)
        self.description = 'XY plot'


        if (config == None):  # Create a config from the template
            self.config = configXYplot()
        else:
            self.config = config

        if add_line == False:
            try:
                self.config.lines.pop(0)
            except:
                logger.debug(funcname, exc_info=True)

        # self.logger.debug('plot widget config {:s}'.format(str(self.config)))
        backcolor = str(self.config.backgroundcolor.as_rgb())
        bordercolor = str(self.config.bordercolor.as_rgb())
        # logger.debug(funcname + 'backcolor {:s}'.format(str(backcolor)))
        style = "background-color : {:s};border : 1px solid {:s};".format(backcolor, bordercolor)
        logger.debug(funcname + 'Style: {:s}'.format(str(style)))
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
            self.logger.debug(funcname + ': Adding plot ')  # + str(config))
            try:
                title = config.title
            except:
                title = "Plot {:d}".format(i)

            try:
                name = config.name
            except:
                name = "Plot {:d}".format(i)

            # https://stackoverflow.com/questions/44402399/how-to-disable-the-default-context-menu-of-pyqtgraph
            plot = pyqtgraph.PlotWidget(title=title, name=name)
            plot.plotItem.vb.menu.clear()
            menu = plot.plotItem.vb.menu.addMenu('Line config')
            self.lineMenu = menu
            # Add line
            addLineAction = plot.plotItem.vb.menu.addAction('Add line')
            addLineAction.triggered.connect(self.pyqtgraphAddLineAction)


            # plot = redvyprPlotWidget(title=title,name=name)
            plot.register(name=name)
            # Add a legend
            legend = plot.addLegend()
            if config.interactive.lower() == 'mouse':
                self.logger.debug('Adding interactive mouse (vertical line)')
                plot.scene().sigMouseMoved.connect(self.mouseMoved)
                plot.scene().sigMouseClicked.connect(self.mouseClicked)
                self.vb = plot.plotItem.vb
                # Add a vertical line
                color = QtGui.QColor(200, 100, 100)
                linewidth = 2.0
                pen = pyqtgraph.mkPen(color, width=linewidth)
                self.vLineMouse = pyqtgraph.InfiniteLine(angle=90, movable=False, pen=pen)
                # print('Set pen 3')
                plot.addItem(self.vLineMouse, ignoreBounds=True)

            self.layout.addWidget(plot)
            self.plotWidget = plot
            self.legendWidget = legend
            # plot_dict = {'widget': plot, 'lines': []}

    def pyqtgraphAddLineAction(self):
        funcname = __name__ + '.pyqtgraphAddLineAction()'
        logger.debug(funcname)
        newline = configLine()
        self.addLineConfigWidget = redvypr.gui.pydanticConfigWidget(newline, configname='new line')
        self.addLineConfigWidget.setWindowTitle('Add line')
        # self.configWidget.config_changed_flag.connect(self.apply_config)
        self.addLineConfigWidget.show()

    def pyqtgraphLineAction(self):
        """ Function is called whenever a line is configured

        """
        funcname = __name__ + '.pyqtgraphLineAction()'
        logger.debug(funcname)
        linename = self.sender()._linename
        lineConfig = self.sender()._line
        self.lineConfigWidget = redvypr.gui.pydanticConfigWidget(lineConfig,configname=linename)
        self.lineConfigWidget.setWindowTitle('Config {}'.format(linename))
        #self.configWidget.config_changed_flag.connect(self.apply_config)
        self.lineConfigWidget.show()

    def pyqtgraphRedvyprAction(self, hallo):
        """

        """
        funcname = __name__ + '.pyqtgraphRedvyprAction()'
        logger.debug(funcname)
        self.configWidget = redvypr.gui.configWidget(self.config)
        self.configWidget.setWindowIcon(QtGui.QIcon(_icon_file))
        self.configWidget.config_changed_flag.connect(self.apply_config)
        self.configWidget.show()

    def mouseMoved(self, evt):
        """Function if mouse has been moved
        """
        pos = (evt.x(), evt.y())
        mousePoint = self.vb.mapSceneToView(evt)
        # print('mouse moved',mousePoint.x())
        self.vLineMouse.setPos(mousePoint.x())
        # for vline in self.vlines:
        #    vline.setPos(mousePoint.x())

    def mouseClicked(self, evt):
        # col =
        # col = pg.mkPen(0.5,width=3)
        # colsymbol = pg.mkPen(color=QtGui.QColor(150,150,150),width=4)
        # print('Clicked: ' + str(evt.scenePos()))
        pass

    def set_title(self, title):
        """
        Sets the title of the plot
        """
        funcname = __name__ + '.set_title()'
        logger.debug(funcname)
        self.config.title = title
        self.plotWidget.setTitle(title)

    def set_line(self, index, y_addr, name='$y', x_addr='$t(y)', color=[255, 0, 0], linewidth=1, bufsize=2000):
        """
        Sets the line at index to the parameters
        """

        self.add_line(y_addr=y_addr, name=name, x_addr=x_addr, color=color, linewidth=linewidth, bufsize=bufsize, index=index)

    def add_line(self, y_addr, x_addr='$t(y)', name='$y', error_addr='', color=None, linewidth=1, bufsize=20000, numplot=2000, index=None):
        """
        Adds a line to the plot
        """
        funcname = __name__ + '.add_line()'
        self.logger.debug(funcname)
        if isinstance(y_addr, redvypr.RedvyprAddress):
            logger.debug('Redvypr y-address')
            y_addr = y_addr.address_str
        if isinstance(x_addr, redvypr.RedvyprAddress):
            logger.debug('Redvypr x-address')
            x_addr = x_addr.address_str
        if isinstance(error_addr, redvypr.RedvyprAddress):
            logger.debug('Redvypr error-address')
            error_addr = error_addr.address_str
        #print('add line',y_addr,color)
        if color is None: # No color defined, take color from the colors list
            nlines = len(self.config.lines) - 1
            colind = nlines % len(colors)
            color = colors[colind]
            logger.debug('Color')

        if index is None:
            rconfig = configLine()
            self.config.lines.append(rconfig)
            index = len(self.config.lines) - 1

        self.config.lines[index].buffersize = bufsize
        self.config.lines[index].numplot    = numplot
        self.config.lines[index].linewidth  = linewidth
        #print('Using color',color)
        color_tmp = pydColor(color)
        self.config.lines[index].color = color_tmp
        self.config.lines[index].x_addr = x_addr
        self.config.lines[index].y_addr = y_addr
        self.config.lines[index].error_addr = error_addr
        self.config.lines[index].name = name
        self.apply_config()

    def apply_config(self):
        """
        Function is called by the initialization or after the configuration was changed

        Returns:

        """
        funcname = __name__ + '.apply_config()'
        self.logger.debug(funcname)
        # Recreate the lineMenu
        for iline, line in enumerate(self.config.lines):
            name = self.config.lines[iline].name
            linename = "Line {}: {}".format(iline,name)
            lineAction = self.lineMenu.addAction(linename)
            lineAction._line = line
            lineAction._iline = iline
            lineAction._linename = linename
            lineAction.triggered.connect(self.pyqtgraphLineAction)

        # Here a subscription should be done to the device ...

        plot = self.plotWidget
        # Title
        title = self.config.title
        plot.setTitle(title)

        try:
            datetick_x = self.config.datetick_x
        except:
            datetick_x = False

        if datetick_x:
            self.logger.debug(funcname + 'Datetick')
            axis = pyqtgraph.DateAxisItem(orientation='bottom', utcOffset=0)
            plot.setAxisItems({"bottom": axis})
        else:
            self.logger.debug(funcname + ' No Datetick')
            axis = pyqtgraph.AxisItem(orientation='bottom')
            plot.setAxisItems({"bottom": axis})

        # Label
        # If a xlabel is defined
        try:
            plot.setLabel('left', self.config.ylabel)
        except:
            pass

        # If a ylabel is defined
        try:
            plot.setLabel('bottom', self.config.xlabel)
        except:
            pass

        # Add lines with the actual data to the graph
        for iline, line in enumerate(self.config.lines):
            # print('Line',line)
            # FLAG_HAVE_LINE = False

            # check if we have already a lineplot, if yes, dont bother
            try:
                line._lineplot
                continue
            except:
                pass

            try:
                line._name_applied = line.name
            except:
                line._name_applied = 'line {:d}'.format(iline)

            lineplot = pyqtgraph.PlotDataItem(name=line._name_applied)
            line._lineplot = lineplot  # Add the line as an attribute to the configuration
            lineplot._line_config = line
            try:
                x_addr = line.x_addr
            except:
                pass

            try:
                y_addr = line.y_addr
            except:
                pass

            try:
                color = redvypr.gui.get_QColor(line.color)
            except Exception as e:
                self.logger.debug('Definition of color not usable:',exc_info=True)
                color = QtGui.QColor(255, 10, 10)

            line._tlastupdate = 0
            plot.addItem(lineplot)
            # Configuration

        # Update the line configuration
        self.legendWidget.clear()
        for iline, line in enumerate(self.config.lines):
            try:
                self.logger.debug(funcname + ': Updating line {:d}'.format(iline))
                print('Line',line,iline)
                x_addr = line.x_addr
                y_addr = line.y_addr
                y_raddr = redvypr.RedvyprAddress(y_addr)
                print('x_addr', x_addr)
                print('y_addr', y_addr)
                if (x_addr == '$t(y)'):
                    self.logger.debug(funcname + ' Using time variable of y')
                    #xtmp = redvypr.data_packets.modify_addrstr(y_raddr.address_str, datakey='t')
                    ## print('xtmp',xtmp)
                    #x_raddr = redvypr.redvypr_address(xtmp)
                    x_raddr = redvypr.RedvyprAddress(y_addr, datakey='t')
                else:
                    x_raddr = redvypr.RedvyprAddress(x_addr)

                print('x_addrnew', x_addr,x_raddr)
                # These attributes are used in plot.Device.connect_devices to actually subscribe to the fitting devices
                line._x_raddr = x_raddr
                line._y_raddr = y_raddr

                #print('Color',self.config.lines[iline].color.as_rgb())
                color = redvypr.gui.get_QColor(self.config.lines[iline].color)
                # print('Set pen 2')
                linewidth = self.config.lines[iline].linewidth
                # print('Set pen 3')
                #color = QtGui.QColor(200, 100, 100)
                #print('COLOR!!!!', color, type(color), linewidth)
                pen = pyqtgraph.mkPen(color, width=float(linewidth))
                line._lineplot.setPen(pen)

                # Error address
                if len(line.error_addr) > 0:
                    line._error_raddr = redvypr.RedvyprAddress(line.error_addr)
                    errorplot = pyqtgraph.ErrorBarItem(name=line._name_applied,pen=pen)
                    line._errorplot = errorplot  # Add the line as an attribute to the configuration
                    errorplot._line_config = line
                    plot.addItem(errorplot)
                else:
                    line._error_raddr = ''
                    line._errorplot = None
                    # print('Set pen 1')


                name = self.config.lines[iline].name
                if (name.lower() == '$y'):
                    self.logger.debug(funcname + ' Replacing with y')
                    name = y_addr

                self.logger.debug(funcname + ' Setting the name')
                self.legendWidget.addItem(line._lineplot, name)
                line._lineplot.setData(name=name)
            except Exception as e:
                logger.debug('Exception config lines: {:s}'.format(str(e)),exc_info=True)
                raise ValueError('')

        self.logger.debug(funcname + ' done.')

    def clear_buffer(self):
        """ Clears the buffer of all lines
        """
        # Check if the device is to be plotted

        for iline, line in enumerate(self.config.lines):
            line.databuffer = dataBufferLine()
            # Set the data
            line._lineplot.setData(x=line.databuffer.xdata, y=line.databuffer.ydata)

    def get_data(self, xlim):
        """
        Gets the data of the buffer in the limits of xlim
        """
        funcname = __name__ + '.get_data():'
        data = []
        tdata = []
        xdata = []
        ydata = []
        for iline, line in enumerate(self.config.lines):
            #print('Line', line)
            #print('Type Line', type(line))
            #line_dict = line.line_dict
            #line = line_dict['line']  # The line to plot
            #config = line_dict['config']  # The line to plot
            t = np.asarray(line.databuffer.tdata)  # The line to plot
            x = np.asarray(line.databuffer.xdata)  # The line to plot
            y = np.asarray(line.databuffer.ydata)  # The line to plot
            err = np.asarray(line.databuffer.errordata)  # The line to plot
            ind = (x > xlim[0]) & (x < xlim[1])
            tdata_tmp = t[ind]
            xdata_tmp = x[ind]
            ydata_tmp = y[ind]
            data.append({'x': xdata_tmp, 'y': ydata_tmp, 't': tdata_tmp})
            #tdata.append(tdata_tmp)
            #xdata.append(xdata_tmp)
            #ydata.append(ydata_tmp)
            self.logger.debug(funcname + ' Got data of length {:d}'.format(len(tdata_tmp)))
            # print('get_data',datetime.datetime.utcfromtimestamp(tdata_tmp[0]),datetime.datetime.utcfromtimestamp(xdata_tmp[0]))

        return data

    def update_plot(self, data):
        """ Updates the plot based on the given data
        """
        funcname = self.__class__.__name__ + '.update_plot():'
        tnow = time.time()
        # print(funcname + 'got data',data,tnow)

        # try:
        if True:
            # Loop over all plot axes
            if True:
                # Check if the device is to be plotted
                for iline, line in enumerate(self.config.lines):
                    error_raddr = line._error_raddr
                    #print('device',data['_redvypr']['device'])
                    #print('data',data)
                    #print('line',line)
                    #print('line A', line._x_raddr, (data in line._x_raddr))
                    #print('line B', line._y_raddr, (data in line._y_raddr))
                    #print('fdsfsfsd',(data in line._x_raddr) and (data in line._y_raddr))
                    if (data in line._x_raddr) and (data in line._y_raddr):
                        pw = self.plotWidget  # The plot widget
                        #print('Databuffer',line.databuffer)
                        tdata = line.databuffer.tdata  # The line to plot
                        xdata = line.databuffer.xdata  # The line to plot
                        ydata = line.databuffer.ydata  # The line to plot
                        # data can be a single float or a list, if its a list add it item by item
                        newt = data['_redvypr']['t']  # Add also the time of the packet
                        newx = data[line._x_raddr.datakey]
                        newy = data[line._y_raddr.datakey]

                        if (type(newx) is not list):
                            newx = [newx]
                        if (type(newy) is not list):
                            newy = [newy]

                        if len(line.error_addr) > 0:
                            #print('errordata',error_raddr.datakey)
                            newerror = data[error_raddr.datakey]
                            if (type(newerror) is not list):
                                newerror = [newerror]
                            #print('newerror',newerror)
                        else:
                            newerror = [0]

                        if (len(newx) != len(newy)):
                            logger.warning(
                                'lengths of x and y data different (x:{:d}, y:{:d})'.format(len(newx), len(newy)))
                            return

                        for inew in range(len(newx)):  # TODO this can be optimized using indices instead of a loop
                            line.databuffer.tdata.append( float(newt) )
                            line.databuffer.xdata.append( float(newx[inew]) )
                            line.databuffer.ydata.append( float(newy[inew]) )
                            line.databuffer.errordata.append(float(newerror[inew]) )
                            if len(line.databuffer.tdata) > line.buffersize:
                                line.databuffer.tdata.pop(0)
                                line.databuffer.xdata.pop(0)
                                line.databuffer.ydata.pop(0)
                                line.databuffer.errordata.pop(0)

                            #tdata = np.roll(tdata, -1)
                            #xdata = np.roll(xdata, -1)
                            #ydata = np.roll(ydata, -1)
                            #tdata[-1] = float(newt)
                            #xdata[-1] = float(newx[inew])
                            #ydata[-1] = float(newy[inew])
                            #line.databuffer.tdata = tdata
                            #line.databuffer.xdata = xdata
                            #line.databuffer.ydata = ydata

                        # Show the unit in the legend, if wished by the user and we have access to the device that can give us the metainformation
                        if (self.config.show_units) and (self.device is not None):
                            try:
                                line._datakeys  # datakeys found, doing nothing
                            except:
                                line._datakeys = self.device.get_metadata_datakey(line._y_raddr)
                                self.logger.debug(funcname + ' Datakeyinfo {:s}'.format(str(line._datakeys)))
                                unit = None
                                for k in line._datakeys.keys():
                                    # print('key',k,yaddr,k in yaddr)
                                    if k in line._y_raddr:
                                        try:
                                            unit = line._datakeys[k]['unit']
                                            break
                                        except:
                                            unit = None

                                if unit is not None:
                                    name = line.name
                                    name_new = name + ' [{:s}]'.format(unit)
                                    self.config.lines[iline].name = name_new
                                    self.apply_config()

            # Update the lines plot
            for iline, line in enumerate(self.config.lines):
                tlastupdate = line._tlastupdate  # The time the plot was last updated
                # Check if an update of the plot shall be done, or if only the buffer is updated
                dt = tnow - tlastupdate
                if dt > self.config.dt_update:
                    update = True
                    line._tlastupdate = tnow
                else:
                    update = False
                    # print('no update')

                if (update):  # We could check here if data was changed above the for given line
                    x = line.databuffer.xdata[-line.numplot:]
                    y = line.databuffer.ydata[-line.numplot:]
                    line._lineplot.setData(x=x, y=y)
                    # Update the error
                    if line._errorplot is not None:
                        if len(x) > 0:
                            #print('Updating errorplot')
                            err = line.databuffer.errordata[-line.numplot:]
                            #print('err',err,x,y)
                            beamwidth=None
                            line._errorplot.setData(x=np.asarray(x), y=np.asarray(y), top=np.asarray(err)*1, bottom=np.asarray(err)*1,beam=beamwidth)
                    # pw.setXRange(min(x[:ind]),max(x[:ind]))

