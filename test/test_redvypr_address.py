"""
Tests redvypr address creation and comparison, especially with regular expression
"""

import redvypr.data_packets

print('Redvypr address test')

data = {'_redvypr': {'t': 1695268409.8360054, 'device': 'DHF_SI_FC0FE7FFFE16A264', 'host': {'hostname': 'hf', 'tstart': 1695268296.165177, 'addr': '192.168.178.157', 'uuid': '176473386979093-145', 'local': True}}, 'type': 'HFSI', 'mac': 'FC0FE7FFFE16A264', 'ts': 339412.9375, 'np': 169706, 'tUTC': '2023-09-21 03:53:29.228', 'HF': -0.000114, 'NTC0': 21.673092052110803, 'NTC1': 21.865225532249667, 'NTC2': 22.00807675325683}

ntcdstream0 = 'NTC0/DHF_raw_FC0FE7FFFE167225:redvypr@192.168.178.157::176473386979093-194'
ntcdstream1 = 'NTC1/DHF_raw_FC0FE7FFFE167225:redvypr@192.168.178.157::176473386979093-194'
ntcdstream2 = 'NTC2/DHF_raw_FC0FE7FFFE167225:redvypr@192.168.178.157::176473386979093-194'
ntcdstreamtest = 'NTCXYZ2/DHF_raw_FC0FE7FFFE167225:redvypr@192.168.178.157::176473386979093-194'
Tdstream = 'T/DHF_raw_FC0FE7FFFE167225:redvypr@192.168.178.157::176473386979093-194'
Taddrs = [ntcdstream0,ntcdstream1,ntcdstream2,Tdstream,ntcdstreamtest]

addr_re1 = redvypr.data_packets.redvypr_address('§.*§')
print('Data in re1', data in addr_re1)
addr_re2 = redvypr.data_packets.redvypr_address('§.*§/§.*DHF_.*§')
addr_re2.get_str('<key>/<device>:<host>@<addr>::<uuid>')
print('Data in re2', data in addr_re2)
# Test the address type strings
addr = redvypr.data_packets.redvypr_address('data/randdata_1:redvypr@192.168.178.26::04283d40-ef3c-11ec-ab8f-21d63600f1d0')
for stype in addr.strtypes:
    print('Address:',addr.get_str(stype))


addr_ntc_re = redvypr.data_packets.redvypr_address('§(NTC[0-9])|(T)§/§DHF_raw.*§')
for dstream in Taddrs:
    print('Datastream',dstream)
    addrtmp = redvypr.data_packets.redvypr_address(dstream)
    print('Test',addrtmp in addr_ntc_re)

