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
from . import sensor_firmware_config
from . import nmea_mac64_utils
from redvypr.utils.databuffer import DatapacketAvg

#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict
tarv2nmea_R_sample_test1 = b'$D8478FFFFE95CD4D,1417,88.562500:$D8478FFFFE95CA01,TAR_S,R_B4,85.125000,23,88.125000,23,3703.171,3687.865,3689.992,3673.995,3663.933,3646.964,3650.582,3658.807,3658.235,3659.743,3677.440,3656.256,3667.873,3692.007,3700.870,3693.682,3714.597,3723.282,3741.300,3729.004,3742.731,3734.452,3760.982,3785.253,3748.399,3769.112,3764.206,3778.452,3766.012,3773.516,3774.506,3782.260,3754.508,3738.320,3731.787,3747.988,3719.920,3736.585,3730.321,3727.657,3729.182,3723.627,3738.785,3752.083,3736.633,3725.642,3747.952,3708.696,3727.275,3738.761,3734.088,3707.147,3733.981,3712.535,3716.624,3746.563,3726.405,3743.333,3719.324,3713.793,3726.637,3713.620,3743.029,3731.889\n'
tarv2nmea_R_sample_test2 = b'$D8478FFFFE95CD4D,1418,88.625000:$D8478FFFFE95CA01,TAR_S,T_B4,85.125000,23,88.125000,23,18.7687,18.8769,18.8618,18.9755,19.0472,19.1687,19.1427,19.0838,19.0879,19.0771,18.9509,19.1021,19.0191,18.8476,18.7849,18.8357,18.6882,18.6271,18.5011,18.5870,18.4911,18.5489,18.3641,18.1963,18.4516,18.3078,18.3418,18.2432,18.3292,18.2773,18.2705,18.2169,18.4091,18.5219,18.5675,18.4544,18.6507,18.5340,18.5778,18.5965,18.5858,18.6247,18.5186,18.4259,18.5337,18.6106,18.4547,18.7297,18.5991,18.5188,18.5515,18.7406,18.5522,18.7027,18.6739,18.4644,18.6052,18.4869,18.6549,18.6938,18.6036,18.6950,18.4890,18.5668\n'
tarv2nmea_R_test1 = b'$D8478FFFFE95CD4D,TAR,R_B4,88.125000,23,3791.505,3780.276,3783.786,3753.388,3735.459,3698.891,3713.560,3683.382,3725.874,3732.151,3738.183,3739.709,3744.310,3748.047,3752.655,3764.850,3759.181,3785.050,3776.687,3785.038,3828.752,3797.263,3797.710,3803.897,3824.091,3827.292,3829.092,3824.091,3837.073,3832.835,3796.941,3802.335,3752.142,3761.262,3754.997,3748.661,3758.782,3756.773,3764.004,3756.636,3772.050,3748.459,3745.413,3754.330,3753.191,3741.783,3730.935,3770.715,3731.245,3730.243,3753.847,3743.356,3744.942,3746.802,3766.078,3743.780,3763.622,3735.769,3750.420,3763.968,3752.762,3761.935,3727.597,3736.508\n'

# Generic tar, legacy, define two, one for R and one for T
#tarv2nmea_test1 = b'$FC0FE7FFFE155D8C,TAR,B2,36533.125000,83117,3498.870,3499.174,3529.739,3490.359,3462.923,3467.226,3480.077,3443.092,3523.642,3525.567,3509.492,3561.330,3565.615,3486.693,3588.670,3539.169,3575.104,3523.946,3496.343,3480.160,3531.045,3501.624,3497.010,3557.235,3479.952,3458.297,3523.052,3487.223,3571.087,3525.740,3580.928,3534.818\n'
#tar_b2_split = b'\$(?P<mac>[A-F,0-9]+),TAR,B2,(?P<counter>[0-9.]+),(?P<np>[0.9]+),(?P<TAR>[0-9.]+,*)\n'
tarv2nmea_split = b'\$(?P<mac>.+),TAR,(?P<parameterunit>[A-c])_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter>[0-9.]+),(?P<np>[0-9]+),(?P<TAR>.*)\n'
tarv2nmea_str_format = {'mac':'str','counter':'float','parameterunit':'str','ntctype':'str','ntcdist':'float','np':'int','TAR':'array'}
tarv2nmea_datakey_metadata = {'mac':{'unit':'mac64','description':'mac of the sensor'},'np':{'unit':'counter'},'TAR':{'unit':'Ohm'}}
tarv2nmea_packetid_format = '{mac}__TAR'
tarv2nmea_description = 'Temperature array NMEA like text format'

# tar for R
tarv2nmea_R_split = b'\$(?P<mac>.+),TAR,R_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter>[0-9.]+),(?P<np>[0-9]+),(?P<R>.*)\n'
tarv2nmea_R_str_format = {'mac':'str','counter':'float','ntctype':'str','ntcdist':'float','np':'int','R':'array'}
tarv2nmea_R_datakey_metadata = {'mac':{'unit':'mac64','description':'mac of the sensor'},'np':{'unit':'counter'},'R':{'unit':'Ohm'}}
tarv2nmea_R_packetid_format = '{mac}__TAR__R'
tarv2nmea_R_description = 'Temperature array of NTC resistance in ohm, NMEA like text format'

# tar for T
tarv2nmea_T_split = b'\$(?P<mac>.+),TAR,T_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter>[0-9.]+),(?P<np>[0-9]+),(?P<T>.*)\n'
tarv2nmea_T_str_format = {'mac':'str','counter':'float','ntctype':'str','ntcdist':'float','np':'int','T':'array'}
tarv2nmea_T_datakey_metadata = {'mac':{'unit':'mac64','description':'mac of the sensor'},'np':{'unit':'counter'},'T':{'unit':'degC'}}
tarv2nmea_T_packetid_format = '__TAR__T'
tarv2nmea_T_description = 'Temperature array of NTC temperature in degC, converted internally in the sensor using onboard coefficients NMEA like text format'

# Generic tar sample, legacy, define two, one for R and one for T
tarv2nmea_sample_split = b'\$(?P<mac>.+),TAR_S;(?P<counter>[0-9.]+);(?P<np>[0-9]+),(?P<parameterunit>[A-c])_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter_local>[0-9.]+),(?P<np_local>[0-9]+),(?P<TAR>.*)\n'
tarv2nmea_sample_str_format = {'mac':'str','counter':'float','counter_local':'float','parameterunit':'str','ntctype':'str','ntcdist':'float','np':'int','np_local':'int','TAR':'array'}
tarv2nmea_sample_datakey_metadata = {'mac':{'unit':'mac64','description':'mac of the sensor'},'np':{'unit':'counter'},'TAR':{'unit':'Ohm'}}
tarv2nmea_sample_packetid_format = '__TAR_S'
tarv2nmea_sample_description = 'Temperature array datapacket initiated by a sample command'


tarv2nmea_R_sample_split = b'\$(?P<mac>.+),TAR_S;(?P<counter>[0-9.]+);(?P<np>[0-9]+),R_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter_local>[0-9.]+),(?P<np_local>[0-9]+),(?P<R>.*)\n'
tarv2nmea_R_sample_str_format = {'mac':'str','counter':'float','counter_local':'float','ntctype':'str','ntcdist':'float','np':'int','np_local':'int','R':'array'}
tarv2nmea_R_sample_datakey_metadata = {'mac':{'unit':'mac64','description':'mac of the sensor'},'np':{'unit':'counter'},'R':{'unit':'Ohm'}}
tarv2nmea_R_sample_packetid_format = '__TAR_S__R'
tarv2nmea_R_sample_description = 'Temperature array datapacket initiated by a sample command'

#$D8478FFFFE95E740,1333612,83350.750000:$D8478FFFFE95CA01,1333609,83350.562500:$D8478FFFFE960155,TAR_S;83350.062500;41676,T_B4,83352.625000,41679,22.8676,23.3250,23.6779,23.8075,24.5429,24.5523,24.8531,24.6138,24.5245,24.3931,24.3789,23.9727,23.6818,23.2973,23.1026,22.9623,22.4240,22.0318,21.5546,20.9095,20.4307,19.9684,19.6013,19.1512,18.7156,18.3240,18.0466,17.9554,17.6042,17.2420,17.2303,16.9244,17.0201,16.7837,16.7710,16.5264,16.3620,16.2336,16.1800,16.1013,15.8603,15.8406,15.7468,15.8856,15.5547,15.7500,15.5480,15.3910,15.2764,15.4010,15.3414,15.1583,15.2317,14.9590,15.0831,15.0845,15.0918,14.8507,14.9967,14.9612,14.7171,14.9477,14.8946,14.7653\n
tarv2nmea_T_sample_split = b'\$(?P<mac>.+),TAR_S;(?P<counter>[0-9.]+);(?P<np>[0-9]+),T_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter_local>[0-9.]+),(?P<np_local>[0-9]+),(?P<T>.*)\n'
tarv2nmea_T_sample_str_format = {'mac':'str','counter':'float','counter_local':'float','ntctype':'str','ntcdist':'float','np':'int','np_local':'int','T':'array'}
tarv2nmea_T_sample_datakey_metadata = {'mac':{'unit':'mac64','description':'mac of the sensor'},'np':{'unit':'counter'},'T':{'unit':'degC'}}
tarv2nmea_T_sample_packetid_format = '__TAR_S__T'
tarv2nmea_T_sample_description = 'Temperature array datapacket initiated by a sample command'

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.tar')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

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
    merge_groups: bool = True
    average: bool = True
    avg_intervals: list = [300,30,10]
    avg_dimensions: list = ['t','t','n']
    #avg_intervals: list = [2]
    #avg_dimensions: list = ['n']


def create_avg_databuffer(config, datatype=None):
    avg_intervals = config['avg_intervals']
    avg_dimensions = config['avg_dimensions']
    avg_databuffers = []
    for avg_int,avg_dim in zip(avg_intervals,avg_dimensions):
        avg_databuffer = redvypr.utils.databuffer.DatapacketAvg(avg_dimension=avg_dim,avg_interval=avg_int,address=datatype)
        avg_databuffers.append(avg_databuffer)

    return avg_databuffers

def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname)
    packetbuffer = {-1000:None} # Add a dummy key
    packetbuffer_avg = {}  # Add a dummy key
    packetbuffer_merged_avg = {}  # Add a dummy key

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


        try:
            print('Data',datapacket['data'])
        except:
            continue
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
                for ip,p in enumerate(data_packet_processed):
                    print('p',p)
                    mactmp = p['mac']
                    mac_parsed = nmea_mac64_utils.parse_nmea_mac64_string(mactmp)
                    print('mac parsed',mac_parsed)
                    p['mac'] = mac_parsed['mac']
                    p['parents'] = mac_parsed['parents']
                    p['_redvypr']['packetid'] = p['mac'] + p['_redvypr']['packetid']
                    mac = p['mac']
                    print('mac {} {}'.format(ip,mactmp))
                    dataqueue.put(p)
                    # Averaging the data
                    try:
                        packetbuffer_avg[mac]
                    except:
                        packetbuffer_avg[mac] = {}
                    try:
                        packetbuffer_avg[mac][datatype]
                    except:
                        packetbuffer_avg[mac][datatype] = create_avg_databuffer(config, datatype=datatype)
                    try:
                        for d in packetbuffer_avg[mac][datatype]:  # loop over all average buffers and do the averaging
                            packet_avg = d.append(p)
                            print('Packet avg')
                            try:
                                d.__counter__ += 1
                            except:
                                d.__counter__ = 0
                            # print('Packet avg raw',packet_avg)
                            if packet_avg is not None:
                                dpublish = redvypr.Datapacket()#packetid=packetid_final)
                                packet_avg.update(dpublish)
                                packet_avg['mac'] = mac
                                packet_avg['np'] = d.__counter__
                                packet_avg['counter'] = d.__counter__
                                # print('Publishing average data', d.datakey_save)
                                dataqueue.put(packet_avg)
                                # print('Packet avg publish',packet_avg)
                    except:
                        logger.info('Could not average the data', exc_info=True)


                #print('Datapacket processed',data_packet_processed)
                logger.debug('Data packet processed (without calibration):{}'.format(len(data_packet_processed)))
                #print('mac',mac,counter,np)
                #if npmax < 0:  # The first measurement
                #    npmax = np
                if config['merge_groups']:
                    pmerge = data_packet_processed[0]
                    mac = pmerge['mac']
                    parents = pmerge['parents']
                    counter = pmerge['counter']
                    np = pmerge['np']
                    # Check if we have the downstream device, if yes process, else do nothing
                    if len(parents) > 0:  # The most downstream device
                        macdown = parents[0]
                    else:  # The most downstream device
                        macdown = mac
                        # Add the data to the buffer
                        try:
                            packetbuffer[macdown]
                            npmax = max(packetbuffer[macdown].keys())
                        except:
                            packetbuffer[macdown] = {}
                            npmax = -1000


                        # Check if a new packet arrived (meaning that np is larger than npmax)
                        # If yes, merge all parts of the old one first
                        if (np > npmax) and (npmax > 0):  # Process packetnumber npmax
                            for datatype_tmp in packetbuffer[macdown][npmax].keys():  # Loop over all datatypes
                                npackets = len(packetbuffer[macdown][npmax][datatype_tmp].keys())
                                dmerge = [None] * npackets
                                datapacket_merged = {}
                                #print('Npackets',npackets)
                                for mac_tmp in packetbuffer[macdown][npmax][datatype_tmp].keys():
                                    pmerge2 = packetbuffer[macdown][npmax][datatype_tmp][mac_tmp]
                                    parents_tmp = pmerge2['parents']
                                    # Count the number of parents and put it at the list location
                                    i = len(parents_tmp)
                                    if i >= npackets:
                                        logger.debug('Could not add {}'.format(mac_tmp))
                                        continue
                                    if i == 0:  # First packet
                                        mac_final = mac_tmp + '_m'
                                        counter_final = counter
                                        # The merged packetid
                                        packetid_final = '{}__TAR__{}_merged'.format(mac_final,datatype_tmp)
                                        dp = redvypr.Datapacket(packetid=packetid_final)
                                        datapacket_merged.update(dp)
                                        datapacket_merged['mac'] = mac_final
                                        datapacket_merged['counter'] = counter_final
                                    #print('mac_tmp',mac_tmp,i)
                                    #print('Datapacket processed', data_packet_processed)
                                    #print('Datapacket',datapacket)
                                    #print('datatype_tmp',datatype_tmp,datatype)
                                    #print('P',pmerge2)
                                    # Add the data to a list, that is hstacked later
                                    dmerge[i] = pmerge2[datatype_tmp]
                                # Merge the packages into one large one
                                #print('dmerge', dmerge)
                                #print('len dmerge', len(dmerge))
                                tar_merge = numpy.hstack(dmerge).tolist()
                                #print('Tar merge',len(tar_merge))
                                datapacket_merged[datatype_tmp] = tar_merge
                                datapacket_merged['np'] = npmax
                                datapacket_merged['datatype'] = datatype_tmp
                                datapacket_merged['t'] = p['t']  # Add time
                                print('publish merged data, merged merged')
                                logger.info('Publishing merged data {} {} {}'.format(mac_final, np,datatype))
                                dataqueue.put(datapacket_merged)
                                if False:
                                    # Averaging the data
                                    try:
                                        packetbuffer_merged_avg[macdown]
                                    except:
                                        packetbuffer_merged_avg[macdown] = {}

                                    try:
                                        packetbuffer_merged_avg[macdown][datatype_tmp]
                                    except:
                                        #packetbuffer_avg[mac][datatype_tmp] = DatapacketAvg(address=datatype_tmp)
                                        packetbuffer_merged_avg[macdown][datatype_tmp] = create_avg_databuffer(config, datatype=datatype_tmp)

                                    try:
                                        for d in packetbuffer_merged_avg[macdown][datatype_tmp]:  # loop over all average buffers and do the averaging
                                            packet_avg = d.append(datapacket_merged)
                                            try:
                                                d.__counter__ += 1
                                            except:
                                                d.__counter__ = 0
                                            #print('Packet avg raw',packet_avg)
                                            if packet_avg is not None:
                                                dpublish = redvypr.Datapacket(packetid=packetid_final)
                                                packet_avg.update(dpublish)
                                                packet_avg['mac'] = mac_final
                                                packet_avg['np'] = d.__counter__
                                                packet_avg['counter'] = d.__counter__
                                                #print('Publishing average data', d.datakey_save)
                                                dataqueue.put(packet_avg)
                                                #print('Packet avg publish',packet_avg)
                                    except:
                                        logger.info('Could not average the data',exc_info=True)

                            # Remove from buffer
                            packetbuffer[macdown].pop(npmax)

                    try:
                        packetbuffer[macdown][np]
                    except:
                        packetbuffer[macdown][np] = {}

                    try:
                        packetbuffer[macdown][np][datatype]
                    except:
                        packetbuffer[macdown][np][datatype] = {}

                    packetbuffer[macdown][np][datatype][mac] = p

    return None

class RedvyprDeviceWidget(RedvyprDeviceWidget_simple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.show_numpackets = 1
        self.packetbuffer = {}
        self.datadisplaywidget = QtWidgets.QWidget(self)
        self.datadisplaywidget_layout = QtWidgets.QHBoxLayout(self.datadisplaywidget)
        self.tabwidget = QtWidgets.QTabWidget()
        self.datadisplaywidget_layout.addWidget(self.tabwidget)
        self.layout.addWidget(self.datadisplaywidget)
        self.avg_databuffer_dummy={}
        self.avg_addresses = {'R':[],'T':[]}
        self.avg_databuffer_dummy['R'] = create_avg_databuffer(self.device.custom_config.model_dump(), datatype='R')
        self.avg_databuffer_dummy['T'] = create_avg_databuffer(self.device.custom_config.model_dump(), datatype='T')
        for d in self.avg_databuffer_dummy['R']:
            self.avg_addresses['R'].append(d.get_return_addresses()['avg'])
            self.avg_addresses['R'].append(d.get_return_addresses()['std'])
        for d in self.avg_databuffer_dummy['T']:
            self.avg_addresses['T'].append(d.get_return_addresses()['avg'])
            self.avg_addresses['T'].append(d.get_return_addresses()['std'])


    def update_data(self, data):
        """
        """
        funcname = __name__ + '.update_data():'
        tnow = time.time()
        #print(funcname + 'Got some data', data)
        datatype = None
        icols = []  # The columns in the table that will be updated
        datatars = [] # The data in the columns to be updated
        colheaders = []
        headerlabels = {}
        # Check if datakeys has 'R' or 'T'
        if 'R' in data.keys():
            datatype = 'R'
            datatar = data[datatype]
            icol = 0
            icols.append(icol)
            datatars.append(datatar)
            colheaders.append(datatype)
        elif 'T' in data.keys():
            datatype = 'T'
            datatar = data[datatype]
            icol = 0
            icols.append(icol)
            datatars.append(datatar)
            colheaders.append(datatype)
        else:
            #print('Data',data)
            #print('Checking for average',data.keys())
            for datatype_tmp in self.avg_addresses:
                for icol_avg,a in enumerate(self.avg_addresses[datatype_tmp]):
                    rdata = redvypr.Datapacket(data)
                    #print('Address', rdata.datakeys())
                    #print('testing a', a, data in a, a in data)
                    if data in a:
                        icol = icol_avg + 1
                        #print('Found averaged data from address {} {}'.format(a,icol))
                        datatype = datatype_tmp
                        datatar = rdata[a]
                        icols.append(icol)
                        datatars.append(datatar)
                        colheaders.append(a.datakey)

        if len(icols) == 0:
            return

        for icol,datatar,colheader in zip(icols,datatars,colheaders):
            irows = ['mac', 'np', 'counter']  # Rows to plot
            try:
                np = data['np']
                mac = data['mac']
                counter = data['counter']
            except:
                logger.info('Could not get data',exc_info=True)
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
                numcols = 1 + len(self.avg_addresses[datatype])
                #print('Numcols')
                table.setColumnCount(numcols)
                #self.datadisplaywidget_layout.addWidget(table)
                self.tabwidget.addTab(table,'{} {}'.format(mac,datatype))
                headerlabels = []
                headerlabels.append(datatype)
                for icol_avg, a in enumerate(self.avg_addresses[datatype]):
                    headerlabels.append(a.datakey)

                table.setHorizontalHeaderLabels(headerlabels)

            # Fill the table
            #headeritem = QtWidgets.QTableWidgetItem(colheader)
            #table.setHorizontalHeaderItem(icol, headeritem)
            try:
                self.packetbuffer[mac][datatype]['packets'].append(data)
                # Update the table
                table = self.packetbuffer[mac][datatype]['table']
                if len(self.packetbuffer[mac][datatype]['packets']) > self.show_numpackets:
                    self.packetbuffer[mac][datatype]['packets'].pop(0)
                    #table.removeColumn(0)
                    #table.setColumnCount(self.show_numpackets)

                #print('Icol',icol)
                for irow,key in enumerate(irows):
                    d = data[key]
                    dataitem = QtWidgets.QTableWidgetItem(str(d))
                    table.setItem(irow, icol, dataitem)
                for i, d in enumerate(datatar):
                    datastr = "{:4f}".format(d)
                    dataitem = QtWidgets.QTableWidgetItem(datastr)
                    irowtar = i + irow
                    table.setItem(irowtar, icol, dataitem)
            except:
                logger.info('Does not work',exc_info=True)

        table.resizeColumnsToContents()

