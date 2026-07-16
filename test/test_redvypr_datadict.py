import redvypr
import time

print('Creating hostinfo')
hostinfo = redvypr.create_hostinfo(hostname='someredvypr')
hostinfo2 = redvypr.create_hostinfo(hostname='otherredvypr')

# Create bogus devicenames, devicemodulename and numpackets
devicename = 'somedevice'
packetid = 'someid'
sensor = 'tempsensor'
sensorid = '01'
devicemodulename = 'somedevicemodulename'
numpacket = 0
tread = time.time() # The time the packet was received from the queue (in redvypr.distribute_data)
# Create a dictionary with some data
data = {'T':10.03}
sensoraddress = redvypr.RedvyprAddress(sensorid=sensorid, packetid=packetid, device=devicename,sensor=sensor,hostinfo=hostinfo)
print(f"Sensoraddress:{sensoraddress}")
rdata = redvypr.RedvyprDatadict(data,raddress=sensoraddress)
print(f"rdata:{rdata}")
print(f"rdata address:{rdata.address}")
print("Setting filterkeys")
rdata.set_filterkeys(deviceid="FE23AB42",sensor="tempsensor_rev2")
print(f"rdata address:{rdata.address}")

(datakeys,datakeys_dict) = rdata.datakeys(expand=True,return_type='both')
print('Datakeys',datakeys)
print('Datakeys',datakeys_dict)
rdata.expand_data()
