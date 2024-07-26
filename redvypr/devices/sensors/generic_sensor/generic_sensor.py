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
from PyQt5 import QtWidgets, QtCore, QtGui
import qtawesome
from redvypr.data_packets import check_for_command
from  redvypr.data_packets import create_datadict as redvypr_create_datadict
#import redvypr.config as redvypr_config
from redvypr.redvypr_address import RedvyprAddress, RedvyprAddressStr
from redvypr.devices.plot import plot_widgets
from redvypr.devices.plot import XYplotWidget
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

class BinaryDataSplitter():
    """

    """
    def __init__(self, sensors=[]):
        funcname = __name__ + '__init__():'
        self.regex_splitters = []
        self.sensors = sensors
        for sensor in sensors:
            logger.debug(funcname + 'Adding sensor {}'.format(sensor.name))
            sensor._str_functions = {}
            self.regex_splitters.append(sensor.regex_split)
            # Add functions for datatypes
            for key in sensor.str_format:
                vartype = sensor.str_format[key]
                print('key',key,'vartype',vartype)
                if vartype.lower() == 'float':
                    sensor._str_functions[key] = float
                elif vartype.lower() == 'int':
                    sensor._str_functions[key] = int
                elif vartype.lower() == 'str':
                    sensor._str_functions[key] = str

    def datapacket_process(self, data):
        """
        Processes a redvypr datapacket. Checks if subscription is valid and sends it to the proper sensor
        :param data:
        :return:
        """
        print('Hallo data',data)
        sensors = []

        for isensor,sensor in enumerate(self.config.sensors):
            if data in sensor.datastream:
                print('Processing data for sensor',isensor)
                sensors.append(sensor)

        #self.binary_process(binary_stream, sensors)


    def binary_process(self, binary_stream, sensors=None):
        """

        :param binary_stream:
        :param sensors:
        :return:
        """
        if sensors is None:
            sensors = self.sensors
        matches_all = self.binary_split(binary_stream, sensors)
        data_packets = []
        for rematches,sensor in zip(matches_all,sensors):
            print('Match/Sensor',rematches,sensor)
            for rematch in rematches:
                data_packet = redvypr_create_datadict(device=sensor.name)
                flag_data = False
                print('Processing match',rematch)
                print('Variables found',rematch.groupdict())
                redict = rematch.groupdict()
                for keyname in redict:
                    if keyname in sensor.binary_format.keys():
                        binary_format = sensor.binary_format[keyname]
                        print('Found binary key with format',keyname, binary_format)
                        # convert the data
                        data = struct.unpack(binary_format,redict[keyname])
                        if len(data) == 1:
                            data = data[0]
                        data_packet[keyname] = data
                        flag_data = True
                    if keyname in sensor.str_format.keys():
                        print('Found str key',keyname)
                        # get the right function
                        convfunction = sensor._str_functions[keyname]
                        # convert the data
                        data = convfunction(redict[keyname])
                        data_packet[keyname] = data
                        flag_data = True
                        print('Converted data to',data)

                if flag_data:
                    data_packets.append(data_packet)

        return data_packets

    def binary_split(self, binary_stream, sensors=None):
        """
        Splits the data into pieces
        :param binary_stream:
        :param sensors:
        :return:
        """
        if sensors is None:
            sensors = self.sensors
        matches_all = []
        for sensor in sensors:
            regex = sensor.regex_split
            matches = []
            print('Regex',regex,binary_stream)
            #rematch = re.search(regex, binary_stream)
            rematchiter = re.finditer(regex, binary_stream)
            rematch = [r for r in rematchiter]
            print('Match',rematch)
            matches_all.append(rematch)

        return matches_all



def start(device_info, config = None, dataqueue = None, datainqueue = None, statusqueue = None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    config = DeviceCustomConfig.model_validate(config)
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
            datastream = sensor.datastream
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
        self.sensor_config_widget = pydanticConfigWidget(sensor)
        self.sensor_config_widget.show()

    def sensor_remove_clicked(self):
        sensor = self.sender().__sensor__
        isensor = self.device.custom_config.sensors.index(sensor)
        self.device.custom_config.sensors.pop(isensor)
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
        self.sensor_standard_combo.currentIndexChanged.connect(self.add_sensor_combo_changed)
        self.add_sensor_widget_layout.addWidget(self.sensor_standard_combo,0,0)
        # Predefined sensors
        self.sensor_combo = QtWidgets.QComboBox()
        for sensor in predefined_sensors:
            self.sensor_combo.addItem(sensor.name)
        self.sensor_combo.currentIndexChanged.connect(self.add_sensor_combo_changed)
        self.add_sensor_widget_layout.addWidget(self.sensor_combo,0,1)

        self.sensor_standard_combo.setCurrentIndex(0)
        self.add_sensor_widget.show()

    def add_sensor_combo_changed(self):
        combo = self.sender()
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
        self.add_sensor_config_widget = pydanticConfigWidget(self.__sensor_to_add__)
        self.add_sensor_config_widget.config_editing_done.connect(self.add_sensor_applied)
        self.add_sensor_widget_layout.addWidget(self.add_sensor_config_widget,1,0,1,2)
        #self.config_widget.showMaximized()
        print('Sensorname',sensorname,'sensorindex',sensorindex)
        print('Sensor',sensor)

    def add_sensor_applied(self):
        funcname = __name__ + '.add_sensor_applied():'
        logger.debug(funcname)
        self.device.custom_config.sensors.append(self.__sensor_to_add__)
        self.add_sensor_widget.close()
        self.update_sensortable()


