from PyQt5 import QtWidgets, QtCore, QtGui
import redvypr.gui
import sys
from redvypr.utils import configtemplate_to_dict, apply_config_to_dict,configdata
import redvypr.config
import copy

d =configdata([])
d.value.append(configdata(None))
copy.deepcopy(configdata(None))
#copy.deepcopy(d)

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
config_template4['listconfig'] = {'type': 'list', 'dynamic': True, 'options': [config_template2, config_template2]}


config_template = {}
config_template['template_name'] = 'zeromq'
config_template['address'] = {'type': 'str', 'default': '127.0.0.1'}
config_template['port'] = {'type': 'int', 'default': 18196}
config_template['direction'] = {'type': 'str', 'options': ['receive', 'publish'], 'default': 'receive'}
config_template['data'] = {'type': 'str'}
config_template['serialize'] = {'type': 'str', 'options': ['yaml', 'str'], 'default': 'yaml'}
config_template['listconfig'] = {'type': 'list', 'default':[config_template2], 'dynamic': True, 'options': [config_template2, config_template3, config_template4]}

config = {}
config['address'] = '192.168.178.10'
config['port'] = 10000
config['listconfig'] = []
config['listconfig'].append({'name': 'type2'})
config['listconfig'].append({'template_name': 'typetest'})

print('Testing copy/deepcopy')
cdict = redvypr.config.configDict()
cdict['a'] = 3
cdict.test = 'test'
ccdict = copy.deepcopy(cdict)
print('Cdict',cdict,cdict.test,type(cdict),type(ccdict))
clist = redvypr.config.configList()
clist.append(3)
clist[0] = 5
clist.test = 'test'
cclist = copy.deepcopy(clist)
print('CList',clist,clist.test,type(clist),type(cclist))

cint = redvypr.config.configNumber(3)
cint.test = 'test'
ccint = copy.deepcopy(cint)
print('Cint',cint,cint.test,type(cint),type(ccint))

cint = redvypr.config.configNumber(3.20)
cint.test = 'test'
ccint = copy.deepcopy(cint)
print('Cfloat',cint,cint.test,type(cint),type(ccint))

cint = redvypr.config.configNumber(True)
cint.test = 'test'
ccint = copy.deepcopy(cint)
print('Cbool',cint,cint.test,type(cint),type(ccint))

cint = redvypr.config.configNumber(None)
cint.test = 'test'
ccint = copy.deepcopy(cint)
print('CNone',cint,cint.test,type(cint),type(ccint))


# Test if numbers can be modified when taken from dictionary
n1 = redvypr.config.configNumber(3)
n2 = 3
cdict1 = redvypr.config.configDict()
cdict1['n1'] = n1
cdict1['n2'] = n2
print('cdict1 before change',cdict1)
n1 += 5
n2 = 5
print('cdict1 after change',cdict1)

print('Converting data')
d = redvypr.config.data_to_configdata([3,5,6])
print(d,type(d))
print(redvypr.config.configdata_to_data(d))
d = redvypr.config.data_to_configdata(3)
print(d,type(d))
d = redvypr.config.data_to_configdata(None)
print(d,type(d))
d = redvypr.config.data_to_configdata('Hallo')
print(d,type(d))
print(redvypr.config.configdata_to_data(d))
d = redvypr.config.data_to_configdata(redvypr.config.configString('Hallo'))
print(d,type(d))
try:
    print(redvypr.config.configdata_to_data('test'))
except Exception as e:
    print(e)

if False:
    confdict = configtemplate_to_dict(config_template)
    print('config config', confdict)
    apply_config_to_dict(config, confdict)
    # configtree = redvypr.gui.redvypr_dictionary_widget(d)
    # configtree = redvypr.gui.redvypr_data_tree(d)
    print('Config: ', config)

