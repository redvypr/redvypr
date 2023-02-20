import redvypr
import time

print('This script demonstrates the conceptual creation, processing and filter steps of a redvypr datapacket')

print('Creating hostinfo')
hostinfo = redvypr.create_hostinfo()

# Create bogus devicenames, devicemodulename and numpackets
devicename = 'somedevice'
devicemodulename = 'somedevicemodulename'
numpacket = 0
tread = time.time() # The time the packet was received from the queue (in redvypr.distribute_data)
# Create a dictionary with some data
data = {'x':10,'y':20}
print('Data sent by the device thread:')
print(data)
print('Treating the datapacket, i.e. adding hostinfo, devicename ...')
redvypr.data_packets.treat_datadict(data, devicename, hostinfo, numpacket, tread,devicemodulename)
print('Data after receviced by th redvypr main thread and garnished with additional information:')
print(data)

print('Filtering data')
raddr_x = redvypr.data_packets.redvypr_address('x/*')
raddr_all = redvypr.data_packets.redvypr_address('*')
data_filtered_x = raddr_x.get_data(data)
print('Got data (x)')
print(data_filtered_x)

data_filtered_all = raddr_all.get_data(data)
print('Got data (all)')
print(data_filtered_all)



