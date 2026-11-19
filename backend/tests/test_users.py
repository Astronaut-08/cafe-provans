"""Керування персоналом (/users): доступ, створення, зміна, вимкнення, скидання пароля, «останній адмін»."""
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.enums import UserRole
from app.db.models.refresh_token import RefreshToken
from app.modules.users.service import _TEMP_PASSWORD_ALPHABET, generate_temporary_password
from tests.factories import PASSWORD, bearer, make_location, make_user

URL = '/api/v1/users'
LOGIN = '/api/v1/auth/login'
ME = '/api/v1/auth/me'
REFRESH = '/api/v1/auth/refresh'
T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_time(set_now):
    set_now(T0)


@pytest.fixture
async def boss(db_session):
    return await make_user(db_session, 'boss', role=UserRole.admin, email='boss@example.com')


@pytest.fixture
def h(boss):
    return bearer(boss, T0)


NEW_USER = dict(login='olena', password='Initial-pass-1', full_name='Олена', role='waiter')


async def create(client, headers, **overrides) -> dict:
    r = await client.post(URL, headers=headers, json={**NEW_USER, **overrides})
    assert r.status_code == 201, r.text
    return r.json()


# ---------- доступ ----------

@pytest.mark.parametrize('method, path, body', [
    ('GET', URL, None), ('POST', URL, NEW_USER), ('GET', f'{URL}/1', None),
    ('PATCH', f'{URL}/1', {'full_name': 'X'}), ('POST', f'{URL}/1/reset-password', None),
])
async def test_closed_without_login(client, method, path, body):
    r = await client.request(method, path, json=body)
    assert r.status_code == 401 and r.json()['error']['code'] == 'not_authenticated'


@pytest.mark.parametrize('role', [UserRole.waiter, UserRole.chef])
@pytest.mark.parametrize('method, path, body', [
    ('GET', URL, None), ('POST', URL, NEW_USER), ('GET', f'{URL}/1', None),
    ('PATCH', f'{URL}/1', {'full_name': 'X'}), ('POST', f'{URL}/1/reset-password', None),
])
async def test_only_admin_may_manage_staff(client, db_session, role, method, path, body):
    staff = await make_user(db_session, 'staff1', role=role)
    r = await client.request(method, path, json=body, headers=bearer(staff, T0))
    assert r.status_code == 403 and r.json()['error']['code'] == 'forbidden'


# ---------- створення ----------

async def test_create_returns_the_user_without_any_password_material(client, h):
    data = await create(client, h, phone='+380501112233', email='Olena@Example.com')
    assert data['login'] == 'olena' and data['role'] == 'waiter' and data['is_active'] is True
    assert data['email'] == 'olena@example.com'           # нижній регістр
    assert data['must_change_password'] is True and data['locked_until'] is None
    assert not {'password', 'password_hash', 'token_version', 'failed_login_attempts'} & set(data)


async def test_created_employee_logs_in_with_initial_password_and_must_change_it(client, h):
    await create(client, h)
    r = await client.post(LOGIN, json={'login': 'olena', 'password': 'Initial-pass-1'})
    assert r.status_code == 200 and r.json()['must_change_password'] is True
    # доки не змінить, працювати з API не може
    token = {'Authorization': f'Bearer {r.json()["access_token"]}'}
    assert (await client.get('/api/v1/categories', headers=token)).status_code == 200   # публічне читання відкрите
    assert (await client.post('/api/v1/categories', json={'name': 'X'}, headers=token)).status_code in (403,)


async def test_password_is_stored_hashed(client, h, db_session):
    await create(client, h)
    from app.db.models.user import User
    user = (await db_session.scalars(select(User).where(User.login == 'olena'))).one()
    assert user.password_hash.startswith('scrypt$') and 'Initial-pass-1' not in user.password_hash


async def test_login_is_normalized_and_unique_case_insensitively(client, h):
    await create(client, h, login='  Olena ')
    r = await client.post(URL, headers=h, json={**NEW_USER, 'login': 'OLENA'})
    assert r.status_code == 409 and r.json()['error']['code'] == 'login_taken'


async def test_duplicate_phone_and_email_are_conflicts(client, h):
    await create(client, h, phone='+380501112233', email='a@example.com')
    r = await client.post(URL, headers=h, json={**NEW_USER, 'login': 'second', 'phone': '+380501112233'})
    assert (r.status_code, r.json()['error']['code']) == (409, 'phone_taken')
    r = await client.post(URL, headers=h, json={**NEW_USER, 'login': 'second', 'email': 'A@EXAMPLE.com'})
    assert (r.status_code, r.json()['error']['code']) == (409, 'email_taken')


async def test_conflict_does_not_leave_a_half_created_user(client, h):
    await create(client, h)
    await client.post(URL, headers=h, json=NEW_USER)
    assert len((await client.get(URL, headers=h)).json()) == 2   # boss + olena


async def test_admin_requires_an_email(client, h):
    r = await client.post(URL, headers=h, json={**NEW_USER, 'role': 'admin'})
    assert (r.status_code, r.json()['error']['code']) == (422, 'admin_email_required')
    ok = await create(client, h, login='second_boss', role='admin', email='b@example.com')
    assert ok['role'] == 'admin'


async def test_unknown_location_is_a_clear_error(client, h):
    r = await client.post(URL, headers=h, json={**NEW_USER, 'location_id': 999})
    assert (r.status_code, r.json()['error']['code']) == (422, 'location_not_found')


async def test_staff_can_be_bound_to_a_location(client, h, db_session):
    location = await make_location(db_session)
    assert (await create(client, h, location_id=location.id))['location_id'] == location.id


@pytest.mark.parametrize('patch', [
    {'login': 'ab'}, {'login': 'with space'}, {'password': 'short'}, {'password': ' ' * 10}, {'role': 'owner'},
    {'email': 'not-an-email'}, {'email': 'a b@example.com'}, {'full_name': ''}, {'is_active': False},
    {'must_change_password': False}, {'token_version': 5},
])
async def test_create_validation(client, h, patch):
    r = await client.post(URL, headers=h, json={**NEW_USER, **patch})
    assert r.status_code == 422 and r.json()['error']['code'] == 'validation_error'


# ---------- читання ----------

async def test_list_and_filters(client, h, db_session):
    loc = await make_location(db_session)
    await make_user(db_session, 'waiter1', role=UserRole.waiter, location=loc, full_name='Борис')
    await make_user(db_session, 'chef1', role=UserRole.chef, full_name='Анатолій')
    await make_user(db_session, 'waiter2', role=UserRole.waiter, active=False, full_name='Віра')

    def logins(r):
        return [u['login'] for u in r.json()]

    everyone = await client.get(URL, headers=h)
    assert sorted(logins(everyone)) == ['boss', 'chef1', 'waiter1', 'waiter2']
    assert logins(await client.get(URL, headers=h, params={'role': 'waiter'})) == ['waiter1', 'waiter2']
    assert logins(await client.get(URL, headers=h, params={'is_active': 'false'})) == ['waiter2']
    assert logins(await client.get(URL, headers=h, params={'location_id': loc.id})) == ['waiter1']
    assert logins(await client.get(URL, headers=h, params={'role': 'waiter', 'is_active': 'true'})) == ['waiter1']
    assert (await client.get(URL, headers=h, params={'role': 'cook'})).status_code == 422
    assert not {'password', 'password_hash', 'token_version'} & {key for user in everyone.json() for key in user}
    assert 'scrypt' not in everyone.text


async def test_get_one_404_and_invalid_id(client, h):
    created = await create(client, h)
    assert (await client.get(f'{URL}/{created["id"]}', headers=h)).json() == created
    assert (await client.get(f'{URL}/99999', headers=h)).status_code == 404
    assert (await client.get(f'{URL}/0', headers=h)).status_code == 422
    assert (await client.get(f'{URL}/99999999999', headers=h)).status_code == 422


# ---------- зміна ----------

async def test_update_fields(client, h, db_session):
    created = await create(client, h)
    loc = await make_location(db_session)
    r = await client.patch(f'{URL}/{created["id"]}', headers=h, json={
        'full_name': 'Олена Коваль', 'phone': '+380991112233', 'email': 'O@Example.com',
        'role': 'chef', 'location_id': loc.id,
    })
    assert r.status_code == 200
    data = r.json()
    assert (data['full_name'], data['phone'], data['email'], data['role'], data['location_id']) == (
        'Олена Коваль', '+380991112233', 'o@example.com', 'chef', loc.id)
    assert (await client.get(f'{URL}/{created["id"]}', headers=h)).json() == data


async def test_update_can_clear_optional_fields_but_not_required_ones(client, h):
    created = await create(client, h, phone='+380501112233', email='a@example.com')
    r = await client.patch(f'{URL}/{created["id"]}', headers=h, json={'phone': None, 'email': None})
    assert r.status_code == 200 and r.json()['phone'] is None and r.json()['email'] is None
    for field in ('full_name', 'role', 'is_active'):
        assert (await client.patch(f'{URL}/{created["id"]}', headers=h, json={field: None})).status_code == 422


@pytest.mark.parametrize('field', ['login', 'password', 'password_hash', 'must_change_password', 'token_version'])
async def test_update_cannot_touch_credentials(client, h, field):
    created = await create(client, h)
    r = await client.patch(f'{URL}/{created["id"]}', headers=h, json={field: 'whatever123'})
    assert r.status_code == 422


async def test_update_conflicts_and_404(client, h):
    a = await create(client, h, login='first', phone='+380501112233', email='a@example.com')
    b = await create(client, h, login='second')
    r = await client.patch(f'{URL}/{b["id"]}', headers=h, json={'phone': a['phone']})
    assert (r.status_code, r.json()['error']['code']) == (409, 'phone_taken')
    r = await client.patch(f'{URL}/{b["id"]}', headers=h, json={'email': 'A@example.com'})
    assert (r.status_code, r.json()['error']['code']) == (409, 'email_taken')
    r = await client.patch(f'{URL}/{b["id"]}', headers=h, json={'location_id': 999})
    assert (r.status_code, r.json()['error']['code']) == (422, 'location_not_found')
    assert (await client.patch(f'{URL}/99999', headers=h, json={'full_name': 'X'})).status_code == 404
    # зміна не пройшла, дані ті самі
    assert (await client.get(f'{URL}/{b["id"]}', headers=h)).json() == b


async def test_promoting_to_admin_requires_an_email_and_clearing_it_is_refused(client, h):
    created = await create(client, h)
    r = await client.patch(f'{URL}/{created["id"]}', headers=h, json={'role': 'admin'})
    assert (r.status_code, r.json()['error']['code']) == (422, 'admin_email_required')
    ok = await client.patch(f'{URL}/{created["id"]}', headers=h, json={'role': 'admin', 'email': 'x@example.com'})
    assert ok.status_code == 200
    r = await client.patch(f'{URL}/{created["id"]}', headers=h, json={'email': None})
    assert (r.status_code, r.json()['error']['code']) == (422, 'admin_email_required')


# ---------- вимкнення ----------

async def test_disabling_cuts_off_the_employee_at_once(client, h, db_session):
    await make_user(db_session, 'olena', role=UserRole.waiter)
    tokens = (await client.post(LOGIN, json={'login': 'olena', 'password': PASSWORD})).json()
    mine = {'Authorization': f'Bearer {tokens["access_token"]}'}
    uid = tokens['user']['id']

    r = await client.patch(f'{URL}/{uid}', headers=h, json={'is_active': False})
    assert r.status_code == 200 and r.json()['is_active'] is False
    # токен перестає діяти негайно, а не коли мине його термін
    assert (await client.get(ME, headers=mine)).status_code in (401, 403)
    assert (await client.post(REFRESH, json={'refresh_token': tokens['refresh_token']})).status_code in (401, 403)
    assert (await client.post(LOGIN, json={'login': 'olena', 'password': PASSWORD})).status_code == 403
    assert all(t.revoked_at == T0 for t in (await db_session.scalars(select(RefreshToken))).all())


async def test_reenabling_restores_login_but_not_old_tokens(client, h, db_session):
    await make_user(db_session, 'olena', role=UserRole.waiter)
    tokens = (await client.post(LOGIN, json={'login': 'olena', 'password': PASSWORD})).json()
    uid = tokens['user']['id']
    await client.patch(f'{URL}/{uid}', headers=h, json={'is_active': False})
    await client.patch(f'{URL}/{uid}', headers=h, json={'is_active': True})
    assert (await client.post(LOGIN, json={'login': 'olena', 'password': PASSWORD})).status_code == 200
    assert (await client.get(ME, headers={'Authorization': f'Bearer {tokens["access_token"]}'})).status_code == 401
    assert (await client.post(REFRESH, json={'refresh_token': tokens['refresh_token']})).status_code == 401


async def test_changing_a_role_does_not_log_the_employee_out(client, h, db_session):
    await make_user(db_session, 'olena', role=UserRole.waiter)
    tokens = (await client.post(LOGIN, json={'login': 'olena', 'password': PASSWORD})).json()
    await client.patch(f'{URL}/{tokens["user"]["id"]}', headers=h, json={'role': 'chef'})
    me = await client.get(ME, headers={'Authorization': f'Bearer {tokens["access_token"]}'})
    assert me.status_code == 200 and me.json()['role'] == 'chef'


# ---------- останній адмін ----------

async def test_the_only_admin_cannot_disable_or_demote_himself(client, h, boss):
    for body in ({'is_active': False}, {'role': 'waiter'}, {'role': 'chef', 'is_active': False}):
        r = await client.patch(f'{URL}/{boss.id}', headers=h, json=body)
        assert (r.status_code, r.json()['error']['code']) == (409, 'last_admin'), body
    assert (await client.get(f'{URL}/{boss.id}', headers=h)).json()['role'] == 'admin'


async def test_second_admin_makes_it_possible(client, h, boss, db_session):
    other = await make_user(db_session, 'boss2', role=UserRole.admin, email='b2@example.com')
    assert (await client.patch(f'{URL}/{other.id}', headers=h, json={'is_active': False})).status_code == 200
    # другий вимкнено, тож boss знову єдиний активний
    r = await client.patch(f'{URL}/{boss.id}', headers=h, json={'role': 'waiter'})
    assert (r.status_code, r.json()['error']['code']) == (409, 'last_admin')


async def test_disabled_admins_do_not_count_as_other_admins(client, h, boss, db_session):
    await make_user(db_session, 'old_boss', role=UserRole.admin, email='o@example.com', active=False)
    r = await client.patch(f'{URL}/{boss.id}', headers=h, json={'is_active': False})
    assert r.status_code == 409


async def test_admin_may_demote_himself_when_another_admin_exists(client, h, boss, db_session):
    await make_user(db_session, 'boss2', role=UserRole.admin, email='b2@example.com')
    r = await client.patch(f'{URL}/{boss.id}', headers=h, json={'role': 'chef'})
    assert r.status_code == 200 and r.json()['role'] == 'chef'


async def test_editing_other_fields_of_the_only_admin_is_fine(client, h, boss):
    r = await client.patch(f'{URL}/{boss.id}', headers=h, json={'full_name': 'Новий Бос', 'role': 'admin', 'is_active': True})
    assert r.status_code == 200 and r.json()['full_name'] == 'Новий Бос'


# ---------- скидання пароля ----------

async def test_reset_gives_a_temporary_password_shown_once(client, h, db_session):
    await make_user(db_session, 'olena', role=UserRole.waiter)
    uid = (await client.post(LOGIN, json={'login': 'olena', 'password': PASSWORD})).json()['user']['id']
    r = await client.post(f'{URL}/{uid}/reset-password', headers=h)
    assert r.status_code == 200
    temp = r.json()['temporary_password']
    assert set(r.json()) == {'temporary_password'} and len(temp) == 12

    # старий пароль не діє, тимчасовий діє, але змушує змінити
    assert (await client.post(LOGIN, json={'login': 'olena', 'password': PASSWORD})).status_code == 401
    login = await client.post(LOGIN, json={'login': 'olena', 'password': temp})
    assert login.status_code == 200 and login.json()['must_change_password'] is True
    # більше ніде не показується
    for text in ((await client.get(f'{URL}/{uid}', headers=h)).text, (await client.get(URL, headers=h)).text):
        assert temp not in text


async def test_reset_ends_the_employees_sessions_and_unlocks_him(client, h, db_session):
    user = await make_user(db_session, 'olena', role=UserRole.waiter, locked_until=T0 + timedelta(minutes=10), failed_attempts=3)
    session = bearer(user, T0)
    refresh = (await client.post(LOGIN, json={'login': 'olena', 'password': PASSWORD})).status_code   # заблокований: 429
    assert refresh == 429
    r = await client.post(f'{URL}/{user.id}/reset-password', headers=h)
    assert r.status_code == 200
    await db_session.refresh(user)
    assert user.locked_until is None and user.failed_login_attempts == 0 and user.must_change_password is True
    assert (await client.get(ME, headers=session)).status_code == 401     # старий токен мертвий
    assert (await client.post(LOGIN, json={'login': 'olena', 'password': r.json()['temporary_password']})).status_code == 200


async def test_each_reset_gives_a_different_password(client, h, db_session):
    user = await make_user(db_session, 'olena')
    first = (await client.post(f'{URL}/{user.id}/reset-password', headers=h)).json()['temporary_password']
    second = (await client.post(f'{URL}/{user.id}/reset-password', headers=h)).json()['temporary_password']
    assert first != second
    assert (await client.post(LOGIN, json={'login': 'olena', 'password': first})).status_code == 401


async def test_admin_cannot_reset_his_own_password_this_way(client, h, boss):
    r = await client.post(f'{URL}/{boss.id}/reset-password', headers=h)
    assert (r.status_code, r.json()['error']['code']) == (403, 'cannot_reset_own_password')
    assert (await client.post(LOGIN, json={'login': 'boss', 'password': PASSWORD})).status_code == 200


async def test_admin_may_reset_another_admin(client, h, db_session):
    other = await make_user(db_session, 'boss2', role=UserRole.admin, email='b2@example.com')
    assert (await client.post(f'{URL}/{other.id}/reset-password', headers=h)).status_code == 200


async def test_reset_unknown_user_is_404(client, h):
    assert (await client.post(f'{URL}/99999/reset-password', headers=h)).status_code == 404


async def test_full_flow_temporary_password_then_own_password(client, h):
    created = await create(client, h)
    temp = (await client.post(f'{URL}/{created["id"]}/reset-password', headers=h)).json()['temporary_password']
    tokens = (await client.post(LOGIN, json={'login': 'olena', 'password': temp})).json()
    mine = {'Authorization': f'Bearer {tokens["access_token"]}'}
    r = await client.post('/api/v1/auth/change-password', headers=mine,
                          json={'current_password': temp, 'new_password': 'My-own-password-9'})
    assert r.status_code == 200 and r.json()['must_change_password'] is False
    assert (await client.post(LOGIN, json={'login': 'olena', 'password': 'My-own-password-9'})).status_code == 200
    assert (await client.post(LOGIN, json={'login': 'olena', 'password': temp})).status_code == 401


# ---------- генератор тимчасових паролів ----------

def test_temporary_password_shape_and_alphabet():
    for _ in range(300):
        password = generate_temporary_password()
        assert len(password) == 12 and set(password) <= set(_TEMP_PASSWORD_ALPHABET)
    assert not set('0O1lI') & set(_TEMP_PASSWORD_ALPHABET)


def test_temporary_password_has_enough_variety():
    assert len({generate_temporary_password() for _ in range(500)}) == 500
    # усі символи алфавіту реально використовуються
    seen = set(''.join(generate_temporary_password() for _ in range(2000)))
    assert seen == set(_TEMP_PASSWORD_ALPHABET)


def test_temporary_password_satisfies_the_password_policy():
    from app.modules.users.schemas import UserCreate
    UserCreate(login='abc', password=generate_temporary_password(), full_name='X', role=UserRole.chef)
    assert re.fullmatch(r'[A-Za-z2-9]{12}', generate_temporary_password())
