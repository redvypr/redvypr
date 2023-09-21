"""
Tests redvypr address creation and comparison
"""

import redvypr.data_packets

print('Redvypr address test')

data = {'_redvypr': {'t': 1695268409.8360054, 'device': 'DHF_SI_FC0FE7FFFE16A264', 'host': {'hostname': 'hf', 'tstart': 1695268296.165177, 'addr': '192.168.178.157', 'uuid': '176473386979093-145', 'local': True}}, 'type': 'HFSI', 'mac': 'FC0FE7FFFE16A264', 'ts': 339412.9375, 'np': 169706, 'tUTC': '2023-09-21 03:53:29.228', 'HF': -0.000114, 'NTC0': 21.673092052110803, 'NTC1': 21.865225532249667, 'NTC2': 22.00807675325683}


addr_re1 = redvypr.data_packets.redvypr_address('§.*§')
print('Data in re1', data in addr_re1)
addr_re2 = redvypr.data_packets.redvypr_address('§.*§/§.*DHF_.*§')
addr_re2.get_str('<key>/<device>:<host>@<addr>::<uuid>')
print('Data in re2', data in addr_re2)
# Test the address type strings
addr = redvypr.data_packets.redvypr_address('data/randdata_1:redvypr@192.168.178.26::04283d40-ef3c-11ec-ab8f-21d63600f1d0')
for stype in addr.strtypes:
    print('Address:',addr.get_str(stype))
