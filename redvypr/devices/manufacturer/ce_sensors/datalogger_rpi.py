"""

Raspberry PI based datalogger device

Configuration options for a heatflow device

.. code-block::

- deviceconfig:
    name: datalogger_rpi
    config:
      dummy:
        - name: HFSV
          coeff: [2, 0, 9200, 0, 0, W/m2]
  devicemodulename: datalogger_rpi

"""

import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import yaml
import pyqtgraph
import tempsensor
# This import does only work on a respberry PI (spidev needed)
from .ads124s0x import ads124s0x_pihat

logger = logging.getLogger('datalogger_rpi')
logger.setLevel(logging.DEBUG)

    
description = 'Interface to a raspberry PI based ADSADC shield'

pyqtgraph.setConfigOption('background', 'w')
pyqtgraph.setConfigOption('foreground', 'k')

logging.basicConfig(stream=sys.stderr)


class datadisplay(QtWidgets.QWidget):
    """ A class that displays a number together with a title
    """
    def __init__(self,title=''):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        self.titlestr = title
        self.title    = QtWidgets.QLabel(self.titlestr)
        self.data     = QtWidgets.QLabel('no data')
        fsize         = self.data.fontMetrics().size(0, self.data.text())
        self.data.setFont(QtGui.QFont('Arial', fsize.height()+10))
        layout.addWidget(self.title)
        layout.addWidget(self.data)

    def set_data(self,data):
        newdatastr = "{:.6f}".format(data) # TODO, here a format string defined in the widget could be applied
        self.data.setText(newdatastr)
  
        


def parse_nmea(data):
    """ Parses a NMEA type heatflow data string
    $pi4werkstatt,0,2022-04-27 03:44:52.481,1651031092.482,0.00000000
    """

    datas = data.split(',')
    datadict = {}
    datadict['sn']         = datas[0][1:]        # Serialnumber
    datadict['tsample']    = float(datas[3])
    channel                = datas[1]            # The channel
    channel_unit           = '?' + channel
    datadict['ch']         = channel
    datadict[channel]      = float(datas[4])     # The data
    datadict[channel_unit] = {'unit':'V'}
    
    return datadict


def convert_data(data,chn,config):
    funcname = __name__ + '.convert_data():'    

    try:
        confch     = config['channels'][chn]
        convtype   = config['channels'][chn]['type']
        convcoeffs = config['channels'][chn]['coeffs']        
    except Exception as e:
        logger.debug(funcname + ' Did not find conversion data for channel {:s}'.format(chn))
        confch = None

    if(confch is not None):
        #print('Found configuration')
        data_conv = {}
        try:
            chconv = config['channels'][chn]['device']['serialnumber']# The channel name of the converted data
        except:
            chconv = chn + '_conv'
        if(confch['type'].upper() == 'Steinhart-Hart NTC'.upper()): # NTC, TODO, this should be done more general
            T                   = tempsensor.ntc.get_T_Steinhart_Hart(data,convcoeffs)
            infoconv            = '?' + chconv
            data_conv[chconv]   = T
            data_conv[infoconv] = {'ch':chn}
            data_conv['ch_conv'] = chconv # Make a key with the converted channel name, that makes it easier to look for the data
            #print('Temperature',T)
        elif(confch['type'].upper() == 'Polynom'.upper()): # NTC, TODO, this should be done more general            
            p = numpy.polynomial.Polynomial(convcoeffs)
            res = p(data)
            infoconv            = '?' + chconv
            data_conv[chconv]   = res
            data_conv[infoconv] = {'ch':chn}
            data_conv['ch_conv'] = chconv # Make a key with the converted channel name, that makes it easier to look for the data

        return data_conv        
    else:
        return None
        


def start(datainqueue,dataqueue,comqueue,devicename,config={}):
    funcname = __name__ + '.start()'

    adc = ads124s0x_pihat()
    adc.init_device()
    ind_datarate = 4
    SPS = adc.SPS[ind_datarate]
    twait = 2.1/float(SPS)
    #twait = 0.1
    print('SPS',SPS,'twait',twait)
    adc.reset()
    adc.set_datarate(datarate = ind_datarate)
    # Set IDAC0 to AIN5 with 0.1 mA
    refreg = int('00010010', 2) # Power on the internal reference, which is needed for the IDAQ
    IDACcurr = int('00000011', 2) # 100uA
    IDACmuxreg = int('11110101', 2) # IDAC1 on AIN5, IDAC2 off
    print('Setup IDAC1 on AIN5 with 100uA')
    adc.write_reg(adc.regs['REF'],[refreg])
    adc.write_reg(adc.regs['IDACMAG'],[IDACcurr])
    adc.write_reg(adc.regs['IDACMUX'],[IDACmuxreg])        
    # Read Pairs:
    # NTC0
    # NTC1
    # VIN
    # Current
    adc.get_registers()
    adc.print_registers()
    adc.start()

    i = -1
    while True:
        try:
            com = comqueue.get(block=False)
            logger.info(funcname + ': received command "{:s}", stopping now'.format(com))
            break
        except:
            pass


        i += 1
        td = datetime.datetime.now(datetime.timezone.utc)

        time.sleep(.01)
        t = time.time()
        if(i%4 == 0):
            adc.set_input(1,0)
        if(i%4 == 1):
            adc.set_input(3,2)                        
        if(i%4 == 2):
            adc.set_input(9,8)        
        if(i%4 == 3):
            adc.set_input(11,10)

        chn = "{:d}".format((i%4)+1)
        adc.start()
        tu = time.time()
        td = datetime.datetime.fromtimestamp(tu,tz=datetime.timezone.utc)
        tstr = td.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        time.sleep(twait)
        adc_data = adc.read_data()
        datad = {'t':time.time(),chn:adc_data,'ch':chn}                    
        # Convert the data (if coefficients are available
        datac = convert_data(adc_data,chn,config)
        if(datac is not None):
            datad = {**datad,**datac}

        #print('Data',datad)
        #print(chn + ',' + csvstr)
        dataqueue.put(datad)

#except Exception as e:
#                logger.debug(funcname + ':Exception:' + str(e))            

class Device():
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None,config = {}):
        """
        """
        self.publish     = True # publishes data, a typical device is doing this
        self.subscribe   = True  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.config      = config # Please note that this is typically a placeholder, the config structure will be written by redvypr and the yaml
        self.name        = 'datalogger_rpi' # This will be overwritten by the config!
                
    def start(self):
        start(self.datainqueue,self.dataqueue,self.comqueue,devicename=self.name,config=self.config)
        
    def __str__(self):
        sstr = 'heatflow_sensor'
        return sstr



class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device) # Signal requesting a start of the device (starting the thread)
    device_stop  = QtCore.pyqtSignal(Device) # Signal requesting a stop of device
    connect      = QtCore.pyqtSignal(Device) # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QFormLayout(self)
        self.device   = device
        self.label    = QtWidgets.QLabel("Heatflowsensor setup")
        self.conbtn = QtWidgets.QPushButton("Connect to datasource devices")
        self.conbtn.clicked.connect(self.con_clicked)
        self.startbtn = QtWidgets.QPushButton("Start logging")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)

        layout.addRow(self.label)        
        layout.addRow(self.conbtn)
        layout.addRow(self.startbtn)

    def con_clicked(self):
        button = self.sender()
        self.connect.emit(self.device)        
            
    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            print("button pressed")
            self.device_start.emit(self.device)
            button.setText("Stop logging")
            self.conbtn.setEnabled(False)
        else:
            print('button released')
            self.device_stop.emit(self.device)
            button.setText("Start logging")
            self.conbtn.setEnabled(True)
            
            
    def thread_status(self,status):
        """ This function is called by redvypr whenever the thread is started/stopped
        """   
        self.update_buttons(status['threadalive'])

       
    def update_buttons(self,thread_status):
            """ Updating all buttons depending on the thread status (if its alive, graying out things)
            """
            if(thread_status):
                self.startbtn.setText('Stop reading data')
                self.startbtn.setChecked(True)
                #self.conbtn.setEnabled(False)
            else:
                self.startbtn.setText('Start reading data')
                #self.conbtn.setEnabled(True)




class displayDeviceWidget(QtWidgets.QWidget):
    """ Widget is showing logger data
    """
    def __init__(self,dt_update = 0.5,device=None,buffersize=1000,tabwidget=None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout_plot        = QtWidgets.QGridLayout(self)
        self.device = device
        self.tabname = 'Converted data plots'        
        self.dt_update = dt_update
        self.buffersizestd = buffersize
        self.plots = []
        
        # Add a widget with the data 
        if(tabwidget is not None):
            self.create_datadisplaywidget()
            self.create_converteddatadisplaywidget()
            #self.datadisplaywidget = QtWidgets.QWidget()            
            tabwidget.addTab(self.datadisplaywidget,'Sensor data')
            if('channels' in self.device.config.keys()):
                tabwidget.addTab(self.converteddatadisplaywidget,'Converted data')            
            
            
        #self.rawplot = QtWidgets.QWidget(self)
        #self.layout_rawplot = QtWidgets.QGridLayout(self.rawplot)
        #tabwidget.addTab(self.rawplot,'Rawdata data plots')                    
        #self.create_dataplotwidget() # This widget is for plots of the data
        config = {'dt_update':self.dt_update,'last_update':time.time()}
        self.config = config


                
    def create_dataplotwidget(self):
        funcname = __name__ + '.create_dataplotwidget()'
        # Add axes to the widget
        for i in range(6):
            if i == 0:
                logger.debug(funcname + ': Adding voltage plot')
                # The axes
                title = 'Heat flow voltage'
                location = [0,0]
                whichwidget = 0
                datetick = True
                ylabel = 'V'
                # The line to plot
                buffersize = self.buffersizestd
                xdata = np.zeros(buffersize) * np.NaN
                ydata = np.zeros(buffersize) * np.NaN
                name = 'HFS'
                lineplot = pyqtgraph.PlotDataItem( name = name )
                linewidth = 1
                color = QtGui.QColor(255,10,10)
                x = 't'
                y = 'hfV'

            elif i == 1:
                logger.debug(funcname + ': Adding heat flow plot')
                # The axes
                title = 'Heat flow'
                location = [0,0]
                whichwidget = 1                
                datetick = True
                ylabel = 'W/m**2'
                # The line to plot
                buffersize = self.buffersizestd
                xdata = np.zeros(buffersize) * np.NaN
                ydata = np.zeros(buffersize) * np.NaN
                name = 'HFS'
                lineplot = pyqtgraph.PlotDataItem( name = name )
                linewidth = 1
                color = QtGui.QColor(255,10,10)
                x = 't'
                y = 'hf'
            elif i == 2:
                logger.debug(funcname + ': Adding heat flow plot')
                # The axes
                title = 'Temperature voltage'
                location = [1,0]
                whichwidget = 0                
                datetick = True
                ylabel = 'V'
                # The line to plot
                buffersize = self.buffersizestd
                xdata = np.zeros(buffersize) * np.NaN
                ydata = np.zeros(buffersize) * np.NaN
                name = 'Temp [V]'
                lineplot = pyqtgraph.PlotDataItem( name = name )
                linewidth = 1
                color = QtGui.QColor(255,10,10)
                x = 't'
                y = 'NTCV'
            elif i == 3:
                logger.debug(funcname + ': Adding heat flow plot')
                # The axes
                title = 'Temperature'
                location = [1,0]
                whichwidget = 1                
                datetick = True
                ylabel = 'degC'
                # The line to plot
                buffersize = self.buffersizestd
                xdata = np.zeros(buffersize) * np.NaN
                ydata = np.zeros(buffersize) * np.NaN
                name = 'Temp '
                lineplot = pyqtgraph.PlotDataItem( name = name )
                linewidth = 1
                color = QtGui.QColor(255,10,10)
                x = 't'
                y = 'NTC'
            elif i == 4:
                logger.debug(funcname + ': Adding input voltage plot')
                # The axes
                title = 'Input voltage not scaled'
                location = [2,0]
                whichwidget = 0                
                datetick = True
                ylabel = 'V'
                # The line to plot
                buffersize = self.buffersizestd
                xdata = np.zeros(buffersize) * np.NaN
                ydata = np.zeros(buffersize) * np.NaN
                name = 'VINV'
                lineplot = pyqtgraph.PlotDataItem( name = name )
                linewidth = 1
                color = QtGui.QColor(255,10,10)
                x = 't'
                y = 'VIN'
            elif i == 5:
                logger.debug(funcname + ': Adding input voltage plot')
                # The axes
                title = 'Input voltage'
                location = [2,0]
                whichwidget = 1                
                datetick = True
                ylabel = 'V'
                # The line to plot
                buffersize = self.buffersizestd
                xdata = np.zeros(buffersize) * np.NaN
                ydata = np.zeros(buffersize) * np.NaN
                name = 'VIN'
                lineplot = pyqtgraph.PlotDataItem( name = name )
                linewidth = 1
                color = QtGui.QColor(255,10,10)
                x = 't'
                y = 'VIN'


            plot = pyqtgraph.PlotWidget(title=title)
            if(whichwidget == 1):
                self.layout_plot.addWidget(plot,location[0],location[1])
            else:
                self.layout_rawplot.addWidget(plot,location[0],location[1])
            if(datetick):
                axis = pyqtgraph.DateAxisItem(orientation='bottom')
                plot.setAxisItems({"bottom": axis})

            plot.setLabel('left', ylabel )
            if False:
                plot.setLabel('bottom', xlabel )

            plot_dict = {'widget':plot,'lines':[]}
            # Add a lines with the actual data to the graph
            if True:
                # Heat flow sensor Voltage
                logger.debug(funcname + ':Adding a line to the plot')
                # Configuration of the line plot
                lineconfig = {'device':self.device,'x':x,'y':y,'linewidth':linewidth,'color':color}
                # Add the line and the configuration to the lines list
                line_dict = {'line':lineplot,'config':lineconfig,'x':xdata,'y':ydata}
                # The lines are sorted according to the devicenames, each device has a list of lines attached to it
                plot_dict['lines'].append(line_dict)
                plot.addItem(lineplot)
                # Add the line to all plots
                self.plots.append(plot_dict)


    def create_datadisplaywidget(self):
        """ Widget that shows the heatflowsensor data
        """
        self.datadisplaywidget = QtWidgets.QWidget()
        self.datadisplaywidget_layout = QtWidgets.QGridLayout(self.datadisplaywidget)
        self.snlabel       = QtWidgets.QLabel('Serialnumber')
        self.timelabel     = QtWidgets.QLabel('Time')
        fsize         = self.snlabel.fontMetrics().size(0, self.snlabel.text())
        self.snlabel.setFont(QtGui.QFont('Arial', fsize.height()+10))
        self.snlabel.setAlignment(QtCore.Qt.AlignCenter)        
        self.timelabel.setFont(QtGui.QFont('Arial', fsize.height()+10))
        self.timelabel.setAlignment(QtCore.Qt.AlignCenter)                
        self._datadisplays = {}
        self._datadisplays['1'] = datadisplay(title='CH1')
        self._datadisplays['2'] = datadisplay(title='CH2')
        self._datadisplays['3'] = datadisplay(title='CH3')
        self._datadisplays['4'] = datadisplay(title='CH4')


        self.datadisplaywidget_layout.addWidget(self.snlabel,0,0,1,2)
        self.datadisplaywidget_layout.addWidget(self.timelabel,1,0,1,2)        
        self.datadisplaywidget_layout.addWidget(self._datadisplays['1'],2,0)
        self.datadisplaywidget_layout.addWidget(self._datadisplays['2'],2,1)
        self.datadisplaywidget_layout.addWidget(self._datadisplays['3'],3,0)
        self.datadisplaywidget_layout.addWidget(self._datadisplays['4'],3,1)                
            
        
    def create_converteddatadisplaywidget(self):
        """ Widget that shows the heatflowsensor data
        """
        self.converteddatadisplaywidget = QtWidgets.QWidget()
        self.converteddatadisplaywidget_layout = QtWidgets.QGridLayout(self.converteddatadisplaywidget)
        self._cdatadisplays = {}
        for ser in self.device.config['channels'].keys():
            try:
                chconv = self.device.config['channels'][ser]['device']['serialnumber']# The channel name of the converted data
            except:
                chconv = ser + '_conv'
                
            self._cdatadisplays[chconv] = datadisplay(title=chconv)
            if(ser == '1'):
                loc = [2,0]
            elif(ser == '2'):
                loc = [2,1]
            elif(ser == '3'):
                loc = [3,0]
            elif(ser == '4'):
                loc = [3,1]
                
            self.converteddatadisplaywidget_layout.addWidget(self._cdatadisplays[chconv],loc[0],loc[1])

        
    
    def thread_status(self,status):
        """ This function is regularly called by redvypr whenever the thread is started/stopped
        """
        pass        
        #self.update_buttons(status['threadalive'])
        
    def update_line_styles(self):
        for plot_dict in self.plot_dicts:
            for line_dict in plot_dict['lines']:
                config = line_dict['config'] 
        
    def update(self,data):
        """ Updates the data display
        """
        
        funcname = __name__ + '.update():'
        tnow = time.time()
        #logger.debug(funcname + 'data {:s}'.format(str(data)))
        try:
            #print(funcname + 'got data',data)
            devicename = data['device']
            # Only plot the data in intervals of dt_update length, this prevents high CPU loads for fast devices
            update = (tnow - self.config['last_update']) > self.config['dt_update']

            if(update):
                self.config['last_update'] = tnow

            # Serialnumber (should stay the same though)
            #self.snlabel.setText(data['sn'])
            # Update the time
            timestr = datetime.datetime.fromtimestamp(data['t']).strftime('%d %b %Y %H:%M:%S')
            self.timelabel.setText(timestr)
            # Update data display
            channel = data['ch'] # Get the channel
            
            newdata = float(data[channel])
            #print('Channel',channel,'newdata',newdata)
            self._datadisplays[channel].set_data(newdata)

            # Look for converted data
            if 'ch_conv' in data.keys():
                #print('Got converted data')
                chconv = data['ch_conv']

                newdata_conv = float(data[chconv])
                #print('Channel',channel,'newdata',newdata)
                self._cdatadisplays[chconv].set_data(newdata_conv)                
                
            
        except Exception as e:
            logger.debug(funcname + ':' + str(e))



    

