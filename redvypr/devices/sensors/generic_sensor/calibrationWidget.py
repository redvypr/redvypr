import datetime
import numpy as np
import logging
import sys
import os
import threading
import copy
import yaml
import json
import typing
import pydantic
import numpy
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget
from PyQt6 import QtWidgets, QtCore, QtGui
import redvypr.gui as gui
from pathlib import Path

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('calibrationWidget')
logger.setLevel(logging.DEBUG)


class CalibrationsWidget(QtWidgets.QWidget):
    """
    Widget to configure a sensor
    """
    config_changed_flag = QtCore.pyqtSignal()  # Signal notifying that the configuration has changed
    def __init__(self, *args, sensor, calibrations, redvypr_device=None, calibration_models=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        self.datefmt = '%Y-%m-%d %H:%M:%S'
        self.device = redvypr_device
        self.sensor = sensor
        self.sn = sensor.sn
        self.calibrations = calibrations
        self.calibration_models = calibration_models
        self.configWidget = pydanticConfigWidget(self.sensor, exclude=['parameter'])

        self.parameterWidget = QtWidgets.QWidget(self)
        self.fill_parameter_widgets()

        self.combinedWidget = QtWidgets.QWidget()
        self.combinedWidget_layout = QtWidgets.QHBoxLayout(self.combinedWidget)

        self.combinedWidget_layout.addWidget(self.configWidget,1)
        self.combinedWidget_layout.addWidget(self.parameterWidget,2)
        self.layout = QtWidgets.QGridLayout(self)
        self.layout.addWidget(self.combinedWidget, 0, 0, 1, 2)
        #self.layout.addWidget(self.configWidget, 0, 0)
        #self.layout.addWidget(self.parameterWidget,0,1)

    def __assign_calibrations__(self):
        funcname = __name__ + '__assign_calibrations():'
        print('Find calibration for sensor',self.sensor)
        match_dict = {}
        match_dict = {'parameter': None, 'sn': None}
        match_dict['date_sort'] = self.auto_check_date_combo_oldest.currentText()
        if self.auto_check_sn.isChecked():
            sn_calibration = self.auto_check_sn_edit.text()
            match_dict['sn'] = sn_calibration

        if self.auto_check_date.isChecked():
            datetmp = self.auto_check_date_edit.dateTime()
            date = datetmp.toPyDateTime()
            print('datetmp',datetmp,type(datetmp))
            match_dict['date'] = date

        if self.auto_check_id.isChecked():
            calibration_id = self.auto_check_id_edit.text()
            match_dict['calibration_id'] = calibration_id
        else:
            match_dict['calibration_id'] = None

        self.device.find_calibrations_for_sensor(self.sensor, match_dict)
        self.__fill_calibration_table__()
        print('Done assigning')
    def __create_calibration_widget__(self):
        self.__calbutton_clicked__ = self.sender()
        self.__calwidget__ = sensorCoeffWidget(calibrations=self.calibrations, redvypr_device=self.device, calibration_models=self.calibration_models)
        self.applyCoeffButton = QtWidgets.QPushButton('Apply')
        self.applyCoeffButton.clicked.connect(self.applyCalibration_clicked)
        self.cancelCoeffButton = QtWidgets.QPushButton('Cancel')
        self.cancelCoeffButton.clicked.connect(self.applyCalibration_clicked)
        self.__calwidget__.sensorCoeffWidget_layout.addWidget(self.applyCoeffButton, 4, 0)
        self.__calwidget__.sensorCoeffWidget_layout.addWidget(self.cancelCoeffButton, 4, 1)

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
        """
        Gets all parameter from the sensor
        :param parameter:
        :return:
        """
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

        else:
            raise Exception('parameter should be an instance of pydantic.BaseModel')


        return parameter_all
    def __fill_calibration_table__(self):
        funcname = __name__ + '__fill_calibration_table__():'
        logger.debug(funcname)
        self.parameterTable.clear()
        parameter_all = self.get_parameter(self.sensor.parameter)
        #print('Parameter all',parameter_all)
        nRows = len(parameter_all)
        nCols = 8
        self.parameterTable.setRowCount(nRows)
        self.parameterTable.setColumnCount(nCols)
        self.parameterTable.setHorizontalHeaderLabels(['Sensor Parameter','Calibration Type','Choose calibration','Show calibration','Cal SN','Cal Parameter','Cal Date','Cal Comment'])
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
            # Calibration type
            item_type = QtWidgets.QTableWidgetItem(para.calibration_type)
            self.parameterTable.setItem(i, 1, item_type)
            self.parameterTable.setCellWidget(i, 1+1, but_choose)
            self.parameterTable.setCellWidget(i, 2+1, but_show)
            # SN
            item = QtWidgets.QTableWidgetItem(para.sn)
            self.parameterTable.setItem(i, 1+2+1, item)
            # Parameter
            item = QtWidgets.QTableWidgetItem(para.parameter)
            self.parameterTable.setItem(i, 2+2+1, item)
            # Date
            datestr = para.date.strftime(self.datefmt)
            item = QtWidgets.QTableWidgetItem(datestr)
            self.parameterTable.setItem(i, 3+2+1, item)
            # Comment
            item = QtWidgets.QTableWidgetItem(para.comment)
            self.parameterTable.setItem(i, 4+2+1, item)

        self.parameterTable.resizeColumnsToContents()

    def __show_calibration__(self):
        funcname = __name__ + '.show_calibration():'
        logger.debug(funcname)
    def fill_parameter_widgets(self):
        funcname = __name__ +'.fill_parameter_widgets():'
        self.parameterLayout = QtWidgets.QGridLayout(self.parameterWidget)
        self.parameterAuto = QtWidgets.QPushButton('Assign calibration')
        self.parameterAuto.clicked.connect(self.__assign_calibrations__)
        self.parameterTable = QtWidgets.QTableWidget()

        self.auto_check_sn = QtWidgets.QCheckBox('SN')
        self.auto_check_sn.setEnabled(False)
        #self.auto_check_sn.setChecked(True)
        self.auto_check_sn_edit = QtWidgets.QLineEdit()
        self.auto_check_sn_edit.setText(self.sn)
        #self.auto_check_sn_edit.setEnabled(False)

        self.auto_check_date = QtWidgets.QCheckBox('Date')
        #self.auto_check_date.setEnabled(False)
        self.auto_check_date.setChecked(True)
        t0 = QtCore.QDateTime(1970,1,1,0,0,0)
        self.auto_check_date_edit = QtWidgets.QDateTimeEdit(t0)
        self.auto_check_date_edit.setDisplayFormat("yyyy-MM-dd HH:MM:ss")
        #self.auto_check_date_edit = QtWidgets.QLineEdit()
        #self.auto_check_date_edit.setText('1970-01-01 00:00:00')
        #self.auto_check_date_edit.setEnabled(False)
        self.auto_check_date_combo_oldest = QtWidgets.QComboBox()
        self.auto_check_date_combo_oldest.addItem('newest')
        self.auto_check_date_combo_oldest.addItem('oldest')

        self.auto_check_id = QtWidgets.QCheckBox('Calibration id')
        #self.auto_check_id.setEnabled(False)
        self.auto_check_id.setChecked(True)
        self.auto_check_id_edit = QtWidgets.QLineEdit()
        self.auto_check_id_edit.setText('')
        #self.auto_check_id_edit.setEnabled(False)

        self.parameterLayout.addWidget(self.parameterAuto, 0, 0, 1 , 3)
        self.parameterLayout.addWidget(self.auto_check_sn, 1, 0)
        self.parameterLayout.addWidget(self.auto_check_sn_edit, 1, 1)
        self.parameterLayout.addWidget(self.auto_check_date, 2, 0)
        self.parameterLayout.addWidget(self.auto_check_date_edit, 2, 1)
        self.parameterLayout.addWidget(self.auto_check_date_combo_oldest, 2, 2)
        self.parameterLayout.addWidget(self.auto_check_id, 3, 0)
        self.parameterLayout.addWidget(self.auto_check_id_edit, 3, 1)
        self.parameterLayout.addWidget(self.parameterTable, 4, 0, 1, 3)
        self.__fill_calibration_table__()


class sensorCalibrationsWidget(QtWidgets.QWidget):
    """
    Widget to choose/load/remove new calibrations from files
    """
    config_changed_flag = QtCore.pyqtSignal()  # Signal notifying that the configuration has changed
    def __init__(self, *args, calibrations, redvypr_device=None, calibration_models=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        self.datefmt = '%Y-%m-%d %H:%M:%S'
        logger.debug(funcname)
        layout = QtWidgets.QVBoxLayout(self)
        self.calibrations = calibrations
        #if calibration_models is None and redvypr_device is not None:
        #    calhints = typing.get_type_hints(redvypr_device.config)['calibrations']
        #    calibration_models = typing.get_args(typing.get_args(calhints)[0])
        print('Hallo hallo hallo')
        print('Calibration models',calibration_models)
        print('Hallo hallo hallo')
        self.calibration_models = calibration_models
        self.device = redvypr_device
        self.sensorCoeffWidget = QtWidgets.QWidget()
        layout.addWidget(self.sensorCoeffWidget)
        #self.sensorCoeffWidget.setWindowIcon(QtGui.QIcon(_icon_file))
        # self.sensorCoeffWidget.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.WindowStaysOnTopHint)
        self.sensorCoeffWidget_layout = QtWidgets.QGridLayout(self.sensorCoeffWidget)
        self.sensorCoeffWidget_list = QtWidgets.QTableWidget()


        # self.sensorCoeffWidget_list.currentRowChanged.connect(self.sensorcoefficient_changed)

        self.__sensorCoeffWidget_list_populate__()

        self.loadCoeffSubFolder = QtWidgets.QCheckBox('Load all calibrations in folder and subfolders')
        self.loadCoeffSubFolder.setChecked(True)
        self.editCoeff = QtWidgets.QCheckBox('Edit calibrations')
        self.editCoeff.setChecked(True)
        self.loadCoeffButton = QtWidgets.QPushButton('Load coefficients')
        self.loadCoeffButton.clicked.connect(self.chooseCalibrationFiles)
        self.saveCoeffButton = QtWidgets.QPushButton('Save coefficients')
        self.saveCoeffButton.setEnabled(False)
        self.addCoeffButton = QtWidgets.QPushButton('Add coefficient')
        if calibration_models is None:
            self.addCoeffButton.setEnabled(False)
        else:
            self.addCoeffButton.clicked.connect(self.__add_calibration__)
        #self.filterCoeffButton = QtWidgets.QPushButton('Filter coefficient')
        #self.filterCoeffButton.setEnabled(False)
        self.remCoeffButton = QtWidgets.QPushButton('Remove coefficients')
        self.remCoeffButton.clicked.connect(self.remCalibration_clicked)

        # self.calibrationConfigWidget = gui.configWidget(self.device.calibration, editable=False)
        self.calibrationConfigWidget = QtWidgets.QWidget()
        self.calibrationConfigWidget_layout = QtWidgets.QVBoxLayout(self.calibrationConfigWidget)
        self.sensorCoeffWidget_layout.addWidget(self.sensorCoeffWidget_list, 0, 0)
        self.sensorCoeffWidget_layout.addWidget(self.calibrationConfigWidget, 0, 1)
        self.sensorCoeffWidget_layout.addWidget(self.loadCoeffButton, 1, 0)
        self.sensorCoeffWidget_layout.addWidget(self.saveCoeffButton, 1, 1)
        self.sensorCoeffWidget_layout.addWidget(self.addCoeffButton, 2, 0)
        self.sensorCoeffWidget_layout.addWidget(self.remCoeffButton, 2, 1)
        self.sensorCoeffWidget_layout.addWidget(self.loadCoeffSubFolder, 3, 0)
        self.sensorCoeffWidget_layout.addWidget(self.editCoeff, 3, 1)


    def __add_calibration__(self):
        """
        Opens a widget that allows to add a user defined calibration
        """
        funcname = __name__ + '.__add_calibration__():'
        logger.debug(funcname)
        # Create an add calibration widget
        self.addCalibrationWidget = QtWidgets.QWidget()
        self.addCalibrationWidget_layout = QtWidgets.QGridLayout(self.addCalibrationWidget)
        self.calibrationModelCombo = QtWidgets.QComboBox()
        for cal in self.calibration_models:
            c = cal()
            caltype = c.calibration_type
            self.calibrationModelCombo.addItem(caltype)

        self.calibrationModelCombo.currentIndexChanged.connect(self.__add_calibration_type_changed__)
        self.addCalibrationApply = QtWidgets.QPushButton('Apply')
        self.addCalibrationApply.clicked.connect(self.__addCalibrationClicked__)
        self.addCalibrationWidget_layout.addWidget(QtWidgets.QLabel('Calibration type'), 0, 0)
        self.addCalibrationWidget_layout.addWidget(self.calibrationModelCombo, 0, 1)
        self.addCalibrationWidget_layout.addWidget(self.addCalibrationApply, 2, 0,1,2)
        self.addCalibrationWidget.show()

        self.__add_calibration_type_changed__(0)

    def __addCalibrationClicked__(self):
        print('Add clicked')
        self.addCalibrationWidget.close()
        print('Calibration',self.__cal_new_tmp__)
        self.device.add_calibration(self.__cal_new_tmp__)
        # Redraw the list
        self.__sensorCoeffWidget_list_populate__()

    def __add_calibration_type_changed__(self, calibration_index):
        """
        Function is called when a calibration_model is changed
        """
        calmodel = self.calibration_models[calibration_index]
        cal = calmodel()
        self.__cal_new_tmp__ = cal
        #print('Index',calibration_index)
        try:
            #self.__add_coefficient_calConfigWidget_tmp__.delete_later()
            self.__add_coefficient_calConfigWidget_tmp__.setParent(None)
        except:
            pass
        self.__add_coefficient_calConfigWidget_tmp__ = gui.pydanticConfigWidget(cal, config_location='right')
        self.__add_coefficient_calConfigWidget_tmp__.config_changed_flag.connect(self.__config_changed__)
        self.addCalibrationWidget_layout.addWidget(self.__add_coefficient_calConfigWidget_tmp__,1,0,1,2)

        # does not work yet
        #width1 = self.self.__add_coefficient_calConfigWidget_tmp__.horizontalScrollBar().sizeHint().width()
        #width0 = self.sensorCoeffWidget_list.horizontalScrollBar().sizeHint().width()
        #self.resize(width0 + width1, self.sensorCoeffWidget_list.sizeHint().height())
    def __config_changed__(self):
        self.config_changed_flag.emit()

    def chooseCalibrationFiles(self):
        """

        """
        funcname = __name__ + '.chooseCalibrationFiles():'
        logger.debug(funcname)
        # fileName = QtWidgets.QFileDialog.getLoadFileName(self, 'Load Calibration', '',
        #                                                 "Yaml Files (*.yaml);;All Files (*)")

        if self.loadCoeffSubFolder.isChecked():
            fileNames = QtWidgets.QFileDialog.getExistingDirectory(self)
            fileNames = ([fileNames],None)
        else:
            fileNames = QtWidgets.QFileDialog.getOpenFileNames(self, 'Load Calibration', '',
                                                               "Yaml Files (*.yaml);;All Files (*)")

        #print('Filenames',fileNames)
        for fileName in fileNames[0]:
            # self.device.read_calibration_file(fileName)
            #print('Adding file ...', fileName)
            if os.path.isdir(fileName):
                #print('Path',Path(fileName))
                coefffiles = list(Path(fileName).rglob("*.[yY][aA][mM][lL]"))
                #print('Coeffiles',coefffiles)
                for coefffile in coefffiles:
                    self.device.add_calibration_file(str(coefffile))
            else:
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

                if self.editCoeff.isChecked():
                    self.__calConfigWidget_tmp__ = gui.pydanticConfigWidget(cal)
                    # If the calibration was edited, update the list
                    self.__calConfigWidget_tmp__.config_changed_flag.connect(self.__configEdited__)
                else:
                    self.__calConfigWidget_tmp__ = gui.pydanticQTreeWidget(cal, dataname=cal.sn + '/' + cal.parameter,
                    show_datatype=False)

                self.__calConfigWidget_tmp__.cal = cal
                self.calibrationConfigWidget_layout.addWidget(self.__calConfigWidget_tmp__)

    def __configEdited__(self):
        funcname = __name__ + '.__configEdited__():'
        print(funcname)
        # Update the list of calibrations
        self.__sensorCoeffWidget_list_populate__()

    def __sensorCoeffWidget_list_populate__(self):
        try:
            self.sensorCoeffWidget_list.itemChanged.disconnect(self.__sensorCoeffWidget_list_item_changed__)
        except:
            pass

        self.sensorCoeffWidget_list.setSortingEnabled(False)
        colheaders = ['SN', 'Calibration type', 'Parameter', 'Calibration date']
        icol_sn = colheaders.index('SN')
        icol_para = colheaders.index('Parameter')
        icol_date = colheaders.index('Calibration date')
        icol_caltype = colheaders.index('Calibration type')
        self.sensorCoeffWidget_list.setColumnCount(len(colheaders))
        self.sensorCoeffWidget_list.setHorizontalHeaderLabels(colheaders)

        # Fill the list with sn
        sns = []  # Get all serialnumbers

        for cal in self.calibrations:
            print('Cal', cal)
            sns.append(cal.sn)

        self.sensorCoeffWidget_list.setRowCount(len(self.calibrations))
        for i, cal in enumerate(self.calibrations):
            # SN
            item = QtWidgets.QTableWidgetItem(cal.sn)
            user_role = 10
            role = QtCore.Qt.UserRole + user_role
            item.setData(role, cal)
            self.sensorCoeffWidget_list.setItem(i, icol_sn, item)
            # Calibration type
            item = QtWidgets.QTableWidgetItem(cal.calibration_type)
            item.setData(role, cal)
            self.sensorCoeffWidget_list.setItem(i, icol_caltype, item)
            # Parameter
            icol_caltype = colheaders.index('Calibration type')
            # Distinguish between RedvyprAddress and str
            try:
                parameter_str = cal.parameter.address_str
            except:
                parameter_str = cal.parameter

            item = QtWidgets.QTableWidgetItem(parameter_str)
            item.setData(role, cal)
            self.sensorCoeffWidget_list.setItem(i, icol_para, item)
            # Caldate
            datestr = cal.date.strftime(self.datefmt)
            item = QtWidgets.QTableWidgetItem(datestr)
            item.setData(role, cal)
            self.sensorCoeffWidget_list.setItem(i, icol_date, item)

        self.sensorCoeffWidget_list.resizeColumnsToContents()
        self.sensorCoeffWidget_list.currentCellChanged.connect(self.__sensorCoeffWidget_list_item_changed__)
        self.sensorCoeffWidget_list.setSortingEnabled(True)

    def remCalibration_clicked(self):
        funcname = __name__ + '.remCalibration_clicked()'
        logger.debug(funcname)

        try:
            self.__calConfigWidget_tmp__.close()
        except:
            pass

        rows = []
        for i in self.sensorCoeffWidget_list.selectionModel().selection().indexes():
            row, column = i.row(), i.column()
            rows.append(row)

        rows = list(set(rows))
        rows.sort(reverse=True)
        for index in rows:
            calibration = self.device.custom_config.calibrations.pop(index)
            logger.debug('Removed {}'.format(calibration))

        self.__sensorCoeffWidget_list_populate__()


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
                calibrations = {'calibrations': self.device.custom_config['calibrations'][sn]}
                self.calibrationConfigWidget = gui.configWidget(calibrations, editable=False,
                                                                configname='Coefficients of {:s}'.format(sn))
                self.sensorCoeffWidget_layout.addWidget(self.calibrationConfigWidget, 0, 1)
                # self.sensorstack.setCurrentIndex(index)
            else:
                try:
                    self.calibrationConfigWidget.close()
                except:
                    pass

