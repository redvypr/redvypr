"""
sensor
function binary2raw -> dict with datakey (parameter)
generic_sensor (with optional calibrations)

"""
import logging
import sys
import typing
import pydantic
import re
import struct
import time
import datetime
from PyQt5 import QtWidgets, QtCore, QtGui
import qtawesome
from redvypr.data_packets import check_for_command
from  redvypr.data_packets import create_datadict as redvypr_create_datadict
#import redvypr.config as redvypr_config
from redvypr.redvypr_address import RedvyprAddress, RedvyprAddressStr
from redvypr.devices.plot import plot_widgets
from redvypr.devices.plot import XYplotWidget
from redvypr.device import RedvyprDevice
import redvypr.files as redvypr_files
import redvypr.widgets.standard_device_widgets
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget
from redvypr.devices.sensors.calibration.calibration_models import calibration_HF, calibration_NTC, calibration_const, calibration_poly
from redvypr.devices.sensors.csvsensors.sensorWidgets import sensorCoeffWidget, sensorConfigWidget
from .sensor_definitions import Sensor, BinarySensor, predefined_sensors

_icon_file = redvypr_files.icon_file

redvypr_devicemodule = True

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('generic_sensor')
logger.setLevel(logging.DEBUG)

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Processing and conversion of raw data to unit using calibration models'

class DeviceCustomConfig(pydantic.BaseModel):
    sensors: typing.List[typing.Annotated[typing.Union[Sensor, BinarySensor], pydantic.Field(discriminator='sensortype')]]\
        = pydantic.Field(default=[], description = 'List of sensors')
    calibration_files: list = pydantic.Field(default=[])



def start(device_info, config = None, dataqueue = None, datainqueue = None, statusqueue = None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    print('Got config',config)
    config = DeviceCustomConfig.model_validate(config)
    print('Got config serialized', config)

    for sensor in config.sensors:
        logger.debug('Creating keyinfo packet for sensor {}'.format(sensor.name))
        keyinfo_packet = sensor.create_keyinfo_datapacket()
        print('Datapacket',keyinfo_packet)
        dataqueue.put(keyinfo_packet)

    #splitter = BinaryDataSplitter(config.sensors)
    #print('Splitter',splitter)
    while True:
        data = datainqueue.get(block = True)
        if(data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            if (command == 'stop'):
                logger.debug('Got a command: {:s}'.format(str(data)))
                logger.debug('Command is for me: {:s}'.format(str(command)))
                break

            for sensor in config.sensors:
                print('Sensor',sensor)
                print('Type sensor', type(sensor))
                sensordata = sensor.datapacket_process(data)
                if type(sensordata) is list: # List means that there was a valid packet
                    for data_packet in sensordata:
                        print('Publishing data_packet',data_packet)
                        dataqueue.put(data_packet)


class Device(RedvyprDevice):
    """
    generic_sensor device
    """
    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)


    def update_subscriptions(self):
        funcname = __name__ + '.update_subscriptions():'
        logger.debug(funcname)
        self.unsubscribe_all()
        for sensor in self.custom_config.sensors:
            self.subscribe_address(sensor.datastream)

    def add_sensor(self, sensor):
        flag_name_new = True
        for sen in self.custom_config.sensors:
            if sen.name == sensor.name:
                flag_name_new = False
                break

        if flag_name_new:
            logger.debug('Adding sensor {}'.format(sensor.name))
            self.custom_config.sensors.append(sensor)
            self.update_subscriptions()
            self.config_changed_signal.emit()
        else:
            raise('Sensor name exists already')

    def remove_sensor(self, sensor):
        isensor = self.custom_config.sensors.index(sensor)
        if isensor >=0:
            logger.debug('Removing sensor {}'.format(sensor.name))
            self.custom_config.sensors.pop(isensor)
            self.update_subscriptions()
            self.config_changed_signal.emit()

class initDeviceWidget(redvypr.widgets.standard_device_widgets.redvypr_deviceInitWidget):
    def __init__(self, *args, **kwargs):
        funcname = __name__ + '__init__():'
        logger.debug(funcname)
        super().__init__(*args, **kwargs)

        self.sensorwidget = QtWidgets.QWidget()
        self.sensorwidget_layout = QtWidgets.QVBoxLayout(self.sensorwidget)

        self.sensortable = QtWidgets.QTableWidget()
        self.sensortable.setRowCount(1)

        self.sensor_addbutton = QtWidgets.QPushButton('Add sensor')
        self.sensor_addbutton.clicked.connect(self.add_sensor_clicked)
        self.sensorwidget_layout.addWidget(self.sensortable)
        self.sensorwidget_layout.addWidget(self.sensor_addbutton)

        self.layout.removeWidget(self.label)
        self.label.setParent(None)

        self.layout.addWidget(self.sensorwidget, 0,0,1,-1)
        self.update_sensortable()
        # Add the widgets to the config widget, that enables/disables them when thread is running
        self.config_widgets.append(self.sensortable)
        self.config_widgets.append(self.sensor_addbutton)

    def update_sensortable(self):
        funcname = __name__ + '.update_sensortable():'
        nsensors = len(self.device.custom_config.sensors)
        self.sensortable.clear()
        self.sensortable.setRowCount(nsensors)
        colheaders = ['Name', 'Datastream', 'Configure', 'Remove']
        self.sensortable.setColumnCount(4)
        self.sensortable.setHorizontalHeaderLabels(colheaders)
        icol_name = 0
        icol_subscribe = 1
        icol_config = 2
        icol_delete = 3
        for irow,sensor in enumerate(self.device.custom_config.sensors):
            name = sensor.name
            item_name = QtWidgets.QTableWidgetItem(name)
            self.sensortable.setItem(irow,icol_name,item_name)
            datastream = str(sensor.datastream)
            item_datastream = QtWidgets.QTableWidgetItem(datastream)
            self.sensortable.setItem(irow, icol_subscribe, item_datastream)

            config_icon = qtawesome.icon('fa.navicon')
            item_config = QtWidgets.QPushButton(config_icon,'Config')
            item_config.__sensor__ = sensor
            item_config.clicked.connect(self.sensor_config_clicked)
            self.sensortable.setCellWidget(irow, icol_config, item_config)

            bin_icon = qtawesome.icon('ri.delete-bin-5-fill')
            item_del = QtWidgets.QPushButton(bin_icon,'Remove')
            item_del.__sensor__ = sensor
            item_del.clicked.connect(self.sensor_remove_clicked)
            self.sensortable.setCellWidget(irow, icol_delete, item_del)

        self.sensortable.resizeColumnsToContents()

    def sensor_config_clicked(self):
        sensor = self.sender().__sensor__
        self.sensor_config_widget = pydanticConfigWidget(sensor,redvypr=self.device.redvypr)
        self.sensor_config_widget.config_editing_done.connect(self.device.update_subscriptions)
        self.sensor_config_widget.show()

    def sensor_remove_clicked(self):
        sensor = self.sender().__sensor__
        self.device.remove_sensor(sensor)
        self.update_sensortable()

    def add_sensor_clicked(self):
        self.add_sensor_widget = QtWidgets.QWidget()
        self.add_sensor_widget.setWindowTitle('Add sensor')
        self.add_sensor_widget_layout = QtWidgets.QGridLayout(self.add_sensor_widget)
        # Standard sensors
        self.sensor_standard_combo = QtWidgets.QComboBox()
        self.sensor_standard_combo.addItem('Sensor')
        self.sensor_standard_combo.addItem('BinarySensor')
        self.sensor_standard_combo.setCurrentIndex(1)
        #self.sensor_standard_combo.currentIndexChanged.connect(self.add_sensor_combo_changed)
        self.sensor_standard_choose = QtWidgets.QPushButton('Choose sensor')
        self.sensor_standard_choose.clicked.connect(self.add_sensor_combo_changed)
        self.add_sensor_widget_layout.addWidget(self.sensor_standard_combo, 0, 0)
        self.add_sensor_widget_layout.addWidget(self.sensor_standard_choose, 1, 0)
        # Predefined sensors
        self.sensor_combo = QtWidgets.QComboBox()
        for sensor in predefined_sensors:
            self.sensor_combo.addItem(sensor.name)
        #self.sensor_combo.currentIndexChanged.connect(self.add_sensor_combo_changed)
        self.sensor_predefined_choose = QtWidgets.QPushButton('Choose sensor')
        self.sensor_predefined_choose.clicked.connect(self.add_sensor_combo_changed)
        self.add_sensor_widget_layout.addWidget(self.sensor_combo,0,1)
        self.add_sensor_widget_layout.addWidget(self.sensor_predefined_choose, 1, 1)

        #self.sensor_standard_combo.setCurrentIndex(0)
        self.sensor_standard_choose.clicked.emit()
        self.add_sensor_widget.show()

    def add_sensor_combo_changed(self):
        #combo = self.sender()
        button = self.sender()
        if button == self.sensor_predefined_choose:
            combo = self.sensor_combo
        else:
            combo = self.sensor_standard_combo
        sensorname = combo.currentText()
        sensorindex = combo.currentIndex()
        if combo == self.sensor_combo:
            sensor = predefined_sensors[sensorindex]
        else:
            if sensorindex == 0:
                sensor = Sensor()
            else:
                sensor = BinarySensor()

        try:
            self.add_sensor_widget_layout.removeWidget(self.add_sensor_config_widget)
            self.add_sensor_config_widget.setParent(None)
        except:
            pass

        self.__sensor_to_add__ = sensor
        self.add_sensor_config_widget = pydanticConfigWidget(self.__sensor_to_add__, redvypr=self.device.redvypr, close_after_editing=False)
        self.add_sensor_config_widget.config_editing_done.connect(self.add_sensor_applied)
        self.add_sensor_widget_layout.addWidget(self.add_sensor_config_widget,2,0,1,2)
        #self.config_widget.showMaximized()
        #print('Sensorname',sensorname,'sensorindex',sensorindex)
        #print('Sensor',sensor)

    def add_sensor_applied(self):
        funcname = __name__ + '.add_sensor_applied():'
        logger.debug(funcname)
        try:
            self.device.add_sensor(self.__sensor_to_add__)
            self.add_sensor_widget.close()
            self.update_sensortable()
        except:
            logger.info('Could not add sensor', exc_info=True)
        #self.device.custom_config.sensors.append(self.__sensor_to_add__)



class SensorWidget(QtWidgets.QWidget):
    def __init__(self, *args, sensor=None, **kwargs):
        funcname = __name__ + '__init__():'
        #logger.debug(funcname)
        print('fds',kwargs,type(kwargs))
        self.sensor = sensor
        print('Sensor',self.sensor)
        super().__init__(*args, **kwargs)
        self.layout = QtWidgets.QGridLayout(self)
        self.label = QtWidgets.QLabel(self.sensor.name)
        self.sensor_address = RedvyprAddress('/d:{}'.format(sensor.name))
        self.datatable = QtWidgets.QTableWidget()
        self.datatable.setColumnCount(3)
        self.datatable.setRowCount(2)
        self.datakey_items = {} # Dictionary with the tablewidgetitems
        self.datakey_units = {}  # Dictionary with the units
        self.icol_key = 0
        self.icol_data = 1
        self.icol_unit = 2
        item_tstr = QtWidgets.QTableWidgetItem('NA')
        item_tustr = QtWidgets.QTableWidgetItem('NA')
        self.datakey_items['t'] = [item_tustr, item_tstr]
        item_key_tstr = QtWidgets.QTableWidgetItem('Time')
        item_key_tustr = QtWidgets.QTableWidgetItem('Time (unix)')
        self.datatable.setItem(0, self.icol_data, item_tustr)
        self.datatable.setItem(1, self.icol_data, item_tstr)
        self.datatable.setItem(0, self.icol_key, item_key_tustr)
        self.datatable.setItem(1, self.icol_key, item_key_tstr)

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.datatable)

    def update_data(self,data):
        funcname = __name__ + '.update_data():'
        print(funcname + 'Got data for sensor ',self.sensor.name)
        if data in self.sensor_address:
            print(funcname + ' Datapacket fits, Processing data')
            keys = redvypr.data_packets.datapacket(data).datakeys()
            if '_keyinfo' in data.keys():
                logger.debug('Updating keyinfo')
                # This should be done with device.get_metadata
                for k in data['_keyinfo'].keys():
                    unit = data['_keyinfo'][k]['unit']
                    self.datakey_units[k] = unit

            if 't' in keys:
                t = keys.remove('t')
                # Display always the time
                tdata = datetime.datetime.utcfromtimestamp(data['t'])
                tudatastr = str(data['t'])
                tdatastr = tdata.strftime('%Y-%m-%d %H:%M:%S.%f')
                item_tustr = self.datakey_items['t'][0]
                item_tstr = self.datakey_items['t'][1]
                self.datatable.setItem(0, self.icol_data, item_tustr)
                self.datatable.setItem(1, self.icol_data, item_tstr)
                item_tustr.setText(tudatastr)
                item_tstr.setText(tdatastr)
                if True:
                    for k in keys:
                        datastr = str(data[k]) # This can be done more fancy
                        # Check if the datakey is already
                        if k not in self.datakey_items:
                            nrows = self.datatable.rowCount()
                            #print(funcname + 'Creating new item {}'.format(nrows))
                            datakeyitem = QtWidgets.QTableWidgetItem(k)
                            dataitem = QtWidgets.QTableWidgetItem(datastr)
                            try:
                                unit = self.datakey_units[k]
                            except:
                                unit = 'NA'

                            dataunititem = QtWidgets.QTableWidgetItem(unit)
                            #self.datatable.insertRow(nrows+1)
                            self.datatable.setRowCount(nrows + 1)
                            self.datatable.setItem(nrows, self.icol_key, datakeyitem)
                            self.datatable.setItem(nrows, self.icol_data, dataitem)
                            self.datatable.setItem(nrows, self.icol_unit, dataunititem)
                            self.datakey_items[k] = [dataitem,dataunititem]
                        else:
                            # Data
                            dataitem = self.datakey_items[k][0]
                            dataitem.setText(datastr)
                            # Unit
                            unit = self.datakey_units[k]
                            dataunititem = self.datakey_items[k][1]
                            dataunititem.setText(unit)







class displayDeviceWidget(QtWidgets.QWidget):
    """ Widget is displaying incoming data as text
    """

    def __init__(self, device=None, tabwidget=None):
        """
        device [optional]
        tabwidget [optional]

        """
        funcname = __name__ + '.__init__()'
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        self.layout = layout
        self.tabwidget = tabwidget
        self.device = device
        self.sensorwidget = None # The widget showing the sensor data
        # A timer that is regularly calling the device.status function
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_status)
        self.statustimer.start(2000)

        self.sensortable = QtWidgets.QTableWidget()
        self.device.config_changed_signal.connect(self.update_sensortable)
        #self.sensortable.setRowCount(1)

        layout.addWidget(self.sensortable, 0, 0)
        self.update_sensortable()


    def update_sensortable(self):
        funcname = __name__ + '.update_sensortable():'
        nsensors = len(self.device.custom_config.sensors)
        self.sensortable.clear()
        self.sensortable.setRowCount(nsensors)
        colheaders = ['Name', 'Packets received', 'Packets processed', 'Show', 'Plot']
        self.sensortable.setColumnCount(5)
        self.sensortable.setHorizontalHeaderLabels(colheaders)
        icol_name = 0
        icol_packet_recv = 1
        icol_packet_proc = 2
        icol_show = 3
        icol_plot = 4
        for irow, sensor in enumerate(self.device.custom_config.sensors):
            # Create a sensorwidget, if not exsisting
            try:
                sensor.__sensorwidget__
            except:
                sensor.__sensorwidget__ = SensorWidget(sensor=sensor)

            name = sensor.name
            item_name = QtWidgets.QTableWidgetItem(name)
            self.sensortable.setItem(irow, icol_name, item_name)

            show_icon = qtawesome.icon('ei.list')
            item_show = QtWidgets.QPushButton(show_icon, 'Show')
            item_show.__sensor__ = sensor
            item_show.clicked.connect(self.sensor_show_clicked)
            self.sensortable.setCellWidget(irow, icol_show, item_show)

            plot_icon = qtawesome.icon('ph.chart-line-fill')
            item_plot = QtWidgets.QPushButton(plot_icon, 'Plot')
            item_plot.__sensor__ = sensor
            item_plot.clicked.connect(self.sensor_plot_clicked)
            self.sensortable.setCellWidget(irow, icol_plot, item_plot)

        self.sensortable.resizeColumnsToContents()

        # If there are sensors already, click the last one to show the sensorwidget
        if self.sensorwidget is None:
            nrows = self.sensortable.rowCount()
            if nrows > 0:
                item_show.clicked.emit()


    def sensor_show_clicked(self):
        try:
            self.layout.removeWidget(self.sensorwidget)
            self.sensorwidget.hide()
        except:
            logger.debug('Could not remove widget',exc_info=True)

        sensor = self.sender().__sensor__
        self.sensorwidget = sensor.__sensorwidget__
        self.layout.addWidget(self.sensorwidget, 0,1)
        self.sensorwidget.show()
        print('Show')

    def sensor_plot_clicked(self):
        print('Plot')
    def thread_status(self, status):
        """ This function is regularly called by redvypr whenever the thread is started/stopped
        """
        pass
        # self.update_buttons(status['threadalive'])

    def update_status(self):
        """
        """
        funcname = __name__ + 'update_status():'
        try:
            statusdata = self.device.get_status()
            # print(funcname + str(statusdata))
        except:
            logger.debug(funcname,exc_info=True)

    def update(self, data):
        """
        """
        funcname = __name__ + '.update()'
        tnow = time.time()
        print('got data',data)
        for sensor in self.device.custom_config.sensors:
            print('Updating')
            try:
                sensor.__sensorwidget__.update_data(data)
            except:
                logger.info('Could not update',exc_info=True)



