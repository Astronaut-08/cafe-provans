"""/admin/locations: керування закладами (адмін)."""
import pytest
from sqlalchemy import select

from app.db.enums import UserRole
from app.db.models.delivery_zone import DeliveryZone
from tests.factories import bearer, make_location, make_user

URL = '/api/v1/admin/locations'


async def test_requires_admin(client, db_session):
    loc = await make_location(db_session)
    waiter = await make_user(db_session, 'olga', role=UserRole.waiter)
    for method, url, body in [('get', URL, None), ('post', URL, {'name': 'X'}), ('get', f'{URL}/{loc.id}', None),
                              ('patch', f'{URL}/{loc.id}', {'name': 'Y'})]:
        assert (await client.request(method, url, json=body)).status_code == 401
        assert (await client.request(method, url, json=body, headers=bearer(waiter))).status_code == 403


async def test_create_location_with_default_zones(client, db_session, login_as):
    login_as(UserRole.admin)
    response = await client.post(URL, json={
        'name': 'Provans', 'city': 'Болехів', 'address': 'вул. Шевченка, 1', 'phone': '+380501234567',
        'opening_time': '09:00', 'closing_time': '22:00',
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body['city'], body['timezone'], body['is_active'], body['image_url']) == ('Болехів', 'Europe/Kyiv', True, None)

    zones = (await db_session.scalars(select(DeliveryZone).where(DeliveryZone.location_id == body['id'])
                                      .order_by(DeliveryZone.sort_order))).all()
    assert [(z.code, float(z.min_order_amount)) for z in zones] == [('green', 400.0), ('yellow', 600.0), ('red', 1000.0)]
    assert (await client.get(f'/api/v1/locations/{body["id"]}')).status_code == 200      # гість його бачить


@pytest.mark.parametrize('payload', [
    {}, {'name': ''}, {'name': 'X' * 71}, {'name': 'X', 'timezone': 'Mars/Base'},
    {'name': 'X', 'delivery_map_url': 'http://insecure.example.com'},
    {'name': 'X', 'delivery_map_url': 'javascript:alert(1)'},
    {'name': 'X', 'image_url': '/media/x.jpg'},          # фото лише через завантаження
    {'name': 'X', 'unknown': 1},
])
async def test_create_rejects_invalid_payload(client, db_session, login_as, payload):
    login_as(UserRole.admin)
    assert (await client.post(URL, json=payload)).status_code == 422
    assert (await client.get(URL)).json() == []


async def test_admin_sees_inactive_locations_that_guests_do_not(client, db_session, login_as):
    login_as(UserRole.admin)
    active = await make_location(db_session, 'Активний')
    hidden = await make_location(db_session, 'Прихований', active=False)

    assert [loc['id'] for loc in (await client.get(URL)).json()] == [active.id, hidden.id]
    assert (await client.get(f'{URL}/{hidden.id}')).status_code == 200
    assert [loc['id'] for loc in (await client.get('/api/v1/locations')).json()] == [active.id]
    assert (await client.get(f'/api/v1/locations/{hidden.id}')).status_code == 404
    assert (await client.get(f'{URL}/9999')).status_code == 404


async def test_patch_changes_only_given_fields_and_toggles_visibility(client, db_session, login_as):
    login_as(UserRole.admin)
    loc = await make_location(db_session, 'Provans', city='Болехів', address='вул. Шевченка, 1')

    body = (await client.patch(f'{URL}/{loc.id}', json={'address': 'вул. Франка, 5'})).json()
    assert (body['address'], body['city'], body['name']) == ('вул. Франка, 5', 'Болехів', 'Provans')

    await client.patch(f'{URL}/{loc.id}', json={'is_active': False})
    assert (await client.get(f'/api/v1/locations/{loc.id}')).status_code == 404       # зник для гостей
    await client.patch(f'{URL}/{loc.id}', json={'is_active': True})
    assert (await client.get(f'/api/v1/locations/{loc.id}')).status_code == 200

    cleared = (await client.patch(f'{URL}/{loc.id}', json={'address': None})).json()   # null очищає необов'язкове поле
    assert cleared['address'] is None


@pytest.mark.parametrize('payload', [{'name': None}, {'timezone': None}, {'is_active': None}, {'name': ''},
                                     {'timezone': 'Mars/Base'}, {'image_url': 'x'}])
async def test_patch_rejects_invalid_payload(client, db_session, login_as, payload):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    assert (await client.patch(f'{URL}/{loc.id}', json=payload)).status_code == 422


async def test_patch_unknown_location_is_404(client, login_as):
    login_as(UserRole.admin)
    assert (await client.patch(f'{URL}/9999', json={'name': 'X'})).status_code == 404
