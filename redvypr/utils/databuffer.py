import redvypr
import redvypr.redvypr_address as redvypr_address
import numpy as np



class DatapacketBuffer:
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
        else:
            raise ValueError('Address does not fit')


class DatapacketAvg:
    """
    Averages the datakey in address in datapackets
    """
    def __init__(self, address='/k:data', avg_interval=10, avg_dimension='n', return_mode='continous', buffersize=10000):
        self.address = redvypr_address.RedvyprAddress(address)
        self.avg_interval = avg_interval
        self.avg_dimension = avg_dimension
        self.return_mode = return_mode
        self.datakey_save = '<'+self.address.datakey + '>_({}={})'.format(avg_dimension,avg_interval)
        self.datakey_std_save = 'std(<' + self.address.datakey + '>_({}={}))'.format(avg_dimension,avg_interval)
        self.datakey_min_save = 'min(<' + self.address.datakey + '>_({}={}))'.format(avg_dimension,avg_interval)
        self.datakey_max_save = 'max(<' + self.address.datakey + '>_({}={}))'.format(avg_dimension,avg_interval)
        self.datakey_med_save = 'med(<' + self.address.datakey + '>_({}={}))'.format(avg_dimension,avg_interval)
        self.datapackets_raw = []
        self.avg_data_raw = []
        self.t = []
        self.buffersize = buffersize

    def get_return_addresses(self):
        """
        Returns the datakey address of the processed (averaged) data
        Returns
        -------
        Dictionary with the addresses

        """
        addr = {}
        addr['avg'] = redvypr_address.RedvyprAddress(self.datakey_save)
        addr['std'] = redvypr_address.RedvyprAddress(self.datakey_std_save)
        addr['max'] = redvypr_address.RedvyprAddress(self.datakey_max_save)
        addr['min'] = redvypr_address.RedvyprAddress(self.datakey_min_save)
        return addr
    def process_buffer(self):
        if self.avg_dimension == 'n':  # Numpackets
            n = len(self.t)
        elif self.avg_dimension == 't':  # Delta time
            n = self.t[-1] - self.t[0]
        else:
            raise ValueError('Unknown average dimension {}'.format(self.avg_dimension))
        if n > self.avg_interval:
            avg_data_merged = np.vstack(self.avg_data_raw)
            print('Shape avg data',np.shape(avg_data_merged))
            data_ret = {}
            # avg
            t_avg_data = np.mean(self.t)
            avg_data = np.mean(avg_data_merged,0).tolist()
            data_ret['t'] = t_avg_data
            data_ret[self.datakey_save] = avg_data
            # std
            std_data = np.std(avg_data_merged, 0).tolist()
            data_ret[self.datakey_std_save] = std_data
            # min
            min_data = np.min(avg_data_merged, 0).tolist()
            data_ret[self.datakey_min_save] = min_data
            # max
            max_data = np.max(avg_data_merged, 0).tolist()
            data_ret[self.datakey_max_save] = max_data

            if self.return_mode == 'single':
                self.datapackets_raw = []
                self.avg_data_raw = []
                self.t = []
            elif self.return_mode == 'continous':
                self.datapackets_raw.pop(0)
                self.avg_data_raw.pop(0)
                self.t.pop(0)
            else:
                raise('Unknown return mode')


            return data_ret

    def append(self, datapacket):
        rdata = redvypr.Datapacket(datapacket)
        if datapacket in self.address:
            avg_data = rdata[self.address]
            # Here should e something like a type check
            self.avg_data_raw.append(avg_data)
            self.t.append(datapacket['t'])
            self.datapackets_raw.append(datapacket)
            if len(self.datapackets_raw) > self.buffersize:
                self.datapackets_raw.pop(0)
                self.avg_data_raw.pop(0)
                self.t.pop(0)

            # Process the data
            if len(self.datapackets_raw) > 2:
                data_avg = self.process_buffer()
                print('Returning data')
                return data_avg
        else:
            print('Address',self.address)
            print('rdata',rdata.get_addressstr())
            raise ValueError('Address does not fit')
