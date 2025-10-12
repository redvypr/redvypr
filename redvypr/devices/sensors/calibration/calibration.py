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
#from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import random
import pydantic
import typing
from collections.abc import Iterable
import numpy
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import check_for_command
from redvypr.device import RedvyprDevice
import redvypr.files as redvypr_files
import redvypr.gui
import redvypr.data_packets
from redvypr.devices.plot import XYPlotWidget
from .calibration_models import CalibrationData, CalibrationPoly, CalibrationNTC
from .calibration_type_widgets import  CalibrationCalculationWidget, ConfigWidgetInitNTC, ConfigWidgetInitPolynom
from .autocalibration import  Autocalentry, Autocalconfig, Autocalwidget
_logo_file = redvypr_files.logo_file
_icon_file = redvypr_files.icon_file
description = 'Calibration of sensors'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.calibration')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

calibration_types = ["Polynom","NTC"]
calibration_types_config_widgets = {"polynom":ConfigWidgetInitPolynom,"ntc":ConfigWidgetInitNTC}

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = 'Calibration of sensors'
    gui_tablabel_display: str = 'Realtime data'


def get_uuid():
    return 'CAL_' + str(uuid.uuid4())


class CalibrationSensorAndConfigData(CalibrationData):
    rawdata: list = pydantic.Field(default=[])
    time_rawdata: list = pydantic.Field(default=[])
    realtimeplottype: typing.Literal['Table', 'XY-Plot'] = pydantic.Field(default='Table', description='Type of realtimedataplot')
    calibrationtype: typing.Literal['polynom', 'ntc'] = pydantic.Field(default='polynom')
    order_coeff: int = pydantic.Field(default=0,description='Order coefficient for polynom used for fit')
    calibration_config: None | CalibrationPoly | CalibrationNTC = pydantic.Field(default=None,description='Calibration configuration')

class DeviceCustomConfig(pydantic.BaseModel):
    calibrationdata: typing.Optional[typing.List[CalibrationSensorAndConfigData]] = pydantic.Field(default=[])
    calibrationdata_time: typing.Optional[typing.List] = pydantic.Field(default=[])
    #calibration_coeffs: typing.Optional[typing.List] = pydantic.Field(default=[])
    calibrationtype_default: typing.Literal['polynom', 'ntc'] = pydantic.Field(default='polynom')
    calibrationtype_extra: typing.Dict = pydantic.Field(default={})
    ind_ref_sensor: int = -1
    name_ref_sensor: str = ''
    dataformat: str = '{:.4f}'
    calibration_id: str = ''
    calibration_uuid: str = pydantic.Field(default_factory=get_uuid)
    calibration_comment: str = ''
    calibration_file_structure: str = pydantic.Field(default='{SENSOR_MODEL}_{SN}_{PARAMETER}_{CALDATE}.yaml')
    calibration_directory_structure: str = pydantic.Field(default='{SENSOR_MODEL}/{SN}/{PARAMETER}/')
    autocal: bool = pydantic.Field(default=True)
    autocal_config: Autocalconfig = pydantic.Field(default=Autocalconfig())
    gui_realtimedata_ncols: int = 3

class Device(RedvyprDevice):
    """
    heatflow_serial device
    """

    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)
        logger.debug(funcname)
        # Check the number of sensors and of the ref sensors is valid
        nsensors = len(self.custom_config.calibrationdata)
        iref = self.custom_config.ind_ref_sensor
        if(iref >= nsensors):
            logger.warning('Index of reference sensor is larger than number of sensors, resetting to zero')
            self.custom_config.ind_ref_sensor = -1


        self.subscribe_to_sensors()

    def create_sensor_calibration_config_legacy(self, newsen: str | RedvyprAddress, sentype='datastream', calibrationtype=None, calconfig=None):
        cal_object = None
        if sentype == 'datastream':
            channel = newsen.datakey
        else:
            channel = ''

        if calibrationtype.lower() == "ntc":
            # And finally the fit
            Toff = calconfig['Toff']
            poly_degree = calconfig['poly_degree']
            cal_object = CalibrationNTC(channel=channel, Toff=Toff, poly_degree=poly_degree)

        elif calibrationtype.lower() == "polynom":
            poly_degree = calconfig['poly_degree']
            cal_object = CalibrationPoly(channel=channel,poly_degree=poly_degree)

        return cal_object

    def create_calibration_object_and_calc_coeff_for_sensor(self, sensor):
        funcname = __name__ + ".create_calibration_object_and_calc_coeff_for_sensor()"
        print(funcname)
        refindex = self.custom_config.ind_ref_sensor
        print('Refindex', refindex)
        print("Sensor ")
        print(sensor)
        print("Sensor done")
        if sensor is None:
            print('sensor is None')
            return None
        if refindex >= 0 and (len(self.custom_config.calibrationdata_time) > 0):
            calibration_data_reference = CalibrationData(**self.custom_config.calibrationdata[refindex].model_dump())
            calibrationtype = sensor.calibrationtype
            calibration_data = CalibrationData(**sensor.model_dump())
            print("calibration_data")
            print(calibration_data)
            print("calibration_data_reference")
            print(calibration_data_reference)
            print("calibrationdata done")
            calibration_final = sensor.calibration_config.model_copy() # Create a calibration object
            # Fill in the data
            calibration_final.channel = RedvyprAddress(sensor.channel)
            calibration_final.sn = sensor.sn
            calibration_final.sensor_model = sensor.sensor_model
            calibration_final.calibration_uuid = self.custom_config.calibration_uuid
            calibration_final.calibration_id = self.custom_config.calibration_id
            calibration_final.calibration_data = calibration_data
            calibration_final.calibration_reference_data = calibration_data_reference
            tdata = calibration_data.time_data[0]
            tdatetime = datetime.datetime.fromtimestamp(tdata, datetime.timezone.utc)
            tdatas = tdatetime.strftime('%Y-%m-%d %H:%M:%S.%f%z')
            calibration_final.date = tdatetime
            calibration_final.calc_coeffs()
            print("Calibration final")
            print(calibration_final)
            print("Calibration final done")
            return calibration_final


    def add_sensor_calibration_config(self, sensor, calconfig=None):
        print("Adding calconfig",calconfig)
        cal_object = None
        channel = sensor.channel
        calibrationtype = sensor.calibrationtype

        if calibrationtype.lower() == "ntc":
            # And finally the fit
            Toff = calconfig['Toff']
            poly_degree = calconfig['poly_degree']
            cal_object = CalibrationNTC(channel=channel, Toff=Toff, poly_degree=poly_degree)

        elif calibrationtype.lower() == "polynom":
            poly_degree = calconfig['poly_degree']
            cal_object = CalibrationPoly(channel=channel, poly_degree=poly_degree)


        print("Cal object",cal_object)
        print("Cal object done")
        sensor.calibration_config = cal_object

    def add_sensor(self, newsen: str | RedvyprAddress, sentype='datastream', calibrationtype=None, calconfig=None):
        funcname = __name__ + '.add_sensor()'
        logger.debug(funcname + ' Adding new sensor with name: "{:s}"'.format(str(newsen)))
        sentype = str(sentype)
        #cal_object = self.create_sensor_calibration_config(newsen, sentype=sentype, calibrationtype=calibrationtype, calconfig=calconfig)
        #newsen = str(newsen)
        if sentype == 'datastream':
            logger.debug(funcname + ' Adding datastream of sensor {}'.format(newsen))
            sensor = CalibrationSensorAndConfigData(datastream=newsen, channel=newsen.datakey, inputtype=sentype,
                                                    calibrationtype=calibrationtype, calibration_config=None)
            self.custom_config.calibrationdata.append(sensor)
            index = len(self.custom_config.calibrationdata) - 1
        else:
            logger.debug(funcname + ' Adding manual sensor')
            #print('config',str(newsen))
            sensor = CalibrationSensorAndConfigData(inputtype=sentype, calibrationtype=calibrationtype, calibration_config=None)
            self.custom_config.calibrationdata.append(sensor)
            index = len(self.custom_config.calibrationdata) - 1

        # Adding calibration_config
        self.add_sensor_calibration_config(sensor, calconfig)
        self.__make_calibrationdata_equally_long__()
        self.subscribe_to_sensors()


    def rem_sensor(self, index, sentype='datastream'):
        funcname = __name__ + '.rem_sensor()'
        logger.debug(funcname)
        if True:
            self.custom_config.calibrationdata.pop(index)
            #self.devicedisplaywidget.datastreams.pop(index)
            if len(self.custom_config.calibrationdata) == 0:
                self.custom_config.calibrationdata_time = []

    def subscribe_to_sensors(self):
        funcname = __name__ + '.subscribe_to_sensors():'
        logger.debug(funcname)
        self.unsubscribe_all()
        for i,sdata in enumerate(self.custom_config.calibrationdata):
            if sdata.inputtype == 'datastream':
                datastream = sdata.datastream
                if len(datastream) > 0:
                    logger.debug(funcname + 'subscribing to {}'.format(datastream))
                    self.subscribe_address(datastream)

    def rem_data(self, index):
        funcname = __name__ + '.rem_data()'
        logger.debug(funcname)
        self.custom_config.calibrationdata_time.pop(index)
        if True:
            for sdata in self.custom_config.calibrationdata:
                sdata.data.pop(index)
                sdata.rawdata.pop(index)
                sdata.time_data.pop(index)
                sdata.time_rawdata.pop(index)


    def add_data(self, time, sensorindex, data, time_data, rawdata, time_rawdata):
    #self.device.add_data(tget, p.sensorindex, 'datastream', ydata, tdata, rawdata_all, timedata_all)
        """
        Adds/modifies data to the sensor @ sensorindex
        sentype = datastream, manual
        """
        funcname = __name__ + '.add_data()'
        logger.debug(funcname)
        # Search first if there has been an entry already
        flag_new_entry = True
        for i,t in enumerate(self.custom_config.calibrationdata_time):
            if t == time:
                flag_new_entry = False
                break

        # create a new entry
        if flag_new_entry:
            self.custom_config.calibrationdata_time.append(time)
            i = len(self.custom_config.calibrationdata_time) - 1
            for sdata in self.custom_config.calibrationdata:
                sdata.data.append(np.nan)
                sdata.rawdata.append(np.nan)
                sdata.time_data.append(np.nan)
                sdata.time_rawdata.append(np.nan)

        # And finally add the data
        sdata = self.custom_config.calibrationdata[sensorindex]
        sdata.data[i] = data
        sdata.rawdata[i] = rawdata
        sdata.time_data[i] = float(time_data)
        sdata.time_rawdata[i] = time_rawdata

        self.__make_calibrationdata_equally_long__()

    def __make_calibrationdata_equally_long__(self):
        funcname = __name__ + '.__make_calibrationdata_equally_long__()'
        logger.debug(funcname)
        # Check if all lists have the same length, if not, fill them with None
        lmax = 0
        if True:
            for sdata in self.custom_config.calibrationdata:
                lmax = max(len(sdata.data),lmax)


        #print('lmax',lmax)
        if True:
            for sdata in self.custom_config.calibrationdata:
                while len(sdata.data) < lmax:
                    sdata.data.append(np.nan)
                    sdata.rawdata.append(np.nan)
                    sdata.time_data.append(np.nan)
                    sdata.time_rawdata.append(np.nan)

    def save_calibrations(self, folder, calibrations):
        """
        Saves a list of calibrations into a folder structure

        :param folder:
        :return:
        """
        funcname = __name__ + '__save_calibration__():'
        overwrite = True
        create_path = True
        fnames_full = self.save_widget_dict['fnames_full']
        #calibration_file_structure: str = pydantic.Field(default='{SENSOR_MODEL}_{SN}_{PARAMETER}_{CALDATE}.yaml')
        #calibration_directory_structure: str = pydantic.Field(default='{SENSOR_MODEL}/{SN}/{PARAMETER}/')
        for cal in calibrations:
            folder_path_orig = self.custom_config.calibration_directory_structure
            folder_path = folder_path_orig.format(SENSOR_MODEL=cal.sensor_model, SN=cal.sn, PARAMETER=cal.channel)
            calfilename_orig = self.custom_config.calibration_file_structure
            calfilename = calfilename_orig(SENSOR_MODEL=cal.sensor_model, SN=cal.sn, PARAMETER=cal.channel)
            fname_full = os.path.join(folder_path,calfilename)
            if os.path.isdir(folder_path):
                print('Path exists: {}'.format(folder_path))
            else:
                print('Creating directory: {}'.format(folder_path))
                os.mkdir(folder_path)

            if os.path.isfile(fname_full):
                logger.warning('File is already existing {:s}'.format(fname_full))
                file_exist = True
            else:
                file_exist = False

            if overwrite or (file_exist == False):
                logger.info('Saving file to {:s}'.format(fname_full))
                if cal.comment == 'reference sensor':
                    logger.debug(funcname + ' Will not save calibration (reference sensor)')
                else:
                    cdump = cal.model_dump()
                    # data_save = yaml.dump(cdump)

                    with open(fname_full, 'w') as fyaml:
                        yaml.dump(cdump, fyaml)
                    print('Cal', cal)

def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Starting calibration data read thread')

    while True:
        data = datainqueue.get(block=True)
        #print('Read data',data)
        command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
        # logger.debug('Got a command: {:s}'.format(str(data)))
        if (command is not None):
            if command == 'stop':
                sstr = funcname + ': Command is for me: {:s}'.format(str(command))
                logger.debug(sstr)
                return
        else:
            dataqueue.put(data)







class QTableCalibrationWidget(QtWidgets.QTableWidget):
    def __init__(self, *args, device=None, **kwargs):
        """ Widget to show realtime calibration data """
        try:
            sensorindex = kwargs.pop('sensorindex')
        except:
            sensorindex = -1

        QtWidgets.QTableWidget.__init__(self, *args, **kwargs)
        self.data_buffer = []
        self.data_buffer_t = []
        self.data_buffer_len = 2000
        self.headerlabel = None
        self.sensorindex = sensorindex
        self.device = device
        self.setColumnCount(1)
        hlabel = "{}:".format(sensorindex)
        self.setHorizontalHeaderLabels([hlabel])
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)

    def get_data(self, t_intervall):
        funcname = __name__ + '.get_data():'
        logger.info(funcname)
        ## Relative data
        #if (t_intervall[0] <= 0) and (t_intervall[1] <= 0):
        #    t_intervall[0] = t_intervall[0] + self.data_buffer_t[-1]
        #    t_intervall[1] = t_intervall[1] + self.data_buffer_t[-1]

        ttmp = np.asarray(self.data_buffer_t)
        ind = (ttmp >= min(t_intervall)) & (ttmp <= max(t_intervall))
        print(funcname, 'ind', ind)
        data = {'t': [], 'x': [], 'y': []}
        if sum(ind) > 0:
            indi = np.where(ind)[0]
            #print('indi', indi)
            for i in indi:
                data['t'].append(self.data_buffer_t[i])
                data['x'].append(self.data_buffer_t[i])
                data['y'].append(self.data_buffer[i])

            #print('Shape',np.shape(data['y']))
        else:
            pass

        data['t'] = np.asarray(data['t'])
        data['y'] = np.asarray(data['y'])
        data['x'] = np.asarray(data['x'])
        return data


    def update_plot(self, data):
        #print('QTableCalibrationWidget, updating',data)

        try:
            #print('Datastream',self.datastream,type(self.datastream))
            # self.datastream is defined in the displayWidget
            daddr = redvypr.RedvyprAddress(self.datastream)
            dindex = self.sensorindex
            rdata = redvypr.data_packets.Datapacket(data)
        except:
            logger.info('No datastream yet ',exc_info=True)
            daddr = None

        if daddr is not None:
            if rdata in daddr:
                #print('Got data to update')
                data_tmp = rdata[daddr.datakey]
                data_tmp_t = rdata['t']
                if isinstance(data_tmp, numpy.ndarray):
                    data_final = numpy.mean(data_tmp)
                    data_final_t = numpy.mean(data_tmp_t)
                    # Generic Iterables (Listen, Tupel, Sets, Generatoren)
                elif isinstance(data_tmp, Iterable):
                    data_final = numpy.mean(data_tmp)
                    data_final_t = numpy.mean(data_tmp_t)
                else:
                    data_final = data_tmp
                    data_final_t = data_tmp_t

                self.data_buffer.append(data_final)
                self.data_buffer_t.append(data_final_t)

                if len(self.data_buffer) > self.data_buffer_len:
                    self.data_buffer.pop(0)
                    self.data_buffer_t.pop(0)

                # Update the realtime datatable
                self.setRowCount(1)

                if True:
                    self.setColumnCount(1)
                    dstr = str(data_final)
                    item = QtWidgets.QTableWidgetItem(dstr)
                    self.setItem(0, 0, item)

                #print('len data buffer', self.data_buffer_t)
                #self.resizeColumnsToContents()
                ncols = self.rowCount()
                header = self.horizontalHeader()
                header.setSectionResizeMode(ncols-1, QtWidgets.QHeaderView.Stretch)
                if self.headerlabel is None:
                    hlabel = "{}:".format(dindex) + daddr.get_str('/k')
                    if self.device is not None:
                        metadata = self.device.get_metadata(daddr)
                        #print("Metadata of datapaket", rdata)
                        #print("Metadata: ", daddr, metadata)
                        try:
                            unitstr = metadata["unit"]
                        except:
                            unitstr = ""

                        if len(unitstr) > 0:
                            hlabel += " [{}]".format(unitstr)

                    self.headerlabel = hlabel
                    self.setHorizontalHeaderLabels([hlabel])
                    self.setVerticalHeaderLabels([])
                    header = self.horizontalHeader()
                    header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)



class PlotCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.fig = fig
        FigureCanvas.__init__(self, fig)
        self.setParent(parent)
        FigureCanvas.setSizePolicy(self, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        FigureCanvas.updateGeometry(self)
        #self.plot_rand()

    def plot_rand(self):
        data = [random.random() for i in range(25)]
        ax = self.figure.add_subplot(111)
        ax.plot(data, 'r-')
        ax.set_title('PyQt and Matplotlib Demonstration')
        self.draw()


def fit_ntc_legacy(T,R,Toff, poly_degree=3):
    TK = T + Toff
    T_1 = 1 / (TK)
    # logR = log(R/R0)
    logR = np.log(R)
    P_R = np.polyfit(logR, T_1, poly_degree)
    return {'P_R':P_R}

def calc_ntc_legacy(R,P_R,Toff):
    T_1 = np.polyval(P_R,np.log(R))
    T = 1/T_1 - Toff
    return T

def calc_NTC_legacy(calibration, R):
    """
    Calculate the temperature based on the calibration and a resistance
    """
    P_R = calibration.coeff
    Toff = calibration.Toff
    T_1 = np.polyval(P_R,np.log(R))
    T = 1/T_1 - Toff
    return T





#
#
# Init
#
#
class initDeviceWidget(QtWidgets.QWidget):
    connect = QtCore.pyqtSignal(
        RedvyprDevice)  # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices

    def __init__(self, device=None, tabwidget=None):
        """
        Standard deviceinitwidget if the device is not providing one by itself.

        Args:
            device:
        """
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.config_widgets = []
        self.device = device
        self.tabwidget = tabwidget
        # Create widgets to choose the datastreams and manual sensors
        self.createSensorInputWidgets()
        # Start-button
        self.startbutton = QtWidgets.QPushButton('Start')
        self.startbutton.clicked.connect(self.start_clicked)
        self.startbutton.setCheckable(True)
        # Process kill button (if thread)
        if (self.device.mp == 'multiprocess')  or (self.device.mp == 'qthread'):
            # Killbutton
            self.killbutton = QtWidgets.QPushButton('Kill process')
            self.killbutton.clicked.connect(self.kill_clicked)

        # Connect button
        self.conbutton = QtWidgets.QPushButton("Subscribe")
        self.conbutton.clicked.connect(self.connect_clicked)
        self.config_widgets.append(self.conbutton)


        self.layout.addWidget(self.sensorsConfig, 0, 0, 1, 4)
        self.layout.addWidget(self.conbutton, 1, 0, 1, 4)
        if (self.device.mp == 'multiprocess') or (self.device.mp == 'qthread'):
            self.layout.addWidget(self.startbutton, 2, 0, 1, 3)
            self.layout.addWidget(self.killbutton, 2, 3)
        else:
            self.layout.addWidget(self.startbutton, 2, 0, 1, 4)

        # If the config is changed, update the device widget

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)
        #self.config_widget.config_changed_flag.connect(self.config_changed)

    def createSensorInputWidgets(self):
        """

        """
        self.sensorsConfig = QtWidgets.QWidget()
        self.sensorsConfig_layout = QtWidgets.QVBoxLayout(self.sensorsConfig)
        self.populateSensorInputWidgets()

    def clearInputWidgets(self):

        # Clear all widgets and draw them again
        layout = self.sensorsConfig_layout
        while layout.count():
            item = layout.takeAt(0)
            # item.close()
            widget = item.widget()
            widget.deleteLater()
            # widget.close()

    def populateSensorInputWidgets(self):

        # Clear all widgets and draw them again
        layout = self.sensorsConfig_layout
        while layout.count():
            item = layout.takeAt(0)
            # item.close()
            widget = item.widget()
            widget.deleteLater()
            #widget.close()

        self.sensoradd = QtWidgets.QPushButton('Add sensor')  # Add a sensor
        self.sensoradd.clicked.connect(self.sensorAddClicked)
        self.sensorsadd = QtWidgets.QPushButton('Add sensors')  # Add several sensor by choosing a list of datastreams
        self.sensorsadd.clicked.connect(self.sensorsAddClicked)
        self.mansensoradd = QtWidgets.QPushButton('Add manual sensor')  # Add a manual sensor
        self.mansensoradd.clicked.connect(self.sensorAddClicked)
        self.autocalbtn = QtWidgets.QPushButton('Autocalibration')  # Add an autocalibration
        autocalibration = self.device.custom_config.autocal
        self.autocalbtn.setCheckable(True)  #
        self.autocalbtn.setChecked(autocalibration) # Set the checked state, the action is done in the displaywidget.__init__
        self.autocalbtn.clicked.connect(self.sensorAutocalClicked)


        self.caltype = QtWidgets.QComboBox()  # Calibration type of sensor
        calibrationtype = self.device.custom_config.calibrationtype_default.lower()
        calidx = 0
        for itmp, c in enumerate(calibration_types):
            self.caltype.addItem(c)
            if c == calibrationtype:
                calidx = itmp

        self.caltype.setCurrentIndex(calidx)
        self.caltype.currentIndexChanged.connect(self.__replace_calibration_config_widget__)
        # Add a custom calibration widget, defined for each calibration type
        calibration_config_widget = calibration_types_config_widgets[calibrationtype]
        self.calibration_config_widget = QtWidgets.QWidget()
        self.calibration_config_widget_layout = QtWidgets.QVBoxLayout(self.calibration_config_widget)
        # Change the calibation widget
        self.__replace_calibration_config_widget__()

        # Widget to show all the sensor widgets
        self.butwidget = QtWidgets.QWidget()
        self.butlayout = QtWidgets.QHBoxLayout(self.butwidget)
        self.butlayout.addWidget(self.sensoradd)
        self.butlayout.addWidget(self.sensorsadd)
        self.butlayout.addWidget(self.mansensoradd)
        self.butlayout.addWidget(self.autocalbtn)
        self.butlayout.addWidget(QtWidgets.QLabel('Calibration Type'))
        self.butlayout.addWidget(self.caltype)
        self.butlayout.addWidget(QtWidgets.QLabel('Calibration Config'))
        self.butlayout.addWidget(self.calibration_config_widget)
        # Sensorswidget with scrollarea
        self.sensorsConfig_datastream = QtWidgets.QWidget()
        self.sensorsConfig_datastream_scroll = QtWidgets.QScrollArea()
        self.sensorsConfig_datastream_scroll.setWidgetResizable(True)
        self.sensorsConfig_datastream_scroll.setWidget(self.sensorsConfig_datastream)
        # The layout for the individual sensors
        self.sensorsConfig_datastream_layout = QtWidgets.QGridLayout(self.sensorsConfig_datastream)
        self.sensorsConfig_manual = QtWidgets.QWidget()
        self.sensorsConfig_manual_layout = QtWidgets.QGridLayout(self.sensorsConfig_manual)
        self.sensorsConfig_manual_scroll = QtWidgets.QScrollArea()
        self.sensorsConfig_manual_scroll.setWidgetResizable(True)
        self.sensorsConfig_manual_scroll.setWidget(self.sensorsConfig_manual)
        self.sensorsConfig_layout.addWidget(self.butwidget)
        self.sensorsConfig_layout.addWidget(QtWidgets.QLabel('Datastreams'))
        self.sensorsConfig_layout.addWidget(self.sensorsConfig_datastream_scroll)
        self.sensorsConfig_layout.addWidget(QtWidgets.QLabel('Manual sensors'))
        self.sensorsConfig_layout.addWidget(self.sensorsConfig_manual_scroll)
        ref_group=QtWidgets.QButtonGroup() # Number group
        nsensors = 0
        sensors = []
        buttons = []
        for i,sdata in enumerate(self.device.custom_config.calibrationdata):
            if sdata.inputtype == 'datastream':
                sensorNum = QtWidgets.QLabel(str(nsensors))
                dstr = sdata.datastream.address_str
                sensorDatastream = QtWidgets.QLineEdit(dstr) # The subscribed datastream
                sensorDatastream.setReadOnly(True)
                sensorDatastream.datastream = sdata.datastream
                sensorChoose = QtWidgets.QPushButton('Choose')  # Choose a datastream
                sensorChoose.clicked.connect(self.chooseDatastream)
                sensorChoose.lineEditDatastream_addr = sensorDatastream
                sensorChoose.listindex = i
                sensorRem = QtWidgets.QPushButton('Remove')  # Choose a datastream
                sensorRem.clicked.connect(self.sensorRemClicked)
                sensorRem.listindex = i
                sensorRem.sensortype = 'datastream'
                # The realtime plot type
                sensorPlotType = QtWidgets.QComboBox()  # Choose a datastream
                sensorPlotType.addItem('Table')
                sensorPlotType.addItem('XY Plot')
                sensorPlotType.listindex = i
                sensorPlotType.sensortype = 'datastream'
                if 'XY' in sdata.realtimeplottype:
                    sensorPlotType.setCurrentIndex(1)  # XY
                else:
                    sensorPlotType.setCurrentIndex(0)  # Table
                sensorPlotType.currentIndexChanged.connect(self.__realtime_plot_changed__)

                # Calibration type
                sensorCalibrationType = QtWidgets.QComboBox()  # Choose a datastream
                sensorCalibrationType.listindex = i
                sensorCalibrationType.sensortype = 'datastream'
                idx_cal = 0
                for idx,c in enumerate(calibration_types):
                    sensorCalibrationType.addItem(c)
                    if c.lower() == sdata.calibrationtype.lower():
                        idx_cal = idx

                sensorCalibrationType.setCurrentIndex(idx_cal)
                sensorCalibrationType.currentIndexChanged.connect(self.__calibration_type_changed__)
                self.device.custom_config.calibrationdata[i].__calibration_type_widget__ = sensorCalibrationType


                # Calibration config
                sensorCalibrationConfig = QtWidgets.QWidget()
                sensorCalibrationConfigLayout = QtWidgets.QGridLayout(sensorCalibrationConfig)
                self.device.custom_config.calibrationdata[i].__sensorCalibrationConfigLayout__ = sensorCalibrationConfigLayout
                self.__change_calibration_config_widget_for_sensor__(i)

                # Reference index
                refbutton = QtWidgets.QRadioButton("Reference")
                refbutton.refindex = i
                refbutton.toggled.connect(self.__refsensor_changed__)
                buttons.append(refbutton)
                ref_group.addButton(refbutton,id=nsensors)
                sensors.append({'sensorDatastream':sensorDatastream})
                self.sensorsConfig_datastream_layout.addWidget(sensorNum, nsensors, 0)
                self.sensorsConfig_datastream_layout.addWidget(sensorDatastream, nsensors, 1)
                self.sensorsConfig_datastream_layout.addWidget(sensorChoose, nsensors, 3)
                self.sensorsConfig_datastream_layout.addWidget(sensorRem, nsensors, 4)
                self.sensorsConfig_datastream_layout.addWidget(sensorPlotType, nsensors, 5)
                self.sensorsConfig_datastream_layout.addWidget(sensorCalibrationType, nsensors, 6)
                self.sensorsConfig_datastream_layout.addWidget(sensorCalibrationConfig, nsensors, 7)
                self.sensorsConfig_datastream_layout.addWidget(refbutton, nsensors, 8)
                nsensors += 1
                if i == int(self.device.custom_config.ind_ref_sensor):
                    refbutton.setChecked(True)
            else:
                mansensorNum = QtWidgets.QLabel(str(nsensors))
                mansensorName = QtWidgets.QLineEdit(sdata.sn)  # The name of the sensor
                mansensorName.editingFinished.connect(self.manualSensorChanged)
                mansensorName.listindex = i
                mansensorRem = QtWidgets.QPushButton('Remove')  # Choose a datastream
                # Calibration type
                manCalibrationType = QtWidgets.QComboBox()  # Choose a datastream
                manCalibrationType.listindex = i
                manCalibrationType.sensortype = 'datastream'
                idx_cal = 0
                for idx,c in enumerate(calibration_types):
                    manCalibrationType.addItem(c)
                    if c.lower() == sdata.calibrationtype.lower():
                        idx_cal = idx

                manCalibrationType.setCurrentIndex(idx_cal)
                manCalibrationType.currentIndexChanged.connect(self.__calibration_type_changed__)

                # Calibration config
                manCalibrationConfig = QtWidgets.QWidget()
                manCalibrationConfigLayout = QtWidgets.QGridLayout(manCalibrationConfig)
                self.device.custom_config.calibrationdata[i].__sensorCalibrationConfigLayout__ = manCalibrationConfigLayout
                self.__change_calibration_config_widget_for_sensor__(i)

                self.device.custom_config.calibrationdata[i].__calibration_type_widget__ = manCalibrationType
                # Reference
                manrefbutton = QtWidgets.QRadioButton("Reference")
                manrefbutton.refindex = i
                manrefbutton.toggled.connect(self.__refsensor_changed__)
                buttons.append(manrefbutton)
                ref_group.addButton(manrefbutton,id=nsensors)
                mansensorRem.clicked.connect(self.sensorRemClicked)
                mansensorRem.listindex = i
                mansensorRem.sensortype = 'manual'
                sensors.append({'mansensorName':mansensorName})
                self.sensorsConfig_manual_layout.addWidget(mansensorNum, nsensors, 0)
                self.sensorsConfig_manual_layout.addWidget(mansensorName, nsensors, 1)
                self.sensorsConfig_manual_layout.addWidget(mansensorRem, nsensors, 2)
                self.sensorsConfig_manual_layout.addWidget(manCalibrationType, nsensors, 3)
                self.sensorsConfig_manual_layout.addWidget(manCalibrationConfig, nsensors, 4)
                self.sensorsConfig_manual_layout.addWidget(manrefbutton, nsensors, 5)
                if i == int(self.device.custom_config.ind_ref_sensor):
                    manrefbutton.setChecked(True)

                nsensors += 1

        ref_group.setExclusive(True)
        self.ref_group = ref_group
        self.sensors = sensors
        ind_ref_sensor = self.device.custom_config.ind_ref_sensor
        # Set the reference sensor
        if ind_ref_sensor>=0:
            refbutton = buttons[ind_ref_sensor]
            refbutton.setChecked(True)
            self.__update_refsensor_widgets__(ind_ref_sensor)

    def __replace_calibration_config_widget__(self):
        """
        Replaces the calibration config widget with a new one, based on the calibration type combobox
        """
        layout = self.calibration_config_widget_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        calibrationtype = self.caltype.currentText().lower()
        # Add a custom calibration widget, defined for each calibration type
        calibration_config_widget = calibration_types_config_widgets[calibrationtype]
        self.calibration_config_widget_custom = calibration_config_widget()
        self.calibration_config_widget_layout.addWidget(self.calibration_config_widget_custom)

    def sensorAutocalClicked(self):
        checked = self.autocalbtn.isChecked()
        self.device.devicedisplaywidget.showAutocalWidget(checked)

    def __calibration_type_changed__(self, index):
        """
        Called when the calibration type of sensor is changed.
        """
        funcname = __name__ + '.__calibration_type_changed__():'
        print(funcname + ' {}'.format(index))
        calibrationTypeCombo = self.sender()
        calibrationtype = calibrationTypeCombo.currentText()

        indexsensor = calibrationTypeCombo.listindex
        #print('Hallo', sensorPlotType.currentText())
        self.device.custom_config.calibrationdata[indexsensor].calibrationtype = calibrationtype
        #print('Sensor config', self.device.custom_config.calibrationdata[indexsensor])
        self.updateDisplayWidget()

    def __change_calibration_config_widget_for_sensor__(self, indexsensor):
        # Change the calibration config widget
        calibrationtype = self.device.custom_config.calibrationdata[indexsensor].calibrationtype.lower()
        layout = self.device.custom_config.calibrationdata[indexsensor].__sensorCalibrationConfigLayout__
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        # Add a custom calibration widget, defined for each calibration type
        calibration_config_widget = calibration_types_config_widgets[calibrationtype]()
        calibration_config_widget.listindex = indexsensor
        calibration_config_widget.config_changed.connect(self.__calibration_config_for_sensor_changed__)
        calibration_config_widget.config_changed.emit(calibration_config_widget.get_config())
        layout.addWidget(calibration_config_widget)

    def __calibration_config_for_sensor_changed__(self, config):
        print("Config changed", config)
        # TODO
        configwidget = self.sender()
        indexsensor = configwidget.listindex
        sensor = self.device.custom_config.calibrationdata[indexsensor]
        print("SEnsor", sensor)
        print("Indexsensor",indexsensor)
        self.device.add_sensor_calibration_config(sensor,config)
        print("SEnsor again", self.device.custom_config.calibrationdata[indexsensor])

    def __realtime_plot_changed__(self, index):
        """
        Called when the plot type of a sensor is changed.
        """
        funcname = __name__ + '.__realtime_plot_changed__():'
        # print(funcname + ' {}'.format(index))
        sensorPlotType = self.sender()
        plottype = sensorPlotType.currentText()

        indexsensor = sensorPlotType.listindex
        # print('Hallo', sensorPlotType.currentText())
        self.device.custom_config.calibrationdata[indexsensor].realtimeplottype = plottype
        # print('Sensor config', self.device.custom_config.calibrationdata[indexsensor])
        self.updateDisplayWidget()

    def __refsensor_changed__(self):
        """
        Called when the reference sensor of a sensor is changed.
        """
        funcname = __name__ + '.__refsensor_changed__():'
        logger.debug(funcname)
        if self.sender().isChecked():
            index = self.sender().refindex
            index_old = self.device.custom_config.ind_ref_sensor
            self.device.custom_config.ind_ref_sensor = index
            self.device.custom_config.name_ref_sensor = self.device.custom_config.calibrationdata[index].sn
            self.__update_refsensor_widgets__(index)

    def __update_refsensor_widgets__(self, indexnew):
        try:
            for c in self.device.custom_config.calibrationdata:
                c.__calibration_type_widget__.setEnabled(True)

            self.device.custom_config.calibrationdata[indexnew].__calibration_type_widget__.setEnabled(False)
        except:
            logger.debug("Could not update refsensor",exc_info=True)

    def chooseDatastream(self):
        funcname = __name__ + '.chooseDatastream():'
        logger.debug(funcname)
        button = self.sender()
        self.dstreamwidget = redvypr.gui.RedvyprAddressWidget(self.device.redvypr)
        self.dstreamwidget.apply.connect(self.datastreamChosen)
        self.dstreamwidget.lineEditDatastream_addr = button.lineEditDatastream_addr
        self.dstreamwidget.listindex = button.listindex
        self.dstreamwidget.show()

    def datastreamChosen(self, datastream_dict):
        funcname = __name__ + '.datastreamChosen():'
        logger.debug(funcname)
        #print('Choosen',datastream_dict)
        #self.sender().lineEditSubed_addr.setText(datastream_dict['datastream_str'])
        #self.sender().lineEditSub_addr.setText(datastream_dict['datastream_str'])
        index = self.sender().listindex
        #print('Index',index)
        #print('sensordata', self.device.custom_config.calibrationdata)
        #print('datastream',datastream_dict)
        self.device.custom_config.calibrationdata[index].datastream = datastream_dict['datastream_address']
        try:
            self.device.devicedisplaywidget.plot_widgets[index].datastream = None
        except:
            pass

        self.updateDisplayWidget()
        self.device.subscribe_to_sensors()

    def caltype_combobox_changed_legacy(self, value):
        logger.debug("combobox changed {}".format(value))
        self.device.custom_config.calibrationtype_default = value.lower()
        self.device.devicedisplaywidget.create_calibration_widget()

    def manualSensorChanged(self):
        funcname = __name__ + '.manualsSensorChanged():'
        logger.debug(funcname)
        l = self.sender()
        sensorname = l.text()
        #print('Editing finished',sensorname)
        i = self.sender().listindex
        self.device.custom_config.calibrationdata[i].sn = sensorname
        #self.device.config['manualsensors']
        self.updateDisplayWidget()

    def sensorsAddClicked(self):
        funcname = __name__ + '.sensorsAddClicked():'
        logger.debug(funcname)
        self.dstreamswidget = redvypr.gui.RedvyprMultipleAddressesWidget(self.device.redvypr)
        self.dstreamswidget.apply.connect(self.sensorsApplyClicked)
        self.dstreamswidget.show()

    def sensorsApplyClicked(self,datastreamdict):
        funcname = __name__ + '.sensorsApplyClicked():'
        logger.debug(funcname)
        # Adding all addresses
        for addr in datastreamdict['addresses']:
            newsen = addr
            logger.debug(funcname + 'Adding {}'.format(newsen))
            calibrationtype = self.caltype.currentText().lower()
            calorder = self.calibration_config_widget.value()
            self.device.add_sensor(newsen, sentype='datastream',calibrationtype=calibrationtype, calorder=calorder)

        if len(datastreamdict['addresses'])>0:
            layout = self.sensorsConfig_layout
            while layout.count():
                item = layout.takeAt(0)
                #item.close()
                widget = item.widget()
                widget.deleteLater()

            self.populateSensorInputWidgets()
            self.updateDisplayWidget()

    def sensorAddClicked(self):
        funcname = __name__ + '.sensorAddClicked():'
        logger.debug(funcname)

        logger.debug(funcname + 'config {}'.format(self.device.custom_config))
        calibrationtype = self.caltype.currentText().lower()
        newsen = RedvyprAddress('')
        calconfig = self.calibration_config_widget_custom.get_config()
        if self.sender() == self.sensoradd:
            logger.debug('datastream sensor')
            self.device.add_sensor(newsen, sentype = 'datastream', calibrationtype=calibrationtype, calconfig=calconfig)
        else:
            logger.debug('Manual sensor')
            self.device.add_sensor(newsen, sentype = 'manual', calibrationtype=calibrationtype, calconfig=calconfig)

        layout = self.sensorsConfig_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            widget.deleteLater()

        self.populateSensorInputWidgets()
        self.updateDisplayWidget()

    def sensorRemClicked(self):
        funcname = __name__ + '.sensorRemClicked():'
        logger.debug(funcname)
        sensorRem = self.sender()
        layout = self.sensorsConfig_layout
        while layout.count():
            item = layout.takeAt(0)
            # item.close()
            widget = item.widget()
            widget.deleteLater()

        #print('Config', self.device.custom_config)
        #print('Index',sensorRem.listindex)
        if sensorRem.sensortype == 'manual':
            self.device.rem_sensor(sensorRem.listindex, 'manual')
        else:
            self.device.rem_sensor(sensorRem.listindex, 'datastream')

        self.populateSensorInputWidgets()
        self.updateDisplayWidget()

    def updateDisplayWidget(self):
        funcname = __name__ + '.updateDisplayWidget():'
        logger.debug(funcname)
        self.populateSensorInputWidgets()
        self.device.devicedisplaywidget.clear_widgets()
        self.device.devicedisplaywidget.create_widgets()
    def config_changed(self):
        """


        Args:
            config:

        Returns:

        """
        funcname = __name__ + '.config_changed():'
        logger.debug(funcname)

    def kill_clicked(self):
        button = self.sender()
        logger.debug("Kill device {:s}".format(self.device.name))
        self.device.kill_process()

    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            logger.debug("button pressed")
            button.setText('Starting')
            self.device.thread_start()
            # self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            # button.setText('Stopping')
            self.startbutton.setChecked(True)
            self.device.thread_stop()

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']
        # Running
        if (thread_status):
            self.startbutton.setText('Stop')
            self.startbutton.setChecked(True)
            for w in self.config_widgets:
                w.setEnabled(False)
        # Not running
        else:
            self.startbutton.setText('Start')
            for w in self.config_widgets:
                w.setEnabled(True)

            # Check if an error occured and the startbutton
            if (self.startbutton.isChecked()):
                self.startbutton.setChecked(False)
            # self.conbtn.setEnabled(True)

    def connect_clicked(self):
        button = self.sender()
        self.connect.emit(self.device)





class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None, tabwidget=None):
        funcname = __name__ + '__init__():'
        logger.debug(funcname)
        super(QtWidgets.QWidget, self).__init__()
        self.layout        = QtWidgets.QGridLayout(self)
        self.irowdatastart = 5 # The row of the datatable where the data starts
        self.irowparameter = 0  # The row of the datatable where the data starts
        self.irowinput     = 1  # The row of the datatable where the data starts
        self.irowunit      = 2  # The row of the datatable where the data starts
        self.irowmac_sn    = 3  # The row of the datatable where the data starts
        self.irowsenstype  = 4  # The row of the datatable where the data starts
        self.rowheader = ['Parameter','Input','Unit', 'SN', 'Sensortype']
        self.device = device

        self.tabwidget = tabwidget
        self.sensorcols = []
        self.sensorcolsindex = []
        self.manualsensorcols = []
        self.manualsensorcolsindex = []
        self.timecolindex = 0 # Index of the time column
        # Add realtimeplots
        self.plot_widgets = []
        # Create all widgets
        self.create_widgets()

        autocalflag = self.device.custom_config.autocal
        if autocalflag:
            self.showAutocalWidget(autocalflag)

    def showAutocalWidget(self, checked):
        tabwidget = self.tabwidget
        logger.debug('Autocal checked')
        if checked:
            logger.debug('Adding autocalibration')
            self.autocalwidget = Autocalwidget(device=self.device)
            tabwidget.addTab(self.autocalwidget,'Autocalibration')
        else:
            try:
                tabwidget.removeTab(tabwidget.indexOf(self.autocalwidget))
                self.autocalwidget.close()
            except:
                logger.debug('Could not close autocalwidget',exc_info=True)

    def finalize_init(self):
        funcname = __name__ + 'finalize_init():'
        logger.debug(funcname)
        self.order_tabs()


    def clear_widgets(self):
        """
        Clear widgets
        """
        funcname = __name__ + '.clear_widgets():'
        logger.debug(funcname)
        w_delete = [self.realtimedata_parent_widget, self.calibrationdata_widget, self.realtimedata_parent_widget, self.calibrationcalculation_widget]
        for w in w_delete:
            try:
                w.deleteLater()
            except Exception as e:
                pass

        layout = self.layout
        while layout.count():
            item = layout.takeAt(0)
            # item.close()
            widget = item.widget()
            widget.deleteLater()

    def create_widgets(self):
        funcname = __name__ + 'create_widgets():'
        logger.debug(funcname)

        #
        # Create the Calibration widget with the averaged data
        #
        self.calibrationdata_widget = QtWidgets.QWidget()
        self.calibrationdata_widget_layout = QtWidgets.QGridLayout(self.calibrationdata_widget)
        self.calibrationdata_table = QtWidgets.QTableWidget()

        self.addLineButton = QtWidgets.QPushButton('Add empty row')
        self.addLineButton.clicked.connect(self.addBlankCalibrationData)
        self.remLineButton = QtWidgets.QPushButton('Rem row(s)')
        self.remLineButton.clicked.connect(self.remCalibrationData)
        # The widget the realtime data is shown
        self.realtimedata_parent_widget = QtWidgets.QWidget()
        self.realtimedata_parent_widget_layout = QtWidgets.QGridLayout(self.realtimedata_parent_widget)
        # Add a scroll area, to deal with a lot of data
        self.plot_widgets_parent_scroll = QtWidgets.QScrollArea()
        self.plot_widgets_parent_scroll.setWidget(self.realtimedata_parent_widget)
        self.plot_widgets_parent_scroll.setWidgetResizable(True)
        # Add the realtime data
        self.add_plots()
        self.addintervall_time = QtWidgets.QDoubleSpinBox()
        self.addintervall_time.setValue(30.0)
        self.addintervall_combo = QtWidgets.QComboBox()
        self.addintervall_combo.addItem('Last x seconds')
        self.addintervall_combo.addItem('Manually')
        self.addintervall_combo.currentTextChanged.connect(self.get_intervalldatamode_changed)
        # Set the mode of the XY-Plots correctly
        self.get_intervalldatamode_changed()

        self.addintervall_button = QtWidgets.QPushButton('Add intervall')
        self.addintervall_button.clicked.connect(self.get_intervalldata)

        self.clearbuffer_button = QtWidgets.QPushButton('Clear buffer')
        self.clearbuffer_button.clicked.connect(self.clear_buffer)

        self.layout.addWidget(self.plot_widgets_parent_scroll,0,0,1,-1)
        self.layout.addWidget(self.addintervall_time, 1, 0)
        self.layout.addWidget(self.addintervall_combo, 1, 1)
        self.layout.addWidget(self.addintervall_button, 1, 2,1,2)
        self.layout.addWidget(self.clearbuffer_button, 3, 3)

        # Create the self.calibration_widget, that processes the raw data in self.datatable for calibration (i.e. NTC, heatflow, polyfit ...)
        self.calibrationcalculation_widget = QtWidgets.QWidget()
        self.calibrationcalculation_widget_layout = QtWidgets.QVBoxLayout(self.calibrationcalculation_widget)

        # Datatable widget
        label = QtWidgets.QLabel('Calibration data')
        label.setStyleSheet("font-weight: bold")
        label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        label.setAlignment(QtCore.Qt.AlignCenter)
        self.calibrationdata_table_widget = QtWidgets.QWidget()
        #self.datatable_widget.setStyleSheet("background-color: rgb(255,0,0); margin:5px; border:1px solid rgb(0, 255, 0); ")
        calibrationdatatable_widget_layout = QtWidgets.QVBoxLayout(self.calibrationdata_table_widget)
        self.datainput_configwidget = QtWidgets.QWidget()
        self.inputlayout = QtWidgets.QGridLayout(self.datainput_configwidget)
        self.datainput_configwidgets = {}
        self.datainput_configwidgets['lUUID'] = QtWidgets.QLineEdit(self.device.custom_config.calibration_uuid)
        self.datainput_configwidgets['lUUID'].setReadOnly(True)
        self.datainput_configwidgets['lUUID_label'] = QtWidgets.QLabel('Calibration UUID')
        self.datainput_configwidgets['lID'] = QtWidgets.QLineEdit(self.device.custom_config.calibration_id)
        self.datainput_configwidgets['lID_label'] = QtWidgets.QLabel('Calibration ID')
        self.datainput_configwidgets['lco'] = QtWidgets.QLineEdit(self.device.custom_config.calibration_comment)
        self.datainput_configwidgets['lco'].editingFinished.connect(self.update_custom_config_from_widgets)
        self.datainput_configwidgets['lco_label'] = QtWidgets.QLabel('Calibration comment')
        self.datainput_configwidgets['lID'].editingFinished.connect(self.update_custom_config_from_widgets)
        self.inputlayout.addWidget(self.datainput_configwidgets['lUUID_label'], 0, 0)
        self.inputlayout.addWidget(self.datainput_configwidgets['lUUID'], 0, 1)
        self.inputlayout.addWidget(self.datainput_configwidgets['lID_label'], 1, 0)
        self.inputlayout.addWidget(self.datainput_configwidgets['lID'], 1, 1)
        self.inputlayout.addWidget(self.datainput_configwidgets['lco_label'], 2, 0)
        self.inputlayout.addWidget(self.datainput_configwidgets['lco'], 2, 1)

        calibrationdatatable_widget_layout.addWidget(label)
        calibrationdatatable_widget_layout.addWidget(self.datainput_configwidget)
        calibrationdatatable_widget_layout.addWidget(self.calibrationdata_table)
        calibrationdatatable_widget_layout.setStretch(0, 1)
        calibrationdatatable_widget_layout.setStretch(1, 1)
        calibrationdatatable_widget_layout.setStretch(2, 10)

        # Create the layout
        self.calibrationdata_widget_layout.addWidget(self.calibrationdata_table_widget, 0, 0, 1, 3)
        self.calibrationdata_widget_layout.addWidget(self.addLineButton, 1, 0)
        self.calibrationdata_widget_layout.addWidget(self.remLineButton, 1, 1)

        # Add the tablewidget as a new tab
        self.tabwidget.addTab(self.calibrationdata_widget, 'Calibration data')
        # Add the tablewidget as a new tab
        calibrationtype = self.device.custom_config.calibrationtype_default.lower()
        self.tabwidget.addTab(self.calibrationcalculation_widget, 'TMP')

        self.update_datatable()
        # This needs to be done after the tab, as it changes text of the tab
        self.create_calibration_widget()  # Is adding a widget to self.calibration_widget
        #self.order_tabs()

    def update_custom_config_from_widgets(self):
        funcname = __name__ + '.update_custom_config_from_widgets():'
        logger.debug(funcname)
        self.device.custom_config.calibration_comment = self.datainput_configwidgets['lco'].text()
        self.device.custom_config.calibration_id = self.datainput_configwidgets['lID'].text()
        #print('Config')
        #print(self.device.custom_config)
        #print('Done')

    def remCalibrationData(self):
        """
        Removes selected data entries
        """
        funcname = __name__ + '.remCalibrationData():'
        logger.debug(funcname)
        rows = []
        if self.calibrationdata_table.selectionModel().selection().indexes():
            for i in self.calibrationdata_table.selectionModel().selection().indexes():
                row, column = i.row(), i.column()
                if row >= self.irowdatastart:
                    if row not in rows:
                        rows.append(row)
                else:
                    logger.debug(funcname + ' Metadata, will not remove')

        #print('Removing',rows)
        if len(rows) > 0:
            for row in rows:
                rowdata = row - self.irowdatastart
                #print('row',rowdata)
                self.device.rem_data(rowdata)

            self.update_datatable()

    def addBlankCalibrationData(self):
        """
        Adds a blank calibrationdata to the datatable
        """
        funcname = __name__ + '.addBlankCalibrationData():'
        logger.debug(funcname)
        tadd = time.time()
        # def add_data(self, time, sensorindex, sentype, data, time_data, rawdata, time_rawdata):
        if len(self.device.custom_config.calibrationdata) > 0:
            self.device.add_data(tadd, 0, np.nan, tadd, np.nan, np.nan)
            # Update the table
            self.update_datatable()
        else:
            logger.warning(funcname + ' No sensors defined')
            return None

    def order_tabs(self):
        funcname = '.order_tabs():'
        #print(funcname)
        old_position = self.tabwidget.indexOf(self)
        #print(funcname,old_position,'self')
        self.tabwidget.tabBar().moveTab(old_position, 1)

        old_position = self.tabwidget.indexOf(self.calibrationdata_widget)
        #print(funcname, old_position, 'datatable')
        self.tabwidget.tabBar().moveTab(old_position, 2)

        old_position = self.tabwidget.indexOf(self.calibrationcalculation_widget)
        #print(funcname, old_position, 'calibration')
        self.tabwidget.tabBar().moveTab(old_position, 3)

    def create_calibration_widget(self):
        """
        Creates a calibration widget that uses the averaged data in the datatable to calculate coefficients
        """
        funcname = __name__ + '.create_calibration_widget():'
        logger.debug(funcname)
        # Remove all old widgets
        index = self.calibrationcalculation_widget_layout.count()
        while(index >= 1):
            myWidget = self.calibrationcalculation_widget_layout.itemAt(index - 1).widget()
            myWidget.setParent(None)
            index -=1

        calibrationtype = self.device.custom_config.calibrationtype_default.lower()
        calwidget = CalibrationCalculationWidget(self)
        tabtext = "Calculate calibrations"

        self.calibrationcalculation_widget_layout.addWidget(calwidget)
        # Update the text of the tab
        index = self.tabwidget.indexOf(self.calibrationcalculation_widget)
        self.tabwidget.setTabText(index, tabtext)
        self.order_tabs()

    def refsensor_changed(self, index):
        funcname = __name__ + '.refsensor_changed():'
        logger.debug(funcname)
        self.device.custom_config.ind_ref_sensor = index
        self.device.custom_config.name_ref_sensor = self.allsensornames[self.device.custom_config.ind_ref_sensor.data]
        # Update calibration table
        #self.update_coefftable_ntc()
        #print('Config', self.device.custom_config)

    def add_plots(self):
        """
        Add the realtimedata plots/tables
        :return:
        """
        funcname = __name__ + '.add_plots():'
        logger.debug(funcname)
        # Clear "old" plots
        #for p in self.plot_widgets:
        #    p.close()

        #try:
        #    self.plot_widgets_parent_layout.removeItem(self.realtimedata_vertical_spacer)
        #except:
        #    pass

        # Re-Initialize plot_widgets
        #self.plot_widgets = []
        #self.datastreams = []  # List of all datastreams
        self.sensorcols = []
        self.sensorcolsindex = []
        self.manualsensorcols = []
        self.manualsensorcolsindex = []
        self.allsensornames = []
        nwidgets = 0
        ioff = 1
        nrow = 0
        ncol = 0
        for i, sdata in enumerate(self.device.custom_config.calibrationdata):
            # Realtimedata
            if sdata.inputtype == 'datastream':
                # This is to check if the plot has changed
                try:
                    realtimeplottype = sdata.__realtimeplottype
                except:
                    #logger.info('Could not get plottype',exc_info=True)
                    realtimeplottype = 'unknown'

                same_plotwidgettype = realtimeplottype == sdata.realtimeplottype
                try:
                    plot_widget = sdata.__plot_widget
                    logger.debug('Plotwidget is existing')
                    flag_new_plot_widget = False
                except:
                    logger.debug(funcname + 'creating plotwidget')
                    flag_new_plot_widget = True

                #print('same_plotwidgettype',realtimeplottype, same_plotwidgettype,flag_new_plot_widget)
                # Check if the plotwidgettype changed
                if (same_plotwidgettype == False) and (flag_new_plot_widget == False):
                    #print('Changing plotwidget')
                    try:
                        sdata.__plot_widget.setParent(None)
                    except:
                        logger.info('Could not close widget',exc_info=True)

                    flag_new_plot_widget = True

                if flag_new_plot_widget:
                    #print('Adding new widget',sdata.realtimeplottype)
                    #config = {}
                    #config['title'] = sdata.sn
                    #self.datastreams.append(None)
                    #plot_widget = plot_widgets.redvypr_graph_widget(config=config)
                    if 'XY' in sdata.realtimeplottype:
                        #print('Adding XYplotwidget with address {}'.format(sdata.datastream))
                        configLine = XYPlotWidget.configLine(y_addr=sdata.datastream)
                        config = XYPlotWidget.ConfigXYplot(interactive='xlim_keep', data_dialog='off', lines=[configLine])
                        plot_widget = XYPlotWidget.XYPlotWidget(config=config, redvypr_device=self.device)
                        plot_widget.plotWidget.scene().sigMouseMoved.connect(self.anyMouseMoved)
                        plot_widget.interactive_signal.connect(self.xyplot_interactive_signal)
                        #plot_widget.plotWidget.scene().sigMouseClicked.connect(self.anyMouseClicked)
                        plot_widget.vlines = []  # List of vertical lines
                        plot_widget.vlines_xpos = []  # List of vertical lines
                        sdata.__realtimeplottype = sdata.realtimeplottype
                        print('Done')
                    elif 'able' in sdata.realtimeplottype:
                        plot_widget = QTableCalibrationWidget(sensorindex=i, device=self.device)
                        sdata.__realtimeplottype = sdata.realtimeplottype

                plot_widget.datatablecolumn = i + ioff  # The column the data is saved
                plot_widget.sensorindex = i
                plot_widget.sensortype = 'datastream'
                #self.plot_widgets.append(plot_widget)
                self.sensorcolsindex.append(plot_widget.datatablecolumn)
                self.sensorcols.append(str(sdata.datastream))
                self.allsensornames.append(str(sdata.datastream))
                # Check if there is already a subscription
                plot_widget.datastream = sdata.datastream  # Datastream to be plotted
                #self.set_datastream(i, sdata.datastream, sn=sdata.sn, unit=sdata.unit, sensortype=sdata.sensor_model, parameter=sdata.parameter)
                # Add the widget to the parent widget
                self.realtimedata_parent_widget_layout.addWidget(plot_widget, nrow, ncol)
                ncol += 1
                if ncol >= self.device.custom_config.gui_realtimedata_ncols:
                    ncol = 0
                    nrow += 1
                nwidgets += 1

                sdata.__plot_widget = plot_widget

            # Manualdata
            else:
                if len(self.sensorcolsindex)>0:
                    ioff = max(self.sensorcolsindex) + 1 # Make a new ioff

                self.manualsensorcols.append(str(sdata.sn))
                self.manualsensorcolsindex.append(i + ioff)
                self.allsensornames.append(str(sdata.sn))

        #self.realtimedata_vertical_spacer = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        #self.plot_widgets_parent_layout.addItem(self.realtimedata_vertical_spacer, nrow+1, 0)
        # Update the name of the reference sensor
        try:
            self.device.custom_config.name_ref_sensor = self.allsensornames[self.device.custom_config.ind_ref_sensor]
        except:
            self.device.custom_config.name_ref_sensor = ''

        self.plot_widgets = []
        layout = self.realtimedata_parent_widget_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)

            # Prüfen, ob das Item ein Widget ist
            widget = item.widget()
            if widget:
                self.plot_widgets.append(widget)

    def xyplot_interactive_signal(self, data_interactive):
        funcname = __name__ + '.xyplot_interactive_signal():'
        logger.debug(funcname)
        sender = self.sender()
        #print('Got data',data_interactive)
        xpos = data_interactive['xlines']
        try:
            self.__interactive_lines
        except:
            self.__interactive_lines = []

        if len(xpos) == 0:  # Set the position everywhere
            self.__t_intervall_interactive = None
            #print('Removing lines')
            for l in self.__interactive_lines:
                l['plotwidget'].plotWidget.removeItem(l['line'])

            self.__interactive_lines = []
        elif len(xpos) == 2: # Set the position everywhere
            self.__t_intervall_interactive = xpos
            for p in self.plot_widgets:
                # print('Moveit',type(p),type(XYplotWidget),isinstance(p,type(XYplotWidget)))
                if isinstance(p, XYPlotWidget.XYPlotWidget):
                    if sender == p.plotWidget.scene():
                        pass
                    else:
                        logger.debug('Adding line')
                        for i in range(2):
                            # Add lines to the graphs
                            angle = 90
                            color = QtGui.QColor(200, 100, 100)
                            linewidth = 2.0
                            pen = pyqtgraph.mkPen(color, width=linewidth)
                            line = pyqtgraph.InfiniteLine(angle=angle, movable=False, pen=pen)
                            line.setPos(xpos[i])
                            p.plotWidget.addItem(line, ignoreBounds=True)
                            self.__interactive_lines.append({'plotwidget':p,'line':line})

    def get_intervalldatamode_changed(self):
        mode = self.addintervall_combo.currentText()
        #print('Mode',mode)
        for p in self.plot_widgets:
            # print('Moveit',type(p),type(XYplotWidget),isinstance(p,type(XYplotWidget)))
            if isinstance(p, XYPlotWidget.XYPlotWidget):
                if 'manually' in mode.lower():
                    p.set_interactive_mode('xlim_keep')
                else:
                    p.set_interactive_mode('standard')
    def get_intervalldata(self):
        """
        Gets data and updates the datatable
        """
        funcname = __name__ + '.get_intervalldata():'
        logger.debug(funcname)
        tget = time.time() # The time the data was added
        timeintervaltype = self.addintervall_combo.currentText()
        if 'last' in timeintervaltype.lower():
            t1 = time.time()
            t0 = t1 - self.addintervall_time.value()
            #t1 = 0
            #t0 = t1 - self.addintervall_time.value()
            t_intervall = [t0, t1]
            dt = t1 - t0
            print('Getting time in interval {} {} {}'.format(t1,t0,dt))
        else:
            try:
                t_intervall = self.__t_intervall_interactive
            except:
                t_intervall = None
            print('Getting manual time interval',t_intervall)
        if t_intervall is not None:
            for i, caldata in enumerate(self.device.custom_config.calibrationdata):
                print('Getting data from {}'.format(caldata))
                if caldata.inputtype == 'datastream':
                    logger.info(funcname + 'Datastream')
                    plot_widget = caldata.__plot_widget
                    #sensor_data_tmp = self.device.custom_config.calibrationdata[plot_widget.sensorindex]
                    #print('a',sensor_data_tmp)
                    #print('b',sensor_data_tmp.realtimeplot)

                    data = plot_widget.get_data(t_intervall)
                    print("Caldata", caldata)
                    print("t_interval", t_intervall)
                    print('Data',data)
                    print("Done")
                    if isinstance(plot_widget, XYPlotWidget.XYPlotWidget):
                        data = data['lines'][0]
                    #print('Got data from widget', data)
                    col = plot_widget.datatablecolumn
                    if len(data['y']) > 0:
                        rawdata_all = data['y'] #.tolist()
                        timedata_all = data['t']#.tolist()
                        # Average the data and convert it to standard python types
                        ydata = np.mean(rawdata_all,0).tolist() # Convert to list
                        tdata = float(np.mean(data['t'], 0))
                        #if len(ydata) == 1:
                        #    ydata = float(ydata)

                        tdatetime = datetime.datetime.utcfromtimestamp(tdata)
                        tdatas = tdatetime.strftime('%d-%m-%Y %H:%M:%S.%f')
                        # Add the data to the dictionary
                        #print('Averaged data',ydata)
                        #def add_data(self, time, sensorindex, sentype, data, time_data, rawdata, time_rawdata):
                        self.device.add_data(tget,plot_widget.sensorindex,ydata,tdata,rawdata_all,timedata_all)
                else:
                    logger.info(funcname + ' Manual')


        print('get intervalldata time', self.device.custom_config.calibrationdata_time)
        print('get intervalldata', self.device.custom_config.calibrationdata)
        self.update_datatable()

    def __datatable_item_changed__(self, item):
        funcname = __name__ + '__datatable_item_changed__():'
        logger.debug(funcname)
        #print(item)
        #item = QtWidgets.QTableWidgetItem(sdata.sn)
        #self.datatable.setItem(self.irowmac_sn, col, item)
        #item = QtWidgets.QTableWidgetItem(sdata.sensor_model)
        #self.datatable.setItem(self.irowsenstype, col, item)
        #item = QtWidgets.QTableWidgetItem(sdata.unit)
        #self.datatable.setItem(self.irowunit, col, item)
        #item = QtWidgets.QTableWidgetItem(sdata.inputtype)
        #self.datatable.setItem(self.irowinput, col, item)
        row = self.calibrationdata_table.row(item)
        # Check if there is metadata to be changed
        if row == self.irowmac_sn:
            newsn = item.text()
            logger.debug(funcname + 'Changing SN to:{}'.format(newsn))
            item.__calibrationdata__.sn = newsn
        elif row == self.irowunit:
            newunit = item.text()
            logger.debug(funcname + 'Changing unit to:{}'.format(newunit))
            item.__calibrationdata__.unit = newunit
        elif row == self.irowsenstype:
            newmodel = item.text()
            logger.debug(funcname + 'Changing unit to:{}'.format(newmodel))
            item.__calibrationdata__.sensor_model = newmodel
        else: # Or the data itself
            try:
                data = float(item.text())
            except:
                logger.debug(funcname + 'Could not change data',exc_info=True)
                data = item.text()

            # Add the data
            try:
                item.__parent__[item.__dindex__] = data
            except:
                logger.debug(funcname + 'Could not change data', exc_info=True)


    def update_datatable(self):
        """
        Updates the datatable with data from self.device.config
        """
        funcname = __name__ + '.update_datatable():'
        logger.debug(funcname)
        try:
            self.calibrationdata_table.itemChanged.disconnect(self.__datatable_item_changed__)
        except:
            pass

        ncols = 1 + len(self.device.custom_config.calibrationdata)
        self.calibrationdata_table.setColumnCount(ncols)
        ndatarows = len(self.device.custom_config.calibrationdata_time)
        self.calibrationdata_table.setRowCount(self.irowdatastart + ndatarows)

        #self.datatable.horizontalHeader().ResizeMode(self.datatable.horizontalHeader().ResizeToContents)
        #columns = ['Time'] + self.sensorcols + self.manualsensorcols
        colheaders = ['Time']
        for i in range(ncols - 1):
            colheaders.append(str(i))
        # headeritem = QtWidgets.QTableWidgetItem('Time')
        # self.datatable.setHorizontalHeaderItem(self.timecolindex, headeritem)
        self.calibrationdata_table.setHorizontalHeaderLabels(colheaders)
        self.calibrationdata_table.setVerticalHeaderLabels(self.rowheader)
        self.calibrationdata_table.resizeColumnsToContents()

        # self.datatable.setHorizontalHeaderLabels(self.datacolumns)
        col = 0
        #print('fdsfd', self.device.custom_config)

        for idata in range(ndatarows):
            itemdata = self.device.custom_config.calibrationdata_time[idata]
            tdatetime = datetime.datetime.utcfromtimestamp(itemdata)
            itemdatastr = tdatetime.strftime('%d-%m-%Y %H:%M:%S.%f')
            item = QtWidgets.QTableWidgetItem(itemdatastr)
            self.calibrationdata_table.setItem(self.irowdatastart + idata, 0, item)


        #print('config', self.device.custom_config)
        if True:
            for isensor,sdata in enumerate(self.device.custom_config.calibrationdata):
                col += 1
                #print('sensor sdata:',isensor,sdata)
                # Add all the metainformation
                #sensor_data['mac'] = ''
                #sensor_data['unit'] = ''
                #sensor_data['sensortype'] = ''
                #sensor_data['subscribe'] = ''
                #sensor_data['datastream'] = ''
                #sensor_data['comment'] = ''
                item = QtWidgets.QTableWidgetItem(sdata.inputtype)
                item.__calibrationdata__ = sdata
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.calibrationdata_table.setItem(self.irowinput, col, item)
                item = QtWidgets.QTableWidgetItem(sdata.channel)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                item.__calibrationdata__ = sdata
                self.calibrationdata_table.setItem(self.irowparameter, col, item)
                item = QtWidgets.QTableWidgetItem(sdata.sn)
                item.__calibrationdata__ = sdata
                self.calibrationdata_table.setItem(self.irowmac_sn, col, item)
                item = QtWidgets.QTableWidgetItem(sdata.sensor_model)
                item.__calibrationdata__ = sdata
                self.calibrationdata_table.setItem(self.irowsenstype, col, item)
                item = QtWidgets.QTableWidgetItem(sdata.unit)
                item.__calibrationdata__ = sdata
                self.calibrationdata_table.setItem(self.irowunit, col, item)

                #print('ndatarows',ndatarows)
                for idata in range(ndatarows):
                    #print('isensor',isensor,'idata',idata)
                    itemdata = sdata.data[idata]
                    #print('Data',itemdata)
                    if type(itemdata) == float:
                        try:
                            itemdatastr = "{:f}".format(itemdata)
                        except:
                            itemdatastr = "NaN"
                    elif type(itemdata) == list:
                        #https://stackoverflow.com/questions/2762058/format-all-elements-of-a-list
                        strFormat = '[ ' + len(itemdata) * '{:f} ' + ']'
                        itemdatastr = strFormat.format(*itemdata)
                    else:
                        itemdatastr = 'NaN'
                    #sdata['time_data'][idata]
                    item = QtWidgets.QTableWidgetItem(itemdatastr)
                    item.__calibrationdata__ = sdata
                    self.calibrationdata_table.setItem(self.irowdatastart + idata, col, item)
                    if sdata.inputtype == 'manual':
                        item.__parent__ = sdata.data
                        item.__dindex__  = idata

        self.calibrationdata_table.resizeColumnsToContents()
        self.calibrationdata_table.itemChanged.connect(self.__datatable_item_changed__)
        #self.datatable.setSizeAdjustPolicy(QtWidgets.QTableWidget.AdjustToContents)
        # self.datatable.resize(self.datatable.sizeHint())

    def update_datatable_metainformation(self,i):
        """
        Updates the metainformation of the datatable (units, sn/mac, sensortype)
        """
        funcname = __name__ + '.update_datatable_metainformation():'
        logger.debug(funcname)
        #self.datatable.setHorizontalHeaderLabels(self.datacolumns)

        p = self.plot_widgets[i]
        col = p.datatablecolumn
        item = QtWidgets.QTableWidgetItem(p.unit)
        self.calibrationdata_table.setItem(self.irowunit, col, item)
        item = QtWidgets.QTableWidgetItem(p.sn)
        self.calibrationdata_table.setItem(self.irowmac_sn, col, item)
        item = QtWidgets.QTableWidgetItem(p.sensortype)
        self.calibrationdata_table.setItem(self.irowsenstype, col, item)

        headeritem = QtWidgets.QTableWidgetItem(p.sensname_header)
        self.calibrationdata_table.setHorizontalHeaderItem(col, headeritem)

        self.calibrationdata_table.resizeColumnsToContents()
        self.calibrationdata_table.setSizeAdjustPolicy(QtWidgets.QTableWidget.AdjustToContents)
        #self.datatable.resize(self.datatable.sizeHint())

    def clear_buffer(self):
        funcname = __name__ + '.clear_buffer():'
        logger.debug(funcname)
        for i, p in enumerate(self.plot_widgets):
            p.clear_buffer()

    def anyMouseMoved(self,evt):
        sender = self.sender()
        mousePoint = sender.parent().plotItem.vb.mapSceneToView(evt)
        #mousePoint = sender.plotItem.vb.mapSceneToView(evt)
        for p in self.plot_widgets:
            #print('Moveit',type(p),type(XYplotWidget),isinstance(p,type(XYplotWidget)))
            if isinstance(p,XYPlotWidget.XYPlotWidget):
                if sender == p.plotWidget.scene():
                    pass
                else:
                    p.vLineMouse.setPos(mousePoint.x())


    def anyMouseClicked(self, evt):
        sender = self.sender()
        #print('Clicked: ' + str(evt.scenePos()))
        color = QtGui.QColor(100,100,100)
        for p in self.plot_widgets:
            mousePoint = p.vb.mapSceneToView(evt.scenePos())
            xpos = mousePoint.x()
            linewidth = 1
            pen = pyqtgraph.mkPen(color, width=linewidth)
            vLineClick = pyqtgraph.InfiniteLine(angle=90, movable=False, pen=pen)
            vLineClick.setPos(xpos)
            p.vlines.append(vLineClick)
            p.vlines_xpos.append(xpos)
            if len(p.vlines) > 2:
                vLine_rem  = p.vlines.pop(0)
                vline_rem_xpos = p.vlines_xpos.pop(0)
                p.plotWidget.removeItem(vLine_rem)
            #print('Set pen 3')
            p.plotWidget.addItem(vLineClick, ignoreBounds=True)

    def set_datastream_legacy(self,i, d, sn='', unit='', sensortype='', parameter=''):
        """
        Set the datastream for sensor i
        """
        funcname = __name__ + '.set_datastream():'
        logger.debug(funcname)
        #print('Set datastream!!')
        #print('i',i,'d',d,'sn',sn,'unit',unit,'sensortype',sensortype)
        #print('--------Set datastream!!---------')
        p = self.plot_widgets[i]
        if True:
            self.device.custom_config.calibrationdata[i].datastream = d
            self.device.custom_config.calibrationdata[i].sn = sn
            self.device.custom_config.calibrationdata[i].unit = unit
            self.device.custom_config.calibrationdata[i].sensor_model = sensortype
            self.device.custom_config.calibrationdata[i].channel = parameter
            self.allsensornames[i] = d
            p.datastream = d
        if isinstance(p, XYPlotWidget.XYPlotWidget):
            p.config.lines[0].y_addr = d
            #print('line', p.config.lines[0])
            p.set_title(d)
            p.apply_config()
        if True:
            # I dont like this, should be replaced by the SensorData definitions
            p.sn = sn
            p.unit = unit
            #print('p.unit', p.unit)
            p.sensortype = sensortype
            # Add devicename to the column
            daddr = redvypr.RedvyprAddress(d)
            senstr = daddr.get_str('/d/k/')
            col = p.datatablecolumn
            tmp = self.allsensornames[i]
            try:
                self.device.custom_config.name_ref_sensor = self.allsensornames[self.device.custom_config.ind_ref_sensor]
            except:
                logger.debug(funcname + ' Could not set ref sensor',exc_info=True)
            self.sensorcols[i] = senstr
            p.sensname_header = daddr.datakey
            #self.datacolumns[col] = senstr
            self.update_datatable()
            self.device.deviceinitwidget.populateSensorInputWidgets()

    def update_data(self, data):
        funcname = __name__ + '.update():'
        logger.debug(funcname)
        try:
            #print('Data',data)
            found_subscription = False
            for i, caldata in enumerate(self.device.custom_config.calibrationdata):
                if caldata.inputtype == 'datastream':
                    plot_widget = caldata.__plot_widget
                    #print('Checking widget',i,plot_widget.datastream)
                    if data in plot_widget.datastream:
                        #logger.debug('Updating plot {:d}')
                        plot_widget.update_plot(data)
                        try:
                            update_datainfo = caldata.__update_with_datapacket
                        except:
                            update_datainfo = True

                        if update_datainfo:
                            datastream = caldata.datastream
                            #logger.debug('Updating datastreams {}'.format(datastream))
                            try:
                                keyinfo = self.device.redvypr.get_metadata(datastream)
                            except:
                                keyinfo = None
                            #keyinfo = self.device.get_metadata(datastream)
                            logger.debug(funcname + 'Datakeyinfo {}'.format(keyinfo))
                            #print('Keyinfo',keyinfo)
                            try:
                                parameter = datastream.datakey
                            except:
                                parameter = 'NA'

                            # Try to get a serial number
                            # Use the metadataentry first, otherwise use the packetid
                            try:
                                sn = keyinfo['sn']
                            except:
                                try:
                                    sn = datastream.packetid
                                except:
                                    sn = ''
                            try:
                                unit = keyinfo['unit']
                            except:
                                unit = 'NA'
                            try:
                                sensortype = keyinfo['sensortype']
                            except:
                                try:
                                    sensortype = datastream.devicename
                                except:
                                    sensortype = ''

                            p = plot_widget
                            caldata.sn = sn
                            caldata.unit = unit
                            caldata.sensor_model = sensortype
                            caldata.channel = parameter
                            self.allsensornames[i] = datastream
                            p.sn = sn
                            p.unit = unit
                            # print('p.unit', p.unit)
                            p.sensortype = sensortype
                            # Add devicename to the column
                            senstr = datastream.get_str('/d/k/')
                            col = p.datatablecolumn
                            tmp = self.allsensornames[i]
                            self.sensorcols[i] = senstr
                            p.sensname_header = datastream.datakey
                            self.update_datatable()
                            caldata.__update_with_datapacket = False

                        plot_widget.update_plot(data)

        except Exception:
            logger.warning('Could not update with data',exc_info=True)


        #print('Hallo',self.datastreams)





        
