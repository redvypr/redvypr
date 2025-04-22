import copy
import datetime
import os.path
import zoneinfo
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import pyqtgraph
import yaml
import uuid
import matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import random
import pydantic
import typing
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import check_for_command
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
import redvypr.files as redvypr_files
import redvypr.gui
import redvypr.data_packets
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget
from redvypr.gui import RedvyprAddressWidget
from redvypr.devices.plot import XYPlotWidget
from redvypr.devices.plot import plot_widgets_legacy
from .calibration_models import CalibrationHeatFlow, CalibrationNTC, CalibrationPoly

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.autocalibration')
logger.setLevel(logging.DEBUG)

class AutoCalEntry(pydantic.BaseModel):
    """
    An entry for the autocalibration procedure
    """
    autocalmode: typing.Literal['timer', 'response', 'threshold'] = pydantic.Field(default='response',
                                                                                   description='The mode, i.e. the way autocal shall behave after the value is set.')
    parameter: RedvyprAddress = pydantic.Field(default=RedvyprAddress(),
                                                       description='The parameter to be changed')
    parameter_set: float = pydantic.Field(default=0.0, description='The value the parameter shall be changed to')
    parameter_steady: RedvyprAddress = pydantic.Field(default=RedvyprAddress(),
                                               description='The parameter giving the signal if the desired value is steady')
    parameter_steady_true: typing.Any = pydantic.Field(default=1, description='The value that is sent by parameter_steady when the value is steady')
    parameter_steady_false: typing.Any = pydantic.Field(default=0,
                                                   description='The value that is sent by parameter_steady when the value ist not yet steady')
    command: str = pydantic.Field(default='', description='The command to be sent')
    timer_wait: float = pydantic.Field(default=120, description='Seconds to wait')
    sample_delay: float = pydantic.Field(default=2.0, description='The delay [s] after which the paremeters are sampled')
    entry_min_runtime: float = pydantic.Field(default=5.0, description='The mininum time[s] an entry should run before analysis is performed')


class AutoCalConfig(AutoCalEntry):
    entries: typing.Optional[typing.List[AutoCalEntry]] = pydantic.Field(default=[], editable=True)
    start_index: int = pydantic.Field(default=0, description='The index of the entries to start with')
    parameter_delta: float = pydantic.Field(default=1.0,
                                            description='The delta between the next entry if a new is added',
                                            editable=True)
    parameter_start: float = pydantic.Field(default=0, description='The start value of the parameter',
                                            editable=True)
    autocalmode: typing.Literal['timer', 'response', 'threshold'] = pydantic.Field(default='timer',
                                                                                   description='The mode, i.e. the way autocal shall behave after the value is set.')


class autocalWidget(QtWidgets.QWidget):
    def __init__(self, device=None):
        """
        Standard deviceinitwidget if the device is not providing one by itself.

        Args:
            device:
        """
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.device = device
        self.config = self.device.custom_config.autocal_config
        self.layout = QtWidgets.QGridLayout(self)
        self.calentrytable = QtWidgets.QTableWidget()
        self.parameterinput = QtWidgets.QPushButton('Parameter')
        self.parameterinput.clicked.connect(self.parameterClicked)
        self.parameterinput_edit = QtWidgets.QLineEdit()
        self.parameterinput_edit.setText(self.config.parameter.get_str())

        self.parameter_steady_edit = QtWidgets.QLineEdit()
        self.parameter_steady_edit.setText(self.config.parameter_steady.get_str())
        self.parameter_steady_button = QtWidgets.QPushButton('Parameter steady')
        self.parameter_steady_button.clicked.connect(self.parameterClicked)

        self.parameter_start = QtWidgets.QDoubleSpinBox()
        self.parameter_start.setMinimum(-1e10)
        self.parameter_start.setMaximum(1e10)
        self.parameter_start.setValue(self.config.parameter_start)

        self.parameter_delta = QtWidgets.QDoubleSpinBox()
        self.parameter_delta.setMinimum(-1e10)
        self.parameter_delta.setMaximum(1e10)
        self.parameter_delta.setValue(self.config.parameter_delta)

        self.addentry = QtWidgets.QPushButton('Add entry')
        self.addentry.clicked.connect(self.additem_clicked)
        self.rementry = QtWidgets.QPushButton('Remove entry')
        self.rementry.clicked.connect(self.remitem_clicked)
        self.start = QtWidgets.QPushButton('Start autocalibration')
        self.start.clicked.connect(self.start_clicked)
        self.start.setCheckable(True)
        self.start_index = QtWidgets.QSpinBox()
        self.start_index.setValue(self.config.start_index)
        self.start_index.valueChanged.connect(self.start_index_changed)
        #timer_wait
        self.parameter_steady_true = QtWidgets.QLineEdit()
        self.parameter_steady_true.setText(str(self.config.parameter_steady_true))
        self.parameter_steady_false = QtWidgets.QLineEdit()
        self.parameter_steady_false.setText(str(self.config.parameter_steady_false))
        self.timer_wait = QtWidgets.QDoubleSpinBox()
        self.timer_wait.setMinimum(0.0)
        self.timer_wait.setMaximum(10000.0)
        self.timer_wait.setValue(self.config.timer_wait)
        self.parameter_threshold = QtWidgets.QDoubleSpinBox()
        self.modecombo = QtWidgets.QComboBox()
        modes = typing.get_args(typing.get_type_hints(AutoCalConfig())['autocalmode'])
        for m in modes:
            self.modecombo.addItem(str(m))

        self.modecombo.setCurrentIndex(1)
        self.layout_config0 = QtWidgets.QHBoxLayout()
        self.layout_config0.addWidget(self.parameterinput)
        self.layout_config0.addWidget(self.parameterinput_edit)
        self.layout_config0.addWidget(QtWidgets.QLabel('Parameter start'))
        self.layout_config0.addWidget(self.parameter_start)
        self.layout_config0.addWidget(QtWidgets.QLabel('Parameter delta'))
        self.layout_config0.addWidget(self.parameter_delta)
        self.layout.addLayout(self.layout_config0, 0, 0,1,-1)
        self.layout_config1 = QtWidgets.QHBoxLayout()
        self.layout_config1.addWidget(QtWidgets.QLabel('Mode'))
        self.layout_config1.addWidget(self.modecombo)
        self.layout_config1.addWidget(self.parameter_steady_button)
        self.layout_config1.addWidget(self.parameter_steady_edit,3)
        self.layout_config1.addWidget(QtWidgets.QLabel('Parameter steady true'))
        self.layout_config1.addWidget(self.parameter_steady_true,1)
        self.layout_config1.addWidget(QtWidgets.QLabel('Parameter steady false'))
        self.layout_config1.addWidget(self.parameter_steady_false,1)
        self.layout_config1.addWidget(QtWidgets.QLabel('Timer wait'))
        self.layout_config1.addWidget(self.timer_wait)
        self.layout_config1.addWidget(QtWidgets.QLabel('Threshold'))
        self.layout_config1.addWidget(self.parameter_threshold)
        self.layout.addLayout(self.layout_config1, 1, 0, 1,-1)

        irow = 1
        self.layout.addWidget(self.addentry, 1+irow, 0,1,-1)
        self.layout.addWidget(self.calentrytable, 2+irow, 0, 1, -1)
        self.layout.addWidget(self.rementry, 3+irow, 0,1,-1)
        self.layout.addWidget(self.start, 4+irow, 0, 1, -1)
        self.layout.addWidget(QtWidgets.QLabel('Start index'), 4+irow, 2)
        self.layout.addWidget(self.start_index, 4+irow, 3)
        self.layout.addWidget(self.start, 4+irow, 0, 1, 2)

        self.col_status = 0
        self.col_addr = 1
        self.col_parameter_set = 2
        self.col_mode = 3
        self.col_timer_wait = 4
        self.col_addr_steady = 5
        self.col_sample_delay = 6
        self.col_value = 7

        self.colheader = ['Status', 'Address', 'Parameter set', 'Mode', 'Timer wait', 'Addr steady', 'Sample delay', 'Value']
        self.update_entrytable()
        # Adding myself to the guiqueue to get the data for autocalibration
        self.device.add_guiqueue(widget=self)

    def start_index_changed(self):
        funcname = __name__ + '.start_index_changed():'
        logger.debug(funcname)
        self.config.start_index = self.start_index.value()

    def start_clicked(self):
        funcname = __name__ + '.start_clicked():'
        logger.debug(funcname)
        if self.start.isChecked():
            if self.device.isRunning() == False:
                logger.debug(funcname + 'Calibration device is not running yet, starting first')
                self.device.thread_start()
            start_index = self.config.start_index
            self._autocal_entry_running = False
            logger.debug('Starting at index {}'.format(start_index))
            self._autocal_entry_index = start_index
            self.autcal_run_timer = QtCore.QTimer()
            self.autcal_run_timer.timeout.connect(self.autocal_run)
            self.autcal_run_timer.start(1000)
            self.start_index.setEnabled(False)
            self.autocal_run()
            self.start.setText('Stop autocalibration')
        else:
            logger.debug('Stopping')
            self.start_index.setEnabled(True)
            self.autcal_run_timer.stop()
            self.start.setText('Start autocalibration')

    def autocal_run(self):
        funcname = __name__ + '.autocal_run():'
        logger.debug(funcname)
        try:
            self._autocal_entry_run = self.config.entries[self._autocal_entry_index]
        except:
            logger.debug(funcname + 'Could not get entry, stopping')
            self.autcal_run_timer.stop()
            self.start.setChecked(False)
            self.start_index.setEnabled(True)
            self.start.setText('Start autocalibration')
            for irow, entry in enumerate(self.config.entries):
                item_status = QtWidgets.QTableWidgetItem('Idle')
                item_status.setFlags(item_status.flags() ^ QtCore.Qt.ItemIsEditable)
                self.calentrytable.setItem(irow, self.col_status, item_status)

            return

        self.start_index.setEnabled(False)
        #print('Processing entry',self._autocal_entry_index)
        # Check if an entry is processed
        parameter = self._autocal_entry_run.parameter
        #print('Device',parameter.devicename)
        #print('Datakey', parameter.datakey)


        if self._autocal_entry_running:
            #print('Running, doing nothing, could update status here')

            col_status = 0
            item_status = self.calentrytable.item(self.config.start_index, self.col_status)
            trun = time.time() - self._autocal_entry_tstart
            item_status.setText('Running {:.1f}'.format(trun))
            if self._autocal_entry_run.autocalmode == 'response':
                pass
                #print('Response')
        else:
            # Find the device
            devices = self.device.redvypr.get_device_objects()
            flag_device_found = False
            self._autocal_entry_device = None
            for d in devices:
                #print('d',d)
                if d.name == parameter.devicename:
                    logger.debug(funcname + 'Found a device')
                    flag_device_found = True
                    self._autocal_entry_device = d

            if self._autocal_entry_device is not None:
                logger.debug(funcname + 'Sending command')
                comdata = {'temp':self._autocal_entry_run.parameter_set}
                self._autocal_entry_device.thread_command(command='set', data=comdata)

            if self._autocal_entry_run.autocalmode == 'response':
                logger.debug(funcname + 'Processing entry with response mode')
                self.device.subscribe_address(self._autocal_entry_run.parameter)
                self.device.subscribe_address(self._autocal_entry_run.parameter_steady)
                self._autocal_response_steady = False
                self._autocal_entry_running = True
                self._autocal_entry_tstart = time.time()
            elif self._autocal_entry_run.autocalmode == 'timer':
                logger.debug(funcname + 'Processing entry with timer mode')
                self.device.subscribe_address(self._autocal_entry_run.parameter)
                self._autocal_entry_running = True
                self._autocal_entry_tstart = time.time()
                dt_wait = self._autocal_entry_run.timer_wait

                logger.debug(funcname + 'Waiting for {}'.format(dt_wait))
                self.autcal_run_timer_entry = QtCore.QTimer()
                self.autcal_run_timer_entry.timeout.connect(self.autocal_run_entry_wait)
                self.autcal_run_timer_entry.start(int(dt_wait * 1000))
                # Set item status
                item_status = self.calentrytable.item(self.config.start_index, self.col_status)
                trun = time.time() - self._autocal_entry_tstart
                item_status.setText('Running {:.1f}'.format(trun))

    def autocal_run_entry_wait(self):
        funcname = __name__ + '.autocal_run_entry_wait():'
        logger.debug(funcname + 'Waited long enough, sampling and increasing index')
        self.autcal_run_timer_entry.stop()
        self.autocal_run_next_entry()

    def autocal_run_next_entry(self):
        funcname = __name__ + '.autocal_run_next_entry():'
        # Increasing index
        # Status of table
        item_status = self.calentrytable.item(self.config.start_index, self.col_status)
        trun = time.time() - self._autocal_entry_tstart
        item_status.setText('Idle')
        self.config.start_index += 1
        start_index = self.config.start_index
        logger.debug('Index {}'.format(start_index))
        self._autocal_entry_index = start_index
        self.start_index.setValue(self.config.start_index)
        self._autocal_entry_running = False
        # Sampling
        logger.debug(funcname + 'Sampling')
        self.device.devicedisplaywidget.get_intervalldata()
        self.autocal_run() # Start a new round

    def update_entrytable(self):
        self.calentrytable.clear()

        self.calentrytable.setColumnCount(len(self.colheader))

        nrows = len(self.config.entries)
        self.calentrytable.setRowCount(nrows)

        self.calentrytable.setHorizontalHeaderLabels(self.colheader)
        for irow, entry in enumerate(self.config.entries):
            #print('Entry',entry)
            item_status = QtWidgets.QTableWidgetItem('Idle')
            item_status.setFlags(item_status.flags() ^ QtCore.Qt.ItemIsEditable)
            self.calentrytable.setItem(irow, self.col_status, item_status)

            addr = entry.parameter.get_str('/d/k')
            item_addr = QtWidgets.QTableWidgetItem(addr)
            item_addr.setFlags(item_addr.flags() ^ QtCore.Qt.ItemIsEditable)
            self.calentrytable.setItem(irow, self.col_addr, item_addr)

            parameter_set = str(entry.parameter_set)
            item_set = QtWidgets.QTableWidgetItem(parameter_set)
            item_set.setFlags(item_set.flags() ^ QtCore.Qt.ItemIsEditable)
            self.calentrytable.setItem(irow, self.col_parameter_set,item_set)

            autocalmode = str(entry.autocalmode)
            item_mode = QtWidgets.QTableWidgetItem(autocalmode)
            item_mode.setFlags(item_mode.flags() ^ QtCore.Qt.ItemIsEditable)
            self.calentrytable.setItem(irow, self.col_mode, item_mode)

            timer_wait = str(entry.timer_wait)
            item_wait = QtWidgets.QTableWidgetItem(timer_wait)
            item_wait.setFlags(item_wait.flags() ^ QtCore.Qt.ItemIsEditable)
            self.calentrytable.setItem(irow, self.col_timer_wait, item_wait)

            sample_delay = str(entry.sample_delay)
            item_sample_delay = QtWidgets.QTableWidgetItem(sample_delay)
            item_sample_delay.setFlags(item_sample_delay.flags() ^ QtCore.Qt.ItemIsEditable)
            self.calentrytable.setItem(irow, self.col_sample_delay, item_sample_delay)

            item_value = QtWidgets.QTableWidgetItem('NA')
            item_value.setFlags(item_value.flags() ^ QtCore.Qt.ItemIsEditable)
            self.calentrytable.setItem(irow, self.col_value, item_value)

            addr_steady = entry.parameter_steady.get_str('/d/k')
            item_addr_steady = QtWidgets.QTableWidgetItem(addr_steady)
            item_addr_steady.setFlags(item_addr_steady.flags() ^ QtCore.Qt.ItemIsEditable)
            self.calentrytable.setItem(irow, self.col_addr_steady, item_addr_steady)

    def additem_clicked(self):
        funcname = __name__ + '.additem_clicked()'
        logger.debug(funcname)
        parameter_start = self.parameter_start.value()
        parameter_delta = self.parameter_delta.value()
        timer_wait = self.timer_wait.value()
        autocalmode = self.modecombo.currentText()
        self.parameter_start.setValue(parameter_start + parameter_delta)
        entry = AutoCalEntry(parameter_set=parameter_start, parameter=self.config.parameter,autocalmode=autocalmode,
                             parameter_steady=self.config.parameter_steady,
                             timer_wait=timer_wait)
        self.config.entries.append(entry)
        self.update_entrytable()

    def remitem_clicked(self):
        funcname = __name__ + '.remitem_clicked()'
        logger.debug(funcname)
        indexes = []
        for selectionRange in self.calentrytable.selectedRanges():
            indexes.extend(range(selectionRange.topRow(), selectionRange.bottomRow()+1))

        indexes.reverse()
        logger.debug(funcname + "Removing  indexes {}".format(indexes)) #
        for i in indexes:
            self.config.entries.pop(i)

        self.update_entrytable()

    def send_commnd_to_device(self,calentry):
        funcname = __name__ + '.send_commnd_to_device()'
        logger.debug(funcname)
        devicename = calentry.parameter.devicename
        #print('Devicename',devicename)

    def parameterClicked(self):
        self.pydantic_config = RedvyprAddressWidget(redvypr=self.device.redvypr)
        self.pydantic_config.apply.connect(self.parameter_changed)
        self.__pydantic_config_sender__ = self.sender()
        self.pydantic_config.show()
    def parameter_changed(self,config):
        funcname = __name__ + '.parameter_changed():'
        logger.debug(funcname + 'Config {}'.format(config))
        device = config['device']
        address = config['datastream_address']
        if self.__pydantic_config_sender__ == self.parameterinput:
            self.config.parameter = address
            self.parameterinput_edit.setText(self.config.parameter.get_str())
        elif self.__pydantic_config_sender__ == self.parameter_steady_button:
            self.config.parameter_steady = address
            self.parameter_steady_edit.setText(self.config.parameter_steady.get_str())

    def update_data(self,data):
        funcname = __name__ + '.update_data():'
        logger.debug(funcname)
        if data in self._autocal_entry_run.parameter:
            #print('Data for autocalibration',data)
            item_value = self.calentrytable.item(self.config.start_index, self.col_value)
            rdata = redvypr.data_packets.Datapacket(data)
            valuedata = rdata[self._autocal_entry_run.parameter]
            valuedatastr = str(valuedata)
            item_value.setText(valuedatastr)

        if self._autocal_entry_run.autocalmode == 'response':
            if data in self._autocal_entry_run.parameter_steady:
                trun = time.time() - self._autocal_entry_tstart
                #print('Found steady paramter')
                steady_true = self._autocal_entry_run.parameter_steady_true
                steady_false = self._autocal_entry_run.parameter_steady_false
                rdata = redvypr.data_packets.Datapacket(data)
                steadydata = rdata[self._autocal_entry_run.parameter_steady]
                #print('Steadydata',steadydata)
                # Check if steady and at least next_entry_min_time seconds

                if steadydata == steady_true and (trun > self._autocal_entry_run.entry_min_runtime):
                    if self._autocal_response_steady == False:
                        print('Parameter steady ...')
                        self._autocal_response_steady = True
                        self._autocal_response_steady_time = time.time()
                        #dtwaititem = self.calentrytable.item(self.config.start_index, self.col_timer_wait)
                        #dt_wait = float(dtwaititem.text())
                        #dtwaititem.dt_wait = dt_wait
                    else:
                        pass

                if self._autocal_response_steady:
                    print('Steady')
                    try:
                        dt = time.time() - self._autocal_response_steady_time
                        dtwaititem = self.calentrytable.item(self.config.start_index, self.col_timer_wait)
                        #dt_wait = int(dtwaititem.text())
                        dt_wait = self.config.entries[self.config.start_index].timer_wait
                        #dt_wait = dtwaititem.dt_wait
                        dt_left = dt_wait - dt
                        dtwaititem.setText('{:.2f}'.format(dt_left))
                        print('dt', dt, 'dt_wait', dt_wait)
                        if dt_left > 0:
                            print('Still waiting')
                            pass
                        else:
                            print('New round')
                            self._autocal_entry_running = False
                            self.autocal_run_next_entry()
                    except:
                        logger.warning('Could not process',exc_info=True)