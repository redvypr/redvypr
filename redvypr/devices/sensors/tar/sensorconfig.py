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
import os
from pathlib import Path
import copy
import re
import threading
import pydantic
import redvypr
from . import sensor_firmware_config
#from . import tar
from redvypr.devices.sensors.generic_sensor.calibrationWidget import GenericSensorCalibrationWidget, CalibrationsTable
#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.tar.sensorconfig')
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


class TarCfg():
    """
    ntc calibration
    struct tar_ntc_calibration{
	uint8_t format;
	uint8_t uuid[32];
	char id[64];
	struct calcoeff calibrations[TARV21_NNTC];
	char date[32];
	char comment[256];
	};

    """
    def __init__(self):
        self.commands = {}
        self.commands['savecal'] = {'wait':20}
        self.commands['set cal ntc'] = {'wait':0.25}
        self.commands['set calid'] = {'wait': 0.25}
        self.commands['set caluuid'] = {'wait': 0.25}
        self.commands['set calcomment'] = {'wait': 0.25}
        self.commands['set caldate'] = {'wait': 0.25}

    def get_printcal_command(self, mac="*", addmeta=1, i0=None, i1=None):
        macstr = mac
        command = "${:s}!,printcal ntc {} {} {}\n".format(macstr, addmeta,
                                                          i0, i1)

        return command
    def get_savecal_command(self, mac="*"):
        savecalcmd = "${:s}!,savecal\n".format(mac)
        return savecalcmd

    def get_calcomment_command(self, comment, mac="*" ):
        maxlen = 256
        macstr = mac
        if len(comment) >= maxlen:
            comment = comment[:maxlen-3] + '..'
        comstr = "set calcomment {}".format(comment)
        devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
        return devicecommand

    def get_caldate_str(self, date):
        if isinstance(date, datetime.datetime):
            datemod = date.replace(microsecond=0)
            datestr = datetime.datetime.isoformat(datemod)
        else:
            datestr = str(date)

        return datestr
    def get_caldate_command(self, date, mac="*"):
        maxlen = 32
        macstr = mac
        tmpstr = self.get_caldate_str(date)
        if len(tmpstr) >= maxlen:
            tmpstr = tmpstr[:maxlen-3] + '..'
        comstr = "set caldate {}".format(tmpstr)
        devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
        return devicecommand

    def get_caluuid_command(self, uuid, mac="*"):
        macstr = mac
        maxlen = 32
        tmpstr = str(uuid)
        if len(tmpstr) >= maxlen:
            tmpstr = tmpstr[:maxlen-3] + '..'
        comstr = "set caluuid {}".format(tmpstr)
        devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
        return devicecommand

    def get_calid_command(self, id, mac="*"):
        macstr = mac
        maxlen = 64
        tmpstr = str(id)
        if len(tmpstr) >= maxlen:
            tmpstr = tmpstr[:maxlen-3] + '..'
        comstr = "set calid {}".format(tmpstr)
        devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
        return devicecommand

    def create_calibration_commands(self, calibrations, calibration_id=None, calibration_uuid=None, comment=None, date=None, savecal=True, mac="*"):
        """
        Creates commands to set the calibrations of the sensor
        The structure is similar to this here:
        $D8478FFFFE95CA01,set calid <id>\n
        $D8478FFFFE95CA01,set caluuid <uuid>\n
        $D8478FFFFE95CA01,set calcomment <comment>\n
        $D8478FFFFE95CA01,set caldate <datestr in ISO8190 format (max 31 Bytes)>\n
        $D8478FFFFE95CA01,set cal ntc21 4 1.128271e-03 3.289026e-04 -1.530210e-05 1.131836e-06 0.000000e+00\n

        Parameters
        ----------
        calibrations
        calibration_id
        calibration_uuid
        comment

        Returns
        -------

        """
        maxlen = 20
        macstr = mac

        commands = []

        if calibration_id is not None:
            tmpstr = str(calibration_id)
            if len(tmpstr) > maxlen:
                tmpstr = tmpstr[:maxlen]
            comstr = "set calid {}".format(tmpstr)
            devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
            commands.append(devicecommand)
        if calibration_uuid is not None:
            tmpstr = str(calibration_uuid)
            if len(tmpstr) > maxlen:
                tmpstr = tmpstr[:maxlen]
            comstr = "set caluuid {}".format(tmpstr)
            devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
            commands.append(devicecommand)
        if date is not None:
            if isinstance(date,datetime.datetime):
                datestr = datetime.datetime.isoformat(date)
            else:
                datestr = str(date)
            tmpstr = datestr
            if len(tmpstr) > 31:
                tmpstr = tmpstr[:maxlen]
            comstr = "set caldate {}".format(tmpstr)
            devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
            commands.append(devicecommand)
        if comment is not None:
            tmpstr = str(comment)
            if len(tmpstr) > maxlen:
                tmpstr = tmpstr[:maxlen]
            comstr = "set calcomment {}".format(tmpstr)
            devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
            commands.append(devicecommand)
        for i, cal_key in enumerate(calibrations):
            # Check if dictionary or list, if dictionary, parameter is dict_key
            if isinstance(calibrations, dict):
                calibration = calibrations[cal_key]
                parameter = str(cal_key)
            elif isinstance(calibrations, list):
                calibration = cal_key
                parameter = str(calibration.channel.datakey)

            #print('Parameter',parameter)
            if calibration.calibration_type == 'ntc':
                self.logger.debug('NTC calibration')
                # Find index in parameter that looks like this: '''R["63"]''')
                indices = re.findall(r'\d+', str(parameter))
                if len(indices) == 1:  # Should be only one
                    index = indices[0]
                    caltype = 4
                    coeff = calibration.coeff
                    coeff_write = []
                    for icoeff in range(5):
                        try:
                            #coeff_write.append(coeff[icoeff])
                            # Send the reverse entries
                            itmp = - icoeff - 1
                            coeff_write.append(coeff[itmp])
                        except:
                            coeff_write.append(0.0)

                    comstr = "set cal ntc{index} {caltype} {c0} {c1} {c2} {c3} {c4}".format(index=index,caltype=caltype,c0=coeff_write[0],c1=coeff_write[1],c2=coeff_write[2],c3=coeff_write[3],c4=coeff_write[4])
                    devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
                    commands.append(devicecommand)
        if savecal:
            devicecommand = "${:s}!,savecal\n".format(macstr)
            commands.append(devicecommand)

        return commands

    def get_wait_time_for_command(self, com):
        """
        Returns a rough time that the device needs to process the command
        Parameters
        ----------
        com

        Returns
        -------
        dt_sleep: Time in seconds
        """
        dt_sleep = 0.5
        for k in self.commands.keys():
            if isinstance(com, bytes):
                ktest = k.encode('utf-8')
            else:
                ktest = k
            if ktest in com:
                dt_sleep = self.commands[k]['wait']
                break

        return dt_sleep


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
        self.calibration_simple = TarCalibrationsWidget()
        self.tabwidget.addTab(self.calibration,'Calibration coefficients')
        self.hexflasher = HexflashWidget(comqueue=self.__comqueue)
        self.device = device
        self.dhffl = None
        self.dhffl_show = None
        self.mac_sensor = None
        self.detectandstayinbootloader = QtWidgets.QCheckBox('Stay in bootloader if starting device detected')
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
        self.tabwidget.addTab(self.calibration_simple, 'Calibration simple')
        #layout.addWidget(self.startbtn)
        #layout.addWidget(self.stopbtn)

        self.status_serial = 'closed'


        self.update_device_tree()
        self.update_timer =QtCore.QTimer()
        self.update_timer.timeout.connect(self.update_device_tree_timer)
        self.update_timer.start(1000)

    def update_device_tree_timer(self):
        #print('status',self.status_serial)
        if self.status_serial == 'open':
            self.devicetree.setEnabled(True)
            #print('Updating device tree')
            if self.dhffl is not None:
                #print('Queue',self.read_queue)
                data_recv = self.dhffl.read_messages_for_parsing_devicemacs(read_queue=2)
                ndevfound = self.dhffl_show.parse_messages_and_create_devicemacs(data_recv,overwrite=False)
                #print('Devices_mac',self.dhffl.devices_mac)
                if ndevfound is not None:
                    self.update_device_tree()
        else:
            self.devicetree.setEnabled(False)

    def init_commandwidget(self):
        layout = QtWidgets.QGridLayout(self.commandwidget)
        self.query_button = QtWidgets.QPushButton('Query devices')
        self.query_button.clicked.connect(self.query_devices)
        self.startsample_button = QtWidgets.QPushButton('Startsample')
        self.stopsample_button = QtWidgets.QPushButton('Stopsample')


        self.setsampleinterval_button = QtWidgets.QPushButton('Set sampling interval')
        self.setsampleinterval_button.clicked.connect(self.set_sampleinterval)
        self.sampleinterval_spin = QtWidgets.QSpinBox()
        self.sampleinterval_spin.setMaximum(3600)
        self.sampleinterval_spin.setMinimum(0)
        self.startsample_button.setEnabled(False)
        self.stopsample_button.setEnabled(False)
        self.setsampleinterval_button.setEnabled(False)
        self.startsample_button.clicked.connect(self.startstopsample_clicked)
        self.stopsample_button.clicked.connect(self.startstopsample_clicked)

        layout.addWidget(self.query_button, 0, 0, 1, -1)
        layout.addWidget(self.startsample_button, 1, 0)
        layout.addWidget(self.stopsample_button, 1, 1)
        layout.addWidget(self.setsampleinterval_button, 2, 0)
        layout.addWidget(self.sampleinterval_spin, 2, 1)


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
        layout.addWidget(self.detectandstayinbootloader, 3, 0)


    def qtreewidget_item_changed(self, itemnew, itemold):
        logger.debug('Itemchanged {} {}'.format(itemnew, itemold))
        macstr = itemnew.text(0)
        nchilds = itemnew.childCount()
        if nchilds == 0:
            self.mac_sensor = self.dhffl.devices_mac[macstr]
            #print('Macstr', macstr, self.mac_sensor)
            self.device_changed()

    def set_sampleinterval(self):
        funcname = __name__ + 'set_sampleinterval():'
        logger.debug(funcname)
        ts = self.sampleinterval_spin.value()
        macobject = self.mac_sensor
        logger.debug(funcname + ' Setting sampling counter to {}'.format(ts))
        self.dhffl.set_sampling_period_of_device(macstr=macobject.macstr, ts=ts)
        self.dhffl.get_sampling_period_of_device(macstr=macobject.macstr)
        self.update_device_tree()

    def device_changed(self):
        self.startsample_button.setEnabled(True)
        self.stopsample_button.setEnabled(True)
        self.setsampleinterval_button.setEnabled(True)
    def query_devices(self, get_calib=False):
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

                    if get_calib:
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
                self.calibration.update_device_tree_calibrations()
                self.hexflasher.update_device_tree()
                self.update_device_tree()

    def update_device_tree(self):
        #logger.debug('Updating device tree')
        try:
            self.devicetree.currentItemChanged.disconnect(self.qtreewidget_item_changed)
        except:
            pass
        self.devicetree.clear()
        self.devicetree.setColumnCount(10)
        # self.devicetree.setHeaderHidden(True)
        self.devicetree.setHeaderLabels(
            ['Device', 'Firmware status', 'Version', 'Bootloader version', 'Board ID', 'Bootflag', 'Boot countdown','Flagsample','Sample counter','Sampling period'])
        root = self.devicetree.invisibleRootItem()
        if self.dhffl is None:
            logger.warning('No serial connection yet')
        else:
            dhffl = self.dhffl_show
            for macstr in dhffl.devices_mac.keys():
                if dhffl.devices_mac[macstr].parents is None:
                    mac = dhffl.devices_mac[macstr]
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
                    for m in dhffl.devices_mac[macstr].parents:
                        mactmp = dhffl.devices_mac[m]
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

    def startstopsample_clicked(self):
        b = self.sender()
        macobject = self.mac_sensor
        if b == self.startsample_button:
            logger.debug('Start sampling')
            COMMAND = "${:s}!,startsample\n".format(macobject.macstr)
            self.dhffl.serial_write(COMMAND.encode('utf-8'))
        else:
            logger.debug('Stop sampling')
            COMMAND = "${:s}!,stopsample\n".format(macobject.macstr)
            self.dhffl.serial_write(COMMAND.encode('utf-8'))

        nlines_max = 5
        for i in range(nlines_max):
            try:
                data = self.dhffl.serial.readline()
                if len(data) == 0:
                    continue
            except Exception as e:
                continue

        self.query_devices()

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
                self.dhffl = sensor_firmware_config.dhf_flasher(serial_name, baud=serial_baud)
                self.dhffl_show = sensor_firmware_config.dhf_flasher(serial_name, baud=serial_baud)
                self.dhffl.start()  # Starting the serial read thread
                #self.read_queue = self.dhffl.add_serial_read_queue()
            except:
                logger.warning('Could not open serial port',exc_info=True)
                button.setChecked(False)
                return

            self.statuswidget = SerialStatusWidget(dhffl=self.dhffl, data_queue=self.dhffl.serial_queue_status,
                                                   comqueue=self.__comqueue)
            self.statuswidget.statuswidget_queue.put('test')
            logger.debug('Starting hexflasher')
            self.hexflasher.start(self.dhffl, statuswidget=self.statuswidget)
            logger.debug('Starting calibration')

            self.calibration.start(self.dhffl, statuswidget=self.statuswidget)
            self.calibration_simple.add_device(self.dhffl, statuswidget=self.statuswidget)
            self.tabwidget.addTab(self.statuswidget, 'Serial status')
            self.commandwidget.setEnabled(True)
            button.setText('Close')
            self.status_serial = 'open'
        else:
            self.stop_clicked()
            self.status_serial = 'closed'
            self.commandwidget.setEnabled(False)

    def stop_clicked(self):
        logger.debug('Stop clicked')
        button = self._button_serial_openclose
        self.dhffl.stop()
        #self.hexflasher.stop()
        index = self.tabwidget.indexOf(self.statuswidget)
        self.tabwidget.removeTab(index)
        self.statuswidget.close()
        button.setText('Open')


class SerialStatusWidget(QtWidgets.QWidget):
    def __init__(self, dhffl=None, data_queue=None, comqueue=None):
        super(QtWidgets.QWidget, self).__init__()
        self.logger = logging.getLogger('redvypr.device.tar.sensorconfig.SerialStatusWidget')
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
        self.dhffl.serial_write(COMMAND.encode('utf-8') + lineend)


    def statuswidget_cancel_clicked(self):
        self.logger.info('Cancelling')
        self.comqueue.put('Cancel')

    def update_statuswidget(self):
        while True:
            try:
                data = self.statuswidget_queue.get_nowait()
            except:
                break

            #print('Got data (update_statuswidget)',data)
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
        self.logger = logging.getLogger('redvypr.device.tar.sensorconfig.CalibrationsWriteToSensorWidget')
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

        self.logger.debug('Calcommands: {}'.format(calcommands))

    def __write_clicked__(self):
        self.logger.debug('Writing calcommands')
        self.__update_calcommands__()
        if self.dhffl is not None and self.macobject is not None:
            macstr = self.macobject.macstr
            thread_args = (self.calcommands, None, self.__comqueue)
            writethread = threading.Thread(target=self.dhffl.write_calibrations, args=thread_args)
            self.logger.info('Starting write calibration thread')
            writethread.start()

class FirmwareCalibrationsWidget(QtWidgets.QWidget):
    def __init__(self, dhffl=None, sensor = None, comqueue=None):
        funcname = __name__ + '.__init__():'
        super(QtWidgets.QWidget, self).__init__()
        self.__comqueue = comqueue
        self.logger = logging.getLogger('redvypr.device.tar.sensorconfig.SensorCalibrationWidget')
        self.logger.setLevel(logging.DEBUG)
        self.layout = QtWidgets.QGridLayout(self)
        #if sensor is None:
        #    self.logger.debug(funcname + 'Adding standard tar sensor')
        #    self.sensor = tar.TarSensor()

        self.dhffl = dhffl
        self.query_button = QtWidgets.QPushButton('Query devices')
        self.query_button.clicked.connect(self.query_devices)
        self.readcal_button = QtWidgets.QPushButton('Read calibrations')
        self.readcal_button.clicked.connect(self.read_calibration_clicked)
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
        self.layout.addWidget(self.readcal_button, 1, 0)
        self.layout.addWidget(self.choose_calibrations_button, 2, 0)
        self.layout.addWidget(self.devicetree, 3, 0)
        self.layout.addWidget(self.calibwidget, 4, 0)

        self.currentmac = ''
        self.update_device_tree_calibrations()

    def read_calibration_clicked(self):
        funcname = __name__ + '.read_calibration_clicked():'
        logger.debug(funcname)
        self.logger.debug(funcname + 'Reading calibration of mac:{}'.format(self.currentmac))
        mac = self.currentmac
        if True:
            mac_sensor = self.dhffl.devices_mac[mac]
            print('Mac sensor', mac_sensor)
            self.logger.debug('Getting calibration config of device')
            macobject = self.dhffl.get_calibration_of_device(mac_sensor.macstr)
            if macobject is not None:
                logger.debug('Found calibrations, updating coeff tables')
                # updating tables
                calibrations = macobject.calibrations
                # calibrations_edit = copy.deepcopy(macobject.calibrations)
                calibrations_edit = {}
                for key in macobject.calibrations.keys():
                    calib = macobject.calibrations[key]
                    calibrations_edit[key] = None
                    if calib not in self.calibrations_all:
                        self.calibrations_all.append(calib)

                self.calibwidget.update_calibration_all_table(self.calibrations_all)
                self.calibwidget.update_calibration_table(self.calibtablename_firmware, calibrations)
                self.calibwidget.update_calibration_table(self.calibtablename_edit, calibrations_edit)
                sensor_info = {'sn': self.currentmac}
                self.calibwidget.update_sensor_info(sensor_info)
                self.macobject_choosen = macobject


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

    def update_device_tree_calibrations(self):
        self.logger.debug('Updating device tree (calibrations)')
        self.devicetree.currentItemChanged.disconnect(self.qtreewidget_item_changed)
        self.devicetree.clear()
        self.devicetree.setColumnCount(8)
        # self.devicetree.setHeaderHidden(True)
        self.devicetree.setHeaderLabels(
            ['Device', 'Num calibrations', 'Firmware status', 'Version', 'Bootloader version', 'Board ID', 'Bootflag', 'Boot countdown'])
        root = self.devicetree.invisibleRootItem()
        if self.dhffl is None:
            self.logger.warning('No serial connection yet')
        else:
            # Sort the devices according to their parents to make one tree
            macstrs = {}
            macsstrs_tmp = list(self.dhffl.devices_mac.keys())
            while len(macsstrs_tmp)>0:
                maxlenchain = -1
                mostupstreammac = None
                for macstr in macsstrs_tmp:
                    try:
                        chainlen = len(self.dhffl.devices_mac[macstr].parents)
                    except:
                        chainlen = 0

                    if chainlen > maxlenchain:
                        maxlenchain = chainlen
                        mostupstreammac = macstr

                # loop over the item with the most parents
                if self.dhffl.devices_mac[mostupstreammac].parents is None:
                    macstrs[mostupstreammac] = [mostupstreammac]
                    macsstrs_tmp.remove(mostupstreammac)  # Remove the item from the list
                else:
                    macstrs[mostupstreammac] = []
                    for m in self.dhffl.devices_mac[mostupstreammac].parents:
                        macsstrs_tmp.remove(m)  # Remove the item from the list
                        macstrs[mostupstreammac].append(m)

            # And how plot the items
            for macstr in macstrs.keys():
                if True:
                    parentitm = root
                    for m in macstrs[macstr]:
                        mactmp = self.dhffl.devices_mac[m]
                        bootloader_version = mactmp.bootloader_version
                        if bootloader_version is None:
                            bootloader_version = 'Inactive'
                        version = mactmp.version
                        brdid = mactmp.brdid
                        status = mactmp.status
                        bootflag = mactmp.bootflag
                        countdown = mactmp.countdown
                        numcalibrations = str(len(mactmp.calibrations.keys()))
                        itm = QtWidgets.QTreeWidgetItem(
                            [m, numcalibrations, status, version, bootloader_version, brdid, str(bootflag), str(countdown)])

                        itm.__mac__ = m
                        parentitm.addChild(itm)
                        parentitm = itm

        self.devicetree.expandAll()
        self.devicetree.resizeColumnToContents(0)
        self.devicetree.sortByColumn(0, QtCore.Qt.AscendingOrder)
        self.devicetree.currentItemChanged.connect(self.qtreewidget_item_changed)

    def qtreewidget_item_changed(self, itemnew, itemold):
        self.logger.debug('Itemchanged {} {}'.format(itemnew, itemold))
        macstr = itemnew.text(0)
        self.currentmac = macstr
        self.mac_sensor = self.dhffl.devices_mac[macstr]

    def query_devices(self):
        funcname = __name__ + '.query_devices():'
        if self.dhffl is None:
            logger.warning('Open serial port first')
        else:
            mac_sensors = self.dhffl.ping_devices()
            if mac_sensors is not None:
                for mac in self.dhffl.devices_mac:
                    mac_sensor = self.dhffl.devices_mac[mac]
                    self.logger.debug(funcname + ' Get config of {}'.format(mac_sensor))
                    self.dhffl.get_config_of_device(mac_sensor.macstr)
                    #self.logger.debug('Getting calibration config of device')
                    #self.dhffl.get_calibration_of_device(mac_sensor.macstr)
                time.sleep(0.1)
                # And now the calibrations
                if False:
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
                self.update_device_tree_calibrations()


class HexflashWidget(QtWidgets.QWidget):
    def __init__(self, comqueue):
        super(QtWidgets.QWidget, self).__init__()
        self.dhffl = None
        self.inq = queue.Queue()
        self.outq = queue.Queue()

        self.__comqueue = comqueue
        self.command_buttons_enable = [] # List of command buttons that are only enabled if a serial device is open
        self.flash_buttons_enable = []  # List of command buttons that are only enabled if a serial device is open

        self.logger = logging.getLogger('redvypr.device.tar.sensorconfig.HexflashWidget')
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


class TarCalibrationsWidget(QtWidgets.QWidget):
    def __init__(self,calibrations = None):
        super(QtWidgets.QWidget, self).__init__()
        self.tarcfg = TarCfg()
        self.dhffl = None
        # Take care of the calibration list
        if calibrations is None:
            self.calibrations = redvypr.devices.sensors.calibration.calibration_models.CalibrationList()
        else:
            self.calibrations = redvypr.devices.sensors.calibration.calibration_models.CalibrationList(
                calibrations)


        layout = QtWidgets.QFormLayout(self)
        self.caltable = CalibrationsTable(calibrations=self.calibrations)
        layout.addRow(self.caltable)
        self.loadCalibrationButton = QtWidgets.QPushButton('Load Calibration(s)')
        self.loadCalibrationButton.clicked.connect(self.chooseCalibrationFiles)

        self.loadCalibrationsfSubFolder = QtWidgets.QCheckBox(
            'Load all calibrations in folder and subfolders')
        self.loadCalibrationsfSubFolder.setChecked(True)
        layout.addRow(self.loadCalibrationButton, self.loadCalibrationsfSubFolder)

        self.uuidcheck = QtWidgets.QCheckBox("Use UUID")
        self.uuidcheck.setChecked(True)
        self.uuidedit = QtWidgets.QLineEdit()
        layout.addRow(self.uuidcheck,self.uuidedit)

        self.idcheck = QtWidgets.QCheckBox("Use ID")
        self.idcheck.setChecked(True)
        self.idedit = QtWidgets.QLineEdit()
        layout.addRow(self.idcheck,self.idedit)

        self.datecheck = QtWidgets.QCheckBox("Use Date")
        self.datecheck.setChecked(True)
        self.dateedit = QtWidgets.QLineEdit()
        layout.addRow(self.datecheck,self.dateedit)

        self.commentcheck = QtWidgets.QCheckBox("Use Comment")
        self.commentcheck.setChecked(True)
        self.commentedit = QtWidgets.QLineEdit()
        layout.addRow(self.commentcheck,self.commentedit)

        self.savecalcheck = QtWidgets.QCheckBox("Add save to flash command")
        self.savecalcheck.setChecked(True)

        self.createCalibrationCommandButton = QtWidgets.QPushButton('Send calibration commands')
        self.createCalibrationCommandButton.clicked.connect(self.send_commands_clicked)
        layout.addRow(self.createCalibrationCommandButton, self.savecalcheck)

    def add_device(self, dhffl, statuswidget):
        """
        Adds a config device to talk to the sensors
        Parameters
        ----------
        dhffl
        statuswidget

        Returns
        -------

        """
        logger.info('Starting tar calibrationswidget')
        self.dhffl = dhffl
        # self.create_statuswidget()  # This will be done with a button later
        self.statuswidget = statuswidget

    def chooseCalibrationFiles(self):
        """

        """
        funcname = __name__ + '.chooseCalibrationFiles():'
        logger.debug(funcname)
        # fileName = QtWidgets.QFileDialog.getLoadFileName(self, 'Load Calibration', '',
        #                                                 "Yaml Files (*.yaml);;All Files (*)")

        if self.loadCalibrationsfSubFolder.isChecked():
            fileNames = QtWidgets.QFileDialog.getExistingDirectory(self)
            fileNames = ([fileNames], None)
        else:
            fileNames = QtWidgets.QFileDialog.getOpenFileNames(self, 'Load Calibration', '',
                                                               "Yaml Files (*.yaml);;All Files (*)")

        # print('Filenames',fileNames)
        for fileName in fileNames[0]:
            # self.device.read_calibration_file(fileName)
            # print('Adding file ...', fileName)
            if os.path.isdir(fileName):
                print('Path', Path(fileName))
                coefffiles = list(Path(fileName).rglob("*.[yY][aA][mM][lL]"))
                print('Coeffiles', coefffiles)
                for coefffile in coefffiles:
                    print('Coefffile to open', coefffile, str(coefffile))
                    self.calibrations.add_calibration_file(str(coefffile))
            else:
                self.calibrations.add_calibration_file(fileName)

        # Fill the list with sn
        if len(fileNames[0]) > 0:
            logger.debug(funcname + ' Updating the calibration table')
            self.caltable.update_table(self.calibrations)
            self.update_calmetadata()

    def update_calmetadata(self):
        """
        Update of the calibration metadata
        Returns
        -------

        """
        cal = self.calibrations[0]
        uuid = cal.calibration_uuid
        date = self.tarcfg.get_caldate_str(cal.date)
        comment = cal.comment
        id = cal.calibration_id
        self.uuidedit.setText(uuid)
        self.idedit.setText(id)
        self.commentedit.setText(comment)
        self.dateedit.setText(date)

    def create_command_string(self):
        """
        Creates command string for the calibrations
        Returns
        -------

        """
        commands = []
        savecalcmds = {}
        for cal in self.calibrations:
            #print("calibration",cal)
            mac = cal.sn#.split("_")[1]
            savecalcmds[mac] = self.tarcfg.get_savecal_command(mac)
            tar_cfg = sensor_firmware_config.dhf_sensor(mac)
            if 'ntc' in cal.calibration_type.lower():
                com = tar_cfg.create_calibration_commands(calibrations=[cal], calibration_id=None,
                                            calibration_uuid=None, comment=None, date=None,
                                            savecal=False)
                commands.append(com[0])


        #for com in commands:
        #    print(com)
        # Loop over all macs and add extra commands (savecal, comment, uuid etc.)
        for mac,com in savecalcmds.items():
            if self.commentcheck.isChecked():
                comment = self.commentedit.text()
                if len(comment) > 0:
                    print("Adding comment")
                    c = self.tarcfg.get_calcomment_command(comment, mac=mac)
                    commands.append(c)
            if self.datecheck.isChecked():
                comment = self.dateedit.text()
                if len(comment) > 0:
                    print("Adding date")
                    c = self.tarcfg.get_caldate_command(comment, mac=mac)
                    commands.append(c)
            if self.uuidcheck.isChecked():
                comment = self.uuidedit.text()
                if len(comment) > 0:
                    print("Adding uuid")
                    c = self.tarcfg.get_caluuid_command(comment, mac=mac)
                    commands.append(c)
            if self.idcheck.isChecked():
                comment = self.idedit.text()
                if len(comment) > 0:
                    print("Adding id")
                    c = self.tarcfg.get_calid_command(comment, mac=mac)
                    commands.append(c)

            if self.savecalcheck.isChecked():
                commands.append(com)

        return commands

    def send_commands_clicked(self):
        commands = self.create_command_string()
        self._sendWidget = SensorSendCommandWidget(commands=commands, dhffl = self.dhffl)
        self._sendWidget.show()




class SensorSendCommandWidget(QtWidgets.QWidget):
    """
    Widget that shows and sends commands to a sensor
    """
    def __init__(self,commands = None, dhffl = None):
        super(QtWidgets.QWidget, self).__init__()
        self.tarcfg = TarCfg()
        self.layout = QtWidgets.QVBoxLayout(self)
        self.dhffl = dhffl
        if commands is None:
            self.commands = []
        else:
            self.commands = commands

        for i, c in enumerate(self.commands):
            self.commands[i] = c.encode('utf-8')

        self._commands_send = []

        self._commands_state = []
        self._commands_checks = []
        self.iColCom = 2
        self.iColCheck = 1
        self.iColSend = 0
        self.command_table = QtWidgets.QTableWidget()
        self.layout.addWidget(self.command_table)
        self.check_send_all = QtWidgets.QCheckBox("Send")
        self.check_send_all.setChecked(True)
        self.check_send_all.toggled.connect(self._commands_to_send_changed)
        self.layout.addWidget(self.check_send_all)
        self.button_send_all = QtWidgets.QPushButton("Send")
        #self.button_send_all.__commands = self.commands
        self.button_send_all.clicked.connect(self._send_commands)
        if self.dhffl is None:
            self.button_send_all.setEnabled(False)
        self.layout.addWidget(self.button_send_all)
        self._populate_command_table()
        self.button_send_all.__commands = []
        for i, ccheck in enumerate(self._commands_checks):
            self.button_send_all.__commands.append(
                (self.commands[i], ccheck))

    def _populate_command_table(self):
        print("Populating table")
        self._commands_state = []
        self._commands_checks = []
        self.command_table.clear()
        self._tableheader = ["Send","Send (yes/no)","Command"]
        self.command_table.setColumnCount(len(self._tableheader))
        self.command_table.setHorizontalHeaderLabels(self._tableheader)
        self.command_table.setRowCount(len(self.commands))
        for iRow,c in enumerate(self.commands):
            cstr = c
            item = QtWidgets.QTableWidgetItem(str(cstr))
            self.command_table.setItem(iRow,self.iColCom,item)
            check_send = QtWidgets.QCheckBox("Send")
            send_state = True
            check_send.setChecked(send_state)
            check_send.__iRow = iRow
            check_send.toggled.connect(self._commands_to_send_changed)
            self._commands_state.append(send_state)
            self._commands_checks.append(check_send)
            self.command_table.setCellWidget(iRow, self.iColCheck, check_send)
            button_send = QtWidgets.QPushButton("Send")
            button_send.__iRow = iRow
            button_send.__commands = [(cstr,check_send)]
            button_send.clicked.connect(self._send_commands)
            if self.dhffl is None:
                button_send.setEnabled(False)
            self.command_table.setCellWidget(iRow, self.iColSend, button_send)

        self.command_table.resizeColumnsToContents()

    def add_commands(self, commands):
        self.commands.append(commands)
        self._populate_command_table()

    def _commands_to_send_changed(self):
        self.button_send_all.__commands = []
        if self.sender() == self.check_send_all:
            if self.check_send_all.isChecked():
                for i, ccheck in enumerate(self._commands_checks):
                        self.button_send_all.__commands.append(
                            (self.commands[i], ccheck))
                #self.button_send_all.__commands = self.commands
            else:
                self.button_send_all.__commands = []

            for ccheck in self._commands_checks:
                ccheck.setChecked(self.check_send_all.isChecked())

        else:
            for i,ccheck in enumerate(self._commands_checks):
                if ccheck.isChecked():
                    self.button_send_all.__commands.append((self.commands[i],ccheck))

    def _send_commands(self):
        commands = self.sender().__commands
        print("Sending commands",commands)
        if len(self._commands_send) > 0:
            self.button_send_all.setText("Send")
            self._commands_send = []
            return
        self._commands_send = []
        if self.dhffl is not None:
            print('commands',commands)
            for com,check in commands:
                dt_sleep = self.tarcfg.get_wait_time_for_command(com)


                print("Sending now",com)
                self._commands_send.append([com,check,dt_sleep])

            self._send_commands_timer()

        else:
            logger.warning("No device connected")

    def _send_commands_timer(self):
        print('_send_commands_timer():')
        if len(self._commands_send) == 0:
            self.button_send_all.setText("Send")
        if len(self._commands_send) > 0:
            self.button_send_all.setText("Stop sending ({})".format(len(self._commands_send)))
            data_tmp = self._commands_send.pop(0)
            timeout = int(data_tmp[2] * 1000)
            print(timeout)
            check = data_tmp[1]
            data_send = data_tmp[0]
            # Send the data to the device
            print("data send",data_send)
            self.dhffl.serial_queue_write.put(data_send)
            check.setChecked(False)
            self.timer = QtCore.QTimer()
            self.timer.setSingleShot(True)
            self.timer.setInterval(timeout)
            self.timer.timeout.connect(self._send_commands_timer)
            self.timer.start()