import logging
from PyQt6 import QtWidgets, QtCore, QtGui


# This is at the moment not working, due to the threads/subprocesses.
class QTextEditHandler(logging.Handler):
    def __init__(self, text_edit_widget):
        super().__init__()
        self.text_edit_widget = text_edit_widget

    def emit(self, record):
        try:
            msg = self.format(record)
            self.text_edit_widget.append(msg)
        except Exception:
            self.handleError(record)


class QLoggerWidget(QtWidgets.QWidget):
    def __init__(self,*args,logger=None,**kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logger
        self.layout = QtWidgets.QVBoxLayout(self)
        self.logtext = QtWidgets.QTextEdit()
        self.layout.addWidget(self.logtext)
        self.logtext.setReadOnly(True)  # Read-only
        self.log_handler = QTextEditHandler(self.logtext)
        self.logger.addHandler(self.log_handler)


class loglevelWidget(QtWidgets.QWidget):
    def __init__(self,*args, redvypr=None, **kwargs):
        """A widget to show and edit the loglevel of the redvypr instances

        """
        super().__init__(*args,**kwargs)
        self.short_imported_only = True
        self.redvypr = redvypr
        # Get the loggernames of the devices
        logger_names = ["redvypr","redvypr.base"]
        baselogger = logging.getLogger("redvypr.base")
        for base_tmp in baselogger.getChildren():
            logger_names.append(base_tmp.name)
        for dev_dict in self.redvypr.devices:
            dev_obj = dev_dict.get("device")
            if dev_obj:
                logger_tmp = getattr(dev_obj, 'logger', None)
                if logger_tmp:
                    logger_names.append(logger_tmp.name)

        self.logger_names_devices = logger_names
        self.__logtable = QtWidgets.QTreeWidget()
        self.__loglevelwidget_layout = QtWidgets.QVBoxLayout(self)
        self.__check_all_loggers = QtWidgets.QCheckBox('Show all loggers')
        self.__check_all_loggers.setChecked(False)
        self.__check_all_loggers.stateChanged.connect(self.__update_logleveltable)
        self.__loglevelwidget_layout.addWidget(self.__logtable)
        self.__loglevelwidget_layout.addWidget(self.__check_all_loggers)
        self.__update_logleveltable()

    def __update_logleveltable(self):
        loglevels = ['INFO', 'DEBUG', 'WARNING', 'ERROR', 'CRITICAL']
        self.__logtable.clear()
        table = self.__logtable
        root = table.invisibleRootItem()
        table.setColumnCount(3)
        table.setHeaderLabels(['Logger name', 'Loglevel', 'Loglevel of group'])
        redvypr_logger = []
        other_logger = []
        other_logger_root = []
        rootlogger = logging.getLogger('root')
        #print("devices",self.logger_names_devices)
        for name in logging.root.manager.loggerDict:
            #print("Name",name)
            #print(name in self.logger_names_devices)
            #self.logger_names_devices
            logger_tmp = logging.getLogger(name)
            if self.short_imported_only:
                if name in self.logger_names_devices:
                    redvypr_logger.append(logger_tmp)
            else:
                if 'redvypr' in name:
                    redvypr_logger.append(logger_tmp)
                else:
                    other_logger.append(logger_tmp)
                    # print('Parent',logger_tmp.parent)
                    if logger_tmp.parent == rootlogger:
                        other_logger_root.append(logger_tmp)

        logger_tmp = logging.getLogger('redvypr')
        itm = QtWidgets.QTreeWidgetItem([logger_tmp.name])
        root.addChild(itm)
        # Add combobox for logger alone
        loglevel_combobox = QtWidgets.QComboBox()
        loglevel_combobox.__logger__ = logger_tmp
        loglevel_combobox.__propagate_down__ = False
        for i, l in enumerate(loglevels):
            loglevel_combobox.addItem(l)

        level = logger_tmp.getEffectiveLevel()
        levelname = logging.getLevelName(level)
        loglevel_combobox.setCurrentText(levelname)
        loglevel_combobox.currentIndexChanged.connect(self.__loglevelChanged__)
        table.setItemWidget(itm, 1, loglevel_combobox)
        # Add combobox for logger and children
        loglevel_combobox_all = QtWidgets.QComboBox()
        loglevel_combobox_all.__logger__ = logger_tmp
        loglevel_combobox_all.__propagate_down__ = True
        for i, l in enumerate(loglevels):
            loglevel_combobox_all.addItem(l)

        level = logger_tmp.getEffectiveLevel()
        levelname = logging.getLevelName(level)
        loglevel_combobox_all.setCurrentText(levelname)
        loglevel_combobox_all.currentIndexChanged.connect(self.__loglevelChanged__)
        table.setItemWidget(itm, 2, loglevel_combobox_all)

        logger_children = logger_tmp.getChildren()
        self.__update_logleveltable_recursive(itm, logger_children)

        if self.__check_all_loggers.isChecked():
            # update the other loggers
            for other_logger_tmp in other_logger_root:
                logger_children = other_logger_tmp.getChildren()
                itm_other = QtWidgets.QTreeWidgetItem([other_logger_tmp.name])
                root.addChild(itm_other)
                # Add combobox for logger alone
                loglevel_combobox = QtWidgets.QComboBox()
                loglevel_combobox.__logger__ = other_logger_tmp
                loglevel_combobox.__propagate_down__ = False
                for i, l in enumerate(loglevels):
                    loglevel_combobox.addItem(l)

                level = other_logger_tmp.getEffectiveLevel()
                levelname = logging.getLevelName(level)
                loglevel_combobox.setCurrentText(levelname)
                loglevel_combobox.currentIndexChanged.connect(self.__loglevelChanged__)
                table.setItemWidget(itm_other, 1, loglevel_combobox)
                if len(logger_children) > 0:
                    # Add combobox for logger and children
                    loglevel_combobox_all = QtWidgets.QComboBox()
                    loglevel_combobox_all.__logger__ = other_logger_tmp
                    loglevel_combobox_all.__propagate_down__ = True
                    for i, l in enumerate(loglevels):
                        loglevel_combobox_all.addItem(l)

                    level = other_logger_tmp.getEffectiveLevel()
                    levelname = logging.getLevelName(level)
                    loglevel_combobox_all.setCurrentText(levelname)
                    loglevel_combobox_all.currentIndexChanged.connect(self.__loglevelChanged__)
                    table.setItemWidget(itm_other, 2, loglevel_combobox_all)
                    self.__update_logleveltable_recursive(itm_other, logger_children)

    def __update_logleveltable_recursive(self, itm, logger_children):
        table = self.__logtable
        loglevels = ['INFO', 'DEBUG', 'WARNING', 'ERROR', 'CRITICAL']
        for logger_children in logger_children:
            # print('Logger children',logger_children)
            if logger_children.name in self.logger_names_devices:
                itm_child = QtWidgets.QTreeWidgetItem([logger_children.name])
                itm.addChild(itm_child)
                # Add combobox
                loglevel_combobox = QtWidgets.QComboBox()
                loglevel_combobox.__logger__ = logger_children
                for i, l in enumerate(loglevels):
                    loglevel_combobox.addItem(l)

                level = logger_children.getEffectiveLevel()
                levelname = logging.getLevelName(level)
                loglevel_combobox.setCurrentText(levelname)
                loglevel_combobox.currentIndexChanged.connect(self.__loglevelChanged__)
                table.setItemWidget(itm_child, 1, loglevel_combobox)

                logger_children_children = logger_children.getChildren()
                if len(logger_children_children) > 0:
                    # Add combobox for logger and children
                    loglevel_combobox_all = QtWidgets.QComboBox()
                    loglevel_combobox_all.__logger__ = logger_children
                    loglevel_combobox_all.__propagate_down__ = True
                    for i, l in enumerate(loglevels):
                        loglevel_combobox_all.addItem(l)

                    level = logger_children.getEffectiveLevel()
                    levelname = logging.getLevelName(level)
                    loglevel_combobox_all.setCurrentText(levelname)
                    loglevel_combobox_all.currentIndexChanged.connect(self.__loglevelChanged__)
                    table.setItemWidget(itm_child, 2, loglevel_combobox_all)

                self.__update_logleveltable_recursive(itm_child, logger_children_children)

        table.expandAll()
        for i in range(3):
            table.resizeColumnToContents(i)

        # self.devicetree.sortByColumn(0, QtCore.Qt.AscendingOrder)
        # self.devicetree.currentItemChanged.connect(self.qtreewidget_item_changed)

    def __loglevelChanged__(self):
        loglevel = self.sender().currentText()
        logger_tmp = self.sender().__logger__
        propagate_down = self.sender().__propagate_down__
        if (logger_tmp is not None):
            logger_tmp.info('loglevel changed to {}'.format(loglevel))
            # logger_tmp.setLevel(loglevel)
            self.redvypr.set_loglevel(loglevel=loglevel, loggername=logger_tmp.name, propagate_down=propagate_down)
            self.__update_logleveltable()


