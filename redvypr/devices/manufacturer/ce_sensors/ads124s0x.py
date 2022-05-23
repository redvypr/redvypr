import time
import sys
from collections.abc import Iterable   
import datetime
try:
    import spidev
except:
    print('WARNING: Could not import spidev, the module cannot be used to connect to a real device, only useful for testing!')



class ads124s0x_pihat:
    def __init__(self,spidev=None):
        self.spidev = spidev
        # The register definitions
        regs             = {}
        regs['ID']       = 0
        regs['STATUS']   = 1
        regs['INPMUX']   = 2
        regs['PGA']      = 3
        regs['DATARATE'] = 4
        regs['REF']      = 5
        regs['IDACMAG']  = 6
        regs['IDACMUX']  = 7
        self.regs = regs
        SPS_all = [2,5,10,16.6,20,50,60,100,200,400,800,1000,2000,4000,4000,-9999]
        self.SPS = SPS_all                
        self.register = None

    def init_device(self):
        # Looking for ADS device
        spi = spidev.SpiDev()
        bus = 0 # SPI0
        device = 0 # CS
        spi.open(bus,device)
        spi.max_speed_hz = 1000000 # 5000 before
        spi.mode = 0b01
        self.spi = spi        
        print('Starting up the ADC ...')
        print('Reading all registers:')
        data = self.read_reg(0,18) # Reading all registers
        print('Registers:',data)
        self.reset()
        time.sleep(.5)
        #print('Initializing the ADC to chop mode and single mode')
        #set_datarate(chop=1,mode=1) # Chop mode, single sample mode
        #set_datarate() # Standard mode
        #data = self.read_reg(0,18) # Reading all registers
        #print('Registers after setup:',data)

    def get_registers(self):
        """ Reads all registers
        """
        print('Starting up the ADC ...')
        print('Reading all registers:')
        data = self.read_reg(0,18) # Reading all registers
        self.register = data[2:]

    def print_registers(self):
        """ Prints a human readable status of the registers
        """
        self.print_idreg(self.register[0])
        self.print_statusreg(self.register[1])
        self.print_muxreg(self.register[2])
        self.print_pgareg(self.register[3])
        self.print_dataratereg(self.register[4])
        self.print_refreg(self.register[5])
        self.print_idacmagreg(self.register[6])
        self.print_idacmuxreg(self.register[7])        



    def print_idreg(self,reg):
        # id register
        DEV_ID        = (reg & int('00000111', 2))>>0
        DEV_RSV       = (reg & int('11111000', 2))>>3
        # Device ID
        print('ID reserved',DEV_RSV,'Device ID',DEV_ID)
        
    def print_statusreg(self,reg):
        # Status register        
        FL_REF_L0     = (reg & int('00000001', 2))>>0
        FL_REF_L1     = (reg & int('00000010', 2))>>1
        FL_N_RAILN    = (reg & int('00000100', 2))>>2
        FL_N_RAILP    = (reg & int('00001000', 2))>>3
        FL_P_RAILN    = (reg & int('00010000', 2))>>4
        FL_P_RAILP    = (reg & int('00100000', 2))>>5
        RDY           = (reg & int('01000000', 2))>>6
        FL_POR        = (reg & int('10000000', 2))>>7
        print('Status:')
        print('Reference voltage monitor flag,level0:')        
        if(FL_REF_L0 == 0):
            print('\tDifferential reference voltage >= 0.3 V (default)')
        else:
            print('\tDifferential reference voltage < 0.3 V')

        print('Reference voltage monitor flag,level1:')
        if(FL_REF_L1 == 0):
            print('\tDifferential reference voltage >= 1/3 * (AVDD - AVSS)(default)')
        else:
            print('\tDifferential reference voltage < 1/3 * (AVDD - AVSS)')

        print('Negative PGA output at negative rail flag:')
        if(FL_N_RAILN == 0):
            print('\tNo error (default)')
        else:
            print('\tPGA negative output within 150 mV of AVSS')

        print('Negative PGA output at positive rail flag:')        
        if(FL_N_RAILP == 0):
            print('\tNo error (default)')            
        else:
            print('\tPGA negative output within 150 mV of AVDD')

        print('Positive PGA output at negative rail flag:')            
        if(FL_P_RAILN == 0):
            print('\tNo error (default)')
        else:
            print('\tPGA positive output within 150 mV of AVSS')
        print('Positive PGA output at positive rail flag:')
        if(FL_P_RAILP == 0):
            print('\tNo error (default)')            
        else:
            print('\tPGA positive output within 150 mV of AVDD')

        print('Device ready flag:')
        if(RDY == 0):
            print('\tADC ready for communication (default)')
        else:
            print('\tADC not ready')
        print('POR flag:')
        if(FL_POR == 0):
            print('\tRegister has been cleared and no POR event has occurred.')
        else:
            print('\tPOR event occurred and has not been cleared. Flag must be cleared by user register write (default).')                   
    def print_muxreg(self,reg=None):
        if(reg == None):
            reg = self.register[2]
        MUXP     = (reg & int('11110000', 2))>>4  #        
        MUXN     = reg & int('00001111', 2)  #
        # Input MUX register
        mux_all = ['AIN0','AIN1 (default)','AIN2','AIN3','AIN4','AIN5','AIN6','ööAIN7','AIN8','AIN9','AIN10','AIN11','AINCOM','reserved','reserved','reserved']
        print('Inputs  mux:',MUXN,MUXP)
        muxn = mux_all[MUXN]
        muxp = mux_all[MUXP]        
        mux_str = '\tPositive mux: ' + muxp + ' Negative input: ' + muxn
        print(mux_str)        
    def print_pgareg(self,reg):
        # PGA register
        GAIN     = reg & int('00001111', 2)       #
        PGA_EN   = (reg & int('00110000', 2))>>4  #
        DELAY    = (reg & int('11000000', 2))>>6  #
        # GAIN register
        print('Gain:')
        gains = [1,2,4,8,16,32,64,128]
        gain = gains[GAIN]
        gain_str = '\tGain of {:1.0f}'.format(gain)
        print(gain_str)
        print('PGA enable')
        if(PGA_EN == 0):
            print('\tPGA is powered down and bypassed. Enables single-ended measurements with unipolarsupply (Set gain = 1) (default)')
        elif(PGA_EN == 1):
            print('\tPGA enabled (gain= 1 to 128)')
        else:
            print('\tReserved')

        delays = [14,25,64,256,1024,2048,4096,1]
        print('Delay:')
        delay = delays[DELAY]
        delay_str = '\tDelay of {:1.0f}'.format(delay)
        print(delay_str)        

    def print_dataratereg(self,reg):
        # Datarate register
        DR       = reg & int('00001111', 2)       #
        FILTER   = (reg & int('00010000', 2))>>4  #
        MODE     = (reg & int('00100000', 2))>>5  #
        CLK      = (reg & int('01000000', 2))>>6  #
        G_CHOP   = (reg & int('10000000', 2))>>7  #

        # DATARATE register
        print('Datarate:')

        SPS = self.SPS[DR]
        SPS_str = '\t{:.1f} samples per second'.format(SPS)
        print(SPS_str)        
        print('Digital filter',FILTER)
        if(FILTER == 1):
            print('\tLow-latency filter (default)')
        else:
            print('\tsinc**3 filter')

        print('Conversion mode',MODE)
        if(MODE == 1):
            print('\tSingle-shot conversion mode')
        else:
            print('\tContinuous conversion mode (default)')

        print('Clock source selection',CLK)
        if(CLK == 1):
            print('\tExternal clock')
        else:
            print('\tInternal 4.096-MHz oscillator (default)')        

        print('Global chop enable',G_CHOP)
        if(G_CHOP == 1):
            print('\tEnabled')
        else:
            print('\tDisabled (default)')        

    def print_refreg(self,reg):
        # Ref register
        REFCON   = reg & int('00000011', 2)       # 
        REFSEL   = (reg & int('00001100', 2))>>2  # 
        REFN_BUF = (reg & int('00010000', 2))>>4  #
        REFP_BUF = (reg & int('00100000', 2))>>5  #
        FL_REF_EN= (reg & int('11000000', 2))>>6  #

        print('Internal reference:')
        if(REFCON == 0):
            print('\tInternal reference off (default)')
        elif(REFCON == 1):
            print('\tInternal reference on, but powers down in power-down mode ')
        elif(REFCON == 2):
            print('\tInternal reference on, even in power down mode')
        elif(REFCON == 3):
            print('\tReference reserved')

        print('Reference voltage used:')            
        if(REFSEL == 0):
            print('\tREFP0,REFN0 (default)')
        elif(REFSEL == 1):
            print('\tREFP1,REFN1')
        elif(REFSEL == 2):
            print('\tInternal 2.5V reference')
        elif(REFSEL == 3):
            print('\tRefsel reserved')

        print('Negative reference buffer bypass:')
        if(REFN_BUF == 0):
            print('\tEnabled')
        else:
            print('\tDisabled (default)')
            
        print('Negative reference buffer bypass:')
        if(REFP_BUF == 0):
            print('\tEnabled (default)')
        else:
            print('\tDisabled')

        print('Reference monitor configuration:')
        if(FL_REF_EN == 0):
            print('\tDisabled (default)')
        elif(FL_REF_EN == 1):
            print('\tFL_REF_L0 monitor enabled, threshold 0.3V')
        elif(FL_REF_EN == 2):
            print('\tFL_REF_L0 and FL_REF__L1 monitors enabled, threshold 0.3V and 1/3 - (AVDD-AVSS)')
        elif(FL_REF_EN == 3):
            print('\tFL_REF_L0 monitor and 10-MOhm pull-together enabled, threshold 0.3V')


    def print_idacmagreg(self,reg):
        # idacmag register
        IMAG      = reg & int('00001111', 2)       # 
        RSV       = (reg & int('00110000', 2))>>4  # 
        PSW       = (reg & int('01000000', 2))>>6  #
        FL_RAIL_EN= (reg & int('10000000', 2))>>7  #

        imag_all = [0,10,50,100,250,500,750,1000,1500,2000,0,0,0,0,0,0]
        imag = imag_all[IMAG]
        imag_str = '\tExcitation Current {:d}uA'.format(imag)
        print('IDAC Register:')
        print(imag_str)
        
    def print_idacmuxreg(self,reg):
        # idacmux register
        I2MUX     = (reg & int('11110000', 2))>>4  #        
        I1MUX     = reg & int('00001111', 2)  #
        # Input MUX register
        mux_all = ['AIN0','AIN1','AIN2','AIN3','AIN4','AIN5','AIN6','ööAIN7','AIN8','AIN9','AIN10','AIN11','AINCOM','disconnected (default)','disconnected (default)','disconnected (default)']
        print('IDAC mux:',I1MUX,I2MUX)
        i1mux = mux_all[I1MUX]
        i2mux = mux_all[I2MUX]        
        mux_str = '\tI1 mux: ' + i1mux + ' I2 mux: ' + i2mux
        print(mux_str)
        

    def set_datarate(self,chop=0,clk=0,mode=0,dfilter=1,datarate=4):
        """ Sets the datarate register
        """
        cmd = chop     <<7
        cmd += clk     <<6
        cmd += mode    <<5
        cmd += dfilter <<4
        if(datarate < 16):
            cmd += datarate
        else:
            print('Wrong datarate, exiting')
            return

        comstr = "{:08b}".format(cmd)
        print('Set datarate binary ',comstr)
        print('set_datarate: cmd:',cmd)
        self.write_reg(self.regs['DATARATE'],[cmd])

    def reset(self):
        """ Resets the ADC
        """
        cmd = int('00000110', 2)  # start command
        data = self.spi.xfer2([cmd])

    def start(self):
        """ Starts the conversion
        """
        cmd = int('00001000', 2)  # start command
        data = self.spi.xfer2([cmd])
        
    def stop(self):
        """ Stops a conversion
        """
        cmd = int('00001010', 2)  # start command
        data = self.spi.xfer2([cmd])    

    def read_data(self,fmt='dec',status=False,crc=False,Vref=2.5):
        """ reads adc data using the rdata command
        args:
           fmt: 'dec','bin','int'
        """
        cmd = int('00010010', 2)  # Read command
        if((status == False) and (crc == False)):
            cmd_all = [cmd,0,0,0]

        #print('read data',cmd_all)
        data = self.spi.xfer2(cmd_all)
        if((status == False) and (crc == False)):    
            adc = data[1:4]
            adcn = (adc[0]<<16) + (adc[1]<<8) + adc[2]
            if(adc[0] <128): # positive number
                pass
            else:
                adcn = adcn - 2**24

            adcnr = adcn/(1<<23)*Vref            
            #print('ADC',adc)        
            #print('ADCnum',adcn)
            #print('ADCnr',adcnr)
            if(fmt == 'bin'):
                return adc
            if(fmt == 'int'):
                return adcn                                    
            if(fmt == 'dec'):
                return adcnr


    def set_input(self,iplus,iminus):
        """ Sets the inputs for the ADC
        """
        plusgood = (iplus>=0) and (iplus<=11)
        minusgood = (iminus>=0) and (iminus<=11)
        cmd = iminus + (iplus<<4)
        #binstr = "Register: {:08b}".format(cmd)
        #print(binstr)
        if(plusgood and minusgood):
            self.write_reg(self.regs['INPMUX'],[cmd])
        else:
            print('Registers have to be between 0 and 11')
            return



    def write_reg(self,reg,data):
        #print("Write register(s)",reg,data)
        cmd_all = []
        cmd = int('01000000', 2)  # Read command
        cmd += reg
        nreg = len(data)-1
        cmd_all.append(cmd)
        cmd_all.append(nreg)
        cmd_all.extend(data)
        #print(cmd.to_bytes(1,'big'))
        #print(cmd_all,len(cmd_all))
        data = self.spi.xfer2(cmd_all)

    def read_reg(self,reg,num_regs):
        print("Reading register(s)",reg,num_regs)
        cmd_all = []
        cmd = int('00100000', 2)  # Read command
        cmd += reg
        cmd_all.append(cmd)
        cmd_all.append(num_regs-1)
        cmd_all.extend([0]*num_regs)
        #print(cmd.to_bytes(1,'big'))
        #print(cmd_all,len(cmd_all))
        data = self.spi.xfer2(cmd_all)
        return data


    #https://stackoverflow.com/questions/1952464/in-python-how-do-i-determine-if-an-object-is-iterable
    def iterable(self,obj):
        return isinstance(obj, Iterable)

    def to_csv(self,tu,data):
        """ Creates a csv data string out of the input data
        """
        td = datetime.datetime.fromtimestamp(tu,tz=datetime.timezone.utc)
        tstr = td.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # check if we have an iterable object
        if(self.iterable(data) == False):
            data = [data]
        pstr = tstr + ',{:.3f}'.format(tu)
        #https://stackoverflow.com/questions/1952464/in-python-how-do-i-determine-if-an-object-is-iterable
        for d in data:
            pstr += ',{:1.8f}'.format(d)

        return pstr
    



