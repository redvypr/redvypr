import datetime
import logging
import sys
from redvypr.data_packets import check_for_command
import pydantic
from pydantic import field_validator
import typing
import uuid
import hashlib
from typing import Any
import json
from redvypr.redvypr_address import RedvyprAddress

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('event_definitions')
logger.setLevel(logging.INFO)

redvypr_devicemodule = True


class Person(pydantic.BaseModel):
    first_name: str = pydantic.Field(default="")
    last_name: str = pydantic.Field(default="")
    email: typing.Optional[str] = None
    phone: typing.Optional[str] = None
    role: typing.Optional[str] = pydantic.Field(
        default=None,
        description="e.g., 'Lead Scientist', 'Field Technician'"
    )

    @property
    def full_name(self) -> str:
        """Returns the combined first and last name."""
        return f"{self.first_name} {self.last_name}"

class DatastreamBaseConfig(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='allow')
    version: str = 'v1.0'
    name: str = ''
    tstart: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    tend: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    location: typing.Optional[str] = pydantic.Field(default=None)
    lon: typing.Optional[float] = pydantic.Field(default=None)
    lat: typing.Optional[float] = pydantic.Field(default=None)
    contacts: typing.List[Person] = pydantic.Field(default_factory=list)
    description: str = 'A config for a specific datastream'

    @field_validator('tstart', 'tend', )
    @classmethod
    def ensure_utc(cls, v):
        if v and v.tzinfo is None:
            # Wenn keine TZ vorhanden, gehe von UTC aus oder wirf einen Fehler
            return v.replace(tzinfo=datetime.timezone.utc)
        return v

class EventBaseConfig(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='allow')
    version: str = 'v1.0'
    name: str = ''
    datastream: RedvyprAddress = pydantic.Field(default_factory=lambda: RedvyprAddress("@"),description="The datastream")
    num: int = pydantic.Field(default=0,description="Event number")
    uuid: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    eventtype: str = pydantic.Field(default='generic')
    # Die "Vorschlagsliste" als Klassen-Attribut (wird nicht mit-serialisiert)
    default_event_types: typing.ClassVar[list[str]] = [
        'measurement',
        'station',
        'generic',
        'mooring',
        'calibration'
    ]

    tstart: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    tend: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    tcreated: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    tmodified: typing.Optional[datetime.datetime] = pydantic.Field(default=None)
    location: typing.Optional[str] = pydantic.Field(default=None)
    lon: typing.Optional[float] = pydantic.Field(default=None)
    lat: typing.Optional[float] = pydantic.Field(default=None)
    contacts: typing.List[Person] = pydantic.Field(default_factory=list)
    description: typing.Optional[str] = pydantic.Field(default=None)
    datastreams: typing.Dict[str, DatastreamBaseConfig] = pydantic.Field(
        default_factory=dict)

    def create_redvypr_address(self) -> 'RedvyprAddress':
        caldate = self.calibration_date.isoformat()
        series = self.series
        astr = f"@i:calibration and calibration_type=='{self.calibration_type}' and calibration_date==dt({caldate}) and manufacturer_sn=='{self.manufacturer_sn}'"
        if len(series) > 0:
            astr += f" and series=='{series}'"
        raddr = RedvyprAddress(astr)
        return raddr

    @field_validator('tstart', 'tend', 'tcreated', 'tmodified')
    @classmethod
    def ensure_utc(cls, v):
        if v and v.tzinfo is None:
            # Wenn keine TZ vorhanden, gehe von UTC aus oder wirf einen Fehler
            return v.replace(tzinfo=datetime.timezone.utc)
        return v

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
        if not isinstance(other, EventBaseConfig):
            return False
        return self.get_data_hash() == other.get_data_hash()

    def __hash__(self) -> int:
        """Enables the use of sets and dict keys by returning the integer representation of the hash."""
        # Python's hash() must return an integer
        return int(self.get_data_hash(), 16)


