import copy
import datetime
import pytz
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import qtawesome
import time
import yaml
import numpy
import logging
import sys
import pydantic
import xarray as xr
import redvypr
import redvypr.devices.sensors.generic_sensor.sensor_definitions as sensor_definitions
import redvypr.devices.sensors.calibration.calibration_models as calibration_models
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from redvypr.devices.sensors.tar import nmea_mac64_utils


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.tar_process')
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

#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict
tarv2nmea_R_sample_test1 = b'$D8478FFFFE95CD4D,1417,88.562500:$D8478FFFFE95CA01,TAR_S,R_B4,85.125000,23,88.125000,23,3703.171,3687.865,3689.992,3673.995,3663.933,3646.964,3650.582,3658.807,3658.235,3659.743,3677.440,3656.256,3667.873,3692.007,3700.870,3693.682,3714.597,3723.282,3741.300,3729.004,3742.731,3734.452,3760.982,3785.253,3748.399,3769.112,3764.206,3778.452,3766.012,3773.516,3774.506,3782.260,3754.508,3738.320,3731.787,3747.988,3719.920,3736.585,3730.321,3727.657,3729.182,3723.627,3738.785,3752.083,3736.633,3725.642,3747.952,3708.696,3727.275,3738.761,3734.088,3707.147,3733.981,3712.535,3716.624,3746.563,3726.405,3743.333,3719.324,3713.793,3726.637,3713.620,3743.029,3731.889\n'
tarv2nmea_R_sample_test2 = b'$D8478FFFFE95CD4D,1418,88.625000:$D8478FFFFE95CA01,TAR_S,T_B4,85.125000,23,88.125000,23,18.7687,18.8769,18.8618,18.9755,19.0472,19.1687,19.1427,19.0838,19.0879,19.0771,18.9509,19.1021,19.0191,18.8476,18.7849,18.8357,18.6882,18.6271,18.5011,18.5870,18.4911,18.5489,18.3641,18.1963,18.4516,18.3078,18.3418,18.2432,18.3292,18.2773,18.2705,18.2169,18.4091,18.5219,18.5675,18.4544,18.6507,18.5340,18.5778,18.5965,18.5858,18.6247,18.5186,18.4259,18.5337,18.6106,18.4547,18.7297,18.5991,18.5188,18.5515,18.7406,18.5522,18.7027,18.6739,18.4644,18.6052,18.4869,18.6549,18.6938,18.6036,18.6950,18.4890,18.5668\n'
tarv2nmea_R_test1 = b'$D8478FFFFE95CD4D,TAR,R_B4,88.125000,23,3791.505,3780.276,3783.786,3753.388,3735.459,3698.891,3713.560,3683.382,3725.874,3732.151,3738.183,3739.709,3744.310,3748.047,3752.655,3764.850,3759.181,3785.050,3776.687,3785.038,3828.752,3797.263,3797.710,3803.897,3824.091,3827.292,3829.092,3824.091,3837.073,3832.835,3796.941,3802.335,3752.142,3761.262,3754.997,3748.661,3758.782,3756.773,3764.004,3756.636,3772.050,3748.459,3745.413,3754.330,3753.191,3741.783,3730.935,3770.715,3731.245,3730.243,3753.847,3743.356,3744.942,3746.802,3766.078,3743.780,3763.622,3735.769,3750.420,3763.968,3752.762,3761.935,3727.597,3736.508\n'

config = {}
config['merge_tar_chain'] = True




# Generic tar sample, legacy, define two, one for R and one for T
if True:
    # T
    tarv2nmea_T_split = (
        br'^'  # Start of the string
        b'(?P<macparents>(?:\$[0-9A-F]+:)*)'  # Optional parent macs (not likely but can happen)
        b'\$(?P<mac>[0-9A-F]+),'  # The mac 
        b'TAR,'
        b'(?P<ntcnum>[0-9]+)'
        b'(?P<ntctype>[A-C])'
        b'(?P<ntcdist>[0-9]),'
        b'T(?P<ntcistart>[0-9]+)-(?P<ntciend>[0-9]+),'
        b'(?P<t>[0-9.]+),'
        b'(?P<np>[0-9]+),'
        b'(?P<T>.*)\n'
    )
    tarv2nmea_T_str_format = {'mac': 'str', 't': 'float', 'ntctype': 'str',
                              'ntcistart':'int','ntciend':'int','ntcnum':'int',
                              'ntcdist': 'float', 'np': 'int', 'T': 'array'}
    tarv2nmea_T_datakey_metadata = {'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
                                           'np': {'unit': 'counter'}, 'T': {'unit': 'degC'}}
    tarv2nmea_T_packetid_format = '__TAR__T'
    tarv2nmea_T_description = 'Temperature array temperaturedatapacket'
    # R
    tarv2nmea_R_split = (
        br'^'  # Start of the string
        b'(?P<macparents>(?:\$[0-9A-F]+:)*)'  # Optional parent macs (not likely but can happen)
        b'\$(?P<mac>[0-9A-F]+),'  # The mac 
        b'TAR,'
        b'(?P<ntcnum>[0-9]+)'
        b'(?P<ntctype>[A-C])'
        b'(?P<ntcdist>[0-9]),'
        b'R(?P<ntcistart>[0-9]+)-(?P<ntciend>[0-9]+),'
        b'(?P<t>[0-9.]+),'
        b'(?P<np>[0-9]+),'
        b'(?P<R>.*)\n'
    )
    tarv2nmea_R_str_format = {'mac': 'str', 't': 'float', 'ntctype': 'str',
                              'ntcistart': 'int', 'ntciend': 'int', 'ntcnum': 'int',
                              'ntcdist': 'float', 'np': 'int', 'R': 'array'}
    tarv2nmea_R_datakey_metadata = {'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
                                    'np': {'unit': 'counter'}, 'R': {'unit': 'Ohm'}}
    tarv2nmea_R_packetid_format = '__TAR__R'
    tarv2nmea_R_description = 'Temperature array resistance datapacket'


if True:
    #tarv2nmea_R_sample_split = b'\$(?P<mac>.+),TAR_S;(?P<counter>[0-9.]+);(?P<np>[0-9]+),R_(?P<ntctype>[A-c])(?P<ntcdist>[0-9]),(?P<counter_local>[0-9.]+),(?P<np_local>[0-9]+),(?P<R>.*)\n'
    #tarv2nmea_R_sample_str_format = {'mac': 'str', 'counter': 'float', 'counter_local': 'float', 'ntctype': 'str',
    #                                 'ntcdist': 'float', 'np': 'int', 'np_local': 'int', 'R': 'array'}
    #tarv2nmea_R_sample_datakey_metadata = {'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
    #                                       'np': {'unit': 'counter'}, 'R': {'unit': 'Ohm'}}
    #tarv2nmea_R_sample_packetid_format = '__TAR_S__R'
    #tarv2nmea_R_sample_description = 'Temperature array datapacket initiated by a sample command'

    # T
    # b'$D8478FFFFE95E740:$D8478FFFFE95CA01:$D8478FFFFE960155:$D8478FFFFE95CD4D,TAR(42708.062,10678),64B4,T32-63,42709.125,10680,19.913,19.773,19.743,19.721,19.583,19.543,19.434,19.431,19.267,19.387,19.369,19.262,19.226,19.274,19.309,18.989,19.224,19.191,18.978,19.017,18.970,18.928,18.770,18.901,18.742,18.922,18.805,18.702,18.770,18.701,18.938,18.872\n'
    # Non working datastring
    # b'$D8478FFFF.553,41:$D8478FFFFE95E740:$D8478FFFFE960155:$D8478FFFFE95CD4D,TAR(172.062,44),64B4,T0-31,172.062,45,46.358,46.873,47.110,46.911,47.266,47.559,47.617,47.432,47.335,47.218,46.552,45.761,45.958,45.724,45.483,45.408,45.385,44.839,44.621,44.592,45.320,45.118,42.553,45.257,45.214,45.834,45.449,44.843,45.244,45.435,45.606,46.310\n'
    tarv2nmea_T_sample_split = (
        br'^'  # Start of the string
        b'(?P<macparents>(?:\$[0-9A-F]+:)*)'  # Optional parent macs
        b'\$(?P<mac>[0-9A-F]+),'  # The mac 
        b'TAR\((?P<t>[0-9.]+),(?P<np>[0-9]+)\),'
        b'(?P<ntcnum>[0-9]+)'
        b'(?P<ntctype>[A-C])'
        b'(?P<ntcdist>[0-9]),'
        b'T(?P<ntcistart>[0-9]+)-(?P<ntciend>[0-9]+),'
        b'(?P<counter_local>[0-9.]+),'
        b'(?P<np_local>[0-9]+),'
        b'(?P<T>.*)\n'
    )
    tarv2nmea_T_sample_str_format = {'mac': 'str', 't': 'float', 'counter_local': 'float',
                                     'macparents': 'str', 'ntctype': 'str',
                                     'ntcistart': 'int', 'ntciend': 'int', 'ntcnum': 'int',
                                     'ntcdist': 'float', 'np': 'int', 'np_local': 'int', 'T': 'array'}
    tarv2nmea_T_sample_datakey_metadata = {'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
                                           'np': {'unit': 'counter'}, 'T': {'unit': 'degC'}}
    tarv2nmea_T_sample_packetid_format = '__TAR_S__T'
    tarv2nmea_T_sample_description = 'Temperature array datapacket initiated by a sample command'
    # R
    tarv2nmea_R_sample_split = (
        br'^'  # Start of the string
        b'(?P<macparents>(?:\$[0-9A-F]+:)*)'  # Optional parent macs
        b'\$(?P<mac>[0-9A-F]+),'  # The mac 
        b'TAR\((?P<t>[0-9.]+),(?P<np>[0-9]+)\),'
        b'(?P<ntcnum>[0-9]+)'
        b'(?P<ntctype>[A-C])'
        b'(?P<ntcdist>[0-9]),'
        b'R(?P<ntcistart>[0-9]+)-(?P<ntciend>[0-9]+),'
        b'(?P<counter_local>[0-9.]+),'
        b'(?P<np_local>[0-9]+),'
        b'(?P<R>.*)\n'
    )
    tarv2nmea_R_sample_str_format = {'mac': 'str', 't': 'float', 'counter_local': 'float',
                                     'macparents': 'str', 'ntctype': 'str',
                                     'ntcistart': 'int', 'ntciend': 'int', 'ntcnum': 'int',
                                     'ntcdist': 'float', 'np': 'int', 'np_local': 'int', 'R': 'array'}
    tarv2nmea_R_sample_datakey_metadata = {'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
                                           'np': {'unit': 'counter'}, 'R': {'unit': 'Ohm'}}
    tarv2nmea_R_sample_packetid_format = '__TAR_S__R'
    tarv2nmea_R_sample_description = 'Temperature array resistance datapacket initiated by a sample command'


class TarProcessor():
    def __init__(self):
        self.init_buffer()
        self.init_sensors()
    def init_buffer(self):
        self.packetbuffer_tar_merge = {}  # A buffer to add split messages into one packet
        self.packetbuffer_nump_tar = {}  # A packetbuffer to add split messages into one packet
        # packetbuffer = {-1000:None} # Add a dummy key
        self.packetbuffer = {}
        self.np_lastpublished = -1000
        self.csv_save_data = {}
        self.sensors_datasizes = {}
        self.np_last = -1000
        self.np_first = None
        self.nump_max = -1000
        self.np_processed_counter = 0
        self.np_processed = -1000
        self.num_tar_sensors_max = 0
        self.tar_setup = []
        self.data_merged_xr_all = {}

    def init_sensors(self):
        tarv2nmea_T = sensor_definitions.BinarySensor(name='tarv2nmea_T', regex_split=tarv2nmea_T_split,
                                                             str_format=tarv2nmea_T_str_format,
                                                             autofindcalibration=False,
                                                             description=tarv2nmea_T_description,
                                                             datakey_metadata=tarv2nmea_T_datakey_metadata,
                                                             packetid_format=tarv2nmea_T_packetid_format,
                                                             datastream=redvypr.RedvyprAddress('/k:data'))

        tarv2nmea_R = sensor_definitions.BinarySensor(name='tarv2nmea_R', regex_split=tarv2nmea_R_split,
                                                      str_format=tarv2nmea_R_str_format,
                                                      autofindcalibration=False,
                                                      description=tarv2nmea_R_description,
                                                      datakey_metadata=tarv2nmea_R_datakey_metadata,
                                                      packetid_format=tarv2nmea_R_packetid_format,
                                                      datastream=redvypr.RedvyprAddress('/k:data'))

        tarv2nmea_T_sample = sensor_definitions.BinarySensor(name='tarv2nmea_T_sample',
                                                             regex_split=tarv2nmea_T_sample_split,
                                                             str_format=tarv2nmea_T_sample_str_format,
                                                             autofindcalibration=False,
                                                             description=tarv2nmea_T_sample_description,
                                                             datakey_metadata=tarv2nmea_T_sample_datakey_metadata,
                                                             packetid_format=tarv2nmea_T_sample_packetid_format,
                                                             datastream=redvypr.RedvyprAddress('/k:data'))

        tarv2nmea_R_sample = sensor_definitions.BinarySensor(name='tarv2nmea_R_sample',
                                                             regex_split=tarv2nmea_R_sample_split,
                                                             str_format=tarv2nmea_R_sample_str_format,
                                                             autofindcalibration=False,
                                                             description=tarv2nmea_R_sample_description,
                                                             datakey_metadata=tarv2nmea_R_sample_datakey_metadata,
                                                             packetid_format=tarv2nmea_R_sample_packetid_format,
                                                             datastream=redvypr.RedvyprAddress('/k:data'))

        # Create the tar sensors
        self.datatypes = []
        self.sensors = []

        self.sensors.append(tarv2nmea_T)
        self.datatypes.append('T')
        self.sensors.append(tarv2nmea_R)
        self.datatypes.append('R')
        self.sensors.append(tarv2nmea_T_sample)
        self.datatypes.append('T')
        self.sensors.append(tarv2nmea_R_sample)
        self.datatypes.append('R')

    def merge_datapackets(self, data_packet_processed):
        merged_packets = []
        if data_packet_processed is not None:
            if len(data_packet_processed) > 0:
                for ip, p in enumerate(data_packet_processed):
                    try:
                        mactmp = p['macparents'] + '$' + p['mac']
                    except:
                        mactmp = p['mac']

                    print('Packet', p)
                    print('Packet with mac')
                    print('Mactmp', mactmp)
                    mac_parsed = nmea_mac64_utils.parse_nmea_mac64_string(mactmp)
                    print('mac parsed', mac_parsed)
                    if mac_parsed is None:  # Not a valid mac
                        continue

                    # print('p',p)
                    p['mac'] = mac_parsed['mac']
                    p['parents'] = mac_parsed['parents']

                    num_tar_sensors = len(p['parents']) + 1
                    if self.num_tar_sensors_max < num_tar_sensors:
                        self.num_tar_sensors_max = num_tar_sensors
                        self.tar_setup = p['parents'] + [p['mac']]
                    # try:
                    #    print('p',p['macparents'])
                    #    p['parents'] = p['macparents'].split(':')
                    # except:
                    #    p['parents']=[]

                    packetid = p['mac'] + p['_redvypr']['packetid']
                    datatype_packet = packetid.split('__')[-1]
                    p['_redvypr']['packetid'] = packetid
                    mac = p['mac']
                    nump = p['np']
                    self.nump_max = max(self.nump_max,nump)

                    print('mac {} {} nump:{} packettype: {}'.format(ip, mactmp, nump, datatype_packet))
                    flag_valid_packet = False
                    # Packets that do not need to be merged
                    if (datatype_packet != 'T') and (datatype_packet != 'R'):
                        pass
                        # flag_valid_packet = True
                    else:  # T and R needs to be merged
                        # print('Merging packet',p)
                        print('Merging packet', p['ntcistart'], p['ntciend'], p['ntcnum'], p['mac'], p['parents'])
                        self.sensors_datasizes[mac] = p['ntcnum']
                        try:
                            dataarray = self.packetbuffer_tar_merge[mac][datatype_packet][nump]['dataarray']
                        except:
                            # print('Creating array')
                            dataarray = numpy.zeros(p['ntcnum']) * numpy.nan

                        print('Shape dataarray', numpy.shape(dataarray))
                        #
                        try:
                            self.packetbuffer_tar_merge[mac]
                        except:
                            self.packetbuffer_tar_merge[mac] = {}
                        try:
                            self.packetbuffer_tar_merge[mac][datatype_packet]
                        except:
                            self.packetbuffer_tar_merge[mac][datatype_packet] = {}
                        try:
                            self.packetbuffer_tar_merge[mac][datatype_packet][nump]
                        except:
                            self.packetbuffer_tar_merge[mac][datatype_packet][nump] = {'dataarray':None,'nmerged':0,'ntcnum':p['ntcnum'],'packets_raw':[]}
                        #
                        try:
                            self.packetbuffer_nump_tar[nump]
                        except:
                            self.packetbuffer_nump_tar[nump] = {}
                        try:
                            self.packetbuffer_nump_tar[nump][datatype_packet]
                        except:
                            self.packetbuffer_nump_tar[nump][datatype_packet] = {}
                        try:
                            self.packetbuffer_nump_tar[nump][datatype_packet][mac]
                        except:
                            self.packetbuffer_nump_tar[nump][datatype_packet][mac] = None

                        # Check if the dataarray is big enough
                        # if len(dataarray) < p['ntciend'] + 1:
                        try:
                            dataarray[p['ntcistart']:p['ntciend'] + 1] = p[datatype_packet]
                        except:
                            logger.debug('Could not add data', exc_info=True)

                        self.packetbuffer_tar_merge[mac][datatype_packet][nump]['dataarray'] = dataarray
                        self.packetbuffer_tar_merge[mac][datatype_packet][nump]['nmerged'] += len(p[datatype_packet])
                        self.packetbuffer_tar_merge[mac][datatype_packet][nump]['packets_raw'].append(p)


                        np_processed = nump
                        if self.np_first is None:
                            self.np_first = nump
                        else:
                            self.np_processed_counter = nump - self.np_first

                        # Check if the packet is merged
                        nmerged = self.packetbuffer_tar_merge[mac][datatype_packet][nump]['nmerged']
                        nntc = self.packetbuffer_tar_merge[mac][datatype_packet][nump]['ntcnum']
                        if nmerged == nntc:
                            print('Merge completed!!!')
                            print('Merge completed!!!')
                            print('Merge completed!!!')
                            dataarray_merged = self.packetbuffer_tar_merge[mac][datatype_packet][nump]['dataarray']

                            praw = self.packetbuffer_tar_merge[mac][datatype_packet][nump]['packets_raw'][0]
                            pmerged = praw.copy()
                            pmerged.pop('ntcistart')
                            pmerged.pop('ntciend')
                            pmerged[datatype_packet] = dataarray_merged
                            merged_packets.append(pmerged)
                            self.packetbuffer_nump_tar[nump][datatype_packet][mac] = pmerged

                # print('Datapacket processed',data_packet_processed)
                # logger.debug('Data packet processed (without calibration):{}'.format(len(data_packet_processed)))
                # print('mac',mac,counter,np)
        return merged_packets
    def merge_tar_chain(self):
        if config['merge_tar_chain'] and (self.np_processed_counter) > 10:
            # Creating array
            print('Merging packets')
            numps = list(self.packetbuffer_nump_tar.keys())
            print('Numps', numps, self.num_tar_sensors_max, self.tar_setup)
            for nump_merge in numps[:-1]:  # Dont merge the last one
                ppub_dict = self.packetbuffer_nump_tar.pop(nump_merge)
                for datatype_merge in ppub_dict.keys():
                    print('Merging packet {} with datatype'.format(nump_merge, datatype_merge))
                    ppub = ppub_dict[datatype_merge]
                    print('HALLO', ppub)
                    print('HALLO HALLO')
                    # input('fds')
                    data_merged = []
                    t_merge = None
                    mac_final = 'TARM_' + self.tar_setup[0] + 'N{}'.format(len(self.tar_setup))
                    if datatype_merge == 'T':
                        unitstr = 'degC'
                    elif datatype_merge == 'R':
                        unitstr = 'Ohm'
                    for ntar, mac_merge in enumerate(self.tar_setup):  # Merge according to the sensor design
                        try:
                            data_merge = ppub[mac_merge][datatype_merge]
                        except:
                            logger.info('MAC not in buffer {}'.format(mac_merge))
                            ntcnum = self.sensors_datasizes[mac_merge]
                            data_merge = numpy.zeros(ntcnum) * numpy.nan

                        data_merged.append(data_merge)
                        if t_merge is None:
                            try:
                                t_merge = ppub[mac_merge]['t']
                            except:
                                pass

                    data_merged = numpy.hstack(data_merged)
                    print('data merged')
                    print(data_merged)
                    print('Done')
                    coord = {'time': numpy.asarray([t_merge]),
                             'numntc': numpy.arange(len(data_merged))}

                    data_tmp = numpy.zeros((1, len(data_merged)))
                    data_tmp[0, :] = data_merged
                    data_merged_xr = xr.DataArray(data_tmp,
                                                  dims=['time', 'numntc'],
                                                  coords=coord)

                    nump_xr = xr.DataArray([nump_merge],
                                           dims=['time'],
                                           coords={'time': numpy.asarray([t_merge])})

                    dataset_merged_xr = xr.Dataset(coords=coord)
                    dataset_merged_xr.attrs["units"] = unitstr
                    dataset_merged_xr[datatype_merge] = data_merged_xr
                    dataset_merged_xr['np'] = nump_xr

                    print('nump merge', nump_merge)
                    # Concat to xarray
                    try:
                        self.data_merged_xr_all[datatype_merge]
                    except:
                        logger.info('Creating xarray', exc_info=True)
                        self.data_merged_xr_all[datatype_merge] = xr.Dataset(coords=coord)
                        # data_merged_xr_all[datatype_merge][datatype_merge].attrs["units"] = unitstr
                        self.data_merged_xr_all[datatype_merge].attrs["mac"] = mac_final

                    self.data_merged_xr_all[datatype_merge] = xr.concat(
                        [self.data_merged_xr_all[datatype_merge], dataset_merged_xr], dim='time')
                    self.data_merged_xr_all[datatype_merge][datatype_merge].attrs["units"] = unitstr
                    print('data merged xr', self.data_merged_xr_all[datatype_merge])



    def process_rawdata(self, binary_data):
        packets = {'merged_packets':None,'merged_tar_chain':None}
        for sensor, datatype in zip(self.sensors, self.datatypes):
            # print('Checking for sensor',sensor,datatype)
            # Check for overflow
            datapacket = redvypr.Datapacket()
            datapacket['data'] = binary_data
            datapacket['t'] = time.time()
            try:
                if b'..\n' in binary_data:
                    data_packet_processed = None
                else:
                    data_packet_processed = sensor.datapacket_process(datapacket, datakey='data')
            except:
                logger.debug('Could not process data', exc_info=True)
                print('Could not get data')

            if data_packet_processed is not None:
                break

        if data_packet_processed is not None:
            merged_packets = self.merge_datapackets(data_packet_processed)
            packets['merged_packets'] = merged_packets
            self.merge_tar_chain()

        return packets

    def process_file(self, filename_tar):
        f = open(filename_tar, 'rb')
        for binary_data in f.readlines():
            print('data from line', binary_data)
            self.process_rawdata(binary_data)

    def to_ncfile(self):
        if True:
            for datatype_merge in self.data_merged_xr_all.keys():
                mac_final = self.data_merged_xr_all[datatype_merge].attrs["mac"]
                fname_nc = mac_final + '_' + datatype_merge + '.nc'
                print('saving to:{}'.format(fname_nc))
                self.data_merged_xr_all[datatype_merge].to_netcdf(fname_nc)










