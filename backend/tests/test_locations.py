"""Публічне API закладів: GET /locations, GET /locations/{id}."""
from datetime import UTC, datetime, time

import pytest

from tests.factories import make_location

URL = '/api/v1/locations'


def utc(h: int, m: int = 0, *, month=1) -> datetime:
    return datetime(2026, month, 15, h, m, tzinfo=UTC)


async def test_list_returns_only_active_locations_ordered_by_id(client, db_session):
    first = await make_location(db_session, 'Болехів')
    await make_location(db_session, 'Закритий', active=False)
    third = await make_location(db_session, 'Велика Тура')

    body = (await client.get(URL)).json()
    assert [row['id'] for row in body] == [first.id, third.id]
    assert [row['name'] for row in body] == ['Болехів', 'Велика Тура']


async def test_list_does_not_expose_internal_fields(client, db_session):
    await make_location(db_session)
    row = (await client.get(URL)).json()[0]
    assert 'is_active' not in row
    assert set(row) == {
        'id', 'name', 'city', 'address', 'phone', 'instagram', 'opening_time', 'closing_time', 'timezone',
        'is_open_now',
    }


async def test_list_is_empty_when_there_are_no_locations(client):
    assert (await client.get(URL)).json() == []


async def test_is_open_now_is_null_when_hours_are_unknown(client, db_session):
    location = await make_location(db_session)
    # «невідомо» це не «зачинено»: фронтенд не повинен писати гостю, що закрито
    assert (await client.get(f'{URL}/{location.id}')).json()['is_open_now'] is None


async def test_is_open_now_is_null_when_only_one_bound_is_set(client, db_session):
    location = await make_location(db_session, opening=time(10))
    assert (await client.get(f'{URL}/{location.id}')).json()['is_open_now'] is None


@pytest.mark.parametrize('utc_moment, expected', [
    (utc(7, 59), False),   # 09:59 у Києві
    (utc(8, 0), True),     # 10:00: відкриття включно
    (utc(19, 59), True),   # 21:59
    (utc(20, 0), False),   # 22:00: закриття не включно
])
async def test_is_open_now_uses_the_location_timezone_not_utc(client, db_session, set_now, utc_moment, expected):
    location = await make_location(db_session, opening=time(10), closing=time(22))
    set_now(utc_moment)
    assert (await client.get(f'{URL}/{location.id}')).json()['is_open_now'] is expected


async def test_is_open_now_follows_daylight_saving_time(client, db_session, set_now):
    location = await make_location(db_session, opening=time(10), closing=time(22))
    set_now(utc(7, 30, month=7))   # літо: 10:30 у Києві (UTC+3), відкрито
    assert (await client.get(f'{URL}/{location.id}')).json()['is_open_now'] is True
    set_now(utc(7, 30, month=1))   # зима: 09:30 у Києві (UTC+2), ще зачинено
    assert (await client.get(f'{URL}/{location.id}')).json()['is_open_now'] is False


async def test_is_open_now_for_hours_past_midnight(client, db_session, set_now):
    location = await make_location(db_session, opening=time(18), closing=time(2))
    # зима, Київ = UTC+2: години роботи 18:00-02:00 за Києвом це 16:00-00:00 за UTC
    for moment, kyiv, expected in [
        (utc(15, 59), '17:59', False),
        (utc(16, 0), '18:00', True),
        (utc(22, 30), '00:30', True),
        (utc(23, 59), '01:59', True),
        (utc(0, 0), '02:00', False),    # закриття не включно
        (utc(10, 0), '12:00', False),
    ]:
        set_now(moment)
        assert (await client.get(f'{URL}/{location.id}')).json()['is_open_now'] is expected, kyiv


async def test_list_computes_is_open_now_for_every_location(client, db_session, set_now):
    await make_location(db_session, 'Відкритий', opening=time(0), closing=time(0))   # цілодобово
    await make_location(db_session, 'Без годин')
    set_now(utc(12))
    body = (await client.get(URL)).json()
    assert [row['is_open_now'] for row in body] == [True, None]


async def test_get_one(client, db_session):
    location = await make_location(db_session, 'Provans', address='вул. Січових Стрільців, 1')
    body = (await client.get(f'{URL}/{location.id}')).json()
    assert body['name'] == 'Provans'
    assert body['address'] == 'вул. Січових Стрільців, 1'


async def test_inactive_location_is_404_not_403(client, db_session):
    location = await make_location(db_session, active=False)
    r = await client.get(f'{URL}/{location.id}')
    assert r.status_code == 404
    assert r.json()['error']['code'] == 'not_found'


async def test_unknown_location_is_404_with_ukrainian_message(client):
    r = await client.get(f'{URL}/999')
    assert r.status_code == 404
    assert r.json()['error']['message'] == 'Заклад не знайдено'


@pytest.mark.parametrize('bad_id', ['0', '-1', 'abc', '99999999999'])
async def test_bad_id_is_422_not_500(client, bad_id):
    r = await client.get(f'{URL}/{bad_id}')
    assert r.status_code == 422
    assert r.json()['error']['code'] == 'validation_error'


async def test_locations_are_read_only(client):
    assert (await client.post(URL, json={'name': 'X'})).status_code == 405


async def test_invalid_timezone_in_db_does_not_break_the_endpoint(client, db_session, set_now):
    # некоректний пояс у БД не повинен валити публічний список: запасний варіант UTC (12:00 у вікні)
    await make_location(db_session, opening=time(10), closing=time(22), timezone='Mars/Olympus')
    set_now(utc(12))
    r = await client.get(URL)
    assert r.status_code == 200
    assert r.json()[0]['is_open_now'] is True
