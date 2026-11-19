"""Схеми персоналу. Ролі: admin (усе), waiter (замовлення, доступність страв), chef (лише статуси).
`password_hash` у відповідь не потрапляє ніколи: UserRead його просто не містить.
Службових полів входу (token_version, лічильник спроб) у відповідях теж немає.
"""
import re
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


_EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _normalize_email(value: str) -> str:
    # БД вимагає email = lower(email). Повну перевірку адреси робить лише справжній лист, тут відсікаємо очевидне сміття
    value = value.lower()
    if not _EMAIL.match(value):
        raise ValueError('Некоректний email')
    return value


def _not_blank(value: str) -> str:
    # пароль не обрізаємо (пробіли можуть бути його частиною), але з самих пробілів він бути не може
    if not value.strip():
        raise ValueError('Пароль не може складатися лише з пробілів')
    return value


Login = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=50),
    AfterValidator(_normalize_login),
]
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254), AfterValidator(_normalize_email)]
# Єдина вимога до нового пароля для всіх місць: створення працівника, зміна, відновлення, тимчасовий
NewPassword = Annotated[str, Field(min_length=8, max_length=128), AfterValidator(_not_blank)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=70)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    login: Login
    password: NewPassword  # початковий: працівник замінить його власним при першому вході
    full_name: FullName
    phone: Phone | None = None
    email: Email | None = None  # для адміна обов'язковий (перевіряє сервіс): на нього йде код відновлення пароля
    role: UserRole
    location_id: int | None = None  # адмін може не належати конкретній локації


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    full_name: FullName | None = None
    phone: Phone | None = None
    email: Email | None = None
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
    email: str | None
    role: UserRole
    location_id: int | None
    is_active: bool
    must_change_password: bool
    locked_until: datetime | None  # до коли заблоковано вхід після невдалих спроб (None: не заблоковано)
    created_at: datetime


class TemporaryPassword(BaseModel):
    """Відповідь на скидання пароля адміністратором. Пароль показується ОДИН раз і ніде не зберігається у
    відкритому вигляді: адміністратор передає його працівнику, а той при першому вході замінює."""
    temporary_password: str
