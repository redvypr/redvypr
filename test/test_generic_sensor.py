import redvypr.devices.sensors.generic_sensor.sensor_definitions as sensor_definitions
import redvypr
import time
from redvypr.devices.sensors.calibration.calibration_models import CalibrationHeatFlow, CalibrationNTC, CalibrationLinearFactor, CalibrationPoly

hostinfo = redvypr.create_hostinfo(hostname='generic_sensor_test')
datapacket = redvypr.data_packets.create_datadict(device='rawdata',hostinfo=hostinfo)
datapacket['data'] = sensor_definitions.tar_b2_test1
datapacket['t'] = time.time()
print('Datapacket',datapacket)
metadata = sensor_definitions.tar_b2.create_metadata_datapacket()

print('Metadata',metadata)
print('Test 1')
#sensor_definitions.tar_b2.binary_process(sensor_definitions.tar_b2_test1)
data_packet_processed = sensor_definitions.tar_b2.datapacket_process(datapacket)
print('Data packet processed',data_packet_processed)
# Create a tar sensor and add a calibration
tar_sensor = sensor_definitions.BinarySensor(**sensor_definitions.tar_b2.model_dump())
tar_sensor = sensor_definitions.tar_b2.model_copy()
data_packet_processed = tar_sensor.datapacket_process(datapacket)
print('Data packet processed (without calibration)',data_packet_processed)

# Get the expanded datastreams
rdata = redvypr.data_packets.Datapacket(data_packet_processed[0])
datakeys = rdata.datakeys(expand=True)
print('Datakeys',datakeys)
caladdr = redvypr.redvypr_address.RedvyprAddress(datakey=datakeys['TAR'][0][0])
caladdr2 = redvypr.redvypr_address.RedvyprAddress(datakey=datakeys['TAR'][1][0])
print('Calibration address',caladdr)
# Adding a calibration to the sensor
cal_const = CalibrationLinearFactor(coeff=2.0, parameter=caladdr, address_apply=caladdr, datakey_result='foo')
cal_const2 = CalibrationLinearFactor(coeff=3.0, parameter=caladdr2, address_apply=caladdr2)
print('Calibration',cal_const)
tar_sensor.add_calibration_for_datapacket(calibration=cal_const)
tar_sensor.add_calibration_for_datapacket(calibration=cal_const2)
#tar_sensor.calibrations[caladdr.address_str] = cal_const
#tar_sensor.calibrations[caladdr2.address_str] = cal_const2
print('Tar sensor',tar_sensor)

data_packet_processed_with_calibration = tar_sensor.datapacket_process(datapacket)
print('Data packet processed (with calibration)',data_packet_processed_with_calibration)
