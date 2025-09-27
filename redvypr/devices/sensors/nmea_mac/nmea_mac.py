import copy
import datetime
import pytz
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import qtawesome
import time
import logging
import sys
import pydantic
import redvypr
from redvypr.data_packets import check_for_command
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from . import nmea_mac_process
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import Datapacket

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.sensors.nmea_mac')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Processes data from sensors of the type NMEA MAC type'
    gui_tablabel_display: str = 'NMEA MAC'

class DeviceCustomConfig(pydantic.BaseModel):
    convert_files: list = pydantic.Field(default=[], description='Convert the files in the list')
    size_packetbuffer: int = 10
    datastream: RedvyprAddress = pydantic.Field(default=RedvyprAddress("data"))


def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger_thread = logging.getLogger('redvypr.device.nmea_mac.start')
    logger_thread.setLevel(logging.DEBUG)
    logger_thread.debug(funcname)
    nmea_mac_processer = nmea_mac_process.NMEAMacProcessor()

    if len(config['convert_files']):
        logger_thread.info('Converting datafiles')
        for fname in config['convert_files']:
            logger_thread.info('Converting {}'.format(fname))
            nmea_mac_processer.process_file(fname)
            nmea_mac_processer.to_ncfile()


    while True:
        datapacket = datainqueue.get()
        [command, comdata] = check_for_command(datapacket, thread_uuid=device_info['thread_uuid'],
                                               add_data=True)
        if command is not None:
            logger.debug('Command is for me: {:s}'.format(str(command)))
            if command == 'stop':
                logger.info(funcname + 'received command:' + str(datapacket) + ' stopping now')
                logger.debug('Stop command')
                return

        # Checking for datakey, if existing, process data, TODO: Replace with address
        try:
            print(config["datastream"])
            rawdata = Datapacket(datapacket)[config["datastream"]]
            print("Rawdata",rawdata)
        except:
            logger.info("Could not get data",exc_info=True)
            rawdata = None

        if rawdata is not None:
            processed_packets = nmea_mac_processer.process_rawdata(rawdata)
            print(processed_packets)
            if len(processed_packets['merged'])>0:
                for ppub in processed_packets['merged']:
                        print('Publishing',ppub)
                        dataqueue.put(ppub)


class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.show_numpackets = 1
        self.packetbuffer = {}
        self.qtreebuffer = {} # A buffer for the device qtree
        self.devicetree = QtWidgets.QTreeWidget(self)
        self.devicetree.setColumnCount(3)
        # self.devicetree.setHeaderHidden(True)
        self.devicetree.setHeaderLabels(['MAC','Datatype','Plot'])
        root = self.devicetree.invisibleRootItem()
        self.root_data = QtWidgets.QTreeWidgetItem(['data'])
        root.addChild(self.root_data)
        self.datadisplaywidget = QtWidgets.QWidget(self)
        self.splitter = QtWidgets.QSplitter()
        self.splitter.addWidget(self.devicetree)
        self.splitter.addWidget(self.datadisplaywidget)
        #self.splitter.setStretchFactor(0, 0)  #
        #self.splitter.setStretchFactor(1, 1)  # Stretch the right one
        self.splitter.setHandleWidth(2)
        self.datadisplaywidget_layout = QtWidgets.QHBoxLayout(self.datadisplaywidget)
        self.tabwidget = QtWidgets.QTabWidget()
        self.datadisplaywidget_layout.addWidget(self.tabwidget)
        self.layout.addWidget(self.splitter)
        self.devicetree.currentItemChanged.connect(self.devicetree_item_changed)
        self.files_button = QtWidgets.QPushButton("Convert file(s)")
        self.files_button.clicked.connect(self.choose_files_clicked)
        self.config_widgets.append(self.files_button)
        #self.layout_buttons.removeWidget(self.subscribe_button)
        self.layout_buttons.removeWidget(self.configure_button)
        self.layout_buttons.addWidget(self.files_button, 2, 2, 1, 1)
        self.layout_buttons.addWidget(self.configure_button, 2, 3, 1, 1)


    def choose_files_clicked(self):
        options = QtWidgets.QFileDialog.Options()
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Choose tar file(s)", "",
                                                "All Files (*);;Text Files (*.txt)", options=options)
        if files:
            self.device.custom_config.convert_files = files
            for file in files:
                print(file)
    def devicetree_item_changed(self, itemnew, itemold):
        funcname = __name__ + '.devicetree_item_changed():'
        try:
            mac = itemnew.__mac__
            datatype = itemnew.__datatype__
        except:
            return

        table = self.packetbuffer[mac][datatype]['table']
        self.tabwidget.setCurrentWidget(table)

    def devicetree_plot_button_clicked(self, itemclicked):
        button = self.sender()
        #print('Itemclicked',itemclicked)
        #print(self.device.redvypr.redvypr_device_scan.redvypr_devices)
        if button.isChecked() == False:
            logger.debug('Closing plot')
            try:
                self.device.redvypr.redvypr_widget.closeDevice(button.__plotdevice__)
                delattr(button, '__plotdevice__')
                delattr(itemclicked,'__plotdevice__')
                button.setText('Plot')
            except:
                logger.debug('Could not close device',exc_info=True)
                button.setChecked(True)
        else:
            try:
                plotdevice = itemclicked.__plotdevice__
            except:
                plotdevice = None

            if plotdevice is None:
                logger.debug('Creating PcolorPlotDevice')
                mac = itemclicked.__mac__
                datatype = itemclicked.__datatype__
                packetid = itemclicked.__packetid__
                datastream = redvypr.RedvyprAddress(packetid=packetid,datakey=datatype)
                custom_config = redvypr.devices.plot.PcolorPlotDevice.DeviceCustomConfig(datastream=datastream)
                devicemodulename = 'redvypr.devices.plot.PcolorPlotDevice'
                plotname = 'Pcolor({})'.format(mac)
                device_parameter = RedvyprDeviceParameter(name=plotname,autostart=True)
                plotdevice = self.device.redvypr.add_device(devicemodulename=devicemodulename,
                                               base_config=device_parameter, custom_config=custom_config)

                itemclicked.__plotdevice__ = plotdevice
                packets = self.packetbuffer[mac][datatype]['packets']
                # Update the plot widget with the data in the buffer
                for ip,p in enumerate(packets):
                    for (guiqueue, widget) in plotdevice.guiqueues:
                        widget.update_plot(p)

                #logger.debug('Starting plot device')
                #plotdevice.thread_start()
                button.__plotdevice__ = plotdevice
                button.setText('Close')

    def parameter_plot_button_clicked(self, row):
        funcname = __name__ + 'parameter_plot_button_clicked():'
        print(funcname)
        print('Row',row)
        button = self.sender()
        print('Button',button.__address__)
        address = button.__address__
        mac = button.__mac__
        datatype = button.__datatype__
        packetid = button.__packetid__
        if button.isChecked():
            try:
                button.__plotdevice__
            except:
                devicemodulename = 'redvypr.devices.plot.XYPlotDevice'
                plotname = 'XYPlot({},{})'.format(mac,address.datakey)
                device_parameter = RedvyprDeviceParameter(name=plotname, autostart=True)
                xaddr = redvypr.RedvyprAddress(datakey="t")
                #print("Addresses",address,xaddr)
                custom_config = redvypr.devices.plot.XYPlotDevice.DeviceCustomConfig()
                custom_config.lines[0].y_addr = redvypr.RedvyprAddress(address)
                custom_config.lines[0].x_addr = xaddr
                plotdevice = self.device.redvypr.add_device(devicemodulename=devicemodulename,
                                                            base_config=device_parameter,
                                                            custom_config=custom_config)

                packets = self.packetbuffer[mac][datatype]['packets']
                # Update the plot widget with the data in the buffer
                for ip, p in enumerate(packets):
                    for (guiqueue, widget) in plotdevice.guiqueues:
                        widget.update_plot(p, force_update=True)

                logger.debug('Starting plot device')
                plotdevice.thread_start()
                button.__plotdevice__ = plotdevice
                button.setText('Close')
        else:
            try:
                self.device.redvypr.redvypr_widget.closeDevice(button.__plotdevice__)
                delattr(button,'__plotdevice__')
                button.setText('Plot')
            except:
                logger.info('Could not close device',exc_info=True)
                button.setChecked(True)

    def update_data(self, data):
        """
        """
        try:
            funcname = __name__ + '.update_data():'
            tnow = time.time()
            #print(funcname + 'Got some data', data)
            datatype = None
            icols = []  # The columns in the table that will be updated
            datatars = [] # The data in the columns to be updated
            colheaders = []
            headerlabels = {}
            packetid = data['_redvypr']['packetid']
            # Get data from packet
            try:
                np = data['np']
                mac = data['mac']
                counter = data['t']
            except:
                #logger.info('Could not get data', exc_info=True)
                return
            #print('Got packet',packetid)
            for datatype in ["R","T"]:
                # Check if datakeys has 'R' or 'T'
                if datatype in data.keys():
                    datatar = data[datatype]
                    icol = 0
                    icols.append(icol)
                    datatars.append(datatar)
                    colheaders.append(datatype)

                if True:
                    icols.append(1)
                    datatars.append(None)
                    colheaders.append('Plot')

                # If nothing to display
                if len(icols) == 0:
                    return



                try:
                    parents = data['parents']
                except:
                    parents = []

                macs_tarchain = parents + [mac]
                parentitm = self.root_data
                #print('mac', mac, 'Macs', macs_tarchain)
                tmpdict = self.qtreebuffer
                flag_tree_update = False
                for mac_qtree in macs_tarchain:
                    try:
                        itm = tmpdict[mac_qtree]['item']
                        tmpdict_new = tmpdict[mac_qtree]
                    except:
                        logger.info('did not work', exc_info=True)
                        itm = QtWidgets.QTreeWidgetItem([mac_qtree, ''])
                        tmpdict_new = {'item': itm}
                        tmpdict[mac_qtree] = tmpdict_new
                        parentitm.addChild(itm)
                        flag_tree_update = True

                    try:
                        itm_datatype = tmpdict_new['item_' + datatype]
                    except:
                        itm_datatype = QtWidgets.QTreeWidgetItem([packetid, datatype])
                        tmpdict_new['item_' + datatype] = itm_datatype
                        itm_datatype.__mac__ = mac
                        itm_datatype.__datatype__ = datatype
                        itm_datatype.__packetid__ = packetid
                        itm.addChild(itm_datatype)
                        flag_tree_update = True
                        # Button erstellen und zur Zelle hinzufügen
                        button = QtWidgets.QPushButton("Plot")
                        button.setCheckable(True)
                        button.clicked.connect(lambda _, item=itm_datatype: self.devicetree_plot_button_clicked(item))
                        # Button in die dritte Spalte des TreeWidgetItems einfügen
                        self.devicetree.setItemWidget(itm_datatype, 2, button)
                    parentitm = itm
                    tmpdict = tmpdict_new



                # Test if packetbuffer exists
                try:
                    self.packetbuffer[mac]
                except:
                    self.packetbuffer[mac] = {}

                # update the table packetbuffer
                try:
                    self.packetbuffer[mac][datatype]
                except:
                    self.packetbuffer[mac][datatype] = {'packets': []}

                self.packetbuffer[mac][datatype]['packets'].append(data)
                # if len(self.packetbuffer[mac][datatype]['packets']) > self.show_numpackets:
                if len(self.packetbuffer[mac][datatype]['packets']) > self.device.custom_config.size_packetbuffer:
                    self.packetbuffer[mac][datatype]['packets'].pop(0)

                # Update the table
                irows = ['mac', 'np', 't']  # Rows to plot
                try:
                    table = self.packetbuffer[mac][datatype]['table']
                except:
                    table = QtWidgets.QTableWidget()
                    self.packetbuffer[mac][datatype]['table'] = table
                    table.setRowCount(len(datatar) + len(irows) - 1)
                    numcols = len(icols)
                    # print('Numcols')
                    table.setColumnCount(numcols)
                    # self.datadisplaywidget_layout.addWidget(table)
                    self.tabwidget.addTab(table, '{} {}'.format(mac, datatype))
                    headerlabels = [datatype]
                    table.setHorizontalHeaderLabels(headerlabels)
                    # Create plot buttons
                    if True:

                        try:
                            for irow, key in enumerate(irows):
                                pass
                                #d = data[key]
                                #dataitem = QtWidgets.QTableWidgetItem(str(d))
                                #table.setItem(irow, icol, dataitem)

                            # And now the real data
                            for i, d in enumerate(datatar):
                                rdata = redvypr.Datapacket(data)
                                datakey = "['{}'][{}]".format(datatype,i)
                                address = redvypr.RedvyprAddress(data, datakey = datakey)
                                datakey = "{}".format(datatype)
                                address = redvypr.RedvyprAddress(data, datakey = datakey)
                                datastr = "{:4f}".format(d)
                                # Button erstellen und zur Zelle hinzufügen
                                button = QtWidgets.QPushButton("Plot")
                                button.setCheckable(True)
                                #button.clicked.connect(
                                #    lambda _, item=itm_datatype: self.devicetree_plot_button_clicked(item))
                                dataitem = QtWidgets.QTableWidgetItem(datastr)
                                irowtar = i + irow
                                button.clicked.connect(self.parameter_plot_button_clicked)
                                button.__address__ = address
                                button.__mac__ = mac
                                button.__datatype__ = datatype
                                button.__packetid__ = packetid
                                icol = 1
                                table.setCellWidget(irowtar, icol, button)
                        except:
                            logger.info('Could not add button', exc_info=True)

                for icol,datatar,colheader in zip(icols,datatars,colheaders):
                    # update the table packetbuffer
                    if datatar is not None:
                        try:
                            #print('Icol',icol)
                            # First the metadata
                            for irow,key in enumerate(irows):
                                d = data[key]
                                dataitem = QtWidgets.QTableWidgetItem(str(d))
                                table.setItem(irow, icol, dataitem)
                            # And now the real data
                            for i, d in enumerate(datatar):
                                datastr = "{:4f}".format(d)
                                dataitem = QtWidgets.QTableWidgetItem(datastr)
                                irowtar = i + irow
                                table.setItem(irowtar, icol, dataitem)
                        except:
                            logger.info('Does not work',exc_info=True)

                table.resizeColumnsToContents()
            # update qtreewidget
            if flag_tree_update:
                # self.devicetree.expandAll()
                self.devicetree.resizeColumnToContents(0)
                # self.devicetree.sortByColumn(0, QtCore.Qt.AscendingOrder)
        except:
            logger.debug('Could not update data',exc_info=True)

