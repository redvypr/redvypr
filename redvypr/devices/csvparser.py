import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import sys
from redvypr.device import redvypr_device
from redvypr.data_packets import check_for_command

import csv2dict

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('csvparser')
logger.setLevel(logging.DEBUG)

description = 'Parses comma separated values (csv)'


def start(dataqueue, datainqueue, statusqueue, config=None):
    """ zeromq receiving data
    """
    funcname = __name__ + '.start()'

    # Some variables for status
    tstatus = time.time()
    try:
        dtstatus = config['dtstatus']
    except:
        dtstatus = 2  # Send a status message every dtstatus seconds

    #
    npackets = 0  # Number packets received
    while True:
        data = datainqueue.get()
        command = check_for_command(data)
        if(command is not None):
            print('Got a command',command)
            break

        print('Data',data)


class Device(redvypr_device):
    def __init__(self, **kwargs):
        """
        """
        super(Device, self).__init__(**kwargs)
        self.publish     = True
        self.subscribe   = True
        self.description = 'csvparser'
        self.thread_communication = self.datainqueue # Change the commandqueue to the datainqueue

    def start(self):
        print('Start')



class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device)
    device_stop = QtCore.pyqtSignal(Device)

    def __init__(self, device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        self.device = device
        self.label = QtWidgets.QLabel("csv parser setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')

        self.editwidget = []  # A list of all widgets that are editable and need to be enabled/disabled
        self.startbtn = QtWidgets.QPushButton("Start data")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)

        layout.addWidget(self.label, 0, 0)
        layout.addWidget(self.startbtn, 1, 0)

    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            self.device_start.emit(self.device)
            button.setText("Starting")

            for e in self.editwidget:
                e.setEnabled(False)
        else:
            button.setText("Stopping")
            self.device_stop.emit(self.device)
            # self.conbtn.setEnabled(True)

    def thread_status(self, status):
        """ This function is called by redvypr whenever the thread is started/stopped
        """
        self.update_buttons(status['threadalive'])

    def update_buttons(self, thread_status):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """
        if (thread_status):
            self.startbtn.setText('Stop logging')
            self.startbtn.setChecked(True)
            # self.conbtn.setEnabled(False)
        else:
            self.startbtn.setText('Start logging')
            self.startbtn.setChecked(False)
            for e in self.editwidget:
                e.setEnabled(True)
            # self.conbtn.setEnabled(True)


class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QVBoxLayout(self)

    def update(self, data):
        try:
            self.lcd.display(0)
        except:
            self.lcd.display(1)
