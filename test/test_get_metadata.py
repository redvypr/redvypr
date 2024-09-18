import redvypr
import time
redvypr.logger.setLevel('DEBUG')

r = redvypr.Redvypr(hostname='metadatatest',loglevel='DEBUG')
devicemodulename = r.get_devicemodulename_from_str('test_device')
dev = r.add_device(devicemodulename=devicemodulename)

print('Device',dev)
dev.thread_start()
time.sleep(2)
dev.thread_stop()
time.sleep(0.5)

print('----------------------')
print('Device metadata')
print(dev.statistics['metadata'])
print('Device metadata done')
print('----------------------')

raddrs = []
raddrs.append(redvypr.RedvyprAddress('*'))
raddrs.append(redvypr.RedvyprAddress('/k:["data_list_list"]'))
raddrs.append(redvypr.RedvyprAddress("/k:['data_list_list'][0]"))
raddrs.append(redvypr.RedvyprAddress("/k:['data_list_list'][1]"))
raddrs.append(redvypr.RedvyprAddress('/k:["data_list_poly"][0]'))
raddrs.append(redvypr.RedvyprAddress('/k:["data_dict_list"]["temp"]'))
raddrs.append(redvypr.RedvyprAddress("/k:['data_dict_list']['temp'][0]"))
raddrs.append(redvypr.RedvyprAddress('/k:["data_dict_list"]["pressure"][0]'))

#print('Raddr1',raddr1.datakeyeval)
for raddr in raddrs:
    meta = dev.get_metadata(raddr)
    print('-----------------------')
    print('Metadata for address {}: {}'.format(raddr,meta))

