import copy
import time
import logging
import sys
import yaml
from PyQt5 import QtWidgets, QtCore, QtGui
from redvypr.utils import addrm_device_as_data_provider,get_data_receiving_devices,get_data_providing_devices,configtemplate_to_dict
from redvypr.device import redvypr_device
from redvypr.widgets.devicelist_widget import redvypr_devicelist_widget
import redvypr.utils
import redvypr.files as files

_logo_file = files.logo_file
_icon_file = files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr')
logger.setLevel(logging.DEBUG)

#
#
class redvypr_ip_widget(QtWidgets.QWidget):
    """ Widget that shows the IP and network devices of the host
    """

    def __init__(self):
        """
        """
        funcname = __name__ + '.__init__():'
        super(QtWidgets.QWidget, self).__init__()
        # self.setWindowIcon(QtGui.QIcon(_icon_file))
        # self.table = QtWidgets.QTableWidget()
        self.show()





#
#
#
#
#
class redvypr_config_widget(QtWidgets.QWidget):
    config_changed = QtCore.pyqtSignal(dict)  # Signal notifying that the configuration has changed
    config_changed_flag = QtCore.pyqtSignal()  # Signal notifying that the configuration has changed
    def __init__(self, template={}, config=None,loadsavebutton=True,redvypr_instance=None):
        funcname = __name__ + '.__init__():'
        super().__init__()
        self.redvypr=redvypr_instance
        # TODO, convert config to dictionary with configdata objects
        self.config = config
        self.layout = QtWidgets.QGridLayout(self)
        self.layout.setColumnStretch(0, 1)
        self.layout.setColumnStretch(1, 1)
        try:
            configname = config['name']
        except:
            configname = 'config'

        self.template = template
        conftemplate = configtemplate_to_dict(template=template)
        if(config is not None):
            logger.debug(funcname + 'Applying config to template')
            self.config = redvypr.utils.apply_config_to_dict(config, conftemplate)

        self.configtree = redvypr_config_tree(data = self.config,dataname=configname)
        self.configtree.expandAll()
        self.configtree.resizeColumnToContents(0)

        #self.itemExpanded.connect(self.resize_view)
        #self.itemCollapsed.connect(self.resize_view)
        self.configtree.itemDoubleClicked.connect(self.__open_config_gui)
        #self.configtree.itemChanged.connect(self.item_changed)  # If an item is changed
        #self.configtree.currentItemChanged.connect(self.current_item_changed)  # If an item is changed
        self.configgui = QtWidgets.QWidget() # Widget where the user can modify the content
        self.configgui_layout = QtWidgets.QVBoxLayout(self.configgui)

        if(loadsavebutton):
            # Add load/save buttons
            self.load_button = QtWidgets.QPushButton('Load')
            self.load_button.clicked.connect(self.load_config)
            self.save_button = QtWidgets.QPushButton('Save')
            self.save_button.clicked.connect(self.save_config)

        self.layout.addWidget(self.configtree,0,0)
        self.layout.addWidget(self.configgui, 0, 1)
        if (loadsavebutton):
            self.layout.addWidget(self.load_button, 1, 0)
            self.layout.addWidget(self.save_button, 1, 1)

    def reload_config(self):
        """
        Clears the configtree and redraws it. Good after a third person change of the configuration
        Returns:

        """
        funcname = __name__ + '.reload_config():'
        logger.debug(funcname)
        self.configtree.reload_data(self.config)

    def load_config(self):
        funcname = __name__ + '.load_config():'
        fname_open = QtWidgets.QFileDialog.getOpenFileName(self, 'Open file', '',"YAML files (*.yaml);; All files (*)")
        if(len(fname_open[0]) > 0):
            logger.info(funcname + 'Opening file {:s}'.format(fname_open[0]))
            fname = fname_open[0]
            with open(fname, 'r') as yfile:
                config = yaml.safe_load(yfile)
                conftemplate = configtemplate_to_dict(template=self.template)
                if (config is not None):
                    logger.debug(funcname + 'Applying config to template')
                    self.config = redvypr.utils.apply_config_to_dict(config, conftemplate)
                    print('New config:',config)
                    self.reload_config()


    def save_config(self):
        funcname = __name__ + '.save_config():'
        fname_open = QtWidgets.QFileDialog.getSaveFileName(self, 'Save file', '',"YAML files (*.yaml);; All files (*)")
        if(len(fname_open[0]) > 0):
            logger.info(funcname + 'Save file file {:s}'.format(fname_open[0]))
            print('Saving', self.configtree.data)
            config = copy.deepcopy(self.configtree.data)
            print('Deepcopy', config)
            fname = fname_open[0]
            with open(fname, 'w') as yfile:
                yaml.dump(config, yfile)

    def get_config(self):
        """
        Returns a configuation dictionary of the qtreewidgetitem

        Returns:

        """
        config = copy.deepcopy(self.configtree.data)
        return config


    def __open_config_gui(self,item):
        """
        After an item was clicked this function checks if there is a configuration gui for that type of data, if yes open that configuration
        widget
        Returns:

        """
        funcname = __name__ + '.__open_config_gui():'
        data = item.__data__
        try:
            options = item.__options__
        except:
            options = None

        try:
            modifiable = item.__modifiable__
        except:
            modifiable = False

        try:
            modifiable_parent = item.__parent__.__modifiable__
        except:
            modifiable_parent = False
        print(funcname, type(data),modifiable,modifiable_parent)

        if (type(data) == dict) and modifiable_parent: # A template dictionary item in a modifiable list
            pass
        elif((type(data) == list) or (type(data) == dict)) and not(modifiable):
            return

        try:
            dtype = data.template['type']
        except:
            if(type(data) == redvypr.utils.configdata):
                dtype = data.value.__class__.__name__
            else:
                dtype = data.__class__.__name__

            #print('dtpye',dtype)
            #dtype = 'str'

        item.__datatype__ = dtype
        self.remove_input_widgets()
        if (dtype == 'dict'):
            #print('Dictdictdict')
            self.config_widget_dict(item)
        elif(dtype == 'int'):
            self.config_widget_number(item,'int')
        elif (dtype == 'float'):
            self.config_widget_number(item,'float')
        elif (dtype == 'datastream'):
            self.config_widget_datastream(item)
        elif (dtype == 'color'):
            self.config_widget_color(item)
        elif (dtype == 'bool'):
            #
            data.template['options'] = ['False','True']
            self.config_widget_str_combo(item)
        elif(dtype == 'str'):
            # If we have options
            try:
                data.template['options']
                self.config_widget_str_combo(item)
            # Let the user enter
            except Exception as e:
                print('Exception',e)
                self.config_widget_str(item)
        elif (dtype == 'list'): # Modifiable list
            self.config_widget_list_combo(item)
            #print('List')


    def __config_widget_button(self):
        """
        Applies the changes of the configuration widget

        Returns:

        """
        funcname = __name__ + '.__config_widget_button(): '
        btn = self.sender()
        if(btn == self.__configwidget_apply):
            item = btn.item
            dtype = item.__datatype__
            logger.debug(funcname + 'Apply')
            data = None
            btntext = btn.text()
            try:
                flag_remove = btn.__removeitem__
            except:
                flag_remove = False
            #print('btntext',btntext)
            if (flag_remove):  # Add/Remove from list
                logger.debug(funcname + ' Removing item')
                item.__dataparent__.remove(item.__data__)
                self.reload_config()
                config = self.get_config()
                self.config_changed_flag.emit()
                self.config_changed.emit(config)
                return
            if (dtype == 'list'):  # Add/Remove from list
                #print('Add to list')
                templatename = str(self.__configwidget_input.currentText())
                template_options = item.__options__
                template_names = []
                newitem_dict = redvypr.utils.configdata(None)
                for t in template_options:
                    if(templatename == t['template_name']):
                        #print('Found template')
                        configdict = redvypr.utils.configtemplate_to_dict(t)
                        newitem_dict = configdict


                #print(item.__dataparent__[item.__dataindex__])


                #print('tname',templatename)
                template = item.__dataparent__[item.__dataindex__].template
                #print('Template')
                item.__dataparent__[item.__dataindex__].value.append(newitem_dict)
                #print(item.__dataparent__[item.__dataindex__])
                self.reload_config()
                config = self.get_config()
                self.config_changed_flag.emit()
                self.config_changed.emit(config)
                return

            elif (dtype == 'datastream'):
                data = self.__configwidget_input.datastreamcustom.text()

            elif (dtype == 'color'):
                color = self.__configwidget_input.currentColor()
                rgb = color.getRgb()
                data = list(rgb)

            # TODO, check what kind of widget we have here
            if (data is None):
                try:
                    data = self.__configwidget_input.value() # Works for int/float spinboxes
                except:
                    pass

            if (data is None):
                try:
                    data = self.__configwidget_input.text() # Works for lineedits (str)
                except:
                    pass
            if (data is None):
                try:
                    data = str(self.__configwidget_input.currentText()) # Works for comboboxes (combo_str)
                except Exception as e:
                    pass

                #print('DATADATATAT',data,type(data),dtype,bool(data))
                # Test if we have a bool
                if(dtype == 'bool'):
                    data = data.lower() == 'True'

            if(data is not None):
                logger.debug(funcname + 'Got data')
                print('data',data)
                item.setText(1,str(data))
                try: # If configdata
                    item.__dataparent__[item.__dataindex__].value = data
                except:
                    item.__dataparent__[item.__dataindex__] = data
            else:
                logger.debug(funcname + 'No valid data')

        config = self.get_config()
        self.config_changed_flag.emit()
        self.config_changed.emit(config)

    def config_widget_color(self, item):
        """
                Lets the user choose a color
                Args:
                    item:

                Returns:

                """
        self.remove_input_widgets()

        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QVBoxLayout(self.__configwidget_int)
        # The color dialog
        colorwidget = QtWidgets.QColorDialog(self.__configwidget_int)
        colorwidget.setOptions(QtWidgets.QColorDialog.NoButtons| QtWidgets.QColorDialog.DontUseNativeDialog)
        colorwidget.setWindowFlags(QtCore.Qt.Widget)
        self.__configwidget_input = colorwidget
        self.__layoutwidget_int.addWidget(colorwidget)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addWidget(self.__configwidget_apply)
        colorwidget.open()
        #self.__layoutwidget_int.addWidget(self.w)

    def config_widget_datastream(self, item):
        """
        Lets the user change a datastream
        Args:
            item:

        Returns:

        """
        self.remove_input_widgets()
        datastreamwidget = redvypr_devicelist_widget(redvypr=self.redvypr, showapplybutton=False)
        datastreamwidget.item     = item
        self.__configwidget_input = datastreamwidget
        self.__configwidget_int   = QtWidgets.QWidget()
        self.__layoutwidget_int   = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__layoutwidget_int.addRow(datastreamwidget)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addRow(self.__configwidget_apply)

    def config_widget_number(self, item, dtype='int'):
        """
        Creates a widgets to modify an integer value

        Returns:

        """
        index = item.__dataindex__
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        #self.__configwidget_input = QtWidgets.QLineEdit()
        if(dtype=='int'):
            self.__configwidget_input = QtWidgets.QSpinBox()
            self.__configwidget_input.setRange(int(-1e9),int(1e9))
            try:
                value = int(item.text(1))
            except:
                value = 0
            self.__configwidget_input.setValue(value)
        else:
            self.__configwidget_input = QtWidgets.QDoubleSpinBox()
            self.__configwidget_input.setRange(-1e9, 1e9)
            try:
                value = float(item.text(1))
            except:
                value = 0.0
            self.__configwidget_input.setValue(value)

        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Enter value for {:s}'.format(index)))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.__layoutwidget_int.addRow(self.__configwidget_apply)
        self.configgui_layout.addWidget(self.__configwidget_int)

    def config_widget_str(self,item):

        index = item.__dataindex__
        data = ''
        try:
            data = str(item.__data__)
        except:
            pass
        try:
            data = str(item.__data__.value)
        except:
            pass

        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__configwidget_input = QtWidgets.QLineEdit()
        self.__configwidget_input.setText(data)
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Enter string for {:s}'.format(index)))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addRow(self.__configwidget_apply)


    def config_widget_str_combo(self, item):
        index = item.__dataindex__
        data  = item.__data__
        options = data.template['options']
        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__configwidget_input = QtWidgets.QComboBox()
        for option in options:
            self.__configwidget_input.addItem(option)
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Options for {:s}'.format(index)))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addRow(self.__configwidget_apply)

    def config_widget_list_combo(self, item):
        """
        Config widget for a modifiable list
        Args:
            item:

        Returns:

        """
        index = item.__dataindex__
        data = item.__data__
        template_options = item.__options__
        options = []
        for t in template_options:
            options.append(t['template_name'])
        print('Options',options)
        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__configwidget_input = QtWidgets.QComboBox()
        for option in options:
            self.__configwidget_input.addItem(option)
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Options for {:s}'.format(index)))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Add')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addRow(self.__configwidget_apply)


    def config_widget_dict(self, item):
        """
        Config widget to edit (at the moment remove) a dictionary item
        Args:
            item:

        Returns:

        """

        funcname = __name__ + '.config_widget_dict(): '
        logger.debug(funcname)
        index = item.__dataindex__
        data  = item.__data__
        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Remove')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.__configwidget_apply.__removeitem__ = True
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addRow(self.__configwidget_apply)


    def remove_input_widgets(self):
        """
        Removes all widgets from configgui
        Returns:

        """
        layout = self.configgui_layout
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        #for i in range(len(self.__configgui_list)):
        #    widget = self.__configgui_list.pop()
        #    self.configgui_layout.remWidget(widget)

#
#
#
#
#
class redvypr_config_tree(QtWidgets.QTreeWidget):
    """ Qtreewidget that display a data structure
    """

    def __init__(self, data={}, dataname='data'):
        funcname = __name__ + '.__init__():'
        super().__init__()

        logger.debug(funcname + str(data))
        self.setExpandsOnDoubleClick(False)
        # make only the first column editable
        #self.setEditTriggers(self.NoEditTriggers)
        #self.header().setVisible(False)
        self.setHeaderLabels(['Variable','Value','Type'])
        self.data     = data
        self.dataname = dataname
        # Create the root item
        self.root = self.invisibleRootItem()
        #self.root.__data__ = data
        self.root.__dataindex__ = ''
        self.root.__datatypestr__ = ''
        self.root.__parent__ = None
        self.setColumnCount(3)
        self.create_qtree()
        #self.itemExpanded.connect(self.resize_view)
        #self.itemCollapsed.connect(self.resize_view)

    def reload_data(self,data):
        self.data = data
        self.clear()
        self.create_qtree()
        self.expandAll()
        self.resizeColumnToContents(0)

    def seq_iter(self,obj):
        return redvypr.utils.seq_iter(obj)

    def create_item(self, index, data, parent):
        """
        Creates recursively qtreewidgetitems. If the item to be created is a sequence (dict or list), it calls itself as often as it finds a real value
        Args:
            index:
            data:
            parent:

        Returns:

        """
       # print('data0',data)
        try:
            sequence = self.seq_iter(data.value)
        except:
            sequence = self.seq_iter(data)
        #print('Data',sequence)
        if(sequence == None): # Check if we have an item that is something with data (not a list or dict)
            data_value = data.value  # Data is a configdata object, or list or dict
            #print('Data value',str(data_value),data)
            flag_configdata = False
            try:
                typestr = data.template['type']
                flag_configdata = True
            except:
                typestr = data_value.__class__.__name__


            item       = QtWidgets.QTreeWidgetItem([str(index), str(data_value),typestr])
            #item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)  # editable
            item.__data__ = data
            item.__dataparent__   = parent.__data__ # can be used to reference the data (and change it)
            item.__dataindex__    = index
            item.__datatypestr__  = typestr
            item.__parent__       = parent

            index_child = self.item_is_child(parent, item)
            if  index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(item)
            else: # Update the data (even if it hasnt changed
                parent.child(index_child).setText(1,str(data_value))

        else:
            #print('loop')
            try:
                datatmp = data.value
            except:
                datatmp = data


            typestr = datatmp.__class__.__name__
            flag_modifiable = False
            try:
                options = data.template['options'] # Modifiable list (configdata with value "list")
                flag_modifiable = True
            except:
                options = None

            if(index is not None):
                indexstr = index
            newparent = QtWidgets.QTreeWidgetItem([str(index), '',typestr])
            item = newparent
            newparent.__data__         = datatmp
            newparent.__dataindex__    = index
            newparent.__datatypestr__  = typestr
            newparent.__parent__       = parent
            newparent.__modifiable__   = flag_modifiable
            try:
                newparent.__dataparent__ = parent.__data__  # can be used to reference the data (and change it)
            except:
                newparent.__dataparent__ = None
            if (options is not None):  # Modifiable list
                #print('List item, adding options')
                newparent.__options__ = options



            index_child = self.item_is_child(parent, newparent)
            if index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(newparent)
            else:
                newparent = parent.child(index_child)

            for newindex in sequence:
                newdata = datatmp[newindex]
                self.create_item(newindex,newdata,newparent)

    def item_is_child(self,parent,child):
        """
        Checks if the item is a child already

        Args:
            parent:
            child:

        Returns:

        """
        numchilds  = parent.childCount()
        for i in range(numchilds):
            testchild = parent.child(i)
            #flag1 = testchild.__data__        == child.__data__
            flag1 = True
            flag2 = testchild.__dataindex__   == child.__dataindex__
            #flag3 = testchild.__datatypestr__ == child.__datatypestr__
            flag3 = True
            flag4 = testchild.__parent__      == child.__parent__

            #print('fdsfd',i,testchild.__data__,child.__data__)
            #print('flags',flag1,flag2,flag3,flag4)
            if(flag1 and flag2 and flag3 and flag4):
                return i

        return None

    def create_qtree(self, editable=True):
        """Creates a new qtree from the configuration and replaces the data in
        the dictionary with a configdata obejct, that save the data
        but also the qtreeitem, making it possible to have a synced
        config dictionary from/with a qtreewidgetitem. TODO: Worth to
        replace with a qviewitem?

        """
        funcname = __name__ + '.create_qtree():'
        logger.debug(funcname)
        self.blockSignals(True)
        if True:
            self.create_item(self.dataname,self.data,self.root)

        self.dataitem = self.root.child(0)
        self.resizeColumnToContents(0)
        self.blockSignals(False)

    def resize_view(self):
        pass
        print('resize ...')
        #self.resizeColumnToContents(0)










#
#
# configWidget
#
#
class configWidget(QtWidgets.QWidget):
    config_changed = QtCore.pyqtSignal(dict)  # Signal notifying that the configuration has changed
    config_changed_flag = QtCore.pyqtSignal()  # Signal notifying that the configuration has changed
    def __init__(self, config={}, template={}, loadsavebutton=True,redvypr_instance=None):
        funcname = __name__ + '.__init__():'
        super().__init__()
        self.redvypr=redvypr_instance
        config_tmp   = redvypr.config.dict_to_configDict(config)
        template_tmp = redvypr.config.dict_to_configDict(template)
        self.layout = QtWidgets.QGridLayout(self)
        self.layout.setColumnStretch(0, 1)
        self.layout.setColumnStretch(1, 1)
        try:
            configname = config['name']
        except:
            configname = 'config'

        logger.debug(funcname + 'Applying config to template')
        self.config = redvypr.config.apply_config_to_configDict(config_tmp, template_tmp)

        self.configtree = redvypr_config_tree(data = self.config,dataname=configname)
        self.configtree.expandAll()
        self.configtree.resizeColumnToContents(0)

        #self.itemExpanded.connect(self.resize_view)
        #self.itemCollapsed.connect(self.resize_view)
        self.configtree.itemDoubleClicked.connect(self.__open_config_gui)
        #self.configtree.itemChanged.connect(self.item_changed)  # If an item is changed
        #self.configtree.currentItemChanged.connect(self.current_item_changed)  # If an item is changed
        self.configgui = QtWidgets.QWidget() # Widget where the user can modify the content
        self.configgui_layout = QtWidgets.QVBoxLayout(self.configgui)

        if(loadsavebutton):
            # Add load/save buttons
            self.load_button = QtWidgets.QPushButton('Load')
            self.load_button.clicked.connect(self.load_config)
            self.save_button = QtWidgets.QPushButton('Save')
            self.save_button.clicked.connect(self.save_config)

        self.layout.addWidget(self.configtree,0,0)
        self.layout.addWidget(self.configgui, 0, 1)
        if (loadsavebutton):
            self.layout.addWidget(self.load_button, 1, 0)
            self.layout.addWidget(self.save_button, 1, 1)

    def reload_config(self):
        """
        Clears the configtree and redraws it. Good after a third person change of the configuration
        Returns:

        """
        funcname = __name__ + '.reload_config():'
        logger.debug(funcname)
        self.configtree.reload_data(self.config)

    def load_config(self):
        funcname = __name__ + '.load_config():'
        fname_open = QtWidgets.QFileDialog.getOpenFileName(self, 'Open file', '',"YAML files (*.yaml);; All files (*)")
        if(len(fname_open[0]) > 0):
            logger.info(funcname + 'Opening file {:s}'.format(fname_open[0]))
            fname = fname_open[0]
            with open(fname, 'r') as yfile:
                config = yaml.safe_load(yfile)
                conftemplate = configtemplate_to_dict(template=self.template)
                if (config is not None):
                    logger.debug(funcname + 'Applying config to template')
                    self.config = redvypr.utils.apply_config_to_dict(config, conftemplate)
                    print('New config:',config)
                    self.reload_config()


    def save_config(self):
        funcname = __name__ + '.save_config():'
        fname_open = QtWidgets.QFileDialog.getSaveFileName(self, 'Save file', '',"YAML files (*.yaml);; All files (*)")
        if(len(fname_open[0]) > 0):
            logger.info(funcname + 'Save file file {:s}'.format(fname_open[0]))
            print('Saving', self.configtree.data)
            config = copy.deepcopy(self.configtree.data)
            print('Deepcopy', config)
            fname = fname_open[0]
            with open(fname, 'w') as yfile:
                yaml.dump(config, yfile)

    def get_config(self):
        """
        Returns a configuation dictionary of the qtreewidgetitem

        Returns:

        """
        config = copy.deepcopy(self.configtree.data)
        return config


    def __open_config_gui(self,item):
        """
        After an item was clicked this function checks if there is a configuration gui for that type of data, if yes open that configuration
        widget
        Returns:

        """
        funcname = __name__ + '.__open_config_gui():'
        data = item.__data__
        try:
            options = item.__options__
        except:
            options = None

        try:
            modifiable = item.__modifiable__
        except:
            modifiable = False

        try:
            modifiable_parent = item.__parent__.__modifiable__
        except:
            modifiable_parent = False


        if (type(data) == dict) and modifiable_parent: # A template dictionary item in a modifiable list
            pass
        elif((type(data) == list) or (type(data) == dict)) and not(modifiable):
            return

        try:
            dtype = data.template['type']
        except:
            if(type(data) == redvypr.utils.configdata):
                dtype = data.value.__class__.__name__
            else:
                dtype = data.__class__.__name__

            #print('dtpye',dtype)
            #dtype = 'str'

        print(funcname, type(data), modifiable, modifiable_parent,dtype)
        item.__datatype__ = dtype
        self.remove_input_widgets()
        if (dtype == 'configDict'):
            print(funcname + 'configDict')
            self.config_widget_dict(item)
        elif(dtype == 'int'):
            self.config_widget_number(item,'int')
        elif (dtype == 'float'):
            self.config_widget_number(item,'float')
        elif (dtype == 'datastream'):
            self.config_widget_datastream(item)
        elif (dtype == 'color'):
            self.config_widget_color(item)
        elif (dtype == 'bool'):
            #
            data.template['options'] = ['False','True']
            self.config_widget_str_combo(item)
        elif(dtype == 'str'):
            # If we have options
            try:
                data.template['options']
                self.config_widget_str_combo(item)
            # Let the user enter
            except Exception as e:
                print('Exception',e)
                self.config_widget_str(item)
        elif (dtype == 'list'): # Modifiable list
            self.config_widget_list_combo(item)
            #print('List')


    def __config_widget_button(self):
        """
        Applies the changes of the configuration widget

        Returns:

        """
        funcname = __name__ + '.__config_widget_button(): '
        btn = self.sender()
        if(btn == self.__configwidget_apply):
            item = btn.item
            dtype = item.__datatype__
            logger.debug(funcname + 'Apply')
            print('dtype',dtype)
            data = None
            btntext = btn.text()
            try:
                flag_remove = btn.__removeitem__
            except:
                flag_remove = False
            #print('btntext',btntext)
            if (flag_remove):  # Add/Remove from list
                logger.debug(funcname + ' Removing item')
                item.__dataparent__.remove(item.__data__)
                self.reload_config()
                config = self.get_config()
                self.config_changed_flag.emit()
                self.config_changed.emit(config)
                return
            if (btn.__type__ == 'dict'):  # Add/Remove from dictionary
                print('dict')
                type_add = self.__configwidget_input.currentText() # combobox
                key_add  = self.__configwidget_key.text()
                print('Type to be added',type_add)
                print('Key to be added', key_add)
                return
            if (dtype == 'list'):  # Add/Remove from list
                #print('Add to list')
                templatename = str(self.__configwidget_input.currentText())
                template_options = item.__options__
                template_names = []
                newitem_dict = redvypr.utils.configdata(None)
                for t in template_options:
                    if(templatename == t['template_name']):
                        #print('Found template')
                        configdict = redvypr.utils.configtemplate_to_dict(t)
                        newitem_dict = configdict


                #print(item.__dataparent__[item.__dataindex__])


                #print('tname',templatename)
                template = item.__dataparent__[item.__dataindex__].template
                #print('Template')
                item.__dataparent__[item.__dataindex__].value.append(newitem_dict)
                #print(item.__dataparent__[item.__dataindex__])
                self.reload_config()
                config = self.get_config()
                self.config_changed_flag.emit()
                self.config_changed.emit(config)
                return

            elif (dtype == 'datastream'):
                data = self.__configwidget_input.datastreamcustom.text()

            elif (dtype == 'color'):
                color = self.__configwidget_input.currentColor()
                rgb = color.getRgb()
                data = list(rgb)

            # TODO, check what kind of widget we have here
            if (data is None):
                try:
                    data = self.__configwidget_input.value() # Works for int/float spinboxes
                except:
                    pass

            if (data is None):
                try:
                    data = self.__configwidget_input.text() # Works for lineedits (str)
                except:
                    pass
            if (data is None):
                try:
                    data = str(self.__configwidget_input.currentText()) # Works for comboboxes (combo_str)
                except Exception as e:
                    pass

                #print('DATADATATAT',data,type(data),dtype,bool(data))
                # Test if we have a bool
                if(dtype == 'bool'):
                    data = data.lower() == 'True'

            if(data is not None):
                logger.debug(funcname + 'Got data')
                print('data',data)
                item.setText(1,str(data))
                try: # If configdata
                    item.__dataparent__[item.__dataindex__].value = data
                except:
                    item.__dataparent__[item.__dataindex__] = data
            else:
                logger.debug(funcname + 'No valid data')

        elif (btn == self.__configwidget_remove):
            print('remove')
        else:
            logger.debug(funcname + 'unknown button')

        config = self.get_config()
        self.config_changed_flag.emit()
        self.config_changed.emit(config)

    def config_widget_color(self, item):
        """
                Lets the user choose a color
                Args:
                    item:

                Returns:

                """
        self.remove_input_widgets()

        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QVBoxLayout(self.__configwidget_int)
        # The color dialog
        colorwidget = QtWidgets.QColorDialog(self.__configwidget_int)
        colorwidget.setOptions(QtWidgets.QColorDialog.NoButtons| QtWidgets.QColorDialog.DontUseNativeDialog)
        colorwidget.setWindowFlags(QtCore.Qt.Widget)
        self.__configwidget_input = colorwidget
        self.__layoutwidget_int.addWidget(colorwidget)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addWidget(self.__configwidget_apply)
        colorwidget.open()
        #self.__layoutwidget_int.addWidget(self.w)

    def config_widget_datastream(self, item):
        """
        Lets the user change a datastream
        Args:
            item:

        Returns:

        """
        self.remove_input_widgets()
        datastreamwidget = redvypr_devicelist_widget(redvypr=self.redvypr, showapplybutton=False)
        datastreamwidget.item     = item
        self.__configwidget_input = datastreamwidget
        self.__configwidget_int   = QtWidgets.QWidget()
        self.__layoutwidget_int   = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__layoutwidget_int.addRow(datastreamwidget)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addRow(self.__configwidget_apply)

    def config_widget_number(self, item, dtype='int'):
        """
        Creates a widgets to modify an integer value

        Returns:

        """
        index = item.__dataindex__
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        #self.__configwidget_input = QtWidgets.QLineEdit()
        if(dtype=='int'):
            self.__configwidget_input = QtWidgets.QSpinBox()
            self.__configwidget_input.setRange(int(-1e9),int(1e9))
            try:
                value = int(item.text(1))
            except:
                value = 0
            self.__configwidget_input.setValue(value)
        else:
            self.__configwidget_input = QtWidgets.QDoubleSpinBox()
            self.__configwidget_input.setRange(-1e9, 1e9)
            try:
                value = float(item.text(1))
            except:
                value = 0.0
            self.__configwidget_input.setValue(value)

        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Enter value for {:s}'.format(index)))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.__layoutwidget_int.addRow(self.__configwidget_apply)
        self.configgui_layout.addWidget(self.__configwidget_int)

    def config_widget_str(self,item):

        index = item.__dataindex__
        data = ''
        try:
            data = str(item.__data__)
        except:
            pass
        try:
            data = str(item.__data__.value)
        except:
            pass

        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__configwidget_input = QtWidgets.QLineEdit()
        self.__configwidget_input.setText(data)
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Enter string for {:s}'.format(index)))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addRow(self.__configwidget_apply)


    def config_widget_str_combo(self, item):
        index = item.__dataindex__
        data  = item.__data__
        options = data.template['options']
        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__configwidget_input = QtWidgets.QComboBox()
        for option in options:
            self.__configwidget_input.addItem(option)
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Options for {:s}'.format(index)))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addRow(self.__configwidget_apply)

    def config_widget_list_combo(self, item):
        """
        Config widget for a modifiable list
        Args:
            item:

        Returns:

        """
        index = item.__dataindex__
        data = item.__data__
        template_options = item.__options__
        options = []
        for t in template_options:
            options.append(t['template_name'])
        print('Options',options)
        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__configwidget_input = QtWidgets.QComboBox()
        for option in options:
            self.__configwidget_input.addItem(option)
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Options for {:s}'.format(index)))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Add')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.configgui_layout.addWidget(self.__configwidget_int)
        self.__layoutwidget_int.addRow(self.__configwidget_apply)


    def config_widget_dict(self, item):
        """
        Config widget to edit (at the moment remove) a dictionary item
        Args:
            item:

        Returns:

        """

        funcname = __name__ + '.config_widget_dict(): '
        logger.debug(funcname)
        index = item.__dataindex__
        data = item.__data__
        parent = item.__parent__
        parentparent = parent.__parent__
        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)

        self.__configwidget_key = QtWidgets.QLineEdit('data1')
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Dict key'),self.__configwidget_key)

        self.__configwidget_input = QtWidgets.QComboBox()
        for t in redvypr.config.template_types:
            self.__configwidget_input.addItem(t['type'])

        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Type'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Add')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.__configwidget_apply.__type__ = 'dict'
        self.__layoutwidget_int.addRow(self.__configwidget_apply)
        # Buttons
        if(parentparent is not None):
            self.__configwidget_remove = QtWidgets.QPushButton('Remove')
            self.__configwidget_remove.clicked.connect(self.__config_widget_button)
            self.__configwidget_remove.item = item
            self.__configwidget_remove.__removeitem__ = True
            self.__layoutwidget_int.addRow(self.__configwidget_remove)

        self.configgui_layout.addWidget(self.__configwidget_int)



    def remove_input_widgets(self):
        """
        Removes all widgets from configgui
        Returns:

        """
        layout = self.configgui_layout
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        #for i in range(len(self.__configgui_list)):
        #    widget = self.__configgui_list.pop()
        #    self.configgui_layout.remWidget(widget)




#
#
#
#
#
class configQTreeWidget(QtWidgets.QTreeWidget):
    """ Qtreewidget that display a configDict data structure
    """

    def __init__(self, data={}, dataname='data'):
        funcname = __name__ + '.__init__():'
        super().__init__()
        if(type(data) == dict): # Convert to configDict to allow to store extra attributes
            data = redvypr.config.dict_to_configDict(data)
        elif (type(data) == redvypr.config.configDict) or (type(data) == redvypr.config.configuration):
            print(funcname,'Type config')
            pass
        else:
            raise TypeError(funcname + ' Expecting a dict or a configDict as data')
        logger.debug(funcname + str(data))
        self.setExpandsOnDoubleClick(False)
        # make only the first column editable
        #self.setEditTriggers(self.NoEditTriggers)
        #self.header().setVisible(False)
        self.setHeaderLabels(['Variable','Value','Type'])
        self.data     = data
        self.dataname = dataname
        # Create the root item
        self.root = self.invisibleRootItem()
        #self.root.__data__ = data
        self.root.__dataindex__ = ''
        self.root.__datatypestr__ = ''
        self.root.__parent__ = None
        self.setColumnCount(3)
        self.create_qtree()
        #self.itemExpanded.connect(self.resize_view)
        #self.itemCollapsed.connect(self.resize_view)

    def reload_data(self,data):
        self.data = data
        self.clear()
        self.create_qtree()
        self.expandAll()
        self.resizeColumnToContents(0)

    def seq_iter(self,obj):
        return redvypr.utils.seq_iter(obj)

    def create_item(self, index, data, parent):
        """
        Creates recursively qtreewidgetitems. If the item to be created is a sequence (dict or list), it calls itself as often as it finds a real value
        Args:
            index:
            data:
            parent:

        Returns:

        """
        sequence = self.seq_iter(data)
        #print('Data',sequence)
        if(sequence == None): # Check if we have an item that is something with data (not a list or dict)
            data_value = data  #
            #print('Data value',str(data_value),data)
            flag_configdata = False
            try:
                typestr = data.template['type']
                flag_configdata = True
            except:
                typestr = data_value.__class__.__name__


            item       = QtWidgets.QTreeWidgetItem([str(index), str(data_value),typestr])
            #item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)  # editable
            item.__data__ = data
            item.__dataparent__   = parent.__data__ # can be used to reference the data (and change it)
            item.__dataindex__    = index
            item.__datatypestr__  = typestr
            item.__parent__       = parent
            # Add the item to the data
            data.__item__ = item

            index_child = self.item_is_child(parent, item)
            if  index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(item)
            else: # Update the data (even if it hasnt changed
                parent.child(index_child).setText(1,str(data_value))

        else:
            #print('loop')
            datatmp = data


            typestr = datatmp.__class__.__name__
            flag_modifiable = False
            try:
                options = data.template['options'] # Modifiable list (configdata with value "list")
                flag_modifiable = True
            except:
                options = None

            if(index is not None):
                indexstr = index
            newparent = QtWidgets.QTreeWidgetItem([str(index), '',typestr])
            item = newparent
            newparent.__data__         = datatmp
            newparent.__dataindex__    = index
            newparent.__datatypestr__  = typestr
            newparent.__parent__       = parent
            newparent.__modifiable__   = flag_modifiable
            try:
                newparent.__dataparent__ = parent.__data__  # can be used to reference the data (and change it)
            except:
                newparent.__dataparent__ = None
            if (options is not None):  # Modifiable list
                #print('List item, adding options')
                newparent.__options__ = options



            index_child = self.item_is_child(parent, newparent)
            if index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(newparent)
            else:
                newparent = parent.child(index_child)

            for newindex in sequence:
                newdata = datatmp[newindex]
                self.create_item(newindex,newdata,newparent)

    def item_is_child(self,parent,child):
        """
        Checks if the item is a child already

        Args:
            parent:
            child:

        Returns:

        """
        numchilds  = parent.childCount()
        for i in range(numchilds):
            testchild = parent.child(i)
            #flag1 = testchild.__data__        == child.__data__
            flag1 = True
            flag2 = testchild.__dataindex__   == child.__dataindex__
            #flag3 = testchild.__datatypestr__ == child.__datatypestr__
            flag3 = True
            flag4 = testchild.__parent__      == child.__parent__

            #print('fdsfd',i,testchild.__data__,child.__data__)
            #print('flags',flag1,flag2,flag3,flag4)
            if(flag1 and flag2 and flag3 and flag4):
                return i

        return None

    def create_qtree(self, editable=True):
        """Creates a new qtree from the configuration and replaces the data in
        the dictionary with a configdata obejct, that save the data
        but also the qtreeitem, making it possible to have a synced
        config dictionary from/with a qtreewidgetitem. TODO: Worth to
        replace with a qviewitem?

        """
        funcname = __name__ + '.create_qtree():'
        logger.debug(funcname)
        self.blockSignals(True)
        if True:
            self.create_item(self.dataname,self.data,self.root)

        self.dataitem = self.root.child(0)
        self.resizeColumnToContents(0)
        self.blockSignals(False)

    def resize_view(self):
        pass
        print('resize ...')
        #self.resizeColumnToContents(0)

