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
    merge_tar_chain: bool = pydantic.Field(default=True, description='Merges a chain of TAR sensors into one packet')
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

        try:
            print('Data', datapacket['data'])
            print('Done done done')
        except:
            continue

        merged_packets = tar_processor.process_rawdata(datapacket['data'])
        if merged_packets['merged_packets'] is not None:
            if config['publish_raw_sensor']:
                for ppub in merged_packets['merged_packets']:
                    print('Publishing')
                    print('Publishing')
                    #print('Publishing',ppub)
                    dataqueue.put(ppub)

        if merged_packets['merged_tar_chain'] is not None:
            for ppub in merged_packets['merged_tar_chain']:
                print('Publishing merged tar chain')
                print('Publishing merged tar chain')
                #print('Publishing merged tar chain',ppub)
                dataqueue.put(ppub)

    if False:
        packetbuffer_tar = {}  # A buffer to add split messages into one packet
        #packetbuffer = {-1000:None} # Add a dummy key
        packetbuffer = {}
        np_lastpublished = -1000
        csv_save_data = {}
        sensors_datasizes = {}

        # Create the tar sensors
        datatypes = []
        sensors = []

        tarv2nmea_T = sensor_definitions.BinarySensor(name='tarv2nmea_T', regex_split=tarv2nmea_T_split,
                                                             str_format=tarv2nmea_T_str_format,
                                                             autofindcalibration=False,
                                                             description=tarv2nmea_T_description,
                                                             datakey_metadata=tarv2nmea_T_datakey_metadata,
                                                             packetid_format=tarv2nmea_T_packetid_format,
                                                             datastream=redvypr.RedvyprAddress('/k:data'))

        tarv2nmea_R = sensor_definitions.BinarySensor(name='tarv2nmea_R', regex_split=tarv2nmea_R_split,
                                                      str_format=tarv2nmea_R_str_format,
                                                      autofindcalibration=False,
                                                      description=tarv2nmea_R_description,
                                                      datakey_metadata=tarv2nmea_R_datakey_metadata,
                                                      packetid_format=tarv2nmea_R_packetid_format,
                                                      datastream=redvypr.RedvyprAddress('/k:data'))

        tarv2nmea_T_sample = sensor_definitions.BinarySensor(name='tarv2nmea_T_sample',
                                                             regex_split=tarv2nmea_T_sample_split,
                                                             str_format=tarv2nmea_T_sample_str_format,
                                                             autofindcalibration=False,
                                                             description=tarv2nmea_T_sample_description,
                                                             datakey_metadata=tarv2nmea_T_sample_datakey_metadata,
                                                             packetid_format=tarv2nmea_T_sample_packetid_format,
                                                             datastream=redvypr.RedvyprAddress('/k:data'))

        tarv2nmea_R_sample = sensor_definitions.BinarySensor(name='tarv2nmea_R_sample',
                                                             regex_split=tarv2nmea_R_sample_split,
                                                             str_format=tarv2nmea_R_sample_str_format,
                                                             autofindcalibration=False,
                                                             description=tarv2nmea_R_sample_description,
                                                             datakey_metadata=tarv2nmea_R_sample_datakey_metadata,
                                                             packetid_format=tarv2nmea_R_sample_packetid_format,
                                                             datastream=redvypr.RedvyprAddress('/k:data'))

        sensors.append(tarv2nmea_T)
        datatypes.append('T')
        sensors.append(tarv2nmea_R)
        datatypes.append('R')
        sensors.append(tarv2nmea_T_sample)
        datatypes.append('T')
        sensors.append(tarv2nmea_R_sample)
        datatypes.append('R')

        while True:
            datapacket = datainqueue.get()
            [command, comdata] = check_for_command(datapacket, thread_uuid=device_info['thread_uuid'],
                                                   add_data=True)
            if command is not None:
                logger.debug('Command is for me: {:s}'.format(str(command)))
                if command=='stop':
                    logger.info(funcname + 'received command:' + str(datapacket) + ' stopping now')
                    logger.debug('Stop command')
                    return


            try:
                print('Data',datapacket['data'])
                print('Done done done')
            except:
                continue


            for sensor,datatype in zip(sensors,datatypes):
                #print('Checking for sensor',sensor,datatype)
                # Check for overflow
                try:
                    binary_data = sensor.__rdatastream__.get_data(datapacket)
                    if b'..\n' in binary_data:
                        data_packet_processed = None
                    else:
                        data_packet_processed = sensor.datapacket_process(datapacket)
                except:
                    print('Could not get data')

                if data_packet_processed is not None:
                    break

            if data_packet_processed is not None:
                if len(data_packet_processed) > 0:
                    for ip,p in enumerate(data_packet_processed):
                        try:
                            mactmp = p['macparents'] + '$' + p['mac']
                        except:
                            mactmp = p['mac']

                        print('Packet with mac')
                        print('Mactmp', mactmp)
                        mac_parsed = nmea_mac64_utils.parse_nmea_mac64_string(mactmp)
                        print('mac parsed', mac_parsed)
                        if mac_parsed is None: # Not a valid mac
                            continue

                        if config['publish_single_sensor_sentence']:
                            ppublish = copy.deepcopy(p)
                            ppublish['_redvypr']['packetid'] += '_raw'
                            ppublish['mac'] += '_raw'
                            istr = "_i{}-{}".format(ppublish['ntcistart'],ppublish['ntciend'] + 1)
                            packetid = ppublish['mac'] + ppublish['_redvypr']['packetid'] + istr
                            ppublish['_redvypr']['packetid'] = packetid
                            dataqueue.put(ppublish)
                        #print('p',p)
                        p['mac'] = mac_parsed['mac']
                        p['parents'] = mac_parsed['parents']
                        #try:
                        #    print('p',p['macparents'])
                        #    p['parents'] = p['macparents'].split(':')
                        #except:
                        #    p['parents']=[]

                        packetid = p['mac'] + p['_redvypr']['packetid']
                        datatype_packet = packetid.split('__')[-1]
                        p['_redvypr']['packetid'] = packetid
                        mac = p['mac']
                        nump = p['np']

                        print('mac {} {} nump:{} packettype: {}'.format(ip,mactmp,nump,datatype_packet))
                        flag_valid_packet = False
                        # Packets that do not need to be merged
                        if (datatype_packet != 'T') and (datatype_packet != 'R'):
                            dataqueue.put(p)
                            #flag_valid_packet = True
                        else:  # T and R needs to be merged
                            #print('Merging packet',p)
                            print('Merging packet',p['ntcistart'],p['ntciend'],p['ntcnum'],p['mac'],p['parents'])
                            sensors_datasizes[mac] = p['ntcnum']
                            try:
                                dataarray = packetbuffer_tar[mac][datatype_packet][nump][datatype_packet]
                            except:
                                #print('Creating array')
                                dataarray = numpy.zeros(p['ntcnum']) * numpy.nan

                            print('Shape dataarray',numpy.shape(dataarray))
                            try:
                                packetbuffer_tar[mac]
                            except:
                                packetbuffer_tar[mac] = {}
                            try:
                                packetbuffer_tar[mac][datatype_packet]
                            except:
                                packetbuffer_tar[mac][datatype_packet] = {}
                            try:
                                packetbuffer_tar[mac][datatype_packet][nump]
                            except:
                                packetbuffer_tar[mac][datatype_packet][nump] = p

                            # Check if the dataarray is ig enough
                            #if len(dataarray) < p['ntciend'] + 1:
                            try:
                                dataarray[p['ntcistart']:p['ntciend']+1] = p[datatype_packet]
                            except:
                                logger_thread.debug('Could not add data', exc_info=True)

                            packetbuffer_tar[mac][datatype_packet][nump][datatype_packet] = dataarray
                            if sum(numpy.isnan(dataarray)) == 0:
                                print('Publishing packet ...',mac,len(packetbuffer_tar[mac][datatype_packet][nump][datatype_packet]))
                                dataarray = packetbuffer_tar[mac][datatype_packet][nump][datatype_packet]
                                packetbuffer_tar[mac][datatype_packet][nump][datatype_packet] = list(dataarray)
                                ppub = packetbuffer_tar[mac][datatype_packet].pop(nump)
                                datapacket_process = ppub
                                if config['publish_raw_sensor']:
                                    dataqueue.put(ppub)
                                flag_valid_packet = True


                    #print('Datapacket processed',data_packet_processed)
                    #logger.debug('Data packet processed (without calibration):{}'.format(len(data_packet_processed)))
                    #print('mac',mac,counter,np)
                    if config['merge_tar_chain'] and flag_valid_packet:
                        pmerge = datapacket_process
                        mac = pmerge['mac']
                        parents = pmerge['parents']
                        counter = pmerge['counter']
                        nump = pmerge['np']
                        print('Merging groups',mac,parents,nump)
                        # Check if we have the downstream device, if yes process, else do nothing
                        if len(parents) == 0:  # The most downstream device
                            macdown = mac
                        else:  # Device with parents
                            #macdown = mac
                            macdown = parents[0]

                        if True:
                            # Add the data to the buffer
                            try:
                                npmax = max(packetbuffer[macdown].keys())
                            except:
                                npmax = -1000

                            try:
                                npmin = min(packetbuffer[macdown].keys())
                            except:
                                npmin = -10000

                            print('npmax', npmax, 'nump', nump)
                            print('npmin', npmin, 'nump', nump)
                            # Check if a new packet arrived (meaning that np is larger than npmax)
                            # If yes, merge all parts of the old one first
                            if (nump > npmin) and (npmin > 0):  # Process packetnumber npmax
                                print('Nump > npmin')
                                for nptmp in packetbuffer[macdown].keys():  # Loop over all datatypes
                                    for datatype_tmp in packetbuffer[macdown][nptmp].keys():
                                        for mactmp2 in packetbuffer[macdown][nptmp][datatype_tmp].keys():
                                            print('packetuffer keys', nptmp, datatype_tmp, mactmp2, 'macdown',macdown, npmax)

                                packets_publish = {}
                                flag_packet_publish = False
                                for npmerge in packetbuffer[macdown].keys():  # Loop over all packages with number
                                    print('Merging',npmerge,nump)
                                    if npmerge == nump:
                                        continue

                                    packets_publish[npmerge] = {}
                                    for datatype_tmp in packetbuffer[macdown][npmerge].keys():  # Loop over all datatypes
                                        npackets = len(packetbuffer[macdown][npmerge][datatype_tmp].keys())
                                        #print('!npmax', npmerge, datatype_tmp,'packets',npackets)
                                        datapacket_merged = {}
                                        mac_final = 'TARM_' + macdown + 'N{}'.format(npackets)
                                        counter_final = npmerge
                                        # The merged packetid
                                        packetid_final = '{}_{}'.format(mac_final, datatype_tmp)
                                        dp = redvypr.Datapacket(packetid=packetid_final)
                                        datapacket_merged.update(dp)
                                        datapacket_merged['mac'] = mac_final
                                        datapacket_merged['counter'] = counter_final
                                        dmerge = [None] * npackets
                                        try:
                                            packetbuffer[macdown][npmerge][datatype_tmp]['merge_attempts']
                                        except:
                                            packetbuffer[macdown][npmerge][datatype_tmp]['merge_attempts'] = 0

                                        for mac_tmp in packetbuffer[macdown][npmerge][datatype_tmp].keys():
                                            if mac_tmp == 'merge_attempts':  # Check if merge did not work out
                                                packetbuffer[macdown][npmerge][datatype_tmp]['merge_attempts'] += 1
                                                if packetbuffer[macdown][npmerge][datatype_tmp]['merge_attempts'] > 30:
                                                    packets_publish[npmerge][datatype_tmp] = None
                                                    flag_packet_publish = True
                                                    print('Merging failed, will mark {} to be removed'.format(npmerge))

                                                continue

                                            pmerge2 = packetbuffer[macdown][npmerge][datatype_tmp][mac_tmp]
                                            parents_tmp = pmerge2['parents']
                                            # Count the number of parents and put it at the list location
                                            i = len(parents_tmp)
                                            if i >= npackets:
                                                #while npackets <= i+1:
                                                #    npackets += 1
                                                #    dmerge.append(None)
                                                logger.debug('Could not add {}'.format(mac_tmp))
                                                continue

                                            #print('mac_tmp',mac_tmp,i)
                                            #print('Datapacket processed', data_packet_processed)
                                            #print('Datapacket',datapacket)
                                            #print('datatype_tmp',datatype_tmp,datatype)
                                            #print('P',pmerge2)
                                            # Add the data to a list, that is hstacked later
                                            data_merge = pmerge2[datatype_tmp]
                                            print('keys',pmerge2.keys())
                                            len_data_merge = pmerge2['ntcnum']
                                            if len(data_merge) == len_data_merge:
                                                dmerge[i] = data_merge
                                            else: # Here it could also be replaced by NaN
                                                logger.debug('Could not add {} ({}), len differs should be {} is {}'.format(mac_tmp,datatype_tmp,len(data_merge),len_data_merge))
                                                continue

                                        # Merge the packages into one large one
                                        #print('dmerge', dmerge)
                                        #print('len dmerge', len(dmerge))
                                        if mac_final is not None:
                                            if None in dmerge: # This is bad, mark it
                                                packets_publish[npmerge][datatype_tmp] = None
                                                logger.debug('Found an invalid dataset, will not merge')
                                            else:
                                                # Make an long array out of the list
                                                dmerge = numpy.hstack(dmerge)
                                                # Do a quality check
                                                if 'T' in datatype_tmp:
                                                    #print('sanity check or {}'.format(datatype_tmp), dmerge)
                                                    dmerge[dmerge > 800] = numpy.nan
                                                    dmerge[dmerge < -5] = numpy.nan
                                                    #print('sanity check done', dmerge)

                                                tar_merge = dmerge.tolist()
                                                #print('Tar merge',len(tar_merge))
                                                #if len(tar_merge) < 10:
                                                #    return
                                                datapacket_merged[datatype_tmp] = tar_merge
                                                datapacket_merged['np'] = npmerge
                                                datapacket_merged['datatype'] = datatype_tmp
                                                datapacket_merged['t'] = p['t']  # Add time
                                                #print('publish merged data, merged merged')
                                                logger.info('Publishing merged data {} {} {}'.format(mac_final, nump,datatype))
                                                # Adding the merged data to the publish dictionary
                                                packets_publish[npmerge][datatype_tmp] = datapacket_merged
                                                flag_packet_publish = True
                                                np_lastpublished = npmerge

                                                # Save the data temporalily into a csv
                                                print('Packetid final',packetid_final)
                                                csvdata = [npmerge,p['t']] + tar_merge
                                                #print('csvdata',csvdata)
                                                try:
                                                    csv_save_data[packetid_final]
                                                except:
                                                    csv_save_data[packetid_final] = []
                                                csv_save_data[packetid_final].append(csvdata)
                                                csvname = packetid_final + '_data.txt'
                                                #print('Data csv',csv_save_data[packetid_final])
                                                dsave = numpy.asarray(csv_save_data[packetid_final])
                                                #print('shape',numpy.shape(dsave))
                                                print('Saved')
                                                numpy.savetxt(csvname,dsave)

                                if flag_packet_publish:
                                    print('Publishing the merged data')
                                    for npmerge in packets_publish.keys():  # Loop over all datatypes
                                        for datatype_tmp in packets_publish[npmerge].keys():  # Loop over all datatypes
                                            print('Publishing',npmerge,datatype_tmp)
                                            datapacket_merged = packets_publish[npmerge][datatype_tmp]
                                            if datapacket_merged is not None:
                                                dataqueue.put(datapacket_merged)
                                            packetbuffer[macdown][npmerge].pop(datatype_tmp)
                                            if len(packetbuffer[macdown][npmerge].keys()) == 0:
                                                packetbuffer[macdown].pop(npmerge)

                        # Add the data to the buffer
                        try:
                            packetbuffer[macdown]
                        except:
                            packetbuffer[macdown] = {}

                        try:
                            packetbuffer[macdown][nump]
                        except:
                            packetbuffer[macdown][nump] = {}

                        try:
                            packetbuffer[macdown][nump][datatype]
                        except:
                            packetbuffer[macdown][nump][datatype] = {}

                        packetbuffer[macdown][nump][datatype][mac] = pmerge

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
        logger.info('Plot clicked')
        #print('Itemclicked',itemclicked)
        #print(self.device.redvypr.redvypr_device_scan.redvypr_devices)
        if False:
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
        address = button.__address__
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
                print('Starting starting starting')
                plotdevice.thread_start()
                button.__plotdevice__ = plotdevice
                print('Done')
                #button.setText('Close')
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
            #print('Got packet',packetid)
            # Check if datakeys has 'R' or 'T'
            if 'R' in data.keys():
                datatype = 'R'
                datatar = data[datatype]
                icol = 0
                icols.append(icol)
                datatars.append(datatar)
                colheaders.append(datatype)
            elif 'T' in data.keys():
                datatype = 'T'
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

            # Get data from packet
            try:
                np = data['np']
                mac = data['mac']
                counter = data['t']
            except:
                logger.info('Could not get data', exc_info=True)
                return

            try:
                parents = data['parents']
            except:
                parents = []

            macs_tarchain = parents + [mac]
            if "raw" in packetid:
                parentitm = self.root_raw
            elif "TARchain" in packetid:
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
                    itm.addChild(itm_datatype)
                    flag_tree_update = True
                    # Button erstellen und zur Zelle hinzufügen
                    button = QtWidgets.QPushButton("Plot")
                    button.setCheckable(False)
                    button.clicked.connect(lambda _, item=itm_datatype: self.devicetree_plot_button_clicked(item))
                    # Button in die dritte Spalte des TreeWidgetItems einfügen
                    self.devicetree.setItemWidget(itm_datatype, 2, button)
                parentitm = itm
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

