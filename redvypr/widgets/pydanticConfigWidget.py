import copy
import time
import logging
import sys
import yaml
from PyQt5 import QtWidgets, QtCore, QtGui
import pydantic
import typing
from redvypr.configdata import configtemplate_to_dict
from redvypr.device import redvypr_device
from redvypr.widgets.redvypr_addressWidget import datastreamWidget
import redvypr.configdata
import redvypr.files as files


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('pydanticConfigWidget')
logger.setLevel(logging.DEBUG)


class pydanticDeviceConfigWidget(QtWidgets.QWidget):
    """
    Config widget for a pydantic configuration
    """
    def __init__(self, device = None, exclude = []):
        funcname = __name__ + '.__init__():'
        super().__init__()
        logger.debug(funcname)
        self.device = device
        self.exclude = exclude
        self.layout = QtWidgets.QGridLayout(self)
        self.label = QtWidgets.QLabel('Configuration of\n{:s}'.format(self.device.name))
        self.layout.addWidget(self.label)
        dataname = self.device.name + '.config'
        self.configWidget = pydanticQTreeWidget(self.device.config, dataname=dataname, exclude = self.exclude)
        self.layout.addWidget(self.configWidget)

#
#
# configWidget
#
#
class pydanticConfigWidget(QtWidgets.QWidget):
    #config_changed = QtCore.pyqtSignal(dict)  # Signal notifying that the configuration has changed
    config_changed_flag = QtCore.pyqtSignal()  # Signal notifying that the configuration has changed
    def __init__(self, config=None, editable = True, configname = None, exclude = [], config_location='bottom'):
        funcname = __name__ + '.__init__():'
        super().__init__()
        self.exclude = exclude
        self.layout = QtWidgets.QGridLayout(self)
        self.config_location = config_location
        #self.label = QtWidgets.QLabel('Configuration of\n{:s}'.format(self.device.name))
        #self.layout.addWidget(self.label)
        if configname is None:
            configname = 'pydanticConfig'

        self.config = config
        self.configWidget = pydanticQTreeWidget(self.config, dataname=configname, exclude=self.exclude)
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


        #self.closeButton = QtWidgets.QPushButton('Close')
        #self.closeButton.clicked.connect(self.close)

        self.layout.addWidget(self.configWidget, 0, 0)
        #self.layout.addWidget(self.closeButton, 1, 0)

    def __createConfigWidgetForItem(self, item):
        """
        creates self.__configwidget for item type
        :param item:
        :return:
        """
        print('Create configwidget', item)
        if (item.__datatypestr__ == 'int') or (item.__datatypestr__ == 'float'):
            self.createConfigWidgetNumber(item, dtype=item.__datatypestr__)
        elif (item.__datatypestr__ == 'str'):
            self.createConfigWidgetStr(item)
        elif (item.__datatypestr__ == 'datetime'):
            self.createConfigWidgetDateTime(item)
        elif (item.__datatypestr__ == 'bool'):
            self.createConfigWidgetBool(item)

    def __comboTypeChanged(self,index):
        """
        Called when the combobox of the datatype is changed
        :param index:
        :return:
        """
        print('Index',index)
        user_role_config = 11
        role = QtCore.Qt.UserRole + user_role_config
        item = self.__configCombo.itemData(index, role)
        # Get the datatypestr and call the gui create function again
        datatypestr = self.__configCombo.currentText()
        item.__datatypestr__ = datatypestr
        print('Open config gui with item',item)
        # Changed the datatype, now recreate the widgets
        self.configGui_layout.removeItem(self.stretchy_spacer_thing)
        try:
            self.__configwidget.close()
        except:
            pass

        self.__createConfigWidgetForItem(item)
        self.configGui_layout.addWidget(self.__configwidget)
        # Add a stretch
        self.configGui_layout.addItem(self.stretchy_spacer_thing)



    def __openConfigGui__(self, item):
        funcname = __name__ + '.__openConfigGui__():'
        logger.info(funcname)
        # Remove the stretch and all widgets
        self.configGui_layout.removeItem(self.stretchy_spacer_thing)
        try:
            self.__configwidget.close()
        except:
            pass
        try:
            self.__configCombo.close()
        except:
            pass

        print('some information')
        print(item.__data__)
        print(item.__dataparent__)
        print(item.__dataindex__)
        print(item.__datatypestr__)
        print(item.__parent__)
        print('Done')
        try:
            type_hints = item.__type_hints__
        except:
            type_hints = None

        if type_hints is not None:
            print('Type hints', type_hints)
            # Get the different type hints
            type_args = typing.get_args(type_hints)
            self.__configCombo = QtWidgets.QComboBox()
            index_datatype = None
            for arg in type_args:
                argstr = arg.__name__
                self.__configCombo.addItem(argstr)
                index = self.__configCombo.count() - 1
                datatypestr_tmp = item.__data__.__class__.__name__
                if argstr == datatypestr_tmp:
                    index_datatype = index
                user_role_config = 11
                role = QtCore.Qt.UserRole + user_role_config
                self.__configCombo.setItemData(index, item, role)
                print('index',index,'item',item,'argstr',argstr, datatypestr_tmp, item.__datatypestr__)

            if index_datatype is not None:
                self.__configCombo.setCurrentIndex(index_datatype)
                item.__datatypestr__ = datatypestr_tmp
            # Get the index for the combo
            self.__configCombo.currentIndexChanged.connect(self.__comboTypeChanged)
            self.configGui_layout.addWidget(self.__configCombo)



        self.__createConfigWidgetForItem(item)
        self.configGui_layout.addWidget(self.__configwidget)
        # Add a stretch
        self.configGui_layout.addItem(self.stretchy_spacer_thing)

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
        #if (parentparent is not None):  # Remove button
        #    self.__add_remove_btn__(self.__layoutwidget_int, item=item, dtype='str')
        #    try:
        #        removable = parent.__data__.children_removable
        #    except Exception as e:
        #        removable = True

        #    self.__configwidget_remove.setEnabled(removable)

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
        # if (parentparent is not None):  # Remove button
        #    self.__add_remove_btn__(self.__layoutwidget_int, item=item, dtype='str')
        #    try:
        #        removable = parent.__data__.children_removable
        #    except Exception as e:
        #        removable = True

        #    self.__configwidget_remove.setEnabled(removable)

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
        item = self.sender().item
        #print(item.__data__)
        #print(item.__dataparent__)
        #print(item.__dataindex__)
        #print(item.__datatypestr__)
        #print(item.__parent__)
        data_set = False
        if self.sender().__configType == 'configNumber':
            print(funcname + ' ' + self.sender().__configType)
            print('Setting data')
            print('Reloading data')
            print('Item',item)
            self.__configwidget_input
            data = self.__configwidget_input.value()  # Works for int/float spinboxes
            data_set = True
        elif self.sender().__configType == 'configStr':
            data = self.__configwidget_input.text()  # Textbox
            data_set = True

        elif self.sender().__configType == 'configDateTime':
            print('Datetime')
            datetmp = self.__configwidget_input.dateTime()
            data = datetmp.toPyDateTime()
            data_set = True

        elif self.sender().__configType == 'configBool':
            data = self.__configwidget_input.currentText() == 'True' # Combobox
            data_set = True

        if data_set:
            print('Type',type(item.__dataparent__))
            setattr(item.__dataparent__,item.__dataindex__, data)
            # item.setText(1, str(data_num))
            self.configWidget.reload_data()
            self.config_changed_flag.emit()






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

    def create_item(self, index, data, parent, edit_flags = None):
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

        #print('Hallo',type(data))
        flag_basemodel = False
        if isinstance(data, dict):
            #print('dict')
            flag_iterate = True
        elif isinstance(data, list):
            #print('list')
            flag_iterate = True
        #elif isinstance(data, pydantic.BaseModel):
        elif data.__class__.__base__ == pydantic.BaseModel:
            #print('basemodel')
            flag_iterate = True
            flag_basemodel = True
        else:
            #print('item')
            flag_iterate = False

        # Try to get extra information
        if edit_flags is None:
            edit_flags = {'editable':True}

        try:
            #print('fsfdsf',parent.__data__)
            attr = getattr(parent.__data__,index)
            mfields = parent.__data__.model_fields[index]
            #print('Mfields',mfields)
            editable = mfields.json_schema_extra['editable']
            #editable = parent.__data__[index].json_schema_extra['editable']
            #print('Editable',index,editable)
            edit_flags['editable'] = editable
        except Exception as e:
            #logger.debug('extra fields',exc_info=True)
            pass

        if edit_flags['editable'] and self.show_editable_only:
            if(flag_iterate == False): # Check if we have an item that is something with data (not a pydantic module, list or dict)
                data_value = data  #
                # Check for the types
                type_hints_index = None
                try:
                    parentdata = parent.__data__
                    if parentdata.__class__.__base__ == pydantic.BaseModel:
                        type_hints = typing.get_type_hints(parentdata)
                        print(type_hints)
                        # save the type hints
                        type_hints_index = type_hints[index]
                        typestr = type_hints[index].__name__
                except:
                    logger.info('bad',exc_info=True)
                    typestr = data_value.__class__.__name__


                indexstr = str(index)
                # Check if item should be excluded
                if indexstr in self.exclude:
                    return
                item = QtWidgets.QTreeWidgetItem([indexstr, str(data_value),typestr])
                #item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)  # editable
                item.__data__ = data
                item.__dataparent__ = parent.__data__ # can be used to reference the data (and change it)
                item.__dataindex__ = index
                item.__datatypestr__ = typestr
                item.__parent__ = parent
                item.__type_hints__ = type_hints_index
                # Add the item to the data
                #print('data',data)
                #print('data',type(data))
                #data.__item__ = item

                index_child = self.item_is_child(parent, item)
                if index_child == None:  # Check if the item is already existing, if no add it
                    parent.addChild(item)
                else: # Update the data (even if it hasnt changed
                    parent.child(index_child).setText(1,str(data_value))

            else:
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
                        #print('Dict',newindex)
                        newdata = datatmp[newindex]
                    elif isinstance(data, list):
                        #print('List', newindex)
                        newdata = datatmp[numi]
                        newindex = numi
                    elif data.__class__.__base__ == pydantic.BaseModel:
                        #print('numi',numi)
                        #print('newindex', newindex)
                        newdata = newindex[1]
                        newindex = newindex[0]
                        #print('basemodel newdata',newdata)
                        #print('newindex',newindex)
                        #print('newparent',newparent)

                    self.create_item(newindex, newdata, newparent, edit_flags = edit_flags)

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



    def resize_view(self):
        pass
        #self.resizeColumnToContents(0)

