"""

Logger that writes xlsx files

"""

from PyQt6 import QtWidgets, QtCore, QtGui
import sys
import pydantic
import typing
import os
import time
import datetime
import logging
import numpy
import netCDF4

import redvypr.metadata
from redvypr.device import RedvyprDevice
import redvypr.data_packets as data_packets
import redvypr.redvypr_address as redvypr_address
import redvypr.packet_statistic as packet_statistics
import redvypr.gui

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.netcdfwriter')
logger.setLevel(logging.INFO)

redvypr_devicemodule = True
class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = "Saves subscribed devices in a netCDF4 file"
    gui_tablabel_display: str = 'netCDF logging status'

class DeviceCustomConfig(pydantic.BaseModel):
    dt_sync: int = pydantic.Field(default=60,description='Time after which an open file is synced on disk')
    dt_newfile: int = pydantic.Field(default=3600,description='Time after which a new file is created')
    dt_newfile_unit: typing.Literal['none','seconds','hours','days'] = pydantic.Field(default='seconds')
    dt_update:int = pydantic.Field(default=2,description='Time after which an upate is sent to the gui')
    nc_bufsize:int = pydantic.Field(default=10,description='netcdf buffer size, storing data before it is written to the file')
    dt_bufsync: float = pydantic.Field(default=10,
                                    description='Time after which the netcdf buffer is synced to file')
    clearqueue: bool = pydantic.Field(default=True, description='Flag if the buffer of the subscribed queue should be emptied before start')
    zlib: bool = pydantic.Field(default=False, description='Flag if zlib compression shall be used for the netCDF data')
    size_newfile:int = pydantic.Field(default=500,description='Size of object in RAM after which a new file is created')
    size_newfile_unit: typing.Literal['none','bytes','kB','MB'] = pydantic.Field(default='MB')
    datafolder:str = pydantic.Field(default='.',description='Folder the data is saved to')
    fileextension:str= pydantic.Field(default='nc',description='File extension, if empty not used')
    fileprefix:str= pydantic.Field(default='redvypr',description='If empty not used')
    filepostfix:str= pydantic.Field(default='netcdfwriter',description='If empty not used')
    filedateformat:str= pydantic.Field(default='%Y-%m-%d_%H%M%S',description='Dateformat used in the filename, must be understood by datetime.strftime')
    filecountformat:str= pydantic.Field(default='04',description='Format of the counter. Add zero if trailing zeros are wished, followed by number of digits. 04 becomes {:04d}')




logger = logging.getLogger('netcdfwriter')


class NetCDFWriter:
    def __init__(self, device_info, config):
        self.device_info = device_info
        self.config = config
        self.file_count = 0

        self.flag_zlib = config.get('zlib', False)
        self.packets_written = 0
        self.bytes_written = 0
        self.file_status = {}
        self.vars_updated = []
        self.deviceinfo_all = None

        # Buffer structures
        self.data_buffer = {}
        self.t_file_created = time.time()
        self.t_last_flush = time.time()
        self.t_last_buf_sync = time.time()

        # Calculate rotation limits
        self.dt_new_file_seconds = self._calc_time_limit()
        self.size_new_file_bytes = self._calc_size_limit()

        # Initialize the first file
        self.nc, self.filename = self.create_logfile()
        self._init_file_metadata()

    def _calc_time_limit(self):
        try:
            dt_orig = self.config['dt_newfile']
            unit = self.config['dt_newfile_unit'].lower()
            factor = {'seconds': 1.0, 'hours': 3600.0, 'days': 86400.0}.get(unit, 0.0)
            return dt_orig * factor
        except Exception:
            logger.debug("Configuration incomplete (time limit)", exc_info=True)
            return 0

    def _calc_size_limit(self):
        try:
            size_orig = self.config['size_newfile']
            unit = self.config['size_newfile_unit'].lower()
            factor = {'bytes': 1.0, 'kb': 1000.0, 'mb': 1e6}.get(unit, 0.0)
            return size_orig * factor
        except Exception:
            logger.debug("Configuration incomplete (size limit)", exc_info=True)
            return 0

    def create_logfile(self):
        filename = ''
        if len(self.config['datafolder']) > 0:
            if os.path.isdir(self.config['datafolder']):
                filename += self.config['datafolder'] + os.sep
            else:
                logger.warning(
                    f"Data folder {self.config['datafolder']} does not exist.")
                return None, ''

        if len(self.config['fileprefix']) > 0:
            filename += self.config['fileprefix']

        if len(self.config['filedateformat']) > 0:
            t_str = datetime.datetime.now().strftime(self.config['filedateformat'])
            filename += '_' + t_str

        if len(self.config['filecountformat']) > 0:
            c_str = "{:" + self.config['filecountformat'] + "d}"
            filename += '_' + c_str.format(self.file_count)

        if len(self.config['filepostfix']) > 0:
            filename += '_' + self.config['filepostfix']

        if len(self.config['fileextension']) > 0:
            filename += '.' + self.config['fileextension']

        logger.info(f"Will create a new file: {filename}")
        nc = netCDF4.Dataset(filename, mode='w', format='NETCDF4')
        return nc, filename

    def _init_file_metadata(self):
        self.nc.redvypr_version = f"redvypr {redvypr.version}"
        self.t_file_created = time.time()

    def get_nc_structure(self, nc_object=None):
        """ Recursively scans the NetCDF structure """
        if nc_object is None:
            nc_object = self.nc

        structure = {'attributes': {}, 'variables': {}, 'groups': {}}
        structure['attributes'] = {attr: nc_object.getncattr(attr) for attr in
                                   nc_object.ncattrs()}

        for var_name, var_obj in nc_object.variables.items():
            var_attributes = {attr: var_obj.getncattr(attr) for attr in
                              var_obj.ncattrs()}
            structure['variables'][var_name] = {
                'shape': var_obj.shape,
                'length': len(var_obj) if 'time' in var_obj.dimensions else 0,
                'dimensions': var_obj.dimensions,
                'attributes': var_attributes
            }

        for group_name, group_obj in nc_object.groups.items():
            structure['groups'][group_name] = self.get_nc_structure(group_obj)

        return structure

    def get_current_status(self, closed_status=-1):
        """ Generates status dictionary for queue communication """
        self.bytes_written = os.path.getsize(self.filename)

        # Update NetCDF core attributes
        self.nc.filename = self.filename
        self.nc.filename_full = os.path.realpath(self.filename)
        self.nc.closed = closed_status
        self.nc.bytes_written = self.bytes_written
        self.nc.packets_written = self.packets_written

        return {
            '_deviceinfo': {
                'filename': self.filename,
                'filename_full': os.path.realpath(self.filename),
                'created': self.t_file_created,
                'closed': closed_status,
                'bytes_written': self.bytes_written,
                'packets_written': self.packets_written,
                'file_status': self.file_status,
                'file_status_reduced': self.file_status,
                'nc_structure': self.get_nc_structure() if closed_status == -1 else {}
            }
        }

    def check_rotation_and_flush(self, force_close=False):
        """ Checks limits and rotates the file or executes a disk sync """
        t_check = time.time()

        # 1. Regular disk flush (sync)
        if (t_check - self.t_last_flush) > self.config['dt_sync'] and not force_close:
            self.nc.sync()
            self.bytes_written = os.path.getsize(self.filename)
            logger.info(
                f"Syncing netCDF file {self.filename} ({self.bytes_written} bytes)")
            self.t_last_flush = t_check

        # 2. Rotation check (file size or age limits)
        file_age = t_check - self.t_file_created
        flag_time = (self.dt_new_file_seconds > 0) and (
                    file_age >= self.dt_new_file_seconds)
        flag_size = (self.size_new_file_bytes > 0) and (
                    self.bytes_written >= self.size_new_file_bytes)

        if flag_time or flag_size or force_close:
            closed_time = time.time() if force_close else t_check
            status_msg = self.get_current_status(closed_status=closed_time)

            self.nc.close()
            self.file_count += 1
            logger.info(f"Closed file {self.filename}")

            if not force_close:
                # Open a new file
                self.bytes_written = 0
                self.packets_written = 0
                self.nc, self.filename = self.create_logfile()
                self._init_file_metadata()

            return status_msg
        return None

    def add_datapacket(self, data):
        """ Processes and writes a single data packet """
        packet_address = redvypr.RedvyprAddress(data)

        # Handle commands (Info/Metadata updates)
        [command, comdata] = data_packets.check_for_command(data, thread_uuid=
        self.device_info['thread_uuid'], add_data=True)
        if command == 'info' and packet_address.packetid == 'metadata':
            self.deviceinfo_all = data['deviceinfo_all']
            self.vars_updated = []

        # Validate Hostname UUID
        if packet_address.uuid == self.device_info['hostinfo']['uuid']:
            hostname = self.device_info['hostinfo']['host']
        else:
            hostname = f"{packet_address.host}__UUID__{packet_address.uuid}"

        publisher = packet_address.publisher
        devicename = packet_address.device

        # Dynamically build Group hierarchy
        if hostname not in self.nc.groups:
            logger.debug(f"Creating base group {hostname}")
            self.nc.createGroup(hostname)
            self.data_buffer[hostname] = {}

        if publisher not in self.nc[hostname].groups:
            logger.debug(f"Creating publishing device {publisher}")
            self.nc[hostname].createGroup(publisher)
            self.data_buffer[hostname][publisher] = {}

        if devicename not in self.nc[hostname][publisher].groups:
            logger.debug(f"Creating device {devicename}")
            nc_device = self.nc[hostname][publisher].createGroup(devicename)
            nc_device.redvypr_address = redvypr_address.RedvyprAddress(
                data).to_address_string()
            self.data_buffer[hostname][publisher][devicename] = {}

        nc_device = self.nc[hostname][publisher][devicename]
        datakeys = data_packets.Datapacket(data).datakeys()

        if 't' in datakeys:
            datakeys.remove('t')

        for k in datakeys:
            if k not in nc_device.groups:
                logger.debug(f"Creating group for datakey {k}")
                nc_datakey = nc_device.createGroup(k)
                nc_datakey.redvypr_address = redvypr_address.RedvyprAddress(data,
                                                                            datakey=k).to_address_string()
                nc_datakey.stack = 0

                nc_datakey.createDimension('time', None)
                nc_datakey.createVariable('time', float, ('time',))

                self.data_buffer[hostname][publisher][devicename][k] = {'time': [],
                                                                        k: []}

                typedata = type(data[k])
                lent = len(data['t']) if isinstance(data['t'],
                                                    (list, numpy.ndarray)) else 1

                if typedata in (list, numpy.ndarray):
                    try:
                        logger.info(
                            f"Creating variable {k} with list/ndarray type {typedata}")
                        dwrite = numpy.asarray(data[k])
                        datatype_array = dwrite.dtype
                        dwrite_shape = numpy.shape(dwrite)
                        lenk = dwrite_shape[0]
                        dimnames = ['time']

                        if lent == lenk and len(dwrite_shape) == 1:
                            nc_datakey.stack = 1
                        else:
                            ishape = 1 if lent == lenk else 0
                            for id, nd in enumerate(dwrite_shape[ishape:]):
                                dimname = f"{k}_n_{id}"
                                dimnames.append(dimname)
                                nc_datakey.createDimension(dimname, nd)
                                nc_datakey.stack = 2

                        var = nc_datakey.createVariable(k, datatype_array, dimnames,
                                                        zlib=self.flag_zlib)
                        setattr(var, 'redvypr_address',
                                packet_address.to_address_string())
                    except Exception:
                        logger.warning(f"Could not create variable for {k}",
                                       exc_info=True)
                elif typedata is str:
                    logger.info("Creating string variable")
                    var = nc_datakey.createVariable(k, str, ('time',), zlib=False)
                    setattr(var, 'redvypr_address', packet_address.to_address_string())
                elif typedata in (bytes, dict, None, type(None)):
                    var = None
                else:
                    try:
                        logger.info(f"Creating variable with type {typedata}")
                        var = nc_datakey.createVariable(k, typedata, ('time',),
                                                        zlib=self.flag_zlib)
                        setattr(var, 'redvypr_address',
                                packet_address.to_address_string())
                    except Exception:
                        var = None

            # Set metadata attributes
            if self.deviceinfo_all is not None and (k in nc_device.groups):
                try:
                    nc_datakey = nc_device[k]
                    var = nc_datakey.variables.get(k, None)
                    if var not in self.vars_updated:
                        raddress_tmp = redvypr_address.RedvyprAddress(data)
                        metadata_tmp = redvypr.metadata.get_metadata(
                            self.deviceinfo_all, raddress_tmp, mode="merge")
                        if len(metadata_tmp.keys()) > 0:
                            for metakey in metadata_tmp.keys():
                                setattr(nc_device, metakey, metadata_tmp[metakey])
                        self.vars_updated.append(var)
                except Exception:
                    logger.debug("Could not set metadata", exc_info=True)

        # Write data to internal memory buffer
        self.packets_written += 1
        flag_sync_databuffer_size = False

        for k in datakeys:
            if k not in nc_device.groups:
                continue

            data_tmp = data[k]
            t_tmp = data.get('t', data.get('_redvypr', {}).get('t', time.time()))

            self.data_buffer[hostname][publisher][devicename][k][k].append(data_tmp)
            self.data_buffer[hostname][publisher][devicename][k]['time'].append(t_tmp)

            nbuf = len(self.data_buffer[hostname][publisher][devicename][k]['time'])
            if nbuf >= self.config['nc_bufsize']:
                flag_sync_databuffer_size = True

        # Flash buffer if limit reached or buffer timeout expired
        if flag_sync_databuffer_size or (
                (time.time() - self.t_last_buf_sync) > self.config['dt_bufsync']):
            self.flush_databuffer(datakeys, hostname, publisher, devicename)

    def flush_databuffer(self, datakeys, hostname, publisher, devicename):
        """ Commits memory buffered data into NetCDF variables """
        self.t_last_buf_sync = time.time()
        logger.debug(f"Syncing databuffer to {self.filename}")

        nc_device = self.nc[hostname][publisher][devicename]
        for k in datakeys:
            if k not in nc_device.groups:
                continue

            nc_datakey = nc_device[k]
            data_write = self.data_buffer[hostname][publisher][devicename][k][k]

            if len(data_write) > 0:
                logger.debug(f"\tSyncing {k}")
                t_write = self.data_buffer[hostname][publisher][devicename][k]['time']

                # Clear buffer keys
                self.data_buffer[hostname][publisher][devicename][k]['time'] = []
                self.data_buffer[hostname][publisher][devicename][k][k] = []

                var_k = nc_datakey.variables[k]
                var_t = nc_datakey.variables['time']
                lent_nc = len(var_t)

                if nc_datakey.stack == 1:
                    try:
                        t_write_flat = numpy.concatenate(t_write)
                    except Exception:
                        print(f"Could not concatenate variable: {k}")
                        continue
                else:
                    t_write_flat = t_write

                lent_new = len(t_write_flat)
                var_t[lent_nc:lent_nc + lent_new] = t_write_flat

                if isinstance(data_write[0], str):
                    for i, val in enumerate(data_write):
                        try:
                            var_k[lent_nc + i] = val
                        except Exception:
                            print("Could not sync index and value:", i, val)
                else:
                    if nc_datakey.stack == 1:
                        data_np = numpy.concatenate(data_write)
                    elif nc_datakey.stack == 2:
                        data_np = numpy.stack(data_write)
                    else:
                        data_np = numpy.asarray(data_write)

                    try:
                        var_k[lent_nc:lent_nc + lent_new, ...] = data_np
                    except Exception as e:
                        print(f"Write error for variable {k}: {e}")

                self.file_status[k] = self.file_status.get(k, 0) + 1


def start(device_info, config, dataqueue=None, datainqueue=None, statusqueue=None):
    logger_start = logging.getLogger('netcdfwriter/thread')
    logger_start.setLevel(logging.INFO)
    func_name = __name__ + '.start()'
    logger_start.debug(func_name + ': Opening worker queue writer.')

    # 1. Purge queue if requested in config
    if config['clearqueue']:
        while not datainqueue.empty():
            try:
                datainqueue.get(block=False)
            except Exception:
                break

    # 2. Instantiate the Writer class (automatically handles first file creation)
    writer = NetCDFWriter(device_info, config)

    # Broadcast initial status
    initial_status = writer.get_current_status(closed_status=-1)
    dataqueue.put(initial_status)

    t_last_update = time.time()
    flag_run = True
    packets_read = 0

    # 3. Main Consumer Loop
    while flag_run:
        t_check = time.time()
        time.sleep(0.05)

        while not datainqueue.empty() and flag_run:
            try:
                data = datainqueue.get(block=False)
                packets_read += 1

                if data is not None:
                    # Check for stop commands
                    packet_address = redvypr.RedvyprAddress(data)
                    [command, comdata] = data_packets.check_for_command(
                        data, thread_uuid=device_info['thread_uuid'], add_data=True
                    )
                    if command == 'stop':
                        logger_start.debug('Stop command received via queue.')
                        flag_run = False
                        break

                    # Filter metadata packets (handled internally via 'info' commands)
                    if redvypr_address.RedvyprAddress(
                            redvypr.redvypr_address.metadata_address)(data,
                                                                      strict=False):
                        logger_start.debug('Ignoring redundant metadata packet.')
                        continue

                    # Forward the data packet to the class instance
                    writer.add_datapacket(data)

            except Exception as e:
                logger.exception(e)
                logger.debug(func_name + ': Exception occurred: ' + str(e))

            # Trigger inner rotation & flush verification
            rot_status = writer.check_rotation_and_flush(force_close=False)
            if rot_status:
                dataqueue.put(rot_status)

        # Heartbeat: Periodically send runtime statistics to main thread
        if (time.time() - t_last_update) > config['dt_update']:
            t_last_update = time.time()
            status_msg = writer.get_current_status(closed_status=-1)
            dataqueue.put(status_msg)

        # Outer check for rotation (handles edge cases where incoming data halts)
        rot_status = writer.check_rotation_and_flush(force_close=False)
        if rot_status:
            dataqueue.put(rot_status)

    # 4. Thread termination -> Force shutdown and close open file descriptors cleanly
    final_status = writer.check_rotation_and_flush(force_close=True)
    if final_status:
        dataqueue.put(final_status)

    logger_start.info(func_name + " Thread executed and stopped cleanly.")


class Device(RedvyprDevice):
    """
    netCDFlogger device
    """

    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)


#
#
# The init widget
#
#
class initDeviceWidget(QtWidgets.QWidget):
    connect      = QtCore.pyqtSignal(RedvyprDevice) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QGridLayout(self)
        #print('Hallo,device config',device.config)
        self.device   = device
        self.redvypr  = device.redvypr
        self.label    = QtWidgets.QLabel("netCDF logger setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')
        self.config_widgets= [] # A list of all widgets that can only be used of the device is not started yet
        # Input output widget
        self.inlabel  = QtWidgets.QLabel("Input")
        self.inlist   = QtWidgets.QListWidget()
        #
        self.adddeviceinbtn   = QtWidgets.QPushButton("Subscribe")
        self.adddeviceinbtn.clicked.connect(self.con_clicked)
        self.adddeviceinbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        # The output widgets
        self.outlabel        = QtWidgets.QLabel("Logfile")
        self.outfilename     = QtWidgets.QLineEdit()
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
        
        self.folderbtn   = QtWidgets.QPushButton("Folder")
        self.config_widgets.append(self.folderbtn)
        self.folderbtn.clicked.connect(self.get_datafolder)
        
        # The rest
        #self.conbtn = QtWidgets.QPushButton("Connect logger to devices")
        #self.conbtn.clicked.connect(self.con_clicked)        
        self.startbtn = QtWidgets.QPushButton("Start logging")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)
        self.startbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)


        # Delta t for new file
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
        self.dt_newfile = edit
        self.dt_newfile.setToolTip('Create a new file every N seconds.\nFilename is "filenamebase"_yyyymmdd_HHMMSS_count."ext".\nUse 0 to disable feature.')
        try:
            self.dt_newfile.setText(str(self.device.custom_config['dt_newfile']))
        except Exception as e:
            self.dt_newfile.setText('0')
            
        # Delta t for new file
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
        self.size_newfile = edit
        self.size_newfile.setToolTip('Create a new file if N bytes of RAM are used.\nFilename is "filenamebase"_yyyymmdd_HHMMSS_count."ext".\nUse 0 to disable feature.')
        try:
            self.size_newfile.setText(str(self.device.custom_config.size_newfile))
        except Exception as e:
            self.size_newfile.setText('0')
            
        self.newfiletimecombo = QtWidgets.QComboBox()
        times = typing.get_args(self.device.custom_config.model_fields['dt_newfile_unit'].annotation)
        timeunit = self.device.custom_config.dt_newfile_unit
        for t in times:
            self.newfiletimecombo.addItem(t)

        index = self.newfiletimecombo.findText(timeunit)
        self.newfiletimecombo.setCurrentIndex(index)
        #self.newfiletimecombo.addItem('None')
        #self.newfiletimecombo.addItem('seconds')
        #self.newfiletimecombo.addItem('hours')
        #self.newfiletimecombo.addItem('days')
        #self.newfiletimecombo.setCurrentIndex(1)
            
        self.newfilesizecombo = QtWidgets.QComboBox()
        self.newfilesizecombo.addItem('None')
        self.newfilesizecombo.addItem('bytes')
        self.newfilesizecombo.addItem('kB')
        self.newfilesizecombo.addItem('MB')
        self.newfilesizecombo.setCurrentIndex(3)
        
        sizelabel = QtWidgets.QLabel('New file after')
         # File change layout
        self.newfilewidget = QtWidgets.QWidget()
        self.newfilelayout = QtWidgets.QFormLayout(self.newfilewidget)
        self.newfilelayout.addRow(sizelabel)
        self.newfilelayout.addRow(self.dt_newfile,self.newfiletimecombo)
        self.newfilelayout.addRow(self.size_newfile,self.newfilesizecombo)
        
        # Filenamelayout
        self.folder_text = QtWidgets.QLineEdit('')
        self.extension_text = QtWidgets.QLineEdit('redvypr_raw')
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
        self.outlayout.addWidget(self.folder_text, 0, 1,1,4)
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

        self.outlayout.addWidget(self.newfilewidget,4,0,1,4)

        #self.outlayout.addStretch(1)
            
        layout.addWidget(self.label,0,0,1,2)
        #layout.addWidget(self.inlabel,1,0)
        #layout.addWidget(self.inlist,2,0)
        layout.addWidget(self.outlabel,1,0)
        layout.addWidget(self.outwidget,2,0)
        layout.addWidget(self.adddeviceinbtn, 5, 0)
        layout.addWidget(self.startbtn,6,0)

        self.config_to_widgets()
        self.connect_widget_signals()
        # Connect the signals that notify a change of the connection
        self.device.redvypr.device_status_changed_signal.connect(self.update_device_list)
        #self.redvypr.devices_connected.connect
        self.device.subscription_changed_signal.connect(self.update_device_list)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)


    def connect_widget_signals(self,connect=True):
        """
        Connects the signals of the widgets such that an update of the config is done

        Args:
            connect:

        Returns:

        """
        funcname = self.__class__.__name__ + '.connect_widget_signals():'
        logger.debug(funcname)
        if(connect):
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
        retdata = QtWidgets.QFileDialog.getExistingDirectory(self,"Choose datafolder")
        #print('Datafolder',retdata)
        datafolder = retdata
        if datafolder:
            self.folder_text.setText(datafolder)
            
    def con_clicked(self):
        funcname = self.__class__.__name__ + '.con_clicked():'
        logger.debug(funcname)
        button = self.sender()
        if(button == self.adddeviceinbtn):
            self.connect.emit(self.device) # The connect signal is connected with connect_device that will open a subscribe/connect widget
            self.update_device_list()

    def update_datastream_table(self):
        """

        """
        # columns = ['Columnnr.', 'Datakey', 'Device', 'Format', 'Full Address String']
        funcname = self.__class__.__name__ + '.update_datastream_table():'
        print(funcname)
        datastreams_subscribed = self.device.get_subscribed_datastreams()
        print('datastreams subscribed',datastreams_subscribed)
        self.datastreamtable.clear()
        self.datastreamtable.setRowCount(len(datastreams_subscribed))
        for i,d in enumerate(datastreams_subscribed):
            dadr = str(redvypr_address.RedvyprAddress(d))
            item = QtWidgets.QTableWidgetItem(d)
            self.datastreamtable.setItem(i,4,item)

        self.datastreamtable.resizeColumnsToContents()

    def update_device_list(self):
        funcname = self.__class__.__name__ + '.update_device_list():'
        logger.debug(funcname)
        #print('Devices',devicestr_provider,devicestr_receiver)
        raddresses = self.device.get_subscribed_deviceaddresses()
        #print('Deviceaddresses',raddresses)
        self.inlist.clear()
        for raddr in raddresses:
            self.inlist.addItem(str(raddr))


    def config_to_widgets(self):
        """
        Updates the widgets according to the device config

        Returns:

        """
        funcname = self.__class__.__name__ + '.config_to_widgets():'
        logger.debug(funcname)

        config = self.device.custom_config
        print('config',config)
        self.dt_newfile.setText(str(config.dt_newfile))
        for i in range(self.newfiletimecombo.count()):
            self.newfiletimecombo.setCurrentIndex(i)
            if(self.newfiletimecombo.currentText().lower() == config.dt_newfile_unit):
                break

        for i in range(self.newfilesizecombo.count()):
            self.newfilesizecombo.setCurrentIndex(i)
            if (self.newfilesizecombo.currentText().lower() == config.size_newfile_unit):
                break

        self.size_newfile.setText(str(config.size_newfile))

        if len(config.datafolder)>0:
            self.folder_text.setText(config.datafolder)
        # Update filename and checkboxes
        filename_all = []
        filename_all.append([config.fileextension,self.extension_text,self.extension_check])
        filename_all.append([config.fileprefix,self.prefix_text,self.prefix_check])
        filename_all.append([config.filepostfix,self.postfix_text,self.postfix_check])
        filename_all.append([config.filedateformat,self.date_text,self.date_check])
        filename_all.append([config.filecountformat,self.count_text,self.count_check])
        for i in range(len(filename_all)):
            widgets = filename_all[i]
            if(len(widgets[0])==0):
                widgets[2].setChecked(False)
                widgets[1].setText('')
            else:
                widgets[2].setChecked(True)
                widgets[1].setText(widgets[0])

    def widgets_to_config(self,config):
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

        if(self.extension_check.isChecked()):
            config.fileextension = self.extension_text.text()
        else:
            config.fileextension = ''

        if(self.prefix_check.isChecked()):
            config.fileprefix = self.prefix_text.text()
        else:
            config.fileprefix = ''

        if(self.postfix_check.isChecked()):
            config.filepostfix = self.postfix_text.text()
        else:
            config.filepostfix = ''

        if(self.date_check.isChecked()):
            config.filedateformat = self.date_text.text()
        else:
            config.filedateformat = ''

        if(self.count_check.isChecked()):
            config.filecountformat = self.count_text.text()
        else:
            config.filecountformat = ''

        print('Config',config)
        return config

    def update_device_config(self):
        """
        Updates the device config based on the widgets
        Returns:

        """
        funcname = self.__class__.__name__ + '.update_device_config():'
        logger.debug(funcname)
        self.widgets_to_config(self.device.custom_config)

    def start_clicked(self):
        funcname = self.__class__.__name__ + '.start_clicked():'
        logger.debug(funcname)
        button = self.sender()
        if button.isChecked():
            logger.debug(funcname + "button pressed")
            self.update_device_config()
            self.device.thread_start()
        else:
            logger.debug(funcname + 'button released')
            self.device.thread_stop()

            
    def update_buttons(self):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """

            status = self.device.get_thread_status()
            thread_status = status['thread_running']

            # Running
            if(thread_status):
                self.startbtn.setText('Stop')
                self.startbtn.setChecked(True)
                for w in self.config_widgets:
                    w.setEnabled(False)
            # Not running
            else:
                self.startbtn.setText('Start')
                for w in self.config_widgets:
                    w.setEnabled(True)
                    
                # Check if an error occured and the startbutton 
                if(self.startbtn.isChecked()):
                    self.startbtn.setChecked(False)
                #self.conbtn.setEnabled(True)


class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        self.device = device
        layout = QtWidgets.QVBoxLayout(self)
        hlayout = QtWidgets.QHBoxLayout()
        self.filetable = QtWidgets.QTableWidget()
        headers = ['Filename','Bytes written','Packets written','Date created','Date closed','Full filepath']
        self.filetable.setColumnCount(len(headers))
        self.filetable.setHorizontalHeaderLabels(headers)
        self.filetable.resizeColumnsToContents()
        self.filelab = QtWidgets.QLabel("File: ")
        self.byteslab = QtWidgets.QLabel("Bytes written: ")
        self.packetslab = QtWidgets.QLabel("Packets written: ")
        # Table that displays all datastreams and the format as it is written to the file
        self.deviceinfoQtree = redvypr.gui.dictQTreeWidget(dataname='file status', show_datatype = False)
        # Update layout
        updatelayout = QtWidgets.QHBoxLayout()
        self.update_auto = QtWidgets.QCheckBox('Autoupdate file status')
        self.update_auto.setChecked(True)
        updatelayout.addWidget(self.update_auto)

        hlayout.addWidget(self.byteslab)
        hlayout.addWidget(self.packetslab)
        layout.addWidget(self.filelab)        
        layout.addLayout(hlayout)
        layout.addWidget(self.filetable)
        layout.addWidget(self.deviceinfoQtree)
        # Add update options
        layout.addLayout(updatelayout)

    def update_qtreewidget(self, nc_structure):
        funcname = __name__ + '.update_qtreewidget()'
        logger.debug(funcname)
        if self.update_auto.isChecked():
            # Update the qtree
            # https://stackoverflow.com/questions/9364754/remembering-scroll-value-of-a-qtreewidget-in-pyqt?rq=3
            bar = self.deviceinfoQtree.verticalScrollBar()
            yScroll = bar.value()
            #print('File status',nc_structure)
            self.deviceinfoQtree.reload_data(nc_structure)
            self.deviceinfoQtree.verticalScrollBar().setSliderPosition(yScroll)

    def update_data(self,data):
        funcname = __name__ + '.update()'
        #print(funcname,data)
        try:
            data['_deviceinfo']
        except:
            return

        try:
            nc_structure = data['_deviceinfo']['nc_structure']
            #print("nc structure",nc_structure)
            self.update_qtreewidget(nc_structure)
        except:
            pass

        # Update qtree
        try:
            # Test if the file status has changed, if yes make an update
            file_status_tmp = data['_deviceinfo']['file_status']
            try:
                self.update_qtreewidget()
            except:
                pass
                #logger.debug(funcname, exc_info=True)

        except:
            pass
            #logger.info(funcname, exc_info=True)


        try:
            #print('data',data)
            try:
                filename_table = self.filetable.item(0,0).text()
            except:
                filename_table = ''

            try:
                data['_deviceinfo']['filename']
                FLAG_FILEUPDATE = True
            except:
                FLAG_FILEUPDATE = False

            if FLAG_FILEUPDATE:
                #print('Filename table',filename_table,data['_deviceinfo']['filename'])
                try:
                    tclose = datetime.datetime.fromtimestamp(data['_deviceinfo']['closed']).strftime(
                        '%d-%m-%Y %H:%M:%S')
                    item = QtWidgets.QTableWidgetItem(tclose)
                    self.filetable.setItem(0, 4, item)
                except:
                    pass

                if filename_table != data['_deviceinfo']['filename']:
                    self.filetable.insertRow(0)
                    try:
                        #headers = ['Filename', 'Date created', 'Bytes written', 'Date closed']
                        item = QtWidgets.QTableWidgetItem(data['_deviceinfo']['filename'])
                        self.filetable.setItem(0,0,item)
                        item = QtWidgets.QTableWidgetItem(data['_deviceinfo']['filename_full'])
                        self.filetable.setItem(0, 5, item)
                        tcreate = datetime.datetime.fromtimestamp(data['_deviceinfo']['created']).strftime('%d-%m-%Y %H:%M:%S')
                        item = QtWidgets.QTableWidgetItem(tcreate)
                        self.filetable.setItem(0, 3, item)
                    except Exception as e:
                        logger.exception(e)

                item = QtWidgets.QTableWidgetItem(str(data['_deviceinfo']['bytes_written']))
                self.filetable.setItem(0, 1, item)
                item = QtWidgets.QTableWidgetItem(str(data['_deviceinfo']['packets_written']))
                self.filetable.setItem(0, 2, item)
                self.filetable.resizeColumnsToContents()
                self.filelab.setText("File: {:s}".format(data['_deviceinfo']['filename']))
                self.byteslab.setText("Bytes written: {:d}".format(data['_deviceinfo']['bytes_written']))
                self.packetslab.setText("Packets written: {:d}".format(data['_deviceinfo']['packets_written']))
        except:
            logger.info(funcname, exc_info=True)


        #self.text.insertPlainText(str(data['_deviceinfo']['data']))
        
