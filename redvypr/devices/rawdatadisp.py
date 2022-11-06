import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import yaml
from redvypr.device import redvypr_device
from redvypr.data_packets import check_for_command

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('rawdatadisp')
logger.setLevel(logging.DEBUG)

description = 'Displays data as text received from connected devices'

config_template = {}
config_template['bufsize']        = {'type': 'int','default':10000,'description':'The buffer size of the text display (the MaximumBlockCount of the QPlainTextEdit)'}
config_template['redvypr_device'] = {}
config_template['redvypr_device']['publish']     = False
config_template['redvypr_device']['subscribe']   = True
config_template['redvypr_device']['description'] = description


def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start()'        
    while True:
        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if (data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command: {:s}'.format(str(data)))
            if (command is not None):
                logger.debug('Command is for me: {:s}'.format(str(command)))
                break

        time.sleep(0.05)
        while(datainqueue.empty() == False):
            try:
                data = datainqueue.get(block=False)
                dataqueue.put(data)

            except Exception as e:
                logger.debug(funcname + ':Exception:' + str(e))            


class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QFormLayout(self)
        self.device   = device
        self.text     = QtWidgets.QPlainTextEdit(self)
        self.clearbtn = QtWidgets.QPushButton('Clear')
        self.clearbtn.clicked.connect(self.cleartext)
        self.scrollchk= QtWidgets.QCheckBox('Scroll to end')
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(self.device.config['bufsize'])
        layout.addRow(self.text)
        layout.addRow(self.scrollchk,self.clearbtn)
        self.text.insertPlainText("Hello, this is the raw data display device!\n")
        
    def cleartext(self):
        self.text.clear()        

    def update(self,data):
        #cursor = QtGui.QTextCursor(self.text.document())
        prev_cursor = self.text.textCursor()
        pos = self.text.verticalScrollBar().value()
        self.text.moveCursor(QtGui.QTextCursor.End)
        self.text.insertPlainText(str(data) + '\n')
        #cursor.setPosition(0)
        #self.text.setTextCursor(prev_cursor)
        if(self.scrollchk.isChecked()):
            self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
        else:
            self.text.verticalScrollBar().setValue(pos)
        
