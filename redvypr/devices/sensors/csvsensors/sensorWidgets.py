import datetime
import numpy as np
import logging
import sys
import threading
import copy
import yaml
import json
import typing
import pydantic
from PyQt5 import QtWidgets, QtCore, QtGui
import redvypr.gui as gui

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('sensorWidgets')
logger.setLevel(logging.DEBUG)


class sensorCoeffWidget(QtWidgets.QWidget):
    """

    """

    def __init__(self, *args, redvypr_device=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        layout = QtWidgets.QVBoxLayout(self)
        self.device = redvypr_device
        self.sensorCoeffWidget = QtWidgets.QWidget()
        layout.addWidget(self.sensorCoeffWidget)
        #self.sensorCoeffWidget.setWindowIcon(QtGui.QIcon(_icon_file))
        # self.sensorCoeffWidget.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.WindowStaysOnTopHint)
        self.sensorCoeffWidget_layout = QtWidgets.QGridLayout(self.sensorCoeffWidget)
        self.sensorCoeffWidget_list = QtWidgets.QTableWidget()

        # self.sensorCoeffWidget_list.currentRowChanged.connect(self.sensorcoefficient_changed)

        colheaders = ['SN', 'Parameter', 'Calibration date']
        self.sensorCoeffWidget_list.setColumnCount(len(colheaders))
        self.sensorCoeffWidget_list.setHorizontalHeaderLabels(colheaders)
        self.__sensorCoeffWidget_list_populate__()

        self.loadCoeffButton = QtWidgets.QPushButton('Load coefficients')
        self.loadCoeffButton.clicked.connect(self.chooseCalibrationFiles)
        self.remCoeffButton = QtWidgets.QPushButton('Remove coefficients')
        self.remCoeffButton.clicked.connect(self.remCalibration_clicked)

        # self.calibrationConfigWidget = gui.configWidget(self.device.calibration, editable=False)
        self.calibrationConfigWidget = QtWidgets.QWidget()
        self.calibrationConfigWidget_layout = QtWidgets.QVBoxLayout(self.calibrationConfigWidget)
        self.sensorCoeffWidget_layout.addWidget(self.sensorCoeffWidget_list, 0, 0)
        self.sensorCoeffWidget_layout.addWidget(self.calibrationConfigWidget, 0, 1)
        self.sensorCoeffWidget_layout.addWidget(self.loadCoeffButton, 1, 0)
        self.sensorCoeffWidget_layout.addWidget(self.remCoeffButton, 1, 1)

    def chooseCalibrationFiles(self):
        """

        """
        funcname = __name__ + '.chooseCalibrationFiles():'
        logger.debug(funcname)
        # fileName = QtWidgets.QFileDialog.getLoadFileName(self, 'Load Calibration', '',
        #                                                 "Yaml Files (*.yaml);;All Files (*)")

        fileNames = QtWidgets.QFileDialog.getOpenFileNames(self, 'Load Calibration', '',
                                                           "Yaml Files (*.yaml);;All Files (*)")
        for fileName in fileNames[0]:
            # self.device.read_calibration_file(fileName)
            print('Adding file ...', fileName)
            self.device.add_calibration_file(fileName)

        # Fill the list with sn

        if len(fileNames[0]) > 0:
            logger.debug(funcname + ' Updating the calibrationlist')
            self.__sensorCoeffWidget_list_populate__()

    def __sensorCoeffWidget_list_item_changed__(self, old, new):
        print('Changed', old, new)
        user_role = 10
        role = QtCore.Qt.UserRole + user_role
        item = self.sensorCoeffWidget_list.currentItem()
        if item is not None:
            print('fds', self.sensorCoeffWidget_list.currentRow(), item.data(role))
            cal = item.data(role)
            try:
                cal_old = self.__calConfigWidget_tmp__.cal
            except:
                cal_old = None

            if cal_old == cal:
                print('Same calibration, doing nothing')
            else:
                try:
                    self.__calConfigWidget_tmp__.close()
                except:
                    pass

                self.__calConfigWidget_tmp__ = gui.pydanticQTreeWidget(cal, dataname=cal.sn + '/' + cal.parameter,
                                                                       show_datatype=False)
                self.__calConfigWidget_tmp__.cal = cal
                self.calibrationConfigWidget_layout.addWidget(self.__calConfigWidget_tmp__)

    def __sensorCoeffWidget_list_populate__(self):
        try:
            self.sensorCoeffWidget_list.itemChanged.disconnect(self.__sensorCoeffWidget_list_item_changed__)
        except:
            pass

        # Fill the list with sn
        sns = []  # Get all serialnumbers

        for cal in self.device.config.calibrations:
            print('Cal', cal)
            sns.append(cal.sn)

        self.sensorCoeffWidget_list.setRowCount(len(self.device.config.calibrations) + 1)
        for i, cal in enumerate(self.device.config.calibrations):
            item = QtWidgets.QTableWidgetItem(cal.sn)
            user_role = 10
            role = QtCore.Qt.UserRole + user_role
            item.setData(role, cal)
            self.sensorCoeffWidget_list.setItem(i, 0, item)
            item = QtWidgets.QTableWidgetItem(cal.parameter)
            item.setData(role, cal)
            self.sensorCoeffWidget_list.setItem(i, 1, item)
            item = QtWidgets.QTableWidgetItem(cal.date)
            item.setData(role, cal)
            self.sensorCoeffWidget_list.setItem(i, 2, item)

        self.sensorCoeffWidget_list.resizeColumnsToContents()
        self.sensorCoeffWidget_list.currentCellChanged.connect(self.__sensorCoeffWidget_list_item_changed__)

    def remCalibration_clicked(self):
        funcname = __name__ + '.remCalibration_clicked()'
        logger.debug(funcname)
        self.calibrationConfigWidget.close()
        item = self.sensorCoeffWidget_list.takeItem(self.sensorCoeffWidget_list.currentRow())
        index = self.sensorCoeffWidget_list.currentRow()
        sn = item.text()
        calibration = self.device.config.calibrations.pop(index)
        print('Removed', calibration)

    def sensorcoefficient_changed(self, index):
        """
        Changes the active widget that is shown when clicked on the QListWidget
        """
        funcname = __name__ + '.sensorcoefficient_changed()'
        logger.debug(funcname)
        if index is not None:
            item = self.sensorCoeffWidget_list.currentItem()
            if item is not None:
                sn = self.sensorCoeffWidget_list.currentItem().text()
                return
                print('sn', sn)
                self.calibrationConfigWidget.close()
                calibrations = {'calibrations': self.device.config['calibrations'][sn]}
                self.calibrationConfigWidget = gui.configWidget(calibrations, editable=False,
                                                                configname='Coefficients of {:s}'.format(sn))
                self.sensorCoeffWidget_layout.addWidget(self.calibrationConfigWidget, 0, 1)
                # self.sensorstack.setCurrentIndex(index)
            else:
                try:
                    self.calibrationConfigWidget.close()
                except:
                    pass

class sensorCoeffWidget_legacy(QtWidgets.QWidget):
    """
    Widget to display all sensor coefficients
    """
    coeff = QtCore.pyqtSignal( dict )  # Signal returning the coefficients
    def __init__(self, *args, redvypr_device=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        self.device = redvypr_device
        self.layout = QtWidgets.QGridLayout(self)
        self.create_sensorcoefficientWidget_table()

        # Add buttons
        self.apply_button = QtWidgets.QPushButton('Apply')
        self.apply_button.clicked.connect(self.coeff_chosen)
        self.cancel_button = QtWidgets.QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.coeff_cancel)
        self.layout.addWidget(self.sensorCoeffWidget_table, 0, 0,1,2)
        self.layout.addWidget(self.apply_button, 1, 0)
        self.layout.addWidget(self.cancel_button, 1, 1)

    def coeff_chosen(self):
        funcname = __name__ + '.coeff_chosen():'
        logger.debug(funcname)
        row = self.sensorCoeffWidget_table.currentRow()
        item = self.sensorCoeffWidget_table.item(row,0)
        #print('Coeff',item.coeff)
        calibration = item.calibration
        print('Calibration',calibration)
        cal = {'calibration':calibration}

        self.coeff.emit(cal)
        self.close()

    def coeff_cancel(self):
        funcname = __name__ + '.coeff_cancel():'
        logger.debug(funcname)
        self.close()
    def create_sensorcoefficientWidget_table(self):
        """

        """
        funcname = __name__ + '.create_sensorcoefficientWidget_table():'
        logger.debug(funcname)
        self.col_sn = 0
        self.col_model = 1
        self.col_parameter = 2
        self.col_date = 3
        sensorCoeffWidget_table = QtWidgets.QTableWidget()
        sensorCoeffWidget_table.setColumnCount(4)
        columns = ['SN','Model','Parameter','Date']
        sensorCoeffWidget_table.setHorizontalHeaderLabels(columns)
        # Fill the table with sn
        nrows = len(self.device.config.calibrations)
        print('Calibrations', self.device.config.calibrations)
        sensorCoeffWidget_table.setRowCount(nrows)
        row = 0
        for calibration in self.device.config.calibrations:
            sn = calibration.sn
            if True:
                if True:
                    parameter = calibration.parameter
                    td = get_date_from_calibration(calibration, parameter)
                    #date = str(calibration['parameter'][parameter]['date'])
                    date = td.strftime('%Y-%m-%d %H:%M:%S')
                    model = str(calibration.sensor_model)
                    item = QtWidgets.QTableWidgetItem(str(sn))
                    item.calibration = calibration
                    sensorCoeffWidget_table.setItem(row,self.col_sn,item)
                    item = QtWidgets.QTableWidgetItem(str(model))
                    item.calibration = calibration
                    sensorCoeffWidget_table.setItem(row, self.col_model, item)
                    item = QtWidgets.QTableWidgetItem(str(parameter))
                    item.calibration = calibration
                    sensorCoeffWidget_table.setItem(row, self.col_parameter, item)
                    item = QtWidgets.QTableWidgetItem(str(date))
                    item.calibration = calibration
                    sensorCoeffWidget_table.setItem(row, self.col_date, item)
                    row += 1

        self.sensorCoeffWidget_table = sensorCoeffWidget_table
        self.sensorCoeffWidget_table.resizeColumnsToContents()