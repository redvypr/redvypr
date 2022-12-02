import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import logging
import sys
import yaml

description = 'An example device'

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('exampledevice')
logger.setLevel(logging.DEBUG)

