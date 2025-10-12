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
from .calibration_models import CalibrationHeatFlow, CalibrationNTC, CalibrationPoly, SensorData, CalibrationData
from .autocalibration import  AutoCalEntry, AutoCalConfig, autocalWidget
from redvypr.devices.sensors.generic_sensor.calibrationWidget import CalibrationsSaveWidget
_logo_file = redvypr_files.logo_file
_icon_file = redvypr_files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.calibration')
logger.setLevel(logging.DEBUG)

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
        parameter_raddr = RedvyprAddress(parameter)
        cal_poly = CalibrationPoly(parameter=parameter_raddr, sn=sdata.sn, sensor_model=sdata.sensor_model, calibration_uuid=self.device.custom_config.calibration_uuid)
        #cal_poly.parameter = sdata.parameter
        #cal_poly.sn = sdata.sn
        #cal_poly.sensor_model = sdata.sensor_model
        tdatas = tdatetime.strftime('%Y-%m-%d %H:%M:%S.%f')
        cal_poly.date = tdatetime
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
            tdata = self.device.custom_config.calibrationdata_time[0]
            tdatetime = datetime.datetime.utcfromtimestamp(tdata)
            tdatas = tdatetime.strftime('%Y-%m-%d %H:%M:%S.%f')
            calibrations = []
            degree = self.device.custom_config.calibrationtype_extra['poly_degree']
            for i, sdata in enumerate(self.device.custom_config.calibrationdata):
                if i == refindex:
                    cal_POLY = CalibrationPoly()
                    cal_POLY.parameter = RedvyprAddress(sdata.parameter)
                    cal_POLY.sn = sdata.sn
                    cal_POLY.date = tdatetime
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
                            parameter = RedvyprAddress(sdata.parameter)
                            cal_POLY = self.calc_poly_coeff(parameter, sdata, tdatetime, caldata, refdata, degree)
                            calibrations.append(cal_POLY)
                        elif len(calshape) == 2:
                            print('Array of sensors')
                            cal_POLYs = []
                            for isub in range(calshape[1]):
                                parameter = RedvyprAddress(sdata.parameter + '[{}]'.format(isub))
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
            calibrations = self.calc_poly_coeffs()
        except Exception as e:
            logger.warning(funcname)
            logger.exception(e)
            calibrations = None

        print(funcname + 'Calibrations',calibrations)

        if calibrations is not None:
            # Save the data
            self.calibration_poly['calibrationdata'] = calibrationdata
            self.calibration_poly['calibrations'] = calibrations
            # Save the calibration as a private attribute
            self.device.custom_config.__calibrations__ = calibrations
            headers = ['Parameter','SN','Coeffs']
            self.calibration_poly['coefftable'].setHorizontalHeaderLabels(headers)
            irow = 0
            for i, coeff_tmp in enumerate(calibrations):
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
                    parameter = str(coeff.parameter)
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
        calibrationtype = self.device.custom_config.calibrationtype.lower()
        if calibrationtype == 'poly':
            logger.debug(funcname + ' plotting POLY calibration')
            try:
                calibrationdata = self.device.custom_config.calibrationdata
                coeffs = self.device.custom_config.__calibrations__
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
        calibrations = self.device.custom_config.__calibrations__
        self.__savecalwidget__ = CalibrationsSaveWidget(calibrations=calibrations)
        self.__savecalwidget__.show()




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
            self.calibration_ntc['layout'].addRow(label)
            self.calibration_ntc['layout'].addRow(self.calibration_ntc['coefftable'])
            self.calibration_ntc['layout'].addRow(self.calibration_ntc['calcbutton'])
            self.calibration_ntc['layout'].addRow(self.calibration_ntc['plotbutton'])
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

    def calc_ntc_coeff(self, calibration_data, calibration_reference):
        print("Hallo",calibration_data)
        tdata = calibration_data.time_data[0]
        tdatetime = datetime.datetime.utcfromtimestamp(tdata)
        tdatas = tdatetime.strftime('%Y-%m-%d %H:%M:%S.%f%z')
        parameter = RedvyprAddress(calibration_data.parameter)
        # And finally the fit
        Toff = 273.15
        poly_degree = 3
        cal_NTC = CalibrationNTC(parameter = parameter, sn = calibration_data.sn,
                                 sensor_model = calibration_data.sensor_model,
                                 calibration_uuid=self.device.custom_config.calibration_uuid,
                                 calibration_data=calibration_data, calibration_reference_data=calibration_reference,
                                 date=tdatetime, Toff=Toff)

        cal_NTC.fit_ntc(poly_degree)

        print('Fit data', cal_NTC.coeff)
        if False: # This should be somewhere else
            # T_test = calc_ntc(R, P_R, TOFF)
            T_test = cal_NTC.raw2data(R)
            # Calculate Ntest values between min and max
            Ntest = 100
            Rtest = np.linspace(min(R), max(R), Ntest)
            T_Ntest = cal_NTC.raw2data(Rtest)
        print('Cal NTC', cal_NTC)

        return cal_NTC

    def calc_ntc_coeffs(self):
        funcname = __name__ + '.calc_ntc_coeffs():'
        logger.debug(funcname)

        refindex = self.device.custom_config.ind_ref_sensor
        print('Refindex', refindex)
        if refindex >= 0 and (len(self.device.custom_config.calibrationdata_time) > 0):
            calibration_reference = CalibrationData(**self.device.custom_config.calibrationdata[refindex].model_dump())
            #calibration_reference = CalibrationData.model_validate(self.device.custom_config.calibrationdata[refindex],
            #                                                       from_attributes=False, strict=True)

            calibrations = []
            for i, sdata in enumerate(self.device.custom_config.calibrationdata):
                if i == refindex:
                    #cal_NTC = CalibrationNTC()
                    #cal_NTC.parameter = RedvyprAddress(sdata.parameter)
                    #cal_NTC.sn = sdata.sn
                    #cal_NTC.date = tdatetime
                    #cal_NTC.comment = 'reference sensor'
                    calibrations.append(None)
                else:
                    try:
                        calibration_data = CalibrationData(**self.device.custom_config.calibrationdata[i].model_dump())
                        #calibration_data = CalibrationData.model_validate(
                        #    self.device.custom_config.calibrationdata[i],
                        #    from_attributes=False, strict=True)
                        caldata = np.asarray(calibration_data.data)
                        print('Caldata',caldata)
                        print('Shape caldata',np.shape(caldata))
                        calshape = np.shape(caldata)

                        if len(calshape) == 1:
                            print('Normal array')
                            parameter = RedvyprAddress(calibration_data.parameter)
                            cal_NTC = self.calc_ntc_coeff(calibration_data=calibration_data, calibration_reference=calibration_reference)
                            calibrations.append(cal_NTC)
                        elif len(calshape) == 2:
                            print('Array of sensors')
                            cal_NTCs = []
                            for isub in range(calshape[1]):
                                parameter = RedvyprAddress(sdata.parameter + '[{}]'.format(isub))
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

    def get_calibrations(self):
        table = self.calibration_ntc['coefftable']
        rows = []
        calibrations = []
        if table.selectionModel().selection().indexes():
            for i in table.selectionModel().selection().indexes():
                row, column = i.row(), i.column()
                item = table.item(row,0)
                calibration = item.__calibration__
                rows.append(row)
                calibrations.append(calibration)

        return calibrations



    def update_coefftable_ntc(self):
        funcname = __name__ + '.update_coefftable_ntc():'
        logger.debug(funcname)
        self.calibration_ntc['coefftable'].clear()
        nrows = len(self.device.custom_config.calibrationdata) - 1
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
            self.device.custom_config.__calibrations__ = coeffs
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

                for cindex,calibration in zip(coeff_index,coeff_tmp):
                    parameter = calibration.parameter
                    #if cindex is not None:
                    #    parameter += '[{}]'.format(cindex)
                    try:
                        parameter_str = parameter.address_str
                    except:
                        parameter_str = str(parameter)
                    #print('Parameter',parameter,str(parameter),type(parameter))
                    item = QtWidgets.QTableWidgetItem(parameter_str)
                    item.__parameter__ = parameter
                    item.__calibration__ = calibration
                    self.calibration_ntc['coefftable'].setItem(irow,0,item)
                    item = QtWidgets.QTableWidgetItem(calibration.sn)
                    self.calibration_ntc['coefftable'].setItem(irow,1,item)
                    try:
                        coeff_sen = calibration.coeff
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
        calibrationtype = self.device.custom_config.calibrationtype.lower()
        if calibrationtype == 'ntc':
            logger.debug(funcname + ' plotting NTC calibration')
            try:
                calibrationdata = self.device.custom_config.calibrationdata
                coeffs = self.device.custom_config.__calibrations__
            except Exception as e:
                coeffs = None
                logger.exception(e)
                logger.debug(funcname)
            if coeffs is not None:
                self.plot_ntc(coeffs)
        else:
            logger.debug(funcname + ' Unknown calibration {:s}'.format(calibrationtype))

    def plot_ntc(self, coeffs=None):
        funcname = __name__ + '.plot_ntc():'
        logger.debug(funcname)
        calibrations = self.get_calibrations()
        logger.debug('Calibrations: {}'.format(calibrations))
        #self.plot_coeff_widget = PlotWidgetNTC(self.device.custom_config, coeffs)
        #self.plot_coeff_widget.show()

    def save_calibration(self):
        funcname = __name__ + '.save_calibration():'
        logger.debug(funcname)
        calibrations = self.device.custom_config.__calibrations__
        self.__savecalwidget__ = CalibrationsSaveWidget(calibrations=calibrations)
        self.__savecalwidget__.show()



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
        coeffs = self.device.custom_config.__calibrations__

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
            coeffs = self.device.custom_config.__calibrations__
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
                coeffs = self.device.custom_config.__calibrations__
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
                    cal_HF = CalibrationHeatFlow(calibration_id=self.device.custom_config.calibration_id, calibration_comment=self.device.custom_config.calibration_comment, calibration_uuid=self.device.custom_config.calibration_uuid)
                    cal_HF.sn = sdata.sn
                    cal_HF.date = tdatetime
                    cal_HF.comment = 'reference sensor'
                    calibrations.append(cal_HF)
                else:
                    cal_HF = CalibrationHeatFlow(calibration_id=self.device.custom_config.calibration_id, calibration_comment=self.device.custom_config.calibration_comment, calibration_uuid=self.device.custom_config.calibration_uuid)
                    cal_HF.sn = sdata.sn
                    cal_HF.date = tdatetime
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
            self.device.custom_config.__calibrations__ = calibrations
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