import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import sys
import pynmea2
import pydantic
import typing
import copy

import redvypr.data_packets
import redvypr.data_packets as data_packets
from redvypr.device import RedvyprDevice
from redvypr.data_packets import check_for_command



logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('nmeaparser')
logger.setLevel(logging.DEBUG)

description = 'Parses NMEA data strings'

redvypr_devicemodule = True
class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = 'NMEA0183 parsing device'

class DeviceCustomConfig(pydantic.BaseModel):
    dt_status: float = 2.0
    messages:list = pydantic.Field(default=[])
    datakey: str = pydantic.Field(default='',description='The datakey to look for NMEA data, if empty scan all fields and use the first match')

def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    """ 
    """
    funcname = __name__ + '.start()'

    # Some variables for status
    tstatus = time.time()

    dtstatus = config['dt_status']

    #
    npackets = 0  # Number packets received
    while True:
        data = datainqueue.get()
        command = check_for_command(data)
        if(command is not None):
            if command == 'stop':
                logger.debug('Got a stop command, stopping thread')
                break

        #print('Data',data)
        # Check if the datakey is in the datapacket
        if len(config['datakey']) == 0:
            datakeys = redvypr.data_packets.Datapacket(data).datakeys()
        else:
            if config['datakey'] in data.keys():
                datakeys = [config['datakey']]
            else:
                datakeys = []

        for datakey in datakeys:
            dataparse = data[datakey]
            if (type(dataparse) == bytes):
                try:
                    dataparse = dataparse.decode('UTF-8')
                except:
                    logger.debug(funcname + ' Could not decode:',exc_info=True)
                    continue
            if (type(dataparse) == str) and (len(dataparse) > 2):
                print('Parsing data at datakey {}:{}'.format(datakey,dataparse))

                try:
                    msg = pynmea2.parse(dataparse)
                    talker = msg.talker
                    sentence_type = msg.sentence_type
                    daddr = redvypr.RedvyprAddress(data)
                    devname = sentence_type + '_' + daddr.devicename
                    print('Devicename', daddr.devicename)
                    data_parsed = redvypr.data_packets.create_datadict(data=msg.talker, datakey='talker', device=devname)
                    data_parsed['sentence_type'] = sentence_type
                    #attr = dir(msg)
                    #for a in attr:
                    #    d = getattr(msg,a)
                    #    #print('da',a,d)
                    #    if not(a.startswith('_')):
                    #        if(type(d) == float) or (type(d) == int) or (type(d) == str) or (type(d) == bool):
                    #            data_parsed[a] = d
                    for field in msg.fields:
                        field_short = field[1]
                        field_descr = field[0]
                        data_parsed[field_short] = getattr(msg,field_short)

                    print('Parsing of type {} suceeded:{}'.format(sentence_type,msg))
                    #print('Longitude',msg.longitude,msg.latitude)
                    print('Data parsed',data_parsed)
                    print('----Done-----')
                    dataqueue.put(data_parsed)
                    #if msgtype == 'GGA':
                    #    #tGGA = msg.timestamp
                    #    data_parsed = redvypr.data_packets.datapacket(data = msg.longitude, datakey='lon',device = devname)
                    #    data_parsed['latitude'] = msg.latitude
                    #    dataqueue.put(data_parsed)
                except:
                    logger.debug('NMEA Parsing failed:', exc_info=True)





class initDeviceWidget(QtWidgets.QWidget):
    connect = QtCore.pyqtSignal(
        RedvyprDevice)  # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        self.device   = device

        self.messagelist = QtWidgets.QListWidget()
        self.sub_button = QtWidgets.QPushButton('Subscribe')
        self.sub_button.clicked.connect(self.subscribe_clicked)
        self.start_button = QtWidgets.QPushButton('Start')
        self.start_button.clicked.connect(self.start_clicked)
        self.start_button.setCheckable(True)
        layout.addWidget(self.messagelist)
        layout.addWidget(self.sub_button)
        layout.addWidget(self.start_button)
        self.config_widgets = []
        self.config_widgets.append(self.sub_button)
        self.config_widgets.append(self.messagelist)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

        for i,NMEA_message in enumerate(['GGA','VTG']):
            item = QtWidgets.QListWidgetItem(NMEA_message)
            #item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            item.setCheckState(QtCore.Qt.Checked)
            self.messagelist.addItem(item)


    def start_clicked(self):
        button = self.sender()
        print('start utton',button.isChecked())
        if button.isChecked():
            logger.debug("button pressed")
            button.setText('Starting')
            self.device.thread_start()
            #self.start_button.setChecked(True)
            # self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            # button.setText('Stopping')
            #self.start_button.setChecked(False)
            self.device.thread_stop()

    def subscribe_clicked(self):
        funcname = __name__ + '.subscribe_clicked()'
        print(funcname)
        self.connect.emit(self.device)

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']
        # Running
        if (thread_status):
            self.start_button.setText('Stop')
            self.start_button.setChecked(True)
            for w in self.config_widgets:
                w.setEnabled(False)
        # Not running
        else:
            self.start_button.setText('Start')
            for w in self.config_widgets:
                w.setEnabled(True)

            # Check if an error occured and the startbutton
            if (self.start_button.isChecked()):
                self.start_button.setChecked(False)
            # self.conbtn.setEnabled(True)


