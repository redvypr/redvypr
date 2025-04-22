import copy
import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import serial
import serial.tools.list_ports
import logging
import sys
import threading
import pydantic
import typing
from redvypr.data_packets import check_for_command, create_datadict
from redvypr.device import RedvyprDevice
import redvypr.files as redvypr_files

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.manual')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Allows to send data manually'
    gui_icon: str = 'mdi.serial-port'


def start(*args,**kwargs):
    return

class RedvyprDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        self.device   = device


        self.sendbutton = QtWidgets.QPushButton("Send")
        self.sendbutton.clicked.connect(self.send_clicked)
        self.datakey_edit = QtWidgets.QLineEdit()
        self.datakey_edit.setText('comment')
        self.comment_edit = QtWidgets.QLineEdit()
        self.comment_edit.setText('Some manual comment')

        self.date_edit = QtWidgets.QDateTimeEdit()
        try:
            self.date_edit.setDateTime(datetime.datetime.now())
            timeformat = 'dd.MM.yyyy HH:MM:ss'
            self.date_edit.setDisplayFormat(timeformat)
        except:
            logger.info('Could net setup date',exc_info=True)
        self.datakey_date_edit = QtWidgets.QLineEdit()
        self.datakey_date_edit.setText('t')
        # Some numbers
        self.datakey_number_edit = QtWidgets.QLineEdit()
        self.datakey_number_edit.setText('data')
        self.number_edit = QtWidgets.QDoubleSpinBox()

        layout.addWidget(QtWidgets.QLabel("Datakey"),0,0)
        layout.addWidget(QtWidgets.QLabel("Data"),0,2)
        layout.addWidget(self.datakey_edit,layout.rowCount()+1,0,1,2)
        layout.addWidget(self.comment_edit,layout.rowCount()-1,2,1,5)
        layout.addWidget(self.datakey_date_edit, layout.rowCount()+1, 0, 1, 2)
        layout.addWidget(self.date_edit, layout.rowCount()-1, 2, 1, 5)
        layout.addWidget(self.datakey_number_edit, layout.rowCount()+1, 0, 1, 2)
        layout.addWidget(self.number_edit, layout.rowCount()-1, 2, 1, 5)

        layout.addWidget(self.sendbutton,layout.rowCount()+1,0,1,-1)
        layout.setRowStretch(layout.rowCount(), 1)

    def send_clicked(self):
        funcname = __name__ + '.send_clicked()'
        logger.debug(funcname)
        data = {}
        # Add the comment
        datakey = str(self.datakey_edit.text())
        data[datakey] = str(self.comment_edit.text())
        # Add the date
        datakey = str(self.datakey_date_edit.text())
        tsend = self.date_edit.dateTime().toPyDateTime()
        data[datakey] = tsend.timestamp()

        # Add the number
        datakey = str(self.datakey_number_edit.text())
        data[datakey] = self.number_edit.value()

        logger.debug('Sending data: {}'.format(data))
        self.device.dataqueue.put(data)
