import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import logging
import sys
import redvypr.widgets.redvyprSubscribeWidget
from redvypr.device import RedvyprDevice
from redvypr.widgets.pydanticConfigWidget import pydanticDeviceConfigWidget
from redvypr.gui import iconnames
import qtawesome

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.widgets.standard_device_widgets')
logger.setLevel(logging.DEBUG)


class displayDeviceWidget_standard(QtWidgets.QWidget):
    """ Widget is displaying incoming data as text
    """

    def __init__(self, device=None, tabwidget=None):
        """
        device [optional]
        tabwidget [optional]

        """
        funcname = __name__ + '.__init__()'
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QGridLayout(self)
        self.tabwidget = tabwidget
        self.device = device
        # A timer that is regularly calling the device.status function
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_status)
        self.statustimer.start(2000)

        self.text = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)
        layout.addWidget(self.text, 0, 0)

    def thread_status(self, status):
        """ This function is regularly called by redvypr whenever the thread is started/stopped
        """
        pass
        # self.update_buttons(status['threadalive'])

    def update_status(self):
        """
        """
        funcname = __name__ + 'update_status():'
        try:
            statusdata = self.device.status()
            # print(funcname + str(statusdata))
            self.text.clear()
            self.text.insertPlainText(str(statusdata))
        except Exception as e:
            logger.debug(funcname + str(e))
            pass

    def update_data(self, data):
        """ Function that is called from the redvypr_main widget if new data in a dataqueue has been received.
        """
        funcname = __name__ + '.update_data()'
        tnow = time.time()
        # print('got data',data)

        devicename = data['device']
        # Only plot the data in intervals of dt_update length, this prevents high CPU loads for fast devices
        update = (tnow - self.config['last_update']) > self.config['dt_update']

        if (update):
            self.config['last_update'] = tnow





#
#
#
#
#
class redvypr_deviceInitWidget(QtWidgets.QWidget):
    subscribed = QtCore.pyqtSignal(
        RedvyprDevice)  # Signal displaying a subscription

    def __init__(self, device=None,redvypr=None):
        """
        Standard deviceinitwidget if the device is not providing one by itself.

        Args:
            device:
        """
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.config_widgets = []
        self.device = device
        self.redvypr = redvypr
        #self.config_widget = configWidget(device.config,redvypr_instance=self.device.redvypr)

        #self.config_widgets.append(self.config_widget)
        labelstr = 'Init device\n' + str(device.name)
        self.label = QtWidgets.QLabel(labelstr)
        font = QtGui.QFont('Arial', 20)
        font.setBold(True)
        self.label.setFont(font)
        self.label.setAlignment(QtCore.Qt.AlignCenter)

        # Start-button
        self.startbutton = QtWidgets.QPushButton('Start')
        self.startbutton.clicked.connect(self.start_clicked)
        self.startbutton.setCheckable(True)
        #self.startbutton.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        # Process kill button (if thread)
        if (self.device.mp == 'multiprocess') or (self.device.mp == 'qthread'):
            # Killbutton
            self.killbutton = QtWidgets.QPushButton('Kill process')
            self.killbutton.clicked.connect(self.kill_clicked)
            #self.killbutton.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        # Connect button
        self.configure_button = QtWidgets.QPushButton("Configure")
        self.configure_button.clicked.connect(self.configure_clicked)
        # self.conbutton.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.config_widgets.append(self.configure_button)

        # Connect button
        self.subscribe_button = QtWidgets.QPushButton("Subscribe")
        self.subscribe_button.clicked.connect(self.subscribe_clicked)
        #self.conbutton.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.config_widgets.append(self.subscribe_button)

        #self.layout.addWidget(self.config_widget, 0, 0, 1, 4)
        self.layout.addWidget(self.label, 0, 0, 1, 4)
        self.layout.addWidget(self.configure_button, 1, 0, 1, 4)
        self.layout.addWidget(self.subscribe_button, 2, 0, 1, 4)
        if (self.device.mp == 'multiprocess')  or (self.device.mp == 'qthread'):
            self.layout.addWidget(self.startbutton, 3, 0, 1, 3)
            self.layout.addWidget(self.killbutton, 3, 3)
        else:
            self.layout.addWidget(self.startbutton, 4, 0, 1, 4)

        # If the config is changed, update the device widget

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

        #self.config_widget.config_changed_flag.connect(self.config_changed)

    def config_changed(self):
        """


        Args:
            config:

        Returns:

        """
        funcname = __name__ + '.config_changed():'
        logger.debug(funcname)

    def kill_clicked(self):
        button = self.sender()
        logger.debug("Kill device {:s}".format(self.device.name))
        self.device.kill_process()

    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            logger.debug("button pressed")
            button.setText('Starting')
            self.device.thread_start()
            # self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            # button.setText('Stopping')
            self.startbutton.setChecked(True)
            self.device.thread_stop()

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']
        # Running
        if (thread_status):
            self.startbutton.setText('Stop')
            self.startbutton.setChecked(True)
            for w in self.config_widgets:
                w.setEnabled(False)
        # Not running
        else:
            self.startbutton.setText('Start')
            for w in self.config_widgets:
                w.setEnabled(True)

            # Check if an error occured and the startbutton
            if (self.startbutton.isChecked()):
                self.startbutton.setChecked(False)
            # self.conbtn.setEnabled(True)

    def subscribe_clicked(self):
        button = self.sender()
        # self.__con_widget = redvyprConnectWidget(devices=self.redvypr.devices, device=device)
        self.__subscribeWidget = redvypr.widgets.redvyprSubscribeWidget.SubscribeWidget(redvypr=self.redvypr, device=self.device)
        self.__subscribeWidget.show()
        self.subscribed.emit(self.device)

    def configure_clicked(self):
        button = self.sender()

        funcname = __name__ + '.config_clicked():'
        logger.debug(funcname)
        self.config_widget = pydanticDeviceConfigWidget(self.device)
        self.config_widget.showMaximized()
        #self.subscribed.emit(self.device)



class RedvyprdevicewidgetSimple(QtWidgets.QWidget):
    subscribed = QtCore.pyqtSignal(
        RedvyprDevice)  # Signal displaying a subscription

    def __init__(self, device=None, redvypr=None):
        """
        Simple devicewidget

        Args:
            device:
        """
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.layout_base = QtWidgets.QVBoxLayout(self)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.layout_base.addWidget(self.splitter)
        self.widget = QtWidgets.QWidget()
        self.layout = QtWidgets.QVBoxLayout(self.widget)
        self.buttons_widget = QtWidgets.QWidget()
        self.layout_buttons = QtWidgets.QGridLayout(self.buttons_widget)
        self.config_widgets = []
        self.device = device
        #self.redvypr = redvypr
        # Start-button
        self.startbutton = QtWidgets.QPushButton('Start')
        self.startbutton.clicked.connect(self.start_clicked)
        self.startbutton.setCheckable(True)
        self.device.thread_started.connect(self.thread_status_changed)
        self.device.thread_stopped.connect(self.thread_status_changed)
        #self.startbutton.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        # Process kill button (if thread)
        if (self.device.mp == 'multiprocess') or (self.device.mp == 'qthread'):
            # Killbutton
            self.killbutton = QtWidgets.QPushButton('Kill process')
            self.killbutton.clicked.connect(self.kill_clicked)
            #self.killbutton.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        # configure button
        icon = qtawesome.icon(iconnames['settings'])
        self.configure_button = QtWidgets.QPushButton("Configure")
        self.configure_button.setIcon(icon)
        self.configure_button.clicked.connect(self.configure_clicked)
        # self.conbutton.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.config_widgets.append(self.configure_button)
        # subscribe button
        self.subscribe_button = QtWidgets.QPushButton("Subscribe")
        self.subscribe_button.clicked.connect(self.subscribe_clicked)
        #self.conbutton.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.config_widgets.append(self.subscribe_button)
        #self.layout.addWidget(self.config_widget, 0, 0, 1, 4)
        self.layout_buttons.addWidget(self.subscribe_button, 2, 0, 1, 2)
        self.layout_buttons.addWidget(self.configure_button, 2, 2, 1, 2)
        if (self.device.mp == 'multiprocess')  or (self.device.mp == 'qthread'):
            self.layout_buttons.addWidget(self.startbutton, 3, 0, 1, 3)
            self.layout_buttons.addWidget(self.killbutton, 3, 3)
        else:
            self.layout_buttons.addWidget(self.startbutton, 4, 0, 1, 4)

        # Add both widgets to splitter
        #self.layout_base.addWidget(self.widget)
        #self.layout_base.addWidget(self.buttons_widget)
        self.splitter.addWidget(self.widget)
        self.splitter.addWidget(self.buttons_widget)
        self.splitter.setStretchFactor(0, 1)  # Stretch the upper one
        self.splitter.setStretchFactor(1, 0)  # Make the lower one smaller
        self.splitter.setHandleWidth(2)
        # If the config is changed, update the device widget
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def thread_status_changed(self, status):
        funcname = __name__ + '.thread_status_changed():'
        logger.debug(funcname)
        #print('status',status)

    def config_changed(self):
        """


        Args:
            config:

        Returns:

        """
        funcname = __name__ + '.config_changed():'
        logger.debug(funcname)

    def kill_clicked(self):
        button = self.sender()
        logger.debug("Kill device {:s}".format(self.device.name))
        self.device.kill_process()

    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            logger.debug("button pressed")
            button.setText('Starting')
            self.device.thread_start()
            # self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            # button.setText('Stopping')
            self.startbutton.setChecked(True)
            self.device.thread_stop()

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']
        # Running
        if (thread_status):
            self.startbutton.setText('Stop')
            self.startbutton.setChecked(True)
            for w in self.config_widgets:
                w.setEnabled(False)
        # Not running
        else:
            self.startbutton.setText('Start')
            for w in self.config_widgets:
                w.setEnabled(True)

            # Check if an error occured and the startbutton
            if (self.startbutton.isChecked()):
                self.startbutton.setChecked(False)
            # self.conbtn.setEnabled(True)

    def subscribe_clicked(self):
        button = self.sender()
        # self.__con_widget = redvyprConnectWidget(devices=self.redvypr.devices, device=device)
        self.__subscribeWidget = redvypr.widgets.redvyprSubscribeWidget.SubscribeWidget(redvypr=self.redvypr, device=self.device)
        self.__subscribeWidget.show()
        self.subscribed.emit(self.device)

    def configure_clicked(self):
        button = self.sender()

        funcname = __name__ + '.config_clicked():'
        logger.debug(funcname)
        self.config_widget = pydanticDeviceConfigWidget(self.device)
        self.config_widget.showMaximized()
        #self.subscribed.emit(self.device)


class RedvyprdevicewidgetStartonly(QtWidgets.QWidget):
    subscribed = QtCore.pyqtSignal(
        RedvyprDevice)  # Signal displaying a subscription

    def __init__(self,device=None, redvypr=None):
        """
        Simple devicewidget

        Args:
            device:
        """
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.layout = QtWidgets.QGridLayout(self)
        self.buttons_widget = QtWidgets.QWidget()
        self.layout_buttons = QtWidgets.QGridLayout(self.buttons_widget)
        self.config_widgets = []
        self.device = device
        self.redvypr = redvypr
        # Start-button
        self.startbutton = QtWidgets.QPushButton('Start')
        self.startbutton.clicked.connect(self.start_clicked)
        self.startbutton.setCheckable(True)
        self.device.thread_started.connect(self.thread_status_changed)
        self.device.thread_stopped.connect(self.thread_status_changed)
        #self.startbutton.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        # Process kill button (if thread)
        if (self.device.mp == 'multiprocess') or (self.device.mp == 'qthread'):
            # Killbutton
            self.killbutton = QtWidgets.QPushButton('Kill process')
            self.killbutton.clicked.connect(self.kill_clicked)
            #self.killbutton.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        if (self.device.mp == 'multiprocess')  or (self.device.mp == 'qthread'):
            self.layout_buttons.addWidget(self.startbutton, 0, 0, 1, 3)
            self.layout_buttons.addWidget(self.killbutton, 0, 3)
        else:
            self.layout_buttons.addWidget(self.startbutton, 0, 0, 1, 4)

        self.layout.addWidget(self.buttons_widget)
        # If the config is changed, update the device widget
        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def update_data(self, data):
        pass
        #print('Got data',data)

    def thread_status_changed(self, status):
        funcname = __name__ + '.thread_status_changed():'
        logger.debug(funcname)

    def kill_clicked(self):
        button = self.sender()
        logger.debug("Kill device {:s}".format(self.device.name))
        self.device.kill_process()

    def start_clicked(self):
        button = self.sender()
        if button.isChecked():
            logger.debug("button pressed")
            button.setText('Starting')
            self.device.thread_start()
            # self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            # button.setText('Stopping')
            self.startbutton.setChecked(True)
            self.device.thread_stop()

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']
        # Running
        if (thread_status):
            self.startbutton.setText('Stop')
            self.startbutton.setChecked(True)
            for w in self.config_widgets:
                w.setEnabled(False)
        # Not running
        else:
            self.startbutton.setText('Start')
            for w in self.config_widgets:
                w.setEnabled(True)

            # Check if an error occured and the startbutton
            if (self.startbutton.isChecked()):
                self.startbutton.setChecked(False)
            # self.conbtn.setEnabled(True)




