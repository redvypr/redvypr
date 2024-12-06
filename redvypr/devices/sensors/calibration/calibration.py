import copy
import datetime
import os.path
import zoneinfo
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
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
from redvypr.gui import datastreamWidget
from redvypr.devices.plot import XYplotWidget
from redvypr.devices.plot import plot_widgets
from .calibration_models import calibration_HF, calibration_NTC, calibration_poly
from .autocalibration import  AutoCalEntry, AutoCalConfig, autocalWidget

_logo_file = redvypr_files.logo_file
_icon_file = redvypr_files.icon_file
description = 'Calibration of sensors'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('calibration')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = True
    description: str = 'Calibration of sensors'
    gui_tablabel_display: str = 'Realtime data'

# Dictionary for sensordata
class SensorData(pydantic.BaseModel):
    sn: str = pydantic.Field(default='')
    parameter: str = pydantic.Field(default='')
    sensor_model: str = pydantic.Field(default='')
    unit: str = pydantic.Field(default='')
    sensortype: str = pydantic.Field(default='')
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress(''))
    inputtype: str = pydantic.Field(default='')
    comment: str = pydantic.Field(default='')
    data: list = pydantic.Field(default=[])
    rawdata: list = pydantic.Field(default=[])
    time_data: list = pydantic.Field(default=[])
    time_rawdata: list = pydantic.Field(default=[])
    realtimeplottype: typing.Literal['Table', 'XY-Plot'] = pydantic.Field(default='Table', description='Type of realtimedataplot')

def get_uuid():
    return 'CAL_' + str(uuid.uuid4())

class DeviceCustomConfig(pydantic.BaseModel):
    calibrationdata: typing.Optional[typing.List[SensorData]] = pydantic.Field(default=[])
    calibrationdata_time: typing.Optional[typing.List] = pydantic.Field(default=[])
    #calibration_coeffs: typing.Optional[typing.List] = pydantic.Field(default=[])
    calibrationtype: typing.Literal['polynom','ntc'] = pydantic.Field(default='polynom')
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
    autocal_config: AutoCalConfig = pydantic.Field(default=AutoCalConfig())
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


        # Convert calibrationdata to normal data
        self.subscribe_to_sensors()

    def add_standard_config(self):
        # Check if we have NTC or heatflow calibration
        if str(self.custom_config.calibrationtype).lower() == 'ntc':
            print('NTC calibration')
            # config_template['sensors']           = {'type':'list','default':['§(NTC[0-9])|(T)§/§DHF_raw.*§','§(NTC[0-9])|(T)§/§DHF_raw.*§','§(NTC[0-9])|(T)§/§DHF_raw.*§','§(NTC[0-9])|(T)§/§DHF_raw.*§'], 'description':'The subscriptions for the sensors to be calibrated, for each subscription the first will be taken and not used for the next sensor'}
            sensors = ['{(NTC[0-9])}/{DHF_raw.*}', '{(NTC[0-9])}/{DHF_raw.*}', '{(NTC[0-9])}/{DHF_raw.*}',
                       '{(NTC[0-9])}/{DHF_raw.*}', '(NTC[0-9])}/{DHF_raw.*}', '{(NTC[0-9])}/{DHF_raw.*}']
            manualsensors = ['FLUID100-N-2l']
            for s in sensors:
                self.add_sensor(s, 'datastream')

            for s in manualsensors:
                self.add_sensor(s, 'manual')
        elif str(self.custom_config.calibrationtype).lower() == 'heatflow':
            print('Heatflow calibration')
            # config_template['sensors']           = {'type':'list','default':['§(NTC[0-9])|(T)§/§DHF_raw.*§','§(NTC[0-9])|(T)§/§DHF_raw.*§','§(NTC[0-9])|(T)§/§DHF_raw.*§','§(NTC[0-9])|(T)§/§DHF_raw.*§'], 'description':'The subscriptions for the sensors to be calibrated, for each subscription the first will be taken and not used for the next sensor'}
            sensors = ['{(HF[0-9])}/{DHF_raw.*}', '{(HF[0-9])}/{DHF_raw.*}', '{(HF[0-9])}/{DHF_raw.*}']
            manualsensors = []
            for s in sensors:
                self.add_sensor(s, 'datastream')

            for s in manualsensors:
                self.add_sensor(s, 'manual')

        self.subscribe_to_sensors()

    def add_sensor(self, newsen, sentype='datastream'):
        funcname = __name__ + '.add_sensor()'
        logger.debug(funcname + ' Adding new sensor with name: "{:s}"'.format(str(newsen)))
        sentype = str(sentype)

        #newsen = str(newsen)
        if sentype == 'datastream':
            logger.debug(funcname + ' Adding datastream of sensor {}'.format(newsen))
            sensor = SensorData(datastream=newsen, parameter=newsen.datakey, inputtype=sentype)
            self.custom_config.calibrationdata.append(sensor)
            index = len(self.custom_config.calibrationdata) - 1
        else:
            logger.debug(funcname + ' Adding manual sensor')
            #print('config',str(newsen))
            sensor = SensorData(mac=newsen, inputtype=sentype)
            self.custom_config.calibrationdata.append(sensor)
            index = len(self.custom_config.calibrationdata) - 1

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
                sdata.data.append(np.NaN)
                sdata.rawdata.append(np.NaN)
                sdata.time_data.append(np.NaN)
                sdata.time_rawdata.append(np.NaN)

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
                    sdata.data.append(np.NaN)
                    sdata.rawdata.append(np.NaN)
                    sdata.time_data.append(np.NaN)
                    sdata.time_rawdata.append(np.NaN)

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
            folder_path = folder_path_orig.format(SENSOR_MODEL=cal.sensor_model, SN=cal.sn, PARAMETER=cal.parameter)
            calfilename_orig = self.custom_config.calibration_file_structure
            calfilename = calfilename_orig(SENSOR_MODEL=cal.sensor_model, SN=cal.sn, PARAMETER=cal.parameter)
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



class CalibrationWidgetPoly(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tabtext = 'Polynom Calibration'
        # A widget for the calibration using a polynom
        self.device = self.parent().device
        try:
            degree = self.device.custom_config.calibrationtype_extra['poly_degree']
        except:
            degree = 2
            self.device.custom_config.calibrationtype_extra['poly_degree'] = degree

        layout = QtWidgets.QVBoxLayout(self)
        self.calibration_poly = {}
        self.calibration_poly['widget'] = QtWidgets.QWidget()
        layout.addWidget(self.calibration_poly['widget'])
        self.calibration_poly['layout'] = QtWidgets.QFormLayout(self.calibration_poly['widget'])
        self.calibration_poly['degree'] = QtWidgets.QSpinBox()
        self.calibration_poly['degree'].setValue(degree)
        self.calibration_poly['degree'].setMaximum(10)
        self.calibration_poly['degree'].setMinimum(0)
        self.calibration_poly['degree'].valueChanged.connect(self._poly_degree_changed)
        self.calibration_poly['plotbutton'] = QtWidgets.QPushButton('Plot')
        self.calibration_poly['plotbutton'].clicked.connect(self.plot_data)
        self.calibration_poly['calcbutton'] = QtWidgets.QPushButton('Calculate')
        self.calibration_poly['calcbutton'].clicked.connect(self.calc_poly_coeffs_clicked)
        self.calibration_poly['savecalibbutton'] = QtWidgets.QPushButton('Save Calibration')
        self.calibration_poly['savecalibbutton'].clicked.connect(self.save_calibration)
        self.calibration_poly['coefftable'] = QtWidgets.QTableWidget()

        if True:
            self.update_coefftable_poly()
            label = QtWidgets.QLabel('Polynom Calibration')
            label.setStyleSheet("font-weight: bold")
            # label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            label.setAlignment(QtCore.Qt.AlignCenter)
            deglabel = QtWidgets.QLabel('Degree')
            self.calibration_poly['layout'].addRow(label)
            self.calibration_poly['layout'].addRow(deglabel, self.calibration_poly['degree'])
            self.calibration_poly['layout'].addRow(self.calibration_poly['coefftable'])
            self.calibration_poly['layout'].addRow(self.calibration_poly['calcbutton'])
            self.calibration_poly['layout'].addRow(self.calibration_poly['plotbutton'])
            self.calibration_poly['layout'].addRow(self.calibration_poly['savecalibbutton'])
            # self.calibration_poly['layout'].setStretch(0, 1)
            # self.calibration_poly['layout'].setStretch(1, 10)

    def _poly_degree_changed(self):
        funcname = __name__ + '._poly_degree_changed():'
        degree = self.calibration_poly['degree'].value()
        logger.debug(funcname + 'Degree {}'.format(degree))
        self.device.custom_config.calibrationtype_extra['poly_degree'] = degree
    def calc_poly_coeffs_clicked(self):
        """
        Calculate the coefficients
        """
        funcname = __name__ + '.calc_poly_coeffs_clicked():'
        logger.debug(funcname)
        self.update_coefftable_poly()

    def calc_poly_coeff(self, parameter, sdata, tdatetime, caldata, refdata, degree):
        funcname = __name__ + '.calc_poly_coeff():'
        logger.debug(funcname)
        cal_poly = calibration_poly(parameter = parameter, sn = sdata.sn, sensor_model = sdata.sensor_model)
        #cal_poly.parameter = sdata.parameter
        #cal_poly.sn = sdata.sn
        #cal_poly.sensor_model = sdata.sensor_model
        tdatas = tdatetime.strftime('%Y-%m-%d %H:%M:%S.%f')
        cal_poly.date = tdatas
        caldataa = np.asarray(caldata)
        print('caldata', caldataa)
        print('refdata', refdata)
        # And finally the fit
        fitdata = np.polyfit(refdata,caldataa,degree)
        cal_poly.coeff = fitdata.tolist()
        # T_test = calc_poly(R, P_R, TOFF)
        #T_test = calc_POLY(cal_POLY, R)
        # Calculate Ntest values between min and max
        #Ntest = 100
        #Rtest = np.linspace(min(R), max(R), Ntest)
        #T_Ntest = calc_POLY(cal_POLY, Rtest)

        # caldata = np.asarray(self.device.config.calibrationdata[i].data) * 1000  # V to mV
        # print('Caldata', caldata)
        # print('Refdata', refdata)
        # ratio = np.asarray(refdata) / np.asarray(caldata)
        # cal_POLY.coeff = float(ratio.mean())
        # cal_POLY.coeff_std = float(ratio.std())
        print('Cal POLY', cal_poly)

        return cal_poly

    def calc_poly_coeffs(self):
        funcname = __name__ + '.calc_poly_coeffs():'
        logger.debug(funcname)

        refindex = self.device.custom_config.ind_ref_sensor
        print('Refindex', refindex)
        if refindex >= 0 and (len(self.device.custom_config.calibrationdata_time) > 0):
            refdata = np.asarray(self.device.custom_config.calibrationdata[refindex].data)
            coeff_hf = {}
            coeff_hf['hf'] = []
            coeff_hf['hf_std'] = []
            coeff_hf['hf_ratio'] = []
            tdata = self.device.custom_config.calibrationdata_time[0]
            tdatetime = datetime.datetime.utcfromtimestamp(tdata)
            tdatas = tdatetime.strftime('%Y-%m-%d %H:%M:%S.%f')
            calibrations = []
            degree = self.device.custom_config.calibrationtype_extra['poly_degree']
            for i, sdata in enumerate(self.device.custom_config.calibrationdata):
                if i == refindex:
                    cal_POLY = calibration_poly()
                    cal_POLY.parameter = sdata.parameter
                    cal_POLY.sn = sdata.sn
                    cal_POLY.date = tdatas
                    cal_POLY.comment = 'reference sensor'
                    calibrations.append(cal_POLY)
                else:
                    try:
                        caldata = np.asarray(self.device.custom_config.calibrationdata[i].data)
                        print('Caldata',caldata)
                        print('Shape caldata',np.shape(caldata))
                        calshape = np.shape(caldata)
                        if len(calshape) == 1:
                            print('Normal array')
                            parameter = sdata.parameter
                            cal_POLY = self.calc_poly_coeff(parameter, sdata, tdatetime, caldata, refdata, degree)
                            calibrations.append(cal_POLY)
                        elif len(calshape) == 2:
                            print('Array of sensors')
                            cal_POLYs = []
                            for isub in range(calshape[1]):
                                parameter = sdata.parameter + '[{}]'.format(isub)
                                cal_POLYs.append(self.calc_poly_coeff(parameter, sdata, tdatetime, caldata[:,isub], refdata, degree))

                            calibrations.append(cal_POLYs)
                        else:
                            logger.warning(funcname + ' Too many dimensions', exc_info=True)
                            calibrations.append(None)
                            continue

                    except:
                        logger.warning(funcname + 'Could not calculate coefficients', exc_info=True)
                        calibrations.append(None)

            return calibrations
        else:
            logger.warning('No reference sensor or not enough data')
            return None

    def update_coefftable_poly(self):
        funcname = __name__ + '.update_coefftable_poly():'
        logger.debug(funcname)
        self.calibration_poly['coefftable'].clear()
        nrows = len(self.device.custom_config.calibrationdata)
        try:
            self.calibration_poly['coefftable'].setRowCount(nrows)
        except:
            logger.debug(funcname, exc_info=True)
            return

        self.calibration_poly['coefftable'].setColumnCount(3)
        # Calculate the coefficients
        try:
            calibrationdata = self.calibdata_to_dict()
        except Exception as e:
            logger.exception(e)
            return

        print(funcname + 'Calculating coefficients')
        try:
            coeffs = self.calc_poly_coeffs()
        except Exception as e:
            logger.warning(funcname)
            logger.exception(e)
            coeffs = None

        print(funcname + 'Coeffs',coeffs)

        if coeffs is not None:
            # Save the data
            self.calibration_poly['calibrationdata'] = calibrationdata
            self.calibration_poly['coeffs'] = coeffs
            # Save the calibration as a private attribute
            self.device.custom_config.__calibration_coeffs__ = coeffs
            headers = ['Parameter','SN','Coeffs']
            self.calibration_poly['coefftable'].setHorizontalHeaderLabels(headers)
            irow = 0
            for i, coeff_tmp in enumerate(coeffs):
                if coeff_tmp is None:
                    continue
                if type(coeff_tmp) == list:
                    nrows += len(coeff_tmp)
                    coeff_index = range(len(coeff_tmp))
                    self.calibration_poly['coefftable'].setRowCount(nrows)
                else:
                    coeff_tmp = [coeff_tmp]
                    coeff_index = [None]

                for cindex,coeff in zip(coeff_index,coeff_tmp):
                    parameter = coeff.parameter
                    #if cindex is not None:
                    #    parameter += '[{}]'.format(cindex)
                    item = QtWidgets.QTableWidgetItem(parameter)
                    self.calibration_poly['coefftable'].setItem(irow,0,item)
                    item = QtWidgets.QTableWidgetItem(coeff.sn)
                    self.calibration_poly['coefftable'].setItem(irow,1,item)
                    try:
                        coeff_sen = coeff.coeff
                        coeff_str = str(coeff_sen)
                        item_coeff = QtWidgets.QTableWidgetItem(coeff_str)
                        self.calibration_poly['coefftable'].setItem(irow, 2, item_coeff)
                    except Exception as e:
                        logger.exception(e)

                    irow += 1

        self.calibration_poly['coefftable'].resizeColumnsToContents()

    def calibdata_to_dict(self):
        funcname = __name__ + '.calibdata_to_dict():'
        logger.debug(funcname)
        calibdata = []
        for sdata in self.device.custom_config.calibrationdata:
            calibdata.append(sdata.model_dump())

        return calibdata

    def plot_data(self):
        funcname = __name__ + '.plot_data():'
        logger.debug(funcname)
        print('Hallo')
        calibrationtype = self.device.custom_config.calibrationtype.lower()
        if calibrationtype == 'poly':
            logger.debug(funcname + ' plotting POLY calibration')
            try:
                calibrationdata = self.device.custom_config.calibrationdata
                coeffs = self.device.custom_config.__calibration_coeffs__
            except Exception as e:
                coeffs = None
                logger.exception(e)
                logger.debug(funcname)
            if coeffs is not None:
                self.plot_poly(coeffs)
        else:
            logger.debug(funcname + ' Unknown calibration {:s}'.format(calibrationtype))

        # self.update_tables_calc_coeffs()

    def save_calibration(self):
        funcname = __name__ + '.save_calibration():'
        logger.debug(funcname)

        self.save_widget = QtWidgets.QWidget()
        self.save_widget_layout = QtWidgets.QFormLayout(self.save_widget)
        self.save_widget_dict = {}
        folderpath_init = '.' + os.sep + '{SN}'
        self.save_widget_dict['le'] = QtWidgets.QLineEdit(folderpath_init)
        self.save_widget_dict['le'].editingFinished.connect(self.__populate__calibrationfilelist__)
        calfolder = QtWidgets.QPushButton('Choose Calibration Folder')
        calfolder.clicked.connect(self.__choose_calfolder__)

        calfile_structure = '{SN}_{PARAMETER}_{CALDATE}.yaml'
        self.save_widget_dict['le_calfile'] = QtWidgets.QLineEdit(calfile_structure)
        self.save_widget_dict['le_calfile'].editingFinished.connect(self.__populate__calibrationfilelist__)

        self.save_widget_dict['filelist'] = QtWidgets.QListWidget()

        savecal_but = QtWidgets.QPushButton('Save calibration')
        savecal_but.clicked.connect(self.__save_calibration__)

        self.save_widget_layout.addRow(calfolder, self.save_widget_dict['le'])
        self.save_widget_layout.addRow(QtWidgets.QLabel('Calibrationfile'),self.save_widget_dict['le_calfile'])
        self.save_widget_layout.addRow(self.save_widget_dict['filelist'])
        self.save_widget_layout.addRow(savecal_but)
        # Update the calibrationdata
        # calibrationdata = self.calibdata_to_dict()
        # self.update_coefftable_poly()
        # try:
        #    calibrationdata = self.calibration_poly['calibrationdata']
        #    coeffs = self.calibration_poly['coeffs']
        # except Exception as e:
        #    logger.debug(funcname)
        #    logger.exception(e)
        #    coeffs = None


        self.__populate__calibrationfilelist__()
        #folderpath = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Folder')


        self.save_widget.show()

    def __save_calibration__(self):
        funcname = __name__ + '__save_calibration__():'
        overwrite = True
        create_path = True
        fnames_full = self.save_widget_dict['fnames_full']
        for fname_full,fname_cal_full,c,cal in fnames_full:
            dirname = os.path.dirname(fname_full)
            if os.path.isdir(dirname):
                print('Path exists')
            elif create_path:
                print('Creating directory')
                os.mkdir(dirname)
            else:
                print('Directory does not exist, will not write file')
                continue
            if os.path.isfile(fname_full):
                logger.warning('File is already existing {:s}'.format(fname_full))
                file_exist = True
            else:
                file_exist = False

            if overwrite or (file_exist == False):
                logger.info('Saving file to {:s}'.format(fname_full))
                if c.comment == 'reference sensor':
                    logger.debug(funcname + ' Will not save calibration (reference sensor)')
                else:
                    cdump = c.model_dump()
                    # data_save = yaml.dump(cdump)

                    with open(fname_full, 'w') as fyaml:
                        yaml.dump(cdump, fyaml)
                    print('Cal', cal)
                    caldump = cal.model_dump()
                    # data_save = yaml.dump(cdump)
                    #with open(fname_cal_full, 'w') as fyaml:
                    #    yaml.dump(caldump, fyaml)

    def __populate__calibrationfilelist__(self):
        funcname = __name__ + '__populate__calibrationfilelist__():'
        calibrationdata = self.device.custom_config.calibrationdata
        coeffs = self.device.custom_config.__calibration_coeffs__

        fnames_full = []
        folderpath = self.save_widget_dict['le'].text()
        self.save_widget_dict['filelist'].clear()
        if len(folderpath) > 0:
            logger.debug(funcname + ' Saving data to folder {:s}'.format(folderpath))
            for c_tmp, cal in zip(coeffs, calibrationdata):
                if type(c_tmp) is not list:
                    c_tmp = [c_tmp]
                for c in c_tmp:
                    # Calibrationdata stays the same if its a list for all subparameter
                    print('Saving coeff', c)
                    date = datetime.datetime.strptime(c.date, "%Y-%m-%d %H:%M:%S.%f")
                    dstr = date.strftime('%Y-%m-%d_%H-%M-%S')
                    fname = '{:s}_{:s}_{:s}.yaml'.format(c.sn, c.parameter, dstr)
                    calfile_structure = self.save_widget_dict['le_calfile'].text()
                    try:
                        fname = calfile_structure.format(SN=c.sn, CALDATE=dstr, PARAMETER=c.parameter)
                    except:
                        fname = calfile_structure

                    fname_full = folderpath + '/' + fname
                    # Add the placeholders
                    try:
                        fname_full = fname_full.format(SN=c.sn, CALDATE=dstr, PARAMETER=c.parameter)
                    except:
                        pass

                    fname_cal = '{:s}_{:s}_{:s}_calibrationdata.yaml'.format(c.sn, c.parameter, dstr)
                    fname_cal_full = folderpath + '/' + fname_cal
                    fnames_full.append([fname_full,fname_cal_full, c,cal])

                    self.save_widget_dict['filelist'].addItem(fname_full)

                self.save_widget_dict['fnames_full'] = fnames_full


    def __choose_calfolder__(self):
        folderpath = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Folder')
        if len(folderpath) > 0:
            self.save_widget_dict['le'].setText(folderpath)







class CalibrationWidgetNTC(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tabtext = 'NTC Calibration'
        # A NTC widget for the calibration
        self.device = self.parent().device
        layout = QtWidgets.QVBoxLayout(self)
        self.calibration_ntc = {}
        self.calibration_ntc['widget'] = QtWidgets.QWidget()
        layout.addWidget(self.calibration_ntc['widget'])
        self.calibration_ntc['layout'] = QtWidgets.QFormLayout(self.calibration_ntc['widget'])
        self.calibration_ntc['refcombo'] = QtWidgets.QComboBox()
        self.calibration_ntc['plotbutton'] = QtWidgets.QPushButton('Plot')
        self.calibration_ntc['plotbutton'].clicked.connect(self.plot_data)
        self.calibration_ntc['calcbutton'] = QtWidgets.QPushButton('Calculate')
        self.calibration_ntc['calcbutton'].clicked.connect(self.calc_ntc_coeffs_clicked)
        self.calibration_ntc['dhfsbutton'] = QtWidgets.QPushButton('DHFS commands')
        self.calibration_ntc['dhfsbutton'].clicked.connect(self.dhfs_command_clicked)
        self.calibration_ntc['savecalibbutton'] = QtWidgets.QPushButton('Save Calibration')
        self.calibration_ntc['savecalibbutton'].clicked.connect(self.save_calibration)
        self.calibration_ntc['coefftable'] = QtWidgets.QTableWidget()

        if True:
            self.update_coefftable_ntc()
            label = QtWidgets.QLabel('NTC Calibration')
            label.setStyleSheet("font-weight: bold")
            # label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            label.setAlignment(QtCore.Qt.AlignCenter)
            reflabel = QtWidgets.QLabel('Reference Sensor')
            print('Add')
            self.calibration_ntc['layout'].addRow(label)
            self.calibration_ntc['layout'].addRow(self.calibration_ntc['coefftable'])
            self.calibration_ntc['layout'].addRow(self.calibration_ntc['calcbutton'])
            self.calibration_ntc['layout'].addRow(self.calibration_ntc['plotbutton'])
            self.calibration_ntc['layout'].addRow(self.calibration_ntc['dhfsbutton'])
            self.calibration_ntc['layout'].addRow(self.calibration_ntc['savecalibbutton'])
            # self.calibration_ntc['layout'].setStretch(0, 1)
            # self.calibration_ntc['layout'].setStretch(1, 10)


    def calc_ntc_coeffs_clicked(self):
        """
        Calculate the coefficients
        """
        funcname = __name__ + '.calc_ntc_coeffs_clicked():'
        logger.debug(funcname)
        self.update_coefftable_ntc()

    def calc_ntc_coeff(self, parameter, sdata, tdatetime, caldata, refdata):
        cal_NTC = calibration_NTC(parameter = parameter, sn = sdata.sn, sensor_model = sdata.sensor_model, calibration_uuid=self.device.custom_config.calibration_uuid)
        #cal_NTC.parameter = sdata.parameter
        #cal_NTC.sn = sdata.sn
        #cal_NTC.sensor_model = sdata.sensor_model
        tdatas = tdatetime.strftime('%Y-%m-%d %H:%M:%S.%f')
        cal_NTC.date = tdatas
        R = np.asarray(caldata)
        R = np.abs(R)
        T = refdata
        print('R', R)
        print('T', T)
        # And finally the fit
        TOFF = 273.15
        fitdata = fit_ntc(T, R, TOFF)
        P_R = fitdata['P_R']
        cal_NTC.coeff = P_R.tolist()
        print('P_R', P_R)
        # T_test = calc_ntc(R, P_R, TOFF)
        T_test = calc_NTC(cal_NTC, R)
        # Calculate Ntest values between min and max
        Ntest = 100
        Rtest = np.linspace(min(R), max(R), Ntest)
        T_Ntest = calc_NTC(cal_NTC, Rtest)

        # caldata = np.asarray(self.device.config.calibrationdata[i].data) * 1000  # V to mV
        # print('Caldata', caldata)
        # print('Refdata', refdata)
        # ratio = np.asarray(refdata) / np.asarray(caldata)
        # cal_NTC.coeff = float(ratio.mean())
        # cal_NTC.coeff_std = float(ratio.std())
        print('Cal NTC', cal_NTC)

        return cal_NTC

    def calc_ntc_coeffs(self):
        funcname = __name__ + '.calc_ntc_coeffs():'
        logger.debug(funcname)

        refindex = self.device.custom_config.ind_ref_sensor
        print('Refindex', refindex)
        if refindex >= 0 and (len(self.device.custom_config.calibrationdata_time) > 0):
            refdata = np.asarray(self.device.custom_config.calibrationdata[refindex].data)
            coeff_hf = {}
            coeff_hf['hf'] = []
            coeff_hf['hf_std'] = []
            coeff_hf['hf_ratio'] = []
            tdata = self.device.custom_config.calibrationdata_time[0]
            tdatetime = datetime.datetime.utcfromtimestamp(tdata)
            tdatas = tdatetime.strftime('%Y-%m-%d %H:%M:%S.%f')
            calibrations = []
            for i, sdata in enumerate(self.device.custom_config.calibrationdata):
                if i == refindex:
                    cal_NTC = calibration_NTC()
                    cal_NTC.parameter = sdata.parameter
                    cal_NTC.sn = sdata.sn
                    cal_NTC.date = tdatas
                    cal_NTC.comment = 'reference sensor'
                    calibrations.append(cal_NTC)
                else:
                    try:
                        caldata = np.asarray(self.device.custom_config.calibrationdata[i].data)
                        print('Caldata',caldata)
                        print('Shape caldata',np.shape(caldata))
                        calshape = np.shape(caldata)
                        if len(calshape) == 1:
                            print('Normal array')
                            parameter = sdata.parameter
                            cal_NTC = self.calc_ntc_coeff(parameter, sdata, tdatetime, caldata, refdata)
                            calibrations.append(cal_NTC)
                        elif len(calshape) == 2:
                            print('Array of sensors')
                            cal_NTCs = []
                            for isub in range(calshape[1]):
                                parameter = sdata.parameter + '[{}]'.format(isub)
                                cal_NTCs.append(self.calc_ntc_coeff(parameter, sdata, tdatetime, caldata[:,isub], refdata))

                            calibrations.append(cal_NTCs)
                        else:
                            logger.warning(funcname + ' Too many dimensions', exc_info=True)
                            calibrations.append(None)
                            continue

                    except:
                        logger.warning(funcname + 'Could not calculate coefficients', exc_info=True)
                        calibrations.append(None)

            return calibrations
        else:
            logger.warning('No reference sensor or not enough data')
            return None

    def update_coefftable_ntc(self):
        funcname = __name__ + '.update_coefftable_ntc():'
        logger.debug(funcname)
        self.calibration_ntc['coefftable'].clear()
        nrows = len(self.device.custom_config.calibrationdata)
        try:
            self.calibration_ntc['coefftable'].setRowCount(nrows)
        except:
            logger.debug(funcname, exc_info=True)
            return

        self.calibration_ntc['coefftable'].setColumnCount(3)
        # Calculate the coefficients
        try:
            calibrationdata = self.calibdata_to_dict()
        except Exception as e:
            logger.exception(e)
            return

        print(funcname + 'Calculating coefficients')
        try:
            coeffs = self.calc_ntc_coeffs()
        except Exception as e:
            logger.warning(funcname)
            logger.exception(e)
            coeffs = None

        print(funcname + 'Coeffs',coeffs)

        if coeffs is not None:
            # Save the data
            self.calibration_ntc['calibrationdata'] = calibrationdata
            self.calibration_ntc['coeffs'] = coeffs
            # Save the calibration as a private attribute
            self.device.custom_config.__calibration_coeffs__ = coeffs
            headers = ['Parameter','SN','Coeffs']
            self.calibration_ntc['coefftable'].setHorizontalHeaderLabels(headers)
            irow = 0
            for i, coeff_tmp in enumerate(coeffs):
                if coeff_tmp is None:
                    continue
                if type(coeff_tmp) == list:
                    nrows += len(coeff_tmp)
                    coeff_index = range(len(coeff_tmp))
                    self.calibration_ntc['coefftable'].setRowCount(nrows)
                else:
                    coeff_tmp = [coeff_tmp]
                    coeff_index = [None]

                for cindex,coeff in zip(coeff_index,coeff_tmp):
                    parameter = coeff.parameter
                    #if cindex is not None:
                    #    parameter += '[{}]'.format(cindex)
                    try:
                        parameter_str = parameter.address_str
                    except:
                        parameter_str = str(parameter)
                    print('Parameter',parameter,str(parameter),type(parameter))
                    item = QtWidgets.QTableWidgetItem(parameter_str)
                    item.__parameter__ = parameter
                    self.calibration_ntc['coefftable'].setItem(irow,0,item)
                    item = QtWidgets.QTableWidgetItem(coeff.sn)
                    self.calibration_ntc['coefftable'].setItem(irow,1,item)
                    try:
                        coeff_sen = coeff.coeff
                        coeff_str = str(coeff_sen)
                        item_coeff = QtWidgets.QTableWidgetItem(coeff_str)
                        self.calibration_ntc['coefftable'].setItem(irow, 2, item_coeff)
                    except Exception as e:
                        logger.exception(e)

                    irow += 1

        self.calibration_ntc['coefftable'].resizeColumnsToContents()

    def calibdata_to_dict(self):
        funcname = __name__ + '.calibdata_to_dict():'
        logger.debug(funcname)
        calibdata = []
        for sdata in self.device.custom_config.calibrationdata:
            calibdata.append(sdata.model_dump())

        return calibdata

    def plot_data(self):
        funcname = __name__ + '.plot_data():'
        logger.debug(funcname)
        print('Hallo')
        calibrationtype = self.device.custom_config.calibrationtype.lower()
        if calibrationtype == 'ntc':
            logger.debug(funcname + ' plotting NTC calibration')
            try:
                calibrationdata = self.device.custom_config.calibrationdata
                coeffs = self.device.custom_config.__calibration_coeffs__
            except Exception as e:
                coeffs = None
                logger.exception(e)
                logger.debug(funcname)
            if coeffs is not None:
                self.plot_ntc(coeffs)
        else:
            logger.debug(funcname + ' Unknown calibration {:s}'.format(calibrationtype))

        # self.update_tables_calc_coeffs()

    def dhfs_command_clicked(self):
        funcname = __name__ + '.dhfs_command_clicked():'
        logger.debug(funcname)
        try:
            calibrationdata = self.device.custom_config.calibrationdata
            coeffs = self.device.custom_config.__calibration_coeffs__
        except Exception as e:
            logger.exception(e)
            logger.debug(funcname)

        for c, cal in zip(coeffs, calibrationdata):
            # print('Coeff', c)
            if 'ntc' in c.parameter.lower():
                coeffstr = ''
                # print('coeff',c.coeff)
                for ctmp in reversed(c.coeff):
                    coeffstr += '{:.6e} '.format(ctmp)
                comstr = '{:s}: set {:s} {:s}'.format(c.sn, c.parameter.lower(), coeffstr)
                # print('Command')
                print(comstr)
            elif 'hf' in c.parameter.lower():
                coeffstr = '{:.3f} '.format(c.coeff)
                comstr = '{:s}: set {:s} {:s}'.format(c.sn, c.parameter.lower(), coeffstr)
                # print('Command')
                print(comstr)
            else:
                logger.info(funcname + ' unknown parameter {:s}'.format(c.parameter))

    def save_calibration(self):
        funcname = __name__ + '.save_calibration():'
        logger.debug(funcname)

        self.save_widget = QtWidgets.QWidget()
        self.save_widget_layout = QtWidgets.QFormLayout(self.save_widget)
        self.save_widget_dict = {}
        folderpath_init = '.' + os.sep + '{SN}' + os.sep + '{CALDATE}'
        self.save_widget_dict['le'] = QtWidgets.QLineEdit(folderpath_init)
        self.save_widget_dict['le'].editingFinished.connect(self.__populate__calibrationfilelist__)
        calfolder = QtWidgets.QPushButton('Choose Calibration Folder')
        calfolder.clicked.connect(self.__choose_calfolder__)

        calfile_structure = '{SN}_{PARAMETER}_{CALDATE}.yaml'
        self.save_widget_dict['le_calfile'] = QtWidgets.QLineEdit(calfile_structure)
        self.save_widget_dict['le_calfile'].editingFinished.connect(self.__populate__calibrationfilelist__)

        self.save_widget_dict['filelist'] = QtWidgets.QListWidget()

        savecal_but = QtWidgets.QPushButton('Save calibration')
        savecal_but.clicked.connect(self.__save_calibration__)

        self.save_widget_layout.addRow(calfolder, self.save_widget_dict['le'])
        self.save_widget_layout.addRow(QtWidgets.QLabel('Calibrationfile'),self.save_widget_dict['le_calfile'])
        self.save_widget_layout.addRow(self.save_widget_dict['filelist'])
        self.save_widget_layout.addRow(savecal_but)
        # Update the calibrationdata
        # calibrationdata = self.calibdata_to_dict()
        # self.update_coefftable_ntc()
        # try:
        #    calibrationdata = self.calibration_ntc['calibrationdata']
        #    coeffs = self.calibration_ntc['coeffs']
        # except Exception as e:
        #    logger.debug(funcname)
        #    logger.exception(e)
        #    coeffs = None


        self.__populate__calibrationfilelist__()
        #folderpath = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Folder')


        self.save_widget.show()

    def __save_calibration__(self):
        funcname = __name__ + '__save_calibration__():'
        overwrite = True
        create_path = True
        fnames_full = self.save_widget_dict['fnames_full']
        for fname_full,fname_cal_full,c,cal in fnames_full:
            dirname = os.path.dirname(fname_full)
            if os.path.isdir(dirname):
                logger.info('Folder exists:{}'.format(dirname))
            elif c.comment == 'reference sensor':
                logger.info('Reference sensor, ignoring')
            elif create_path:
                logger.info('Creating folder:{}'.format(dirname))
                #os.mkdir(dirname)
                os.makedirs(dirname)
            else:

                logger.info('Folder {} does not exist, will not write file'.format(dirname))
                continue
            if os.path.isfile(fname_full):
                logger.warning('File is already existing {:s}'.format(fname_full))
                file_exist = True
            else:
                file_exist = False

            if overwrite or (file_exist == False):
                logger.info('Saving file to {:s}'.format(fname_full))
                if c.comment == 'reference sensor':
                    logger.debug(funcname + ' Will not save calibration (reference sensor)')
                else:
                    cdump = c.model_dump()
                    # data_save = yaml.dump(cdump)

                    with open(fname_full, 'w') as fyaml:
                        yaml.dump(cdump, fyaml)
                    print('Cal', cal)
                    caldump = cal.model_dump()
                    # data_save = yaml.dump(cdump)
                    #with open(fname_cal_full, 'w') as fyaml:
                    #    yaml.dump(caldump, fyaml)

    def __populate__calibrationfilelist__(self):
        funcname = __name__ + '__populate__calibrationfilelist__():'
        calibrationdata = self.device.custom_config.calibrationdata
        coeffs = self.device.custom_config.__calibration_coeffs__

        fnames_full = []
        folderpath = self.save_widget_dict['le'].text()
        self.save_widget_dict['filelist'].clear()
        if len(folderpath) > 0:
            logger.debug(funcname + ' Saving data to folder {:s}'.format(folderpath))
            for c_tmp, cal in zip(coeffs, calibrationdata):
                if type(c_tmp) is not list:
                    c_tmp = [c_tmp]
                for c in c_tmp:
                    # Calibrationdata stays the same if its a list for all subparameter
                    print('Saving coeff', c)
                    date = datetime.datetime.strptime(c.date, "%Y-%m-%d %H:%M:%S.%f")
                    dstr = date.strftime('%Y-%m-%d_%H-%M-%S')
                    # Distinguish between RedvyprAddress and str
                    try:
                        parameter_str = c.parameter.address_str
                    except:
                        parameter_str = c.parameter
                    fname = '{:s}_{:s}_{:s}.yaml'.format(c.sn, parameter_str, dstr)
                    calfile_structure = self.save_widget_dict['le_calfile'].text()
                    try:
                        fname = calfile_structure.format(SN=c.sn, CALDATE=dstr, PARAMETER=parameter_str)
                    except:
                        fname = calfile_structure

                    fname_full = folderpath + '/' + fname
                    # Add the placeholders
                    try:
                        fname_full = fname_full.format(SN=c.sn, CALDATE=dstr, PARAMETER=parameter_str)
                    except:
                        pass

                    fname_cal = '{:s}_{:s}_{:s}_calibrationdata.yaml'.format(c.sn, parameter_str, dstr)
                    fname_cal_full = folderpath + '/' + fname_cal
                    fnames_full.append([fname_full,fname_cal_full, c,cal])

                    self.save_widget_dict['filelist'].addItem(fname_full)

                self.save_widget_dict['fnames_full'] = fnames_full


    def __choose_calfolder__(self):
        folderpath = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Folder')
        if len(folderpath) > 0:
            self.save_widget_dict['le'].setText(folderpath)

class PlotWidgetNTC(QtWidgets.QWidget):
    def __init__(self, config, coeffs):
        super().__init__()
        self.setWindowIcon(QtGui.QIcon(_icon_file))
        funcname = self.__class__.__name__ + '__init__():'

        self.setWindowTitle('Calibration results')
        self.plotlist = QtWidgets.QListWidget()
        self.plotlist.currentRowChanged.connect(self.change_plot)
        layout = QtWidgets.QHBoxLayout(self)
        tabwidget = QtWidgets.QStackedWidget()
        self.tabwidget = tabwidget
        layout.addWidget(self.plotlist)
        layout.addWidget(tabwidget)
        layout.setStretch(0, 1)
        layout.setStretch(1, 5)
        senwidgets = {}

        refindex = config.ind_ref_sensor
        print('Refindex', refindex)
        if refindex >= 0 and (len(config.calibrationdata_time) > 0):
            refdata = np.asarray(config.calibrationdata[refindex].data)
            tdata = config.calibrationdata_time[0]
            tdatetime = datetime.datetime.utcfromtimestamp(tdata)
            tdatas = tdatetime.strftime('%Y-%m-%d %H:%M:%S.%f')
            calibrations = []
            for i, sdata in enumerate(config.calibrationdata):
                cal_NTC = coeffs[i]
                if i == refindex:
                    print('Refindex')
                else:
                    caldata = np.asarray(config.calibrationdata[i])
                    R = np.asarray(caldata)
                    T = refdata
                    print('R', R)
                    print('T', T)
                    sen = cal_NTC.parameter + '/' + cal_NTC.sn
                    self.plotlist.addItem(sen)
                    senwidgets[sen] = {}
                    senwidget = QtWidgets.QWidget()
                    senwidgets[sen]['widget'] = senwidget
                    tabwidget.addWidget(senwidget)  # ,sen)
                    senlayout = QtWidgets.QVBoxLayout(senwidget)

                    mplplot = PlotCanvas(self, width=5, height=4)
                    axes = mplplot.fig.add_subplot(211)
                    axes.plot(caldata, refdata, 'or')
                    axes.set_title(sen)
                    # Calculate the data using the coefficients
                    if True:
                        T = calc_NTC(cal_NTC,caldata)
                        dT = T - refdata
                        axes_dT = mplplot.fig.add_subplot(212)
                        axes_dT.plot(caldata, dT, 'or')

                    senlayout.addWidget(mplplot)




    def change_plot(self,index):
        funcname = self.__class__.__name__ + '.change_plot():'
        logger.debug(funcname)
        self.tabwidget.setCurrentIndex(index)



class CalibrationWidgetHeatflow(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        QtWidgets.QWidget.__init__(self, *args, **kwargs)
        self.device = self.parent().device # The redvypr device
        self.calibration_hf = {}
        self.calibration_hf['widget'] = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.calibration_hf['widget'])
        self.calibration_hf['layout'] = QtWidgets.QFormLayout(self.calibration_hf['widget'])
        self.calibration_hf['refcombo'] = QtWidgets.QComboBox()
        self.calibration_hf['plotbutton'] = QtWidgets.QPushButton('Plot')
        self.calibration_hf['plotbutton'].clicked.connect(self.plot_data)
        self.calibration_hf['calcbutton'] = QtWidgets.QPushButton('Calculate')
        self.calibration_hf['calcbutton'].clicked.connect(self.calc_hf_coeffs_clicked)
        self.calibration_hf['dhfsbutton'] = QtWidgets.QPushButton('DHFS command')
        self.calibration_hf['dhfsbutton'].clicked.connect(self.dhfs_command_clicked)
        self.calibration_hf['savecalibbutton'] = QtWidgets.QPushButton('Save Calibration')
        self.calibration_hf['savecalibbutton'].clicked.connect(self.save_calibration)
        self.calibration_hf['coefftable'] = QtWidgets.QTableWidget()
        self.calibration_hf['coefftable'].horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        # self.calibration_hf['coefftable'].verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        # self.update_coefftable_ntc()
        for sen in self.parent().sensorcols:
            self.calibration_hf['refcombo'].addItem(sen)

        for sen in self.parent().manualsensorcols:
            self.calibration_hf['refcombo'].addItem(sen)

        label = QtWidgets.QLabel('Heatflow Calibration')
        label.setStyleSheet("font-weight: bold")
        # label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        label.setAlignment(QtCore.Qt.AlignCenter)
        reflabel = QtWidgets.QLabel('Reference Sensor')
        self.calibration_hf['layout'].addRow(label)
        self.calibration_hf['layout'].addRow(self.calibration_hf['coefftable'])
        self.calibration_hf['layout'].addRow(self.calibration_hf['calcbutton'])
        self.calibration_hf['layout'].addRow(self.calibration_hf['plotbutton'])
        self.calibration_hf['layout'].addRow(self.calibration_hf['dhfsbutton'])
        self.calibration_hf['layout'].addRow(self.calibration_hf['savecalibbutton'])
        # self.calibration_ntc['layout'].setStretch(0, 1)
        # self.calibration_ntc['layout'].setStretch(1, 10)
        # END HF widget
        # self.calibration_widget = self.calibration_ntc['widget']
        self.update_coefftable_hf()

    def save_calibration(self):
        funcname = __name__ + '.save_calibration():'
        logger.debug(funcname)
        overwrite = True
        # Update the calibrationdata
        #calibrationdata = self.calibdata_to_dict()
        #self.update_coefftable_ntc()
        #try:
        #    calibrationdata = self.calibration_ntc['calibrationdata']
        #    coeffs = self.calibration_ntc['coeffs']
        #except Exception as e:
        #    logger.debug(funcname)
        #    logger.exception(e)
        #    coeffs = None

        calibrationdata = self.device.custom_config.calibrationdata
        coeffs = self.device.custom_config.__calibration_coeffs__

        folderpath = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Folder')
        if len(folderpath) > 0:
            logger.debug(funcname + ' Saving data to folder {:s}'.format(folderpath))
            for c,cal in zip(coeffs,calibrationdata):
                print('Saving coeff',c)
                date = datetime.datetime.strptime(c.date,"%Y-%m-%d %H:%M:%S.%f")
                dstr = date.strftime('%Y-%m-%d_%H-%M-%S')
                fname = '{:s}_{:s}_{:s}.yaml'.format(c.sn,c.parameter,dstr)
                fname_full = folderpath + '/' + fname
                fname_cal = '{:s}_{:s}_{:s}_calibrationdata.yaml'.format(c.sn, c.parameter, dstr)
                fname_cal_full = folderpath + '/' + fname_cal
                if os.path.isfile(fname_full):
                    logger.warning('File is already existing {:s}'.format(fname_full))
                    file_exist = True
                else:
                    file_exist = False

                if overwrite or (file_exist == False):
                    logger.info('Saving file to {:s}'.format(fname_full))
                    if c.comment == 'reference sensor':
                        logger.debug(funcname + ' Will not save calibration (reference sensor)')
                    else:
                        cdump = c.model_dump()
                        #data_save = yaml.dump(cdump)
                        with open(fname_full, 'w') as fyaml:
                            yaml.dump(cdump, fyaml)

                        caldump = cal.model_dump()
                        # data_save = yaml.dump(cdump)
                        with open(fname_cal_full, 'w') as fyaml:
                            yaml.dump(caldump, fyaml)

    def dhfs_command_clicked(self):
        funcname = __name__ + '.dhfs_command_clicked():'
        logger.debug(funcname)
        try:
            calibrationdata = self.device.custom_config.calibrationdata
            coeffs = self.device.custom_config.__calibration_coeffs__
        except Exception as e:
            logger.exception(e)
            logger.debug(funcname)


        for c, cal in zip(coeffs, calibrationdata):
            #print('Coeff', c)
            if 'ntc' in c.parameter.lower():
                coeffstr = ''
                #print('coeff',c.coeff)
                for ctmp in reversed(c.coeff):
                    coeffstr += '{:.6e} '.format(ctmp)
                comstr = '{:s}: set {:s} {:s}'.format(c.sn,c.parameter.lower(),coeffstr)
                #print('Command')
                print(comstr)
            elif 'hf' in c.parameter.lower():
                coeffstr = '{:.3f} '.format(c.coeff)
                comstr = '{:s}: set {:s} {:s}'.format(c.sn, c.parameter.lower(), coeffstr)
                # print('Command')
                print(comstr)
            else:
                logger.info(funcname + ' unknown parameter {:s}'.format(c.parameter))

    def plot_data(self):
        funcname = __name__ + '.plot_data():'
        logger.debug(funcname)
        print('Hallo')
        calibrationtype = self.device.custom_config.calibrationtype.lower()
        if calibrationtype == 'ntc':
            logger.debug(funcname + ' plotting NTC calibration')
            try:
                calibrationdata = self.device.custom_config.calibrationdata
                coeffs = self.device.custom_config.__calibration_coeffs__
            except Exception as e:
                coeffs = None
                logger.exception(e)
                logger.debug(funcname)
            if coeffs is not None:
                self.plot_ntc(coeffs)
        else:
            logger.debug(funcname + ' Unknown calibration {:s}'.format(calibrationtype))

        #self.update_tables_calc_coeffs()

    def calc_hf_coeffs_clicked(self):
        """
        Calculate the coefficients
        """
        funcname = __name__ + '.calc_hf_coeffs_clicked():'
        logger.debug(funcname)
        self.update_coefftable_hf()

    def calc_hf_coeffs(self):
        funcname = __name__ + '.calc_hf_coeffs():'
        logger.debug(funcname)

        refindex  = self.device.custom_config.ind_ref_sensor
        print('Refindex', refindex)
        if refindex >= 0 and (len(self.device.custom_config.calibrationdata_time) > 0):
            refdata = self.device.custom_config.calibrationdata[refindex].data
            coeff_hf = {}
            coeff_hf['hf'] = []
            coeff_hf['hf_std'] = []
            coeff_hf['hf_ratio'] = []
            tdata = self.device.custom_config.calibrationdata_time[0]
            tdatetime = datetime.datetime.utcfromtimestamp(tdata)
            tdatas = tdatetime.strftime('%Y-%m-%d %H:%M:%S.%f')
            calibrations = []
            for i,sdata in enumerate(self.device.custom_config.calibrationdata):
                if i == refindex:
                    cal_HF = calibration_HF(calibration_id=self.device.custom_config.calibration_id,calibration_comment=self.device.custom_config.calibration_comment, calibration_uuid=self.device.custom_config.calibration_uuid)
                    cal_HF.sn = sdata.sn
                    cal_HF.date = tdatas
                    cal_HF.comment = 'reference sensor'
                    calibrations.append(cal_HF)
                else:
                    cal_HF = calibration_HF(calibration_id=self.device.custom_config.calibration_id,calibration_comment=self.device.custom_config.calibration_comment, calibration_uuid=self.device.custom_config.calibration_uuid)
                    cal_HF.sn = sdata.sn
                    cal_HF.date = tdatas
                    cal_HF.sensor_model = sdata.sensor_model
                    # TODO, V to mV more smart
                    caldata = np.asarray(self.device.custom_config.calibrationdata[i].data) * 1000 # V to mV
                    print('Caldata',caldata)
                    print('Refdata', refdata)
                    ratio = np.asarray(refdata)/np.asarray(caldata)
                    cal_HF.coeff = float(ratio.mean())
                    cal_HF.coeff_std = float(ratio.std())
                    calibrations.append(cal_HF)

            return calibrations
        else:
            logger.warning('No reference sensor or not enough data')
            return None

    def update_coefftable_hf(self):
        funcname = __name__ + '.update_coefftable_hf():'
        logger.debug(funcname)
        calibrations = self.calc_hf_coeffs()
        if calibrations is not None:
            print('Calibrations',calibrations)
            nrows = len(self.device.custom_config.calibrationdata) - 1
            self.calibration_hf['coefftable'].clear()
            self.calibration_hf['coefftable'].setColumnCount(3)
            self.calibration_hf['coefftable'].setRowCount(nrows)
            colheaders = ['SN','Coeff','Coeff std']
            self.calibration_hf['coefftable'].setHorizontalHeaderLabels(colheaders)
            # Save the calibration as a private attribute
            self.device.custom_config.__calibration_coeffs__ = calibrations
            refindex = self.device.custom_config.ind_ref_sensor
            imac   = 0
            icoeff = 1
            icoeff_std = 2
            irow   = -1
            print('Calibrationdata', self.device.custom_config.calibrationdata)
            for i, sdata in enumerate(self.device.custom_config.calibrationdata):
                print('calibrationdata',i,sdata)
                if i == refindex:
                    continue
                irow += 1
                # MAC
                senname = calibrations[i].sn
                item = QtWidgets.QTableWidgetItem(senname)
                self.calibration_hf['coefftable'].setItem(irow,imac,item)
                # Coeff
                coeffstr = "{:.4f}".format(calibrations[i].coeff)
                item = QtWidgets.QTableWidgetItem(coeffstr)
                self.calibration_hf['coefftable'].setItem(irow, icoeff, item)
                # Coeff_std
                coeff_stdstr = "{:.4f}".format(calibrations[i].coeff_std)
                item = QtWidgets.QTableWidgetItem(coeff_stdstr)
                self.calibration_hf['coefftable'].setItem(irow, icoeff_std, item)



class QTableCalibrationWidget(QtWidgets.QTableWidget):
    def __init__(self, *args, **kwargs):
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
        self.setColumnCount(1)
        hlabel = "{}:".format(sensorindex)
        self.setHorizontalHeaderLabels([hlabel])
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)

    def get_data(self, t_intervall):
        # Relative data
        if (t_intervall[0] <= 0) and (t_intervall[1] <= 0):
            t_intervall[0] = t_intervall[0] + self.data_buffer_t[-1]
            t_intervall[1] = t_intervall[1] + self.data_buffer_t[-1]

        ttmp = np.asarray(self.data_buffer_t)
        ind = (ttmp >= min(t_intervall)) & (ttmp <= max(t_intervall))
        print('ind', ind)
        data = {'t': [], 'x': [], 'y': []}
        if sum(ind) > 0:
            indi = np.where(ind)[0]
            print('indi', indi)
            for i in indi:
                data['t'].append(self.data_buffer_t[i])
                data['x'].append(self.data_buffer_t[i])
                data['y'].append(self.data_buffer[i])

            print('Shape',np.shape(data['y']))
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
                self.data_buffer.append(data_tmp)
                self.data_buffer_t.append(rdata['t'])

                if len(self.data_buffer) > self.data_buffer_len:
                    self.data_buffer.pop(0)
                    self.data_buffer_t.pop(0)

                # Update the table
                self.setRowCount(1)
                if type(data_tmp) == list:
                    self.setColumnCount(len(data_tmp))
                    for indd, d in enumerate(data_tmp):
                        dstr = str(d)
                        item = QtWidgets.QTableWidgetItem(dstr)
                        self.setItem(0,indd,item)
                else:
                    self.setColumnCount(1)
                    dstr = str(data_tmp)
                    item = QtWidgets.QTableWidgetItem(dstr)
                    self.setItem(0, 0, item)

                #print('len data buffer', self.data_buffer_t)
                #self.resizeColumnsToContents()
                ncols = self.rowCount()
                header = self.horizontalHeader()
                header.setSectionResizeMode(ncols-1, QtWidgets.QHeaderView.Stretch)
                if self.headerlabel is None:
                    hlabel = "{}:".format(dindex) + daddr.get_str('/k')
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


def fit_ntc(T,R,Toff):
    TK = T + Toff
    T_1 = 1 / (TK)
    # logR = log(R/R0)
    logR = np.log(R)
    P_R = np.polyfit(logR, T_1, 3)
    return {'P_R':P_R}

def calc_ntc_legacy(R,P_R,Toff):
    T_1 = np.polyval(P_R,np.log(R))
    T = 1/T_1 - Toff
    return T

def calc_NTC(calibration, R):
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
        #self.config_widget = redvypr.gui.configWidget(device.config,redvypr_instance=self.device.redvypr)

        #self.config_widgets.append(self.config_widget)

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
        self.caltype.addItem('Polynom')
        #self.caltype.addItem('Heatflow')
        self.caltype.addItem('NTC')
        calibrationtype = self.device.custom_config.calibrationtype.lower()
        if calibrationtype == 'ntc':
            self.caltype.setCurrentIndex(1) # NTC
        else:
            self.caltype.setCurrentIndex(0) # Polynom


        self.caltype.currentTextChanged.connect(self.caltype_combobox_changed)

        self.butwidget = QtWidgets.QWidget()
        self.butlayout = QtWidgets.QHBoxLayout(self.butwidget)
        self.butlayout.addWidget(self.sensoradd)
        self.butlayout.addWidget(self.sensorsadd)
        self.butlayout.addWidget(self.mansensoradd)
        self.butlayout.addWidget(self.autocalbtn)
        self.butlayout.addWidget(QtWidgets.QLabel('Calibration Type'))
        self.butlayout.addWidget(self.caltype)
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

                sensorPlotType = QtWidgets.QComboBox()  # Choose a datastream
                sensorPlotType.addItem('Table')
                sensorPlotType.addItem('XY Plot')
                sensorPlotType.listindex = i
                sensorPlotType.sensortype = 'datastream'

                if 'XY' in sdata.realtimeplottype:
                    sensorPlotType.setCurrentIndex(1)  # XY
                else:
                    sensorPlotType.setCurrentIndex(0)  # Table
                sensorPlotType.currentIndexChanged.connect(self.__realtimePlotChanged__)
                refbutton = QtWidgets.QRadioButton("Reference")
                refbutton.refindex = i
                refbutton.toggled.connect(self.refsensor_changed)
                buttons.append(refbutton)
                ref_group.addButton(refbutton,id=nsensors)
                sensors.append({'sensorDatastream':sensorDatastream})
                self.sensorsConfig_datastream_layout.addWidget(sensorNum, nsensors, 0)
                self.sensorsConfig_datastream_layout.addWidget(sensorDatastream, nsensors, 1)
                self.sensorsConfig_datastream_layout.addWidget(sensorChoose, nsensors, 3)
                self.sensorsConfig_datastream_layout.addWidget(sensorRem, nsensors, 4)
                self.sensorsConfig_datastream_layout.addWidget(sensorPlotType, nsensors, 5)
                self.sensorsConfig_datastream_layout.addWidget(refbutton, nsensors, 6)
                nsensors += 1
                if i == int(self.device.custom_config.ind_ref_sensor):
                    refbutton.setChecked(True)
            else:
                mansensorNum = QtWidgets.QLabel(str(nsensors))
                mansensorName = QtWidgets.QLineEdit(sdata.sn)  # The name of the sensor
                mansensorName.editingFinished.connect(self.manualSensorChanged)
                mansensorName.listindex = i
                mansensorRem = QtWidgets.QPushButton('Remove')  # Choose a datastream
                manrefbutton = QtWidgets.QRadioButton("Reference")
                manrefbutton.refindex = i
                manrefbutton.toggled.connect(self.refsensor_changed)
                buttons.append(manrefbutton)
                ref_group.addButton(manrefbutton,id=nsensors)
                mansensorRem.clicked.connect(self.sensorRemClicked)
                mansensorRem.listindex = i
                mansensorRem.sensortype = 'manual'
                sensors.append({'mansensorName':mansensorName})
                self.sensorsConfig_manual_layout.addWidget(mansensorNum, nsensors, 0)
                self.sensorsConfig_manual_layout.addWidget(mansensorName, nsensors, 1)
                self.sensorsConfig_manual_layout.addWidget(mansensorRem, nsensors, 2)
                self.sensorsConfig_manual_layout.addWidget(manrefbutton, nsensors, 3)
                if i == int(self.device.custom_config.ind_ref_sensor):
                    manrefbutton.setChecked(True)

                nsensors += 1

        ref_group.setExclusive(True)
        self.ref_group = ref_group
        self.sensors = sensors

    def sensorAutocalClicked(self):
        checked = self.autocalbtn.isChecked()
        self.device.devicedisplaywidget.showAutocalWidget(checked)


    def __realtimePlotChanged__(self,index):
        funcname = __name__ + '.__realtimePlotChanged__():'
        print(funcname + ' {}'.format(index))
        sensorPlotType = self.sender()
        plottype = sensorPlotType.currentText()

        indexsensor = sensorPlotType.listindex
        print('Hallo', sensorPlotType.currentText())
        self.device.custom_config.calibrationdata[indexsensor].realtimeplottype = plottype
        print('Sensor config', self.device.custom_config.calibrationdata[indexsensor])
        self.updateDisplayWidget()

    def refsensor_changed(self):

        funcname = __name__ + '.refsensor_changed():'
        logger.debug(funcname)
        if self.sender().isChecked():
            index = self.sender().refindex
            self.device.custom_config.ind_ref_sensor = index
            self.device.custom_config.name_ref_sensor = self.device.custom_config.calibrationdata[index].sn
            # Update calibration table
            # self.update_coefftable_ntc()
            #print('Config', self.device.custom_config)

    def chooseDatastream(self):
        funcname = __name__ + '.chooseDatastream():'
        logger.debug(funcname)
        button = self.sender()
        self.dstreamwidget = redvypr.gui.datastreamWidget(self.device.redvypr)
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
        print('datastream',datastream_dict)
        self.device.custom_config.calibrationdata[index].datastream = datastream_dict['datastream_address']
        try:
            self.device.devicedisplaywidget.plot_widgets[index].datastream = None
        except:
            pass

        self.updateDisplayWidget()
        self.device.subscribe_to_sensors()

    def caltype_combobox_changed(self, value):
        logger.debug("combobox changed {}".format(value))
        self.device.custom_config.calibrationtype = value.lower()
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
        self.dstreamswidget = redvypr.gui.datastreamsWidget(self.device.redvypr)
        self.dstreamswidget.apply.connect(self.sensorsApplyClicked)
        self.dstreamswidget.show()

    def sensorsApplyClicked(self,datastreamdict):
        funcname = __name__ + '.sensorsApplyClicked():'
        logger.debug(funcname)
        # Adding all addresses
        for addr in datastreamdict['addresses']:
            newsen = addr
            logger.debug(funcname + 'Adding {}'.format(newsen))
            self.device.add_sensor(newsen, 'datastream')

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

        newsen = RedvyprAddress('')
        if self.sender() == self.sensoradd:
            logger.debug('datastream sensor')
            self.device.add_sensor(newsen,'datastream')
        elif self.sender() == self.sensorsadd:
            logger.debug(funcname + ' multiple datastream sensors')
            self.device.add_sensor(newsen, 'datastream')
        else:
            logger.debug('Manual sensor')
            self.device.add_sensor(newsen, 'manual')

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

        print('Config', self.device.custom_config)
        print('Index',sensorRem.listindex)
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
            self.autocalwidget = autocalWidget(device=self.device)
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
        w_delete = [self.plot_widgets_parent, self.tablewidget, self.plot_widgets_parent, self.calibration_widget]
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
        self.tablewidget = QtWidgets.QWidget()
        self.tablewidget_layout = QtWidgets.QGridLayout(self.tablewidget)
        self.datatable = QtWidgets.QTableWidget()
        # self.update_datatable()
        self.addLineButton = QtWidgets.QPushButton('Add empty row')
        self.addLineButton.clicked.connect(self.addBlankCalibrationData)
        self.remLineButton = QtWidgets.QPushButton('Rem row(s)')
        self.remLineButton.clicked.connect(self.remCalibrationData)
        #self.loadcalibbutton = QtWidgets.QPushButton('Load Calibration')
        #self.loadcalibbutton.clicked.connect(self.load_calibration)
        # The widget the realtime data is shown
        self.plot_widgets_parent = QtWidgets.QWidget()
        self.plot_widgets_parent_layout = QtWidgets.QGridLayout(self.plot_widgets_parent)
        # Add a scroll area, to deal with a lot of data
        self.plot_widgets_parent_scroll = QtWidgets.QScrollArea()
        self.plot_widgets_parent_scroll.setWidget(self.plot_widgets_parent)
        self.plot_widgets_parent_scroll.setWidgetResizable(True)
        # Add the realtime data
        self.add_plots()

        self.addintervall_time = QtWidgets.QDoubleSpinBox()
        self.addintervall_time.setValue(30.0)
        self.addintervall_combo = QtWidgets.QComboBox()
        self.addintervall_combo.addItem('Last x seconds')
        self.addintervall_combo.addItem('Manually')
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
        self.calibration_widget = QtWidgets.QWidget()
        self.calibration_widget_layout = QtWidgets.QVBoxLayout(self.calibration_widget)

        # Datatable widget
        label = QtWidgets.QLabel('Calibration data')
        label.setStyleSheet("font-weight: bold")
        label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        label.setAlignment(QtCore.Qt.AlignCenter)
        self.datatable_widget = QtWidgets.QWidget()
        #self.datatable_widget.setStyleSheet("background-color: rgb(255,0,0); margin:5px; border:1px solid rgb(0, 255, 0); ")
        datatable_widget_layout = QtWidgets.QVBoxLayout(self.datatable_widget)
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
        #datatable_widget_layout.addStretch()



        datatable_widget_layout.addWidget(label)
        datatable_widget_layout.addWidget(self.datainput_configwidget)
        datatable_widget_layout.addWidget(self.datatable)
        datatable_widget_layout.setStretch(0, 1)
        datatable_widget_layout.setStretch(1, 1)
        datatable_widget_layout.setStretch(2, 10)


        # Create the layout

        #splitter1 = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        #splitter1.addWidget(self.datatable_widget)
        #splitter1.addWidget(self.calibration_widget)

        #self.tablewidget_layout.addWidget(splitter1,0,0,1,2)
        self.tablewidget_layout.addWidget(self.datatable_widget, 0, 0, 1, 3)
        self.tablewidget_layout.addWidget(self.addLineButton, 1, 0)
        self.tablewidget_layout.addWidget(self.remLineButton, 1, 1)
        #self.tablewidget_layout.addWidget(self.loadcalibbutton, 1, 1)
        #self.tablewidget_layout.addWidget(self.savecalibbutton, 1, 2)
        #self.tablewidget_layout.addWidget(self.calibration_widget,0,3)

        # Add the tablewidget as a new tab
        self.tabwidget.addTab(self.tablewidget,'Calibration data')
        # Add the tablewidget as a new tab
        calibrationtype = self.device.custom_config.calibrationtype.lower()
        self.tabwidget.addTab(self.calibration_widget, 'TMP')

        self.update_datatable()
        # This needs to be done after the tab, as it changes text of the tab
        self.create_calibration_widget()  # Is adding a widget to self.calibration_widget
        #self.order_tabs()

    def update_custom_config_from_widgets(self):
        funcname = __name__ + '.update_custom_config_from_widgets():'
        print(funcname)
        self.device.custom_config.calibration_comment = self.datainput_configwidgets['lco'].text()
        self.device.custom_config.calibration_id = self.datainput_configwidgets['lID'].text()
        #print('Config')
        #print(self.device.custom_config)
        #print('Done')

    def remCalibrationData(self):
        """
        Adds a blank calibrationdata to the datatable
        """
        funcname = __name__ + '.remCalibrationData():'
        logger.debug(funcname)
        rows = []
        if self.datatable.selectionModel().selection().indexes():
            for i in self.datatable.selectionModel().selection().indexes():
                row, column = i.row(), i.column()
                if row >= self.irowdatastart:
                    if row not in rows:
                        rows.append(row)
                else:
                    logger.debug(funcname + ' Metadata, will not remove')

        print('Removing',rows)
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
            self.device.add_data(tadd, 0, np.NaN, np.NaN, np.NaN, np.NaN)
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

        old_position = self.tabwidget.indexOf(self.tablewidget)
        #print(funcname, old_position, 'datatable')
        self.tabwidget.tabBar().moveTab(old_position, 2)

        old_position = self.tabwidget.indexOf(self.calibration_widget)
        #print(funcname, old_position, 'calibration')
        self.tabwidget.tabBar().moveTab(old_position, 3)

    def create_calibration_widget(self):
        """
        Creates a calibration widget that uses the averaged data in the datatable to calculate coefficients
        """
        funcname = __name__ + '.create_calibration_widget():'
        logger.debug(funcname)
        # Remove all old widgets
        index = self.calibration_widget_layout.count()
        while(index >= 1):
            myWidget = self.calibration_widget_layout.itemAt(index-1).widget()
            myWidget.setParent(None)
            index -=1

        calibrationtype = self.device.custom_config.calibrationtype.lower()

        if calibrationtype.lower() == 'polynom':
            logger.debug(funcname + ' Creating Polynom calibration widget')
            tabtext = 'Polynom Calibration'
            calwidget = CalibrationWidgetPoly(self)
            self.calibration_widget_layout.addWidget(calwidget)

        elif calibrationtype == 'ntc':
            logger.debug(funcname + ' Creating NTC calibration widget')
            tabtext = 'NTC Calibration'
            calwidget = CalibrationWidgetNTC(self)
            self.calibration_widget_layout.addWidget(calwidget)

        elif calibrationtype == 'heatflow':
            logger.info(funcname + ' Heatflow calibration')
            tabtext = 'Heatflow calibration'
            calwidget = CalibrationWidgetHeatflow(self)
            self.calibration_widget_layout.addWidget(calwidget)
        else:
            logger.warning(funcname + ' Unknown calibration type {:s}'.format(calibrationtype))
            tabtext = 'Unknown calibration'
            label = QtWidgets.QLabel('Unknown calibration type')
            self.calibration_widget_layout.addWidget(label)

        # Update the text of the tab
        index = self.tabwidget.indexOf(self.calibration_widget)
        self.tabwidget.setTabText(index, tabtext)
        self.order_tabs()

    def calibdata_to_dict(self):
        funcname = __name__ + '.calibdata_to_dict():'
        logger.debug(funcname)
        calibdata = []
        for sdata in self.device.custom_config.calibrationdata:
            calibdata.append(sdata.model_dump())

        return calibdata

    def update_tables_calc_coeffs(self):
        funcname = __name__ + '.update_tables():'
        logger.debug(funcname)
        self.update_coefftable_ntc()



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
                try:
                    realtimeplottype = sdata.__realtimeplottype
                    same_plotwidgettype = realtimeplottype == sdata.realtimeplottype
                except:
                    logger.info('Could not get plottype',exc_info=True)
                    realtimeplottype = 'unknown'
                    same_plotwidgettype = False

                try:
                    plot_widget = sdata.__plot_widget
                    logger.debug('Plotwidget is existing')
                    flag_new_plot_widget = False
                except:
                    logger.debug(funcname + 'creating plotwidget')
                    flag_new_plot_widget = True

                print('same_plotwidgettype',realtimeplottype, same_plotwidgettype,flag_new_plot_widget)
                # Check if the plitwidgettype changed
                if (same_plotwidgettype == False) and (flag_new_plot_widget == False):
                    print('Changing plotwidget')
                    try:
                        sdata.__plot_widget.setParent(None)
                    except:
                        logger.info('Could not close widget',exc_info=True)

                    flag_new_plot_widget = True

                if flag_new_plot_widget:
                    print('Adding new widget',sdata.realtimeplottype)
                    #config = {}
                    #config['title'] = sdata.sn
                    #self.datastreams.append(None)
                    #plot_widget = plot_widgets.redvypr_graph_widget(config=config)
                    if 'XY' in sdata.realtimeplottype:
                        print('Adding XYplotwidget')
                        config = XYplotWidget.configXYplot()
                        plot_widget = XYplotWidget.XYPlotWidget(config=config, redvypr_device=self.device)
                        #plot_widget.plotWidget.scene().sigMouseMoved.connect(self.anyMouseMoved)
                        #plot_widget.plotWidget.scene().sigMouseClicked.connect(self.anyMouseClicked)
                        plot_widget.vlines = []  # List of vertical lines
                        plot_widget.vlines_xpos = []  # List of vertical lines
                        sdata.__realtimeplottype = sdata.realtimeplottype
                        print('Done')
                    elif 'able' in sdata.realtimeplottype:
                        plot_widget = QTableCalibrationWidget(sensorindex=i)
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
                self.plot_widgets_parent_layout.addWidget(plot_widget, nrow, ncol)
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

    def get_intervalldata(self):
        """
        Gets data and updates the datatable
        """
        funcname = __name__ + '.get_intervalldata():'
        logger.debug(funcname)
        tget = time.time() # The time the data was added
        timeintervaltype = self.addintervall_combo.currentText()
        if 'last' in timeintervaltype.lower():
            #t1 = time.time()
            #t0 = t1 - self.addintervall_time.value()
            t1 = 0
            t0 = t1 - self.addintervall_time.value()
            dt = t1 - t0
            t_intervall = [t0, t1]
            print('Getting time in interval {} {} {}'.format(t1,t0,dt))
        else:
            print('Getting manual time interval')
            t_intervall = None
            for i, plot_widget in enumerate(self.plot_widgets):
                if len(plot_widget.vlines) == 2:  # If we have two vertical linex, enough to define an interval
                    print('Getting data', plot_widget.vlines_xpos)
                    t_intervall = [min(plot_widget.vlines_xpos), max(plot_widget.vlines_xpos)]

        # for i, plot_widget in enumerate(self.plot_widgets):
        for i, caldata in enumerate(self.device.custom_config.calibrationdata):
            plot_widget = caldata.__plot_widget
            #sensor_data_tmp = self.device.custom_config.calibrationdata[plot_widget.sensorindex]
            #print('a',sensor_data_tmp)
            #print('b',sensor_data_tmp.realtimeplot)
            if True:
                if t_intervall is not None:
                    data = plot_widget.get_data(t_intervall)
                    if isinstance(plot_widget, XYplotWidget.XYPlotWidget):
                        data = data[0]
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


        print('get intervalldata time', self.device.custom_config.calibrationdata_time)
        print('get intervalldata', self.device.custom_config.calibrationdata)
        self.update_datatable()

    def __datatable_item_changed__(self,item):
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
        row = self.datatable.row(item)
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
            self.datatable.itemChanged.disconnect(self.__datatable_item_changed__)
        except:
            pass

        ncols = 1 + len(self.device.custom_config.calibrationdata)
        self.datatable.setColumnCount(ncols)
        ndatarows = len(self.device.custom_config.calibrationdata_time)
        self.datatable.setRowCount(self.irowdatastart + ndatarows)

        #self.datatable.horizontalHeader().ResizeMode(self.datatable.horizontalHeader().ResizeToContents)
        #columns = ['Time'] + self.sensorcols + self.manualsensorcols
        colheaders = ['Time']
        for i in range(ncols - 1):
            colheaders.append(str(i))
        # headeritem = QtWidgets.QTableWidgetItem('Time')
        # self.datatable.setHorizontalHeaderItem(self.timecolindex, headeritem)
        self.datatable.setHorizontalHeaderLabels(colheaders)
        self.datatable.setVerticalHeaderLabels(self.rowheader)
        self.datatable.resizeColumnsToContents()

        # self.datatable.setHorizontalHeaderLabels(self.datacolumns)
        col = 0
        #print('fdsfd', self.device.custom_config)

        for idata in range(ndatarows):
            itemdata = self.device.custom_config.calibrationdata_time[idata]
            tdatetime = datetime.datetime.utcfromtimestamp(itemdata)
            itemdatastr = tdatetime.strftime('%d-%m-%Y %H:%M:%S.%f')
            item = QtWidgets.QTableWidgetItem(itemdatastr)
            self.datatable.setItem(self.irowdatastart + idata, 0, item)


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
                self.datatable.setItem(self.irowinput, col, item)
                item = QtWidgets.QTableWidgetItem(sdata.parameter)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                item.__calibrationdata__ = sdata
                self.datatable.setItem(self.irowparameter, col, item)
                item = QtWidgets.QTableWidgetItem(sdata.sn)
                item.__calibrationdata__ = sdata
                self.datatable.setItem(self.irowmac_sn, col, item)
                item = QtWidgets.QTableWidgetItem(sdata.sensor_model)
                item.__calibrationdata__ = sdata
                self.datatable.setItem(self.irowsenstype, col, item)
                item = QtWidgets.QTableWidgetItem(sdata.unit)
                item.__calibrationdata__ = sdata
                self.datatable.setItem(self.irowunit, col, item)

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
                    self.datatable.setItem(self.irowdatastart + idata, col, item)
                    if sdata.inputtype == 'manual':
                        item.__parent__ = sdata.data
                        item.__dindex__  = idata

        self.datatable.resizeColumnsToContents()
        self.datatable.itemChanged.connect(self.__datatable_item_changed__)
        #self.datatable.setSizeAdjustPolicy(QtWidgets.QTableWidget.AdjustToContents)
        # self.datatable.resize(self.datatable.sizeHint())

    def update_datatable_metainformation(self,i):
        """
        Updates the metainformation of the datatable (units, sn/mac, sensortype
        """
        funcname = __name__ + '.update_datatable_metainformation():'
        logger.debug(funcname)
        #self.datatable.setHorizontalHeaderLabels(self.datacolumns)

        p = self.plot_widgets[i]
        col = p.datatablecolumn
        item = QtWidgets.QTableWidgetItem(p.unit)
        self.datatable.setItem(self.irowunit,col,item)
        item = QtWidgets.QTableWidgetItem(p.sn)
        self.datatable.setItem(self.irowmac_sn, col, item)
        item = QtWidgets.QTableWidgetItem(p.sensortype)
        self.datatable.setItem(self.irowsenstype, col, item)

        headeritem = QtWidgets.QTableWidgetItem(p.sensname_header)
        self.datatable.setHorizontalHeaderItem(col, headeritem)

        self.datatable.resizeColumnsToContents()
        self.datatable.setSizeAdjustPolicy(QtWidgets.QTableWidget.AdjustToContents)
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

    def set_datastream(self,i, d, sn='', unit='', sensortype='', parameter=''):
        """
        Set the datastream for sensor i
        """
        funcname = __name__ + '.set_datastream():'
        logger.debug(funcname)
        print('Set datastream!!')
        print('i',i,'d',d,'sn',sn,'unit',unit,'sensortype',sensortype)
        print('--------Set datastream!!---------')
        p = self.plot_widgets[i]
        if True:
            self.device.custom_config.calibrationdata[i].datastream = d
            self.device.custom_config.calibrationdata[i].sn = sn
            self.device.custom_config.calibrationdata[i].unit = unit
            self.device.custom_config.calibrationdata[i].sensor_model = sensortype
            self.device.custom_config.calibrationdata[i].parameter = parameter
            self.allsensornames[i] = d
            p.datastream = d
        if isinstance(p, XYplotWidget.XYPlotWidget):
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

    def plot_ntc(self, coeffs = None):
        funcname = __name__ + '.plot_ntc():'
        logger.debug(funcname)
        self.plot_coeff_widget = PlotWidgetNTC(self.device.custom_config, coeffs)
        self.plot_coeff_widget.show()

    def update_data(self, data):
        funcname = __name__ + '.update():'
        logger.debug(funcname)
        try:
            #print('Data',data)
            found_subscription = False
            for i, caldata in enumerate(self.device.custom_config.calibrationdata):
                plot_widget = caldata.__plot_widget

                print('Checking widget',i,plot_widget.datastream)
                if data in plot_widget.datastream:
                    logger.debug('Updating plot {:d}')
                    plot_widget.update_plot(data)
                    try:
                        update_datainfo = caldata.__update_with_datapacket
                    except:
                        update_datainfo = True

                    if update_datainfo:
                        datastream = caldata.datastream
                        logger.debug('Updating datastreams {}'.format(datastream))
                        keyinfo = self.device.redvypr.get_metadata(datastream)
                        #keyinfo = self.device.get_metadata(datastream)
                        logger.debug(funcname + 'Datakeyinfo {}'.format(keyinfo))
                        print('Keyinfo',keyinfo)
                        try:
                            parameter = datastream.datakey
                        except:
                            parameter = 'NA'

                        # Try to get a serial number
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
                        caldata.parameter = parameter
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





        
