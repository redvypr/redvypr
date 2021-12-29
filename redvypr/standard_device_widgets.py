import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import logging
import sys
import yaml

description = 'An example device'

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('exampledevice')
logger.setLevel(logging.DEBUG)

class displayDeviceWidget_standard(QtWidgets.QWidget):
    """ Widget is plotting realtimedata using the pyqtgraph functionality
    This widget can be configured with a configuration dictionary 
    """
    def __init__(self,device=None,tabwidget=None):
        """
        device [optional]
        tabwidget [optional]
        
        """
        funcname = __name__ + '.start()'
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QGridLayout(self)
        self.device = device
        # A timer that is regularly calling the device.status function
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_status)
        self.statustimer.start(2000)

        self.text     = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)
        layout.addWidget(self.text,0,0)

                
    def thread_status(self,status):
        """ This function is regularly called by redvypr whenever the thread is started/stopped
        """
        pass        
        #self.update_buttons(status['threadalive'])
        
    def update_status(self):
        """
        """
        funcname = __name__ + 'update_status():'
        try:
            statusdata = self.device.status()
            #print(funcname + str(statusdata))
            self.text.clear()
            self.text.insertPlainText(str(statusdata))
        except Exception as e:
            #logger.debug(funcname + str(e) + 'hallo')
            pass

        
    def update(self,data):
        """ 
        """
        funcname = __name__ + '.update()'
        tnow = time.time()
        #print('got data',data)
        
        devicename = data['device']
        # Only plot the data in intervals of dt_update length, this prevents high CPU loads for fast devices
        update = (tnow - self.config['last_update']) > self.config['dt_update']
        
        if(update):
            self.config['last_update'] = tnow
