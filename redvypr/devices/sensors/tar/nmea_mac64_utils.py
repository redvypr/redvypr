import logging
import numpy as np


teststrs = []
teststrs.append('$D8478FFFFE95E740')
teststrs.append('$D8478FFFFE95E740,1108456,69278.500000:$D8478FFFFE95CA01,1108427,69276.687500:$D8478FFFFE960155,1108467,69279.187500:$D8478FFFFE95CD4D')
teststrs.append('$D8478FFFFE95E740,1108456,69278.500000:$D8478FFFFE95CA01:$*!,sample ;69278.062500;34640\n')
teststrs.append('$D8478FFFFE95E740,1108457,69278.562500:$D8478FFFFE95CA01')
teststrs.append('$D8478FFFFE95E740,1108459,69278.687500:$D8478FFFFE95CA01,1108457,69278.562500:$D8478FFFFE960155,TAR_S;')


def calc_macsum(macstr):
    macsum = np.uint64(0)
    mac = []
    for i in range(0, 16, 2):
        try:
            mac.append(np.uint8(int(macstr[i:i + 2], 16)))
            # print(int(datas[i:i + 2],16),datas[i:i + 2])
            macsum += mac[-1]
        except Exception as e:
            # self.logger.exception(e)
            FLAG_MAC = False
            return None

    macsum = np.uint8(macsum)
    # print('Macsum {:02X} {}'.format(macsum, hex(macsum)))
    return macsum

def parse_nmea_mac64_string(macstr):
    """
    Parses a macstr of type


    Parameters
    ----------
    macstr

    Returns
    -------

    """
    result = {}
    macs = []
    stripped_string = ''
    if '<' in macstr:
        #print("numparents in string")
        downstream_mac = macstr.split("<")[0].replace("$","")
        mac = macstr.split(">")[1].replace("$","")
        #print("downstream mac",downstream_mac)
        numdownstreammacs = int(macstr.split("<")[1].split(">")[0])
        #print("mac", mac,numdownstreammacs)
        for i in range(numdownstreammacs):
            macs.append(None)

        macs.append(mac)
        macs[0] = downstream_mac
        stripped_string = None
    else:
        splits = macstr.split(':')
        for i,s in enumerate(splits):
            if len(s) >= 16:  # Add a dollar, if not present
                if s[0] != '$':
                    s = '$' + s

            if len(s) >= 17:
                if (calc_macsum(s[1:17]) is not None) and (s[0] == '$'):
                    #print('Found mac',s)
                    macs.append(s[1:17])
                    # Add the subsequent string as extra data, this will be done to get the last valid string
                    stripped_string = ':'.join(splits[i:])

    if len(macs)==0:
        result = None
    else:
        result['stripped_string'] = stripped_string
        result['mac'] = macs[-1]
        result['parents'] = []
        if len(macs) > 1:
            result['parents'] = macs[0:-1]

    print("result",result)
    return result

def strip_first_macs(datad):
    tmpstr0 = datad
    datads = None
    while True:
        print('tmpstr0',tmpstr0)
        try:
            dhf_sensor(tmpstr0[1:17])
            datads = tmpstr0
        except:
            break

        if tmpstr0[17] == ':':
            tmpstr = tmpstr0[18:]
            try:
                dhf_sensor(tmpstr[1:17])
                tmpstr0 = tmpstr
            except:
                break
        else:
            break

    return datads

