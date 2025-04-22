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

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.TablePlotWidget')
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)


class ConfigTablePlot(pydantic.BaseModel):
    datastreams: typing.List[typing.Union[RedvyprAddress]] = pydantic.Field(default=[RedvyprAddress('t'),
                                                                                     RedvyprAddress('/k:["_redvypr"]["numpacket"]'),
                                                                                     RedvyprAddress('/k:*')
                                                                                     ],
                                                                                 description='The realtimedata datastreams to be displayed in the table')
    num_packets_show: int = pydantic.Field(default=10,
                                            description='The number of columns to show')
    expansion_level: int = pydantic.Field(default=100,
                                           description='The level of expansion of the datakeys')

class TablePlotWidget(QtWidgets.QWidget):
    def __init__(self, *args, config=ConfigTablePlot(), **kwargs):
        """
        A table widget that displays data of subscribed redvypr data packets

        """
        funcname = __name__ + '.init():'
        super().__init__(*args, **kwargs)
        self.config = config
        self.data_table_keys_show = []
        self.layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget()
        self.layout.addWidget(self.table)

    def update_data(self, data):
        """
        """
        funcname = __name__ + '.update_data():'
        rdata = Datapacket(data)
        expand_level = self.config.expansion_level
        data_table = []
        data_table_keys_new = []
        for d in self.config.datastreams:
            print('d',d, d in rdata, rdata in d)
            if rdata in d:
                print('d in data',d)
                datakeys = rdata.datakeys([d], expand=expand_level)
                print('datakeys',datakeys)
                for dk in datakeys:
                    data_tmp = rdata[dk]
                    print('Data tmp',data_tmp)
                    data_table.append(data_tmp)
                    data_table_keys_new.append(dk)

        if self.data_table_keys_show == data_table_keys_new:
            flag_new_keys = False
        else:
            self.data_table_keys_show = data_table_keys_new
            flag_new_keys = True
        print('Data show',data_table)

        if self.table.rowCount() < len(self.data_table_keys_show):
            self.table.setRowCount(len(self.data_table_keys_show))
            self.table.setColumnCount(2)

        if flag_new_keys:
            for irow, dk in enumerate(self.data_table_keys_show):
                item = QtWidgets.QTableWidgetItem(str(dk))
                icol = 0
                self.table.setItem(irow,icol,item)
        if True:
            for irow, data_item in enumerate(data_table):
                item = QtWidgets.QTableWidgetItem(str(data_item))
                icol = 1
                self.table.setItem(irow, icol, item)


        try:
            tnow = time.time()
        except:
            pass

