"""Команда створення першого адміна й аварійного скидання його пароля."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import create_admin as cli
from app.db.create_admin import CreateAdminError, create_admin, reset_admin_password
from app.db.enums import UserRole
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import User
from tests.factories import make_user

LOGIN = '/api/v1/auth/login'
ARGS = dict(login='Admin', password='Secret-pass-1', full_name='Іван Петренко', email='Admin@Example.com')


async def test_creates_an_admin_who_can_log_in_through_the_api(client, db_session):
    user = await create_admin(db_session, **ARGS)
    assert (user.login, user.role, user.email, user.is_active) == ('admin', UserRole.admin, 'admin@example.com', True)
    # хеш сумісний з перевіркою при вході, і перший адмін не змушений міняти пароль, який щойно вигадав
    r = await client.post(LOGIN, json={'login': 'admin', 'password': 'Secret-pass-1'})
    assert r.status_code == 200
    assert r.json()['must_change_password'] is False and r.json()['user']['role'] == 'admin'


async def test_password_is_not_stored_in_clear(db_session):
    user = await create_admin(db_session, **ARGS)
    assert user.password_hash.startswith('scrypt$') and 'Secret-pass-1' not in user.password_hash


@pytest.mark.parametrize('override', [
    {'password': 'short'}, {'password': ' ' * 12}, {'login': 'ab'}, {'login': 'two words'},
    {'email': 'nope'}, {'full_name': '  '},
])
async def test_applies_the_same_validation_as_the_api(db_session, override):
    with pytest.raises(CreateAdminError):
        await create_admin(db_session, **{**ARGS, **override})
    assert (await db_session.scalars(select(User))).all() == []


async def test_duplicate_login_or_email_is_a_readable_error(db_session):
    await create_admin(db_session, **ARGS)
    with pytest.raises(CreateAdminError, match='уже використовується'):
        await create_admin(db_session, **ARGS)
    with pytest.raises(CreateAdminError, match='уже використовується'):
        await create_admin(db_session, **{**ARGS, 'login': 'other'})   # той самий email
    # сесія після помилки придатна до роботи
    await create_admin(db_session, **{**ARGS, 'login': 'other', 'email': 'other@example.com'})


async def test_emergency_reset_changes_password_unlocks_and_ends_sessions(client, db_session):
    user = await make_user(
        db_session, 'boss', role=UserRole.admin, email='b@example.com',
        locked_until=datetime.now(UTC) + timedelta(minutes=10), failed_attempts=2,
    )
    db_session.add(RefreshToken(
        user_id=user.id, family_id=__import__('uuid').uuid4(), token_hash='h' * 64,
        created_at=datetime.now(UTC), expires_at=datetime.now(UTC) + timedelta(days=1),
    ))
    await db_session.commit()

    await reset_admin_password(db_session, login=' BOSS ', password='Emergency-pass-7')
    await db_session.refresh(user)
    assert user.locked_until is None and user.failed_login_attempts == 0 and user.token_version == 1
    assert user.must_change_password is False
    assert all(t.revoked_at is not None for t in (await db_session.scalars(select(RefreshToken))).all())
    assert (await client.post(LOGIN, json={'login': 'boss', 'password': 'Emergency-pass-7'})).status_code == 200


async def test_emergency_reset_only_for_existing_admins(db_session):
    await make_user(db_session, 'waiter1', role=UserRole.waiter)
    for login in ('waiter1', 'nobody'):
        with pytest.raises(CreateAdminError, match='Адміністратора з таким логіном немає'):
            await reset_admin_password(db_session, login=login, password='Emergency-pass-7')


async def test_emergency_reset_applies_the_password_policy(db_session):
    await make_user(db_session, 'boss', role=UserRole.admin, email='b@example.com')
    with pytest.raises(CreateAdminError, match='Пароль'):
        await reset_admin_password(db_session, login='boss', password='short')


def test_password_comes_from_the_environment_when_set(monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'From-env-pass-1')
    monkeypatch.setattr(cli.getpass, 'getpass', lambda *_: pytest.fail('не повинен питати в терміналі'))
    assert cli._ask_password() == 'From-env-pass-1'


def test_interactive_password_must_be_repeated_identically(monkeypatch):
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    answers = iter(['Secret-pass-1', 'Secret-pass-2'])
    monkeypatch.setattr(cli.getpass, 'getpass', lambda *_: next(answers))
    with pytest.raises(CreateAdminError, match='не збігаються'):
        cli._ask_password()
    answers = iter(['Secret-pass-1', 'Secret-pass-1'])
    assert cli._ask_password() == 'Secret-pass-1'
