import redvypr.redvypr_address as redvypr_address
import numpy as np



class DatapacketBuffer():
    def __init__(self, address='*', buffersize=10000):
        self.address = redvypr_address.RedvyprAddress(address)
        self.datapackets = []
        self.t = []
        self.buffersize = buffersize
    def append(self, datapacket):
        if datapacket in self.address:
            self.t.append(datapacket['t'])
            self.datapackets.append(datapacket)
            if len(self.datapackets) > self.buffersize:
                self.datapackets.pop(0)
                self.t.pop(0)
