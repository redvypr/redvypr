import datetime
import pytz
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import qtawesome
import time
import numpy as np
import serial
import serial.tools.list_ports
import logging
import sys
import copy
import threading
import pydantic
import redvypr
from . import hexflasher
from . import tar
from redvypr.devices.sensors.generic_sensor.calibrationWidget import GenericSensorCalibrationWidget, CalibrationsTable
#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('sensorconfig')
logger.setLevel(logging.DEBUG)


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Configuration of a sensor: Reads to and write from the flash of a compatible device, reads/write parameter calibrations'
    gui_tablabel_display: str = 'Sensorconfig'

class DeviceCustomConfig(pydantic.BaseModel):
    baud: int = 115200
    parity: str = serial.PARITY_NONE
    stopbits: int = serial.STOPBITS_ONE
    bytesize: int = serial.EIGHTBITS
    dt_poll: float = 0.05
    chunksize: int = pydantic.Field(default=1000, description='The maximum amount of bytes read with one chunk')
    packetdelimiter: str = pydantic.Field(default='\n', description='The delimiter to distinuish packets')
    comport: str = ''


redvypr_devicemodule = True


class HexSpinBox(QtWidgets.QSpinBox):
    def __init__(self, *args):
        super().__init__(*args)
        self.setMinimum(0)
        self.setMaximum(1000000)
        self.setPrefix("0x")
        self.setDisplayIntegerBase(16)

def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname)
    return None


class RedvyprDeviceWidget(QtWidgets.QWidget):
    def __init__(self, device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.__comqueue = queue.Queue()
        self.initwidget = QtWidgets.QWidget()
        self.initlayout = QtWidgets.QVBoxLayout(self.initwidget)
        self.tabwidget = QtWidgets.QTabWidget()
        self.calibration = FirmwareCalibrationsWidget(comqueue=self.__comqueue)
        self.tabwidget.addTab(self.calibration,'Calibration coefficients')
        self.hexflasher = HexflashWidget(comqueue=self.__comqueue)
        self.device = device
        self.dhffl = None
        self.serialwidget = QtWidgets.QWidget()
        self.init_serialwidget()
        self.label = QtWidgets.QLabel("Serial device")

        # Command and devictreewidget
        self.commandwidget = QtWidgets.QWidget()
        self.commandwidget.setEnabled(False)
        self.init_commandwidget()
        self.devicetree = QtWidgets.QTreeWidget()

        self.initlayout.addWidget(self.label)
        self.initlayout.addWidget(self.serialwidget)
        self.initlayout.addWidget(self.commandwidget)
        self.initlayout.addWidget(self.devicetree)
        self.initlayout.addStretch()
        layout.addWidget(self.tabwidget)
        self.tabwidget.addTab(self.initwidget, 'Serial setup')
        self.tabwidget.addTab(self.hexflasher, 'Flashing Firmware')
        self.tabwidget.addTab(self.calibration, 'Calibration coefficients')
        #layout.addWidget(self.startbtn)
        #layout.addWidget(self.stopbtn)

        self.update_device_tree()

    def init_commandwidget(self):
        layout = QtWidgets.QGridLayout(self.commandwidget)
        self.query_button = QtWidgets.QPushButton('Query devices')
        self.query_button.clicked.connect(self.query_devices)
        layout.addWidget(self.query_button, 0, 0)

    def init_serialwidget(self):
        """Fills the serial widget with content
        """
        layout = QtWidgets.QGridLayout(self.serialwidget)
        # Serial baud rates
        baud = [300, 600, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 576000, 921600]
        self._combo_serial_devices = QtWidgets.QComboBox()
        #self._combo_serial_devices.currentIndexChanged.connect(self._serial_device_changed)
        self._combo_serial_baud = QtWidgets.QComboBox()
        for b in baud:
            self._combo_serial_baud.addItem(str(b))

        self._combo_serial_baud.setCurrentIndex(9)
        # creating a line edit
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)

        # setting line edit
        self._combo_serial_baud.setLineEdit(edit)

        self._combo_parity = QtWidgets.QComboBox()
        self._combo_parity.addItem('None')
        self._combo_parity.addItem('Odd')
        self._combo_parity.addItem('Even')
        self._combo_parity.addItem('Mark')
        self._combo_parity.addItem('Space')

        self._combo_stopbits = QtWidgets.QComboBox()
        self._combo_stopbits.addItem('1')
        self._combo_stopbits.addItem('1.5')
        self._combo_stopbits.addItem('2')

        self._combo_databits = QtWidgets.QComboBox()
        self._combo_databits.addItem('8')
        self._combo_databits.addItem('7')
        self._combo_databits.addItem('6')
        self._combo_databits.addItem('5')

        self._button_serial_openclose = QtWidgets.QPushButton('Open')
        self._button_serial_openclose.setCheckable(True)
        self._button_serial_openclose.clicked.connect(self.start_clicked)

        # Check for serial devices and list them
        for comport in serial.tools.list_ports.comports():
            self._combo_serial_devices.addItem(str(comport.device))

        #How to differentiate packets
        self._packet_ident_lab = QtWidgets.QLabel('Packet identification')
        self._packet_ident = QtWidgets.QComboBox()
        self._packet_ident.addItem('newline \\n')
        self._packet_ident.addItem('newline \\r\\n')
        self._packet_ident.addItem('None')
        # Max packetsize
        self._packet_size_lab = QtWidgets.QLabel("Maximum packet size")
        self._packet_size_lab.setToolTip(
            'The number of received bytes after which a packet is sent.\n Add 0 for no size check')
        onlyInt = QtGui.QIntValidator()
        self._packet_size = QtWidgets.QLineEdit()
        self._packet_size.setValidator(onlyInt)
        self._packet_size.setText('0')
        #self.packet_ident

        layout.addWidget(self._packet_ident, 0, 1)
        layout.addWidget(self._packet_ident_lab, 0, 0)
        layout.addWidget(self._packet_size_lab, 0, 2)
        layout.addWidget(self._packet_size, 0, 3)
        layout.addWidget(QtWidgets.QLabel('Serial device'), 1, 0)
        layout.addWidget(self._combo_serial_devices, 2, 0)
        layout.addWidget(QtWidgets.QLabel('Baud'), 1, 1)
        layout.addWidget(self._combo_serial_baud, 2, 1)
        layout.addWidget(QtWidgets.QLabel('Parity'), 1, 2)
        layout.addWidget(self._combo_parity, 2, 2)
        layout.addWidget(QtWidgets.QLabel('Databits'), 1, 3)
        layout.addWidget(self._combo_databits, 2, 3)
        layout.addWidget(QtWidgets.QLabel('Stopbits'), 1, 4)
        layout.addWidget(self._combo_stopbits, 2, 4)
        layout.addWidget(self._button_serial_openclose, 2, 5)


    def query_devices(self):
        if self.dhffl is None:
            logger.warning('Open serial port first')
        else:
            mac_sensors = self.dhffl.ping_devices()
            if mac_sensors is not None:
                for mac in self.dhffl.devices_mac:
                    mac_sensor = self.dhffl.devices_mac[mac]
                    print('Mac sensor', mac_sensor)
                    logger.debug('Getting config of device')
                    self.dhffl.get_config_of_device(mac_sensor.macstr)
                    #self.logger.debug('Getting calibration config of device')
                    #self.dhffl.get_calibration_of_device(mac_sensor.macstr)
                time.sleep(0.1)
                for mac in self.dhffl.devices_mac:
                    mac_sensor = self.dhffl.devices_mac[mac]
                    print('Mac sensor', mac_sensor)
                    logger.debug('Getting sample interval')
                    macobject = self.dhffl.get_sampling_period_of_device(mac_sensor.macstr)
                    if macobject is not None:
                        logger.debug('Found sampling period')

                    macobject = self.dhffl.get_calibration_of_device(mac_sensor.macstr)
                    if macobject is not None:
                        logger.debug('Found calibrations, updating coeff tables')
                        # updating tables
                        calibrations = macobject.calibrations
                        #calibrations_edit = copy.deepcopy(macobject.calibrations)
                        calibrations_edit = {}
                        for key in macobject.calibrations.keys():
                            calib = macobject.calibrations[key]
                            calibrations_edit[key] = None
                            if calib not in self.calibration.calibrations_all:
                                self.calibration.calibrations_all.append(calib)

                        # Update calibration table
                        self.calibration.calibwidget.update_calibration_all_table(self.calibration.calibrations_all)
                        self.calibration.calibwidget.update_calibration_table(self.calibration.calibtablename_firmware, calibrations)
                        self.calibration.calibwidget.update_calibration_table(self.calibration.calibtablename_edit, calibrations_edit)
                        self.calibration.macobject_choosen = macobject

                print('Found devices {}'.format(mac_sensors.keys()))
                self.calibration.update_device_tree()
                self.hexflasher.update_device_tree()
                self.update_device_tree()

    def update_device_tree(self):
        logger.debug('Updating device tree')
        #self.devicetree.currentItemChanged.disconnect(self.qtreewidget_item_changed)
        self.devicetree.clear()
        self.devicetree.setColumnCount(10)
        # self.devicetree.setHeaderHidden(True)
        self.devicetree.setHeaderLabels(
            ['Device', 'Firmware status', 'Version', 'Bootloader version', 'Board ID', 'Bootflag', 'Boot countdown','Flagsample','Sample counter','Sampling period'])
        root = self.devicetree.invisibleRootItem()
        if self.dhffl is None:
            logger.warning('No serial connection yet')
        else:
            for macstr in self.dhffl.devices_mac.keys():
                if self.dhffl.devices_mac[macstr].parents is None:
                    mac = self.dhffl.devices_mac[macstr]
                    bootloader_version = mac.bootloader_version
                    if bootloader_version is None:
                        bootloader_version = 'Inactive'
                    version = mac.version
                    brdid = mac.brdid
                    status = mac.status
                    bootflag = mac.bootflag
                    countdown = mac.countdown
                    sample_counter = mac.sample_counter
                    sample_period = mac.sample_period
                    flagsample = mac.flagsample
                    itm = QtWidgets.QTreeWidgetItem(
                        [macstr, status, version, bootloader_version, brdid, str(bootflag), str(countdown),str(flagsample), str(sample_counter),str(sample_period)])
                    root.addChild(itm)
                else:
                    parentitm = root
                    for m in self.dhffl.devices_mac[macstr].parents:
                        mactmp = self.dhffl.devices_mac[m]
                        bootloader_version = mactmp.bootloader_version
                        if bootloader_version is None:
                            bootloader_version = 'Inactive'
                        version = mactmp.version
                        brdid = mactmp.brdid
                        status = mactmp.status
                        bootflag = mactmp.bootflag
                        countdown = mactmp.countdown
                        itm = QtWidgets.QTreeWidgetItem(
                            [m, status, version, bootloader_version, brdid, str(bootflag), str(countdown)])
                        parentitm.addChild(itm)
                        parentitm = itm

        self.devicetree.expandAll()
        self.devicetree.resizeColumnToContents(0)
        self.devicetree.sortByColumn(0, QtCore.Qt.AscendingOrder)
        #self.devicetree.currentItemChanged.connect(self.qtreewidget_item_changed)

    def start_clicked(self):
        logger.debug('Start clicked')
        #print('Start clicked')
        button = self._button_serial_openclose
        print('ischecked',button.isChecked())

        #if ('Open' in button.text()):
        if button.isChecked():
            serial_name = str(self._combo_serial_devices.currentText())
            serial_baud = int(self._combo_serial_baud.currentText())
            self.device.custom_config.comport = serial_name
            self.device.custom_config.baud = serial_baud
            stopbits = self._combo_stopbits.currentText()
            if (stopbits == '1'):
                self.device.custom_config.stopbits = serial.STOPBITS_ONE
            elif (stopbits == '1.5'):
                self.device.custom_config.stopbits = serial.STOPBITS_ONE_POINT_FIVE
            elif (stopbits == '2'):
                self.device.custom_config.stopbits = serial.STOPBITS_TWO

            databits = int(self._combo_databits.currentText())
            self.device.custom_config.bytesize = databits

            parity = self._combo_parity.currentText()
            if (parity == 'None'):
                self.device.custom_config.parity = serial.PARITY_NONE
            elif (parity == 'Even'):
                self.device.custom_config.parity = serial.PARITY_EVEN
            elif (parity == 'Odd'):
                self.device.custom_config.parity = serial.PARITY_ODD
            elif (parity == 'Mark'):
                self.device.custom_config.parity = serial.PARITY_MARK
            elif (parity == 'Space'):
                self.device.custom_config.parity = serial.PARITY_SPACE

            logger.info('Starting dhffl at comport {:s}'.format(serial_name))
            try:
                self.dhffl = hexflasher.dhf_flasher(serial_name, baud=serial_baud)
            except:
                logger.warning('Could not open serial port',exc_info=True)
                button.setChecked(False)
                return

            self.statuswidget = SerialStatusWidget(dhffl=self.dhffl, data_queue=self.dhffl.serial_queue_write,
                                                   comqueue=self.__comqueue)
            self.statuswidget.statuswidget_queue.put('test')
            logger.debug('Starting hexflasher')
            self.hexflasher.start(self.dhffl, statuswidget=self.statuswidget)
            logger.debug('Starting calibration')

            self.calibration.start(self.dhffl, statuswidget=self.statuswidget)
            self.tabwidget.addTab(self.statuswidget, 'Serial status')
            self.commandwidget.setEnabled(True)
            button.setText('Close')
        else:
            self.stop_clicked()
            self.commandwidget.setEnabled(False)

    def stop_clicked(self):
        logger.debug('Stop clicked')
        button = self._button_serial_openclose
        self.hexflasher.stop()
        index = self.tabwidget.indexOf(self.statuswidget)
        self.tabwidget.removeTab(index)
        self.statuswidget.close()
        button.setText('Open')


class SerialStatusWidget(QtWidgets.QWidget):
    def __init__(self, dhffl=None, data_queue=None, comqueue=None):
        super(QtWidgets.QWidget, self).__init__()
        self.logger = logging.getLogger('SerialStatusWidget')
        self.logger.setLevel(logging.DEBUG)
        #self.layout = QtWidgets.QGridLayout(self)
        self.dhffl = dhffl
        self.comqueue=comqueue

        self.statuswidget = self
        self.statuswidget_layout = QtWidgets.QVBoxLayout(self.statuswidget)
        self.statuswidget_progress = QtWidgets.QProgressBar()
        self.statuswidget_layout.addWidget(self.statuswidget_progress)
        self.statuswidget_progress_label = QtWidgets.QLabel('Status')
        self.statuswidget_layout.addWidget(self.statuswidget_progress_label)
        self.statuswidget_cancel = QtWidgets.QPushButton('Cancel')
        self.statuswidget_cancel.clicked.connect(self.statuswidget_cancel_clicked)
        self.statuswidget_layout.addWidget(self.statuswidget_cancel)
        self.statuswidget_text = QtWidgets.QPlainTextEdit()
        self.statuswidget_layout.addWidget(self.statuswidget_text)
        self.statuswidget_com = QtWidgets.QLineEdit()
        self.statuswidget_layout.addWidget(self.statuswidget_com)
        self.statuswidget_com_send = QtWidgets.QPushButton('Send')
        self.statuswidget_com_send.clicked.connect(self.send_command_clicked)
        self.statuswidget_layout.addWidget(self.statuswidget_com_send)
        self.statuswidget_queue = data_queue
        self.statuswidget_timer = QtCore.QTimer()
        self.statuswidget_timer.timeout.connect(self.update_statuswidget)
        self.statuswidget_timer.start(200)

    def send_command_clicked(self):
        COMMAND = self.statuswidget_com.text()
        self.logger.debug('Send command {}'.format(COMMAND))
        lineend = b'\n'
        self.dhffl.serial.write(COMMAND.encode('utf-8') + lineend)
        time.sleep(0.1)
        nreturn = self.dhffl.serial.inWaiting()
        nlines_max = 100
        if nreturn > 0:
            for i in range(nlines_max):
                try:
                    data = self.dhffl.serial.readline()
                    if len(data) == 0:
                        break
                except Exception as e:
                    continue


    def statuswidget_cancel_clicked(self):
        self.logger.info('Cancelling')
        self.comqueue.put('Cancel')

    def update_statuswidget(self):
        #print('Hallo')
        while True:
            try:
                data = self.statuswidget_queue.get_nowait()
            except:
                break

            #print('data',data)
            if isinstance(data, list):
                tu = data[0]
                td = datetime.datetime.fromtimestamp(tu)
                direction = data[1]
                serial_data = data[2]
                datastr = direction + ':' + td.isoformat() + '\t' + str(serial_data) + '\n'
                self.statuswidget_text.insertPlainText(datastr)
                cursor = self.statuswidget_text.textCursor()
                cursor.movePosition(cursor.End)
                self.statuswidget_text.setTextCursor(cursor)
            elif isinstance(data, dict):
                #infodata = {'status': 'write', 'written': ihexd, 'write_total': len(hexdata)}
                if data['status'] == 'write':
                    try:
                        progress = int(data['written'] / data['write_total'] * 100)
                        self.statuswidget_progress.setValue(progress)
                    except:
                        pass
                    try:
                        message = data['message']
                    except:
                        message = 'Writing'
                    self.statuswidget_progress_label.setText(message)
                elif data['status'] == 'read':
                    progress = int(data['read'] / data['read_total'] * 100)
                    self.statuswidget_progress.setValue(progress)
                    try:
                        message = data['message']
                    except:
                        message = 'Reading'
                    self.statuswidget_progress_label.setText(message)
                else:
                    try:
                        message = data['message']
                    except:
                        continue
                    self.statuswidget_progress_label.setText(message)
            else:
                self.logger.debug('Statuswidget, got data:{}'.format(data))

class CalibrationsWriteToSensorWidget(QtWidgets.QWidget):
    def __init__(self, *args, calibrations=None, macobject=None, dhffl=None, comqueue=None):
        funcname = __name__ + '__init__()'
        super().__init__(*args)
        self.logger = logging.getLogger('CalibrationsWriteToSensorWidget')
        self.logger.setLevel(logging.DEBUG)
        self.__comqueue = comqueue
        self.calibrations = calibrations
        self.macobject = macobject
        self.dhffl = dhffl

        # self.dhffl
        for para0 in self.calibrations:
            self.cal0 = self.calibrations[para0]
            break

        meta_data = {}
        meta_data['id'] = self.cal0.calibration_id
        meta_data['date'] = self.cal0.date.isoformat()
        meta_data['uuid'] = self.cal0.calibration_uuid
        meta_data['comment'] = self.cal0.comment
        self.layout = QtWidgets.QGridLayout(self)
        self.cal_meta = QtWidgets.QWidget()
        self.cal_meta_layout = QtWidgets.QFormLayout(self.cal_meta)
        self.cal_meta_lineedits = {}
        file_format_check = {'id':'Calibration ID', 'uuid':'Calibration UUID', 'comment':'Comment', 'date':'Calibration date'}
        for format_check in file_format_check:
            self.cal_meta_lineedits[format_check] = QtWidgets.QLineEdit()
            self.cal_meta_lineedits[format_check].setText(str(meta_data[format_check]))
            self.cal_meta_layout.addRow(file_format_check[format_check],self.cal_meta_lineedits[format_check])
            self.cal_meta_lineedits[format_check].textChanged.connect(self.__update_calcommands__)

        # Write buttons
        self.write_button = QtWidgets.QPushButton('Write to sensor')
        self.write_button.clicked.connect(self.__write_clicked__)
        self.show_write_button = QtWidgets.QPushButton('Show files to write')
        self.show_write_button.clicked.connect(self.__write_clicked__)
        self.result_text = QtWidgets.QPlainTextEdit()

        self.layout.addWidget(self.cal_meta, 0, 0)
        self.layout.addWidget(self.result_text, 1, 0)
        self.layout.addWidget(self.show_write_button, 2, 0)
        self.layout.addWidget(self.write_button, 3, 0)

        self.__update_calcommands__()

    def __update_calcommands__(self):
        meta_data = {}
        for key in self.cal_meta_lineedits.keys():
            metastr = str(self.cal_meta_lineedits[key].text())
            if len(metastr) > 0:
                meta_data[key] = metastr
            else:
                meta_data[key] = None

        calcommands = self.macobject.create_calibration_commands(self.calibrations, calibration_id=meta_data['id'],
                                                                 date=meta_data['date'],
                                                                 calibration_uuid=meta_data['uuid'], comment=meta_data['comment'])

        self.result_text.clear()
        for calcommand in calcommands:
            self.result_text.appendPlainText(str(calcommand[:-1]))  # Without the newline

        cursor = self.result_text.textCursor()
        cursor.movePosition(cursor.Start)
        self.result_text.setTextCursor(cursor)
        self.calcommands = calcommands

        print('Calcommands', calcommands)

    def __write_clicked__(self):
        print('Writing ...')
        self.__update_calcommands__()
        if self.dhffl is not None and self.macobject is not None:
            macstr = self.macobject.macstr
            thread_args = (self.calcommands, None, self.__comqueue)

            writethread = threading.Thread(target=self.dhffl.write_calibrations, args=thread_args)
            self.logger.info('Starting write calibration thread')
            writethread.start()

        #for calcommand in self.calcommands:
        #    print('Writing')
        #    logstr = 'Writing:' + str(calcommand[:-1])
        #    self.result_text.appendPlainText(logstr)  # Without the newline
        #    self.dhffl.write_data(calcommand)
        #    cursor = self.result_text.textCursor()
        #    cursor.movePosition(cursor.End)
        #    self.result_text.setTextCursor(cursor)
        #    time.sleep(0.2)


class FirmwareCalibrationsWidget(QtWidgets.QWidget):
    def __init__(self, dhffl=None, sensor = None, comqueue=None):
        funcname = __name__ + '.__init__():'
        super(QtWidgets.QWidget, self).__init__()
        self.__comqueue = comqueue
        self.logger = logging.getLogger('SensorCalibrationWidget')
        self.logger.setLevel(logging.DEBUG)
        self.layout = QtWidgets.QGridLayout(self)
        if sensor is None:
            self.logger.debug(funcname + 'Adding standard tar sensor')
            self.sensor = tar.TarSensor()

        self.dhffl = dhffl

        self.query_button = QtWidgets.QPushButton('Query devices')
        self.query_button.clicked.connect(self.query_devices)
        self.choose_calibrations_button = QtWidgets.QPushButton('Write calibrations to device')
        self.choose_calibrations_button.clicked.connect(self.write_calibrations_to_device)
        # List of calibrations
        self.calibrations_all = []
        self.devicetree = QtWidgets.QTreeWidget()
        self.devicetree.currentItemChanged.connect(self.qtreewidget_item_changed)
        self.calibtablename_edit = 'Edit calibrations'
        self.calibtablename_firmware = 'Calibrations Sensorfirmware'
        calibrations_sensor = {self.calibtablename_firmware:[], self.calibtablename_edit:[]}
        calibrations_sensor_options = {self.calibtablename_firmware: {'editable':False}, self.calibtablename_edit: {'editable':True}}
        self.calibwidget = GenericSensorCalibrationWidget(calibrations_all=self.calibrations_all, calibrations_sensor=calibrations_sensor, calibrations_sensor_options=calibrations_sensor_options)

        self.layout.addWidget(self.query_button, 0, 0)
        self.layout.addWidget(self.choose_calibrations_button, 1, 0)
        self.layout.addWidget(self.devicetree, 2, 0)
        self.layout.addWidget(self.calibwidget, 3, 0)

        self.update_device_tree()

    def write_calibrations_to_device(self):
        funcname = __name__ + '.write_calibrations_to_device():'
        logger.debug(funcname)
        try:
            macobject = self.macobject_choosen
        except:
            self.logger.warning('No object choosen to write data to')

        calibrations = self.calibwidget.calibrationsTable[self.calibtablename_edit].calibrations
        self.__calwritewidget__ = CalibrationsWriteToSensorWidget(calibrations=calibrations, macobject=macobject, dhffl=self.dhffl, comqueue=self.__comqueue)
        self.__calwritewidget__.setWindowTitle('Calibrations to sensor {}'.format(macobject.macstr))
        self.__calwritewidget__.show()

    def start(self, dhffl, statuswidget):
        self.logger.info('Starting')
        self.dhffl = dhffl
        # self.create_statuswidget()  # This will be done with a button later
        self.statuswidget = statuswidget

    def update_device_tree(self):
        self.logger.debug('Updating device tree')
        self.devicetree.currentItemChanged.disconnect(self.qtreewidget_item_changed)
        self.devicetree.clear()
        self.devicetree.setColumnCount(7)
        # self.devicetree.setHeaderHidden(True)
        self.devicetree.setHeaderLabels(
            ['Device', 'Firmware status', 'Version', 'Bootloader version', 'Board ID', 'Bootflag', 'Boot countdown'])
        root = self.devicetree.invisibleRootItem()
        if self.dhffl is None:
            self.logger.warning('No serial connection yet')
        else:
            for macstr in self.dhffl.devices_mac.keys():
                if self.dhffl.devices_mac[macstr].parents is None:
                    mac = self.dhffl.devices_mac[macstr]
                    bootloader_version = mac.bootloader_version
                    if bootloader_version is None:
                        bootloader_version = 'Inactive'
                    version = mac.version
                    brdid = mac.brdid
                    status = mac.status
                    bootflag = mac.bootflag
                    countdown = mac.countdown
                    itm = QtWidgets.QTreeWidgetItem(
                        [macstr, status, version, bootloader_version, brdid, str(bootflag), str(countdown)])
                    root.addChild(itm)
                else:
                    parentitm = root
                    for m in self.dhffl.devices_mac[macstr].parents:
                        mactmp = self.dhffl.devices_mac[m]
                        bootloader_version = mactmp.bootloader_version
                        if bootloader_version is None:
                            bootloader_version = 'Inactive'
                        version = mactmp.version
                        brdid = mactmp.brdid
                        status = mactmp.status
                        bootflag = mactmp.bootflag
                        countdown = mactmp.countdown
                        itm = QtWidgets.QTreeWidgetItem(
                            [m, status, version, bootloader_version, brdid, str(bootflag), str(countdown)])
                        parentitm.addChild(itm)
                        parentitm = itm

        self.devicetree.expandAll()
        self.devicetree.resizeColumnToContents(0)
        self.devicetree.sortByColumn(0, QtCore.Qt.AscendingOrder)
        self.devicetree.currentItemChanged.connect(self.qtreewidget_item_changed)

    def qtreewidget_item_changed(self, itemnew, itemold):
        self.logger.debug('Itemchanged {} {}'.format(itemnew, itemold))
        macstr = itemnew.text(0)
        nchilds = itemnew.childCount()
        if nchilds == 0:
            self.mac_sensor = self.dhffl.devices_mac[macstr]
            print('Macstr', macstr, self.mac_sensor)
            self.device_changed()

    def query_devices(self):
        if self.dhffl is None:
            logger.warning('Open serial port first')
        else:
            mac_sensors = self.dhffl.ping_devices()
            if mac_sensors is not None:
                for mac in self.dhffl.devices_mac:
                    mac_sensor = self.dhffl.devices_mac[mac]
                    print('Mac sensor', mac_sensor)
                    self.logger.debug('Getting config of device')
                    self.dhffl.get_config_of_device(mac_sensor.macstr)
                    #self.logger.debug('Getting calibration config of device')
                    #self.dhffl.get_calibration_of_device(mac_sensor.macstr)
                time.sleep(0.1)
                for mac in self.dhffl.devices_mac:
                    mac_sensor = self.dhffl.devices_mac[mac]
                    print('Mac sensor', mac_sensor)
                    self.logger.debug('Getting calibration config of device')
                    macobject = self.dhffl.get_calibration_of_device(mac_sensor.macstr)
                    if macobject is not None:
                        logger.debug('Found calibrations, updating coeff tables')
                        # updating tables
                        calibrations = macobject.calibrations
                        #calibrations_edit = copy.deepcopy(macobject.calibrations)
                        calibrations_edit = {}
                        for key in macobject.calibrations.keys():
                            calib = macobject.calibrations[key]
                            calibrations_edit[key] = None
                            if calib not in self.calibrations_all:
                                self.calibrations_all.append(calib)

                        self.calibwidget.update_calibration_all_table(self.calibrations_all)
                        self.calibwidget.update_calibration_table(self.calibtablename_firmware, calibrations)
                        self.calibwidget.update_calibration_table(self.calibtablename_edit, calibrations_edit)
                        self.macobject_choosen = macobject

                print('Found devices {}'.format(mac_sensors.keys()))
                self.update_device_tree()


class HexflashWidget(QtWidgets.QWidget):
    def __init__(self, comqueue):
        super(QtWidgets.QWidget, self).__init__()
        self.dhffl = None
        self.inq = queue.Queue()
        self.outq = queue.Queue()

        self.__comqueue = comqueue
        self.command_buttons_enable = [] # List of command buttons that are only enabled if a serial device is open
        self.flash_buttons_enable = []  # List of command buttons that are only enabled if a serial device is open

        self.logger = logging.getLogger('HexflashWidget')
        self.logger.setLevel(logging.DEBUG)
        self.layout = QtWidgets.QGridLayout(self)

        self.devicetree = QtWidgets.QTreeWidget()
        self.devicetree.currentItemChanged.connect(self.qtreewidget_item_changed)
        self.reset_button = QtWidgets.QPushButton('Reset')
        self.command_buttons_enable.append(self.reset_button)
        self.reset_button.clicked.connect(self.reset_clicked)

        self.startbootmon_button = QtWidgets.QPushButton('Start Bootmonitor')
        self.command_buttons_enable.append(self.startbootmon_button)
        self.startbootmon_button.clicked.connect(self.start_bootmonitor_clicked)

        self.startsample_button = QtWidgets.QPushButton('Startsample')
        self.command_buttons_enable.append(self.startsample_button)
        self.stopsample_button = QtWidgets.QPushButton('Stopsample')
        self.command_buttons_enable.append(self.stopsample_button)
        self.startsample_button.clicked.connect(self.startstopsample_clicked)
        self.stopsample_button.clicked.connect(self.startstopsample_clicked)

        # read
        self.read_button = QtWidgets.QPushButton('Read')
        self.flash_buttons_enable.append(self.read_button)
        self.read_button.clicked.connect(self.read_clicked)
        self.read_filename = QtWidgets.QWidget()
        self.read_filename_layout = QtWidgets.QHBoxLayout(self.read_filename)
        self.filename_read_edit = QtWidgets.QLineEdit("")
        iconname = "fa5.folder-open"
        folder_icon = qtawesome.icon(iconname)
        self.filename_read_button = QtWidgets.QPushButton()
        self.filename_read_button.setIcon(folder_icon)
        self.read_filename_layout.addWidget(self.filename_read_edit)
        self.read_filename_layout.addWidget(self.filename_read_button)
        # read address range
        self.read_address_range = QtWidgets.QWidget()
        self.read_address_range_layout = QtWidgets.QHBoxLayout(self.read_address_range)
        self.read_address_start = HexSpinBox()
        self._boot_load_offset = 0x5000
        self._flashsize_sam4l_generic = 0x40000
        self.read_address_start.setValue(self._boot_load_offset)
        self.read_address_start.valueChanged.connect(self.automatic_filename_changed)
        self.read_address_end = HexSpinBox()
        self.read_address_end.setValue(self._flashsize_sam4l_generic)
        self.read_address_end.valueChanged.connect(self.automatic_filename_changed)
        self.read_radio_all = QtWidgets.QRadioButton('All')
        self.read_radio_range = QtWidgets.QRadioButton('Address range')
        self.read_radio_all.setChecked(True)
        self.read_radio_all.toggled.connect(self.automatic_filename_changed)
        self.read_radio_range.toggled.connect(self.automatic_filename_changed)
        self.read_automatic_filename = QtWidgets.QCheckBox('Automatic Filename')
        self.read_automatic_filename.setChecked(True)
        self.read_automatic_filename.stateChanged.connect(self.automatic_filename_changed)
        self.read_address_range_layout.addWidget(self.read_automatic_filename)
        self.read_address_range_layout.addWidget(self.read_radio_all)
        self.read_address_range_layout.addWidget(self.read_radio_range)
        self.read_address_range_layout.addWidget(self.read_address_start)
        self.read_address_range_layout.addWidget(self.read_address_end)

        self.write_filename = QtWidgets.QWidget()
        self.write_filename_layout = QtWidgets.QHBoxLayout(self.write_filename)
        self.filename_write_edit = QtWidgets.QLineEdit("")
        iconname = "fa5.folder-open"
        folder_icon = qtawesome.icon(iconname)
        self.filename_write_button = QtWidgets.QPushButton()
        self.filename_write_button.setIcon(folder_icon)
        self.filename_write_button.clicked.connect(self.write_file_choose_clicked)
        self.write_filename_layout.addWidget(self.filename_write_edit)
        self.write_filename_layout.addWidget(self.filename_write_button)

        # Create flag_widgets
        self.flag_widgets = QtWidgets.QWidget()
        self.flag_widgets_layout = QtWidgets.QGridLayout(self.flag_widgets)
        self.flag_widgets_layout.addWidget(QtWidgets.QLabel('Bootflag'), 0, 0, 1, 2)
        self.flag_widgets_layout.addWidget(QtWidgets.QLabel('Countdown'), 0, 2, 1, 2)
        self.flag_widgets_boot_combo = QtWidgets.QComboBox()
        self.flag_widgets_boot_combo.addItem('0')
        self.flag_widgets_boot_combo.addItem('1')
        self.flag_widgets_layout.addWidget(self.flag_widgets_boot_combo, 1, 0)
        self.flag_widgets_boot_set = QtWidgets.QPushButton('Set')
        self.command_buttons_enable.append(self.flag_widgets_boot_set)
        self.flag_widgets_boot_set.clicked.connect(self.set_flag_clicked)
        self.flag_widgets_layout.addWidget(self.flag_widgets_boot_set, 1, 1)
        self.flag_widgets_countdown_spin = QtWidgets.QSpinBox()
        self.flag_widgets_countdown_spin.setMinimum(0)
        self.flag_widgets_countdown_spin.setMaximum(255)
        self.flag_widgets_countdown_spin.setValue(5)
        self.flag_widgets_layout.addWidget(self.flag_widgets_countdown_spin, 1, 2)
        self.flag_widgets_countdown_set = QtWidgets.QPushButton('Set')
        self.command_buttons_enable.append(self.flag_widgets_countdown_set)
        self.flag_widgets_countdown_set.clicked.connect(self.set_flag_clicked)
        self.flag_widgets_layout.addWidget(self.flag_widgets_countdown_set, 1, 3)

        self.write_button = QtWidgets.QPushButton('Flash device')
        self.write_button.clicked.connect(self.write_clicked)
        self.flash_buttons_enable.append(self.write_button)

        self.query_button = QtWidgets.QPushButton('Query devices')
        self.query_button.clicked.connect(self.ping_devices)

        self.command_button_widget = QtWidgets.QWidget()
        self.command_button_widget_layout = QtWidgets.QHBoxLayout(self.command_button_widget)
        self.command_button_widget_layout.addWidget(self.startbootmon_button)
        self.command_button_widget_layout.addWidget(self.reset_button)
        self.command_button_widget_layout.addWidget(self.startsample_button)
        self.command_button_widget_layout.addWidget(self.stopsample_button)

        self.layout.addWidget(self.query_button, 0, 0)
        self.layout.addWidget(self.command_button_widget, 0, 1, 1, -1)
        self.layout.addWidget(self.flag_widgets, 1, 1, 1, 2)
        self.layout.addWidget(self.devicetree, 1, 0, -1, 1)
        self.layout.addWidget(self.read_button, 2, 1)
        self.layout.addWidget(self.read_filename, 2, 2)
        self.layout.addWidget(self.read_address_range, 3, 1, 1, -1)
        self.layout.addWidget(self.write_button, 4, 1)
        self.layout.addWidget(self.write_filename, 4, 2)
        self.mac_sensor = None

        for b in self.command_buttons_enable:
            b.setEnabled(False)

        self.automatic_filename_changed()
        self.update_device_tree()


    def create_statuswidget_legacy(self):
        """
        Creating a widget that shows the serial datastream
        """
        if self.dhffl is not None:
            self.statuswidget = QtWidgets.QWidget()
            self.statuswidget_layout = QtWidgets.QVBoxLayout(self.statuswidget)
            self.statuswidget_progress = QtWidgets.QProgressBar()
            self.statuswidget_layout.addWidget(self.statuswidget_progress)
            self.statuswidget_progress_label = QtWidgets.QLabel('Status')
            self.statuswidget_layout.addWidget(self.statuswidget_progress_label)
            self.statuswidget_cancel = QtWidgets.QPushButton('Cancel')
            self.statuswidget_cancel.clicked.connect(self.statuswidget_cancel_clicked)
            self.statuswidget_layout.addWidget(self.statuswidget_cancel)
            self.statuswidget_text = QtWidgets.QPlainTextEdit()
            self.statuswidget_layout.addWidget(self.statuswidget_text)
            self.statuswidget_com = QtWidgets.QLineEdit()
            self.statuswidget_layout.addWidget(self.statuswidget_com)
            self.statuswidget_com_send = QtWidgets.QPushButton('Send')
            self.statuswidget_com_send.clicked.connect(self.send_command_clicked)
            self.statuswidget_layout.addWidget(self.statuswidget_com_send)
            self.statuswidget_queue = self.dhffl.serial_queue_write
            self.statuswidget_timer = QtCore.QTimer()
            self.statuswidget_timer.timeout.connect(self.update_statuswidget)
            self.statuswidget_timer.start(200)

    def startstopsample_clicked(self):
        b = self.sender()
        macobject = self.mac_sensor
        if b == self.startsample_button:
            self.logger.debug('Start sample, not implemented yet')
            COMMAND = "${:s}!,startsample\n".format(macobject.macstr)
            self.dhffl.serial.write(COMMAND.encode('utf-8'))
        else:
            self.logger.debug('Stop sample, not implemented yet')
            COMMAND = "${:s}!,stopsample\n".format(macobject.macstr)
            self.dhffl.serial.write(COMMAND.encode('utf-8'))

        nlines_max = 5
        for i in range(nlines_max):
            try:
                data = self.dhffl.serial.readline()
                if len(data) == 0:
                    continue
            except Exception as e:
                continue
    def send_command_clicked(self):
        COMMAND = self.statuswidget_com.text()
        self.logger.debug('Send command {}'.format(COMMAND))
        lineend = b'\n'
        self.dhffl.serial.write(COMMAND.encode('utf-8') + lineend)
        time.sleep(0.1)
        nreturn = self.dhffl.serial.inWaiting()
        nlines_max = 100
        if nreturn > 0:
            for i in range(nlines_max):
                try:
                    data = self.dhffl.serial.readline()
                    if len(data) == 0:
                        break
                except Exception as e:
                    continue

    def qtreewidget_item_changed(self,itemnew,itemold):
        self.logger.debug('Itemchanged {} {}'.format(itemnew,itemold))
        macstr = itemnew.text(0)
        nchilds = itemnew.childCount()
        if nchilds == 0:
            self.mac_sensor = self.dhffl.devices_mac[macstr]
            print('Macstr', macstr, self.mac_sensor)
            self.device_changed()

    def set_flag_clicked(self):
        self.logger.debug('Set flag clicked')
        bootflag = int(self.flag_widgets_boot_combo.currentText())
        countdown = int(self.flag_widgets_countdown_spin.value())
        mac = self.dhffl.sendFlag(self.mac_sensor, bootflag=bootflag, countdown=countdown)
        time.sleep(0.1)
        self.dhffl.get_config_of_device(self.mac_sensor.macstr)
        self.update_device_tree()

    def start_bootmonitor_clicked(self):
        self.logger.debug('Start bootmonitor clicked')
        mac = self.dhffl.startBootmonitor(self.mac_sensor)
        if mac is not None:
            self.logger.debug('Pinging again')
            # Ping the devices again to update list
            self.ping_devices()

    def reset_clicked(self):
        self.logger.debug('Reset clicked')
        mac = self.dhffl.sendReset(self.mac_sensor)

    def write_file_choose_clicked(self):
        filters = "Hex files (*.hex *.lhex);;All files (*)"
        filename = QtWidgets.QFileDialog.getOpenFileName(filter=filters)
        if filename:
            self.filename_write_edit.setText(filename[0])

    def write_callback(self):
        self.writethread = False
        self.write_button.setEnabled(True)
    def write_clicked(self):
        self.logger.debug('Write clicked')
        filename = self.filename_write_edit.text()
        #try:
        #    self.writethread
        #    flag_nowrite = False
        #except:
        #    flag_nowrite = True

        #if flag_nowrite == False:
        #    self.logger.warning('Already writing')
        if len(filename)>0:
            self.logger.debug('Will flash device {} with data from file'.format(self.mac_sensor.macstr, filename))
            macstr = self.mac_sensor.macstr
            f = open(filename)
            hexdata = []
            for l in f.readlines():
                l.replace('\n','')
                hexdata.append(l)

            self.__data_write = hexdata
            self.__data_written = []
            self.__data_write_len = len(self.__data_write)
            if self.dhffl is not None and self.mac_sensor is not None:
                macstr = self.mac_sensor.macstr
                filename = self.filename_read_edit.text()
                callback = self.write_callback
                thread_args = (macstr, hexdata, True, self.__comqueue,callback)

                writethread = threading.Thread(target=self.dhffl.writeFlash, args=thread_args)
                self.logger.info('Starting write thread')
                writethread.start()
                self.write_button.setEnabled(False)
                #index = self.parent().tabwidget.indexOf(self.parent().statuswidget)
                #self.parent().tabwidget.setCurrentIndex(index)
                #self.parent().statuswidget.setFocus()
                # macsensor = self.dhffl.readFlash(macstr, addr_start=addr_start, addr_end=addr_end)

    def read_clicked(self):
        self.logger.debug('Read clicked')
        #DEVICECOMMAND = "$*!,ping\n"
        #self.inq.put('SEND {:s}'.format(DEVICECOMMAND))  # needed?!
        if self.read_radio_all.isChecked():
            self.logger.debug('Reading whole memory')
            addr_start = None
            addr_end = None
        elif self.read_radio_range.isChecked():
            self.logger.debug('Reading address range')
            addr_start = self.read_address_start.value()
            addr_end = self.read_address_end.value()

        if self.dhffl is not None and self.mac_sensor is not None:
            self.statuswidget_progress.setValue(0)
            self.statuswidget_progress_label.setText('Start Reading')
            macstr = self.mac_sensor.macstr
            filename = self.filename_read_edit.text()

            thread_args = (macstr, addr_start, addr_end, filename, self.__comqueue)
            readthread = threading.Thread(target=self.dhffl.readFlash, args=thread_args)
            self.logger.info('Starting read thread')
            readthread.start()
            #macsensor = self.dhffl.readFlash(macstr, addr_start=addr_start, addr_end=addr_end)

    def statuswidget_cancel_clicked(self):
        self.logger.info('Cancelling')
        self.__comqueue.put('Cancel')

    def ping_devices(self):
        if self.dhffl is None:
            logger.warning('Open serial port first')
        else:
            mac_sensors = self.dhffl.ping_devices()
            if mac_sensors is not None:
                for mac in self.dhffl.devices_mac:
                    mac_sensor = self.dhffl.devices_mac[mac]
                    print('Mac sensor',mac_sensor)
                    self.logger.debug('Getting config of device')
                    self.dhffl.get_config_of_device(mac_sensor.macstr)
                print('Found devices {}'.format(mac_sensors.keys()))
                self.update_device_tree()

    def start(self, dhffl, statuswidget):
        self.logger.info('Starting')
        if True:
            self.dhffl = dhffl
            #self.create_statuswidget()  # This will be done with a button later
            self.statuswidget = statuswidget

    def stop(self):
        self.logger.info('Stopping')
        for b in self.command_buttons_enable:
            b.setEnabled(False)
        for b in self.flash_buttons_enable:
            b.setEnabled(False)
        self.mac_sensor = None
        try:
            self.statuswidget_timer.stop()
        except:
            logger.info('Could not stop timer',exc_info=True)

    def update_device_tree(self):
        self.logger.debug('Updating device tree')
        self.devicetree.currentItemChanged.disconnect(self.qtreewidget_item_changed)
        self.devicetree.clear()
        self.devicetree.setColumnCount(7)
        # self.devicetree.setHeaderHidden(True)
        self.devicetree.setHeaderLabels(['Device','Firmware status','Version','Bootloader version','Board ID','Bootflag','Boot countdown'])
        root = self.devicetree.invisibleRootItem()

        if self.dhffl is None:
            self.logger.warning('No serial connection yet')
        else:

            for macstr in self.dhffl.devices_mac.keys():
                status = None
                version = None
                brdid = None
                bootloader_version = None
                bootflag = None
                countdown = None
                if self.dhffl.devices_mac[macstr].parents is None:
                    mac = self.dhffl.devices_mac[macstr]
                    bootloader_version = mac.bootloader_version
                    if bootloader_version is None:
                        bootloader_version = 'Inactive'
                    version = mac.version
                    brdid = mac.brdid
                    status = mac.status
                    bootflag = mac.bootflag
                    countdown = mac.countdown
                    itm = QtWidgets.QTreeWidgetItem([macstr, status, version, bootloader_version, brdid, str(bootflag), str(countdown)])
                    root.addChild(itm)
                else:
                    parentitm = root
                    for m in self.dhffl.devices_mac[macstr].parents:
                        mactmp = self.dhffl.devices_mac[m]
                        bootloader_version = mactmp.bootloader_version
                        if bootloader_version is None:
                            bootloader_version = 'Inactive'
                        version = mactmp.version
                        brdid = mactmp.brdid
                        status = mactmp.status
                        bootflag = mactmp.bootflag
                        countdown = mactmp.countdown
                        itm = QtWidgets.QTreeWidgetItem([m, status, version, bootloader_version, brdid, str(bootflag), str(countdown)])
                        parentitm.addChild(itm)
                        parentitm = itm


        self.devicetree.expandAll()
        self.devicetree.resizeColumnToContents(0)
        self.devicetree.sortByColumn(0, QtCore.Qt.AscendingOrder)
        self.devicetree.currentItemChanged.connect(self.qtreewidget_item_changed)

    def automatic_filename_changed(self):
        print('Changed',self.read_automatic_filename.isChecked())
        if self.read_automatic_filename.isChecked():
            filename = self.get_filename()
            self.filename_read_edit.setText(filename)

    def get_filename(self):
        try:
            macstr = self.mac_sensor.macstr
        except:
            macstr = "{MAC}"

        if self.read_radio_range.isChecked():
            start = self.read_address_start.value()
            end = self.read_address_end.value()
            rangestr = "_0x{:04x}_0x{:04x}".format(start,end)
        else:
            rangestr = ""
        #datestr = datetime.datetime.now().strftime('__%Y-%m-%d_%H%M%S')
        datestr = datetime.datetime.now().isoformat()
        filename = "mem_{}_{}{}.lhex".format(macstr, datestr, rangestr)
        return filename

    def device_changed(self):
        self.logger.debug('Device changed')
        filename = self.get_filename()
        self.filename_read_edit.setText(filename)
        if self.mac_sensor.status_firmware == 'bootmonitor':
            for b in self.command_buttons_enable:
                b.setEnabled(True)
            for b in self.flash_buttons_enable:
                b.setEnabled(True)
        else:
            for b in self.command_buttons_enable:
                b.setEnabled(True)

            for b in self.flash_buttons_enable:
                b.setEnabled(False)
