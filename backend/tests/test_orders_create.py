"""Створення замовлення: ціни закладу, акції, доставка за зонами, гість за телефоном, права."""
from datetime import UTC, datetime, time

import pytest
from sqlalchemy import func, select

from app.db.models.customer import Customer
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.order_status_history import OrderStatusHistory
from app.db.models.payment import Payment
from tests.factories import make_area, make_dish, make_promotion, make_zone, set_dish_location
from tests.orders_world import build_world, delivery_payload, pickup_payload

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)   # п'ятниця, 14:00 у Києві


@pytest.fixture
async def w(db_session, set_now):
    set_now(NOW)
    return await build_world(db_session, NOW)


async def post(client, headers, body):
    return await client.post('/api/v1/orders', json=body, headers=headers)


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


# ---------- успішний самовивіз ----------

async def test_pickup_order_is_created_with_prices_from_the_server(client, w):
    r = await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.pizza.id, 2), (w.cola.id, 1)], name='Марія'))
    assert r.status_code == 201, r.text
    body = r.json()

    assert body['order_number'] == f'PR-{body["id"]:06d}'
    assert (body['status'], body['payment_status'], body['source']) == ('new', 'pending', 'waiter')
    assert (body['fulfillment_type'], body['location_id']) == ('pickup', w.l1.id)
    assert (body['subtotal_price'], body['delivery_price'], body['total_price']) == (450.0, 0.0, 450.0)
    assert body['delivery_zone'] is None and body['delivery_address'] is None
    assert body['customer'] == {'id': body['customer']['id'], 'phone': '+380671234567', 'full_name': 'Марія'}

    assert [i['name'] for i in body['items']] == ['Маргарита', 'Кола']           # у порядку замовлення
    items = {i['name']: i for i in body['items']}
    assert items['Маргарита']['unit_price'] == 200.0 and items['Маргарита']['quantity'] == 2
    assert items['Маргарита']['line_total'] == 400.0
    assert items['Кола']['line_total'] == 50.0
    assert items['Маргарита']['dish_id'] == w.pizza.id and items['Маргарита']['promotion_id'] is None

    assert [(p['provider'], p['amount'], p['status']) for p in body['payments']] == [('cash', 450.0, 'pending')]
    assert [(h['status'], h['changed_by']['full_name']) for h in body['history']] == [('new', 'Оля Офіціант')]
    assert body['allowed_statuses'] == ['confirmed', 'cancelled']


async def test_location_price_override_is_used(client, w):
    r = await post(client, w.h.waiter2, pickup_payload(w.l2.id, [(w.pizza.id, 1)]))
    assert r.status_code == 201
    assert r.json()['items'][0]['unit_price'] == 250.0     # у закладі 2 власна ціна


async def test_terminal_payment_method_is_stored(client, w):
    r = await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.pizza.id, 1)], method='terminal'))
    assert r.json()['payments'][0]['provider'] == 'terminal'


async def test_order_numbers_are_unique_and_follow_the_id(client, w):
    first = (await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.cola.id, 1)]))).json()
    second = (await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.cola.id, 1)]))).json()
    assert first['order_number'] != second['order_number']
    assert second['id'] > first['id']
    assert not first['order_number'].startswith('new-')


async def test_rows_are_written_together(client, db_session, w):
    r = await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.pizza.id, 3)]))
    order_id = r.json()['id']
    assert await count(db_session, Order) == 1
    assert await count(db_session, OrderItem) == 1
    assert await count(db_session, Payment) == 1
    history = (await db_session.scalars(select(OrderStatusHistory).where(OrderStatusHistory.order_id == order_id))).all()
    assert len(history) == 1 and history[0].changed_by == w.waiter.id


async def test_blank_notes_become_null(client, w):
    body = pickup_payload(w.l1.id, [(w.cola.id, 1)], staff_notes='   ')
    body['items'][0]['note'] = '  '
    r = await post(client, w.h.waiter, body)
    assert r.json()['staff_notes'] is None and r.json()['items'][0]['note'] is None


async def test_item_note_and_staff_notes_are_saved(client, w):
    body = pickup_payload(w.l1.id, [(w.pizza.id, 1)], staff_notes=' Подзвонити за 5 хв ')
    body['items'][0]['note'] = 'без цибулі'
    r = (await post(client, w.h.waiter, body)).json()
    assert r['staff_notes'] == 'Подзвонити за 5 хв' and r['items'][0]['note'] == 'без цибулі'


async def test_same_dish_in_two_lines_is_allowed(client, w):
    body = pickup_payload(w.l1.id, [(w.pizza.id, 1), (w.pizza.id, 1)])
    body['items'][1]['note'] = 'без сиру'
    r = await post(client, w.h.waiter, body)
    assert r.status_code == 201 and r.json()['total_price'] == 400.0 and len(r.json()['items']) == 2


# ---------- нельзя довіряти клієнту ----------

@pytest.mark.parametrize('extra', [
    {'total_price': 1}, {'status': 'completed'}, {'payment_status': 'paid'}, {'source': 'website'},
    {'delivery_price': 0}, {'subtotal_price': 1},
])
async def test_client_cannot_send_server_owned_fields(client, w, extra):
    r = await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.cola.id, 1)], **extra))
    assert r.status_code == 422


async def test_client_cannot_send_prices_in_items(client, w):
    body = pickup_payload(w.l1.id, [(w.cola.id, 1)])
    body['items'][0]['unit_price'] = 1
    assert (await post(client, w.h.waiter, body)).status_code == 422


# ---------- валідація запиту ----------

@pytest.mark.parametrize('mutate', [
    lambda b: b.update(items=[]),
    lambda b: b.update(items=[{'quantity': 1}]),                                   # ні страви, ні акції
    lambda b: b.update(items=[{'dish_id': 1, 'promotion_id': 1, 'quantity': 1}]),  # і те, і те
    lambda b: b['items'][0].update(quantity=0),
    lambda b: (b['items'][0].update(quantity=0), b['items'].append({'dish_id': b['items'][0]['dish_id'], 'quantity': 1})),
    lambda b: b['items'][0].update(quantity=51),
    lambda b: b['items'][0].update(quantity=-1),
    lambda b: b['items'][0].update(dish_id=0),
    lambda b: b.update(items=b['items'] * 51),
    lambda b: b.update(payment_method='crypto'),
    lambda b: b.update(payment_method='online'),
    lambda b: b.pop('payment_method'),
    lambda b: b.pop('customer'),
    lambda b: b['customer'].update(phone='12345'),
    lambda b: b['customer'].update(phone=''),
    lambda b: b['customer'].update(phone='067' + ' ' * 40 + '1234567'),            # з пробілами задовге
    lambda b: b['customer'].update(full_name='x' * 201),
    lambda b: b.update(fulfillment_type='teleport'),
    lambda b: b.update(staff_notes='x' * 1001),
    lambda b: b.update(location_id=0),
    lambda b: b.update(location_id=2_147_483_648),
    lambda b: b['items'][0].update(note='x' * 251),
])
async def test_invalid_request_is_422(client, w, mutate):
    body = pickup_payload(w.l1.id, [(w.cola.id, 1)])
    mutate(body)
    r = await post(client, w.h.waiter, body)
    # саме помилка валідації запиту, а не бізнес-правило сервісу (воно теж відповідає 422, але з іншим кодом)
    assert r.status_code == 422, r.text
    assert r.json()['error']['code'] == 'validation_error', r.text


async def test_delivery_requires_an_address_and_pickup_forbids_one(client, w):
    body = pickup_payload(w.l1.id, [(w.pizza.id, 3)])
    body['fulfillment_type'] = 'delivery'
    r = await post(client, w.h.waiter, body)
    assert r.status_code == 422 and r.json()['error']['code'] == 'validation_error'
    body = pickup_payload(w.l1.id, [(w.pizza.id, 3)])
    body['delivery'] = {'city': 'Болехів', 'street': 'вул. Шевченка', 'building': '5'}
    r = await post(client, w.h.waiter, body)
    assert r.status_code == 422 and r.json()['error']['code'] == 'validation_error'


@pytest.mark.parametrize('field', ['city', 'street', 'building'])
async def test_delivery_address_parts_are_required(client, w, field):
    body = delivery_payload(w.l1.id, [(w.pizza.id, 3)])
    body['delivery'][field] = '  '
    r = await post(client, w.h.waiter, body)
    assert r.status_code == 422 and r.json()['error']['code'] == 'validation_error'


# ---------- позиції ----------

async def test_all_item_problems_are_reported_together(client, db_session, w):
    r = await post(client, w.h.waiter, pickup_payload(
        w.l1.id, [(w.pasta.id, 1), (w.off.id, 1), (w.stopped.id, 1), (999_999, 1), (w.cola.id, 1)],
    ))
    assert r.status_code == 422
    error = r.json()['error']
    assert error['code'] == 'invalid_items'
    assert error['details'] == [
        {'dish_id': w.pasta.id, 'name': 'Паста', 'reason': 'not_in_menu'},
        {'dish_id': w.off.id, 'name': 'Знята з продажу', 'reason': 'unavailable'},
        {'dish_id': w.stopped.id, 'name': 'У стоп-листі', 'reason': 'unavailable'},
        {'dish_id': 999_999, 'name': None, 'reason': 'not_found'},
    ]
    assert await count(db_session, Order) == 0


async def test_failed_order_leaves_no_customer_behind(client, db_session, w):
    await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.off.id, 1)], phone='0501112233'))
    assert await count(db_session, Customer) == 0


async def test_zero_total_is_rejected(client, w):
    r = await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.free.id, 1)]))
    assert r.status_code == 422 and r.json()['error']['code'] == 'order_total_zero'


async def test_free_item_is_fine_next_to_a_paid_one(client, w):
    r = await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.free.id, 2), (w.cola.id, 1)]))
    assert r.status_code == 201 and r.json()['total_price'] == 50.0


async def test_absurd_total_is_rejected_not_a_500(client, w):
    r = await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.gold.id, 50)]))   # 5 000 000
    assert r.status_code == 422 and r.json()['error']['code'] == 'order_too_large'


async def test_total_at_the_limit_is_accepted(client, db_session, w):
    dish = await make_dish(db_session, w.category, 'Банкет', '20000.00', sell_in=[w.l1])
    r = await post(client, w.h.waiter, pickup_payload(w.l1.id, [(dish.id, 50)]))        # рівно 1 000 000
    assert r.status_code == 201 and r.json()['total_price'] == 1_000_000.0


# ---------- акції ----------

async def test_promotion_with_fixed_price(client, db_session, w):
    promo = await make_promotion(
        db_session, 'Піца + кола', locations=[w.l1], items=[(w.pizza, 1), (w.cola, 1)], price='199.00',
    )
    body = pickup_payload(w.l1.id, [])
    body['items'] = [{'promotion_id': promo.id, 'quantity': 2}]
    r = await post(client, w.h.waiter, body)
    assert r.status_code == 201, r.text
    item = r.json()['items'][0]
    assert (item['name'], item['unit_price'], item['quantity'], item['line_total']) == ('Піца + кола', 199.0, 2, 398.0)
    assert item['promotion_id'] == promo.id and item['dish_id'] is None
    assert r.json()['total_price'] == 398.0


async def test_promotion_price_is_the_sum_when_not_fixed(client, db_session, w):
    promo = await make_promotion(db_session, 'Сет', locations=[w.l1], items=[(w.pizza, 2), (w.cola, 1)])
    body = pickup_payload(w.l1.id, [])
    body['items'] = [{'promotion_id': promo.id}]
    assert (await post(client, w.h.waiter, body)).json()['total_price'] == 450.0


async def test_promotion_uses_location_prices(client, db_session, w):
    await set_dish_location(db_session, w.pizza, w.l1, price_override='150.00')
    promo = await make_promotion(db_session, 'Сет', locations=[w.l1], items=[(w.pizza, 1)])
    body = pickup_payload(w.l1.id, [])
    body['items'] = [{'promotion_id': promo.id}]
    assert (await post(client, w.h.waiter, body)).json()['total_price'] == 150.0


@pytest.mark.parametrize('kwargs', [
    {'status': 'draft'}, {'status': 'paused'}, {'status': 'archived'},
    {'end_date': datetime(2026, 11, 1).date()},                       # закінчилась
    {'start_date': datetime(2026, 12, 1).date()},                     # ще не почалась
    {'start_time': time(18, 0), 'end_time': time(23, 0)},             # зараз 14:00
])
async def test_promotion_that_is_not_active_now_is_rejected(client, db_session, w, kwargs):
    from app.db.enums import PromotionStatus
    if 'status' in kwargs:
        kwargs = {'status': PromotionStatus(kwargs['status'])}
    promo = await make_promotion(db_session, 'Не зараз', locations=[w.l1], items=[(w.pizza, 1)], price='100', **kwargs)
    body = pickup_payload(w.l1.id, [])
    body['items'] = [{'promotion_id': promo.id}]
    r = await post(client, w.h.waiter, body)
    assert r.status_code == 422 and r.json()['error']['code'] == 'invalid_items'
    assert r.json()['error']['details'] == [{'promotion_id': promo.id, 'name': None, 'reason': 'unavailable'}]


async def test_promotion_of_another_location_or_unknown_is_rejected(client, db_session, w):
    elsewhere = await make_promotion(db_session, 'Тільки заклад 2', locations=[w.l2], items=[(w.pizza, 1)])
    for promo_id in (elsewhere.id, 999_999):
        body = pickup_payload(w.l1.id, [])
        body['items'] = [{'promotion_id': promo_id}]
        r = await post(client, w.h.waiter, body)
        assert r.status_code == 422 and r.json()['error']['code'] == 'invalid_items'


async def test_promotion_with_a_dish_in_stop_list_is_rejected_even_when_not_paused(client, db_session, w):
    promo = await make_promotion(
        db_session, 'Сет', locations=[w.l1], items=[(w.pizza, 1), (w.stopped, 1)], pause_if_unavailable=False,
    )
    body = pickup_payload(w.l1.id, [])
    body['items'] = [{'promotion_id': promo.id}]
    r = await post(client, w.h.waiter, body)
    assert r.status_code == 422
    assert r.json()['error']['details'] == [{'promotion_id': promo.id, 'name': 'Сет', 'reason': 'unavailable'}]


# ---------- доставка ----------

async def test_delivery_in_a_zone_with_enough_money(client, w):
    r = await post(client, w.h.waiter, delivery_payload(w.l1.id, [(w.pizza.id, 2)]))   # 400 = мінімум зеленої
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['fulfillment_type'] == 'delivery'
    assert body['delivery_zone'] == {'code': 'green', 'name': 'Green'}
    assert body['delivery_address'] == 'Болехів, вул. Шевченка, 5'
    assert (body['subtotal_price'], body['delivery_price'], body['total_price']) == (400.0, 0.0, 400.0)


async def test_delivery_details_go_into_the_address_text(client, w):
    body = delivery_payload(w.l1.id, [(w.pizza.id, 2)])
    body['delivery']['details'] = 'під\'їзд 2, домофон 15'
    r = await post(client, w.h.waiter, body)
    assert r.json()['delivery_address'] == 'Болехів, вул. Шевченка, 5 (під\'їзд 2, домофон 15)'


async def test_delivery_below_the_zone_minimum_is_rejected(client, db_session, w):
    r = await post(client, w.h.waiter, delivery_payload(w.l1.id, [(w.pizza.id, 1), (w.cola.id, 3)]))   # 350 < 400
    assert r.status_code == 422
    error = r.json()['error']
    assert error['code'] == 'below_minimum_order'
    assert error['details'] == {'zone': 'green', 'min_order_amount': 400.0, 'subtotal': 350.0}
    assert await count(db_session, Order) == 0


async def test_pickup_has_no_minimum(client, w):
    assert (await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.cola.id, 1)]))).status_code == 201


async def test_delivery_outside_the_zones_is_rejected(client, w):
    r = await post(client, w.h.waiter, delivery_payload(w.l1.id, [(w.pizza.id, 3)], city='Київ'))
    assert r.status_code == 422
    assert r.json()['error']['code'] == 'delivery_unavailable'
    assert r.json()['error']['details'] == {'reason': 'outside_zones'}


async def test_delivery_where_no_zones_are_configured(client, w):
    # у закладу 2 немає жодної зони
    r = await post(client, w.h.waiter2, delivery_payload(w.l2.id, [(w.pizza.id, 3)], city='Велика Турʼя'))
    assert r.status_code == 422 and r.json()['error']['details'] == {'reason': 'not_configured'}


async def test_street_listed_in_a_zone_overrides_the_city_zone(client, db_session, w):
    red = await make_zone(db_session, w.l1, 'red', minimum='1000', sort_order=3)
    await make_area(db_session, red, 'Болехів', 'вул. Далека')
    r = await post(client, w.h.waiter, delivery_payload(w.l1.id, [(w.pizza.id, 3)], street='вул. Далека'))   # 600 < 1000
    assert r.status_code == 422 and r.json()['error']['code'] == 'below_minimum_order'
    assert r.json()['error']['details']['zone'] == 'red'


async def test_ambiguous_street_is_rejected(client, db_session, w):
    yellow = await make_zone(db_session, w.l1, 'yellow', minimum='600', sort_order=2)
    red = await make_zone(db_session, w.l1, 'red', minimum='1000', sort_order=3)
    await make_area(db_session, yellow, 'Болехів', 'вул. Лесі')
    await make_area(db_session, red, 'Болехів', 'пров. Лесі')
    r = await post(client, w.h.waiter, delivery_payload(w.l1.id, [(w.pizza.id, 5)], street='Лесі'))
    assert r.status_code == 422 and r.json()['error']['details'] == {'reason': 'ambiguous_street'}


async def test_zone_id_is_not_leaked_by_the_public_delivery_api(client, w):
    r = await client.post(f'/api/v1/locations/{w.l1.id}/delivery/check-address', json={'city': 'Болехів'})
    assert r.status_code == 200
    assert 'zone_id' not in r.json() and 'zone_id' not in r.json()['zone']


# ---------- гість за телефоном ----------

async def test_the_same_guest_in_different_phone_formats_is_one_customer(client, db_session, w):
    ids = set()
    for phone in ('0671234567', '+38 (067) 123-45-67', '380671234567'):
        r = await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.cola.id, 1)], phone=phone))
        ids.add(r.json()['customer']['id'])
    assert len(ids) == 1
    assert await count(db_session, Customer) == 1


async def test_customer_name_is_filled_in_later_but_never_overwritten(client, w):
    first = (await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.cola.id, 1)]))).json()
    assert first['customer']['full_name'] is None
    second = (await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.cola.id, 1)], name='Марія'))).json()
    assert second['customer']['full_name'] == 'Марія'                     # імені не було: дописали
    third = (await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.cola.id, 1)], name='Марйя'))).json()
    assert third['customer']['full_name'] == 'Марія'                      # вже є: не перезаписуємо


async def test_different_phones_are_different_customers(client, db_session, w):
    for phone in ('0671234567', '0501234567'):
        await post(client, w.h.waiter, pickup_payload(w.l1.id, [(w.cola.id, 1)], phone=phone))
    assert await count(db_session, Customer) == 2


# ---------- права й заклад ----------

async def test_authentication_is_required(client, w):
    r = await client.post('/api/v1/orders', json=pickup_payload(w.l1.id, [(w.cola.id, 1)]))
    assert r.status_code == 401


async def test_chef_cannot_create_orders(client, w):
    r = await post(client, w.h.chef, pickup_payload(w.l1.id, [(w.cola.id, 1)]))
    assert r.status_code == 403 and r.json()['error']['code'] == 'forbidden'


async def test_waiter_cannot_create_orders_in_another_location(client, w):
    r = await post(client, w.h.waiter, pickup_payload(w.l2.id, [(w.pizza.id, 1)]))
    assert r.status_code == 403 and r.json()['error']['code'] == 'other_location'


async def test_waiter_without_a_location_cannot_create_orders(client, w):
    r = await post(client, w.h.waiter_free, pickup_payload(w.l1.id, [(w.cola.id, 1)]))
    assert r.status_code == 403 and r.json()['error']['code'] == 'no_location'


async def test_admin_can_create_orders_anywhere(client, w):
    for location, dish in ((w.l1, w.cola), (w.l2, w.pizza)):
        r = await post(client, w.h.admin, pickup_payload(location.id, [(dish.id, 1)]))
        assert r.status_code == 201 and r.json()['source'] == 'waiter'


async def test_inactive_and_unknown_locations_are_404(client, db_session, w):
    w.l1.is_active = False
    await db_session.commit()
    r = await post(client, w.h.admin, pickup_payload(w.l1.id, [(w.cola.id, 1)]))
    assert r.status_code == 404
    r = await post(client, w.h.admin, pickup_payload(999_999, [(w.cola.id, 1)]))
    assert r.status_code == 404
