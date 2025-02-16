import datetime
import pytz
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import qtawesome
import time
import yaml
import numpy as numpy
import logging
import sys
import pydantic
import redvypr
from redvypr.data_packets import check_for_command
from redvypr.device import RedvyprDevice
from redvypr.widgets.standard_device_widgets import RedvyprDeviceWidget_simple
from redvypr.devices.sensors.generic_sensor.calibrationWidget import GenericSensorCalibrationWidget
import redvypr.devices.sensors.calibration.calibration_models as calibration_models
import redvypr.devices.sensors.generic_sensor.sensor_definitions as sensor_definitions
from . import hexflasher

#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict
tarv2nmea_R_sample_test1 = b'$D8478FFFFE95CD4D,1417,88.562500:$D8478FFFFE95CA01,TAR_S,R_B4,85.125000,23,88.125000,23,3703.171,3687.865,3689.992,3673.995,3663.933,3646.964,3650.582,3658.807,3658.235,3659.743,3677.440,3656.256,3667.873,3692.007,3700.870,3693.682,3714.597,3723.282,3741.300,3729.004,3742.731,3734.452,3760.982,3785.253,3748.399,3769.112,3764.206,3778.452,3766.012,3773.516,3774.506,3782.260,3754.508,3738.320,3731.787,3747.988,3719.920,3736.585,3730.321,3727.657,3729.182,3723.627,3738.785,3752.083,3736.633,3725.642,3747.952,3708.696,3727.275,3738.761,3734.088,3707.147,3733.981,3712.535,3716.624,3746.563,3726.405,3743.333,3719.324,3713.793,3726.637,3713.620,3743.029,3731.889\n'
tarv2nmea_R_sample_test2 = b'$D8478FFFFE95CD4D,1418,88.625000:$D8478FFFFE95CA01,TAR_S,T_B4,85.125000,23,88.125000,23,18.7687,18.8769,18.8618,18.9755,19.0472,19.1687,19.1427,19.0838,19.0879,19.0771,18.9509,19.1021,19.0191,18.8476,18.7849,18.8357,18.6882,18.6271,18.5011,18.5870,18.4911,18.5489,18.3641,18.1963,18.4516,18.3078,18.3418,18.2432,18.3292,18.2773,18.2705,18.2169,18.4091,18.5219,18.5675,18.4544,18.6507,18.5340,18.5778,18.5965,18.5858,18.6247,18.5186,18.4259,18.5337,18.6106,18.4547,18.7297,18.5991,18.5188,18.5515,18.7406,18.5522,18.7027,18.6739,18.4644,18.6052,18.4869,18.6549,18.6938,18.6036,18.6950,18.4890,18.5668\n'
tarv2nmea_R_test1 = b'$D8478FFFFE95CD4D,TAR,R_B4,88.125000,23,3791.505,3780.276,3783.786,3753.388,3735.459,3698.891,3713.560,3683.382,3725.874,3732.151,3738.183,3739.709,3744.310,3748.047,3752.655,3764.850,3759.181,3785.050,3776.687,3785.038,3828.752,3797.263,3797.710,3803.897,3824.091,3827.292,3829.092,3824.091,3837.073,3832.835,3796.941,3802.335,3752.142,3761.262,3754.997,3748.661,3758.782,3756.773,3764.004,3756.636,3772.050,3748.459,3745.413,3754.330,3753.191,3741.783,3730.935,3770.715,3731.245,3730.243,3753.847,3743.356,3744.942,3746.802,3766.078,3743.780,3763.622,3735.769,3750.420,3763.968,3752.762,3761.935,3727.597,3736.508\n'

# Generic tar, legacy, define two, one for R and one for T
#tarv2nmea_test1 = b'$FC0FE7FFFE155D8C,TAR,B2,36533.125000,83117,3498.870,3499.174,3529.739,3490.359,3462.923,3467.226,3480.077,3443.092,3523.642,3525.567,3509.492,3561.330,3565.615,3486.693,3588.670,3539.169,3575.104,3523.946,3496.343,3480.160,3531.045,3501.624,3497.010,3557.235,3479.952,3458.297,3523.052,3487.223,3571.087,3525.740,3580.928,3534.818\n'
#tar_b2_split = b'\$(?P<MAC>[A-F,0-9]+),TAR,B2,(?P<counter>[0-9.]+),(?P<np>[0.9]+),(?P<TAR>[0-9.]+,*)\n'
tarv2nmea_split = b'\$(?P<MAC>.+),TAR,(?P<parameterunit>[A-c])_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter>[0-9.]+),(?P<np>[0-9]+),(?P<TAR>.*)\n'
tarv2nmea_str_format = {'MAC':'str','counter':'float','parameterunit':'str','ntctype':'str','ntcdist':'float','np':'int','TAR':'array'}
tarv2nmea_datakey_metadata = {'MAC':{'unit':'MAC64','description':'MAC of the sensor'},'np':{'unit':'counter'},'TAR':{'unit':'Ohm'}}
tarv2nmea_packetid_format = '{MAC}__TAR'
tarv2nmea_description = 'Temperature array NMEA like text format'

# tar for R
tarv2nmea_R_split = b'\$(?P<MAC>.+),TAR,R_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter>[0-9.]+),(?P<np>[0-9]+),(?P<R>.*)\n'
tarv2nmea_R_str_format = {'MAC':'str','counter':'float','ntctype':'str','ntcdist':'float','np':'int','R':'array'}
tarv2nmea_R_datakey_metadata = {'MAC':{'unit':'MAC64','description':'MAC of the sensor'},'np':{'unit':'counter'},'R':{'unit':'Ohm'}}
tarv2nmea_R_packetid_format = '{MAC}__TAR__R'
tarv2nmea_R_description = 'Temperature array of NTC resistance in ohm, NMEA like text format'

# tar for T
tarv2nmea_T_split = b'\$(?P<MAC>.+),TAR,T_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter>[0-9.]+),(?P<np>[0-9]+),(?P<T>.*)\n'
tarv2nmea_T_str_format = {'MAC':'str','counter':'float','ntctype':'str','ntcdist':'float','np':'int','T':'array'}
tarv2nmea_T_datakey_metadata = {'MAC':{'unit':'MAC64','description':'MAC of the sensor'},'np':{'unit':'counter'},'T':{'unit':'degC'}}
tarv2nmea_T_packetid_format = '{MAC}__TAR__T'
tarv2nmea_T_description = 'Temperature array of NTC temperature in degC, converted internally in the sensor using onboard coefficients NMEA like text format'

# Generic tar sample, legacy, define two, one for R and one for T
tarv2nmea_sample_split = b'\$(?P<MAC>.+),TAR_S;(?P<counter>[0-9.]+);(?P<np>[0-9]+),(?P<parameterunit>[A-c])_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter_local>[0-9.]+),(?P<np_local>[0-9]+),(?P<TAR>.*)\n'
tarv2nmea_sample_str_format = {'MAC':'str','counter':'float','counter_local':'float','parameterunit':'str','ntctype':'str','ntcdist':'float','np':'int','np_local':'int','TAR':'array'}
tarv2nmea_sample_datakey_metadata = {'MAC':{'unit':'MAC64','description':'MAC of the sensor'},'np':{'unit':'counter'},'TAR':{'unit':'Ohm'}}
tarv2nmea_sample_packetid_format = '{MAC}__TAR_S'
tarv2nmea_sample_description = 'Temperature array datapacket initiated by a sample command'


tarv2nmea_R_sample_split = b'\$(?P<MAC>.+),TAR_S;(?P<counter>[0-9.]+);(?P<np>[0-9]+),R_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter_local>[0-9.]+),(?P<np_local>[0-9]+),(?P<R>.*)\n'
tarv2nmea_R_sample_str_format = {'MAC':'str','counter':'float','counter_local':'float','ntctype':'str','ntcdist':'float','np':'int','np_local':'int','R':'array'}
tarv2nmea_R_sample_datakey_metadata = {'MAC':{'unit':'MAC64','description':'MAC of the sensor'},'np':{'unit':'counter'},'R':{'unit':'Ohm'}}
tarv2nmea_R_sample_packetid_format = '{MAC}__TAR_S__R'
tarv2nmea_R_sample_description = 'Temperature array datapacket initiated by a sample command'

tarv2nmea_T_sample_split = b'\$(?P<MAC>.+),TAR_S;(?P<counter>[0-9.]+);(?P<np>[0-9]+),S_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter_local>[0-9.]+),(?P<np_local>[0-9]+),(?P<T>.*)\n'
tarv2nmea_T_sample_str_format = {'MAC':'str','counter':'float','counter_local':'float','ntctype':'str','ntcdist':'float','np':'int','np_local':'int','T':'array'}
tarv2nmea_T_sample_datakey_metadata = {'MAC':{'unit':'MAC64','description':'MAC of the sensor'},'np':{'unit':'counter'},'T':{'unit':'degC'}}
tarv2nmea_T_sample_packetid_format = '{MAC}__TAR_S__T'
tarv2nmea_T_sample_description = 'Temperature array datapacket initiated by a sample command'

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('tar')
logger.setLevel(logging.DEBUG)


class TarSensor(sensor_definitions.BinarySensor):
    num_ntc: int = pydantic.Field(default=64, description='number of ntc sensors')
    def __init__(self,*args,**kwargs):
        super().__init__(*args, **kwargs)
        for n in range(self.num_ntc):
            datakey_ntc = '''R['{}'].'''.format(n)
            self.calibrations_raw[datakey_ntc] = None

        self.set_standard_calibrations()

    def set_standard_calibrations(self):
        """
        Sets standard NTC calibrations to all parameters
        """
        for datakey_ntc in self.calibrations_raw:
            coeffs = [-2.3169660632264368e-08, - 1.0330814536964214e-06, - 0.000210399828596111, - 0.001612330551548827]
            calNTC = calibration_models.CalibrationNTC(coeffs=coeffs)
            self.calibrations_raw[datakey_ntc] = calNTC


class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Processes data from temperature array sensors'
    gui_tablabel_display: str = 'Temperature array (TAR)'

class DeviceCustomConfig(pydantic.BaseModel):
    baud: int = 115200

redvypr_devicemodule = True


def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname)
    packetbuffer = {-1000:None} # Add a dummy key
    # Create the tar sensor
    tarv2nmea_R = sensor_definitions.BinarySensor(name='tarv2nmea_R', regex_split=tarv2nmea_R_split,
                                                str_format=tarv2nmea_R_str_format,
                                                autofindcalibration=False,
                                                description=tarv2nmea_R_description,
                                                example_data=tarv2nmea_R_test1,
                                                datakey_metadata=tarv2nmea_R_datakey_metadata,
                                                packetid_format=tarv2nmea_R_packetid_format,
                                                datastream=redvypr.RedvyprAddress('/k:data'))

    tarv2nmea_T = sensor_definitions.BinarySensor(name='tarv2nmea_T', regex_split=tarv2nmea_T_split,
                                                  str_format=tarv2nmea_T_str_format,
                                                  autofindcalibration=False,
                                                  description=tarv2nmea_T_description,
                                                  example_data=tarv2nmea_R_test1,
                                                  datakey_metadata=tarv2nmea_T_datakey_metadata,
                                                  packetid_format=tarv2nmea_T_packetid_format,
                                                  datastream=redvypr.RedvyprAddress('/k:data'))

    tarv2nmea_R_sample = sensor_definitions.BinarySensor(name='tarv2nmea_R_sample', regex_split=tarv2nmea_R_sample_split,
                                                str_format=tarv2nmea_R_sample_str_format,
                                                autofindcalibration=False,
                                                description=tarv2nmea_R_sample_description,
                                                example_data=tarv2nmea_R_sample_test1,
                                                datakey_metadata=tarv2nmea_R_sample_datakey_metadata,
                                                packetid_format=tarv2nmea_R_sample_packetid_format,
                                                datastream=redvypr.RedvyprAddress('/k:data'))

    tarv2nmea_T_sample = sensor_definitions.BinarySensor(name='tarv2nmea_T_sample', regex_split=tarv2nmea_T_sample_split,
                                                         str_format=tarv2nmea_T_sample_str_format,
                                                         autofindcalibration=False,
                                                         description=tarv2nmea_T_sample_description,
                                                         example_data=tarv2nmea_R_sample_test1,
                                                         datakey_metadata=tarv2nmea_T_sample_datakey_metadata,
                                                         packetid_format=tarv2nmea_T_sample_packetid_format,
                                                         datastream=redvypr.RedvyprAddress('/k:data'))

    while True:
        datapacket = datainqueue.get()
        [command, comdata] = check_for_command(datapacket, thread_uuid=device_info['thread_uuid'],
                                               add_data=True)
        if command is not None:
            logger.debug('Command is for me: {:s}'.format(str(command)))
            if command=='stop':
                logger.info(funcname + 'received command:' + str(datapacket) + ' stopping now')
                logger.debug('Stop command')
                return


        #try:
        #    print('Data',datapacket['data'])
        #except:
        #    continue
        data_packet_processed = tarv2nmea_R.datapacket_process(datapacket)
        datatype = 'R'
        if data_packet_processed is None:
            data_packet_processed = tarv2nmea_T.datapacket_process(datapacket)
            datatype = 'T'
            if data_packet_processed is None:
                data_packet_processed = tarv2nmea_R_sample.datapacket_process(datapacket)
                datatype = 'R'
                if data_packet_processed is None:
                    data_packet_processed = tarv2nmea_T_sample.datapacket_process(datapacket)
                    datatype = 'T'

        if data_packet_processed is not None:
            if len(data_packet_processed) > 0:
                #print('Datapacket processed',data_packet_processed)
                logger.debug('Data packet processed (without calibration):{}'.format(len(data_packet_processed)))
                mac = data_packet_processed[0]['MAC']
                counter = data_packet_processed[0]['counter']
                np = data_packet_processed[0]['np']
                npmax = max(packetbuffer.keys())
                #print('MAC',mac,counter,np)
                #if npmax < 0:  # The first measurement
                #    npmax = np
                # Check if a new packet arrived (meaning that np is larger than npmax)
                # If yes, merge all parts of the old one first
                if (np > npmax) and (npmax > 0):  # Process packetnumber npmax
                    for datatype_tmp in packetbuffer[npmax].keys():  # Loop over all datatypes
                        npackets = len(packetbuffer[npmax][datatype_tmp].keys())
                        dmerge = [None] * npackets
                        datapacket_merged = {}
                        #print('Npackets',npackets)
                        for mac_tmp in packetbuffer[npmax][datatype_tmp].keys():
                            p = packetbuffer[npmax][datatype_tmp][mac_tmp]
                            # Count the ':' and put it at the list location
                            i = mac_tmp.count(':')
                            if i >= npackets:
                                logger.debug('Could not add {}'.format(mac_tmp))
                                continue
                            if i == 0:  # First packet
                                mac_final = mac_tmp
                                counter_final = counter
                                # The merged packetid
                                packetid_final = '{}__TAR__{}'.format(mac_final,datatype_tmp)
                                dp = redvypr.Datapacket(packetid=packetid_final)
                                datapacket_merged.update(dp)
                                datapacket_merged['mac'] = mac_final
                                datapacket_merged['counter'] = counter_final
                            #print('mac_tmp',mac_tmp,i)
                            print('Datapacket processed', data_packet_processed)
                            print('Datapacket',datapacket)
                            print('P',p)
                            # Add the data to a list, that is hstacked later
                            dmerge[i] = p[datatype_tmp]
                        # Merge the packages into one large one
                        #print('dmerge', dmerge)
                        #print('len dmerge', len(dmerge))
                        tar_merge = numpy.hstack(dmerge).tolist()
                        #print('Tar merge',len(tar_merge))
                        datapacket_merged[datatype_tmp] = tar_merge
                        datapacket_merged['np'] = npmax
                        datapacket_merged['datatype'] = datatype_tmp
                        #print('publish')
                        dataqueue.put(datapacket_merged)
                    # Remove from buffer
                    packetbuffer.pop(npmax)

                try:
                    packetbuffer[np]
                except:
                    packetbuffer[np] = {}

                try:
                    packetbuffer[np][datatype]
                except:
                    packetbuffer[np][datatype] = {}

                packetbuffer[np][datatype][mac] = data_packet_processed[0]

                #print(data_packet_processed[0]['MAC'])
                #print(data_packet_processed[0]['counter'])
                #print(data_packet_processed[0]['np'])
                #print(data_packet_processed[0]['datatype'])
    return None

class RedvyprDeviceWidget(RedvyprDeviceWidget_simple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.show_numpackets = 5
        self.packetbuffer = {}
        self.datadisplaywidget = QtWidgets.QWidget(self)
        self.datadisplaywidget_layout = QtWidgets.QVBoxLayout(self.datadisplaywidget)
        self.layout.addWidget(self.datadisplaywidget)

    def update_data(self, data):
        """
        """
        funcname = __name__ + '.update_data()'
        tnow = time.time()
        #print(funcname + 'Got some data', data)
        # Check if datakeys has 'R' or 'T'
        if 'R' in data.keys():
            datatype = 'R'
        elif 'T' in data.keys():
            datatype = 'T'
        else:
            return

        irows = ['mac', 'np', 'counter', datatype]  # Rows to plot
        try:
            np = data['np']
            mac = data['mac']
            counter = data['counter']
            datatar = data[datatype]
        except:
            return

        try:
            self.packetbuffer[mac]
        except:
            self.packetbuffer[mac] = {}

        try:
            self.packetbuffer[mac][datatype]
        except:
            table = QtWidgets.QTableWidget()
            self.packetbuffer[mac][datatype] = {'table': table,
                                                     'packets': []}

            table.setRowCount(len(datatar) + len(irows) - 1)


            table.setColumnCount(self.show_numpackets)
            self.datadisplaywidget_layout.addWidget(table)

        try:
            self.packetbuffer[mac][datatype]['packets'].append(data)

            # Update the table
            table = self.packetbuffer[mac][datatype]['table']
            if len(self.packetbuffer[mac][datatype]['packets']) > self.show_numpackets:
                self.packetbuffer[mac][datatype]['packets'].pop(0)
                table.removeColumn(0)
                table.setColumnCount(self.show_numpackets)

            icol = len(self.packetbuffer[mac][datatype]['packets']) - 1
            for irow,key in enumerate(irows):
                d = data[key]
                dataitem = QtWidgets.QTableWidgetItem(str(d))
                table.setItem(irow, icol, dataitem)
                if key == datatype:
                    for i, d in enumerate(datatar):
                        dataitem = QtWidgets.QTableWidgetItem(str(d))
                        irowtar = i + irow
                        table.setItem(irowtar, icol, dataitem)
        except:
            logger.info('Does not work',exc_info=True)



