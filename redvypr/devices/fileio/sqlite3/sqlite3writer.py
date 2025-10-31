from datetime import datetime, timezone
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import yaml
import pydantic
import typing
import copy
import os
import sqlite3
import json
from redvypr.device import RedvyprDevice
from redvypr.data_packets import check_for_command
from redvypr.packet_statistic import do_data_statistics, create_data_statistic_dict
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.sqlite3writer')
logger.setLevel(logging.DEBUG)


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = "Write data packets into a sqlite3 file"
    gui_icon: str = 'mdi.database-import'

class DeviceCustomConfig(pydantic.BaseModel):
    filename: str = pydantic.Field(default="testdata.rdvsql3", description='Filename')
    dt_sync: int = pydantic.Field(default=5,
                                  description='Time after which an open file is synced on disk')
    dt_newfile: int = pydantic.Field(default=3600,
                                     description='Time after which a new file is created')
    dt_newfile_unit: typing.Literal[
        'none', 'seconds', 'hours', 'days'] = pydantic.Field(default='seconds')
    dt_update: int = pydantic.Field(default=2,
                                    description='Time after which an upate is sent to the gui')
    clearqueue: bool = pydantic.Field(default=True,
                                      description='Flag if the buffer of the subscribed queue should be emptied before start')
    zlib: bool = pydantic.Field(default=True,
                                description='Flag if zlib compression shall be used for the netCDF data')
    size_newfile: int = pydantic.Field(default=500,
                                       description='Size of object in RAM after which a new file is created')
    size_newfile_unit: typing.Literal['none', 'bytes', 'kB', 'MB'] = pydantic.Field(
        default='MB')
    datafolder: str = pydantic.Field(default='.',
                                     description='Folder the data is saved to')
    fileextension: str = pydantic.Field(default='rdvsql3',
                                        description='File extension, if empty not used')
    fileprefix: str = pydantic.Field(default='redvypr', description='If empty not used')
    filepostfix: str = pydantic.Field(default='',
                                      description='If empty not used')
    filedateformat: str = pydantic.Field(default='%Y-%m-%d_%H%M%S',
                                         description='Dateformat used in the filename, must be understood by datetime.strftime')
    filecountformat: str = pydantic.Field(default='04',
                                          description='Format of the counter. Add zero if trailing zeros are wished, followed by number of digits. 04 becomes {:04d}')

redvypr_devicemodule = True


def create_logfilename(config, count=0):
    funcname = __name__ + '.create_logfilename():'
    logger.debug(funcname)

    filename = ''
    if len(config['datafolder']) > 0:
        if os.path.isdir(config['datafolder']):
            filename += config['datafolder'] + os.sep
        else:
            logger.warning(funcname + ' Data folder {:s} does not exist.'.format(filename))
            return None

    if(len(config['fileprefix'])>0):
        filename += config['fileprefix']

    if (len(config['filedateformat']) > 0):
        tstr = datetime.now().strftime(config['filedateformat'])
        filename += '_' + tstr

    if (len(config['filecountformat']) > 0):
        cstr = "{:" + config['filecountformat'] +"d}"
        filename += '_' + cstr.format(count)

    if (len(config['filepostfix']) > 0):
        filename += '_' + config['filepostfix']

    if (len(config['fileextension']) > 0):
        filename += '.' + config['fileextension']

    logger.info(funcname + ' Will create a new file: {:s}'.format(filename))

    return filename


def json_safe_dumps(obj):
    """Convert complex Redvypr packets into JSON-safe text."""
    def default(o):
        # numpy arrays → convert to Python lists
        if isinstance(o, np.ndarray):
            return o.tolist()
        # numpy scalar values (e.g. np.int64, np.float64)
        if isinstance(o, (np.generic,)):
            return o.item()
        # Handle Python 'type' objects (e.g., <class 'float'>)
        if isinstance(o, type):
            return str(o)
        # Handle datetime
        if isinstance(o, datetime):
            return o.isoformat()
        # Handle other unknown types
        return str(o)
    return json.dumps(obj, default=default, ensure_ascii=False)

class RedvyprDB:
    def __init__(self, db_file: str = "redvypr_data.db"):
        """Open a persistent connection to the SQLite database."""
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        #self.conn.execute("PRAGMA journal_mode=WAL;")  # better performance for concurrent reads/writes
        self.cursor = self.conn.cursor()
        self.file_status = 'open'
        self.init_db()

    def init_db(self):
        """Create the table if it doesn’t exist."""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS redvypr_packets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                data JSON NOT NULL
            )
        """)
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_redvypr_timestamp
            ON redvypr_packets (timestamp)
        """)
        self.conn.commit()

    def insert_packet(self, packet: dict, timestamp: str | None = None):
        """Insert a Redvypr packet with the current or provided timestamp."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        try:
            jsonstr = json_safe_dumps(packet)
            #print("Jsonstr",jsonstr)
        except:
            logger.info("Could not serialize data",exc_info=True)
            #print(packet)
            raise ValueError("Bad")

        self.cursor.execute("""
            INSERT INTO redvypr_packets (timestamp, data)
            VALUES (?, json(?))
        """, (timestamp, jsonstr))

    def commit(self):
        """Manually commit — e.g. after multiple inserts."""
        self.conn.commit()

    def get_all_packets(self):
        """Fetch all stored packets."""
        self.cursor.execute("SELECT id, timestamp, data FROM redvypr_packets ORDER BY timestamp DESC")
        return [
            {"id": row[0], "timestamp": row[1], "data": json.loads(row[2])}
            for row in self.cursor.fetchall()
        ]

    def query_by_device(self, device_id: str):
        """Example query: filter packets by device_id inside the JSON."""
        self.cursor.execute("""
            SELECT id, timestamp, data
            FROM redvypr_packets
            WHERE json_extract(data, '$.device_id') = ?
            ORDER BY timestamp DESC
        """, (device_id,))
        return [
            {"id": row[0], "timestamp": row[1], "data": json.loads(row[2])}
            for row in self.cursor.fetchall()
        ]

    def close(self):
        """Close the database connection cleanly."""
        self.file_status = 'closed'
        self.conn.commit()
        self.conn.close()

def start(device_info, config={'filename': ''}, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'
    logger_start = logging.getLogger('redvypr.device.sqlite3writer.thread')
    logger_start.setLevel(logging.DEBUG)
    funcname = __name__ + '.start()'
    logger_start.debug(funcname + ':Opening writing:')

    if True:
        try:
            dtneworig = config['dt_newfile']
            dtunit = config['dt_newfile_unit']
            if (dtunit.lower() == 'seconds'):
                dtfac = 1.0
            elif (dtunit.lower() == 'hours'):
                dtfac = 3600.0
            elif (dtunit.lower() == 'days'):
                dtfac = 86400.0
            else:
                dtfac = 0

            dtnews = dtneworig * dtfac
            logger_start.info(
                funcname + ' Will create new file every {:d} {:s}.'.format(
                    config['dt_newfile'], config['dt_newfile_unit']))
        except:
            logger.debug("Configuration incomplete", exc_info=True)
            dtnews = 0

        try:
            sizeneworig = config['size_newfile']
            sizeunit = config['size_newfile_unit']
            if (sizeunit.lower() == 'kb'):
                sizefac = 1000.0
            elif (sizeunit.lower() == 'mb'):
                sizefac = 1e6
            elif (sizeunit.lower() == 'bytes'):
                sizefac = 1
            else:
                sizefac = 0

            sizenewb = sizeneworig * sizefac  # Size in bytes
            logger_start.info(
                funcname + ' Will create new file every {:d} {:s}.'.format(
                    config['size_newfile'], config['size_newfile_unit']))
        except:
            logger.debug("Configuration incomplete", exc_info=True)
            sizenewb = 0  # Size in bytes

    try:
        config['dt_sync']
    except:
        config['dt_sync'] = 5

    t_last = time.time()
    count = 0
    packets_written = 0
    statistics = create_data_statistic_dict()
    flag_new_file = True
    tfile = time.time()  # Save the time the file was created
    tupdate = time.time()
    numpackets_tmp = 0
    while True:
        tcheck = time.time()

        if flag_new_file:
            filename = create_logfilename(config, count)
            logger_start.debug("Opening new file:{}".format(filename))
            count += 1
            # Create the database file
            db = RedvyprDB(filename)
            tfile = time.time()
            flag_new_file = False
            bytes_written = 0
            packets_written = 0
            data_stat = {'_deviceinfo': {}}
            data_stat['_deviceinfo']['filename'] = filename
            data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
            data_stat['_deviceinfo']['created'] = time.time()
            data_stat['_deviceinfo']['bytes_written'] = bytes_written
            data_stat['_deviceinfo']['packets_written'] = packets_written
            statusqueue.put(data_stat)

        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if (data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            # logger.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                sstr = funcname + ': Command is for me: {:s}'.format(str(command))
                logger.debug(sstr)
                if command == 'stop':
                    logger.debug('Stopping')
                    db.close()
                    data_stat = {'_deviceinfo': {}}
                    data_stat['_deviceinfo']['filename'] = filename
                    data_stat['_deviceinfo']['filename_full'] = os.path.realpath(
                        filename)
                    data_stat['_deviceinfo']['closed'] = time.time()
                    data_stat['_deviceinfo']['bytes_written'] = bytes_written
                    data_stat['_deviceinfo']['packets_written'] = packets_written
                    statusqueue.put(data_stat)
                    #dataqueue.put(data_stat)
                    break
            else:
                numpackets_tmp += 1

            unix_time = data['_redvypr']['t']
            timestamp = datetime.fromtimestamp(unix_time, tz=timezone.utc).isoformat()




            # print("Inserting packet")
            db.insert_packet(data,timestamp)
            packets_written += 1
            bytes_written = os.path.getsize(filename)
            print("Packets written",packets_written,"bytes written",bytes_written)

        if (time.time() - tupdate) > config['dt_sync']:
            packets_per_second = numpackets_tmp / (time.time() - t_last)
            t_last = time.time()
            print("packets per second", packets_per_second)
            numpackets_tmp = 0
            tupdate = time.time()
            if db.file_status == 'open':
                db.commit()
                data_stat = {'_deviceinfo': {}}
                data_stat['_deviceinfo']['filename'] = filename
                data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
                data_stat['_deviceinfo']['created'] = time.time()
                data_stat['_deviceinfo']['bytes_written'] = bytes_written
                data_stat['_deviceinfo']['packets_written'] = packets_written
                statusqueue.put(data_stat)

        if True:  # Check if a new file should be created, close the old one and write the header
            file_age = tcheck - tfile
            FLAG_TIME = (dtnews > 0) and (file_age >= dtnews)
            FLAG_SIZE = (sizenewb > 0) and (bytes_written >= sizenewb)
            if FLAG_TIME or FLAG_SIZE and (db.file_status == 'open'):
                db.close()
                flag_new_file = True
                data_stat = {'_deviceinfo': {}}
                data_stat['_deviceinfo']['filename'] = filename
                data_stat['_deviceinfo']['filename_full'] = os.path.realpath(filename)
                data_stat['_deviceinfo']['closed'] = time.time()
                data_stat['_deviceinfo']['bytes_written'] = bytes_written
                data_stat['_deviceinfo']['packets_written'] = packets_written
                statusqueue.put(data_stat)


        time.sleep(0.1)


#
#
# The init widget
#
#

class DeviceConfigWidget(QtWidgets.QWidget):
    connect = QtCore.pyqtSignal(
        RedvyprDevice)  # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices

    def __init__(self, *args, device=None, mainwindow=None, **kwargs):
        super().__init__(*args, **kwargs)
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        # print('Hallo,device config',device.config)
        self.device = device
        self.redvypr = device.redvypr
        self.label = QtWidgets.QLabel("Sqlite3 logger setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')
        self.config_widgets = []  # A list of all widgets that can only be used of the device is not started yet
        # Input output widget
        self.inlabel = QtWidgets.QLabel("Input")
        self.inlist = QtWidgets.QListWidget()
        #
        self.adddeviceinbtn = QtWidgets.QPushButton("Subscribe")
        self.adddeviceinbtn.clicked.connect(mainwindow.subscribe_clicked)

        self.adddeviceinbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                                          QtWidgets.QSizePolicy.Expanding)
        # The output widgets
        self.outlabel = QtWidgets.QLabel("Logfile")
        self.outfilename = QtWidgets.QLineEdit()
        # Checkboxes
        self.prefix_check = QtWidgets.QCheckBox('Prefix')
        self.date_check = QtWidgets.QCheckBox('Date/Time')
        self.count_check = QtWidgets.QCheckBox('Counter')
        self.postfix_check = QtWidgets.QCheckBox('Postfix')
        self.extension_check = QtWidgets.QCheckBox('Extension')

        try:
            filename = self.device.custom_config['filename']
        except:
            filename = ''

        self.outfilename.setText(filename)

        self.folderbtn = QtWidgets.QPushButton("Folder")
        self.config_widgets.append(self.folderbtn)
        self.folderbtn.clicked.connect(self.get_datafolder)

        # Delta t for new file
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
        self.dt_newfile = edit
        self.dt_newfile.setToolTip(
            'Create a new file every N seconds.\nFilename is "filenamebase"_yyyymmdd_HHMMSS_count."ext".\nUse 0 to disable feature.')
        try:
            self.dt_newfile.setText(str(self.device.custom_config['dt_newfile']))
        except Exception as e:
            self.dt_newfile.setText('0')

        # Delta t for new file
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
        self.size_newfile = edit
        self.size_newfile.setToolTip(
            'Create a new file if N bytes of RAM are used.\nFilename is "filenamebase"_yyyymmdd_HHMMSS_count."ext".\nUse 0 to disable feature.')
        try:
            self.size_newfile.setText(str(self.device.custom_config.size_newfile))
        except Exception as e:
            self.size_newfile.setText('0')

        self.newfiletimecombo = QtWidgets.QComboBox()
        times = typing.get_args(
            self.device.custom_config.model_fields['dt_newfile_unit'].annotation)
        timeunit = self.device.custom_config.dt_newfile_unit
        for t in times:
            self.newfiletimecombo.addItem(t)

        index = self.newfiletimecombo.findText(timeunit)
        self.newfiletimecombo.setCurrentIndex(index)

        self.newfilesizecombo = QtWidgets.QComboBox()
        self.newfilesizecombo.addItem('none')
        self.newfilesizecombo.addItem('bytes')
        self.newfilesizecombo.addItem('kB')
        self.newfilesizecombo.addItem('MB')
        self.newfilesizecombo.setCurrentIndex(3)

        sizelabel = QtWidgets.QLabel('New file after')
        # File change layout
        self.newfilewidget = QtWidgets.QWidget()
        self.newfilelayout = QtWidgets.QHBoxLayout(self.newfilewidget)
        self.newfilelayout.addWidget(sizelabel)
        self.newfilelayout.addWidget(self.dt_newfile)
        self.newfilelayout.addWidget(self.newfiletimecombo)
        self.newfilelayout.addWidget(self.size_newfile)
        self.newfilelayout.addWidget(self.newfilesizecombo)

        # Filenamelayout
        self.folder_text = QtWidgets.QLineEdit('')
        self.extension_text = QtWidgets.QLineEdit('rdvsql3')
        self.prefix_text = QtWidgets.QLineEdit('')
        self.date_text = QtWidgets.QLineEdit('%Y-%m-%d_%H%M%S')
        self.count_text = QtWidgets.QLineEdit('04d')
        self.postfix_text = QtWidgets.QLineEdit('')

        self.prefix_check = QtWidgets.QCheckBox('Prefix')
        self.date_check = QtWidgets.QCheckBox('Date/Time')
        self.count_check = QtWidgets.QCheckBox('Counter')
        self.postfix_check = QtWidgets.QCheckBox('Postfix')
        self.extension_check = QtWidgets.QCheckBox('Extension')
        # The outwidget
        self.outwidget = QtWidgets.QWidget()
        self.outlayout = QtWidgets.QGridLayout(self.outwidget)
        # Datafolder lineedit
        self.outlayout.addWidget(self.folderbtn, 0, 0)
        self.outlayout.addWidget(self.folder_text, 0, 1, 1, 4)
        # Checkboxes
        self.outlayout.addWidget(self.prefix_check, 1, 0)
        self.outlayout.addWidget(self.date_check, 1, 1)
        self.outlayout.addWidget(self.count_check, 1, 2)
        self.outlayout.addWidget(self.postfix_check, 1, 3)
        self.outlayout.addWidget(self.extension_check, 1, 4)

        self.outlayout.addWidget(self.prefix_text, 2, 0)
        self.outlayout.addWidget(self.date_text, 2, 1)
        self.outlayout.addWidget(self.count_text, 2, 2)
        self.outlayout.addWidget(self.postfix_text, 2, 3)
        self.outlayout.addWidget(self.extension_text, 2, 4)

        self.outlayout.addWidget(self.newfilewidget, 4, 0, 1, 4)

        # self.outlayout.addStretch(1)

        layout.addWidget(self.label, 0, 0, 1, 2)
        # layout.addWidget(self.inlabel,1,0)
        # layout.addWidget(self.inlist,2,0)
        layout.addWidget(self.outlabel, 1, 0)
        layout.addWidget(self.outwidget, 2, 0)
        layout.addWidget(self.adddeviceinbtn, 5, 0)

        self.config_to_widgets()
        self.connect_widget_signals()

    def connect_widget_signals(self, connect=True):
        """
        Connects the signals of the widgets such that an update of the config is done

        Args:
            connect:

        Returns:

        """
        funcname = self.__class__.__name__ + '.connect_widget_signals():'
        logger.debug(funcname)
        if (connect):
            self.prefix_check.stateChanged.connect(self.update_device_config)
            self.postfix_check.stateChanged.connect(self.update_device_config)
            self.date_check.stateChanged.connect(self.update_device_config)
            self.count_check.stateChanged.connect(self.update_device_config)
            self.extension_check.stateChanged.connect(self.update_device_config)
            self.prefix_text.editingFinished.connect(self.update_device_config)
            self.postfix_text.editingFinished.connect(self.update_device_config)
            self.date_text.editingFinished.connect(self.update_device_config)
            self.count_text.editingFinished.connect(self.update_device_config)
            self.extension_text.editingFinished.connect(self.update_device_config)
            self.newfilesizecombo.currentIndexChanged.connect(self.update_device_config)
            self.newfiletimecombo.currentIndexChanged.connect(self.update_device_config)
        else:
            self.prefix_check.stateChanged.disconnect()
            self.postfix_check.stateChanged.disconnect()
            self.date_check.stateChanged.disconnect()
            self.count_check.stateChanged.disconnect()
            self.extension_check.stateChanged.disconnect()
            self.prefix_text.editingFinished.disconnect()
            self.postfix_text.editingFinished.disconnect()
            self.date_text.editingFinished.disconnect()
            self.count_text.editingFinished.disconnect()
            self.extension_text.editingFinished.disconnect()
            self.newfilesizecombo.currentIndexChanged.disconnect()
            self.newfiletimecombo.currentIndexChanged.disconnect()

    def get_datafolder(self):
        funcname = self.__class__.__name__ + '.get_datafolder():'
        logger.debug(funcname)
        retdata = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose datafolder")
        # print('Datafolder',retdata)
        datafolder = retdata
        if datafolder:
            self.folder_text.setText(datafolder)

    def config_to_widgets(self):
        """
        Updates the widgets according to the device config

        Returns:

        """
        funcname = self.__class__.__name__ + '.config_to_widgets():'
        logger.debug(funcname)

        config = self.device.custom_config
        print('config', config)
        self.dt_newfile.setText(str(config.dt_newfile))
        for i in range(self.newfiletimecombo.count()):
            self.newfiletimecombo.setCurrentIndex(i)
            if (self.newfiletimecombo.currentText().lower() == config.dt_newfile_unit):
                break

        for i in range(self.newfilesizecombo.count()):
            self.newfilesizecombo.setCurrentIndex(i)
            if (
                    self.newfilesizecombo.currentText().lower() == config.size_newfile_unit):
                break

        self.size_newfile.setText(str(config.size_newfile))

        if len(config.datafolder) > 0:
            self.folder_text.setText(config.datafolder)
        # Update filename and checkboxes
        filename_all = []
        filename_all.append(
            [config.fileextension, self.extension_text, self.extension_check])
        filename_all.append([config.fileprefix, self.prefix_text, self.prefix_check])
        filename_all.append([config.filepostfix, self.postfix_text, self.postfix_check])
        filename_all.append([config.filedateformat, self.date_text, self.date_check])
        filename_all.append([config.filecountformat, self.count_text, self.count_check])
        for i in range(len(filename_all)):
            widgets = filename_all[i]
            if (len(widgets[0]) == 0):
                widgets[2].setChecked(False)
                widgets[1].setText('')
            else:
                widgets[2].setChecked(True)
                widgets[1].setText(widgets[0])

    def widgets_to_config(self, config):
        """
        Reads the widgets and creates a config
        Returns:
            config: Config dictionary
        """
        funcname = self.__class__.__name__ + '.widgets_to_config():'
        logger.debug(funcname)
        config.dt_newfile = int(self.dt_newfile.text())
        config.dt_newfile_unit = self.newfiletimecombo.currentText()
        config.size_newfile = int(self.size_newfile.text())
        config.size_newfile_unit = self.newfilesizecombo.currentText()

        config.datafolder = self.folder_text.text()

        if (self.extension_check.isChecked()):
            config.fileextension = self.extension_text.text()
        else:
            config.fileextension = ''

        if (self.prefix_check.isChecked()):
            config.fileprefix = self.prefix_text.text()
        else:
            config.fileprefix = ''

        if (self.postfix_check.isChecked()):
            config.filepostfix = self.postfix_text.text()
        else:
            config.filepostfix = ''

        if (self.date_check.isChecked()):
            config.filedateformat = self.date_text.text()
        else:
            config.filedateformat = ''

        if (self.count_check.isChecked()):
            config.filecountformat = self.count_text.text()
        else:
            config.filecountformat = ''

        print('Config', config)
        return config

    def update_device_config(self):
        """
        Updates the device config based on the widgets
        Returns:

        """
        funcname = self.__class__.__name__ + '.update_device_config():'
        logger.debug(funcname)
        self.widgets_to_config(self.device.custom_config)

class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args, **kwargs)
        layout = QtWidgets.QGridLayout()
        self.file_statistics = {'filenames_created':[]}
        #self.device = device
        self.config_widget = DeviceConfigWidget(mainwindow = self, device = self.device)
        self.config_widgets= [] # A list of all widgets that can only be used of the device is not started yet
        # Input output widget
        self.inlabel  = QtWidgets.QLabel("Filenames") 
        self.inlabel.setStyleSheet(''' font-size: 20px; font: bold''')
        self.filename_edit = QtWidgets.QLineEdit()
        self.filanembtn = QtWidgets.QPushButton("Choose file")

        self.inlist = QtWidgets.QTableWidget()
        self.inlist.setColumnCount(4)
        self.inlist.setRowCount(0)
        self.inlist.setSortingEnabled(True)
        
        self.__filelistheader__ = ['Name','Size','created','Packets saved']
        self.inlist.setHorizontalHeaderLabels(self.__filelistheader__)

        layout.addWidget(self.config_widget,0,0,1,-1)
        
        layout.addWidget(self.inlabel,4,0,1,-1,QtCore.Qt.AlignCenter)
        layout.addWidget(self.inlist,5,0,1,-1)

        self.layout_buttons.removeWidget(self.subscribe_button)
        self.layout_buttons.removeWidget(self.configure_button)
        self.layout_buttons.addWidget(self.configure_button,3,5,1,1)
        #self.layout_buttons.addWidget(self.configure_button, 2, 2, 1, 2)
        self.subscribe_button.close()
        self.startbutton.disconnect()
        self.startbutton.clicked.connect(self.start_clicked)
        self.layout.addLayout(layout)

        self.statustimer_2 = QtCore.QTimer()
        self.statustimer_2.timeout.connect(self.update_status)
        self.statustimer_2.start(500)

    def finalize_init(self):
        """ Util function that is called by redvypr after initializing all config (i.e. the configuration from a yaml file)
        """
        funcname = self.__class__.__name__ + '.finalize_init()'
        logger.debug(funcname)
        
    def rem_files(self):
        """ Remove the selected files from the files list
        """
        funcname = self.__class__.__name__ + '.rem_files()'
        logger.debug(funcname)
        rows = []
        for i in self.inlist.selectionModel().selection().indexes():
            row, column = i.row(), i.column()
            rows.append(row)
        
        rows = list(set(rows))
        rows.sort(reverse=True)  
        for i in rows:
            self.device.custom_config.files.pop(i)
            
        self.update_filenamelist() 

    def add_files(self):
        """ Opens a dialog to choose file to add
        """
        funcname = self.__class__.__name__ + '.add_files()'
        logger.debug(funcname)
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(self,"Rawdatafiles","","All Files (*)")
        for f in filenames: 
            self.device.custom_config.files.append(f)
            
        
        self.update_filenamelist()
        self.inlist.sortItems(0, QtCore.Qt.AscendingOrder)
            

    def start_clicked(self):
        funcname = self.__class__.__name__ + '.start_clicked():'
        logger.debug(funcname)
        button = self.sender()

        if button.isChecked():
            logger.debug(funcname + "button pressed")
            self.device.custom_config = self.config_widget.widgets_to_config(self.device.custom_config)
            self.device.thread_start()
        else:
            logger.debug(funcname + 'button released')
            self.device.thread_stop()

    def update_status(self):
        statusqueue = self.device.statusqueue
        while (statusqueue.empty() == False):
            try:
                data = statusqueue.get(block=False)
                statusdata = data['_deviceinfo']
                print('data', statusdata)
                filename = statusdata['filename']
                irow = 0
                if filename not in self.file_statistics['filenames_created']:
                    self.file_statistics['filenames_created'].append(filename)
                    self.inlist.insertRow(0)

                item = QtWidgets.QTableWidgetItem(filename)  # Packets sent
                self.inlist.setItem(irow, 0, item)
                item = QtWidgets.QTableWidgetItem(
                    str(statusdata['bytes_written']))  # Packets sent
                self.inlist.setItem(irow, 1, item)

                timestamp = datetime.fromtimestamp(statusdata['created'],
                                                   tz=timezone.utc).isoformat()
                item = QtWidgets.QTableWidgetItem(timestamp)
                self.inlist.setItem(irow, 2, item)
                item = QtWidgets.QTableWidgetItem(
                    str(statusdata['packets_written']))  # Packets sent
                self.inlist.setItem(irow, 3, item)
                self.inlist.resizeColumnsToContents()
            except:
                logger.info('Problem',exc_info=True)
                break





