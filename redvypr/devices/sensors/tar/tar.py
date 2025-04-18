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
import redvypr
from redvypr.data_packets import check_for_command
from redvypr.device import RedvyprDevice
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.devices.sensors.generic_sensor.calibrationWidget import GenericSensorCalibrationWidget
import redvypr.devices.sensors.calibration.calibration_models as calibration_models
import redvypr.devices.sensors.generic_sensor.sensor_definitions as sensor_definitions
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from . import sensor_firmware_config
from . import nmea_mac64_utils
from redvypr.utils.databuffer import DatapacketAvg


#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict
tarv2nmea_R_sample_test1 = b'$D8478FFFFE95CD4D,1417,88.562500:$D8478FFFFE95CA01,TAR_S,R_B4,85.125000,23,88.125000,23,3703.171,3687.865,3689.992,3673.995,3663.933,3646.964,3650.582,3658.807,3658.235,3659.743,3677.440,3656.256,3667.873,3692.007,3700.870,3693.682,3714.597,3723.282,3741.300,3729.004,3742.731,3734.452,3760.982,3785.253,3748.399,3769.112,3764.206,3778.452,3766.012,3773.516,3774.506,3782.260,3754.508,3738.320,3731.787,3747.988,3719.920,3736.585,3730.321,3727.657,3729.182,3723.627,3738.785,3752.083,3736.633,3725.642,3747.952,3708.696,3727.275,3738.761,3734.088,3707.147,3733.981,3712.535,3716.624,3746.563,3726.405,3743.333,3719.324,3713.793,3726.637,3713.620,3743.029,3731.889\n'
tarv2nmea_R_sample_test2 = b'$D8478FFFFE95CD4D,1418,88.625000:$D8478FFFFE95CA01,TAR_S,T_B4,85.125000,23,88.125000,23,18.7687,18.8769,18.8618,18.9755,19.0472,19.1687,19.1427,19.0838,19.0879,19.0771,18.9509,19.1021,19.0191,18.8476,18.7849,18.8357,18.6882,18.6271,18.5011,18.5870,18.4911,18.5489,18.3641,18.1963,18.4516,18.3078,18.3418,18.2432,18.3292,18.2773,18.2705,18.2169,18.4091,18.5219,18.5675,18.4544,18.6507,18.5340,18.5778,18.5965,18.5858,18.6247,18.5186,18.4259,18.5337,18.6106,18.4547,18.7297,18.5991,18.5188,18.5515,18.7406,18.5522,18.7027,18.6739,18.4644,18.6052,18.4869,18.6549,18.6938,18.6036,18.6950,18.4890,18.5668\n'
tarv2nmea_R_test1 = b'$D8478FFFFE95CD4D,TAR,R_B4,88.125000,23,3791.505,3780.276,3783.786,3753.388,3735.459,3698.891,3713.560,3683.382,3725.874,3732.151,3738.183,3739.709,3744.310,3748.047,3752.655,3764.850,3759.181,3785.050,3776.687,3785.038,3828.752,3797.263,3797.710,3803.897,3824.091,3827.292,3829.092,3824.091,3837.073,3832.835,3796.941,3802.335,3752.142,3761.262,3754.997,3748.661,3758.782,3756.773,3764.004,3756.636,3772.050,3748.459,3745.413,3754.330,3753.191,3741.783,3730.935,3770.715,3731.245,3730.243,3753.847,3743.356,3744.942,3746.802,3766.078,3743.780,3763.622,3735.769,3750.420,3763.968,3752.762,3761.935,3727.597,3736.508\n'



# Generic tar sample, legacy, define two, one for R and one for T
if True:
    # T
    tarv2nmea_T_split = (
        b'(?P<macparents>(?:\$[0-9A-F]+:)*)'  # Optional parent macs (not likely but can happen)
        b'\$(?P<mac>[0-9A-F]+),'  # The mac 
        b'TAR,'
        b'(?P<ntcnum>[0-9]+)'
        b'(?P<ntctype>[A-C])'
        b'(?P<ntcdist>[0-9]),'
        b'T(?P<ntcistart>[0-9]+)-(?P<ntciend>[0-9]+),'
        b'(?P<counter>[0-9.]+),'
        b'(?P<np>[0-9]+),'
        b'(?P<T>.*)\n'
    )
    tarv2nmea_T_str_format = {'mac': 'str', 'counter': 'float', 'ntctype': 'str',
                              'ntcistart':'int','ntciend':'int','ntcnum':'int',
                              'ntcdist': 'float', 'np': 'int', 'T': 'array'}
    tarv2nmea_T_datakey_metadata = {'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
                                           'np': {'unit': 'counter'}, 'T': {'unit': 'degC'}}
    tarv2nmea_T_packetid_format = '__TAR__T'
    tarv2nmea_T_description = 'Temperature array temperaturedatapacket'
    # R
    tarv2nmea_R_split = (
        b'(?P<macparents>(?:\$[0-9A-F]+:)*)'  # Optional parent macs (not likely but can happen)
        b'\$(?P<mac>[0-9A-F]+),'  # The mac 
        b'TAR,'
        b'(?P<ntcnum>[0-9]+)'
        b'(?P<ntctype>[A-C])'
        b'(?P<ntcdist>[0-9]),'
        b'R(?P<ntcistart>[0-9]+)-(?P<ntciend>[0-9]+),'
        b'(?P<counter>[0-9.]+),'
        b'(?P<np>[0-9]+),'
        b'(?P<R>.*)\n'
    )
    tarv2nmea_R_str_format = {'mac': 'str', 'counter': 'float', 'ntctype': 'str',
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
    tarv2nmea_T_sample_split = (
        b'(?P<macparents>(?:\$[0-9A-F]+:)*)'  # Optional parent macs
        b'\$(?P<mac>[0-9A-F]+),'  # The mac 
        b'TAR\((?P<counter>[0-9.]+),(?P<np>[0-9]+)\),'
        b'(?P<ntcnum>[0-9]+)'
        b'(?P<ntctype>[A-C])'
        b'(?P<ntcdist>[0-9]),'
        b'T(?P<ntcistart>[0-9]+)-(?P<ntciend>[0-9]+),'
        b'(?P<counter_local>[0-9.]+),'
        b'(?P<np_local>[0-9]+),'
        b'(?P<T>.*)\n'
    )
    tarv2nmea_T_sample_str_format = {'mac': 'str', 'counter': 'float', 'counter_local': 'float',
                                     'macparents': 'str', 'ntctype': 'str',
                                     'ntcistart': 'int', 'ntciend': 'int', 'ntcnum': 'int',
                                     'ntcdist': 'float', 'np': 'int', 'np_local': 'int', 'T': 'array'}
    tarv2nmea_T_sample_datakey_metadata = {'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
                                           'np': {'unit': 'counter'}, 'T': {'unit': 'degC'}}
    tarv2nmea_T_sample_packetid_format = '__TAR_S__T'
    tarv2nmea_T_sample_description = 'Temperature array datapacket initiated by a sample command'
    # R
    tarv2nmea_R_sample_split = (
        b'(?P<macparents>(?:\$[0-9A-F]+:)*)'  # Optional parent macs
        b'\$(?P<mac>[0-9A-F]+),'  # The mac 
        b'TAR\((?P<counter>[0-9.]+),(?P<np>[0-9]+)\),'
        b'(?P<ntcnum>[0-9]+)'
        b'(?P<ntctype>[A-C])'
        b'(?P<ntcdist>[0-9]),'
        b'R(?P<ntcistart>[0-9]+)-(?P<ntciend>[0-9]+),'
        b'(?P<counter_local>[0-9.]+),'
        b'(?P<np_local>[0-9]+),'
        b'(?P<R>.*)\n'
    )
    tarv2nmea_R_sample_str_format = {'mac': 'str', 'counter': 'float', 'counter_local': 'float',
                                     'macparents': 'str', 'ntctype': 'str',
                                     'ntcistart': 'int', 'ntciend': 'int', 'ntcnum': 'int',
                                     'ntcdist': 'float', 'np': 'int', 'np_local': 'int', 'R': 'array'}
    tarv2nmea_R_sample_datakey_metadata = {'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
                                           'np': {'unit': 'counter'}, 'R': {'unit': 'Ohm'}}
    tarv2nmea_R_sample_packetid_format = '__TAR_S__R'
    tarv2nmea_R_sample_description = 'Temperature array resistance datapacket initiated by a sample command'






#IMU
#'$D8478FFFFE95E740:$D8478FFFFE95CA01:$D8478FFFFE960155:$D8478FFFFE95CD4D,TAR_S;4944.062;1237,IM,4946.688,1240,-8064,1308,321,-108,73,16,1630\n'

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
    merge_tar_chain: bool = True
    publish_single_sensor_sentence: bool = True
    publish_raw_sensor: bool = True
    size_packetbuffer: int = 10





def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname)
    packetbuffer_tar = {}  # A buffer to add split messages into one packet
    #packetbuffer = {-1000:None} # Add a dummy key
    packetbuffer = {}
    np_lastpublished = -1000

    # Create the tar sensors
    datatypes = []
    sensors = []

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

    sensors.append(tarv2nmea_T)
    datatypes.append('T')
    sensors.append(tarv2nmea_R)
    datatypes.append('R')
    sensors.append(tarv2nmea_T_sample)
    datatypes.append('T')
    sensors.append(tarv2nmea_R_sample)
    datatypes.append('R')

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
        #    print('Done done done')
        #except:
        #    continue


        for sensor,datatype in zip(sensors,datatypes):
            #print('Checking for sensor',sensor,datatype)
            data_packet_processed = sensor.datapacket_process(datapacket)
            if data_packet_processed is not None:
                break



        if data_packet_processed is not None:
            if len(data_packet_processed) > 0:
                for ip,p in enumerate(data_packet_processed):
                    if config['publish_single_sensor_sentence']:
                        ppublish = copy.deepcopy(p)
                        ppublish['_redvypr']['packetid'] += '_raw'
                        ppublish['mac'] += '_raw'
                        istr = "_i{}-{}".format(ppublish['ntcistart'],ppublish['ntciend'] + 1)
                        packetid = ppublish['mac'] + ppublish['_redvypr']['packetid'] + istr
                        ppublish['_redvypr']['packetid'] = packetid
                        dataqueue.put(ppublish)
                    #print('p',p)
                    try:
                        mactmp = p['macparents'] +'$'+  p['mac']
                    except:
                        mactmp = p['mac']

                    print('Mactmp',mactmp)
                    mac_parsed = nmea_mac64_utils.parse_nmea_mac64_string(mactmp)
                    print('mac parsed',mac_parsed)
                    p['mac'] = mac_parsed['mac']
                    p['parents'] = mac_parsed['parents']
                    #try:
                    #    print('p',p['macparents'])
                    #    p['parents'] = p['macparents'].split(':')
                    #except:
                    #    p['parents']=[]

                    packetid = p['mac'] + p['_redvypr']['packetid']
                    datatype_packet = packetid.split('__')[-1]
                    p['_redvypr']['packetid'] = packetid
                    mac = p['mac']
                    nump = p['np']
                    print('mac {} {} nump:{} packettype: {}'.format(ip,mactmp,nump,datatype_packet))
                    flag_valid_packet = False
                    # Packets that do not need to be merged
                    if (datatype_packet != 'T') and (datatype_packet != 'R'):
                        dataqueue.put(p)
                        #flag_valid_packet = True
                    else:  # T and R needs to be merged
                        #print('Merging packet',p)
                        #print('Merging packet',p['ntcistart'],p['ntciend'],p['ntcnum'],p['mac'],p['parents'])
                        try:
                            dataarray = packetbuffer_tar[mac][datatype_packet][nump][datatype_packet]
                        except:
                            #print('Creating array')
                            dataarray = numpy.zeros(p['ntcnum']) * numpy.nan

                        try:
                            packetbuffer_tar[mac]
                        except:
                            packetbuffer_tar[mac] = {}
                        try:
                            packetbuffer_tar[mac][datatype_packet]
                        except:
                            packetbuffer_tar[mac][datatype_packet] = {}
                        try:
                            packetbuffer_tar[mac][datatype_packet][nump]
                        except:
                            packetbuffer_tar[mac][datatype_packet][nump] = p


                        dataarray[p['ntcistart']:p['ntciend']+1] = p[datatype_packet]
                        packetbuffer_tar[mac][datatype_packet][nump][datatype_packet] = dataarray
                        if sum(numpy.isnan(dataarray)) == 0:
                            print('Publishing packet ...',mac,len(packetbuffer_tar[mac][datatype_packet][nump][datatype_packet]))
                            dataarray = packetbuffer_tar[mac][datatype_packet][nump][datatype_packet]
                            packetbuffer_tar[mac][datatype_packet][nump][datatype_packet] = list(dataarray)
                            ppub = packetbuffer_tar[mac][datatype_packet].pop(nump)
                            datapacket_process = ppub
                            if config['publish_raw_sensor']:
                                dataqueue.put(ppub)
                            flag_valid_packet = True




                #print('Datapacket processed',data_packet_processed)
                #logger.debug('Data packet processed (without calibration):{}'.format(len(data_packet_processed)))
                #print('mac',mac,counter,np)
                if config['merge_tar_chain'] and flag_valid_packet:
                    pmerge = datapacket_process
                    mac = pmerge['mac']
                    parents = pmerge['parents']
                    counter = pmerge['counter']
                    nump = pmerge['np']
                    print('Merging groups',mac,parents,nump)
                    # Check if we have the downstream device, if yes process, else do nothing
                    if len(parents) == 0:  # The most downstream device
                        macdown = mac
                    else:  # Device with parents
                        #macdown = mac
                        macdown = parents[0]

                    if True:
                        # Add the data to the buffer
                        try:
                            npmax = max(packetbuffer[macdown].keys())
                        except:
                            npmax = -1000

                        try:
                            npmin = min(packetbuffer[macdown].keys())
                        except:
                            npmin = -10000

                        print('npmax', npmax, 'nump', nump)
                        print('npmin', npmin, 'nump', nump)
                        # Check if a new packet arrived (meaning that np is larger than npmax)
                        # If yes, merge all parts of the old one first
                        if (nump > npmin) and (npmin > 0):  # Process packetnumber npmax
                            print('Nump > npmin')
                            for nptmp in packetbuffer[macdown].keys():  # Loop over all datatypes
                                for datatype_tmp in packetbuffer[macdown][nptmp].keys():
                                    for mactmp2 in packetbuffer[macdown][nptmp][datatype_tmp].keys():
                                        print('packetuffer keys', nptmp, datatype_tmp, mactmp2, 'macdown',macdown, npmax)

                            packets_publish = {}
                            flag_packet_publish = False
                            for npmerge in packetbuffer[macdown].keys():  # Loop over all datatypes
                                print('Merging',npmerge,nump)
                                if npmerge == nump:
                                    continue

                                packets_publish[npmerge] = {}
                                for datatype_tmp in packetbuffer[macdown][npmerge].keys():  # Loop over all datatypes
                                    npackets = len(packetbuffer[macdown][npmerge][datatype_tmp].keys())
                                    #print('!npmax', npmerge, datatype_tmp,'packets',npackets)
                                    datapacket_merged = {}
                                    mac_final = 'TARM_' + macdown
                                    counter_final = npmerge
                                    # The merged packetid
                                    packetid_final = '{}__TAR__{}_merged'.format(mac_final, datatype_tmp)
                                    dp = redvypr.Datapacket(packetid=packetid_final)
                                    datapacket_merged.update(dp)
                                    datapacket_merged['mac'] = mac_final
                                    datapacket_merged['counter'] = counter_final
                                    dmerge = [None] * npackets
                                    try:
                                        packetbuffer[macdown][npmerge][datatype_tmp]['merge_attempts']
                                    except:
                                        packetbuffer[macdown][npmerge][datatype_tmp]['merge_attempts'] = 0

                                    for mac_tmp in packetbuffer[macdown][npmerge][datatype_tmp].keys():
                                        if mac_tmp == 'merge_attempts':  # Check if merge did not work out
                                            packetbuffer[macdown][npmerge][datatype_tmp]['merge_attempts'] += 1
                                            if packetbuffer[macdown][npmerge][datatype_tmp]['merge_attempts'] > 30:
                                                packets_publish[npmerge][datatype_tmp] = None
                                                flag_packet_publish = True
                                                print('Merging failed, will mark {} to be removed'.format(npmerge))

                                            continue

                                        pmerge2 = packetbuffer[macdown][npmerge][datatype_tmp][mac_tmp]
                                        parents_tmp = pmerge2['parents']
                                        # Count the number of parents and put it at the list location
                                        i = len(parents_tmp)
                                        if i >= npackets:
                                            #while npackets <= i+1:
                                            #    npackets += 1
                                            #    dmerge.append(None)
                                            logger.debug('Could not add {}'.format(mac_tmp))
                                            continue

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
                                    if mac_final is not None:
                                        tar_merge = numpy.hstack(dmerge).tolist()
                                        #print('Tar merge',len(tar_merge))
                                        datapacket_merged[datatype_tmp] = tar_merge
                                        datapacket_merged['np'] = npmerge
                                        datapacket_merged['datatype'] = datatype_tmp
                                        datapacket_merged['t'] = p['t']  # Add time
                                        #print('publish merged data, merged merged')
                                        logger.info('Publishing merged data {} {} {}'.format(mac_final, nump,datatype))
                                        # Adding the merged data to the publish dictionary
                                        packets_publish[npmerge][datatype_tmp] = datapacket_merged
                                        flag_packet_publish = True
                                        np_lastpublished = npmerge

                            if flag_packet_publish:
                                print('Publishing the merged data')
                                for npmerge in packets_publish.keys():  # Loop over all datatypes
                                    for datatype_tmp in packets_publish[npmerge].keys():  # Loop over all datatypes
                                        print('Publishing',npmerge,datatype_tmp)
                                        datapacket_merged = packets_publish[npmerge][datatype_tmp]
                                        if datapacket_merged is not None:
                                            dataqueue.put(datapacket_merged)
                                        packetbuffer[macdown][npmerge].pop(datatype_tmp)
                                        if len(packetbuffer[macdown][npmerge].keys()) == 0:
                                            packetbuffer[macdown].pop(npmerge)

                    # Add the data to the buffer
                    try:
                        packetbuffer[macdown]
                    except:
                        packetbuffer[macdown] = {}

                    try:
                        packetbuffer[macdown][nump]
                    except:
                        packetbuffer[macdown][nump] = {}

                    try:
                        packetbuffer[macdown][nump][datatype]
                    except:
                        packetbuffer[macdown][nump][datatype] = {}

                    packetbuffer[macdown][nump][datatype][mac] = pmerge

    return None

class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.show_numpackets = 1
        self.packetbuffer = {}
        self.qtreebuffer = {} # A buffer for the device qtree
        self.devicetree = QtWidgets.QTreeWidget(self)
        self.devicetree.setColumnCount(3)
        # self.devicetree.setHeaderHidden(True)
        self.devicetree.setHeaderLabels(['MAC','Datatype','Plot'])
        root = self.devicetree.invisibleRootItem()
        self.root_raw = QtWidgets.QTreeWidgetItem(['raw'])
        self.root_single = QtWidgets.QTreeWidgetItem(['single sensor'])
        self.root_tar = QtWidgets.QTreeWidgetItem(['tar merged'])
        root.addChild(self.root_tar)
        root.addChild(self.root_single)
        root.addChild(self.root_raw)
        self.datadisplaywidget = QtWidgets.QWidget(self)
        self.splitter = QtWidgets.QSplitter()
        self.splitter.addWidget(self.devicetree)
        self.splitter.addWidget(self.datadisplaywidget)
        #self.splitter.setStretchFactor(0, 0)  #
        #self.splitter.setStretchFactor(1, 1)  # Stretch the right one
        self.splitter.setHandleWidth(2)
        self.datadisplaywidget_layout = QtWidgets.QHBoxLayout(self.datadisplaywidget)
        self.tabwidget = QtWidgets.QTabWidget()
        self.datadisplaywidget_layout.addWidget(self.tabwidget)
        self.layout.addWidget(self.splitter)
        self.devicetree.currentItemChanged.connect(self.devicetree_item_changed)

    def devicetree_item_changed(self, itemnew, itemold):
        funcname = __name__ + '.devicetree_item_changed():'
        try:
            mac = itemnew.__mac__
            datatype = itemnew.__datatype__
        except:
            return

        table = self.packetbuffer[mac][datatype]['table']
        self.tabwidget.setCurrentWidget(table)

    def devicetree_plot_button_clicked(self, itemclicked):
        button = self.sender()
        #print('Itemclicked',itemclicked)
        #print(self.device.redvypr.redvypr_device_scan.redvypr_devices)
        if button.isChecked() == False:
            logger.debug('Closing plot')
            try:
                self.device.redvypr.redvypr_widget.closeDevice(button.__plotdevice__)
                delattr(button, '__plotdevice__')
                delattr(itemclicked,'__plotdevice__')
                button.setText('Plot')
            except:
                logger.debug('Could not close device',exc_info=True)
                button.setChecked(True)
        else:
            try:
                plotdevice = itemclicked.__plotdevice__
            except:
                plotdevice = None

            if plotdevice is None:
                logger.debug('Creating PcolorPlotDevice')
                mac = itemclicked.__mac__
                datatype = itemclicked.__datatype__
                packetid = itemclicked.__packetid__
                datastream = redvypr.RedvyprAddress(packetid=packetid,datakey=datatype)
                custom_config = redvypr.devices.plot.PcolorPlotDevice.DeviceCustomConfig(datastream=datastream)
                devicemodulename = 'redvypr.devices.plot.PcolorPlotDevice'
                plotname = 'Pcolor({})'.format(mac)
                device_parameter = RedvyprDeviceParameter(name=plotname)
                plotdevice = self.device.redvypr.add_device(devicemodulename=devicemodulename,
                                               base_config=device_parameter, custom_config=custom_config)

                itemclicked.__plotdevice__ = plotdevice
                packets = self.packetbuffer[mac][datatype]['packets']
                # Update the plot widget with the data in the buffer
                for ip,p in enumerate(packets):

                    for (guiqueue, widget) in plotdevice.guiqueues:
                        widget.update_data(p)

                logger.debug('Starting plot device')
                plotdevice.thread_start()
                button.__plotdevice__ = plotdevice
                button.setText('Close')

    def parameter_plot_button_clicked(self, row):
        funcname = __name__ + 'parameter_plot_button_clicked():'
        print(funcname)
        print('Row',row)
        button = self.sender()
        print('Button',button.__address__)
        address = button.__address__
        mac = button.__mac__
        datatype = button.__datatype__
        packetid = button.__packetid__
        if button.isChecked():
            try:
                button.__plotdevice__
            except:
                devicemodulename = 'redvypr.devices.plot.XYPlotDevice'
                plotname = 'XYPlot({},{})'.format(mac,address.datakey)
                device_parameter = RedvyprDeviceParameter(name=plotname)
                custom_config = redvypr.devices.plot.XYPlotDevice.DeviceCustomConfig()
                custom_config.lines[0].y_addr = redvypr.RedvyprAddress(address)
                plotdevice = self.device.redvypr.add_device(devicemodulename=devicemodulename,
                                                            base_config=device_parameter,
                                                            custom_config=custom_config)

                packets = self.packetbuffer[mac][datatype]['packets']
                # Update the plot widget with the data in the buffer
                for ip, p in enumerate(packets):
                    for (guiqueue, widget) in plotdevice.guiqueues:
                        widget.update_data(p,force_update=True)

                logger.debug('Starting plot device')
                plotdevice.thread_start()
                button.__plotdevice__ = plotdevice
                button.setText('Close')
        else:
            try:
                self.device.redvypr.redvypr_widget.closeDevice(button.__plotdevice__)
                delattr(button,'__plotdevice__')
                button.setText('Plot')
            except:
                logger.info('Could not close device',exc_info=True)
                button.setChecked(True)




    def update_data(self, data):
        """
        """
        try:
            funcname = __name__ + '.update_data():'
            tnow = time.time()
            #print(funcname + 'Got some data', data)
            datatype = None
            icols = []  # The columns in the table that will be updated
            datatars = [] # The data in the columns to be updated
            colheaders = []
            headerlabels = {}
            packetid = data['_redvypr']['packetid']
            #print('Got packet',packetid)
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

            if True:
                icols.append(1)
                datatars.append(None)
                colheaders.append('Plot')

            # If nothing to display
            if len(icols) == 0:
                return

            # Get data from packet
            try:
                np = data['np']
                mac = data['mac']
                counter = data['counter']
            except:
                logger.info('Could not get data', exc_info=True)
                return

            try:
                parents = data['parents']
            except:
                parents = []

            macs_tarchain = parents + [mac]
            if "raw" in packetid:
                parentitm = self.root_raw
            elif "TARM" in packetid:
                parentitm = self.root_tar
            else:
                parentitm = self.root_single
            #print('mac', mac, 'Macs', macs_tarchain)
            tmpdict = self.qtreebuffer
            flag_tree_update = False
            for mac_qtree in macs_tarchain:
                try:
                    itm = tmpdict[mac_qtree]['item']
                    tmpdict_new = tmpdict[mac_qtree]
                except:
                    logger.info('did not work', exc_info=True)
                    itm = QtWidgets.QTreeWidgetItem([mac_qtree, ''])
                    tmpdict_new = {'item': itm}
                    tmpdict[mac_qtree] = tmpdict_new
                    parentitm.addChild(itm)
                    flag_tree_update = True

                try:
                    itm_datatype = tmpdict_new['item_' + datatype]
                except:
                    itm_datatype = QtWidgets.QTreeWidgetItem([packetid, datatype])
                    tmpdict_new['item_' + datatype] = itm_datatype
                    itm_datatype.__mac__ = mac
                    itm_datatype.__datatype__ = datatype
                    itm_datatype.__packetid__ = packetid
                    itm.addChild(itm_datatype)
                    flag_tree_update = True
                    # Button erstellen und zur Zelle hinzufügen
                    button = QtWidgets.QPushButton("Plot")
                    button.setCheckable(True)
                    button.clicked.connect(lambda _, item=itm_datatype: self.devicetree_plot_button_clicked(item))
                    # Button in die dritte Spalte des TreeWidgetItems einfügen
                    self.devicetree.setItemWidget(itm_datatype, 2, button)
                parentitm = itm
                tmpdict = tmpdict_new

            if flag_tree_update:
                #self.devicetree.expandAll()
                self.devicetree.resizeColumnToContents(0)
                #self.devicetree.sortByColumn(0, QtCore.Qt.AscendingOrder)

            # Test if packetbuffer exists
            try:
                self.packetbuffer[mac]
            except:
                self.packetbuffer[mac] = {}

            # update the table packetbuffer
            try:
                self.packetbuffer[mac][datatype]
            except:
                self.packetbuffer[mac][datatype] = {'packets': []}

            self.packetbuffer[mac][datatype]['packets'].append(data)
            # if len(self.packetbuffer[mac][datatype]['packets']) > self.show_numpackets:
            if len(self.packetbuffer[mac][datatype]['packets']) > self.device.custom_config.size_packetbuffer:
                self.packetbuffer[mac][datatype]['packets'].pop(0)

            # Update the table
            irows = ['mac', 'np', 'counter']  # Rows to plot
            try:
                table = self.packetbuffer[mac][datatype]['table']
            except:
                table = QtWidgets.QTableWidget()
                self.packetbuffer[mac][datatype]['table'] = table
                table.setRowCount(len(datatar) + len(irows) - 1)
                numcols = len(icols)
                # print('Numcols')
                table.setColumnCount(numcols)
                # self.datadisplaywidget_layout.addWidget(table)
                self.tabwidget.addTab(table, '{} {}'.format(mac, datatype))
                headerlabels = [datatype]
                table.setHorizontalHeaderLabels(headerlabels)
                # Create plot buttons
                if True:

                    try:
                        for irow, key in enumerate(irows):
                            pass
                            #d = data[key]
                            #dataitem = QtWidgets.QTableWidgetItem(str(d))
                            #table.setItem(irow, icol, dataitem)

                        # And now the real data
                        for i, d in enumerate(datatar):
                            rdata = redvypr.Datapacket(data)
                            datakey = "['{}'][{}]".format(datatype,i)
                            address = redvypr.RedvyprAddress(data, datakey = datakey)
                            datastr = "{:4f}".format(d)
                            # Button erstellen und zur Zelle hinzufügen
                            button = QtWidgets.QPushButton("Plot")
                            button.setCheckable(True)
                            #button.clicked.connect(
                            #    lambda _, item=itm_datatype: self.devicetree_plot_button_clicked(item))
                            dataitem = QtWidgets.QTableWidgetItem(datastr)
                            irowtar = i + irow
                            button.clicked.connect(self.parameter_plot_button_clicked)
                            button.__address__ = address
                            button.__mac__ = mac
                            button.__datatype__ = datatype
                            button.__packetid__ = packetid
                            icol = 1
                            table.setCellWidget(irowtar, icol, button)
                    except:
                        logger.info('Could not add button', exc_info=True)

            for icol,datatar,colheader in zip(icols,datatars,colheaders):
                # update the table packetbuffer
                if datatar is not None:
                    try:
                        #print('Icol',icol)
                        # First the metadata
                        for irow,key in enumerate(irows):
                            d = data[key]
                            dataitem = QtWidgets.QTableWidgetItem(str(d))
                            table.setItem(irow, icol, dataitem)
                        # And now the real data
                        for i, d in enumerate(datatar):
                            datastr = "{:4f}".format(d)
                            dataitem = QtWidgets.QTableWidgetItem(datastr)
                            irowtar = i + irow
                            table.setItem(irowtar, icol, dataitem)
                    except:
                        logger.info('Does not work',exc_info=True)

            table.resizeColumnsToContents()
        except:
            logger.debug('Could not update data',exc_info=True)

