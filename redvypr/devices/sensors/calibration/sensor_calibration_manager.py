import copy
import datetime
import os.path
import zoneinfo
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import logging
import sys
import pyqtgraph
import yaml
import uuid
import pydantic
import typing
from collections.abc import Iterable
import numpy
from redvypr.redvypr_address import RedvyprAddress
from redvypr.data_packets import check_for_command
from redvypr.device import RedvyprDevice
import redvypr.files as redvypr_files
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple



_logo_file = redvypr_files.logo_file
_icon_file = redvypr_files.icon_file
description = 'Manager for sensors and calibrations'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.sencalmgr')
logger.setLevel(logging.DEBUG)

redvypr_devicemodule = True

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = False
    subscribes: bool = False
    description: str = 'Managa calibrations and sensors'


def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    return


class Device(RedvyprDevice):
    """
    Sensor and calibration manager
    """

    def __init__(self, **kwargs):
        """
        """
        funcname = __name__ + '__init__()'
        super(Device, self).__init__(**kwargs)
        logger.debug(funcname)

class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)