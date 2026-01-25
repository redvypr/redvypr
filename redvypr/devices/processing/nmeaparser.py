import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
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
logger = logging.getLogger('redvypr.device.nmeaparser')
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

class WMV_post():
    def __init__(self):
        """
        "$IIMWV,006,R,000.0,M,A*26"

        <MWV(wind_angle=Decimal('6'), reference='R', wind_speed=Decimal('0.0'), wind_speed_units='M', status='A')>
        Field descriptions:
        0) Talker
        1) ID
        2) Wind Angle, 0 to 360 degrees
        3) Reference, R = Relative, T = True
        4) Wind Speed
        5) Wind Speed Units, K/M/N: K:kmh-1, M: ms-1, N:Knots
        6) Status, A = Data Valid
        7) Checksum
        """
        self.speed_factors = {'M': 1.0, 'N': 0.51444, 'K': 0.27778}
    def __call__(self, nmea_obj):
        datadict = {}
        try:
            wind_angle = float(nmea_obj.wind_angle)
        except:
            wind_angle = np.nan
        datadict['wind_angle'] = wind_angle

        try:
            wind_speed = float(nmea_obj.wind_speed)
        except:
            wind_speed = np.nan
        datadict['wind_speed'] = self.speed_ms(wind_speed,nmea_obj.wind_speed_units)

        return datadict
    def speed_ms(self,speed, unit) -> float:
        return speed * self.speed_factors.get(unit, 1.0)

    def metadata(self, baseaddress=None):
        """

        Returns
        -------

        """
        if baseaddress is None:
            baseaddrstr = ''
        else:
            baseaddrstr = baseaddress.to_address_string()
        metadict = {}
        metadict[f'wind_angle{baseaddrstr}'] = {'unit':'deg','description': 'Wind Angle, 0 to 360 degrees'}
        metadict[f'wind_speed{baseaddrstr}'] = {'unit':'ms-1','description': 'Wind Speed'}
        return metadict
# Here Postprocessing of registered talker are defined
class NMEAPostprocess():
    def __init__(self):
        self.sentence_types = {}
        self.sentence_types['MWV'] = WMV_post()

def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    """ 
    """
    funcname = __name__ + '.start()'

    # Some variables for status
    tstatus = time.time()

    dtstatus = config['dt_status']

    #
    nmea_postprocess = NMEAPostprocess()
    nmea_metadata = {} # Dictionary with metadata entries
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
            if (type(dataparse) == str) and (len(dataparse) > 2) and (dataparse.startswith("$")):
                #print(f'Parsing data at datakey {datakey}:')
                #print(f"dataparse:{dataparse}")
                try:
                    msg = pynmea2.parse(dataparse)
                    talker = msg.talker
                    sentence_type = msg.sentence_type
                    daddr = redvypr.RedvyprAddress(data)
                    #print(f"daddr:{daddr}")
                    devname = 'nmeaparser' + '_' + daddr.packetid
                    packetid = f'nmea_{sentence_type}'
                    if sentence_type in nmea_postprocess.sentence_types.keys():
                        #print(f"Postprocessing:{sentence_type=}")
                        data_parsed = nmea_postprocess.sentence_types[sentence_type](msg)
                        raddr = redvypr.RedvyprAddress(device=devname, packetid=packetid)
                        data_packet = raddr.to_redvypr_dict()
                        data_packet.update(data_parsed)
                        #print(f"Data packet:{data_packet}")
                        dataqueue.put(data_packet)
                        # Test if we have to send metadata (if not done already)
                        if sentence_type not in nmea_metadata:
                            metadata = nmea_postprocess.sentence_types[
                                sentence_type].metadata(baseaddress=raddr)
                            metadata_packet = redvypr.data_packets.create_metadatapacket(
                                metadata)
                            #print("Metadata",metadata_packet)
                            dataqueue.put(metadata_packet)
                            nmea_metadata[sentence_type] = metadata_packet
                    else:
                        data_parsed = redvypr.data_packets.create_datadict(data=msg.talker, datakey='talker', device=devname)
                        data_parsed['sentence_type'] = sentence_type

                        for field in msg.fields:
                            field_short = field[1]
                            field_descr = field[0]
                            field_data = getattr(msg, field_short)
                            if isinstance(field_data, pynmea2.Decimal):
                                field_data = float(field_data)
                            data_parsed[field_short] = field_data

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


