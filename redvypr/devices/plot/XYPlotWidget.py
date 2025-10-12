import datetime
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
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
from collections.abc import Iterable
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
logger = logging.getLogger('redvypr.device.XYPlotWidget(base)')
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)

colors = ['red','blue','green','gray','yellow','purple']

class Databufferline(pydantic.BaseModel):
    model_config = {'extra': 'allow'}
    skip_bufferdata_when_serialized: bool = pydantic.Field(default=True, description='Do not save the buffer data when serialized')
    tdata: list = pydantic.Field(default=[])
    xdata: list = pydantic.Field(default=[])
    ydata: list = pydantic.Field(default=[])
    errordata: list = pydantic.Field(default=[])
    def clear(self):
        self.tdata = []
        self.xdata = []
        self.ydata = []
        self.errordata = []

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
    unit_x: str = pydantic.Field(default='', description='The unit of the line')
    unit_y: str = pydantic.Field(default='', description='The unit of the line')
    label: str = pydantic.Field(default='', description='The of the line')
    label_format: str = pydantic.Field(default='{NAME} {Y_ADDR} [{UNIT}]', description='The name of the line, this is shown in the legend, $y to use the redvypr address')
    x_addr: RedvyprAddress = pydantic.Field(default=RedvyprAddress('t'), description='The realtimedata address of the x-axis')
    y_addr: RedvyprAddress = pydantic.Field(default=RedvyprAddress('/d:somedevice/k:data'), description='The realtimedata address of the x-axis')
    error_addr: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''), description='The realtimedata address for an optional error band around the line')
    error_mode: typing.Literal['off', 'standard', 'factor', 'constant'] = pydantic.Field(default='off', description='')
    error_factor: float = pydantic.Field(default=1.1, description='')
    error_constant: float = pydantic.Field(default=.01, description='')
    color: pydColor = pydantic.Field(default=pydColor('red'), description='The color of the line')
    linewidth: float = pydantic.Field(default=2.0, description='The linewidth')
    linestyle: typing.Literal['SolidLine','DashLine','DotLine','DashDotLine','DashDotDotLine'] = pydantic.Field(default='SolidLine', description='The linestyle, see also https://doc.qt.io/qt-6/qt.html#PenStyle-enum')
    databuffer: Databufferline = pydantic.Field(default=Databufferline(), description='The databuffer', editable=False)
    plot_mode_x: typing.Literal['all', 'last_N_s', 'last_N_points'] = pydantic.Field(default='all', description='')
    last_N_s: float = pydantic.Field(default=60,
                                     description='Plots the last seconds, if plot_mode_x is set to last_N_s')
    last_N_points: int = pydantic.Field(default=1000,
                                        description='Plots the last points, if plot_mode_x is set to last_N_points')
    plot_every_Nth: int = pydantic.Field(default=1, description='Uses every Nth datapoint for plotting')

    def get_data(self, xlim=None, ylim=None):
        funcname = __name__ + '.get_data():'
        t = np.asarray(self.databuffer.tdata)  # The line to plot
        x = np.asarray(self.databuffer.xdata)  # The line to plot
        y = np.asarray(self.databuffer.ydata)  # The line to plot
        err = np.asarray(self.databuffer.errordata)  # The line to plot
        ind_x = np.ones(x.shape, dtype=bool)
        ind_y = np.ones(y.shape, dtype=bool)
        if xlim is not None:
            ind_x = (x > xlim[0]) & (x < xlim[1])

        if ylim is not None:
            ind_y = (y > ylim[0]) & (y < ylim[1])

        ind = ind_x & ind_y
        tdata_tmp = t[ind]
        xdata_tmp = x[ind]
        ydata_tmp = y[ind]
        err_tmp = err[ind]
        return {'x': xdata_tmp, 'y': ydata_tmp, 't': tdata_tmp, 'err': err_tmp}

    def append(self, data):
        inx = (data in self.x_addr)
        iny = (data in self.y_addr)
        if inx and iny:
            rdata = redvypr.data_packets.Datapacket(data)
            # data can be a single float or a list, if its a list add it item by item
            newt = data['t']  # Add also the time of the packet
            newx = self.x_addr.get_data(rdata)
            newy = self.y_addr.get_data(rdata)

            if (type(newx) is not list):
                newx = [newx]
            if (type(newy) is not list):
                newy = [newy]

            if self.error_mode != 'off':
                error_mode: typing.Literal['off', 'standard', 'factor', 'constant'] = pydantic.Field(
                    default='standard', description='')
                error_factor: float = pydantic.Field(default=1.1, description='')
                error_constant: float = pydantic.Field(default=.01, description='')
                # print('errordata',error_raddr.datakey)
                if len(self.error_addr) > 0 and self.error_mode == 'standard':
                    # logger.debug('Error standard')
                    newerror = self.error_addr.get_data(rdata)
                    if (type(newerror) is not list):
                        newerror = [newerror]
                    # print('newerror',newerror)
                elif self.error_mode == 'factor':
                    # print('Error factor')
                    errdata = np.asarray(newy)
                    errdata_factor = errdata * self.error_factor - errdata.mean()
                    newerror = errdata_factor.tolist()
                elif self.error_mode == 'constant':
                    # print('Error constant')
                    newerror = [self.error_constant] * len(newx)
            else:
                newerror = [0] * len(newx)

            if (len(newx) != len(newy)) or (len(newx) != len(newerror)):
                raise ValueError('lengths of x, y and error data different (x:{:d}, y:{:d}, err:{:d})'.format(len(newx), len(newy), len(newerror)))

            for inew in range(len(newx)):  # TODO this can be optimized using indices instead of a loop
                if isinstance(newt, Iterable):
                    self.databuffer.tdata.append(float(newt[inew]))
                else:
                    self.databuffer.tdata.append(float(newt))

                self.databuffer.xdata.append(float(newx[inew]))
                self.databuffer.ydata.append(float(newy[inew]))
                self.databuffer.errordata.append(float(newerror[inew]))
                while len(self.databuffer.tdata) > self.buffersize:
                    self.databuffer.tdata.pop(0)
                    self.databuffer.xdata.pop(0)
                    self.databuffer.ydata.pop(0)
                    self.databuffer.errordata.pop(0)

        else:
            raise ValueError('Datapacket does not contain data for address xaddr:{}:{}, yadd:{}:{}'.format(self.x_addr,inx,self.y_addr,iny))

class ConfigXYplot(pydantic.BaseModel):
    location: list  = pydantic.Field(default=[])
    type: typing.Literal['XY-Plot'] = pydantic.Field(default='XY-Plot')
    dt_update: float = pydantic.Field(default=0.25,description='Update time of the plot [s]')
    interactive: typing.Literal['standard', 'rectangle','xlim','ylim','xlim_keep','ylim_keep'] = pydantic.Field(default='standard',description='Interactive modes')
    data_dialog: typing.Literal['off', 'table'] = pydantic.Field(default='table', description='Option if a data dialog is shown when finished with the interactive mode')
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


class XYDataViewer(QtWidgets.QWidget):
    def __init__(self, data, device = None, xyplotwidget=None):
        """
        Widget is used to select data in plot and display it

        """
        funcname = __name__ + '.init():'
        super().__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        self.xyplotwidget = xyplotwidget

        self.data = data
        self.device = device
        self.setWindowTitle('redvypr data selection')
        for i,d in enumerate(self.data['lines']):
            table = XYDataTable(d)
            tabname = 'Line {}'.format(i)
            #tabname = d['name']
            self.tabs.addTab(table,tabname)

        self.extras_widget = QtWidgets.QWidget()
        self.extras_widget_layout = QtWidgets.QFormLayout(self.extras_widget)
        self._comment_widget = QtWidgets.QLineEdit()
        self.extras_widget_layout.addRow('Comment',self._comment_widget)

        self.tabs.addTab(self.extras_widget, 'Extra')


        self.apply_button = QtWidgets.QPushButton('Send')
        self.cancel_button = QtWidgets.QPushButton('Cancel')
        self.apply_button.clicked.connect(self.send_clicked)
        self.cancel_button.clicked.connect(self.close)

        self.layout.addWidget(self.tabs, 0, 0,1,-1)
        self.layout.addWidget(self.apply_button, 1, 0)
        self.layout.addWidget(self.cancel_button, 1, 1)

    def send_clicked(self):
        logger.debug('Send clicked ...')
        comment_str = self._comment_widget.text()
        self.data['comment'] = comment_str
        if self.xyplotwidget is not None:
            logger.debug('Data:{}'.format(self.data))

            self.xyplotwidget.publish_data(self.data)


class XYDataTable(QtWidgets.QTableWidget):
    def __init__(self, data):
        """

        """
        funcname = __name__ + '.init():'
        super().__init__()
        self.data = data
        self.setColumnCount(3)
        t = self.data['t']
        x = self.data['x']
        y = self.data['y']
        rowoff = 2
        self.setRowCount(len(x) + rowoff)
        self.col_t = 0
        self.col_x = 1
        self.col_y = 2
        try:
            xaddrstr = self.data['x_addr'].get_str()
        except:
            xaddrstr = str(self.data['x_addr'])
        try:
            yaddrstr = self.data['y_addr'].get_str()
        except:
            yaddrstr = str(self.data['y_addr'])
        item = QtWidgets.QTableWidgetItem('Time')
        self.setItem(0, self.col_t, item)
        item = QtWidgets.QTableWidgetItem(xaddrstr)
        self.setItem(0, self.col_x, item)
        item = QtWidgets.QTableWidgetItem(yaddrstr)
        self.setItem(0, self.col_y, item)
        item = QtWidgets.QTableWidgetItem(str(self.data['unit_x']))
        self.setItem(1, self.col_x, item)
        item = QtWidgets.QTableWidgetItem(str(self.data['unit_y']))
        self.setItem(1, self.col_y, item)

        for irow, t_data in enumerate(t):
            t_str = datetime.datetime.utcfromtimestamp(t_data).strftime('%Y-%m-%d %H:%M:%S.%f')
            item = QtWidgets.QTableWidgetItem(t_str)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.setItem(irow + rowoff, self.col_t, item)

        for irow,x_data in enumerate(x):
            x_str = str(x_data)
            item = QtWidgets.QTableWidgetItem(x_str)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.setItem(irow+rowoff,self.col_x,item)

        for irow, y_data in enumerate(y):
            y_str = str(y_data)
            item = QtWidgets.QTableWidgetItem(y_str)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.setItem(irow+rowoff, self.col_y, item)

        self.resizeColumnsToContents()

    def keyPressEvent(self, event):
        # Prüfen, ob Strg+C gedrückt wurde
        if event.key() == QtCore.Qt.Key_C and (event.modifiers() & QtCore.Qt.ControlModifier):
            self.handle_copy_event()
        else:
            # Standardverhalten für andere Tasten
            super().keyPressEvent(event)

    def handle_copy_event(self):
        #
        selected_items = self.selectedItems()
        copied_text = ''
        if selected_items:
            if len(selected_items) == 1:
                QtWidgets.QApplication.clipboard().setText(selected_items[0].text())
            else:
                for row in range(self.rowCount()):
                    for column in range(self.columnCount()):
                        for item in selected_items:
                            if (item.row() == row) and (item.column() == column):
                                copied_text += item.text()

                        copied_text += '\t'
                    copied_text += '\n'
                QtWidgets.QApplication.clipboard().setText(copied_text)


# config_template_graph['description'] = description_graph
class XYPlotWidget(QtWidgets.QFrame):
    """ Widget is plotting realtimedata using the pyqtgraph functionality

    """
    closing = QtCore.pyqtSignal()  # Signal notifying that a subscription changed
    interactive_signal = QtCore.pyqtSignal(dict)  # Signal notifying that a subscription changed
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
        self._interactive_mode = ''
        self.x_min = 0
        self.x_max = 0
        if (config == None):  # Create a config from the template
            self.config = ConfigXYplot()
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

    def set_interactive_mode(self, mode):
        modes = ['standard', 'rectangle', 'xlim', 'ylim', 'xlim_keep', 'ylim_keep']
        if mode in modes:
            self.config.interactive = mode
            self.apply_config()
        else:
            raise ValueError('Unknown mode {}, choose between {}'.format(mode,modes))

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
            # Data selection
            dataSelectionMenu = plot.plotItem.vb.menu.addMenu('Data selection')
            dataSelectionAction = QtWidgets.QWidgetAction(self)
            # Create Dataselection-Widget to choose from the different options
            dataSelectionMenuWidget = QtWidgets.QWidget()
            dataSelectionMenuWidget_layout = QtWidgets.QVBoxLayout(dataSelectionMenuWidget)
            self._dataSelection_radio_standard = QtWidgets.QRadioButton('Standard')
            self._dataSelection_radio_rectangle = QtWidgets.QRadioButton('Rectangle')
            self._dataSelection_radio_xlim = QtWidgets.QRadioButton('X-Range')
            self._dataSelection_radio_ylim = QtWidgets.QRadioButton('Y-Range')
            if self.config.interactive == 'standard':
                self._dataSelection_radio_standard.setChecked(True)
            elif self.config.interactive == 'rectangle':
                self._dataSelection_radio_rectangle.setChecked(True)
            elif self.config.interactive == 'xlim':
                self._dataSelection_radio_xlim.setChecked(True)
            elif self.config.interactive == 'ylim':
                self._dataSelection_radio_ylim.setChecked(True)
            self._dataSelection_radio_standard.toggled.connect(self.pyqtgraphdataSelectionAction)
            self._dataSelection_radio_rectangle.toggled.connect(self.pyqtgraphdataSelectionAction)
            self._dataSelection_radio_xlim.toggled.connect(self.pyqtgraphdataSelectionAction)
            self._dataSelection_radio_ylim.toggled.connect(self.pyqtgraphdataSelectionAction)
            dataSelectionMenuWidget_layout.addWidget(self._dataSelection_radio_standard)
            dataSelectionMenuWidget_layout.addWidget(self._dataSelection_radio_rectangle)
            dataSelectionMenuWidget_layout.addWidget(self._dataSelection_radio_xlim)
            dataSelectionMenuWidget_layout.addWidget(self._dataSelection_radio_ylim)
            dataSelectionAction.setDefaultWidget(dataSelectionMenuWidget)
            dataSelectionMenu.addAction(dataSelectionAction)
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
            self.layout.addWidget(plot)
            self.plotWidget = plot
            self.legendWidget = legend
            # plot_dict = {'widget': plot, 'lines': []}

    def clean_all_interactive_items(self):
        """
        Cleans all potential old interactive items
        Returns
        -------

        """
        funcname = __name__ + '.clean_all_interactive_items():'
        self.logger.debug(funcname)

        plot = self.plotWidget
        # Items from xlim mode
        try:
            plot.removeItem(self.vLineMouse)
        except:
            pass

        # Items from rectangle mode
        try:
            self.plotWidget.removeItem(self.interactive_rectangle['rect'])
            self.interactive_rectangle['rect'] = None
        except:
            pass

        try:
            self.plotWidget.removeItem(self.interactive_rectangle['scatter'])
            self.interactive_rectangle['points'] = []
        except:
            pass

        try:
            for line in self.interactive_xylim['lines']:
                self.plotWidget.removeItem(line)

            self.interactive_xylim['lines'] = []
        except:
            pass

    def enable_interactive_standard(self,):
        """
        Enables the interactive xlim or ylim mode for data selection
        Returns
        -------

        """
        funcname = __name__ + '.enable_interactive_standard():'
        if 'standard' in self._interactive_mode:
            self.logger.debug(funcname + ' standard mode already enabled')
        else:
            self.logger.debug(funcname + ' Enabling standard mode')
            self.clean_all_interactive_items()
            self._interactive_mode = 'standard'

    def enable_interactive_xylim(self,mode='xlim'):
        """
        Enables the interactive xlim or ylim mode for data selection
        Returns
        -------

        """
        funcname = __name__ + '.enable_interactive_xylim():'
        if 'lim' in self._interactive_mode :
            self.logger.debug(funcname + ' xlim mode already enabled')
        else:
            self.logger.debug(funcname + ' Enabling xlim mode')
            self.clean_all_interactive_items()
            plot = self.plotWidget
            self.logger.debug('Adding interactive mouse (vertical line)')
            #plot.scene().sigMouseMoved.connect(self.mouse_moved)
            #plot.scene().sigMouseClicked.connect(self.mouse_clicked)
            self.interactive_xylim = {}
            self.interactive_xylim['lines'] = []
            if 'xlim' in self.config.interactive.lower():
                self.interactive_xylim['angle'] = 90
            else:
                self.interactive_xylim['angle'] = 0
            #self.vb = plot.plotItem.vb
            # Add a vertical line
            color = QtGui.QColor(200, 100, 100)
            linewidth = 2.0
            pen = pyqtgraph.mkPen(color, width=linewidth)
            self.vLineMouse = pyqtgraph.InfiniteLine(angle=self.interactive_xylim['angle'], movable=False, pen=pen)
            # print('Set pen 3')
            plot.addItem(self.vLineMouse, ignoreBounds=True)
            self._interactive_mode = self.config.interactive

    def enable_interactive_rectangle(self):
        """
        Enables the rectangle mode
        Returns
        -------

        """
        funcname = __name__ + '.enable_interactive_rectangle():'
        if self._interactive_mode == 'rectangle':
            self.logger.debug(funcname + ' Rectangle mode already enabled')
        else:
            self.logger.debug(funcname + ' Enabling rectangle mode')
            self.clean_all_interactive_items()
            plot = self.plotWidget
            self.interactive_rectangle = {}
            self.interactive_rectangle['points'] = []
            self.interactive_rectangle['rect'] = None
            self._interactive_mode = 'rectangle'

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

    def pyqtgraphdataSelectionAction(self):
        funcname = __name__ + '.pyqtgraphdataSelectionAction():'
        if self._dataSelection_radio_standard.isChecked():
            self.config.interactive = 'standard'
        elif self._dataSelection_radio_rectangle.isChecked():
            self.config.interactive = 'rectangle'
        elif self._dataSelection_radio_xlim.isChecked():
            self.config.interactive = 'xlim'
        elif self._dataSelection_radio_ylim.isChecked():
            self.config.interactive = 'ylim'

        self.logger.debug(funcname + ' Dataselction:{}'.format(self.config.interactive))
        self.apply_config()

    def pyqtgraphXMenuAction(self):
        funcname = __name__ + '.pyqtgraphXMenuAction()'
        self.logger.debug(funcname)

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
            self.lineConfigWidget = redvypr.widgets.redvyprAddressWidget.RedvyprAddressWidget(redvypr=self.redvypr, device=self.device)
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

    def mouse_moved(self, evt):
        """Function if mouse has been moved
        """
        pos = (evt.x(), evt.y())
        if 'xlim' in self.config.interactive:
            mousePoint = self.plotWidget.plotItem.vb.mapSceneToView(evt)
            self.vLineMouse.setPos(mousePoint.x())
        elif 'ylim' in self.config.interactive:
            mousePoint = self.plotWidget.plotItem.vb.mapSceneToView(evt)
            self.vLineMouse.setPos(mousePoint.y())
        elif self.config.interactive == 'rectangle':
            mousePoint = self.plotWidget.plotItem.vb.mapSceneToView(evt)
            points = self.interactive_rectangle['points']
            #print('Hallo',len(points))
            if len(points) == 1:
                x0 = self.interactive_rectangle['points'][0]['pos'][0]
                y0 = self.interactive_rectangle['points'][0]['pos'][1]
                dx = mousePoint.x() - x0
                dy = mousePoint.y() - y0
                logger.debug('Rectangle:{} {}'.format(dx, dy))
                if self.interactive_rectangle['rect'] is None:
                    self.interactive_rectangle['rect'] = pyqtgraph.RectROI([x0, y0], [dx, dy],
                                                                           pen='r')  # Position [2, 2], Größe [3, 2]
                    self.plotWidget.addItem(self.interactive_rectangle['rect'])
                else:
                    self.interactive_rectangle['rect'].setSize([dx,dy])

    def mouse_clicked(self, event):
        #print('Click!')
        #print('Clicked: ' + str(event.scenePos()))
        data_user = None
        if 'lim' in self.config.interactive:
            color = QtGui.QColor(200, 100, 100)
            linewidth = 2.0
            pen = pyqtgraph.mkPen(color, width=linewidth)
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                nlines = 2
                vb = self.plotWidget.plotItem.vb
                # vb = self.plotWidget.vb
                mouse_point = vb.mapSceneToView(event.scenePos())
                x, y = mouse_point.x(), mouse_point.y()
                lines = self.interactive_xylim['lines']
                angle = self.interactive_xylim['angle']
                line = pyqtgraph.InfiniteLine(angle=angle, movable=False, pen=pen)
                if 'xlim' in self.config.interactive:
                    line.setPos(x)
                else:
                    line.setPos(y)
                self.plotWidget.addItem(line, ignoreBounds=True)
                lines.append(line)
                #if len(lines) < nlines:

                if len(lines) == nlines:
                    # This works at the moment only for nlines=2, but its a start
                    xlim_tmp = [lines[0].getXPos(),lines[-1].getXPos()]
                    xlim = [min(xlim_tmp),max(xlim_tmp)]
                    ylim_tmp = [lines[0].getYPos(), lines[-1].getYPos()]
                    ylim = [min(ylim_tmp), max(ylim_tmp)]
                    if 'xlim' in self.config.interactive:
                        data_user = self.get_data(xlim=xlim)
                    else:
                        data_user = self.get_data(ylim=ylim)

                    # Create data to be emitted
                    data_emit = {'xlines': [], 'ylines': []}
                    for l in lines:
                        if 'xlim' in self.config.interactive:
                            data_emit['xlines'].append(l.getXPos())
                        else:
                            data_emit['ylines'].append(l.getYPos())

                    # Emit a signal, that all lines are set
                    self.interactive_signal.emit(data_emit)
                    #print('Data user',data_user)
                    if not('_keep' in self.config.interactive):
                        for l in lines:
                            self.plotWidget.removeItem(l)

                        self.interactive_xylim['lines'] = []

                if len(lines) > nlines:
                    data_emit = {'xlines': [], 'ylines': []}
                    # Emit a signal, that there are no lines anymore
                    self.interactive_signal.emit(data_emit)
                    # Remove all lines and start from scratch
                    for l in lines:
                        self.plotWidget.removeItem(l)

                    self.interactive_xylim['lines'] = []

        elif self.config.interactive == 'rectangle':
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                vb = self.plotWidget.plotItem.vb
                #vb = self.plotWidget.vb
                mouse_point = vb.mapSceneToView(event.scenePos())
                x, y = mouse_point.x(), mouse_point.y()
                points = self.interactive_rectangle['points']
                points.append({'pos': (x, y), 'size': 10, 'pen': {'color': 'b', 'width': 2}, 'brush': 'r'})
                #print('Points',points,len(points))
                try:
                    logger.info('Set data')
                    #self.interactive_rectangle['scatter'].setData(points)
                except:
                    logger.info('Could not set data', exc_info=True)

                if len(points) == 1:
                    #print('Adding items')
                    self.interactive_rectangle['scatter'] = pyqtgraph.ScatterPlotItem()
                    self.plotWidget.addItem(self.interactive_rectangle['scatter'])
                    #self.interactive_rectangle['scatter'].setData(points)
                    self.plotWidget.scene().sigMouseMoved.connect(self.mouse_moved)
                elif len(points) == 2:
                    #print('Two points, getting data')
                    xlim = np.sort([self.interactive_rectangle['points'][0]['pos'][0],
                                    self.interactive_rectangle['points'][1]['pos'][0]])
                    ylim = np.sort([self.interactive_rectangle['points'][0]['pos'][1],
                                    self.interactive_rectangle['points'][1]['pos'][1]])
                    #xlim = [min(), max(self.interactive_rectangle['points'][1]['pos'])]
                    #ylim = [min(self.interactive_rectangle['points'][0]['pos']), max(self.interactive_rectangle['points'][1]['pos'])]
                    data_user = self.get_data(xlim,ylim)
                    #print('Got data',data_user)
                    # Remove all items
                    self.plotWidget.removeItem(self.interactive_rectangle['rect'])
                    self.interactive_rectangle['rect'] = None
                    self.plotWidget.removeItem(self.interactive_rectangle['scatter'])
                    self.interactive_rectangle['points'] = []
                    #try:
                    #    self.plotWidget.scene().sigMouseMoved.disconnect(self.mouse_moved)
                    #except:
                    #    pass

        # Show the data, if available
        if data_user is not None:
            if self.config.data_dialog == 'table':
                # Here it could be decided what to do with the data
                self._data_table = XYDataViewer(data_user, device=self.device, xyplotwidget=self)
                self._data_table.show()
            elif self.config.data_dialog == 'off':
                self.publish_data(data_user)


    def set_title(self, title):
        """
        Sets the title of the plot
        """
        funcname = __name__ + '.set_title()'
        self.logger.debug(funcname)
        self.config.title = title
        self.plotWidget.setTitle(title)

    def set_line(self, index, y_addr, name='$y', x_addr='t', color=[255, 0, 0], linewidth=1, bufsize=2000):
        """
        Sets the line at index to the parameters
        """
        self.add_line(y_addr=y_addr, name=name, x_addr=x_addr, color=color, linewidth=linewidth, bufsize=bufsize, index=index)

    def add_line(self, y_addr, x_addr='t', name='$y', error_addr='', color=None, linewidth=1, bufsize=20000, numplot=2000, index=None):
        """
        Adds a line to the plot
        """
        funcname = __name__ + '.add_line()'
        self.logger.debug(funcname)
        if not(isinstance(y_addr, redvypr.RedvyprAddress)):
            self.logger.debug('Redvypr y-address')
            y_addr = redvypr.RedvyprAddress(y_addr)
        if not(isinstance(x_addr, redvypr.RedvyprAddress)):
            self.logger.debug('Redvypr x-address')
            x_addr = redvypr.RedvyprAddress(x_addr)
        if not(isinstance(error_addr, redvypr.RedvyprAddress)):
            self.logger.debug('Redvypr error-address')
            error_addr = redvypr.RedvyprAddress(error_addr)
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
        self.config.lines[index]._xdata_addr_old = x_addr
        # Add the address as well to the data
        #self.config.lines[index].databuffer.xdata_addr = x_addr
        #self.config.lines[index].databuffer.ydata_addr = y_addr
        #self.config.lines[index].databuffer.errordata_addr = error_addr
        self.apply_config()

    def construct_labelname(self, line, labelformat=None):
        name = line.name
        unit = line.unit_y
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
        #line.y_addr = address_dict['datastream_str']
        #print('Address dict',address_dict)
        line.y_addr = address_dict['datastream_address']
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

            # Add the address as well to the data
            #line.databuffer.xdata_addr = line.x_addr
            #line.databuffer.ydata_addr = line.y_addr
            #line.databuffer.errordata_addr = line.error_addr
            #line.databuffer.error_mode = line.error_mode
            #line.databuffer.error_factor = line.error_factor
            #line.databuffer.error_constant = line.error_constant

            # Creating the correct addresses first
            try:
                self.logger.debug('Line {},{}'.format(line,iline))
                # Error address
                error_addr = None
                if line.error_mode != 'off':
                    self.logger.debug('Error mode 1')
                    errorplot = pyqtgraph.ErrorBarItem(name=line._name_applied,pen=pen)
                    line._errorplot = errorplot  # Add the line as an attribute to the configuration
                    errorplot._line_config = line
                    plot.addItem(errorplot)
                else:
                    self.logger.debug('Error mode 2')
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
                try:
                    line._xdata_addr_old
                except:
                    line._xdata_addr_old = line.x_addr

                if line._xdata_addr_old == line.x_addr:
                    self.logger.debug('Address did not change')
                else:
                    self.logger.debug('Address changed')
                    line._xdata_addr_old = line.x_addr
                    line.databuffer.clear()
                    # TODO, here an unsubscribe and resubscribe would be better
                    #self.logger.debug('Address changed, clearing buffer')
                    #self.clear_buffer(line)

                #
                self.logger.debug(funcname + ' Setting the name')
                try:
                    self.legendWidget.removeItem(line._lineplot)
                except:
                    self.logger.debug(funcname + ' Could not remove line')
                self.legendWidget.addItem(line._lineplot, line.label)
                self.logger.debug('Setting the data')
                line._lineplot.setData(name=line.label,x=[],y=[])
                if self.config.automatic_subscription:
                    self.logger.debug(funcname + 'Subscribing to x address {}'.format(line.x_addr))
                    self.device.subscribe_address(line.x_addr)
                    self.logger.debug(funcname + 'Subscribing to y address {}'.format(line.y_addr))
                    self.device.subscribe_address(line.y_addr)
                    if line._errorplot is not None:
                        self.logger.debug(funcname + 'Subscribing to error address {}'.format(line.error_addr))
                        self.device.subscribe_address(line.error_addr)

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

        # Enable/disable interactive modes, connect only once
        try:
            plot.scene().sigMouseMoved.disconnect(self.mouse_moved)
        except:
            pass
        try:
            plot.scene().sigMouseClicked.disconnect(self.mouse_clicked)
        except:
            pass

        plot.scene().sigMouseMoved.connect(self.mouse_moved)
        plot.scene().sigMouseClicked.connect(self.mouse_clicked)
        if self.config.interactive.lower() == 'rectangle':
            self.logger.debug(funcname + 'Interactive rectangle mode')
            self.enable_interactive_rectangle()
        elif 'lim' in self.config.interactive.lower():
            self.enable_interactive_xylim()
        elif 'standard' in self.config.interactive.lower():
            self.enable_interactive_standard()

        self.logger.debug(funcname + ' done.')

    def get_metadata_for_line(self, line):
        funcname = __name__ + '.get_metadata_for_line():'
        iline = self.config.lines.index(line)
        self.logger.debug(funcname + 'Getting metadata for {}'.format(line.y_addr))
        try:
            line._metadata  # metadata found, doing nothing
        except:
            line._metadata = self.device.get_metadata(line.y_addr)
            self.logger.debug(funcname + ' Datakeyinfo {:s}'.format(str(line._metadata)))
            try:
                unit = line._metadata['unit']
                self.logger.debug(funcname + 'Found a unit for {}'.format(line.y_addr))
            except:
                self.logger.debug(funcname + 'Did not find a unit', exc_info=True)
                unit = None

            if unit is not None:
                self.config.lines[iline].unit_y = unit
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
            line_tmp.databuffer = Databufferline()
            # Set the data
            line_tmp._lineplot.setData(x=line_tmp.databuffer.xdata, y=line_tmp.databuffer.ydata)

    def publish_data(self, datapacket_publish):
        """
        Publishes the data via the dataqueue or by a signal.

        Parameters
        ----------
        data

        Returns
        -------

        """
        funcname = __name__ + '.publish_data():'
        try:
            dataqueue = self.device.dataqueue
        except:
            dataqueue = None

        if dataqueue is not None:
            logger.debug(funcname + 'Sending datapacket')
            dataqueue.put(datapacket_publish)
            logger.debug('datapacket:{}'.format(datapacket_publish))

    def get_data(self, xlim=None, ylim=None):
        """
        Gets the data of the buffer in the limits of xlim and/or ylim
        """
        funcname = __name__ + '.get_data():'
        logger.debug(funcname + 'get data:{}'.format(xlim,ylim))
        data = []
        tdata = []
        xdata = []
        ydata = []
        datapacket = {}
        for iline, line in enumerate(self.config.lines):
            #print('Line', line)
            #print('Type Line', type(line))
            #line_dict = line.line_dict
            #line = line_dict['line']  # The line to plot
            #config = line_dict['config']  # The line to plot
            #t = np.asarray(line.databuffer.tdata)  # The line to plot
            #x = np.asarray(line.databuffer.xdata)  # The line to plot
            #y = np.asarray(line.databuffer.ydata)  # The line to plot
            #err = np.asarray(line.databuffer.errordata)  # The line to plot
            #ind_x = np.ones(x.shape, dtype=bool)
            #ind_y = np.ones(y.shape, dtype=bool)
            #print(funcname + 'xlim',xlim,'ylim',ylim)
            #if xlim is not None:
            #    ind_x = (x > xlim[0]) & (x < xlim[1])
            #
            #if ylim is not None:
            #    ind_y = (y > ylim[0]) & (y < ylim[1])

            #print('ind',ind_x,ind_y)
            #ind = ind_x & ind_y
            # check for relative data


            data_tmp = line.get_data(xlim,ylim)
            tdata_tmp = data_tmp['t']
            xdata_tmp = data_tmp['x']
            ydata_tmp = data_tmp['y']
            errdata_tmp = data_tmp['err']
            data.append({'x': xdata_tmp, 'y': ydata_tmp, 't': tdata_tmp, 'err':errdata_tmp,
                         'x_addr':line.x_addr, 'y_addr':line.y_addr,
                         'unit_x': line.unit_x, 'unit_y': line.unit_y,
                         'name':line.name})

            self.logger.debug(funcname + ' Got data of length {:d}'.format(len(tdata_tmp)))
            # print('get_data',datetime.datetime.utcfromtimestamp(tdata_tmp[0]),datetime.datetime.utcfromtimestamp(xdata_tmp[0]))
            try:
                x_addrstr = line.x_addr.get_str()
            except:
                x_addrstr = str(line.x_addr)

        datapacket['lines'] = data
        return datapacket

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

    def update_plot(self, data, force_update=False):
        """ Updates the plot based on the given data
        """
        funcname = self.__class__.__name__ + '.update_plot():'
        #self.logger.debug(funcname + 'Update {}'.format(len(self.config.lines)))
        tnow = time.time()
        ## Create a redvypr datapacket
        #rdata = redvypr.data_packets.Datapacket(data)
        #print(funcname + 'got data',data,tnow)
        try:
            # Check if the device is to be plotted
            # Loop over all lines
            for iline, line in enumerate(self.config.lines):
                line.__newdata = False
                try:
                    line.append(data)
                    line.__newdata = True
                except:
                    self.logger.debug('Could not add data',exc_info=True)
                    #pass

                if True:
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
                                self.config.lines[iline].unit_y = unit
                                self.apply_config()

            # Update the lines plot
            something_updated = False
            for iline, line in enumerate(self.config.lines):
                tlastupdate = line._tlastupdate  # The time the plot was last updated
                # Check if an update of the plot shall be done, or if only the buffer is updated
                dt = tnow - tlastupdate
                if dt > self.config.dt_update:
                    update = True
                elif force_update:
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