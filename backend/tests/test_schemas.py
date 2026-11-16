"""Схеми, які ще не підключені до роутерів (Фаза 3-4): перевіряємо правила, що мають збігатися з БД."""
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.db.enums import UserRole
from app.modules.locations.schemas import LocationCreate, LocationUpdate
from app.modules.users.schemas import UserCreate, UserRead, UserUpdate

USER = dict(login='anna', password='longenough', full_name='Анна', role=UserRole.waiter)


def test_login_is_normalized_to_lowercase_like_db_check_requires():
    assert UserCreate(**{**USER, 'login': '  Anna.K  '}).login == 'anna.k'


@pytest.mark.parametrize('login', ['ab', 'an na', 'a' * 51, ''])
def test_bad_login_is_rejected(login):
    with pytest.raises(ValidationError):
        UserCreate(**{**USER, 'login': login})


def test_password_length_bounds():
    for password in ('short', 'x' * 129):
        with pytest.raises(ValidationError):
            UserCreate(**{**USER, 'password': password})


def test_unknown_role_is_rejected_and_old_roles_are_gone():
    for role in ('operator', 'manager', 'root'):
        with pytest.raises(ValidationError):
            UserCreate(**{**USER, 'role': role})
    assert {r.value for r in UserRole} == {'admin', 'waiter', 'chef'}


def test_admin_may_have_no_location():
    assert UserCreate(**{**USER, 'role': UserRole.admin}).location_id is None


def test_user_read_never_exposes_password_material():
    assert not {'password', 'password_hash'} & set(UserRead.model_fields)
    row = type('Row', (), dict(
        id=1, login='anna', full_name='Анна', phone=None, role=UserRole.chef,
        location_id=None, is_active=True, created_at=datetime(2026, 1, 1), password_hash='SECRET',
    ))()
    assert 'SECRET' not in UserRead.model_validate(row).model_dump_json()


def test_user_update_cannot_null_required_fields_but_can_clear_phone():
    for field in ('full_name', 'role', 'is_active'):
        with pytest.raises(ValidationError):
            UserUpdate(**{field: None})
    assert UserUpdate(phone=None).phone is None


def test_location_defaults_and_timezone_validation():
    assert LocationCreate(name='Provans').timezone == 'Europe/Kyiv'
    with pytest.raises(ValidationError, match='часовий пояс'):
        LocationCreate(name='Provans', timezone='Mars/Olympus')
    with pytest.raises(ValidationError, match='часовий пояс'):
        LocationUpdate(timezone='Mars/Olympus')


def test_location_update_nulls():
    assert LocationUpdate(address=None).address is None  # необов'язкове поле можна очистити
    with pytest.raises(ValidationError):
        LocationUpdate(name=None)
