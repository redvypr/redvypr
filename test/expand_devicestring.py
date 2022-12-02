import redvypr.data_packets

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

for datastream in d:
    d_expanded = redvypr.data_packets.expand_devicestring(datastream)
    d_parsed = redvypr.data_packets.parse_addrstr(datastream)    
    print('datastream orig:\t',datastream)
    print('datastream expanded:\t',d_expanded)
    print('datastream parsed:\t',d_parsed)    
    print('-----')
    print('-----')








