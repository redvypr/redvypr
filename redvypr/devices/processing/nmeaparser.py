import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import sys
import redvypr.utils.csv2dict as csv2dict
import copy
import redvypr.data_packets as data_packets
from redvypr.device import redvypr_device
from redvypr.data_packets import check_for_command



logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('nmeaparser')
logger.setLevel(logging.DEBUG)

description = 'Parses NMEA data strings'

config_template = {}
config_template['name']              = 'nmeaparser'
config_template['messages']          = {'type':'list','default':[]}
config_template['datakey']           = {'type':'str','default':'data'}
config_template['redvypr_device']    = {}
config_template['redvypr_device']['publish']   = True
config_template['redvypr_device']['subscribe'] = True
config_template['redvypr_device']['description'] = description


def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    """ 
    """
    funcname = __name__ + '.start()'

    # Some variables for status
    tstatus = time.time()

    print('Hallo, start!', config)
    NMEA_definitions = csv2dict.NMEA_definitions
    NMEA_definitions_process = []
    for NMEA_message in NMEA_definitions:
        for message in config['messages']:
            print('message',message,config['messages'])
            if message in NMEA_message['name']:
                NMEA_definitions_process.append(NMEA_message)

    print('Version {:s}'.format(csv2dict.__version__))
    csv = csv2dict.csv2dict()
    csv.add_csvdefinition(csv2dict.NMEA_definitions)
    csv.print_definitions()

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
            if command == 'stop':
                print('Got a stop command')
                break

        #print('Data',data)
        # Check if the datakey is in the datapacket
        if config['datakey'] in data.keys():
            csvdata = data['data']
            dicts = csv.parse_data(csvdata)
            for packet in dicts: # Loop over the list and make a packet out of it
                print('packet',packet)
                try:
                    devicename = packet['deviceid']
                except:
                    devicename = packet['name']
                data_packets.treat_datadict(packet, devicename, hostinfo=data['_redvypr']['host'], numpacket = data['_redvypr']['numpacket'], tpacket=data['t'])
                print('Putting',packet)
                dataqueue.put(packet)

            #print(dicts)

    print('Hallo, stop!')



class initDeviceWidget(QtWidgets.QWidget):
    connect = QtCore.pyqtSignal(
        redvypr_device)  # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        self.device   = device

        print('Version {:s}'.format(csv2dict.__version__))
        self.csv = csv2dict.csv2dict()
        # Adding NMEA definitions
        self.csv.add_csvdefinition(copy.deepcopy(csv2dict.NMEA_definitions))
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

        for i,NMEA_message in enumerate(csv2dict.NMEA_definitions):
            name = NMEA_message['name']
            item = QtWidgets.QListWidgetItem(name)
            #item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            item.setCheckState(QtCore.Qt.Checked)
            item.NMEA_message = NMEA_message
            self.messagelist.addItem(item)


    def start_clicked(self):
        button = self.sender()
        print('start utton',button.isChecked())
        if button.isChecked():
            logger.debug("button pressed")
            NMEA_messages = []
            for i in range(self.messagelist.count()):
                item = self.messagelist.item(i)
                if item.checkState():
                    print(i, "is checked")
                    NMEA_messages.append(item.NMEA_message['name'])

            print(NMEA_messages)
            self.device.config['messages'].data.extend(NMEA_messages)
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
        thread_status = status['thread_status']
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


