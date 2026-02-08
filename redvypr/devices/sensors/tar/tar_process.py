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
import numpy as np
import logging
import sys
import pydantic
import xarray as xr
import redvypr
import redvypr.devices.sensors.generic_sensor.sensor_definitions as sensor_definitions
import redvypr.devices.sensors.calibration.calibration_models as calibration_models
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from redvypr.devices.sensors.tar import nmea_mac64_utils
from redvypr.data_packets import create_datadict as redvypr_create_datadict, add_metadata2datapacket, Datapacket


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.tar_process')
logger.setLevel(logging.DEBUG)


class TarDevice():
    """
    TarDevice collects single datapackets, stores them into buffers
    and merges them to one datapacket
    """
    def __init__(self, mac=None, *args, **kwargs):
        self.mac = mac
        self.parents = []
        self.packetbuffer_nump = {}
        self.packetbuffer_tar_merge = {}
    def add_datapacket(self, datapacket):
        if datapacket['mac'] == self.mac:
            logger.info("Adding datapacket ...")
        else:
            logger.info("mac do not fit ...")
            return

        p = datapacket
        try:
            parents = p['parents_raw']
        except:
            parents = None
        if True:
            if True:
                packetid = p['_redvypr']['packetid']
                datatype_packet = packetid.split('_')[0]
                p['_redvypr']['packetid'] = packetid
                mac = p['mac']
                try:
                    p['np'] = p['np_dsample']
                    if p['np'] is None:
                        p['np'] = p['np_local']
                except:
                    p['np'] = p['np_local']

                nump = p['np']
                # print('\nMAC:{}\n'.format(mac))
                # print('mac {} {} nump:{} packettype: {}'.format(ip, mactmp, nump, datatype_packet))
                # Create buffer entries
                if True:
                    #
                    try:
                        self.packetbuffer_nump[nump]
                    except:
                        self.packetbuffer_nump[nump] = {}

                    # Packets that do dont have indices and arrays do not need to be merged
                    # print("datatype_packet",datatype_packet)
                    # T and R needs to be merged first, so create a list of packets to be merged
                    if (datatype_packet == 'T') or (datatype_packet == 'R'):
                        try:
                            self.packetbuffer_nump[nump][datatype_packet]
                        except:
                            self.packetbuffer_nump[nump][datatype_packet] = []

                        self.packetbuffer_nump[nump][datatype_packet].append(p)
                    else:
                        # print(funcname + 'Nothing to merge, appending original packet',datatype_packet,mac)
                        self.packetbuffer_nump[nump][datatype_packet] = p

                if datatype_packet == 'dn':
                    #print(f"\n Found done packet, merging packets with nump:{nump}")
                    datapacket_merge = self.merge_datapackets(nump)
                    return datapacket_merge

        return None



    def merge_datapackets(self, nump):
        datatypes_packet = self.packetbuffer_nump[nump].keys()
        if True:
            p = self.packetbuffer_nump[nump]['dn']
            trecv = p['_redvypr']['t']
            mac = p['mac']
            try:
                parents_raw = p['parents_raw']
            except:
                parents_raw = None

            logger.debug(f"Merging {mac=},{trecv=},{parents_raw}")
            packetid = f"tar_{mac}"
            device = f"tar_{mac}"
            datapacket_merge_redvypr = redvypr_create_datadict(tu=trecv,
                                                       packetid=packetid,
                                                       device=device)
            datapacket_merge_redvypr['parents_raw'] = parents_raw
        datapacket_merge = {}

        for datatype in datatypes_packet:
            logger.debug(f"Merging {datatype}")
            if not(datatype == 'T' or datatype == 'R'):
                p = self.packetbuffer_nump[nump][datatype]
                datapacket_merge.update(p)
            else:
                logger.debug("Need to merge with indices")
                ntcnum = self.packetbuffer_nump[nump][datatype][0]['ntcnum']
                ntcdist = self.packetbuffer_nump[nump][datatype][0]['ntcdist']
                ntctype = self.packetbuffer_nump[nump][datatype][0]['ntctype']
                datapacket_merge['ntcnum'] = ntcnum
                datapacket_merge['ntcdist'] = ntcdist
                datapacket_merge['ntctype'] = ntctype
                dataarray = numpy.zeros(ntcnum) * numpy.nan
                for p in self.packetbuffer_nump[nump][datatype]:
                    try:
                        dataarray[p['ntcistart']:p['ntciend'] + 1] = p[datatype]
                    except:
                        logger.debug(f'Could not add data for {datatype}', exc_info=True)
                        # print(f"{data_packet_processed=}")

                datapacket_merge[datatype] = dataarray.tolist()


        # Calculate the sensor locations
        xdist = numpy.arange(0, ntcnum) * ntcdist / 1000
        ydist = numpy.arange(0, ntcnum) * 0
        datapacket_merge['pos_pcb_x'] = xdist
        datapacket_merge['pos_pcb_y'] = ydist
        # print('Xdist', xdist)
        sensors_body = np.column_stack(
            (xdist, np.zeros_like(xdist), np.zeros_like(xdist)))

        # print(pmerge2['IMU'])
        ax = datapacket_merge['acc'][0]
        ay = datapacket_merge['acc'][1]
        az = datapacket_merge['acc'][2]
        phi, theta = acc_to_roll_pitch(ay, ax, az)
        R = R_from_roll_pitch(phi, theta)
        # print('a', ax, ay, az, phi, theta, R)
        sensors_world = (R @ sensors_body.T).T  # shape (N,3)
        # for i, pw in enumerate(sensors_world):
        #    X, Y, Z = pw
        #    print(f"Sensor {i}: X={X:.4f} m, Z={Z:.4f} m")

        datapacket_merge['pos_x'] = sensors_world[:, 0].tolist()
        # pmerge2['pos_y'] = sensors_world[:, 1].tolist()
        datapacket_merge['pos_z'] = sensors_world[:, 2].tolist()
        # Update the redvypr information
        datapacket_merge.update(datapacket_merge_redvypr)
        #print(f"Merged to:{datapacket_merge}\n\n")
        return datapacket_merge


# not used at the moment
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


# Generic tar sample
tarv2nmea_device_format = 'tar_{mac}'
if True:
    tarv2nmea_header_split = (
        br'^'  # Start der Zeile
        # 1. macparents_raw: Alles bis zum letzten Doppelpunkt (optional)
        br'(?P<macparents_raw>[!$0-9A-F:]*)'
        # 2. Absender-MAC
        br'\$(?P<mac>[0-9A-F]{16}),'
        # 3. TAR mit optionaler Klammergruppe
        # Wir nutzen (?: ... )? für eine nicht-fangende optionale Gruppe
        br'TAR'
        br'(?:\('
        br'(?P<num_upstream>[0-9]+),'
        br'(?P<counter_dsample>[0-9.]+),'
        br'(?P<np_dsample>[0-9]+)'
        br'\))?,'
    )
    tarv2nmea_nmea_str_format_base = {'mac': 'str',
                                      'macparents_raw': 'str',
                                      'counter_dsample': 'float', 'np_dsample': 'int',
                                      'counter_local': 'float', 'np_local': 'int',
                                      'numupstream': 'int'}
    tarv2nmea_nmea_datakey_metadata_base = {
        'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
        'np_dsample': {'unit': 'counter'},
        'counter_dsample': {'unit': 's',
                            'description': 'Counter of the device that sent the dsample command, starts when device is powered up'},
        'counter_local': {'unit': 's',
                          'description': 'Counter, starts when device is powered up'},
        'np_local': {'unit': 'counter'}}
    # T
    tarv2nmea_T_split = tarv2nmea_header_split + (
        b'(?P<ntcnum>[0-9]+)'
        b'(?P<ntctype>[A-C])'
        b'(?P<ntcdist>[0-9]),'
        b'T(?P<ntcistart>[0-9]+)-(?P<ntciend>[0-9]+),'
        b'(?P<counter_local>[0-9.]+),'
        b'(?P<np_local>[0-9]+),'
        b'(?P<T>.*)\n'
    )
    tarv2nmea_T_str_format = tarv2nmea_nmea_str_format_base.copy()
    tarv2nmea_T_str_format['ntctype']= 'str'
    tarv2nmea_T_str_format['ntcistart'] = 'int'
    tarv2nmea_T_str_format['ntciend'] = 'int'
    tarv2nmea_T_str_format['ntcnum'] = 'int'
    tarv2nmea_T_str_format['ntcdist'] = 'float'
    tarv2nmea_T_str_format['T'] = 'array'
    tarv2nmea_T_datakey_metadata = tarv2nmea_nmea_datakey_metadata_base.copy()
    tarv2nmea_T_datakey_metadata['T'] =  {'unit': 'degC'}
    tarv2nmea_T_packetid_format = 'T_{mac}'
    tarv2nmea_T_description = 'Temperature array temperature datapacket'
    # R
    tarv2nmea_R_split =  tarv2nmea_header_split + (
        b'(?P<ntcnum>[0-9]+)'
        b'(?P<ntctype>[A-C])'
        b'(?P<ntcdist>[0-9]),'
        b'R(?P<ntcistart>[0-9]+)-(?P<ntciend>[0-9]+),'
        b'(?P<counter_local>[0-9.]+),'
        b'(?P<np_local>[0-9]+),'
        b'(?P<R>.*)\n'
    )
    tarv2nmea_R_str_format = tarv2nmea_nmea_str_format_base.copy()
    tarv2nmea_R_str_format['ntctype']= 'str'
    tarv2nmea_R_str_format['ntcistart'] = 'int'
    tarv2nmea_R_str_format['ntciend'] = 'int'
    tarv2nmea_R_str_format['ntcnum'] = 'int'
    tarv2nmea_R_str_format['ntcdist'] = 'float'
    tarv2nmea_R_str_format['R'] = 'array'
    tarv2nmea_R_datakey_metadata = tarv2nmea_nmea_datakey_metadata_base.copy()
    tarv2nmea_R_datakey_metadata['R'] = {'unit': 'Ohm'}
    tarv2nmea_R_packetid_format = 'R_{mac}'
    tarv2nmea_R_description = 'Temperature array resistance datapacket'


# IMU
if True:
    #b'$FC0FE7FFFEDE51A2:$FC0FE7FFFEDEA929,TAR(0.500,1),IM,0.500,1,a,0.020,0.122,1.012,g,0.27,-2.92,-0.85,m,-26.00,14.00,538.00,T,22.96\n'
    # IMU
    tarv2nmea_IMU_split = tarv2nmea_header_split + (
        b'IM,'
        b'(?P<counter_local>[0-9.]+),'
        b'(?P<np_local>[0-9]+),'
        b'a,(?P<acc>.*),'
        b'g,(?P<gyro>.*),'
        b'm,(?P<mag>.*),'
        b'T,(?P<T_IMU>.*)\n'
    )
    tarv2nmea_IMU_str_format = tarv2nmea_nmea_str_format_base.copy()
    tarv2nmea_IMU_str_format['acc'] = 'array'
    tarv2nmea_IMU_str_format['gyro'] = 'array'
    tarv2nmea_IMU_str_format['mag'] = 'array'
    tarv2nmea_IMU_str_format['T_IMU'] = 'float'
    tarv2nmea_IMU_datakey_metadata = tarv2nmea_nmea_datakey_metadata_base.copy()
    tarv2nmea_IMU_datakey_metadata['acc'] = {'unit': '9.81 x m/s**2','description':'Acceleration'}
    tarv2nmea_IMU_datakey_metadata['gyro'] = {'unit': 'deg/s', 'description': 'Gyro'}
    tarv2nmea_IMU_datakey_metadata['mag'] ={'unit': 'Tsla', 'description': 'Magnetometer'}
    tarv2nmea_IMU_datakey_metadata['T_IMU'] = {'unit': 'degC', 'description': 'Temperature of the IMU sensor'}
    tarv2nmea_IMU_packetid_format = 'IMU_{mac}'
    tarv2nmea_IMU_description = 'Temperature array IMU raw datapacket'

    # done packet
    b'$FC0FE7FFFEDE33B7,TAR,dn,25540.562,5109,0.312500,0.062500\n'
    b'$FC0FE7FFFEDE33B7:$FC0FE7FFFEDE51A2:$FC0FE7FFFEDE4109:$FC0FE7FFFEDEA929:$FC0FE7FFFEDE39F3,TAR(4,25540.562,5109),dn,25429.500,5089,0.375000,0.062500\n'

    tarv2nmea_dn_split = tarv2nmea_header_split + (
        br'dn,'
        # 4. Die restlichen Daten
        br'(?P<counter_local>[0-9.]+),'
        br'(?P<np_local>[0-9]+),'
        br'(?P<dt_sample>[0-9.]+),'
        br'(?P<dt_sent>[0-9.]+)'
        br'[\r\n]*$'
    )
    tarv2nmea_dn_str_format = tarv2nmea_nmea_str_format_base.copy()
    tarv2nmea_dn_str_format['dt_sample'] = 'float'
    tarv2nmea_dn_str_format['dt_send'] = 'float'
    tarv2nmea_dn_datakey_metadata = tarv2nmea_nmea_datakey_metadata_base.copy()
    tarv2nmea_dn_datakey_metadata['dt_sample'] = {'unit':'s'}
    tarv2nmea_dn_datakey_metadata['dt_send'] = {'unit': 's'}
    tarv2nmea_dn_packetid_format = 'dn_{mac}'
    tarv2nmea_dn_description = 'sampling "done" datapacket'



class TarProcessor():
    def __init__(self):
        self.tar_devices = {} # Dictionary of TarDevices
        self.metadata_sent = None
        self.init_buffer()
        self.init_sensors()
    def init_buffer(self):
        self.packetbuffer_tar_merge = {}  # A buffer to add split messages into one packet
        self.packetbuffer_nump_tar = {}  # A packetbuffer to add split messages into one packet
        # packetbuffer = {-1000:None} # Add a dummy key
        self.packetbuffer = {}
        self.metadata = {} # metadata per MAC
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
        tarv2nmea_dn = sensor_definitions.BinarySensor(name='tarv2nmea_dn',
                                                      regex_split=tarv2nmea_dn_split,
                                                      str_format=tarv2nmea_dn_str_format,
                                                      autofindcalibration=False,
                                                      description=tarv2nmea_dn_description,
                                                      datakey_metadata=tarv2nmea_dn_datakey_metadata,
                                                      packetid_format=tarv2nmea_dn_packetid_format,
                                                      device_format=tarv2nmea_device_format,
                                                      datastream=redvypr.RedvyprAddress(
                                                          'data'))
        tarv2nmea_T = sensor_definitions.BinarySensor(name='tarv2nmea_T', regex_split=tarv2nmea_T_split,
                                                             str_format=tarv2nmea_T_str_format,
                                                             autofindcalibration=False,
                                                             description=tarv2nmea_T_description,
                                                             datakey_metadata=tarv2nmea_T_datakey_metadata,
                                                             packetid_format=tarv2nmea_T_packetid_format,
                                                             device_format=tarv2nmea_device_format,
                                                             datastream=redvypr.RedvyprAddress('data'))

        tarv2nmea_R = sensor_definitions.BinarySensor(name='tarv2nmea_R', regex_split=tarv2nmea_R_split,
                                                      str_format=tarv2nmea_R_str_format,
                                                      autofindcalibration=False,
                                                      description=tarv2nmea_R_description,
                                                      datakey_metadata=tarv2nmea_R_datakey_metadata,
                                                      packetid_format=tarv2nmea_R_packetid_format,
                                                      device_format=tarv2nmea_device_format,
                                                      datastream=redvypr.RedvyprAddress('data'))

        tarv2nmea_IMU = sensor_definitions.BinarySensor(name='tarv2nmea_IMU',
                                                             regex_split=tarv2nmea_IMU_split,
                                                             str_format=tarv2nmea_IMU_str_format,
                                                             autofindcalibration=False,
                                                             description=tarv2nmea_IMU_description,
                                                             datakey_metadata=tarv2nmea_IMU_datakey_metadata,
                                                             packetid_format=tarv2nmea_IMU_packetid_format,
                                                             device_format=tarv2nmea_device_format,
                                                             datastream=redvypr.RedvyprAddress(
                                                                 'data'))

        # Create the tar sensors
        self.datatypes = []
        self.sensors = []

        self.sensors.append(tarv2nmea_dn)
        self.datatypes.append('dn')
        self.sensors.append(tarv2nmea_T)
        self.datatypes.append('T')
        self.sensors.append(tarv2nmea_R)
        self.datatypes.append('R')
        self.sensors.append(tarv2nmea_IMU)
        self.datatypes.append('IMU')

    def merge_tar_chain(self):
        funcname = __name__ + '.merge_tar_chain():'
        if config['merge_tar_chain'] and (self.np_processed_counter) > 2:
            # Creating array
            print('Merging tar chain')
            numps = list(self.packetbuffer_nump_tar.keys())
            print('Numps', numps, self.num_tar_sensors_max, self.tar_setup)
            merged_packets = []
            mac_downstream = self.tar_setup[0]
            try:
                for nump_merge in numps[:-1]:  # Dont merge the last one
                    #print('keys',self.packetbuffer_nump_tar[nump_merge].keys())
                    if 'merged' in self.packetbuffer_nump_tar[nump_merge].keys():
                        #print("Merging ...")
                        ppub_dict = self.packetbuffer_nump_tar.pop(nump_merge)
                        #ppub_dict = self.packetbuffer_nump_tar[nump_merge]
                        ppub = ppub_dict['merged']

                        mac_final = 'tar_chain_' + mac_downstream + 'N{}'.format(
                            len(self.tar_setup))

                        packetid_chain = "merged_" + mac_downstream + 'N{}'.format(
                            len(self.tar_setup))
                        #print('HALLO', ppub)
                        #print('HALLO HALLO\n\n\n')
                        l1 = len(ppub.keys())
                        l2 = len(self.tar_setup)
                        if l1 == l2:
                            #merged_packet_work['_redvypr']['packetid'] = mac_final
                            merged_packet_work = redvypr.RedvyprAddress(ppub[mac_downstream],device=mac_final,packetid=packetid_chain).to_redvypr_dict()
                            #print("Blank merge packet",merged_packet_work)
                            #merged_packet_work = copy.deepcopy(ppub[mac_downstream])
                        else:
                            print(
                                funcname + "Not enough packets for tar chain to merge: {} instead of {}".format(
                                    l1, l2))
                            continue
                        # input('fds')
                        for datatype_merge in ['T','R','acc','mag','T_IMU','pos_x','pos_z']:
                            #print('Merging tar chains packet {} with datatype'.format(
                            #    nump_merge, datatype_merge))
                            data_merged = []
                            t_merge = None
                            if datatype_merge == 'T':
                                unitstr = 'degC'
                            elif datatype_merge == 'R':
                                unitstr = 'Ohm'
                            for ntar, mac_merge in enumerate(self.tar_setup): # Merge according to the sensor design
                                try:
                                    data_merge = ppub[mac_merge][datatype_merge]
                                except:
                                    logger.info('MAC not in buffer {}'.format(mac_merge))
                                    ntcnum = self.sensors_datasizes[mac_merge]
                                    data_merge = numpy.zeros(ntcnum) * numpy.nan

                                # Add the last position onto pos x/z
                                if "pos" in datatype_merge and len(data_merged)>0:
                                    data_offset = data_merged[-1][-1]
                                    data_merge = numpy.asarray(data_merge) + data_offset
                                data_merged.append(data_merge)
                                if t_merge is None:
                                    try:
                                        t_merge = ppub[mac_merge]['t']
                                    except:
                                        pass

                            data_merged = numpy.hstack(data_merged)
                            print(funcname + 'merging tar chain, data of {} merged '.format(datatype_merge))
                            #print(data_merged)
                            merged_packet_work[datatype_merge] = data_merged.tolist()
                            merged_packet_work['mac'] = mac_final
                            merged_packet_work['np'] = nump_merge
                        merged_packets.append(merged_packet_work)
                        #print(merged_packet_work)
                        #raise(ValueError)
                        print(funcname + 'Done')
            except:
                logger.info("Could not merge chain",exc_info=True)
                raise (ValueError)

            print('Done with tar chain merging, returning:')
            return merged_packets

    def process_datapacket(self, datapacket):
        """
        Processes a redvypr datapacket
        Parameters
        ----------
        datapacket

        Returns
        -------

        """
        pass
    def process_rawdata(self, binary_data):
        packets = {'merged_packets':None,'merged_tar_chain':None,'metadata':None}
        #print(f"\nProcessing rawdata:{binary_data}")
        for sensor, datatype in zip(self.sensors, self.datatypes):
            #print(f'Checking for sensor:{sensor,datatype}')
            # Check for overflow
            datapacket = redvypr.Datapacket()
            datapacket['data'] = binary_data
            datapacket['t'] = time.time()
            try:
                if b'..\n' in binary_data:
                    data_packets_processed = None
                else:
                    data_packets_processed = sensor.datapacket_process(datapacket, datakey='data')
            except:
                logger.debug('Could not process data', exc_info=True)

            if data_packets_processed is not None:
                flag_found_data = True
                for data_packet_processed in data_packets_processed:
                    #print(f'Found datapacket of sensor {sensor.name}\nDatatype:{datatype}\n')
                    #print(f'Processed datapacket:{data_packet_processed}')
                    mac = data_packet_processed['mac']
                    if mac not in self.tar_devices.keys():
                        self.tar_devices[mac] = TarDevice(mac=mac)

                    # Add also metadata
                    if self.metadata_sent is None:
                        meta_packet = sensor.create_metadata_datapacket(
                            device=f"tar_{mac}",
                            packetid=f"tar_{mac}")

                        metadata = meta_packet['_metadata']
                        try:
                            self.metadata[mac]
                        except:
                            self.metadata[mac] = {}
                        self.metadata[mac].update(metadata)
                        #print(f"\n\n\nMetadata:{self.metadata[mac]}")

                    datapacket_merged = self.tar_devices[mac].add_datapacket(data_packet_processed)
                    if datapacket_merged is not None:
                        if packets['merged_packets'] is None:
                            packets['merged_packets'] = []
                        packets['merged_packets'].append(datapacket_merged)
                        if self.metadata_sent is None:
                            packets['metadata'] = [{'_metadata':self.metadata[mac]}]
                        else:
                            self.metadata_sent = [self.metadata[mac]]

        if data_packets_processed is None:
            pass
        else:
            pass
            # Merge datapackets which have only parts (T,R with NTC indices)
            #print("\nMerging the tar chain")
            #merged_tar_chain = self.merge_tar_chain()
            #print("Merging the tar chain done",merged_tar_chain)
            #print("done merging chain\n\n")
            #packets['merged_tar_chain'] = merged_tar_chain

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


# Functions for IMU processing
def acc_to_roll_pitch(ax, ay, az):
    phi = np.arctan2(ay, az)  # roll
    theta = np.arctan2(-ax, np.sqrt(ay * ay + az * az))  # pitch
    return phi, theta

def R_from_roll_pitch(phi, theta):
    Rx = np.array([[1, 0, 0],
                   [0, np.cos(phi), -np.sin(phi)],
                   [0, np.sin(phi), np.cos(phi)]])
    Ry = np.array([[np.cos(theta), 0, np.sin(theta)],
                   [0, 1, 0],
                   [-np.sin(theta), 0, np.cos(theta)]])
    return Ry @ Rx  # Body -> World (without yaw)










