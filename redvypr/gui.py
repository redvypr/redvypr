import copy
import logging
import sys
import yaml
import datetime
import qtawesome
from pydantic.color import Color as pydColor
from PyQt6 import QtWidgets, QtCore, QtGui
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from redvypr.widgets.redvyprSubscribeWidget import redvyprSubscribeWidget
#from redvypr.widgets.gui_config_widgets import redvypr_ip_widget, configQTreeWidget, configWidget,
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget, pydanticDeviceConfigWidget, dictQTreeWidget, datastreamMetadataWidget
from redvypr.widgets.redvyprAddressWidget import datastreamWidget, datastreamsWidget
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import RedvyprMetadata, RedvyprDeviceMetadata
import redvypr.files as files
import redvypr.device as device

_logo_file = files.logo_file
_icon_file = files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.gui')
logger.setLevel(logging.INFO)

# Some standard iconnames
iconnames = {'settings':'ri.settings-5-line'}


class deviceTableWidget(QtWidgets.QTableWidget):
    """
    Tablewidget that displays all devices of the redvypr instance, gives informations and controls possibility.

    """

    def __init__(self, redvyprWidget=None):
        """

        Args:
            redvypr:
            device:
        """
        super(deviceTableWidget, self).__init__()
        self.redvyprWidget = redvyprWidget
        self.redvypr = redvyprWidget.redvypr
        self.redvypr.device_added.connect(self.populate_table)
        self.redvypr.device_removed.connect(self.populate_table)
        self.populate_table()
        self._updatetimer = QtCore.QTimer()
        self._updatetimer.timeout.connect(self.updateDevicePackets)
        self._updatetimer.timeout.connect(self.deviceThreadStatusCheckAll)
        self._updatetimer.start(2000)
    def populate_table(self):
        nRows = len(self.redvypr.devices)
        colheader = ['Name', 'Start', 'Subscribe', 'Loglevel', 'Window location', 'Configure', 'View',
                         'Packets published', 'Packets received']

        self.colheader = colheader
        nCols = len(colheader)
        self.__startbuttons = []
        self.clear()
        self.setRowCount(nRows)
        self.setColumnCount(nCols)
        self.setHorizontalHeaderLabels(colheader)
        for irow,d in enumerate(self.redvypr.devices):
            #print('d',d)
            device = d['device']
            devicedict = d
            # Devicename
            colindex = colheader.index('Name')
            devicename = device.name
            item_name = QtWidgets.QTableWidgetItem(devicename)
            self.setItem(irow, colindex, item_name)
            # Start
            button_start = QtWidgets.QPushButton('Start')
            self.__startbuttons.append(button_start)
            button_start.setCheckable(True)
            button_start.__device = device
            device.thread_started.connect(self.deviceThreadStatusChanged)
            device.thread_stopped.connect(self.deviceThreadStatusChanged)
            button_start.__devicedict = devicedict
            button_start.clicked.connect(self.deviceStartStopClicked)
            colindex = colheader.index('Start')
            self.setCellWidget(irow, colindex, button_start)
            # Subscribe
            button_subscribe = QtWidgets.QPushButton('Subscribe')
            button_subscribe.__device = device
            button_subscribe.__devicedict = devicedict
            button_subscribe.clicked.connect(self.deviceSubscribeClicked)
            colindex = colheader.index('Subscribe')
            self.setCellWidget(irow, colindex, button_subscribe)
            # Loglevel
            if True:
                level = device.logger.getEffectiveLevel()
                levelname = logging.getLevelName(level)
                loglevels = ['INFO', 'DEBUG', 'WARNING', 'ERROR', 'CRITICAL']
                log_combo = QtWidgets.QComboBox()
                for i, l in enumerate(loglevels):
                    log_combo.addItem(l)

                log_combo.setCurrentText(levelname)
                log_combo.__device = device
                log_combo.__devicedict = devicedict
                log_combo.currentIndexChanged.connect(self.loglevelChanged)
                colindex = colheader.index('Loglevel')
                self.setCellWidget(irow, colindex, log_combo)
            # Dock location
            combo_choose = QtWidgets.QComboBox()
            combo_choose.addItem('Tab')
            combo_choose.addItem('Window')
            combo_choose.addItem('Hide')
            combo_choose.__device = device
            combo_choose.__devicedict = devicedict
            # Change the combo to the device setup
            device_dockstr = device.device_parameter.gui_dock
            combo_choose.setCurrentText(device_dockstr)
            combo_choose.currentIndexChanged.connect(self.widgetlocChanged)

            colindex = colheader.index('Window location')
            self.setCellWidget(irow, colindex, combo_choose)
            # Configure
            button_configure = QtWidgets.QPushButton('Configure')
            button_configure.__device = device
            button_configure.__devicedict = devicedict
            button_configure.setEnabled(True)
            button_configure.clicked.connect(self.deviceConfigureClicked)
            colindex = colheader.index('Configure')
            self.setCellWidget(irow, colindex, button_configure)
            # View
            button_view = QtWidgets.QPushButton('View')
            button_view.__device = device
            button_view.__devicedict = devicedict
            button_view.clicked.connect(self.deviceViewClicked)
            colindex = colheader.index('View')
            self.setCellWidget(irow, colindex, button_view)

        self.hideColumn(colheader.index('Loglevel'))
        self.resizeColumnsToContents()
        self.updateDevicePackets()

    def updateDevicePackets(self):
        """
        Updates the packets numbers in the table
        :return:
        """
        funcname = __name__ + '.updateDevicePackets():'
        #logger.debug(funcname)
        for irow, d in enumerate(self.redvypr.devices):
            npub = d['device'].statistics['packets_published']
            colindex = self.colheader.index('Packets published')
            item_pub = QtWidgets.QTableWidgetItem(str(npub))
            self.setItem(irow, colindex, item_pub)
            nrecv = d['device'].statistics['packets_received']
            colindex = self.colheader.index('Packets received')
            item_recv = QtWidgets.QTableWidgetItem(str(nrecv))
            self.setItem(irow, colindex, item_recv)

    def deviceViewClicked(self):
        funcname = __name__ + '.deviceViewClicked():'
        logger.debug(funcname)
        devicedict = self.sender().__devicedict
        tabindex = self.redvyprWidget.devicetabs.indexOf(devicedict['widget'])
        try:
            if tabindex > -1:
                self.redvyprWidget.devicetabs.setCurrentWidget(devicedict['widget'])
            else:
                devicedict['widget'].setFocus()
                devicedict['widget'].raise_()
                devicedict['widget'].activateWindow()
        except:
            logger.debug('View', exc_info=True)

    def deviceThreadStatusCheckAll(self):
        """
        Function checks the thread status of all devices and updates the buttons
        """
        for b in self.__startbuttons:
            device_tmp = b.__device
            startbutton = b
            status = device_tmp.get_thread_status()
            thread_status = status['thread_running']
            self.__update_start_button(startbutton, thread_status)
    def deviceThreadStatusChanged(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """
        device_tmp = self.sender()
        startbutton = None
        # Search for the correct startbutton
        for b in self.__startbuttons:
            if b.__device == device_tmp:
                startbutton = b
        # startbutton = self.__startbutton_clicked
        #print('Update!',device)
        status = device_tmp.get_thread_status()
        thread_status = status['thread_running']
        self.__update_start_button(startbutton, thread_status)

    def __update_start_button(self,startbutton, thread_status):
        if startbutton is not None:
            #print('Hall', status)
            #print('Hall', thread_status)
            # Running
            if (thread_status):
                startbutton.setText('Stop')
                startbutton.setChecked(True)
            # Not running
            else:
                startbutton.setText('Start')
                # Check if an error occured and the startbutton
                if (startbutton.isChecked()):
                    startbutton.setChecked(False)
                # self.conbtn.setEnabled(True)


    def deviceSubscribeClicked(self):
        funcname = __name__ + '.deviceSubscribeClicked()'
        button = self.sender()
        device = button.__device
        logger.debug(funcname + ':' + str(device))
        # self.__con_widget = redvyprConnectWidget(devices=self.redvypr.devices, device=device)
        self.__subscribeWidget = redvyprSubscribeWidget(redvypr=self.redvypr, device=device)
        self.__subscribeWidget.show()

    def deviceConfigureClicked(self):
        button = self.sender()
        funcname = __name__ + '.deviceConfigureClicked():'
        button = self.sender()
        device = button.__device
        logger.debug(funcname + ':' + str(device))
        self.__info_widget = redvypr_deviceInfoWidget(device)
        self.__info_widget.show()

    def deviceStartStopClicked(self):
        button = self.sender()
        #self.__startbutton_clicked = button
        device = button.__device
        if button.isChecked():
            logger.debug("button pressed")
            button.setText('Starting')
            device.thread_start()
            # self.device_start.emit(self.device)
        else:
            logger.debug('button released')
            button.setText('Stopping')
            button.setChecked(True)
            device.thread_stop()

    def loglevelChanged(self):
        devicedict = self.sender().__devicedict
        loglevel = self.sender().currentText()
        logger = devicedict['logger']
        logger.info('loglevel changed to {}'.format(loglevel))
        if(logger is not None):
            logger.setLevel(loglevel)


    def widgetlocChanged(self, index):
        """
        Functions checks if a device widget shall be attached to the tab layout
        or is a free floating window
        :param index:
        :return:
        """
        combo = self.sender()
        widgetloc = combo.currentText()
        devicewidget = combo.__devicedict['widget']
        device = combo.__device
        tabindex = self.redvyprWidget.devicetabs.indexOf(devicewidget)
        #print('Index', index, combo.__device, widgetloc, tabindex)
        widgetname = combo.__device.name
        if widgetloc == 'Window':
            if tabindex > -1:
                self.redvyprWidget.devicetabs.removeTab(tabindex)
                devicewidget.setParent(None)
                devicewidget.setWindowTitle(widgetname)
            device.device_parameter.gui_dock = widgetloc
            devicewidget.show()

        elif widgetloc == 'Hide':
            if tabindex > -1:
                self.redvyprWidget.devicetabs.removeTab(tabindex)
                devicewidget.setParent(None)
                devicewidget.setWindowTitle(widgetname)
            device.device_parameter.gui_dock = widgetloc
            devicewidget.show()
            devicewidget.hide()
        else:
            if tabindex == -1: #Add to tab, if not already there
                self.redvyprWidget.devicetabs.addTab(devicewidget, widgetname)
                device.device_parameter.gui_dock = widgetloc


class deviceTabWidget(QtWidgets.QTabWidget):
    def resizeEvent(self, event):
        #print("Window has been resized",event)
        #print('fds',event.size().width())
        wtran = event.size().width()-500
        #print('fsfsd',self.widget(1).width())
        self.setStyleSheet("QTabBar::tab:disabled {"+\
                        "width: {:d}px;".format(wtran)+\
                        "color: transparent;"+\
                        "background: transparent;}")
        super(deviceTabWidget, self).resizeEvent(event)



def get_QColor(data):
    """
    Returns a qcolor based on the data input, data can be either a string, a list of rgb or a dictionary of type {'r':250,'g':100,'b':0}
    """
    funcname = __name__ + '.get_QColor():'
    logger.debug(funcname)
    colordata = copy.deepcopy(data)
    #print('Colordata',colordata)
    #print('Type colordata', type(colordata))
    if(type(colordata) == str):
        color = QtGui.QColor(colordata)
    elif (type(colordata) == tuple):
        color = QtGui.QColor(colordata[0], colordata[1], colordata[2])
    elif (type(colordata) == list):
        color = QtGui.QColor(colordata[0], colordata[1], colordata[2])
    elif (type(colordata) == pydColor):
        colors = colordata.as_rgb_tuple()
        color = QtGui.QColor(colors[0], colors[1], colors[2])
    else:
        colors = colordata
        color = QtGui.QColor(colors['r'], colors['g'], colors['b'])

    return color

class redvyprAddDeviceWidget(QtWidgets.QWidget):
    """ A widget that lists all devices found in modules and in the python files included in the path list.

    """
    def __init__(self, redvypr_device_scan=None, redvypr=None):
        """

        Args:
            redvypr:
            device:
        """
        super(redvyprAddDeviceWidget, self).__init__()
        self.redvypr = redvypr
        if redvypr is not None:
            self.redvypr_device_scan = redvypr.redvypr_device_scan
        elif (redvypr_device_scan is not None):
            self.redvypr_device_scan = redvypr_device_scan
        else:
            self.redvypr_device_scan = device.RedvyprDeviceScan()

        # Update the devicetree
        self.create_tree_widget()
        self.update_tree_widget()
        self.create_deviceinfo_widget()
        # Create widgets for adding/removing devices
        self.addbtn = QtWidgets.QPushButton('Add')
        self.addbtn.clicked.connect(self.add_device_click)
        self.devnamelabel = QtWidgets.QLabel('Devicename')
        self.devname = QtWidgets.QLineEdit()
        self.mp_label = QtWidgets.QLabel('Multiprocessing options')
        self.mp_qthread = QtWidgets.QRadioButton('QThread')
        self.mp_thread = QtWidgets.QRadioButton('Thread')
        self.mp_multi = QtWidgets.QRadioButton('Multiprocessing')
        self.mp_group = QtWidgets.QButtonGroup()
        self.mp_group.addButton(self.mp_qthread)
        self.mp_group.addButton(self.mp_thread)
        self.mp_group.addButton(self.mp_multi)
        self.mp_qthread.setChecked(True)

        self.log_label = QtWidgets.QLabel('Loglevel')
        self.logwidget = QtWidgets.QComboBox()  # A Combobox to change the loglevel of the device
        # Fill the logwidget
        if (logger is not None):
            level = logger.getEffectiveLevel()
            levelname = logging.getLevelName(level)
            loglevels = ['INFO', 'DEBUG', 'WARNING', 'ERROR', 'CRITICAL']
            for i, l in enumerate(loglevels):
                self.logwidget.addItem(l)

            self.logwidget.setCurrentText(levelname)
        else:
            self.logwidget.addItem('NA')

        thread_layout = QtWidgets.QHBoxLayout()
        thread_layout.addWidget(self.mp_qthread)
        thread_layout.addWidget(self.mp_multi)
        thread_layout.addWidget(self.mp_thread)
        self.layout = QtWidgets.QFormLayout(self)
        self.layout.addRow(self.devicetree)
        self.layout.addRow(self.deviceinfo)
        self.layout.addRow(self.log_label,self.logwidget)
        self.layout.addRow(self.mp_label,thread_layout)
        #self.layout.addRow(self.mp_thread, self.mp_multi)
        self.layout.addRow(self.devnamelabel, self.devname)
        self.layout.addRow(self.addbtn)

        self.setWindowIcon(QtGui.QIcon(_icon_file))
        self.setWindowTitle("redvypr add device")

    def create_deviceinfo_widget(self):
        """
        Creates a widget that shows the device information
        Returns:

        """
        self.deviceinfo = QtWidgets.QWidget()  #
        self.deviceinfo_layout = QtWidgets.QFormLayout(self.deviceinfo)
        self.__devices_info_sourcelabel2 = QtWidgets.QLabel()
        self.__devices_info_sourcelabel4 = QtWidgets.QLabel()
        self.__devices_info_sourcelabel6 = QtWidgets.QLabel()
        self.deviceinfo_layout.addRow(QtWidgets.QLabel('Name'),self.__devices_info_sourcelabel2)
        self.deviceinfo_layout.addRow(QtWidgets.QLabel('Source'),self.__devices_info_sourcelabel4)
        self.deviceinfo_layout.addRow(QtWidgets.QLabel('Description'),self.__devices_info_sourcelabel6)

    def create_tree_widget(self):
        """
        Creates the QtreeWidget with the
        Returns:

        """
        self.devicetree = QtWidgets.QTreeWidget()  # All dataproviding devices
        self.devicetree.setColumnCount(1)
        #self.devicetree.setHeaderHidden(True)
        self.devicetree.setHeaderLabels(['Device'])
        self.devicetree.currentItemChanged.connect(self.__item_changed__)
        self.devicetree.itemDoubleClicked.connect(self.__apply_item__)
        self.devicetree.setSortingEnabled(True)

    def update_tree_widget(self):
        self.devicetree.clear()
        root = self.devicetree.invisibleRootItem()
        #moduleroot = QtWidgets.QTreeWidgetItem(['modules', ''])
        #root.addChild(moduleroot)
        def update_recursive(moddict,parentitem):
            try:
                keys = moddict.keys()
            except:
                keys = None

            if(keys is None):
                return
            else:
                for k in moddict.keys():
                    if(k == '__devices__'): # List of devices in the module
                        for devdict in moddict[k]:
                            devicename = devdict['name']
                            #print('devdict',devdict)
                            # remove trailing modules separated by '.'
                            devicename = devicename.split('.')[-1]
                            itm = QtWidgets.QTreeWidgetItem([devicename, ''])
                            itm.devdict = devdict # Add device information
                            parentitem.addChild(itm)
                    else:
                        # remove trailing modules separated by '.'
                        if '/' in k: # Check if its a path or a module file
                            ktxt = k
                        else:
                            ktxt = k.split('.')[-1]

                        itm = QtWidgets.QTreeWidgetItem([ktxt, ''])
                        itm.devdict = None # Not a device
                        parentitem.addChild(itm)
                        update_recursive(moddict[k],itm)

        #update_recursive(self.redvypr_device_scan.redvypr_devices['modules'],moduleroot)
        update_recursive(self.redvypr_device_scan.redvypr_devices, root)


        self.devicetree.expandAll()
        self.devicetree.resizeColumnToContents(0)
        self.devicetree.sortByColumn(0, QtCore.Qt.AscendingOrder)

    def __item_changed__(self, new, old):
        logger.debug('Item changed')
        if new.devdict is not None:
            self.__update_device_info__(new.devdict)
            self.addbtn.setEnabled(True)
        else:
            self.addbtn.setEnabled(False)

    def __apply_item__(self):
        logger.debug('Apply')

    def __update_device_info__(self,devdict):
        """ Populates the self.__devices_info widget with the info of the module
        """
        infotxt = devdict['name']
        self.__devices_info_sourcelabel2.setText(infotxt)
        infotxt2 = devdict['file']
        self.__devices_info_sourcelabel4.setText(infotxt2)
        try:
            desctxt = devdict['module'].description
        except Exception as e:
            desctxt = ''

        self.__devices_info_sourcelabel6.setText(desctxt)

    def __device_name(self):
        devicemodulename = self.__devices_list.currentItem().text()
        devicename = devicemodulename + '_{:d}'.format(self.redvypr.numdevice + 1)
        self.__devices_devname.setText(devicename)
        self.__device_info()

    def add_device_click(self):
        """ Adds the device
        """
        funcname = __name__ + 'add_device_click():'
        logger.debug(funcname)
        getSelected = self.devicetree.selectedItems()
        if getSelected:
            item = getSelected[0]

        if item.devdict is not None:
            devicemodulename = item.devdict['name']
            device_parameter = RedvyprDeviceParameter()
            if self.mp_thread.isChecked():
                device_parameter.multiprocess = 'thread'
            elif self.mp_qthread.isChecked():
                device_parameter.multiprocess = 'qthread'
            elif self.mp_multi.isChecked():
                device_parameter.multiprocess = 'multiprocessing'

            levelname = self.logwidget.currentText()
            device_parameter.loglevel = levelname
            devname = str(self.devname.text())
            if len(devname) > 0:
                device_parameter.name = devname

            logger.debug('devicemodulename {}'.format(devicemodulename))
            logger.debug('Adding device, config {}'.format(device_parameter))
            if self.redvypr is not None:
                self.redvypr.add_device(devicemodulename=devicemodulename, base_config=device_parameter)
            self.devname.clear()
            # Update the name
            #self.__device_name()
            # Closing
            self.close()
        else:
            logger.warning(funcname + 'Not a device')




#
#
#
# A logging handler for qplaintext
#
#
#
class QPlainTextEditLogger(logging.Handler):
    def __init__(self):
        super(QPlainTextEditLogger, self).__init__()

    def add_widget(self,widget):        
        self.widget = widget

    def emit(self, record):
        msg = self.format(record)
        self.widget.appendPlainText(msg)

    def write(self, m):
        pass   
    



#
#
# Widget shows the statistics of the device
#
#
class redvypr_deviceStatisticWidget(QtWidgets.QWidget):
    """
    Widgets shows the device statistic as text
    """
    def __init__(self, device = None, dt_update=1000):
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.device = device
        self.layout = QtWidgets.QGridLayout(self)
        self.infowidget       = QtWidgets.QPlainTextEdit()
        self.infowidget.setReadOnly(True)
        self.layout.addWidget(self.infowidget,0,0)

        self.__update_info()
        # Todo, let the user choose for an update
        #self.updatetimer = QtCore.QTimer()
        #self.updatetimer.timeout.connect(self.__update_info)
        #self.updatetimer.start(dt_update)

    def __update_info(self):
        funcname = __name__ + '.__update_info():'
        prev_cursor = self.infowidget.textCursor()
        pos  = self.infowidget.verticalScrollBar().value()
        pos2 = self.infowidget.verticalScrollBar().value()
        self.infowidget.clear()
        sortstat = {}
        for i in sorted(self.device.statistics):
            sortstat[i]=self.device.statistics[i]

        sortstat['datakeys'] = sorted(sortstat['datakeys'])
        statstr = yaml.dump(sortstat)
        self.infowidget.insertPlainText(statstr + '\n')
        #self.infowidget.moveCursor(QtGui.QTextCursor.End)
        # cursor.setPosition(0)
        # self.text.setTextCursor(prev_cursor)
        if True:
            self.infowidget.verticalScrollBar().setValue(pos)

class redvypr_deviceInfoWidget(QtWidgets.QWidget):
    """
    Information widget of a device
    """
    connect = QtCore.pyqtSignal(
        RedvyprDevice)  # Signal requesting a connect of the datainqueue with available dataoutqueues of other devices
    def __init__(self, device = None, dt_update = 1000):
        funcname = __name__ + '.__init__():'
        logger.debug(funcname)
        super().__init__()
        self.device = device
        self.setWindowTitle(device.name)
        self.layout = QtWidgets.QGridLayout(self)
        tstr = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.update_label = QtWidgets.QLabel('Last update {:s}'.format(tstr))
        self.packetRecv_label = QtWidgets.QLabel('Packets received {:d}'.format(0))
        self.packetPubl_label = QtWidgets.QLabel('Packets published {:d}'.format(0))
        self.publist_label = QtWidgets.QLabel('Publishes to')
        self.publist = QtWidgets.QListWidget()
        self.sublist_label = QtWidgets.QLabel('Subscribed devices')
        self.sublist = QtWidgets.QListWidget()
        #self.subBtn = QtWidgets.QPushButton('Subscribe')
        #self.subBtn.clicked.connect(self.connect_clicked)
        self.metadataBtn = QtWidgets.QPushButton('Edit Device Metadata')
        self.metadataBtn.clicked.connect(self.metadata_clicked)
        if self.device.publishes:
            self.ddBtn = QtWidgets.QPushButton('Edit Datastream Metadata')
            self.ddBtn.clicked.connect(self.data_devices_clicked)
        self.confBtn = QtWidgets.QPushButton('Configure')
        self.confBtn.clicked.connect(self.config_clicked)
        self.statBtn = QtWidgets.QPushButton('Statistics')
        self.statBtn.clicked.connect(self.statistics_clicked)
        self.layout.addWidget(self.update_label)
        self.layout.addWidget(self.packetRecv_label)
        self.layout.addWidget(self.packetPubl_label)
        self.layout.addWidget(self.sublist_label)
        self.layout.addWidget(self.sublist)
        self.layout.addWidget(self.publist_label)
        self.layout.addWidget(self.publist)
        self.layout.addWidget(self.statBtn)
        if self.device.publishes:
            self.layout.addWidget(self.ddBtn)
        self.layout.addWidget(self.confBtn)
        self.layout.addWidget(self.metadataBtn)

        self.updatetimer = QtCore.QTimer()
        self.updatetimer.timeout.connect(self.__update_info)
        self.updatetimer.start(dt_update)

    def data_devices_clicked(self):
        funcname = __name__ + '.data_devices_clicked():'
        try:
            self.data_device_widget.setParent(None)
        except:
            pass

        # Filter the addresses
        device_filter_address = RedvyprAddress(uuid=self.device.address.uuid,publisher=self.device.address.publisher)
        filter_include = [device_filter_address]
        #print('Filter include',filter_include)
        #self.data_device_widget = datastreamWidget(redvypr=self.device.redvypr,filter_include=filter_include)
        self.data_device_widget = datastreamMetadataWidget(redvypr=self.device.redvypr, device=self.device, filter_include=filter_include)
        self.data_device_widget.setWindowTitle(self.device.name)
        self.data_device_widget.show()

    def config_clicked(self):
        funcname = __name__ + '.config_clicked():'
        logger.debug(funcname)
        self.config_widget = pydanticDeviceConfigWidget(self.device)
        #targetWidget.showFullScreen()
        self.config_widget.showMaximized()

    def metadata_clicked(self):
        funcname = __name__ + '.metadata_clicked():'
        logger.debug(funcname)
        metadata_device = copy.deepcopy(self.device.statistics['metadata'])
        deviceAddress = RedvyprAddress(devicename=self.device.name)
        try:
            metadata_raw = metadata_device[deviceAddress.address_str]
        except:
            logger.info('Could not load metadata', exc_info=True)
            metadata_raw = {}

        metadata = RedvyprDeviceMetadata(**metadata_raw)
        print('Metadata',metadata)
        self.__metadata_edit = metadata
        self.__metadata_address = deviceAddress
        self.metadata_config = pydanticConfigWidget(metadata, configname=deviceAddress.address_str)
        self.metadata_config.config_editing_done.connect(self.metadata_config_apply)
        self.metadata_config.show()

    def metadata_config_apply(self):
        funcname = __name__ + '.metadata_config_apply():'
        logger.debug(funcname)

        print('Metadata new',self.__metadata_edit)
        metadata = self.__metadata_edit.model_dump()
        self.device.set_metadata(self.__metadata_address, metadata)

    def statistics_clicked(self):
        funcname = __name__ + '.statistics_clicked():'
        logger.debug(funcname)
        self.statistics_widget = redvypr_deviceStatisticWidget(device=self.device)
        self.statistics_widget.show()

    def subscribe_clicked(self):
        funcname = __name__ + '.subscribe_clicked():'
        logger.debug(funcname)
        button = self.sender()
        self.__subscribeWidget = redvyprSubscribeWidget(redvypr=self.redvypr, device=self.device)
        self.__subscribeWidget.show()
        #self.connect.emit(self.device)

    def __update_info(self):
        funcname = __name__ + '.__update_info():'
        #logger.debug(funcname)
        tstr = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.update_label.setText('Last update {:s}'.format(tstr))
        nrecv = self.device.statistics['packets_received']
        npub = self.device.statistics['packets_published']
        self.packetRecv_label.setText('Packets received {:d}'.format(nrecv))
        self.packetPubl_label.setText('Packets published {:d}'.format(npub))

        devs = self.device.get_subscribed_devices()
        self.sublist.clear()
        for d in devs:
            devname = d.name
            self.sublist.addItem(devname)

        devs_sub = self.device.publishing_to()
        self.publist.clear()
        for d in devs_sub:
            devname = d.name
            self.publist.addItem(devname)

