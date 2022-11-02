from PyQt5 import QtWidgets, QtCore, QtGui
import redvypr.gui
import sys
from redvypr.utils import configtemplate_to_dict, apply_config_to_dict

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

    config_options = {'type': 'str','default':'test','options':['1','2','zehn'],'range':[0,2,1]}
    config_template = {}
    config_template['name']      = 'zeromq'
    config_template['address']   = {'type': 'str','default':'127.0.0.1'}
    config_template['port']      = {'type': 'int','default':18196}
    config_template['direction'] = {'type': 'str', 'options': ['receive', 'publish'],'default':'receive'}
    config_template['data']      = {'type': 'str'}
    config_template['serialize'] = {'type': 'str', 'options': ['yaml', 'str'],'default':'yaml'}

    config = {}
    config['address'] = '192.168.178.10'
    config['port'] = 10000

    confdict = configtemplate_to_dict(config_template)
    print('config config',confdict)
    apply_config_to_dict(config, confdict)
    #configtree = redvypr.gui.redvypr_dictionary_widget(d)
    #configtree = redvypr.gui.redvypr_data_tree(d)
    configtree = redvypr.gui.redvypr_config_widget(config)
    configtree.apply_config(config)
    #configtree = redvypr.gui.redvypr_config_widget(template = config_template,config=config)
    #configtree.apply_config(config)
    layout.addWidget(configtree)
    widget.show()
    sys.exit(app.exec_())



if __name__ == '__main__':
    main()
