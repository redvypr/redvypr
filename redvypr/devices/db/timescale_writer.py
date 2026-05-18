from PyQt6 import QtWidgets, QtCore
import time
import logging
import sys
import pydantic
import typing
import qtawesome
from redvypr.device import RedvyprDevice
from redvypr.data_packets import check_for_command, commandpacket
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple, RedvyprDeviceStartStopKillConfigWidget
from redvypr.redvypr_address import RedvyprAddress
from .db_config_util import DbConfigWidget, DbTableConfig
from .db_engine_timescale import TimescaleConfig,DbTimescaleWriter, TimescaleDbConfigWidget, TimescaleStatusTableWidget

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.db.timescale_writer')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = 'Writes data into a postgres/timescale database'
    gui_tablabel_display: str = 'database status'


initial_config = TimescaleConfig()
initial_config.write_config.name = "Timescale Writer"
raw_table = DbTableConfig(tablename="redvypr_raw",addresses=["@"],tabletype="redvypr_datapacket")
flat_table = DbTableConfig(tablename="redvypr_flat",addresses=["@"],tabletype="data_flat")
initial_config.write_config.tables["redvypr_raw"] = raw_table
initial_config.write_config.tables["redvypr_flat"] = flat_table

class DeviceCustomConfig(pydantic.BaseModel):
    auto_create_table: bool = pydantic.Field(default=True, description="Create redvypr tables automatically at start, if not existing")
    database: TimescaleConfig = pydantic.Field(default=initial_config)

def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger_thread = logging.getLogger('redvypr.device.timescale_writer.start')
    logger_thread.setLevel(logging.DEBUG)
    logger_thread.debug(funcname)
    dt_update = 1  # Update interval in seconds
    dt_update_db = 10  # Update interval in seconds
    packet_inserted = 0
    packet_inserted_failure = 0
    metadata_address_inserted = 0
    t_update = time.time() - dt_update
    t_update_db = time.time() - dt_update_db
    print("Config",config)
    print("device_info", device_info)



    device_config = DeviceCustomConfig(**config)
    dbconfig = device_config.database
    print("Database tables",dbconfig)
    addresses_subscribe = []
    for table_name, t_cfg in dbconfig.write_config.tables.items():
        for addr in t_cfg.addresses:
            addresses_subscribe.append(addr)
    logger_thread.info("Opening database")
    try:
        db = DbTimescaleWriter(config=dbconfig,mode="write")
        compacket = commandpacket("unsubscribe_all")
        dataqueue.put(compacket)
        compacket = commandpacket("subscribe",comdata=addresses_subscribe)
        #print(f"Compacket:{compacket}")
        dataqueue.put(compacket)

        statistics = {}
        while True:
            datapacket = datainqueue.get()
            #print("Got data",datapacket)
            addrstr = RedvyprAddress(datapacket).to_address_string()
            #print("Addstr",addrstr)
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
                    db.disconnect()
                    return
                # Check if there is metadata to save
                elif command == 'info' and packetid == 'metadata':
                    logger.info(f"Info command:{datapacket.keys()}")
                    metadata = datapacket["deviceinfo_all"]["metadata"]
                    #print("Metadata", metadata)
                    # add_metadata(self, address: str, uuid: str, metadata_dict: dict,mode: str = "merge"):
                    for metadata_address_str, metadata_content in metadata.items():
                        #print("Adding metadata", metadata_address_str)
                        metadata_address = RedvyprAddress(metadata_address_str)
                        try:
                            uuid = metadata_address.uuid
                        except:
                            uuid = None

                        if uuid is None:
                            print("Could not get uuid from metadata, get from host")
                            uuid = device_info["hostinfo"]["uuid"]

                        try:
                            db.add_metadata(address=metadata_address_str, uuid=uuid,
                                            metadata_dict=metadata_content)
                            metadata_address_inserted += 1
                        except:
                            logger_thread.info("Could not add metadata",exc_info=True)

            else:  # Only save real data
                #print('Inserting datapacket',datapacket)
                try:
                    statistics[addrstr]
                except:
                    statistics[addrstr] = {'packet_inserted': 0,
                                           'packet_inserted_failure': 0}
                try:
                    #print("Inserting packet")
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
                #data['filename'] = db.filepath
                #data['filesize'] = db.get_memory_usage()
                data['packet_inserted'] = packet_inserted
                data['packet_inserted_failure'] = packet_inserted_failure
                data['metadata_address_inserted'] = metadata_address_inserted
                data['statistics'] = statistics
                data['status_db'] = db.get_status()
                #print("Status data",data)
                statusqueue.put(data)
            if ((time.time() - t_update_db) > dt_update_db):
                t_update_db = time.time()
                #print("Status")
                #db_status = db.get_status()
                #statusqueue.put(db_status)
                #print("Db Status",db_status)

    except:
        logger_thread.exception("Could not connect to database")
        return





def get_database_info(config):
    db = DbTimescaleWriter(config=config)
    print("Opening with config",config)
    with db:
        print("Opened")
        # 1. Setup (gentle approach)
        db.identify_and_setup()
        status = db.identify_and_check_health()

        print(f"--- Database Health Check ---")
        print(f"Engine:  {status['engine']} (Timescale: {status['is_timescale']})")
        print(f"Tables:  {'✅ Found' if status['tables_exist'] else '❌ Missing'}")
        print(f"Write:   {'✅ Permitted' if status['can_write'] else '❌ Denied'}")
        print(f"-----------------------------")

        stats = db.get_unique_combination_stats(keys=['uuid'])
        print("Stats",stats)

        info = db.get_database_info()
        return info



class DisplayDbStatusWidgetExtended(QtWidgets.QGroupBox):
    def __init__(self, title="Database Status", parent=None):
        super().__init__(title, parent)
        # Set a reasonable maximum width so it doesn't push the splitter too far
        self.setMinimumWidth(250)
        self.setup_ui()

    def setup_ui(self):
        # 1. Main Layout for the GroupBox
        self.main_layout = QtWidgets.QVBoxLayout(self)

        # 2. Create the Scroll Area
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)  # Clean look
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        # 3. Create a Container Widget for the FormLayout
        self.content_widget = QtWidgets.QWidget()
        self.grid = QtWidgets.QFormLayout(self.content_widget)
        self.grid.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        # Set the content widget to the scroll area
        self.scroll_area.setWidget(self.content_widget)

        # 4. Add the Scroll Area to the Main Layout
        self.main_layout.addWidget(self.scroll_area)

        # Update timestamp at the bottom (outside the scroll area)
        self.last_update_label = QtWidgets.QLabel("Last update: Never")
        self.last_update_label.setStyleSheet("font-size: 10px; color: gray;")
        self.main_layout.addWidget(self.last_update_label,
                                   alignment=QtCore.Qt.AlignmentFlag.AlignRight)

    def update_status(self, status_dict: dict):
        """Clears and redraws the status rows."""
        # Clear rows
        while self.grid.count():
            child = self.grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for key, value in status_dict.items():
            display_key = key.replace("_", " ").title() + ":"
            val_label = QtWidgets.QLabel()

            # Logic for formatting (same as before)
            if key == "connection":
                val_label.setText(f"● {value}")
                color = "#27ae60" if "connected" in str(value).lower() else "#c0392b"
                val_label.setStyleSheet(f"font-weight: bold; color: {color};")
            else:
                val_label.setText(str(value))
                val_label.setStyleSheet("font-weight: bold; color: #2c3e50;")

            # Make text selectable in case users want to copy a path
            val_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

            self.grid.addRow(display_key, val_label)

        now = QtCore.QDateTime.currentDateTime().toString("hh:mm:ss")
        self.last_update_label.setText(f"Last update: {now}")



class RedvyprDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.tabwidget = QtWidgets.QTabWidget()
        self.layout.addWidget(self.tabwidget)
        self.device = device
        initial_config = self.device.custom_config
        self.device.thread_started.connect(self.thread_start_signal)
        # The database and device start/stop widget
        self.device_widget = QtWidgets.QWidget()
        self.layout_device = QtWidgets.QVBoxLayout(self.device_widget)
        self.startstop = RedvyprDeviceStartStopKillConfigWidget(device=device,
                                                                show_subscribe=False,
                                                                show_configure=False)
        print(f"Databases:{self.device.custom_config.database=}")
        self.db_config_widget = TimescaleDbConfigWidget(initial_config=self.device.custom_config.database)
        self.layout_device.addWidget(self.db_config_widget)
        self.db_config_widget.db_config_changed.connect(self.dbfile_config_changed)

        self.layout_device.addWidget(self.startstop, alignment=QtCore.Qt.AlignBottom)
        self.tabwidget.addTab(self.device_widget,'Init/Start/Stop')
        # Single datastreams
        self.writer_config_widget = DbConfigWidget(initial_config=self.device.custom_config.database.write_config,
                                                   redvypr=self.device.redvypr)
        self.writer_config_widget.config_changed.connect(self.dbwriter_config_changed)
        self.tabwidget.addTab(self.writer_config_widget, 'Writer Config')

        self.status_widget = QtWidgets.QWidget()
        self.status_widget_layout = QtWidgets.QVBoxLayout(self.status_widget)
        self.status_table = TimescaleStatusTableWidget()
        self.status_widget_layout.addWidget(self.status_table)
        self.tabwidget.addTab(self.status_widget, 'Status')

        #
        self.startstop.config_widgets.append(self.db_config_widget)
        self.startstop.config_widgets.append(self.writer_config_widget)
        #
        self.statustimer_db = QtCore.QTimer()
        self.statustimer_db.timeout.connect(self.update_status)

    def dbwriter_config_changed(self):
        new_config = self.writer_config_widget.get_config()
        self.device.custom_config.database.write_config = new_config
        print("Config changed",self.device.custom_config)#new_config)

    def dbfile_config_changed(self):
        new_file_config = self.db_config_widget.get_config()
        new_writer_config = self.writer_config_widget.get_config()
        new_file_config.write_config = new_writer_config
        self.device.custom_config.database = new_file_config
        print("DB File, Config changed", self.device.custom_config)  # new_config)

    def update_status(self):
        """Clears and redraws the status rows."""
        # Clear rows
        #print("Update")
        try:
            status = self.device.statusqueue.get_nowait()
        except:
            status = None
        if status:
            self.status_table.update_table(status)

    def thread_start_signal(self):
        print("Thread started, starting statustimer")
        self.statustimer_db.start(1000)



