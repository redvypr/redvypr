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
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
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
    subscribes: bool = True
    description: str = 'NMEA0183 parsing device'

class DeviceCustomConfig(pydantic.BaseModel):
    dt_status: float = 2.0
    messages:list = pydantic.Field(default=[])
    datakey: str = pydantic.Field(default='',description='The datakey to look for NMEA data, if empty scan all fields and use the first match')

class LatLon_post():
    def __init__(self):
        """ Generic class for GGA,RMC packets """
    def __call__(self, nmea_obj):
        datadict = {}
        if len(nmea_obj.lat) == 0:
            datadict['lat'] = np.nan
            datadict['lon'] = np.nan
        else:
            try:
                lat = float(nmea_obj.latitude)
            except:
                lat = np.nan
            datadict['lat'] = lat

            try:
                lon = float(nmea_obj.longitude)
            except:
                lon = np.nan
            datadict['lon'] = lon

        if hasattr(nmea_obj, "timestamp"):
            td = nmea_obj.timestamp
            #print(f"Timestamp:{td}")
            datadict['timestamp'] = td
        if hasattr(nmea_obj,"datetime"):
            td = nmea_obj.datetime
            #print(f"Time/Date:{td}")
            datadict['datetime'] = td
            datadict['t'] = td.timestamp()

        return datadict

    def speed_ms(self,speed, unit) -> float:
        return speed * self.speed_factors.get(unit, 1.0)

    def metadata(self, baseaddress=None):
        """ Creates a metadata dict for the packet type """
        if baseaddress is None:
            baseaddrstr = ''
        else:
            baseaddrstr = baseaddress.to_address_string()
        metadict = {}
        metadict[f'lat{baseaddrstr}'] = {'unit':'deg','description': 'Latitude'}
        metadict[f'lon{baseaddrstr}'] = {'unit':'deg','description': 'Longitude'}
        return metadict

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
        """ Creates a metadata dict for the packet type """
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
        self.sentence_types['GGA'] = LatLon_post()
        self.sentence_types['RMC'] = LatLon_post()

def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    """ 
    """
    funcname = __name__ + '.start()'

    # Some variables for status
    dt_update = config['dt_status']  # Update interval in seconds
    t_update = time.time() - dt_update
    #
    nmea_postprocess = NMEAPostprocess()
    nmea_metadata = {} # Dictionary with metadata entries
    nmea_status = {}
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
                    #print(f"msg parsed:",msg)
                    talker = msg.talker
                    sentence_type = msg.sentence_type
                    daddr = redvypr.RedvyprAddress(data)
                    devname = 'nmeaparser' + '_' + daddr.packetid
                    packetid = f'nmea_{sentence_type}'
                    status_indexname = f"{sentence_type}_{daddr.packetid}"
                    # Update the status
                    try:
                        nmea_status[status_indexname]['packets_read'] += 1
                    except:
                        nmea_status[status_indexname] = {'packets_read': 1,
                                                         'sentence_type': sentence_type,
                                                         'packetid_publisher': daddr.packetid,
                                                         'packets_published': 0}
                    #print(f"daddr:{daddr}")

                    # Check for post processing
                    if sentence_type in nmea_postprocess.sentence_types.keys():
                        print(f"Postprocessing:{sentence_type=}")
                        data_parsed = nmea_postprocess.sentence_types[sentence_type](msg)
                        raddr = redvypr.RedvyprAddress(device=devname, packetid=packetid)
                        data_packet = raddr.to_redvypr_dict()
                        # Copy time, TODO: This should be able by the API
                        data_packet['_redvypr']['t'] = data['_redvypr']['t']
                        data_packet.update(data_parsed)
                        #print(f"Data packet:{data_packet}")
                        dataqueue.put(data_packet)
                        # Test if we have to send metadata (if not done already)
                        if sentence_type not in nmea_metadata:
                            metadata = nmea_postprocess.sentence_types[
                                sentence_type].metadata(baseaddress=raddr)
                            metadata_packet = redvypr.data_packets.create_metadatapacket(
                                metadata)
                            print("Metadata post processing",metadata_packet)
                            dataqueue.put(metadata_packet)
                            nmea_status[status_indexname]['packets_published'] += 1
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

                        # Copy time, TODO: This should be able by the API
                        data_parsed['_redvypr']['t'] = data['_redvypr']['t']
                        #print('Parsing of type {} suceeded:{}'.format(sentence_type,msg))
                        #print('Longitude',msg.longitude,msg.latitude)
                        #print('Data parsed',data_parsed)
                        #print('----Done-----')

                        dataqueue.put(data_parsed)
                        nmea_status[status_indexname]['packets_published'] += 1
                except:
                    logger.debug('NMEA Parsing failed:', exc_info=True)

        if ( (time.time() - t_update) > dt_update ):
            t_update = time.time()
            #print(f"NMEA status:{nmea_status}")
            statusqueue.put(nmea_status)


class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.statustable = QtWidgets.QTableWidget()
        self.statustable.setRowCount(1)
        self._statustableheader = ['Sentence type', 'Num packets read', 'Device']
        self.statustable.setColumnCount(len(self._statustableheader))
        self.statustable.setHorizontalHeaderLabels(self._statustableheader)
        self.layout.addWidget(self.statustable)
        self.device.thread_started.connect(self.thread_start_signal)
        self.statustimer_db = QtCore.QTimer()
        self.statustimer_db.timeout.connect(self.update_status)

    def thread_start_signal(self):
        print("Thread started, starting statustimer")
        self.statustimer_db.start(500)

    def update_status(self):
        status = self.device.get_thread_status()
        thread_status = status['thread_running']
        # Running
        if (thread_status):
            pass
        # Not running
        else:
            #print("Thread not running anymore, stopping timer")
            self.statustimer_db.stop()

        try:
            data = self.device.statusqueue.get(block=False)
            print(" Got status data", data)
        except:
            data = None

        if data is not None:
            try:
                # Wir gehen durch jeden Key (z.B. 'GSA_COM3') im Dictionary
                for key, info in data.items():
                    sentence = str(info.get('sentence_type', ''))
                    packets = str(info.get('packets_read', '0'))
                    device = str(info.get('packetid_publisher', ''))

                    # Prüfen, ob für diesen Key bereits eine Zeile existiert
                    # Wir nutzen den Key (z.B. 'GSA_COM3') als eindeutiges Merkmal
                    row_index = -1
                    for i in range(self.statustable.rowCount()):
                        item = self.statustable.item(i,
                                                     0)  # Wir vergleichen den Sentence Type in Spalte 0
                        device_item = self.statustable.item(i,
                                                            2)  # und Device in Spalte 2
                        if item and item.text() == sentence and device_item and device_item.text() == device:
                            row_index = i
                            break

                    # Wenn nicht gefunden, neue Zeile hinzufügen
                    if row_index == -1:
                        row_index = self.statustable.rowCount()
                        # Falls die erste Zeile bei Initialisierung leer ist, nutzen wir diese
                        if row_index == 1 and self.statustable.item(0, 0) is None:
                            row_index = 0
                        else:
                            self.statustable.insertRow(row_index)

                    # Zellen befüllen/aktualisieren
                    self.statustable.setItem(row_index, 0,
                                             QtWidgets.QTableWidgetItem(sentence))
                    self.statustable.setItem(row_index, 1,
                                             QtWidgets.QTableWidgetItem(packets))
                    self.statustable.setItem(row_index, 2,
                                             QtWidgets.QTableWidgetItem(device))

            except Exception as e:
                print(f"Fehler beim Update der Tabelle: {e}")

