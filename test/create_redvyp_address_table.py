import redvypr
import time


def rcall_str(addr, pkt):
    try:
        return addr(pkt, soft_missing=False)
    except redvypr.redvypr_address.FilterNoMatch:
        return "FilterNoMatch"
    except KeyError:
        return "KeyError"
    except NameError:
        return "NameError"

raddr1_str = "dl[1]@d:dev1"
raddr1 = redvypr.RedvyprAddress(raddr1_str)
raddr2_str = "dl[1]@d:dev1 and p:p2"
raddr2 = redvypr.RedvyprAddress(raddr2_str)
raddr3_str = "data@d:t1dev"
raddr3 = redvypr.RedvyprAddress(raddr3_str)
raddr4_str = "!@d:dev1"
raddr4 = redvypr.RedvyprAddress(raddr4_str)
raddr5_str = "@d:dev1"
raddr5 = redvypr.RedvyprAddress(raddr5_str)
datapacket_bare = {'dl':[1,7]}
datapacket = datapacket_bare.copy()
datapacket_empty = {}
# Create a bogus redvypr host
print('Creating hostinfo')
hostinfo = redvypr.create_hostinfo(hostname='trdvpr')
devicename = 'dev1'
devicemodulename = 't1devmod'
numpacket = 0
tread = time.time() # The time the packet was received from the queue (in redvypr.distribute_data)
print("Treating the bare datapacket, as if if was published by a redvypr-device")
print("Redvypr will add packet metadata")
redvypr.packet_statistic.treat_datadict(datapacket, devicename, hostinfo, numpacket, tread,devicemodulename)
redvypr.packet_statistic.treat_datadict(datapacket_empty, devicename, hostinfo, numpacket, tread,devicemodulename)
print("Get data from datapackets using redvypr addresses")

print(f"{raddr1(datapacket)=}")
print(f"{raddr1(datapacket, soft_missing=False)=}")
print(f"raddr1(datapacket_bare,soft_missing=False)={rcall_str(raddr1,datapacket_bare)}")
print(f"raddr3(datapacket)={rcall_str(raddr3,datapacket)}")
print(f"{raddr1(raddr2_str)=}")
print(f"{raddr1(raddr2_str, soft_missing=False)=}")
print(f"{raddr2(raddr1_str, soft_missing=False, strict=False)=}")
print(f"{raddr4(datapacket,strict=False)=}")
print(f"{raddr4(datapacket_empty)=}")
print(f"{raddr4("@d:dev1")=}")
print(f"{raddr4("@d:dev2",strict=False)=}")
print(f"{raddr4("data@d:dev1",strict=False)=}")
#print(f"{raddr5(datapacket)=}")


raddr = redvypr.RedvyprAddress('@')
raddr_noselector = redvypr.RedvyprAddress("!@")