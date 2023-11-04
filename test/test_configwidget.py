from PyQt5 import QtWidgets, QtCore, QtGui
import redvypr.gui
import sys
#from redvypr.utils import configtemplate_to_dict, apply_config_to_dict,configdata
import redvypr.config
import copy



config_options = {'type': 'str', 'default': 'test', 'options': ['1', '2', 'zehn'], 'range': [0, 2, 1]}

config_template2 = {}
config_template2['template_name'] = 'type2'
config_template2['address'] = {'type': 'str', 'default': '127.0.0.1'}
config_template2['port'] = {'type': 'int', 'default': 18196}

config_template3 = {}
config_template3['template_name'] = 'type3'
config_template3['serial'] = {'type': 'str', 'default': 'COM0'}
config_template3['port'] = {'type': 'int', 'default': 18196}

config_template4 = {}
config_template4['template_name'] = 'type4'
config_template4['listconfig'] = {'type': 'list', 'modify': True, 'options': [config_template2, config_template2]}


config_template = {}
config_template['template_name'] = 'testtemplate'
config_template['address'] = {'type': 'str', 'default': '127.0.0.1'}
config_template['port'] = {'type': 'int', 'default': 18196}
config_template['direction'] = {'type': 'str', 'options': ['receive', 'publish'], 'default': 'receive'}
config_template['data'] = {'type': 'str'}
config_template['int_option'] = {'type': 'int', 'options': [3,4,4], 'default': 3}
config_template['int'] = {'type': 'int'}
config_template['listconfig'] = {'type': 'list', 'default':[config_template2,config_template4], 'modify': True, 'options': ['int',config_template2, config_template3, config_template4]}

config = {}
config['address'] = '192.168.178.10'
config['port'] = 10000
config['listconfig'] = []
config['listconfig'].append({'name': 'type2'})
config['listconfig'].append({'template_name': 'typetest'})

from redvypr.devices.plot.plot_widgets import redvypr_numdisp_widget, redvypr_graph_widget, config_template_numdisp, config_template_graph
description = 'Device that plots the received data'
config_template = {}
#config_template['plots'] = {'type': 'list', 'modify': True, 'options': [config_template_numdisp, config_template_graph]}
config_template['dt_update'] = {'type':'color'}
config_template['redvypr_device'] = {}
config_template['redvypr_device']['publish'] = False
config_template['redvypr_device']['subscribe'] = True
config_template['redvypr_device']['description'] = description




config_template_poly = {}
config_template_poly['template_name'] = 'polynom'
config_template_poly['coefficients'] = {'type': 'list', 'modify': True, 'options': ['float','int']}
#config_template_poly['coefficients'] = {'type': 'list', 'modify': True, 'options': ['float']}
config_template_poly['unit'] = {'type':'str'}
config_template_poly['datastream_in'] = {'type':'datastream'}
config_template_poly['datastream_out'] = {'type':'datastream'}


config_template_hf = {}
config_template_hf['template_name'] = 'heatflow'
config_template_hf['sensitivity'] = {'type':'float','default':1.0}
config_template_hf['unit'] = {'type':'str'}
config_template_hf['datastream_in'] = {'type':'datastream'}
config_template_hf['datastream_out'] = {'type':'datastream'}




config_template = {}
config_template['template_name'] = "sensor_raw2unit"
config_template['sensors'] = {'type': 'list', 'modify': True, 'default':[config_template_poly], 'options': [config_template_hf, config_template_poly]}
config_template['redvypr_device'] = {}
config_template['redvypr_device']['publish']     = True
config_template['redvypr_device']['subscribe']   = True
config_template['redvypr_device']['description'] = description





calibration_template_channel = {}
calibration_template_channel['template_name']  = 'channelconfiguration'
calibration_template_channel['sn_mac'] = {'type': 'str', 'default': '', 'modify': True, 'description':'The serial number and/or MAC address of the sensor that is attached to the channel'}

calibration_template_sensor = {}
calibration_template_sensor['template_name']  = 'sensorconfiguration'
calibration_template_sensor['sn_mac'] = {'type': 'str', 'default': '', 'modify': True, 'description':'The serial number and/or MAC address of the logger to which sensor are attached'}
calibration_template_sensor['channels'] = {'type': 'dict', 'default': {}, 'options': [calibration_template_channel],'modify': True, 'description':'The configuration of the individual channels'}

config_template = {}
config_template['STR'] = {'type': 'str', 'default': 'BALR','modify': True}
config_template['DM'] = {'type': 'dict', 'default': {}, 'options': [calibration_template_sensor,'str'],'modify': True}
config_template['D'] = {'type': 'dict', 'default': {}, 'options': [calibration_template_sensor,'str'],'modify': False}
config_template['LM'] = {'type': 'list', 'default': [], 'options': [calibration_template_sensor,'str','bool'],'modify': True}
config_template['L'] = {'type': 'list', 'default': [], 'options': [calibration_template_sensor],'modify': False}




configtest = redvypr.config.configuration(config_template)

def main():
    app = QtWidgets.QApplication(sys.argv)
    screen = app.primaryScreen()
    #print('Screen: %s' % screen.name())
    size = screen.size()
    #print('Size: %d x %d' % (size.width(), size.height()))
    rect = screen.availableGeometry()
    width = int(rect.width()*4/5)
    height = int(rect.height()*2/3)

    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(widget)

    configtree = redvypr.gui.configWidget(config=configtest)
    # Set the size

    layout.addWidget(configtree)
    widget.resize(1000, 800)  # TODO, calculate the size of the widget
    widget.show()
    sys.exit(app.exec_())



if __name__ == '__main__':
    main()
