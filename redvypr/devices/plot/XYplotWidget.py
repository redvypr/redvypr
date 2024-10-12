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
#from pydantic_extra_types import Color as pydColor
import typing
import pyqtgraph
import redvypr.data_packets
import redvypr.gui
import redvypr.files as files
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget
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

class dataBufferLine(pydantic.BaseModel):
    model_config = {'extra': 'allow'}
    skip_bufferdata_when_serialized: bool = pydantic.Field(default=True, description='Do not save the buffer data when serialized')
    tdata: list = pydantic.Field(default=[])
    xdata: list = pydantic.Field(default=[])
    ydata: list = pydantic.Field(default=[])
    errordata: list = pydantic.Field(default=[])
    tdata_addr: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''))
    xdata_addr: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''))
    ydata_addr: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''))
    errordata_addr: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''))

    @pydantic.model_serializer
    def ser_model(self) -> typing.Dict[str, typing.Any]:
        if self.skip_bufferdata_when_serialized:
            return {'tdata': [],'xdata': [],'ydata': [],'errordata': [], 'skip_bufferdata_when_serialized':self.skip_bufferdata_when_serialized}
        else:
            return {'tdata': self.tdata, 'xdata': self.xdata, 'ydata': self.ydata, 'errordata': self.errordata,
                    'skip_bufferdata_when_serialized': self.skip_bufferdata_when_serialized}

class configLine(pydantic.BaseModel,extra='allow'):
    buffersize: int = pydantic.Field(default=20000,description='The size of the buffer holding the data of the line')
    numplot_max: int = pydantic.Field(default=2000, description='The number of data points to be plotted maximally')
    name: str = pydantic.Field(default='Line', description='The name of the line, this is shown in the legend, $y to use the redvypr address')
    unit: str = pydantic.Field(default='', description='The unit of the line')
    label: str = pydantic.Field(default='', description='The of the line')
    label_format: str = pydantic.Field(default='{NAME} {Y_ADDR} [{UNIT}]', description='The name of the line, this is shown in the legend, $y to use the redvypr address')
    x_addr: typing.Union[typing.Literal['$t(y)'],RedvyprAddress] = pydantic.Field(default='$t(y)', description='The realtimedata address of the x-axis, use $t(y) to automatically choose the time corresponding to the y-data')
    y_addr: RedvyprAddress = pydantic.Field(default=RedvyprAddress('/d:somedevice/k:data'), description='The realtimedata address of the x-axis')
    error_addr: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''), description='The realtimedata address for an optional error band around the line')
    error_mode: typing.Literal['off', 'standard', 'factor', 'constant'] = pydantic.Field(default='off', description='')
    error_factor: float = pydantic.Field(default=1.1, description='')
    error_constant: float = pydantic.Field(default=.01, description='')
    color: pydColor = pydantic.Field(default=pydColor('red'), description='The color of the line')
    linewidth: float = pydantic.Field(default=2.0, description='The linewidth')
    linestyle: typing.Literal['SolidLine','DashLine','DotLine','DashDotLine','DashDotDotLine'] = pydantic.Field(default='SolidLine', description='The linestyle, see also https://doc.qt.io/qt-6/qt.html#PenStyle-enum')
    databuffer: dataBufferLine = pydantic.Field(default=dataBufferLine(), description='The databuffer', editable=False)
    plot_mode_x: typing.Literal['all', 'last_N_s', 'last_N_points'] = pydantic.Field(default='all', description='')
    last_N_s: float = pydantic.Field(default=60,
                                     description='Plots the last seconds, if plot_mode_x is set to last_N_s')
    last_N_points: int = pydantic.Field(default=1000,
                                        description='Plots the last points, if plot_mode_x is set to last_N_points')
    plot_every_Nth: int = pydantic.Field(default=1, description='Uses every Nth datapoint for plotting')

class configXYplot(pydantic.BaseModel):
    location: list  = pydantic.Field(default=[])
    type: str = 'XYplot'
    dt_update: float = pydantic.Field(default=0.25,description='Update time of the plot [s]')
    interactive: typing.Literal['standard', 'mouse'] = pydantic.Field(default='standard',description='Interactive modes')
    backgroundcolor: pydColor = pydantic.Field(default=pydColor('lightgray'),description='Backgroundcolor')
    bordercolor: pydColor = pydantic.Field(default=pydColor('lightgray'), description='Bordercolor')
    show_legend: bool = pydantic.Field(default=True, description='Show legend (True) or hide (False)')
    show_units: bool = pydantic.Field(default=True, description='Add the unit of the y-data to the legend, queried from the datakey')
    datetick_x: bool = pydantic.Field(default=True, description='x-axis is a date axis')
    datetick_y: bool = pydantic.Field(default=True, description='y-axis is a date axis')
    title: str = pydantic.Field(default='', description='')
    name: str = pydantic.Field(default='', description='The name of the plotWidget')
    xlabel: str = pydantic.Field(default='', description='')
    ylabel: str = pydantic.Field(default='', description='')
    lines: typing.Optional[typing.List[configLine]] = pydantic.Field(default=[configLine()], editable=True)
    plot_mode_x: typing.Literal['all', 'last_N_s', 'last_N_unit'] = pydantic.Field(default='all', description='')
    last_N_s: float = pydantic.Field(default=10,
                                     description='Plots the last seconds, if plot_mode_x is set to last_N_s')
    last_N_points: int = pydantic.Field(default=1000,
                                        description='Plots the last points, if plot_mode_x is set to last_N_points')
    automatic_subscription: bool = pydantic.Field(default=True,
                                                  description='subscribes automatically the adresses of the lines at the host device')

# config_template_graph['description'] = description_graph
class XYPlotWidget(QtWidgets.QFrame):
    """ Widget is plotting realtimedata using the pyqtgraph functionality

    """
    closing = QtCore.pyqtSignal()  # Signal notifying that a subscription changed

    def __init__(self, config=None, redvypr_device=None, add_line=True, loglevel=logging.INFO):
        """

        """
        funcname = __name__ + '.init():'
        super(QtWidgets.QFrame, self).__init__()
        self.device = redvypr_device
        if self.device is not None:
            self.redvypr = self.device.redvypr
        else:
            self.redvypr = None
        self.logger = logging.getLogger('XYplot')
        self.logger.setLevel(loglevel)
        self.description = 'XY plot'

        self.x_min = 0
        self.x_max = 0
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
        self.xAxisLimitsChanged()

    def create_widgets(self):

        """
        Creates the configuration

        Returns:

        """
        funcname = __name__ + '.create_widgets()'
        config = self.config
        self.logger.debug(funcname)
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
            # General config
            configAction = plot.plotItem.vb.menu.addAction('General config')
            configAction.triggered.connect(self.pyqtgraphConfigAction)
            # X-Axis
            xMenu = plot.plotItem.vb.menu.addMenu('X-Axis')
            xAction = QtWidgets.QWidgetAction(self)
            # Create X-Menu
            xMenuWidget = QtWidgets.QWidget()
            xMenuWidget_layout = QtWidgets.QVBoxLayout(xMenuWidget)
            self._xaxis_radio_auto = QtWidgets.QRadioButton('Autoscale')
            self._xaxis_radio_lasts = QtWidgets.QRadioButton('Last N-Seconds')

            if self.config.plot_mode_x == 'all':
                self._xaxis_radio_auto.setChecked(True)
            else:
                self._xaxis_radio_lasts.setChecked(True)

            self._xaxis_radio_auto.toggled.connect(self.xAxisLimitsChanged)
            self._xaxis_spin_lasts = QtWidgets.QDoubleSpinBox()
            self._xaxis_spin_lasts.setValue(self.config.last_N_s)
            self._xaxis_spin_lasts.setMinimum(0)
            self._xaxis_spin_lasts.setMaximum(1e12)
            self._xaxis_spin_lasts.valueChanged.connect(self.xAxisLimitsChanged)
            xMenuWidget_layout.addWidget(self._xaxis_radio_auto)
            xMenuWidget_layout.addWidget(self._xaxis_radio_lasts)
            xMenuWidget_layout.addWidget(self._xaxis_spin_lasts)
            xAction.setDefaultWidget(xMenuWidget)
            xMenu.addAction(xAction)
            #xMenu.triggered.connect(self.pyqtgraphXMenuAction)
            # Y-Axis
            yMenu = plot.plotItem.vb.menu.addMenu('Y-Axis')
            #yMenu.triggered.connect(self.pyqtgraphYMenuAction)
            # Line config menu
            menu = plot.plotItem.vb.menu.addMenu('Line config')
            self.lineMenu = menu
            # Clear buffer
            bufferMenu = plot.plotItem.vb.menu.addMenu('Clear buffer')
            self.bufferMenu = bufferMenu
            # Remove menu
            removeMenu = plot.plotItem.vb.menu.addMenu('Remove line')
            self.removeMenu = removeMenu
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

    def xAxisLimitsChanged(self):
        funcname = __name__ + '.xAxisLimitsChanged():'
        logger.debug(funcname)
        self.config.last_N_s = self._xaxis_spin_lasts.value()
        if self._xaxis_radio_auto.isChecked():
            logger.debug(funcname + 'Enabling auto scaling')
            self.config.plot_mode_x = 'all'
        if self._xaxis_radio_lasts.isChecked():
            logger.debug(funcname + 'Enabling last s range')
            self.config.plot_mode_x = 'last_N_s'

        # Update if it is existing already ...
        try:
            self.plotWidget
            self.applyPlotRanges()
        except:
            pass

    def applyPlotRanges(self):
        funcname = __name__ + '.applyPlotRanges():'
        logger.debug(funcname)
        if self.config.plot_mode_x == 'all':
            self.plotWidget.enableAutoRange(axis='x')
            self.plotWidget.setAutoVisible(x=True)
        elif self.config.plot_mode_x == 'last_N_s':
            xmin = self.x_max - self.config.last_N_s
            xmax = self.x_max
            self.plotWidget.setXRange(xmin, xmax)

        self.plotWidget.enableAutoRange(axis='y')
        self.plotWidget.setAutoVisible(y=True)

    def pyqtgraphXMenuAction(self):
        funcname = __name__ + '.pyqtgraphXMenuAction()'
        logger.debug(funcname)

    def pyqtgraphYMenuAction(self):
        funcname = __name__ + '.pyqtgraphYMenuAction()'
        logger.debug(funcname)

    def pyqtgraphConfigAction(self):
        funcname = __name__ + '.pyqtgraphConfigAction()'
        logger.debug(funcname)
        self.ConfigWidget = pydanticConfigWidget(self.config, configname='new line',exclude=['lines'], redvypr=self.redvypr)
        self.ConfigWidget.config_changed_flag.connect(self.apply_config)
        self.ConfigWidget.show()

    def pyqtgraphRemLineAction(self):
        funcname = __name__ + '.pyqtgraphRemLineAction()'
        logger.debug(funcname)
        index_remove = self.sender()._iline
        self.config.lines.pop(index_remove)
        self.sender()._line._lineplot.clear()
        self.apply_config()

    def pyqtgraphAddLineAction(self):
        funcname = __name__ + '.pyqtgraphAddLineAction()'
        logger.debug(funcname)
        newline = configLine()
        self.__newline = newline
        self.addLineConfigWidget = pydanticConfigWidget(newline, configname='new line', redvypr=self.device.redvypr)
        self.addLineConfigWidget.setWindowTitle('Add line')
        self.addLineConfigWidget.config_editing_done.connect(self.pyqtgraphAddLineDone)
        self.addLineConfigWidget.show()

    def pyqtgraphAddLineDone(self):
        if self.__newline is not None:
            self.config.lines.append(self.__newline)
        self.apply_config()

    def pyqtgraphLineAction(self):
        """ Function is called whenever a line is configured

        """
        funcname = __name__ + '.pyqtgraphLineAction()'
        self.logger.debug(funcname)
        config_mode = self.sender().text()
        if 'address' in config_mode.lower():
            #print('Address')
            linename = self.sender()._linename
            lineConfig = self.sender()._line
            self.lineConfigWidget = redvypr.widgets.redvyprAddressWidget.datastreamWidget(redvypr=self.redvypr, device=self.device)
            self.lineConfigWidget.setWindowTitle('Y-Address for {}'.format(linename))
            self.lineConfigWidget.apply.connect(self.apply_config_address)
            self.lineConfigWidget._line = self.sender()._line
            self.lineConfigWidget.show()

        elif 'color' in config_mode.lower():
            #print('Color')
            linename = self.sender()._linename
            lineConfig = self.sender()._line
            self.lineConfigWidget = QtWidgets.QColorDialog()
            self.lineConfigWidget._line = lineConfig
            #self.lineConfigWidget.currentColorChanged.connect(self.apply_config_color)
            self.lineConfigWidget.accepted.connect(self.apply_config_color)
            self.lineConfigWidget.show()

        elif 'settings' in config_mode.lower():
            linename = self.sender()._linename
            lineConfig = self.sender()._line
            self.lineConfigWidget = pydanticConfigWidget(lineConfig, configname=linename, redvypr=self.device.redvypr)
            self.lineConfigWidget.setWindowTitle('Config {}'.format(linename))
            self.lineConfigWidget.config_editing_done.connect(self.apply_config)
            self.lineConfigWidget.show()

    def pyqtgraphBufferAction(self):
        """ Function is called whenever a clear buffer action is called

        """
        funcname = __name__ + '.pyqtgraphBufferAction()'
        self.logger.debug(funcname)
        self.clear_buffer()

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
        self.logger.debug(funcname)
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
            self.logger.debug('Redvypr y-address')
            y_addr = y_addr.address_str
        if isinstance(x_addr, redvypr.RedvyprAddress):
            self.logger.debug('Redvypr x-address')
            x_addr = x_addr.address_str
        if isinstance(error_addr, redvypr.RedvyprAddress):
            self.logger.debug('Redvypr error-address')
            error_addr = error_addr.address_str
        #print('add line',y_addr,color)
        if color is None: # No color defined, take color from the colors list
            nlines = len(self.config.lines) - 1
            colind = nlines % len(colors)
            color = colors[colind]
            self.logger.debug('Color')

        if index is None:
            rconfig = configLine()
            self.config.lines.append(rconfig)
            index = len(self.config.lines) - 1

        self.config.lines[index].buffersize = bufsize
        self.config.lines[index].numplot_max = numplot
        self.config.lines[index].linewidth = linewidth
        #print('Using color',color)
        color_tmp = pydColor(color)
        self.config.lines[index].color = color_tmp
        self.config.lines[index].x_addr = x_addr
        self.config.lines[index].y_addr = y_addr
        self.config.lines[index].error_addr = error_addr
        self.config.lines[index].name = name
        # Add the address as well to the data
        self.config.lines[index].databuffer.xdata_addr = x_addr
        self.apply_config()

    def construct_labelname(self, line, labelformat=None):
        name = line.name
        unit = line.unit
        x_addr = RedvyprAddress(line.x_addr).address_str_explicit
        y_addr = RedvyprAddress(line.y_addr).address_str_explicit
        if labelformat == None:
            labelname = line.label_format
            labelname = labelname.format(NAME=name,UNIT=unit,X_ADDR=x_addr,Y_ADDR=y_addr)
        self.logger.debug('Labelname {}'.format(labelname))
        return labelname

    def apply_config_address(self,address_dict):
        funcname = __name__ + '.apply_config_address():'
        self.logger.debug(funcname)
        line = self.sender()._line
        #print('Line',line,line.y_addr)
        line.y_addr = address_dict['datastream_str']
        #print('Line config',line.confg)
        self.apply_config()

    def apply_config_color(self):
        funcname = __name__ + 'apply_config_color():'
        logger.debug(funcname)
        try:
            color = self.sender().currentColor()  # ComboBox
            color1 = color.getRgb()
            color_tmp = (color1[0], color1[1], color1[2])
            rint = int(color1[0] * 255)
            gint = int(color1[1] * 255)
            bint = int(color1[2] * 255)
            data = pydColor(color_tmp)
            self.sender()._line.color = data
            self.apply_config()
        except:
            logger.info('Could not set color',exc_info=True)

    def apply_config_linewidth(self):
        spinbox = self.sender()
        spinbox._line.linewidth = spinbox.value()
        self.apply_config()

    def apply_config_linestyle(self):
        combobox = self.sender()
        combobox._line.linestyle = combobox.currentText()
        self.apply_config()

    def apply_config(self):
        """
        Function is called by the initialization or after the configuration was changed

        Returns:

        """
        funcname = __name__ + '.apply_config():'
        self.logger.debug(funcname)
        # Recreate the lineMenu
        self.lineMenu.clear()
        self.removeMenu.clear()
        self.bufferMenu.clear()
        # Add a clear buffer action
        bufferAction = self.bufferMenu.addAction('All lines')
        bufferAction.triggered.connect(self.pyqtgraphBufferAction)

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

        # Legend update
        self.legendWidget.clear()
        # Add lines with the actual data to the graph
        for iline, line in enumerate(self.config.lines):
            self.logger.debug(funcname + ': Updating line {:d}'.format(iline))
            # Creating the correct addresses first
            try:
                self.logger.debug('Line {},{}'.format(line,iline))
                x_addr = line.x_addr
                y_addr = line.y_addr
                if len(y_addr) >= 0:
                    y_raddr = redvypr.RedvyprAddress(y_addr)
                    #print('x_addr', x_addr)
                    #print('y_addr', y_addr)
                    if (x_addr == '$t(y)'):
                        self.logger.debug(funcname + ' Using time variable of y')
                        #xtmp = redvypr.data_packets.modify_addrstr(y_raddr.address_str, datakey='t')
                        ## print('xtmp',xtmp)
                        #x_raddr = redvypr.redvypr_address(xtmp)
                        x_raddr = redvypr.RedvyprAddress(y_addr, datakey='t')
                    else:
                        x_raddr = redvypr.RedvyprAddress(x_addr)

                    #print('x_addrnew', x_addr,x_raddr)
                    # These attributes are used in plot.Device.connect_devices to actually subscribe to the fitting devices
                    line._x_raddr = x_raddr
                    line._y_raddr = y_raddr

                # Error address
                error_addr = None
                if line.error_mode != 'off':
                    self.logger.debug('Error mode 1')
                    error_raddr = redvypr.RedvyprAddress(line.error_addr)
                    line._error_raddr = error_raddr
                    errorplot = pyqtgraph.ErrorBarItem(name=line._name_applied,pen=pen)
                    line._errorplot = errorplot  # Add the line as an attribute to the configuration
                    errorplot._line_config = line
                    plot.addItem(errorplot)
                else:
                    self.logger.debug('Error mode 2')
                    line._error_raddr = redvypr.RedvyprAddress('')
                    line._errorplot = None
                    # print('Set pen 1')
            except:
                self.logger.debug(funcname + 'Could not update addresses',exc_info=True)
                continue

            # print('Line',line)
            # FLAG_HAVE_LINE = False
            self.get_metadata_for_line(line) # This is updating the unit
            labelname = self.construct_labelname(line)
            line.label = labelname
            linename = "Line {}: {}".format(iline, labelname)
            linename_menu = "Line {}".format(iline)

            # check if we have already a lineplot, if yes, dont bother
            try:
                self.logger.debug(funcname + 'We have already a lineplot, no update')
                lineplot = line._lineplot
            except:
                self.logger.debug(funcname + 'Creating new line with labelname {}'.format(labelname), exc_info=True)
                lineplot = pyqtgraph.PlotDataItem(name=labelname)
                line._lineplot = lineplot  # Add the line as an attribute to the configuration
                plot.addItem(lineplot)

            try:
                line._name_applied = line.name
            except:
                line._name_applied = 'line {:d}'.format(iline)

            lineplot._line_config = line
            line._tlastupdate = 0
            try:
                #print('Color',self.config.lines[iline].color.as_rgb())
                color = redvypr.gui.get_QColor(self.config.lines[iline].color)
                # print('Set pen 2')
                linewidth = self.config.lines[iline].linewidth
                linestyle = self.config.lines[iline].linestyle
                style=eval('QtCore.Qt.' + linestyle)
                # print('Set pen 3')
                #color = QtGui.QColor(200, 100, 100)
                #print('COLOR!!!!', color, type(color), linewidth)
                pen = pyqtgraph.mkPen(color, width=float(linewidth),style=style)
                line._lineplot.setPen(pen)
                # Check if the addresses changed and clear the buffer if necessary
                if line.databuffer.xdata_addr == line.x_addr:
                    self.logger.debug('Address did not change')
                else:
                    pass
                    # TODO, here an unsubscribe and resubscribe would be better
                    #self.logger.debug('Address changed, clearing buffer')
                    #self.clear_buffer(line)

                self.logger.debug(funcname + ' Setting the name')
                try:
                    self.legendWidget.removeItem(line._lineplot)
                except:
                    self.logger.debug(funcname + ' Could not remove line')
                self.legendWidget.addItem(line._lineplot, line.label)
                self.logger.debug('Setting the data')
                line._lineplot.setData(name=line.label,x=[],y=[])
                if self.config.automatic_subscription:
                    self.logger.debug(funcname + 'Subscribing to x address {}'.format(x_raddr))
                    self.device.subscribe_address(x_raddr)
                    self.logger.debug(funcname + 'Subscribing to y address {}'.format(y_raddr))
                    self.device.subscribe_address(y_raddr)
                    if line._errorplot is not None:
                        self.logger.debug(funcname + 'Subscribing to error address {}'.format(error_raddr))
                        self.device.subscribe_address(error_raddr)

                # Create the menu to config the line
                #lineMenuline = QtWidgets.QMenu(linename_menu,self)
                lineMenuline = QtWidgets.QMenu(linename_menu, self.lineMenu)
                lineAction = lineMenuline.addAction('Y-Address')
                lineAction._line = line
                lineAction._iline = iline
                lineAction._linename = linename
                lineAction.triggered.connect(self.pyqtgraphLineAction)

                # Create a widget for the linewidth
                linewidthAction = QtWidgets.QWidgetAction(lineMenuline)
                # Create add XYPlot-Menu
                linewidthWidget = QtWidgets.QWidget()
                linewidthWidget_layout = QtWidgets.QVBoxLayout(linewidthWidget)
                linewidthSpinBox = QtWidgets.QDoubleSpinBox()
                linewidthSpinBox.setValue(line.linewidth)
                linewidthSpinBox._line = line
                linewidthSpinBox.valueChanged.connect(self.apply_config_linewidth)
                # Add a widget for the linestyle
                linewidthWidget_layout.addWidget(QtWidgets.QLabel('Linewidth'))
                linewidthWidget_layout.addWidget(linewidthSpinBox)
                linewidthWidget_layout.addWidget(QtWidgets.QLabel('Linestyle'))
                linestyleComboBox = QtWidgets.QComboBox()
                linestyleComboBox._line = line
                linewidthWidget_layout.addWidget(linestyleComboBox)

                styles_tmp = typing.get_type_hints(line, include_extras=True)['linestyle']
                styles_tmp = typing.get_args(styles_tmp)
                i_style_set = 0
                for i_s,s in enumerate(styles_tmp):
                    linestyleComboBox.addItem(s)
                    if s == line.linestyle:
                        i_style_set = i_s

                linestyleComboBox.setCurrentIndex(i_style_set)
                linestyleComboBox.currentTextChanged.connect(self.apply_config_linestyle)
                #print('Styles',styles_tmp)

                linewidthAction.setDefaultWidget(linewidthWidget)
                lineMenuline.addAction(linewidthAction)

                colorAction = lineMenuline.addAction('Linecolor')
                colorAction._line = line
                colorAction._iline = iline
                colorAction._linename = linename
                colorAction.triggered.connect(self.pyqtgraphLineAction)

                lineAction = lineMenuline.addAction('All settings')
                lineAction._line = line
                lineAction._iline = iline
                lineAction._linename = linename
                lineAction.triggered.connect(self.pyqtgraphLineAction)
                self.lineMenu.addMenu(lineMenuline)
                # remove line menu
                # Remove line
                lineAction = self.removeMenu.addAction(linename_menu)
                lineAction._line = line
                lineAction._iline = iline
                lineAction._linename = linename
                lineAction.triggered.connect(self.pyqtgraphRemLineAction)
            except Exception as e:
                self.logger.debug('Exception config lines: {:s}'.format(str(e)),exc_info=True)
                raise ValueError('')

        self.logger.debug(funcname + ' done.')


    def get_metadata_for_line(self, line):
        funcname = __name__ + '.get_metadata_for_line():'
        iline = self.config.lines.index(line)
        self.logger.debug(funcname + 'Getting metadata for {}'.format(line._y_raddr))
        try:
            line._metadata  # metadata found, doing nothing
        except:
            line._metadata = self.device.get_metadata(line._y_raddr)
            self.logger.debug(funcname + ' Datakeyinfo {:s}'.format(str(line._metadata)))
            try:
                unit = line._metadata['unit']
                self.logger.debug(funcname + 'Found a unit for {}'.format(line._y_raddr))
            except:
                self.logger.debug(funcname + 'Did not find a unit', exc_info=True)
                unit = None

            if unit is not None:
                self.config.lines[iline].unit = unit
                return True

        return None

    def clear_buffer(self, line=None):
        """ Clears the buffer of all lines
        """
        if line is not None:
            lines = [line]
        else:
            lines = self.config.lines

        for iline, line_tmp in enumerate(lines):
            line_tmp.databuffer = dataBufferLine()
            # Set the data
            line_tmp._lineplot.setData(x=line_tmp.databuffer.xdata, y=line_tmp.databuffer.ydata)

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

    def __get_data_for_line(self, line):
        """
        Provides the data for the line to plot
        :return:

        plot_mode_x: typing.Literal['all', 'last_N_s', 'last_N_points'] = pydantic.Field(default='all', description='')
    last_N_s: float = pydantic.Field(default=60,
                                     description='Plots the last seconds, if plot_mode_x is set to last_N_s')
    last_N_points: int = pydantic.Field(default=200,
                                        description='Plots the last points, if plot_mode_x is set to last_N_points')
    plot_every_Nth: int = pydantic.Field(default=1, description='Uses every Nth datapoint for plotting')

        """

        if line.plot_mode_x == 'all':
            ttmp = line.databuffer.tdata[::line.plot_every_Nth]
            xtmp = line.databuffer.xdata[::line.plot_every_Nth]
            ytmp = line.databuffer.ydata[::line.plot_every_Nth]
            errtmp = line.databuffer.errordata[::line.plot_every_Nth]
        elif line.plot_mode_x == 'last_N_s':
            ttmp = line.databuffer.tdata[::line.plot_every_Nth]
            xtmp = line.databuffer.xdata[::line.plot_every_Nth]
            ytmp = line.databuffer.ydata[::line.plot_every_Nth]
            errtmp = line.databuffer.errordata[::line.plot_every_Nth]
            # Find the index
            tnow = ttmp[-1]
            tsearch = tnow - line.last_N_s
            ttmp_ar = np.asarray(ttmp)
            iplot = np.where(ttmp_ar >= tsearch)[0]
            if len(iplot)>0:
                istart = iplot[0]
                ttmp = ttmp[istart:]
                xtmp = xtmp[istart:]
                ytmp = ytmp[istart:]
                errtmp = errtmp[istart:]
            else:
                ttmp = []
                xtmp = []
                ytmp = []
                errtmp = []

        elif line.plot_mode_x == 'last_N_points':
            ttmp = line.databuffer.tdata[::line.plot_every_Nth][-line.last_N_points:]
            xtmp = line.databuffer.xdata[::line.plot_every_Nth][-line.last_N_points:]
            ytmp = line.databuffer.ydata[::line.plot_every_Nth][-line.last_N_points:]
            errtmp = line.databuffer.errordata[::line.plot_every_Nth][-line.last_N_points:]
        else:
            pass

        # Reduce the number of points, if they are more than numplot_max
        x = xtmp[-line.numplot_max:]
        y = ytmp[-line.numplot_max:]
        err = errtmp[-line.numplot_max:]
        # pw.setXRange(min(x[:ind]),max(x[:ind]))
        return [x,y,err]

    def closeEvent(self, event):
        #print('Close event')
        self.closing.emit()

    def update_plot(self, data):
        """ Updates the plot based on the given data
        """
        funcname = self.__class__.__name__ + '.update_plot():'
        #self.logger.debug(funcname + 'Update {}'.format(len(self.config.lines)))
        tnow = time.time()
        # Create a redvypr datapacket
        rdata = redvypr.data_packets.Datapacket(data)
        # print(funcname + 'got data',data,tnow)
        try:
            # Check if the device is to be plotted
            # Loop over all lines
            for iline, line in enumerate(self.config.lines):
                line.__newdata = False
                error_raddr = line._error_raddr
                if len(self.config.lines)>1:
                    #print('device',data['_redvypr']['device'])
                    #print('data',data)
                    #print('line',line)
                    #print('line A', line._x_raddr, (data in line._x_raddr))
                    #print('line B', line._y_raddr, (data in line._y_raddr))
                    #print('fdsfsfsd',(data in line._x_raddr) and (data in line._y_raddr))
                    pass

                #print('data',data)
                #print('line._x_raddr',line._x_raddr,data in line._x_raddr)
                #print('line._y_raddr', line._y_raddr, data in line._y_raddr)
                if (data in line._x_raddr) and (data in line._y_raddr):
                    pw = self.plotWidget  # The plot widget
                    #if len(self.config.lines) > 1:
                    #    print('Databuffer',line.databuffer)
                    tdata = line.databuffer.tdata  # The line to plot
                    xdata = line.databuffer.xdata  # The line to plot
                    ydata = line.databuffer.ydata  # The line to plot
                    # data can be a single float or a list, if its a list add it item by item
                    newt = rdata['_redvypr']['t']  # Add also the time of the packet
                    newx = rdata[line._x_raddr.datakey]
                    newy = rdata[line._y_raddr.datakey]

                    #if len(self.config.lines) > 0:
                    #    print('data xy plotwidget',rdata)
                    #    print('newx datakey', line._x_raddr.datakey)
                    #    print('newx', newx)

                    if (type(newx) is not list):
                        newx = [newx]
                    if (type(newy) is not list):
                        newy = [newy]

                    if  line.error_mode != 'off':
                        error_mode: typing.Literal['off','standard', 'factor', 'constant'] = pydantic.Field(
                            default='standard', description='')
                        error_factor: float = pydantic.Field(default=1.1, description='')
                        error_constant: float = pydantic.Field(default=.01, description='')
                        #print('errordata',error_raddr.datakey)
                        if len(line.error_addr) > 0 and line.error_mode == 'standard':
                            #logger.debug('Error standard')
                            newerror = data[error_raddr.datakey]
                            if (type(newerror) is not list):
                                newerror = [newerror]
                            #print('newerror',newerror)
                        elif line.error_mode == 'factor':
                            #print('Error factor')
                            errdata = np.asarray(newy)
                            errdata_factor = errdata * line.error_factor - errdata.mean()
                            newerror = errdata_factor.tolist()
                        elif line.error_mode == 'constant':
                            #print('Error constant')
                            newerror = [line.error_constant] * len(newx)
                    else:
                        newerror = [0]

                    if (len(newx) != len(newy)):
                        self.logger.warning(
                            'lengths of x and y data different (x:{:d}, y:{:d})'.format(len(newx), len(newy)))
                        return

                    for inew in range(len(newx)):  # TODO this can be optimized using indices instead of a loop
                        line.databuffer.tdata.append( float(newt) )
                        line.databuffer.xdata.append( float(newx[inew]) )
                        line.databuffer.ydata.append( float(newy[inew]) )
                        line.databuffer.errordata.append(float(newerror[inew]) )
                        while len(line.databuffer.tdata) > line.buffersize:
                            line.databuffer.tdata.pop(0)
                            line.databuffer.xdata.pop(0)
                            line.databuffer.ydata.pop(0)
                            line.databuffer.errordata.pop(0)

                        line.__newdata = True

                        #tdata = np.roll(tdata, -1)
                        #xdata = np.roll(xdata, -1)
                        #ydata = np.roll(ydata, -1)
                        #tdata[-1] = float(newt)
                        #xdata[-1] = float(newx[inew])
                        #ydata[-1] = float(newy[inew])
                        #line.databuffer.tdata = tdata
                        #line.databuffer.xdata = xdata
                        #line.databuffer.ydata = ydata

                    # Show the unit in the legend, if wished by the user, and we have access to the device that can give us the metainformation
                    if (self.config.show_units) and (self.device is not None):
                        #self.logger.debug(funcname + 'Getting metadata for {}'.format(line._y_raddr))
                        try:
                            line._metadata  # metadata found, doing nothing
                        except:
                            line._metadata = self.device.get_metadata(line._y_raddr)
                            self.logger.debug(funcname + ' Datakeyinfo {:s}'.format(str(line._datakeys)))
                            try:
                                unit = line._metadata['unit']
                                self.logger.debug(funcname + 'Found a unit for {}'.format(line._y_raddr))
                            except:
                                self.logger.debug(funcname + 'Did not find a unit',exc_info=True)
                                unit = None

                            if unit is not None:
                                self.config.lines[iline].unit = unit
                                self.apply_config()

            # Update the lines plot
            something_updated = False
            for iline, line in enumerate(self.config.lines):
                tlastupdate = line._tlastupdate  # The time the plot was last updated
                # Check if an update of the plot shall be done, or if only the buffer is updated
                dt = tnow - tlastupdate
                if dt > self.config.dt_update:
                    update = True
                else:
                    update = False
                    # print('no update')

                #if len(self.config.lines) > 1:
                #    print('Update',update,line.__newdata)
                if update and line.__newdata:  # We could check here if data was changed above the for given line
                    line._tlastupdate = tnow
                    try:
                        [x,y,err]= self.__get_data_for_line(line)
                        #print('x',x,'err',err)
                        line._lineplot.setData(x=x, y=y)
                        self.x_min = min(self.x_min,min(x))
                        self.x_max = max(self.x_max, max(x))
                        something_updated = True
                        if line._errorplot is not None:
                            beamwidth = None
                            line._errorplot.setData(x=np.asarray(x), y=np.asarray(y), top=np.asarray(err) * 1,
                                                    bottom=np.asarray(err) * 1, beam=beamwidth)

                    except:
                        self.logger.info('Could not update line',exc_info=True)

            if something_updated:
                try:
                    # Check if ranges need to be changed
                    if self.config.plot_mode_x == 'last_N_s':
                        xmin = self.x_max - self.config.last_N_s
                        xmax = self.x_max
                        self.plotWidget.setXRange(xmin,xmax)
                except:
                    logger.info(funcname,exc_info=True)

            if len(self.config.lines) > 1:
                pass
                #print('DONE DONE DONE')
        except:
            self.logger.debug('Could not update data', exc_info=True)