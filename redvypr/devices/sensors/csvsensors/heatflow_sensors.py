import datetime
import redvypr.data_packets as data_packets
import numpy
import logging
import sys
import zoneinfo
from PyQt5 import QtWidgets, QtCore, QtGui
import pydantic
import typing
from redvypr.devices.plot import XYplotWidget
from redvypr.devices.plot import plot_widgets
from redvypr.redvypr_address import RedvyprAddress
from redvypr.devices.sensors.calibration.calibration_models import calibration_HF, calibration_NTC
import redvypr.gui as gui
from .sensorWidgets import sensorCoeffWidget, sensorConfigWidget


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('heatflow_sensors')
logger.setLevel(logging.DEBUG)


class parameter_DHFS50(pydantic.BaseModel):
    HF: calibration_HF = calibration_HF(parameter='HF')
    NTC0: calibration_NTC = calibration_NTC(parameter='NTC0')
    NTC1: calibration_NTC = calibration_NTC(parameter='NTC1')
    NTC2: calibration_NTC = calibration_NTC(parameter='NTC2')

class sensor_DHFS50(pydantic.BaseModel):
    description: str = 'Digital heat flow sensor DHFS50'
    sensor_type: typing.Literal['DHFS50'] = 'DHFS50'
    sensor_model: str = 'DHFS50'
    sensor_configuration: str = 'DHFS50-1m'
    parameter: parameter_DHFS50 = parameter_DHFS50()
    sn: str = pydantic.Field(default='', description='The serial number and/or MAC address of the sensor')
    comment: str = pydantic.Field(default='')
    convert_rawdata: bool = pydantic.Field(default=True, description='Uses the calibrations of the parameter to convert rawdata into meaningful units')
    avg_data: list = pydantic.Field(default=[60, 300], description='List of averaging intervals')
    show_rawdata: bool = pydantic.Field(default=True, description='Show the raw data in the gui')
    show_convdata: bool = pydantic.Field(default=True, description='Show the converted data in the gui')

class channels_HFV4CH(pydantic.BaseModel):
    C0: calibration_HF = calibration_HF(parameter='C0')
    C1: calibration_HF = calibration_HF(parameter='C1')
    C2: calibration_HF = calibration_HF(parameter='C2')
    C3: calibration_HF = calibration_HF(parameter='C3')

class logger_HFV4CH(pydantic.BaseModel):
    description: str = '4 Channel voltage logger'
    sensor_type: typing.Literal['hfv4ch'] = 'hfv4ch'
    logger_model: str = '4 Channel ADS logger'
    logger_configuration: str = 'Raspberry PI board'
    channels: channels_HFV4CH = channels_HFV4CH()
    sn: str = pydantic.Field(default='', description='The serial number and/or MAC address of the sensor')
    comment: str = pydantic.Field(default='')


def convert_HF(datapacket, loggerconfigurations=None):
    """
    Converts raw data into SI units
    """
    funcname = 'convert_HF():'
    logger.debug(funcname)
    try:
        mac = datapacket['sn']
    except:
        mac = None

    #datapacketSI = {}
    devicename = 'DHF_SI_' + mac
    datapacketSI = data_packets.create_datadict(device=devicename, hostinfo=datapacket['_redvypr']['host'], tu=datapacket['t'])


    datapacketSI['type'] = 'HFSI'
    datapacketSI['sensortype'] = datapacket['sensortype']
    datapacketSI['sn'] = datapacket['sn']
    datapacketSI['ts'] = datapacket['ts']
    datapacketSI['np'] = datapacket['np']
    datapacketSI['tUTC'] = datetime.datetime.utcfromtimestamp(datapacket['t']).isoformat(sep=' ',
                                                                                         timespec='milliseconds')
    #print('loggerconfigs',loggerconfigurations)
    if (mac is not None) and (loggerconfigurations is not None):
        flag_mac_calib = False
        try:
            c = loggerconfigurations[mac]
        except:
            c = None

        if c is not None:
            datapacketSI['datatype'] = 'converted_cal'  # Here the id of the calibration could be added
            #print('Found configuration',c)
            if True:
                flag_mac_calib = True
                logger.debug(funcname + 'Found calibration for {:s}, converting'.format(mac))
                for parameter_tuple in c.parameter:
                    parameter = parameter_tuple[0]
                    parameter_calibration = parameter_tuple[1]
                    coeff = parameter_calibration.coeff
                    if parameter == 'HF':
                        data = datapacket['HF']
                        dataSI = data * coeff * 1000
                        datapacketSI['HF'] = dataSI
                    elif 'NTC' in parameter:
                        # Convert data using a Hoge (Steinhardt-Hart) Type of Equation
                        # print('NTC', parameter, coeff['coeff'])
                        if parameter in datapacket.keys():
                            poly = coeff
                            Toff = parameter_calibration.Toff
                            # print('Poly', poly)
                            data = datapacket[parameter]
                            data_tmp = numpy.polyval(poly, numpy.log(data))
                            # print('data_tmp', data_tmp)
                            data_tmp = 1 / data_tmp - Toff
                            dataSI = data_tmp
                            # print('data_SI', dataSI)
                            datapacketSI[parameter] = dataSI

                return datapacketSI

        if flag_mac_calib == False:
            logger.debug(funcname + 'Did not find calibration for {:s}'.format(mac))
            return None

    return None


def parse_HF_raw(data, sensortype='DHFS50', datapacket=None):
    """
    b'$FC0FE7FFFE167225,HF,00012848.3125,6424,-0.001354,848.389,848.389,852.966\n'
    """
    datasplit = data.split(',')
    macstr = datasplit[0][1:17]
    packettype = datasplit[1]  # HF
    if datapacket is None:
        datapacket = {}
    datapacket['type'] = packettype
    datapacket['sn'] = macstr
    datapacket['sensortype'] = sensortype
    valid_package = False
    if len(datasplit) == 8:
        ts = float(datasplit[2])  # Sampling time
        np = int(datasplit[3])  # Number of packet
        datapacket['HF'] = float(datasplit[4])
        datapacket['NTC0'] = float(datasplit[5])
        datapacket['NTC1'] = float(datasplit[6])
        datapacket['NTC2'] = float(datasplit[7])
        datapacket['ts'] = ts
        datapacket['np'] = np
        valid_package = True

    if valid_package:
        return datapacket
    else:
        return None



def parse_HFS_raw(data, sensortype='DHFS50'):
    """
    HFS SI data from the sensor itself
    """
    datasplit = data.split(',')
    macstr = datasplit[0][1:17]
    packettype = datasplit[1]  # HFS
    datapacket = {}
    datapacket['type'] = packettype
    datapacket['sn'] = macstr
    datapacket['sensortype'] = sensortype
    valid_package = False
    if len(datasplit) == 8:
        ts = float(datasplit[2])  # Sampling time
        np = int(datasplit[3])  # Number of packet
        datapacket['HF'] = float(datasplit[4])
        datapacket['NTC0'] = float(datasplit[5])
        datapacket['NTC1'] = float(datasplit[6])
        datapacket['NTC2'] = float(datasplit[7])
        datapacket['ts'] = ts
        datapacket['np'] = np
        valid_package = True

    if valid_package:
        return datapacket
    else:
        return None


def add_keyinfo_HF_raw(datapacket):
    """
    Adds keyinfo to the HF_raw datapacket
    """
    macstr = datapacket['sn']
    # print('Datapacket', datapacket)
    keys = list(datapacket.keys())
    for dkey in keys:
        # print(funcname + ' datakey {:s}'.format(dkey))
        if 'NTC' in dkey:
            unit = 'ohm'
        elif 'HF' in dkey:
            unit = 'V'
        elif dkey == 'T':
            unit = 'CNT'
        else:
            unit = 'NA'

        # print('Datakeyinfo',unit,macstr,dkey)
        data_packets.add_keyinfo2datapacket(datapacket, datakey=dkey,
                                            unit=unit, description=None,
                                            infokey='sn', info=macstr)
        data_packets.add_keyinfo2datapacket(datapacket, datakey=dkey,
                                            infokey='sensortype', info='DHFS50')
    return datapacket


def parse_IMU_raw(data, sensortype='DHFS50'):
    """
    b'$FC0FE7FFFE167225,IMU,00012848.3125,6424,-24534,32,-1,-129,-249,0,43872,-7,-1,-75\n'
    """
    datasplit = data.split(',')
    macstr = datasplit[0][1:17]
    packettype = datasplit[1]  # IMU
    datapacket = {}
    datapacket['type'] = packettype
    datapacket['sn'] = macstr
    datapacket['sensortype'] = sensortype
    acc = []
    gyro = []
    mag = []
    T = -9999.9
    valid_package = False
    if len(datasplit) == 14:
        ts = float(datasplit[2])  # Sampling time
        np = int(datasplit[3])  # Number of packet
        # print('{:f} {:d}'.format(ts,np))
        # print('datasplit',datasplit)
        ind_acc = 4
        ind_gyro = 7
        ind_T = 10
        ind_mag = 11
        for n in range(3):
            acc.append(int(datasplit[ind_acc + n]))
        for n in range(3):
            gyro.append(int(datasplit[ind_gyro + n]))
        for n in range(3):
            mag.append(int(datasplit[ind_mag + n]))

        T = int(datasplit[ind_T])
        valid_package = True
        datapacket['acc'] = acc
        datapacket['gyro'] = gyro
        datapacket['mag'] = mag
        datapacket['T'] = T
        datapacket['ts'] = ts
        datapacket['np'] = np

    if valid_package:
        return datapacket
    else:
        return None


def parse_HFV_raw(data, sensortype='PIBOARD'):
    """
    b'$KAL1,HFV,2023-11-03 05:30:29.589,0,-0.021414,1,-0.870808,2,-0.019380,3,-0.000244'
    """
    funcname = __name__ + '.parse_HFV_raw():'
    logger.debug(funcname)

    datasplit = data.split(',')
    snstr = datasplit[0][1:]
    packettype = datasplit[1]  # HFV
    tstr = datasplit[2]
    td = datetime.datetime.strptime(tstr, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=zoneinfo.ZoneInfo('UTC'))

    datapacket = {}
    datapacket['type'] = packettype
    datapacket['sn'] = snstr
    datapacket['sensortype'] = sensortype
    datapacket['t'] = td.timestamp()
    for i in range(0, 8, 2):
        ch = datasplit[3 + i]
        voltage = datasplit[3 + i + 1]
        channelname = 'C' + str(ch)
        datapacket[channelname] = float(voltage)

    return datapacket


def process_IMU_packet(dataline,data, macstr, macs_found):
    funcname = __name__ + '.process_IMU_packet()'
    datapacket = parse_IMU_raw(dataline)
    datapacket['t'] = data['t']
    datapacket['devicename'] = 'DHF_raw_' + macstr
    if macstr not in macs_found['IMU']:
        logger.debug(funcname + 'New MAC found, will add datakeyinfo')
        # print('Datapacket', datapacket)
        keys = list(datapacket.keys())
        for dkey in keys:
            # print(funcname + ' datakey {:s}'.format(dkey))
            unit = 'CNT'
            data_packets.add_keyinfo2datapacket(datapacket, datakey=dkey,
                                                unit=unit, description=None,
                                                infokey='sn', info=macstr)
            data_packets.add_keyinfo2datapacket(datapacket, datakey=dkey,
                                                infokey='sensortype', info='DHFS50')

        macs_found['IMU'].append(macstr)
    # print('IMU packet',datapacket)


def process_HF_data(dataline, data, device_info, sensorconfig, config, macs_found):
    """
    Processes Heatflow raw data
    """
    funcname = __name__ + '.process_HF_data():'
    datapackets = []
    datapacket = parse_HF_raw(dataline)

    macstr = datapacket['sn']
    sn = datapacket['sn']
    if datapacket is not None:
        devicename = 'DHF_raw_' + macstr
        datapacket['datatype'] = 'raw'
        datapacket['t'] = data['_redvypr']['t']
        datapacket_HF = data_packets.create_datadict(device=devicename, hostinfo=device_info['hostinfo'], tu=data['t'])
        datapacket_HF.update(datapacket)
        if macstr not in macs_found['HF']:
            logger.debug(funcname + 'New MAC found, will add keyinfo')
            datapacket_HF = add_keyinfo_HF_raw(datapacket_HF)

            # print('datapacket',datapacket)
            macs_found['HF'].append(macstr)
        # Convert the data (if calibration found)
        datapackets.append(datapacket_HF)
        if sensorconfig is not None:
            flag_convert = config.sensorconfigurations[sn].convert_rawdata
            if flag_convert:
                datapacket_HFSI = convert_HF(datapacket_HF, config.sensorconfigurations)               # print('datapacket hfsi',datapacket_HFSI)
                # print('sn {:s}', sn)
                if datapacket_HFSI is not None:
                    # Check if units should be set, this is only done once
                    if macstr not in macs_found['HFSI']:
                        logger.debug(funcname + 'New MAC found, will add keyinfo')
                        # print('Datapacket', datapacket)
                        keys = list(datapacket.keys())
                        for dkey in keys:
                            # print(funcname + ' datakey {:s}'.format(dkey))
                            if 'NTC' in dkey:
                                unit = 'degC'
                            elif 'HF' in dkey:
                                unit = 'W m-2'
                            else:
                                unit = 'NA'

                            # print('Datakeyinfo', unit, macstr, dkey)
                            data_packets.add_keyinfo2datapacket(datapacket_HFSI,
                                                                datakey=dkey,
                                                                unit=unit,
                                                                description=None,
                                                                infokey='sn',
                                                                info=macstr)
                            data_packets.add_keyinfo2datapacket(datapacket_HFSI,
                                                                datakey=dkey,
                                                                infokey='sensortype',
                                                                info='DHFS50')

                        # print('datapacket', datapacket)
                        macs_found['HFSI'].append(macstr)

                datapackets.append(datapacket_HFSI)
        # print('HF packet',datapacket)
        print('DATAPACKETS')
        print('datapackets',datapackets)
        print('DATAPACKETS')
        return datapackets


def process_HFS_data(dataline, data, device_info):
    try:
        datapacket = parse_HFS_raw(dataline)
    except:
        logger.debug(' Could not decode {:s}'.format(str(dataline)), exc_info=True)
        datapacket = None

    if datapacket is not None:
        macstr = datapacket['sn']
        devicename = 'DHF_SI_' + macstr
        datapacket_HFSI = data_packets.create_datadict(device=devicename, hostinfo=device_info['hostinfo'], tu=data['t'])
        datapacket_HFSI['type'] = 'HFSI'
        datapacket_HFSI['datatype'] = 'converted_' + macstr
        datapacket_HFSI.update(datapacket)
        return datapacket_HFSI

        # Averaging the data
        if False:
            dataqueue.put(datapacket_HFS)
            # Do averaging.
            sn = datapacket_HFS['sn']
            try:
                datapacket_HFS_avg = avg_objs[sn].average_data(data)
            except:
                parameters = ['t', 'HF', 'NTC0', 'NTC1', 'NTC2']
                avg_objs[sn] = average_datapacket(datapacket_HFS, parameters, loggerconfig)
                datapacket_HFS_avg = avg_objs[sn].average_data(data)
                logger.debug(funcname + ' could not average:', exc_info=True)

            if datapacket_HFS_avg is not None:
                dataqueue.put(datapacket_HFS_avg)


        return datapacket_HFSI




#
#
# Here the widgets start
#
#
class DHFS50Widget_config(QtWidgets.QWidget):
    """
    Widget to configure a DHFS50 logger
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
            self.device.custom_config.sensorconfigurations[self.sn]
            logger.debug(funcname + ' Found a configuration')
        except:
            logger.warning(funcname + ' Did not find a configuration')
            return

        self.layout = QtWidgets.QGridLayout(self)
        self.coeffInput = []
        self.coeff_widget = QtWidgets.QTabWidget()
        print('Configuration', self.device.custom_config.sensorconfigurations[self.sn])
        snlabel = QtWidgets.QLabel('DHFS50 calibration coefficients of\n' + self.sn)
        self.layout.addWidget(snlabel,0,0)

        nparameter = len(list(self.device.custom_config.sensorconfigurations[self.sn].parameter))

        #self.coeff_table = QtWidgets.QTableWidget()
        #self.coeff_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.layout.addWidget(self.coeff_widget, 2, 0)

        self.parameter_buttons = {}
        self.parameter_widgets = {}
        self.parameter_calwidgets = {}
        for i,k_tmp in enumerate(self.device.custom_config.sensorconfigurations[self.sn].parameter):
            k = k_tmp[0]
            calibration = k_tmp[1]
            self.parameter_widgets[k] = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(self.parameter_widgets[k])
            self.parameter_buttons[k] = QtWidgets.QPushButton('Choose calibration')
            self.parameter_buttons[k].clicked.connect(self.choose_calibration)
            self.parameter_buttons[k].parameter = k
            layout.addWidget(self.parameter_buttons[k])
            calwidget = gui.pydanticQTreeWidget(calibration,dataname = k)
            self.parameter_calwidgets[k] = calwidget
            layout.addWidget(calwidget)
            self.coeff_widget.addTab(self.parameter_widgets[k], k)
            #self.layout.addWidget(self.parameter_buttons[k], 1, i+0)

        #self.fill_coeff_table()

    def choose_calibration(self):
        """
        Let the user choose a calibration for the parameter
        """
        but = self.sender()

        funcname = __name__ + '.choose_calibration():'
        logger.debug(funcname)
        self._sensor_choose_dialog = sensorCoeffWidget(redvypr_device=self.device)
        #self._sensor_choose_dialog.coeff.connect(self.calibration_chosen)
        #self._sensor_choose_dialog.parameter = self.sender().parameter
        self._sensor_choose_dialog.show()

    def calibration_chosen(self, calibration_sent):
        funcname = __name__ + '.calibration_chosen():'
        logger.debug(funcname)
        #print('Coeff sent',calibration_sent)
        calibration_new = calibration_sent['calibration']
        # Use only the chosen parameter, remove the rest
        parameter = self.sender().parameter
        # print('Coeff',coeff,'sn',sn,'channel',channel)
        ## Make a test configuration for KAL1
        # channelconfig = redvypr_config.configuration(calibration_template_channel)
        # channelconfig['sn'] = self.nosensorstr  # The serialnumber of the channel
        if True:
            logger.debug('Adding {} to channel {:s}'.format(calibration_sent, parameter))
            #channels = self.device.config.sensorconfigurations[self.sn].channels
            #setattr(channels, channelname, calibration)
            calibration_old = self.device.custom_config.sensorconfigurations[self.sn].parameter
            print('calibration_old', type(calibration_old))
            print('calibration_new', type(calibration_sent))
            print('hallohallo',calibration_old.model_validate(calibration_new))
            # Check if the new coefficients fit
            try:
                calibration_old.model_validate(calibration_new)
                setattr(self.device.custom_config.sensorconfigurations[self.sn].parameter, parameter, calibration_new)
                self.parameter_calwidgets[parameter].reload_data(calibration_new)
            except:
                logger.debug('Calibration format does not fit',exc_info = True)



        #self.fill_coeff_table()
        print('configuration', self.device.custom_config.sensorconfigurations[self.sn])


#
#
#
#
#
class HFVWidget_config(QtWidgets.QWidget):
    """
    Widget to display information from a 4 Channel Voltage board
    """

    def __init__(self, *args, sn=None, redvypr_device=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        self.device = redvypr_device
        self.nosensorstr = ''
        self.sn = sn

        # Get the channel names
        ch_tmp = channels_HFV4CH()
        self.channelnames = []
        for i, ch in enumerate(ch_tmp):
            print(ch)
            self.channelnames.append(ch[0])

        print('Channelsnames',self.channelnames)

        # Try to find a configuration for the logger
        try:
            self.device.custom_config.sensorconfigurations[self.sn]
            logger.debug(funcname + ' Found a configuration')
        except:
            logger.warning(funcname + ' Did not find a configuration')
            return

        self.layout = QtWidgets.QGridLayout(self)
        self.coeffInput = []
        self.coeff_widget = QtWidgets.QWidget()
        self.create_coeff_widget()
        self.layout.addWidget(self.coeff_widget, 0, 0, 1, 2)


    def create_coeff_widget(self):
        """

        """
        # Coeffs
        # Serialnum
        # Sensortype
        # Comment
        # Show converted data

        self.coeff_layout = QtWidgets.QGridLayout(self.coeff_widget)
        self.use_coeff_checks = []
        self.serialnum_texts = []
        self.comment_texts = []
        self.sensor_choose_buttons = []

        # Get the channel names
        for i,chname in enumerate(self.channelnames):
            but = QtWidgets.QPushButton('Sensor {:s}'.format(chname))
            but.clicked.connect(self.choose_sensor)
            self.sensor_choose_buttons.append(but)
            self.coeff_layout.addWidget(but,0,i)
            but.channelname  = chname
            but.channelindex = i

        row = 0
        col = 0
        self.coeff_table = QtWidgets.QTableWidget()
        self.coeff_layout.addWidget(self.coeff_table, 1, 0,1,4)

        self.index_serialnum = 0
        self.index_coeff = 2
        self.index_model = 1
        self.index_date = 3
        self.index_fname = 4

        # Fill table with configuration data
        #addresses = ["<broadcast>", "<IP>", myip]
        #completer = QtWidgets.QCompleter(addresses)
        #self.addressline.setCompleter(completer)
        self.fill_coeff_table()

    def sensor_chosen(self,coeff_sent):
        funcname = __name__ + '.sensor_chosen():'
        logger.debug(funcname)

        calibration = coeff_sent['calibration']#
        sn = calibration.sn
        # Use only the chosen parameter, remove the rest
        channelname = self.sender().channelname
        #print('Coeff',coeff,'sn',sn,'channel',channel)
        ## Make a test configuration for KAL1
        #channelconfig = redvypr_config.configuration(calibration_template_channel)
        #channelconfig['sn'] = self.nosensorstr  # The serialnumber of the channel
        if sn == self.nosensorstr:
            logger.debug(funcname + 'Removing sensor')
        else:
            logger.debug('Adding {:s} to channel {:s}'.format(sn, channelname))
            channels = self.device.custom_config.sensorconfigurations[self.sn].channels
            setattr(channels,channelname,calibration)

        self.fill_coeff_table()
        #print('configuration',self.device.config['sensorconfigurations'][self.sn])

    def choose_sensor(self):
        """
        Let the user choose a sensor for the channel
        """
        but = self.sender()

        funcname = __name__ + '.choose_sensor():'
        logger.debug(funcname)
        self._sensor_choose_dialog = sensorCoeffWidget(redvypr_device=self.device)
        self._sensor_choose_dialog.coeff.connect(self.sensor_chosen)
        self._sensor_choose_dialog.channelname = self.sender().channelname
        self._sensor_choose_dialog.show()


    def fill_coeff_table(self):
        """

        """
        funcname = __name__ + '.fill_coeff_table()'
        logger.debug(funcname)


        self.coeff_table.clear()
        self.coeff_table.setRowCount(5)
        self.coeff_table.setColumnCount(len(self.channelnames))
        self.coeff_table.setVerticalHeaderLabels(
            ['Serialnum', 'Model', 'Coefficient', 'Calibration date', 'Comment'])
        self.coeff_table.setHorizontalHeaderLabels(self.channelnames )
        for ch,ch_tmp in enumerate(self.device.custom_config.sensorconfigurations[self.sn].channels):
            chstr = ch_tmp[0]
            sn_sensor_attached = None
            channels = self.device.custom_config.sensorconfigurations[self.sn].channels
            calibration = getattr(channels,chstr)
            print('Got channel',calibration)
            sn_sensor_attached = calibration.sn

            if sn_sensor_attached is None:
                logger.warning('Could not find coeffcients for {:s}'.format(sn_sensor_attached))
                continue
            elif len(sn_sensor_attached) == 0:
                logger.warning('No sensor attached at channel {:s}'.format(chstr))
                continue
            else:
                print('Using calibration',calibration)
                # Try to find coefficients for the sensor
                try:
                    coeff = str(calibration.coeff)
                except Exception as e:
                    coeff = numpy.NaN
                    logger.debug(funcname)
                    logger.exception(e)
                    logger.debug(funcname)

                #
                try:
                    fname = str(calibration['original_file'])
                except Exception as e:
                    fname = ''
                    logger.debug(funcname, exc_info=True)

                # Try to find coefficients for the sensor
                try:
                    coeff_date = str(calibration.date)
                except Exception as e:
                    coeff_date = ''
                    logger.debug(funcname)
                    logger.exception(e)
                    logger.debug(funcname)

                # Try to find coefficients for the sensor
                try:
                    model = str(calibration.sensor_model)
                except Exception as e:
                    model = ''
                    logger.debug(funcname)
                    logger.exception(e)
                    logger.debug(funcname)

                index_col = ch
                index_row = self.index_serialnum
                item = QtWidgets.QTableWidgetItem(str(sn_sensor_attached))
                self.coeff_table.setItem(index_row,index_col,item)

                if coeff is numpy.NaN:
                    coeffstr = ''
                else:
                    coeffstr = str(coeff)

                index_row = self.index_coeff
                item = QtWidgets.QTableWidgetItem(coeffstr)
                self.coeff_table.setItem(index_row, index_col, item)

                index_row = self.index_model
                item = QtWidgets.QTableWidgetItem(str(model))
                self.coeff_table.setItem(index_row, index_col, item)

                index_row = self.index_date
                item = QtWidgets.QTableWidgetItem(str(coeff_date))
                self.coeff_table.setItem(index_row, index_col, item)

                #index_row = self.index_fname
                #item = QtWidgets.QTableWidgetItem(str(fname))
                #self.coeff_table.setItem(index_row, index_col, item)

        self.coeff_table.resizeColumnsToContents()

class HFVWidget(QtWidgets.QWidget):
    """
    Widget to display information from a 4 Channel Voltage board
    """

    def __init__(self, *args, sn=None, redvypr_device=None):
        funcname = __name__ + '__init__()'
        super(QtWidgets.QWidget, self).__init__(*args)
        logger.debug(funcname)
        self.device = redvypr_device

        self.sn = sn
        # Try to find a configuration for the logger
        try:
            self.device.custom_config.sensorconfigurations[self.sn]
            logger.debug(funcname + ' Found a configuration')
        except:
            logger.warning(funcname + ' Did not find a configuration, will need to create one')
            return
            # Make a test configuration for KAL1
            #channelconfig = config.configuration(calibration_template_channel)

        self.rawconvtabs = QtWidgets.QTabWidget()

        # Add table with the data (raw data)
        self.datatable_raw = QtWidgets.QTableWidget()
        self.datatable_raw.setColumnCount(6)
        self.datatable_raw.setRowCount(2)
        self.datatable_raw.resizeRowsToContents()
        self.datatable_raw.horizontalHeader().hide()
        self.datatable_raw.verticalHeader().hide()
        self.datatable_raw.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.datatable_raw.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        # Add table with the data (converted data)
        self.datatable_conv = QtWidgets.QTableWidget()
        self.datatable_conv.setColumnCount(6)
        self.datatable_conv.setRowCount(2)
        self.datatable_conv.horizontalHeader().hide()
        self.datatable_conv.verticalHeader().hide()
        self.datatable_conv.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.datatable_conv.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        # Fill the tables
        for i in range(4):
            item = QtWidgets.QTableWidgetItem('CH' + str(i))
            self.datatable_raw.setItem(0, i + 1, item)
            item = QtWidgets.QTableWidgetItem('CH' + str(i))
            self.datatable_conv.setItem(0, i + 1, item)

        item = QtWidgets.QTableWidgetItem('Time')
        self.datatable_raw.setItem(0, 0, item)
        item = QtWidgets.QTableWidgetItem('Time')
        self.datatable_conv.setItem(0, 0, item)
        item = QtWidgets.QTableWidgetItem('Unit')
        self.datatable_raw.setItem(0, 5, item)
        item = QtWidgets.QTableWidgetItem('Unit')
        self.datatable_conv.setItem(0, 5, item)
        item = QtWidgets.QTableWidgetItem('V')
        self.datatable_raw.setItem(1, 5, item)
        item = QtWidgets.QTableWidgetItem('Wm-2')
        self.datatable_conv.setItem(1, 5, item)

        self.layout = QtWidgets.QGridLayout(self)
        self.layout.addWidget(self.rawconvtabs,0,0)

        self.rawdatawidget = QtWidgets.QWidget()
        rawlayout = QtWidgets.QGridLayout(self.rawdatawidget)
        rawlayout.addWidget(self.datatable_raw, 0, 0, 1, 2)

        self.convdatawidget = QtWidgets.QWidget()
        convlayout = QtWidgets.QGridLayout(self.convdatawidget)
        convlayout.addWidget(self.datatable_conv, 0, 0, 1, 2)


        self.plot_widgets_HFV = []
        self.plot_widgets_HFVSI = []
        self.coeffInput = []
        self.layout.setRowStretch(0, 1)
        row = 0
        col = 0
        for i in range(4):
            # Create plots
            plot_widgets.logger.setLevel(logging.INFO)
            config = XYplotWidget.configXYplot(title='Voltage CH{:d}'.format(i))
            plot_widget_HFV = XYplotWidget.XYplot(config=config, redvypr_device=self.device.redvypr)
            # Subscribe to channel
            plot_widget_HFV.set_line(0, 'C{:d}'.format(i) + '/{HFV_raw_.*}', name='HFV C{:d}'.format(i), color='red', linewidth=2)
            self.plot_widgets_HFV.append(plot_widget_HFV)
            rawlayout.addWidget(plot_widget_HFV, row+1, col)
            rawlayout.setRowStretch(row+1, 3)

            config = XYplotWidget.configXYplot(title='Heat flow CH{:d}'.format(i))
            plot_widget_HFVSI = XYplotWidget.XYplot(config=config, redvypr_device=self.device.redvypr)
            # Subscribe to channel
            plot_widget_HFVSI.set_line(0, 'C{:d}'.format(i) + '/{HFV_SI_.*}', name='HFVSI C{:d}'.format(i), color='red',
                                     linewidth=2)
            self.plot_widgets_HFVSI.append(plot_widget_HFVSI)
            convlayout.addWidget(plot_widget_HFVSI, row + 1, col)
            convlayout.setRowStretch(row + 1, 1)

            col += 1
            if col > 1:
                col = 0
                row += 1

        self.rawconvtabs.addTab(self.rawdatawidget,'Raw data')
        self.rawconvtabs.addTab(self.convdatawidget, 'Converted data')


    def update(self, data):
        """
        Updating the local data with datapacket
        """
        funcname = __name__ + '.update()'
        logger.debug(funcname)
        mac = data['sn']
        if mac in self.sn:
            #print(funcname + ' Got data',data)
            # Update table
            if data['type'] == 'HFV':  # Raw data
                tdata = datetime.datetime.utcfromtimestamp(data['t'])
                tdatastr = tdata.strftime('%Y-%m-%d %H:%M:%S.%f')
                item = QtWidgets.QTableWidgetItem(tdatastr)
                self.datatable_raw.setItem(1,0, item)
                for chi in range(4):
                    channelname = 'C' + str(chi)
                    chdata = "{:+.6f}".format(data[channelname])
                    item = QtWidgets.QTableWidgetItem(str(chdata))
                    self.datatable_raw.setItem(1, chi + 1, item)

                #self.datatable_raw.resizeColumnsToContents()
                for i in range(4):
                    try:
                        #print('data',data,i)
                        self.plot_widgets_HFV[i].update_plot(data)
                    except Exception as e:
                        pass
            elif data['type'] == 'HFVSI':  # Converted data
                try:
                    tdata = datetime.datetime.utcfromtimestamp(data['t'])
                    tdatastr = tdata.strftime('%Y-%m-%d %H:%M:%S.%f')
                    item = QtWidgets.QTableWidgetItem(tdatastr)
                    self.datatable_conv.setItem(1, 0, item)
                    for chi in range(4):
                        try:
                            channelname = 'C' + str(chi)
                            chdata = "{:+.6f}".format(data[channelname])
                            item = QtWidgets.QTableWidgetItem(str(chdata))
                            self.datatable_conv.setItem(1, chi + 1, item)
                        except:
                            pass
                except:
                    pass

                for i in range(4):
                    print('Updating')
                    try:
                        self.plot_widgets_HFVSI[i].update_plot(data)
                    except Exception as e:
                        logger.info('Error',exc_info=True)
                        pass



class DHFSWidget(QtWidgets.QWidget):
    """
    Widget to display Digital Heat flow sensor data
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
                self.configuration = self.device.custom_config.sensorconfigurations[sn]
            except Exception as e:
                logger.exception(e)

        #self.parameter = ['HF', 'NTC0', 'NTC1', 'NTC2']
        self.parameter = []
        self.parameter_unit = []
        self.parameter_unitconv = []
        print('Adding parameter')
        for ptmp in self.configuration.parameter:
            print('Parameter',ptmp)
            p = ptmp[0]
            self.parameter.append(p)
            self.parameter_unit.append(None)
            self.parameter_unitconv.append(None)

        #self.create_coeff_widget()
        self.XYplots = []
        self.layout = QtWidgets.QVBoxLayout(self)
        self.hlayout = QtWidgets.QHBoxLayout(self)
        self.configButton = QtWidgets.QPushButton('Configure')
        self.configButton.clicked.connect(self.__configClicked__)
        # Add a widget for the raw data
        self.rawdataWidget = QtWidgets.QWidget()
        self.rawdataWidget_layout = QtWidgets.QVBoxLayout(self.rawdataWidget)
        label = QtWidgets.QPushButton('Raw data')
        label.setEnabled(False)
        self.rawdataWidget_layout.addWidget(label)
        # Add a table for the raw data
        self.datatable_raw = QtWidgets.QTableWidget()
        self.rawdataWidget_layout.addWidget(self.datatable_raw)
        # number of columns
        ncols = 4
        self.datatable_raw.setColumnCount(ncols)
        self.datatable_raw_parameterheader = ['Time']
        for i, p in enumerate(self.parameter):
            self.datatable_raw_parameterheader.append(p)

        self.datatable_raw.setRowCount(len(self.datatable_raw_parameterheader))
        self.datatable_raw.setVerticalHeaderLabels(self.datatable_raw_parameterheader)
        self.datatable_raw.setHorizontalHeaderLabels(['Parameter','Unit','Data'])
        self.datatable_raw.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.datatable_raw.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        # Converted data
        self.convdataWidget = QtWidgets.QWidget()
        self.convdataWidget_layout = QtWidgets.QVBoxLayout(self.convdataWidget)
        label = QtWidgets.QPushButton('Converted data')
        label.setEnabled(False)
        self.convdataWidget_layout.addWidget(label)
        # Add a table for the conv data
        self.datatable_conv = QtWidgets.QTableWidget()
        self.convdataWidget_layout.addWidget(self.datatable_conv)
        self.datatable_conv.setColumnCount(ncols)
        self.datatable_conv.setRowCount(len(self.datatable_raw_parameterheader))
        self.datatable_conv.setVerticalHeaderLabels(self.datatable_raw_parameterheader)
        self.datatable_conv.setHorizontalHeaderLabels(['Parameter', 'Unit', 'Data'])
        self.datatable_conv.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.datatable_conv.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)


        if self.configuration.show_rawdata:
            self.hlayout.addWidget(self.rawdataWidget)
        if self.configuration.show_convdata:
            self.hlayout.addWidget(self.convdataWidget)

        self.layout.addLayout(self.hlayout)
        self.layout.addWidget(self.configButton)
        self.add_XYplots()


    def __configClicked__(self):

        #self.configWidget = DHFS50Widget_config(sn = self.sn, redvypr_device=self.device)
        self.configWidget = sensorConfigWidget(sensor=self.configuration, calibrations=self.device.custom_config.calibrations)
        self.configWidget.config_changed_flag.connect(self.__configChanged__)
        self.configWidget.show()

    def __configChanged__(self):
        print('Config changed')
        # Updating the widgets

    def add_XYplots(self):

        self.device_subscriptions_raw = []
        self.device_subscriptions_si = []
        for p_index,p in enumerate(self.parameter):
            # The parameter
            # Raw
            subtmp_raw = '/d:{{DHF_raw_{}}}/k:{}/'.format(self.sn, p)
            self.device_subscriptions_raw.append(subtmp_raw)
            config = XYplotWidget.configXYplot(title='{} {}'.format(self.sn, p))
            self.plot_widget_HF_raw = XYplotWidget.XYplot(config=config, redvypr_device=self.device)
            self.plot_widget_HF_raw.set_line(0, subtmp_raw, name=p, color='red', linewidth=2)
            # Create the button to plot the widget
            but = QtWidgets.QPushButton('Plot')
            but.clicked.connect(self.__plot_clicked__)
            self.datatable_raw.setCellWidget(p_index + 1, 3, but)
            but.__widget__ = self.plot_widget_HF_raw
            # Converted
            subtmp_si = '/d:{{DHF_SI_{}}}/k:{}/'.format(self.sn, p)
            self.device_subscriptions_si.append(subtmp_si)
            config = XYplotWidget.configXYplot(title='{} (converted)'.format(p))
            self.plot_widget_HF_SI = XYplotWidget.XYplot(config=config, redvypr_device=self.device)
            self.plot_widget_HF_SI.set_line(0, subtmp_si, name=p, color='red', linewidth=2)
            # Create the button to plot the widget
            but = QtWidgets.QPushButton('Plot')
            but.clicked.connect(self.__plot_clicked__)
            self.datatable_conv.setCellWidget(p_index + 1, 3, but)
            but.__widget__ = self.plot_widget_HF_SI
            # Add all the plots, such that they can be updated
            self.XYplots.append(self.plot_widget_HF_raw)
            self.XYplots.append(self.plot_widget_HF_SI)

            if False: # Average data
                print('Average data!! 0')
                self.avgWidget = QtWidgets.QWidget()
                self.avgWidget_layout = QtWidgets.QVBoxLayout(self.avgWidget)
                self.rawconvtabs.addTab(self.avgWidget, 'Average')

                config = XYplotWidget.configXYplot(title='Heat flow average')
                self.plot_widget_HF_SI_AVG = XYplotWidget.XYplot(config=config, redvypr_device=redvypr_device, add_line=False)
                for i,avg_s in enumerate(self.configuration.avg_data):
                    avg_str = str(avg_s) + 's'
                    avg_datakey = 'HF_avg_{}'.format(avg_str)
                    std_datakey = 'HF_std_{}'.format(avg_str)
                    raddress = RedvyprAddress(datakey=avg_datakey, devicename='{DHF_SIAVG_.*}')
                    raddress_std = RedvyprAddress(datakey=std_datakey, devicename='{DHF_SIAVG_.*}')
                    address = raddress.address_str
                    address_std = raddress_std.address_str
                    #'HF_avg_10s'
                    #Publishing avg:10s packet
                    #{'_redvypr': {'t': 1707832080.2044983, 'device': 'DHF_SIAVG_FC0FE7FFFE164EE0', 'host': {'hostname': 'redvypr', 'tstart': 1708066243.1493528, 'addr': '192.168.178.157', 'uuid': '176473386979093-187'}}, 't_avg_10s': 1707832073.2196076, 't_std_10s': 3.4081697616298503, 't_n_10s': 6, 'HF_avg_10s': 3.607291333333333, 'HF_std_10s': 0.04859570904468358, 'HF_n_10s': 6, 'NTC0_avg_10s': 21.016166666666663, 'NTC0_std_10s': 0.0003726779962504204, 'NTC0_n_10s': 6, 'NTC1_avg_10s': 21.119, 'NTC1_std_10s': 0.0, 'NTC1_n_10s': 6, 'NTC2_avg_10s': 21.113333333333333, 'NTC2_std_10s': 0.00047140452079160784, 'NTC2_n_10s': 6}
                    self.plot_widget_HF_SI_AVG.add_line(address, name=address, linewidth=1, error_addr=address_std)
                    self.avgWidget_layout.addWidget(self.plot_widget_HF_SI_AVG)

                # Add the three temperature sensors as well
                for NNTC in range(0,3):
                    config = XYplotWidget.configXYplot(title='Temperature (average)')
                    plot_widget_NTC_SI_AVG = XYplotWidget.XYplot(config=config, redvypr_device=redvypr_device,
                                                                     add_line=False)
                    for i, avg_s in enumerate(self.configuration.avg_data):
                        avg_str = str(avg_s) + 's'
                        avg_datakey = 'NTC{}_avg_{}'.format(NNTC,avg_str)
                        std_datakey = 'NTC{}_std_{}'.format(NNTC,avg_str)
                        raddress = RedvyprAddress(datakey=avg_datakey, devicename='{DHF_SIAVG_.*}')
                        raddress_std = RedvyprAddress(datakey=std_datakey, devicename='{DHF_SIAVG_.*}')
                        address = raddress.address_str
                        address_std = raddress_std.address_str
                        plot_widget_NTC_SI_AVG.add_line(address, name=address, linewidth=1, error_addr=address_std)
                        self.avgWidget_layout.addWidget(plot_widget_NTC_SI_AVG)
                        self.XYplots.append(plot_widget_NTC_SI_AVG)

            if False:
                # Add all the plots, such that they can be updated
                self.XYplots.append(self.plot_widget_HF_SI_AVG)
                self.XYplots.append(self.plot_widget_HF_raw)
                self.XYplots.append(self.plot_widget_NTC_raw)
                self.XYplots.append(self.plot_widget_HF_SI)
                self.XYplots.append(self.plot_widget_NTC_SI)


                self.layout_raw.addWidget(self.plot_widget_HF_raw,1,0)
                self.layout_raw.addWidget(self.plot_widget_NTC_raw,2,0)
                self.layout_conv.addWidget(self.plot_widget_HF_SI,1,0)
                self.layout_conv.addWidget(self.plot_widget_NTC_SI,2,0)

    def __plot_clicked__(self):
        but = self.sender()
        but.__widget__.show()

    def update(self, data):
        """
        Updating the local data with datapacket
        """
        funcname = __name__ + '__update__()'
        logger.debug(funcname)
        #print('Got data for widget',data)
        mac = data['sn']

        col_parameter = 0
        col_unit = 1
        col_data = 2
        row_time = 0
        #print('Got data', data['_redvypr']['device'],mac)
        for plot in self.XYplots:
            print('plot update',len(plot.config.lines), mac)
            plot.update_plot(data)

        if mac in self.sn:
            # Update table
            if data['type'] == 'HF':  # Raw data
                #print('Updating')
                # Time
                tdata = datetime.datetime.utcfromtimestamp(data['t'])
                tdatastr = tdata.strftime('%Y-%m-%d %H:%M:%S.%f')
                item = QtWidgets.QTableWidgetItem(tdatastr)
                self.datatable_raw.setItem(row_time, col_data, item)
                for p_index,p in enumerate(self.parameter):
                    # The parameter
                    item = QtWidgets.QTableWidgetItem(p)
                    self.datatable_raw.setItem(p_index + 1, col_parameter, item)
                    # The data
                    try:
                        chdata = "{:+.6f}".format(data[p])
                        item = QtWidgets.QTableWidgetItem(str(chdata))
                        self.datatable_raw.setItem(p_index + 1, col_data, item)
                    except Exception as e:
                        logger.debug(funcname, exc_info=True)

                    if self.parameter_unit[p_index] is None:
                        #datastream = data_packets.get_datastream_from_data(data,p)
                        datastream = RedvyprAddress(data, datakey = p)
                        #print('datastream',datastream)
                        #keyinfo = self.device.get_metadata_datakey(datastream)
                        keyinfo = {}
                        try:
                            self.parameter_unit[p_index] = str(keyinfo['unit'])
                        except:
                            self.parameter_unit[p_index] = str('NA')

                        item = QtWidgets.QTableWidgetItem(self.parameter_unit[p_index])
                        self.datatable_raw.setItem(p_index + 1, col_unit, item)
                        #print('Keyinfo', keyinfo)
                        #print('Parameter', p)
                        #print('datastream',datastream)
                        #print('keyinfo', keyinfo)

            elif data['type'] == 'HFSI':  # converted data
                print('Updating HFSI')
                # Time
                tdata = datetime.datetime.utcfromtimestamp(data['t'])
                tdatastr = tdata.strftime('%Y-%m-%d %H:%M:%S.%f')
                item = QtWidgets.QTableWidgetItem(tdatastr)
                self.datatable_conv.setItem(row_time, col_data, item)
                for p_index, p in enumerate(self.parameter):
                    print('parameter',p)
                    # The parameter
                    item = QtWidgets.QTableWidgetItem(p)
                    self.datatable_conv.setItem(p_index + 1, col_parameter, item)
                    if self.parameter_unitconv[p_index] is None:
                        datastream = RedvyprAddress(data, datakey=p)
                        ##datastream = data_packets.get_datastream_from_data(data, p)
                        #keyinfo = self.device.get_metadata_datakey(datastream)
                        keyinfo = {}
                        try:
                            self.parameter_unitconv[p_index] = str(keyinfo['unit'])
                        except:
                            self.parameter_unitconv[p_index] = str('NA')

                        item = QtWidgets.QTableWidgetItem(self.parameter_unitconv[p_index])
                        self.datatable_conv.setItem(p_index + 1, col_unit, item)
                        # print('Keyinfo', keyinfo)
                        #print('Parameter', p)
                        #print('datastream', datastream)
                        #print('keyinfo', keyinfo)

                    # Update the data
                    try:
                        chdata = "{:+.6f}".format(data[p])
                        item = QtWidgets.QTableWidgetItem(str(chdata))
                        self.datatable_conv.setItem(p_index + 1, col_data, item)
                    except Exception as e:
                        logger.debug(funcname, exc_info=True)

        # Fill the datatables






