"""Вхід, токени, оновлення, вихід, зміна пароля (HTTP зверху вниз, реальна БД, реальні токени)."""
import base64
import hashlib
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.config import settings
from app.core.security import _derive, needs_rehash
from app.db.enums import UserRole
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import User
from app.modules.auth import service as auth_service
from tests.factories import PASSWORD, bearer, make_user

LOGIN = '/api/v1/auth/login'
REFRESH = '/api/v1/auth/refresh'
LOGOUT = '/api/v1/auth/logout'
ME = '/api/v1/auth/me'
CHANGE = '/api/v1/auth/change-password'
ADMIN_ONLY = '/api/v1/users'   # будь-який захищений ендпоінт: для перевірки токена й прапорця зміни пароля

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
ACCESS_TTL = timedelta(minutes=settings.access_token_ttl_minutes)
REFRESH_TTL = timedelta(days=settings.refresh_token_ttl_days)


@pytest.fixture(autouse=True)
def fixed_time(set_now):
    set_now(T0)


async def sign_in(client, login='anna', password=PASSWORD):
    r = await client.post(LOGIN, json={'login': login, 'password': password})
    assert r.status_code == 200, r.text
    return r.json()


def auth(tokens: dict) -> dict:
    return {'Authorization': f'Bearer {tokens["access_token"]}'}


async def reload(db, user: User) -> User:
    await db.refresh(user)
    return user


async def error_of(response, status: int) -> dict:
    assert response.status_code == status, response.text
    return response.json()['error']


# ---------- вхід ----------

async def test_login_returns_tokens_and_user_without_secrets(client, db_session):
    await make_user(db_session, 'anna', role=UserRole.waiter)
    r = await client.post(LOGIN, json={'login': 'anna', 'password': PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body['token_type'] == 'bearer'
    assert body['expires_in'] == int(ACCESS_TTL.total_seconds())
    assert body['must_change_password'] is False
    assert body['user']['login'] == 'anna' and body['user']['role'] == 'waiter'
    assert len(body['refresh_token']) >= 64
    # жодних слідів пароля чи службових полів
    assert not {'password', 'password_hash', 'token_version', 'failed_login_attempts'} & set(body['user'])
    assert 'scrypt' not in r.text


async def test_login_is_case_insensitive_and_trims(client, db_session):
    await make_user(db_session, 'anna')
    r = await client.post(LOGIN, json={'login': '  ANNA ', 'password': PASSWORD})
    assert r.status_code == 200


async def test_access_token_works_right_after_login(client, db_session):
    await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    r = await client.get(ME, headers=auth(tokens))
    assert r.status_code == 200 and r.json()['login'] == 'anna'


async def test_refresh_token_is_stored_only_as_hash(client, db_session):
    await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    stored = (await db_session.scalars(select(RefreshToken))).one()
    assert stored.token_hash == hashlib.sha256(tokens['refresh_token'].encode()).hexdigest()
    assert tokens['refresh_token'] not in (stored.token_hash, str(stored.family_id))
    assert stored.expires_at == T0 + REFRESH_TTL and stored.created_at == T0 and stored.revoked_at is None


async def test_wrong_password_and_unknown_login_look_identical(client, db_session):
    await make_user(db_session, 'anna')
    wrong = await client.post(LOGIN, json={'login': 'anna', 'password': 'not-the-password'})
    unknown = await client.post(LOGIN, json={'login': 'nobody', 'password': 'not-the-password'})
    assert wrong.status_code == unknown.status_code == 401
    a, b = wrong.json()['error'], unknown.json()['error']
    assert a['code'] == b['code'] == 'invalid_credentials'
    assert a['message'] == b['message']


async def test_unknown_login_still_spends_time_hashing_a_password(client, db_session, monkeypatch):
    # без цього відповідь на неіснуючий логін приходила б миттєво, і логіни можна було б вгадати за часом
    calls = []
    real = auth_service.verify_password
    monkeypatch.setattr(auth_service, 'verify_password', lambda pw, h: calls.append(h) or real(pw, h))
    await client.post(LOGIN, json={'login': 'nobody', 'password': 'whatever1'})
    assert len(calls) == 1 and calls[0].startswith('scrypt$')


async def test_login_requires_both_fields_and_rejects_extras(client):
    assert (await client.post(LOGIN, json={'login': 'anna'})).status_code == 422
    assert (await client.post(LOGIN, json={'password': 'x'})).status_code == 422
    assert (await client.post(LOGIN, json={'login': 'a', 'password': 'x', 'role': 'admin'})).status_code == 422
    assert (await client.post(LOGIN, json={'login': '', 'password': 'x'})).status_code == 422


async def test_validation_error_does_not_echo_the_password(client):
    r = await client.post(LOGIN, json={'login': 'anna', 'password': 'p' * 500})
    assert r.status_code == 422 and 'ppppp' not in r.text


async def test_short_login_is_just_wrong_credentials_not_a_validation_error(client):
    r = await client.post(LOGIN, json={'login': 'ab', 'password': 'whatever1'})
    assert (await error_of(r, 401))['code'] == 'invalid_credentials'


async def test_disabled_account_with_right_password_gets_a_clear_403(client, db_session):
    await make_user(db_session, 'anna', active=False)
    r = await client.post(LOGIN, json={'login': 'anna', 'password': PASSWORD})
    assert (await error_of(r, 403))['code'] == 'account_disabled'
    # а без вірного пароля нічого не розкриваємо
    r = await client.post(LOGIN, json={'login': 'anna', 'password': 'wrong-password'})
    assert (await error_of(r, 401))['code'] == 'invalid_credentials'
    assert not (await db_session.scalars(select(RefreshToken))).all()


async def test_login_flags_temporary_password(client, db_session):
    await make_user(db_session, 'anna', must_change=True)
    assert (await sign_in(client))['must_change_password'] is True


async def test_login_rehashes_an_old_password_hash(client, db_session):
    # хеш із застарілими параметрами (N=2^14) при вдалому вході замінюється поточним
    salt = b'0123456789abcdef'
    old = 'scrypt$16384$8$2$%s$%s' % (
        base64.b64encode(salt).decode(), base64.b64encode(_derive(PASSWORD, salt, 2 ** 14, 8, 2)).decode(),
    )
    user = await make_user(db_session, 'anna')
    user.password_hash = old
    await db_session.commit()
    assert needs_rehash(old)

    await sign_in(client)
    await reload(db_session, user)
    assert user.password_hash != old and not needs_rehash(user.password_hash)
    await sign_in(client)  # новий хеш теж пускає


async def test_login_purges_only_expired_refresh_tokens_of_that_user(client, db_session, set_now):
    anna = await make_user(db_session, 'anna')
    bob = await make_user(db_session, 'bobby')
    first = await sign_in(client, 'anna')           # цей токен прострочиться
    await sign_in(client, 'bobby')                  # токен іншого користувача не чіпаємо
    await client.post(LOGOUT, json={'refresh_token': first['refresh_token']})
    assert len((await db_session.scalars(select(RefreshToken))).all()) == 2   # токен Анни, токен Боба

    set_now(T0 + REFRESH_TTL + timedelta(seconds=1))
    await sign_in(client, 'anna')
    owners = sorted(t.user_id for t in (await db_session.scalars(select(RefreshToken))).all())
    # токени Анни: прострочений видалено, лишився свіжий. Токен Боба, хоч теж прострочений, не чіпали:
    # прибирання стосується лише того, хто входить
    assert owners == sorted([anna.id, bob.id])


# ---------- захист від підбору пароля ----------

async def attempt(client, password='wrong-password', login='anna'):
    return await client.post(LOGIN, json={'login': login, 'password': password})


async def test_fifth_failed_attempt_locks_the_account(client, db_session):
    user = await make_user(db_session, 'anna')
    for _ in range(4):
        assert (await attempt(client)).status_code == 401
    r = await attempt(client)  # п'ята
    err = await error_of(r, 429)
    assert err['code'] == 'account_locked'
    assert err['details']['retry_after_seconds'] == 15 * 60
    assert r.headers['Retry-After'] == str(15 * 60)
    assert '15 хв' in err['message']
    await reload(db_session, user)
    assert user.locked_until == T0 + timedelta(minutes=15) and user.failed_login_attempts == 0


async def test_failed_attempts_are_really_saved(client, db_session):
    # помилка відкочує незакомічене: лічильник має зберігатися ДО відповіді з помилкою
    user = await make_user(db_session, 'anna')
    for expected in (1, 2, 3):
        await attempt(client)
        await reload(db_session, user)
        assert user.failed_login_attempts == expected


async def test_locked_account_rejects_even_the_correct_password(client, db_session):
    await make_user(db_session, 'anna', locked_until=T0 + timedelta(minutes=10))
    r = await client.post(LOGIN, json={'login': 'anna', 'password': PASSWORD})
    err = await error_of(r, 429)
    assert err['details']['retry_after_seconds'] == 600
    assert '10 хв' in err['message']


async def test_lock_does_not_spend_hashing_time_or_count_attempts(client, db_session, monkeypatch):
    user = await make_user(db_session, 'anna', locked_until=T0 + timedelta(minutes=10))
    monkeypatch.setattr(auth_service, 'verify_password', lambda *a: pytest.fail('пароль перевірявся під час блокування'))
    await attempt(client)
    await reload(db_session, user)
    assert user.failed_login_attempts == 0


async def test_lock_expires_and_counter_starts_from_zero(client, db_session, set_now):
    user = await make_user(db_session, 'anna')
    for _ in range(5):
        await attempt(client)
    set_now(T0 + timedelta(minutes=15, seconds=-1))
    assert (await attempt(client, PASSWORD)).status_code == 429   # ще заблоковано
    set_now(T0 + timedelta(minutes=15))
    for _ in range(4):                                             # після блокування знову 4 допустимі промахи
        assert (await attempt(client)).status_code == 401
    r = await attempt(client, PASSWORD)
    assert r.status_code == 200
    await reload(db_session, user)
    assert user.locked_until is None and user.failed_login_attempts == 0


async def test_successful_login_resets_the_counter(client, db_session):
    user = await make_user(db_session, 'anna')
    for _ in range(4):
        await attempt(client)
    assert (await attempt(client, PASSWORD)).status_code == 200
    await reload(db_session, user)
    assert user.failed_login_attempts == 0
    for _ in range(4):                       # без скидання п'ятий промах тут уже заблокував би
        assert (await attempt(client)).status_code == 401


async def test_one_users_failures_do_not_lock_another(client, db_session):
    await make_user(db_session, 'anna')
    await make_user(db_session, 'bobby')
    for _ in range(5):
        await attempt(client, login='anna')
    assert (await attempt(client, PASSWORD, login='bobby')).status_code == 200


# ---------- перевірка access-токена ----------

async def test_no_token_gives_not_authenticated_with_bearer_challenge(client):
    r = await client.get(ME)
    assert (await error_of(r, 401))['code'] == 'not_authenticated'
    assert r.headers['WWW-Authenticate'] == 'Bearer'


async def test_other_authorization_scheme_is_not_authenticated(client):
    r = await client.get(ME, headers={'Authorization': 'Basic YW5uYTpwYXNz'})
    assert (await error_of(r, 401))['code'] == 'not_authenticated'


@pytest.mark.parametrize('token', ['garbage', 'a.b.c', ''])
async def test_garbage_token_is_invalid(client, token):
    r = await client.get(ME, headers={'Authorization': f'Bearer {token}'})
    assert (await error_of(r, 401))['code'] in ('invalid_token', 'not_authenticated')


async def test_token_signed_with_another_key_is_invalid(client, db_session):
    user = await make_user(db_session, 'anna')
    payload = {'typ': 'access', 'sub': str(user.id), 'tv': 0, 'iat': int(T0.timestamp()), 'exp': int((T0 + ACCESS_TTL).timestamp())}
    forged = jwt.encode(payload, 'another-secret-another-secret-another-secret', algorithm='HS256')
    r = await client.get(ME, headers={'Authorization': f'Bearer {forged}'})
    assert (await error_of(r, 401))['code'] == 'invalid_token'


async def test_expired_token_says_so_and_boundary_is_exact(client, db_session, set_now):
    await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    set_now(T0 + ACCESS_TTL - timedelta(seconds=1))
    assert (await client.get(ME, headers=auth(tokens))).status_code == 200
    set_now(T0 + ACCESS_TTL)
    err = await error_of(await client.get(ME, headers=auth(tokens)), 401)
    assert err['code'] == 'token_expired'


async def test_token_of_unknown_user_is_invalid(client, db_session):
    user = await make_user(db_session, 'anna')
    headers = bearer(user, T0)
    await db_session.delete(user)
    await db_session.commit()
    assert (await error_of(await client.get(ME, headers=headers), 401))['code'] == 'invalid_token'


async def test_disabling_the_user_cuts_access_immediately(client, db_session):
    user = await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    user.is_active = False
    await db_session.commit()
    assert (await error_of(await client.get(ME, headers=auth(tokens)), 403))['code'] == 'account_disabled'


async def test_role_is_read_from_db_not_from_token(client, db_session):
    user = await make_user(db_session, 'anna', role=UserRole.waiter)
    tokens = await sign_in(client)
    assert (await error_of(await client.get(ADMIN_ONLY, headers=auth(tokens)), 403))['code'] == 'forbidden'
    user.role = UserRole.admin
    await db_session.commit()
    assert (await client.get(ADMIN_ONLY, headers=auth(tokens))).status_code == 200   # той самий токен


async def test_token_with_old_version_is_invalid(client, db_session):
    user = await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    user.token_version = 1
    await db_session.commit()
    assert (await error_of(await client.get(ME, headers=auth(tokens)), 401))['code'] == 'invalid_token'


async def test_temporary_password_blocks_everything_except_me_and_change_password(client, db_session):
    await make_user(db_session, 'anna', role=UserRole.admin, must_change=True)
    tokens = await sign_in(client)
    assert (await client.get(ME, headers=auth(tokens))).status_code == 200
    err = await error_of(await client.get(ADMIN_ONLY, headers=auth(tokens)), 403)
    assert err['code'] == 'password_change_required'
    r = await client.post(CHANGE, headers=auth(tokens), json={'current_password': PASSWORD, 'new_password': 'Brand-new-1'})
    assert r.status_code == 200 and r.json()['must_change_password'] is False
    assert (await client.get(ADMIN_ONLY, headers=auth(r.json()))).status_code == 200


# ---------- оновлення токена ----------

async def test_refresh_gives_a_new_working_pair(client, db_session, set_now):
    await make_user(db_session, 'anna')
    first = await sign_in(client)
    set_now(T0 + timedelta(minutes=29))
    r = await client.post(REFRESH, json={'refresh_token': first['refresh_token']})
    assert r.status_code == 200
    second = r.json()
    assert second['refresh_token'] != first['refresh_token'] and second['access_token'] != first['access_token']
    assert second['user']['login'] == 'anna'
    # новий access живе від моменту оновлення, а не від першого входу
    set_now(T0 + timedelta(minutes=29) + ACCESS_TTL - timedelta(seconds=1))
    assert (await client.get(ME, headers=auth(second))).status_code == 200


async def test_refresh_rotates_the_token_and_keeps_the_family(client, db_session):
    await make_user(db_session, 'anna')
    first = await sign_in(client)
    await client.post(REFRESH, json={'refresh_token': first['refresh_token']})
    rows = (await db_session.scalars(select(RefreshToken).order_by(RefreshToken.id))).all()
    assert len(rows) == 2
    assert rows[0].revoked_at == T0 and rows[1].revoked_at is None
    assert rows[0].family_id == rows[1].family_id


async def test_reusing_a_rotated_refresh_token_revokes_the_whole_chain(client, db_session):
    await make_user(db_session, 'anna')
    first = await sign_in(client)
    second = (await client.post(REFRESH, json={'refresh_token': first['refresh_token']})).json()
    # старий токен прийшов знову: його вкрали або використали двічі
    r = await client.post(REFRESH, json={'refresh_token': first['refresh_token']})
    assert (await error_of(r, 401))['code'] == 'invalid_refresh_token'
    # і новий токен ланцюжка теж більше не діє
    r = await client.post(REFRESH, json={'refresh_token': second['refresh_token']})
    assert (await error_of(r, 401))['code'] == 'invalid_refresh_token'
    assert all(t.revoked_at is not None for t in (await db_session.scalars(select(RefreshToken))).all())


async def test_reuse_in_one_session_does_not_touch_another_login(client, db_session):
    await make_user(db_session, 'anna')
    phone = await sign_in(client)
    laptop = await sign_in(client)
    new_phone = (await client.post(REFRESH, json={'refresh_token': phone['refresh_token']})).json()
    await client.post(REFRESH, json={'refresh_token': phone['refresh_token']})     # повтор на телефоні
    assert (await client.post(REFRESH, json={'refresh_token': new_phone['refresh_token']})).status_code == 401
    assert (await client.post(REFRESH, json={'refresh_token': laptop['refresh_token']})).status_code == 200


async def test_unknown_refresh_token_is_rejected(client, db_session):
    await make_user(db_session, 'anna')
    r = await client.post(REFRESH, json={'refresh_token': 'x' * 64})
    assert (await error_of(r, 401))['code'] == 'invalid_refresh_token'


async def test_refresh_token_expires_exactly_at_its_deadline(client, db_session, set_now):
    await make_user(db_session, 'anna')
    just_before = await sign_in(client)
    at_deadline = await sign_in(client)
    set_now(T0 + REFRESH_TTL - timedelta(seconds=1))
    assert (await client.post(REFRESH, json={'refresh_token': just_before['refresh_token']})).status_code == 200
    set_now(T0 + REFRESH_TTL)
    err = await error_of(await client.post(REFRESH, json={'refresh_token': at_deadline['refresh_token']}), 401)
    assert err['code'] == 'invalid_refresh_token'


async def test_refresh_for_disabled_user_is_forbidden(client, db_session):
    user = await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    user.is_active = False
    await db_session.commit()
    r = await client.post(REFRESH, json={'refresh_token': tokens['refresh_token']})
    assert (await error_of(r, 403))['code'] == 'account_disabled'


async def test_refresh_validates_body(client):
    assert (await client.post(REFRESH, json={})).status_code == 422
    assert (await client.post(REFRESH, json={'refresh_token': ''})).status_code == 422
    assert (await client.post(REFRESH, json={'refresh_token': 'x' * 201})).status_code == 422


async def test_refresh_does_not_accept_an_access_token(client, db_session):
    await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    r = await client.post(REFRESH, json={'refresh_token': tokens['access_token']})
    assert r.status_code == 401


# ---------- вихід ----------

async def test_logout_ends_the_session_including_rotated_tokens(client, db_session):
    await make_user(db_session, 'anna')
    first = await sign_in(client)
    second = (await client.post(REFRESH, json={'refresh_token': first['refresh_token']})).json()
    r = await client.post(LOGOUT, json={'refresh_token': second['refresh_token']})
    assert r.status_code == 204 and r.content == b''
    assert (await client.post(REFRESH, json={'refresh_token': second['refresh_token']})).status_code == 401
    assert all(t.revoked_at is not None for t in (await db_session.scalars(select(RefreshToken))).all())


async def test_logout_with_a_stale_token_still_ends_the_whole_session(client, db_session):
    # старий (вже замінений) токен міг потрапити до чужих рук: вихід із ним не має лишати живим новий токен сесії
    await make_user(db_session, 'anna')
    first = await sign_in(client)
    second = (await client.post(REFRESH, json={'refresh_token': first['refresh_token']})).json()
    assert (await client.post(LOGOUT, json={'refresh_token': first['refresh_token']})).status_code == 204
    assert (await client.post(REFRESH, json={'refresh_token': second['refresh_token']})).status_code == 401


async def test_logout_ends_only_this_session(client, db_session):
    await make_user(db_session, 'anna')
    phone = await sign_in(client)
    laptop = await sign_in(client)
    await client.post(LOGOUT, json={'refresh_token': phone['refresh_token']})
    assert (await client.post(REFRESH, json={'refresh_token': phone['refresh_token']})).status_code == 401
    assert (await client.post(REFRESH, json={'refresh_token': laptop['refresh_token']})).status_code == 200


async def test_logout_is_idempotent_and_does_not_reveal_unknown_tokens(client, db_session):
    await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    assert (await client.post(LOGOUT, json={'refresh_token': 'x' * 64})).status_code == 204
    assert (await client.post(LOGOUT, json={'refresh_token': tokens['refresh_token']})).status_code == 204
    assert (await client.post(LOGOUT, json={'refresh_token': tokens['refresh_token']})).status_code == 204


# ---------- зміна пароля ----------

async def test_change_password_switches_the_password_and_all_sessions(client, db_session):
    user = await make_user(db_session, 'anna')
    phone = await sign_in(client)
    laptop = await sign_in(client)
    r = await client.post(CHANGE, headers=auth(laptop), json={'current_password': PASSWORD, 'new_password': 'Brand-new-1'})
    assert r.status_code == 200
    fresh = r.json()
    # новий пароль працює, старий ні
    assert (await attempt(client, 'Brand-new-1')).status_code == 200
    assert (await error_of(await attempt(client, PASSWORD), 401))['code'] == 'invalid_credentials'
    # усі раніше видані токени мертві, зокрема того, хто міняв
    for old in (phone, laptop):
        assert (await client.get(ME, headers=auth(old))).status_code == 401
        assert (await client.post(REFRESH, json={'refresh_token': old['refresh_token']})).status_code == 401
    # а пара, видана у відповіді, працює
    assert (await client.get(ME, headers=auth(fresh))).status_code == 200
    assert (await client.post(REFRESH, json={'refresh_token': fresh['refresh_token']})).status_code == 200
    await reload(db_session, user)
    assert user.token_version == 1 and user.must_change_password is False


async def test_change_password_with_wrong_current_password(client, db_session):
    user = await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    r = await client.post(CHANGE, headers=auth(tokens), json={'current_password': 'nope-nope', 'new_password': 'Brand-new-1'})
    assert (await error_of(r, 422))['code'] == 'invalid_current_password'
    await reload(db_session, user)
    assert user.failed_login_attempts == 1
    assert (await attempt(client, PASSWORD)).status_code == 200   # пароль не змінився


async def test_guessing_the_current_password_with_a_stolen_token_gets_locked(client, db_session):
    await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    body = {'current_password': 'nope-nope', 'new_password': 'Brand-new-1'}
    for _ in range(4):
        assert (await client.post(CHANGE, headers=auth(tokens), json=body)).status_code == 422
    assert (await error_of(await client.post(CHANGE, headers=auth(tokens), json=body), 429))['code'] == 'account_locked'
    # навіть правильний пароль у заблокованому акаунті не приймається
    r = await client.post(CHANGE, headers=auth(tokens), json={'current_password': PASSWORD, 'new_password': 'Brand-new-1'})
    assert r.status_code == 429


async def test_new_password_must_differ_from_current(client, db_session):
    await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    r = await client.post(CHANGE, headers=auth(tokens), json={'current_password': PASSWORD, 'new_password': PASSWORD})
    assert (await error_of(r, 422))['code'] == 'same_password'


@pytest.mark.parametrize('new_password', ['q7!zK', 'x' * 129, '        ', ''])
async def test_new_password_must_meet_the_policy(client, db_session, new_password):
    await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    r = await client.post(CHANGE, headers=auth(tokens), json={'current_password': PASSWORD, 'new_password': new_password})
    err = await error_of(r, 422)
    assert err['code'] == 'validation_error'
    assert new_password.strip() == '' or new_password not in r.text   # введене значення не повторюється у відповіді


async def test_change_password_requires_login(client):
    r = await client.post(CHANGE, json={'current_password': 'x', 'new_password': 'Brand-new-1'})
    assert r.status_code == 401


async def test_change_password_stores_a_hash_not_the_password(client, db_session):
    user = await make_user(db_session, 'anna')
    tokens = await sign_in(client)
    await client.post(CHANGE, headers=auth(tokens), json={'current_password': PASSWORD, 'new_password': 'Brand-new-1'})
    await reload(db_session, user)
    assert user.password_hash.startswith('scrypt$') and 'Brand-new-1' not in user.password_hash
