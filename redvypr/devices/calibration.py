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
        
        # The mininum and maximum times, used for making the time axis the same between different sensors
        self.tmin = []
        self.tmax = []
        
        self.tmin_old = np.NaN
        self.tmax_old = 0
        
        self.dt_allowoff = 20 # The offset allowed before a new range is used
        
        # Variable to save interval for averaging/cutting by user choice
        self.user_interval = []
        self.data_interval = []
        
        # The units of the different devices
        self.units = []
                
    def start(self):
        start(self.datainqueue,self.dataqueue,self.comqueue)
        
    def get_trange(self):
        """ Create a x axis range for
        """
        
        tmin = min(self.tmin)# - self.dt_allowoff
        tmax = max(self.tmax)# + self.dt_allowoff
        print(self.tmax,self.tmax_old)
        if((tmax-self.tmax_old) > 0):
            tmax = tmax + self.dt_allowoff
            self.tmax_old = tmax
            return [tmin,tmax]
        else:
            return [self.tmin_old,self.tmax_old]
        
        #print('tminmax',tmin,tmax)
        
        
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
    sig_mouse_moved = QtCore.pyqtSignal(float,float) # Signal that is emitted whenever a mouse was moved
    sig_tminmax_changed = QtCore.pyqtSignal(float,float) # Signal that is emitted whenever the minimum and maximum time interval changed
    sig_mouse_clicked = QtCore.pyqtSignal()
    sig_new_user_data = QtCore.pyqtSignal(int) # Signal emitted when the user choose a data interval
    def __init__(self,config = None, dt_update = 0.5,device=None,buffersize=100,numdisp=None):
        """
        Args:
        config:
        numdisp: The display number used to identify the widget
        """
        funcname = __name__ + '.start()'
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QGridLayout(self)
        self.device = device
        self.numdisp = numdisp
        self.buffersizestd = buffersize
        self.plots = []        
        # Add axes to the widget
        #config = device.config
        
        
        print('Hallo',config)
        i = 0
        
        self.vlines = []
        self.vLine_interactive = pyqtgraph.InfiniteLine(angle=90, movable=False)
         
        if True:
            logger.debug(funcname + ': Adding plot' + str(config))
            title = '{:s} x:{:s}, y:{:s}'.format(config['device'],config['x'],config['y']) 
            
            plot = pyqtgraph.PlotWidget(title=title)
            layout.addWidget(plot,1,0)

            graph = plot
            
            if True:
                graph.addItem(self.vLine_interactive, ignoreBounds=True)
                        
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
            line_dict = {'line':lineplot,'config':lineconfig,'x':xdata,'y':ydata,'widget':plot,'newdata':False}
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
        self.mouse_moved_proc(mousePoint.x(), mousePoint.y())
        self.sig_mouse_moved.emit(mousePoint.x(),mousePoint.y())
        
    def mouse_moved_proc(self,x,y):
        """ Function is process the mouse movement, this can be local or by a signal call from another widget 
        """
        if True:
            self.vLine_interactive.setPos(x)
            
            
    def mouse_clicked_proc(self):
        """ Function that is called by signals from other widgets if a mouse was clicked
        """
        print('User Interval',self.device.user_interval)
        for vline in self.vlines:
            self.plots[0]['widget'].removeItem(vline)
            
        self.vlines = []
        for x in self.device.user_interval:
            vLine = pyqtgraph.InfiniteLine(angle=90, movable=False)
            vLine.setPos(x)       
            self.plots[0]['widget'].addItem(vLine, ignoreBounds=True)
            self.vlines.append(vLine)
            
        
    def get_data_clicked(self):
        """ Function called by the get_data button to, yes, get_data
        """
        print('Get some data',len(self.vlines),self.numdisp)
        if(len(self.vlines) == 2):
            print('Get some data')
            tmin = self.device.user_interval[0]
            tmax = self.device.user_interval[1]
            ind = (self.plots[0]['x'] > tmin) & (self.plots[0]['x'] <= tmax)
            xinterval = self.plots[0]['x'][ind]
            yinterval = self.plots[0]['y'][ind]
            print('Len ind',len(ind),len(xinterval))
            if(len(xinterval)>0):
                self.device.data_interval[self.numdisp].append({'x':xinterval,'y':yinterval,'xuser':[tmin,tmax]})
            else:
                self.device.data_interval[self.numdisp].append({'x':[np.NaN],'y':[np.NaN],'xuser':[tmin,tmax]})
                
            # Tell the world that there is new data   
        self.sig_new_user_data.emit(self.numdisp)
            
    def mouseClicked(self,evt):
        """ If the mouse was clicked in this pyqtgraph widget
        """
        
        if evt.button() == QtCore.Qt.LeftButton:
            #col = 
            col = pyqtgraph.mkPen(0.5,width=3)
            colsymbol = pyqtgraph.mkPen(color=QtGui.QColor(150,150,150),width=4)         
            print('Clicked: ' + str(evt.scenePos()))
            mousePoint = self.viewbox.mapSceneToView(evt.scenePos())
            x = mousePoint.x()
            self.device.user_interval.append(x)
            while(len(self.device.user_interval)>2):
                self.device.user_interval.pop(0)
                
            self.mouse_clicked_proc()
             
            if False:
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
            self.sig_mouse_clicked.emit() # Emitting the signal    
                
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
                
    def update_tminmax(self,tmin,tmax):
        """ Functions changes xlimits based on a global value found in device.tmin device.tmax
        """
        pw            = self.plots[0]['widget'] # The plot widget
        pw.setXRange(tmin,tmax)
            
        
    def update(self,data):
        funcname = __name__ + '.update()'
        tnow = time.time()
        #print('got data',data)
        
        devicename = data['device']
        # Only plot the data in intervals of dt_update length, this prevents high CPU loads for fast devices
        update = (tnow - self.config['last_update']) > self.config['dt_update']
        
        
        if(update):
            print('update')
            self.config['last_update'] = tnow
        
        try:
            # Loop over all plot axes
            for line_dict in self.plots:
                # Check if the device is to be plotted
                #lineconfig = {'device':name,'x':x,'y':y,'linewidth':linewidth,'color':color}
                #line_dict = {'line':lineplot,'config':lineconfig,'x':xdata,'y':ydata}
                if(device_in_data(line_dict['config']['device'],data)):
                    #print('data',data) 
                    if True:
                        line      = line_dict['line'] # The line to plot
                        config    = line_dict['config'] # The line to plot
                        x         = line_dict['x'] # The line to plot
                        y         = line_dict['y'] # The line to plot 
                        
                        # data can be a single float or a list
                        newx = data[config['x']]
                        newy = data[config['y']]
                        # Try to get the unit
                        propskeyy = 'props@' + config['y']
                        try:
                            unitstry = data[propskeyy]['unit']
                            self.device.units[self.numdisp] = {'x':'time','y':unitstry}
                        except:
                            self.device.units[self.numdisp] = {'x':'time','y':'NA'}
                        if(type(newx) is not list):
                            newx = [newx]
                            newy = [newy]
                            
                        for inew in range(len(newx)): # TODO this can be optimized using indices instead of a loop
                            x        = np.roll(x,-1)
                            y        = np.roll(y,-1)
                            x[-1]    = float(newx[inew])
                            y[-1]    = float(newy[inew])
                            line_dict['x']  = x
                            line_dict['y']  = y
                            
                        line_dict['newdata']  = True
                        self.device.tmin[self.numdisp] = np.nanmin(x)
                        self.device.tmax[self.numdisp] = np.nanmax(x)  
            if(update):
                for line_dict in self.plots:
                    if(line_dict['newdata']):
                        line      = line_dict['line'] # The line to plot
                        config    = line_dict['config'] # The line to plot
                        x         = line_dict['x'] # The line to plot
                        y         = line_dict['y'] # The line to plot  
                        line.setData(x=x,y=y,pen = pyqtgraph.mkPen(config['color'], width=config['linewidth']))
                        line_dict['newdata']  = False
                        
                    # Use the same time axes for all
                    pw            = line_dict['widget'] # The plot widget
                    if(True):
                        [tmin,tmax] = self.device.get_trange()
                        pw.setXRange(tmin,tmax)
                        self.sig_tminmax_changed.emit(tmin,tmax)
                        ylabel = '[{:s}]'.format(self.device.units[self.numdisp]['y'])
                        pw.setLabel('left', ylabel)
    
        except Exception as e:
            print(e)
            
            
#
#
# The widgets shows average data values together with some statistics and fitting
#
#
class displayTableWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout        = QtWidgets.QGridLayout(self)
        self.device = device
        self.datatable = QtWidgets.QTableWidget()
        self.layout.addWidget(self.datatable,0,0)
        # Buttons to add/remove datapoints
        self.init_table_buttons()
        # The fit widget
        self.init_fitwidget()
        self.layout.addWidget(self.fitwidget['widget'],0,1)
        self.rowstart = 2
        
    def init_table_buttons(self):
        self.btnlayout = QtWidgets.QGridLayout()
        self.layout.addLayout(self.btnlayout,1,0)
        self.btn_addrow = QtWidgets.QPushButton('Add row')
        self.btn_addrow.clicked.connect(self.add_row)
        self.btn_remrow = QtWidgets.QPushButton('Rem row(s)')
        self.btn_remrow.clicked.connect(self.rem_row)
        self.btnlayout.addWidget(self.btn_addrow,0,0)
        self.btnlayout.addWidget(self.btn_remrow,0,1)
        
    def add_row(self):
        """ Adds a new row in the table (manually)
        """
        print('Adding row')
        numrows = self.datatable.rowCount()
        # Add fill value to all data intervals
        for d in self.device.data_interval:
            d.append(None)
        if True:
            self.datatable.setRowCount(numrows + 1)
        
    def rem_row(self):
        """ Remove the selected rows of the table
        """
        print('Removing row')
        rows = []
        for i in self.datatable.selectionModel().selection().indexes():
            row, column = i.row(), i.column()
            rows.append(row)
        
        rows = list(set(rows))  
        rows.sort(reverse=True)   
        print('Rows',rows)
                
        for row in rows:
            if(row >= self.rowstart):
                print('Removing row',row)                        
                self.datatable.removeRow(row)
            else:
                print('Will not remove the first rows',row) 
        
    def init_table(self):
        """
        """
        # Check if config has necessary entries
        try:
            self.device.config['manual']
        except:
            self.device.config['manual'] = []
            
        try:
            self.device.config['comments']
        except:
            self.device.config['comments'] = []
            
            
        try:
            self.device.config['devices']
        except:
            self.device.config['devices'] = []
            
        numcols = len(self.device.config['devices']) + len(self.device.config['manual']) + len(self.device.config['comments'])
        self.datatable.setColumnCount(numcols+2)
        self.datatable.setRowCount(self.rowstart)
        
        #item = QtWidgets.QTableWidgetItem('#')
        #self.datatable.setItem(0,0,item)
        
        item = QtWidgets.QTableWidgetItem('t start')
        self.datatable.setItem(0,0,item)
        
        item = QtWidgets.QTableWidgetItem('t end')
        self.datatable.setItem(0,1,item)
        
        # Add the devices
        colnum = 2
        for i,dev in enumerate(self.device.config['devices']):
            item = QtWidgets.QTableWidgetItem(dev['device'])
            self.datatable.setItem(0,colnum+i,item)
        
        colnum = colnum +i + 1
        
         
        print('Manual',self.device.config['manual'])    
        for i,dev in enumerate(self.device.config['manual']):
            devname = dev['name']
            try:
                devunit = dev['unit']
            except:
                devunit = ''
                
            print('devname',devname,colnum)
            # Add name
            item = QtWidgets.QTableWidgetItem(devname)
            self.datatable.setItem(0,colnum + i,item)
            # Add unit
            item = QtWidgets.QTableWidgetItem(devunit)
            self.datatable.setItem(1,colnum + i,item)
            
        colnum = colnum + i + 1
        # Adding comment rows to the table
        print('Comments',self.device.config['comments'])    
        for i,dev in enumerate(self.device.config['comments']):
            devname = dev['name']
            try:
                devunit = dev['unit']
            except:
                devunit = ''
                
            print('devname',devname,colnum)
            # Add name
            item = QtWidgets.QTableWidgetItem(devname)
            self.datatable.setItem(0,colnum + i,item)
            # Add unit
            item = QtWidgets.QTableWidgetItem(devunit)
            self.datatable.setItem(1,colnum + i,item)
            
        
        #self.device.redvypr.get_data_providing_devices(self.device)        
        self.datatable.resizeColumnsToContents()
        
        # this is done to call reference sensor_changed for the first time
        reference_sensor = self.fitwidget['refcombo'].currentText()
        self.reference_sensor_changed(reference_sensor)
        
    def update_table(self,numdisp=None):
        """ This is called when new data from the realtimedataplot is available, please note that every subscribed device is calling this
        """
        print('Updating',numdisp)
        numrows = self.datatable.rowCount()
        print(self.device.data_interval[numdisp])
        numintervals = len(self.device.data_interval[numdisp]) + self.rowstart
        print('numrows',numrows,'numintervals',numintervals)
        if((numintervals+1) > numrows):
            self.datatable.setRowCount(numrows + 1)#numintervals+self.rowstart)
        
        # Unitstr
        xunit = self.device.units[numdisp]['x']
        yunit = self.device.units[numdisp]['y']
        xunititem = QtWidgets.QTableWidgetItem(xunit)
        yunititem = QtWidgets.QTableWidgetItem(yunit)
        self.datatable.setItem(1,1,xunititem)
        self.datatable.setItem(1,2,xunititem)
        self.datatable.setItem(1,numdisp+3,yunititem)
        
        # The averaged data
        xdata = self.device.data_interval[numdisp][-1]['x']
        ydata = self.device.data_interval[numdisp][-1]['y']
        xuser = self.device.data_interval[numdisp][-1]['xuser']
        xmean = np.nanmean(xdata)
        ymean = np.nanmean(ydata)
        t1str = datetime.datetime.fromtimestamp(xuser[0]).strftime('%d.%m.%Y %H:%M:%S')
        t2str = datetime.datetime.fromtimestamp(xuser[1]).strftime('%d.%m.%Y %H:%M:%S')
        strformat = '{:2.2f}'
        nitem = QtWidgets.QTableWidgetItem(str(numintervals))
        t1item = QtWidgets.QTableWidgetItem(t1str)
        t2item = QtWidgets.QTableWidgetItem(t2str)
        xitem = QtWidgets.QTableWidgetItem(strformat.format(xmean))
        yitem = QtWidgets.QTableWidgetItem(strformat.format(ymean))
        
        #self.datatable.setItem(numintervals+1,0,nitem)
        self.datatable.setItem(numintervals,0,t1item)
        self.datatable.setItem(numintervals,1,t2item)
        self.datatable.setItem(numintervals,numdisp+2,yitem)
        
        self.datatable.resizeColumnsToContents()
        
    def init_fitwidget(self):
        """
        """
        self.fitwidget = {}
        self.fitwidget['widget'] = QtWidgets.QWidget(self)
        self.fitwidget['layout'] = QtWidgets.QGridLayout(self.fitwidget['widget'])
        self.fitwidget['refcombo'] = QtWidgets.QComboBox(self)
        self.fitwidget['refcombo'].currentTextChanged.connect(self.reference_sensor_changed)
        for i,dev in enumerate(self.device.config['devices']):
            self.fitwidget['refcombo'].addItem(dev['device'])
            
        for i,dev in enumerate(self.device.config['manual']):
            self.fitwidget['refcombo'].addItem(dev['name'])
            
        self.fitwidget['layout'].addWidget(QtWidgets.QLabel('Reference Sensor'),0,0)
        self.fitwidget['layout'].addWidget(self.fitwidget['refcombo'],1,0)
        

     
    def reference_sensor_changed(self,reference_sensor):
        """ Is called whenever the reference sensor was changed
        """   
        # Get the column number of the reference sensor
        numcols = self.datatable.columnCount()
        for i in range(numcols):
            item = self.datatable.item(0,i)
            itemtext = item.text()
            if(itemtext  == reference_sensor):
                item.setBackground(QtGui.QColor(200,200,200))
            else:
                item.setBackground(QtGui.QColor(255,255,255))
#
#
# The display widget
#
#
class displayDeviceWidget(QtWidgets.QWidget):
    """ Widget is a wrapper for several plotting widgets (numdisp, graph) 
    This widget can be configured with a configuration dictionary
    Args: 
    tabwidget:
    """
    
    def __init__(self,dt_update = 0.25,device=None,buffersize=100,tabwidget = None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout        = QtWidgets.QGridLayout(self)
        self.device = device
        self.buffersizestd = buffersize
        self.plots = []
        self.databuf = [] # A buffer of data
        self.tabwidget = tabwidget
        self.widgets = {}

        self.tabwidget.addTab(self,'Data')   
        config = {'dt_update':dt_update,'last_update':time.time()}
        self.config = config
        if True: # Here one could check if we want to have a table 
            self.widgets['table'] = displayTableWidget(device = self.device)
            
            i1 = self.tabwidget.addTab(self.widgets['table'],'Table')
            
        # Add buttons
        self.btn_add_interval = QtWidgets.QPushButton('Get data')
        
        self.update_widgets()

    def update_widgets(self):
        """ Compares self.config and widgets and add/removes plots if necessary
        """
        funcname = __name__ + '.update_widgets():'
        logger.debug(funcname)
        self.device.tmin = []
        self.device.tmax = []
        # Remove all plots (thats brute but easy to bookeep
        for plot in self.plots:
            plot.close()
            
        # Clear the data interval list
        self.device.data_interval = []
        # Add axes to the widget
        config=self.device.config
        #print('Hallo2',config['devices'])
        for i,config_device in enumerate(config['devices']):
            logger.debug(funcname + ': Adding device ' + str(config_device))                
            plot = displayDeviceCalibrationWidget(config_device,device=self.device,numdisp=i)
            self.btn_add_interval.clicked.connect(plot.get_data_clicked)
            self.layout.addWidget(plot,i,0)
            self.plots.append(plot)
            # Add the tmin/tmax functionality
            self.device.tmin.append(1e30)
            self.device.tmax.append(-1e30)
            self.device.data_interval.append([])
            self.device.units.append({'x':'time','y':'NA'})
            
        # Connect all mouse moved signals
        for plot in self.plots:
            for plot2 in self.plots:
                if(plot == plot2):
                    continue
                else:
                    plot.sig_mouse_moved.connect(plot2.mouse_moved_proc)
                    plot.sig_tminmax_changed.connect(plot2.update_tminmax)
                    plot.sig_mouse_clicked.connect(plot2.mouse_clicked_proc)
                    plot.sig_new_user_data.connect(self.new_user_data)
         
        self.layout.addWidget(self.btn_add_interval,i+1,0)
        # Update the average data table
        self.widgets['table'].init_table()
        
        
    def new_user_data(self,numdisp):
        print('New user data',numdisp)
        self.widgets['table'].update_table(numdisp=numdisp)
               
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

            
