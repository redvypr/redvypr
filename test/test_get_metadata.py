import redvypr
import time
redvypr.logger.setLevel('DEBUG')

r = redvypr.Redvypr(hostname='metadatatest',loglevel='DEBUG')
devicemodulename = r.get_devicemodulename_from_str('test_device')
d = r.add_device(devicemodulename=devicemodulename)

print('D',d)
dev = d[0]['device']
dev.thread_start()
time.sleep(2)
dev.thread_stop()
time.sleep(0.5)
raddr1 = redvypr.RedvyprAddress('*')
raddr2 = redvypr.RedvyprAddress('/k:["data_list_poly"][0]')
raddr3 = redvypr.RedvyprAddress('/k:["data_dict_list"]["temp"][0]')
raddr4 = redvypr.RedvyprAddress('/k:["data_dict_list"]["pressure"][0]')
print('Raddr1',raddr1.datakeyeval)
meta1 = dev.get_metadata_datakey(raddr1)
print('Metadata',meta1)
print('Test metadata 2')
meta2 = dev.get_metadata_datakey(raddr2,all_entries=False)
print('Metadata',meta2)
#meta3 = dev.get_metadata_datakey(raddr3)
#print('Metadata',meta2)
#meta4 = dev.get_metadata_datakey(raddr4)
#print('Metadata',meta2)
#print('Deviceinfo all',r.deviceinfo_all)

#while True:
#    print('Hallo')
#    time.sleep(10)
