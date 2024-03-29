import copy
import time
import logging
import sys
import yaml
from PyQt5 import QtWidgets, QtCore, QtGui
import pydantic
from redvypr.configdata import configtemplate_to_dict
from redvypr.device import redvypr_device
from redvypr.widgets.redvypr_addressWidget import datastreamWidget
import redvypr.configdata
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




class pdDeviceConfigWidget(QtWidgets.QWidget):
    """
    Config widget for a pydantic configuration
    """
    def __init__(self, device = None):
        funcname = __name__ + '.__init__():'
        super().__init__()
        logger.debug(funcname)
        self.device = device
        self.layout = QtWidgets.QGridLayout(self)
        self.label = QtWidgets.QLabel('Configuration of\n{:s}'.format(self.device.name))
        self.layout.addWidget(self.label)
        dataname = self.device.name + '.config'
        self.configWidget = pydanticQTreeWidget(self.device.config, dataname=dataname)
        self.layout.addWidget(self.configWidget)
        self.setWindowIcon(QtGui.QIcon(_icon_file))




#
#
# configWidget
#
#
class configWidget(QtWidgets.QWidget):
    #config_changed = QtCore.pyqtSignal(dict)  # Signal notifying that the configuration has changed
    config_changed_flag = QtCore.pyqtSignal()  # Signal notifying that the configuration has changed
    def __init__(self, config=None, loadsavebutton=False, redvypr_instance=None, show_datatype = False, editable = True, configname = None):
        funcname = __name__ + '.__init__():'
        if config == None:
            config = redvypr.config.configuration({})
        super().__init__()
        logger.debug(funcname)
        self.redvypr= redvypr_instance
        self.layout = QtWidgets.QGridLayout(self)

        if configname is None:
            try:
                configname = config['name']
            except:
                configname = 'config'


        self.config = config
        self.configtree = configQTreeWidget(data = self.config, dataname=configname, show_datatype = show_datatype)
        self.configtree.expandAll()
        self.configtree.resizeColumnToContents(0)

        #self.itemExpanded.connect(self.resize_view)
        #self.itemCollapsed.connect(self.resize_view)
        if editable:
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

        self.layout.addWidget(self.configtree, 0, 0)
        if editable:
            self.layout.addWidget(self.configgui, 0, 1)
            self.layout.setColumnStretch(0, 1)
            self.layout.setColumnStretch(1, 1)
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
        self.remove_input_widgets()
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
                    self.config = redvypr.configdata.apply_config_to_dict(config, conftemplate)
                    logger.debug(funcname + 'New config: {:s}'.format(str(config)))
                    self.reload_config()


    def save_config(self):
        funcname = __name__ + '.save_config():'
        logger.debug(funcname)
        #print('Save',self.config)
        if True:
            fname_open = QtWidgets.QFileDialog.getSaveFileName(self, 'Save file', '',"YAML files (*.yaml);; All files (*)")
            if(len(fname_open[0]) > 0):
                logger.info(funcname + 'Save file file {:s}'.format(fname_open[0]))
                #print('Saving', self.configtree.data)
                config = copy.deepcopy(self.configtree.data)
                #print('Deepcopy', config)
                fname = fname_open[0]
                with open(fname, 'w') as yfile:
                    yaml.dump(config, yfile)

    def get_config(self):
        """
        Returns a copy of the configuration dictionary of the qtreewidgetitem

        Returns:
             config: config dictionary
        """
        config = copy.deepcopy(self.configtree.data)
        return config

    def apply_config_change(self):
        """
        Sends signals with the changed configuration
        Returns:

        """
        funcname = __name__ + '.apply_config_change():'
        logger.debug(funcname)
        self.config_changed_flag.emit()

    def __open_config_gui(self,item):
        """
        After an item was clicked this function checks if there is a configuration gui for that type of data, if yes open that configuration
        widget
        Returns:

        """
        funcname = __name__ + '.__open_config_gui():'
        logger.debug(funcname)
        #print('Hallo gui', type(self.config))
        data = item.__data__
        #print('Hallo gui data', type(data))
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
            dtype = data.template['subtype']
        except:
            dtype = data.__class__.__name__

        #print(data.template)
        #print(funcname, type(data), modifiable, modifiable_parent,dtype)
        item.__datatype__ = dtype
        data = item.__data__
        self.remove_input_widgets()
        if (dtype == 'configDict') or (dtype == 'configuration'):
            logger.debug(funcname + 'configDict')
            self.config_widget_dict(item)
        elif (dtype == 'configList'):  # Modifiable list
            logger.debug(funcname + 'configList')
            self.config_widget_list_combo(item)
        elif (dtype == 'configNumber'):
            dtype_data = type(data.data)
            logger.debug(funcname + 'configNumber {:s}'.format(str(dtype_data)))
            if(dtype_data == int):
                self.config_widget_number(item,'int')
            elif (dtype_data == float):
                self.config_widget_number(item,'float')
            elif (dtype_data == bool):
                options = ['False', 'True']
                self.config_widget_str_combo(item,options)
        elif (dtype == 'datastream'):
            logger.debug(funcname + 'Datastream')
            self.config_widget_datastream(item)
        elif (dtype == 'color'):
            self.config_widget_color(item)

        elif(dtype == 'configString'):
            try:
                options = data.options
            except:
                options = None
            # If we have options
            if options is not None:
                self.config_widget_str_combo(item)
            # Let the user enter
            else:
                self.config_widget_str(item)


    #
    # Function is called when "apply" or "remove" is clicked
    #
    def __config_widget_button(self):
        """
        Applies the changes of the configuration widget

        Returns:

        """
        funcname = __name__ + '.__config_widget_button(): '
        btn = self.sender()
        item = btn.item
        data = item.__data__
        dataindex = item.__dataindex__
        if btn == self.__configwidget_apply:
            dtype = item.__datatype__
            logger.debug(funcname + 'Apply')
            logger.debug(funcname + 'dtype {:s}'.format(str(dtype)))
            btntext = btn.text()
            if (btn.__type__ == 'dict'):  # Add/Remove from dictionary
                logger.debug(funcname + 'dict')

                logger.debug(funcname + 'Add to list')
                type_add = self.__configwidget_input.currentText()  # combobox
                options_items_add = self.__configwidget_input.__options__item__  # Dictionary with the items
                data_add = options_items_add[type_add]  # The item to be added
                logger.debug(funcname + 'Type to be added {:s}'.format(str(type_add)))
                data_add.__parent__ = data
                key_add  = self.__configwidget_key.text()
                logger.debug(funcname + 'Type to be added {:s}'.format(str(type_add)))
                logger.debug(funcname + 'Key to be added'.format(str(key_add)))
                if(key_add not in data.keys()):
                    logger.debug('Adding key {:s} data_add {:s}'.format(str(key_add),str(data_add)))
                    data[key_add] = data_add
                else:
                    logger.info(funcname + 'key {:s} does already exist'.format(key_add))

                self.reload_config()
                self.apply_config_change()
                return
            if (btn.__type__ == 'list'):  # Add/Remove from list
                logger.debug(funcname + 'Add to list')
                type_add  = self.__configwidget_input.currentText()  # combobox
                options_items_add = self.__configwidget_input.__options__item__ # Dictionary with the items
                data_add = options_items_add[type_add] # The item to be added
                logger.debug(funcname + 'Type to be added {:s}'.format(str(type_add)))
                # TODO, this should be done in the append function of the configList
                data_add.__parent__ = data
                data.append(data_add)
                self.reload_config()
                self.apply_config_change()
                return

            elif (btn.__type__ == 'str'):  # Add/Remove from list
                try:
                    data_str = self.__configwidget_input.text()  # Works for lineedits (str)
                except:
                    pass

                logger.debug(funcname + ' str {:s}'.format(str(type(self.config))))
                data.data = data_str
                item.setText(1, str(data_str))
                self.apply_config_change()
                return

            elif (btn.__type__ == 'int') or (btn.__type__ == 'float'):  # Add/Remove from list
                data_num = self.__configwidget_input.value() # Works for int/float spinboxes
                data.data = data_num
                item.setText(1, str(data_num))
                self.apply_config_change()
                return

            elif btn.__type__ == 'strcombo':
                data_str = str(self.__configwidget_input.currentText())  # Works for comboboxes (combo_str)
                if (type(data.data) == bool):
                    data.data = data_str == 'True'
                else:
                    data.data = data_str

                item.setText(1, str(data_str))
                self.apply_config_change()
                return

            elif btn.__type__ == 'datastream':
                logger.debug( funcname + 'Datastream')
                data.data = self.__configwidget_input.addressline.text()
                item.setText(1, str(data.data))
                self.apply_config_change()
                return

            elif btn.__type__ == 'color':
                logger.debug( funcname + 'Color')
                color = self.__configwidget_input.currentColor()
                rgb = color.getRgb()
                data['r'].data = rgb[0]
                data['g'].data = rgb[1]
                data['b'].data = rgb[2]
                data['a'].data = rgb[3]
                self.reload_config()
                self.apply_config_change()
                return

        elif btn == self.__configwidget_remove:
            #if (btn.__type__ == 'dict'):  # Add/Remove from list
            logger.debug( funcname + 'Removing item')
            #print('parent',data.__parent__,type(data.__parent__))
            #print('index',dataindex)
            data.__parent__.pop(dataindex)
            #print('config',self.get_config())
            self.reload_config()
        else:
            logger.debug(funcname + 'unknown button')

        self.apply_config_change()
        self.__configwidget_input.close()


    #
    # The configuration widgets
    #
    def config_widget_color(self, item):
        """
                Lets the user choose a color
                Args:
                    item:

                Returns:

        """
        funcname = __name__ + '.config_widget_color():'
        index = item.__dataindex__
        parent = item.__parent__
        data = item.__data__
        parentparent = parent.__parent__
        self.remove_input_widgets()

        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QVBoxLayout(self.__configwidget_int)
        color = QtGui.QColor(data['r'], data['g'], data['b'])#, data['a'])
        #color = QtGui.QColor(255, 0, 0)  # , data['a'])
        logger.debug(funcname + 'Color {:s}, {:s}'.format(str(data),str(color.getRgb())))
        # The color dialog
        colorwidget = QtWidgets.QColorDialog(self.__configwidget_int)
        colorwidget.setOptions(QtWidgets.QColorDialog.NoButtons| QtWidgets.QColorDialog.DontUseNativeDialog)
        colorwidget.setWindowFlags(QtCore.Qt.Widget)
        colorwidget.setCurrentColor(color)
        self.__configwidget_input = colorwidget
        self.__layoutwidget_int.addWidget(colorwidget)
        # Buttons
        self.__add_apply_btn__(self.__layoutwidget_int, item=item, dtype='color')
        if (parentparent is not None):
            self.__add_remove_btn__(self.__layoutwidget_int, item=item, dtype='color')

        self.configgui_layout.addWidget(self.__configwidget_int)
        colorwidget.open()
        #self.__layoutwidget_int.addWidget(self.w)

    def config_widget_datastream(self, item):
        """
        Lets the user change a datastream
        Args:
            item:

        Returns:

        """
        funcname = __name__ + '.config_widget_datastream():'
        logger.debug(funcname)
        index = item.__dataindex__
        parent = item.__parent__
        data = item.__data__
        parentparent = parent.__parent__
        self.remove_input_widgets()
        datastreamwidget = datastreamWidget(redvypr=self.redvypr, showapplybutton=False,datastreamstring=data.data)
        datastreamwidget.item     = item
        self.__configwidget_input = datastreamwidget
        self.__configwidget_int   = QtWidgets.QWidget()
        self.__layoutwidget_int   = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__layoutwidget_int.addRow(datastreamwidget)

        self.__add_apply_btn__(self.__layoutwidget_int, item=item, dtype='datastream')
        if (parentparent is not None):
            self.__add_remove_btn__(self.__layoutwidget_int, item=item, dtype='datastream')

        self.configgui_layout.addWidget(self.__configwidget_int)

    def config_widget_number(self, item, dtype='int'):
        """
        Creates a widgets to modify an integer value

        Returns:

        """
        index = item.__dataindex__
        parent = item.__parent__
        data = item.__data__
        parentparent = parent.__parent__
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

        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Enter value for {:s}'.format(str(index))))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)

        # Buttons
        self.__add_apply_btn__(self.__layoutwidget_int, item=item, dtype='int')
        if (parentparent is not None):
            self.__add_remove_btn__(self.__layoutwidget_int, item=item, dtype='int')

        self.configgui_layout.addWidget(self.__configwidget_int)

    def config_widget_str(self,item):

        index = item.__dataindex__
        parent = item.__parent__
        data = item.__data__
        parentparent = parent.__parent__

        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__configwidget_input = QtWidgets.QLineEdit()
        self.__configwidget_input.setText(str(data))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Enter string for {:s}'.format(str(index))))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__add_apply_btn__(self.__layoutwidget_int, item=item, dtype='str')
        if (parentparent is not None): # Remove button
            self.__add_remove_btn__(self.__layoutwidget_int, item=item, dtype='str')
            try:
                removable = parent.__data__.children_removable
            except Exception as e:
                removable = True

            self.__configwidget_remove.setEnabled(removable)

        self.configgui_layout.addWidget(self.__configwidget_int)


    def config_widget_str_combo(self, item,options=None):
        index = item.__dataindex__
        data = item.__data__
        parent = item.__parent__
        parentparent = parent.__parent__

        index = item.__dataindex__
        data  = item.__data__
        #options = data.template['options']
        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__configwidget_input = QtWidgets.QComboBox()
        for option in options:
            self.__configwidget_input.addItem(option)
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Options for {:s}'.format(str(index))))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__add_apply_btn__(self.__layoutwidget_int, item=item, dtype='strcombo')
        if (parentparent is not None):
            self.__add_remove_btn__(self.__layoutwidget_int, item=item, dtype='strcombo')
            try:
                removable = parent.__data__.children_removable
            except Exception as e:
                removable = True

            self.__configwidget_remove.setEnabled(removable)

        self.configgui_layout.addWidget(self.__configwidget_int)


    def get_options_from_config(self,options):
        funcname = __name__ + '.get_options_from_config():'
        options_tmp = options
        # Fill the options combo and the corresponding items
        options_str = []  # The strings used in the combo box
        options_item = {}  # A dictionary that helps to quickly get the item having the str
        try:  # First have a look if there are template options
            logger.debug(funcname + 'Using template options')
            logger.debug(funcname + 'Options are {:s}'.format(str(options_tmp)))
            for o in options_tmp:
                # print('option',o)
                # print('------------------')
                if (
                        'type' in o.keys()):  # This is a default entry from redvypr.config.__template_types__modifiable_list_dict__
                    try:
                        tempname = o['type']
                        # opt_tmp = redvypr.config.template_types_dict[tempname]
                        data_item = o['default']
                        data_item = redvypr.config.data_to_configdata(data_item)
                        data_item.template = o  # Add the template
                        try:
                            data_item.subtype = o['subtype']
                        except:
                            pass

                        options_str.append(tempname)
                        options_item[tempname] = data_item
                    except Exception as e:
                        logger.exception(e)
                        logger.debug(funcname + 'Could not find template type for {:s}'.format(str(o)))
                elif ('template_name' in o.keys()):
                    tempname = o['template_name']
                    data_item = redvypr.config.dict_to_configDict(o, process_template=True)
                    data_item.template = o  # Add the template
                    options_str.append(tempname)
                    options_item[tempname] = data_item

        except Exception as e:  # First have a look if there are template options
            logger.exception(e)

        return [options_str, options_item]

    def config_widget_list_combo(self, item):
        """
        Config widget for a modifiable list
        Args:
            item:

        Returns:

        """
        funcname = __name__ + '.config_widget_list_combo():'
        index = item.__dataindex__
        data = item.__data__
        parent = item.__parent__
        parentparent = parent.__parent__

        #template_options = item.__options__
        #options = []
        #for t in template_options:
        #    options.append(t['template_name'])
        self.remove_input_widgets()
        self.__configwidget_int = QtWidgets.QWidget()
        self.__layoutwidget_int = QtWidgets.QFormLayout(self.__configwidget_int)
        self.__configwidget_input = QtWidgets.QComboBox()
        # Fill the options combo and the corresponding items
        options_str = [] # The strings used in the combo box
        options_item = {} # A dictionary that helps to quickly get the item having the str
        try: # First have a look if there are template options
            options_tmp = data.options
            logger.debug(funcname + 'Template is'.format(str(data.template)))
            logger.debug(funcname + 'Using template options')
            logger.debug(funcname + 'Options are {:s}'.format(str(options_tmp)))
            for o in options_tmp:
                #print('option',o)
                #print('------------------')
                if('type' in o.keys()): # This is a default entry from redvypr.config.__template_types__modifiable_list_dict__
                    try:
                        tempname = o['type']
                        #opt_tmp = redvypr.config.template_types_dict[tempname]
                        data_item = o['default']
                        data_item = redvypr.config.data_to_configdata(data_item)
                        data_item.template = o  # Add the template
                        try:
                            data_item.subtype = o['subtype']
                        except:
                            pass

                        options_str.append(tempname)
                        options_item[tempname] = data_item
                    except Exception as e:
                        logger.exception(e)
                        logger.debug(funcname + 'Could not find template type for {:s}'.format(str(o)))
                elif('template_name' in o.keys()):
                    tempname = o['template_name']
                    data_item = redvypr.config.dict_to_configDict(o,process_template=True)
                    data_item.template = o  # Add the template
                    options_str.append(tempname)
                    options_item[tempname] = data_item
        except Exception as e: # Do we still need this?
            logger.exception(e)
            logger.debug(funcname + 'Standard template option because of {:s}'.format(str(e)))
            options_standard = redvypr.config.template_types

            for opt_tmp in options_standard:
                tempname = opt_tmp['type']
                options_str.append(tempname)
                data_item = opt_tmp['default']
                data_item = redvypr.config.data_to_configdata(data_item)
                try:
                    data_item.subtype = opt_tmp['subtype']
                except:
                    pass

                #print('Tempname',tempname)
                options_item[tempname] = data_item

        # update the widgets
        self.__configwidget_input.__options__item__ = options_item
        for t in options_str:
            self.__configwidget_input.addItem(t)

        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Options for {:s}'.format(str(index))))
        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)

        # Buttons
        enabled = len(options_str) > 0 # If there is options
        self.__add_apply_btn__(self.__layoutwidget_int, item=item, dtype='list' , enabled=enabled)
        if (parentparent is not None):
            self.__add_remove_btn__(self.__layoutwidget_int, item=item, dtype='list')
            try:
                removable = parent.__data__.children_removable
            except Exception as e:
                removable = True

            self.__configwidget_remove.setEnabled(removable)

        self.configgui_layout.addWidget(self.__configwidget_int)

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
        # Check if options have been specified, otherwise use all standard template types
        try:  # First have a look if there are template options
            options_tmp = data.options
        except:
            options_tmp = None

        #print('Options tmp, dict',options_tmp)
        enabled = True
        if options_tmp is not None: # Fill combobox with standard template types
            [options_str,options_item] = self.get_options_from_config(options_tmp)
            self.__configwidget_input.__options__item__ = options_item
            for t in options_str:
                self.__configwidget_input.addItem(t)

            enabled = len(options_str) > 0  # If there is options
        else:
            enabled = False

        self.__layoutwidget_int.addRow(QtWidgets.QLabel('Type'), self.__configwidget_input)
        # Buttons
        self.__configwidget_key.setEnabled(enabled)
        self.__add_apply_btn__(self.__layoutwidget_int, item=item, dtype='dict', enabled = enabled)
        if(parentparent is not None):
            self.__add_remove_btn__(self.__layoutwidget_int, item=item, dtype='dict')
            try:
                removable = parent.__data__.children_removable
            except Exception as e:
                removable = True

            self.__configwidget_remove.setEnabled(removable)

        self.configgui_layout.addWidget(self.__configwidget_int)

    def __add_remove_btn__(self,layout,item,dtype):
        self.__configwidget_remove = QtWidgets.QPushButton('Remove')
        self.__configwidget_remove.clicked.connect(self.__config_widget_button)
        self.__configwidget_remove.item = item
        self.__configwidget_remove.__type__ = dtype
        self.__configwidget_remove.__removeitem__ = True
        try:
            layout.addRow(self.__configwidget_remove)
        except:
            layout.addWidget(self.__configwidget_remove)

    def __add_apply_btn__(self, layout, item, dtype, enabled = True):
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.__config_widget_button)
        self.__configwidget_apply.item = item
        self.__configwidget_apply.__type__ = dtype
        self.__configwidget_apply.__removeitem__ = False
        self.__configwidget_apply.setEnabled(enabled)
        try:
            layout.addRow(self.__configwidget_apply)
        except:
            layout.addWidget(self.__configwidget_apply)




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




class dictQTreeWidget(QtWidgets.QTreeWidget):
    """ Qtreewidget that display a Dict data structure
    """

    def __init__(self, data={}, dataname='data', show_datatype = True):
        funcname = __name__ + '.__init__():'
        super().__init__()
        if(type(data) == dict): # Convert to configDict to allow to store extra attributes
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

        # Show the datatpye column
        if show_datatype == False:
            self.header().hideSection(2)
        #self.itemExpanded.connect(self.resize_view)
        #self.itemCollapsed.connect(self.resize_view)

    def reload_data(self,data):
        self.data = data
        self.clear()
        self.create_qtree()
        self.expandAll()
        self.resizeColumnToContents(0)

    def seq_iter(self,obj):
        return redvypr.configdata.seq_iter(obj)

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
        if(sequence == None): # Check if we have an item that is something with data (not a list or dict)
            data_value = data  #
            typestr = data_value.__class__.__name__

            item       = QtWidgets.QTreeWidgetItem([str(index), str(data_value),typestr])
            #item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)  # editable
            item.__data__ = data
            item.__dataparent__   = parent.__data__ # can be used to reference the data (and change it)
            item.__dataindex__    = index
            item.__datatypestr__  = typestr
            item.__parent__       = parent
            # Add the item to the data
            #print('data',data)
            #print('data',type(data))

            index_child = self.item_is_child(parent, item)
            if  index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(item)
            else: # Update the data (even if it hasnt changed
                parent.child(index_child).setText(1,str(data_value))

        else:
            #print('loop')
            datatmp = data
            typestr = datatmp.__class__.__name__
            if(index is not None):
                indexstr = index
            newparent = QtWidgets.QTreeWidgetItem([str(index), '',typestr])
            item = newparent
            newparent.__data__         = datatmp
            newparent.__dataindex__    = index
            newparent.__datatypestr__  = typestr
            newparent.__parent__       = parent
            try:
                newparent.__dataparent__ = parent.__data__  # can be used to reference the data (and change it)
            except:
                newparent.__dataparent__ = None

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
        config dictionary from/with a qtreewidgetitem.

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
        #self.resizeColumnToContents(0)

#
#
#
#
#
class configQTreeWidget(QtWidgets.QTreeWidget):
    """ Qtreewidget that display a configDict data structure
    """

    def __init__(self, data={}, dataname='data', show_datatype = True):
        funcname = __name__ + '.__init__():'
        super().__init__()
        if(type(data) == dict): # Convert to configDict to allow to store extra attributes
            data = redvypr.config.dict_to_configDict(data)
        elif (type(data) == redvypr.config.configDict) or (type(data) == redvypr.config.configuration):
            #print(funcname,'Type config')
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

        # Show the datatpye column
        if show_datatype == False:
            self.header().hideSection(2)
        #self.itemExpanded.connect(self.resize_view)
        #self.itemCollapsed.connect(self.resize_view)

    def reload_data(self,data):
        self.data = data
        self.clear()
        self.create_qtree()
        self.expandAll()
        self.resizeColumnToContents(0)

    def seq_iter(self,obj):
        return redvypr.configdata.seq_iter(obj)

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
            #print('data',data)
            #print('data',type(data))
            data.__item__ = item

            index_child = self.item_is_child(parent, item)
            if  index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(item)
            else: # Update the data (even if it hasnt changed
                parent.child(index_child).setText(1,str(data_value))

        else:
            #print('loop')
            datatmp = data

            try:
                typestr = datatmp.template['type']
            except:
                typestr = datatmp.__class__.__name__
            #typestr = datatmp.__class__.__name__
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
        #self.resizeColumnToContents(0)





class pydanticQTreeWidget(QtWidgets.QTreeWidget):
    """ Qtreewidget that display a pydantic object
    """

    def __init__(self, data=None, dataname = 'data', show_datatype = True):
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
        self.show_datatype = show_datatype

        #self.itemExpanded.connect(self.resize_view)
        #self.itemCollapsed.connect(self.resize_view)

    def seq_iter(self, obj):
        """
        To treat dictsionaries and lists equally this functions returns either the keys of dictionararies or the indices of a list.
        This allows a
        index = seq_iter(data)
        for index in data:
            data[index]

        with index being a key or an int.

        Args:
            obj:

        Returns:
            list of indicies

        """
        obj_test = obj

        if isinstance(obj_test, dict):
            return obj
        elif isinstance(obj_test, list):
            return range(0, len(obj))
        else:
            return None

    def reload_data(self,data):
        self.data = data
        self.clear()
        self.create_qtree()
        self.expandAll()
        self.resizeColumnToContents(0)

    def create_item(self, index, data, parent):
        """
        Creates recursively qtreewidgetitems. If the item to be created is a sequence (dict or list), it calls itself as often as it finds a real value
        Args:
            index:
            data:
            parent:

        Returns:

        """
        print('Hallo',type(data))
        if isinstance(data, dict):
            print('dict')
            flag_iterate = True
        elif isinstance(data, list):
            print('list')
            flag_iterate = True
        #elif isinstance(data, pydantic.BaseModel):
        elif data.__class__.__base__ == pydantic.BaseModel:
            print('basemodel')
            flag_iterate = True
        else:
            print('item')
            flag_iterate = False

        if(flag_iterate == False): # Check if we have an item that is something with data (not a pydantic module, list or dict)
            data_value = data  #
            typestr = data_value.__class__.__name__
            item       = QtWidgets.QTreeWidgetItem([str(index), str(data_value),typestr])
            #item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)  # editable
            item.__data__ = data
            item.__dataparent__   = parent.__data__ # can be used to reference the data (and change it)
            item.__dataindex__    = index
            item.__datatypestr__  = typestr
            item.__parent__       = parent
            # Add the item to the data
            #print('data',data)
            #print('data',type(data))
            #data.__item__ = item

            index_child = self.item_is_child(parent, item)
            if  index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(item)
            else: # Update the data (even if it hasnt changed
                parent.child(index_child).setText(1,str(data_value))

        else:
            #print('loop')
            datatmp = data

            typestr = datatmp.__class__.__name__
            #typestr = datatmp.__class__.__name__
            flag_modifiable = True
            if(index is not None):
                indexstr = index

            print('gf',index)
            print('gf type', type(index))
            print('Hallo',str(index))
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

            index_child = self.item_is_child(parent, newparent)
            if index_child == None:  # Check if the item is already existing, if no add it
                parent.addChild(newparent)
            else:
                newparent = parent.child(index_child)


            for numi, newindex in enumerate(data):
                if isinstance(data, dict):
                    print('Dict',newindex)
                    newdata = datatmp[newindex]
                elif isinstance(data, list):
                    print('List', newindex)
                    newdata = datatmp[numi]
                    newindex = numi
                elif data.__class__.__base__ == pydantic.BaseModel:
                    print('numi',numi)
                    print('newindex', newindex)
                    newdata = newindex[1]
                    newindex = newindex[0]
                    print('basemodel newdata',newdata)
                    print('newindex',newindex)
                    print('newparent',newparent)

                self.create_item(newindex , newdata, newparent)

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
        print('data',self.data)
        if True:
            self.create_item(self.dataname,self.data,self.root)

        self.dataitem = self.root.child(0)
        self.resizeColumnToContents(0)
        self.blockSignals(False)
        self.expandAll()
        self.resizeColumnToContents(0)
        # Show the datatpye column
        if self.show_datatype == False:
            self.header().hideSection(2)



    def resize_view(self):
        pass
        #self.resizeColumnToContents(0)

