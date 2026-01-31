import copy
import datetime
import pytz
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import qtawesome
import time
import yaml
import numpy
import logging
import sys
import pydantic
import redvypr
from redvypr.data_packets import check_for_command
from redvypr.device import RedvyprDevice
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.devices.sensors.generic_sensor.calibrationWidget import GenericSensorCalibrationWidget
import redvypr.devices.sensors.generic_sensor.sensor_definitions as sensor_definitions
from redvypr.device import RedvyprDevice, RedvyprDeviceParameter
from . import sensor_firmware_config
from . import nmea_mac64_utils
from . import tar_process
from redvypr.utils.databuffer import DatapacketAvg

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.tar')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True




class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Processes data from temperature array sensors'
    gui_tablabel_display: str = 'Temperature array (TAR)'

class DeviceCustomConfig(pydantic.BaseModel):
    merge_tar_chain: bool = pydantic.Field(default=False, description='Merges a chain of TAR sensors into one packet')
    publish_single_sensor_sentence: bool = pydantic.Field(default=False, description='Publishes the very raw data, not merged, just parsed')
    publish_raw_sensor: bool = True
    size_packetbuffer: int = 10
    convert_files: list = pydantic.Field(default=[], description='Convert the files in the list')


def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger_thread = logging.getLogger('redvypr.device.tar.start')
    logger_thread.setLevel(logging.DEBUG)
    logger_thread.debug(funcname)
    tar_processor = tar_process.TarProcessor()
    metadata_dict = {} # Store the metadata

    metadata_packets = tar_processor.create_metadata_packets()
    for p in metadata_packets:
        dataqueue.put(p)

    if len(config['convert_files']):
        logger_thread.info('Converting datafiles')
        for fname in config['convert_files']:
            logger_thread.info('Converting {}'.format(fname))
            tar_processor.process_file(fname)
            tar_processor.to_ncfile()


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

        #print("Got data",datapacket.keys())
        try:
            # This needs to be refined with the datastreams
            datapacket['data']
            #print('Data', datapacket['data'])
            #print('Done done done')
        except:
            continue

        #print("Processing data:")
        #print(f"{datapacket['data']=}")
        merged_packets = tar_processor.process_rawdata(datapacket['data'])
        if merged_packets['metadata'] is not None:
            for ppub in merged_packets['metadata']:
                # Publish the data
                dataqueue.put(ppub)
        if merged_packets['merged_packets'] is not None:
            if config['publish_raw_sensor']:
                for ppub in merged_packets['merged_packets']:
                    atmp = redvypr.RedvyprAddress(ppub)
                    pkid = atmp.packetid
                    #print("Atmp",atmp)
                    # Metadata
                    if pkid not in metadata_dict.keys():
                        pass
                        #print("New metadata")

                    # Publish the data
                    dataqueue.put(ppub)

        if merged_packets['merged_tar_chain'] is not None:
            for ppub in merged_packets['merged_tar_chain']:
                #print('Publishing merged tar chain')
                #print('Publishing merged tar chain')
                #print('Publishing merged tar chain',ppub)
                dataqueue.put(ppub)

    return None

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
        self.root_raw = QtWidgets.QTreeWidgetItem(['raw'])
        self.root_single = QtWidgets.QTreeWidgetItem(['single sensor'])
        self.root_tar = QtWidgets.QTreeWidgetItem(['tar merged'])
        root.addChild(self.root_tar)
        root.addChild(self.root_single)
        root.addChild(self.root_raw)

        # 1. GroupBox erstellen
        self.filter_group = QtWidgets.QWidget()
        self.filter_layout = QtWidgets.QHBoxLayout(
            self.filter_group)  # Horizontal anordnen

        self.filter_layout.setContentsMargins(0, 0, 0, 0)
        # Setzt den Abstand zwischen den Checkboxen auf einen kleinen Wert (z.B. 10px)
        self.filter_layout.setSpacing(10)
        # Verhindert, dass das Widget vertikalen Platz beansprucht, der ihm nicht zusteht
        self.filter_group.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                                        QtWidgets.QSizePolicy.Maximum)
        # 2. Checkboxen erstellen
        self.cb_raw = QtWidgets.QCheckBox("Raw")
        self.cb_single = QtWidgets.QCheckBox("Single")
        self.cb_chain = QtWidgets.QCheckBox("Chain")

        # 3. Standardwerte & Signale (wie zuvor)
        for cb, item in zip([self.cb_raw, self.cb_single, self.cb_chain],
                            [self.root_raw, self.root_single, self.root_tar]):
            cb.setChecked(True)
            # Lambda nutzt 'item=item', um den aktuellen Wert in der Schleife zu binden
            cb.stateChanged.connect(
                lambda state, i=item, c=cb: i.setHidden(not c.isChecked()))
            self.filter_layout.addWidget(cb)

        self.filter_layout.addStretch(1)
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
        self.layout.addWidget(self.filter_group)
        self.layout.addWidget(self.splitter)
        self.devicetree.currentItemChanged.connect(self.devicetree_item_changed)
        self.files_button = QtWidgets.QPushButton("Convert file(s)")
        self.files_button.clicked.connect(self.choose_files_clicked)



        self.config_widgets.append(self.files_button)
        #self.layout_buttons.removeWidget(self.subscribe_button)
        self.layout_buttons.removeWidget(self.configure_button)
        self.layout_buttons.addWidget(self.files_button, 2, 2, 1, 1)
        self.layout_buttons.addWidget(self.configure_button, 2, 3, 1, 1)



    def update_tree_visibility(self):
        self.root_raw.setHidden(not self.cb_raw.isChecked())
        self.root_single.setHidden(not self.cb_single.isChecked())
        self.root_tar.setHidden(not self.cb_chain.isChecked())

        # Falls das aktuell selektierte Item jetzt unsichtbar ist -> Selektion löschen
        current = self.devicetree.currentItem()
        if current and current.isHidden():
            self.devicetree.setCurrentItem(None)


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
        logger.info('Plot clicked')
        #print('Itemclicked',itemclicked)
        #print(self.device.redvypr.redvypr_device_scan.redvypr_devices)
        if True:
            try:
                plotdevice = itemclicked.__plotdevice__
            except:
                plotdevice = None

            if plotdevice is None:
                logger.debug('Creating PcolorPlotDevice')
                mac = itemclicked.__mac__
                datatype = itemclicked.__datatype__
                packets = self.packetbuffer[mac][datatype]['packets']
                if "pos" in datatype: # Plot the position as xy-plot
                    print('Plotting position')
                    address_tmp = itemclicked.__address__
                    address_x = redvypr.RedvyprAddress(address_tmp, datakey='pos_x')
                    address_y = redvypr.RedvyprAddress(address_tmp, datakey='pos_z')

                    devicemodulename = 'redvypr.devices.plot.XYPlotDevice'
                    plotname = 'XYPlot_{}_{}'.format(mac, address_y.datakey)
                    device_parameter = RedvyprDeviceParameter(name=plotname)
                    custom_config = redvypr.devices.plot.XYPlotDevice.DeviceCustomConfig(datetick_x=False)
                    custom_config.lines[0].databuffer_add_mode = 'clear first'
                    custom_config.lines[0].x_addr = redvypr.RedvyprAddress(address_x)
                    custom_config.lines[0].y_addr = redvypr.RedvyprAddress(address_y)
                    custom_config.lines[0].label = 'pos x,z'
                    custom_config.lines[0].label_format = '{NAME}'
                    print('Config line',custom_config.lines[0])
                    plotdevice = self.device.redvypr.add_device(
                        devicemodulename=devicemodulename,
                        base_config=device_parameter,
                        custom_config=custom_config)

                    itemclicked.__plotdevice__ = plotdevice
                    logger.debug('Starting plot device')
                    # Update the plot widget with the data in the buffer
                    for ip, p in enumerate(packets):
                        for (guiqueue, widget) in plotdevice.guiqueues:
                            print("updating with",p)
                            widget.update_data(p, force_update=True)
                    plotdevice.thread_start()
                    button.__plotdevice__ = plotdevice
                else: # otherwise as pcolorplot
                    packetid = itemclicked.__packetid__
                    datastream = redvypr.RedvyprAddress(packetid=packetid,datakey=datatype)
                    custom_config = redvypr.devices.plot.PcolorPlotDevice.DeviceCustomConfig(datastream=datastream)
                    devicemodulename = 'redvypr.devices.plot.PcolorPlotDevice'
                    plotname = 'Pcolor({})'.format(mac)
                    device_parameter = RedvyprDeviceParameter(name=plotname,autostart=True)
                    plotdevice = self.device.redvypr.add_device(devicemodulename=devicemodulename,
                                                   base_config=device_parameter, custom_config=custom_config)

                    itemclicked.__plotdevice__ = plotdevice
                    # Update the plot widget with the data in the buffer
                    for ip,p in enumerate(packets):
                        for (guiqueue, widget) in plotdevice.guiqueues:
                            widget.update_data(p)

                    logger.debug('Starting plot device')
                    plotdevice.thread_start()
                    button.__plotdevice__ = plotdevice
                #button.setText('Close')

    def parameter_plot_button_clicked(self, row):
        funcname = __name__ + 'parameter_plot_button_clicked():'
        print(funcname)
        print('Row',row)
        button = self.sender()
        print('Button',button.__address__)
        address_tmp = button.__address__
        address = redvypr.RedvyprAddress(redvypr.RedvyprAddress(address_tmp).to_address_string("k,i,p,d,u"))
        #address = address_tmp
        logger.info(funcname + "Address for plotting:{}".format(address))
        mac = button.__mac__
        datatype = button.__datatype__
        packetid = button.__packetid__
        if True:
            try:
                button.__plotdevice__
            except:
                devicemodulename = 'redvypr.devices.plot.XYPlotDevice'
                plotname = 'XYPlot({},{})'.format(mac,address.datakey)
                device_parameter = RedvyprDeviceParameter(name=plotname)
                custom_config = redvypr.devices.plot.XYPlotDevice.DeviceCustomConfig()
                custom_config.lines[0].y_addr = redvypr.RedvyprAddress(address)
                plotdevice = self.device.redvypr.add_device(devicemodulename=devicemodulename,
                                                            base_config=device_parameter,
                                                            custom_config=custom_config)

                packets = self.packetbuffer[mac][datatype]['packets']
                # Update the plot widget with the data in the buffer
                for ip, p in enumerate(packets):
                    for (guiqueue, widget) in plotdevice.guiqueues:
                        widget.update_data(p, force_update=True)

                logger.debug('Starting plot device')
                plotdevice.thread_start()
                button.__plotdevice__ = plotdevice
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
        #print("Got data",data)
        address_packet = redvypr.RedvyprAddress(data)
        datatypes_plot = ['T','R','acc','gyro','mag','T_IMU','pos_x','pos_y','pos_z']
        try:
            funcname = __name__ + '.update_data():'
            tnow = time.time()
            #print(funcname + 'Got some data', data)

            packetid = data['_redvypr']['packetid']
            #print('Got packet',packetid)
            for datatype in datatypes_plot:
                icols = []  # The columns in the table that will be updated
                datatars = []  # The data in the columns to be updated
                colheaders = []
                headerlabels = {}
                # Check if datakeys has 'R' or 'T'
                if datatype in data.keys():
                    datatar = data[datatype]
                    icol = 0
                    icols.append(icol)
                    datatars.append(datatar)
                    colheaders.append(datatype)
                else:
                    continue

                # Create new column for plot
                if True:
                    icols.append(1)
                    datatars.append(None)
                    colheaders.append('Plot')

                # If nothing to display
                if len(icols) == 0:
                    return

                # Get data from packet
                try:
                    np = data['np']
                    mac = data['mac']
                    counter = data['t']
                except:
                    #logger.info('Could not get data', exc_info=True)
                    return

                try:
                    parents = data['parents']
                except:
                    parents = []

                #print("packetid",data['_redvypr']['packetid'],'parents',parents)
                macs_tarchain = parents + [mac]
                if "raw" in packetid:
                    parentitm = self.root_raw
                elif "tar_chain" in packetid:
                    parentitm = self.root_tar
                else:
                    parentitm = self.root_single
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
                        itm_datatype.__address__ = address_packet
                        itm.addChild(itm_datatype)
                        flag_tree_update = True
                        # Button erstellen und zur Zelle hinzufügen
                        button = QtWidgets.QPushButton("Plot")
                        button.setCheckable(False)
                        button.clicked.connect(lambda _, item=itm_datatype: self.devicetree_plot_button_clicked(item))
                        # Button in die dritte Spalte des TreeWidgetItems einfügen
                        self.devicetree.setItemWidget(itm_datatype, 2, button)

                    #parentitm = itm
                    tmpdict = tmpdict_new

                if flag_tree_update:
                    #self.devicetree.expandAll()
                    self.devicetree.resizeColumnToContents(0)
                    #self.devicetree.sortByColumn(0, QtCore.Qt.AscendingOrder)

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
                                datakey = "{}[{}]".format(datatype,i)
                                address = redvypr.RedvyprAddress(data, datakey = datakey)
                                datastr = "{:4f}".format(d)
                                # Button erstellen und zur Zelle hinzufügen
                                button = QtWidgets.QPushButton("Plot")
                                button.setCheckable(False)
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
        except:
            logger.debug('Could not update data',exc_info=True)

