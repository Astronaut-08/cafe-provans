"""Доставка: GET /locations/{id}/delivery і POST /locations/{id}/delivery/check."""
import pytest

from tests.factories import make_location, make_zone, square

# Умовні «координати міста»: [довгота, широта]. Три вкладені квадрати навколо (10, 10),
# як вкладені зони Google My Maps: червона охоплює жовту, жовта охоплює зелену.
GREEN = square(9, 9, 11, 11)
YELLOW = square(8, 8, 12, 12)
RED = square(5, 5, 15, 15)


def info_url(location_id: int) -> str:
    return f'/api/v1/locations/{location_id}/delivery'


def check_url(location_id: int) -> str:
    return f'{info_url(location_id)}/check'


@pytest.fixture
async def city(db_session):
    location = await make_location(db_session)
    # навмисно створюємо у «неправильному» порядку id: сортування має іти за sort_order
    await make_zone(db_session, location, 'red', name='Червона', minimum='1000', polygon=RED, sort_order=3)
    await make_zone(db_session, location, 'green', name='Зелена', minimum='400', polygon=GREEN, sort_order=1)
    await make_zone(db_session, location, 'yellow', name='Жовта', minimum='600', polygon=YELLOW, sort_order=2)
    return location


async def check(client, location, lat, lng):
    return await client.post(check_url(location.id), json={'lat': lat, 'lng': lng})


# ---------- модель ----------

async def test_zone_without_polygon_is_stored_as_sql_null_not_json_null(db_session):
    """Регресія: без JSONB(none_as_null=True) ORM писав би JSON 'null': це не SQL NULL, тож
    `polygon IS NOT NULL` було б істинним, а CHECK-обмеження відхилило б запис."""
    from sqlalchemy import text

    location = await make_location(db_session)
    zone = await make_zone(db_session, location, 'green', polygon=None)
    is_sql_null = await db_session.scalar(text('SELECT polygon IS NULL FROM delivery_zones WHERE id = :id'), {'id': zone.id})
    assert is_sql_null is True


@pytest.mark.parametrize('garbage', [
    {'type': 'Point', 'coordinates': [1, 2]},
    {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]},
    {'coordinates': [[0, 0]]},
    [1, 2, 3],
    'polygon',
    42,
])
async def test_database_rejects_anything_but_polygon_geometry(db_session, garbage):
    """Страховка на рівні БД: навіть мимо API й імпортера сміття в `polygon` не потрапить."""
    from sqlalchemy.exc import IntegrityError

    location = await make_location(db_session)
    with pytest.raises(IntegrityError, match='polygon_geojson'):
        await make_zone(db_session, location, 'green', polygon=garbage)


async def test_database_accepts_polygon_and_multipolygon(db_session):
    location = await make_location(db_session)
    await make_zone(db_session, location, 'green', polygon=GREEN, sort_order=1)
    multi = {'type': 'MultiPolygon', 'coordinates': [GREEN['coordinates']]}
    await make_zone(db_session, location, 'yellow', polygon=multi, sort_order=2)


# ---------- GET: умови доставки ----------

async def test_info_lists_zones_nearest_first_with_free_delivery(client, city):
    body = (await client.get(info_url(city.id))).json()
    assert body['delivery_price'] == 0.0
    assert [(z['code'], z['min_order_amount']) for z in body['zones']] == [
        ('green', 400.0), ('yellow', 600.0), ('red', 1000.0),
    ]


async def test_info_does_not_leak_polygons_but_says_if_area_exists(client, db_session):
    location = await make_location(db_session)
    await make_zone(db_session, location, 'green', polygon=GREEN, sort_order=1)
    await make_zone(db_session, location, 'yellow', polygon=None, sort_order=2)
    zones = (await client.get(info_url(location.id))).json()['zones']
    assert [z['has_area'] for z in zones] == [True, False]
    assert all('polygon' not in z for z in zones)


async def test_info_skips_inactive_zones_and_other_locations(client, db_session):
    location = await make_location(db_session)
    other = await make_location(db_session, 'Інший')
    await make_zone(db_session, location, 'green', sort_order=1)
    await make_zone(db_session, location, 'yellow', active=False, sort_order=2)
    await make_zone(db_session, other, 'red', sort_order=3)
    assert [z['code'] for z in (await client.get(info_url(location.id))).json()['zones']] == ['green']


# ---------- POST /check: у якій зоні точка ----------

@pytest.mark.parametrize('lat, lng, code, name, minimum', [
    (10, 10, 'green', 'Зелена', 400.0),     # в центрі: найближча зона виграє, хоч у жовту й червону теж потрапляє
    (8.5, 10, 'yellow', 'Жовта', 600.0),    # у жовтій, але поза зеленою
    (6, 10, 'red', 'Червона', 1000.0),      # лише в червоній
])
async def test_point_gets_the_nearest_matching_zone(client, city, lat, lng, code, name, minimum):
    body = (await check(client, city, lat, lng)).json()
    assert body['deliverable'] is True
    assert body['zone'] == {'code': code, 'name': name, 'min_order_amount': minimum}
    assert body['delivery_price'] == 0.0
    assert body['reason'] is None


async def test_point_outside_all_zones_is_pickup_only(client, city):
    body = (await check(client, city, 50, 50)).json()
    assert body == {'deliverable': False, 'zone': None, 'delivery_price': None, 'reason': 'outside_zones'}


async def test_lat_and_lng_are_not_mixed_up(client, db_session):
    location = await make_location(db_session)
    await make_zone(db_session, location, 'green', polygon=square(0, 0, 20, 2))   # довгота 0..20, широта 0..2
    assert (await check(client, location, lat=1, lng=15)).json()['deliverable'] is True
    assert (await check(client, location, lat=15, lng=1)).json()['deliverable'] is False


async def test_real_bolekhiv_like_coordinates(client, db_session):
    """Реалістичні числа: Болехів ≈ 49.05° пн.ш., 23.85° сх.д. (довгота більша за широту)."""
    location = await make_location(db_session)
    await make_zone(db_session, location, 'green', polygon=square(23.84, 49.04, 23.86, 49.06))
    assert (await check(client, location, lat=49.05, lng=23.85)).json()['deliverable'] is True
    assert (await check(client, location, lat=23.85, lng=49.05)).json()['deliverable'] is False


async def test_check_ignores_inactive_zones(client, db_session):
    location = await make_location(db_session)
    await make_zone(db_session, location, 'green', polygon=GREEN, active=False, sort_order=1)
    await make_zone(db_session, location, 'yellow', polygon=YELLOW, minimum='600', sort_order=2)
    assert (await check(client, location, 10, 10)).json()['zone']['code'] == 'yellow'


async def test_check_uses_only_this_locations_zones(client, db_session):
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    await make_zone(db_session, a, 'green', polygon=GREEN)
    assert (await check(client, a, 10, 10)).json()['deliverable'] is True
    body = (await check(client, b, 10, 10)).json()
    assert (body['deliverable'], body['reason']) == (False, 'not_configured')


async def test_not_configured_when_no_zone_has_a_polygon(client, db_session):
    location = await make_location(db_session)
    await make_zone(db_session, location, 'green', polygon=None)
    body = (await check(client, location, 10, 10)).json()
    # це не «поза зонами»: фронтенд не має казати гостю «лише самовивіз», коли просто немає даних
    assert (body['deliverable'], body['reason']) == (False, 'not_configured')


async def test_partially_drawn_zones_still_work_for_the_drawn_ones(client, db_session):
    location = await make_location(db_session)
    await make_zone(db_session, location, 'green', polygon=GREEN, sort_order=1)
    await make_zone(db_session, location, 'red', polygon=None, minimum='1000', sort_order=3)
    assert (await check(client, location, 10, 10)).json()['zone']['code'] == 'green'
    assert (await check(client, location, 50, 50)).json()['reason'] == 'outside_zones'


async def test_multipolygon_zone(client, db_session):
    location = await make_location(db_session)
    multi = {'type': 'MultiPolygon', 'coordinates': [square(0, 0, 1, 1)['coordinates'], square(5, 5, 6, 6)['coordinates']]}
    await make_zone(db_session, location, 'green', polygon=multi)
    assert (await check(client, location, 5.5, 5.5)).json()['deliverable'] is True
    assert (await check(client, location, 3, 3)).json()['deliverable'] is False


# ---------- валідація та помилки ----------

@pytest.mark.parametrize('body', [
    {'lat': 91, 'lng': 10},
    {'lat': -91, 'lng': 10},
    {'lat': 10, 'lng': 181},
    {'lat': 10},
    {'lng': 10},
    {'lat': 'abc', 'lng': 10},
    {'lat': 10, 'lng': 10, 'extra': 1},
    {},
])
async def test_bad_coordinates_are_422(client, city, body):
    r = await client.post(check_url(city.id), json=body)
    assert r.status_code == 422
    assert r.json()['error']['code'] == 'validation_error'


async def test_check_is_post_only(client, city):
    # координати гостя не повинні потрапляти в адресу запиту (а отже в логи проксі)
    assert (await client.get(check_url(city.id), params={'lat': 10, 'lng': 10})).status_code == 405


async def test_inactive_or_unknown_location_is_404(client, db_session):
    inactive = await make_location(db_session, active=False)
    assert (await client.get(info_url(inactive.id))).status_code == 404
    assert (await check(client, inactive, 10, 10)).status_code == 404
    assert (await client.get(info_url(999))).status_code == 404
    assert (await client.post(check_url(999), json={'lat': 1, 'lng': 1})).status_code == 404


async def test_validation_runs_before_database_lookup_for_bad_id(client):
    r = await client.post(check_url(0), json={'lat': 1, 'lng': 1})
    assert r.status_code == 422
