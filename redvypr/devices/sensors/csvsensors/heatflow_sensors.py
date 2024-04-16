import datetime
import redvypr.data_packets as data_packets
import numpy
import logging
import sys
import zoneinfo

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('heatflow_dataprocess')
logger.setLevel(logging.DEBUG)


def convert_HF(datapacket, loggerconfigurations=None):
    """
    Converts raw data into SI units
    """
    funcname = 'convert_HF():'
    logger.debug(funcname)
    try:
        mac = datapacket['sn']
    except:
        mac = None

    datapacketSI = {}
    datapacketSI['type'] = 'HFSI'
    datapacketSI['sensortype'] = datapacket['sensortype']
    datapacketSI['sn'] = datapacket['sn']
    datapacketSI['ts'] = datapacket['ts']
    datapacketSI['np'] = datapacket['np']
    datapacketSI['tUTC'] = datetime.datetime.utcfromtimestamp(datapacket['t']).isoformat(sep=' ',
                                                                                         timespec='milliseconds')
    #print('loggerconfigs',loggerconfigurations)
    if (mac is not None) and (loggerconfigurations is not None):
        flag_mac_calib = False
        try:
            c = loggerconfigurations[mac]
        except:
            c = None

        if c is not None:
            #print('Found configuration',c)
            if True:
                flag_mac_calib = True
                logger.debug(funcname + 'Found calibration for {:s}, converting'.format(mac))
                for parameter_tuple in c.parameter:
                    parameter = parameter_tuple[0]
                    parameter_calibration = parameter_tuple[1]
                    coeff = parameter_calibration.coeff
                    if parameter == 'HF':
                        data = datapacket['HF']
                        dataSI = data * coeff * 1000
                        datapacketSI['HF'] = dataSI
                    elif 'NTC' in parameter:
                        # Convert data using a Hoge (Steinhardt-Hart) Type of Equation
                        # print('NTC', parameter, coeff['coeff'])
                        if parameter in datapacket.keys():
                            poly = coeff
                            Toff = parameter_calibration.Toff
                            # print('Poly', poly)
                            data = datapacket[parameter]
                            data_tmp = numpy.polyval(poly, numpy.log(data))
                            # print('data_tmp', data_tmp)
                            data_tmp = 1 / data_tmp - Toff
                            dataSI = data_tmp
                            # print('data_SI', dataSI)
                            datapacketSI[parameter] = dataSI

                return datapacketSI

        if flag_mac_calib == False:
            logger.debug(funcname + 'Did not findcalibration for {:s}'.format(mac))
            return None

    return None


def parse_HF_raw(data, sensortype='DHFS50'):
    """
    b'$FC0FE7FFFE167225,HF,00012848.3125,6424,-0.001354,848.389,848.389,852.966\n'
    """
    datasplit = data.split(',')
    macstr = datasplit[0][1:17]
    packettype = datasplit[1]  # HF
    datapacket = {}
    datapacket['type'] = packettype
    datapacket['sn'] = macstr
    datapacket['sensortype'] = sensortype
    valid_package = False
    if len(datasplit) == 8:
        ts = float(datasplit[2])  # Sampling time
        np = int(datasplit[3])  # Number of packet
        datapacket['HF'] = float(datasplit[4])
        datapacket['NTC0'] = float(datasplit[5])
        datapacket['NTC1'] = float(datasplit[6])
        datapacket['NTC2'] = float(datasplit[7])
        datapacket['ts'] = ts
        datapacket['np'] = np
        valid_package = True

    if valid_package:
        return datapacket
    else:
        return None



def parse_HFS_raw(data, sensortype='DHFS50'):
    """
    HFS SI data from the sensor itself
    """
    datasplit = data.split(',')
    macstr = datasplit[0][1:17]
    packettype = datasplit[1]  # HFS
    datapacket = {}
    datapacket['type'] = packettype
    datapacket['sn'] = macstr
    datapacket['sensortype'] = sensortype
    valid_package = False
    if len(datasplit) == 8:
        ts = float(datasplit[2])  # Sampling time
        np = int(datasplit[3])  # Number of packet
        datapacket['HF'] = float(datasplit[4])
        datapacket['NTC0'] = float(datasplit[5])
        datapacket['NTC1'] = float(datasplit[6])
        datapacket['NTC2'] = float(datasplit[7])
        datapacket['ts'] = ts
        datapacket['np'] = np
        valid_package = True

    if valid_package:
        return datapacket
    else:
        return None


def add_keyinfo_HF_raw(datapacket):
    """
    Adds keyinfo to the HF_raw datapacket
    """
    macstr = datapacket['sn']
    # print('Datapacket', datapacket)
    keys = list(datapacket.keys())
    for dkey in keys:
        # print(funcname + ' datakey {:s}'.format(dkey))
        if 'NTC' in dkey:
            unit = 'ohm'
        elif 'HF' in dkey:
            unit = 'V'
        elif dkey == 'T':
            unit = 'CNT'
        else:
            unit = 'NA'

        # print('Datakeyinfo',unit,macstr,dkey)
        data_packets.add_keyinfo2datapacket(datapacket, datakey=dkey,
                                            unit=unit, description=None,
                                            infokey='sn', info=macstr)
        data_packets.add_keyinfo2datapacket(datapacket, datakey=dkey,
                                            infokey='sensortype', info='DHFS50')
    return datapacket


def parse_IMU_raw(data, sensortype='DHFS50'):
    """
    b'$FC0FE7FFFE167225,IMU,00012848.3125,6424,-24534,32,-1,-129,-249,0,43872,-7,-1,-75\n'
    """
    datasplit = data.split(',')
    macstr = datasplit[0][1:17]
    packettype = datasplit[1]  # IMU
    datapacket = {}
    datapacket['type'] = packettype
    datapacket['sn'] = macstr
    datapacket['sensortype'] = sensortype
    acc = []
    gyro = []
    mag = []
    T = -9999.9
    valid_package = False
    if len(datasplit) == 14:
        ts = float(datasplit[2])  # Sampling time
        np = int(datasplit[3])  # Number of packet
        # print('{:f} {:d}'.format(ts,np))
        # print('datasplit',datasplit)
        ind_acc = 4
        ind_gyro = 7
        ind_T = 10
        ind_mag = 11
        for n in range(3):
            acc.append(int(datasplit[ind_acc + n]))
        for n in range(3):
            gyro.append(int(datasplit[ind_gyro + n]))
        for n in range(3):
            mag.append(int(datasplit[ind_mag + n]))

        T = int(datasplit[ind_T])
        valid_package = True
        datapacket['acc'] = acc
        datapacket['gyro'] = gyro
        datapacket['mag'] = mag
        datapacket['T'] = T
        datapacket['ts'] = ts
        datapacket['np'] = np

    if valid_package:
        return datapacket
    else:
        return None


def parse_HFV_raw(data, sensortype='PIBOARD'):
    """
    b'$KAL1,HFV,2023-11-03 05:30:29.589,0,-0.021414,1,-0.870808,2,-0.019380,3,-0.000244'
    """
    funcname = __name__ + '.parse_HFV_raw():'
    logger.debug(funcname)

    datasplit = data.split(',')
    snstr = datasplit[0][1:]
    packettype = datasplit[1]  # HFV
    tstr = datasplit[2]
    td = datetime.datetime.strptime(tstr, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=zoneinfo.ZoneInfo('UTC'))

    datapacket = {}
    datapacket['type'] = packettype
    datapacket['sn'] = snstr
    datapacket['sensortype'] = sensortype
    datapacket['t'] = td.timestamp()
    for i in range(0, 8, 2):
        ch = datasplit[3 + i]
        voltage = datasplit[3 + i + 1]
        channelname = 'C' + str(ch)
        datapacket[channelname] = float(voltage)

    return datapacket


def process_IMU_packet(dataline,data, macstr, macs_found_IMU):
    funcname = __name__ + '.process_IMU_packet()'
    datapacket = parse_IMU_raw(dataline)
    datapacket['t'] = data['t']
    datapacket['devicename'] = 'DHF_raw_' + macstr
    if macstr not in macs_found_IMU:
        logger.debug(funcname + 'New MAC found, will add datakeyinfo')
        # print('Datapacket', datapacket)
        keys = list(datapacket.keys())
        for dkey in keys:
            # print(funcname + ' datakey {:s}'.format(dkey))
            unit = 'CNT'
            data_packets.add_keyinfo2datapacket(datapacket, datakey=dkey,
                                                unit=unit, description=None,
                                                infokey='sn', info=macstr)
            data_packets.add_keyinfo2datapacket(datapacket, datakey=dkey,
                                                infokey='sensortype', info='DHFS50')

        macs_found_IMU.append(macstr)
    # print('IMU packet',datapacket)


def process_HFS_data(dataline, data):
    try:
        datapacket_HFSI = parse_HFS_raw(dataline)
    except:
        logger.debug(' Could not decode {:s}'.format(str(dataline)), exc_info=True)
        datapacket_HFSI = None

    if datapacket_HFSI is not None:
        macstr = datapacket_HFSI['sn']
        datapacket_HFSI['t'] = data['t']
        datapacket_HFSI['type'] = 'HFSI'
        datapacket_HFSI['devicename'] = 'DHF_SI_' + macstr
        return datapacket_HFSI






