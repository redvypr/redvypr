"""
sensor
function binary2raw -> dict with datakey (parameter)
generic_sensor (with optional calibrations)

"""
import logging
import sys
import typing
import pydantic
import json
import yaml
import re
import struct
import time
import datetime
import numbers
from PyQt5 import QtWidgets, QtCore, QtGui
import qtawesome
from redvypr.data_packets import check_for_command
from  redvypr.data_packets import create_datadict as redvypr_create_datadict
#import redvypr.config as redvypr_config
from redvypr.redvypr_address import RedvyprAddress, RedvyprAddressStr
from redvypr.device import RedvyprDevice
import redvypr.files as redvypr_files
import redvypr.widgets.standard_device_widgets
from redvypr.devices.plot.XYplotWidget import XYPlotWidget, configXYplot
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget, datastreamMetadataWidget
from redvypr.devices.sensors.calibration.calibration_models import calibration_models, calibration_NTC
from redvypr.devices.sensors.csvsensors.sensorWidgets import sensorCoeffWidget, sensorConfigWidget
from redvypr.gui import iconnames
from .sensor_definitions import Sensor, BinarySensor, predefined_sensors
from .calibrationWidget import sensorCalibrationsWidget

_icon_file = redvypr_files.icon_file

redvypr_devicemodule = True

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('generic_sensor')
logger.setLevel(logging.INFO)

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Processing and conversion of raw data to unit using calibration models'

class DeviceCustomConfig(pydantic.BaseModel):
    sensors: typing.List[typing.Annotated[typing.Union[Sensor, BinarySensor], pydantic.Field(discriminator='sensortype')]]\
        = pydantic.Field(default=[], description = 'List of sensors')
    #calibrations: list = pydantic.Field(default=[])
    calibrations: typing.List[typing.Annotated[typing.Union[*calibration_models], pydantic.Field(discriminator='calibration_type')]] = pydantic.Field(default=[])
    calibration_files: list = pydantic.Field(default=[])



def start(device_info, config = None, dataqueue = None, datainqueue = None, statusqueue = None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    #print('Got config serialized', config)
    config = DeviceCustomConfig.model_validate(config)
    #print('Got config', config)
    for sensor in config.sensors:
        logger.debug('Creating metadata packet for sensor {}'.format(sensor.name))
        metadata_datapacket = sensor.create_metadata_datapacket()
        #print('Metadata datapacket',metadata_datapacket)
        sensor.add_all_calibrations(config.calibrations)
        if metadata_datapacket is not None:
            dataqueue.put(metadata_datapacket)

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
                #print('Sensor',sensor)
                #print('Type sensor', type(sensor))
                #print('data',data)
                # Checking for calibrations
                try:
                    sensordata = sensor.datapacket_process(data)
                except:
                    logger.info('Could not decode datapacket',exc_info=True)
                    sensordata = []
                #print('Sensordata',sensordata)
                if type(sensordata) is list: # List means that there was a valid packet
                    for data_packet in sensordata:
                        #print('Publishing data_packet',data_packet)
                        dataqueue.put(data_packet)


class Device(RedvyprDevice):
    """
    generic_sensor device
    """
    newcalibration_signal = QtCore.pyqtSignal()  # Signal for a new calibration
    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)
        self.calfiles_processed = []


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

    def add_calibration(self, calibration):
        """
        Adds a calibration to the calibration list, checks before, if the calibration exists
        calibration: calibration model
        """
        flag_new_calibration = True
        calibration_json = json.dumps(calibration.model_dump_json())
        for cal_old in self.custom_config.calibrations:
            if calibration_json == json.dumps(cal_old.model_dump_json()):
                flag_new_calibration = False
                break

        if flag_new_calibration:
            logger.debug('Sending new calibration signal')
            self.custom_config.calibrations.append(calibration)
            self.newcalibration_signal.emit()
            return True
        else:
            logger.warning('Calibration exists already')
            return False

    def read_calibration_file(self, fname):
        """
        Open and reads a calibration file, it will as well determine the type of calibration and call the proper function

        """
        funcname = __name__ + '.read_calibration_file():'
        logger.debug(funcname + 'Opening file {:s}'.format(fname))
        try:
            f = open(fname)
            safe_load = False
            if safe_load:
                loader = yaml.SafeLoader
            else:
                loader = yaml.CLoader

            data = yaml.load(f,Loader=loader)
            # print('data',data)
            if 'structure_version' in data.keys(): # Calibration model
                logger.debug(funcname + ' Version {} pydantic calibration model dump'.format(data['structure_version']))
                for calmodel in calibration_models: # Loop over all calibration models definded in sensor_calibrations.py
                    try:
                        calibration = calmodel.model_validate(data)
                        return calibration
                    except:
                        pass

            elif 'sn' in data.keys():
                calibration = {}
                calibration['sn'] = {}
                logger.debug(funcname + ' Version 2 file')
                for sn in data['sn'].keys():  # Add the filename the data was loaded from
                    try:
                        calibration['sn'][sn]
                    except:
                        calibration['sn'][sn] = {}
                        #calibration['sn'][sn]['coeff_files'] = []

                    #calibration['sn'][sn]['coeff_files'].append(fname)
                    calibration['sn'][sn].update(data['sn'][sn])
                    calibration['sn'][sn]['original_file'] = fname
                #    data['sn'][sn].filenames = []
                #    data['sn'][sn].filenames.append(fname)
                # self.calibration['sn'].update(data['sn'])
                return calibration

            elif 'calibration_HF_SI' in data.keys(): # Version 1 file
                logger.debug(funcname + ' Version 1 file')

                sn = data['manufacturer_sn']
                if len(sn) ==0:
                    logger.debug(funcname + ' No serial number')
                else:
                    calibration = calibration_HF(sn=sn,coeff=data['calibration_HF_SI'],date=data['calibration_date'],sensor_model = data['series'])
                    #sn:
                    #    "9299":
                    #    model: F - 005 - 4
                    #    coeffs:
                    #        HF:
                    #        coeff: 8.98
                    #        parameter: HF
                    #        unit: W m-2
                    #        unitraw: mV
                    #        date: 1970 - 01 - 01_00 - 00 - 00
                    return calibration
                    if False:
                        calibration['sn'][sn] = {}
                        calibration['sn'][sn]['model'] = data['series']
                        calibration['sn'][sn]['original_file'] = fname
                        calibration['sn'][sn]['sn'] = sn
                        calibration['sn'][sn]['parameter'] = {}
                        calibration['sn'][sn]['parameter']['HF'] = {}
                        calibration['sn'][sn]['parameter']['HF']['coeff'] = data['calibration_HF_SI']
                        calibration['sn'][sn]['parameter']['HF']['unit'] = 'W m-2'
                        calibration['sn'][sn]['parameter']['HF']['unitraw'] = 'mW'
                        calibration['sn'][sn]['parameter']['HF']['date'] = data['calibration_date']

        except Exception as e:
            logger.exception(e)
            return None

    def add_calibration_file(self, calfile, reload=True):
        funcname = __name__ + 'add_calibration_file():'
        logger.debug(funcname)
        calfiles_tmp = list(self.custom_config.calibration_files)
        if (calfile in calfiles_tmp) and reload:
            #print('Removing file first')
            self.rem_calibration_file(calfile)

        calfiles_tmp = list(self.custom_config.calibration_files)
        #print('Hallo',calfiles_tmp)
        if calfile not in calfiles_tmp:
            #print('Adding file 2',calfile)
            self.custom_config.calibration_files.append(calfile)
        else:
            logger.debug(funcname + ' File is already listed')

        self.process_calibrationfiles()

    def rem_calibration_file(self, calfile):
        funcname = __name__ + 'rem_calibration_file():'
        logger.debug(funcname)
        calfiles_tmp = list(self.custom_config.calibration_files)
        if calfile in calfiles_tmp:
            calibration = self.read_calibration_file(calfile)
            calibration_json = json.dumps(calibration.model_dump_json())
            for cal_old in self.custom_config.calibrations:
                # Test if the calibration is existing
                if calibration_json == json.dumps(cal_old.model_dump_json()):
                    logger.debug(funcname + ' Removing calibration')
                    self.custom_config.calibration_files.remove(calfile)
                    self.custom_config.calibrations.remove(cal_old)
                    self.calfiles_processed.remove(calfile)
                    return True

    def process_calibrationfiles(self):
        funcname = __name__ + '.process_calibrationfiles()'
        logger.debug(funcname)
        fnames = []

        for fname in self.custom_config.calibration_files:
            fnames.append(str(fname))

        self.coeff_filenames = fnames

        for fname in fnames:
            if fname not in self.calfiles_processed:
                logger.debug(funcname + ' reading file {:s}'.format(fname))
                calibration = self.read_calibration_file(fname)
                if calibration is not None:
                    flag_add = self.add_calibration(calibration)
                    if flag_add:
                        self.calfiles_processed.append(fname)
            else:
                logger.debug(funcname + ' file {:s} already processed'.format(fname))


        #print(self.calibration['sn'].keys())
        #self.logger_autocalibration()


class RedvyprDeviceWidget(redvypr.widgets.standard_device_widgets.RedvyprDeviceWidget_startonly):
    def __init__(self,*args,**kwargs):
        super().__init__(*args, **kwargs)
        self.devicedisplaywidget = displayDeviceWidget(device=self.device)
        icon = qtawesome.icon(iconnames['settings'])
        self.sensorshow_combo = QtWidgets.QComboBox()
        self.settings_button = QtWidgets.QPushButton('Settings')
        self.settings_button.setIcon(icon)
        self.settings_button.clicked.connect(self.settings_clicked)
        self.layout.removeWidget(self.buttons_widget)
        self.layout.removeWidget(self.killbutton)
        self.killbutton.hide()
        self.layout.addWidget(self.devicedisplaywidget,0,0)
        self.layout.addWidget(self.buttons_widget,1,0)
        self.layout_buttons.addWidget(self.sensorshow_combo, 0, 4)
        self.layout_buttons.addWidget(self.settings_button,0,5)

        self.device.config_changed_signal.connect(self.update_sensorcombo)
        self.update_sensorcombo()
        self.sensorshow_combo.currentIndexChanged.connect(self.sensorshow_changed)

    def settings_clicked(self):
        self.settings_widget = QtWidgets.QWidget()
        self.sensortable_status = sensorTableWidget(device=self.device)
        self.settings_widget_layout = QtWidgets.QVBoxLayout(self.settings_widget)
        self.initdevicewidget = initDeviceWidget(device=self.device, redvypr=self.redvypr)
        self.settings_widget_layout.addWidget(self.sensortable_status)
        self.settings_widget_layout.addWidget(self.initdevicewidget)
        self.settings_widget.show()

    def sensorshow_changed(self):
        funcname = __name__ + '.sensorshow_changed():'
        logger.debug(funcname)
        sensorname = self.sensorshow_combo.currentText()
        #print('Sensorname', sensorname)
        for irow, sensor in enumerate(self.device.custom_config.sensors):
            if sensorname == sensor.name:
                sensorwidget = sensor.__sensorwidget__
                self.devicedisplaywidget.sensor_show(sensorwidget)

    def update_sensorcombo(self):
        funcname = __name__ + '.update_sensorcombo():'
        logger.debug(funcname)
        #print('Updating...')
        self.sensorshow_combo.clear()
        for irow,sensor in enumerate(self.device.custom_config.sensors):
            name = sensor.name
            self.sensorshow_combo.addItem(name)


    def update_data(self, data):
        self.devicedisplaywidget.update_data(data)



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

        self.sensor_calibrations = QtWidgets.QPushButton('Calibrations')
        self.sensor_calibrations.clicked.connect(self.calibrations_clicked)
        self.sensorwidget_layout.addWidget(self.sensor_calibrations)

        self.layout.removeWidget(self.label)
        self.label.setParent(None)

        self.layout.addWidget(self.sensorwidget, 0,0,1,-1)
        self.update_sensortable()
        # Add the widgets to the config widget, that enables/disables them when thread is running
        self.config_widgets.append(self.sensortable)
        self.config_widgets.append(self.sensor_addbutton)
        self.config_widgets.append(self.sensor_calibrations)

    def calibrations_clicked(self):
        self.calibrationsWidget = sensorCalibrationsWidget(calibrations=self.device.custom_config.calibrations, redvypr_device = self.device)
        self.calibrationsWidget.show()

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
        # Redefined sensor
        if combo == self.sensor_combo:
            sensor = predefined_sensors[sensorindex].model_copy()
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
        layout = QtWidgets.QVBoxLayout(self)
        self.layout = layout
        self.tabwidget = tabwidget
        self.device = device
        self.sensorwidget = None # The widget showing the sensor data
        self.device.config_changed_signal.connect(self.update_sensorwidgets)
        self.update_sensorwidgets()
        try:
            sensorwidget = self.device.custom_config.sensors[0].__sensorwidget__
            self.sensor_show(sensorwidget)
        except:
            logger.info('Could not show widget',exc_info=True)

    def update_sensorwidgets(self):
        funcname = __name__ + '.update_sensorwidgets():'
        nsensors = len(self.device.custom_config.sensors)
        for irow, sensor in enumerate(self.device.custom_config.sensors):
            # Create a sensorwidget, if not existing
            try:
                sensor.__sensorwidget__
            except:
                sensor.__sensorwidget__ = SensorWidget(sensor=sensor, redvypr_device=self.device)

    def sensor_show_clicked(self):
        funcname = __name__ + '.sensor_show_clicked():'
        logger.debug(funcname)
        sensor = self.sender().__sensor__
        self.sensor_show(sensor.__sensorwidget__)

    def sensor_show(self,sensorwidget):
        try:
            self.layout.removeWidget(self.sensorwidget)
            self.sensorwidget.hide()
            # sensorwidget_old = self.splitter.replaceWidget(1,self.sensorwidget)
            # sensorwidget_old.hide()
        except:
            logger.debug('Could not remove widget', exc_info=True)
            # self.splitter.addWidget(self.sensorwidget)

        self.sensorwidget = sensorwidget
        self.layout.addWidget(self.sensorwidget)
        self.sensorwidget.show()

    def sensor_plot_clicked(self):
        pass
        #print('Plot')
    def thread_status(self, status):
        """ This function is regularly called by redvypr whenever the thread is started/stopped
        """
        pass
        # self.update_buttons(status['threadalive'])



    def update_data(self, data):
        """
        """
        funcname = __name__ + '.update_data()'
        tnow = time.time()
        for sensor in self.device.custom_config.sensors:
            try:
                sensor.__sensorwidget__.update_data(data)
            except:
                logger.info('Could not update',exc_info=True)



class SensorWidget(QtWidgets.QWidget):
    def __init__(self, *args, sensor=None, redvypr_device=None, **kwargs):
        funcname = __name__ + '__init__():'
        #logger.debug(funcname)
        self.packets_received = 0
        self.packets_for_me = 0
        self.packets_for_me_old = 0
        self.sensor = sensor
        self.device = redvypr_device
        #print('Sensor',self.sensor)
        super().__init__(*args, **kwargs)
        self.layout = QtWidgets.QHBoxLayout(self)
        #self.label = QtWidgets.QLabel(self.sensor.name)
        self.sensor_address = RedvyprAddress('/d:{}'.format(sensor.name))
        # Table showing the different packetids, which are used to distinguis different sensors
        self.packetidtable = QtWidgets.QTableWidget()
        self.packetidtable.setRowCount(0)
        self.packetidtable.setColumnCount(2)
        self.packetidtable.cellClicked.connect(self.packetid_changed)
        self.datatable = QtWidgets.QTableWidget()
        self.datatable.setRowCount(2)
        self.datatable.setColumnCount(4)
        colheaders = ['Datakey', 'Data', 'Unit', 'XY-Plot']
        self.datatable.setHorizontalHeaderLabels(colheaders)
        self.datakey_items = {} # Dictionary with the tablewidgetitems
        self.datakey_units = {} # Dictionary with the units
        self.datakey_plot = {}# Dictionary with the plot widgets
        self.datakey_plot_data = {}  # Dictionary with the data for the plots
        self.bufferlen = 1000
        self.last_packet = {}  # Dictionary with the plot widgets
        self.packetids = []  # Dictionary with the plot widgets
        self.icol_key = 0
        self.icol_data = 1
        self.icol_unit = 2
        self.icol_plot = 3
        item_key_tstr = QtWidgets.QTableWidgetItem('Time')
        item_key_tustr = QtWidgets.QTableWidgetItem('Time (unix)')
        #self.datatable.setItem(0, self.icol_data, item_tustr)
        #self.datatable.setItem(1, self.icol_data, item_tstr)
        self.datatable.setItem(0, self.icol_key, item_key_tustr)
        self.datatable.setItem(1, self.icol_key, item_key_tstr)

        #self.layout.addWidget(self.label,1)
        self.layout.addWidget(self.packetidtable,1)

        self.layout.addWidget(self.datatable,4)
        self.__packetid_selected = None

    def packetid_changed(self,row,column):
        funcname = __name__ + '.packetid_changed():'
        logger.debug(funcname)
        #print('Packetid changed')
        try:
            packetid = self.packetidtable.item(row,column).text()
            self.__packetid_selected = packetid
            data = self.last_packet[packetid]
            #print('Updating with',packetid)
            #print('Data',data)
            self.datakey_items = {}  # Dictionary with the tablewidgetitems
            self.datakey_units = {}  # Dictionary with the units
            self.__packetid_selected = packetid
            #self.datatable.clear()
            self.datatable.setRowCount(2)
            self.update_data(data)
        except:
            logger.info('Could not change packeid:',exc_info=True)
            packetid = None


        #print(funcname, row, column, packetid)

    def sensor_plot_clicked(self):
        funcname = __name__ + '.sensor_plot_clicked():'
        logger.debug(funcname)
        # No XY-Plot yet, create one
        if self.sender().__xyplot__ is None:
            packetid = self.sender().__packetid__
            k = self.sender().__k__
            logger.debug(funcname + 'Plot clicked, creating XY-Plotwidget')
            logger.debug(funcname + 'sensor address: {} packetid: {}, k: {}'.format(self.sensor_address,packetid,k))
            config_plot = configXYplot(automatic_subscription=False)
            self.datakey_plot[packetid][k] = XYPlotWidget(config=config_plot, add_line=False,
                                                          redvypr_device=self.device)
            yaddr = RedvyprAddress(self.sensor_address, datakey=k, packetid=packetid)

            logger.debug(funcname + 'yaddr: {}'.format(yaddr))
            self.datakey_plot[packetid][k].add_line(yaddr)
            self.sender().__xyplot__ = self.datakey_plot[packetid][k]
            self.datakey_plot[packetid][k].__item_plot__ = self.sender()
            self.datakey_plot[packetid][k].closing.connect(self.__xyplot_closed__)
            windowtitle = 'Plot {} {}'.format(packetid, k)
            self.sender().__xyplot__.setWindowTitle(windowtitle)
            # Adding the buffer data
            buffer_tmp = self.datakey_plot_data[packetid]
            logger.debug(funcname + 'Updating plot with buffer data')
            for data_tmp in buffer_tmp:
                self.datakey_plot[packetid][k].update_plot(data_tmp)


        self.sender().__xyplot__.show()

    def __xyplot_closed__(self):
        funcname = __name__ + '.__xyplot_closed__():'
        logger.debug(funcname)
        xyplot = self.sender()
        item_plot = xyplot.__item_plot__
        packetid = item_plot.__packetid__
        k = item_plot.__k__
        self.datakey_plot[packetid][k] = None
        item_plot.__xyplot__ = None
        xyplot.deleteLater()
        xyplot.setParent(None)
        logger.debug(funcname + 'Closed')

    def __metadata_clicked(self):
        button = self.sender()
        filter_address = RedvyprAddress(packetid='==' + button.__metadata_raddress__.packetid)

        packetid = button.__packetid__
        self.__metawidget = datastreamMetadataWidget(redvypr=self.device.redvypr, device=self.device,
                                                     filter_include=[filter_address])
        self.__metawidget.show()

    def update_data(self, data):
        funcname = __name__ + '.update_data():'
        logger.debug(funcname + 'Got data for sensor {}'.format(self.sensor.name))
        #print('Fresh data:',data,type(data))
        if data in self.sensor_address:
            #print(funcname + ' Datapacket fits, Processing data')
            rdata = redvypr.data_packets.Datapacket(data)
            # Packets are sorted according to the packetid, as this is including the serialnumber
            packetid = rdata.address.packetid
            #print('Got data',rdata)
            #print('Packetid',packetid)

            # Try to update plotdata
            try:
                self.datakey_plot_data[packetid]
            except:
                self.datakey_plot_data[packetid] = []

            self.datakey_plot_data[packetid].append(data)
            if len(self.datakey_plot_data[packetid]) > self.bufferlen:
                self.datakey_plot_data[packetid].pop(0)
            # Check if the packetid has been seen before
            if packetid not in self.packetids and len(packetid) > 0 and (rdata.address.packetidexpand == False):
                self.packetids.append(packetid)
                self.packetidtable.clear()
                self.packetidtable.setRowCount(len(self.packetids))
                self.packetidtable.setHorizontalHeaderLabels(['Packetids for sensor {}'.format(self.sensor.name),'Metadata'])
                for i,p in enumerate(self.packetids):
                    packetiditem = QtWidgets.QTableWidgetItem(p)
                    packetiditem.setFlags(packetiditem.flags() & ~QtCore.Qt.ItemIsEditable)
                    self.packetidtable.setItem(i,0,packetiditem)
                    item_metadata = QtWidgets.QPushButton('Metadata')
                    item_metadata.__packetid__ = packetid
                    item_metadata.__metadata_raddress__ = RedvyprAddress(rdata.address)
                    item_metadata.clicked.connect(self.__metadata_clicked)
                    # self.datakey_plot[packetid][k].__item_plot__ = item_plot
                    icol_metadata = 1
                    self.packetidtable.setCellWidget(i, icol_metadata, item_metadata)
                    if p == self.__packetid_selected:
                        self.packetidtable.setCurrentCell(i, 0)

                self.packetidtable.resizeColumnsToContents()
                if self.__packetid_selected is None:
                    self.__packetid_selected = p
                    self.packetidtable.setCurrentCell(i, 0)

            #print('Packetid',packetid,self.packetids)
            keys = rdata.datakeys(expand=True, return_type='list')
            # Update the last packet dictionary
            if 't' in keys:
                self.last_packet[packetid] = rdata
            # Updating the metadata
            if True: # TODO, this should be done based on a signal notifying that the metadata has changed
                logger.debug('Updating keyinfo')
                # This should be done with device.get_metadata
                #for k in data['_keyinfo'].keys():
                for k in keys:
                    try:
                        self.datakey_units[k]
                    except:
                        raddr_tmp = RedvyprAddress(data,datakey=k)
                        logger.debug(funcname + 'Trying to get metadata for address {}'.format(raddr_tmp))
                        metadata = self.device.get_metadata(raddr_tmp)
                        #print(funcname + ' Got Metadata ...', metadata)
                        try:
                            self.datakey_units[k] = metadata['unit']
                        except:
                            self.datakey_units[k] = None

                    # Update the plot first or create new plot widget
                    if 't' in keys and k is not 't':
                        # Try to update plots
                        try:
                            self.datakey_plot[packetid]
                        except:
                            self.datakey_plot[packetid] = {}
                        try:
                            xyplot = self.datakey_plot[packetid][k]
                            if xyplot is not None:
                                self.datakey_plot[packetid][k].update_plot(data)
                        except:
                            logger.debug('Could not update plot', exc_info=True)
                            logger.debug(funcname + 'Adding XY-Plot (None)')
                            self.datakey_plot[packetid][k] = None

            # Updating the raw data
            flag_packetid = (packetid == self.__packetid_selected)
            #print('Hallo', 'Packetid', packetid, 'Selected', self.__packetid_selected, flag_packetid)
            if 't' in keys:
                self.packets_for_me += 1
            if 't' in keys and flag_packetid:
                #print('Correct packetid, updating table')
                t = keys.remove('t')
                # Display always the time
                tdata = datetime.datetime.utcfromtimestamp(data['t'])
                tudatastr = str(data['t'])
                tdatastr = tdata.strftime('%Y-%m-%d %H:%M:%S.%f')
                try:
                    self.datakey_items['t'][0]
                except:
                    item_tstr = QtWidgets.QTableWidgetItem('NA')
                    item_tustr = QtWidgets.QTableWidgetItem('NA')
                    item_tustr.setText(tudatastr)
                    item_tstr.setText(tdatastr)
                    self.datakey_items = {}
                    self.datakey_items['t'] = [item_tustr, item_tstr]
                    self.datatable.setItem(0, self.icol_data, item_tustr)
                    self.datatable.setItem(1, self.icol_data, item_tstr)

                for k in keys:
                    if True:
                        # Datastring to be displayed
                        datastr = str(rdata[k]) # This can be done more fancy
                        if k not in self.datakey_items:
                            nrows = self.datatable.rowCount()
                            logger.debug(funcname + 'Creating new item {}'.format(nrows))
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
                            # Add a XY-Plot, if datatype fits
                            #if isinstance(data[k], numbers.Number):
                            try:
                                xyplot = self.datakey_plot[packetid][k]
                                plot_icon = qtawesome.icon('ph.chart-line-fill')
                                #item_plot = QtWidgets.QPushButton(plot_icon, 'Plot {} {}'.format(packetid, k))
                                item_plot = QtWidgets.QPushButton(plot_icon, 'Plot')
                                item_plot.__xyplot__ = self.datakey_plot[packetid][k]
                                item_plot.__packetid__ = packetid
                                item_plot.__k__ = k
                                item_plot.clicked.connect(self.sensor_plot_clicked)
                                #self.datakey_plot[packetid][k].__item_plot__ = item_plot
                                self.datatable.setCellWidget(nrows, self.icol_plot, item_plot)
                            except:
                                logger.warning('Could not get item_plot',exc_info=True)
                                item_plot = None


                            self.datakey_items[k] = [nrows, datakeyitem, dataitem, dataunititem, item_plot]
                        else:
                            #print('Just updating',datastr,k)
                            # Data
                            # This could be only done less brute force if packetid has been changed ...
                            irow = self.datakey_items[k][0]
                            nrows = self.datatable.rowCount()
                            datakeyitem = self.datakey_items[k][1]
                            dataitem = self.datakey_items[k][2]
                            dataunititem = self.datakey_items[k][3]
                            item_plot = self.datakey_items[k][4]
                            #print('dataitem',dataitem.text())
                            dataitem.setText(datastr)
                            # Unit
                            try:
                                unit = self.datakey_units[k]
                                dataunititem.setText(unit)
                            except:
                                pass
                                #logger.debug('Could not update unit',exc_info=True)


                self.datatable.resizeColumnsToContents()



class sensorTableWidget(QtWidgets.QWidget):
    """ Widget is displaying all defined sensors
    """

    def __init__(self, device=None):
        funcname = __name__ + '.__init__()'
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.layout = layout
        self.device = device
        # A timer that is regularly calling the device.status function
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_status)
        self.dt_update = 1
        self.sensortable = QtWidgets.QTableWidget()
        self.layout.addWidget(self.sensortable)
        self.device.config_changed_signal.connect(self.update_sensortable)
        # The table columns
        self.icol_name = 0
        self.icol_packet_proc = 1
        self.icol_packet_proc__s = 2
        self.icol_show = 3
        self.icol_plot = 4
        self.update_sensortable()
        self.statustimer.start(self.dt_update * 1000)

    def update_sensortable(self):
        funcname = __name__ + '.update_sensortable():'
        nsensors = len(self.device.custom_config.sensors)
        self.sensortable.clear()
        self.sensortable.setRowCount(nsensors)
        colheaders = ['Name', 'Packets processed', 'Packets/s']
        self.sensortable.setColumnCount(3)
        self.sensortable.setHorizontalHeaderLabels(colheaders)

        for irow, sensor in enumerate(self.device.custom_config.sensors):
            # Create a sensorwidget, if not existing
            try:
                sensor.__sensorwidget__
            except:
                logger.warning('Could not find widget for sensor')
                continue

            name = sensor.name
            item_name = QtWidgets.QTableWidgetItem(name)
            self.sensortable.setItem(irow, self.icol_name, item_name)

            #show_icon = qtawesome.icon('ei.list')
            #item_show = QtWidgets.QPushButton(show_icon, 'Show')
            #item_show.__sensor__ = sensor
            #item_show.clicked.connect(self.sensor_show_clicked)
            #self.sensortable.setCellWidget(irow, self.icol_show, item_show)

            npackets = sensor.__sensorwidget__.packets_for_me
            item_packet = QtWidgets.QTableWidgetItem(str(npackets))
            self.sensortable.setItem(irow, self.icol_packet_proc, item_packet)

            item_packet__s = QtWidgets.QTableWidgetItem(str(0))
            self.sensortable.setItem(irow, self.icol_packet_proc__s, item_packet__s)

        self.sensortable.resizeColumnsToContents()

    def update_status(self):
        """
        """
        funcname = __name__ + 'update_status():'
        try:
            statusdata = self.device.get_status()
            # print(funcname + str(statusdata))
        except:
            logger.debug(funcname,exc_info=True)

        # update the
        for isensor, sensor in enumerate(self.device.custom_config.sensors):
            npackets_old = sensor.__sensorwidget__.packets_for_me_old
            npackets = sensor.__sensorwidget__.packets_for_me
            npackets__s = (npackets - npackets_old)/self.dt_update
            sensor.__sensorwidget__.packets_for_me_old = npackets

            item = self.sensortable.item(isensor, self.icol_packet_proc)
            item.setText(str(npackets))

            item = self.sensortable.item(isensor, self.icol_packet_proc__s)
            item.setText(str(npackets__s))


