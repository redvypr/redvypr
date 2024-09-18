"""
Tests redvypr address creation and comparison with a data packet
"""
import time
import redvypr.data_packets
from redvypr.redvypr_address import RedvyprAddress

# Create some data
datapacket_raw = {'t1':1,'t2':10,'somestring':'Hello World','somelist':[1,2,5,7],'somedict':{'test':'ok','number':3.0}}
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

print('Redvypr address test')
rc0 = RedvyprAddress(datakey='t1')
# Comparisons
rc1 = RedvyprAddress(compare='["t1"]>=3')
rc2 = RedvyprAddress(compare='["t2"]>=3')
rc3 = RedvyprAddress(compare='["somelist"][2]<=1000')
print(rc1)

print('Testing comparisons')
print('Testing rc0',rc0)
test0 = datapacket in rc0
print('Test0',test0)
print('-----------------')
print('Testing rc1',rc1)
test1 = datapacket in rc1
print('Test1',test1)
print('-----------------')
print('Testing rc2',rc2)
test2 = datapacket in rc2
print('Test2',test2)
print('-----------------')
print('Testing rc3',rc3)
test3 = datapacket in rc3
print('Test3',test3)
print('-----------------')

print('Testing regular expressions')
# Regular expressions
re1 = RedvyprAddress('/d:{.*}')
re2 = RedvyprAddress('/d:{some.*}')
re3 = RedvyprAddress('/d:{other.*}')
reall = [re1,re2,re3]

for retest in reall:
    print('-----------------')
    print('Testing',retest)
    test = datapacket in retest
    print('Datapacket in test',test)
    print('-----------------')



print('Testing datakey comparisons of eval strings that are formatted differently')
rev0 = RedvyprAddress('/k:a')
rev1 = RedvyprAddress('/k:["a"][0]["somedata"]')
reeval_test = []
reeval_test.append(RedvyprAddress('/k:["a"]'))
reeval_test.append(RedvyprAddress('''/k:['a']'''))
reeval_test.append(RedvyprAddress("/k:['''a''']"))
reeval_test.append(RedvyprAddress('/k:{[a]}'))
reeval_test.append(RedvyprAddress("/k:['''a'''][0]['somedata']"))
reeval_test.append(RedvyprAddress("/k:['''a'''][1]['somedata']"))

print('----- test 1 -----')
for rev_test in reeval_test:
    print('{} in {}: {}'.format(rev_test,rev0,rev_test in rev0))
print('----- test 2 -----')
for rev_test in reeval_test:
    print('{} in {}: {}'.format(rev_test,rev1,rev_test in rev1))

