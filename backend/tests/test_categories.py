"""Модуль categories: еталон того, як тестувати модуль (HTTP зверху вниз, до реальної БД)."""
import pytest

from app.db.enums import UserRole
from app.db.models.dish import Dish

URL = '/api/v1/categories'


async def create(client, name='Піца', sort_order=0) -> dict:
    r = await client.post(URL, json={'name': name, 'sort_order': sort_order})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def as_admin(login_as):
    login_as(UserRole.admin)


# ---------- права доступу ----------

async def test_reading_is_public(client):
    assert (await client.get(URL)).status_code == 200


@pytest.mark.parametrize('method, path, body', [
    ('POST', URL, {'name': 'X'}),
    ('PATCH', f'{URL}/1', {'name': 'X'}),
    ('DELETE', f'{URL}/1', None),
])
async def test_writing_is_closed_without_login(client, method, path, body):
    r = await client.request(method, path, json=body)
    assert r.status_code == 401
    assert r.json()['error']['code'] == 'not_authenticated'


@pytest.mark.parametrize('role, expected', [
    (UserRole.waiter, 403),
    (UserRole.chef, 403),
    (UserRole.admin, 201),
])
async def test_only_admin_may_create(client, login_as, role, expected):
    login_as(role)
    assert (await client.post(URL, json={'name': 'Піца'})).status_code == expected


# ---------- читання ----------

async def test_list_is_sorted_by_sort_order_then_name(client, as_admin):
    await create(client, 'Десерти', 2)
    await create(client, 'Піца', 1)
    await create(client, 'Напої', 1)
    names = [c['name'] for c in (await client.get(URL)).json()]
    assert names == ['Напої', 'Піца', 'Десерти']


async def test_get_one_and_404(client, as_admin):
    created = await create(client)
    assert (await client.get(f'{URL}/{created["id"]}')).json() == created
    r = await client.get(f'{URL}/{created["id"] + 1000}')
    assert r.status_code == 404
    assert r.json()['error']['code'] == 'not_found'


@pytest.mark.parametrize('bad_id', ['0', '-5', 'abc', '99999999999'])
async def test_invalid_id_is_422_not_500(client, bad_id):
    # 99999999999 раніше дійшло б до asyncpg і закінчилось би 500
    assert (await client.get(f'{URL}/{bad_id}')).status_code == 422


# ---------- створення ----------

async def test_create_returns_read_schema(client, as_admin):
    created = await create(client, '  Піца  ', 3)  # пробіли по краях обрізаються
    assert created == {'id': created['id'], 'name': 'Піца', 'sort_order': 3}


async def test_sort_order_defaults_to_zero(client, as_admin):
    r = await client.post(URL, json={'name': 'Напої'})
    assert r.json()['sort_order'] == 0


@pytest.mark.parametrize('body', [
    {},
    {'name': ''},
    {'name': '   '},
    {'name': 'x' * 101},
    {'name': 'Піца', 'sort_order': -1},
    {'name': 'Піца', 'sortorder': 1},        # одруківка в полі
    {'name': None},
])
async def test_create_rejects_invalid_body(client, as_admin, body):
    assert (await client.post(URL, json=body)).status_code == 422


# ---------- оновлення ----------

async def test_patch_changes_only_sent_fields(client, as_admin):
    created = await create(client, 'Піца', 5)
    r = await client.patch(f'{URL}/{created["id"]}', json={'sort_order': 9})
    assert r.json() == {'id': created['id'], 'name': 'Піца', 'sort_order': 9}
    r = await client.patch(f'{URL}/{created["id"]}', json={'name': 'Піци'})
    assert r.json() == {'id': created['id'], 'name': 'Піци', 'sort_order': 9}


async def test_patch_with_empty_body_changes_nothing(client, as_admin):
    created = await create(client)
    r = await client.patch(f'{URL}/{created["id"]}', json={})
    assert r.status_code == 200 and r.json() == created


@pytest.mark.parametrize('body', [{'name': None}, {'sort_order': None}, {'name': ''}, {'bogus': 1}])
async def test_patch_rejects_null_empty_and_unknown(client, as_admin, body):
    created = await create(client)
    assert (await client.patch(f'{URL}/{created["id"]}', json=body)).status_code == 422


async def test_patch_missing_is_404(client, as_admin):
    assert (await client.patch(f'{URL}/999999', json={'name': 'X'})).status_code == 404


# ---------- видалення ----------

async def test_delete_removes_category(client, as_admin):
    created = await create(client)
    assert (await client.delete(f'{URL}/{created["id"]}')).status_code == 204
    assert (await client.get(f'{URL}/{created["id"]}')).status_code == 404
    assert (await client.delete(f'{URL}/{created["id"]}')).status_code == 404


async def test_delete_category_with_dishes_is_409_and_keeps_everything(client, as_admin, db_session):
    created = await create(client)
    db_session.add(Dish(category_id=created['id'], name='Маргарита', price=180))
    await db_session.commit()

    r = await client.delete(f'{URL}/{created["id"]}')
    assert r.status_code == 409
    assert r.json()['error']['code'] == 'category_not_empty'

    # після відкату і категорія, і страва на місці, а сесія лишилась робочою
    assert (await client.get(f'{URL}/{created["id"]}')).status_code == 200
    assert len((await client.get(URL)).json()) == 1
