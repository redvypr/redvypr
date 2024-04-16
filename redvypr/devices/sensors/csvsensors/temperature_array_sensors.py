import datetime
import redvypr.data_packets as data_packets
import numpy
import logging
import zoneinfo
import pydantic
import typing
import sys
import logging
from PyQt5 import QtWidgets, QtCore, QtGui
from .calibration_models import calibration_HF, calibration_NTC, get_date_from_calibration
from .average_data import average_data

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('temperature_array_sensors')
logger.setLevel(logging.DEBUG)

avg_objs_TAR_raw = {}  # Average dataobjects


class parameter_TAR(pydantic.BaseModel):
    NTC_A: typing.Optional[typing.List[calibration_NTC]] = pydantic.Field(default=[])
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
                parameter_name = 'NTC{:d}'.format(i)
                ntc_coeff = [1.9560290742146262e-07, -7.749325133113135e-08, 0.00025341112950681254,
                             0.0012350747622505245]
                coeff_comment = 'Standard coefficients, not calibration'
                NTCcal = calibration_NTC(parameter=parameter_name, coeff=ntc_coeff, comment=coeff_comment)
                self.parameter.NTC_A.append(NTCcal)
                self.parameter.pos_x.append(pos_x)
                #print('Adding parameter',parameter_name)
                pos_x += dx_positions


def process_TAR_data(dataline, data, device_info, loggerconfig):
    funcname = __name__ + '.process_TAR_data():'
    datapackets_return = []
    try:
        datapacket_TAR = process_TAR_raw(dataline, data, device_info)
    except:
        logger.info(' Could not decode {:s}'.format(str(dataline)), exc_info=True)
        datapacket_TAR = None

    if datapacket_TAR is not None:
        datapackets_return.append(datapacket_TAR)
        # Convert to temperature
        devicename = 'TAR_SI_' + datapacket_TAR['sn']
        datapacket_TAR_T = data_packets.datapacket(device=devicename, tu=datapacket_TAR['_redvypr']['t'],
                                                   hostinfo=device_info['hostinfo'])
        datapacket_TAR_T['type'] = datapacket_TAR['type']
        datapacket_TAR_T['np'] = datapacket_TAR['np']
        datapacket_TAR_T['sn'] = datapacket_TAR['sn']
        datapacket_TAR_T['t'] = datapacket_TAR['t']
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
        print('Datapacket TAR', datapacket_TAR_T)
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
        datapacket_redvypr = data_packets.datapacket(device=devicename, tu=data['_redvypr']['t'],
                                                     hostinfo=device_info['hostinfo'])
        datapacket_redvypr.update(datapacket)

        return datapacket_redvypr


# Temperature array
def parse_TAR_raw(data, sensortype='TAR'):
    """
    Parses temperature array
    $FC0FE7FFFE155D8C,TAR,B2,36533.125000,83117,3498.870,3499.174,3529.739,3490.359,3462.923,3467.226,3480.077,3443.092,3523.642,3525.567,3509.492,3561.330,3565.615,3486.693,3588.670,3539.169,3575.104,3523.946,3496.343,3480.160,3531.045,3501.624,3497.010,3557.235,3479.952,3458.297,3523.052,3487.223,3571.087,3525.740,3580.928,3534.818
    """
    print('Got data', data)
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
            poly = [1.9560290742146262e-07, -7.749325133113135e-08, 0.00025341112950681254, 0.0012350747622505245]
            Toff = 273.15
            # print('Poly', poly)
            data_tmp = numpy.polyval(poly, numpy.log(data))
            # print('data_tmp', data_tmp)
            data_tmp = 1 / data_tmp - Toff
            dataSI = data_tmp
            #print('data_SI', dataSI,type(dataSI))
            #datapacket[parameter] = float(dataSI)
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
        print('Devicename',devicename)
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