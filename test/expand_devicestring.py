import redvypr.data_packets

data_packet = {'data': 'Hello World!', 'device': 'test_device_0', 'host': {'hostname': 'redvypr', 'tstart': 1670422195.4220772, 'addr': '192.168.178.26', 'uuid': '20221207150955.421856-93328248922693-013', 'local': True}, 't': 1670422215.8423817, 'numpacket': 3}
print('Expanding address strings:')
print(redvypr.data_packets.expand_address_string('test'))
print(redvypr.data_packets.expand_address_string('data/randdata_1:redvypr@192.168.178.26::04283d40-ef3c-11ec-ab8f-21d63600f1d0'))
print(redvypr.data_packets.expand_address_string('data/randdata_1::04283d40-ef3c-11ec-ab8f-21d63600f1d0'))
print(redvypr.data_packets.expand_address_string('data:test/randata'))


d = []
d.append('data/rand1:randredvypr')
d.append('data/rand1')
d.append('t/randdata::5c9295ee-6f8e-11ec-9f01-f7ad581789cc')
d.append('?data/randdata_1:redvypr@192.168.178.26::04283d40-ef3c-11ec-ab8f-21d63600f1d0')
d.append('data/randdata_1:redvypr@192.168.178.26::04283d40-ef3c-11ec-ab8f-21d63600f1d0')
d.append('data/randdata_1:redvypr@192.168.178.26')
d.append('data/randdata_1::04283d40-ef3c-11ec-ab8f-21d63600f1d0')
d.append('data/randdata_1:redvypr')
d.append('data/randdata_1::99283d40-ef3c-11ec-ab8f-21d63600f1d0')
d.append('*/randdata_1::04283d40-ef3c-11ec-ab8f-21d63600f1d0')
d.append('data/randdata_1:*')
d.append('foo')
d.append('wrong number::of::@@::')




for i,datastream in enumerate(d):
    print('i',i)
    print('datastream orig:\t', datastream)
    d_expanded = redvypr.data_packets.expand_address_string(datastream)
    d_parsed = redvypr.data_packets.parse_addrstr(datastream)    
    print('datastream expanded:\t',d_expanded)
    print('datastream parsed:\t',d_parsed)    
    print('-----')
    print('-----')


# Test the address
addr = redvypr.data_packets.redvypraddress('data/randdata_1:redvypr@192.168.178.26::04283d40-ef3c-11ec-ab8f-21d63600f1d0')
for stype in addr.strtypes:
    print('Address:',addr.get_str(stype))


addr2 = redvypr.data_packets.redvypraddress('')
print('strtpyes',addr2.get_strtypes())

addr3 = redvypr.data_packets.redvypr_address('test')
print(addr3)

print('Test if address is in data_packet')
#addr4 = redvypr.data_packets.redvypr_address('data/*::20221207150955.421856-93328248922693-013peter')
addr4 = redvypr.data_packets.redvypraddress('data/*')
inpacket = data_packet in addr4
print('Addr4',addr4)
print('in packet:',addr4,inpacket)









