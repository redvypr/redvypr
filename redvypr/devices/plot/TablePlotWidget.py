import datetime
import pytz
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
import redvypr.data_packets
import redvypr.gui
import redvypr.files as files
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget
from redvypr.widgets.redvyprAddressWidget import RedvyprAddressEditWidget
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket
from redvypr.data_packets import check_for_command

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.TablePlotWidget')
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)


class ConfigTablePlot(pydantic.BaseModel):
    type: typing.Literal['TablePlot'] = pydantic.Field(default='TablePlot')
    datastreams: typing.List[typing.Union[RedvyprAddress]] = pydantic.Field(default=[RedvyprAddress('_redvypr["t"]'),
                                                                                     RedvyprAddress('_redvypr["numpacket"]'),
                                                                                     RedvyprAddress(
                                                                                         '_redvypr["packetid"]'),
                                                                                     RedvyprAddress('sine_rand')
                                                                                     ],
                                                                                 description='The realtimedata datastreams to be displayed in the table')
    formats: typing.Dict[str, str] =  pydantic.Field(default={'_redvypr["t"]':'ISO8601',
                                                            'sine_rand':'{:.2f}'})
    num_packets_show: int = pydantic.Field(default=2,
                                            description='The number of columns to show')
    expansion_level: int = pydantic.Field(default=100,
                                           description='The level of expansion of the datakeys')
    ignore_command_packets: bool = pydantic.Field(default=True,
                                          description='Ignore command packets')
    ignore_metadata_packets: bool = pydantic.Field(default=True,
                                                  description='Ignore metadata packets')
    show_unit: bool = pydantic.Field(default=True,
                                                  description='Show the unit')

class TablePlotWidget(QtWidgets.QWidget):
    def __init__(self, *args, config=None, redvypr_device=None, **kwargs):
        """
        A table widget that displays data of subscribed redvypr data packets

        """
        funcname = __name__ + '.init():'
        super().__init__(*args, **kwargs)
        if config is None:
            config = ConfigTablePlot()
        self.config = config
        self.device = redvypr_device
        if self.device is not None:
            self.redvypr = self.device.redvypr
        else:
            self.redvypr = None
        self.counter = 0
        self.data_table_keys_show = []
        self.col_last_keys_show = 0
        self.col_current = 0
        self.col_packets_showed = 0
        self.numrows_header = 1
        self.layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget()
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)

        # Enable context menu policy
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.layout.addWidget(self.table)
        self.apply_config()

    def show_context_menu(self, position):
        # Get the item at the clicked position
        item = self.table.itemAt(position)
        # Create a menu specific to the item
        menu = QtWidgets.QMenu(self)
        try:
            datastream = item.__datastream__
        except:
            datastream = None

        resizeTable = QtGui.QAction("Resize Table", self)
        resizeTable.triggered.connect(lambda: self.table.resizeColumnsToContents())
        menu.addAction(resizeTable)
        if item is not None and datastream is not None:
            # Create a xyplot action
            actionXyplot = QtGui.QAction("Plot XY", self)
            actionXyplot.triggered.connect(lambda: self.create_xyplot(item))
            menu.addAction(actionXyplot)
            # Create a format menu/action
            formats = []
            menu_formats = menu.addMenu('Formats')
            actionAddformat = QtGui.QAction("Add format", self)
            actionAddformat.triggered.connect(lambda: self.edit_format(item))
            menu_formats.addAction(actionAddformat)
            for fa in self.config.formats:
                try:
                    data_tmp = RedvyprAddress(fa)(datastream)
                except:
                    data_tmp = None
                if data_tmp is not None:
                    format_tmp = self.config.formats[fa]
                    formats.append(format_tmp)
                    menu_format_datastream = menu_formats.addMenu(fa)
                    dataformatAction = QtWidgets.QWidgetAction(self)
                    dataFormatWidget = QtWidgets.QWidget()
                    dataFormatWidget_layout = QtWidgets.QVBoxLayout(dataFormatWidget)
                    format_lineEdit = QtWidgets.QLineEdit(format_tmp)
                    dataFormatWidget_layout.addWidget(format_lineEdit)
                    applybutton = QtWidgets.QPushButton('Apply')
                    applybutton.__formatskey__ = fa
                    applybutton.__format__ = format_tmp
                    applybutton.__format_lineEdit__ = format_lineEdit
                    applybutton.__menu__ = menu_formats
                    applybutton.clicked.connect(self.apply_format_clicked)
                    removebutton = QtWidgets.QPushButton('Remove')
                    removebutton.clicked.connect(self.remove_format_clicked)
                    removebutton.__formatskey__ = fa
                    removebutton.__menu__ = menu_formats
                    dataFormatWidget_layout.addWidget(format_lineEdit)
                    dataFormatWidget_layout.addWidget(applybutton)
                    dataFormatWidget_layout.addWidget(removebutton)
                    dataformatAction.setDefaultWidget(dataFormatWidget)
                    menu_format_datastream.addAction(dataformatAction)

        # Create a configure action
        configAction = QtGui.QAction("Configure", self)
        configAction.triggered.connect(self.config_clicked)
        menu.addAction(configAction)


        # Show the menu at the position of the mouse click
        menu.exec_(self.table.viewport().mapToGlobal(position))

    def create_xyplot(self,item):
        address = RedvyprAddress(item.__datastream__)
        try:
            devicemodulename = 'redvypr.devices.plot.XYPlotDevice'
            plotname = 'XYPlot({})'.format(address.datakey)
            device_parameter = RedvyprDeviceParameter(name=plotname)
            custom_config = redvypr.devices.plot.XYPlotDevice.DeviceCustomConfig()
            custom_config.lines[0].y_addr = redvypr.RedvyprAddress(address)
            plotdevice = self.device.redvypr.add_device(devicemodulename=devicemodulename,
                                                        base_config=device_parameter,
                                                        custom_config=custom_config)

            logger.debug('Starting plot device')
            plotdevice.thread_start()
        except:
            logger.debug('Could not add XY-Plot',exc_info=True)

    def edit_format(self,item):
        #print('Editing format',item,item.__datastream__)
        datastream = item.__datastream__
        self.address_edit_tmp = RedvyprAddressEditWidget(redvypr_address_str=datastream)
        applybutton = self.address_edit_tmp.configwidget_apply
        self.address_edit_tmp.layout.removeWidget(applybutton)
        self.address_edit_tmp.layout.addWidget(applybutton,8,0)

        self.address_edit_tmp.layout.addWidget(QtWidgets.QLabel('Format'), 6, 0)
        self.format_edit = QtWidgets.QLineEdit('{}')
        self.address_edit_tmp.layout.addWidget(self.format_edit, 7, 0)
        self.address_edit_tmp.address_finished.connect(self.edit_format_finished)

        self.address_edit_tmp.show()

    def edit_format_finished(self, addr):
        #print('Address', addr)
        format_new = self.format_edit.text()
        #print('Format new',format_new)
        addrstr = addr['address_str']
        new_dict = {addrstr: format_new, **self.config.formats}
        self.config.formats = new_dict
        self.address_edit_tmp.close()

    def apply_format_clicked(self):
        button = self.sender()
        print('Button apply', button)
        self.config.formats[button.__formatskey__] = button.__format_lineEdit__.text()
        button.__menu__.close()

    def remove_format_clicked(self):
        button = self.sender()
        print('Button remove',button)
        self.config.formats.pop(button.__formatskey__)
        button.__menu__.close()
    def config_clicked(self):
        button = self.sender()

        funcname = __name__ + '.config_clicked():'
        logger.debug(funcname)
        self.config_widget = pydanticConfigWidget(self.config)
        self.config_widget.show()
        #self.config_widget.showMaximized()

        # self.subscribed.emit(self.device)

    def apply_config(self):
        self.reset_table()
        self.device.unsubscribe_all()
        if self.device is not None:
            for d in self.config.datastreams:
                self.device.subscribe_address(d)

    def reset_table(self):
        self.col_last_keys_show = 0
        self.col_current = 0
        self.col_packets_showed = 0
        self.data_table_keys_show = []
        self.data_table_datastreams_show = []
        self.table.setColumnCount(2)
        self.table.setRowCount(1)
        self.table.clear()
        # Plot the header
        item = QtWidgets.QTableWidgetItem('Datakeys')
        item.__counter__ = self.counter
        item.__numrows__ = 1
        item.setBackground(QtGui.QBrush(QtGui.QColor("lightblue")))
        self.table.setItem(0, 0, item)
        item = QtWidgets.QTableWidgetItem('Data')
        item.__counter__ = self.counter
        item.__numrows__ = 1
        item.setBackground(QtGui.QBrush(QtGui.QColor("lightgrey")))
        self.table.setItem(0, 1, item)

    def update_plot(self, data):
        """
        """
        funcname = __name__ + '.update_data():'
        rdata = Datapacket(data)
        if self.config.ignore_command_packets:
            command = check_for_command(data)
            if self.config.ignore_metadata_packets:
                if rdata.address.packetid == 'metadata':
                    return
            if command is not None:
                return

        # Check if everything is found in the data packet
        for d in self.config.datastreams:
            if not d.matches(data):
                return

        if self.col_packets_showed >= self.config.num_packets_show:
            # print('Reset')
            if self.table.columnCount() == 2:
                print("Resetting")
                self.reset_table()
            counter = self.table.item(0, 0).__counter__
            counter1 = self.table.item(0, 1).__counter__
            if counter == counter1:
                self.table.removeColumn(1)
                self.col_packets_showed -= 1
                self.col_current -= 1

            counter = self.table.item(self.numrows_header, 0).__counter__
            counter1 = self.table.item(self.numrows_header, 1).__counter__
            if counter != counter1:
                self.table.removeColumn(0)
                self.col_current -= 1

            numrows_tmp = 0
            for icol_tmp in range(self.table.columnCount()):
                item = self.table.item(0, icol_tmp)
                numrows_tmp = max(item.__numrows__, numrows_tmp)

            self.table.setRowCount(numrows_tmp + self.numrows_header)

        expand_level = self.config.expansion_level
        data_table = []
        data_table_keys_new = []
        data_table_datastreams_new = []
        for d in self.config.datastreams:
            if not d.matches(data):
                return
            else:
                #print('d in data',d)
                datakeys = rdata.datakeys([d], expand=expand_level,return_type='list')
                datastreams = rdata.datastreams([d], expand=expand_level)
                data_table_datastreams_new += datastreams
                # print('rdata',rdata)
                #print('expand level',expand_level)
                #print('datakeys',datakeys)
                for dk in datakeys:
                    data_tmp = rdata[dk]
                    #print('Data tmp',data_tmp)
                    data_table.append(data_tmp)
                    data_table_keys_new.append(dk)


        if self.data_table_keys_show == data_table_keys_new:
            flag_new_keys = False
        else:
            self.data_table_keys_show = data_table_keys_new
            flag_new_keys = True
            self.counter += 1

        #print('Data keys table', data_table_keys_new,flag_new_keys)
        #print('Data keys table show', self.data_table_keys_show)
        #print('Data show',data_table)
        if self.table.rowCount() < len(self.data_table_keys_show):
            self.table.setRowCount(len(self.data_table_keys_show)+self.numrows_header)

        # Plot datakeys
        if flag_new_keys:
            self.data_table_keys_show = data_table_keys_new
            self.data_table_datastreams_show = data_table_datastreams_new
            icol = self.col_current
            ncols = self.table.columnCount()
            if ncols < (icol + 1):
                self.table.setColumnCount(ncols+1)

            self.col_last_keys_show = icol
            self.col_current += 1

            # Plot the header
            item = QtWidgets.QTableWidgetItem('Datakeys')
            item.__counter__ = self.counter
            item.__numrows__ = len(data_table_keys_new)
            item.setBackground(QtGui.QBrush(QtGui.QColor("lightblue")))
            self.table.setItem(0, icol, item)
            # Plot the datakeys
            ds = None
            for irow in range(self.table.rowCount()):
                if irow < len(data_table_keys_new):
                    dk = data_table_keys_new[irow]
                    ds = data_table_datastreams_new[irow]
                else:
                    dk = ''

                dkstr = str(dk)  # Here one could do some formatting
                # Metadata
                if self.redvypr is not None and self.config.show_unit:
                    metadata = self.redvypr.get_metadata(ds)
                    try:
                        unit = " / {}".format(metadata['unit'])
                        dkstr += unit
                    except:
                        pass

                item = QtWidgets.QTableWidgetItem(dkstr)
                item.__counter__ = self.counter
                item.__datastream__ = ds
                item.__datakey__ = dk
                self.table.setItem(irow+self.numrows_header,icol,item)

        # Plot data
        if True:
            icol = self.col_current
            ncols = self.table.columnCount()
            if ncols < (icol + 1):
                self.table.setColumnCount(ncols + 1)
            self.col_current += 1
            self.col_packets_showed += 1
            item = QtWidgets.QTableWidgetItem('Data')
            item.__counter__ = self.counter
            item.__numrows__ = len(data_table)
            item.setBackground(QtGui.QBrush(QtGui.QColor("lightgrey")))
            self.table.setItem(0, icol, item)
            datastream_show_tmp = None
            datakey_show_tmp = None
            for irow in range(self.table.rowCount()):
                if irow < len(data_table):
                    data_item = data_table[irow]
                    datastream_show_tmp = self.data_table_datastreams_show[irow]
                    datakey_show_tmp = self.data_table_keys_show[irow]
                    format_show = '{}'
                    for format_addressstr in self.config.formats:
                        format_address = RedvyprAddress(format_addressstr)
                        #print("format_address",format_address)
                        #print("datastream_show_tmp",datastream_show_tmp)
                        try:
                            data_tmp = format_address(datastream_show_tmp)
                        except:
                            data_tmp = None
                        if data_tmp is not None:
                            format_show = self.config.formats[format_addressstr]
                            break

                    # data_str = str(data_item)
                    # Convert the data into a string
                    if format_show == 'ISO8601':
                        dt_object = datetime.datetime.fromtimestamp(data_item, pytz.utc)
                        data_str = dt_object.isoformat()
                    else:
                        try:
                            data_str = format_show.format(data_item)
                        except:
                            logger.warning('Could not apply format str "" for address: {}'.format(format_show,
                                                                                              format_addressstr),
                                       exc_info=True)
                else:
                    data_str = ''

                item = QtWidgets.QTableWidgetItem(data_str)
                item.__counter__ = self.counter
                item.__data__ = data_item
                item.__datastream__ = datastream_show_tmp
                item.__datakey__ = datakey_show_tmp
                self.table.setItem(irow+self.numrows_header, icol, item)

        # TODO, here should be better a user resize be possible
        self.table.resizeColumnsToContents()


