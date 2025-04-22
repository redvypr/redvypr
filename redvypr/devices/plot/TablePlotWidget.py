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
import redvypr.data_packets
import redvypr.gui
import redvypr.files as files
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket
from redvypr.data_packets import check_for_command

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.TablePlotWidget')
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)


class ConfigTablePlot(pydantic.BaseModel):
    datastreams: typing.List[typing.Union[RedvyprAddress]] = pydantic.Field(default=[RedvyprAddress('/k:["_redvypr"]["t"]'),
                                                                                     RedvyprAddress('/k:["_redvypr"]["numpacket"]'),
                                                                                     RedvyprAddress(
                                                                                         '/k:["_redvypr"]["packetid"]'),
                                                                                     RedvyprAddress('/k:*')
                                                                                     ],
                                                                                 description='The realtimedata datastreams to be displayed in the table')
    num_packets_show: int = pydantic.Field(default=2,
                                            description='The number of columns to show')
    expansion_level: int = pydantic.Field(default=100,
                                           description='The level of expansion of the datakeys')
    ignore_command_packets: bool = pydantic.Field(default=True,
                                          description='Ignore command packets')
    ignore_metadata_packets: bool = pydantic.Field(default=True,
                                                  description='Ignore metadata packets')

class TablePlotWidget(QtWidgets.QWidget):
    def __init__(self, *args, config=ConfigTablePlot(), **kwargs):
        """
        A table widget that displays data of subscribed redvypr data packets

        """
        funcname = __name__ + '.init():'
        super().__init__(*args, **kwargs)
        self.config = config
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
        self.layout.addWidget(self.table)

    def reset_table(self):
        self.col_last_keys_show = 0
        self.col_current = 0
        self.col_packets_showed = 0
        self.data_table_keys_show = []
        self.table.setColumnCount(0)
        self.table.setRowCount(0)
        self.table.clear()

    def update_data(self, data):
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

        # Ceck if the table has to be resized
        if self.col_packets_showed >= self.config.num_packets_show:
            #print('Reset')
            if self.table.columnCount() == 2:
                self.reset_table()
            counter = self.table.item(0,0).__counter__
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
                item = self.table.item(0,icol_tmp)
                numrows_tmp = max(item.__numrows__,numrows_tmp)

            self.table.setRowCount(numrows_tmp+self.numrows_header+1)

        expand_level = self.config.expansion_level
        data_table = []
        data_table_keys_new = []
        for d in self.config.datastreams:
            #print('d',d, d in rdata, rdata in d)
            if rdata in d:
                #print('d in data',d)
                datakeys = rdata.datakeys([d], expand=expand_level,return_type='list')
                # print('rdata',rdata)
                #print('expand level',expand_level)
                #print('datakeys',datakeys)
                for dk in datakeys:
                    data_tmp = rdata[dk]
                    #print('Data tmp',data_tmp)
                    data_table.append(data_tmp)
                    data_table_keys_new.append(dk)

        #print('Data keys table', data_table_keys_new)
        if self.data_table_keys_show == data_table_keys_new:
            flag_new_keys = False
        else:
            self.data_table_keys_show = data_table_keys_new
            flag_new_keys = True
            self.counter += 1

        #print('Data keys table show', self.data_table_keys_show)
        #print('Data show',data_table)
        if self.table.rowCount() < len(self.data_table_keys_show):
            self.table.setRowCount(len(self.data_table_keys_show))

        # Plot datakeys
        if flag_new_keys:
            self.data_table_keys_show = data_table_keys_new
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
            for irow in range(self.table.rowCount()):
                if irow < len(data_table_keys_new):
                    dk = data_table_keys_new[irow]
                else:
                    dk = ''

                item = QtWidgets.QTableWidgetItem(str(dk))
                item.__counter__ = self.counter
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
            for irow in range(self.table.rowCount()):
                if irow < len(data_table):
                    data_item = data_table[irow]
                else:
                    data_item = ''

                item = QtWidgets.QTableWidgetItem(str(data_item))
                item.__counter__ = self.counter
                self.table.setItem(irow+self.numrows_header, icol, item)

        self.table.resizeColumnsToContents()


