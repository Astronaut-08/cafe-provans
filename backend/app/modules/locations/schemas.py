from datetime import time
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=70)]


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f'Невірний часовий пояс: {value}')
    return value


class LocationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: Name
    address: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    instagram: str | None = Field(default=None, max_length=150)
    opening_time: time | None = None
    closing_time: time | None = None
    timezone: str = Field(default='Europe/Kyiv', max_length=50)
    is_active: bool = True

    _check_timezone = field_validator('timezone')(_validate_timezone)


class LocationUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: Name | None = None
    address: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    instagram: str | None = Field(default=None, max_length=150)
    opening_time: time | None = None
    closing_time: time | None = None
    timezone: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None

    @field_validator('timezone')
    @classmethod
    def _check_timezone(cls, value: str | None) -> str | None:
        return value if value is None else _validate_timezone(value)

    @model_validator(mode='after')
    def forbid_null_for_required(self) -> 'LocationUpdate':
        # address/phone/instagram/часи можна очистити (null), решта обовʼязкова
        for field in ('name', 'timezone', 'is_active'):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f'Поле {field} не може бути null')
        return self


class LocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: str | None
    phone: str | None
    instagram: str | None
    opening_time: time | None
    closing_time: time | None
    timezone: str
    is_active: bool
