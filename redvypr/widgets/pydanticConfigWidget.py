import copy
import time
import logging
import sys
import yaml
from PyQt5 import QtWidgets, QtCore, QtGui
import pydantic
from pydantic.color import Color as pydColor
import typing
from redvypr.device import RedvyprDevice
from redvypr.widgets.redvypr_addressWidget import RedvyprAddressWidgetSimple, RedvyprAddressWidget
import redvypr.files as files


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('pydanticConfigWidget')
logger.setLevel(logging.DEBUG)


class pydanticDeviceConfigWidget(QtWidgets.QWidget):
    """
    Config widget for a pydantic configuration
    """
    def __init__(self, device=None, exclude=[], config_location='right', show_datatype=False):
        funcname = __name__ + '.__init__():'
        super().__init__()
        logger.debug(funcname)
        self.setWindowTitle('Config of {}'.format(device.name))
        self.device = device
        try:
            redvypr = self.device.redvypr
        except:
            redvypr = None
        self.exclude = exclude
        self.layout = QtWidgets.QGridLayout(self)
        self.label = QtWidgets.QLabel('Configuration of\n{:s}'.format(self.device.name))
        self.layout.addWidget(self.label)
        dataname = self.device.name + '.config'
        config = self.device.custom_config
        if config is None:
            logger.warning('No config existing')
            self.configWidget = QtWidgets.QLabel('No config existing!')
        else:
            print('Config to edit',self.device.custom_config)
            print('tpye',type(self.device.custom_config))
            self.configWidget = pydanticConfigWidget(self.device.custom_config, configname=dataname, exclude=self.exclude, config_location=config_location, show_datatype=show_datatype, redvypr=redvypr)
            self.configWidget.config_changed_flag.connect(self.config_changed)
            self.configWidget.config_editing_done.connect(self.closeClicked)
            #self.configWidget = pydanticQTreeWidget(self.device.custom_config, dataname=dataname, exclude=self.exclude)
        self.layout.addWidget(self.configWidget)

    def config_changed(self):
        funcname = __name__ + '.config_changed():'
        logger.debug(funcname)
        self.device.config_changed()

    def closeClicked(self):
        funcname = __name__ + '.closeClicked():'
        logger.debug(funcname)
        self.close()

#
#
# pydanticConfigWidget
#
#
class pydanticConfigWidget(QtWidgets.QWidget):
    #config_changed = QtCore.pyqtSignal(dict)  # Signal notifying that the configuration has changed
    config_changed_flag = QtCore.pyqtSignal()  # Signal notifying that the configuration has changed
    config_editing_done = QtCore.pyqtSignal()
    def __init__(self, config=None, editable=True, configname=None, exclude=[], config_location='right', show_datatype=False, redvypr=None, show_editable_only=True):
        funcname = __name__ + '.__init__():'
        super().__init__()
        self.redvypr = redvypr
        self.exclude = exclude
        self.layout = QtWidgets.QGridLayout(self)
        self.config_location = config_location
        #self.label = QtWidgets.QLabel('Configuration of\n{:s}'.format(self.device.name))
        #self.layout.addWidget(self.label)
        if configname is None:
            configname = 'pydanticConfig'

        self.config = config
        self.configWidget = pydanticQTreeWidget(self.config, dataname=configname, exclude=self.exclude, show_datatype=show_datatype, show_editable_only=show_editable_only)
        if editable:
            self.configWidget.itemDoubleClicked.connect(self.__openConfigGui__)
            self.configGui = QtWidgets.QWidget()  # Widget where the user can modify the content
            self.configGui_layout = QtWidgets.QVBoxLayout(self.configGui)
            self.edit_label = QtWidgets.QLabel('Edit data')
            self.configGui_layout.addWidget(self.edit_label)
            self.stretchy_spacer_thing = QtWidgets.QSpacerItem(10,10,QtWidgets.QSizePolicy.Minimum,QtWidgets.QSizePolicy.Expanding)
            self.configGui_layout.addItem(self.stretchy_spacer_thing)
            # Add a blank widget for editing
            self.__configwidget = QtWidgets.QWidget()
            self.configGui_layout.addWidget(self.__configwidget)
            if self.config_location == 'bottom':
                self.layout.addWidget(self.configGui, 1, 0)
            else:
                self.layout.addWidget(self.configGui, 0, 1)


        self.closeButton = QtWidgets.QPushButton('Close')
        self.closeButton.clicked.connect(self.closeClicked)

        self.layout.addWidget(self.configWidget, 0, 0)
        self.layout.addWidget(self.closeButton, 2, 0, 1, 2)

    def closeClicked(self):
        funcname = __name__ + '.close():'
        logger.debug(funcname)
        self.config_editing_done.emit()
        self.close()

    def __comboUpdateItem(self, index):
        """
        I called when the combo that allows the user to choose a datatype is changed
        :param index:
        :return:
        """
        funcname = __name__ + '.__comboUpdateItem():'
        logger.debug(funcname)
        user_role_config = 11
        role = QtCore.Qt.UserRole + user_role_config
        item = self.__configCombo.itemData(index, role)
        # Get the datatypestr and call the gui create function again
        datatypestr = self.__configCombo.currentText()
        logger.debug(funcname + 'Datatypestr {}'.format(datatypestr))
        item.__datatypestr__ = datatypestr

        # Get the type_hint object and create standard type
        #dobject = typing.get_args(item.__type_hints__)[index]  # This is not working with unions, using interprete type_hints instead
        type_dict = self.interprete_type_hints(item.__type_hints__)
        dobject = type_dict['datatype_objects'][datatypestr]
        print('type dict',type_dict)
        print('Item', item)
        print('Index',index)
        print('Item type hints', item.__type_hints__)
        print('Item datatypestr', datatypestr)
        print('Dobject',dobject)
        logger.debug(funcname + ' object : {}'.format(dobject))
        try:
            flag_add = item.__flag_add__
        except:
            flag_add = False

        if flag_add:
            logger.debug(funcname + ' Add flag')
        else:
            logger.debug(funcname + ' Modifying item')
            if 'literal' in dobject.__name__.lower():
                logger.debug(funcname + 'Literal type hint')
                literal_args = typing.get_args(dobject)
                # Get the first element
                data = literal_args[0]
                item.__datatypestr__ = 'literal'
                item.__literal_options__ = literal_args
            elif 'color' in dobject.__name__.lower():
                logger.debug(funcname + 'Color type hint')
                item.__data__ = dobject('red')
            else:
                item.__data__ = dobject()

            logger.debug(funcname + 'Index: {} datatpystr: {} data: {}'.format(index,datatypestr, item.__data__))


    def __comboTypeChanged(self,index):
        """
        Called when the combobox of the datatype is changed
        :param index:
        :return:
        """
        funcname = __name__ + '__comboTypeChanged():'
        logger.debug(funcname)
        #print('Index', index)
        self.__comboUpdateItem(index)
        user_role_config = 11
        role = QtCore.Qt.UserRole + user_role_config
        item = self.__configCombo.itemData(index, role)


        self.__configwidget.setParent(None)
        #self.configGui_layout.addWidget(self.__configwidget)
        self.configGui_layout.removeItem(self.stretchy_spacer_thing)

        try:
            flag_add = item.__flag_add__
        except:
            flag_add = False

        if flag_add:
            logger.debug(funcname + ' Add flag')
        else:
            self.CreateConfigWidgetForItem(item)
        #print('Item',item)
        #print('Clear gui')
        #self.__clearConfigGui__()
        #print('Populate gui')
        self.__populateConfigGui__()
        #self.__openConfigGui__(item)

        #print('Open config gui with item',item)
        # Changed the datatype, now recreate the widgets
        #self.configGui_layout.removeItem(self.stretchy_spacer_thing)
        #try:
        #    self.__configwidget.close()
        #except:
        #    pass


        #self.configGui_layout.addWidget(self.__configwidget)
        ## Add a stretch
        #self.configGui_layout.addItem(self.stretchy_spacer_thing)

    def interprete_type_hints(self, type_hints):
        funcname = __name__ + '.interprete_type_hints():'
        type_dict = None
        #print('Type hints', type_hints)
        if type_hints is not None:
            #print('Name', type_hints.__name__)
            type_dict = {'type_args':[],'datatype_objects':{}}
            # Get the different type hints
            type_args = typing.get_args(type_hints)
            #print('Type args', len(type_args), type(type_hints))
            index_datatype = None
            # Create a combo to allow the user to choose between the different
            # data type choices
            # checks if type hints are annotations or types/unions
            # Annotations are used for extra information, type/unions for
            # And are ignored
            #print('Classname', type_hints.__class__.__name__)
            isliteral = 'Literal' in type_hints.__class__.__name__
            isannotated = 'Annotated' in type_hints.__class__.__name__
            type_dict['isannotated'] = isannotated
            type_dict['isliteral'] = isliteral
            type_dict['type_root'] = None
            if 'union' in type_hints.__name__.lower():
                logger.debug(funcname + ' Found Union of datatypes in type hints')
                type_dict['type_root'] = 'union'
            logger.debug(funcname + 'Isannotated {}'.format(isannotated))
            if isliteral:
                type_dict['literal_options'] = type_args
            elif len(type_args) > 0 and not (isannotated):
                # Remove str from args, as this is a mandatary entry for dict, but not needed
                if 'dict' in type_hints.__name__.lower() and (type_args[0].__name__.lower() == 'str' or type_args[0].__name__.lower() == 'int'):
                    logger.debug(funcname + 'Removing str/int entry for dict')
                    type_args_new = list(type_args)
                    type_args_new.pop(0)
                    type_args = tuple(type_args_new)

                # loop over all type args, if there is a union within (i.e. a list with some datatypes), loop over the union
                # for example typing.List[typing.Union[float, str]]
                for arg in type_args:
                    logger.debug(funcname + 'arg {} arg_name {}'.format(arg,arg.__name__))
                    if 'union' in arg.__name__.lower():
                        logger.debug(funcname + ' Found Union of datatypes')
                        type_dict['type_root'] = 'union'
                        type_args_union = typing.get_args(arg)
                        for arg_union in type_args_union:
                            argstr = arg_union.__name__
                            logger.debug(funcname + 'Adding datatype: {}'.format(argstr))
                            type_dict['type_args'].append(argstr)
                            # Add the object as well
                            type_dict['datatype_objects'][argstr] = arg_union
                    else:
                        argstr = arg.__name__
                        type_dict['type_args'].append(argstr)
                        # Add the object as well
                        type_dict['datatype_objects'][argstr] = arg

        return type_dict

    def __populateConfigGui__(self):
        print('Additional widgets',self.additional_config_gui_widgets)
        for w in self.additional_config_gui_widgets:
            try:
                print('Adding widget',w)
                self.configGui_layout.addWidget(w)
            except:
                logger.debug('Could not add widget',exc_info=True)

        self.configGui_layout.addWidget(self.__configwidget)
        #self.configGui_layout.addItem(self.stretchy_spacer_thing)

    def __clearConfigGui__(self):
        self.configGui_layout.removeItem(self.stretchy_spacer_thing)
        for i in reversed(range(self.configGui_layout.count())):
            self.configGui_layout.itemAt(i).widget().setParent(None)
            #self.configGui_layout.itemAt(i).widget().hide()


    def __openConfigGui__(self, item):
        """
        Function is called when an item is double clicked. It creates the
        config widget.
        :param item:
        :return:
        """
        funcname = __name__ + '.__openConfigGui__():'
        logger.debug(funcname + ' for item {}'.format(item.text(0)))
        has_combo = False
        self.additional_config_gui_widgets = []
        self.__clearConfigGui__()
        editable = item.__editable__
        #print('editable',editable)
        flag_add = False
        if editable==False:
            #print('Not editable')
            pass
        else:
            #print('some information')
            #print(item.__data__)
            #print(item.__dataparent__)
            #print(item.__dataindex__)
            #print(item.__datatypestr__)
            #print(item.__parent__)
            #print('Done')
            try:
                type_hints = item.__type_hints__
            except:
                type_hints = None

            ## Add type hints to pydantic basemodel with extra=allow
            #if pydantic.BaseModel in item.__data__.__class__.__mro__:
            #    if item.__flag_add_entry__:
            #        type_hints = typing.Union[bool, int, float, str]

            type_dict = self.interprete_type_hints(type_hints)
            print(funcname + ' Type hints', type_hints)
            print(funcname + ' Type dict', type_dict)
            if type_dict is not None:
                index_datatype = None
                # Create a combo to allow the user to choose between the different
                # data type choices
                # checks if type hints are annotations or types/unions
                # Annotations are used for extra information, type/unions for
                if type_dict['isliteral']:
                    #print('Literal options',type_dict['literal_options'])
                    item.__datatypestr__ = 'literal'
                    item.__datatype__ = typing.Literal
                    item.__literal_options = type_dict['literal_options']
                elif type_dict['isannotated']:
                    pass
                # This is a union
                elif (len(type_dict['type_args']))>0 and (type_hints.__name__.lower() == 'union'):
                    print('Type args')
                    self.__configCombo = QtWidgets.QComboBox()
                    has_combo = True
                    logger.debug(funcname + 'Filling combo box')
                    for iarg,argstr in enumerate(type_dict['type_args']):
                        print('Argstr ...',argstr)
                        # If annotated data is available look search for known datatypes
                        if argstr == 'Annotated':
                            #print('Annotated argument')
                            annotations = typing.get_args(typing.get_args(item.__type_hints__)[iarg])
                            #print('Annotations ...', annotations)
                            for annotation in annotations:
                                if annotation == 'RedvyprAddressStr':
                                    argstr = annotation
                                    break
                        self.__configCombo.addItem(argstr)
                        index = self.__configCombo.count() - 1
                        datatypestr_tmp = item.__data__.__class__.__name__
                        if argstr == datatypestr_tmp:
                            index_datatype = index
                        user_role_config = 11
                        role = QtCore.Qt.UserRole + user_role_config
                        self.__configCombo.setItemData(index, item, role)
                        #print('index',index,'item',item,'argstr',argstr, datatypestr_tmp, item.__datatypestr__)

                    data = item.__data__
                    print('data type',type(data))
                    # Check if the combo is meant to choose between different types
                    print('Type dict',type_dict)
                    if type_dict['type_root'] == 'union':
                        logger.debug(funcname + 'Union')
                        # Add the config combo to the layout
                        self.additional_config_gui_widgets.append(self.__configCombo)
                    elif isinstance(data, dict):
                        print('Add options for dict')
                        flag_add = True
                    elif isinstance(data, list):
                        logger.debug(funcname + 'Create options for adding items to list')
                        self.configGui_layout.addWidget(
                            QtWidgets.QLabel('Add entry of type to list {}'.format(item.__dataindex__)))

                        addWidget_tmp = QtWidgets.QWidget()
                        addWidget_tmp_layout = QtWidgets.QHBoxLayout(addWidget_tmp)
                        addWidget_tmp_layout.addWidget(QtWidgets.QLabel('Append type to list'))
                        addWidget_tmp_layout.addWidget(self.__configCombo)
                        self.additional_config_gui_widgets.append(addWidget_tmp)
                        flag_add = True
                    elif pydantic.BaseModel in data.__class__.__mro__:
                        #print('Add options for basemodel')
                        self.configGui_layout.addWidget(
                            QtWidgets.QLabel('Add entry of type to pydantic BaseModel child {}'.format(item.__dataindex__)))

                        self.__configKeyInput = QtWidgets.QLineEdit('newattribute')
                        # Widget for key/datatype to add
                        addWidget_tmp = QtWidgets.QWidget()
                        addWidget_tmp_layout = QtWidgets.QHBoxLayout(addWidget_tmp)
                        addWidget_tmp_layout.addWidget(self.__configKeyInput)
                        addWidget_tmp_layout.addWidget(self.__configCombo)
                        self.additional_config_gui_widgets.append(addWidget_tmp)
                        flag_add = True
                    else: # Ordinary item, adding nothing special
                        logger.debug(funcname + 'Ordinary item')
                        ## Add the config combo to the layout
                        #self.additional_config_gui_widgets.append(self.__configCombo)

                    item_data = item.__data__

                    if index_datatype is not None:
                        self.__configCombo.setCurrentIndex(index_datatype)
                        item.__datatypestr__ = datatypestr_tmp
                        item.__datatype__ = item.__data__.__class__
                    else:
                        self.__configCombo.setCurrentIndex(0)
                        # self.__comboUpdateItem(0)

                    # Get the index for the combo
                    self.__configCombo.currentIndexChanged.connect(self.__comboTypeChanged)

            #self.__configWidget = QtWidgets.QLabel('Hallo')
            #print('Configwidget 1',self.__configWidget)
            self.CreateConfigWidgetForItem(item)
            print('Flag add',flag_add)
            if flag_add:
                item.__flag_add__ = True
            else:
                item.__flag_add__ = False
            #print('Configwidget 2', self.__configwidget)
            #config_gui_widgets.append(self.__configwidget)
            #self.configGui_layout.addWidget(self.__configwidget)
            # Add a remove button if the item can be removed
            parentdata = item.__dataparent__
            try:
                removable = item.__removable__
            except:
                removable = False
            if removable:
                self.__remove_button = QtWidgets.QPushButton('Remove')
                self.__remove_button.item = item
                self.__remove_button.clicked.connect(self.__removeClicked)
                self.configGui_layout.addWidget(QtWidgets.QLabel('Remove entry'))
                self.configGui_layout.addWidget(self.__remove_button)
            # Add a stretch
            #self.configGui_layout.addItem(self.stretchy_spacer_thing)
            #self.additional_config_gui_widgets.append(self.stretchy_spacer_thing)
            self.__populateConfigGui__()
            if has_combo:
                self.__configCombo.setCurrentIndex(0)
                #self.__comboTypeChanged(0)

    def __removeClicked(self):
        funcname = __name__ + '.__removeClicked():'
        logger.debug(funcname)
        item = self.sender().item
        parentdata = item.__dataparent__
        if isinstance(parentdata, dict):
            #print('Removing from dict')
            parentdata.pop(item.__dataindex__,None)
        elif isinstance(parentdata, list):
            #print('Removing from list')
            parentdata.pop(item.__dataindex__)
        elif pydantic.BaseModel in parentdata.__class__.__mro__:
            #print('Removing from basemodel')
            delattr(parentdata, item.__dataindex__)

        self.__clearConfigGui__()
        # Reload and redraw all data
        self.configWidget.reload_data()
        self.config_changed_flag.emit()
        #print(item.__data__)
        #print(item.__dataparent__)
        #print(item.__dataindex__)
        #print(item.__datatypestr__)
        #print(item.__parent__)

    def CreateConfigWidgetForItem(self, item):
        """
        creates self.__configwidget for item type
        :param item:
        :return:
        """
        funcname = __name__ + '.CreateConfigWidgetForItem():'
        try:
            datatypestr = item.__datatypestr__
        except:
            datatypestr = 'NA'

        logger.debug(funcname + 'Datatypestr {}'.format(datatypestr))
        #print('MRO',item.__data__.__class__.__mro__)

        try:
            self.__configwidget.close()
        except:
            pass

        #if pydantic.BaseModel in item.__data__.__class__.__mro__:
        #    print('Existing Basemodel ...')
        #    self.createConfigWidgetBaseModel(item)
        if (item.__datatypestr__ == 'int') or (item.__datatypestr__ == 'float'):
            self.createConfigWidgetNumber(item, dtype=item.__datatypestr__)
        elif (item.__datatypestr__.lower() == 'color'):
            logger.debug(funcname + 'Color datatype')
            self.createConfigWidgetColor(item)
        elif (item.__datatypestr__.lower() == 'literal'):
            logger.debug('Literal datatype')
            self.createConfigWidgetLiteral(item)
        elif (item.__datatypestr__ == 'str'):
            logger.debug('Str')
            self.createConfigWidgetStr(item)
        elif (item.__datatypestr__ == 'datetime'):
            self.createConfigWidgetDateTime(item)
        elif (item.__datatypestr__ == 'bool'):
            self.createConfigWidgetBool(item)
        elif (item.__datatypestr__ == 'RedvyprAddressStr'):
            logger.debug('RedvyprAddressStr')
            self.createConfigWidgetRedvyprAddressStr(item)
        elif (item.__datatypestr__ == 'list'):
            self.createConfigWidgetList(item)
        elif (item.__datatypestr__ == 'dict'):
            logger.debug(funcname + 'Dictionary')
            self.createConfigWidgetDict(item)
        elif pydantic.BaseModel in item.__data__.__class__.__mro__:
            logger.debug(funcname + 'BaseModel')
            self.createConfigWidgetBaseModelNew(item)
        else:
            try: # Check if there is a valid type_hint, otherwise do nothing
                type_hints = item.__type_hints__
                type_dict = self.interprete_type_hints(type_hints)
                dobject = type_dict['datatype_objects'][item.__datatypestr__]
                self.createConfigWidgetBaseModelNew(item)
            except:
                logger.debug('Could not create a widget:',exc_info=True)

    def createConfigWidgetColor(self, item):
        funcname = __name__ + '.createConfigWidgetColor():'
        logger.debug(funcname)
        index = item.__dataindex__
        parent = item.__parent__
        type_hints = item.__type_hints__

        self.__configwidget = QtWidgets.QWidget()
        self.__layoutwidget = QtWidgets.QVBoxLayout(self.__configwidget)
        self.__layoutwidget.addWidget(QtWidgets.QLabel('Choose color for {:s}'.format(str(index))))
        self.__configwidget_input = QtWidgets.QColorDialog()
        self.__layoutwidget.addWidget(self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.applyGuiInput)
        self.__configwidget_apply.__configType = 'configColor'
        self.__configwidget_apply.item = item
        self.__layoutwidget.addWidget(self.__configwidget_apply)
        logger.debug('Done')

    def createConfigWidgetLiteral(self, item):
        logger.debug('createConfigWidgetLiteral')
        index = item.__dataindex__
        parent = item.__parent__
        type_hints = item.__type_hints__
        #
        if type_hints.__name__ == 'Literal':
            literal_options = typing.get_args(type_hints)
        else:
            literal_options = item.__literal_options__
        self.__configwidget = QtWidgets.QWidget()
        self.__layoutwidget = QtWidgets.QVBoxLayout(self.__configwidget)
        self.__layoutwidget.addWidget(QtWidgets.QLabel('Choose option for {:s}'.format(str(index))))
        self.__configwidget_input = QtWidgets.QComboBox()
        for o in literal_options:
            self.__configwidget_input.addItem(str(o))

        self.__layoutwidget.addWidget(self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.applyGuiInput)
        self.__configwidget_apply.__configType = 'configLiteral'
        self.__configwidget_apply.item = item
        self.__layoutwidget.addWidget(self.__configwidget_apply)



    def createConfigWidgetBaseModel(self, item):
        logger.debug('createConfigWidgetBaseModel')
        self.__configwidget = QtWidgets.QWidget()

    def createConfigWidgetList(self, item):
        logger.debug('createConfigWidgetList')
        self.createConfigWidgetDict(item)
        self.__layoutwidget.removeWidget(self.__keylabel)
        self.__layoutwidget.removeWidget(self.__configwidget_input)
        self.__keylabel.close()
        self.__configwidget_input.close()
        self.__configwidget_apply.__configType = 'configList'

    def createConfigWidgetBaseModelNew(self, item):
        logger.debug('createConfigWidgetBaseModelNew')
        data = item.__data__
        try:
            model_config = data.model_config['extra']
        except:
            model_config = 'omitted'

        if 'allow' in model_config.lower():
            editable = True
        else:
            editable = False

        if editable:
            self.createConfigWidgetDict(item)
            self.__configwidget_apply.__configType = 'configBaseModel'
            self.__configwidget_input.setText('newattribute')
        else:
            self.__configwidget = QtWidgets.QWidget()
            self.__layoutwidget = QtWidgets.QVBoxLayout(self.__configwidget)
            self.__layoutwidget.addWidget(QtWidgets.QLabel('Cannot add attribute'))

    def createConfigWidgetDict(self, item):
        funcname = __name__ + '.createConfigWidgetDict():'
        logger.debug('createConfigWidgetDict')
        index = item.__dataindex__
        parent = item.__parent__
        data = item.__data__
        type_hints_standard = typing.Union[bool, int, float, str]
        try:
            type_hints = item.__type_hints__
            if type_hints is None:
                logger.debug(funcname + 'Create standard type hints')
                type_hints = type_hints_standard
                item.__type_hints__ = type_hints_standard
        except:
            type_hints = type_hints_standard

        print('Type hints', type_hints)
        type_dict = self.interprete_type_hints(type_hints)
        print('Type dict', type_dict)
        addCombo = QtWidgets.QComboBox()
        has_combo = True
        logger.debug(funcname + 'Filling combo box')
        for iarg, argstr in enumerate(type_dict['type_args']):
            print('Argstr ...', argstr)
            # If annotated data is available look search for known datatypes
            if argstr == 'Annotated':
                # print('Annotated argument')
                annotations = typing.get_args(typing.get_args(item.__type_hints__)[iarg])
                # print('Annotations ...', annotations)
                for annotation in annotations:
                    if annotation == 'RedvyprAddressStr':
                        argstr = annotation
                        break
            addCombo.addItem(argstr)
            # Save also the object
            user_role_config = 11
            role = QtCore.Qt.UserRole + user_role_config
            dobject = type_dict['datatype_objects'][argstr]
            addCombo.setItemData(iarg, dobject, role)

        self.__configwidget_combo = addCombo
        self.__configwidget = QtWidgets.QWidget()
        self.__layoutwidget = QtWidgets.QFormLayout(self.__configwidget)
        keylabel = QtWidgets.QLabel('Datakey')
        self.__keylabel = keylabel
        self.__configwidget_input = QtWidgets.QLineEdit('newkey')
        #self.__configwidget_input.setText(str(data))
        self.__layoutwidget.addRow(QtWidgets.QLabel('Add a new entry for {:s}'.format(str(index))))
        self.__layoutwidget.addRow(keylabel, self.__configwidget_input)
        self.__layoutwidget.addRow(QtWidgets.QLabel('Datatype'), addCombo)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Add')
        self.__configwidget_apply.clicked.connect(self.applyGuiInput)
        self.__configwidget_apply.__configType = 'configDict'
        self.__configwidget_apply.item = item
        self.__layoutwidget.addRow(self.__configwidget_apply)

    def createConfigWidgetStr(self, item):
        index = item.__dataindex__
        parent = item.__parent__
        data = item.__data__
        parentparent = parent.__parent__
        self.__configwidget = QtWidgets.QWidget()
        self.__layoutwidget = QtWidgets.QFormLayout(self.__configwidget)
        self.__configwidget_input = QtWidgets.QLineEdit()
        self.__configwidget_input.setText(str(data))
        self.__layoutwidget.addRow(QtWidgets.QLabel('Enter string for {:s}'.format(str(index))))
        self.__layoutwidget.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.applyGuiInput)
        self.__configwidget_apply.__configType = 'configStr'
        self.__configwidget_apply.item = item
        self.__configwidget_cancel = QtWidgets.QPushButton('Cancel')
        self.__layoutwidget.addRow(self.__configwidget_apply)
        self.__layoutwidget.addRow(self.__configwidget_cancel)

    def createConfigWidgetRedvyprAddressStr(self, item):
        funcname = __name__ + 'createConfigWidgetRedvyprAddressStr():'
        logger.debug(funcname)
        try:
            index = item.__dataindex__
            parent = item.__parent__
            data = item.__data__
            parentparent = parent.__parent__
            self.__configwidget = QtWidgets.QWidget()
            self.__layoutwidget = QtWidgets.QFormLayout(self.__configwidget)
            if self.redvypr is not None:
                self.__configwidget_input = RedvyprAddressWidget(data,redvypr=self.redvypr)
            else:
                self.__configwidget_input = RedvyprAddressWidgetSimple(data)
            self.__configwidget_input.__configType = 'configRedvyprAddress'
            self.__configwidget_input.item = item
            self.__configwidget_input.address_finished.connect(self.applyGuiInput)
            self.__layoutwidget.addWidget(self.__configwidget_input)
        except:
            logger.info('Error in RedvyprAddress',exc_info=True)


    def createConfigWidgetDateTime(self, item, dateformat='yyyy-MM-dd HH:MM:ss'):

        index = item.__dataindex__
        parent = item.__parent__
        data = item.__data__
        parentparent = parent.__parent__
        self.__configwidget = QtWidgets.QWidget()
        self.__layoutwidget = QtWidgets.QFormLayout(self.__configwidget)
        self.__configwidget_input = QtWidgets.QDateTimeEdit(data)
        self.__configwidget_input.setDisplayFormat(dateformat)
        self.__layoutwidget.addRow(QtWidgets.QLabel('Enter date/time for {:s}'.format(str(index))))
        self.__layoutwidget.addRow(QtWidgets.QLabel('Date/Time'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.applyGuiInput)
        self.__configwidget_apply.__configType = 'configDateTime'
        self.__configwidget_apply.item = item
        self.__configwidget_cancel = QtWidgets.QPushButton('Cancel')
        self.__layoutwidget.addRow(self.__configwidget_apply)
        self.__layoutwidget.addRow(self.__configwidget_cancel)
        # if (parentparent is not None):  # Remove button
        #    self.__add_remove_btn__(self.__layoutwidget_int, item=item, dtype='str')
        #    try:
        #        removable = parent.__data__.children_removable
        #    except Exception as e:
        #        removable = True

        #    self.__configwidget_remove.setEnabled(removable)

    def createConfigWidgetBool(self, item):

        index = item.__dataindex__
        parent = item.__parent__
        data = item.__data__
        parentparent = parent.__parent__
        self.__configwidget = QtWidgets.QWidget()
        self.__layoutwidget = QtWidgets.QFormLayout(self.__configwidget)
        self.__configwidget_input = QtWidgets.QComboBox()
        self.__configwidget_input.addItem('True')
        self.__configwidget_input.addItem('False')
        self.__layoutwidget.addRow(QtWidgets.QLabel('Enter bool for {:s}'.format(str(index))))
        self.__layoutwidget.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)
        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.applyGuiInput)
        self.__configwidget_apply.__configType = 'configBool'
        self.__configwidget_apply.item = item
        self.__configwidget_cancel = QtWidgets.QPushButton('Cancel')
        self.__layoutwidget.addRow(self.__configwidget_apply)
        self.__layoutwidget.addRow(self.__configwidget_cancel)

    def createConfigWidgetNumber(self, item, dtype='int'):
        """
        Creates a widgets to modify an integer value

        Returns:

        """
        funcname = __name__ + '.createConfigWidgetNumber():'
        logger.debug(funcname)
        index = item.__dataindex__
        parent = item.__parent__
        data = item.__data__
        parentparent = parent.__parent__
        self.__configwidget = QtWidgets.QWidget()
        self.__layoutwidget = QtWidgets.QFormLayout(self.__configwidget)
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

        self.__layoutwidget.addRow(QtWidgets.QLabel('Enter value for {:s}'.format(str(index))))
        self.__layoutwidget.addRow(QtWidgets.QLabel('Value'), self.__configwidget_input)

        # Buttons
        self.__configwidget_apply = QtWidgets.QPushButton('Apply')
        self.__configwidget_apply.clicked.connect(self.applyGuiInput)
        self.__configwidget_apply.__configType = 'configNumber'
        self.__configwidget_apply.item = item
        self.__configwidget_cancel = QtWidgets.QPushButton('Cancel')
        self.__layoutwidget.addRow(self.__configwidget_apply)
        self.__layoutwidget.addRow(self.__configwidget_cancel)


    def applyGuiInput(self):
        funcname = __name__ + '.applyGuiInput()'
        logger.debug(funcname)
        item = self.sender().item
        print('Some info')
        print('item_data',item.__data__)
        print('item_parent',item.__dataparent__)
        print('item_dataindex',item.__dataindex__)
        item_data = item.__data__
        # The flag to add a new item
        flag_add = item.__flag_add__

        #print('datatypestr',item.__datatypestr__)
        #print(item.__parent__)
        #print('Some info done')
        data_set = False
        if self.sender().__configType == 'configNumber':
            #print(funcname + ' ' + self.sender().__configType)
            #print('Setting data')
            #print('Reloading data')
            #print('Item',item)
            self.__configwidget_input
            data = self.__configwidget_input.value()  # Works for int/float spinboxes
            data_set = True

        elif self.sender().__configType == 'configList':
            logger.debug(funcname + 'Processing configList')
            data = item.__data__
            datakey = self.__configwidget_input.text()  # ComboBox
            index = self.__configwidget_combo.currentIndex()
            print('Dict newkey', datakey, 'Index', index)
            user_role_config = 11
            role = QtCore.Qt.UserRole + user_role_config
            dobject = self.__configwidget_combo.itemData(index, role)
            print('Dobject', dobject)
            dobject_add = dobject()
            data.append(dobject_add)
            # Reload and redraw all data
            self.configWidget.reload_data()
            self.config_changed_flag.emit()
            return

        elif self.sender().__configType == 'configBaseModel':
            logger.debug(funcname + 'Processing configBaseModel')
            data = item.__data__
            datakey = self.__configwidget_input.text()  # ComboBox
            index = self.__configwidget_combo.currentIndex()
            print('Dict newkey', datakey,'Index',index)
            user_role_config = 11
            role = QtCore.Qt.UserRole + user_role_config
            dobject = self.__configwidget_combo.itemData(index, role)
            print('Dobject',dobject)
            dobject_add = dobject()
            #data[datakey] = dobject_add
            setattr(data, datakey, dobject_add)
            # Reload and redraw all data
            self.configWidget.reload_data()
            self.config_changed_flag.emit()
            return

        elif self.sender().__configType == 'configDict':
            logger.debug(funcname + 'Processing dictionary')
            data = item.__data__
            datakey = self.__configwidget_input.text()  # ComboBox
            index = self.__configwidget_combo.currentIndex()
            print('Dict newkey', datakey,'Index',index)
            user_role_config = 11
            role = QtCore.Qt.UserRole + user_role_config
            dobject = self.__configwidget_combo.itemData(index, role)
            print('Dobject',dobject)
            dobject_add = dobject()
            data[datakey] = dobject_add
            # Reload and redraw all data
            self.configWidget.reload_data()
            self.config_changed_flag.emit()
            return

        elif self.sender().__configType == 'configLiteral':
            data = self.__configwidget_input.currentText()  # ComboBox
            data_set = True

        elif self.sender().__configType == 'configColor':
            #print(funcname + ' Color')
            color = self.__configwidget_input.currentColor()  # ComboBox
            #color1 = color.getRgbF()
            color1 = color.getRgb()
            color_tmp = (color1[0],color1[1],color1[2])
            rint = int(color1[0] * 255)
            gint = int(color1[1] * 255)
            bint = int(color1[2] * 255)
            data = pydColor(color_tmp)
            #print('Got color',data)
            data_set = True

        elif self.sender().__configType == 'configStr':
            data = self.__configwidget_input.text()  # Textbox
            data_set = True

        elif self.sender().__configType == 'configRedvyprAddressStr':
            data = self.__configwidget_input.text()  # Textbox
            data_set = True

        elif self.sender().__configType == 'configDateTime':
            #print('Datetime')
            datetmp = self.__configwidget_input.dateTime()
            data = datetmp.toPyDateTime()
            data_set = True

        elif self.sender().__configType == 'configBool':
            data = self.__configwidget_input.currentText() == 'True' # Combobox
            data_set = True

        elif self.sender().__configType == 'configRedvyprAddress':
            addr = self.sender().redvypr_address
            data = str(addr)
            data_set = True
        else:
            logger.warning('Unknown config type {}'.format(self.sender().__configType))

        if data_set:
            if True: # or an existing model was changed
                #print('Type',type(item.__dataparent__))
                # Dictionaries?!
                if pydantic.BaseModel in item.__dataparent__.__class__.__mro__:
                    logger.debug('Adding to pydantic basemodel')
                    setattr(item.__dataparent__,item.__dataindex__, data)
                elif isinstance(item.__dataparent__, list):
                    logger.debug('Changing data at index {}'.format(item.__dataindex__))
                    item.__dataparent__[item.__dataindex__] = data
                # item.setText(1, str(data_num))

            # Reload and redraw all data
            self.configWidget.reload_data()
            self.config_changed_flag.emit()



#
#
#
# pydanticQTreeWidget
#
#
class pydanticQTreeWidget(QtWidgets.QTreeWidget):
    """ Qtreewidget that display a pydantic object
    """

    def __init__(self, data=None, dataname='data', show_datatype=True, show_editable_only=True, exclude=[]):
        funcname = __name__ + '.__init__():'
        super().__init__()
        logger.debug(funcname + str(data))
        self.setExpandsOnDoubleClick(False)
        # make only the first column editable
        #self.setEditTriggers(self.NoEditTriggers)
        #self.header().setVisible(False)
        self.exclude = exclude
        self.setHeaderLabels(['Variable','Value','Type'])
        self.data = data
        self.dataname = dataname
        # Display options
        self.show_editable_only = show_editable_only
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

    def reload_data(self, data=None):
        if data is not None:
            self.data = data

        self.clear()
        self.create_qtree()
        self.expandAll()
        self.resizeColumnToContents(0)

    def create_item(self, index, data, parent, edit_flag=None):
        """
        Creates recursively qtreewidgetitems. If the item to be created is a sequence (dict or list), it calls itself as often as it finds a real value
        Args:
            index:
            data:
            parent:

        Returns:

        """
        funcname = __name__ + '.create_item():'
        logger.debug(funcname)

        #print('Parent',parent)
        #print('Hallo',type(data))
        #print('Hallo2',data.__class__.__base__)
        flag_basemodel = False
        if isinstance(data, dict):
            #print('dict')
            flag_iterate = True
            flag_add_entry = True
        elif isinstance(data, list):
            #print('list')
            flag_iterate = True
            flag_add_entry = True
        elif pydantic.BaseModel in data.__class__.__mro__:
            #print('basemodel')
            try:
                model_config = data.model_config['extra']
            except:
                model_config = 'omitted'
            flag_iterate = True
            flag_basemodel = True
            flag_add_entry = False
            if 'allow' in model_config.lower():
                flag_add_entry = True
        else:
            #print('item')
            flag_iterate = False
            flag_add_entry = False




        # Find an optional "editable" flag
        editable = True
        try:
            #print('test editable ...')
            #print('Editable',parent.__data__)
            attr = getattr(parent.__data__,index)
            mfields = parent.__data__.model_fields[index]
            #print('Mfields ...',mfields)
            editable = mfields.json_schema_extra['editable']
            #editable = parent.__data__[index].json_schema_extra['editable']
            logger.debug('{} has an editable flag with {}'.format(index,editable))
            #print('done test editable ...')
        except:
            editable = True
            logger.debug('extra fields {}'.format(index),exc_info=True)

        #print('editable', editable)
        # Get the parentdata
        try:
            parentdata = parent.__data__
        except:
            parentdata = None

        try:  # If the parent allow to add entries, this item is removable
            removable = parent.__flag_add_entry__
            #print('removable', removable)
        except:
            removable = False


        if self.show_editable_only == False:
            flag_show_item = True
        elif editable and self.show_editable_only:
            flag_show_item = True
        else:
            flag_show_item = False

        if flag_show_item:
            if True:
                data_value = data  #
                # Check for the types
                type_hints_index = None
                typestr = data_value.__class__.__name__
                datatype = data_value.__class__
                try:
                    # Check if the parent is a pydantic Basemodel child
                    if pydantic.BaseModel in parentdata.__class__.__mro__:
                        # Check if the item is an etxra field that can
                        # be removed or a predefined field
                        base_attributes = parentdata.model_construct().model_dump().keys()
                        if index in base_attributes:
                            logger.debug('Attribute {} is a predefined attribute, not removable'.format(index))
                            removable = False

                        type_hints = typing.get_type_hints(parentdata,include_extras=True)
                        # save the type hints
                        type_hints_index = type_hints[index]
                        #print('type hints index', type_hints_index)
                        typestr = type_hints[index].__name__
                        datatype = type_hints[index]
                        # If annotated data is available look search for known datatypes
                        if typestr == 'Annotated':
                            #print('Annotated')
                            annotations = typing.get_args(type_hints[index])
                            for annotation in annotations:
                                if annotation == 'RedvyprAddressStr':
                                    typestr = annotation
                                    break

                except:
                    logger.debug('Could not get type hints for {}'.format(index),exc_info=True)

                indexstr = str(index)
                # Check if item should be excluded
                if indexstr in self.exclude:
                    return

            if (flag_iterate == False):  # Check if we have an item that is something with data (not a pydantic module, list or dict)
                item = QtWidgets.QTreeWidgetItem([indexstr, str(data_value),typestr])
                #item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)  # editable
                item.__data__ = data
                item.__dataparent__ = parentdata# parent.__data__ # can be used to reference the data (and change it)
                item.__dataindex__ = index
                item.__datatypestr__ = typestr
                item.__datatype__ = datatype
                item.__parent__ = parent
                item.__type_hints__ = type_hints_index
                item.__flag_add_entry__ = flag_add_entry
                item.__removable__ = removable
                item.__editable__ = editable
                # Add the item to the data
                #print('data',data)
                #print('data',type(data))
                #data.__item__ = item

                index_child = self.item_is_child(parent, item)
                if index_child == None:  # Check if the item is already existing, if no add it
                    parent.addChild(item)
                else: # Update the data (even if it hasnt changed
                    parent.child(index_child).setText(1,str(data_value))

            else: # Item that is iterable and can be a parent
                #print('loop')
                datatmp = data
                typestr = datatmp.__class__.__name__
                flag_modifiable = True
                indexstr = str(index)
                # Check if item should be excluded
                if indexstr in self.exclude:
                    return

                #print('gf',index)
                #print('gf type', type(index))
                #print('Hallo',str(index))
                # Create new item
                newparent = QtWidgets.QTreeWidgetItem([str(index), '',typestr])
                item = newparent
                newparent.__data__ = datatmp
                newparent.__dataindex__ = index
                newparent.__datatypestr__ = typestr
                newparent.__datatype__ = datatype
                newparent.__parent__ = parent
                newparent.__dataparent__ = parentdata  # parent.__data__ # can be used to reference the data (and change it)
                newparent.__modifiable__ = flag_modifiable
                newparent.__type_hints__ = type_hints_index
                newparent.__flag_add_entry__ = flag_add_entry
                newparent.__removable__ = removable
                newparent.__editable__ = editable
                #try:
                #    newparent.__dataparent__ = parent.__data__  # can be used to reference the data (and change it)
                #except:
                #    newparent.__dataparent__ = None

                index_child = self.item_is_child(parent, newparent)
                if index_child == None:  # Check if the item is already existing, if no add it
                    parent.addChild(newparent)
                else:
                    newparent = parent.child(index_child)


                for numi, newindex in enumerate(data):
                    if isinstance(data, dict):
                        #print('Dict',newindex)
                        newdata = datatmp[newindex]
                    elif isinstance(data, list):
                        #print('List', newindex)
                        newdata = datatmp[numi]
                        newindex = numi
                    elif pydantic.BaseModel in data.__class__.__mro__:
                        #print('numi',numi)
                        #print('newindex', newindex)
                        newdata = newindex[1]
                        newindex = newindex[0]
                        #print('basemodel newdata',newdata)
                        #print('newindex',newindex)
                        #print('newparent',newparent)
                    else:
                        logger.warning('Cannot iterate over type {}',type(data))

                    self.create_item(newindex, newdata, newparent, edit_flag= edit_flag)

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
        #print('data',self.data)
        if True:
            self.create_item(self.dataname, self.data, self.root)

        self.dataitem = self.root.child(0)
        self.resizeColumnToContents(0)
        self.blockSignals(False)
        self.expandAll()
        self.resizeColumnToContents(0)



    def resize_view(self):
        pass
        #self.resizeColumnToContents(0)


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
        if isinstance(obj, dict):
            return obj
        elif isinstance(obj, list):
            return range(0, len(obj))
        else:
            return None

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

