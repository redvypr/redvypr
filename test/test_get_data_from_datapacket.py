import redvypr
import time
from redvypr import RedvyprAddress

raddr = redvypr.RedvyprAddress('@')
raddr_index = redvypr.RedvyprAddress("somelist[3]@")
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
print('---------------\n\n')
print('2:\tUsing the keyword functionality of dictionaries but with square brackets to allow to access members of lists etc')
print('''data = rdatapacket["somedict['test']"]''')
data = rdatapacket["somedict['test']"]
print('data',data)
print('---------------\n\n')
print('3:\tUsing a redvypr address\n')
print('''raddr = redvypr.RedvyprAddress("somelist[2]")''')
print('''data = rdatapacket[raddr]''')
raddr = redvypr.RedvyprAddress("somelist[2]")
data = rdatapacket[raddr]
print('data',data)
print('---------------\n\n')
#print('address',raddr_index)
#print('R datapacket',rdatapacket)

print("Testing data key expansion 1")
res_expected = ["somedict['test']", "somedict['number']"]
res = rdatapacket.datakeys(datakeys=RedvyprAddress("somedict"),expand=True,return_type="list")
assert res == res_expected, "Test of datakeys function failed"
print("done\n-------------------\n\n")

print("Testing data key expansion 2")
res_expected = {'somedict': {'test': ("somedict['test']", str),
  'number': ("somedict['number']", float)}}
res = rdatapacket.datakeys(datakeys=RedvyprAddress("somedict"),expand=True)
assert res == res_expected, "Test of datakeys function failed"
print("done\n-------------------\n\n")

print("Testing data key expansion 3")
res_expected = ['somedict']
res = rdatapacket.datakeys(datakeys="somedict",expand=False)
assert res == res_expected, "Test of datakeys function failed"
print("done\n-------------------\n\n")


print("Testing data key expansion 4")
res_expected = {'t1': ('t1', int)}
res = rdatapacket.datakeys(datakeys="t1",expand=True)
assert res == res_expected, "Test of datakeys function failed"
print("done\n-------------------\n\n")
