import copy
import numpy as np
import datetime
import pytz
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import qtawesome
import time
import logging
import sys
import pydantic
import typing
import redvypr
from redvypr.data_packets import check_for_command
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket
from .timescaledb import RedvyprTimescaleDb
from .db_writer import DBConfigWidget

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db.db_reader')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = 'Reads data into a database'
    gui_tablabel_display: str = 'db reader'

class DeviceCustomConfig(pydantic.BaseModel):
    size_packetbuffer: int = 10
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress("data"))
    dbname: str = pydantic.Field(default="postgres")
    user: str = pydantic.Field(default="postgres")
    password: str = pydantic.Field(default="password")
    host: str = pydantic.Field(default="pi5server1")
    port: int = pydantic.Field(default=5433)

def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger_thread = logging.getLogger('redvypr.device.db_reader.start')
    logger_thread.setLevel(logging.DEBUG)
    logger_thread.debug(funcname)
    dt_update = 1  # Update interval in seconds
    packets_read = 0
    packets_published = 0
    t_update = time.time() - dt_update
    print("Config",config)
    print("device_info", device_info)

    pconfig = DeviceCustomConfig(**config)
    logger_thread.info("Opening database")
    try:
        db = RedvyprTimescaleDb(dbname = pconfig.dbname,
                                user= pconfig.user,
                                password=pconfig.password,
                                host=pconfig.host,
                                port=pconfig.port)

        with db:
            print("Opened")
            # 1. Setup (gentle approach)
            db.identify_and_setup()
            status = db.check_health()

            print(f"--- Database Health Check ---")
            print(f"Engine:  {status['engine']} (Timescale: {status['is_timescale']})")
            print(f"Tables:  {'✅ Found' if status['tables_exist'] else '❌ Missing'}")
            print(f"Write:   {'✅ Permitted' if status['can_write'] else '❌ Denied'}")
            print(f"-----------------------------")

            db_info = db.get_database_info()
            statistics = {}
            packets_read_buffer = []
            print("Number of measurements", db_info["measurement_count"])
            ntotal = db_info["measurement_count"]
            nchunk = 100
            ind_read = 0
            t_packet_old = 0  # Time of the last sent packet
            t_packet = 0  # Time of the last sent packet
            t_thread_sent = 0  # Time of the last sent packet
            t_thread_now = 0  # Time of the last sent packet
            data_send = None

            while True:
                try:
                    datapacket = datainqueue.get(block=False)
                except:
                    datapacket = None
                    time.sleep(0.5)
                # print("Got data",datapacket)
                if datapacket is not None:
                    [command, comdata] = check_for_command(datapacket,
                                                           thread_uuid=device_info[
                                                               'thread_uuid'],
                                                           add_data=True)
                    if command is not None:
                        paddr = RedvyprAddress(datapacket)
                        packetid = paddr.packetid
                        publisher = paddr.publisher
                        device = paddr.device
                        logger.debug(
                            'Command is for me: {:s}. Packetid: {}, device: {}, publisher: {}'.format(
                                str(command), packetid, device, publisher))
                        if command == 'stop':
                            logger.info(funcname + 'received command:' + str(
                                datapacket) + ' stopping now')
                            logger.debug('Stop command')
                            return
                        elif command == 'info' and packetid == 'metadata':
                            print("Info command", datapacket.keys())
                else:
                    # Check if we have to fill the packetbuffer again
                    if len(packets_read_buffer) < int(nchunk / 10):
                        print("Reading packets")
                        if (ind_read + nchunk) < ntotal:
                            nread = nchunk
                        elif ind_read < (ntotal - 1):
                            nread = ntotal - ind_read
                        else:
                            print("All read")
                            return

                        print("Reading #{} packets from {}".format(nread, ind_read))
                        data = db.get_packets_range(ind_read, nread)
                        packets_read += len(data)
                        ind_read += nread
                        packets_read_buffer.extend(data)

                    if len(packets_read_buffer) > 1:
                        # t_packet_old = 0  # Time of the last sent packet
                        # t_packet = 0  # Time of the last sent packet
                        # t_thread_sent = 0  # Time of the last sent packet
                        # t_thread_now = 0  # Time of the last sent packet
                        if data_send is None:
                            data_send = packets_read_buffer.pop(0)
                            # print("Data send",data_send)
                            id_send = data_send["id"]
                            t_packet = data_send["timestamp"]
                            t_packet_unix = t_packet.timestamp()
                            packet_send = data_send["data"]

                        t_thread_now = time.time()
                        dt_packet = t_packet_unix - t_packet_old
                        dt_thread = t_thread_now - t_thread_sent
                        # print("dt", dt_packet, dt_thread)
                        if dt_thread >= dt_packet:
                            print("Sending", id_send, t_packet)
                            packets_published += 1
                            t_thread_sent = t_thread_now
                            t_packet_old = t_packet_unix
                            dataqueue.put(packet_send)
                            data_send = None

                if ((time.time() - t_update) > dt_update):
                    t_update = time.time()
                    print("Updating", packets_read, packets_published)
                    data = {}
                    data['t'] = time.time()
                    data['packets_read'] = packets_read
                    data['packets_published'] = packets_published
                    data['statistics'] = statistics
                    statusqueue.put(data)
    except:
        logger_thread.exception("Could not connect to database")
        return
    finally:
        logger_thread.info("Thread shutting down, connection cleaned up.")










class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.statistics = {}
        self._statistics_items = {}
        initial_config = self.device.custom_config
        # 2. Create the new DBConfigWidget
        self.db_config_widget = DBConfigWidget(initial_config=initial_config)
        self.statustable = QtWidgets.QTableWidget()
        self.statustable.setRowCount(1)
        self._statustableheader = ['Packets','Packets read','Packets published']
        self.statustable.setColumnCount(len(self._statustableheader))
        self.statustable.setHorizontalHeaderLabels(self._statustableheader)
        item = QtWidgets.QTableWidgetItem("All")
        self.statustable.setItem(0, 0, item)
        self.statustable.resizeColumnsToContents()

        # 3. Add the DBConfigWidget to the main content area (self.layout)
        # We add it at the top of the 'self.widget' (main content area)
        self.layout.addWidget(self.db_config_widget)
        self.layout.addWidget(self.statustable)
        self.layout.addStretch(1)  # Push the DB widget to the top

        self.statustimer_db = QtCore.QTimer()
        self.statustimer_db.timeout.connect(self.update_status)


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
                item_read = QtWidgets.QTableWidgetItem(str(data['packets_read']))
                item_published = QtWidgets.QTableWidgetItem(
                    str(data['packets_published']))
                self.statistics.update(data['statistics'])
                #print("Statistics",self.statistics)
                self.statustable.setItem(0,1,item_read)
                self.statustable.setItem(0, 2, item_published)
                for row,(k, i) in enumerate(self.statistics.items()):
                    #print("k",k)
                    #print("i", i)
                    k_mod = RedvyprAddress(k).to_address_string(["i","p","h","d"])
                    try:
                        item_read = self._statistics_items[k][1]
                        item_published = self._statistics_items[k][2]
                        istr = str(i['packets_read'])
                        item_read.setText(istr)
                    except:
                        logger.info("Could not get data",exc_info=True)
                        item_addr = QtWidgets.QTableWidgetItem(k_mod)
                        item_read = QtWidgets.QTableWidgetItem(str(i['packets_read']))
                        item_published = QtWidgets.QTableWidgetItem(
                            str(i['packets_published']))
                        self._statistics_items[k] = (item_addr,item_read,item_published)
                        nrows = self.statustable.rowCount()
                        self.statustable.setRowCount(nrows + 1)
                        self.statustable.setItem(nrows, 0, item_addr)
                        self.statustable.setItem(nrows, 1, item_read)
                        self.statustable.setItem(nrows, 2, item_published)

                    #item = self._statistics_items[k]

                self.statustable.resizeColumnsToContents()
            except:
                logger.info("Could not update data",exc_info=True)


    # This is bad style, needs to be changed to thread_started signal and continous update of configuration
    def start_clicked(self):
        self.device.custom_config = self.db_config_widget.get_config()
        self.statustimer_db.start(500)
        super().start_clicked()