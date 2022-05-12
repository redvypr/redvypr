"""
Sensor calibration device

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
from redvypr.data_packets import device_in_data, get_keys, get_datastream
import redvypr.files as files
import xlsxwriter
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

class ntc():
    def __init__(self):
        self.K0 = 273.15 # Zero Kelvin in degree Celsius
    def fit_Steinhart_Hart(self,T,data_fit,R25=1,cfit=3):
        """ Fitting data with a Steinhart-Hart type 
        """
        funcname = 'fit_Steinhart_Hart():'
        K = T + self.K0
        K_1 = 1/K
        dlog = np.log(data_fit)
        try:
            P = np.polyfit(dlog,K_1,cfit)
        except Exception as e:
            logger.debug(funcname + ': Exception fit {:s}'.format(e))
            P = [np.NaN] * cfit
        K_1_fit = np.polyval(P,dlog)
        T_fit = 1/K_1_fit - 273.15
        fit = {'P':P,'T_fit':T_fit,'dlog':dlog,'K_1':K_1,'K_1_fit':K_1_fit,'K':K,'data_fit':data_fit}
        return fit
    
    def print_coeffs(self,fit):
        P = fit['P']
        for i in range(len(P)):
            print('a[{:d}]: {:e}'.format(i,P[-i-1]))
    
    
    def get_T_Steinhart_Hart(self,data,P):
        """ Gets the temperature from a fit polynom and raw data
        """
        dlog = np.log(data)    
        K_1_fit = np.polyval(P,dlog)
        T_fit = 1/K_1_fit - self.K0
        return T_fit

_icon_file = files.icon_file

pyqtgraph.setConfigOption('background', 'w')
pyqtgraph.setConfigOption('foreground', 'k')

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('calibration')
logger.setLevel(logging.INFO)

description = "Sensor calibration device"


standard_color = QtGui.QColor(255,10,10)
standard_color_vline = QtGui.QColor(255,100,100)
standard_linewidth_vline = 2
def start(datainqueue,dataqueue,comqueue):
    funcname = __name__ + '.start()'        
    while True:
        try:
            com = comqueue.get(block=False)
            logger.debug('Received {:s}'.format(str(com)))
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
                
#
#
#https://stackoverflow.com/questions/14097463/displaying-nicely-an-algebraic-expression-in-pyqt#44593428
#
class MathTextLabel(QtWidgets.QWidget):

    def __init__(self, mathText, parent=None, **kwargs):
        super(QtWidgets.QWidget, self).__init__(parent, **kwargs)

        l=QtWidgets.QVBoxLayout(self)
        l.setContentsMargins(0,0,0,0)

        r,g,b,a=self.palette().base().color().getRgbF()

        self._figure=Figure(edgecolor=(r,g,b), facecolor=(r,g,b))
        self._canvas=FigureCanvas(self._figure)
        l.addWidget(self._canvas)
        self._figure.clear()
        text=self._figure.suptitle(
            mathText,
            x=0.0,
            y=1.0,
            horizontalalignment='left',
            verticalalignment='top',
            #size=QtGui.QFont().pointSize()*2
            size=QtGui.QFont().pointSize()
        )
        self._canvas.draw()

        (x0,y0),(x1,y1)=text.get_window_extent().get_points()
        w=x1-x0; h=y1-y0

        self._figure.set_size_inches(w/80, h/80)
        self.setFixedSize(int(w),int(h))
        
        
#                
#
#
#
#
#
#
class PlotWidget(QtWidgets.QWidget):
    """ Widget is plotting realtimedata using the pyqtgraph functionality
    This widget can be configured with a configuration dictionary 
    """
    sig_mouse_moved = QtCore.pyqtSignal(float,float) # Signal that is emitted whenever a mouse was moved
    sig_tminmax_changed = QtCore.pyqtSignal(float,float) # Signal that is emitted whenever the minimum and maximum time interval changed
    sig_mouse_clicked = QtCore.pyqtSignal()
    sig_new_user_data = QtCore.pyqtSignal(int) # Signal emitted when the user choose a data interval
    def __init__(self,config = None, dt_update = 0.5,device=None,buffersize=1000,numdisp=None):
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
        
        i = 0
        self.vlines = []
        color = standard_color_vline
        linewidth = standard_linewidth_vline
        self.vLine_interactive = pyqtgraph.InfiniteLine(angle=90, movable=False,pen = pyqtgraph.mkPen(color, width=linewidth))
         
        if True:
            logger.debug(funcname + ': Adding plot' + str(config))
            title = '{:s} x:{:s}, y:{:s}'.format(config['device'],config['x'],config['y']) 
            
            plot = pyqtgraph.PlotWidget(title=title)
            plot.sigRangeChanged.connect(self._range_changed)
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
                colors = config['color']
                color = QtGui.QColor(colors[0],colors[1],colors[2])
            except Exception as e:
                logger.debug('No color found:' + str(e))
                
                color = standard_color
                    
            # Configuration of the line plot
            lineconfig = {'device':name,'x':x,'y':y,'linewidth':linewidth,'color':color}
            # Add the line and the configuration to the lines list
            line_dict = {'line':lineplot,'config':lineconfig,'x':xdata,'y':ydata,'widget':plot,'newdata':False}
            plot.addItem(lineplot)
            # Configuration 
            self.plots.append(line_dict)
            
        config = {'dt_update':dt_update,'last_update':time.time()}
        self.config = config
        
    def _range_changed(self):
        """ Called when the x or y range of the plot was change
        """
        print('Changed')
        axX = self.plots[0]['widget'].getAxis('bottom')
        print('x axis range: {}'.format(axX.range)) # <------- get range of x axis
        self.sig_tminmax_changed.emit(axX.range[0],axX.range[1])
        
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
            
        
    def clear_data(self):
        """ Clear all data to NaN
        """
        self.plots[0]['x'][:] = np.NaN
        self.plots[0]['y'][:] = np.NaN 
        self.plot_data(force_plot=True)
        
    def get_data_clicked(self):
        """ Function called by the get_data button to, yes, get_data
        """
        print('Get some data',len(self.vlines),self.numdisp)
        data_ret = None
        if(len(self.vlines) == 2):
            print('Get some data')
            tmin = self.device.user_interval[0]
            tmax = self.device.user_interval[1]
            ind = (self.plots[0]['x'] > tmin) & (self.plots[0]['x'] <= tmax)
            xinterval = self.plots[0]['x'][ind]
            yinterval = self.plots[0]['y'][ind]
            print('Len ind',len(ind),len(xinterval))
            if(len(xinterval)>0):
                data_ret = {'x':xinterval.tolist(),'y':yinterval.tolist(),'xuser':[tmin,tmax]}
                #self.device.data_interval[self.numdisp].append({'x':xinterval.tolist(),'y':yinterval.tolist(),'xuser':[tmin,tmax]})
            else:
                data_ret = {'x':[np.NaN],'y':[np.NaN],'xuser':[tmin,tmax]}
                #self.device.data_interval[self.numdisp].append({'x':[np.NaN],'y':[np.NaN],'xuser':[tmin,tmax]})
                
            # Tell the world that there is new data   
        #self.sig_new_user_data.emit(self.numdisp)
        return data_ret
            
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
        print('Hallo',self.device._xsync )
        if(self.device._xsync == 2):
            pw.setXRange(tmin,tmax)
        elif(self.device._xsync == 1):
            print('Updating',tmin,tmax)
            pw.setXRange(tmin,tmax)
            
    def plot_data(self,force_plot = False):
        funcname = __name__ + '.plot_data():'
        try:
            # Loop over all plot axes
            for line_dict in self.plots:
                for line_dict in self.plots:
                    if(line_dict['newdata'] or force_plot):
                        line      = line_dict['line'] # The line to plot
                        config    = line_dict['config'] # The line to plot
                        x         = line_dict['x'] # The line to plot
                        y         = line_dict['y'] # The line to plot  
                        line.setData(x=x,y=y,pen = pyqtgraph.mkPen(config['color'], width=config['linewidth']))
                        line_dict['newdata']  = False
                        
                    # Use the same time axes for all
                    pw            = line_dict['widget'] # The plot widget
                    if(True):
                        config_device = line_dict['config']
                        datastream_x = config_device['device'] + '(' + config_device['x'] + ',' + config_device['y'] + ')' 
                        #datastream_x_combo = 
                        #[tmin,tmax] = self.device.get_trange()
                        #print('tmin',tmin,tmax)
                        #pw.setXRange(tmin,tmax)
                        #self.sig_tminmax_changed.emit(tmin,tmax)
                        ylabel = '[{:s}]'.format(self.device.units[self.numdisp]['y'])
                        #print('hallo',self.numdisp,ylabel)
                        pw.setLabel('left', ylabel)
        except Exception as e:
            logger.debug(funcname + str(e))
            
    def update(self,data):
        funcname = __name__ + '.update():'
        tnow = time.time()
        #print('got data',data)
        
        devicename = data['device']
        # Only plot the data in intervals of dt_update length, this prevents high CPU loads for fast devices
        update = (tnow - self.config['last_update']) > self.config['dt_update']
        
        
        if(update):
            #print('update')
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
                        propskeyy = '?' + config['y']
                        try:
                            unitstry = data[propskeyy]['unit']
                            self.device.units[self.numdisp] = {'x':'time','y':unitstry}
                        except Exception as e:
                            self.device.units[self.numdisp] = {'x':'time','y':'NA'}
                        if(type(newx) is not list):
                            newx = [newx]
                            newy = [newy]
                            
                        #print('Self numdisp',self.numdisp,self.device.units[self.numdisp])
                        for inew in range(len(newx)): # TODO this can be optimized using indices instead of a loop
                            x        = np.roll(x,-1)
                            y        = np.roll(y,-1)
                            x[-1]    = float(newx[inew])
                            y[-1]    = float(newy[inew])
                            line_dict['x']  = x
                            line_dict['y']  = y
                            
                        line_dict['newdata']  = True
                          
            self.plot_data()
    
        except Exception as e:
            pass
            #logger.debug(funcname + str(e))
            
            
#
#
# 
#
#
class PolyfitWidget(QtWidgets.QWidget):
    """ The widgets shows average data values together with some statistics and fitting
    """
    def __init__(self,device=None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout           = QtWidgets.QGridLayout(self)
        self.device           = device
        self.datatable        = QtWidgets.QTableWidget()
        self.datatable.horizontalHeader().hide()
        self.datatable.verticalHeader().hide()
        self.datatable_widget = QtWidgets.QWidget()
        self.datatable.itemChanged.connect(self._datatable_item_changed)
        
        self.headerrows = 2
        self.coloffset  = 1
        self.num_additional_columns = 2 # tstart/tend/numsamples        
        
        # Buttons to add/remove datapoints
        self.init_widgets()
        
        
        self.update_table()
        
    def init_widgets(self):
        """ Create all widgets and put them in a layout
        """
        self.btnlayout = QtWidgets.QGridLayout(self.datatable_widget)
        
        self.layout.addLayout(self.btnlayout,1,0,1,4)
        self.btn_addhdr = QtWidgets.QPushButton('Add header')
        self.btn_addhdr.clicked.connect(self.add_headerrow)
        self.btn_addrow = QtWidgets.QPushButton('Add row')
        self.btn_addrow.clicked.connect(self.add_row)
        self.btn_remrow = QtWidgets.QPushButton('Rem row(s)')
        self.btn_remrow.clicked.connect(self.rem_row)
        self.label_strformat = QtWidgets.QPushButton('Number format')
        self.lineedit_strformat = QtWidgets.QLineEdit('{:2.4f}')
        self.btnlayout.addWidget(self.datatable,1,0,1,5)
        self.btnlayout.addWidget(self.btn_addhdr,2,0)
        self.btnlayout.addWidget(self.btn_addrow,2,1)
        self.btnlayout.addWidget(self.btn_remrow,2,2)
        self.btnlayout.addWidget(self.label_strformat,2,3)
        self.btnlayout.addWidget(self.lineedit_strformat,2,4)
        datalabel = QtWidgets.QLabel('Data')
        datalabel.setAlignment(QtCore.Qt.AlignCenter)
        datalabel.setStyleSheet("font-weight: bold")
        self.btnlayout.addWidget(datalabel,0,0,1,3)
        
        # Initialize the fitwidgets
        self.fitwidget = {}
        self.fitwidget['widget'] = QtWidgets.QWidget(self)
        self.fitwidget['fitbutton'] = QtWidgets.QPushButton('Fit data')
        self.fitwidget['plotbutton'] = QtWidgets.QPushButton('Plot fit')
        

        self.fitwidget['layout'] = QtWidgets.QGridLayout(self.fitwidget['widget'])
        self.fitwidget['refcombo'] = QtWidgets.QComboBox(self)
        self.fitwidget['fittable'] = QtWidgets.QTableWidget(self)
        self.fitwidget['fittable'].horizontalHeader().hide()
        self.fitwidget['fittable'].verticalHeader().hide()
        self.fitwidget['refcombo'].currentTextChanged.connect(self.reference_sensor_changed)
        ## To choose which fit to use    
        self.fitwidget['fitcombo'] = QtWidgets.QComboBox(self)
        self.fitwidget['layout'].addWidget(QtWidgets.QLabel('Fit type'),1,0)
        self.fitwidget['layout'].addWidget(self.fitwidget['fitcombo'],1,1)
        
        self.fitwidget['layout'].addWidget(self.fitwidget['fittable'],3,0,1,2)   
        self.fitwidget['layout'].addWidget(QtWidgets.QLabel('Reference Sensor'),4,0)
        self.fitwidget['layout'].addWidget(self.fitwidget['refcombo'],4,1)
        self.fitwidget['layout'].addWidget(self.fitwidget['fitbutton'],5,0,1,1)
        self.fitwidget['layout'].addWidget(self.fitwidget['plotbutton'],5,1,1,1)
        self.fitwidget['plotbutton'].clicked.connect(self.plot_fit)
        fitlabel = QtWidgets.QLabel('Data fit')
        fitlabel.setStyleSheet("font-weight: bold")
        fitlabel.setAlignment(QtCore.Qt.AlignCenter)
        self.fitwidget['layout'].addWidget(fitlabel,0,0,1,2)
        self.fitwidget['fittable'].resizeColumnsToContents()
        
        
        splitter1 = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter1.addWidget(self.datatable_widget)
        splitter1.addWidget(self.fitwidget['widget'])
        self.layout.addWidget(splitter1)
        
    def plot_fit(self):
        """ Plots the original data together with the fit 
        """
        funcname = self.__class__.__name__ + 'plot_fit()'
        self._plot_widget = QtWidgets.QWidget()
        l=QtWidgets.QVBoxLayout(self._plot_widget)
        l.setContentsMargins(0,0,0,0)

        r,g,b,a=self.palette().base().color().getRgbF()

        self._plot_figure=Figure(edgecolor=(r,g,b), facecolor=(r,g,b))
        self._plot_canvas=FigureCanvas(self._plot_figure)
        l.addWidget(self._plot_canvas)
        self._plot_figure.clear()
        ax = self._plot_figure.add_subplot(111)
        ax.plot([1,2],[1,4],'-r')
        self._plot_canvas.draw()
        self._plot_widget.show()
        
    def add_headerrow(self):
        """ Adds a new headerrow to the table
        """
        self.datatable.insertRow(self.headerrows)
        self.headerrows += 1   
        item = QtWidgets.QTableWidgetItem('Header')
        self.datatable.setItem(self.headerrows-1,0,item)
        self.datatable.resizeColumnsToContents()     
        
    def add_row(self):
        """ Adds a new row in the table (manually)
        """
        print('Adding row')
        numrows = self.datatable.rowCount()
        # Add fill value to all data intervals
        self.datatable.setRowCount(numrows + 1)
        indrow = numrows # numrows - 1 
        for idev,dev in enumerate(self.device.data_interval):
            dempty = {'x':[np.NaN],'y':[np.NaN],'xuser':[0,0]}
            dev.append(dempty)
            
        self.update_table()
        
            
        
    def rem_row(self):
        """ Remove the selected rows of the table
        """
        funcname = self.__class__.__name__ + '.rem_row():'
        logger.debug(funcname)
        rows = []
        for i in self.datatable.selectionModel().selection().indexes():
            row, column = i.row(), i.column()
            rows.append(row)
        
        rows = list(set(rows))
        rows.sort(reverse=True)   
        print('Rows',rows)
        # Remove them from the 
                
        for row in rows:
            #if(row >= self.headerrows): # Check if its an header
            if(row >= 2): # Check if its not an header
                if(row<self.headerrows): # Check if its a header added by the user
                    logger.debug(funcname + 'Removing header row {:d}'.format(row))                        
                    self.datatable.removeRow(row)
                    self.headerrows -= 1
                else:
                    logger.debug(funcname + 'Removing data row {:d}'.format(row))                        
                    num_devices = len(self.device.data_interval)
                    for ndev in range(num_devices):
                        dataitem = self.datatable.item(row,ndev + self.coloffset)
                        try:
                            inddata = dataitem.indrawdata
                            print('a',self.device.data_interval[ndev])
                            print('b',inddata,ndev)
                            self.device.data_interval[ndev].pop(inddata)
                        except Exception as e:
                            print('Could not remove data',str(e))
                            
                    self.datatable.removeRow(row)
            else:
                print('Will not remove the first rows',row) 
                
        self.update_table()
    def _get_devicestr(self,dev):
        """ Helper function to make a generic device string out of the config
        """
        y = dev['y']
        datastream = get_datastream(y,device=dev['device'])
        return datastream 
    
    def update_table_header(self):
        """ Initializes the table according to the self.device.config
        """
        
        numcols = len(self.device.config['devices']) + len(self.device.config['polyfit']['manual']) + len(self.device.config['polyfit']['comments'])
        self.numdevices = len(self.device.config['devices']) + len(self.device.config['polyfit']['manual'])
        self.numcols = numcols
        self.datatable.setColumnCount(numcols+1 + self.num_additional_columns)
        self.headerrows = len(self.device.config['polyfit']['headers']) + 2
        self.datatable.setRowCount(self.headerrows)
        # Add the custom headers
        print('Updating header',len(self.device.config['polyfit']['headers']))
        print(self.device.config['polyfit']['headers'])
        for j,header in enumerate(self.device.config['polyfit']['headers']):
            if(type(header) == str):
                item = QtWidgets.QTableWidgetItem(header)
                self.datatable.setItem(2 + j,0,item)
            else: # A List with headername and contents
                print('fsfdf',header)
                for ih,h in enumerate(header):
                    print('Hallo',h,ih,self.headerrows,j)
                    item = QtWidgets.QTableWidgetItem(str(h))
                    self.datatable.setItem(2 + j,ih,item)
            
            
        
        
        
        FLAG_HAS_DEV = False
        # Add the devices
        colnum = 0
        print('Colnum',colnum)    
        for i,dev in enumerate(self.device.config['devices']):
            devstr = self._get_devicestr(dev)
            colnum = colnum + 1
            item = QtWidgets.QTableWidgetItem(devstr)
            self.datatable.setItem(0,colnum,item)
            FLAG_HAS_DEV = True
        
        
        print('Manual',self.device.config['polyfit']['manual'],colnum)
        for i,dev in enumerate(self.device.config['polyfit']['manual']):
            FLAG_HAS_DEV = True
            colnum = colnum + 1
            devname = dev['name']
            try:
                devunit = dev['unit']
            except:
                devunit = ''
                
            print('devname',devname,colnum)
            # Add name
            item = QtWidgets.QTableWidgetItem(devname)
            self.datatable.setItem(0,colnum,item)
            # Add unit
            item = QtWidgets.QTableWidgetItem(devunit)
            self.datatable.setItem(1,colnum,item)
            
        # Adding comment column to the table
        print('Comments',self.device.config['polyfit']['comments'],colnum)
        for i,dev in enumerate(self.device.config['polyfit']['comments']):
            colnum = colnum + 1
            devname = dev['name']
            try:
                devunit = dev['unit']
            except:
                devunit = ''
                
            print('devname',devname,colnum)
            # Add name
            item = QtWidgets.QTableWidgetItem(devname)
            self.datatable.setItem(0,colnum,item)
            # Add unit
            item = QtWidgets.QTableWidgetItem(devunit)
            self.datatable.setItem(1,colnum,item)
            
        colnum = colnum + 1
        # Add additional information
        self._start_add_info_col = colnum
        item = QtWidgets.QTableWidgetItem('t start')
        self.datatable.setItem(0,colnum,item)
        colnum = colnum + 1
        item = QtWidgets.QTableWidgetItem('t end')
        self.datatable.setItem(0,colnum,item)
        colnum = colnum + 1
        
        # The fit widget
        self.config_fitwidget()

        # Add time unit
        if(FLAG_HAS_DEV):
            # Additional information
            xunit = self.device.units[0]['x']
            # t start/t end
            item = QtWidgets.QTableWidgetItem(xunit)
            self.datatable.setItem(1,self._start_add_info_col,item)
            item = QtWidgets.QTableWidgetItem(xunit)
            self.datatable.setItem(1,self._start_add_info_col+1,item)
            
            # Add header description
            item = QtWidgets.QTableWidgetItem('Device')
            self.datatable.setItem(0,0,item)
            item = QtWidgets.QTableWidgetItem('Unit')
            self.datatable.setItem(1,0,item)
            #self.device.redvypr.get_data_providing_devices(self.device)        
            self.datatable.resizeColumnsToContents()
            
            # this is done to call reference sensor_changed for the first time
            reference_sensor = self.fitwidget['refcombo'].currentText()
            
            
            # update the reference sensor
            self.reference_sensor_changed(reference_sensor)
            
        self.datatable.resizeColumnsToContents()
        
        
    def update_table(self):
        """ This is called when new data from the realtimedataplot is available, note that every subscribed device is calling this
        """
        self.datatable.blockSignals(True)
        funcname = self.__class__.__name__ + '.update_table():'
        numdisp = 0
        logger.debug(funcname)
        numrows = self.datatable.rowCount() - self.headerrows
        try:
            numintervals = len(self.device.data_interval[0])
            numdevices = len(self.device.data_interval)
        except:
            logger.warning(funcname + ' No devices/data intervals found')
            return
        
        self.datatable.setRowCount(numintervals + self.headerrows)
        
        
        for ndev in range(numdevices):
            # Unitstr
            xunit = self.device.units[ndev]['x']
            yunit = self.device.units[ndev]['y']
            xunititem = QtWidgets.QTableWidgetItem(xunit)
            yunititem = QtWidgets.QTableWidgetItem(yunit)
            self.datatable.setItem(1,ndev+self.coloffset,yunititem)
            for i in range(numintervals):
                numrow = i + self.headerrows
                numrowsnew = self.datatable.rowCount() - self.headerrows
                #print('fdf',self.device.data_interval[numdisp])
                #print('numrows',numrows,'numintervals',numintervals,'numrow',numrow,'numrowsnew',numrowsnew)
                # The averaged data
                xdata = self.device.data_interval[ndev][i]['x']
                ydata = self.device.data_interval[ndev][i]['y']
                xuser = self.device.data_interval[ndev][i]['xuser']
                xmean = np.nanmean(xdata)
                ymean = np.nanmean(ydata)
                t1str = datetime.datetime.fromtimestamp(xuser[0]).strftime('%d.%m.%Y %H:%M:%S')
                t2str = datetime.datetime.fromtimestamp(xuser[1]).strftime('%d.%m.%Y %H:%M:%S')
                strformat = self.lineedit_strformat.text()
                #strformat = '{:2.2f}'
                nitem  = QtWidgets.QTableWidgetItem(str(numintervals))
                t1item = QtWidgets.QTableWidgetItem(t1str)
                t2item = QtWidgets.QTableWidgetItem(t2str)
                xitem  = QtWidgets.QTableWidgetItem(strformat.format(xmean))
                yitem  = QtWidgets.QTableWidgetItem(strformat.format(ymean))
                yitem.rawdata    = ymean # Save the original data as additional property regardless of the display type
                yitem.indrawdata = i # Save the original data as additional property regardless of the display type
                yitem.inddevice  = ndev # Save the original data as additional property regardless of the display type
                #self.datatable.setItem(numintervals+1,0,nitem)
                # Additional information
                self.datatable.setItem(numrow,self._start_add_info_col,t1item)
                self.datatable.setItem(numrow,self._start_add_info_col+1,t2item)
                # The averaged data itself
                self.datatable.setItem(numrow,ndev+self.coloffset,yitem)
        
        self.datatable.resizeColumnsToContents()
        self.datatable.blockSignals(False)
        
    def _datatable_item_changed(self,item):
        """
        """        
        funcname = self.__class__.__name__ + '._datatable_item_changed():'
        
        print('Item changed',item.text(), item.column(), item.row())
        try:
            newdata = float(item.text())
        except:
            newdata = item.text()
        try: # This exists, if the data was calculated as an average of self.device.user interval
            rawdata    = item.rawdata
            indrawdata = item.indrawdata
            inddevice  = item.inddevice
        except:
            print('C')
            return
        
        logger.debug(funcname + 'Modifying the data_interval data and redrawing table')
        for ind,i in enumerate(self.device.data_interval[inddevice][indrawdata]['y']):
            self.device.data_interval[inddevice][indrawdata]['y'][ind] = newdata
            #i = newdata 
            
        self.update_table()

        
    def config_fitwidget(self):
        """ Fill the widgets with content according to self.device.config
        """
        self.fitwidget['refcombo'].clear()
        for i,dev in enumerate(self.device.config['devices']):
            devstr = self._get_devicestr(dev)
            self.fitwidget['refcombo'].addItem(devstr)
            
        for i,dev in enumerate(self.device.config['polyfit']['manual']):
            self.fitwidget['refcombo'].addItem(dev['name'])
            
        # Fill the fitcombo
        self.fitwidget['fitcombo'].clear()
        self.fitwidget['fitcombo'].addItem('Linear')
        self.fitwidget['fitcombo'].addItem('Polynom')
        self.fitwidget['fitcombo'].addItem('Steinhart-Hart NTC')
        self.fitwidget['fitcombo'].currentTextChanged.connect(self._fittype_changed)
        
        self._fittype_changed() # Call it to initialize the different fit types
        
    def _fittype_changed(self):
        """ Update the different fits of the calibration widget
        """
        # Init the fittable
        self.update_fittable_basis()
        try:
            self.fittypedisplay.close()
        except:
            pass
        curtext = self.fitwidget['fitcombo'].currentText()
        if(curtext == 'Linear'):
            mathText=r'$Y = a \times X$'
            self.update_fittable_linear()
            self.fitwidget['fitbutton'].clicked.connect(self.fitdata_linear)
            self.fittypedisplay = MathTextLabel(mathText)            
        elif(curtext == 'Steinhart-Hart NTC'):
            self.fitwidget['fitbutton'].clicked.connect(self.fitdata_shh)
            mathText=r'$Y^{-1} = a_0 + a_1 \times log(X) + a_2 \times log(X^2) + a_3 \times log(X^3) + a_4 \times log(X^4)$'
            self.fittypedisplay = QtWidgets.QWidget()
            layout = QtWidgets.QFormLayout(self.fittypedisplay)
            mathwidget = MathTextLabel(mathText)
            spin_order = QtWidgets.QSpinBox()
            spin_order.setRange(1, 5)
            spin_order.setValue(3)
            spin_order.valueChanged.connect(self.update_fittable_shh)
            self._poly_order = spin_order
            label_order = QtWidgets.QLabel('Fit Order')
            layout.addRow(mathwidget)
            layout.addRow(label_order,spin_order)
            self.update_fittable_shh()
            
            
        elif(curtext == 'Polynom'):
            mathText=r'$Y = a_0 + a_1 \times X + a_2 \times X^2$'
            self.fittypedisplay = MathTextLabel(mathText)            
        
        self.fitwidget['layout'].addWidget(self.fittypedisplay,2,1,1,-1)
        



        
                
    def update_fittable_shh(self):
        """ Update the table to fill in the fittdata according to a Steinhart-Hart type of fit
        """  
        order = self._poly_order.value()  
        nrows = order + 1   
        self.fitwidget['fittable'].setRowCount(nrows)
        for i in range(nrows-1):
            fititem = QtWidgets.QTableWidgetItem('a{:d}'.format(i))
            self.fitwidget['fittable'].setItem(1+i,0,fititem)
        
    def fitdata_shh(self):
        """ Here the data in self.datatable is fitted against a Steinhart-Hart type of fit typically used for NTC Thermistor
        """
        # Get all data
        order = self._poly_order.value()  
        ndevices = self.numdevices # Get the number of devices
        print('Fit',ndevices)
        if( ndevices > 0): # If we have devices
            nrec = len(self.device.data_interval[0])
            data = np.zeros((nrec,ndevices)) # Fill a numpy array
            for i in range(ndevices):
                for j in range(nrec):
                    ydata = self.datatable.item(self.headerrows + j,self.coloffset + i)
                    try:
                        ydata = float(ydata.rawdata) # TODO, here the original data can be used as well
                    except:
                        ydata = np.NaN
                        
                    print('ydata',i,j,ydata)
                    data[j,i] = ydata
                        
                    print('ydata',i,j,ydata)
                    print('data',data)
                    
            # Fit the data (linear fit)
            ntcfit = ntc()
            for i in range(ndevices):
                fit = ntcfit.fit_Steinhart_Hart(data[:,self.refsensor_deviceindex],data[:,i],cfit=order)
                #print(fit)
                if True:
                    for j in range(order):
                        fitdata = fit['P'][-j-1]
                        fitstr = "{:2.6}".format(fitdata)
                        fititem = QtWidgets.QTableWidgetItem(fitstr)
                        self.fitwidget['fittable'].setItem(1+j,self.coloffset+i,fititem)
                        self.fitwidget['fittable'].item(1,self.coloffset+i).rawdata = fitdata # Save the original as additional property
                
                
                   
        
        
    def update_fittable_linear(self):
        """ Update the table to fill in the fittdata
        """        
        fititem = QtWidgets.QTableWidgetItem('a')
        self.fitwidget['fittable'].setItem(1,0,fititem)
        
    def fitdata_linear(self):
        """ Here the data in self.datatable is read and processed according to the fit type
        """
        # Get all data
        ndevices = self.numdevices # Get the number of devices
        print('Fit',ndevices)
        if( ndevices > 0): # If we have devices
            nrec = len(self.device.data_interval[0])
            data = np.zeros((nrec,ndevices)) # Fill a numpy array
            for i in range(ndevices):
                for j in range(nrec):
                    ydata = self.datatable.item(self.headerrows + j,self.coloffset + i)
                    try:
                        ydata = float(ydata.rawdata) # TODO, here the original data can be used as well
                    except:
                        ydata = np.NaN
                        
                    print('ydata',i,j,ydata)
                    data[j,i] = ydata
                        
                    print('ydata',i,j,ydata)
                    print('data',data)
                    
            # Fit the data (linear fit)
            for i in range(ndevices):
                fit = np.nanmean(data[:,self.refsensor_deviceindex] / data[:,i])
                print('fit',fit)
                fitstr = "{:2.3f}".format(fit) # TODO, here once could choose a format
                if(self.fitwidget['fittable'].item(1,self.coloffset+i) == None):
                    fititem = QtWidgets.QTableWidgetItem('new')
                    self.fitwidget['fittable'].setItem(1,self.coloffset+i,fititem)

                self.fitwidget['fittable'].item(1,self.coloffset+i).rawdata = fit # Save the original as additional property
                self.fitwidget['fittable'].item(1,self.coloffset+i).setText(fitstr)
                     

    def update_fittable_basis(self):
        """
        """
        # Populate the fittable
        self.fitwidget['fittable'].setColumnCount(self.numcols+2)
        self.fitwidget['fittable'].setRowCount(2)
        fititem = QtWidgets.QTableWidgetItem('Coefficients')
        self.fitwidget['fittable'].setItem(0,0,fititem)
        for i in range(self.numcols):
            sensor = self.datatable.item(0,self.coloffset+i).text()
            item = QtWidgets.QTableWidgetItem(sensor)
            self.fitwidget['fittable'].setItem(0,self.coloffset+i,item)
            
            
        self.fitwidget['fittable'].resizeColumnsToContents()
     
    def reference_sensor_changed(self,reference_sensor):
        """ Is called whenever the reference sensor was changed
        """   
        # Get the column number of the reference sensor
        self.refsensor_datatableindex = -1
        funcname = 'reference_sensor_changed():'
        numcols = self.datatable.columnCount()
        refcolor = QtGui.QColor(200,200,200)
        white = QtGui.QColor(255,255,255)
        for i in range(numcols):
            item = self.datatable.item(0,i)
            if(item is not None):
                itemtext = item.text()
                if(itemtext == reference_sensor):
                    item.setBackground(refcolor)
                    self.refsensor_datatableindex = i
                    
                else:
                    item.setBackground(white)
                    
        # Loop over the fittable items
        self.refsensor_fittableindex = -1
        numcols = self.fitwidget['fittable'].columnCount()
        for i in range(numcols):
            item = self.fitwidget['fittable'].item(0,i)
            if item is not None:
                itemtext = item.text()
                if(itemtext == reference_sensor):
                    item.setBackground(refcolor)
                    self.refsensor_fittableindex = i
                else:
                    item.setBackground(white)
                    
        self.refsensor_deviceindex = -1
        for i,dev in enumerate(self.device.config['devices']):
            devstr = self._get_devicestr(dev)
            if(reference_sensor == devstr):
                self.refsensor_deviceindex = i
                #print('Refsensor deviceindex',i)
                break
        
        logger.debug(funcname + 'Refsensor deviceindex {:d}, datatableindex {:d}, fittableindex {:d}'.format(i,self.refsensor_datatableindex,self.refsensor_fittableindex))
#
#
#
#
#
class ResponsetimeWidget(QtWidgets.QWidget):
    """ The widgets helps to calculate the response time of sensors
    """
    def __init__(self,device=None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout           = QtWidgets.QGridLayout(self)
        self.device           = device
        self.plot      = pyqtgraph.PlotWidget()
        self.line      = pyqtgraph.PlotDataItem()
        self.resp_line = pyqtgraph.PlotDataItem()
        self.plot.addItem(self.line)
        self.plot.addItem(self.resp_line)
        self.datetick = True
        self.xdata = np.NaN
        self.ydata = np.NaN
        self.xresp = np.NaN
        self.yresp = np.NaN
        # Widget and UI to calculate response times
        self._calcwidget = QtWidgets.QWidget()
        self._calcbutton = QtWidgets.QPushButton('Calculate')
        self._calcbutton.clicked.connect(self._calc_and_disp_responsetime)
        self._clearbutton = QtWidgets.QPushButton('Clear')
        self._clearbutton.clicked.connect(self._clear_fit)
        self._savebutton = QtWidgets.QPushButton('Save fit')
        self._calcdatawidget = QtWidgets.QWidget() # This widget is used to display the fit data
        self._calcdatalayout = QtWidgets.QGridLayout(self._calcdatawidget)
        
        self._threshlabel = QtWidgets.QLabel('Threshold [%]:')
        self._threshline = QtWidgets.QLineEdit()
        threshtext = "{:f}".format(0.6321*100)
        self._threshline.setText(threshtext)
        self._threshline.setValidator(QtGui.QDoubleValidator())
        self._threshline.setMaxLength(4)
        self._threshline.setAlignment(QtCore.Qt.AlignRight)
        
        self._reslabel = QtWidgets.QLabel(self._create_fittext())
        self._calcdatalayout.addWidget(self._reslabel, 1, 0,1,4)
        
        
        #self._calcbutton.clicked.connect(self._update_plot)
        self._calcwidget_layout = QtWidgets.QGridLayout(self._calcwidget)
        self._calcwidget_layout.addWidget(QtWidgets.QLabel('Calculate exponential responsetime'),0,0,1,4,QtCore.Qt.AlignHCenter)    
        self._calcwidget_layout.addWidget(self._threshlabel, 1, 0)
        self._calcwidget_layout.addWidget(self._threshline, 1, 1)
        self._calcwidget_layout.addWidget(self._calcbutton,1,2)
        self._calcwidget_layout.addWidget(self._clearbutton,1,3)
        self._calcwidget_layout.addWidget(self._savebutton,1,4)
        self._calcwidget_layout.addWidget(self._calcdatawidget,2,0,1,5)        
        
        
        # Devicewidget and UI to choose the data intervals
        self.devicecombo = QtWidgets.QComboBox(self)
        for i,dev in enumerate(self.device.config['devices']):
            self.devicecombo.addItem(dev['device'])
            
        self.intervalcombo = QtWidgets.QComboBox(self)
        self.updatebutton   = QtWidgets.QPushButton('Update')
        self.updatebutton.clicked.connect(self._update_plot)
        self._devicewidget = QtWidgets.QWidget()
        self._devicewidget_layout = QtWidgets.QGridLayout(self._devicewidget)
        self._devicewidget_layout.addWidget(QtWidgets.QLabel('Device'),2,0)    
        self._devicewidget_layout.addWidget(QtWidgets.QLabel('Data interval'),2,1)    
        self._devicewidget_layout.addWidget(self.devicecombo,3,0)    
        self._devicewidget_layout.addWidget(self.intervalcombo,3,1)    
        self._devicewidget_layout.addWidget(self.updatebutton,3,2) 
                 
        
        self.layout.addWidget(self.plot,0,0,1,3)
        self.layout.addWidget(self._calcwidget,1,0,1,3)
        self.layout.addWidget(self._devicewidget,2,0,1,3)
        
        
        self.fitplots = [] # A list of misc plot items plotted to highlight the fit
        self.vlines = [] # Vertical lines to choose interval for response time
        color = standard_color_vline
        linewidth = standard_linewidth_vline
        self.vLine_interactive = pyqtgraph.InfiniteLine(angle=90, movable=False,pen = pyqtgraph.mkPen(color, width=linewidth))
        self.plot.addItem(self.vLine_interactive)
        # Get the mouse move events to draw a line
        self.viewbox = self.plot.plotItem.vb 
        self.plot.scene().sigMouseMoved.connect(self._mouseMoved)
        self.plot.scene().sigMouseClicked.connect(self._mouseClicked)
        self.user_interval = [] # x positions of the interval to be processed for the responsetime
        
        # Add random test data
        self.showtestdata = True
        self._add_test_data()
        
    def _calc_and_disp_responsetime(self):
        """ Function checks if an interval for calculation was choosen and if so calls the responsetime calculation  
        """
        for p in self.fitplots:
            self.plot.removeItem(p)
            
        self.fitplots = []
        
        nlines = len(self.vlines)
        if(nlines==2):
            thresh = np.double(self._threshline.text())/100 # Get the threshold
            tmin = self.user_interval[0]
            tmax = self.user_interval[1]
            ind = (self.xdata > tmin) & (self.xdata <= tmax)
            self.xresp = self.xdata[ind]
            self.yresp = self.ydata[ind]
            color = standard_color
            linewidth = 3 
            
            self.resp_line.setData(x=self.xresp,y=self.yresp,pen = pyqtgraph.mkPen(color, width=linewidth))
            fit = self.calc_responsetime(self.xresp,self.yresp,thresh=thresh)
            # Plot the fit
            line1 = pyqtgraph.PlotDataItem([fit['xresp']],[fit['yresp']], pen =(0, 0, 200), symbolBrush =(0, 0, 200), symbolPen ='w', symbol ='o', symbolSize = 14) 
            self.fitplots.append(line1)
            self.plot.addItem(line1) 
            
            line1 = pyqtgraph.PlotDataItem([fit['x0']],[fit['y0']], pen =(200, 200, 200), symbolBrush =(200, 200, 200), symbolPen ='w', symbol ='o', symbolSize = 14) 
            self.fitplots.append(line1)
            self.plot.addItem(line1) 
            
            line1 = pyqtgraph.PlotDataItem([fit['x1']],[fit['y1']], pen =(100, 100, 100), symbolBrush =(100, 100, 100), symbolPen ='w', symbol ='o', symbolSize = 14) 
            self.fitplots.append(line1)
            self.plot.addItem(line1)
            # Update the response time widget
            self._reslabel.setText(self._create_fittext(fit))
        else:
            logger.warning('Choose an interval for the calculation of the responsetime')
    
    def _create_fittext(self,fit=None):
        if(fit == None):
            return 'Tau [s]: X, X Tau: X, Y Tau: X\nX0: X, X1: X, Y0: X, Y1: X'
        else:
            return 'Tau [s]: {:f}, X Tau: {:f}, Y Tau: {:f}\nyoutX0: {:f}, X1: {:f}, Y0: {:f}, Y1: {:f}'.format(fit['dtresp'],fit['xresp'],fit['yresp'],fit['x0'],fit['x1'],fit['y0'],fit['y1'])
                   
    def _clear_plot(self):
        xdata = []
        ydata = []
        self.line.setData(x=xdata,y=ydata)
        self._clear_fit()
        
    def _clear_fit(self):
        xdata = []
        ydata = []
        self.resp_line.setData(x=xdata,y=ydata)
        for p in self.fitplots:
            self.plot.removeItem(p)
            
        self.fitplots = []
        
    def calc_responsetime(self,x,y,thresh = 0.6321):
        """ Calculates the responsetime of self.xdata, self.ydata
        
        """
        #thresh = 0.6321 # 1-1/exp(1)
    
        x0 = x[0]
        x1 = x[-1]
        y0 = y[0]
        y1 = y[-1]
        dy = (y1 - y0)
    
        ymax = max([y0,y1])
    
        xint = np.NaN
        for i in range(1,len(y)):
            if(y0 > y1):
                yint = (ymax * (1-thresh))
            else:
                yint = (ymax * thresh)
                
            foundthresh0 = (y[i-1] < yint) and (y[i] >= yint)
            foundthresh1 = (y[i-1] > yint) and (y[i] <= yint)
            if(foundthresh0 or foundthresh1):
                xthresh = x[i-1:i+1]
                ythresh = y[i-1:i+1]
                
                xint = np.interp(yint,ythresh,xthresh) # Interpolate the threshold time
                break
    
        dtresp = xint - x0
        fit = {'dtresp':dtresp,'xresp':xint,'yresp':yint,'x0':x0,'y0':y0,'x1':x1,'y1':y1,'x':x,'y':y}
        return fit
        

        
    def _add_test_data(self):
        """ Adds random data for testing purposes 
        """

        tau = np.random.rand(1)[0]
        amp = np.random.rand(1)[0] * 10
        posneg = np.random.rand(1)[0] - 0.5
        x = np.arange(time.time(),time.time()+10,.001)
        x = x - x[0]
        if posneg>0:
            y = np.exp(-x/tau)
        else:
            y = 1 - np.exp(-x/tau)

        y = y * amp + 0.01*amp * np.random.rand(len(y))
        # The whole dataset
        self.xdata = x
        self.ydata = y
        # The data used for the response calculation
        self.xresp = x
        self.yresp = y
        
        self._update_plot()
        pass
    
    def _mouseMoved(self,evt):
        """Function if mouse has been moved in a pyqtgraph
        """
        pos = (evt.x(),evt.y())
        mousePoint = self.viewbox.mapSceneToView(evt)
        self._mouse_moved_proc(mousePoint.x(), mousePoint.y())
         
    def _mouseClicked(self,evt):
        """ If the mouse was clicked in this pyqtgraph widget
        """
        
        if evt.button() == QtCore.Qt.LeftButton:
            col = pyqtgraph.mkPen(0.5,width=3)
            colsymbol = pyqtgraph.mkPen(color=QtGui.QColor(150,150,150),width=4)         
            print('Clicked: ' + str(evt.scenePos()))
            mousePoint = self.viewbox.mapSceneToView(evt.scenePos())
            x = mousePoint.x()
            self.user_interval.append(x)
            while(len(self.user_interval)>2):
                self.user_interval.pop(0)
                
            self._mouse_clicked_proc() 
            
    def _mouse_moved_proc(self,x,y):
        """ Function is process the mouse movement, this can be local or by a signal call from another widget 
        """
        if True:
            print('x',x)
            self.vLine_interactive.setPos(x)
            
            
    def _mouse_clicked_proc(self):
        """ Function that is called by signals from other widgets if a mouse was clicked
        """
        print('User Interval',self.user_interval)
        for vline in self.vlines:
            self.plot.removeItem(vline)
            
        self.vlines = []
        for x in self.user_interval:
            vLine = pyqtgraph.InfiniteLine(angle=90, movable=False)
            vLine.setPos(x)       
            self.plot.addItem(vLine, ignoreBounds=True)
            self.vlines.append(vLine)      
        
    def _update_data_intervals(self):
        """ Function checks the self.device.data_intervals list and updates the items of self.intervalcombo
        """
        numdisp = 0
        print('Updating intervals')
        nintervals = len(self.device.data_interval[numdisp])
        self.intervalcombo.clear()
        for i in range(nintervals):
            self.intervalcombo.addItem(str(i))
            
    def _save_fit(self,fname,fit,filetype='xlsx'):
        """ Save the fit into a file
        """
        fname_xlsx = fname
        if True:
            # Create an new Excel file and add a worksheet.
            workbook = xlsxwriter.Workbook(fname_xlsx)
            worksheet = workbook.add_worksheet()
            worksheet.write(3, 0, 123.456)
            workbook.close()
        
            
    def _update_plot(self):
        """ Redraws the plot
        """
        numdevice = self.devicecombo.currentIndex()
        devname = self.devicecombo.currentText()
        numinterval = self.intervalcombo.currentIndex()
        self._clear_plot()
        
        print('numinterval',numinterval)
        if(numinterval>=0):
            xdata = self.device.data_interval[numdevice][numinterval]['x']
            ydata = self.device.data_interval[numdevice][numinterval]['y']
            print('numinterval',numinterval,'numdevice',numdevice)
            print('xdata',xdata)
            color = standard_color
            linewidth = 1
            # Save the data for later processing
            self.xdata = xdata
            self.ydata = ydata
            self.line.setData(x=xdata,y=ydata,pen = pyqtgraph.mkPen(color, width=linewidth))
            if(self.datetick):
                axis = pyqtgraph.DateAxisItem(orientation='bottom')
                self.plot.setAxisItems({"bottom": axis})
                
            self.plot.setXRange(min(self.xdata),max(self.xdata))
            self.user_interval.append(xdata[0])
            self.user_interval.append(xdata[-1])
            while(len(self.user_interval)>2):
                self.user_interval.pop(0)
                
            self._mouse_clicked_proc()
        elif(self.showtestdata):
            self.showtestdata = False
            color = standard_color
            linewidth = 1
            self.line.setData(x=self.xdata,y=self.ydata,pen = pyqtgraph.mkPen(color, width=linewidth))
            axis = pyqtgraph.DateAxisItem(orientation='bottom')
            self.plot.setAxisItems({"bottom": axis})
            self.plot.setXRange(min(self.xdata),max(self.xdata))
              
            self.user_interval.append(self.xdata[0])
            self.user_interval.append(self.xdata[-1])
            while(len(self.user_interval)>2):
                self.user_interval.pop(0)
                
            self._mouse_clicked_proc()   
        else:
            logger.warning('No data available')



class Device():
    def __init__(self,dataqueue=None,comqueue=None,datainqueue=None,config = {}):
        """
        """
        self.publish     = False # publishes data, a typical sensor is doing this
        self.subscribe   = True  # subscribing data, a typical datalogger is doing this
        self.datainqueue = datainqueue
        self.dataqueue   = dataqueue        
        self.comqueue    = comqueue
        self.config      = config # Please note that this is typically a placeholder, the config structure will be written by redvypr and the yaml
        self.create_standard_config()
        
        # The mininum and maximum times, used for making the time axis the same between different sensors
        self.tmin = []
        self.tmax = []
        
        self.tmin_old = 0#np.NaN
        self.tmax_old = 0
        
        self.dt_allowoff = 20 # The offset allowed before a new range is used
        
        # Variable to save interval for averaging/cutting by user choice
        self.user_interval = []
        self.data_interval = []
        
        # The units of the different devices
        self.units = []
        
        # How and if to synchronize the different X-Axes? 0: None, 1: With one Axes, 2: Last dt
        self._xsync = 0
        self._xsync_dt = 60
        
    def finalize_init(self):
        """ Function is called when the initialization of the redvypr device is completed
        """ 
        
        if True:
            try:
                self.config['devices']
            except:
                self.config['devices'] = [] 
                      
        if False:
            # Check if config has necessary entries
            try:
                self.config['polyfit']
            except:
                self.config['polyfit'] = {}
            
        if 'polyfit' in self.config.keys():
            try:
                self.config['polyfit']['manual']
            except:
                self.config['polyfit']['manual'] = []
                
            try:
                self.config['polyfit']['comments']
            except:
                self.config['polyfit']['comments'] = []
                
                           
            try:
                self.config['polyfit']['headers']
            except:
                self.config['polyfit']['headers'] = []
                
        
    def create_standard_config(self):
        """
        """
        
        try:
            self.config['devices']
        except:
            self.config['devices'] = []
            

    def start(self):
        start(self.datainqueue,self.dataqueue,self.comqueue)
        
    def get_trange(self):
        """ Create a x axis range for
        """
        tmin = np.nanmin(self.tmin)# - self.dt_allowoff
        tmax = np.nanmax(self.tmax)# + self.dt_allowoff
        #print(self.tmax,self.tmax_old)
        if((tmin - self.tmin_old) > self.dt_allowoff):
            self.tmin_old = tmin
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

            
#
#
#
#
#
#
class initDeviceWidget(QtWidgets.QWidget):
    device_start = QtCore.pyqtSignal(Device)
    device_stop = QtCore.pyqtSignal(Device)            
    connect      = QtCore.pyqtSignal(Device) # Signal requesting a connect of the datainqueue with available dataoutqueues of other sensors
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QFormLayout(self)
        self.device   = device        
        self.label    = QtWidgets.QLabel("Rawdatadisplay setup")
        self.conbtn = QtWidgets.QPushButton("Connect logger to devices")
        self.conbtn.clicked.connect(self.con_clicked)        
        
        self.startbtn = QtWidgets.QPushButton("Start logging")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)
        self.loadbtn = QtWidgets.QPushButton("Load calibration")
        self.loadbtn.clicked.connect(self.load_data)
        self.savebtn = QtWidgets.QPushButton('Save calibration')
        self.savebtn.clicked.connect(self.savedata)        
        layout.addRow(self.label)        
        layout.addRow(self.conbtn)
        layout.addRow(self.loadbtn)
        layout.addRow(self.savebtn)
        layout.addRow(self.startbtn)
        
    def load_data(self):
        """
        """
        funcname = self.__class__.__name__ + 'load_data():'
        fname_open = QtWidgets.QFileDialog.getOpenFileName(self, 'Open file', '',"YAML files (*.yaml);; All files (*)")
        print('fname',fname_open)
        fname = fname_open[0]
        with open(fname, 'r') as yfile:
            data_yaml = yaml.safe_load(yfile)
        
        try:
            data_yaml['config']
        except Exception as e:
            logger.warning(funcname + ' No configuration found in yaml, not valid')
            return
        
        try:
            data_yaml['data_interval']
        except Exception as e:
            logger.warning(funcname + ' No data_interval found in yaml, not valid')
            return
        
        # Stop the device first
        self.device_stop.emit(self.device)
        #device = self.redvyprdevicelistentry['device']
        device = self.device
        device.config = data_yaml['config']
        
        # Write the config to update the widgets
        displaywidget = self.redvyprdevicelistentry['displaywidget']
        displaywidget.update_widgets()
        device.data_interval = data_yaml['data_interval']
        if('polyfit' in device.config.keys()):
            logger.debug(funcname + 'Updating polyfit widget')
            displaywidget.widgets['polyfit'].update_table()
            
    def savedata(self):
        """ Save the data found in datatable and fittable into a file format to be choosen by the save widget
        """
        folder = QtWidgets.QFileDialog.getExistingDirectory(None, 'Choose folder to save sensor yaml files')        
        tnow       = datetime.datetime.now()
        tstr       = tnow.strftime('%Y-%m-%d_%H%M%S_')
        fname = tstr + 'polyfit.yaml'
        fname_full = folder + '/' + fname
        # Create a dictionary with the data to be saved
        device= self.device
        data_save = {}
        data_save['data_interval'] = self.device.data_interval
        data_save['config']           = self.device.config
        # Update the header  in config
        if('polyfit' in device.config.keys()):
            displaywidget = self.redvyprdevicelistentry['displaywidget']
            datatable = displaywidget.widgets['polyfit'].datatable
            ncols   = datatable.columnCount()
            nheader = displaywidget.widgets['polyfit'].headerrows
            data_units = []
            for col in range(ncols):
                try:
                    data_units.append(datatable.item(1,col).text())
                except:
                    data_units.append('')
            header = []
            for row in range(2,nheader): # Header starts in third row
                data_row = []
                for col in range(ncols):
                    try:
                        data_row.append(datatable.item(row,col).text())
                    except Exception as e:
                        print('oho',e)
                        data_row.append('')
                    
                header.append(data_row)
            #self.device.config['polyfit']['headers']
        
            data_save['config']['polyfit']['headers'] = header
            data_save['config']['polyfit']['units']   = data_units
        
        print('Saving to file {:s}'.format(fname_full))            
        with open(fname_full, 'w') as fyaml:
            yaml.dump(data_save, fyaml)
                

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
                self.startbtn.setChecked(False)
                #self.conbtn.setEnabled(True)


#
#
# The display widget
#
#
class displayDeviceWidget(QtWidgets.QWidget):
    """ Widget is a wrapper for several calibration widgets (average table, response time, ...) 
    This widget can be configured with a configuration dictionary
    Args: 
    tabwidget:
    device:
    buffersize:
    dt_update:
    """
    
    def __init__(self,dt_update = 0.25,device=None,buffersize=1000,tabwidget = None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout        = QtWidgets.QGridLayout(self)
        self.device        = device
        self.buffersizestd = buffersize
        self.plots         = []
        self.databuf       = [] # A buffer of data
        self.tabwidget     = tabwidget
        self.widgets       = {}

        self.tabwidget.addTab(self,'Data')   
        config = {'dt_update':dt_update,'last_update':time.time()}
        self.config = config
        print('Hallo',self.device.config)
        
            
        # Add buttons
        self.btn_add_interval = QtWidgets.QPushButton('Get data')
        self.btn_clear = QtWidgets.QPushButton('Clear data')
        self.check_sync = QtWidgets.QRadioButton('Sync with')
        self.check_sync.setStatusTip('All axes are synced with the choosen axes')
        self.check_sync_no = QtWidgets.QRadioButton('None')
        self.check_sync_no.setStatusTip('All axes are updated individually')
        self.check_sync_lastdt = QtWidgets.QRadioButton('Last dt')
        self.check_sync_lastdt.setStatusTip('The last dt seconds are displayed')
        self.ledit_lastdt = QtWidgets.QLineEdit()
        self.ledit_lastdt.setValidator(QtGui.QDoubleValidator())
        self.ledit_lastdt.setText('60')
        self.ledit_lastdt.textChanged[str].connect(self._xsync_changed)
        self.combo_sync = QtWidgets.QComboBox()
        self.combo_sync.currentIndexChanged.connect(self._xsync_changed)
        
        self._pub_group = QtWidgets.QButtonGroup()
        self._pub_group.addButton(self.check_sync)
        self._pub_group.addButton(self.check_sync_no)
        self._pub_group.addButton(self.check_sync_lastdt)
        self.check_sync_no.setChecked(True)
        self.check_sync.toggled.connect(self._xsync_changed)
        self.check_sync_no.toggled.connect(self._xsync_changed)
        self.check_sync_lastdt.toggled.connect(self._xsync_changed)
        # A timer for the last dt seconds update
        self._xsync_timer=QtCore.QTimer()
        self._xsync_timer.timeout.connect(self._update_plot_range)  
        self.update_widgets()
        self._xsync_changed()
        
    def _update_plot_range(self):
        """ Updates all plots with a x range, used for last dt x sync
        """
        print('Update plot range timer')
        tmax = time.time()
        tmin = tmax - self.device._xsync_dt
        self.device.tmin = tmin
        self.device.tmax = tmax
        for plot in self.plots:
            plot.update_tminmax(tmin,tmax)
            
    def _xsync_changed(self):
        """ Updates the X-Range configuration of all plots
        """
        print('Hallo')
        self._xsync_timer.stop() # Stop the dt timer
        
        # Connect tmin/max changed of sync to all the others
        config=self.device.config
        for i,config_device in enumerate(config['devices']):
            datastream_x = config_device['device'] + '(' + config_device['x'] + ',' + config_device['y'] + ')' 
            if(datastream_x == self.combo_sync.currentText()):
                print('Current datastream',datastream_x,i)
                break

        for plot in self.plots:
                # Disconnect all signals
                try:
                    plot.sig_tminmax_changed.disconnect()
                except:
                    pass   
                    
        if(self.check_sync_no.isChecked()):
            logger.debug('No X-Sync')
            self.device._xsync = 0
            return
        if(self.check_sync_lastdt.isChecked()):
            logger.debug('Last dt X-Sync')
            dt = float(self.ledit_lastdt.text())
            if(dt>5):
                dt_timeout = 2000 # Every two seconds
            else:
                dt_timeout = dt/2*1000
        
            self._xsync_timer.start(int(dt_timeout)) # Every two seconds
            #self._xsync_timer.timeout.emit()
            self.device._xsync = 2
            self.device._xsync_dt = dt
            return
        # Sync with one axis
        if(self.check_sync.isChecked()):
            logger.debug('Axes X-Sync')
            self.device._xsync = 1   
            plot = self.plots[i]
             
            if True:
                for plot2 in self.plots:
                    if(plot == plot2):
                        continue
                    else:
                        #print('Connecting signals')
                        plot.sig_tminmax_changed.connect(plot2.update_tminmax)

    def update_widgets(self):
        """ Compares self.config and widgets and add/removes plots if necessary
        """
        funcname = self.__class__.__name__ + '.update_widgets():'
        logger.debug(funcname)
        
        if 'polyfit' in self.device.config.keys(): # If the user wants to have a table
            try:
                logger.debug(funcname + 'Already having PolfitWidget')
                self.widgets['polyfit']
            except:
                logger.debug(funcname + 'Adding PolfitWidget')
                self.widgets['polyfit'] = PolyfitWidget(device = self.device)
                i1 = self.tabwidget.addTab(self.widgets['polyfit'],'Polyfit')
            
        if 'responsetime' in self.device.config.keys(): # If the user wants to have a table
            try:
                self.widgets['responsetime']
            except:
                self.widgets['responsetime'] = ResponsetimeWidget(device = self.device)
                i1 = self.tabwidget.addTab(self.widgets['responsetime'],'Responsetime')
            
            
        self.combo_sync.clear()
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
        i = 0
        self.btn_add_interval.clicked.connect(self.get_data_clicked)
        for i,config_device in enumerate(config['devices']):
            logger.debug(funcname + ': Adding device ' + str(config_device))
                                                
            plot = PlotWidget(config_device,device=self.device,numdisp=i,buffersize=self.buffersizestd)
            #self.btn_add_interval.clicked.connect(plot.get_data_clicked)
            self.btn_clear.clicked.connect(plot.clear_data)
            self.layout.addWidget(plot,i,0,1,-1)
            self.plots.append(plot)
            self.device.data_interval.append([])
            self.device.units.append({'x':'s','y':'NA'})
            datastream_x = config_device['device'] + '(' + config_device['x'] + ',' +config_device['y'] + ')' 
            self.combo_sync.addItem(datastream_x)
            
           
        # Connect all mouse moved signals
        for plot in self.plots:
            for plot2 in self.plots:
                if(plot == plot2):
                    continue
                else:
                    plot.sig_mouse_moved.connect(plot2.mouse_moved_proc)
                    #plot.sig_tminmax_changed.connect(plot2.update_tminmax)
                    plot.sig_mouse_clicked.connect(plot2.mouse_clicked_proc)
                    #plot.sig_new_user_data.connect(self.new_user_data)
         
        self.layout.addWidget(self.btn_add_interval,i+1,0,1,-1)
        self.layout.addWidget(self.btn_clear,i+2,6)
        self.layout.addWidget(QtWidgets.QLabel('Sync X-Axis'),i+2,0)
        self.layout.addWidget(self.check_sync_no,i+2,1)
        self.layout.addWidget(self.check_sync,i+2,2)
        self.layout.addWidget(self.combo_sync,i+2,3)
        self.layout.addWidget(self.check_sync_lastdt,i+2,4)
        self.layout.addWidget(self.ledit_lastdt,i+2,5)
        # Update the average data table
        
        if 'polyfit' in self.device.config.keys(): # If the user wants to have a table
            logger.debug(funcname + ': Init polyfit table ')
            self.widgets['polyfit'].update_table_header()

    
    def get_data_clicked(self):
        """ Collects data from all plots and saves it into the self.device.data_interval list
        """
        for i,plot in enumerate(self.plots):
            data = plot.get_data_clicked()
            if(data is not None):
                self.device.data_interval[i].append(data)
                
                
        if 'polyfit' in self.device.config.keys(): # If the user wants to have a table                
            self.widgets['polyfit'].update_table()
        # Update the responsetime widget with the new data            
        if 'responsetime' in self.device.config.keys(): # If the user wants to have a table
            self.widgets['responsetime']._update_data_intervals()
        
        
    def config_widget(self):
        """
        """
        self.configwidget = QtWidgets.QWidget(self)
        self.configwidget.show()
        
    def thread_status(self,status):
        """ This function is regularly called by redvypr whenever the thread is started/stopped
        """
        self.update_buttons(status['threadalive'])
        
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
                
                
