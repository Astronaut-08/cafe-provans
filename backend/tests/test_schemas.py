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
        id=1, login='anna', full_name='Анна', phone=None, email=None, role=UserRole.chef,
        location_id=None, is_active=True, must_change_password=False, locked_until=None,
        created_at=datetime(2026, 1, 1), password_hash='SECRET', token_version=7,
    ))()
    dumped = UserRead.model_validate(row).model_dump_json()
    assert 'SECRET' not in dumped
    # службові поля входу теж не віддаємо
    assert not {'token_version', 'failed_login_attempts'} & set(UserRead.model_fields)


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


def test_location_city_and_map_are_optional_and_clearable():
    created = LocationCreate(name='Provans')
    assert created.city is None and created.delivery_map_url is None
    assert LocationCreate(name='Provans', city='Болехів').city == 'Болехів'
    update = LocationUpdate(city=None, delivery_map_url=None)
    assert update.city is None and update.delivery_map_url is None   # місто й карту можна прибрати


@pytest.mark.parametrize('url', [
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'http://www.google.com/maps/d/embed?mid=x',       # змішаний вміст на https-сайті
    '//www.google.com/maps/d/embed?mid=x',
    'www.google.com/maps/d/embed?mid=x',
])
def test_map_url_must_be_https_because_it_goes_into_an_iframe(url):
    with pytest.raises(ValidationError, match='https://'):
        LocationCreate(name='Provans', delivery_map_url=url)
    with pytest.raises(ValidationError, match='https://'):
        LocationUpdate(delivery_map_url=url)


def test_map_url_https_is_accepted_and_has_a_length_limit():
    ok = 'https://www.google.com/maps/d/embed?mid=18hNmLUbGNEeWuByxKwuwh4IIhX7Xh8M&ehbc=2E312F'
    assert LocationCreate(name='Provans', delivery_map_url=ok).delivery_map_url == ok
    with pytest.raises(ValidationError):
        LocationCreate(name='Provans', delivery_map_url='https://example.com/' + 'a' * 500)
