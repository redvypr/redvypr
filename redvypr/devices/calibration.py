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
from redvypr.data_packets import device_in_data, get_keys

pyqtgraph.setConfigOption('background', 'w')
pyqtgraph.setConfigOption('foreground', 'k')

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('calibration')
logger.setLevel(logging.DEBUG)


def start(datainqueue,dataqueue,comqueue):
    funcname = __name__ + '.start()'        
    while True:
        try:
            com = comqueue.get(block=False)
            print('received',com)
            break
        except:
            pass


        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
                dataqueue.put(data)

            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))
                

class Device():
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None,config = []):
        """
        """
        self.publish     = False # publishes data, a typical sensor is doing this
        self.subscribe   = True  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.config      = config # Please note that this is typically a placeholder, the config structure will be written by redvypr and the yaml
                
    def start(self):
        start(self.datainqueue,self.dataqueue,self.comqueue)
        
    def __str__(self):
        sstr = 'calibration'
        return sstr



class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device)
    device_stop = QtCore.pyqtSignal(Device)            
    connect      = QtCore.pyqtSignal(Device) # Signal requesting a connect of the datainqueue with available dataoutqueues of other sensors
    def __init__(self,sensor=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QFormLayout(self)
        self.device   = device        
        self.label    = QtWidgets.QLabel("Rawdatadisplay setup")
        self.conbtn = QtWidgets.QPushButton("Connect logger to devices")
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
                self.startbtn.setText('Stop logging')
                self.startbtn.setChecked(True)
                #self.conbtn.setEnabled(False)
            else:
                self.startbtn.setText('Start logging')
                #self.conbtn.setEnabled(True)



#                
#
#
#
#
#
#
class displayDeviceCalibrationWidget(QtWidgets.QWidget):
    """ Widget is plotting realtimedata using the pyqtgraph functionality
    This widget can be configured with a configuration dictionary 
    """
    def __init__(self,config = None, dt_update = 0.5,device=None,buffersize=100):
        funcname = __name__ + '.start()'
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QGridLayout(self)
        self.device = device
        self.buffersizestd = buffersize
        self.plots = []        
        # Add axes to the widget
        #config = device.config
        print('Hallo',config)
        i = 0
        if True:
            logger.debug(funcname + ': Adding plot' + str(config))
            title = config['device']
            
            plot = pyqtgraph.PlotWidget(title=title)
            layout.addWidget(plot,i,0)

            graph = plot
            # Get the mouse move events to draw a line 
            graph.scene().sigMouseMoved.connect(self.mouseMoved)
            graph.scene().sigMouseClicked.connect(self.mouseClicked)
            self.viewbox = graph.plotItem.vb
            # Add a vertical line
            vLine = pyqtgraph.InfiniteLine(angle=90, movable=False)            
            graph.addItem(vLine, ignoreBounds=True)
            self.vline = vLine
            
            # Add time as date
            try:
                datetick = config['datetick']
            except:
                datetick = True
                
            if(datetick):
                axis = pyqtgraph.DateAxisItem(orientation='bottom')
                plot.setAxisItems({"bottom": axis})
                
            # If a xlabel is defined                
            try:
                plot.setLabel('left', config['ylabel'] )
            except:
                pass
            
            # If a ylabel is defined                
            try:
                plot.setLabel('bottom', config['xlabel'] )
            except:
                pass
                        
            # Add a lines with the actual data to the graph
            #logger.debug(funcname + ':Adding a line to the plot:' + str(line))
            try:
                buffersize = config['buffersize']
            except:
                buffersize = self.buffersizestd
                    
                xdata = np.zeros(buffersize) * np.NaN
                ydata = np.zeros(buffersize) * np.NaN
                
                
            name = config['device']
            lineplot = pyqtgraph.PlotDataItem( name = name)
                
            try:
                x = config['x']
            except:
                x = ""
                    
            try:
                y = config['y']
            except:
                y = ""
                    
            try:
                linewidth = config['linewidth']
            except:
                linewidth = 1
                    
            try:
                colors = line['color']
                color = QtGui.QColor(colors[0],colors[1],colors[2])
            except Exception as e:
                logger.debug('No color found:' + str(e))
                color = QtGui.QColor(255,10,10)
                    
            # Configuration of the line plot
            lineconfig = {'device':name,'x':x,'y':y,'linewidth':linewidth,'color':color}
            # Add the line and the configuration to the lines list
            line_dict = {'line':lineplot,'config':lineconfig,'x':xdata,'y':ydata,'widget':plot}
            print('Line dict',line_dict)
            plot.addItem(lineplot)
            # Configuration 
            self.plots.append(line_dict)
            
        config = {'dt_update':dt_update,'last_update':time.time()}
        self.config = config

    def mouseMoved(self,evt):
        """Function if mouse has been moved in a pyqtgraph
        """
        pos = (evt.x(),evt.y())
        mousePoint = self.viewbox.mapSceneToView(evt)
        print(mousePoint.x())
        #for vline in self.vlines:
        #    vline.setPos(mousePoint.x())

    def mouseClicked(self,evt):
        """ If the mouse was clicked in a pyqtgraph
        """
        if False:
            #col = 
            col = pyqtgraph.mkPen(0.5,width=3)
            colsymbol = pyqtgraph.mkPen(color=QtGui.QColor(150,150,150),width=4)         
            print('Clicked: ' + str(evt.scenePos()))
            mousePoint = self.vb.mapSceneToView(evt.scenePos())
            click = {}

            if len(self.avg_interval)==2:
                for ax in self.pyqtgraph_axes:
                    for vline in self.avg_interval[0]['vline']:
                        ax['graph'].removeItem(vline)
                    for vline in self.avg_interval[1]['vline']:
                        ax['graph'].removeItem(vline)                    


                self.avg_interval.pop()
                self.avg_interval.pop()            

            click['vline'] = []
            for ax in self.pyqtgraph_axes:
                vLine = pyqtgraph.InfiniteLine(angle=90, movable=False)
                vLine.setPos(mousePoint.x())            
                ax['graph'].addItem(vLine, ignoreBounds=True)        
                click['vline'].append(vLine)

            click['x'] = mousePoint.x()
            self.avg_interval.append(click)        
                
    def config_widget(self):
        """
        """
        self.configwidget = QtWidgets.QWidget(self)
        self.configwidget.show()
        
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
        funcname = __name__ + '.update()'
        tnow = time.time()
        print('got data',data)

        devicename = data['device']
        # Only plot the data in intervals of dt_update length, this prevents high CPU loads for fast devices
        update = (tnow - self.config['last_update']) > self.config['dt_update']
        
        print('update')
        if(update):
            self.config['last_update'] = tnow
        
        try:
            # Loop over all plot axes
            for line_dict in self.plots:
                # Check if the device is to be plotted
                #lineconfig = {'device':name,'x':x,'y':y,'linewidth':linewidth,'color':color}
                #line_dict = {'line':lineplot,'config':lineconfig,'x':xdata,'y':ydata}
                print(devicename,line_dict['config']['device'])                
                if(device_in_data(line_dict['config']['device'],data)): 
                    print('Good')
                    pw        = line_dict['widget'] # The plot widget
                    if True:
                        line      = line_dict['line'] # The line to plot
                        config    = line_dict['config'] # The line to plot
                        x         = line_dict['x'] # The line to plot
                        y         = line_dict['y'] # The line to plot   
                        x         = np.roll(x,-1)       
                        y         = np.roll(y,-1)
                        x[-1]    = float(data[config['x']])
                        y[-1]    = float(data[config['y']])                
                        line_dict['x']  = x
                        line_dict['y']  = y
            if(update):
                for line_dict in self.plots:    
                    if(device_in_data(line_dict['config']['device'],data)): 
                        if True:
                            line      = line_dict['line'] # The line to plot
                            config    = line_dict['config'] # The line to plot
                            x         = line_dict['x'] # The line to plot
                            y         = line_dict['y'] # The line to plot  
                            line.setData(x=x,y=y,pen = pyqtgraph.mkPen(config['color'], width=config['linewidth']))
                            #pw.setXRange(min(x[:ind]),max(x[:ind]))
    
        except Exception as e:
            print(e)

#
#
# The display widget
#
#

class displayDeviceWidget(QtWidgets.QWidget):
    """ Widget is a wrapper for several plotting widgets (numdisp, graph) 
    This widget can be configured with a configuration dictionary 
    """
    def __init__(self,dt_update = 0.25,device=None,buffersize=100):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout        = QtWidgets.QGridLayout(self)
        self.device = device
        self.buffersizestd = buffersize
        self.plots = []
        self.databuf = [] # A buffer of data

            
        config = {'dt_update':dt_update,'last_update':time.time()}
        self.config = config
        self.update_widgets()

    def update_widgets(self):
        """ Compares self.config and widgets and add/removes plots if necessary
        """
        funcname = __name__ + '.update_widgets():'
        logger.debug(funcname)
        # Remove all plots (thats brute but easy to bookeep
        for plot in self.plots:
            plot.close()
            
        # Add axes to the widget
        config=self.device.config
        print('Hallo2',config['devices'])
        for i,config_device in enumerate(config['devices']):
            logger.debug(funcname + ': Adding device ' + str(config_device))                
            plot = displayDeviceCalibrationWidget(config_device,device=self.device)
            self.layout.addWidget(plot,i,0)
            self.plots.append(plot)
                
    def config_widget(self):
        """
        """
        self.configwidget = QtWidgets.QWidget(self)
        self.configwidget.show()
        
    def thread_status(self,status):
        """ This function is regularly called by redvypr whenever the thread is started/stopped
        """
        print('Thread',status)
        #self.update_buttons(status['threadalive'])
        
    def update_line_styles(self):
        for plot_dict in self.plot_dicts:
            for line_dict in plot_dict['lines']:
                config = line_dict['config'] 
        
    def update(self,data):
        funcname = __name__ + '.update():'
        tnow = time.time()
        self.databuf.append(data)
        #print('got data',data)
        #print('statistics',self.device.statistics)
        devicename = data['device']
        # Only plot the data in intervals of dt_update length, this prevents high CPU loads for fast devices
        update = (tnow - self.config['last_update']) > self.config['dt_update']
        #print('update update',update)
        if(update):
            self.config['last_update'] = tnow
            try:
                for data in self.databuf:
                    for plot in self.plots:
                        plot.update(data)

                self.databuf = []
    
            except Exception as e:
                logger.debug(funcname + 'Exception:' + str(e))

            
