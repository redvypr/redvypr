from redvypr.devices.sensors.generic_sensor.generic_sensor import BinarySensor
from redvypr import RedvyprAddress
import re

# HF (Heatflow)
HF_test1 = b'$FC0FE7FFFE1567E3,HF,00000431.3125,108,-0.000072,2774.364,2782.398,2766.746\n'
HF_test2 = b'$FC0FE7FFFE1567E3,HF,00054411.3125,13603,0.000037,2780.217,2786.642,2774.316\n'
HF_split = b'\$(?P<MAC>.+),HF,(?P<counter>[0-9.]+),(?P<np>[0-9]+),(?P<HF_V>[-,\+]*[0-9.]+),(?P<NTC_R>.*)\n'
HF_str_format = {'MAC':'str','counter':'float','np':'int','HF_V':'float','NTC_R':'array'}
HF_datakey_metadata = {'MAC':{'unit':'MAC64','description':'MAC of the sensor'},'np':{'unit':'counter'},'HF_V':{'unit':'Volt'},'NTC_R':{'unit':'Ohm'}}
HF_packetid_format = 'HF_{MAC}'
HF = BinarySensor(name='HF', regex_split=HF_split,
                       str_format=HF_str_format,
                       datakey_metadata=HF_datakey_metadata,
                       packetid_format=HF_packetid_format,
                       datastream=str(RedvyprAddress('/k:data')))


print('Testing sensor definition')
rematch = re.finditer(HF_split, HF_test2)
print(rematch)
for r in rematch:
    print(r)
    redict = r.groupdict()
    print('redict', redict)

print('Done')


