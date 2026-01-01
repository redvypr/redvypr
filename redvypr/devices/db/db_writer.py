from PyQt6 import QtWidgets, QtCore
import time
import logging
import sys
import pydantic
import typing
import qtawesome
from redvypr.data_packets import check_for_command
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.redvypr_address import RedvyprAddress
from .db_util_widgets import DBStatusDialog, TimescaleDbConfigWidget
from .timescaledb import RedvyprTimescaleDb, DatabaseConfig, TimescaleConfig, SqliteConfig

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db.db_writer')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = 'Writes data into a database'
    gui_tablabel_display: str = 'database status'

class DeviceCustomConfig(pydantic.BaseModel):
    database: DatabaseConfig = pydantic.Field(default_factory=TimescaleConfig, discriminator='dbtype')

def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger_thread = logging.getLogger('redvypr.device.db_writer.start')
    logger_thread.setLevel(logging.DEBUG)
    logger_thread.debug(funcname)
    dt_update = 1  # Update interval in seconds
    packet_inserted = 0
    packet_inserted_failure = 0
    t_update = time.time() - dt_update
    print("Config",config)
    print("device_info", device_info)

    device_config = DeviceCustomConfig(**config)
    dbconfig = device_config.database
    logger_thread.info("Opening database")
    try:
        db = RedvyprTimescaleDb(dbname = dbconfig.dbname,
                                user= dbconfig.user,
                                password=dbconfig.password,
                                host=dbconfig.host,
                                port=dbconfig.port)

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
            if status['tables_exist'] and status['can_write']:
                statistics = {}
                while True:
                    datapacket = datainqueue.get()
                    # print("Got data",datapacket)
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
                            metadata = datapacket["deviceinfo_all"]["metadata"]
                            print("Metadata", metadata)
                            # add_metadata(self, address: str, uuid: str, metadata_dict: dict,mode: str = "merge"):
                            for metadata_address_str, metadata_content in metadata.items():
                                print("Adding metadata", metadata_address_str)
                                metadata_address = RedvyprAddress(metadata_address_str)
                                try:
                                    uuid = metadata_address.uuid
                                except:
                                    print(
                                        "Could not get uuid from metadata, get from host")
                                    uuid = device_info["hostinfo"]["uuid"]

                                try:
                                    db.add_metadata(address=metadata_address_str, uuid=uuid,
                                                    metadata_dict=metadata_content)
                                except:
                                    logger_thread.info("Could not add metadata",exc_info=True)

                    else:  # Only save real data
                        # print('Inserting datapacket',datapacket)
                        addrstr = RedvyprAddress(datapacket).to_address_string()
                        try:
                            statistics[addrstr]
                        except:
                            statistics[addrstr] = {'packet_inserted': 0,
                                                   'packet_inserted_failure': 0}
                        try:
                            db.insert_packet(datapacket)
                            packet_inserted += 1
                            statistics[addrstr]['packet_inserted'] += 1
                        except:
                            logger_thread.info("Could not add data",exc_info=True)
                            packet_inserted_failure += 1
                            statistics[addrstr]['packet_inserted_failure'] += 1

                    if ((time.time() - t_update) > dt_update):
                        t_update = time.time()
                        # print("Updating")
                        data = {}
                        data['t'] = time.time()
                        data['packet_inserted'] = packet_inserted
                        data['packet_inserted_failure'] = packet_inserted_failure
                        data['statistics'] = statistics
                        statusqueue.put(data)

    except:
        logger_thread.exception("Could not connect to database")
        return





def get_database_info(config):
    db = RedvyprTimescaleDb(dbname=config.dbname,
                            user=config.user,
                            password=config.password,
                            host=config.host,
                            port=config.port)

    print("Opening with config",config)
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

        stats = db.get_unique_combination_stats(keys=['uuid'])
        print("Stats",stats)

        info = db.get_database_info()
        return info




class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.statistics = {}
        self._statistics_items = {}
        initial_config = self.device.custom_config
        # 2. Create the new DBConfigWidget
        self.db_config_widget = TimescaleDbConfigWidget(initial_config=initial_config.database)
        self.statustable = QtWidgets.QTableWidget()
        self.statustable.setRowCount(1)
        self._statustableheader = ['Packets','Num stored','Num stored error']
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
            #print("data", data)
        except:
            data = None

        if data is not None:
            try:
                item_inserted = QtWidgets.QTableWidgetItem(str(data['packet_inserted']))
                item_inserted_failure = QtWidgets.QTableWidgetItem(
                    str(data['packet_inserted_failure']))
                self.statistics.update(data['statistics'])
                #print("Statistics",self.statistics)
                self.statustable.setItem(0,1,item_inserted)
                self.statustable.setItem(0, 2, item_inserted_failure)
                for row,(k, i) in enumerate(self.statistics.items()):
                    #print("k",k)
                    #print("i", i)
                    k_mod = RedvyprAddress(k).to_address_string(["i","p","h","d"])
                    try:
                        item_inserted = self._statistics_items[k][1]
                        item_inserted_failure = self._statistics_items[k][2]
                        istr = str(i['packet_inserted'])
                        item_inserted.setText(istr)
                    except:
                        logger.info("Could not get data",exc_info=True)
                        item_addr = QtWidgets.QTableWidgetItem(k_mod)
                        item_inserted = QtWidgets.QTableWidgetItem(str(i['packet_inserted']))
                        item_inserted_failure = QtWidgets.QTableWidgetItem(
                            str(i['packet_inserted_failure']))
                        self._statistics_items[k] = (item_addr,item_inserted,item_inserted_failure)
                        nrows = self.statustable.rowCount()
                        self.statustable.setRowCount(nrows + 1)
                        self.statustable.setItem(nrows, 0, item_addr)
                        self.statustable.setItem(nrows, 1, item_inserted)
                        self.statustable.setItem(nrows, 2, item_inserted_failure)

                    #item = self._statistics_items[k]

                self.statustable.resizeColumnsToContents()
            except:
                logger.info("Could not update data",exc_info=True)

    # This is bad style, needs to be changed to thread_started signal and continous update of configuration
    def start_clicked(self):
        self.device.custom_config.database = self.db_config_widget.get_config()
        self.statustimer_db.start(500)
        super().start_clicked()