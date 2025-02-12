import numpy as np
import redvypr
import serial
import logging
import sys
import argparse
import threading
import queue
import serial.tools.list_ports
import logging
import time
import datetime
import numpy
import re
from redvypr.devices.sensors.calibration import calibration_models

logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

logger = logging.getLogger("hexflasher")

# Calibration models for the different caliration types
#'$D8478FFFFE95CD4D,set ntc56 4 1.128271e-03 3.289026e-04 -1.530210e-05 1.131836e-06 0.000000e+00\n'
# The 4 is the calibration type
calibration_types = {}
calibration_types[1] = calibration_models.CalibrationPoly
calibration_types[2] = calibration_models.CalibrationLinearFactor
calibration_types[4] = calibration_models.CalibrationNTC


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



class dhf_sensor():
    def __init__(self,macstr=''):
        self.macstr = macstr
        self.logger = logging.getLogger('dhf_sensor({})'.format(macstr))
        self.logger.setLevel(logging.DEBUG)
        self.macsum_boots = None  # The sum of the macstring as in the BOOT string of the device
        self.parents = None
        self.bootloader_version = None  # The bootloader version of the device
        self.version = None
        self.brdid = None
        self.status = None
        self.status_firmware = None  # bootmonitor or firmware
        self.bootflag = None
        self.countdown = None
        self.flagsample = None

        # Calibrations
        self.calibrations = {}
        self.sample_counter = None
        self.sample_period = None

        self.memfile = None
        self.lhexdata = ''  # String containing the hexdata
        self.readdata_firmware = ''
        self.inittstr = datetime.datetime.now().strftime("%Y_%m_%d__%H_%M_%S")
        self.filename_lhex = '{:s}_memfile_{:s}.lhex'.format(self.macstr, self.inittstr)
        self.macsum = self.calc_macsum()
        if self.macsum is None:
            raise ValueError('Invalid CRC sum of MAC {}'.format(self.macstr))
        self.macsum_str = "{:02X}".format(self.macsum)
        self.lhexfilename_standard = "{}_firmware.lhex".format(macstr)

    def calc_macsum(self):
        macsum = np.uint64(0)
        mac = []
        for i in range(0, 16, 2):
            try:
                mac.append(np.uint8(int(self.macstr[i:i + 2], 16)))
                # print(int(datas[i:i + 2],16),datas[i:i + 2])
                macsum += mac[-1]
            except Exception as e:
                # self.logger.exception(e)
                FLAG_MAC = False
                return None


        macsum = np.uint8(macsum)
        #print('Macsum {:02X} {}'.format(macsum, hex(macsum)))
        return macsum

    def mem2lhex(self, memstr):
        """
        Converts the memory string into a long hex str
        $MMMMMMMMMMMMMMMMr:CCAAAAAAAADDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD

        $MMMMMMMMMMMMMMMMr:CCAAAADDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD

        """
        # get rid of newline
        memstr = memstr.replace('\n', '')
        print('memstr',memstr)

        if (len(memstr)>20) and ('r:' in memstr):
            memcontent = memstr.split('r:')[1]
            macstr = memstr.split('r:')[0]
            com = 'r:'
            countstr = memcontent[0:2]
            print('macstr',macstr)
            print('com', com)
            print('countstr', countstr)
            count = int(countstr, 16)
            len_lon = 2 + 8 + count * 2
            len_short = 2 + 4 + count * 2
            iaddr = 2
            if len(memcontent) >= len_lon:
                idata = 10
                addr = memcontent[iaddr:idata]
            else:
                idata = 6
                addr = '0000' + memcontent[iaddr:idata]

            print('addr', addr)
            datastr = memcontent[idata:]
            lhexstr = ';' + countstr + addr + '00' + datastr
            print('lhexstr',lhexstr)
            return lhexstr
        return None


    def writelhex(self,filename):
        """
        Write a long hex file with the memory content of the device
        :return:
        """
        self.logger.debug('Writing hex to file: {}'.format(filename))
        f = open(filename,'w')
        f.write(self.lhexdata)
        f.close()
    def memdata(self,addr,bindata,filename=None):
        """
        Writes bindata to addr to the memory file
        :param addr:
        :param bindata:
        :return:
        """
        if self.memfile == None:
            if filename == None:
                self.filename_mem = '{:s}_memfile_{:s}.bin'.format(self.macstr, self.inittstr)
            else:
                self.filename_mem = filename

            self.logger.info('Creating memory file for mac {:s}: {:s}'.format(self.macstr,self.filename_mem))
            self.memfile = open(self.filename_mem,'wb')

        self.memfile.seek(addr)
        self.memfile.write(bindata)
        self.memfile.flush()

    def create_read_flashsize_command(self):
        commands = []
        macstr = self.macstr
        macsum_str = self.macsum_str
        self.logger.debug('Create read command for mac {}'.format(macstr))
        comstr = 'f'
        DEVICECOMMAND = "${:s}{:s}{:s}\n".format(macstr, macsum_str, comstr)
        return DEVICECOMMAND

    def create_getts_command(self):
        """
        Create a sampling period command
        Returns
        -------

        """
        macstr = self.macstr
        comstr = "getts"
        devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
        return devicecommand

    def create_calibration_commands(self, calibrations, calibration_id=None, calibration_uuid=None, comment=None, date=None, savecal=True):
        """
        Creates commands to set the calibrations of the sensor
        The structure is similar to this here:
        $D8478FFFFE95CA01,set calid <id>\n
        $D8478FFFFE95CA01,set caluuid <uuid>\n
        $D8478FFFFE95CA01,set calcomment <comment>\n
        $D8478FFFFE95CA01,set caldate <datestr in ISO8190 format (max 31 Bytes)>\n
        $D8478FFFFE95CA01,set ntc21 4 1.128271e-03 3.289026e-04 -1.530210e-05 1.131836e-06 0.000000e+00\n

        Parameters
        ----------
        calibrations
        calibration_id
        calibration_uuid
        comment

        Returns
        -------

        """
        maxlen = 20
        macstr = self.macstr
        commands = []

        if calibration_id is not None:
            tmpstr = str(calibration_id)
            if len(tmpstr) > maxlen:
                tmpstr = tmpstr[:maxlen]
            comstr = "set calid {}".format(tmpstr)
            devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
            commands.append(devicecommand)
        if calibration_uuid is not None:
            tmpstr = str(calibration_uuid)
            if len(tmpstr) > maxlen:
                tmpstr = tmpstr[:maxlen]
            comstr = "set caluuid {}".format(tmpstr)
            devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
            commands.append(devicecommand)
        if date is not None:
            if isinstance(date,datetime.datetime):
                datestr = datetime.datetime.isoformat(date)
            else:
                datestr = str(date)
            tmpstr = datestr
            if len(tmpstr) > 31:
                tmpstr = tmpstr[:maxlen]
            comstr = "set caldate {}".format(tmpstr)
            devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
            commands.append(devicecommand)
        if comment is not None:
            tmpstr = str(comment)
            if len(tmpstr) > maxlen:
                tmpstr = tmpstr[:maxlen]
            comstr = "set calcomment {}".format(tmpstr)
            devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
            commands.append(devicecommand)
        for i, cal_key in enumerate(calibrations):
            # Check if dictionary or list, if dictionary, parameter is dict_key
            if isinstance(calibrations, dict):
                calibration = calibrations[cal_key]
                parameter = str(cal_key)
            elif isinstance(calibrations, list):
                calibration = cal_key
                parameter = str(calibration.parameter.datakey)

            print('Parameter',parameter)
            if calibration.calibration_type == 'ntc':
                self.logger.debug('NTC calibration')
                # Find index in parameter that looks like this: '''R["63"]''')
                indices = re.findall(r'\d+', str(parameter))
                if len(indices) == 1:  # Should be only one
                    index = indices[0]
                    caltype = 4
                    coeff = calibration.coeff
                    comstr = "set ntc{index} {caltype} {c0} {c1} {c2} {c3} {c4}".format(index=index,caltype=caltype,c0=coeff[0],c1=coeff[1],c2=coeff[2],c3=coeff[3],c4=coeff[4])
                    devicecommand = "${:s}!,{:s}\n".format(macstr, comstr)
                    commands.append(devicecommand)
        if savecal:
            devicecommand = "${:s}!,savecal\n".format(macstr)
            commands.append(devicecommand)

        return commands


    def create_read_commands(self,addr,nbytes):
        commands = []
        macstr = self.macstr
        macsum_str = self.macsum_str
        # READ NBYTES STARTADDR
        nread = 32  # read nread bytes at once from device
        nbyteshexstr = hex(int(nbytes))
        startaddrhexstr = hex(int(addr))
        self.logger.debug('Create read command for mac {} addr {}, nbytes {}'.format(macstr,addr,nbytes))
        try:
            nbytes_int = int(nbyteshexstr, 16)
            startaddr_int = int(startaddrhexstr, 16)
            self.logger.debug('Reading {} bytes from {} '.format(nbytes, startaddrhexstr))
            FLAG_READ = True
        except Exception as e:
            logger.exception(e)
            FLAG_READ = False

        if FLAG_READ:
            print('Creating read commands for device {:s}'.format(macstr))
            ntotal = 0
            t0 = time.time()
            for nread_tmp in range(0, nbytes_int, nread):
                nread_com = nread
                raddr = startaddr_int + nread_tmp
                # Check if the number of bytes to read is correct, this can happen at the end of the loop
                eaddr = raddr + nread_com
                endaddr_int = startaddr_int + nbytes_int
                # print('Hallo',eaddr,endaddr_int)
                if eaddr >= endaddr_int:
                    #print('Larger {:x} {:x} {:x} {:x}'.format(raddr, raddr + nread_com, eaddr,endaddr_int),eaddr,endaddr_int,nread_com)
                    nread_com -= eaddr - endaddr_int

                ntotal += nread_com
                #print(nread_tmp, nbytes_int, nread,nread_com, ntotal)
                #print('reading from 0x{:04X}'.format(raddr))
                # macstr = 'FC0FE7FFFE16A264'
                # macsum = '0B'
                comstr = 'r'
                DEVICECOMMAND = "${:s}{:s}{:s}{:02X}{:08X}0000\n".format(macstr, macsum_str, comstr, nread_com,
                                                                         raddr)
                #logger.debug(
                #    'Sending read command:{:s}, with len {:d}'.format(DEVICECOMMAND, len(DEVICECOMMAND)))
                commands.append(DEVICECOMMAND)

        return commands

    def create_write_command(self, hexdata):
        macstr = self.macstr
        macsum_str = self.macsum_str
        DEVICECOMMAND = "${:s}{:s}{:s}\n".format(macstr, macsum_str,hexdata)
        return DEVICECOMMAND

    def create_bootflag_command(self, bootflag):
        self.logger.debug('create_bootflag_command()')
        if self.status_firmware == 'bootmonitor':
            devicecommand = '${}{}bootflag {}\n'.format(self.macstr, self.macsum_str, str(bootflag))
            self.logger.debug('Device is in bootmonitor, command:{}'.format(devicecommand))
        else:
            devicecommand = "${:s}!,bootflag {}\n".format(self.macstr, str(bootflag))
            self.logger.debug('Device is in firmware, command:{}'.format(devicecommand))

        return devicecommand

    def create_bootconfig_command(self):
        self.logger.debug('create_bootconfig_command()')
        if self.status_firmware == 'bootmonitor':
            command = "${:s}{:s}bootconfig\n".format(self.macstr, self.macsum_str)
            self.logger.debug('Device is in bootmonitor, command:{}'.format(command))
        else:
            command = "${:s}!,bootconfig\n".format(self.macstr)
            self.logger.debug('Device is in firmware, command:{}'.format(command))

        return command

    def create_printcalib_command(self):
        self.logger.debug('create_printcalib_command()')
        if self.status_firmware == 'bootmonitor':
            return None
            self.logger.debug('Device is in bootmonitor, calibration config is not supported')
        else:
            command = "${:s}!,printcalib\n".format(self.macstr)
            self.logger.debug('Device calibration command:{}'.format(command))
            return command


def queue_decorator_write_with_param(data_queue):
    def decorator_write(func):
        def wrapper(*args, **kwargs):
            data = args[0]  #
            t = time.time()
            data_queue.put([t,'w',data])
            return func(*args, **kwargs)
        return wrapper
    return decorator_write

def queue_decorator_read_with_param(data_queue):
    def decorator_readline(func):
        def wrapper(*args, **kwargs):
            data = func(*args, **kwargs)
            # Only put data, if there was something ...
            if len(data) > 0:
                t = time.time()
                data_queue.put([t,'r',data])
            return data
        return wrapper
    return decorator_readline

class dhf_flasher():
    """
    Commands in bootmonitor
    Generic commands
    "$*!,ping\n"
    "$ReSeTtEsEr\n"
    "$ExitHexflash\n"
    Commands with MAC
    "baud"
    "start"
    'f'
    'r'
    ';' HEX
    ':' Intel hex

    Description of the commands
    "$*!,ping\n":
    -------------
    Returns:
    $*!,ping
    $D8478FFFFE95E740 CRC67 VER0.7 ?

    'f': Get the memory size
    Returns
    $D8478FFFFE95E74067f
    $D8478FFFFE95E740 mems 0x40000

    'Read command'
    ______________
    The read command operates either with 2bytes (intel hex) or 4 bytes (custom standard) addresses

    M: MAC64
    r: read command
    C: Count
    A: Address
    0: 0

    4 Byte Address:
    $D8478FFFFE95E74067r20000050000000 (command)
    $MMMMMMMMMMMMMMMMMMrCCAAAAAAAA0000
    $D8478FFFFE95E740r:2000005000D2B251F8203003F8012B41F820309F4B53F82020013A43F8202053F82030002B (reply)
    $MMMMMMMMMMMMMMMMr:CCAAAAAAAADDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD
    2 Bytes Address:
    $D8478FFFFE95E74067r2050000000 (Command)
    $D8478FFFFE95E740r:205000E3604FF0FF33E36263620022A64B1A5402B010BD6FF00302E9E713F0010F7BD0 (reply)
    $MMMMMMMMMMMMMMMMr:CCAAAADDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD


    $D8478FFFFE95E74067r20000150000000
    $D8478FFFFE95E740r:2000015000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
    $D8478FFFFE95E74067;200001500000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
    $D8478FFFFE95E74067;200003DDC000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF


    'Write command'
    ______________
    $D8478FFFFE95E74067;CCAAAAAAAA00DDDDDDDDDDDDDDDDDDDDRR
    M: MAC64
    ;: long address marker
    C: Count
    A: Address (4 Bytes)
    D: Data (needs fit with count)
    R: CRC

    $D8478FFFFE95E74067;200003FFE000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFCDFFFF
    $D8478FFFFE95E740w& 3ffe0 20

    """
    def __init__(self,comport=None,baud=9600,loglevel=logging.DEBUG,logcom=True):
        self.logger = logging.getLogger('dhf_flasher')
        loglevel = logging.DEBUG
        self.logger.setLevel(loglevel)
        funcname = '.init():'
        self.logger.debug(funcname)
        self.devices = {}
        self.devices_mac = {}
        self.serial = serial.Serial(comport,baudrate=baud)
        self.serial.timeout = 0.06
        # self.serial.timeout = 0.02
        # Decorate the serial function, to get the data for logging
        self.serial_queue_write = queue.Queue(maxsize=100000)
        self.serial.write = queue_decorator_write_with_param(self.serial_queue_write)(self.serial.write)
        self.serial.readline = queue_decorator_read_with_param(self.serial_queue_write)(self.serial.readline)

        self.logcom = logcom
        self.FLAG_READY = True
        if logcom:
            folder = './'
            tstr = datetime.datetime.now().strftime("%Y_%m_%d__%H_%M_%S")
            self.filename_log = '{:s}{:s}__dhfflasher.log'.format(folder, tstr)
            self.logger.debug('Logging to file {:s}'.format(self.filename_log))
            self.logfile = open(self.filename_log,'wb')
        # res = s.read()
        # print(res)

    def get_sampling_period_of_device(self, macstr):
        """
        $D8478FFFFE95CA01!,getts
        returns
        $D8478FFFFE95CA01:sample counter 32, period 2.000000, flagsample 0
        Parameters
        ----------
        macstr

        Returns
        -------

        """
        funcname = '.get_sampling_period_of_device():'
        self.logger.debug(funcname + '{}'.format(macstr))
        macobject = self.devices_mac[macstr]
        # Start a ping first and wait for response to get the MAC
        command = macobject.create_getts_command()
        try:
            self.logger.debug('Sending {}'.format(command))
            self.serial.write(command.encode('utf-8'))
        except:
            self.logger.info('Exception', exc_info=True)

        t1 = time.time()
        twait = 1.0
        if True:
            # And now check if there is something to receive from the device
            while True:
                dt = time.time() - t1
                if dt > twait:
                    break
                try:
                    data = self.serial.readline()
                except Exception as e:
                    continue

                if len(data) > 0:
                    print(funcname + 'Data:{}'.format(data))
                    datad = data.decode('utf-8')
                    datads = strip_first_macs(datad)  # Strip the string such that only the last mac is there
                    # datads = datad.split(':')[-1]
                    mactmp = dhf_sensor(datads[1:17])
                    print('mactmp', mactmp)
                    if ('sample counter' in datads) and (mactmp is not None):
                        print('Found valid response',datads)
                        try:
                            sample_counter = int(datads.split('sample counter')[1].split(',')[0])
                        except:
                            sample_counter = None

                        try:
                            sample_period = float(datads.split('period')[1].split(',')[0])
                        except:
                            sample_period = None

                        macobject.sample_counter = sample_counter
                        macobject.sample_period = sample_period



    def get_calibration_of_device(self, macstr):
        funcname = '.get_calibration_of_devices():'
        self.logger.debug(funcname + '{}'.format(macstr))
        macobject = self.devices_mac[macstr]
        # Start a ping first and wait for response to get the MAC
        command = macobject.create_printcalib_command()
        try:
            self.logger.debug('Sending {}'.format(command))
            self.serial.write(command.encode('utf-8'))
        except:
            self.logger.info('Exception', exc_info=True)

        t1 = time.time()
        twait = 3.0
        flag_cal_found = False
        calid = ''
        caluuid = ''
        calcomment = ''
        caldate = datetime.datetime(1970,1,1,0,0,0)
        if True:
            # And now check if there is something to receive from the device
            while True:
                dt = time.time() - t1
                if dt > twait:
                    break
                try:
                    data = self.serial.readline()
                except Exception as e:
                    continue


                if len(data) > 0:
                    print(funcname + 'Data:{}'.format(data))
                    datad = data.decode('utf-8')
                    datads = strip_first_macs(datad)  # Strip the string such that only the last mac is there
                    #datads = datad.split(':')[-1]
                    mactmp = dhf_sensor(datads[1:17])
                    print('mactmp',mactmp)
                    if ('set calid' in datads) and (mactmp is not None):
                        calid = datads.split('set calid ')[1][:-1]
                    if ('set caluuid' in datads) and (mactmp is not None):
                        caluuid = datads.split('set caluuid ')[1][:-1]
                    if ('set caldate' in datads) and (mactmp is not None):
                        caldatestr = datads.split('set caldate ')[1][:-1]
                        try:
                            caldate = datetime.datetime.fromisoformat(caldatestr)
                        except:
                            self.logger.warning('Could not convert date:{} into datetime'.format(caldate))
                            caldate = datetime.datetime(1, 1, 1, 0, 0, 0)

                        self.logger.warning('Caldate:{}'.format(caldate))
                    if ('set calcomment' in datads) and (mactmp is not None):
                        calcomment = datads.split('set calcomment ')[1][:-1]
                    if ('set ntc' in datads) and (mactmp is not None):
                        self.logger.debug('Found calibration entry')
                        #'$D8478FFFFE95CD4D,set ntc56 4 1.128271e-03 3.289026e-04 -1.530210e-05 1.131836e-06 0.000000e+00\n'
                        repattern = r"^\$(\w+)!,set (\w+) (\d+) ([0-9A-Za-z+.-]+) ([0-9A-Za-z+.-]+) ([0-9A-Za-z+.-]+) ([0-9A-Za-z+.-]+) ([0-9A-Za-z+.-]+)"
                        match = re.match(repattern, datads)
                        print('datads',datads)
                        if match:
                            wholematch = match.group(0)
                            mac_cal = match.group(1)
                            parameter = match.group(2)
                            # Replace 'ntc' with 'R'
                            if 'ntc' in parameter:
                                parameter = parameter.replace('ntc','R["')
                                parameter += '"]'
                                parameter_apply = parameter.replace('R','T')

                            caltype = int(match.group(3))
                            coeffs = [float(match.group(i)) for i in range(4, 9)]
                            if caltype in calibration_types.keys():
                                if caltype == 4: # At the moment only hoge-3 is supported
                                    parameter = redvypr.RedvyprAddress(parameter)
                                    calmodel = calibration_models.CalibrationNTC(coeff=coeffs,sn=mac_cal,
                                                                                 comment=calcomment,
                                                                                 date=caldate,
                                                                                 calibration_id=calid,
                                                                                 calibration_uuid=caluuid,
                                                                                 parameter=parameter,
                                                                                 parameter_apply=parameter_apply,
                                                                                 sensor_model=macobject.brdid)
                                    self.logger.debug('Adding {} to calibrations'.format(macobject.macstr))
                                    macobject.calibrations[parameter] = calmodel
                                    print('Calmodel',calmodel)
                                    flag_cal_found=True
                        else:
                            print("Could not find calibration")

            if flag_cal_found:
                return macobject
            else:
                return None

    def get_config_of_device(self, macstr):
        # '$D8478FFFFE95CD4D, flag_boot 1 countdown 52\n'
        funcname = '.get_config_of_devices():'
        self.logger.debug(funcname + '{}'.format(macstr))
        macobject = self.devices_mac[macstr]
        # Start a ping first and wait for response to get the MAC
        command = macobject.create_bootconfig_command()
        try:
            self.logger.debug('Sending {}'.format(command))
            self.serial.write(command.encode('utf-8'))
        except:
            self.logger.info('Exception', exc_info=True)

        ntries = 2
        ntries_tot = ntries
        while ntries > 0:
            self.logger.debug(funcname + 'Ntries get config of device:{} of {}'.format(ntries,ntries_tot))
            ntries -= 1
            time.sleep(0.1)
            # And now check if there is something to receive from the device
            for i in range(10):
                try:
                    data = self.serial.readline()
                    if len(data) > 0:
                        self.logger.debug(funcname + ' Got data:{}'.format(data))
                        datad = data.decode('utf-8')
                        datads = datad.split(':')[-1]
                        if ('flag_boot' in datads) and ('countdown' in datads):
                            self.logger.debug('Found flag boot entry')
                            macstr_ret = datads[1:17]
                            bootflag = int(datads.split('flag_boot')[-1][0:3])
                            countdown = int(datads.split('countdown')[-1][0:-1])
                            macobject.bootflag = bootflag
                            macobject.countdown = countdown
                            break
                except Exception as e:
                    continue

    def ping_devices(self):
        """
        Sends a ping a waits for return, checks who answered
        """
        funcname = '.ping_devices():'
        self.logger.debug(funcname)
        self.devices_mac = {} # Delete the old devices ...
        # Start a ping first and wait for response to get the MAC
        try:
            self.serial.write(b"$*!,ping\n")
        except:
            self.logger.info('Exception', exc_info=True)

        ntries = 3
        num_devices_found = 0
        while ntries > 0:
            print('Ntries', ntries)
            ntries -= 1
            time.sleep(0.1)
            # And now check if there is something to receive from the device
            data_recv = []
            #for i in range(5):
            while True:
                try:
                    data = self.serial.readline()
                    if len(data) > 0:
                        data_recv.append(data)
                    else:
                        break
                except Exception as e:
                    continue

            flag_firmware = False
            flag_bootmonitor = False
            if len(data_recv) > 0:
                print('Got data', data_recv)
                for d in data_recv:
                    macobjects = self.get_macobject_from_string(d)
                    if len(macobjects) > 0:
                        mac = macobjects[-1]
                        if len(macobjects) > 1:
                            mac.parents = []
                            for m in macobjects:
                                mac.parents.append(m.macstr)
                        self.logger.debug('Got data from a valid mac:{}'.format(mac.macstr))
                        ret = self.parse_string_from_device(d,mac)
                        if ret is not None:
                            self.logger.debug('Added device {}'.format(ret.macstr))
                            self.devices_mac[mac.macstr] = ret
                            num_devices_found += 1
                        else:
                            self.logger.debug('Could not parse data')

        if num_devices_found > 0:
            return self.devices_mac
        return None  # No devices found

    def startBootmonitor(self, mac):
        """
        Tries to start the bootmonitor
        """
        funcname = '.startBootmonitor():'
        self.logger.debug(funcname)

        macobject = self.devices_mac[mac.macstr]

        if macobject.bootloader_version is not None:
            self.logger.debug("Bootmonitor already started for mac {}".format(macobject.macstr))
            return macobject
        else:
            # Set the bootflag to 0 and reset the device
            command = '${}!,bootflag 0\n'.format(macobject.macstr)
            self.logger.debug("Sending: {}".format(command))
            self.serial.write(command.encode('utf-8'))
            time.sleep(0.2)
            command = '${}!,resetdevice\n'.format(macobject.macstr)
            self.logger.debug("Sending: {}".format(command))
            self.serial.write(command.encode('utf-8'))
            time.sleep(0.2)
            ntries = 3
            while ntries > 0:
                print('Waiting for response:{}'.format(ntries))
                ntries -= 1
                time.sleep(0.1)
                # And now check if there is something to receive from the device
                data_recv = []
                for i in range(5):
                    try:
                        data = self.serial.readline()
                        if len(data) > 0:
                            data_recv.append(data)
                    except Exception as e:
                        continue

                if len(data_recv) > 0:
                    print('Got response:{}'.format(data_recv))
                    for d in data_recv:
                        macobjects = self.get_macobject_from_string(d)
                        for macobj in macobjects:
                            print('Macobject',macobj)
                            if macobj.macstr == macobject.macstr:
                                print('Found mac')
                                ret = self.parse_string_from_device(d, macobj)
                                if ret is not None:
                                    self.logger.debug('Got data from a valid mac:{}'.format(mac.macstr))
                                    if macobj.self.status_firmware is not None:
                                        self.logger.debug('Response from firmware with mac:{}'.format(mac.macstr))
                                        return macobj

        return None  # Could not start bootmonitor

    def readFlashSize(self, macstr):
        """
        Reads the size of the flash
        """
        flashsize = None
        try:
            mac = self.devices_mac[macstr]
        except:
            raise ValueError("MAC {} not found".format(macstr))

        command = mac.create_read_flashsize_command()
        self.logger.debug("Sending: {}".format(command))
        self.serial.write(command.encode('utf-8'))
        time.sleep(0.1)

        data_recv = []
        nlines = 20
        for i in range(nlines):
            if True:
                data = self.serial.readline()
                if len(data) > 0:
                    data_recv.append(data)
                    if b'mems' in data:
                        #data = b'$D8478FFFFE95E740 mems 0x40000\n'
                        flashsize = int(data.split()[-1].decode('utf-8'),16)
                        break

        self.logger.debug('Got flash size data: {}'.format(data_recv))
        return flashsize

    def write_calibrations(self, commands, macstr=None, comqueue=None):
        """
        Writes the commands to the device and waits for receiving answers
        """
        funcname = __name__ + '.writeCommands():'
        tstart = time.time()
        if macstr is not None:
            try:
                mac = self.devices_mac[macstr]
            except:
                raise ValueError("MAC {} not found".format(macstr))

            addrstr = '$' + mac.macstr + '!,'
        else:
            addrstr = ''

        flag_written = False
        for icom, command in enumerate(commands):
            try:
                com = comqueue.get_nowait()
                self.logger.debug('Received cancel command')
                return
            except:
                pass

            write_command = addrstr + command
            write_command = write_command.replace('\n', '') + '\n'
            self.logger.debug(funcname + ' writing {} of {}:{}'.format(icom, len(commands), write_command))
            self.serial.write(write_command.encode('utf-8'))
            if 'savecal' in command:
                nwait = 500
            else:
                nwait = 5

            if True:
                for i in range(nwait):
                    try:
                        com = comqueue.get_nowait()
                        self.logger.debug('Received cancel command')
                        return
                    except:
                        pass
                    data = self.serial.readline()
                    if (len(data) > 0):
                        self.logger.debug('Received data:{}'.format(data))
                        data_ret = data.decode('utf-8')
                        if 'savecal:done' in data_ret:
                            message = 'Calibration saved to flash'
                            infodata = {'status': 'write', 'written': len(commands), 'write_total': len(commands),
                                        'message': message}
                            self.serial_queue_write.put(infodata)
                            time.sleep(0.001)
                            self.logger.debug('Data written to flash')
                            break
                if True:
                    infodata = {'status': 'write', 'written': icom, 'write_total': len(commands)}
                    self.serial_queue_write.put(infodata)
                    time.sleep(0.001)

        tend = time.time()
        dt = tend - tstart
        message = 'Sent {} commands in {}'.format(len(commands), dt)
        infodata = {'status': 'write', 'written': len(commands), 'write_total': len(commands), 'message': message}
        self.serial_queue_write.put(infodata)
        return None

    def writeFlash(self, macstr, hexdata, addr_check=True, comqueue=None, callback=None):
        """
        Writes the flash of a device with mac with the data stored in the hexdata list
        """
        tstart = time.time()
        try:
            mac = self.devices_mac[macstr]
        except:
            raise ValueError("MAC {} not found".format(macstr))

        for ihexd, hexd in enumerate(hexdata):
            try:
                com = comqueue.get_nowait()
                self.logger.debug('Received cancel command')
                return
            except:
                pass

            write_command = mac.create_write_command(hexd)
            write_command = write_command.replace('\n','') + '\n'
            if addr_check is False:
                write_command = write_command.replace(':','.').replace(';',',')
            print('Write command',ihexd,len(hexdata),write_command)
            if True:
                self.serial.write(write_command.encode('utf-8'))
                flag_ok = False
                flag_newcommand = False
                nwait = 500
                for i in range(nwait):
                    try:
                        com = comqueue.get_nowait()
                        self.logger.debug('Received cancel command')
                        return
                    except:
                        pass
                    data = self.serial.readline()
                    if (len(data) > 0):
                        print('data',data)
                    if (len(data) > 0) and (b'w&' in data):  # if there is a proper response
                        flag_ok = True
                    if (len(data) > 0) and (b'?' in data):  # if there is a proper response
                        flag_newcommand = True

                    if flag_ok and flag_newcommand:
                        break
                    elif flag_ok and (flag_newcommand is False):
                        write_command = mac.create_write_command('')
                        self.serial.write(write_command.encode('utf-8'))
                        infodata = {'status': 'write', 'written': ihexd, 'write_total': len(hexdata),
                                    'message': 'Waiting for confirmation of new command {}/{}'.format(i,nwait)}
                        self.serial_queue_write.put(infodata)
                        time.sleep(0.05)
                    elif i > 1:
                        infodata = {'status': 'write','message': 'Waiting for response ({},{}) {}/{}'.format(flag_newcommand, flag_ok, i,nwait)}
                        self.serial_queue_write.put(infodata)

                if (flag_ok is False) and (flag_newcommand is False):
                    message = 'Error, could not flash memory content'
                    self.logger.warning(message)
                    infodata = {'status': 'write', 'written': len(hexdata), 'write_total': len(hexdata),'message':message}
                    self.serial_queue_write.put(infodata)
                    return None
                else:
                    print('ok data', data)
                    infodata = {'status': 'write', 'written': ihexd, 'write_total': len(hexdata)}
                    self.serial_queue_write.put(infodata)
                    time.sleep(0.001)

        tend = time.time()
        dt = tend - tstart
        message = 'Flashed {} rows in {}'.format(len(hexdata),dt)
        infodata = {'status': 'write', 'written': len(hexdata), 'write_total': len(hexdata),'message':message}
        self.serial_queue_write.put(infodata)
        if callback is not None:
            callback()
        return mac

    def readFlash(self, macstr, addr_start=None, addr_stop=None, filename=None, comqueue=None):
        """
        Reads the whole flash of a device with mac
        """
        tstart = time.time()
        try:
            mac = self.devices_mac[macstr]
        except:
            raise ValueError("MAC {} not found".format(macstr))

        flashsize = self.readFlashSize(macstr)
        if flashsize is None:
            raise ValueError("Could not get flashsize")
        else:
            if addr_start is None:
                boot_offset = 0x5000
                addr_start = boot_offset
                nsize = flashsize - boot_offset
            else:
                nsize = addr_stop - addr_start

            read_commands = mac.create_read_commands(addr_start, nsize)
            print('Read commands', len(read_commands), read_commands[0])
            print('Read commands', len(read_commands), read_commands[-1])
            mac.lhexdata = ''  # Converted data
            mac.readdata_firmware = b''  # Raw data received from device
            for ind_com, command in enumerate(read_commands):
                try:
                    com = comqueue.get_nowait()
                    self.logger.debug('Received cancel command')
                    return
                except:
                    pass
                print('Reading', ind_com, len(read_commands))
                self.serial.write(command.encode('utf-8'))
                for i in range(5):
                    data = self.serial.readline()
                    if (len(data) > 0) and (b'r:' in data):  # if there is a proper response
                        break


                if len(data) > 0:
                    print('data', data)
                    mac.readdata_firmware += data
                    # Convert to a lhex datastr
                    datastr = data.decode('utf-8')
                    lhexstr = mac.mem2lhex(datastr)
                    if lhexstr is not None:
                        mac.lhexdata += lhexstr + '\n'
                        #print('Hallo', lhexstr)
                        infodata = {'status': 'read','read': ind_com,'read_total': len(read_commands)}
                        self.serial_queue_write.put(infodata)
                else:
                    self.logger.warning('Error, did not receive memory content')
                    break

                # break
        tend = time.time()
        dt = tend - tstart
        self.logger.debug('Took {}s for reading'.format(dt))
        infodata = {'status': 'read', 'read': len(read_commands), 'read_total': len(read_commands)}
        self.serial_queue_write.put(infodata)
        if filename is not None:
            self.logger.debug('Writing to file {}'.format(filename))
            mac.writelhex(filename)
            infodata['message'] = filename
            self.serial_queue_write.put(infodata)

        return mac

    def sendFlag(self, mac=None, bootflag=None, countdown=None):
        """
        Sends a set flag command
        :return:
        """
        funcname = '.sendReset():'
        self.logger.debug(funcname)
        if bootflag is not None:
            self.logger.debug(funcname + ' bootflag {}'.format(bootflag))
            command = mac.create_bootflag_command(bootflag)
            self.serial.write(command.encode('utf-8'))
            # And now check if there is something to receive from the device
            for i in range(10):
                try:
                    data = self.serial.readline()
                except:
                    continue
        if countdown is not None:
            self.logger.debug(funcname + ' countdown {}'.format(countdown))
            macstr = mac.macstr
            if mac.status_firmware == 'bootmonitor':
                DEVICECOMMAND = '${}{}countdown {}\n'.format(mac.macstr, mac.macsum_str, str(countdown))
            else:
                DEVICECOMMAND = "${:s}!,countdown {}\n".format(macstr, str(countdown))
            self.serial.write(DEVICECOMMAND.encode('utf-8'))
            # And now check if there is something to receive from the device
            for i in range(10):
                try:
                    data = self.serial.readline()
                except:
                    continue



        return None

    def sendReset(self, mac=None):
        """
        Sends a reset command
        :return:
        """
        funcname = '.sendReset():'
        self.logger.debug(funcname)
        if mac is None:
            self.logger.debug(funcname + 'Sending generic reset')
            try:
                self.serial.write(b"$ReSeTtEsEr\n")
            except Exception as e:
                print('Exception', e)
        else:
            macstr = mac.macstr
            if mac.status_firmware == 'bootmonitor':
                DEVICECOMMAND = '${}{}resetdevice\n'.format(mac.macstr, mac.macsum_str)
            else:
                DEVICECOMMAND = "${:s}!,resetdevice\n".format(macstr)

            self.logger.debug('Sending command:{}'.format(DEVICECOMMAND))
            self.serial.write(DEVICECOMMAND.encode('utf-8'))

        time.sleep(0.1)
        # And now check if there is something to receive from the device
        for i in range(5):
            try:
                data = self.serial.readline()
            except:
                continue

        return None

    def write_data(self, data):
        self.logger.debug('Writing data:"{}"'.format(data))
        self.serial.write(data.encode('utf-8'))
        # And now check if there is something to receive from the device
        for i in range(10):
            try:
                data_ret = self.serial.read()
                if len(data_ret) > 0:
                    return data_ret
            except:
                continue

    def readwrite(self, inqueue, outqueue, enter_command_mode=True):
        """

        :return:
        """
        funcname = '.readwrite():'
        logger_thread = logging.getLogger('dhf_flasher' + funcname)
        logger_thread.setLevel(logging.DEBUG)
        logger_thread.debug(funcname)
        self.serial_commands = []
        while True:
            self.FLAG_READY = True # This needsto be refined
            #print('Hallo ...')
            try:
                indata = inqueue.get_nowait()
            except:
                indata = None

            try:
                if indata is not None:
                    print('Got data',indata)
                    logger_thread.info('Got command {:s}'.format(str(indata)))
                    if indata.upper() == 'STOP':
                        self.logger.info('Stopping readwrite loop')
                        #if self.logcom:
                        #    self.logfile.close()
                        return True
                    elif indata.startswith('RESET'):
                        logger_thread.info('Resetting device')
                        self.sendReset()
                    elif indata.startswith('SEND'):
                        senddata = indata.split('SEND')[1].replace(" ","")
                        senddatab = senddata.encode('UTF-8')
                        # Append the command to the command list
                        self.serial_commands.append(senddatab)
                        print('Hallo!')
            except:
                self.logger.info('Could not process', exc_info=True)


            # Check if there is something to send to the device
            if len(self.serial_commands) > 0:
                if self.FLAG_READY:
                    senddata = self.serial_commands.pop(0)
                    logger_thread.debug('Sending data {:s}'.format(senddata.decode('UTF-8')))
                    self.serial.write(senddata)
                    self.last_command = senddata
                    self.FLAG_READY = False

            # And now check if there is something to receive from the device
            try:
                data = self.serial.readline()
            except Exception as e:
                continue

            if(len(data)>0):
                logger_thread.debug('Read from device:{}'.format(str(data)))
                #print('data',data)
                if self.logcom:
                    self.logfile.write(data)
                    self.logfile.flush()

                ret = self.parse_data(data)
                if type(ret) == dict:
                    if ret['type'] == 'boot':
                        logger_thread.info('Found device {:s}'.format(ret['mac']))
                        if enter_command_mode:
                            senddata = "${:s}{:s}\n".format(ret['mac'],ret['macsum'])
                            print('Sending data',senddata)
                            senddatab = senddata.encode('utf-8')
                            self.serial.write(senddatab)
                            self.logfile.write(senddatab)

                    try:
                        if ret['status'] == 'ready':
                            #print('Ready')
                            self.FLAG_READY = True
                        else:
                            self.FLAG_READY = False
                    except Exception as e:
                        self.FLAG_READY = False

                if ret is not None:
                    if 'status' in ret.keys():
                        outqueue.put(ret)

    def parse_string_from_device(self, datastr, macobject):
        """
        Parses strings from device and writes results macobject
        """
        d = datastr
        mac = macobject
        if b'pong' in d:  # Firmware, thats a good start
            # b'$D8478FFFFE95CD4D,!pong FIRMWARE VER 0.6.0 BRDID TARV2.1\n'
            # d.replace('\n','').split('pong ')[1].split(' ')
            # ['FIRMWARE', 'VER', '0.6.0', 'BRDID', 'TARV2.1']
            dc = d.decode('utf-8')
            # print('data dc',dc)
            try:
                dparts = dc.replace('\n', '').split('pong ')[1].split(' ')
            except:
                logger.debug('Could not decode pong {}'.format(dc), exc_info=True)
                return None
            if len(dparts) >= 6:
                mac.version = dparts[2]
                mac.brdid = dparts[4]
                mac.status = dparts[0]
                mac.bootloader_version = None
                mac.status_firmware = 'firmware'
                mac.flagsample = int(dparts[6])
                self.logger.debug(
                    'Successfully response from {} with mac:{} with version {}'.format(
                        mac.status, mac.macstr, mac.version))
            else:
                self.logger.debug('Could not parse string:{}'.format(dc))

            return mac

        elif (b'CRC' in d):  # In the bootmonitor already
            # b'$D8478FFFFE95CD4D,15833,989.562500:$D8478FFFFE95CA01 CRC0B VER1.11 FIRMWARE VER 0.6.0 BRDID TARV2.1 ?\n'
            # b'$D8478FFFFE95CD4D,37522,2345.125000:$D8478FFFFE95CA01 CRC0B VER1.11 HEXBOOT VER 1.11 BRDID TARV2.1 ?\n'
            # Reply question
            # b'$D8478FFFFE95CD4D,213,13.312500:$D8478FFFFE95CA01 CRC0B ?\n'
            dc = d.decode('utf-8')
            dparts = dc.replace('\n', '').split('CRC')[1].split(' ')

            if len(dparts) == 2:  #['0B', '?']
                mac.status_firmware = 'bootmonitor'
            elif len(dparts) == 8:
                # HEXBOOT Version
                # ['0B', 'VER1.11', 'HEXBOOT', 'VER', '1.11', 'BRDID', 'TARV2.1', '?']
                # From firmware started bootmonitor
                # ['0B', 'VER1.11', 'FIRMWARE', 'VER', '0.6.0', 'BRDID', 'TARV2.1', '?']
                mac.version = dparts[4]
                mac.brdid = dparts[-2]
                mac.status = dparts[2]
                mac.bootloader_version = dparts[1]
                mac.status_firmware = 'bootmonitor'
                self.logger.debug(
                    'Successfully response from bootmonitor of {} with mac:{} with version {} bootloader {}'.format(
                        mac.status,mac.macstr, mac.version, mac.bootloader_version))

                return mac


    def get_macobject_from_string(self, datastr):
        """
        b'$D8478FFFFE95CD4D,!pong\n'
        b'$D8478FFFFE95CD4D,605,37.812500:$D8478FFFFE95CA01 CRC0B VER1.11 ?\n'
        """

        if isinstance(datastr,bytes):
            data_all = datastr.decode('UTF-8')
        else:
            data_all = datastr

        # loop over all parts split by ':'
        macobjects = []
        for data in data_all.split(':'):
            if '$' in data and len(data)>=17:
                try:
                    ds = dhf_sensor(data[1:17])
                    macobjects.append(ds)
                except:
                    pass

        return macobjects
    def parse_data(self,data):
        """

        :param data:
        :return:
        """
        funcname = '.parse_data():'
        #self.logger.debug(funcname)
        #print('Datatype',type(data))
        try:
            datas = data.decode('utf-8')
            #print('datas',datas)
        except Exception as e:
            datas = ""
            self.logger.exception(e)

        if len(datas) == 0:
            return None
        else:
            if datas[0] != '$':
                return None
            else:
                self.logger.debug(funcname + 'Found valid sentence start')
                if len(datas) >= 17: # Enough data to check for MAC64
                    FLAG_MAC=True
                    macstr = datas[1:17]
                    mac = []
                    macsum = np.uint64(0)
                    for i in range(1,17,2):
                        try:
                            mac.append(np.uint8(int(datas[i:i + 2], 16)))
                            #print(int(datas[i:i + 2],16),datas[i:i + 2])
                            macsum += mac[-1]
                            #print('Macsum',macsum,mac[-1])
                        except:
                            #self.logger.exception(e)
                            self.logger.debug('Could not calculate macsum',exc_info=True)
                            FLAG_MAC = False
                            break

                    macsum = np.uint8(macsum)


                    if(FLAG_MAC == False):
                        self.logger.debug(funcname + 'Not a valid macaddress of {:s}'.format(datas))
                    else:
                        self.logger.debug(funcname + 'Valid mac {:s} with macsum {:02X}'.format(macstr,macsum))
                        #print('Macsum {:02X} '.format(macsum),macsum)
                        if macstr not in self.devices.keys():
                            self.devices[macstr] = dhf_sensor(macstr)

                        # Check the type of data
                        datavalid = datas[17:]
                        if 'BOOT' in datavalid:
                            self.logger.info('Found boot info: {:s}'.format(datavalid))
                            dtmp = datavalid.replace(" ","")
                            macsum_boots = dtmp[4:6]
                            bootloader_version = dtmp[6:]
                            if True: # Here a test for a valid bootloader version could be done
                                self.logger.info('Found device with mac {:s} and bootloader {:s}'.format(macstr,bootloader_version))
                                self.devices[macstr].bootloader_version = bootloader_version
                                self.devices[macstr].macsum_boots = macsum_boots
                                return {'type': 'boot', 'mac': macstr,'macsum':macsum_boots}
                                #print('dtmp',macsum_boots,bootloader_version)
                        elif '?' in datavalid: # Device ready to get next command
                            logger.debug('Device is ready for command')
                            return {'type':'status','status':'ready'}
                        elif 'w&' in datavalid:
                            addrstr = datavalid.split(" ")[1]
                            lenstr = datavalid.split(" ")[2]
                            logger.debug('Successfull write at addr {:s} with len of {:s}'.format(addrstr,lenstr))
                            retdata = {'type': 'status', 'addrs': addrstr, 'lens': lenstr,'status':'writegood'}
                            return retdata
                        elif 'r:' in datavalid:
                            logger.debug('Found memory content')
                            hexdata = datavalid.split('r:')[1].replace(" ", "").replace(".", "")
                            numbytes = int(hexdata[0:2],16)
                            #print('Numbytes',numbytes)
                            addrstr = hexdata[2:10]
                            memdatastr = hexdata[10:10+numbytes*2]
                            addrint = int(addrstr,16)
                            memdatabytes = bytes.fromhex(memdatastr)
                            # Write data to device
                            #print('Writing data',addrint,memdatabytes)
                            self.devices[macstr].memdata(addrint,memdatabytes)
                            self.devices[macstr].lhexdata += ';' + hexdata
                            self.devices[macstr].writelhex()
                            #print("hexdata", hexdata)
                            #print("Data", numbytes,addrstr,memdatastr)
                            retdata = {'type':'memdata','addrs':addrstr,'memdatas':memdatastr}
                            return retdata




def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--comport", help="displays available comports",default='COM1')
    parser.add_argument("--list_comports", help="displays available comports", action="store_true")
    parser.add_argument("--read_flash", help="reads the given address range, i.e. --read_flash=0x0000-0xFFFF")
    parser.add_argument("--write_flash", help="Writes the given file to flash, i.e. --write_flash=program.hex")
    args = parser.parse_args()
    comport = str(args.comport)

    inq = queue.Queue()
    outq = queue.Queue()
    if args.list_comports:
        print('Available comports')
        print([comport.device for comport in serial.tools.list_ports.comports()])
    else:
        logger.info('Starting dhf-flasher at comport {:s}'.format(comport))
        baud = 9600
        #baud = 115200
        dhffl = dhf_flasher(comport,baud=baud)
        dhffl.logger.setLevel(logging.INFO)
        dhffl.sendReset()
        readwritethread = threading.Thread(target=dhffl.readwrite, args=(inq,outq))
        logger.info('Starting readwrite thread')
        readwritethread.start()
        # Wait for device to be ready
        # Flush the queue
        while True:
            time.sleep(0.5)
            try:
                ret = outq.get_nowait()
                if(ret['status'] == 'ready'):
                    logger.info('Device is ready')
                    break
            except:
                continue
        time.sleep(0.5)
        # Check if interactive or command line mode
        if args.write_flash is not None:
            try:
                macstr = list(dhffl.devices.keys())[0]
                d = dhffl.devices[macstr]
                macsum = d.macsum_boots
                flag_device = True
            except:
                logger.warning('No device found')
                flag_device = False

            if flag_device == False:
                logger.warning('No device found')
                time.sleep(1)
                inq.put('STOP')
                time.sleep(1)
                print('Stopping now')
                return True
            else:
                # Flush the queue
                while True:
                    try:
                        ret = outq.get_nowait()
                    except:
                        break

                filename = args.write_flash
                logger.info('Writing file to flash {:s}'.format(filename))
                fwrite = open(filename)
                flag_ready = True
                flag_writegood = True
                flag_timeout = False
                hexdata_all = []
                for hexdata in fwrite.readlines():
                    hexdata_all.append(hexdata)

                nlines = len(hexdata_all)
                for nline,hexdata in enumerate(hexdata_all):
                    logger.info('Writing {:d} of {:d}'.format(nline,nlines))
                    hexdata_mod = hexdata.replace("\n","").replace("\c","")
                    DEVICECOMMAND = "${:s}{:s}{:s}\n".format(macstr, macsum, hexdata_mod)
                    logger.debug('Sending write command:{:s}, with len {:d}'.format(DEVICECOMMAND, len(DEVICECOMMAND)))
                    inq.put('SEND {:s}'.format(DEVICECOMMAND))
                    flag_ready = False
                    flag_writegood = False
                    tsend = time.time()
                    while True:
                        try:
                            ret = outq.get_nowait()
                        except:
                            time.sleep(0.01)
                            ret = {}
                            ret['status']= 'exception'

                        if ret['status'] == 'writegood':
                            #print('Writegood, continuing')
                            flag_writegood = True
                        elif ret['status'] == 'ready':
                            #print('ready, continuing')
                            flag_ready = True

                        if flag_ready and flag_writegood:
                            print('All good, continuing')
                            break
                        elif ( time.time()- tsend ) > 5:
                            logger.warning('Timeout, stopping write')
                            flag_timeout = True
                            break

                    if flag_timeout:
                        break
                    #input('Yes?')
                    #time.sleep(10)



            # Check if programming has been done
            while True:
                flag_done = (len(dhffl.serial_commands) == 0) and dhffl.FLAG_READY
                print('Status',len(dhffl.serial_commands),dhffl.FLAG_READY)
                time.sleep(0.5)
                if flag_done:
                    time.sleep(1)
                    inq.put('STOP')
                    time.sleep(1)
                    print('Stopping now')
                    return True

        macstr = ''
        #inq.put('Hallo')
        #time.sleep(0.5)
        while True:
            command = input('Command:')
            print('Got command {:s}'.format(command))
            if (command == '\n'):
                continue
            elif (command.upper() == 'DEVICES'):
                print(dhffl.devices)
                for i,mac in enumerate(dhffl.devices.keys()):
                    print('Device {:d}: MAC {:s}'.format(i,mac))
            elif (command.upper() == 'STOP') or (command.upper() == 'EXIT'):
                inq.put('STOP')
                time.sleep(1)
                print('Stopping now')
                return True
            elif (command.upper() == 'RESET'):
                macstr = ''
                inq.put('RESET')
            elif command.upper().startswith('WRITE'):
                # WRITE 2 4000 ABCD
                try:
                    macstr = list(dhffl.devices.keys())[0]
                    d = dhffl.devices[macstr]
                    macsum = d.macsum_boots
                except:
                    logger.warning('No device found')
                    continue

                nbytestr = command.split(' ')[1]
                nbyteshexstr = hex(int(nbytestr))
                startaddrhexstr = command.split(' ')[2]
                datahexstr = command.split(' ')[3]
                try:
                    datawrite = bytes.fromhex(datahexstr)
                    nbytes_int = int(nbyteshexstr, 16)
                    startaddr_int = int(startaddrhexstr, 16)
                    logger.debug('Writing {:s} bytes from {:s} '.format(nbytestr, startaddrhexstr))
                    FLAG_WRITE = True
                except Exception as e:
                    logger.exception(e)
                    FLAG_WRITE = False

                if FLAG_WRITE:
                    comstr = ':'
                    checksum = 0xFF
                    DEVICECOMMAND = "${:s}{:s}{:s}{:02X}{:04X}00{:s}{:02X}\n".format(macstr, macsum, comstr, nbytes_int, startaddr_int,datahexstr,checksum)
                    logger.debug('Sending write command:{:s}, with len {:d}'.format(DEVICECOMMAND, len(DEVICECOMMAND)))
                    inq.put('SEND {:s}'.format(DEVICECOMMAND))
            elif command.upper().startswith('READ'):
                try:
                    macstr = list(dhffl.devices.keys())[0]
                    d = dhffl.devices[macstr]
                    macsum = d.macsum_boots
                except:
                    logger.warning('No device found')
                    continue
                # READ NBYTES STARTADDR
                nread = 32 # read nread bytes at once from device
                comstr_input = command.split(' ')[0]
                nbytestr = command.split(' ')[1]
                nbyteshexstr = hex(int(nbytestr))
                startaddrhexstr = command.split(' ')[2]
                try:
                    nbytes_int = int(nbyteshexstr, 16)
                    startaddr_int = int(startaddrhexstr, 16)
                    logger.debug('Reading {:s} bytes from {:s} '.format(nbytestr,startaddrhexstr))
                    FLAG_READ = True
                except Exception as e:
                    logger.exception(e)
                    FLAG_READ = False

                if FLAG_READ:
                    print('READING from device {:s}'.format(macstr))
                    ntotal = 0
                    t0 = time.time()
                    for nread_tmp in range(0,nbytes_int,nread):
                        nread_com = nread
                        raddr = startaddr_int + nread_tmp
                        # Check if the number of bytes to read is correct, this can happen at the end of the loop
                        eaddr = raddr + nread_com
                        endaddr_int = startaddr_int + nbytes_int
                        #print('Hallo',eaddr,endaddr_int)
                        if eaddr > endaddr_int:
                            #print('Larger')
                            nread_com -= eaddr - endaddr_int

                        ntotal += nread_com
                        #print(nread_tmp, nbytes_int, nread,nread_com, ntotal)
                        #print('reading from 0x{:04X}'.format(raddr))
                        #macstr = 'FC0FE7FFFE16A264'
                        #macsum = '0B'
                        comstr = 'r'
                        DEVICECOMMAND = "${:s}{:s}{:s}{:02X}{:08X}0000\n".format(macstr,macsum,comstr,nread_com,raddr)
                        logger.debug('Sending read command:{:s}, with len {:d}'.format(DEVICECOMMAND,len(DEVICECOMMAND)))
                        inq.put('SEND {:s}'.format(DEVICECOMMAND))
                        data = outq.get()
                        #print('data',data)

                    t1 = time.time()
                    dtread = t1 - t0
                    logger.info('Read {:d}bytes in {:f}s'.format(ntotal,dtread))
                    print('Total',nbytes_int,ntotal)








if __name__ == '__main__':
    sys.exit(main())  # next section explains the use of sys.exit
