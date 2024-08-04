import redvypr
import time

print('This script demonstrates the conceptual creation, processing and filter steps of a redvypr datapacket')

print('Creating hostinfo')
hostinfo = redvypr.create_hostinfo(hostname='someredvypr')
hostinfo2 = redvypr.create_hostinfo(hostname='otherredvypr')

# Create bogus devicenames, devicemodulename and numpackets
devicename = 'somedevice'
packetid = 'someid'
devicemodulename = 'somedevicemodulename'
numpacket = 0
tread = time.time() # The time the packet was received from the queue (in redvypr.distribute_data)
# Create a dictionary with some data
data = {'x':10,'y':20,'z':[1,2,3,4],'u':{'a':[5,6,7],'b':'Hello'}}
print('Data sent by the device thread:')
print(data)
print('Treating the datapacket, i.e. adding hostinfo, devicename ...')
redvypr.redvypr_packet_statistic.treat_datadict(data, devicename, hostinfo, numpacket, tread,devicemodulename)
print('Data after being received by the redvypr main thread and garnished with additional information:')
print(data)

print('And now send the packet through a second redvypr instance')
devicename2 = 'otherdevice'
packetid2 = 'otherid'
devicemodulename2 = 'otherdevicemodulename'
numpacket2 = 1000
tread2 = time.time()
redvypr.redvypr_packet_statistic.treat_datadict(data, devicename2, hostinfo2, numpacket2, tread2, devicemodulename2)
print('Data after received by the second redvypr main thread and garnished with additional information:')
print(data)


print('And now get the datakeys')
rdata = redvypr.data_packets.Datapacket(data)
(datakeys,datakeys_dict) = rdata.datakeys(expand=True,return_type='both')
print('Datakeys',datakeys)
print('Datakeys',datakeys_dict)