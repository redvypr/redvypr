import redvypr
import time

raddr = redvypr.RedvyprAddress('*')
raddr_index = redvypr.RedvyprAddress("/k:['somelist'][3]")
datapacket_raw = {'t1':3,'somestring':'Hello World','somelist':[1,2,5,7],'somedict':{'test':'ok','number':3.0}}
datapacket = datapacket_raw.copy()
# Create a bogus redvypr host
print('Creating hostinfo')
hostinfo = redvypr.create_hostinfo(hostname='someredvypr')
devicename = 'somedevice'
devicemodulename = 'somedevicemodulename'
numpacket = 0
tread = time.time() # The time the packet was received from the queue (in redvypr.distribute_data)
redvypr.packet_statistic.treat_datadict(datapacket, devicename, hostinfo, numpacket, tread,devicemodulename)
print('Datapacket', datapacket)

#
print('Retrieving data')
print('---------------')
print('---------------')
rdatapacket = redvypr.data_packets.Datapacket(datapacket)
print('With a redvypr datapacket (basically an improved dictionary) data can be retrieved')
print('1:\tUsing the keyword functionality of dictionaries')
print('''data = rdatapacket['t1']''')
data = rdatapacket['t1']
print('data',data)
print('---------------')
print('2:\tUsing the keyword functionality of dictionaries but with square brackets to allow to access members of lists etc')
print('This is realized using the eval functionality ...\n')
print('''data = rdatapacket["['somedict']['test']"]''')
data = rdatapacket["['somedict']['test']"]
print('data',data)
print('---------------')
print('3:\tUsing a redvypr address\n')
print('''raddr = redvypr.RedvyprAddress("/k:['somelist'][2]")''')
print('''data = rdatapacket[raddr]''')
raddr = redvypr.RedvyprAddress("/k:['somelist'][2]")
data = rdatapacket[raddr]
print('data',data)
print('---------------')
#print('address',raddr_index)
#print('R datapacket',rdatapacket)


