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
import re
from collections.abc import Iterable
import redvypr
import redvypr.devices.sensors.generic_sensor.sensor_definitions as sensor_definitions
import redvypr.devices.sensors.calibration.calibration_models as calibration_models
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from redvypr.devices.sensors.nmea_mac import nmea_mac64_utils


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.sensor.nmea_mac_process')
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


nmeamac_t_test1 = b"$FC0FE7FFFE220367,t,61168.625000,122337,1081911,61168.125,61168.188,61168.250,61168.312,61168.375,61168.375,61168.438,61168.500,61168.562"
nmeamac_R_test1 = b"$FC0FE7FFFE220367,R,61168.625000,122337,1081911,2817.684,2819.449,2820.933,2822.143,2823.150,2823.991,2824.700,2825.248,2825.665"
nmeamac_T_test1 = b"$FC0FE7FFFE220367,T,61168.625000,122337,1081911,26.008,25.991,25.977,25.965,25.956,25.948,25.941,25.936,25.932"

config = {}

# Generic tar sample
if True:
    # t
    nmeamac_t = (
        br'^'  # Start of the string
        b'(?P<macparents>(?:\$[0-9A-F]+:)*)'  # Optional parent macs (not likely but can happen)
        b'\$(?P<mac>[0-9A-F]+),'  # The mac 
        b't,'
        b'(?P<tp>[0-9.]+),'
        b'(?P<np>[0-9]+),'
        b'(?P<nsamples>[0-9]+),'
        b'(?P<ts>.*)\n'
    )
    nmeamac_t_str_format = {'mac': 'str', 'tp': 'float', 'np': 'int', 'nsamples': 'int', 'ts': 'array'}
    nmeamac_t_datakey_metadata = {'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
                                  'np': {'unit': 'counter'}, 'ts': {'unit': 's'}}
    nmeamac_t_packetid_format = '{mac}__nmeamac_t'
    nmeamac_t_description = 'time data'

    # T
    nmeamac_T = (
        br'^'  # Start of the string
        b'(?P<macparents>(?:\$[0-9A-F]+:)*)'  # Optional parent macs (not likely but can happen)
        b'\$(?P<mac>[0-9A-F]+),'  # The mac 
        b'T,'
        b'(?P<tp>[0-9.]+),'
        b'(?P<np>[0-9]+),'
        b'(?P<nsamples>[0-9]+),'        
        b'(?P<T>.*)\n'
    )
    nmeamac_T_str_format = {'mac': 'str', 'tp': 'float', 'np': 'int','nsamples': 'int', 'T': 'array'}
    nmeamac_T_datakey_metadata = {'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
                                           'np': {'unit': 'counter'}, 'T': {'unit': 'degC'}}
    nmeamac_T_packetid_format = '{mac}__nmeamac_T'
    nmeamac_T_description = 'Temperature data'
    # R
    nmeamac_R = (
        br'^'  # Start of the string
        b'(?P<macparents>(?:\$[0-9A-F]+:)*)'  # Optional parent macs (not likely but can happen)
        b'\$(?P<mac>[0-9A-F]+),'  # The mac 
        b'R,'
        b'(?P<tp>[0-9.]+),'
        b'(?P<np>[0-9]+),'
        b'(?P<nsamples>[0-9]+),'
        b'(?P<R>.*)\n'
    )
    nmeamac_R_str_format = {'mac': 'str', 'tp': 'float', 'np': 'int', 'nsamples': 'int', 'R': 'array'}
    nmeamac_R_datakey_metadata = {'mac': {'unit': 'mac64', 'description': 'mac of the sensor'},
                                  'np': {'unit': 'counter'}, 'R': {'unit': 'Ohm'}}
    nmeamac_R_packetid_format = '{mac}__nmeamac_R'
    nmeamac_R_description = 'Resistance data'


class NMEAMacProcessor():
    def __init__(self):
        self.init_buffer()
        self.init_sensors()
        self.T_all = []
    def init_buffer(self):
        self.merge_by_variable = {} # Buffer for variables to merge by, for exmaple "np"
        self.merge_by_variable["np"] = -9999 # This could be done by configuration
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
        self.dataset_merged = None
        self.data_merged_xr_all = {}

    def init_sensors(self):
        nmeamac_T_sensor = sensor_definitions.BinarySensor(name='nmeamac_T', regex_split=nmeamac_T,
                                                             str_format=nmeamac_T_str_format,
                                                             autofindcalibration=False,
                                                             description=nmeamac_T_description,
                                                             datakey_metadata=nmeamac_T_datakey_metadata,
                                                             packetid_format=nmeamac_T_packetid_format,
                                                             datastream=redvypr.RedvyprAddress('/k:data'))

        nmeamac_t_sensor = sensor_definitions.BinarySensor(name='nmeamac_t', regex_split=nmeamac_t,
                                                           str_format=nmeamac_t_str_format,
                                                           autofindcalibration=False,
                                                           description=nmeamac_t_description,
                                                           datakey_metadata=nmeamac_t_datakey_metadata,
                                                           packetid_format=nmeamac_t_packetid_format,
                                                           datastream=redvypr.RedvyprAddress('/k:data'))

        nmeamac_R_sensor = sensor_definitions.BinarySensor(name='nmeamac_R', regex_split=nmeamac_R,
                                                           str_format=nmeamac_R_str_format,
                                                           autofindcalibration=False,
                                                           description=nmeamac_R_description,
                                                           datakey_metadata=nmeamac_R_datakey_metadata,
                                                           packetid_format=nmeamac_R_packetid_format,
                                                           datastream=redvypr.RedvyprAddress('/k:data'))


        # Create the tar sensors
        self.sensors = []

        self.sensors.append(nmeamac_t_sensor)
        self.sensors.append(nmeamac_T_sensor)
        self.sensors.append(nmeamac_R_sensor)


    def process_rawdata(self, binary_data_all):
        packets = {'merged':[],'raw':[]}
        lines = re.findall(b'.*?\n', binary_data_all)
        for binary_data in lines:
            print("binary data",binary_data)
            for sensor in self.sensors:
                flag_new_packets = False
                #print('Checking for sensor',sensor)
                # Check for overflow
                datapacket = redvypr.Datapacket()
                datapacket['data'] = binary_data
                datapacket['t'] = time.time()
                data_packet_processed = None
                try:
                    data_packet_processed = sensor.datapacket_process(datapacket, datakey='data')
                except:
                    logger.info('Could not process data', exc_info=True)

                # Stop the loop if processing was succesfull
                if data_packet_processed is not None:
                    print("Could parse data of type {}: {}".format(sensor.name, data_packet_processed))
                    packets["raw"].extend(data_packet_processed)
                    # Merge the packets, if possible
                    merged_packets = self.merge_datapackets(data_packet_processed)
                    print("Merged packets", merged_packets)
                    if len(merged_packets) > 0:
                        packets["merged"].extend(merged_packets)

                    break


        return packets

    def merge_datapackets(self,data_packet_processed):
        """

        Parameters
        ----------
        data_packet_processed

        Returns
        -------

        """
        data_packets_merged = []
        for data_packet in data_packet_processed:
            # Merge by np
            npold = self.merge_by_variable["np"]
            npnew = data_packet['np']

            # Check if the next packet is newer, if yes, merge the old one
            if npnew > npold:
                self.packetbuffer[npnew] = [data_packet] # New datapacket, merge the old one
                self.merge_by_variable["np"] = npnew

                if npold in self.packetbuffer.keys():
                    data_packets_merge = self.packetbuffer.pop(npold)

                    for i,d in enumerate(data_packets_merge):
                        if i == 0:
                            data_packet_merge = d
                        else:
                            data_packet_merge.update(d)

                    # replace ts with t
                    try:
                        data_packet_merge["t"] = data_packet_merge.pop("ts")
                        data_packets_merged.append(data_packet_merge)
                        packetid = data_packet_merge["mac"] + "__merged"
                        redvypr.data_packets.set_packetid(data_packet_merge,packetid=packetid)
                    except:
                        logger.warning("Could not merge packet:{}".format(data_packets_merged),exc_info=True)


            else:
                try:
                    self.packetbuffer[npnew].append(data_packet)
                except:
                    self.packetbuffer[npnew] = [data_packet]
                    logger.warning("Inconsistency in packetnumber")


            return data_packets_merged

    def merge_dataset(self, datapacket):
        """
        Merges several datapackets into a large one
        Parameters
        ----------
        datapacket

        Returns
        -------

        """
        dkeys = ["ts","R","T"]#redvypr.data_packets.Datapacket(datapacket).datakeys()
        coord_var = "t"
        # Create the merged datadictionary
        if self.dataset_merged is None:

            logger.info("Creating a new merged databuffer")
            self.dataset_merged = {}
            for k in dkeys:
                self.dataset_merged[k] = (coord_var,[])

        # Add to the datapacket
        for k in dkeys:
            value = datapacket[k]
            lst = self.dataset_merged[k][1]
            # NumPy-Arrays
            if isinstance(value, numpy.ndarray):
                lst.extend(value.tolist())
            # Generic Iterables (Listen, Tupel, Sets, Generatoren)
            elif isinstance(value, Iterable):
                lst.extend(value)
            else:
                lst.append(value)

    def merged_dataset_to_xarray(self):
        coord_var = "t"
        coord_data = self.dataset_merged.pop(coord_var)
        coord_dict = {"t":coord_data[1]}
        ds = xr.Dataset(data_vars=self.dataset_merged,coords=coord_dict)
        return ds
    def process_file(self, filename_tar):
        f = open(filename_tar, 'rb')
        for binary_data in f.readlines():
            print('data from line', binary_data)
            packets = self.process_rawdata(binary_data)
            print("Packets",packets)
            if packets["merged"] is not None:
                for p in packets["merged"]:
                    self.merge_dataset(p)


    def to_ncfile(self):
        if True:
            pass










