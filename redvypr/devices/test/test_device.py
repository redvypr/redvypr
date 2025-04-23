"""

test device

"""
import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import threading
import copy
from redvypr.device import RedvyprDeviceCustomConfig, RedvyprDevice
import redvypr.data_packets
from redvypr.data_packets import check_for_command
import pydantic

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('test_device')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True
class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = 'A simple test device'

class DeviceCustomConfig(RedvyprDeviceCustomConfig):
    delay_s: float = 1.0

def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    print('Config',config)
    pdconfig = DeviceCustomConfig.model_validate(config)
    print('pdconfig',pdconfig)
    #data = {'_keyinfo':config['_keyinfo']}
    # dataqueue.put(data)
    # Send a datapacket with metadata describing the device
    address_str = device_info['address_str']
    device_metadata = {'location':'Room 42'}
    datapacket_info_device = redvypr.data_packets.add_metadata2datapacket(datapacket={}, address=address_str, metadict=device_metadata)
    dataqueue.put(datapacket_info_device)
    # Send a datapacket with information once (that will be put into the statistics)
    datapacket_info = redvypr.data_packets.add_metadata2datapacket(datapacket={}, datakey='sine_rand', metakey='unit',metadata='random unit')
    # Metadata can also be given as a dict
    metadata = {'description':'sinus with random data', 'mac':'ABCDEF1234'}
    datapacket_info = redvypr.data_packets.add_metadata2datapacket(datapacket_info, datakey='sine_rand', metadict=metadata)
    dataqueue.put(datapacket_info)
    i = 0
    counter = 0
    while True:
        try:
            data = datainqueue.get(block = False)
        except:
            data = None
        if(data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command: {:s}'.format(str(data)))
            if (command == 'stop'):
                logger.debug('Command is for me: {:s}'.format(str(command)))
                break

        data = redvypr.data_packets.create_datadict(device = device_info['device'])
        data['data'] = float(np.random.rand(1)-0.5)
        data['sometext'] = 'Hello {}'.format(counter)
        dataqueue.put(data)
        # Calculate some sine
        data_rand = float(np.random.rand(1) - 0.5)
        data_rand_2 = float(np.random.rand(1) - 0.5)
        f_sin = 1 / 30  # Frequency in Hz
        A_sin = 10  # Amplitude
        data_sine = float(A_sin * np.sin(f_sin * time.time()))
        dataqueue.put({'sine_rand': data_rand + data_sine,'count': counter,'sine': data_sine})

        time.sleep(config['delay_s'])
        #print('Hallo')
        # Add complex data
        data = redvypr.data_packets.create_datadict(device='test_complex_data', packetid='complex_data')
        if counter == 0:
            # Add metadata

            metadata = {'unit': 'baseunit'}
            data = redvypr.data_packets.add_metadata2datapacket(data, datakey='data_list_list',
                                                                metadict=metadata)

            metadata = {'unit': 'otherunit of entry 0'}
            data = redvypr.data_packets.add_metadata2datapacket(data, datakey='["data_list_list"][0]',
                                                                metadict=metadata)

            metadata = {'description': 'Counter and polynomial functions of counter', 'unit': 'grigra'}
            data = redvypr.data_packets.add_metadata2datapacket(data, datakey='data_list_poly',
                                                                           metadict=metadata)

            metadata = {'description': 'Temperature', 'unit': 'degC'}
            data = redvypr.data_packets.add_metadata2datapacket(data, datakey='["data_dict_list"]["temp"]',
                                                                metadict=metadata)

            metadata = {'unit': 'Pa'}
            data = redvypr.data_packets.add_metadata2datapacket(data, datakey='["data_dict_list"]["pressure"]',
                                                                metadict=metadata)
        data['data_list'] = [counter,data_sine,data_rand]
        data['data_list_list'] = [[counter, data_sine, data_rand],[counter, data_sine]]
        data['data_list_poly'] = [counter, counter + data_rand, 2 * counter + data_rand, -10 * counter + data_rand+ 3, 0.1 * counter**2 + 2 * counter + data_rand+ 3]
        data['data_dict_list'] = {'temp':[data_rand, 2*data_rand-10],'pressure':10+data_rand}
        data['data_ndarray_1d'] = np.zeros((5,)) + counter
        data['data_ndarray_2d'] = np.zeros((6,7)) + counter
        data['data_ndarray_2d_int'] = np.zeros((3,2),dtype=int) + int(counter)
        #print('datastreams',redvypr.data_packets.Datapacket(data).datastreams(expand=True))
        dataqueue.put(data)
        # Put some pathological data into the queue
        dataqueue.put(None)
        counter += 1
        



