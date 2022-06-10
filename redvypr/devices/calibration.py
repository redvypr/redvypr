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
from redvypr.data_packets import device_in_data, get_keys_from_data, get_datastream, parse_devicestring
import redvypr.files as files
from redvypr.utils import configdata 
from redvypr.gui import redvypr_devicelist_widget
import xlsxwriter
import copy
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import tempsensor

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
        #print('Changed')
        axX = self.plots[0]['widget'].getAxis('bottom')
        #print('x axis range: {}'.format(axX.range)) # <------- get range of x axis
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
                        line      = line_dict['line']   # The line to plot
                        config    = line_dict['config'] # The line to plot
                        x         = line_dict['x']      # The line to plot
                        y         = line_dict['y']      # The line to plot 
                        
                        # data can be a single float or a list
                        newx = data[config['x']]
                        newy = data[config['y']]
                        
                        # Try to get the unit
                        # First via the configuration
                        try:
                            unitstry = config['unit']
                            self.device.units[self.numdisp] = {'x':'time','y':unitstry}
                        except:
                            unitstry = None

                        if(unitstry == None):
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
    def __init__(self,device=None,displaywidget = None):
        funcname = __name__ + '.init()'
        super(QtWidgets.QWidget, self).__init__()
        self.layout           = QtWidgets.QGridLayout(self)
        self.device           = device
        self.datatable        = QtWidgets.QTableWidget()
        self.datatable.horizontalHeader().hide()
        self.datatable.verticalHeader().hide()
        self.datatable_widget = QtWidgets.QWidget()
        self.datatable.itemChanged.connect(self._datatable_item_changed)
        self.displaywidget = displaywidget # The parent widget
        self.headerrows_basis       = 4
        self.headerrows             = self.headerrows_basis
        self.coloffset              = 1
        self.num_additional_columns = 3 # comment/tstart/tend 
        self._row_units  = 1
        self._row_type   = 2
        self._row_serial = 3      
        # Buttons to add/remove datapoints
        self.init_widgets()
        print('Hallo1')
        self.update_table_header()
        print('Hallo24')
        self.update_table()
        print('Hallo2')
        
    def init_widgets(self):
        """ Create all widgets and put them in a layout
        """
        print('Hallo19')
        self.btnlayout = QtWidgets.QGridLayout(self.datatable_widget)
        
        #self.layout.addLayout(self.btnlayout,1,0,1,4)
        self.layout.addWidget(self.datatable_widget,1,0,1,4)
        print('Hallo200')
        self.btn_addhdr = QtWidgets.QPushButton('Add header')
        self.btn_addhdr.clicked.connect(self.add_headerrow)
        self.btn_addrow = QtWidgets.QPushButton('Add row')
        self.btn_addrow.clicked.connect(self.add_row)
        self.btn_remrow = QtWidgets.QPushButton('Rem row(s)')
        self.btn_remrow.clicked.connect(self.rem_row)
        self.btn_autocal = QtWidgets.QPushButton('Autocal')
        self.btn_autocal.clicked.connect(self.autocal)        
        self.label_strformat = QtWidgets.QPushButton('Number format')
        self.lineedit_strformat = QtWidgets.QLineEdit('{:2.4f}')
        self.tabledisplay_combo = QtWidgets.QComboBox()
        self.tabledisplay_combo.addItems(['Mean','Fit','Diff'])
        self.tabledisplay_combo.currentTextChanged.connect(self.update_table)
        self.btnlayout.addWidget(self.datatable,1,0,1,7)
        self.btnlayout.addWidget(self.btn_addhdr,2,0)
        self.btnlayout.addWidget(self.btn_addrow,2,1)
        self.btnlayout.addWidget(self.btn_remrow,2,2)
        self.btnlayout.addWidget(self.btn_autocal,2,3)        
        self.btnlayout.addWidget(self.label_strformat,2,4)
        self.btnlayout.addWidget(self.lineedit_strformat,2,5)
        self.btnlayout.addWidget(self.tabledisplay_combo,2,6)
        datalabel = QtWidgets.QLabel('Data')
        datalabel.setAlignment(QtCore.Qt.AlignCenter)
        datalabel.setStyleSheet("font-weight: bold")
        self.btnlayout.addWidget(datalabel,0,0,1,3)
        
        # Initialize the fitwidgets
        self.fitwidget = {}
        self.fitwidget['widget'] = QtWidgets.QWidget(self)
        self.fitwidget['fitbutton'] = QtWidgets.QPushButton('Fit data')
        self.fitwidget['plotbutton'] = QtWidgets.QPushButton('Plot fit')
        self.fitwidget['savebutton'] = QtWidgets.QPushButton('Save fit')
        self.fitwidget['savebutton'].clicked.connect(self.save_fit)

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
        
        self.fitwidget['layout'].addWidget(self.fitwidget['fittable'],3,0,1,3)   
        self.fitwidget['layout'].addWidget(QtWidgets.QLabel('Reference Sensor'),4,0)
        self.fitwidget['layout'].addWidget(self.fitwidget['refcombo'],4,1)
        self.fitwidget['layout'].addWidget(self.fitwidget['fitbutton'],5,0,1,1)
        self.fitwidget['layout'].addWidget(self.fitwidget['plotbutton'],5,1,1,1)        
        self.fitwidget['layout'].addWidget(self.fitwidget['savebutton'],5,2,1,1)
        
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

        if('autocal' in self.device.config.keys()):
           self.autocal()
           
           
    def save_fit(self):
        """ Saves the fit in files
        """
        funcname = self.__class__.__name__ + '.savefit()'
        print(funcname)

    def autocal(self):
        """ Automatic calibration functionality
        """
        funcname = self.__class__.__name__ + '.autocal()'
        logger.info(funcname)
        # Check if we have a config, if not create one
        try:
            self.device.config['autocal']
        except:
            self.device.config['autocal'] = {}

        try:
            self.device.config['autocal']['dt_sampling']
        except:
            self.device.config['autocal']['dt_sampling'] = 30

        try:
            self.device.config['autocal']['set']
        except:
            self.device.config['autocal']['set'] = [1,2,3,4,5]

        try:
            self.device.config['autocal']['time']
        except:
            self.device.config['autocal']['time'] = [10,15,30,40,5]            
        
        self._autocalw = QtWidgets.QWidget()
        l=QtWidgets.QFormLayout(self._autocalw)
        self._autocaldisplay=QtWidgets.QLabel('Time')
        self._autocalstart    =QtWidgets.QPushButton('Start')
        self._autocalstart.clicked.connect(self._autocal_start)
        self._autocalstartline=QtWidgets.QSpinBox()
        self._autocalstartline.setValue(1)
        self._autocalbtnrows  =QtWidgets.QPushButton('Set rows')
        self._autocalbtnrows.clicked.connect(self._autocal_setrows)
        self._autocalspinrows =QtWidgets.QSpinBox()
        self._autocalspinrows.setMinimum(1)
        self._autocalspinrows.setMaximum(1000)                
        self._autocalspinrows.setValue(len(self.device.config['autocal']['time']))

        self._autocaldt  =QtWidgets.QLabel('Delta t [s] sampling')
        self._autocaldtspin =QtWidgets.QSpinBox()
        self._autocaldtspin.setMinimum(1)
        self._autocaldtspin.setMaximum(1000)                
        self._autocaldtspin.setValue(self.device.config['autocal']['dt_sampling'])
        
        self._autocaltimer=QtCore.QTimer()
        self._autocaltimer.timeout.connect(self._autocal_timeout)


        # Table with the time data
        self._autocaltable = QtWidgets.QTableWidget()


        self._autocaltable.setColumnCount(2)
        self._autocaltable.setHorizontalHeaderLabels(['Set', 'Time [s]'])
        self._autocal_setrows()        


        
        l.addRow(self._autocaldisplay)
        l.addRow(self._autocalstart,self._autocalstartline)
        l.addRow(self._autocaldt,self._autocaldtspin)                
        l.addRow(self._autocalbtnrows,self._autocalspinrows)        
        l.addRow(self._autocaltable)
        
        self._autocalw.show()

    def _autocal_start(self):
        funcname       = self.__class__.__name__ + '._autocal_start()'
        logger.debug(funcname)
        if(self.sender().text() == 'Start'):

            currentrow     = self._autocalstartline.value()
            self._autocal_currentrow = currentrow - 1
            self._autocal_counter = 0 # Causes an immidiate row change
            self._autocaltimer.start(1000)
            self._autocaltimer.timeout.emit()
            self.sender().setText('Stop')

        elif(self.sender().text() == 'Stop'):
            self.sender().setText('Start')            
            self._autocaltimer.stop()
            
    def _autocal_setrows(self):
        rows = self._autocalspinrows.value()
        self._autocaltable.setRowCount(rows)
        self._autocalstartline.setMaximum(rows)

        # Fill the table
        t = self.device.config['autocal']['time']
        s = self.device.config['autocal']['set']
        
        for i in range(len(t)):
            print(i,rows)
            if(i < rows):
                item0 = QtWidgets.QTableWidgetItem(str(s[i]))                
                item1 = QtWidgets.QTableWidgetItem(str(t[i]))
                self._autocaltable.setItem(i,0,item0)
                self._autocaltable.setItem(i,1,item1)                


    def _autocal_timeout(self):
        """ Timeout of the calibration
        """
        refcolor = QtGui.QColor(200,200,200)
        white = QtGui.QColor(255,255,255)        
        funcname = self.__class__.__name__ + '._autocal_timeout()'
        rows = self._autocaltable.rowCount()
        logger.info(funcname)
        print('Timeout')

        self._autocal_counter -= 1
        # New row, sample data, send command to reference device and change row
        if(self._autocal_counter <= 0):
            print('Timeout!',self._autocal_currentrow)
            if(self._autocal_currentrow > 0): # Dont sample the first 
                # Get the dataself.device.config['autocal']['time']
                tsample1 = time.time()
                tsample0 = tsample1 - self._autocaldtspin.value()
                print('Sampling',tsample0,tsample1)
                self.displaywidget.sample_interval(tsample0,tsample1)
            if True:
                # Set the value of the reference device
                item = self._autocaltable.item(self._autocal_currentrow,0)
                try:
                    varset = float(item.text())
                except:
                    varset = None

                if(varset is not None):
                    dev = self.device.config['devices'][self.refsensor_deviceindex]#['device']
                    devdict = parse_devicestring(dev['device'])
                    logger.info(funcname + ' Sending command to device {:s} to set value to {:f}'.format(dev['device'],varset))
                    self.device.redvypr.send_command(devdict['devicename'],{'set':varset})
                else:
                    logger.warning(funcname + ' No value found to send for a command')
                
            # Prepare everything for the next row ...
            self._autocal_currentrow += 1
            self._autocalstartline.setValue(self._autocal_currentrow)
            for i in range(rows):
                item = self._autocaltable.item(i,1)
                if(item is not None):
                    item.setBackground(white)

            # Counter item
            item = self._autocaltable.item(self._autocal_currentrow - 1,1)
            if(item is not None):
                item.setBackground(refcolor)
            else:
                item = QtWidgets.QTableWidgetItem('')
                item.setBackground(refcolor)
                self._autocaltable.setItem(self._autocal_currentrow - 1,1,item)
                
            try:
                self._autocal_currenttimeout = int(item.text())
            except:
                self._autocal_currenttimeout = 2

            self._autocal_counter = self._autocal_currenttimeout


            
        self._autocaldisplay.setText('{:d} s'.format(self._autocal_counter))
        logger.debug(funcname + ' Row: {:d}, timeout {:d},counter {:d}'.format(self._autocal_currentrow,self._autocal_currenttimeout,self._autocal_counter))
        if(self._autocal_currentrow > rows):
            self._autocaltimer.stop()
            self._autocaldisplay.setText('Done')
            self._autocalstart.setText('Start')
            
        
    def plot_fit(self):
        """ Plots the original data together with the fit 
        """
        funcname = self.__class__.__name__ + 'plot_fit()'
        self._plot_widget = QtWidgets.QWidget()
        l=QtWidgets.QFormLayout(self._plot_widget)
        l.setContentsMargins(0,0,0,0)
        r,g,b,a=self.palette().base().color().getRgbF()
        self._plot_figure=Figure(edgecolor=(r,g,b), facecolor=(r,g,b))
        self._plot_canvas=FigureCanvas(self._plot_figure)
        l.addRow(self._plot_canvas)
        
        # Add combo box
        self._plot_combo_y = QtWidgets.QComboBox()
        for i,dev in enumerate(self.device.config['devices']):
            devstr = self._get_devicestr(dev)
            self._plot_combo_y.addItem(devstr)
            
        self._plot_combo_y.currentIndexChanged.connect(self._get_plot_index)
        
        l.addRow(self._plot_canvas)
        l.addRow(self._plot_combo_y)
        
        self._plot_figure.clear()
        self._index_plot = 0
        self._ax_data = self._plot_figure.add_subplot(211) # The original data 
        self._ax_diff = self._plot_figure.add_subplot(212) # The difference between the fit and the data
        self._update_plotfit_data()
        self._plot_widget.show()
        
    def _update_plotfit_data(self):
        """ Updates the plot fit data with current plot index
        """
        data = self.get_data()
        fitdata = self.get_data(datatype='fit')
        index_plot = 0
        self._ax_data.clear()
        self._ax_diff.clear()
        x = data[:,self.refsensor_deviceindex]
        y = data[:,self._index_plot]
        
        xfit  = fitdata[:,self.refsensor_deviceindex]
        yfit  = fitdata[:,self._index_plot]
        ydiff = fitdata[:,self._index_plot] - fitdata[:,self.refsensor_deviceindex]
        print('xfit',xfit,'yfit',yfit)
        self._ax_data.plot(x,y,'+k')
        self._ax_diff.plot(xfit,ydiff,'or')
        self._plot_canvas.draw()
        
        
    def _get_plot_index(self):
        """ Gets the index of the sensor to be plotted
        """
        self._index_plot = self._plot_combo_y.currentIndex()
        self._update_plotfit_data()
        
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
        self.datatable.blockSignals(True)
        print('Config',self.device.config['polyfit'])
        numcols = len(self.device.config['devices'])
        try:
            numcols+= len(self.device.config['polyfit']['manual'])
        except:
            pass
            
        try:
            numcols += len(self.device.config['polyfit']['comments'])
        except:
            pass
        self.numdevices = len(self.device.config['devices']) + len(self.device.config['polyfit']['manual'])
        self.numcols = numcols
        self.datatable.setColumnCount(numcols+1 + self.num_additional_columns)
        self.headerrows = len(self.device.config['polyfit']['headers']) + self.headerrows_basis
        self.datatable.setRowCount(self.headerrows)
        
        # Add the custom headers bloew the standard headers
        print('Updating header',len(self.device.config['polyfit']['headers']))
        for j,header in enumerate(self.device.config['polyfit']['headers']):
            headerrow = self.headerrows_basis + j
            # Check if
            if(type(header) == str):
                item = QtWidgets.QTableWidgetItem(header)
                self.datatable.setItem(headerrow,0,item)
            else: # A List with headername and contents
                for ih,h in enumerate(header):
                    item = QtWidgets.QTableWidgetItem(str(h))
                    self.datatable.setItem(headerrow,ih,item)
            
            
        
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
            self.datatable.setItem(self._row_units,colnum,item)
            
            
            
        colnum = colnum + 1
        # Add additional information
        self._start_add_info_col = colnum
        item = QtWidgets.QTableWidgetItem('Comment')
        self.datatable.setItem(0,colnum,item)
        colnum = colnum + 1
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
            self.datatable.setItem(1,self._start_add_info_col+1,item)
            item = QtWidgets.QTableWidgetItem(xunit)
            self.datatable.setItem(1,self._start_add_info_col+2,item)
            
            # Add header description
            item = QtWidgets.QTableWidgetItem('Device')
            self.datatable.setItem(0,0,item)
            
            
            # Add device/sensor type
            item = QtWidgets.QTableWidgetItem('Type')
            self.datatable.setItem(self._row_type,0,item)
            sensortype = []
            for i,dev in enumerate(self.device.config['devices']):
                try:
                    sensortype.append(dev['type'])
                except:
                    sensortype.append('')
                    
            for ih,h in enumerate(sensortype):
                item = QtWidgets.QTableWidgetItem(str(h))
                devcol = self._get_devicecolumn(ih)
                self.datatable.setItem(self._row_type,devcol,item)
            
            # Add serialnumbers
            item = QtWidgets.QTableWidgetItem('Serialnumber')
            self.datatable.setItem(self._row_serial,0,item)
            serial = []
            for i,dev in enumerate(self.device.config['devices']):
                try:
                    serial.append(dev['serialnumber'])
                except:
                    serial.append('')

            for ih,h in enumerate(serial):
                item = QtWidgets.QTableWidgetItem(str(h))
                devcol = self._get_devicecolumn(ih)
                self.datatable.setItem(self._row_serial,devcol,item)
                
            # Add Units
            item = QtWidgets.QTableWidgetItem('Unit')
            self.datatable.setItem(self._row_units,0,item)
            units = []
            for i,dev in enumerate(self.device.config['devices']):
                try:
                    units.append(dev['unit'])
                except:
                    units.append('')

            for ih,h in enumerate(units):
                item = QtWidgets.QTableWidgetItem(str(h))
                devcol = self._get_devicecolumn(ih)
                self.datatable.setItem(self._row_units,devcol,item)
                self.device.units[ih]['y'] = str(h)
            
            if True:
                # This is done to call reference sensor_changed for the first time
                reference_sensor = self.fitwidget['refcombo'].currentText()
                # update the reference sensor
                self.reference_sensor_changed(reference_sensor)
            
            
        # Add comments (if available)
        try: 
            comments = self.device.config['polyfit']['comments']
        except:
            comments = []
            
        if(len(comments) > self.headerrows - 1):
            self.datatable.setRowCount(len(comments)-1)
            
        for i,c in enumerate(comments):
            item = QtWidgets.QTableWidgetItem(str(c))
            self.datatable.setItem(self._row_serial,self._start_add_info_col,item)
            
        self.datatable.resizeColumnsToContents()
        self.datatable.blockSignals(False)
        
    def update_fitwidgets(self):
        """ Update the fitwidgets according to the config
        """
        funcname = self.__class__.__name__ + '.update_fitwidgets():'
        
        
        refcombo = self.fitwidget['refcombo']
        fitcombo = self.fitwidget['fitcombo']
        fittype = fitcombo.currentText()
        refsensor = refcombo.currentText()
        
        # Fittype
        try:
            fittype = self.device.config['polyfit']['fittype']
            for i in range(fitcombo.count()):
                fittype_tmp = fitcombo.itemText(i)
                print(fittype,fittype_tmp,fittype_tmp == fittype)
                if(fittype_tmp == fittype):
                    fitcombo.setCurrentIndex(i)
                    break
            
        except Exception as e:
            logger.info(funcname + str(e))
            
        # Reference sensor
        try:
            reftype = self.device.config['polyfit']['refsensor']
            print('Found refsensor',reftype)
            for i in range(refcombo.count()):
                reftype_tmp = refcombo.itemText(i)
                if(reftype_tmp == reftype):
                    refcombo.setCurrentIndex(i)
                    break
            
        except Exception as e:
            logger.info(funcname + str(e))
    
    
    def average_data(self):
        """ Averages the raw data and saves it
        """
        funcname = self.__class__.__name__ + '.average_data():'
        logger.debug(funcname)
        try:
            numintervals = len(self.device.data_interval[0])
            numdevices   = len(self.device.data_interval)
        except Exception as e:
            logger.warning(funcname + ' No devices/data intervals found: {:s}'.format(e))
            return
        
        self.device.data_xmean = []
        self.device.data_ymean = []
        
        for ndev in range(numdevices):
            self.device.data_xmean.append([])
            self.device.data_ymean.append([])
            for i in range(numintervals):
                xdata = self.device.data_interval[ndev][i]['x']
                ydata = self.device.data_interval[ndev][i]['y']
                xmean = np.nanmean(xdata)
                ymean = np.nanmean(ydata)
                self.device.data_xmean[-1].append(xmean)
                self.device.data_ymean[-1].append(ymean)
        
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
            numdevices   = len(self.device.data_interval)
            logger.debug(funcname + ' Numintervals {:d} numdevices {:d}'.format(numintervals,numdevices))
        except Exception as e:
            logger.warning(funcname + ' No devices/data intervals found: {:s}'.format(str(e)))
            self.datatable.blockSignals(False)
            return
        
        self.datatable.setRowCount(numintervals + self.headerrows)
        
        self.average_data()
        # What shall we display?
        display = self.tabledisplay_combo.currentText()
        logger.debug(funcname + 'Displaying {:s}'.format(display))
        for ndev in range(numdevices):
            try:
                unitstrmean = self.device.config['devices'][ndev]['unit']
            except Exception as e:
                unitstrmean = 'NA'
                
            try:
                unitstrfit = self.device.fitdata[ndev]['device']['unit_fit']
            except Exception as e:
                unitstrfit = 'NA'
                    
            if(display == 'Fit'):
                unitstr = unitstrfit
            elif(display == 'Diff'):
                unitstr = unitstrmean
            else:
                unitstr = unitstrmean
            # Unitstr
            xunit = self.device.units[ndev]['x']
            #yunit = self.device.units[ndev]['y']
            xunititem = QtWidgets.QTableWidgetItem(xunit)
            yunititem = QtWidgets.QTableWidgetItem(unitstr)
            devcol = self._get_devicecolumn(ndev)
            self.datatable.setItem(self._row_units,devcol,yunititem)
            for i in range(numintervals):
                numrow = i + self.headerrows
                numrowsnew = self.datatable.rowCount() - self.headerrows
                xuser = self.device.data_interval[ndev][i]['xuser']
                #xmean = self.device.data_xmean[ndev][i]
                ymean = self.device.data_ymean[ndev][i]
                try:
                    yfit = self.device.fitdata_converted[ndev][i]
                    yref = self.device.fit_referencedata[i] # The referencedata 
                except:
                    yfit = np.NaN
                    yref = np.NaN
                    
                if(display == 'Fit'):
                    ydisplay = yfit
                elif(display == 'Diff'):
                    ydisplay = yfit - yref
                    print('Diff',yfit,yref,ydisplay)
                else:
                    ydisplay = ymean
                    
                t1str = datetime.datetime.fromtimestamp(xuser[0]).strftime('%d.%m.%Y %H:%M:%S')
                t2str = datetime.datetime.fromtimestamp(xuser[1]).strftime('%d.%m.%Y %H:%M:%S')
                strformat = self.lineedit_strformat.text()
                #strformat = '{:2.2f}'
                nitem  = QtWidgets.QTableWidgetItem(str(numintervals))
                t1item = QtWidgets.QTableWidgetItem(t1str)
                t2item = QtWidgets.QTableWidgetItem(t2str)
                #xitem  = QtWidgets.QTableWidgetItem(strformat.format(xmean))
                yitem  = QtWidgets.QTableWidgetItem(strformat.format(ydisplay))
                yitem.rawdata    = ymean # Save the original data as additional property regardless of the display type
                yitem.indrawdata = i # Save the original data as additional property regardless of the display type
                yitem.inddevice  = ndev # Save the original data as additional property regardless of the display type
                # Additional information
                self.datatable.setItem(numrow,self._start_add_info_col+1,t1item)
                self.datatable.setItem(numrow,self._start_add_info_col+2,t2item)
                # The averaged data itself
                
                self.datatable.setItem(numrow,devcol,yitem)
        
        self.datatable.resizeColumnsToContents()
        self.datatable.blockSignals(False)
        
    def _get_devicecolumn(self,ndev,inverse=False):
        """ Returns the column of the device with the index ndev, 
        if inverse=True returns the device index for the given table column
        """
        if inverse:
            return ndev-self.coloffset
        else:
            return ndev+self.coloffset
        
    def _datatable_item_changed(self,item):
        """ Function is called whenever the user changes the datatable
        """        
        funcname = self.__class__.__name__ + '._datatable_item_changed():'
        
        print('Item changed',item.text(), item.column(), item.row())
        
        row = item.row()
        col = item.column()
        inddev = self._get_devicecolumn(col,inverse=True)
        if(row <= self.headerrows): # Changed in the header section
            newdata = item.text()
            if(row == self._row_units):
                print('Unit changed')
                self.device.config['devices'][inddev]['unit'] = str(newdata)
            elif(row == self._row_type):
                print('Type changed')   
                self.device.config['devices'][inddev]['type'] = str(newdata)
            elif(row == self._row_serial):
                print('Serial changed')
                self.device.config['devices'][inddev]['serialnumber'] = str(newdata)
        else: # Changed in the data section
            try:
                newdata = float(item.text())
            except:
                newdata = item.text()
            try: # This exists, if the data was calculated as an average of self.device.user interval
                rawdata    = item.rawdata
                indrawdata = item.indrawdata
                inddevice  = item.inddevice
            except:
                logger.warning(funcname + 'Could not get rawdata and indices, returning without table update')
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
        
        
    def get_data(self,datatype='mean'):
        """ Collects the averaged data or fitted data in self.datatable and returns it in an array
        """
        funcname = self.__class__.__name__ + '.get_data():'
        logger.debug(funcname)
        ndevices = self.numdevices # Get the number of devices
        print(funcname,'ndevices',ndevices)
        data = None
        if( ndevices > 0): # If we have devices
            nrec = len(self.device.data_interval[0])
            data = np.zeros((nrec,ndevices)) # Fill a numpy array
            fitdata = np.zeros((nrec,ndevices)) # Fill a numpy array
            for i in range(ndevices):
                for j in range(nrec):
                    yitem = self.datatable.item(self.headerrows + j,self.coloffset + i)
                    # The rawdata
                    try:
                        ydata = float(yitem.rawdata) # TODO, here the original data can be used as well
                    except Exception as e:
                        ydata = np.NaN
                        
                    data[j,i] = ydata
                    # The fitdata
                    try:
                        yfitdata = float(yitem.fitdata) # TODO, here the original data can be used as well
                    except Exception as e:
                        yfitdata = np.NaN
                        
                    fitdata[j,i] = yfitdata
                        
        if(datatype == 'mean'):
            return data
        elif(datatype == 'fit'):
            return fitdata
        else:
            return None
    
    
    def update_fittable_shh(self):
        """ Update the table to fill in the fittdata according to a Steinhart-Hart type of fit
        """  
        funcname = self.__class__.__name__ + '.update_fittable_shh():'
        self.fitwidget['fittable'].clear()
        self.update_fittable_basis()
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
        funcname = self.__class__.__name__ + '.fitdata_shh():'
        logger.debug(funcname)
        self.update_fittable_shh()
        order = self._poly_order.value()  

        try:
            numintervals = len(self.device.data_interval[0])
            numdevices   = len(self.device.data_interval)
        except Exception as e:
            logger.warning(funcname + ' No devices/data intervals found: {:s}'.format(e))
            return
        
        #print(funcname,numintervals,numdevices)
        #data = self.get_data()
        fitdata_converted = []
        fittype = self.fitwidget['fitcombo'].currentText()
        if True:
            # Fit the data (linear fit)
            referencedata = self.device.data_ymean[self.refsensor_deviceindex]
            self.device.fit_referencedata = referencedata
            ntcfit = ntc()
            for i in range(numdevices):
                logger.debug(funcname + 'Fitting device {:d} with order {:d}'.format(i,order))
                try:
                    self.device.fitdata[i]['device']
                except:
                    self.device.fitdata[i]['device'] = {}
                try:
                    self.device.fitdata[i]['device']['serialnumber'] = self.device.config['devices'][i]['serialnumber']
                except:
                    self.device.fitdata[i]['device']['serialnumber'] = ''
                try:
                    self.device.fitdata[i]['device']['type'] = self.device.config['devices'][i]['type']
                except:
                    self.device.fitdata[i]['device']['type'] = ''
                try:
                    self.device.fitdata[i]['device']['unit_raw'] = self.device.config['devices'][i]['unit']
                except:
                    self.device.fitdata[i]['device']['unit_raw'] = ''
                try:
                    self.device.fitdata[i]['device']['unit_fit'] = self.device.config['devices'][self.refsensor_deviceindex]['unit']
                except:
                    self.device.fitdata[i]['device']['unit_fit'] = ''
                    
                if(i is not self.refsensor_deviceindex):
                    sensordata    = self.device.data_ymean[i]
                    #print('T',data[:,self.refsensor_deviceindex])
                    print('referencedata',referencedata)
                    print('sensordata',sensordata)
                    #print(i,self.refsensor_deviceindex)
                    
                    
                    fit = tempsensor.ntc.fit_Steinhart_Hart(np.asarray(referencedata),np.asarray(sensordata),cfit=order)
                    # Convert the data
                    fitdata_tmp = tempsensor.ntc.get_T_Steinhart_Hart(sensordata,fit['P'])
                    diff_tmp = fitdata_tmp - referencedata
                    fitdata_converted.append(fitdata_tmp)
                    for j in range(order):
                        fitcoeff = fit['P'][-j-1]
                        fitstr = "{:2.6}".format(fitcoeff)
                        fititem = QtWidgets.QTableWidgetItem(fitstr)
                        #print('fitstr',fitstr,j,i)
                        self.fitwidget['fittable'].setItem(1+j,self.coloffset+i,fititem)
                        self.fitwidget['fittable'].item(1+j,self.coloffset+i).rawdata = fitcoeff # Save the original as additional property
                        
                    self.device.fitdata[i]['coeffs']       = np.ndarray.tolist(fit['P'])
                    self.device.fitdata[i]['order']        = order
                    self.device.fitdata[i]['type']         = fittype
                    
                    
                    
                else:
                    fitdata_converted.append(referencedata)
                    
        self.device.fitdata_converted = fitdata_converted
        print('Fidata converte',fitdata_converted)
        self.fitwidget['fittable'].resizeColumnsToContents()
        
        
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
            item0 = self.datatable.item(0,self.coloffset+i)
            if(item0 is not None):
                sensor = item0.text()
            else:
                sensor = '{:d}'.format(i)
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
        self.units   = []
        self.fitdata = []
        
        # How and if to synchronize the different X-Axes? 0: None, 1: With one Axes, 2: Last dt
        self._xsync = 0
        self._xsync_dt = 60

    def finalize_init(self):
        """ Function is called when the initialization of the redvypr device is completed
        """ 
        funcname = self.__class__.__name__ + 'finalize_init():'
        logger.debug(funcname)
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
            if(type(self.config['polyfit']) is not dict):
                print('to dict')
                self.config['polyfit'] = {}
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
        
        
        self.init_data_structure()
        
    def init_data_structure(self):
        """ Initializes data structure to store and fit calibration data.
        """
        # Clear the data interval list
        funcname = self.__class__.__name__ + 'init_data_structure():'
        logger.debug(funcname)
        try:
            self.data_interval
        except:
            self.data_interval = []

        if(len(self.data_interval)!= len(self.config['devices'])):
            self.data_interval = []
            for i,config_device in enumerate(self.config['devices']):
                self.data_interval.append([])
                
        # Clear the fit data
        self.fitdata       = []
        self.fitdata_converted = None
        for i,config_device in enumerate(self.config['devices']):
            logger.debug(funcname + ': Adding device ' + str(config_device))
            self.fitdata.append({})
            try:
                unitstr = config_device['unit']
            except:
                unitstr = 'NA0'
                
            self.units.append({'name':config_device,'x':'s','y':unitstr})
        
    def create_standard_config(self):
        """
        """
        
        try:
            self.config['devices']
        except:
            self.config['devices'] = []
            

    def start(self):
        start(self.datainqueue,self.dataqueue,self.comqueue)
        
    def connect_devices(self):
        """ Connects devices, if they are not already connected
        """
        funcname = self.__class__.__name__ + '.connect_devices():'                                
        logger.debug(funcname)
        # Remove all connections
        self.redvypr.rm_all_data_provider(self)
        # Check of devices have not been added
        devices = self.redvypr.get_devices() # Get all devices
        calib_devices = []
        for cal in self.config['devices']: # Loop over all plots
            name = cal['device']
            calib_devices.append(name)

        # Add the device if not already done so
        if True:
            for name in calib_devices:
                logger.info(funcname + 'Connecting device {:s}'.format(name))
                ret = self.redvypr.addrm_device_as_data_provider(name,self,remove=False)
                if(ret == None):
                    logger.info(funcname + 'Device was not found')
                elif(ret == False):
                    logger.info(funcname + 'Device was already connected')
                elif(ret == True):
                    logger.info(funcname + 'Device was successfully connected')   
        
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

        # Add buttons
        self.btn_add_interval = QtWidgets.QPushButton('Get data')
        self.btn_add_interval.clicked.connect(self.get_data_from_plots_clicked)
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
        
        # Add a description tab for the general description of the calibration
        self.widgets['description']        = QtWidgets.QWidget()
        self.widgets['description_layout'] = QtWidgets.QGridLayout(self.widgets['description'])
        self.widgets['description_ltext']  = QtWidgets.QLineEdit()
        self.widgets['description_text']   = QtWidgets.QTextEdit()
        self.widgets['description_layout'].addWidget(QtWidgets.QLabel('Operator'),0,0)
        self.widgets['description_layout'].addWidget(self.widgets['description_ltext'],0,1)
        self.widgets['description_layout'].addWidget(QtWidgets.QLabel('Description'),1,0,1,-1)
        self.widgets['description_layout'].addWidget(self.widgets['description_text'],2,0,1,-1)
        i1 = self.tabwidget.addTab(self.widgets['description'],'Description')
        
        
    def update_widgets(self):
        """ Compares self.config and widgets and add/removes plots/widgets if necessary
        """
        funcname = self.__class__.__name__ + '.update_widgets():'
        logger.debug(funcname)
        
        if 'polyfit' in self.device.config.keys(): # If the user wants to have a table
            try:
                self.widgets['polyfit']
                logger.debug(funcname + 'Already having PolfitWidget')
            except:
                logger.debug(funcname + 'Adding PolfitWidget')
                self.widgets['polyfit'] = PolyfitWidget(device = self.device,displaywidget=self)
                logger.debug(funcname + 'Adding PolyfitWidget to tab')
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
            
        self.plots = []    
        # Add axes to the widget
        config=self.device.config
        try:
            self.btn_clear.clicked.disconnect()
        except:
            pass
        i = 0
        for i,config_device in enumerate(config['devices']):
            logger.debug(funcname + ': Adding device ' + str(config_device))
                                                
            plot = PlotWidget(config_device,device=self.device,numdisp=i,buffersize=self.buffersizestd)
            self.btn_clear.clicked.connect(plot.clear_data)
            self.layout.addWidget(plot,i,0,1,-1)
            self.plots.append(plot)
            datastream_x = config_device['device'] + '(' + config_device['x'] + ',' +config_device['y'] + ')' 
            self.combo_sync.addItem(datastream_x)
            
        
        # Updating the data structure (i.e. data_interval)
        self.device.init_data_structure()   
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
            self.widgets['polyfit'].update_fitwidgets()
        
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




    def sample_interval(self,t0,t1):
        """
        Changes the data intervals for sampling (this is needed for
        automatic sampling by autocal, instead of the user choosing
        the interval using the mouse)

        """
        funcname = self.__class__.__name__ + '.sample_interval():'
        logger.info(funcname)        
        self.device.user_interval = []
        self.device.user_interval.append(t0)
        self.device.user_interval.append(t1)
        for i,plot in enumerate(self.plots):
            plot.mouse_clicked_proc()
            data = plot.get_data_clicked()
            if(data is not None):
                self.device.data_interval[i].append(data)

        if 'polyfit' in self.device.config.keys(): # If the user wants to have a table                
            self.widgets['polyfit'].update_table()
        # Update the responsetime widget with the new data            
        if 'responsetime' in self.device.config.keys(): # If the user wants to have a table
            self.widgets['responsetime']._update_data_intervals()


    def get_data_from_plots_clicked(self):
        """ Collects data from all plots and saves it into the self.device.data_interval list
        """
        funcname = self.__class__.__name__ + '.get_data_from_plots_clicked():'
        logger.debug(funcname)
        print('plots',len(self.plots))
        for i,plot in enumerate(self.plots):
            print('Getting data:',i)
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
        layout        = QtWidgets.QGridLayout(self)
        self.device   = device  
        self.label    = QtWidgets.QLabel("Calibration setup")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet(''' font-size: 24px; font: bold''')
        self.conbtn = QtWidgets.QPushButton("Add device")
        self.conbtn.clicked.connect(self.con_clicked)
        self.polybtn = QtWidgets.QPushButton("Add Polyfit")
        self.polybtn.clicked.connect(self.poly_clicked)
        self.respbtn = QtWidgets.QPushButton("Add Responsetime fit")
        self.respbtn.clicked.connect(self.resp_clicked)
        self.updbtn = QtWidgets.QPushButton("Update configuration")
        self.updbtn.clicked.connect(self.update_config_clicked)
        self.updbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)
        self.startbtn = QtWidgets.QPushButton("Start logging")
        self.startbtn.clicked.connect(self.start_clicked)
        self.startbtn.setCheckable(True)
        self.startbtn.setSizePolicy(QtWidgets.QSizePolicy.Preferred,QtWidgets.QSizePolicy.Expanding)
        self.loadbtn = QtWidgets.QPushButton("Load calibration")
        self.loadbtn.clicked.connect(self.load_data)
        self.savebtn = QtWidgets.QPushButton('Save calibration')
        self.savebtn.clicked.connect(self.save_data)  
        self.configtree = configTreeCalibrationWidget(config=self.device.config,redvypr=self.device.redvypr) 
        self.configtree.device_selected.connect(self.qtree_device_selected) 
        
        
        conflabel = QtWidgets.QLabel('Configuration')
        conflabel.setAlignment(QtCore.Qt.AlignCenter)
        conflabel.setStyleSheet(''' font-size: 24px; font: bold''')
           
        layout.addWidget(self.label,0,0,1,2) 
        layout.addWidget(self.conbtn,1,0)
        layout.addWidget(self.polybtn,2,0)
        layout.addWidget(self.respbtn,3,0)
        layout.addWidget(self.savebtn,4,0)
        layout.addWidget(self.loadbtn,5,0)
        layout.addWidget(conflabel,6,0,1,2) 
        layout.addWidget(self.configtree,7,0,1,2)
        layout.addWidget(self.updbtn,1,1,2,1)
        layout.addWidget(self.startbtn,3,1,3,1)
        
        
        
        # Make a new config out of the 
        self.newconfig = {'devices':[]} 
        self.newdata_interval = None
        
    def qtree_device_selected(self,devicename,deviceindex):
        print('qtree_device_selected',devicename)
        if(deviceindex >= 0):
            self.conbtn.setText("Remove device")
        else:
            self.conbtn.setText("Add device")
        
    def load_data(self):
        """ Loading a previously performed calibration
        """
        funcname = self.__class__.__name__ + '.load_data():'
        fname_open = QtWidgets.QFileDialog.getOpenFileName(self, 'Open file', '',"YAML files (*.yaml);; All files (*)")
        logger.info(funcname + 'Opening file {:s}'.format(fname_open[0]))
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
        
        self.newconfig       =data_yaml['config']
        self.newdata_interval=data_yaml['data_interval']
        self.configtree.create_qtree(config)
        
                    
            
    def save_data(self):
        """ Save the data found in datatable and fittable into a file format to be choosen by the save widget
        """
        folder = QtWidgets.QFileDialog.getExistingDirectory(None, 'Choose folder to save sensor yaml files')        
        tnow       = datetime.datetime.now()
        tstr       = tnow.strftime('%Y-%m-%d_%H%M%S_')
        fname = tstr + 'polyfit.yaml'
        fname_full = folder + '/' + fname
        # Create a dictionary with the data to be saved
        device     = self.device
        data_save  = {}
        data_save['data_interval']  = self.device.data_interval
        data_save['fitdata']        = self.device.fitdata
        #data_save['units']          = self.device.units
        data_save['config']         = self.device.config
        # Update the header in config
        if('polyfit' in device.config.keys()):
            displaywidget = self.redvyprdevicelistentry['displaywidget']
            datatable     = displaywidget.widgets['polyfit'].datatable
            ncols         = datatable.columnCount()
            nrows         = datatable.rowCount()
            nheader       = displaywidget.widgets['polyfit'].headerrows
            nheader_basis = displaywidget.widgets['polyfit'].headerrows_basis
            row_units     = displaywidget.widgets['polyfit']._row_units
            row_type      = displaywidget.widgets['polyfit']._row_type
            row_serial    = displaywidget.widgets['polyfit']._row_serial
            

            header = []
            for row in range(nheader_basis,nheader): # Header starts in fourth row
                data_row = []
                for col in range(ncols):
                    try:
                        data_row.append(datatable.item(row,col).text())
                    except Exception as e:
                        data_row.append('')
                    
                header.append(data_row)

            # Get comments 
            comments = []
            col_comment = displaywidget.widgets['polyfit']._start_add_info_col
            for row in range(1,nrows):
                try:
                    comments.append(datatable.item(row,col_comment).text())
                except:
                    comments.append('')

            
            data_save['config']['polyfit']['comments']= comments
            data_save['config']['polyfit']['headers'] = header
            # Saving the fittype and the reference sensor
            fitcombo = displaywidget.widgets['polyfit'].fitwidget['fitcombo']
            refcombo = displaywidget.widgets['polyfit'].fitwidget['refcombo']
            fittype = fitcombo.currentText()
            refsensor = refcombo.currentText()
            data_save['config']['polyfit']['fittype']   = fittype
            data_save['config']['polyfit']['refsensor'] = refsensor
        
        print('Saving to file {:s}'.format(fname_full))            
        with open(fname_full, 'w') as fyaml:
            yaml.dump(data_save, fyaml)
     
    def update_config_clicked(self):
        funcname = self.__class__.__name__ + '.update_config_clicked():'
        logger.debug(funcname)
        self.newconfig = self.configtree.get_config()
        newconfig = copy.deepcopy(self.newconfig)
        print('Updating',newconfig)
        self.apply_new_configuration(config = newconfig,data_interval=self.newdata_interval)
        self.newdata_interval = None
            
    def apply_new_configuration(self,config,data_interval=None):
        """
        Updates all widgets based on the new config and data_interval
        Args:
            config:
            data_interval:
        """
        funcname = self.__class__.__name__ + '.apply_new_configuration():'
        logger.debug(funcname)
        self.device_stop.emit(self.device)
        # Add the config to the device and update the whole widgets
        device               = self.device
        device.config        = copy.deepcopy(config)
        self.device.init_data_structure()
        # Add data_intervals (if available). This is mainly used for loading an old configuration
        if(data_interval is not None):
            device.data_interval = data_interval
            
        device.finalize_init()
        displaywidget = self.redvyprdevicelistentry['displaywidget']
        displaywidget.update_widgets()
        if('polyfit' in device.config.keys()):
            logger.debug(funcname + 'Updating polyfit widget')
            displaywidget.widgets['polyfit'].update_table()
            displaywidget.widgets['polyfit'].update_fitwidgets()
            
    def __device_added__(self,devicedict):
        print('Device added',devicedict)
        devicestr = devicedict['devicename']
        newdevice = {'device':devicestr,'x':'t','y':'NA'}
        
        try:
            devicedicts = self.newconfig['devices']
        except:
            devicedicts = []
            
        FLAG_DEVICE_EXISTS = False
        for d in devicedicts:
            if(d['device'] == devicestr):
                FLAG_DEVICE_EXISTS = True
                
        if(FLAG_DEVICE_EXISTS==True):
            logger.info('Device is already exsiting')
        else:
            logger.info('Adding device {:s}'.format(devicestr))
            self.newconfig['devices'].append(newdevice)
            
        self.newconfig = copy.deepcopy(self.newconfig) # If we have configdata items, clean them
        self.update_configwidgets(self.newconfig)
            
    def update_configwidgets(self,config):
        """ Updating the configuration widgets, basically visualizing the new configuration. This is done before the all widgeta are updated with apply_new_configuration and the configuration is applied
        """
        funcname = self.__class__.__name__ + '.update_configwidgets():'
        logger.debug(funcname)
        self.configtree.create_qtree(config)
        
        
    def poly_clicked(self):
        funcname = self.__class__.__name__ + '.poly_clicked():'
        logger.debug(funcname)
        self.newconfig = copy.deepcopy(self.newconfig)
        self.newconfig['polyfit'] = {'manual':[]}
        self.configtree.create_qtree(self.newconfig)
    
    def resp_clicked(self):
        funcname = self.__class__.__name__ + '.resp_clicked():'
        logger.debug(funcname)
        self.newconfig = copy.deepcopy(self.newconfig)        
        self.newconfig['responsetime'] = {}
        self.configtree.create_qtree(self.newconfig)
        
        
    def con_clicked(self):
        funcname = self.__class__.__name__ + '.con_clicked():'
        logger.debug(funcname)
        button = self.conbtn
        if('Add' in button.text()):
            self.devicechoose = redvypr_devicelist_widget(self.redvypr, device = None,devicename_highlight = None,deviceonly=True,devicelock = False, subscribed_only=False) # Open a device choosing widget
            self.devicechoose.apply.connect(self.__device_added__)
            self.devicechoose.show()
        elif('Rem' in button.text()):
            devname = self.configtree.devicename_selected
            print('Remove',devname)
            ind = self.configtree.deviceindex_selected
            self.newconfig['devices'].pop(ind)
            self.configtree.create_qtree(self.newconfig)
            self.conbtn.setText("Add device")
        
    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            print("button pressed")
            self.device.connect_devices()
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
#
#
#
class configTreeCalibrationWidget(QtWidgets.QTreeWidget):
    """ Qtreewidget that display and modifies the configuration of the calibration config
    """
    device_selected = QtCore.pyqtSignal(str,int) 
    def __init__(self, config = {},editable=True,redvypr=None):
        funcname = __name__ + '.__init__():'
        super().__init__()
            
        self.redvypr     = redvypr
        print(funcname + str(config))
        # make only the first column editable        
        self.setEditTriggers(self.NoEditTriggers)
        self.header().setVisible(False)
        self.create_qtree(config,editable=True)
        
        self.itemExpanded.connect(self.resize_view)
        self.itemCollapsed.connect(self.resize_view)
        # Connect edit triggers
        self.itemDoubleClicked.connect(self.checkEdit)
        self.itemChanged.connect(self.item_changed) # If an item is changed
        self.currentItemChanged.connect(self.current_item_changed) # If an item is changed           
        
    def checkEdit(self, item, column):
        """ Helper function that only allows to edit column 1
        """
        funcname = __name__ + '.checkEdit():'
        logger.debug(funcname + '{:d}'.format(column))
        if column == 1:
            self.edititem(item, column)

    def current_item_changed(self,current,previous):
        """ Save the data in the currently changed item, this is used to
        restore if newly entered data is not valid
        """
        devicename  = 'NA'
        deviceindex = -1
        self.backup_data = current.text(1)
        item = current
        if(item.parent() is not None):
            print(item.text(0),item.parent().text(0))
            if(item.parent().text(0) == 'devices'): # Check if we have a device
                devicename = item.text(1)
                deviceindex = int(item.text(0))
                print('Device',devicename,deviceindex)
                self.devicename_selected = devicename
                self.deviceindex_selected = deviceindex
        
        self.device_selected.emit(devicename,deviceindex)

    def item_changed(self,item,column):
        """ Updates the dictionary with the changed data
        """
        funcname = __name__ + '.item_changed():'
        logger.debug(funcname + 'Changed {:s} {:d} to {:s}'.format(item.text(0),column,item.text(1)))
        # Parse the string given by the changed item using yaml (this makes the types correct again)
        try:
            pstring = "a: {:s}".format(item.text(1))
            yparse = yaml.safe_load(pstring)
            newdata = yparse['a']
        except Exception as e: # Could not parse, use the old, valid data as a backup
            logger.debug(funcname + '{:s}'.format(str(e)))            
            pstring = "a: {:s}".format(self.backup_data)
            yparse = yaml.safe_load(pstring)
            newdata = yparse['a']
            item.setText(1,self.backup_data)
            #print('ohno',e)   
               

        # Change the dictionary 
        try:
            key = item._ncconfig_key
            #print('key',key,item._ncconfig_[key])
            if(type(item._ncconfig_[key]) == configdata):
               item._ncconfig_[key].value = newdata # The newdata, parsed with yaml               
            else:
               item._ncconfig_[key] = newdata # The newdata, parsed with yaml

        except Exception as e:
            logger.debug(funcname + '{:s}'.format(str(e)))

        self.resizeColumnToContents(0)                            

    def create_qtree(self,config,editable=True):
        """Creates a new qtree from the configuration and replaces the data in
        the dictionary with a configdata obejct, that save the data
        but also the qtreeitem, making it possible to have a synced
        config dictionary from/with a qtreewidgetitem. TODO: Worth to
        replace with a qviewitem?

        """
        funcname = __name__ + '.create_qtree():'
        self.config      = config
        logger.debug(funcname)
        self.blockSignals(True)
        if True:
            self.clear()
            root = self.invisibleRootItem()
            self.setColumnCount(2)
            
        for key in sorted(config.keys()):
            if key == 'devices':
                parent = QtWidgets.QTreeWidgetItem([key,''])
                root.addChild(parent)
                for idev,dev in enumerate(config['devices']):
                    devicename = dev['device']
                    deviceitem = QtWidgets.QTreeWidgetItem([str(idev),devicename])
                    parent.addChild(deviceitem)
                    for devkey in config['devices'][idev].keys():
                        keycontent    = config['devices'][idev][devkey]
                        devicekeyitem = QtWidgets.QTreeWidgetItem([devkey,keycontent])
                        deviceitem.addChild(devicekeyitem)
                        # Change the configuration with configdata to store extra informations
                        keycontent_new                   = configdata(keycontent)
                        config['devices'][idev][devkey]  = keycontent_new
                        devicekeyitem._ncconfig_         = config['devices'][idev]
                        devicekeyitem._ncconfig_key      = devkey  
                        if(editable):
                            devicekeyitem.setFlags(devicekeyitem.flags() | QtCore.Qt.ItemIsEditable)
                            
            else:
                value               = config[key]
                data                = configdata(value)
                config[key]         = data                
                child = QtWidgets.QTreeWidgetItem([key,str(value)])
                child._ncconfig_    = config
                child._ncconfig_key = key                
                root.addChild(child)
                if(editable):
                    child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)
                groupparent = child

        self.resizeColumnToContents(0)
        self.blockSignals(False)  
        
    def edititem(self,item,colno):
        funcname = __name__ + 'edititem()'
        #print('Hallo!',item,colno)
        logger.debug(funcname + str(item.text(0)) + ' ' + str(item.text(1)))
        self.item_change = item
        if(item.text(0) == 'device'):
            # Let the user choose all devices and take care that the devices has been connected
            self.devicechoose = redvypr_devicelist_widget(self.redvypr, device = None, deviceonly=True, subscribed_only=False) # Open a device choosing widget
            self.devicechoose.device_name_changed.connect(self.itemtextchange)
            self.devicechoose.show()
        
        if((item.text(0) == 'x') or (item.text(0) == 'y')):
            # Get the devicename first
            parent = item.parent()
            devicename = ''
            device_datakey = None
            print('Childcount',parent.childCount())
            for i in range(parent.childCount()):
                child = parent.child(i)
                keystring = child.text(0)
                print('keystring',keystring)
                if(keystring == 'device'):
                    devicestr_datakey = child.text(1)
                    print('Devicename',devicestr_datakey)
                    break
            
            if(devicestr_datakey is not None): 
                print('Opening devicelist widget')       
                self.devicechoose = redvypr_devicelist_widget(self.redvypr, device = devicestr_datakey,devicename_highlight = devicestr_datakey,deviceonly=False,devicelock = True, subscribed_only=False) # Open a device choosing widget
                self.devicechoose.datakey_name_changed.connect(self.itemtextchange)
                self.devicechoose.show()
        
    def resize_view(self):
        self.resizeColumnToContents(0) 
        
    def itemtextchange(self,itemtext):
        """ Changes the current item text self.item_change, which is defined in self.item_changed. This is a wrapper function to work with signals that return text only
        """
        self.item_change.setText(1,itemtext)
        
    def get_config(self):
        print('Get config',self.config)
        config = self.config
        return config 
                
                
