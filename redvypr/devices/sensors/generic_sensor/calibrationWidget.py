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
import qtawesome

import redvypr.devices.sensors.calibration.calibration_models
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget
from PyQt6 import QtWidgets, QtCore, QtGui
import redvypr.gui as gui
from pathlib import Path

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.calibrationWidget')
logger.setLevel(logging.DEBUG)



class CalibrationsSaveWidget(QtWidgets.QTableWidget):
    def __init__(self, *args, calibrations=None):
        funcname = __name__ + '__init__()'
        super().__init__(*args)
        if isinstance(calibrations,list):
            logger.debug(funcname + 'Changing calibrations to CalibrationList')
            calibrations = redvypr.devices.sensors.calibration.calibration_models.CalibrationList(calibrations)

        self.calibrations = calibrations
        self.layout = QtWidgets.QGridLayout(self)
        self.check_sensor = QtWidgets.QWidget()
        self.check_sensor_layout = QtWidgets.QHBoxLayout(self.check_sensor)
        self.file_format_checkboxes = {}
        file_format_check = {'sn':'Serial Number', 'date':'Date', 'sensor_model':'Sensor model', 'calibration_id': 'Calibration Id', 'calibration_uuid':'Calibration UUID', 'calibration_type':'Calibration type'}
        for format_check in file_format_check:
            self.file_format_checkboxes[format_check] = QtWidgets.QCheckBox(file_format_check[format_check])
            self.file_format_checkboxes[format_check].stateChanged.connect(self.__update_filename__)
            self.check_sensor_layout.addWidget(self.file_format_checkboxes[format_check])
        self.filename_edit = QtWidgets.QLineEdit()
        self.filename_edit.editingFinished.connect(self.__filename_text_changed__)
        iconname = "fa5.folder-open"
        folder_icon = qtawesome.icon(iconname)
        self.filename_button = QtWidgets.QPushButton()
        self.filename_button.setIcon(folder_icon)
        #self.filename_button.textChanged.connect(self.__filename_text_changed__)
        self.filename_button.clicked.connect(self.__get_filename_clicked__)
        #self.filename_choose = QtWidgets.QLineEdit()
        self.filename_widget = QtWidgets.QWidget()
        self.filename_widget_layout = QtWidgets.QHBoxLayout(self.filename_widget)

        # Save buttons
        self.save_button = QtWidgets.QPushButton('Save')
        self.save_button.clicked.connect(self.__save_clicked__)
        self.show_save_button = QtWidgets.QPushButton('Show files to write')
        self.show_save_button.clicked.connect(self.__save_clicked__)
        self.result_text = QtWidgets.QPlainTextEdit()

        self.filename_widget_layout.addWidget(self.filename_edit)
        self.filename_widget_layout.addWidget(self.filename_button)

        self.filename = 'calib_'

        self.layout.addWidget(self.check_sensor, 0, 0)
        self.layout.addWidget(self.filename_widget, 1, 0)
        self.layout.addWidget(self.result_text, 2, 0)
        self.layout.addWidget(self.show_save_button, 3, 0)
        self.layout.addWidget(self.save_button, 4, 0)

    def __filename_text_changed__(self):
        self.filename = self.filename_edit.text()
        print('Editing finished', self.filename)

    def __get_filename_clicked__(self):
        funcname = __name__ + '.__filename_clicked__()'
        if True:
            fileName = QtWidgets.QFileDialog.getSaveFileName(self, 'Save Calibration', '',
                                                             "Yaml Files (*.yaml);;All Files (*)")
        if fileName:
            self.filename = fileName[0]
            self.filename_edit.setText(self.filename)
            self.__update_filename__()

    def __update_filename__(self):
        # Check which fileformats should be added
        self.filename = self.filename_edit.text()
        filename = self.filename
        filename_base = os.path.splitext(filename)[0]
        filename_ext = os.path.splitext(filename)[1]
        for file_format in self.file_format_checkboxes:
            checkbox = self.file_format_checkboxes[file_format]
            format_str = '_{' + file_format + '}'
            if checkbox.isChecked():
                if format_str not in filename_base:
                    filename_base += format_str
            else:
                filename_base = filename_base.replace(format_str,'')

        self.filename = filename_base + filename_ext
        self.filename_edit.setText(self.filename)

    def __save_clicked__(self):
        funcname = __name__ + '.__filename_clicked__()'

        if self.sender() == self.show_save_button:
            write_file = False
        elif self.sender() == self.save_button:
            write_file = True
        else: # shouldnt happen
            write_file = None

        if True:
            logger.debug(funcname + ' Saving to file {}'.format(self.filename))
            filegrouping = ('sn', 'caldate')
            filegrouping = ('sn', 'calibration_uuid', 'calibration_type')
            fileinfo = self.calibrations.save(self.filename, write_file=write_file)
            # Show results in text window
            self.result_text.clear()
            fileinfostr = 'Filenames:\n'
            self.result_text.appendPlainText(fileinfostr)
            for filename_save in fileinfo.keys():
                nfiles = len(fileinfo[filename_save])
                fileinfostr = str(filename_save) + ':{} calibrations'.format(nfiles)
                self.result_text.appendPlainText(fileinfostr)

            if write_file:
                fileinfostr = 'written to disk\n'
            else:
                fileinfostr = 'info only (not written to disk)\n'
            self.result_text.appendPlainText(fileinfostr)

class CalibrationsTable(QtWidgets.QTableWidget):
    """
    Table that is designed to show calibrations. Calibrations can be either a dictionary or a list.
    """
    def __init__(self, *args, calibrations=None, show_columns=None, hide_columns=None, **kwargs):
        funcname = __name__ + '__init__()'
        super().__init__(*args)
        self.datefmt = '%Y-%m-%d %H:%M:%S'
        self.calibrations = calibrations
        self.show_columns = show_columns
        if hide_columns is None:
            hide_columns = ['show']
        else:
            hide_columns.append('show')
        self.hide_columns = hide_columns

        self.columns = {'datastream':0}
        self.columns['caltype'] = 1
        self.columns['choose'] = 2
        self.columns['show'] = 3
        self.columns['sn'] = 4
        self.columns['parameter'] = 5
        self.columns['date'] = 6
        self.columns['id'] = 7
        self.columns['uuid'] = 8
        self.columns['comment'] = 9
        self.columns['coeffs'] = 10

        self.column_names = {'datastream': 'Sensor Parameter'}
        self.column_names['caltype'] = 'Calibration Type'
        self.column_names['choose'] = 'Choose Calibration'
        self.column_names['show'] = 'Show Calibration'
        self.column_names['sn'] = 'Serial number'
        self.column_names['parameter'] = 'Parameter'
        self.column_names['date'] = 'Calibration Date'
        self.column_names['id'] = 'Calibration ID'
        self.column_names['uuid'] = 'Calibration UUID'
        self.column_names['comment'] = 'Comment'
        self.column_names['coeffs'] = 'Coefficients'

        self.header_labels = []
        for lab in self.column_names.keys():
            self.header_labels.append(self.column_names[lab])

        self.nCols = len(self.columns.keys())

        # Populate the table
        self.update_table()

    def get_selected_calibrations(self):
        """

        Returns
        -------
        List of calibrations of selected rows
        """
        funcname = __name__ + 'get_calibrations():'
        calibrations = []
        table = self
        if table.selectionModel().selection().indexes():
            for i in table.selectionModel().selection().indexes():
                row, column = i.row(), i.column()
                caltmp = self.__calibrations_list__[row]
                calibrations.append(caltmp)

        return calibrations

    def update_table(self, calibrations=None):
        """
        updates the table, either with own calibrations or with given calibrations
        calibrations as argument will replace self.calibrations
        Parameters
        ----------
        calibrations: List of calibrations

        Returns
        -------

        """
        funcname = __name__ + 'update_table():'
        logger.debug(funcname)
        if calibrations is not None:
            self.calibrations = calibrations
        self.clear()
        nRows = len(self.calibrations)

        if isinstance(self.calibrations, list):
            logger.debug('Will not show the parameter')
            self.hideColumn(self.columns['datastream'])

        self.setRowCount(nRows)
        self.setColumnCount(self.nCols)
        self.setHorizontalHeaderLabels(self.header_labels)

        self.__calibrations_list__ = []
        #print('Calibrations',self.calibrations)
        for i, cal_key in enumerate(self.calibrations):
            if isinstance(self.calibrations,dict):
                calibration = self.calibrations[cal_key]
                #print('calibration dict', i, cal_key)
                datastreamstr = str(cal_key)
            elif isinstance(self.calibrations, list):
                calibration = cal_key
                #print('calibration list', i )
                datastreamstr = None
            else:
                calibration = None

            if True:
                # Create an extra list with the calibrations
                self.__calibrations_list__.append(calibration)
                # Choose calibration button
                but_choose = QtWidgets.QPushButton('Choose')
                #but_choose.clicked.connect(self.__create_calibration_widget__)
                but_choose.__calibration__ = calibration
                but_choose.__calibration_index__ = i
                but_choose.__calibration_key__ = cal_key
                # Show calibration button
                but_show = QtWidgets.QPushButton('Show')
                #but_show.clicked.connect(self.__show_calibration__)
                self.setCellWidget(i, self.columns['choose'], but_choose)
                self.setCellWidget(i, self.columns['show'], but_show)
                # Datastream
                item = QtWidgets.QTableWidgetItem(datastreamstr)
                self.setItem(i, self.columns['datastream'], item)
            if calibration is not None:
                #print('Calibration', calibration)
                # Calibration type
                item_type = QtWidgets.QTableWidgetItem(calibration.calibration_type)
                self.setItem(i, self.columns['caltype'], item_type)
                # SN
                item = QtWidgets.QTableWidgetItem(calibration.sn)
                self.setItem(i, self.columns['sn'], item)
                # Parameter
                parameterstr = str(calibration.parameter)
                item = QtWidgets.QTableWidgetItem(parameterstr)
                self.setItem(i, self.columns['parameter'], item)
                # Date
                datestr = calibration.date.strftime(self.datefmt)
                item = QtWidgets.QTableWidgetItem(datestr)
                self.setItem(i, self.columns['date'], item)
                # Calibration ID
                item = QtWidgets.QTableWidgetItem(calibration.calibration_id)
                self.setItem(i, self.columns['id'], item)
                # Calibration UUID
                item = QtWidgets.QTableWidgetItem(calibration.calibration_uuid)
                self.setItem(i, self.columns['uuid'], item)
                # Comment
                item = QtWidgets.QTableWidgetItem(calibration.comment)
                self.setItem(i, self.columns['comment'], item)
                # Coefficients
                coeffstr = str(calibration.coeff)
                item = QtWidgets.QTableWidgetItem(coeffstr)
                self.setItem(i, self.columns['coeffs'], item)


        # Hide columns
        #print('Hiding columns',self.hide_columns)
        if self.hide_columns is not None:
            if 'show' not in self.hide_columns:
                self.hide_columns.append('show')
            for col in self.hide_columns:
                logger.debug('Will hide column {}'.format(col))
                colhide = self.columns[col]
                #print('Colhide',colhide)
                self.hideColumn(colhide)

        self.resizeColumnsToContents()

class GenericSensorCalibrationWidget(QtWidgets.QWidget):
    """
    Widget to display the calibrations of a sensor and to let the user choose different calibrations.
    """
    config_changed_flag = QtCore.pyqtSignal()  # Signal notifying that the configuration has changed
    def __init__(self, *args, calibrations_all=None, redvypr_device=None, calibration_models=None, calibrations_sensor={'Calibrations':[], 'Raw Calibrations':[]},calibrations_sensor_options={'Calibrations':None, 'Raw Calibrations':None}):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        self.calibration_files = []
        self.calfiles_processed = []
        self.datefmt = '%Y-%m-%d %H:%M:%S'
        self.device = redvypr_device
        #self.sn = sensor.sn
        # Take care of the calibration list
        if calibrations_all is None:
            self.calibrations = redvypr.devices.sensors.calibration.calibration_models.CalibrationList()
        else:
            self.calibrations = redvypr.devices.sensors.calibration.calibration_models.CalibrationList(calibrations_all)
        if calibration_models is None:
            calibration_models = redvypr.devices.sensors.calibration.calibration_models.calibration_models

        self.calibration_models = calibration_models

        # Sensor generic config widget to load, save sensor config
        self.configWidget = QtWidgets.QWidget()
        self.configWidget_layout = QtWidgets.QGridLayout(self.configWidget)

        # Create calibrationstables
        self.calibrationsTable = {}
        self.calibrationsTableWidgets = {}
        self.calibrationsTableAutoCalButtons = {}
        self.calibrationsTableWidgets_layout = {}
        for calibtablename in calibrations_sensor.keys():
            self.calibrationsTableWidgets[calibtablename] = QtWidgets.QWidget()
            self.calibrationsTableWidgets_layout[calibtablename] = QtWidgets.QVBoxLayout(self.calibrationsTableWidgets[calibtablename])
            # Get some options
            try:
                editable = calibrations_sensor_options[calibtablename]['editable']
            except:
                editable = False


            if editable == False:
                hide_columns = ['choose']
            else:
                # Add autofindbutton
                autofindcal_button = QtWidgets.QPushButton('Find calibration')
                autofindcal_button.clicked.connect(self.find_calibrations)
                autofindcal_button.calibtablename = calibtablename
                self.calibrationsTableAutoCalButtons[calibtablename] = autofindcal_button
                self.calibrationsTableWidgets_layout[calibtablename].addWidget(autofindcal_button)
                hide_columns = []

            calibrations_tmp = calibrations_sensor[calibtablename]
            self.calibrationsTable[calibtablename] = CalibrationsTable(calibrations=calibrations_tmp, hide_columns=hide_columns)
            self.calibrationsTableWidgets_layout[calibtablename].addWidget(self.calibrationsTable[calibtablename])

        self.calibrations_allTable = CalibrationsTable(calibrations=self.calibrations)

        # All calibrations widget
        self.loadCalibrationsfSubFolder = QtWidgets.QCheckBox('Load all calibrations in folder and subfolders')
        self.loadCalibrationsfSubFolder.setChecked(True)
        self.editCalibrations = QtWidgets.QCheckBox('Edit calibrations')
        self.editCalibrations.setChecked(True)
        self.loadCalibrationButton = QtWidgets.QPushButton('Load Calibration(s)')
        self.loadCalibrationButton.clicked.connect(self.chooseCalibrationFiles)
        self.saveCalibrationsButton = QtWidgets.QPushButton('Save Calibration(s)')
        self.saveCalibrationsButton.setEnabled(True)
        self.saveCalibrationsButton.clicked.connect(self.__save_calibration__)
        self.addCalibButton = QtWidgets.QPushButton('Create Calibration')
        if calibration_models is None:
            self.addCalibButton.setEnabled(False)
        else:
            self.addCalibButton.clicked.connect(self.__add_calibration__)
        # self.filterCoeffButton = QtWidgets.QPushButton('Filter coefficient')
        # self.filterCoeffButton.setEnabled(False)
        self.remCalibButton = QtWidgets.QPushButton('Remove Calibration(s)')
        self.remCalibButton.clicked.connect(self.remCalibration_clicked)

        # self.calibrationConfigWidget = gui.configWidget(self.device.calibration, editable=False)
        self.calibrations_allWidget = QtWidgets.QWidget()
        self.calibrations_allLayout = QtWidgets.QGridLayout(self.calibrations_allWidget)
        self.calibrations_allLayout.addWidget(self.calibrations_allTable, 0, 0)
        self.calibrations_allLayout.addWidget(self.loadCalibrationButton, 1, 0)
        self.calibrations_allLayout.addWidget(self.saveCalibrationsButton, 1, 1)
        self.calibrations_allLayout.addWidget(self.addCalibButton, 2, 0)
        self.calibrations_allLayout.addWidget(self.remCalibButton, 2, 1)
        self.calibrations_allLayout.addWidget(self.loadCalibrationsfSubFolder, 3, 0)
        self.calibrations_allLayout.addWidget(self.editCalibrations, 3, 1)

        # Calibrations tab
        self.calibrationsTab = QtWidgets.QTabWidget(self)
        for calibtablename in self.calibrationsTable:
            self.calibrationsTab.addTab(self.calibrationsTableWidgets[calibtablename], calibtablename)

        self.calibrationsTab.addTab(self.calibrations_allWidget, 'All Calibrations')
        self.layout = QtWidgets.QGridLayout(self)
        self.layout.addWidget(self.calibrationsTab, 0, 0)
        #self.layout.addWidget(self.configWidget, 0, 0)
        #self.layout.addWidget(self.parameterWidget,0,1)

    def remCalibration_clicked(self):
        funcname = __name__ + '.remCalibration_clicked():'
        logger.debug(funcname)
        calibrations_remove = self.calibrations_allTable.get_selected_calibrations()
        for i,cal in enumerate(calibrations_remove):
            logger.debug(funcname + 'removing {} of {}:{}'.format(i,len(calibrations_remove),cal))
            self.calibrations.remove(cal)

        self.update_calibration_all_table(self.calibrations)

    def find_calibrations(self):
        funcname = __name__ + '.find_calibrations():'
        logger.debug(funcname)
        autofindcal_button = self.sender()
        calibtablename = autofindcal_button.calibtablename
        print('Autofind for table',calibtablename)
        calibrations = self.calibrations
        calibrations_find = self.calibrationsTable[calibtablename].calibrations
        calibrations_found = copy.deepcopy(calibrations_find)
        # Loop over the calibrations, check if list or dict and try to find proper calibration
        # if dict
        flag_found_calibration = 0
        for i, cal_key in enumerate(calibrations_find):
            if isinstance(calibrations_find, dict):
                calibration = calibrations_find[cal_key]
                print('calibration dict', i, cal_key)
                datastreamstr = str(cal_key)
            elif isinstance(calibrations_find, list):
                raise ValueError('Calibrations need to be a dictionary')
            else:
                raise ValueError('Calibrations need to be a dictionary')

            parameter = cal_key
            calibration_candidates = redvypr.devices.sensors.calibration.calibration_models.find_calibration_for_parameter(parameter,calibrations)
            print('Calibration candidates for parameter',calibration_candidates)
            if len(calibration_candidates) > 0:
                calibration_candidate_final = calibration_candidates[0]
                calibrations_found[cal_key] = calibration_candidate_final
                flag_found_calibration += 1

        # update the table
        if flag_found_calibration > 0:
            self.calibrationsTable[calibtablename].update_table(calibrations=calibrations_found)

    def update_calibration_table(self,calibtablename,calibrations):
        funcname = __name__ + '.__update_calibration_tables__():'
        logger.debug(funcname)
        self.calibrationsTable[calibtablename].update_table(calibrations)

    def update_calibration_all_table(self, calibrations):
        funcname = __name__ + '.__update_calibration_tables__():'
        logger.debug(funcname)
        self.calibrations = redvypr.devices.sensors.calibration.calibration_models.CalibrationList(calibrations)
        self.calibrations_allTable.update_table(self.calibrations)


    def __save_calibration__(self):
        funcname = __name__ + '.__save_calibration__():'
        logger.debug(funcname)

        self.__calsavewidget__ = CalibrationsSaveWidget(calibrations = self.calibrations)
        self.__calsavewidget__.show()

    def chooseCalibrationFiles(self):
        """

        """
        funcname = __name__ + '.chooseCalibrationFiles():'
        logger.debug(funcname)
        # fileName = QtWidgets.QFileDialog.getLoadFileName(self, 'Load Calibration', '',
        #                                                 "Yaml Files (*.yaml);;All Files (*)")

        if self.loadCalibrationsfSubFolder.isChecked():
            fileNames = QtWidgets.QFileDialog.getExistingDirectory(self)
            fileNames = ([fileNames], None)
        else:
            fileNames = QtWidgets.QFileDialog.getOpenFileNames(self, 'Load Calibration', '',
                                                               "Yaml Files (*.yaml);;All Files (*)")

        # print('Filenames',fileNames)
        for fileName in fileNames[0]:
            # self.device.read_calibration_file(fileName)
            # print('Adding file ...', fileName)
            if os.path.isdir(fileName):
                print('Path', Path(fileName))
                coefffiles = list(Path(fileName).rglob("*.[yY][aA][mM][lL]"))
                print('Coeffiles', coefffiles)
                for coefffile in coefffiles:
                    print('Coefffile to open', coefffile, str(coefffile))
                    self.calibrations.add_calibration_file(str(coefffile))
            else:
                self.calibrations.add_calibration_file(fileName)

        # Fill the list with sn
        if len(fileNames[0]) > 0:
            logger.debug(funcname + ' Updating the calibration table')
            self.calibrations_allTable.update_table(self.calibrations)

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








class sensorCalibrationsWidget(QtWidgets.QWidget):
    """
    Widget to choose/load/remove new calibrations from files, this widget works with the generic_sensor device
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
                print('Path',Path(fileName))
                coefffiles = list(Path(fileName).rglob("*.[yY][aA][mM][lL]"))
                print('Coeffiles',coefffiles)
                for coefffile in coefffiles:
                    print('Coefffile to open',coefffile,str(coefffile))
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
                self.calibrations_allLayout.addWidget(self.calibrationConfigWidget, 0, 1)
                # self.sensorstack.setCurrentIndex(index)
            else:
                try:
                    self.calibrationConfigWidget.close()
                except:
                    pass

