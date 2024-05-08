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
import numpy
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget
from PyQt5 import QtWidgets, QtCore, QtGui
import redvypr.gui as gui

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('sensorWidgets')
logger.setLevel(logging.DEBUG)


class sensorConfigWidget(QtWidgets.QWidget):
    """
    Widget to configure a sensor
    """

    def __init__(self, *args, sensor, calibrations, redvypr_device=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        self.device = redvypr_device
        self.sensor = sensor
        self.sn = sensor.sn
        self.calibrations = calibrations

        self.configWidget = pydanticConfigWidget(self.sensor, exclude=['parameter'])

        self.parameterWidget = QtWidgets.QWidget(self)
        self.fill_parameter_widgets()

        self.layout = QtWidgets.QGridLayout(self)
        self.layout.addWidget(self.configWidget,0,0)
        self.layout.addWidget(self.parameterWidget,0,1)

    def __assign_calibrations__(self):
        funcname = __name__ + '__assign_calibrations():'
        print(funcname)
        print('calibrations',self.calibrations)
        cals = self.calibrations
        match = ['parameter','sn']

        parameter = self.get_parameter(self.sensor.parameter)
        for i, para_dict in enumerate(parameter):
            para = para_dict['parameter']
            para_parent = para_dict['parent']
            para_name = para_dict['name']
            para_index = para_dict['index']
            print('Searching for calibration for parameter',i)
            print('Para',para_index,para)
            cal_match = []
            cal_match_date = []
            for cal in cals:
                match_all = True
                for m in match:
                    mcal = getattr(cal, m)
                    mpara = getattr(para, m)
                    if mcal != mpara:
                        match_all = False

                if match_all:
                    print('Found matching parameter')
                    print('Cal',cal)
                    cal_match.append(cal)
                    td = datetime.datetime.strptime(cal.date,'%Y-%m-%d %H:%M:%S.%f')
                    cal_match_date.append(td)

            if len(cal_match) > 0:
                imin = numpy.argmin(cal_match)
                print('Assigning matching parameter')
                # Apply calibration to parameter (could also be a function)
                if para_parent.__class__.__base__ == pydantic.BaseModel:
                    print('Setting parameter to:', para_index, cal)
                    setattr(para_parent, para_index, cal)
                elif isinstance(para_parent, list):
                    print('Updating list with calibrations')
                    para_parent[para_index] = cal
                #self.sensor.parameter.NTC_A[i] = cal_match[imin]

        self.__fill_calibration_table__()

    def __create_calibration_widget__(self):
        self.__calbutton_clicked__ = self.sender()
        self.__calwidget__ = sensorCoeffWidget(calibrations=self.calibrations, redvypr_device=self.device)
        self.applyCoeffButton = QtWidgets.QPushButton('Apply')
        self.applyCoeffButton.clicked.connect(self.applyCalibration_clicked)
        self.cancelCoeffButton = QtWidgets.QPushButton('Cancel')
        self.cancelCoeffButton.clicked.connect(self.applyCalibration_clicked)
        self.__calwidget__.sensorCoeffWidget_layout.addWidget(self.applyCoeffButton, 2, 0)
        self.__calwidget__.sensorCoeffWidget_layout.addWidget(self.cancelCoeffButton, 2, 1)

        self.__calwidget__.show()

    def applyCalibration_clicked(self):
        if self.sender() == self.cancelCoeffButton:
            self.sensorCoeffWidget.close()
        else:
            print('Apply')
            user_role = 10
            item = self.__calwidget__.sensorCoeffWidget_list.currentItem()
            if item is not None:
                role = QtCore.Qt.UserRole + user_role
                print('fds', self.__calwidget__.sensorCoeffWidget_list.currentRow(), item.data(role))
                cal = item.data(role)
                print('Cal', cal)
                self.__cal_apply__ = cal # Save the calibration
                #Update the calibration
                iupdate = self.__calbutton_clicked__.__para_index__
                parameter = self.__calbutton_clicked__.__para__
                parameter_dict = self.__calbutton_clicked__.__para_dict__
                para_parent = parameter_dict['parent']
                para_name = parameter_dict['name']
                print('Iupdate', iupdate,'Parameter',parameter)
                print('Parameter dict', parameter_dict)
                # Apply calibration to parameter (could also be a function)
                if para_parent.__class__.__base__ == pydantic.BaseModel:
                    print('Setting parameter to:',para_name, cal)
                    setattr(para_parent,para_name, cal)
                elif isinstance(para_parent, list):
                    print('Updating list with calibrations')
                    para_parent[iupdate] = cal

                parameter = cal
                self.__calwidget__.close()
                self.__fill_calibration_table__()


    def get_parameter(self, parameter):
        def __get_parameter_recursive__(index, parameter, parameter_all):
            for i, ptmp in enumerate(parameter):
                if isinstance(ptmp, list):
                    index_new = index + '[{}]'.format(i)
                    __get_parameter_recursive__(index_new, ptmp, parameter_all)
                # A pydantic parameter object
                elif ptmp.__class__.__base__ == pydantic.BaseModel:
                    if isinstance(parameter, list):
                        name = '{}[{}]'.format(index,i)
                    else:
                        name = str(i)
                    parameter_all.append({'parameter': ptmp, 'name': name,'parent':parameter,'index':i})


        parameter_all = []
        # Parameter should be a pydantic class
        if parameter.__class__.__base__ == pydantic.BaseModel:
            # Loop over all attributes
            for ptmp in parameter:
                par1 = ptmp[0]
                ptmp_child = getattr(parameter, par1)
                if isinstance(ptmp_child, list):
                    __get_parameter_recursive__(par1, ptmp_child, parameter_all)
                # A pydantic parameter object
                elif ptmp_child.__class__.__base__ == pydantic.BaseModel:
                    parameter_all.append({'parameter':ptmp_child,'name':par1,'parent':parameter})


                print('ptmp',ptmp)

        else:
            raise Exception('parameter should be an instance of pydantic.BaseModel')


        return parameter_all
    def __fill_calibration_table__(self):
        funcname = __name__ + '__fill_calibration_table__():'
        logger.debug(funcname)
        self.parameterTable.clear()
        parameter_all = self.get_parameter(self.sensor.parameter)
        print('Parameter all',parameter_all)
        nRows = len(parameter_all)
        nCols = 7
        self.parameterTable.setRowCount(nRows)
        self.parameterTable.setColumnCount(nCols)
        self.parameterTable.setHorizontalHeaderLabels(['Sensor Parameter','Choose calibration','Show calibration','Cal SN','Cal Parameter','Cal Date','Cal Comment'])
        #print('Config parameter',self.config.parameter)

        for i, para_dict in enumerate(parameter_all):
            #print('Para',para)
            para = para_dict['parameter']
            para_parent = para_dict['parent']
            name = para_dict['name']
            # Choose calibration button
            but_choose = QtWidgets.QPushButton('Choose')
            #but.clicked.connect(self.parent().show_coeffwidget_apply)
            but_choose.clicked.connect(self.__create_calibration_widget__)
            but_choose.__para_dict__ = para_dict
            but_choose.__para__ = para
            but_choose.__para_parent__ = para_parent
            but_choose.__para_index__ = i
            # Show calibration button
            but_show = QtWidgets.QPushButton('Show')
            but_show.clicked.connect(self.__show_calibration__)
            # Parameter
            item = QtWidgets.QTableWidgetItem(name)
            self.parameterTable.setItem(i, 0, item)
            self.parameterTable.setCellWidget(i, 1, but_choose)
            self.parameterTable.setCellWidget(i, 2, but_show)
            # SN
            item = QtWidgets.QTableWidgetItem(para.sn)
            self.parameterTable.setItem(i, 1+2, item)
            # Parameter
            item = QtWidgets.QTableWidgetItem(para.parameter)
            self.parameterTable.setItem(i, 2+2, item)
            # Date
            item = QtWidgets.QTableWidgetItem(para.date)
            self.parameterTable.setItem(i, 3+2, item)
            # Comment
            item = QtWidgets.QTableWidgetItem(para.comment)
            self.parameterTable.setItem(i, 4+2, item)

        self.parameterTable.resizeColumnsToContents()

    def __show_calibration__(self):
        print('Showing calibration')
    def fill_parameter_widgets(self):
        funcname = __name__ +'.fill_parameter_widgets():'
        self.parameterLayout = QtWidgets.QGridLayout(self.parameterWidget)
        self.parameterAuto = QtWidgets.QPushButton('Autofill calibrations')
        self.parameterAuto.clicked.connect(self.__assign_calibrations__)
        self.parameterTable = QtWidgets.QTableWidget()

        self.auto_check_sn = QtWidgets.QCheckBox('SN')
        self.auto_check_sn.setEnabled(False)
        self.auto_check_sn_edit = QtWidgets.QLineEdit()
        self.auto_check_sn_edit.setText(self.sn)
        self.auto_check_sn_edit.setEnabled(False)
        self.parameterLayout.addWidget(self.parameterAuto, 0, 0, 1 , 2)
        self.parameterLayout.addWidget(self.auto_check_sn, 1, 0)
        self.parameterLayout.addWidget(self.auto_check_sn_edit, 1, 1)
        self.parameterLayout.addWidget(self.parameterTable, 2, 0, 1, 2)
        self.__fill_calibration_table__()


class sensorCoeffWidget(QtWidgets.QWidget):
    """
    Widget to choose/load/remove new calibrations from files
    """

    def __init__(self, *args, calibrations, redvypr_device=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        layout = QtWidgets.QVBoxLayout(self)
        self.calibrations = calibrations
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

        for cal in self.calibrations:
            print('Cal', cal)
            sns.append(cal.sn)

        self.sensorCoeffWidget_list.setRowCount(len(self.calibrations) + 1)
        for i, cal in enumerate(self.calibrations):
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

