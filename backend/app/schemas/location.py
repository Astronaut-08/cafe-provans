from pydantic import BaseModel, field_validator
from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

class Location(BaseModel):
    id: int
    name: str
    address: str | None = None
    phone: str | None = None
    instagram: str | None = None
    opening_time: time | None = None
    closing_time: time | None = None
    timezone: str
    is_active: bool = True

    @field_validator('timezone')
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError:
            raise ValueError(f'Невірний часовий пояс: {v}')
        return v