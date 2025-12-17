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
import uuid
from typing import Union, Optional
import redvypr.devices.sensors.calibration.calibration_models
from redvypr.devices.sensors.calibration.calibration_models import CalibrationList, CalibrationWrapper
from redvypr.devices.sensors.calibration.calibration_plot_report_widgets import write_report_pdf
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget
from PyQt6 import QtWidgets, QtCore, QtGui
import redvypr.gui as gui
from pathlib import Path

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.calibrationWidget')
logger.setLevel(logging.DEBUG)



class CalibrationsSaveWidget(QtWidgets.QWidget):
    def __init__(self, *args, calibrations: list | CalibrationList | None = None, save_report = True):
        """
        Widget that allows to save the calibration
        Parameters
        ----------
        args
        calibrations: Calibrationlist
        """
        funcname = __name__ + '__init__()'
        super().__init__(*args)
        self.save_report = save_report
        if isinstance(calibrations,list):
            logger.debug(funcname + 'Changing calibrations to CalibrationList')
            calibrations = CalibrationList(calibrations)

        self.calibrations = calibrations
        print("Calibrations:",calibrations)
        print("done")

        # Add some extras to the calibrations
        for cal in calibrations:
            if cal is not None:
                cal.__save__ = True
                cal.__filename__ = None

        self.calibration_table = QtWidgets.QTableWidget() # Table to show all calibrations and the users choice for saving

        self.layout = QtWidgets.QGridLayout(self)
        self.check_sensor = QtWidgets.QWidget()
        self.check_sensor_layout = QtWidgets.QHBoxLayout(self.check_sensor)
        self.file_format_checkboxes = {}
        self.filename = "{document_type}_{date}"
        file_format_check = {'sn':'Serial Number', 'date':'Date', 'sensor_model':'Sensor model', 'calibration_id': 'Calibration Id', 'calibration_uuid':'Calibration UUID', 'calibration_type':'Calibration type', 'document_type':'Document type'}
        for format_check in file_format_check:
            self.file_format_checkboxes[format_check] = QtWidgets.QCheckBox(file_format_check[format_check])
            if format_check in self.filename:
                self.file_format_checkboxes[format_check].setChecked(True)

            self.file_format_checkboxes[format_check].stateChanged.connect(self.__update_filename__)
            self.check_sensor_layout.addWidget(self.file_format_checkboxes[format_check])

        # Text edits for the extensions
        self.extensionstr_calibrationfile = ".yaml"
        self.extensionstr_reportfile = ".pdf"
        self.extension_calibration = QtWidgets.QLineEdit()
        self.extension_calibration.setText(self.extensionstr_calibrationfile)
        self.extension_calibration.editingFinished.connect(self.__filename_text_changed__)
        if self.save_report:
            self.extension_report = QtWidgets.QLineEdit()
            self.extension_report.setText(self.extensionstr_reportfile)
            self.extension_report.editingFinished.connect(self.__filename_text_changed__)

        widget_extension = QtWidgets.QWidget()
        layout_extension = QtWidgets.QHBoxLayout(widget_extension)
        layout_extension.addWidget(QtWidgets.QLabel("Extension calibration file"))
        layout_extension.addWidget(self.extension_calibration)
        if self.save_report:
            layout_extension.addWidget(QtWidgets.QLabel("Extension report file"))
            layout_extension.addWidget(self.extension_report)

        self.filename_edit = QtWidgets.QLineEdit()

        iconname = "fa5.folder-open"
        folder_icon = qtawesome.icon(iconname)
        self.filename_button = QtWidgets.QPushButton()
        self.filename_button.setIcon(folder_icon)
        #self.filename_button.textChanged.connect(self.__filename_text_changed__)
        self.filename_button.clicked.connect(self.__get_filename_clicked__)
        #self.filename_choose = QtWidgets.QLineEdit()
        self.filename_widget = QtWidgets.QWidget()
        self.filename_widget_layout = QtWidgets.QHBoxLayout(self.filename_widget)
        # Checkbox to save all
        self.save_all_check = QtWidgets.QCheckBox("Save all")
        self.save_all_check.setCheckState(QtCore.Qt.Checked)
        self.save_all_check.stateChanged.connect(self.__save_all_changed__)
        # Save buttons
        self.save_button = QtWidgets.QPushButton('Save')
        self.save_button.clicked.connect(self.__save_clicked__)
        self.filename_widget_layout.addWidget(self.filename_edit)
        self.filename_widget_layout.addWidget(self.filename_button)

        self.filename_edit.setText(self.filename)
        self.filename_edit.editingFinished.connect(self.__filename_text_changed__)
        self.__populate_calibration_table__()  # Fill the table

        self.layout.addWidget(self.check_sensor, 0, 0)
        self.layout.addWidget(widget_extension,1,0)
        self.layout.addWidget(self.filename_widget, 2, 0)
        self.layout.addWidget(self.save_all_check, 3, 0)
        self.layout.addWidget(self.calibration_table, 4, 0)
        self.layout.addWidget(self.save_button, 5, 0)

    def __save_all_changed__(self, state):
        print('save_all_changed',state)
        if state == 0:
            for cal in self.calibrations:
                if cal is not None:
                    cal.__save__ = False
        else:
            for cal in self.calibrations:
                if cal is not None:
                    cal.__save__ = True

        self.__populate_calibration_table__() # Update the table

    def __update_filenames_in_calibrations__(self):
        print('Updating filenames of the calibrations')
        calfiles = self.calibrations.create_filenames_save(self.filename, document_type="calibration")
        print("Calfiles",calfiles)
        print("Calfiles done\n")
        calfiles_report = self.calibrations.create_filenames_save(self.filename, document_type="report")
        if True:
            for cal,filename,filename_report in zip(self.calibrations,calfiles, calfiles_report):
                if cal is not None:
                    cal.__filename__ = filename + self.extensionstr_calibrationfile
                    cal.__filename_report__ = filename_report + self.extensionstr_reportfile

    def __populate_calibration_table__(self):
        colheader = ["Save","SN","Filename"]
        if self.save_report:
            colheader = ["Save", "SN", "Channel", "Filename calibration", "Filename report"]
        self.calibration_table.clear()
        icol_save = 0
        icol_sn = 1
        icol_ch = 2
        icol_filename = 3
        icol_filename_report = 4
        self.calibration_table.setColumnCount(len(colheader))
        self.calibration_table.setHorizontalHeaderLabels(colheader)
        self.__update_filenames_in_calibrations__() # update the filenames to save
        nrows = 0
        i = 0
        print("len calibration",len(self.calibrations))
        for ical,cal in enumerate(self.calibrations):
            print("Cal", ical,cal is None)
            if cal is not None:
                nrows += 1
                self.calibration_table.setRowCount(nrows)
                print("nrows",nrows)
                # Save flag
                checked = cal.__save__
                item_checkbox = QtWidgets.QCheckBox()
                item_checkbox.setChecked(checked)
                cal.__save_check__ = item_checkbox
                #item_checkbox.stateChanged.connect(self.__calibration_save_state_changed__)
                self.calibration_table.setCellWidget(nrows - 1, icol_save, item_checkbox)
                # Serial number
                item = QtWidgets.QTableWidgetItem(cal.sn)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.calibration_table.setItem(nrows-1, icol_sn, item)
                # Channel
                item = QtWidgets.QTableWidgetItem(cal.channel.to_address_string())
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.calibration_table.setItem(nrows - 1, icol_ch, item)
                # Filename calibration
                filename = cal.__filename__
                item = QtWidgets.QTableWidgetItem(filename)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.calibration_table.setItem(nrows - 1, icol_filename, item)
                if self.save_report:
                    # Filename calibration report
                    filename_report = cal.__filename_report__
                    item = QtWidgets.QTableWidgetItem(filename_report)
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                    self.calibration_table.setItem(nrows - 1, icol_filename_report, item)

        self.calibration_table.resizeColumnsToContents()

    def __filename_text_changed__(self):
        self.filename = self.filename_edit.text()
        self.extensionstr_calibrationfile = self.extension_calibration.text()
        self.extensionstr_reportfile = self.extension_report.text()
        self.__update_filename__()

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
            format_str = '{' + file_format + '}'
            if checkbox.isChecked():
                if format_str not in filename_base:
                    filename_base = format_str + filename_base
            else:
                filename_base = filename_base.replace(format_str,'')

        self.filename = filename_base + filename_ext
        self.filename_edit.setText(self.filename)
        self.__update_filenames_in_calibrations__()
        self.__populate_calibration_table__()

    def __save_clicked__(self):
        funcname = __name__ + '.__save_clicked__()'
        if True:
            filenames_save = []
            filenames_save_report = []
            calibrations_save = []
            for cal in self.calibrations:
                if cal is not None:
                    save_check = cal.__save_check__.isChecked()
                    if cal.__save__ and save_check:
                        filenames_save.append(cal.__filename__)
                        filenames_save_report.append(cal.__filename_report__)
                        calibrations_save.append(cal)

            # Save the files
            if len(filenames_save) > 0:
                print("Calibrations to save",calibrations_save)
                print("Filenames to save save", filenames_save)
                CalibrationList(calibrations_save).save(filenames_save)
                if self.save_report:
                    report_function = write_report_pdf
                    CalibrationList(calibrations_save).save_report(filenames_save_report,report_function)

            else:
                logger.warning("No calibrations to save")



class CalibrationsTable(QtWidgets.QTableWidget):
    """
    Table that is designed to show calibrations. Calibrations can be either a dictionary or a list.
    """
    def __init__(self, *args, calibrations=None, show_columns=None, hide_columns=None, **kwargs):
        funcname = __name__ + '__init__()'
        super().__init__(*args)
        self.datefmt = '%Y-%m-%d %H:%M:%S'
        if calibrations is None:
            calibrations = []
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
        self.columns['channel'] = 5
        self.columns['date'] = 6
        self.columns['id'] = 7
        self.columns['uuid'] = 8
        self.columns['comment'] = 9
        self.columns['coeffs'] = 10

        self.column_names = {'datastream': 'Sensor Channel'}
        self.column_names['caltype'] = 'Calibration Type'
        self.column_names['choose'] = 'Choose Calibration'
        self.column_names['show'] = 'Show Calibration'
        self.column_names['sn'] = 'Serial number'
        self.column_names['channel'] = 'Channel'
        self.column_names['date'] = 'Calibration Date'
        self.column_names['id'] = 'Calibration ID'
        self.column_names['uuid'] = 'Calibration UUID'
        self.column_names['comment'] = 'Comment'
        self.column_names['coeffs'] = 'Coefficients'

        self.header_labels = []
        for lab in self.column_names.keys():
            self.header_labels.append(self.column_names[lab])

        self.nCols = len(self.columns.keys())
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.__show_context_menu__)

        # Populate the table
        self.update_table()

    def __show_context_menu__(self, pos):
        """Öffnet ein Kontextmenü beim Rechtsklick."""
        menu = QtWidgets.QMenu(self)
        delete_action = menu.addAction("Delete Calibration(s)")
        action = menu.exec_(self.viewport().mapToGlobal(pos))
        if action == delete_action:
            self.__delete_selected_calibrations__()

    def __delete_selected_calibrations__(self):
        """Löscht die ausgewählten Kalibrierungen."""
        #print("deleting ...")
        selected_rows = set()
        selection_model = self.selectionModel()
        selected_indexes = selection_model.selectedRows()  # Nur Zeilenauswahl
        for index in selected_indexes:
            selected_rows.add(index.row())
        #print("Ausgewählte Zeilen:", selected_rows)
        #print("rows",selected_rows)
        # Entferne die ausgewählten Kalibrierungen aus der Liste/Dictionary
        if isinstance(self.calibrations, list):
            #print("list")
            # Sortiere die Indizes absteigend, um Probleme beim Löschen zu vermeiden
            for row in sorted(selected_rows, reverse=True):
                if row < len(self.calibrations):
                    #print("deleting",row)
                    del self.calibrations[row]
        elif isinstance(self.calibrations, dict):
            # Für Dictionaries: Schlüssel der ausgewählten Reihen entfernen
            keys_to_delete = []
            for row in selected_rows:
                if row < len(self.__calibrations_list__):
                    cal_key = list(self.calibrations.keys())[row]
                    keys_to_delete.append(cal_key)
            for key in keys_to_delete:
                del self.calibrations[key]
        else:
            print("Cannot delete calibrations",type(self.calibrations))

        # Aktualisiere die Tabelle
        self.update_table()

    def get_selected_calibrations(self):
        """

        Returns
        -------
        List of calibrations of selected rows
        """

        calibrations = []
        for index in self.selectionModel().selectedRows():
            row = index.row()
            if row < len(self.__calibrations_list__):
                calibrations.append(self.__calibrations_list__[row])
        return calibrations

    def get_selected_calibrations_legacy(self):
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
            logger.debug('Will not show the channel')
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
                # Channel
                channelstr = str(calibration.channel)
                item = QtWidgets.QTableWidgetItem(channelstr)
                self.setItem(i, self.columns['channel'], item)
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
    Widget to display the calibrations of a sensor and to let the user choose different calibrations. It can read
    multiple files, check if they are already existing and if not add the calibrations.
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

        self.sensorinfo = {'sn':None, 'calibration_type':None, 'calibration_id':None, 'calibration_uuid':None}
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

                clearcal_button = QtWidgets.QPushButton('Clear')
                clearcal_button.clicked.connect(self.clear_calibrations)
                clearcal_button.calibtablename = calibtablename

                self.calibrationsTableAutoCalButtons[calibtablename] = {'find':autofindcal_button,'clear':clearcal_button}
                self.calibrationsTableWidgets_layout[calibtablename].addWidget(autofindcal_button)
                self.calibrationsTableWidgets_layout[calibtablename].addWidget(clearcal_button)
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

    def update_sensor_info(self,sensorinfo):
        funcname = __name__ + '.update_sensorinfo():'
        logger.debug(funcname)
        self.sensorinfo = sensorinfo

    def remCalibration_clicked(self):
        funcname = __name__ + '.remCalibration_clicked():'
        logger.debug(funcname)
        calibrations_remove = self.calibrations_allTable.get_selected_calibrations()
        for i,cal in enumerate(calibrations_remove):
            logger.debug(funcname + 'removing {} of {}:{}'.format(i,len(calibrations_remove),cal))
            self.calibrations.remove(cal)

        self.update_calibration_all_table(self.calibrations)

    def clear_calibrations(self):
        funcname = __name__ + '.clear_calibrations():'
        logger.debug(funcname)
        clearcal_button = self.sender()
        calibtablename = clearcal_button.calibtablename
        calibrations = self.calibrations
        calibrations_find = self.calibrationsTable[calibtablename].calibrations
        calibrations_found = copy.deepcopy(calibrations_find)
        # Loop over the calibrations, check if list or dict and try to find proper calibration
        # if dict
        flag_found_calibration = 0
        for i, cal_key in enumerate(calibrations_find):
            calibrations_find[cal_key] = None

        self.calibrationsTable[calibtablename].update_table(calibrations=calibrations_find)

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

            channel = cal_key
            try:
                sn = self.sensorinfo['sn']
            except:
                sn = None
            calibration_candidates = redvypr.devices.sensors.calibration.calibration_models.find_calibration_for_channel(
                channel=channel, calibrations=calibrations, sn=sn)

            print('Finding calibration for channel {} with sn {}'.format(channel,sn))
            #print('Calibration candidates for channel',calibration_candidates)
            if len(calibration_candidates) > 0:
                print('Found {} calibrations:'.format(len(calibration_candidates)))
                for icand, ctmp in enumerate(calibration_candidates):
                    print('{}:'.format(icand))
                    print(ctmp)

                ichoose = 0
                print('Choosing calibration with index {} '.format(ichoose))
                calibration_candidate_final = calibration_candidates[ichoose]
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
                    self.__calConfigWidget_tmp__ = gui.pydanticQTreeWidget(cal, dataname=cal.sn + '/' + cal.channel,
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
        colheaders = ['SN', 'Calibration type', 'Channel', 'Calibration date']
        icol_sn = colheaders.index('SN')
        icol_para = colheaders.index('Channel')
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
            # Channel
            icol_caltype = colheaders.index('Calibration type')
            # Distinguish between RedvyprAddress and str
            try:
                channel_str = cal.channel.address_str
            except:
                channel_str = cal.channel

            item = QtWidgets.QTableWidgetItem(channel_str)
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


#
# calibrationsManagerWidget
#
# ==============================================================================
# 1. THE MODEL (Data Handling)
# ==============================================================================

class CalibrationListModel(QtCore.QAbstractListModel):
    """
    Qt Model implementation for the CalibrationList object.
    Handles data representation, counting, and providing necessary info
    for the QListView. Also supports drag-and-drop data packaging (MIME).
    """

    def __init__(self, calibration_list: CalibrationList, parent=None):
        super().__init__(parent)
        self._list = calibration_list
        self.list_id = uuid.uuid4().hex  # Unique ID for DND source identification

    def rowCount(self, parent=QtCore.QModelIndex()):
        """Returns the number of calibrations in the list."""
        if parent.isValid(): return 0
        return len(self._list)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        """Returns the data to be displayed in the list view for a given index and role."""
        if not index.isValid() or not (0 <= index.row() < len(self._list)):
            return None

        calibration = self._list[index.row()]

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            # Format the display string for the list item
            date_str = getattr(calibration, 'date', datetime.datetime.min).strftime(
                '%Y-%m-%d')
            channel_str = str(getattr(calibration, 'channel', 'N/A'))
            sn_str = getattr(calibration, 'sn', 'N/A')
            model_str = getattr(calibration, 'sensor_model', 'N/A')

            return f"{channel_str} | {sn_str} | {model_str} | {date_str}"

        elif role == QtCore.Qt.ItemDataRole.ToolTipRole:
            # Display detailed info on mouse hover
            return (f"Content ID: {getattr(calibration, '_content_id', 'N/A')}\n"
                    f"Channel: {getattr(calibration, 'channel', 'N/A')}\n"
                    f"Model: {getattr(calibration, 'sensor_model', 'N/A')}")

        return None

    def flags(self, index):
        """Defines item flags, enabling drag for valid items and drop for the view area."""
        if not index.isValid():
            # Allow dropping onto the view area (empty space)
            return QtCore.Qt.ItemFlag.ItemIsDropEnabled

        flags = (
                QtCore.Qt.ItemFlag.ItemIsEnabled |
                QtCore.Qt.ItemFlag.ItemIsSelectable |
                QtCore.Qt.ItemFlag.ItemIsDragEnabled  # Enable dragging of items
        )
        return flags

    def mimeData(self, indexes):
        """Packages selected calibration items into QMimeData for drag-and-drop or clipboard operations."""
        mime_data = QtCore.QMimeData()
        serialized_calibrations = []

        for i in indexes:
            if i.isValid():
                row = i.row()
                if 0 <= row < len(self._list):
                    calibration = self._list[row]

                    try:
                        # Use Pydantic's serialization method
                        cal_json = calibration.model_dump_json()
                        serialized_calibrations.append(cal_json)
                    except AttributeError:
                        logger.error(
                            "DND_MIME: Calibration object lacks 'model_dump_json()'. Cannot serialize.")
                        return QtCore.QMimeData()

                        # Include source list ID to prevent dropping onto itself
        drag_data = {
            "source_list_id": self.list_id,
            "calibrations": serialized_calibrations
        }

        json_data = json.dumps(drag_data).encode('utf-8')

        mime_type = "application/x-calibration-uuids"
        mime_data.setData(mime_type, QtCore.QByteArray(json_data))

        return mime_data

    def add_calibration_safe(self, calibration):
        """Inserts a calibration object into the list model safely, emitting signals."""
        new_row_idx = len(self._list)
        self.beginInsertRows(QtCore.QModelIndex(), new_row_idx, new_row_idx)
        # Assuming CalibrationList.add_calibration handles duplicate checks
        success = self._list.add_calibration(calibration)
        self.endInsertRows()
        return success

    def remove_by_content_id(self, content_id_str):
        """Removes the first calibration found with the matching content ID."""
        for i, cal in enumerate(self._list):
            if getattr(cal, '_content_id', None) == content_id_str:
                self.beginRemoveRows(QtCore.QModelIndex(), i, i)
                self._list.pop(i)
                self.endRemoveRows()
                return True
        return False

    def sort_list(self, key_attr):
        """Sorts the underlying data list and emits signals to update the view."""
        self.layoutAboutToBeChanged.emit()
        try:
            # Case-insensitive sorting using object attributes
            self._list.sort(key=lambda x: str(getattr(x, key_attr, "")).lower())
        except Exception as e:
            logger.error(f"Error sorting by {key_attr}: {e}")
        self.layoutChanged.emit()


# ==============================================================================
# 2. THE VIEW (List Display and Drag/Drop Handler)
# ==============================================================================
class CalibrationListView(QtWidgets.QListView):
    """
    Custom QListView to display the CalibrationListModel.
    Implements context menu actions (Copy/Cut/Paste/Sort) and drag-and-drop logic (dropEvent).
    """

    def __init__(self, model, manager_ref, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self._manager_ref = manager_ref

        self.doubleClicked.connect(
            lambda index: self._manager_ref.show_calibration_details(index,
                                                                     self.model())
        )

        self.setAlternatingRowColors(True)
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)

        # Drag and Drop Setup
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)

        # Context Menu Setup
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.open_context_menu)

    def open_context_menu(self, position: QtCore.QPoint):
        """Builds and executes the context menu for the list view."""
        menu = QtWidgets.QMenu()

        # --- Copy/Cut/Paste Actions ---
        action_copy = QtGui.QAction("Copy", self)
        action_copy.triggered.connect(self.copy_selected)
        menu.addAction(action_copy)

        action_cut = QtGui.QAction("Cut", self)
        action_cut.triggered.connect(self.cut_selected)
        menu.addAction(action_cut)

        action_paste = QtGui.QAction("Paste", self)
        if self._manager_ref:
            action_paste.triggered.connect(
                lambda: self._manager_ref.paste_to_active_list(self.model()))
            clipboard = QtWidgets.QApplication.clipboard()
            # Only enable paste if clipboard contains our custom MIME data
            action_paste.setEnabled(
                clipboard.mimeData().hasFormat("application/x-calibration-uuids"))
        else:
            action_paste.setEnabled(False)
        menu.addAction(action_paste)

        menu.addSeparator()

        # --- Sort Actions ---
        sort_menu = menu.addMenu("Sort by...")
        sort_options = {
            "Channel": "channel", "Serial Number": "sn", "Sensor Model": "sensor_model",
            "Date": "date", "Content ID": "_content_id",
        }
        for label, attr in sort_options.items():
            action = QtGui.QAction(label, self)
            action.triggered.connect(lambda checked, a=attr: self.model().sort_list(a))
            sort_menu.addAction(action)

        menu.exec(self.mapToGlobal(position))

    def copy_selected(self):
        """Copies the selected items to the system clipboard."""
        selected_indexes = self.selectionModel().selectedRows()
        if not selected_indexes: return
        mime_data = self.model().mimeData(selected_indexes)
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setMimeData(mime_data)

    def cut_selected(self):
        """Copies the selected items to the clipboard and then removes them from the model."""
        selected_indexes = self.selectionModel().selectedRows()
        if not selected_indexes: return

        self.copy_selected()

        # Collect IDs before removing, as index changes during removal
        content_ids_to_remove = []
        for index in selected_indexes:
            if index.isValid():
                cal = self.model()._list[index.row()]
                content_ids_to_remove.append(getattr(cal, '_content_id'))

        for content_id_str in content_ids_to_remove:
            self.model().remove_by_content_id(content_id_str)

    def dragEnterEvent(self, event):
        """Checks if the dragged data is in the correct format."""
        expected_mime = "application/x-calibration-uuids"
        if event.mimeData().hasFormat(expected_mime):
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """Sets the drop action for Move."""
        if event.mimeData().hasFormat("application/x-calibration-uuids"):
            event.setDropAction(QtCore.Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """Handles the dropping of data from one CalibrationListView to another."""
        expected_mime = "application/x-calibration-uuids"

        if event.mimeData().hasFormat(expected_mime):

            data_bytes = event.mimeData().data(expected_mime)
            try:
                data_json = json.loads(data_bytes.data().decode('utf-8'))
                source_id = data_json['source_list_id']
                serialized_calibrations = data_json.get('calibrations', [])
            except Exception as e:
                logger.error(f"DND_DROP: Failed to parse MIME data: {e}", exc_info=True)
                event.ignore()
                return

            manager = self._manager_ref
            if not manager:
                event.ignore()
                return

            source_model = manager.get_model(source_id)
            target_model = self.model()

            # Prevent dropping onto the source list itself
            if not source_model or source_model == target_model:
                event.ignore()
                return

            moved_content_ids = []

            # Deserialize and add to target model
            for cal_json_str in serialized_calibrations:
                try:
                    # Recreate object from JSON using Pydantic's validation
                    print("Validating",cal_json_str)
                    cal_wrapper = CalibrationWrapper.model_validate_json(cal_json_str)
                    cal_copy = cal_wrapper.root
                    print("Type",type(cal_copy))
                    cal_copy.calc_content_id()
                    cid = getattr(cal_copy, '_content_id')

                    if target_model.add_calibration_safe(cal_copy):
                        moved_content_ids.append(cid)

                except Exception as e:
                    logger.error(
                        f"DND_DROP: Error during deserialization or addition: {e}",
                        exc_info=True)
                    continue

            # If the drop action was Move, remove successful transfers from source
            if event.dropAction() == QtCore.Qt.DropAction.MoveAction:
                for content_id_str in moved_content_ids:
                    source_model.remove_by_content_id(content_id_str)

            event.setDropAction(QtCore.Qt.DropAction.MoveAction)
            event.accept()
        else:
            super().dropEvent(event)


# ==============================================================================
# 3. THE MANAGER (Main Widget and Load/Save Logic)
# ==============================================================================
class CalibrationManagerWidget(QtWidgets.QWidget):
    """
    The main widget that manages multiple CalibrationLists side-by-side.
    It orchestrates the creation, loading, saving, and deletion of lists.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibration Manager")
        self.setObjectName("CalibrationManagerWidget")

        # Layouts
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.controls_layout = QtWidgets.QHBoxLayout()
        self.lists_layout = QtWidgets.QHBoxLayout()

        # Control Buttons
        self.btn_new_list = QtWidgets.QPushButton("Create New List")
        self.btn_new_list.clicked.connect(self.create_new_list)

        self.btn_new_list_from_files = QtWidgets.QPushButton("Create List from File(s)")
        self.btn_new_list_from_files.clicked.connect(self.create_list_from_files)

        self.btn_save_all = QtWidgets.QPushButton("Save All Lists")
        self.btn_save_all.clicked.connect(self.save_all)

        # Build control panel
        self.controls_layout.addWidget(self.btn_new_list)
        self.controls_layout.addWidget(self.btn_new_list_from_files)
        self.controls_layout.addWidget(self.btn_save_all)
        self.controls_layout.addStretch()

        # Assemble main layout
        self.main_layout.addLayout(self.controls_layout)
        self.main_layout.addLayout(self.lists_layout)

        # Dictionary to hold all active models, keyed by list_id
        self.models = {}

    def _refresh_single_item(self, index: QtCore.QModelIndex):
        """Helper to emit dataChanged signal for the given index."""
        # Das Model muss den View dazu zwingen, die Daten für diesen Index neu zu laden
        model = self._item_config_widget_model_ref  # Das Model speichern wir unten
        if model and index.isValid():
            logger.debug(f"Emitting dataChanged for row {index.row()}.")
            model.dataChanged.emit(index, index)

        # Cleanup der Referenzen
        self._item_config_widget = None
        self._item_config_widget_model_ref = None

    def show_calibration_details(self, index: QtCore.QModelIndex,
                                 model: 'CalibrationListModel'):
        """
        Retrieves the calibration object corresponding to the double-clicked index
        and prints its details to the console.

        :param index: The QModelIndex of the double-clicked item.
        :param model: The CalibrationListModel that holds the data.
        """
        if not index.isValid():
            logger.warning("Double-click on invalid index.")
            return

        try:
            row = index.row()
            # Access the underlying data list directly via the model
            calibration_entry = model._list[row]

            self._item_config_widget = pydanticConfigWidget(config = calibration_entry)
            self._item_config_widget_index_ref = index
            self._item_config_widget_model_ref = model

            # --- NEU: Signal-Verbindung ---
            # Wenn das Config-Widget die Daten anwendet/speichert, rufen wir die Refresh-Methode auf.
            self._item_config_widget.config_editing_done.connect(
                lambda: self._refresh_single_item(self._item_config_widget_index_ref)
            )
            self._item_config_widget.show()
            if True:
                # Use model_dump_json() for a structured string representation (assuming Pydantic model)
                details_json_string = calibration_entry.model_dump_json(indent=2)

                # Get the list name for context
                try:
                    target_name = model.parent().findChild(QtWidgets.QLabel).text().strip(
                        '<b></b>')
                except:
                    target_name = model.list_id

                logger.info(
                    f"--- Calibration Details (List: {target_name}, Row: {row}) ---")
                print(details_json_string)
                print("------------------------------------------------------------------")

        except IndexError:
            logger.error(f"IndexError: Row {row} out of bounds for model data.")
        except Exception as e:
            logger.error(f"Error accessing calibration details: {e}", exc_info=True)

    # ---------------------------------------------

    def add_calibration_list(self, calibration_list, name="Calibrations"):
        """Adds a visual column for a calibration list (Model + View + Controls)."""
        model = CalibrationListModel(calibration_list)
        self.models[model.list_id] = model

        # Container widget for the list column
        container = QtWidgets.QWidget()
        container.setProperty("list_id", model.list_id)
        container.setMinimumWidth(250)
        vbox = QtWidgets.QVBoxLayout(container)
        vbox.setContentsMargins(4, 4, 4, 4)

        # Title Label
        lbl_title = QtWidgets.QLabel(f"<b>{name}</b>")
        lbl_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        vbox.addWidget(lbl_title)

        # The List View
        view = CalibrationListView(model, manager_ref=self)
        vbox.addWidget(view)

        # List-specific control buttons (Load/Save/Delete)
        btn_layout = QtWidgets.QHBoxLayout()

        btn_load = QtWidgets.QPushButton("Load")
        btn_load.setToolTip(f"Load calibrations from file into '{name}'")
        btn_load.clicked.connect(lambda checked, m=model: self.load_file_to_list(m))

        btn_save = QtWidgets.QPushButton("Save")
        btn_save.setToolTip(f"Save '{name}' to file")
        btn_save.clicked.connect(lambda checked, m=model: self.save_single_list(m))

        # Delete List Button with qtawesome icon
        iconname = "mdi6.delete"
        delete_icon = qtawesome.icon(iconname)
        btn_delete = QtWidgets.QPushButton()
        btn_delete.setIcon(delete_icon)

        # Connect delete button to remove the container
        btn_delete.clicked.connect(
            lambda checked, c=container,
                   list_id=model.list_id: self.delete_list_container(c, list_id, name)
        )

        btn_layout.addWidget(btn_load)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_delete)

        vbox.addLayout(btn_layout)
        self.lists_layout.addWidget(container)

    def delete_list_container(self, container: QtWidgets.QWidget, list_id: str,
                              list_name: str):
        """Removes the visual column and the associated data model."""

        # Confirmation Dialog
        reply = QtWidgets.QMessageBox.question(
            self,
            'Confirm Deletion',
            f"Are you sure you want to delete the list '<b>{list_name}</b>'?\n"
            "This action cannot be undone.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No
        )

        if reply == QtWidgets.QMessageBox.StandardButton.No:
            return

        # 1. Remove from Layout
        self.lists_layout.removeWidget(container)

        # 2. Remove from Model dictionary
        if list_id in self.models:
            del self.models[list_id]
            logger.info(f"Deleted model (ID: {list_id}) from manager.")

        # 3. Clean up the widget
        container.deleteLater()

        QtWidgets.QMessageBox.information(self, "List Deleted",
                                          f"The list '<b>{list_name}</b>' has been deleted.")

    def create_list_from_files(self):
        """Opens a file dialog to select multiple files and combines their calibrations into a new list."""
        file_filter = "Calibration Files (*.yaml *.json *.txt);;All Files (*)"

        fnames, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Create New List from File(s)",
            "",
            file_filter
        )

        if not fnames: return

        name, ok = QtWidgets.QInputDialog.getText(self, "New List Name",
                                                  "Enter name for the combined list:")
        if not ok or not name:
            name = f"Combined List ({len(fnames)} files)"

        new_list = CalibrationList()
        total_loaded = 0
        total_duplicates = 0

        for fname in fnames:
            try:
                temp_list = CalibrationList()
                # Assuming read_calibration_file loads data into temp_list
                calibrations_loaded = temp_list.read_calibration_file(fname)

                if not calibrations_loaded: continue

                # Add loaded calibrations to the new list, duplicates are handled by CalibrationList
                for cal in calibrations_loaded:
                    cal_copy = copy.deepcopy(cal)
                    cal_copy.calc_content_id()

                    if new_list.add_calibration(cal_copy):
                        total_loaded += 1
                    else:
                        total_duplicates += 1

            except Exception as e:
                logger.error(f"Error loading file {fname}: {e}")

        if total_loaded > 0:
            self.add_calibration_list(new_list, name)

            summary = (f"Successfully created list '{name}'.\n"
                       f"Total calibrations loaded: {total_loaded}\n"
                       f"Duplicates skipped (in combined list): {total_duplicates}")
            QtWidgets.QMessageBox.information(self, "Success", summary)
        else:
            QtWidgets.QMessageBox.warning(self, "Info",
                                          "No valid calibrations were loaded from the selected files.")

    def load_file_to_list(self, model: CalibrationListModel):
        """Opens a file dialog and imports calibrations into an EXISTING list."""
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Calibration File",
            "",
            "Calibration Files (*.yaml *.json *.txt);;All Files (*)"
        )

        if fname:
            try:
                temp_list = CalibrationList()
                # Assuming read_calibration_file loads data into temp_list
                calibrations_loaded = temp_list.read_calibration_file(fname)

                if not calibrations_loaded: return

                count = 0
                for cal in calibrations_loaded:
                    cal_copy = copy.deepcopy(cal)
                    cal_copy.calc_content_id()

                    if model.add_calibration_safe(cal_copy):
                        count += 1

                QtWidgets.QMessageBox.information(self, "Load Success",
                                                  f"Successfully loaded {count} calibrations.")

            except Exception as e:
                logger.error(f"Error loading file: {e}")
                QtWidgets.QMessageBox.critical(self, "Load Error",
                                               f"Could not load file:\n{e}")

    def create_new_list(self):
        """Prompts for a name and creates an empty new calibration list."""
        name, ok = QtWidgets.QInputDialog.getText(self, "New List", "Enter list name:")
        if ok and name:
            new_list = CalibrationList()
            self.add_calibration_list(new_list, name)

    def get_model(self, list_id):
        """Retrieves a model instance by its unique ID."""
        return self.models.get(list_id)

    def paste_to_active_list(self, target_model: CalibrationListModel):
        """Pastes serialized objects from the clipboard into the target model."""
        clipboard = QtWidgets.QApplication.clipboard()
        mime_data = clipboard.mimeData()
        expected_mime = "application/x-calibration-uuids"

        if not mime_data.hasFormat(expected_mime):
            QtWidgets.QMessageBox.warning(self, "Paste Error",
                                          "Clipboard does not contain valid calibration data.")
            return

        data_bytes = mime_data.data(expected_mime)
        try:
            data_json = json.loads(data_bytes.data().decode('utf-8'))
            serialized_calibrations = data_json.get('calibrations', [])
        except Exception as e:
            logger.error(f"Paste: Failed to parse MIME data: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(self, "Paste Error",
                                           f"Error parsing data: {e}")
            return

        if not serialized_calibrations:
            QtWidgets.QMessageBox.warning(self, "Paste Error",
                                          "Clipboard is empty or invalid.")
            return

        count = 0
        for cal_json_str in serialized_calibrations:
            try:
                cal_copy = CalibrationWrapper.model_validate_json(cal_json_str)

                if target_model.add_calibration_safe(cal_copy):
                    count += 1
            except Exception as e:
                logger.error(f"Paste: Failed to create object from JSON: {e}",
                             exc_info=True)
                continue

        QtWidgets.QMessageBox.information(self, "Paste Success",
                                          f"Successfully pasted {count} calibrations.")

    def save_single_list(self, model):
        """Saves a single list using the CalibrationsSaveWidget."""
        cal_list = model._list
        if not cal_list:
            QtWidgets.QMessageBox.warning(self, "Info", "List is empty.")
            return

        # Use the dedicated Save Widget for saving functionality
        self._cal_save_widget = CalibrationsSaveWidget(calibrations=cal_list)
        self._cal_save_widget.show()

    def save_all(self):
        """Attempts to save all non-empty lists managed by the widget."""
        for model in self.models.values():
            if len(model._list) > 0:
                self.save_single_list(model)

