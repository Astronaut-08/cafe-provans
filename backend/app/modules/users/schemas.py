"""Схеми персоналу. Ролі: admin (усе), waiter (замовлення, доступність страв), chef (лише статуси).
`password_hash` у відповідь не потрапляє ніколи: UserRead його просто не містить.
"""
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.db.enums import UserRole


def _normalize_login(value: str) -> str:
    # БД вимагає login = lower(login); нормалізуємо тут, щоб "Anna" і "anna" були одним логіном
    value = value.lower()
    if any(ch.isspace() for ch in value):
        raise ValueError('Логін не може містити пробіли')
    return value


Login = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=50),
    AfterValidator(_normalize_login),
]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=70)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    login: Login
    password: str = Field(min_length=8, max_length=128)
    full_name: FullName
    phone: Phone | None = None
    role: UserRole
    location_id: int | None = None  # адмін може не належати конкретній локації


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    full_name: FullName | None = None
    phone: Phone | None = None
    role: UserRole | None = None
    location_id: int | None = None
    is_active: bool | None = None

    @model_validator(mode='after')
    def forbid_null_for_required(self) -> 'UserUpdate':
        for field in ('full_name', 'role', 'is_active'):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f'Поле {field} не може бути null')
        return self


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    full_name: str
    phone: str | None
    role: UserRole
    location_id: int | None
    is_active: bool
    created_at: datetime
