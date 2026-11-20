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


def _validate_map_url(value: str | None) -> str | None:
    # посилання йде в <iframe src>: javascript:, data: та http (змішаний вміст) не приймаємо
    if value is not None and not value.startswith('https://'):
        raise ValueError('Посилання на карту має починатися з https://')
    return value


class LocationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: Name
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=200)
    delivery_map_url: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=20)
    instagram: str | None = Field(default=None, max_length=150)
    opening_time: time | None = None
    closing_time: time | None = None
    timezone: str = Field(default='Europe/Kyiv', max_length=50)
    is_active: bool = True

    _check_timezone = field_validator('timezone')(_validate_timezone)
    _check_map_url = field_validator('delivery_map_url')(_validate_map_url)


class LocationUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: Name | None = None
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=200)
    delivery_map_url: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=20)
    instagram: str | None = Field(default=None, max_length=150)
    opening_time: time | None = None
    closing_time: time | None = None
    timezone: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None

    _check_map_url = field_validator('delivery_map_url')(_validate_map_url)

    @field_validator('timezone')
    @classmethod
    def _check_timezone(cls, value: str | None) -> str | None:
        return value if value is None else _validate_timezone(value)

    @model_validator(mode='after')
    def forbid_null_for_required(self) -> 'LocationUpdate':
        # city/address/карту/phone/instagram/часи можна очистити (null), решта обовʼязкова
        for field in ('name', 'timezone', 'is_active'):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f'Поле {field} не може бути null')
        return self


class LocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    city: str | None
    address: str | None
    delivery_map_url: str | None
    phone: str | None
    instagram: str | None
    image_url: str | None
    opening_time: time | None
    closing_time: time | None
    timezone: str
    is_active: bool


class LocationPublic(BaseModel):
    """Що бачить гість на сайті. Службових полів (is_active) немає: неактивні заклади не віддаються взагалі."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    city: str | None      # усі заклади мережі називаються однаково: відрізняються містом і адресою
    address: str | None
    phone: str | None
    instagram: str | None
    image_url: str | None
    opening_time: time | None
    closing_time: time | None
    timezone: str
    # Зараз відкрито? None, якщо години роботи не задані (невідомо, а не «зачинено»)
    is_open_now: bool | None = None
