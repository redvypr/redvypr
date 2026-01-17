from typing import List, Optional, Union, Literal, TypeVar, Generic, Type
from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import datetime
from redvypr.redvypr_address import RedvyprAddress

class BaseSensor(BaseModel):
    """
    """
    name: str = Field(default='sensor')
    description: str = Field(default='Sensor')
    sn: str = Field(default='',description="The serial number of the sensor")
    sensortype: Literal['BaseSensor'] = Field(default='BaseSensor')



class BaseCalibration(BaseModel):
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda dt: dt.isoformat()  # Saves datetime as ISO-String
        }
    )

    calibration_date: datetime = Field(..., description="Date and time of calibration in ISO format.")
    calibration_type: Literal['BaseCalibration'] = Field(default='BaseCalibration')

    @field_validator('calibration_date', mode='before')
    def parse_calibration_date(cls, value):
        """Parses the calibration_date string into a datetime object."""
        if isinstance(value, str):
            # Beispiel: "14.01.2026 16:15:15" → datetime-Objekt
            return datetime.strptime(value, "%d.%m.%Y %H:%M:%S")
        return value

    def create_redvypr_address(self) -> 'RedvyprAddress':
        """
        Excepts an implementation
        """
        raise NotImplementedError(
            f"Class {self.__class__.__name__} needs 'create_redvypr_address' implementation."
        )


SensorType = TypeVar('SensorType', bound=BaseSensor)
CalibrationType = TypeVar('CalibrationType', bound=BaseCalibration)

class SensorMeta(Generic[SensorType, CalibrationType]):
    """Container class to pair a sensor type with its calibration type."""

    sensor_cls: Type[SensorType]
    calibration_cls: Type[CalibrationType]

    def __init__(self, sensor_cls: Type[SensorType], calibration_cls: Type[CalibrationType]):
        self.sensor_cls = sensor_cls
        self.calibration_cls = calibration_cls

    def create_sensor(self, **kwargs) -> SensorType:
        """Creates a sensor instance."""
        return self.sensor_cls(**kwargs)

    def create_calibration(self, **kwargs) -> CalibrationType:
        """Creates a calibration instance."""
        return self.calibration_cls(**kwargs)

    def create_sensor_from_calibration(
        self,
        calibration: CalibrationType,
        name: str,
        sn: str,
        **kwargs
    ) -> SensorType:
        """Creates a sensor instance from a calibration object."""
        return self.sensor_cls.from_calibration(
            calibration=calibration,
            name=name,
            sn=sn,
            **kwargs
        )





# Classic heat flow sensor
class HeatflowClassicCalibData(BaseModel):
    """Represents calibration coefficients and related data for a heat flow sensor."""

    model_config = ConfigDict(extra='forbid')



    calibcoeff: List[Optional[float]] = Field(
        default_factory=list,
        description="List of calibration coefficients, if set this was the reference sensor. Can include `None` for missing values."
    )
    calibdata: List[List[Union[float, str]]] = Field(
        default_factory=list,
        description="2D list of calibration data points."
    )
    calibration_date: str = Field(
        ...,
        description="Date and time of calibration in `DD.MM.YYYY HH:MM:SS` format."
    )
    header: List[str] = Field(
        default_factory=list,
        description="List of column headers for the calibration data."
    )
    ind_reference: int = Field(
        ...,
        description="Index of the reference channel used for calibration."
    )
    snr: List[str] = Field(
        default_factory=list,
        description="List of serial numbers for the calibrated sensors."
    )
    type: List[str] = Field(
        default_factory=list,
        description="List of sensor types (e.g., 'HFSM10-1m')."
    )

    @classmethod
    def parse_calibcoeff(cls, value: Union[str, float, None]) -> Optional[float]:
        """Parses 'NA' or empty strings to None, otherwise converts to float."""
        if value in ('NA', ''):
            return None
        return float(value) if value is not None else None

    @classmethod
    def preprocess_calibcoeff(cls, calibcoeff: List[Union[str, float]]) -> List[
        Optional[float]]:
        """Converts a list of strings/values (e.g., ['NA', 8.98]) to a list of Optional[float]."""
        return [cls.parse_calibcoeff(item) for item in calibcoeff]




class HeatflowClassicCalibration(BaseModel):
    """Represents the full calibration data for a Heatflow Classic sensor."""

    model_config = ConfigDict(
        extra='forbid',
        json_encoders={datetime: lambda dt: dt.isoformat()}  # ISO-Format für datetime
    )

    # Literal für die Kalibrierungsfamilie
    calibration_type: Literal['heatflow'] = Field(
        default='heatflow',
        description="Type of the calibration (fixed to 'heatflow')."
    )

    # Datetime-Felder
    calibration_date: datetime = Field(..., description="Date and time of calibration (ISO format).")
    date_produced: datetime = Field(..., description="Date when the sensor was produced (ISO format).")

    # Weitere Felder
    RTD: str = Field(default="", description="Resistance Temperature Detector (RTD) value.")
    calibration_HF_SI: Optional[float] = Field(
        default=None,
        description="Heat flux calibration value in SI units."
    )
    calibration_HF_SI_std: Optional[float] = Field(
        default=None,
        description="Standard deviation of the heat flux calibration value."
    )
    calibration_data: List['HeatflowClassicCalibData'] = Field(
        default_factory=list,
        description="List of calibration datasets."
    )
    comment: str = Field(default="", description="Optional comment.")
    contenttable: str = Field(default="", description="Type of content table.")
    customer: str = Field(default="", description="Customer name.")
    housing: str = Field(default="", description="Housing type.")
    impedance: str = Field(default="", description="Impedance value.")
    itemtype: str = Field(default="", description="Type of the item.")
    manufacturer: str = Field(default="", description="Manufacturer name.")
    manufacturer_sn: str = Field(default="", description="Manufacturer's serial number.")
    name: str = Field(default="", description="Name of the sensor.")
    order: str = Field(default="", description="Order number.")
    series: str = Field(default="", description="Series or model.")
    shipped: str = Field(default="", description="Shipping date or status.")
    steg: str = Field(default="", description="Additional metadata.")

    # Validator für datetime-Felder
    @field_validator('calibration_date', 'date_produced', mode='before')
    def parse_datetime(cls, value):
        """Parses datetime strings in 'DD.MM.YYYY HH:MM:SS' format."""
        if isinstance(value, str):
            return datetime.strptime(value, "%d.%m.%Y %H:%M:%S")
        return value

    @field_validator('calibration_data', mode='before')
    def preprocess_calibration_data(cls, value):
        """Converts 'NA' strings in calibration_data to None before validation."""
        if not value:
            return []

        for dataset in value:
            if 'calibcoeff' in dataset:
                dataset['calibcoeff'] = HeatflowClassicCalibData.preprocess_calibcoeff(
                    dataset['calibcoeff'])

        return value


    def create_redvypr_address(self) -> 'RedvyprAddress':
        caldate = self.calibration_date.isoformat()
        series = self.series
        astr = f"@calibration_type=='{self.calibration_type}' and calibration_date==dt({caldate}) and manufacturer_sn=='{self.manufacturer_sn}'"
        if len(series)>0:
            astr += f" and series=='{series}'"
        raddr = RedvyprAddress(astr)
        return raddr



class HeatflowClassicSensor(BaseSensor):
    """
    Specialized class for Heatflow Classic sensors.
    Inherits from BaseSensor and adds specific fields for Heatflow Classic sensors.
    """

    sensortype: Literal['HeatflowClassicSensor'] = Field(
        default='HeatflowClassicSensor',
        description="Type of the sensor (fixed to 'HeatflowClassicSensor')."
    )

    # Additional attributes to BaseSensor
    date_produced: datetime = Field(
        ...,
        description="Date when the sensor was produced."
    )
    series: str = Field(
        default="",
        description="Series or model of the Heatflow Classic sensor."
    )

    @classmethod
    def from_calibration(
        cls,
        calibration: 'HeatflowClassicCalibration',
        name: str,
        sn: str,
        **kwargs
    ) -> 'HeatflowClassicSensor':
        """
        Creates a HeatflowClassicSensor instance from a HeatflowClassicCalibration object.

        Args:
            calibration: An instance of HeatflowClassicCalibration.
            name: Name of the sensor.
            sn: Serial number of the sensor.
            **kwargs: Additional keyword arguments for the sensor.

        Returns:
            HeatflowClassicSensor: An instance of the Heatflow Classic sensor.
        """
        return cls(
            name=name,
            sn=sn,
            series=calibration.series,
            date_produced=calibration.date_produced,
            description=calibration.comment or f"Heatflow Classic Sensor: {calibration.series}",
            **kwargs
        )



# Collect all sensor pairs:
HEATFLOW_CLASSIC_META = SensorMeta[
    HeatflowClassicSensor,
    HeatflowClassicCalibration
](
    sensor_cls=HeatflowClassicSensor,
    calibration_cls=HeatflowClassicCalibration
)