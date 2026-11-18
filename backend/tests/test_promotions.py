"""GET /locations/{id}/promotions: акції, що діють у закладі зараз."""
from datetime import UTC, date, datetime, time

import pytest

from app.db.enums import PromotionStatus
from tests.factories import (
    make_category, make_dish, make_location, make_promotion, set_dish_location,
)


def url(location_id: int) -> str:
    return f'/api/v1/locations/{location_id}/promotions'


def utc(h=10, m=0, *, month=1, day=15, year=2026) -> datetime:
    return datetime(year, month, day, h, m, tzinfo=UTC)


@pytest.fixture
async def shop(db_session, set_now):
    """Заклад + дві страви + фіксований «зараз» (15 січня 2026, 12:00 за Києвом)."""
    set_now(utc(10, 0))
    location = await make_location(db_session)
    category = await make_category(db_session)
    pizza = await make_dish(db_session, category, 'Піца', '250.00', sell_in=[location])
    drink = await make_dish(db_session, category, 'Лимонад', '60.00', sell_in=[location])
    return location, pizza, drink


async def titles(client, location) -> list[str]:
    r = await client.get(url(location.id))
    assert r.status_code == 200, r.text
    return [p['title'] for p in r.json()]


# ---------- хто взагалі потрапляє у вибірку ----------

async def test_only_active_status_is_shown(client, db_session, shop):
    location, pizza, _ = shop
    for status in PromotionStatus:
        await make_promotion(db_session, status.value, locations=[location], items=[(pizza, 1)], status=status)
    assert await titles(client, location) == ['active']


async def test_promotion_must_be_linked_to_the_location(client, db_session, shop):
    location, pizza, _ = shop
    other = await make_location(db_session, 'Інший')
    await make_promotion(db_session, 'Тут', locations=[location], items=[(pizza, 1)])
    await make_promotion(db_session, 'Деінде', locations=[other], items=[(pizza, 1)])
    await make_promotion(db_session, 'Ніде', locations=[], items=[(pizza, 1)])
    await make_promotion(db_session, 'Скрізь', locations=[location, other], items=[(pizza, 1)])
    assert sorted(await titles(client, location)) == ['Скрізь', 'Тут']


async def test_featured_filter_and_order_home_first(client, db_session, shop):
    location, pizza, _ = shop
    await make_promotion(db_session, 'Звичайна', locations=[location], items=[(pizza, 1)])
    await make_promotion(db_session, 'Головна', locations=[location], items=[(pizza, 1)], home=True)
    assert await titles(client, location) == ['Головна', 'Звичайна']

    r = await client.get(url(location.id), params={'featured': 'true'})
    assert [p['title'] for p in r.json()] == ['Головна']


# ---------- дата й час за місцевим часом закладу ----------

async def test_dates_are_inclusive(client, db_session, shop):
    location, pizza, _ = shop
    await make_promotion(db_session, 'Сьогодні', locations=[location], items=[(pizza, 1)],
                         start_date=date(2026, 1, 15), end_date=date(2026, 1, 15))
    await make_promotion(db_session, 'Завтра', locations=[location], items=[(pizza, 1)], start_date=date(2026, 1, 16))
    await make_promotion(db_session, 'Вчора', locations=[location], items=[(pizza, 1)], end_date=date(2026, 1, 14))
    assert await titles(client, location) == ['Сьогодні']


async def test_time_window_uses_location_timezone(client, db_session, shop, set_now):
    location, pizza, _ = shop
    await make_promotion(db_session, 'Бізнес-ланч', locations=[location], items=[(pizza, 1)],
                         start_time=time(12), end_time=time(15))
    set_now(utc(9, 59))    # 11:59 у Києві
    assert await titles(client, location) == []
    set_now(utc(10, 0))    # 12:00
    assert await titles(client, location) == ['Бізнес-ланч']
    set_now(utc(12, 59))   # 14:59
    assert await titles(client, location) == ['Бізнес-ланч']
    set_now(utc(13, 0))    # 15:00, кінець не включно
    assert await titles(client, location) == []


async def test_date_is_taken_in_local_time_not_utc(client, db_session, shop, set_now):
    location, pizza, _ = shop
    await make_promotion(db_session, 'Лише 16-го', locations=[location], items=[(pizza, 1)],
                         start_date=date(2026, 1, 16), end_date=date(2026, 1, 16))
    set_now(utc(23, 0))                 # 15 січня 23:00 UTC = 16 січня 01:00 у Києві
    assert await titles(client, location) == ['Лише 16-го']
    set_now(utc(21, 59))                # 23:59 за Києвом, ще 15-те
    assert await titles(client, location) == []


async def test_overnight_promotion_runs_past_midnight(client, db_session, shop, set_now):
    location, pizza, _ = shop
    await make_promotion(db_session, 'Нічна', locations=[location], items=[(pizza, 1)],
                         start_time=time(22), end_time=time(2), end_date=date(2026, 1, 15))
    set_now(utc(20, 30))                  # 15 січня 22:30 за Києвом
    assert await titles(client, location) == ['Нічна']
    set_now(utc(23, 30))                  # 16 січня 01:30: ще вечір 15-го, end_date не заважає
    assert await titles(client, location) == ['Нічна']
    set_now(utc(0, 0, day=16))            # 02:00: закінчилась
    assert await titles(client, location) == []
    set_now(utc(20, 30, day=16))          # 16 січня 22:30: end_date минув
    assert await titles(client, location) == []


# ---------- ціна ----------

async def test_price_is_sum_of_items_when_auto_calculated(client, db_session, shop):
    location, pizza, drink = shop
    await make_promotion(db_session, 'Набір', locations=[location], items=[(pizza, 2), (drink, 3)])
    promo = (await client.get(url(location.id))).json()[0]
    assert promo['items_total'] == 680.0     # 2*250 + 3*60
    assert promo['price'] == 680.0
    assert promo['savings'] == 0.0
    assert [(i['name'], i['quantity'], i['unit_price']) for i in promo['items']] == [('Піца', 2, 250.0), ('Лимонад', 3, 60.0)]


async def test_fixed_price_and_savings(client, db_session, shop):
    location, pizza, drink = shop
    await make_promotion(db_session, 'Комбо', locations=[location], items=[(pizza, 1), (drink, 1)], price='280.00')
    promo = (await client.get(url(location.id))).json()[0]
    assert (promo['price'], promo['items_total'], promo['savings']) == (280.0, 310.0, 30.0)


async def test_savings_never_negative_when_fixed_price_is_above_items(client, db_session, shop):
    location, pizza, _ = shop
    await make_promotion(db_session, 'Дорожче', locations=[location], items=[(pizza, 1)], price='300.00')
    promo = (await client.get(url(location.id))).json()[0]
    assert (promo['price'], promo['items_total'], promo['savings']) == (300.0, 250.0, 0.0)


async def test_items_are_priced_with_location_override(client, db_session, shop):
    location, pizza, drink = shop
    await set_dish_location(db_session, pizza, location, price_override='200.00')
    await make_promotion(db_session, 'Набір', locations=[location], items=[(pizza, 1), (drink, 1)], price='230.00')
    promo = (await client.get(url(location.id))).json()[0]
    assert (promo['items_total'], promo['savings']) == (260.0, 30.0)


async def test_fixed_price_promotion_without_items_is_shown(client, db_session, shop):
    location, *_ = shop
    await make_promotion(db_session, 'Знижка на все', locations=[location], items=[], price='0.00')
    promo = (await client.get(url(location.id))).json()[0]
    assert (promo['price'], promo['items_total'], promo['savings'], promo['items']) == (0.0, 0.0, 0.0, [])


async def test_promotion_without_price_and_items_is_hidden_not_free(client, db_session, shop):
    location, *_ = shop
    await make_promotion(db_session, 'Без цін', locations=[location], items=[])   # сума позицій = 0 позицій
    assert await titles(client, location) == []


# ---------- доступність страв і pause_if_unavailable ----------

async def test_paused_when_a_dish_is_unavailable_globally(client, db_session, shop):
    location, pizza, drink = shop
    drink.is_available = False
    await db_session.commit()
    await make_promotion(db_session, 'Набір', locations=[location], items=[(pizza, 1), (drink, 1)])
    assert await titles(client, location) == []


async def test_paused_when_a_dish_is_unavailable_in_this_location(client, db_session, shop):
    location, pizza, drink = shop
    await set_dish_location(db_session, drink, location, available=False)
    await make_promotion(db_session, 'Набір', locations=[location], items=[(pizza, 1), (drink, 1)])
    assert await titles(client, location) == []


async def test_paused_when_a_dish_is_not_sold_in_this_location_at_all(client, db_session, shop):
    """Страва без запису dish_locations: outer join дає NULL. Акція не повинна «забути» цю позицію."""
    location, pizza, _ = shop
    elsewhere = await make_dish(db_session, await make_category(db_session, 'Інше'), 'Десерт', '90.00')
    await make_promotion(db_session, 'Набір', locations=[location], items=[(pizza, 1), (elsewhere, 1)])
    assert await titles(client, location) == []


async def test_shown_with_flag_when_pause_is_off(client, db_session, shop):
    location, pizza, drink = shop
    await set_dish_location(db_session, drink, location, available=False)
    await make_promotion(db_session, 'Набір', locations=[location], items=[(pizza, 1), (drink, 1)],
                         pause_if_unavailable=False)
    promo = (await client.get(url(location.id))).json()[0]
    assert promo['has_unavailable_items'] is True
    assert {i['name']: i['is_available'] for i in promo['items']} == {'Піца': True, 'Лимонад': False}


async def test_flag_is_false_when_everything_is_available(client, db_session, shop):
    location, pizza, _ = shop
    await make_promotion(db_session, 'Піца', locations=[location], items=[(pizza, 1)])
    assert (await client.get(url(location.id))).json()[0]['has_unavailable_items'] is False


async def test_unavailable_dish_in_another_location_does_not_pause_this_one(client, db_session, shop):
    location, pizza, _ = shop
    other = await make_location(db_session, 'Інший')
    await set_dish_location(db_session, pizza, other, available=False)
    await make_promotion(db_session, 'Піца', locations=[location, other], items=[(pizza, 1)])
    assert await titles(client, location) == ['Піца']
    assert await titles(client, other) == []


# ---------- заклад ----------

async def test_inactive_or_unknown_location_is_404(client, db_session):
    inactive = await make_location(db_session, active=False)
    assert (await client.get(url(inactive.id))).status_code == 404
    assert (await client.get(url(999))).status_code == 404


async def test_response_fields(client, db_session, shop):
    location, pizza, _ = shop
    await make_promotion(db_session, 'Піца', locations=[location], items=[(pizza, 1)],
                         start_time=time(10), end_time=time(22), start_date=date(2026, 1, 1))
    promo = (await client.get(url(location.id))).json()[0]
    assert set(promo) == {
        'id', 'title', 'description', 'price', 'items_total', 'savings', 'show_on_home',
        'has_unavailable_items', 'start_time', 'end_time', 'start_date', 'end_date', 'items',
    }
    assert set(promo['items'][0]) == {'dish_id', 'name', 'quantity', 'unit_price', 'is_available'}
    assert promo['start_time'] == '10:00:00' and promo['start_date'] == '2026-01-01'
