"""

Temperature calibration device from Leitenberger

Configuration options for a heatflow device

.. code-block::

- deviceconfig:
    name: lrTcal
    config:
      dummy:
        - name: HFSV
          coeff: [2, 0, 9200, 0, 0, W/m2]
  devicemodulename: lrcal_Tfluid

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
import serial

description = 'Interface for the Leitenberger temperature calibration device'

pyqtgraph.setConfigOption('background', 'w')
pyqtgraph.setConfigOption('foreground', 'k')

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('lrcal_Tfluid')
logger.setLevel(logging.DEBUG)

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
        newdatastr = "{:.2f}".format(data) # TODO, here a format string defined in the widget could be applied
        self.data.setText(newdatastr)
  
        





def start(datainqueue,dataqueue,comqueue,devicename,config={}):
    funcname = __name__ + '.start()'
    chunksize = 1000 # The maximum amount of bytes read with one chunk
    logger.debug(funcname + ':Starting reading serial data')        
    nmea_sentence = ''
    sentences = 0
    bytes_read = 0
    ttest = time.time()
    serial_device = False
    
    try:
        serial_name = config['serial_name']
    except:
        serial_name = 'NaN'
    try:
        baud = config['baud']
    except:
        baud = 9600
    try:
        parity=config['parity']
    except:
        parity=serial.PARITY_NONE
    try:
        stopbits=config['stopbits']
    except:
        stopbits=serial.STOPBITS_ONE
    try:
        bytesize= config['bytesize']
    except: 
        bytesize=serial.EIGHTBITS
    
    try:
        max_size = config['max_size']
    except:
        max_size=10000
        
    try:
        dt = config['dt']
    except:
        dt = 0.5
        
    if True:
        try:
            serial_device = serial.Serial(serial_name,baud,parity=parity,stopbits=stopbits,bytesize=bytesize,timeout=0.1)
            #print('Serial device 0',serial_device)            
            #serial_device.timeout(0.05)
            #print('Serial device 1',serial_device)                        
        except Exception as e:
            #print('Serial device 2',serial_device)
            logger.debug(funcname + ': Exception open_serial_device {:s} {:d}: '.format(serial_name,baud) + str(e))
            return False
        
    try:
        datakey = config['datakey']
    except:
        datakey = 'data'  
        
    while True:
        try:
            com = comqueue.get(block=False)
            print('received',com)
        except:
            pass

        time.sleep(dt)
        
        # Read T set
        com = b'$1RVAR0 \r'
        print(com)
        ser.write(com) # write a string
        s = ser.read(100)
        print(s)
        
        #dataqueue.put(datan)

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
        self.name        = 'Tfluid' # This will be overwritten by the config!
                
    def start(self):
        start(self.datainqueue,self.dataqueue,self.comqueue,devicename=self.name,config=self.config)
        
    def __str__(self):
        sstr = 'Leitenberger temperature calibration device'
        return sstr
    
    
    
class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device)
    device_stop = QtCore.pyqtSignal(Device)        
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        self.device   = device
        self.serialwidget = QtWidgets.QWidget()
        self.init_serialwidget()
        self.label    = QtWidgets.QLabel("Leitenberger FLUID100 Calibration setup")
        #self.startbtn = QtWidgets.QPushButton("Open device")
        #self.startbtn.clicked.connect(self.start_clicked)
        #self.stopbtn = QtWidgets.QPushButton("Close device")
        #self.stopbtn.clicked.connect(self.stop_clicked)
        layout.addWidget(self.label)        
        layout.addWidget(self.serialwidget)
        layout.addStretch()
        #layout.addWidget(self.startbtn)
        #layout.addWidget(self.stopbtn)
        
    def thread_status(self,status):
        self.update_buttons(status['threadalive'])

    def init_serialwidget(self):
        """Fills the serial widget with content
        """
        layout = QtWidgets.QGridLayout(self.serialwidget)
        # Serial baud rates
        baud = [300,600,1200,2400,4800,9600,19200,38400,57600,115200,576000,921600]
        self._combo_serial_devices = QtWidgets.QComboBox()
        #self._combo_serial_devices.currentIndexChanged.connect(self._serial_device_changed)
        self._combo_serial_baud = QtWidgets.QComboBox()
        for b in baud:
            self._combo_serial_baud.addItem(str(b))

        self._combo_serial_baud.setCurrentIndex(4)
        # creating a line edit
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
  
        # setting line edit
        self._combo_serial_baud.setLineEdit(edit)
        
        self._combo_parity = QtWidgets.QComboBox()
        self._combo_parity.addItem('None')
        self._combo_parity.addItem('Odd')
        self._combo_parity.addItem('Even')
        self._combo_parity.addItem('Mark')
        self._combo_parity.addItem('Space')
        
        self._combo_stopbits = QtWidgets.QComboBox()
        self._combo_stopbits.addItem('1')
        self._combo_stopbits.addItem('1.5')
        self._combo_stopbits.addItem('2')
        
        self._combo_databits = QtWidgets.QComboBox()
        self._combo_databits.addItem('8')
        self._combo_databits.addItem('7')
        self._combo_databits.addItem('6')
        self._combo_databits.addItem('5')
        
        self._button_serial_openclose = QtWidgets.QPushButton('Open')
        self._button_serial_openclose.clicked.connect(self.start_clicked)


        # Check for serial devices and list them
        for comport in serial.tools.list_ports.comports():
            self._combo_serial_devices.addItem(str(comport.device))

        layout.addWidget(QtWidgets.QLabel('Serial device'),1,0)
        layout.addWidget(self._combo_serial_devices,2,0)
        layout.addWidget(QtWidgets.QLabel('Baud'),1,1)
        layout.addWidget(self._combo_serial_baud,2,1)
        layout.addWidget(QtWidgets.QLabel('Parity'),1,2)  
        layout.addWidget(self._combo_parity,2,2) 
        layout.addWidget(QtWidgets.QLabel('Databits'),1,3)  
        layout.addWidget(self._combo_databits,2,3) 
        layout.addWidget(QtWidgets.QLabel('Stopbits'),1,4)  
        layout.addWidget(self._combo_stopbits,2,4) 
        layout.addWidget(self._button_serial_openclose,2,5)

        
    
    def update_buttons(self,thread_status):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """
        if(thread_status):
            self._button_serial_openclose.setText('Close')
            self._combo_serial_baud.setEnabled(False)
            self._combo_serial_devices.setEnabled(False)
        else:
            self._button_serial_openclose.setText('Open')
            self._combo_serial_baud.setEnabled(True)
            self._combo_serial_devices.setEnabled(True)
        
            
    def start_clicked(self):
        #print('Start clicked')
        button = self._button_serial_openclose
        #print('Start clicked:' + button.text())
        if('Open' in button.text()):
            button.setText('Close')
            serial_name = str(self._combo_serial_devices.currentText())
            serial_baud = int(self._combo_serial_baud.currentText())
            stopbits = self._combo_stopbits.currentText()
            if(stopbits=='1'):
                self.device.stopbits =  serial.STOPBITS_ONE
            elif(stopbits=='1.5'):
                self.device.stopbits =  serial.STOPBITS_ONE_POINT_FIVE
            elif(stopbits=='2'):
                self.device.config['stopbits'] =  serial.STOPBITS_TWO
                
            databits = int(self._combo_databits.currentText())
            self.device.config['bytesize'] = databits

            parity = self._combo_parity.currentText()
            if(parity=='None'):
                self.device.config['parity'] = serial.PARITY_NONE
            elif(parity=='Even'):                
                self.device.config['parity'] = serial.PARITY_EVEN
            elif(parity=='Odd'):                
                self.device.config['parity'] = serial.PARITY_ODD
            elif(parity=='Mark'):                
                self.device.config['parity'] = serial.PARITY_MARK
            elif(parity=='Space'):                
                self.device.config['parity'] = serial.PARITY_SPACE
                
            self.device.config['serial_name'] = serial_name
            self.device.config['baud'] = serial_baud
            self.device_start.emit(self.device)
        else:
            self.stop_clicked()

    def stop_clicked(self):
        #print('Stop clicked')
        button = self._button_serial_openclose
        self.device_stop.emit(self.device)
        button.setText('Closing') 
        #self._combo_serial_baud.setEnabled(True)
        #self._combo_serial_devices.setEnabled(True)      


class displayDeviceWidget(QtWidgets.QWidget):
    """ Widget is showing temperature calibration data
    """
    def __init__(self,dt_update = 0.5,device=None,buffersize=1000,tabwidget=None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout_plot  = QtWidgets.QGridLayout(self)
        self.device = device
        self.tabname = 'Data'        
        self.dt_update = dt_update
        self.buffersizestd = buffersize
        self.plots = []
        
        config = {'dt_update':self.dt_update,'last_update':time.time()}
        self.config = config
        # 
        self.create_plotwidget()


    def create_plotwidget(self):
        funcname = __name__ + '.create_dataplotwidget()'
        # Add axes to the widget
        logger.debug(funcname )
        # The axes
        title = 'LR Cal'
        location = [2,0]
        whichwidget = 0
        datetick = True
        ylabel = 'T [°C]'
        # The line to plot
        buffersize = self.buffersizestd
        xdata = np.zeros(buffersize) * np.NaN
        ydata = np.zeros(buffersize) * np.NaN
        name = 'LR cal'
        lineplot = pyqtgraph.PlotDataItem( name = name )
        linewidth = 1
        color = QtGui.QColor(255,10,10)
        x = 't'
        y = 'hfV'
        if True:
            plot = pyqtgraph.PlotWidget(title=title)
            self.layout_plot.addWidget(plot,2,0,1,2)
            axis = pyqtgraph.DateAxisItem(orientation='bottom')
            plot.setAxisItems({"bottom": axis})
            plot.setLabel('left', ylabel )
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
            
        # Add displays
        self._datadisplays = {}
        self._datadisplays['T'] = datadisplay(title='T')
        self._datadisplays['Tset'] = datadisplay(title='T set')
        self._datadisplays['Tseted'] = QtWidgets.QLineEdit()
        self._datadisplays['Tseted'].setText('15.00')
        self._datadisplays['Tseted'].setValidator(QtGui.QDoubleValidator())
        self._datadisplays['Tseted'].setMaxLength(6)
        self._datadisplays['Tseted'].setAlignment(QtCore.Qt.AlignRight)
        self._datadisplays['Tsetbut'] = QtWidgets.QPushButton('Set temperature')
        self._datadisplays['Tsetbut'].clicked.connect(self._set_temp)
        self.layout_plot.addWidget(self._datadisplays['T'],0,0)
        self.layout_plot.addWidget(self._datadisplays['Tset'],0,1)
        self.layout_plot.addWidget(self._datadisplays['Tseted'],1,0)
        self.layout_plot.addWidget(self._datadisplays['Tsetbut'],1,1)
        
    def _set_temp(self):
        """ Temperature set command
        """
        T = float(self._datadisplays['Tseted'].text())
        logger.debug('Setting temperature to {:f}'.format(T))
        comdict = {'Tset':T}
        self.device.comqueue.put(comdict)
    
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
            self.snlabel.setText(data['sn'])
            # Update the time
            timestr = datetime.datetime.fromtimestamp(data['t']).strftime('%d %b %Y %H:%M:%S')
            self.timelabel.setText(timestr)
            # Update data display
            channel = data['ch'] # Get the channel
            
            newdata = float(data[channel])
            #print('Channel',channel,'newdata',newdata)
            self._datadisplays[channel].set_data(newdata)

            
        except Exception as e:
            logger.debug(funcname + ':' + str(e))


