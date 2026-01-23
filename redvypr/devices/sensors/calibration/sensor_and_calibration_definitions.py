from typing import List, Optional, Union, Literal, TypeVar, Generic, Type
from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import datetime
import json
import hashlib
from typing import Any
from redvypr.redvypr_address import RedvyprAddress
from .calibration_models import CalibrationGeneric, CalibrationLinearFactor, CalibrationNTC, CalibrationPoly

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
    calibration_type: Literal['heatflow_classic'] = Field(
        default='heatflow_classic',
        description="Type of the calibration (fixed to 'heatflow')."
    )

    channel: Literal['hf'] = Field(
        default='hf',
        description="Channel name"
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

    @property
    def sensor_model(self):
        return self.series

    @property
    def date(self):
        return self.calibration_date

    @property
    def sn(self):
        return self.manufacturer_sn

    # In some of the yamls there is a newline in series & name
    @field_validator('series', 'name', mode='before', check_fields=False)
    @classmethod
    def fix_newlines_in_strings(cls, value):
        """Entfernt Newlines aus den Feldern 'series' und 'name'."""
        if isinstance(value, str):
            value_ret = value.replace('\n', '').strip()
            return value_ret
        return value

    # Validator für datetime-Felder
    @field_validator('calibration_date', 'date_produced', mode='before')
    def parse_datetime(cls, value):
        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            # optionales Prefix entfernen
            if value.startswith("__dt__:"):
                value = value.removeprefix("__dt__:")

            # 1) ISO-8601 versuchen
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass

            # 2) Deutsches Format versuchen
            try:
                return datetime.strptime(value, "%d.%m.%Y %H:%M:%S")
            except ValueError:
                pass

            raise ValueError(
                f"Unsupported datetime format: {value!r}. "
                "Expected ISO-8601 or 'DD.MM.YYYY HH:MM:SS'"
            )

        return value
    def parse_datetime_legacy(cls, value):
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
        astr = f"@i:calibration and calibration_type=='{self.calibration_type}' and calibration_date==dt({caldate}) and manufacturer_sn=='{self.manufacturer_sn}'"
        if len(series)>0:
            astr += f" and series=='{series}'"
        raddr = RedvyprAddress(astr)
        return raddr

    def get_data_hash(self) -> str:
        """
        Generates a deterministic SHA256 hash of the model data.
        Uses sorted keys to ensure that field order doesn't change the hash.
        """
        # We use model_dump_json to utilize your custom json_encoders (e.g. for datetime)
        json_string = self.model_dump_json()

        # To ensure "byte-perfect" stability regardless of whitespace/field order in Pydantic:
        # We parse it back once and dump it with sorted keys.
        stable_json = json.dumps(
            json.loads(json_string),
            sort_keys=True,
            separators=(',', ':')
        )
        return hashlib.sha256(stable_json.encode('utf-8')).hexdigest()

    def __eq__(self, other: Any) -> bool:
        """Enables equality comparison based on the data hash."""
        if not isinstance(other, HeatflowClassicCalibration):
            return False
        return self.get_data_hash() == other.get_data_hash()

    def __hash__(self) -> int:
        """Enables the use of sets and dict keys by returning the integer representation of the hash."""
        # Python's hash() must return an integer
        return int(self.get_data_hash(), 16)



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


import pydantic
from typing import Type, Dict, Any, Optional


class CalibrationFactory:
    """
    A dynamic factory to register and create calibration models
    based on the 'calibration_type' field.
    """
    _registry: Dict[str, Type[pydantic.BaseModel]] = {}

    @classmethod
    def register(cls, calibration_type: str, model_class: Type[pydantic.BaseModel]):
        """
        Registers a new calibration model class.
        """
        cls._registry[calibration_type] = model_class
        print(
            f"Registered calibration type: '{calibration_type}' as {model_class.__name__}")

    @classmethod
    def create(cls, data: Dict[str, Any]) -> pydantic.BaseModel:
        # 1. Try via explicit type (Fast Path)
        cal_type = data.get('calibration_type')

        if cal_type:
            for modelname, model in cls._registry.items():
                # Check if the model's default for the type field matches
                # We look at the field definition in Pydantic
                fields = model.model_fields
                target_field = fields.get('calibration_type') or fields.get(
                    'calibration_family')

                if target_field and target_field.default == cal_type:
                    return model.model_validate(data)

        # 2. Fallback: Try all models until one fits (Slow Path)
        print(
            f"No explicit type found or matched. Brute-forcing {len(cls._registry)} models...")

        for modelname,model in cls._registry.items():
            try:
                # model_validate raises a ValidationError if the structure doesn't match
                return model.model_validate(data)
            except pydantic.ValidationError:
                continue

        raise ValueError(
            "None of the registered models could validate the provided data.")

# Initial registration of your core classes
CalibrationFactory.register('linearfactor', CalibrationLinearFactor)
CalibrationFactory.register('polynom', CalibrationPoly)
CalibrationFactory.register('ntc', CalibrationNTC)
CalibrationFactory.register('generic', CalibrationGeneric)
CalibrationFactory.register('heatflow_classic', HeatflowClassicCalibration)

