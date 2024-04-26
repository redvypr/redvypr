import copy
import datetime
import redvypr.data_packets as data_packets
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget
import numpy
import pydantic
import typing
import sys
import logging
from PyQt5 import QtWidgets, QtCore, QtGui
from redvypr.devices.sensors.calibration.calibration_models import calibration_NTC
from .average_data import average_data
from .sensorWidgets import sensorCoeffWidget

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('temperature_array_sensors')
logger.setLevel(logging.DEBUG)

avg_objs_TAR_raw = {}  # Average dataobjects


class parameter_TAR(pydantic.BaseModel):
    NTC_A: typing.Optional[typing.List[calibration_NTC]] = pydantic.Field(default=[])
    name: typing.Optional[typing.List[str]] = pydantic.Field(default=[],description='Name of the parameter')
    pos_x: typing.Optional[typing.List[float]] = pydantic.Field(default=[])
    pos_y: typing.Optional[typing.List[float]] = pydantic.Field(default=[])
    pos_z: typing.Optional[typing.List[float]] = pydantic.Field(default=[])


class sensor_TAR(pydantic.BaseModel):
    description: str = 'Temperature array (TAR) sensor'
    sensor_id: typing.Literal['TAR'] = 'TAR'
    logger_model: str = 'TAR'
    logger_configuration: str = 'TAR'
    parameter: parameter_TAR = parameter_TAR()
    sn: str = pydantic.Field(default='', description='The serial number and/or MAC address of the sensor')
    comment: str = pydantic.Field(default='')
    use_config: bool = pydantic.Field(default=False, description='Use the configuration (True)')
    avg_data: list = pydantic.Field(default=[60, 300], description='List of averaging intervals')

    def init_from_data(self, dataline=None):
        super().__init__()
        if dataline is not None:
            dataparsed = parse_TAR_raw(dataline)
            self.sn = dataparsed['sn']
            n_NTC = len(dataparsed['NTC_A'])
        else:
            return

        # Parse positions, this can be done more elegantly
        dx_positions = float(dataparsed['positions'][1:])
        pos_x = 0
        if n_NTC is not None:
            for i in range(n_NTC):

                if n_NTC > 0:
                    numzeros = int(numpy.floor(numpy.log10(n_NTC))) + 1
                else:
                    numzeros = 1

                #intformat = 'NTC_A{:0' + str(numzeros) + 'd}'
                parameter_name = 'NTC_A[{:d}]'.format(i)
                NTC_name = parameter_name
                ntc_coeff = [1.9560290742146262e-07, -7.749325133113135e-08, 0.00025341112950681254,
                             0.0012350747622505245]
                coeff_comment = 'Standard coefficients, not calibration'
                NTCcal = calibration_NTC(parameter=parameter_name, coeff=ntc_coeff, comment=coeff_comment, sn=self.sn)
                self.parameter.NTC_A.append(NTCcal)
                self.parameter.pos_x.append(pos_x)
                self.parameter.name.append(NTC_name)
                #print('Adding parameter',parameter_name)
                pos_x += dx_positions


def process_TAR_data(dataline, data, device_info, loggerconfig):
    funcname = __name__ + '.process_TAR_data():'
    datapackets_return = []
    try:
        datapacket_TAR = process_TAR_raw(dataline, data, device_info)
        datapacket_TAR['datatype'] = 'raw'
    except:
        logger.info(' Could not decode {:s}'.format(str(dataline)), exc_info=True)
        datapacket_TAR = None

    if datapacket_TAR is not None:

        datapackets_return.append(datapacket_TAR)
        # Convert to temperature
        devicename = 'TAR_SI_' + datapacket_TAR['sn']
        datapacket_TAR_T = data_packets.create_datadict(device=devicename, tu=datapacket_TAR['_redvypr']['t'],
                                                        hostinfo=device_info['hostinfo'])
        datapacket_TAR_T['type'] = datapacket_TAR['type']
        datapacket_TAR_T['np'] = datapacket_TAR['np']
        datapacket_TAR_T['sn'] = datapacket_TAR['sn']
        datapacket_TAR_T['t'] = datapacket_TAR['t']
        datapacket_TAR_T['datatype'] = 'converted'
        datapacket_TAR_T['sensortype'] = datapacket_TAR['sensortype']
        datapacket_TAR_T['NTC_A'] = []
        j = 0
        for i, R in enumerate(datapacket_TAR['NTC_A']):
            j += 1
            #print('COEFF',loggerconfig.parameter.NTC_A)
            poly = loggerconfig.parameter.NTC_A[i].coeff
            #poly = [1.9560290742146262e-07, -7.749325133113135e-08, 0.00025341112950681254, 0.0012350747622505245]
            Toff = 273.15
            # print('Poly', poly)
            data_tmp = numpy.polyval(poly, numpy.log(R))
            # print('data_tmp', data_tmp)
            data_tmp = 1 / data_tmp - Toff
            dataSI = data_tmp
            # print('data_SI', dataSI,type(dataSI))
            # datapacket[parameter] = float(dataSI)
            # And finally the data
            datapacket_TAR_T['NTC_A'].append(float(dataSI))

        datapackets_return.append(datapacket_TAR_T)
        #print('Datapacket TAR', datapacket_TAR_T)
        # dataqueue.put(datapacket_TAR)
        # Do averaging.
        sn = datapacket_TAR['sn']
        if False:
            try:
                datapacket_TAR_avg = avg_objs_TAR_raw[sn].average_data(data)
            except:
                parameters = ['t', 'NTC_A']
                avg_objs_TAR_raw[sn] = average_data(datapacket_TAR, parameters,
                                            loggerconfig)
                datapacket_TAR_avg = avg_objs_TAR_raw[sn].average_data(datapacket_TAR)
                logger.debug(funcname + ' could not average:', exc_info=True)

            if datapacket_TAR_avg is not None:
                datapackets_return.append(datapacket_TAR_avg)

    return datapackets_return


def process_TAR_raw(dataline, data, device_info):
    datapacket = parse_TAR_raw(dataline)
    if datapacket is not None:
        macstr = datapacket['sn']
        datapacket['t'] = data['t']
        devicename = 'TAR_raw_' + macstr
        datapacket_redvypr = data_packets.create_datadict(device=devicename, tu=data['_redvypr']['t'],
                                                          hostinfo=device_info['hostinfo'])
        datapacket_redvypr.update(datapacket)

        return datapacket_redvypr


# Temperature array
def parse_TAR_raw(data, sensortype='TAR'):
    """
    Parses temperature array
    $FC0FE7FFFE155D8C,TAR,B2,36533.125000,83117,3498.870,3499.174,3529.739,3490.359,3462.923,3467.226,3480.077,3443.092,3523.642,3525.567,3509.492,3561.330,3565.615,3486.693,3588.670,3539.169,3575.104,3523.946,3496.343,3480.160,3531.045,3501.624,3497.010,3557.235,3479.952,3458.297,3523.052,3487.223,3571.087,3525.740,3580.928,3534.818
    """
    #print('Got data', data)
    datasplit = data.split(',')
    macstr = datasplit[0][1:17]
    packettype = datasplit[1]  # HF
    datapacket = {}
    datapacket['type'] = packettype
    datapacket['sn'] = macstr
    datapacket['sensortype'] = sensortype
    valid_package = False
    numsp = len(datasplit)
    if numsp > 3:
        ts = float(datasplit[3])  # Sampling time
        np = int(datasplit[4])  # Number of packet
        datapacket['ts'] = ts
        datapacket['np'] = np
        datapacket['positions'] = datasplit[2]
        ntc_all = []
        j = 0
        for i in range(5, numsp):
            j += 1
            data = float(datasplit[i])
            ntc_all.append(data)

        datapacket['NTC_A'] = ntc_all

        valid_package = True

    if valid_package:
        return datapacket
    else:
        return None


class TARWidget(QtWidgets.QWidget):
    """
    Widget to display temperature array sensor data
    """
    def __init__(self,*args, sn=None, redvypr_device=None):
        funcname = __name__ + '__init__()'
        logger.debug(funcname)
        super(QtWidgets.QWidget, self).__init__(*args)

        self.device = redvypr_device
        self.sn = sn
        self.configuration = None
        if self.device is not None:
            try:
                self.configuration = self.device.config.sensorconfigurations[sn]
            except Exception as e:
                logger.exception(e)

        self.pos_x = self.configuration.parameter.pos_x
        self.parameter = ['NTC_A']
        self.parameter_unit = []
        self.parameter_unitconv = []
        #print('Adding parameter')
        self.rawconvtabs = QtWidgets.QTabWidget()
        self.rawwidget = QtWidgets.QWidget()
        self.layout_all = QtWidgets.QGridLayout(self.rawwidget)
        self.convwidget = QtWidgets.QWidget()
        self.layout_conv = QtWidgets.QGridLayout(self.convwidget)
        self.rawconvtabs.addTab(self.rawwidget,'Rawdata')
        self.rawconvtabs.addTab(self.convwidget, 'Converted data')

        self.layout = QtWidgets.QGridLayout(self)
        self.layout.addWidget(self.rawconvtabs,0,0)

        # Add a table for the raw data
        self.datatable_all = QtWidgets.QTableWidget()
        self.datatable_all_columnheader = ['Name','Pos']
        for i, p in enumerate(self.parameter):
            self.datatable_all_columnheader.append(p)
            self.datatable_all_columnheader.append(p)

        nNTC = len(self.configuration.parameter.NTC_A)
        nRows = nNTC + 3 # Add unit, time and numpacket
        self.nRow_data = 3
        self.datatable_all.setRowCount(nRows)

        self.datatable_all.setColumnCount(len(self.datatable_all_columnheader))
        self.datatable_all.setHorizontalHeaderLabels(self.datatable_all_columnheader)
        self.datatable_all.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.datatable_all.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.layout_all.addWidget(self.datatable_all,0,1)

    def update(self, data):
        """
        Updating the local data with datapacket
        """
        funcname = __name__ + '__update__()'
        logger.debug(funcname)
        devicename = data['_redvypr']['device']
        #print('Devicename',devicename)
        dkey = self.parameter[0]
        NTC_A = data[dkey]
        self.nRow_time = 1
        self.nRow_np = 2
        self.nRow_unit = 0
        self.nCol_pos = 1
        if 'raw' in devicename:
            nCol_data = 2
            unit = 'Ohm'
        if 'SI' in devicename:
            nCol_data = 3
            unit = 'degC'

        # Add unit, time, numpackage
        item = QtWidgets.QTableWidgetItem('Unit')
        self.datatable_all.setItem(self.nRow_unit, 0, item)
        item = QtWidgets.QTableWidgetItem('Time')
        self.datatable_all.setItem(self.nRow_time, 0, item)
        item = QtWidgets.QTableWidgetItem('Numsample')
        self.datatable_all.setItem(self.nRow_np, 0, item)

        item = QtWidgets.QTableWidgetItem(unit)
        self.datatable_all.setItem(self.nRow_unit, nCol_data, item)
        td = datetime.datetime.fromtimestamp(data['t'])
        tstr = td.strftime('%d %b %Y %H:%M:%S.%f')
        item = QtWidgets.QTableWidgetItem(tstr)
        self.datatable_all.setItem(self.nRow_time, nCol_data, item)
        npstr = str(data['np'])
        item = QtWidgets.QTableWidgetItem(npstr)
        self.datatable_all.setItem(self.nRow_np, nCol_data, item)

        for i,NTC in enumerate(NTC_A):
            # Name
            namestr = "NTC{:02d}".format(i+1)
            item = QtWidgets.QTableWidgetItem(namestr)
            self.datatable_all.setItem(i+self.nRow_data,0,item)
            # Position
            pos = self.pos_x[i]
            item = QtWidgets.QTableWidgetItem(str(pos))
            self.datatable_all.setItem(i + self.nRow_data, self.nCol_pos, item)
            # Data
            dstr = "{:.3f}".format(NTC)
            item = QtWidgets.QTableWidgetItem(dstr)
            self.datatable_all.setItem(i+self.nRow_data,nCol_data,item)

        # Fill the datatables
        self.datatable_all.resizeColumnsToContents()


#
#
# Here the widgets start
#
#
class TARWidget_config(QtWidgets.QWidget):
    """
    Widget to configure a temperature array sensor
    """

    def __init__(self, *args, sn=None, redvypr_device=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        self.device = redvypr_device
        self.nosensorstr = ''
        self.sn = sn
        # Try to find a configuration for the logger
        try:
            conf = self.device.config.sensorconfigurations[self.sn]
            logger.debug(funcname + ' Found a configuration')
        except:
            logger.warning(funcname + ' Did not find a configuration')
            return

        self.config = conf
        conflocal = copy.deepcopy(conf)
        self.configWidget = pydanticConfigWidget(self.config, exclude=['parameter'])

        self.parameterWidget = QtWidgets.QWidget(self)
        self.fill_parameter_widgets()

        self.layout = QtWidgets.QGridLayout(self)
        self.layout.addWidget(self.configWidget,0,0)
        self.layout.addWidget(self.parameterWidget,0,1)

    def __assign_calibrations__(self):
        funcname = __name__ + '__assign_calibrations():'
        print(funcname)
        print('calibrations',self.device.config.calibrations)
        cals = self.device.config.calibrations
        match = ['parameter','sn']
        for i, para in enumerate(self.config.parameter.NTC_A):
            print('Searching for calibration for parameter',i)
            print('Para',i,para)
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
                self.config.parameter.NTC_A[i] = cal_match[imin]

        self.__fill_calibration_table__()

    def __create_calibration_widget__(self):
        self.__calbutton_clicked__ = self.sender()
        self.__calwidget__ = sensorCoeffWidget(redvypr_device=self.device)
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
                print('Cal',cal)
                self.__cal_apply__ = cal # Save the calibration
                #Update the calibration
                iupdate = self.__calbutton_clicked__.__para_index__
                print('Iupdate', iupdate)
                self.config.parameter.NTC_A[iupdate] = cal
                self.__calwidget__.close()
                self.__fill_calibration_table__()


    def __fill_calibration_table__(self):
        funcname = __name__ + '__fill_calibration_table__():'
        logger.debug(funcname)
        self.parameterTable.clear()
        nRows = len(self.config.parameter.NTC_A)
        nCols = 5
        self.parameterTable.setRowCount(nRows)
        self.parameterTable.setColumnCount(nCols)
        self.parameterTable.setHorizontalHeaderLabels(['Sensor Parameter','Cal SN','Cal Parameter','Cal Date','Cal Comment'])
        #print('Config parameter',self.config.parameter)
        for i,para in enumerate(self.config.parameter.NTC_A):
            #print('Para',para)
            name = self.config.parameter.name[i]
            but = QtWidgets.QPushButton(name)

            #but.clicked.connect(self.parent().show_coeffwidget_apply)
            but.clicked.connect(self.__create_calibration_widget__)
            but.__para__ = para
            but.__para_index__ = i
            self.parameterTable.setCellWidget(i,0,but)
            # SN
            item = QtWidgets.QTableWidgetItem(para.sn)
            self.parameterTable.setItem(i, 1, item)
            # Parameter
            item = QtWidgets.QTableWidgetItem(para.parameter)
            self.parameterTable.setItem(i, 2, item)
            # Date
            item = QtWidgets.QTableWidgetItem(para.date)
            self.parameterTable.setItem(i, 3, item)
            # Comment
            item = QtWidgets.QTableWidgetItem(para.comment)
            self.parameterTable.setItem(i, 4, item)

        self.parameterTable.resizeColumnsToContents()
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
