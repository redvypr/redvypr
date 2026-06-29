from PyQt6 import QtWidgets, QtCore, QtGui

from redvypr.widgets.pydanticConfigWidget import logger


class Dictqtreewidget(QtWidgets.QTreeWidget):
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
        funcname = __name__ + '.reload_data():'
        #print(funcname)
        #print('data',data)
        #print('------')
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
            item.__dataparent__ = parent.__data__ # can be used to reference the data (and change it)
            item.__dataindex__ = index
            item.__datatypestr__ = typestr
            item.__parent__  = parent
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
            newparent.__data__ = datatmp
            newparent.__dataindex__ = index
            newparent.__datatypestr__ = typestr
            newparent.__parent__ = parent
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
            self.create_item(self.dataname, self.data, self.root)

        self.dataitem = self.root.child(0)
        self.resizeColumnToContents(0)
        self.blockSignals(False)

    def resize_view(self):
        pass
        #self.resizeColumnToContents(0)


class EditableDictQTreeWidget(Dictqtreewidget):
    # Signal, das (Adresse, Key/Index-Liste, Constraint-Index-Liste) sendet
    deleteRequested = QtCore.pyqtSignal(str, dict)

    def __init__(self, data={}, dataname='data', show_datatype=True, address="", mode="expanded"):
        super().__init__(data, dataname, show_datatype)
        self.mode = mode
        self.address = address  # Wir merken uns, zu welcher Adresse die Daten gehören
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, pos):
        item = self.itemAt(pos)
        if not item or item == self.dataitem:
            return

        menu = QtWidgets.QMenu(self)
        if self.mode == "expanded":
            delete_action = menu.addAction("Delete entry")

            # delete icon
            delete_action.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_TrashIcon))

            action = menu.exec(self.mapToGlobal(pos))

            if action == delete_action:
                self.handle_delete(item)

        else:
            delete_action = menu.addAction('Delete entry (disabled in "merge" mode)')

            # delete icon
            delete_action.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_TrashIcon))
            delete_action.setEnabled(False)
            action = menu.exec(self.mapToGlobal(pos))

    def handle_delete(self, item):
        # Wir müssen herausfinden, was gelöscht werden soll
        key_or_index = item.__dataindex__
        #parentdata = item.__parentdata__
        data = item.__data__
        parent_item = item.__parent__
        print("Data",data)
        print("Parent",self.dataitem, )

        # Check if we are at the root and want to delete an address
        address = None
        keys_to_remove = None
        constraints_to_remove = None
        if parent_item == self.dataitem:
            address = key_or_index
            keys_to_remove = []
            constraints_to_remove = []
            print("Removing address",address)
        else:
            # Spezialfall: Wir löschen ein Constraint aus der Liste
            if parent_item and parent_item.__dataindex__ == '_constraints':
                constraints_to_remove = [int(key_or_index)]
                address_item = parent_item.__parent__
                address = address_item.__dataindex__
            elif item.__dataindex__ == '_constraints':
                print("Removing all constraints")
                constraints_to_remove = []
                address_item = parent_item
                address = address_item.__dataindex__
            else:
                # Normaler Key-Value Pair
                keys_to_remove = [str(key_or_index)]
                address_item = parent_item
                address = address_item.__dataindex__

            if address_item is not self.dataitem:
                print("Cannot delete items (not base item)")

        # Confirmation dialog
        res = QtWidgets.QMessageBox.question(
            self, "Confirm Deletion",
            f"Are you sure you want to delete '{key_or_index}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if res == QtWidgets.QMessageBox.Yes:
            delete_dict = {'constraints':constraints_to_remove,'keys':keys_to_remove}
            print("Removing",address, delete_dict)
            self.deleteRequested.emit(address, delete_dict)
