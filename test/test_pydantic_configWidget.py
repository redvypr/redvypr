from PyQt5 import QtWidgets, QtCore, QtGui
import redvypr.gui
import sys
import copy
from redvypr.widgets.pydanticConfigWidget import pydanticConfigWidget
from redvypr.redvypr_address import RedvyprAddress, RedvyprAddressStr
import pydantic
import datetime
import typing
import numpy as np
import uuid

class config_test(pydantic.BaseModel):
    """
    Calibration model for a heatflow sensor
    """
    structure_version: str = '1.0'
    calibration_type: typing.Literal['A','one','two'] = 'one'
    parameter: str = 'HF'
    sn: str = '' # The serial number of the sensor
    sensor_model: str = ''  # The sensor model
    coeff: float = np.NaN
    coeff_std: typing.Optional[float] = None
    unit:  str = 'W m-2 mV-1'
    raddr: RedvyprAddressStr = pydantic.Field(default=str(RedvyprAddress('d:test')))
    unit_input: str = 'mV'
    date: datetime.datetime = pydantic.Field(default=datetime.datetime(1970,1,1,0,0,0), description='The calibration date')
    calibration_id: str = pydantic.Field(default_factory=lambda: uuid.uuid4().hex, description='ID of the calibration, can be choosen by the user. ID should be unique')
    comment: typing.Optional[str] = None
    uniontest: typing.Union[str,float] = pydantic.Field(default='fdsf')
    calibrations: typing.List[typing.Union[float, str]] = pydantic.Field(default=[], description = 'List of sensor calibrations')
    #some_dict: typing.Dict[typing.Union[str,float]] = pydantic.Field(default={},
    some_dict: typing.Dict[str,typing.Union[float, bool, list]] = pydantic.Field(default={},description='Configuration of sensors, keys are their serial numbers')

configtest = config_test()

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

    configtree = pydanticConfigWidget(config=configtest, config_location='right')
    # Set the size

    layout.addWidget(configtree)
    widget.resize(1000, 800)
    widget.show()
    sys.exit(app.exec_())



if __name__ == '__main__':
    main()
