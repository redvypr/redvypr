"""
The serial device reads data from the serial interface and publishes them.
"""
import copy
import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import serial
import serial.tools.list_ports
import logging
import sys
import threading
import pydantic
import typing
import re

import redvypr.data_packets
from redvypr.data_packets import check_for_command, create_datadict
from redvypr.redvypr_address import RedvyprAddress
from redvypr.device import RedvyprDevice
import redvypr.files as redvypr_files
from redvypr.data_packets import RedvyprMetadata, RedvyprDeviceMetadata
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget, pydanticDeviceConfigWidget, dictQTreeWidget, datastreamMetadataWidget
from redvypr.devices.interface.serial_single import SerialDeviceConfigRedvypr, SerialDataShowSendWidget, SerialDeviceWidgetRedvypr, packet_start, packet_delimiter, baud_standard
from redvypr.devices.interface.serial_single import start as start_serial_single


_logo_file = redvypr_files.logo_file
_icon_file = redvypr_files.icon_file
description = 'Reading data from serveral serial devices'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.serial')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True


class DeviceBaseConfig(pydantic.BaseModel):
    """
    BaseConfig
    Attributes:
        publishes: True
    """
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Reads to and writes from a serial devices'
    gui_tablabel_display: str = 'Serial device status'
    gui_icon: str = 'mdi.serial-port'

class RedvyprSerialDeviceMetadata(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")
    comment: str = ''


class DeviceCustomConfig(pydantic.BaseModel):
    serial_devices: typing.Optional[typing.List[SerialDeviceConfigRedvypr]] = pydantic.Field(default_factory=list)
    ignore_devices: str = pydantic.Field(default='.*/ttyS[0-9][0-9]*', description='Regular expression of serial device names, that are ignored.')
    gui_show_comport: typing.Optional[
        typing.List[typing.Literal[
            "device", "serial_number", "vid", "pid", "manufacturer"]]] = pydantic.Field(
        default=["device", "serial_number", "vid", "pid", "manufacturer"],description="which details of the comport to show")



def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Starting reading serial data')
    logger.debug('Will open comports {:s}'.format(str(config['serial_devices'])))

    serial_threads = {}
    serial_threads_datainqueues = {}
    dt_poll = 0.05
    for comportconfig in config['serial_devices']:
        logger.debug('Processing device {}'.format(comportconfig['comport_packetid']))
        if comportconfig['use_device'] == False:
            logger.debug('Ignoring device {}'.format(comportconfig['comport_packetid']))
        else:
            logger.debug('Configuring device {}'.format(comportconfig['comport_packetid']))
            queuesize = 100
            config_thread = copy.deepcopy(comportconfig)
            datainqueue_thread = queue.Queue(maxsize=queuesize)
            print("\n\nComportconfig",comportconfig)
            comport = comportconfig['comport_device']
            serial_threads_datainqueues[comport] = datainqueue_thread
            args = [device_info,config_thread,dataqueue,datainqueue_thread,statusqueue]
            serial_thread = threading.Thread(target=start_serial_single, args=args, daemon=True)
            serial_threads[comport] = serial_thread
            logger.debug('Starting thread with config: {:s}'.format(str(config_thread)))
            serial_thread.start()

    while True:
        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if (data is not None):
            [command,comdata] = check_for_command(data, thread_uuid=device_info['thread_uuid'], add_data=True)
            # logger.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                if command == 'stop':
                    sstr = funcname + ': Command is for me: {:s}'.format(str(command))
                    logger.debug(sstr)
                    # Sending stop command to the threads
                    for comport, datainqueue in serial_threads_datainqueues.items():
                        datainqueue.put('stop')

                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass
                    return
                elif command == 'send':  # Something to send
                    #data_com = comdata['command_data']['data']
                    #comport = data_com['comport']
                    #data_send = data_com['data_send']
                    print("Sending",data)
                    if comport in serial_threads_datainqueues.keys():
                        #serial_threads_datainqueues[comport].put(['send',data_send])
                        serial_threads_datainqueues[comport].put(data)
                    else:
                        logger.warning("comport {} not available ({})".format(comport,serial_threads_datainqueues.keys()))

        # Check if any of the threads is running, if not stop main thread as well
        all_dead = True
        for comport, serial_thread in serial_threads.items():
            if serial_thread.is_alive():
                all_dead = False
                break

        if all_dead:
            return

        time.sleep(dt_poll)



class Device(RedvyprDevice):
    """
    serial device
    """

    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)
        logger.debug(funcname)
        self.get_comports()

    def thread_start(self):
        try:
            self.deviceinitwidget.widgets_to_config()
        except:
            logger.debug('Could not init using gui settings',exc_info=True)
        super().thread_start()

    def get_comports(self):
        funcname = __name__ + '.get_comports():'
        logger.debug(funcname)
        comports = serial.tools.list_ports.comports()
        self.comports = []
        serial_devices_new = []
        for comport in comports:
            logger.info(funcname + ' Testing serial device {}, SN:{},vid:{},pid:{},Manufacturer:{}'.format(comport.device, comport.serial_number, comport.vid, comport.pid,
                  comport.manufacturer))
            #print("Comport",comport.device, comport.serial_number, comport.vid, comport.pid,
            #      comport.manufacturer)
            FLAG_DEVICE_EXISTS = False
            for d in self.custom_config.serial_devices:
                if comport.device == d.comport_device: # TODO, here a better comparison is needed
                    logger.debug(funcname + ' Found new device {}'.format(d.comport_device))
                    FLAG_DEVICE_EXISTS = True
                    serial_devices_new.append(d)
                    self.comports.append(comport)
                    break

            if re.match(self.custom_config.ignore_devices,comport.device):
                logger.info('Ignoring device {}'.format(comport.device))
            else:
                if FLAG_DEVICE_EXISTS == False:
                    config = SerialDeviceConfigRedvypr(comport_device=comport.device,
                                                      pid=str(comport.pid),
                                                      vid=str(comport.vid),
                                                      manufacturer=str(comport.manufacturer),
                                                      serial_number=str(comport.serial_number))

                    config.create_packetid_device_short()
                    #self.config.serial_devices.append(config)
                    serial_devices_new.append(config)
                    self.comports.append(comport)

        self.custom_config.serial_devices = serial_devices_new
        logger.debug(funcname + ' serial devices {}'.format(self.custom_config.serial_devices))


class initDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        self.device   = device
        #self.serialwidget = QtWidgets.QWidget()
        self.serialwidgets_parent = QtWidgets.QWidget()
        layout_all = QtWidgets.QGridLayout(self.serialwidgets_parent)
        self.layout_serialwidgets = layout_all
        self.serialwidgets = []
        self.label= QtWidgets.QLabel("Serial device")

        self.comscanbutton = QtWidgets.QPushButton("Rescan comports")
        self.comscanbutton.clicked.connect(self.comscan_clicked)
        # self.comscanbutton.setCheckable(True)
        layout.addWidget(self.comscanbutton)


        self.init_serialwidgets()
        layout.addWidget(self.serialwidgets_parent)

        self.startbutton = QtWidgets.QPushButton("Start")
        self.startbutton.clicked.connect(self.start_clicked)
        self.startbutton.setCheckable(True)
        layout.addWidget(self.startbutton)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def comscan_clicked(self):
        funcname = __name__ + '.comscan_clicked()'
        logger.debug(funcname)
        self.device.get_comports()
        layout = self.layout_serialwidgets
        for i in reversed(range(layout.count())):
            layout.itemAt(i).widget().setParent(None)
        self.init_serialwidgets()
        # Redraw also the devicedisplaywidget
        self.device.devicedisplaywidget.populate_statustable()


    def init_serialwidgets(self):
        layout_all = self.layout_serialwidgets


        for irow, serial_device in enumerate(self.device.custom_config.serial_devices):
            widget = SerialDeviceWidgetRedvypr(config = serial_device,
                                               fix_serial_device=True,
                                               add_packetid=True,
                                               add_usedevice=True)
            serialwidgetdict = {}
            serialwidgetdict['widget'] = widget
            serialwidgetdict['serial_device'] = serial_device
            self.serialwidgets.append(serialwidgetdict)
            layout_all.addWidget(serialwidgetdict['widget'], irow+1, 0)


        layout_all.setRowStretch(layout_all.rowCount(), 1)

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']

        if(thread_status):
            self._button_serial_openclose.setText('Close')
            self._combo_serial_baud.setEnabled(False)
            self._combo_serial_devices.setEnabled(False)
        else:
            self._button_serial_openclose.setText('Open')
            self._combo_serial_baud.setEnabled(True)
            self._combo_serial_devices.setEnabled(True)
        
    def start_clicked(self):
        button = self.sender()
        if ('Start' in button.text()):
            self.device.devicedisplaywidget.comporttable.setEnabled(True)
            self.device.devicedisplaywidget.populate_statustable()
            self.device.thread_start()
            button.setText('Stop')
        else:
            self.stop_clicked()
            self.device.devicedisplaywidget.comporttable.setEnabled(False)

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']
        # Running
        if (thread_status):
            self.startbutton.setText('Stop')
            self.startbutton.setChecked(True)
            for w in self.serialwidgets:
                for i,k in w.items():
                    try:
                        k.setEnabled(False)
                    except:
                        pass
            #for w in self.config_widgets:
            #    w.setEnabled(False)
        # Not running
        else:
            self.startbutton.setText('Start')
            for w in self.serialwidgets:
                for i, k in w.items():
                    try:
                        k.setEnabled(True)
                    except:
                        pass
            # Check if an error occured and the startbutton
            if (self.startbutton.isChecked()):
                self.startbutton.setChecked(False)
            # self.conbtn.setEnabled(True)

    def stop_clicked(self):
        """

        Returns:

        """
        self.device.thread_stop()
        self.startbutton.setText('Closing')


class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None, tabwidget=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        self.device = device
        self.tabwidget = tabwidget
        self.serialwidgets = []
        self.serialwidgetsdict = {}
        self.comporttable = QtWidgets.QTableWidget()
        layout.addWidget(self.comporttable,0,0)
        self.device = device
        self.populate_statustable()
        self.device.new_data.connect(self.new_data)
        self.comporttable.setEnabled(False)

    def populate_statustable(self):
        funcname = __name__ + '.populate_statustable():'
        logger.debug(funcname)
        self.comporttable.clear()
        columns = ['Comport', 'Bytes read', 'Packets read', 'Status', 'Show rawdata']
        self.comporttable.setColumnCount(len(columns))
        self.comporttable.horizontalHeader().ResizeMode(self.comporttable.horizontalHeader().ResizeToContents)
        self.comporttable.setHorizontalHeaderLabels(columns)
        #comports = self.device.comports
        self.comporttable.setRowCount(len(self.device.custom_config.serial_devices))
        self.comports = []
        # for irow, comport in enumerate(comports):
        for irow, serial_config in enumerate(self.device.custom_config.serial_devices):
            self.comports.append(serial_config.comport_device)
            serialwidgetdict = {}
            serialwidgetdict['datawidget'] = SerialDataShowSendWidget(serial_config=serial_config, device=self.device)
            self.serialwidgets.append(serialwidgetdict)
            self.serialwidgetsdict[serial_config.comport_device] = serialwidgetdict

            item = QtWidgets.QTableWidgetItem(serial_config.comport_device_short)
            self.comporttable.setItem(irow, 0, item)
            item = QtWidgets.QTableWidgetItem('0')
            self.comporttable.setItem(irow, 1, item)
            item = QtWidgets.QTableWidgetItem('0')
            self.comporttable.setItem(irow, 2, item)
            # Status
            item = QtWidgets.QTableWidgetItem('closed')
            self.comporttable.setItem(irow, 3, item)

            button = QtWidgets.QPushButton('Show')
            button.clicked.connect(self.__showdata__)
            button.displaywidget = serialwidgetdict['datawidget']
            button.__serial_config__ = serial_config
            self.comporttable.setCellWidget(irow, 4, button)
            button.setEnabled(serial_config.use_device)


        self.comporttable.resizeColumnsToContents()

    def __showdata__(self):
        button = self.sender()
        tabname = button.__serial_config__.comport_device_short
        # Prüfen, ob der Tab bereits existiert
        index = -1
        for i in range(self.tabwidget.count()):
            if self.tabwidget.tabText(i) == tabname:
                index = i
                break
        if index >= 0:
            # Tab existiert: Schließen
            self.tabwidget.removeTab(index)
            button.setText('Show')
        else:
            # Tab existiert nicht: Öffnen
            self.tabwidget.addTab(button.displaywidget, tabname)
            button.setText('Hide')

    def new_data(self, data_list):
        #print('data',data_list)
        for data in data_list:
            try:
                comport = data['comport']
                datawidget = self.serialwidgetsdict[comport]['datawidget']
            except Exception as e:
                #print("Problem",e)
                return
            try:
                status = data['status']
                index = self.comports.index(comport)
                itemstatus = QtWidgets.QTableWidgetItem(status)
                self.comporttable.setItem(index, 3, itemstatus)
            except Exception as e:
                pass
            try:
                index = self.comports.index(comport)
                bstr = "{:d}".format(data['bytes_read'])
                lstr = "{:d}".format(data['sentences_read'])
                itemb = QtWidgets.QTableWidgetItem(bstr)
                items = QtWidgets.QTableWidgetItem(lstr)
                itemstatus = QtWidgets.QTableWidgetItem('open')
                self.comporttable.setItem(index, 1, itemb)
                self.comporttable.setItem(index, 2, items)
                self.comporttable.setItem(index, 3, itemstatus)

            except Exception as e:
                #logger.exception(e)
                pass

            try:
                datawidget.add_data([data])

            except Exception as e:
                logger.exception(e)
                pass
        
