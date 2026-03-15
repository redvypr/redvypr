"""

test device

"""
import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import threading
import copy
from typing import Any, Dict
from redvypr.device import RedvyprDeviceCustomConfig
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.widgets.pydanticConfigWidget import pydanticDeviceConfigWidget
import redvypr.data_packets
from redvypr.data_packets import check_for_command
import pydantic

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('test_device')
logger.setLevel(logging.INFO)

redvypr_devicemodule = True
class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = False
    description: str = 'A simple test device'

class DeviceCustomConfig(RedvyprDeviceCustomConfig):
    delay_s: float = .001
    send_rand: bool = pydantic.Field(default=True,
                                     description="Flag if rand data is to be sent")
    rand_freq_send: float = pydantic.Field(default=0.5,
                                      description="Frequency of sine")
    rand_amp: float = pydantic.Field(default=2.0,
                                     description="Amplitude of the random data")
    send_sine: bool = pydantic.Field(default=True, description="Flag if sine data is to be sent")
    sine_freq: float = pydantic.Field(default=0.1,
                                      description="Frequency of sine")
    sine_amp: float = pydantic.Field(default=1.0,
                                          description="Amplitude of the sind data")
    sine_freq_send: float = pydantic.Field(default=1.0,
                                      description="Frequency of sine data to be sent")
    send_sine_rand: bool = pydantic.Field(default=True,
                                     description="Flag if sine rand data is to be sent")
    sine_rand_amp: float = pydantic.Field(default=0.1,
                                           description="Amplitude of the random data")
    send_fast_single: bool = pydantic.Field(default=False,
                                     description="Flag if fast single data to be sent")
    fast_freq_single: float = pydantic.Field(default=500,
                                                 description="Frequency of the fast data to be sent")
    send_fast_merged: bool = pydantic.Field(default=False,
                                                 description="Flag if fast single data to be sent as merged packets")
    fast_freq_merged_send: float = pydantic.Field(default=2,
                                                  description="Frequency of the merged packets to be sent (filled with fast data)")
    send_latlon: bool = pydantic.Field(default=False,
                                            description="Flag if random position data shall be sent")
    latlon_freq: float = pydantic.Field(default=1,
                                                  description="Frequency of the latlon package")


def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    funcname = __name__ + '.start():'
    logger.debug(funcname)
    #print('Config',config)
    pdconfig = DeviceCustomConfig.model_validate(config)
    #print('pdconfig',pdconfig)
    #data = {'_keyinfo':config['_keyinfo']}
    # dataqueue.put(data)
    # Send a datapacket with metadata describing the device
    address_str = device_info['address_str']
    device_metadata = {'location':'Room 42'}
    datapacket_info_device = redvypr.data_packets.add_metadata2datapacket(datapacket={}, address=address_str, metadict=device_metadata)
    dataqueue.put(datapacket_info_device)
    # Send a datapacket with information once (that will be put into the statistics)
    datapacket_info = redvypr.data_packets.add_metadata2datapacket(datapacket={}, datakey='sine_rand', metakey='unit',metadata='random unit')
    # Metadata can also be given as a dict
    metadata = {'description':'sinus with random data', 'mac':'ABCDEF1234'}
    datapacket_info = redvypr.data_packets.add_metadata2datapacket(datapacket_info, datakey='sine_rand', metadict=metadata)
    dataqueue.put(datapacket_info)
    i = 0
    counter = 0
    t_last_keys = ['sine','rand','fast']
    t_last = {}
    t_tmp = time.time()
    for k in t_last_keys:
        t_last[k] = t_tmp


    print("Config",pdconfig)
    while True:
        time.sleep(pdconfig.delay_s)
        t_now = time.time()
        try:
            data = datainqueue.get(block = False)
        except:
            data = None
        if(data is not None):
            [command,comdata] = check_for_command(data, thread_uuid=device_info['thread_uuid'],add_data=True)
            logger.debug('Got a command: {:s}'.format(str(data)))
            if (command == 'stop'):
                logger.debug('Command is for me: {:s}'.format(str(command)))
                break
            elif (command == 'config'):
                logger.debug('Command is for me: {:s}'.format(str(command)))
                print("Data",data)
                new_config = comdata["command_data"]["data"]["config"]
                print("Applying new config")
                pdconfig = DeviceCustomConfig.model_validate(new_config)

        if pdconfig.send_rand:
            dt_tmp = t_now - t_last['rand']
            if dt_tmp > (1/pdconfig.rand_freq_send):
                print("Sending rand")
                t_last['rand'] = t_now
                data = redvypr.data_packets.create_datadict(device = device_info['device'])
                rand_data = pdconfig.rand_amp * (np.random.rand(10) - 0.5)
                data['rand'] = float(rand_data.mean())
                data['rand_std'] = float(np.std(rand_data))
                data['rand_min'] = float(np.min(rand_data))
                data['rand_max'] = float(np.max(rand_data))
                data['rand_max_min'] = data['rand_max'] - data['rand_min']
                data['sometext'] = 'Hello {}'.format(counter)
                dataqueue.put(data)

        if pdconfig.send_sine:
            dt_tmp = t_now - t_last['sine']
            if dt_tmp > (1 / pdconfig.sine_freq_send):
                t_last['sine'] = t_now
                print("Sending sine")
                # Calculate some sine
                data_rand = pdconfig.sine_rand_amp * float(np.random.rand(1) - 0.5)
                f_sin = 2 * np.pi * pdconfig.sine_freq
                A_sin = pdconfig.sine_amp
                data_sine = float(A_sin * np.sin(f_sin * time.time()))
                data_sine_packet = {'sine_rand': data_rand + data_sine, 'count': counter, 'sine': data_sine}
                #if counter == 0:
                if True:
                    # Add metadata
                    metadata = {'unit': 'nice sine unit'}
                    data_sine_packet = redvypr.data_packets.add_metadata2datapacket(data_sine_packet, datakey='sine',
                                                                        metadict=metadata)
                    metadata = {'unit': 'nice sine unit (random)'}
                    data_sine_packet = redvypr.data_packets.add_metadata2datapacket(data_sine_packet, datakey='sine_rand',
                                                                                    metadict=metadata)
                #print(f"Publishing:{data_sine_packet=}")
                dataqueue.put(data_sine_packet)

        if pdconfig.send_fast_single:
            dt_tmp = t_now - t_last['fast']
            if dt_tmp > (1 / pdconfig.fast_freq_single):
                t_last['fast'] = t_now
                #print("Sending fast")
                data = {}
                rand_data = pdconfig.rand_amp * (np.random.rand(10) - 0.5)
                data['t'] = t_now
                data['fast'] = float(rand_data.mean())
                dataqueue.put(data)


        if pdconfig.send_latlon:
            dt_tmp = t_now - t_last['latlon']
            if dt_tmp > (1 / pdconfig.latlon_freq):
                # Create a position packet
                data_latlon = redvypr.data_packets.create_datadict(packetid='latlon_random',device=device_info['device'])
                data_latlon['lon'] = float(np.random.rand(1) - 0.5) * 180
                data_latlon['lat'] = float(np.random.rand(1) - 0.5) * 90
                data_latlon['t'] = time.time()
                dataqueue.put(data_latlon)

        if False:
            #print('Hallo')
            # Add complex data
            data = redvypr.data_packets.create_datadict(device='test_complex_data', packetid='complex_data')
            if counter == 0:
                # Add metadata

                metadata = {'unit': 'baseunit','location':'another room'}
                data = redvypr.data_packets.add_metadata2datapacket(data, datakey='data_list_list',
                                                                    metadict=metadata)

                metadata = {'unit': 'otherunit of entry 0'}
                data = redvypr.data_packets.add_metadata2datapacket(data, datakey='data_list_list[0]',
                                                                    metadict=metadata)

                metadata = {'description': 'Counter and polynomial functions of counter', 'unit': 'grigra'}
                data = redvypr.data_packets.add_metadata2datapacket(data, datakey='data_list_poly',
                                                                               metadict=metadata)

                metadata = {'description': 'Temperature', 'unit': 'degC'}
                data = redvypr.data_packets.add_metadata2datapacket(data, datakey='data_dict_list["temp"]',
                                                                    metadict=metadata)

                metadata = {'unit': 'Pa'}
                data = redvypr.data_packets.add_metadata2datapacket(data, datakey='data_dict_list["pressure"]',
                                                                    metadict=metadata)
            data['data_list'] = [counter,data_sine,data_rand]
            data['data_list_list'] = [[counter, data_sine, data_rand],[counter, data_sine]]
            data['data_list_poly'] = [counter, counter + data_rand, 2 * counter + data_rand, -10 * counter + data_rand+ 3, 0.1 * counter**2 + 2 * counter + data_rand+ 3]
            data['data_dict_list'] = {'temp':[data_rand, 2*data_rand-10],'pressure':10+data_rand, 'info':{'location':'House','sn':123,'operator':{'name':'Joe','age':89}}}
            data['data_ndarray_1d'] = np.zeros((5,)) + counter
            data['data_ndarray_2d'] = np.zeros((6,7)) + counter
            data['data_ndarray_2d_int'] = np.zeros((3,2),dtype=int) + int(counter)
            #print('datastreams',redvypr.data_packets.Datapacket(data).datastreams(expand=True))
            #print("Publishing now")
            dataqueue.put(data)
            # Put some pathological data into the queue
            dataqueue.put(None)
            counter += 1


class ConfigGroupWidget_old(QtWidgets.QGroupBox):
    def __init__(self, title: str, config_key: str, device_config: Any,
                 fields: Dict[str, str]):
        super().__init__(title)
        self.config_key = config_key
        self.device_config = device_config
        self.fields = fields

        is_checked = getattr(self.device_config, self.config_key)
        self.setCheckable(True)
        self.setChecked(is_checked)

        # Hauptlayout der GroupBox
        self.main_layout = QtWidgets.QVBoxLayout()

        # Erstelle die Tabelle
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(len(self.fields))
        self.table.setRowCount(1)

        # Setze die Beschreibungen als horizontale Header (Überschriften)
        self.table.setHorizontalHeaderLabels(list(self.fields.values()))

        # Tabelle optisch anpassen
        self.table.verticalHeader().setVisible(False)  # Keine Zeilennummern links
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        self.table.setFixedHeight(65)  # Kompakte Höhe für eine Zeile + Header

        # Felder in die Tabelle einfügen
        for column, (field_name, _) in enumerate(self.fields.items()):
            input_widget = QtWidgets.QDoubleSpinBox()
            input_widget.setRange(-1e6, 1e6)
            input_widget.setDecimals(3)
            input_widget.setValue(getattr(self.device_config, field_name))

            # Wichtig: Closure für den field_name im Lambda
            input_widget.valueChanged.connect(
                lambda val, fn=field_name: self.on_field_changed(fn, val)
            )

            # Widget in die Zelle setzen
            self.table.setCellWidget(0, column, input_widget)

        self.main_layout.addWidget(self.table)
        self.setLayout(self.main_layout)

        # Signale verbinden
        self.toggled.connect(self.toggle_visibility)
        self.toggle_visibility(is_checked)

    def toggle_visibility(self, on: bool):
        self.table.setVisible(on)
        setattr(self.device_config, self.config_key, on)

    def on_field_changed(self, field_name: str, value: float):
        setattr(self.device_config, field_name, value)


class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Hauptlayout
        layout = QtWidgets.QVBoxLayout(self)

        # Definition der Zeilen und ihrer zugehörigen Config-Keys/Felder
        # Format: "Anzeigetitel": (Checkbox_Key, {Field_Name: Spalten_Titel})
        self.row_configs = {
            "Sine": ("send_sine", {
                "sine_freq": "Freq",
                "sine_amp": "Amp",
                "sine_freq_send": "Send Freq"
            }),
            "Random": ("send_rand", {
                "rand_freq_send": "Send Freq",
                "rand_amp": "Amp",
                "sine_rand_amp": "Sine Rand Amp"
            }),
            "Fast Single": ("send_fast_single", {
                "fast_freq_single": "Freq",
            }),
            "Fast Merged": ("send_fast_merged", {
                "fast_freq_merged_send": "Packet Freq",
            }),
            "Lat/Lon": ("send_latlon", {
                "latlon_freq": "Packet Freq",
            })
        }

        # Tabelle erstellen
        self.table = QtWidgets.QTableWidget()
        self.table.setRowCount(len(self.row_configs))
        # Spalten: 1 (Titel/Checkbox) + max Felder (hier 3)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["Enable / Feature", "Param 1", "Param 2", "Param 3"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)

        # Zeilenhöhe global erhöhen (z.B. auf 60 Pixel)
        self.table.verticalHeader().setDefaultSectionSize(60)

        # Optional: Den Header (Überschriften) auch etwas mehr Platz geben
        self.table.horizontalHeader().setMinimumHeight(40)

        # Tabelle befüllen
        for row, (title, (check_key, fields)) in enumerate(self.row_configs.items()):
            # --- Spalte 0: Checkbox + Titel ---
            check_widget = QtWidgets.QCheckBox(title)
            is_checked = getattr(self.device.custom_config, check_key)
            check_widget.setChecked(is_checked)
            check_widget.toggled.connect(
                lambda on, k=check_key, r=row: self.on_row_toggled(k, r, on))
            self.table.setCellWidget(row, 0, check_widget)

            # --- Spalten 1-3: Parameter ---
            # Wir speichern die Inputs einer Zeile, um sie später en/disablen zu können
            row_inputs = []
            for col, (field_name, label) in enumerate(fields.items(), start=1):
                container = QtWidgets.QWidget()
                v_layout = QtWidgets.QVBoxLayout(container)
                v_layout.setContentsMargins(2, 2, 2, 2)

                # Kleines Label über dem Spinbox für Klarheit
                lbl = QtWidgets.QLabel(label)
                lbl.setStyleSheet("font-size: 9px; color: gray;")

                spin = QtWidgets.QDoubleSpinBox()
                spin.setRange(-1e6, 1e6)
                spin.setDecimals(3)
                spin.setValue(getattr(self.device.custom_config, field_name))
                spin.valueChanged.connect(
                    lambda val, fn=field_name: setattr(self.device.custom_config, fn,
                                                       val))

                v_layout.addWidget(lbl)
                v_layout.addWidget(spin)
                self.table.setCellWidget(row, col, container)
                row_inputs.append(container)

            # Initialen Status der Zeile setzen (Grey-out)
            for widget in row_inputs:
                widget.setEnabled(is_checked)

            # Wir speichern die Referenzen der Inputs kurzzeitig im Widget-Objekt der Checkbox
            check_widget.setProperty("row_widgets", row_inputs)

        # Tabelle und Apply-Button zum Layout
        layout.addWidget(self.table)

        self.send_config_button = QtWidgets.QPushButton("Apply new config")
        self.send_config_button.clicked.connect(self.send_config_clicked)
        layout.addWidget(self.send_config_button)

        self.layout.addLayout(layout)

    def on_row_toggled(self, key, row_idx, is_on):
        """Aktiviert/Deaktiviert die Eingabefelder einer Zeile."""
        setattr(self.device.custom_config, key, is_on)

        # Hole die Widgets dieser Zeile über das Property
        check_widget = self.table.cellWidget(row_idx, 0)
        row_widgets = check_widget.property("row_widgets")
        for w in row_widgets:
            w.setEnabled(is_on)

    def send_config_clicked(self):
        configdata = {'config': self.device.custom_config}
        self.device.thread_command(command="config", comdata=configdata)
