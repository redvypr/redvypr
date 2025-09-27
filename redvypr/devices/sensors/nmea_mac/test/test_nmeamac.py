import redvypr.devices.sensors.nmea_mac.nmea_mac_process as nmea_mac_process

testfile = "fp07.log"

p = nmea_mac_process.NMEAMacProcessor()
p.process_file(testfile)
print(p.T_all)