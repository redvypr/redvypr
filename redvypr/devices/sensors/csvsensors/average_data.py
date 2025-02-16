import logging
import numpy as np
import sys
from redvypr.redvypr_address import RedvyprAddress
import redvypr.data_packets as data_packets


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.average_data')
logger.setLevel(logging.DEBUG)

class average_data():
    avg_data = {}
    def __init__(self, data, datakeys_avg, loggerconfig):
        self.loggerconfig = loggerconfig
        sn = data['sn']
        self.sn = sn
        self.macstr = sn
        data_addr = RedvyprAddress(data)
        devname = data_addr.devicename
        devsplit = devname.rsplit('_',maxsplit=1)[0]
        self.devicename = devsplit + '_AVG_' + self.macstr
        self.datakeys_avg = datakeys_avg
        self.avg_data = {}
        self.avg_tstart = {}
    def average_data(self,data):
        """
        Abveraging data
        """
        if self.loggerconfig is not None:
            datapacket_avg = None
            # Loop over all average intervals
            for avg_s in self.loggerconfig.avg_data:
                print('Checking for average {}'.format(avg_s))
                try:
                    self.avg_data[avg_s]
                    self.avg_tstart[avg_s]
                except:
                    self.avg_data[avg_s] = []
                    self.avg_tstart[avg_s] = data['t']

                dt = data['t'] - self.avg_tstart[avg_s]
                # Average reached
                if dt >= avg_s:
                    avg_str = str(avg_s) + 's'
                    if len(self.avg_data[avg_s]) > 0:
                        # devicename = datapacket_HFSI['devicename'] + '_avg'


                        datapacket_avg = data_packets.create_datadict(device=self.devicename, tu=data['_redvypr']['t'], hostinfo=self.device_info['hostinfo'])

                        datapacket_avg['type'] = self.data['type']
                        datapacket_avg['sn'] = self.macstr
                        print('Average reached')
                        for parameter in self.datakeys_avg:
                            avgdata = []
                            for d in self.avg_data[avg_s]:
                                avgdata.append(d[parameter])

                            if parameter == 't':
                                datapacket_avg[parameter] = np.mean(avgdata)
                            else:
                                datapacket_avg[parameter + '_avg_{}'.format(avg_str)] = np.mean(avgdata)
                                datapacket_avg[parameter + '_std_{}'.format(avg_str)] = np.std(avgdata)
                                datapacket_avg[parameter + '_n_{}'.format(avg_str)] = len(avgdata)

                        print('Publishing avg:{} packet {}'.format(avg_str, str(datapacket_HFSI_avg)))
                    else:
                        logger.debug('No data to average')

                    self.avg_data[avg_s] = [data]
                    self.avg_tstart[avg_s] = data['t']
                    return datapacket_avg
                else:
                    self.avg_data[avg_s].append(data)
                    return None